"""
BOOB Player - Dolby Vision / EDR Digital Cinema (DVis DCP) Conversion Engine
Transforms 12-bit DCI HDR-DCP XYZ-PQ codestreams into Consumer HDR10 (Rec.2020 PQ)
and Studio Rec.709 SDR deliverables with hardware GPU acceleration.
"""

import os
import sys
import time
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, Callable

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from core.app_paths import get_tool_path
from core.nvjpeg2k_engine import NVJPEG2KEngine, is_gpu_jp2k_available
from core.gpu_detector import GPUDetector


# ==============================================================================
# Precision Color Transformation Matrices (DCI HDR Addendum Annex C.5 / ITU-R)
# ==============================================================================

# Combined Matrix: DCI XYZ (D65) -> Rec.2020 Linear RGB
XYZ_TO_2020 = np.array([
    [ 1.7166514,  -0.35567138, -0.2533659 ],
    [-0.6666838,   1.6164807,   0.01576855],
    [ 0.01764132, -0.04277223,  0.9421033 ],
], dtype=np.float32)

# Combined Matrix: DCI XYZ (D65) -> Rec.709 Linear RGB
XYZ_TO_709 = np.array([
    [ 3.2409692,  -1.5373826,  -0.49861068],
    [-0.9692438,   1.8759677,   0.04155508],
    [ 0.05562895, -0.2039765,   1.056972  ],
], dtype=np.float32)

# SMPTE ST 2084 (Perceptual Quantizer - PQ) Constants
M1 = (2610.0 / 4096.0) / 4.0
M2 = (2523.0 / 4096.0) * 128.0
C1 = (3424.0 / 4096.0)
C2 = (2413.0 / 4096.0) * 32.0
C3 = (2392.0 / 4096.0) * 32.0


def pq_eotf(v: np.ndarray) -> np.ndarray:
    """SMPTE ST 2084 PQ EOTF: normalized code [0..1] -> absolute linear nits [0..10,000]."""
    v_clamped = np.clip(v, 0.0, 1.0)
    p = np.power(v_clamped, 1.0 / M2)
    numerator = np.maximum(p - C1, 0.0)
    denominator = np.maximum(C2 - C3 * p, 1e-8)
    return 10000.0 * np.power(numerator / denominator, 1.0 / M1)


def pq_oetf(nits: np.ndarray) -> np.ndarray:
    """SMPTE ST 2084 PQ OETF: absolute linear nits [0..10,000] -> normalized PQ code [0..1]."""
    norm = np.clip(nits / 10000.0, 0.0, 1.0)
    p = np.power(norm, M1)
    return np.power((C1 + C2 * p) / (1.0 + C3 * p), M2)


def sdr_bt1886_oetf(nits: np.ndarray, target_peak: float = 100.0) -> np.ndarray:
    """BT.1886 / Rec.709 transfer curve: linear nits [0..100] -> gamma 2.4 encoded code [0..1]."""
    norm = np.clip(nits / target_peak, 0.0, 1.0)
    # Rec.709 transfer function
    return np.where(norm <= 0.0031308, norm * 12.92, 1.055 * np.power(norm, 1.0 / 2.4) - 0.055)


def tonemap_sdr_luma_preserve(rgb_linear: np.ndarray, knee: float = 70.0, peak: float = 100.0) -> np.ndarray:
    """
    Applies luminance-weighted highlight knee roll-off (108+ nits DCI -> 100 nits SDR)
    while scaling RGB channels uniformly to preserve hue and saturation perfectly.
    """
    # Rec.709 Luminance weights
    y = (0.2126 * rgb_linear[..., 0] +
         0.7152 * rgb_linear[..., 1] +
         0.0722 * rgb_linear[..., 2])
    
    # Smooth exponential shoulder above knee
    y_mapped = np.where(y <= knee, y, knee + (peak - knee) * (1.0 - np.exp(-(y - knee) / (peak - knee))))
    scale = np.divide(y_mapped, y, out=np.ones_like(y), where=y > 1e-4)
    return np.clip(rgb_linear * scale[..., None], 0.0, peak)


