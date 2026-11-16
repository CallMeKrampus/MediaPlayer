"""
BOOB Player - Deep Media & Codec Inspector
Analyzes detailed stream attributes, bit depths, color primaries, transfer functions,
audio channel configurations, and container parameters.
"""

import json
import subprocess
import os
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from core.app_paths import get_tool_path


def parse_fraction_fps(rate_str: Any, fallback: float = 24.0) -> float:
    """Safely parse fps from strings like '24/1', '24000/1001', '0/0', or floats."""
    if not rate_str or rate_str == "0/0":
        return fallback
    if isinstance(rate_str, (int, float)):
        return float(rate_str) if rate_str > 0 else fallback
    rate_str = str(rate_str).strip()
    if "/" in rate_str:
        try:
            num, den = rate_str.split("/", 1)
            num_f, den_f = float(num), float(den)
            if den_f > 0 and num_f > 0:
                return round(num_f / den_f, 3)
        except Exception:
            pass
    else:
        try:
            f = float(rate_str)
            if f > 0:
                return round(f, 3)
        except Exception:
            pass
    return fallback


class MediaInspector:
    @staticmethod
    def inspect_file(file_path: str) -> Dict[str, Any]:
        """Run ffprobe to get comprehensive container and stream metadata."""
        if not file_path:
            return {"error": "Invalid file path"}

        # If a directory is passed, check if it's a DCP package
        if os.path.isdir(file_path):
            from core.dcp_parser import DCPParser
            if DCPParser.is_dcp_folder(file_path):
                return MediaInspector.inspect_dcp(file_path)
            return {"error": "Path is a directory, not a media file"}

        if not os.path.exists(file_path):
            return {"error": "File does not exist"}

        cmd = [
            get_tool_path("ffprobe"),
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            file_path
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                # For PQ (HDR10) streams lacking stream-level DOVI/HDR10+ side data,
                # run a fast 1-frame probe to inspect SMPTE ST 2094-40 (HDR10+) or RPU frame side data.
                for s in data.get("streams", []):
                    if s.get("codec_type") == "video" and s.get("color_transfer") == "smpte2084":
                        stream_sd = [str(sd.get("side_data_type", "")).lower() for sd in s.get("side_data_list", [])]
                        has_rich_sd = any("dovi" in t or "dolby vision" in t or "hdr10+" in t or "2094" in t for t in stream_sd)
                        if not has_rich_sd:
                            try:
                                frame_cmd = [
                                    get_tool_path("ffprobe"),
                                    "-v", "quiet",
                                    "-print_format", "json",
                                    "-select_streams", "v:0",
                                    "-read_intervals", "%+#1",
                                    "-show_entries", "frame=side_data_list",
                                    file_path,
                                ]
                                fres = subprocess.run(frame_cmd, capture_output=True, text=True, timeout=3)
                                if fres.returncode == 0 and fres.stdout.strip():
                                    fdata = json.loads(fres.stdout)
                                    frames = fdata.get("frames", [])
                                    if frames and frames[0].get("side_data_list"):
                                        s.setdefault("side_data_list", []).extend(frames[0]["side_data_list"])
                            except Exception:
                                pass
                        break
                return MediaInspector.format_probe_data(data)
        except Exception as e:
            print(f"[MediaInspector] Probe exception for {file_path}: {e}")

        return {"error": "Could not probe media file"}

    @staticmethod
    def inspect_dcp(folder_path: str) -> Dict[str, Any]:
        """Inspect a full DCP cinema package by probing its primary picture and sound MXFs."""
        from core.dcp_parser import DCPParser
        try:
            pkg = DCPParser.parse(folder_path)
            if not pkg.compositions:
                return {"error": "No compositions found in DCP package"}
            cpl = pkg.default_composition
            if not cpl.reels:
                return {"error": "No reels found in DCP composition"}
            first_reel = cpl.reels[0]

            pic_info = {}
            if first_reel.picture_path and os.path.exists(first_reel.picture_path):
                pic_info = MediaInspector.inspect_file(first_reel.picture_path)

            snd_info = {}
            if first_reel.sound_path and os.path.exists(first_reel.sound_path):
                snd_info = MediaInspector.inspect_file(first_reel.sound_path)

            total_size_mb = 0
            for r in cpl.reels:
                for p in [r.picture_path, r.sound_path, r.atmos_path]:
                    if p and os.path.exists(p):
                        total_size_mb += os.path.getsize(p) / (1024 * 1024)

            v_tracks = pic_info.get("video_tracks", []) if isinstance(pic_info, dict) else []
            a_tracks = snd_info.get("audio_tracks", []) if isinstance(snd_info, dict) else []

            # If audio tracks found, mark cinema attributes
            for a in a_tracks:
                if first_reel.atmos_path and os.path.exists(first_reel.atmos_path):
                    a["codec"] = "PCM / SMPTE ST 2098-2 (Dolby Atmos IAB)"
                else:
                    a["codec"] = f"Linear PCM Cinema ({first_reel.sound_channels}-Channel)"

            info = {
                "filename": cpl.title,
                "format_name": f"Digital Cinema Package ({cpl.standard})",
                "duration": cpl.total_seconds,
                "size_mb": round(total_size_mb, 2),
                "bitrate_kbps": round((total_size_mb * 8 * 1024) / cpl.total_seconds) if cpl.total_seconds > 0 else 250000,
                "video_tracks": v_tracks,
                "audio_tracks": a_tracks,
                "subtitle_tracks": [],
                "tags": {
                    "Title": cpl.title,
                    "Standard": cpl.standard,
                    "ContentKind": cpl.content_kind,
                    "EditRate": f"{cpl.edit_rate[0]}/{cpl.edit_rate[1]} ({cpl.fps:.2f} fps)",
                    "TotalFrames": str(cpl.total_frames),
                    "ReelsCount": str(len(cpl.reels)),
                    "Issuer": cpl.creator,
                    "IssueDate": cpl.issue_date,
                    "DolbyAtmos": "ST 2098-2 AuxData MXF Present" if getattr(first_reel, "atmos_path", None) else "None"
                }
            }
            return info
        except Exception as e:
            return {"error": f"Failed to inspect DCP: {e}"}

    @staticmethod
    def format_probe_data(data: Dict[str, Any]) -> Dict[str, Any]:
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        
        info = {
            "filename": os.path.basename(fmt.get("filename", "")),
            "format_name": fmt.get("format_long_name", fmt.get("format_name", "Unknown")),
            "duration": float(fmt.get("duration", 0)),
            "size_mb": round(int(fmt.get("size", 0)) / (1024 * 1024), 2) if "size" in fmt else 0,
            "bitrate_kbps": round(int(fmt.get("bit_rate", 0)) / 1000) if "bit_rate" in fmt else 0,
            "video_tracks": [],
            "audio_tracks": [],
            "subtitle_tracks": [],
            "tags": fmt.get("tags", {})
        }

        for s in streams:
            codec_type = s.get("codec_type")
            if codec_type == "video":
                # Safe FPS determination: check avg_frame_rate first, fall back to r_frame_rate
                avg_fps = s.get("avg_frame_rate", "")
                r_fps = s.get("r_frame_rate", "")
                fps_candidate = avg_fps if (avg_fps and avg_fps != "0/0") else r_fps
                fps = parse_fraction_fps(fps_candidate, 24.0)

                # Determine bit depth
                bits = s.get("bits_per_raw_sample")
                if not bits or str(bits).lower() in ("none", "n/a", "0"):
                    pix = str(s.get("pix_fmt", "")).lower()
                    if "12" in pix:
                        bits = "12"
                    elif "10" in pix:
                        bits = "10"
                    elif "16" in pix:
                        bits = "16"
                    else:
                        bits = "8"

                codec_long = s.get("codec_long_name") or s.get("codec_name") or "Unknown"
                codec_short = s.get("codec_name") or "Unknown"
                codec_tag = str(s.get("codec_tag_string") or s.get("codec_tag") or "").lower()
                c_long_l = str(codec_long).lower()
                c_short_l = str(codec_short).lower()
                if "jpeg 2000" in c_long_l or c_short_l in ("jpeg2000", "j2k"):
                    codec_display = "JPEG 2000"
                elif "hevc" in c_long_l or c_short_l in ("hevc", "h265"):
                    codec_display = "HEVC / H.265"
                elif "h.264" in c_long_l or "avc" in c_long_l:
                    codec_display = "H.264 / AVC"
                elif "prores" in c_long_l or "prores" in c_short_l:
                    codec_display = "Apple ProRes"
                elif "vp9" in c_long_l or "vp9" in c_short_l:
                    codec_display = "Google VP9"
                elif "av2" in c_long_l or c_short_l in ("av2", "av02", "aom-av2", "libaom-av2") or "av02" in codec_tag or "aomedia video 2" in c_long_l:
                    codec_display = "AOMedia AV2 (Next-Gen)"
                elif "av1" in c_long_l or c_short_l in ("av1", "av01") or "av01" in codec_tag:
                    codec_display = "AOMedia AV1"
                else:
                    codec_display = codec_long

                # Determine Dolby Vision, HDR10+, HDR10, and HLG metadata from stream/frame side data
                dv_profile = None
                dv_level = None
                dv_compat = None
                is_hdr10plus = False
                has_mastering_or_cll = False
                for sd in s.get("side_data_list", []):
                    sd_type = str(sd.get("side_data_type", "")).lower()
                    if "dovi" in sd_type or "dolby vision" in sd_type:
                        dv_profile = sd.get("dv_profile")
                        dv_level = sd.get("dv_level")
                        dv_compat = sd.get("dv_bl_signal_compatibility_id")
                    elif "hdr10+" in sd_type or "smpte2094" in sd_type or "dynamic hdr" in sd_type:
                        is_hdr10plus = True
                    elif "mastering display" in sd_type or "content light level" in sd_type:
                        has_mastering_or_cll = True

                meta_blob = " ".join([
                    str(fmt.get("filename", "")),
                    json.dumps(fmt.get("tags", {})),
                    json.dumps(s.get("tags", {})),
                ]).lower()
                if any(tok in meta_blob for tok in ("hdr10+", "hdr10plus", "smpte2094")):
                    is_hdr10plus = True

                trc = str(s.get("color_transfer", "") or "").lower()
                prim = str(s.get("color_primaries", "") or "").lower()
                pix_l = str(s.get("pix_fmt", "") or "").lower()

                if dv_profile == 5:
                    hdr_format = "Dolby Vision P5"
                elif dv_profile == 20:
                    hdr_format = "Dolby Vision P20"
                elif dv_profile is not None:
                    hdr_format = f"Dolby Vision P{dv_profile}"
                elif is_hdr10plus:
                    hdr_format = "HDR10+"
                elif trc in ("arib-std-b67", "hlg"):
                    hdr_format = "HLG"
                elif trc in ("smpte2084", "pq") or has_mastering_or_cll:
                    hdr_format = "HDR10"
                elif "xyz" in pix_l or trc == "smpte428":
                    hdr_format = "DCI-XYZ"
                elif "bt2020" in prim:
                    hdr_format = "HDR"
                else:
                    hdr_format = "SDR"

                is_hdr = hdr_format in (
                    "Dolby Vision P5", f"Dolby Vision P{dv_profile}" if dv_profile is not None else "",
                    "HDR10+", "HDR10", "HLG", "HDR"
                ) or (dv_profile is not None)

                v_track = {
                    "index": s.get("index"),
                    "codec": codec_display,
                    "codec_name": s.get("codec_name"),
                    "profile": s.get("profile", "Cinema / High"),
                    "width": s.get("width", 0),
                    "height": s.get("height", 0),
                    "aspect_ratio": s.get("display_aspect_ratio", f"{s.get('width', 0)}:{s.get('height', 0)}"),
                    "pix_fmt": s.get("pix_fmt", "Unknown"),
                    "fps": fps,
                    "color_space": s.get("color_space", "xyz" if "xyz" in str(s.get("pix_fmt", "")).lower() else "bt709"),
                    "color_primaries": s.get("color_primaries", "dci-p3" if "xyz" in str(s.get("pix_fmt", "")).lower() else "bt709"),
                    "color_transfer": s.get("color_transfer", "smpte428" if "xyz" in str(s.get("pix_fmt", "")).lower() else "bt709"),
                    "bits_per_raw_sample": str(bits),
                    "hdr": is_hdr,
                    "hdr_format": hdr_format,
                    "is_hdr10plus": is_hdr10plus,
                    "dolby_vision_profile": dv_profile,
                    "dolby_vision_level": dv_level,
                    "dolby_vision_compat": dv_compat,
                    "is_dv_p5": (dv_profile == 5),
                    "is_dv_p20": (dv_profile == 20),
                    "is_dv_profile_ipt": (dv_profile in (5, 20)),
                    "is_av2": bool("av2" in codec_display.lower()),
                }
                info["video_tracks"].append(v_track)

            elif codec_type == "audio":
                bits = s.get("bits_per_raw_sample") or s.get("bits_per_sample", "24")
                a_track = {
                    "index": s.get("index"),
                    "codec": s.get("codec_long_name", s.get("codec_name")),
                    "codec_name": s.get("codec_name"),
                    "channels": s.get("channels", 2),
                    "channel_layout": s.get("channel_layout", f"{s.get('channels', 2)} Channels"),
                    "sample_rate": s.get("sample_rate", "48000"),
                    "bits_per_raw_sample": str(bits),
                    "bitrate_kbps": round(int(s.get("bit_rate", 0)) / 1000) if "bit_rate" in s else 0,
                    "language": s.get("tags", {}).get("language", "und"),
                    "title": s.get("tags", {}).get("title", f"Audio Track {s.get('index')}")
                }
                info["audio_tracks"].append(a_track)

            elif codec_type == "subtitle":
                sub_track = {
                    "index": s.get("index"),
                    "codec": s.get("codec_long_name", s.get("codec_name")),
                    "codec_name": s.get("codec_name"),
                    "language": s.get("tags", {}).get("language", "und"),
                    "title": s.get("tags", {}).get("title", f"Subtitle {s.get('index')}")
                }
                info["subtitle_tracks"].append(sub_track)

        return info

    @staticmethod
    def get_source_summary(media_data: Dict[str, Any]) -> str:
        """Generate a concise source codec summary string (e.g. 'JPEG 2000 4K @ 24.00 fps (12-bit XYZ)')."""
        if not media_data or "error" in media_data:
            return "Unknown Format"

        v_tracks = media_data.get("video_tracks", [])
        if not v_tracks:
            a_tracks = media_data.get("audio_tracks", [])
            if a_tracks:
                a = a_tracks[0]
                return f"Audio: {a.get('codec', 'PCM')} ({a.get('channels', 2)}ch, {a.get('sample_rate', 48000)}Hz)"
            return media_data.get("format_name", "Media File")

        v = v_tracks[0]
        codec = v.get("codec", "Video")
        w = v.get("width", 0)
        h = v.get("height", 0)
        fps = v.get("fps", 24.0)
        bits = v.get("bits_per_raw_sample", "8")
        pix = str(v.get("pix_fmt", "")).lower()

        # Resolution shorthand
        if w >= 3840:
            res_str = "4K"
        elif w >= 1920:
            res_str = "2K" if "xyz" in pix else "1080p"
        elif w > 0:
            res_str = f"{w}x{h}"
        else:
            res_str = ""

        # Color tag
        hdr_fmt = v.get("hdr_format", "")
        if "xyz" in pix:
            color_tag = f"({bits}-bit XYZ)"
        elif v.get("is_dv_p5") or v.get("dolby_vision_profile") == 5:
            color_tag = f"({bits}-bit Dolby Vision Profile 5)"
        elif v.get("is_dv_p20") or v.get("dolby_vision_profile") == 20:
            color_tag = f"({bits}-bit Dolby Vision Profile 20)"
        elif v.get("dolby_vision_profile"):
            color_tag = f"({bits}-bit DV P{v.get('dolby_vision_profile')})"
        elif hdr_fmt == "HDR10+":
            color_tag = f"({bits}-bit HDR10+)"
        elif hdr_fmt == "HDR10":
            color_tag = f"({bits}-bit HDR10)"
        elif hdr_fmt == "HLG":
            color_tag = f"({bits}-bit HLG HDR)"
        elif v.get("hdr"):
            color_tag = f"({bits}-bit HDR)"
        else:
            color_tag = f"({bits}-bit)"

        parts = [codec]
        if res_str:
            parts.append(res_str)
        if fps > 0:
            parts.append(f"@{fps:.2f}fps" if abs(fps - round(fps)) > 0.01 else f"@{int(fps)}fps")
        parts.append(color_tag)

        return " ".join(parts)

    @staticmethod
    def extract_from_mpv(mpv_player) -> Dict[str, Any]:
        """Extract live metadata from active mpv instance."""
        if not mpv_player:
            return {}

        try:
            track_list = mpv_player.track_list or []
            v_params = mpv_player.video_params or {}
            a_params = mpv_player.audio_params or {}
            codec = getattr(mpv_player, "video_codec", "") or v_params.get("pixelformat", "N/A")
            fps = getattr(mpv_player, "container_fps", 0) or getattr(mpv_player, "estimated_vf_fps", 24.0) or 24.0
            
            return {
                "duration": mpv_player.duration or 0,
                "time_pos": mpv_player.time_pos or 0,
                "video_format": v_params.get("pixelformat", "N/A"),
                "width": v_params.get("w", 0),
                "height": v_params.get("h", 0),
                "aspect": v_params.get("aspect", 0),
                "fps": fps,
                "color_primaries": v_params.get("primaries", "BT.709"),
                "color_gamma": v_params.get("gamma", "sRGB/BT.709"),
                "color_matrix": v_params.get("colormatrix", "BT.709"),
                "audio_format": a_params.get("format", "N/A"),
                "audio_channels": a_params.get("channels", "Stereo"),
                "audio_samplerate": a_params.get("samplerate", 48000),
                "track_count": len(track_list),
                "tracks": track_list,
                "video_tracks": [{
                    "index": 1,
                    "codec": "JPEG 2000" if "xyz" in str(v_params.get("pixelformat", "")).lower() else codec,
                    "width": v_params.get("w", 0),
                    "height": v_params.get("h", 0),
                    "fps": fps,
                    "pix_fmt": v_params.get("pixelformat", "N/A"),
                    "bits_per_raw_sample": "12" if "12" in str(v_params.get("pixelformat", "")) else "8",
                    "hdr": False
                }] if v_params else []
            }
        except Exception:
            return {}

    @staticmethod
    def get_active_image_bounds(img_or_arr: Any, threshold: int = 14) -> Tuple[int, int, int, int]:
        """
        Calculates the bounding box (top, bottom, left, right) of the active image area,
        cropping out any letterboxing (top/bottom black bars) or pillarboxing (left/right black bars).
        Threshold allows for video compression noise and studio limited range levels.
        """
        try:
            if isinstance(img_or_arr, str):
                from PIL import Image
                with Image.open(img_or_arr) as im:
                    arr = np.array(im)
            elif hasattr(img_or_arr, "constBits") and hasattr(img_or_arr, "sizeInBytes"):
                # PyQt6 QImage - convert to canonical byte-order RGBA8888
                from PyQt6.QtGui import QImage
                conv = img_or_arr.convertToFormat(QImage.Format.Format_RGBA8888)
                ptr = conv.constBits()
                ptr.setsize(conv.sizeInBytes())
                arr = np.frombuffer(ptr, np.uint8).reshape((conv.height(), conv.width(), -1))
            elif hasattr(img_or_arr, "size") and hasattr(img_or_arr, "mode"):
                # PIL Image
                arr = np.array(img_or_arr)
            else:
                arr = np.array(img_or_arr)

            if arr.ndim == 3:
                rgb = arr[:, :, :3]
            else:
                rgb = arr

            H, W = rgb.shape[:2]
            row_max = rgb.max(axis=(1, 2)) if rgb.ndim == 3 else rgb.max(axis=1)
            col_max = rgb.max(axis=(0, 2)) if rgb.ndim == 3 else rgb.max(axis=0)

            active_rows = np.where(row_max > threshold)[0]
            active_cols = np.where(col_max > threshold)[0]

            if len(active_rows) == 0 or len(active_cols) == 0:
                return 0, H, 0, W

            top = int(active_rows[0])
            bottom = int(active_rows[-1]) + 1
            left = int(active_cols[0])
            right = int(active_cols[-1]) + 1

            # Safety guard: don't collapse to tiny area if the scene is almost entirely pitch black
            if (bottom - top) * (right - left) < 0.05 * (H * W):
                return 0, H, 0, W

            return top, bottom, left, right
        except Exception:
            return 0, 0, 0, 0

    @staticmethod
    def crop_active_image_area(img_or_arr: Any, threshold: int = 14) -> Any:
        """
        Crops strictly the active image area of an image, removing letterboxing or pillarboxing.
        Preserves original image type (PIL Image, QImage, or numpy ndarray).
        """
        top, bottom, left, right = MediaInspector.get_active_image_bounds(img_or_arr, threshold=threshold)
        if top == 0 and bottom == 0 and left == 0 and right == 0:
            return img_or_arr

        if isinstance(img_or_arr, str):
            from PIL import Image
            with Image.open(img_or_arr) as im:
                H, W = im.size[1], im.size[0]
                if top > 0 or bottom < H or left > 0 or right < W:
                    return im.crop((left, top, right, bottom))
                return im.copy()
        elif hasattr(img_or_arr, "crop") and callable(img_or_arr.crop):
            # PIL Image
            H, W = img_or_arr.size[1], img_or_arr.size[0]
            if top > 0 or bottom < H or left > 0 or right < W:
                return img_or_arr.crop((left, top, right, bottom))
            return img_or_arr
        elif hasattr(img_or_arr, "copy") and hasattr(img_or_arr, "width") and hasattr(img_or_arr, "height"):
            # QImage
            H, W = img_or_arr.height(), img_or_arr.width()
            if top > 0 or bottom < H or left > 0 or right < W:
                return img_or_arr.copy(left, top, right - left, bottom - top)
            return img_or_arr
        elif isinstance(img_or_arr, np.ndarray):
            H, W = img_or_arr.shape[:2]
            if top > 0 or bottom < H or left > 0 or right < W:
                return img_or_arr[top:bottom, left:right]
            return img_or_arr
        return img_or_arr