@dataclass
class DVisConversionConfig:
    input_video_mxf: str
    output_file: str
    target_mode: str = "hdr10"          # "hdr10" or "sdr"
    format_type: str = "mp4_hevc"       # "prores", "mp4_hevc", "mp4_h264"
    audio_mxf: Optional[str] = None
    audio_mode: str = "5.1_aac"         # "5.1_aac", "stereo_aac", "pcm_copy", "none"
    start_frame: int = 0
    end_frame: int = 0                  # 0 means all frames
    fps: float = 24.0
    width: int = 4096
    height: int = 1716
    prefer_gpu: bool = True


class DVisConversionWorker(QThread):
    """
    High-performance background conversion thread for DVis DCP to Consumer HDR10 / SDR.
    Streams raw decoded 12-bit XYZ frames from GPU/FFmpeg, applies vector color transforms,
    and multiplexes audio tracks into the final deliverable.
    """
    progress_updated = pyqtSignal(int, int, float, float)  # current, total, fps, eta_seconds
    status_message = pyqtSignal(str)
    conversion_finished = pyqtSignal(bool, str, str)       # success, output_path, message

    def __init__(self, config: DVisConversionConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._is_cancelled = False
        self._ffmpeg_bin = get_tool_path("ffmpeg")

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        t_start = time.time()
        self.status_message.emit("Initializing DVis DCP Color Pipeline...")

        cfg = self.config
        if not os.path.isfile(cfg.input_video_mxf):
            self.conversion_finished.emit(False, "", f"Input video MXF not found: {cfg.input_video_mxf}")
            return

        # Initialize GPU acceleration if available
        gpu_engine = None
        mxf_offsets = []
        use_gpu = False
        if cfg.prefer_gpu and is_gpu_jp2k_available():
            try:
                gpu_engine = NVJPEG2KEngine.get_instance()
                if gpu_engine.is_available():
                    mxf_offsets = gpu_engine.index_mxf(cfg.input_video_mxf)
                    if len(mxf_offsets) > 0:
                        use_gpu = True
                        gpu_name = GPUDetector.get_info().name or "GPU"
                        self.status_message.emit(f"⚡ Hardware Acceleration: {gpu_name} (NVJPEG2K Active)")
            except Exception as e:
                print(f"[DVisConverter] GPU Init fallback: {e}")
                use_gpu = False

        total_file_frames = len(mxf_offsets) if len(mxf_offsets) > 0 else 5233
        start_idx = max(0, cfg.start_frame)
        end_idx = cfg.end_frame if (cfg.end_frame > 0 and cfg.end_frame <= total_file_frames) else total_file_frames
        frames_to_process = max(1, end_idx - start_idx)

        # Build FFmpeg Encoder Process
        encoder_cmd, pipe_pix_fmt = self._build_encoder_cmd(cfg, frames_to_process)
        self.status_message.emit(f"Encoding target: {cfg.target_mode.upper()} ({cfg.format_type})")

        enc_proc = None
        dec_proc = None

        try:
            enc_proc = subprocess.Popen(encoder_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

            if not use_gpu:
                # CPU Fallback: Stream xyz12le via FFmpeg
                dec_cmd = [
                    self._ffmpeg_bin, "-v", "error",
                    "-threads", "8",
                    "-i", cfg.input_video_mxf,
                    "-map", "0:v:0", "-an", "-f", "rawvideo",
                    "-pix_fmt", "xyz12le"
                ]
                if start_idx > 0:
                    dec_cmd.extend(["-ss", f"{start_idx / cfg.fps:.4f}"])
                dec_cmd.extend(["-vframes", str(frames_to_process), "-"])
                dec_proc = subprocess.Popen(dec_cmd, stdout=subprocess.PIPE)

            bytes_per_xyz12 = cfg.width * cfg.height * 3 * 2
            processed = 0
            last_time = time.time()
            fps_smooth = 0.0

            for frame_idx in range(start_idx, end_idx):
                if self._is_cancelled:
                    self.status_message.emit("Conversion cancelled by user.")
                    self.conversion_finished.emit(False, "", "Conversion cancelled.")
                    return

                if use_gpu:
                    # GPU Direct Frame Decode
                    X, Y, Z = gpu_engine.decode_mxf_frame(cfg.input_video_mxf, frame_idx)
                    # Convert 12-bit planes to normalized codes [0..1]
                    codes_x = X.astype(np.float32) / 4095.0
                    codes_y = Y.astype(np.float32) / 4095.0
                    codes_z = Z.astype(np.float32) / 4095.0
                    xyz = np.stack([codes_x, codes_y, codes_z], axis=-1)
                else:
                    # Read from FFmpeg pipe
                    raw = dec_proc.stdout.read(bytes_per_xyz12)
                    if not raw or len(raw) < bytes_per_xyz12:
                        break
                    words = np.frombuffer(raw, dtype="<u2").reshape(cfg.height, cfg.width, 3)
                    xyz = (words >> 4).astype(np.float32) / 4095.0

                # Color Transform
                out_bytes = self._process_frame_colors(xyz, cfg.target_mode)
                enc_proc.stdin.write(out_bytes)

                processed += 1
                now = time.time()
                dt = now - last_time
                if dt >= 0.5 or processed == frames_to_process:
                    fps_inst = processed / max(0.001, now - t_start)
                    fps_smooth = fps_smooth * 0.8 + fps_inst * 0.2 if fps_smooth > 0 else fps_inst
                    rem_frames = frames_to_process - processed
                    eta_sec = rem_frames / max(0.1, fps_smooth)
                    self.progress_updated.emit(processed, frames_to_process, fps_smooth, eta_sec)
                    last_time = now

            enc_proc.stdin.close()
            enc_proc.wait()

            if dec_proc:
                dec_proc.stdout.close()
                dec_proc.wait()

            total_elapsed = time.time() - t_start
            avg_fps = processed / max(0.001, total_elapsed)
            msg = f"Converted {processed} frames in {total_elapsed:.1f}s ({avg_fps:.1f} FPS)"
            self.status_message.emit("Multiplexing audio and finalizing package...")

            # Multiplex audio if requested and separate file produced
            final_path = self._finalize_audio(cfg, processed)

            self.status_message.emit("Complete!")
            self.conversion_finished.emit(True, final_path, msg)

        except Exception as e:
            self.conversion_finished.emit(False, "", f"Conversion failed: {str(e)}")
        finally:
            if enc_proc and enc_proc.stdin and not enc_proc.stdin.closed:
                try:
                    enc_proc.stdin.close()
                except Exception:
                    pass
            if dec_proc and dec_proc.stdout and not dec_proc.stdout.closed:
                try:
                    dec_proc.stdout.close()
                except Exception:
                    pass

    def _process_frame_colors(self, codes: np.ndarray, target_mode: str) -> bytes:
        """Applies SMPTE ST 2084 EOTF and target color matrix transforms."""
        # 1. Decode PQ to Linear XYZ nits (0 - 10,000)
        xyz_lin = pq_eotf(codes)

        if target_mode == "hdr10":
            # 2a. Map to Rec.2020 Linear
            rgb2020 = np.maximum(xyz_lin @ XYZ_TO_2020.T, 0.0)
            # Re-encode to SMPTE ST 2084 PQ
            pq_encoded = pq_oetf(rgb2020)
            # 16-bit RGB48LE
            words = np.round(np.clip(pq_encoded, 0.0, 1.0) * 65535.0).astype("<u2")
            return words.tobytes()

        else:
            # 2b. Map to Rec.709 Linear with Highlight Preservation
            rgb709 = np.maximum(xyz_lin @ XYZ_TO_709.T, 0.0)
            rgb709_mapped = tonemap_sdr_luma_preserve(rgb709, knee=70.0, peak=100.0)
            # Apply BT.1886 / Rec.709 SDR Gamma (2.4)
            sdr_encoded = sdr_bt1886_oetf(rgb709_mapped, target_peak=100.0)
            # 16-bit RGB48LE
            words = np.round(np.clip(sdr_encoded, 0.0, 1.0) * 65535.0).astype("<u2")
            return words.tobytes()

    def _build_encoder_cmd(self, cfg: DVisConversionConfig, frames_to_process: int) -> Tuple[list, str]:
        """Constructs FFmpeg encoding pipeline with strict broadcast color metadata."""
        out_temp = cfg.output_file

        cmd = [
            self._ffmpeg_bin, "-y", "-v", "error",
            "-f", "rawvideo",
            "-pix_fmt", "rgb48le",
            "-video_size", f"{cfg.width}x{cfg.height}",
            "-framerate", str(cfg.fps),
            "-i", "-",
        ]

        if cfg.target_mode == "hdr10":
            # HDR10: Rec.2020, ST 2084 PQ, Limited Range TV
            cmd.extend([
                "-vf", "zscale=matrixin=gbr:transferin=smpte2084:primariesin=bt2020:rangein=full:matrix=bt2020nc:transfer=smpte2084:primaries=bt2020:range=limited,format=yuv420p10le",
                "-color_primaries", "bt2020",
                "-color_trc", "smpte2084",
                "-colorspace", "bt2020nc",
                "-color_range", "tv",
            ])
            if "prores" in cfg.format_type:
                cmd.extend([
                    "-c:v", "prores_ks", "-profile:v", "3", "-qscale:v", "4",
                    "-pix_fmt", "yuv422p10le"
                ])
            else:
                # HEVC 10-bit
                cmd.extend([
                    "-c:v", "libx265", "-crf", "18", "-preset", "medium",
                    "-x265-params", "hdr10=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:master-display=G(8500,39850)B(6550,2300)R(35400,14600)WP(15635,16450)L(10000000,1):max-cll=108,100"
                ])
        else:
            # SDR: Rec.709, Rec.709, Limited Range TV
            cmd.extend([
                "-vf", "zscale=matrixin=gbr:transferin=bt709:primariesin=bt709:rangein=full:matrix=bt709:transfer=bt709:primaries=bt709:range=limited,format=yuv420p",
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-colorspace", "bt709",
                "-color_range", "tv",
            ])
            if "prores" in cfg.format_type:
                cmd.extend([
                    "-c:v", "prores_ks", "-profile:v", "3", "-qscale:v", "4",
                    "-pix_fmt", "yuv422p10le"
                ])
            elif "h264" in cfg.format_type:
                cmd.extend([
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                    "-pix_fmt", "yuv420p"
                ])
            else:
                cmd.extend([
                    "-c:v", "libx265", "-crf", "20", "-preset", "medium",
                    "-pix_fmt", "yuv420p"
                ])

        cmd.extend(["-an", out_temp])
        return cmd, "rgb48le"

    def _finalize_audio(self, cfg: DVisConversionConfig, processed_frames: int) -> str:
        """Muxes DCP multichannel PCM audio into the converted video container."""
        if not cfg.audio_mxf or not os.path.isfile(cfg.audio_mxf) or cfg.audio_mode == "none":
            return cfg.output_file

        video_temp = cfg.output_file
        name, ext = os.path.splitext(video_temp)
        muxed_output = f"{name}_muxed{ext}"

        audio_filter = ""
        if cfg.audio_mode == "stereo_aac":
            # Extract 5.1 and downmix to stereo
            audio_filter = "pan=stereo|c0=c0+0.707*c2+0.707*c4|c1=c1+0.707*c2+0.707*c5"
            audio_codec = ["-c:a", "aac", "-b:a", "256k"]
        elif cfg.audio_mode == "pcm_copy":
            audio_filter = "pan=5.1|c0=c0|c1=c1|c2=c2|c3=c3|c4=c4|c5=c5"
            audio_codec = ["-c:a", "pcm_s24le"]
        else:
            # 5.1 surround sound AAC
            audio_filter = "pan=5.1|c0=c0|c1=c1|c2=c2|c3=c3|c4=c4|c5=c5"
            audio_codec = ["-c:a", "aac", "-b:a", "448k"]

        cmd = [
            self._ffmpeg_bin, "-y", "-v", "error",
            "-i", video_temp,
            "-i", cfg.audio_mxf,
            "-map", "0:v:0",
            "-filter_complex", f"[1:a]{audio_filter}[aout]",
            "-map", "[aout]",
            "-c:v", "copy",
        ]
        cmd.extend(audio_codec)
        cmd.extend(["-shortest", muxed_output])

        res = subprocess.run(cmd)
        if res.returncode == 0 and os.path.isfile(muxed_output):
            try:
                os.replace(muxed_output, video_temp)
            except Exception:
                return muxed_output
        return video_temp
