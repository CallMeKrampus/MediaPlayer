"""
BOOB Player - Color Pipeline & Tonemapping Engine
Handles Dolby Vision Profile 5 (IPTPQc2 to SDR), HDR10 (BT.2020 PQ to SDR),
and DCI-XYZ (SMPTE 428-1 Gamma 2.6 to sRGB/Rec.709) color conversions.
"""

import os
import json
import math
import subprocess
import tempfile
import threading
from typing import Optional, Dict, Any, Callable, List
from core.app_paths import get_app_base_dir, get_shaders_dir, get_tool_path
from core.debug_logger import DebugLogger


class TonemapEngine:
    PRESETS = {
        "auto": "Automatic Detection (BT.709 Standard)",
        "dv_p5_sdr": "Dolby Vision Profile 5 -> BT.709 SDR",
        "dv_p5_hdr10": "Dolby Vision Profile 5 -> HDR10 (BT.2020 PQ)",
        "dv_p5_hlg": "Dolby Vision Profile 5 -> HLG (BT.2020 HLG)",
        "dv_p20_rpu_sdr": "🧬 Dolby Vision P20 -> BT.709 SDR (Dynamic RPU L8)",
        "dv_p20_rpu_hdr": "🧬 Dolby Vision P20 -> HDR10 / HDR10+ (Dynamic RPU Trim)",
        "hlg_sdr": "⚡ HLG (BT.2100) -> BT.709 SDR (Punchy Filmic)",
        "dvis_dcp_hdr10": "💎 DVis (DCP) -> Consumer HDR10 (BT.2020 PQ)",
        "dvis_dcp_sdr": "💎 DVis (DCP) -> Rec.709 SDR (108 -> 100 nits)",
        "hdr10_sdr": "HDR10 (BT.2020 PQ) -> BT.709 SDR (Gamma 2.2)",
        "hdr10plus_sdr": "HDR10+ (SMPTE 2094-40) -> BT.709 SDR (Dynamic Peak)",
        "hdr10_hdr": "HDR10 / HDR -> BT.2020 PQ (HDR Display)",
        "hdr10plus_hdr": "HDR10+ (SMPTE 2094-40) -> BT.2020 PQ (HDR Display Dynamic)",
        "dci_xyz_srgb": "DCI-XYZ -> BT.709 (DCP Cinema)",
        "filmic_hable": "Filmic Hable -> BT.709 SDR",
        "spline_sdr": "Spline -> BT.709 SDR (100 Nits)",
        "mobius_sdr": "Mobius -> BT.709 SDR",
        "reinhard_sdr": "Reinhard -> BT.709 SDR",
        "passthrough": "Pass-Through (No Tonemapping)",
    }

    # Human-readable names for status / telemetry lines
    PRIM_NAMES = {"bt.709": "BT.709", "bt.2020": "BT.2020", "auto": "Source", "dci-p3": "DCI-P3"}
    TRC_NAMES = {"gamma2.2": "Gamma 2.2", "srgb": "sRGB", "bt.1886": "BT.1886", "pq": "PQ", "hlg": "HLG", "auto": "Source"}
    CURVE_NAMES = {
        "clip": "None (Clip)", "spline": "Spline", "mobius": "Mobius", "reinhard": "Reinhard",
        "hable": "Hable", "bt.2390": "BT.2390 EETF", "st2094-40": "ST.2094-40 (HDR10+)",
        "st2094-10": "ST.2094-10", "auto": "mpv Default",
    }

    ALGORITHMS = [
        ("bt.2390", "BT.2390 EETF (Cinematic Reference)"),
        ("st2094-40", "ST.2094-40 (HDR10+ Dynamic Bezier)"),
        ("spline", "Spline (Smooth Highlight Preservation)"),
        ("mobius", "Mobius (Soft Knee)"),
        ("reinhard", "Reinhard (Photographic)"),
        ("hable", "Hable (Filmic Uncharted 2)"),
        ("clip", "Native Shader / Passthrough (Clip)"),
        ("auto", "Auto (mpv Default)"),
    ]

    TARGET_PEAKS = [
        (80, "80 nits (Dark Room SDR Studio)"),
        (100, "100 nits (Standard SDR Reference)"),
        (150, "150 nits (Bright SDR Display)"),
        (200, "200 nits (Vivid SDR)"),
        (300, "300 nits (High Brightness Office)"),
        (400, "400 nits (DisplayHDR 400)"),
        (600, "600 nits (DisplayHDR 600)"),
        (1000, "1000 nits (Reference Master Peak)"),
        (40, "40 nits (DV P20 RPU L8 Trim)"),
        (48, "48 nits (DV P20 Theatrical Master Peak)"),
    ]

    PEAK_CURVE_PARAMS = {
        80:   (1.18, 0.20),
        100:  (1.52, 0.45),
        150:  (2.65, 1.05),
        200:  (3.80, 1.65),
        300:  (6.20, 2.80),
        400:  (8.80, 3.90),
        600:  (14.0, 6.00),
        1000: (25.0, 10.2),
    }

    def __init__(self, mpv_player=None):
        self.player = mpv_player
        self.base_dir = get_app_base_dir()
        self.shaders_dir = get_shaders_dir()
        
        self.current_preset = "auto"
        self.current_algorithm = "clip"
        self.target_peak = 100
        self.target_prim = "bt.709"
        self.target_trc = "gamma2.2"
        self.hdr_compute_peak = False
        
        # Color adjustments (-100 to 100)
        self.brightness = 0
        self.contrast = 0
        self.saturation = 0
        self.gamma = 0
        self.hue = 0
        
        # Active GLSL shader
        self.active_shader: Optional[str] = None
        # Qube EPIQ PLF Laser Red Balance Correction
        self.is_epiq: bool = False
        # Auto HDR detection state & display dynamic range telemetry
        self.detected_source_hdr: str = "SDR"
        self.display_is_hdr: bool = False
        self.auto_conversion_summary: Optional[str] = None

        # 3D LUT (.cube / .3dl) Calibration
        self.lut_path: Optional[str] = None
        self.lut_enabled: bool = False

        # Windows 11 Direct HDR Pass-Through
        self.hdr_passthrough: bool = False

        # Split-Screen Comparison Wipe
        self.split_wipe_enabled: bool = False
        self.split_wipe_pos: float = 0.5

        # Dynamic Dolby Vision RPU extraction state & cache
        self.current_uri: str = ""
        self._rpu_cache: Dict[Any, Dict[str, Any]] = {}
        self.last_rpu_trims: Optional[Dict[str, Any]] = None
        self._rpu_worker_lock = threading.Lock()
        self._last_rpu_probe_bucket: Optional[int] = None

        # Callback for UI status synchronization
        self.on_preset_change: Optional[Callable[[Dict[str, Any]], None]] = None
        # Callback for real-time GPU grading updates
        self.on_adjustments_change: Optional[Callable[[int, int, int, int, int], None]] = None

    # Set when the renderer cannot present HDR (e.g. the OpenGL fallback swapchain),
    # so every pipeline is configured for SDR output regardless of the display mode.
    sdr_output_only: bool = False

    @staticmethod
    def pq_code_to_nits(pq_val: float) -> float:
        """Convert 12-bit PQ code [0..4095] or normalized [0..1] to absolute linear luminance (nits)."""
        pq = float(pq_val) / 4095.0 if pq_val > 1.0 else float(pq_val)
        pq = max(0.0, min(1.0, pq))
        if pq <= 0.0:
            return 0.0
        m1 = 2610.0 / 4096.0 / 4.0
        m2 = 2523.0 / 4096.0 * 128.0
        c1 = 3424.0 / 4096.0
        c2 = 2413.0 / 4096.0 * 32.0
        c3 = 2392.0 / 4096.0 * 32.0
        p = pq ** (1.0 / m2)
        num = max(p - c1, 0.0)
        den = max(c2 - c3 * p, 1e-6)
        return float((num / den) ** (1.0 / m1) * 10000.0)

    @classmethod
    def parse_rpu_frame_dict(cls, rpu_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a dovi_tool RPU JSON dictionary and compute the exact native libplacebo
        parameters for both SDR (Level 8 trim) and HDR10 / HDR10+ (dynamic/static trim).
        """
        dm = rpu_dict.get("vdr_dm_data", rpu_dict)
        source_min_pq = int(dm.get("source_min_pq", 7))
        source_max_pq = int(dm.get("source_max_pq", 1787))
        source_max_nits = cls.pq_code_to_nits(source_max_pq)

        cmv29_blocks = (dm.get("cmv29_metadata") or {}).get("ext_metadata_blocks") or []
        cmv40_blocks = (dm.get("cmv40_metadata") or {}).get("ext_metadata_blocks") or []

        l1_list = [b["Level1"] for b in cmv29_blocks if "Level1" in b]
        l2_list = [b["Level2"] for b in cmv29_blocks if "Level2" in b]
        l3_list = [b["Level3"] for b in cmv40_blocks if "Level3" in b]
        l8_list = [b["Level8"] for b in cmv40_blocks if "Level8" in b]
        l10_list = [b["Level10"] for b in cmv40_blocks if "Level10" in b]

        l1 = l1_list[0] if l1_list else {"min_pq": source_min_pq, "max_pq": 2081, "avg_pq": 824}
        l3 = l3_list[0] if l3_list else {"min_pq_offset": 2048, "max_pq_offset": 2048, "avg_pq_offset": 2048}
        l8 = l8_list[0] if l8_list else (l2_list[0] if l2_list else None)
        l10 = l10_list[0] if l10_list else None

        has_l2 = bool(l2_list)
        has_l3 = bool(l3_list)
        has_l8 = bool(l8_list)
        has_l10 = bool(l10_list)
        has_dynamic_trim = bool(has_l8 or has_l3 or has_l2)

        l1_max_pq = int(l1.get("max_pq", 2081))
        l3_max_offset = int(l3.get("max_pq_offset", 2048)) - 2048
        eff_max_pq = max(1, min(4095, l1_max_pq + l3_max_offset))
        eff_max_nits = cls.pq_code_to_nits(eff_max_pq)

        trim_slope = int(l8.get("trim_slope", 2048)) if l8 else 2048
        trim_offset = int(l8.get("trim_offset", 2048)) if l8 else 2048
        trim_power = int(l8.get("trim_power", 2048)) if l8 else 2048
        trim_chroma = int(l8.get("trim_chroma_weight", 2048)) if l8 else 2048
        trim_sat = int(l8.get("trim_saturation_gain", 2048)) if l8 else 2048

        slope_gain = max(0.1, 1.0 + (trim_slope - 2048.0) / 4096.0)
        offset_val = (trim_offset - 2048.0) / 4096.0
        power_exp = max(0.2, 1.0 + (trim_power - 2048.0) / 512.0)

        # Exact algebraic equivalent of L1+L3+L8 slope in BT.1886 / Gamma 2.2 domain:
        sdr_l8_target_peak = max(20, int(round(eff_max_nits / (slope_gain ** 2.2))))

        # Target display peak for HDR10 / HDR10+ from Level 10 or Level 2 or source_max_pq
        if l10 and "target_max_pq" in l10:
            hdr_display_target_peak = max(100, int(round(cls.pq_code_to_nits(int(l10["target_max_pq"])))))
        elif l2_list and "target_max_pq" in l2_list[0]:
            hdr_display_target_peak = max(100, int(round(cls.pq_code_to_nits(int(l2_list[0]["target_max_pq"])))))
        else:
            hdr_display_target_peak = 1000

        hdr_sdr_target_peak = max(20, int(round(source_max_nits)))
        brightness_adj = max(-50, min(50, int(round(offset_val * 100.0))))
        saturation_adj = max(-50, min(50, int(round((trim_sat - 2048.0) / 20.48))))

        return {
            "dovi_profile": int(rpu_dict.get("dovi_profile", 20)),
            "dm_version": 2 if cmv40_blocks else 1,
            "source_min_pq": source_min_pq,
            "source_max_pq": source_max_pq,
            "source_max_nits": round(source_max_nits, 2),
            "l1_max_pq": l1_max_pq,
            "l3_max_pq_offset": l3_max_offset,
            "eff_max_pq": eff_max_pq,
            "eff_max_nits": round(eff_max_nits, 2),
            "has_l2": has_l2,
            "has_l3": has_l3,
            "has_l8": has_l8,
            "has_l10": has_l10,
            "has_dynamic_trim": has_dynamic_trim,
            "hdr_target_format": "HDR10+" if has_dynamic_trim else "HDR10",
            "trim_slope": trim_slope,
            "trim_offset": trim_offset,
            "trim_power": trim_power,
            "trim_chroma_weight": trim_chroma,
            "trim_saturation_gain": trim_sat,
            "slope_gain": round(slope_gain, 4),
            "offset_val": round(offset_val, 4),
            "power_exp": round(power_exp, 4),
            "power_gain": round(power_exp, 4),
            "sdr_l8_target_peak": sdr_l8_target_peak,
            "hdr_display_target_peak": hdr_display_target_peak,
            "hdr_sdr_target_peak": hdr_sdr_target_peak,
            "brightness_adj": brightness_adj,
            "saturation_adj": saturation_adj,
        }

    def extract_dynamic_rpu_trims(
        self,
        uri: Optional[str] = None,
        timestamp_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Dynamically extract the current frame/scene RPU metadata via dovi_tool (or live mpv
        video-params fallback) and return parsed L1/L3/L8/L10 libplacebo parameters.
        """
        target_uri = uri or self.current_uri
        if not target_uri and self.player:
            try:
                target_uri = self.player["path"] or ""
            except Exception:
                target_uri = ""

        if timestamp_sec is None:
            if getattr(self, "current_pts", None) is not None and float(self.current_pts) > 0.0:
                timestamp_sec = float(self.current_pts)
            elif self.player:
                try:
                    tp = self.player["time-pos"]
                    timestamp_sec = float(tp) if tp is not None else 60.0
                except Exception:
                    timestamp_sec = 60.0
        ts = max(0.0, float(timestamp_sec if timestamp_sec is not None else 60.0))
        bucket = int(ts // 5.0)

        if target_uri and (target_uri, bucket) in self._rpu_cache:
            return self._rpu_cache[(target_uri, bucket)]

        if target_uri and os.path.isfile(target_uri):
            dovi_bin = get_tool_path("dovi_tool")
            ffmpeg_bin = get_tool_path("ffmpeg")
            if dovi_bin and ffmpeg_bin:
                tmp_rpu = None
                try:
                    fd, tmp_rpu = tempfile.mkstemp(suffix=".rpu")
                    os.close(fd)
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    pre_seek = max(0.0, ts - 5.0)
                    post_seek = max(0.0, ts - pre_seek)
                    ffmpeg_cmd = [
                        ffmpeg_bin, "-hide_banner", "-loglevel", "error",
                        "-ss", f"{pre_seek:.2f}", "-i", target_uri,
                    ]
                    if post_seek > 0.01:
                        ffmpeg_cmd.extend(["-ss", f"{post_seek:.2f}"])
                    ffmpeg_cmd.extend([
                        "-map", "0:v:0", "-an", "-sn", "-dn",
                        "-frames:v", "1", "-c:v", "copy",
                        "-bsf:v", "hevc_mp4toannexb", "-f", "hevc", "-",
                    ])
                    p1 = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=creationflags,
                    )
                    p2 = subprocess.Popen(
                        [dovi_bin, "extract-rpu", "-", "-o", tmp_rpu],
                        stdin=p1.stdout,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=creationflags,
                    )
                    if p1.stdout:
                        p1.stdout.close()
                    p2.communicate(timeout=2.5)
                    p1.wait(timeout=1.0)

                    if os.path.isfile(tmp_rpu) and os.path.getsize(tmp_rpu) > 0:
                        info_out = subprocess.check_output(
                            [dovi_bin, "info", "-i", tmp_rpu, "-f", "0"],
                            stderr=subprocess.PIPE,
                            timeout=1.5,
                            creationflags=creationflags,
                        ).decode("utf-8", errors="replace")
                        brace_idx = info_out.find("{")
                        if brace_idx >= 0:
                            rpu_json = json.loads(info_out[brace_idx:])
                            parsed = self.parse_rpu_frame_dict(rpu_json)
                            self._rpu_cache[(target_uri, bucket)] = parsed
                            return parsed
                except Exception:
                    pass
                finally:
                    if tmp_rpu and os.path.exists(tmp_rpu):
                        try:
                            os.remove(tmp_rpu)
                        except Exception:
                            pass

        # Fallback: inspect live mpv video-params or use standard DV P20 CM v4.0 L8 defaults
        default_rpu = {
            "dovi_profile": 20,
            "vdr_dm_data": {
                "source_min_pq": 7,
                "source_max_pq": 1787,
                "cmv29_metadata": {"ext_metadata_blocks": [{"Level1": {"min_pq": 12, "max_pq": 2081, "avg_pq": 824}}]},
                "cmv40_metadata": {
                    "ext_metadata_blocks": [
                        {"Level3": {"min_pq_offset": 2111, "max_pq_offset": 1838, "avg_pq_offset": 1980}},
                        {
                            "Level8": {
                                "target_display_index": 255,
                                "trim_slope": 2867,
                                "trim_offset": 2048,
                                "trim_power": 2100,
                                "trim_chroma_weight": 2048,
                                "trim_saturation_gain": 2048,
                            }
                        },
                        {"Level10": {"target_display_index": 255, "target_max_pq": 2547}},
                    ]
                },
            },
        }
        return self.parse_rpu_frame_dict(default_rpu)

    def update_dynamic_rpu_async(self, uri: str, timestamp_sec: float):
        """
        Non-blocking background RPU probe during playback for dv_p20_rpu_sdr and dv_p20_rpu_hdr.
        Updates libplacebo native uniform properties when crossing into a new scene bucket.
        """
        if self.current_preset not in ("dv_p20_rpu_sdr", "dv_p20_rpu_hdr") or not uri:
            return
        bucket = int(max(0.0, float(timestamp_sec)) // 5.0)
        if bucket == self._last_rpu_probe_bucket:
            return
        if not self._rpu_worker_lock.acquire(blocking=False):
            return
        self._last_rpu_probe_bucket = bucket

        def _worker():
            try:
                trims = self.extract_dynamic_rpu_trims(uri=uri, timestamp_sec=timestamp_sec)
                self.last_rpu_trims = trims
                if not self.player or self.current_preset not in ("dv_p20_rpu_sdr", "dv_p20_rpu_hdr"):
                    return
                if self.current_preset == "dv_p20_rpu_sdr":
                    slope = trims.get("slope_gain", 1.0)
                    power = trims.get("power_exp", 1.0)
                    new_contrast = max(-50, min(50, int(round((power - 1.0) * 40.0))))
                    new_gamma = max(-50, min(50, int(round((slope - 1.0) * 50.0))))
                    new_bright = int(trims.get("brightness_adj", 0))
                    new_sat = int(trims.get("saturation_adj", 0))
                    if (new_contrast != self.contrast or new_gamma != self.gamma or
                        new_bright != self.brightness or new_sat != self.saturation):
                        self.contrast = new_contrast
                        self.gamma = new_gamma
                        self.brightness = new_bright
                        self.saturation = new_sat
                        try:
                            self.player["contrast"] = new_contrast
                            self.player["gamma"] = new_gamma
                            self.player["brightness"] = new_bright
                            self.player["saturation"] = new_sat
                        except Exception:
                            pass
                        if self.on_preset_change:
                            try:
                                self.on_preset_change(self.get_status_summary())
                            except Exception:
                                pass
                else:
                    hdr_disp = bool(self.is_display_hdr())
                    new_peak = int(trims["hdr_display_target_peak"] if hdr_disp else 100)
                    if new_peak != self.target_peak:
                        self.target_peak = new_peak
                        try:
                            self.player["target-peak"] = new_peak
                        except Exception:
                            pass
                        if self.on_preset_change:
                            try:
                                self.on_preset_change(self.get_status_summary())
                            except Exception:
                                pass
            finally:
                self._rpu_worker_lock.release()

        threading.Thread(target=_worker, daemon=True).start()

    def set_player(self, mpv_player):
        self.player = mpv_player
        self.apply_preset(self.current_preset)

    def apply_preset(self, preset_key: str, is_epiq: Optional[bool] = None, fps: Optional[float] = None):
        DebugLogger.log("APPLY_PRESET", f"apply_preset requested: '{preset_key}', is_epiq={is_epiq}, fps={fps}")
        self.current_preset = preset_key
        self.auto_conversion_summary = None
        if preset_key == "auto":
            self.detected_source_hdr = "SDR"
        if is_epiq is not None:
            self.is_epiq = is_epiq
        if not self.player:
            DebugLogger.log("APPLY_PRESET", f"Player handle is None, stored preset '{preset_key}' without applying mpv properties")
            return

        # 1. Clear existing user shaders & video filters
        self._clear_shaders()
        try:
            self.player["vf"] = ""
        except Exception:
            pass

        # 2. Reset baseline tone-mapping and color properties to clean defaults
        # This completely prevents leftover settings from previous presets from compounding!
        try:
            self.player["tone-mapping"] = "auto"
            self.player["target-prim"] = "auto"
            self.player["target-trc"] = "auto"
            self.player["target-peak"] = "auto"
            self.player["hdr-compute-peak"] = "no"
            self.player["hdr-contrast-recovery"] = 0.0
            self.player["gamut-mapping-mode"] = "auto"
            self.player["target-contrast"] = "auto"
            self.player["target-colorspace-hint"] = "no"
            if isinstance(self.player, dict):
                self.player["vo"] = "gpu-next"
            else:
                vo_val = getattr(self.player, "vo", None)
                if not (isinstance(vo_val, list) and any(isinstance(v, dict) and v.get("name") == "gpu-next" for v in vo_val)):
                    self.player["vo"] = "gpu-next"
        except Exception:
            pass

        # 3. Reset DCI calibrated offsets if switching away from DCI-XYZ
        if preset_key != "dci_xyz_srgb" and (self.brightness == -6 or self.gamma == -5 or self.contrast in (8, 12) or self.saturation in (10, 15)):
            self.brightness = 0
            self.gamma = 0
            self.contrast = 0
            self.saturation = 0
            if self.player:
                try:
                    self.player["brightness"] = 0
                    self.player["gamma"] = 0
                    self.player["contrast"] = 0
                    self.player["saturation"] = 0
                except Exception:
                    pass

        if preset_key == "dv_p5_sdr":
            # Dolby Vision Profile 5: IPTPQc2 -> Rec.709 SDR with Spline and Cinema Contrast Punch
            self.current_algorithm = "spline"
            self.target_peak = 100
            self.target_prim = "bt.709"
            self.target_trc = "gamma2.2"
            self.hdr_compute_peak = True
            self.contrast = 8
            self.saturation = 10
            
            try:
                if isinstance(self.player, dict):
                    self.player["vo"] = "gpu-next"
                self.player["tone-mapping"] = "spline"
                self.player["target-prim"] = "bt.709"
                self.player["target-trc"] = "gamma2.2"
                self.player["target-peak"] = 100
                self.player["hdr-compute-peak"] = "yes"
                self.player["hdr-contrast-recovery"] = 0.0
                self.player["gamut-mapping-mode"] = "perceptual"
                self.player["contrast"] = self.contrast
                self.player["saturation"] = self.saturation
            except Exception:
                pass
            shader_file = os.path.join(self.shaders_dir, "cinema_contrast_punch.glsl")
            self._clear_shaders()
            if os.path.exists(shader_file):
                self._load_shader(shader_file)

        elif preset_key == "hlg_sdr":
            # HLG (BT.2100) -> Rec.709 SDR with Punchy Filmic Contrast & Deep Blacks
            self.current_algorithm = "bt.2390"
            self.target_peak = 100
            self.target_prim = "bt.709"
            self.target_trc = "gamma2.2"
            self.hdr_compute_peak = True
            self.contrast = 10
            self.saturation = 12
            
            try:
                self.player["tone-mapping"] = "bt.2390"
                self.player["target-prim"] = "bt.709"
                self.player["target-trc"] = "gamma2.2"
                self.player["target-peak"] = 100
                self.player["hdr-compute-peak"] = "yes"
                self.player["hdr-contrast-recovery"] = 0.0
                self.player["gamut-mapping-mode"] = "perceptual"
                self.player["contrast"] = self.contrast
                self.player["saturation"] = self.saturation
            except Exception:
                pass
            shader_file = os.path.join(self.shaders_dir, "cinema_contrast_punch.glsl")
            self._clear_shaders()
            if os.path.exists(shader_file):
                self._load_shader(shader_file)

        elif preset_key == "dv_p5_hdr10":
            # Dolby Vision Profile 5: IPTPQc2 -> HDR10 (BT.2020 PQ)
            self.current_algorithm = "clip"
            self.target_peak = 1000
            self.target_prim = "bt.2020"
            self.target_trc = "pq"
            self.hdr_compute_peak = False
            
            try:
                self.player["tone-mapping"] = "clip"
                self.player["target-prim"] = "bt.2020"
                self.player["target-trc"] = "pq"
                self.player["target-peak"] = 1000
                self.player["hdr-compute-peak"] = "no"
                self.player["gamut-mapping-mode"] = "clip"
            except Exception:
                pass
            self._clear_shaders()

        elif preset_key == "dv_p20_rpu_sdr":
            # Dolby Vision Profile 20 -> BT.709 SDR mapped dynamically
            # using extracted RPU Level 1 + Level 3 + Level 8 trim metadata (zero GLSL shaders)
            trims = self.extract_dynamic_rpu_trims()
            self.last_rpu_trims = trims
            self.current_algorithm = "spline"
            self.target_peak = 100
            self.target_prim = "bt.709"
            self.target_trc = "gamma2.2"
            self.hdr_compute_peak = False

            # Govern tone curve strictly by Level 8 trims (slope, power, offset, saturation)
            slope = trims.get("slope_gain", 1.0)
            power = trims.get("power_exp", 1.0)
            self.contrast = max(-50, min(50, int(round((power - 1.0) * 40.0))))
            self.gamma = max(-50, min(50, int(round((slope - 1.0) * 50.0))))
            self.brightness = int(trims.get("brightness_adj", 0))
            self.saturation = int(trims.get("saturation_adj", 0))

            DebugLogger.log(
                "APPLY_PRESET_DV_P20_SDR",
                "Applying Dolby Vision P20 Level 8 trim pipeline",
                slope_gain=slope,
                power_exp=power,
                computed_gamma=self.gamma,
                computed_contrast=self.contrast,
                computed_brightness=self.brightness,
                computed_saturation=self.saturation,
                target_peak=self.target_peak,
                trims=trims,
            )

            try:
                if isinstance(self.player, dict):
                    self.player["vo"] = "gpu-next"
                self.player["tone-mapping"] = "spline"
                self.player["target-prim"] = "bt.709"
                self.player["target-trc"] = "gamma2.2"
                self.player["target-peak"] = self.target_peak
                self.player["target-contrast"] = "auto"
                self.player["target-colorspace-hint"] = "no"
                self.player["hdr-compute-peak"] = "no"
                self.player["hdr-contrast-recovery"] = 0.0
                self.player["gamut-mapping-mode"] = "perceptual"
                self.player["brightness"] = self.brightness
                self.player["contrast"] = self.contrast
                self.player["saturation"] = self.saturation
                self.player["gamma"] = self.gamma
            except Exception as e:
                DebugLogger.log("APPLY_PRESET_ERROR", f"Error setting mpv properties: {e}")
            self._clear_shaders()

        elif preset_key == "dv_p20_rpu_hdr":
            # Dolby Vision Profile 20 -> HDR10 / HDR10+ mapped dynamically
            # Selects HDR10+ (st2094-40 dynamic bezier) when RPU has dynamic L8/L3/L2 trims,
            # or HDR10 (bt.2390 / clip static peak) when only static L1 metadata is present.
            trims = self.extract_dynamic_rpu_trims()
            self.last_rpu_trims = trims
            has_dynamic = bool(trims.get("has_dynamic_trim", True))
            hdr_disp = False
            if getattr(self, "_forced_display_hdr", None) is not None:
                hdr_disp = bool(self._forced_display_hdr)
            else:
                try:
                    hdr_disp = bool(self.is_display_hdr())
                except Exception:
                    pass
            self.display_is_hdr = hdr_disp

            slope = trims.get("slope_gain", 1.0)
            power = trims.get("power_exp", 1.0)
            self.brightness = int(trims.get("brightness_adj", 0))
            self.saturation = int(trims.get("saturation_adj", 0))

            if hdr_disp:
                self.current_algorithm = "st2094-40" if has_dynamic else "clip"
                self.target_peak = int(trims.get("hdr_display_target_peak", 1000))
                self.target_prim = "bt.2020"
                self.target_trc = "pq"
                self.hdr_compute_peak = False
                self.contrast = 0
                self.gamma = 0
            else:
                self.current_algorithm = "st2094-40" if has_dynamic else "bt.2390"
                self.target_peak = 100
                self.target_prim = "bt.709"
                self.target_trc = "gamma2.2"
                self.hdr_compute_peak = False
                self.gamma = max(-50, min(50, int(round((slope - 1.0) * 50.0))))
                self.contrast = max(-50, min(50, int(round((power - 1.0) * 40.0))))

            try:
                if isinstance(self.player, dict):
                    self.player["vo"] = "gpu-next"
                self.player["tone-mapping"] = self.current_algorithm
                self.player["target-prim"] = self.target_prim
                self.player["target-trc"] = self.target_trc
                self.player["target-peak"] = self.target_peak
                self.player["target-contrast"] = "auto"
                self.player["target-colorspace-hint"] = "yes" if hdr_disp else "no"
                self.player["hdr-compute-peak"] = "no"
                self.player["hdr-contrast-recovery"] = 0.0
                self.player["gamut-mapping-mode"] = "perceptual"
                self.player["brightness"] = self.brightness
                self.player["contrast"] = self.contrast
                self.player["saturation"] = self.saturation
                self.player["gamma"] = self.gamma
            except Exception:
                pass
            self._clear_shaders()

        elif preset_key == "dv_p5_hlg":
            # Dolby Vision Profile 5: IPTPQc2 -> HLG (BT.2020 HLG or Punchy HLG SDR)
            hdr_disp = False
            try:
                hdr_disp = bool(self.is_display_hdr())
            except Exception:
                pass

            if hdr_disp:
                self.current_algorithm = "clip"
                self.target_peak = 1000
                self.target_prim = "bt.2020"
                self.target_trc = "hlg"
                self.hdr_compute_peak = False
                try:
                    self.player["tone-mapping"] = "clip"
                    self.player["target-prim"] = "bt.2020"
                    self.player["target-trc"] = "hlg"
                    self.player["target-peak"] = 1000
                    self.player["hdr-compute-peak"] = "no"
                    self.player["gamut-mapping-mode"] = "clip"
                except Exception:
                    pass
                self._clear_shaders()
            else:
                self.current_algorithm = "bt.2390"
                self.target_peak = 100
                self.target_prim = "bt.709"
                self.target_trc = "gamma2.2"
                self.hdr_compute_peak = True
                self.contrast = 10
                self.saturation = 12
                try:
                    self.player["tone-mapping"] = "bt.2390"
                    self.player["target-prim"] = "bt.709"
                    self.player["target-trc"] = "gamma2.2"
                    self.player["target-peak"] = 100
                    self.player["hdr-compute-peak"] = "yes"
                    self.player["hdr-contrast-recovery"] = 0.0
                    self.player["gamut-mapping-mode"] = "perceptual"
                    self.player["contrast"] = self.contrast
                    self.player["saturation"] = self.saturation
                except Exception:
                    pass
                shader_file = os.path.join(self.shaders_dir, "cinema_contrast_punch.glsl")
                self._clear_shaders()
                if os.path.exists(shader_file):
                    self._load_shader(shader_file)

        elif preset_key == "dvis_dcp_hdr10":
            # DVis DCP: 108-nit DCI-XYZ PQ10K -> Consumer HDR10 (BT.2020 PQ)
            self.current_algorithm = "clip"
            self.target_peak = 1000
            self.target_prim = "bt.2020"
            self.target_trc = "pq"
            self.hdr_compute_peak = False
            try:
                self.player["tone-mapping"] = "clip"
                self.player["target-prim"] = "bt.2020"
                self.player["target-trc"] = "pq"
                self.player["target-peak"] = 1000
                self.player["hdr-compute-peak"] = "no"
                self.player["gamut-mapping-mode"] = "clip"
            except Exception:
                pass
            shader_file = os.path.join(self.shaders_dir, "dvis_dcp_to_hdr10.glsl")
            self._clear_shaders()
            if os.path.exists(shader_file):
                self._load_shader(shader_file)

        elif preset_key == "dvis_dcp_sdr":
            # DVis DCP: 108-nit DCI-XYZ PQ10K -> Rec.709 SDR (100 nits)
            self.current_algorithm = "spline"
            self.target_peak = 100
            self.target_prim = "bt.709"
            self.target_trc = "bt.1886"
            self.hdr_compute_peak = False
            try:
                if isinstance(self.player, dict):
                    self.player["vo"] = "gpu-next"
                self.player["tone-mapping"] = "spline"
                self.player["target-prim"] = "bt.709"
                self.player["target-trc"] = "auto"
                self.player["target-peak"] = 100
                self.player["hdr-compute-peak"] = "no"
                self.player["gamut-mapping-mode"] = "clip"
            except Exception:
                pass
            shader_file = os.path.join(self.shaders_dir, "dvis_dcp_to_sdr.glsl")
            self._clear_shaders()
            if os.path.exists(shader_file):
                self._load_shader(shader_file)

        elif preset_key in ("hdr10_sdr", "hdr10plus_sdr"):
            # HDR / HDR10 / HDR10+ (BT.2020 PQ / SMPTE 2094-40) -> BT.709 SDR, Gamma 2.2 @ 100 nits.
            # Delivers the 6_spline_p50 reference brightness at 100 nits via hdr_sdr_peak_100.glsl.
            self._apply_sdr_bt709("spline", target_peak=100, contrast_recovery=0.35)

        elif preset_key == "hdr10_hdr":
            # HDR10 / HDR -> BT.2020 PQ (HDR Display)
            self.current_algorithm = "clip"
            self.target_peak = 1000
            self.target_prim = "bt.2020"
            self.target_trc = "pq"
            self.hdr_compute_peak = False

            try:
                self.player["tone-mapping"] = "clip"
                self.player["target-prim"] = "bt.2020"
                self.player["target-trc"] = "pq"
                self.player["target-peak"] = 1000
                self.player["hdr-compute-peak"] = "no"
                self.player["gamut-mapping-mode"] = "clip"
            except Exception:
                pass
            self._clear_shaders()

        elif preset_key == "hdr10plus_hdr":
            # HDR10+ (SMPTE 2094-40) -> BT.2020 PQ (HDR Display Dynamic)
            self.current_algorithm = "bt.2390"
            self.target_peak = 1000
            self.target_prim = "bt.2020"
            self.target_trc = "pq"
            self.hdr_compute_peak = True

            try:
                self.player["tone-mapping"] = "bt.2390"
                self.player["target-prim"] = "bt.2020"
                self.player["target-trc"] = "pq"
                self.player["target-peak"] = 1000
                self.player["hdr-compute-peak"] = "yes"
                self.player["gamut-mapping-mode"] = "clip"
            except Exception:
                pass
            self._clear_shaders()

        elif preset_key == "dci_xyz_srgb":
            # Cinema pipeline: DCI-XYZ (SMPTE 428-1 Gamma 2.6) -> Rec.709 with Cinema Punch & Vibrancy
            self.target_prim = "bt.709"
            self.target_trc = "gamma2.2"
            self.target_peak = 100
            self.current_algorithm = "clip"
            self.brightness = 0
            self.gamma = 0
            self.contrast = 12 if self.is_epiq else 8
            self.saturation = 15 if self.is_epiq else 10

            try:
                self.player["tone-mapping"] = "clip"
                self.player["gamut-mapping-mode"] = "clip"
                self.player["hdr-compute-peak"] = "no"
                self.player["target-colorspace-hint"] = "no"
                self.player["target-prim"] = "bt.709"
                self.player["target-trc"] = "gamma2.2"
                self.player["target-peak"] = 100
                self.player["brightness"] = 0
                self.player["gamma"] = 0
                self.player["contrast"] = self.contrast
                self.player["saturation"] = self.saturation

                # format=rgb48le instructs swscale to perform clean, 16-bit DCI-XYZ to Rec.709 conversion
                self.player["vf"] = "format=rgb48le"
            except Exception as e:
                print(f"[TonemapEngine] DCI-XYZ Rec.709 setup error: {e}")

            # Calibrated cinema contrast punch shader (deep velvety blacks, bold midtones, P3 color volume)
            shader_file = os.path.join(
                self.shaders_dir,
                "dci_xyz_epiq_to_srgb.glsl" if self.is_epiq else "dci_xyz_to_srgb.glsl"
            )
            self._clear_shaders()
            if os.path.exists(shader_file):
                self._load_shader(shader_file)

        elif preset_key == "filmic_hable":
            self._apply_sdr_bt709("hable")

        elif preset_key == "spline_sdr":
            self._apply_sdr_bt709("spline")

        elif preset_key == "mobius_sdr":
            self._apply_sdr_bt709("mobius")

        elif preset_key == "reinhard_sdr":
            self._apply_sdr_bt709("reinhard")

        elif preset_key == "passthrough":
            # No tone curve, no gamut compression, no peak detection, no shaders.
            # On an HDR display the native signal is handed to the display untouched
            # (target-colorspace-hint). On an SDR display HDR cannot be shown without
            # tonemapping, so out-of-range highlights clip and PQ midtones look dim.
            self.current_algorithm = "clip"
            self.target_prim = "auto"
            self.target_trc = "auto"
            self.hdr_compute_peak = False
            hdr_disp = False
            try:
                hdr_disp = bool(self.is_display_hdr())
            except Exception:
                pass
            self.display_is_hdr = hdr_disp
            try:
                self.player["tone-mapping"] = "clip"
                self.player["gamut-mapping-mode"] = "clip"
                self.player["hdr-compute-peak"] = "no"
                self.player["target-prim"] = "auto"
                self.player["target-trc"] = "auto"
                self.player["target-peak"] = "auto"
                self.player["target-colorspace-hint"] = "yes" if hdr_disp else "no"
            except Exception:
                pass
            self._clear_shaders()

        elif preset_key == "auto":
            self.current_algorithm = "clip"
            self.target_prim = "bt.709"
            self.target_trc = "gamma2.2"
            try:
                self.player["tone-mapping"] = "clip"
                self.player["target-prim"] = "bt.709"
                self.player["target-trc"] = "gamma2.2"
                self.player["hdr-compute-peak"] = "no"
            except Exception:
                pass

        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def _apply_peak_curve_shader(self, nits: int):
        """Load the calibrated target-peak luminance transfer shader for nits."""
        if not self.player or self.current_preset == "passthrough":
            return
        nits_i = int(nits)
        shader_file = os.path.join(self.shaders_dir, f"hdr_sdr_peak_{nits_i}.glsl")
        if not os.path.exists(shader_file):
            # Interpolate or fall back to closest calibrated entry
            closest = min(self.PEAK_CURVE_PARAMS.keys(), key=lambda k: abs(k - nits_i))
            shader_file = os.path.join(self.shaders_dir, f"hdr_sdr_peak_{closest}.glsl")
        self._clear_shaders()
        self._load_shader(shader_file)

    def _apply_sdr_bt709(self, curve: str, target_peak: int = 100, contrast_recovery: float = 0.35):
        """Shared SDR output pipeline: any source -> BT.709 primaries, Gamma 2.2 @ 100 nits."""
        self.current_algorithm = curve
        self.target_peak = target_peak
        self.target_prim = "bt.709"
        self.target_trc = "gamma2.2"
        self.hdr_compute_peak = True
        try:
            self.player["tone-mapping"] = curve
            self.player["target-prim"] = "bt.709"
            self.player["target-trc"] = "gamma2.2"
            self.player["target-peak"] = target_peak
            self.player["hdr-compute-peak"] = "yes"
            self.player["hdr-contrast-recovery"] = contrast_recovery
            self.player["gamut-mapping-mode"] = "auto"
        except Exception:
            pass
        self._apply_peak_curve_shader(target_peak)

    def set_algorithm(self, algo: str):
        self.current_algorithm = algo
        if self.player:
            try:
                self.player["tone-mapping"] = algo
            except Exception:
                pass
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def set_target_peak(self, nits: int):
        self.target_peak = int(nits)
        if self.player:
            try:
                self.player["target-peak"] = int(nits)
            except Exception:
                pass
            if self.current_preset not in ("passthrough", "dv_p20_rpu_sdr", "dv_p20_rpu_hdr"):
                self._apply_peak_curve_shader(int(nits))
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def set_adjustments(self, brightness: int = 0, contrast: int = 0,
                         saturation: int = 0, gamma: int = 0, hue: int = 0):
        self.brightness = brightness
        self.contrast = contrast
        self.saturation = saturation
        self.gamma = gamma
        self.hue = hue
        
        if self.on_adjustments_change:
            try:
                self.on_adjustments_change(brightness, contrast, saturation, gamma, hue)
            except Exception:
                pass

        if self.player:
            try:
                self.player["brightness"] = brightness
                self.player["contrast"] = contrast
                self.player["saturation"] = saturation
                self.player["gamma"] = gamma
                self.player["hue"] = hue
            except Exception:
                pass

    def enable_dci_xyz_mode(self, enabled: bool = True, is_epiq: bool = False, fps: Optional[float] = None, is_dolby_vision: bool = False, **kwargs):
        """Dedicated switch for DCI Cinema XYZ color conversion."""
        self.is_epiq = is_epiq
        if enabled:
            if is_dolby_vision:
                preset = "dvis_dcp_hdr10" if self.display_is_hdr else "dvis_dcp_sdr"
                self.apply_preset(preset, fps=fps)
            else:
                self.apply_preset("dci_xyz_srgb", fps=fps)
        else:
            self.apply_preset("auto")

    def set_3d_lut(self, path: Optional[str]):
        """Load or update custom 3D LUT (.cube / .3dl) file."""
        self.lut_path = path
        self.lut_enabled = bool(path and os.path.exists(path))
        self._apply_3d_lut()
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def toggle_3d_lut(self) -> bool:
        """Toggle active 3D LUT on or off."""
        if not self.lut_path or not os.path.exists(self.lut_path):
            self.lut_enabled = False
        else:
            self.lut_enabled = not self.lut_enabled
        self._apply_3d_lut()
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass
        return self.lut_enabled

    def clear_3d_lut(self):
        """Unload and clear active 3D LUT."""
        self.lut_path = None
        self.lut_enabled = False
        self._apply_3d_lut()
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def _apply_3d_lut(self):
        if not self.player:
            return
        try:
            if self.lut_enabled and self.lut_path and os.path.exists(self.lut_path):
                norm_p = self.lut_path.replace("\\", "/")
                self.player["lut"] = norm_p
                self.player["lut-type"] = "auto"
            else:
                self.player["lut"] = ""
        except Exception:
            pass

    def set_hdr_passthrough(self, enabled: bool):
        """Enable or disable Windows 11 direct HDR swapchain pass-through."""
        self.hdr_passthrough = bool(enabled)
        if not self.player:
            return
        try:
            if self.hdr_passthrough:
                self.player["target-colorspace-hint"] = "yes"
                self.player["target-trc"] = "auto"
                self.player["target-prim"] = "auto"
                self.player["tone-mapping"] = "passthrough"
                self.player["hdr-compute-peak"] = "no"
            else:
                self.apply_preset(self.current_preset)
                self.player["target-colorspace-hint"] = "no"
        except Exception:
            pass
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def set_split_wipe(self, enabled: bool, pos: float = 0.5):
        """Configure A/B comparison split-screen wipe position (0.05 to 0.95)."""
        self.split_wipe_enabled = bool(enabled)
        self.split_wipe_pos = max(0.05, min(0.95, float(pos)))
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def set_epiq_correction(self, enabled: bool):
        self.is_epiq = enabled
        if self.current_preset == "dci_xyz_srgb":
            self.apply_preset("dci_xyz_srgb")
            return
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def enable_dv_profile5_mode(self, enabled: bool = True, target: str = "sdr"):
        """Dedicated switch for Dolby Vision Profile 5 color conversion ('sdr', 'hdr10', 'hlg')."""
        if enabled:
            preset = f"dv_p5_{target.lower()}"
            if preset not in self.PRESETS:
                preset = "dv_p5_sdr"
            self.apply_preset(preset)
        else:
            self.apply_preset("auto")

    def enable_dv_profile20_mode(self, enabled: bool = True, target: str = "sdr"):
        """Dedicated switch for Dolby Vision Profile 20 (3D MV-HEVC) dynamic RPU color conversion ('sdr' or 'hdr')."""
        if enabled:
            t = target.lower()
            if t in ("hdr", "hdr10", "hdr10+", "rpu_hdr"):
                preset = "dv_p20_rpu_hdr"
            else:
                preset = "dv_p20_rpu_sdr"
            self.apply_preset(preset)
        else:
            self.apply_preset("auto")

    def set_3d_lut(self, path: Optional[str]):
        """Load or update custom 3D LUT (.cube / .3dl) file."""
        self.lut_path = path
        self.lut_enabled = bool(path and os.path.exists(path))
        self._apply_3d_lut()
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def toggle_3d_lut(self) -> bool:
        """Toggle active 3D LUT on or off."""
        if not self.lut_path or not os.path.exists(self.lut_path):
            self.lut_enabled = False
        else:
            self.lut_enabled = not self.lut_enabled
        self._apply_3d_lut()
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass
        return self.lut_enabled

    def clear_3d_lut(self):
        """Unload and clear active 3D LUT."""
        self.lut_path = None
        self.lut_enabled = False
        self._apply_3d_lut()
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def _apply_3d_lut(self):
        if not self.player:
            return
        try:
            if self.lut_enabled and self.lut_path and os.path.exists(self.lut_path):
                norm_p = self.lut_path.replace("\\", "/")
                self.player["lut"] = norm_p
                self.player["lut-type"] = "auto"
            else:
                self.player["lut"] = ""
        except Exception:
            pass

    def set_hdr_passthrough(self, enabled: bool):
        """Enable or disable Windows 11 direct HDR swapchain pass-through."""
        self.hdr_passthrough = bool(enabled)
        if not self.player:
            return
        try:
            if self.hdr_passthrough:
                self.player["target-colorspace-hint"] = "yes"
                self.player["target-trc"] = "auto"
                self.player["target-prim"] = "auto"
                self.player["tone-mapping"] = "passthrough"
                self.player["hdr-compute-peak"] = "no"
            else:
                self.apply_preset(self.current_preset)
                self.player["target-colorspace-hint"] = "no"
        except Exception:
            pass
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    def set_split_wipe(self, enabled: bool, pos: float = 0.5):
        """Configure A/B comparison split-screen wipe position (0.05 to 0.95)."""
        self.split_wipe_enabled = bool(enabled)
        self.split_wipe_pos = max(0.05, min(0.95, float(pos)))
        if self.on_preset_change:
            try:
                self.on_preset_change(self.get_status_summary())
            except Exception:
                pass

    @staticmethod
    def get_libplacebo_filter(encoding_type: str) -> str:
        """
        Returns exact libplacebo filter string as defined in the knowledge base:
        - hdr10: hwupload,libplacebo=peak_detect=false:colorspace=9:color_primaries=9:color_trc=16:range=tv:format=yuv420p10le,hwdownload,format=yuv420p10le
        - sdr:   hwupload,libplacebo=peak_detect=false:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:format=yuv420p10le,hwdownload,format=yuv420p10le
        - hlg:   hwupload,libplacebo=peak_detect=false:colorspace=9:color_primaries=9:color_trc=14:range=tv:format=yuv420p10le,hwdownload,format=yuv420p10le
        - none:  hwupload,libplacebo=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:format=yuv420p,hwdownload,format=yuv420p
        """
        et = (encoding_type or "").lower()
        if "hdr10" in et:
            return "hwupload,libplacebo=peak_detect=false:colorspace=9:color_primaries=9:color_trc=16:range=tv:format=yuv420p10le,hwdownload,format=yuv420p10le"
        elif "hlg" in et:
            return "hwupload,libplacebo=peak_detect=false:colorspace=9:color_primaries=9:color_trc=14:range=tv:format=yuv420p10le,hwdownload,format=yuv420p10le"
        elif "sdr" in et:
            return "hwupload,libplacebo=peak_detect=false:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:format=yuv420p10le,hwdownload,format=yuv420p10le"
        elif "none" in et:
            return "hwupload,libplacebo=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:format=yuv420p,hwdownload,format=yuv420p"
        return "hwupload,libplacebo=peak_detect=false:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:format=yuv420p10le,hwdownload,format=yuv420p10le"

    @staticmethod
    def get_ffmpeg_colorspace_filter(encoding_type: str) -> str:
        """
        Returns reference FFmpeg colorspace filter strings for Dolby Vision Profile 5:
        - hdr10: colorspace=space=bt2020:primaries=bt2020:trc=smpte2084:format=p010le
        - sdr:   colorspace=space=bt709:primaries=bt709:trc=iec61966-2-1:itp=bt2100:format=yuv420p
        """
        et = (encoding_type or "").lower()
        if "hdr10" in et:
            return "colorspace=space=bt2020:primaries=bt2020:trc=smpte2084:format=p010le"
        elif "sdr" in et:
            return "colorspace=space=bt709:primaries=bt709:trc=iec61966-2-1:itp=bt2100:format=yuv420p"
        return ""

    @staticmethod
    def get_ffmpeg_conversion_command(
        input_path: str,
        output_path: str,
        color_space: str = "sdr",
        video_codec: str = "hevc_nvenc",
        bitrate_k: int = 15000,
        ffmpeg_bin: str = "ffmpeg"
    ) -> list:
        """
        Constructs the exact FFmpeg command line for converting Dolby Vision Profile 5
        using hardware acceleration and the user's reference parameters.
        """
        cs = (color_space or "sdr").lower()
        vf = TonemapEngine.get_libplacebo_filter(cs)
        resolved_ffmpeg = get_tool_path("ffmpeg") if ffmpeg_bin == "ffmpeg" else ffmpeg_bin

        args = [
            resolved_ffmpeg,
            "-nostdin",
            "-y",
            "-init_hw_device", "vulkan=vk",
            "-filter_hw_device", "vk",
            "-i", input_path,
            "-vf", vf,
        ]

        if "nvenc" in video_codec.lower():
            pix_fmt = "p010le" if cs in ("hdr10", "hlg") else "yuv420p"
            args.extend([
                "-c:v", video_codec,
                "-preset", "p7",
                "-tune", "hq",
                "-rc", "constqp",
                "-qp", "12",
                "-b_ref_mode", "each",
                "-rc-lookahead", "32",
                "-spatial-aq", "1",
                "-aq-strength", "8",
                "-multipass", "fullres",
                "-pix_fmt", pix_fmt,
            ])
        else:
            args.extend([
                "-c:v", video_codec,
                "-b:v", f"{bitrate_k}k",
            ])

        args.extend([
            "-c:a", "copy",
            "-c:s", "copy",
            output_path
        ])
        return args

    @staticmethod
    def get_dvis_conversion_command(
        input_picture_mxf: str,
        output_path: str,
        target_mode: str = "hdr10",
        format_type: str = "mp4_hevc",
        audio_mxf: Optional[str] = None,
        frames: int = 0,
        ffmpeg_bin: str = "ffmpeg"
    ) -> list:
        """
        Constructs FFmpeg command line for converting a DVis (Dolby Vision DCP) picture MXF
        to Consumer HDR10 (BT.2020 PQ) or Studio Rec.709 SDR.
        """
        resolved_ffmpeg = get_tool_path("ffmpeg") if ffmpeg_bin == "ffmpeg" else ffmpeg_bin
        args = [
            resolved_ffmpeg,
            "-nostdin",
            "-y",
            "-threads", "16",
            "-i", input_picture_mxf,
        ]
        if audio_mxf and os.path.isfile(audio_mxf):
            args.extend(["-i", audio_mxf])

        if target_mode.lower() == "hdr10":
            # Direct mapping into Consumer HDR10
            vf = "zscale=matrixin=gbr:transferin=smpte2084:primariesin=bt2020:rangein=full:matrix=bt2020nc:transfer=smpte2084:primaries=bt2020:range=limited,format=yuv420p10le"
            args.extend([
                "-vf", vf,
                "-color_primaries", "bt2020",
                "-color_trc", "smpte2084",
                "-colorspace", "bt2020nc",
                "-color_range", "tv",
            ])
            if "prores" in format_type.lower():
                args.extend(["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"])
            else:
                args.extend(["-c:v", "libx265", "-crf", "18", "-preset", "medium"])
        else:
            # SDR Rec.709
            vf = "zscale=matrixin=gbr:transferin=bt709:primariesin=bt709:rangein=full:matrix=bt709:transfer=bt709:primaries=bt709:range=limited,format=yuv420p"
            args.extend([
                "-vf", vf,
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-colorspace", "bt709",
                "-color_range", "tv",
            ])
            if "prores" in format_type.lower():
                args.extend(["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"])
            elif "h264" in format_type.lower():
                args.extend(["-c:v", "libx264", "-crf", "18", "-preset", "medium"])
            else:
                args.extend(["-c:v", "libx265", "-crf", "20", "-preset", "medium"])

        if audio_mxf and os.path.isfile(audio_mxf):
            args.extend([
                "-filter_complex", "[1:a]pan=5.1|c0=c0|c1=c1|c2=c2|c3=c3|c4=c4|c5=c5[aout]",
                "-map", "0:v:0",
                "-map", "[aout]",
                "-c:a", "aac", "-b:a", "448k"
            ])
        else:
            args.extend(["-an"])

        if frames > 0:
            args.extend(["-frames:v", str(frames)])

        args.append(output_path)
        return args

    @staticmethod
    def is_display_hdr() -> bool:
        """
        Detects if the active Windows display has HDR (Advanced Color) enabled.
        Uses Windows DisplayConfigGetDeviceInfo API (DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO).
        Returns True if HDR is actively enabled on the primary display, False for SDR.
        """
        if TonemapEngine.sdr_output_only:
            return False
        try:
            import sys
            if sys.platform != "win32":
                return False

            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            class LUID(ctypes.Structure):
                _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]

            class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
                _fields_ = [('Numerator', wintypes.UINT), ('Denominator', wintypes.UINT)]

            class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
                _fields_ = [
                    ('adapterId', LUID),
                    ('id', wintypes.UINT),
                    ('modeInfoIdx', wintypes.UINT),
                    ('statusFlags', wintypes.UINT)
                ]

            class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
                _fields_ = [
                    ('adapterId', LUID),
                    ('id', wintypes.UINT),
                    ('modeInfoIdx', wintypes.UINT),
                    ('outputTechnology', wintypes.UINT),
                    ('rotation', wintypes.UINT),
                    ('scaling', wintypes.UINT),
                    ('refreshRate', DISPLAYCONFIG_RATIONAL),
                    ('scanLineOrdering', wintypes.UINT),
                    ('targetAvailable', wintypes.BOOL),
                    ('statusFlags', wintypes.UINT)
                ]

            class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
                _fields_ = [
                    ('sourceInfo', DISPLAYCONFIG_PATH_SOURCE_INFO),
                    ('targetInfo', DISPLAYCONFIG_PATH_TARGET_INFO),
                    ('flags', wintypes.UINT)
                ]

            class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
                _fields_ = [
                    ('infoType', wintypes.UINT),
                    ('id', wintypes.UINT),
                    ('adapterId', LUID),
                    ('dummy', ctypes.c_byte * 64)
                ]

            class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
                _fields_ = [
                    ('type', wintypes.UINT),
                    ('size', wintypes.UINT),
                    ('adapterId', LUID),
                    ('id', wintypes.UINT)
                ]

            class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
                _fields_ = [
                    ('header', DISPLAYCONFIG_DEVICE_INFO_HEADER),
                    ('value', wintypes.UINT),
                    ('colorEncoding', wintypes.UINT),
                    ('bitsPerColorChannel', wintypes.UINT)
                ]

            QDC_ONLY_ACTIVE_PATHS = 0x00000002
            numPath = wintypes.UINT()
            numMode = wintypes.UINT()

            if user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(numPath), ctypes.byref(numMode)) != 0:
                return False

            paths = (DISPLAYCONFIG_PATH_INFO * numPath.value)()
            modes = (DISPLAYCONFIG_MODE_INFO * numMode.value)()

            if user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(numPath), paths, ctypes.byref(numMode), modes, None) != 0:
                return False

            for p in paths:
                adv = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
                adv.header.type = 9  # DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
                adv.header.size = ctypes.sizeof(DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO)
                adv.header.adapterId = p.targetInfo.adapterId
                adv.header.id = p.targetInfo.id

                if user32.DisplayConfigGetDeviceInfo(ctypes.byref(adv)) == 0:
                    # advancedColorEnabled is bit 1 (0x2)
                    if bool(adv.value & 0x2):
                        return True
            return False
        except Exception:
            return False

    def _load_shader(self, shader_path: str):
        if not self.player or not os.path.exists(shader_path):
            return
        try:
            # mpv glsl-shader-append command or glsl-shaders property
            normalized = shader_path.replace("\\", "/")
            self.player.command("change-list", "glsl-shaders", "set", normalized)
            self.active_shader = normalized
        except Exception:
            try:
                self.player["glsl-shaders"] = normalized
                self.active_shader = normalized
            except Exception:
                pass

    def _clear_shaders(self):
        if not self.player:
            return
        try:
            self.player.command("change-list", "glsl-shaders", "clr", "")
            self.active_shader = None
        except Exception:
            try:
                self.player["glsl-shaders"] = ""
                self.active_shader = None
            except Exception:
                pass

    @staticmethod
    def detect_source_hdr_format(
        probe_video_track: Optional[Dict[str, Any]] = None,
        mpv_tracks: Optional[List[Dict[str, Any]]] = None,
        mpv_video_params: Optional[Dict[str, Any]] = None,
        uri: str = "",
    ) -> str:
        """
        Detect source HDR format ('Dolby Vision P5', 'Dolby Vision P7/P8', 'HDR10+',
        'HDR10', 'HLG', 'HDR', 'DCI-XYZ', or 'SDR') from probe metadata, mpv tracks,
        live video-params, and URI hints.
        """
        uri_l = (uri or "").lower()

        if probe_video_track:
            fmt = probe_video_track.get("hdr_format")
            if fmt and fmt != "SDR":
                DebugLogger.log("DETECT_HDR_BRANCH", f"Matched probe_video_track.hdr_format='{fmt}'", fmt=fmt)
                return str(fmt)
            dvp = probe_video_track.get("dolby_vision_profile")
            if dvp == 5 or probe_video_track.get("is_dv_p5"):
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched probe_video_track Dolby Vision P5", dvp=dvp)
                return "Dolby Vision P5"
            if dvp == 20 or probe_video_track.get("is_dv_p20"):
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched probe_video_track Dolby Vision P20", dvp=dvp)
                return "Dolby Vision P20"
            if dvp is not None:
                DebugLogger.log("DETECT_HDR_BRANCH", f"Matched probe_video_track Dolby Vision P{dvp}", dvp=dvp)
                return f"Dolby Vision P{dvp}"
            if probe_video_track.get("is_hdr10plus"):
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched probe_video_track is_hdr10plus")
                return "HDR10+"
            trc = str(probe_video_track.get("color_transfer", "") or "").lower()
            prim = str(probe_video_track.get("color_primaries", "") or "").lower()
            if trc in ("arib-std-b67", "hlg"):
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched probe_video_track HLG", trc=trc)
                return "HLG"
            if trc in ("smpte2084", "pq"):
                res = "HDR10+" if any(k in uri_l for k in ("hdr10+", "hdr10plus", "2094")) else "HDR10"
                DebugLogger.log("DETECT_HDR_BRANCH", f"Matched probe_video_track PQ -> '{res}'", trc=trc, prim=prim)
                return res
            if trc == "smpte428" or "xyz" in str(probe_video_track.get("pix_fmt", "")).lower():
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched probe_video_track DCI-XYZ")
                return "DCI-XYZ"
            sdr_trcs = ("bt709", "bt470bg", "bt470m", "smpte170m", "iec61966-2-1", "gamma22", "gamma28", "bt2020-10", "bt2020-12")
            if trc in sdr_trcs:
                # Wide-gamut SDR (e.g. BT.2020 primaries + BT.709 transfer): gamut-map only, never tonemap
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched probe_video_track SDR TRC", trc=trc)
                return "SDR"
            if "bt2020" in prim or probe_video_track.get("hdr"):
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched probe_video_track HDR via prim/hdr", prim=prim)
                return "HDR"

        is_dv_hint = any(k in uri_l for k in (".dv.", "-dv.", "_dv.", "dv-", "dv_", "dovi", "dolby.vision", "dolby vision", "dv.hevc", "dv.h265"))
        is_dv_p20_hint = any(k in uri_l for k in ("mv-hevc", "dv.p20", "profile20", "p20")) or (is_dv_hint and "3d" in uri_l)

        if mpv_tracks:
            for t in mpv_tracks:
                if t.get("type") != "video":
                    continue
                dvp = t.get("dolby-vision-profile") or t.get("demux-dolby-vision-profile")
                if dvp == 20 or str(dvp) == "20":
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_tracks Dolby Vision P20", dvp=dvp)
                    return "Dolby Vision P20"
                if dvp == 5 or str(dvp) == "5":
                    res = "Dolby Vision P20" if is_dv_p20_hint else "Dolby Vision P5"
                    DebugLogger.log("DETECT_HDR_BRANCH", f"Matched mpv_tracks DV P5 (hint P20={is_dv_p20_hint}) -> '{res}'", dvp=dvp)
                    return res
                if dvp is not None:
                    DebugLogger.log("DETECT_HDR_BRANCH", f"Matched mpv_tracks Dolby Vision P{dvp}", dvp=dvp)
                    return f"Dolby Vision P{dvp}"

        if mpv_video_params:
            gamma_l = str(mpv_video_params.get("gamma", "") or "").lower()
            prim_l = str(mpv_video_params.get("primaries", "") or "").lower()
            cmat_l = str(mpv_video_params.get("colormatrix", "") or "").lower()
            pix_l = str(mpv_video_params.get("pixelformat", "") or "").lower()
            sig_peak = float(mpv_video_params.get("sig-peak", 0) or 0)
            max_luma = float(mpv_video_params.get("max-luma", 0) or 0)

            if "dolbyvision" in cmat_l:
                if probe_video_track and (probe_video_track.get("is_dv_p20") or probe_video_track.get("dolby_vision_profile") == 20):
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params dolbyvision + probe P20")
                    return "Dolby Vision P20"
                if mpv_tracks:
                    for t in mpv_tracks:
                        if t.get("type") == "video":
                            p = t.get("dolby-vision-profile") or t.get("demux-dolby-vision-profile")
                            if p == 20 or str(p) == "20":
                                DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params dolbyvision + track P20")
                                return "Dolby Vision P20"
                if is_dv_p20_hint:
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params dolbyvision + uri hint P20")
                    return "Dolby Vision P20"
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params dolbyvision -> default P5")
                return "Dolby Vision P5"
            if "hlg" in gamma_l or "arib-std-b67" in gamma_l:
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params HLG", gamma=gamma_l)
                return "HLG"
            if any(k in gamma_l for k in ("pq", "smpte2084", "st2084")):
                if probe_video_track and (probe_video_track.get("is_dv_p20") or probe_video_track.get("dolby_vision_profile") == 20):
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params PQ + probe P20 -> 'Dolby Vision P20'")
                    return "Dolby Vision P20"
                if probe_video_track and (probe_video_track.get("is_dv_p5") or probe_video_track.get("dolby_vision_profile") == 5):
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params PQ + probe P5 -> 'Dolby Vision P5'")
                    return "Dolby Vision P5"
                if mpv_tracks:
                    for t in mpv_tracks:
                        if t.get("type") == "video":
                            p = t.get("dolby-vision-profile") or t.get("demux-dolby-vision-profile")
                            if p == 20 or str(p) == "20":
                                DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params PQ + track P20 -> 'Dolby Vision P20'")
                                return "Dolby Vision P20"
                            if p == 5 or str(p) == "5":
                                res = "Dolby Vision P20" if is_dv_p20_hint else "Dolby Vision P5"
                                DebugLogger.log("DETECT_HDR_BRANCH", f"Matched mpv_video_params PQ + track P5 -> '{res}'")
                                return res
                if is_dv_p20_hint:
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params PQ + hint P20 -> 'Dolby Vision P20'")
                    return "Dolby Vision P20"
                if is_dv_hint:
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params PQ + hint DV -> 'Dolby Vision P5'")
                    return "Dolby Vision P5"
                res = "HDR10+" if any(k in uri_l for k in ("hdr10+", "hdr10plus", "2094")) else "HDR10"
                DebugLogger.log("DETECT_HDR_BRANCH", f"Matched mpv_video_params PQ -> '{res}'", gamma=gamma_l)
                return res
            if "xyz" in pix_l or "xyz" in cmat_l:
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params DCI-XYZ")
                return "DCI-XYZ"
            sdr_gamma = any(k in gamma_l for k in ("bt.1886", "bt.709", "srgb", "gamma", "linear")) if gamma_l else False
            if sdr_gamma and sig_peak <= 1.5 and max_luma <= 250:
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params SDR gamma and peak", gamma=gamma_l, sig_peak=sig_peak)
                return "SDR"
            if "bt.2020" in prim_l or "bt2020" in prim_l or sig_peak > 1.5 or max_luma > 250:
                if any(k in uri_l for k in ("hdr10+", "hdr10plus", "2094")):
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params HDR10+ via prim/peak")
                    return "HDR10+"
                if any(k in uri_l for k in ("hdr10", "uhd")):
                    DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params HDR10 via prim/peak")
                    return "HDR10"
                DebugLogger.log("DETECT_HDR_BRANCH", "Matched mpv_video_params HDR via prim/peak")
                return "HDR"

        if any(k in uri_l for k in ("hdr10+", "hdr10plus")):
            DebugLogger.log("DETECT_HDR_BRANCH", "Matched URI hint HDR10+")
            return "HDR10+"

        DebugLogger.log("DETECT_HDR_BRANCH", "No HDR markers matched -> SDR default")
        return "SDR"

    def auto_configure_for_source(
        self,
        source_hdr_format: str,
        is_hdr_display: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Automatically select and apply the tonemapping pipeline matching the source HDR
        format and the active display's supported dynamic range (SDR vs HDR).
        """
        src = (source_hdr_format or "SDR").strip()
        hdr_disp = self.is_display_hdr() if is_hdr_display is None else bool(is_hdr_display)

        if src in ("Dolby Vision P20", "Dolby Vision Profile 20"):
            preset = "dv_p20_rpu_hdr" if hdr_disp else "dv_p20_rpu_sdr"
            summary = f"Auto: 🧬 Dolby Vision P20 -> {'HDR10/10+ (RPU)' if hdr_disp else 'BT.709 SDR (RPU L8)'}"
        elif src == "Dolby Vision P5":
            preset = "dv_p5_hdr10" if hdr_disp else "dv_p5_sdr"
            summary = f"Auto: Dolby Vision P5 -> {'HDR10 BT.2020 PQ' if hdr_disp else 'BT.709 SDR'}"
        elif src == "HDR10+":
            preset = "hdr10plus_hdr" if hdr_disp else "hdr10plus_sdr"
            summary = (
                "Auto: HDR10+ -> HDR BT.2020 PQ (Display HDR)"
                if hdr_disp else "Auto: HDR10+ -> BT.709 SDR (Gamma 2.2, Dynamic Peak)"
            )
        elif src == "HDR10":
            preset = "hdr10_hdr" if hdr_disp else "hdr10_sdr"
            summary = (
                "Auto: HDR10 -> HDR BT.2020 PQ (Display HDR)"
                if hdr_disp else "Auto: HDR10 -> BT.709 SDR (Gamma 2.2)"
            )
        elif src == "DCI-XYZ":
            preset = "dci_xyz_srgb"
            summary = "Auto: DCI-XYZ -> Rec.709 (Cinema Standard)"
        elif src == "HLG":
            preset = "hdr10_hdr" if hdr_disp else "hlg_sdr"
            summary = (
                "Auto: HLG -> HDR BT.2020 HLG (Display HDR)"
                if hdr_disp else "Auto: ⚡ HLG (BT.2100) -> BT.709 SDR (Punchy Filmic)"
            )
        elif src == "HDR" or src.startswith("Dolby Vision"):
            preset = "hdr10_hdr" if hdr_disp else "hdr10_sdr"
            summary = (
                f"Auto: {src} -> HDR BT.2020 PQ (Display HDR)"
                if hdr_disp else f"Auto: {src} -> BT.709 SDR (Gamma 2.2)"
            )
        else:
            preset = "auto"
            summary = None

        DebugLogger.log(
            "AUTO_CONFIGURE",
            f"auto_configure_for_source: source_hdr_format='{src}', hdr_display={hdr_disp} -> selected preset='{preset}'",
            source_hdr_format=src,
            is_hdr_display=hdr_disp,
            selected_preset=preset,
            summary=summary,
        )

        self._forced_display_hdr = hdr_disp
        try:
            self.apply_preset(preset)
        finally:
            self._forced_display_hdr = None
        if src in ("Dolby Vision P20", "Dolby Vision Profile 20") and hdr_disp and self.last_rpu_trims:
            hdr_fmt = self.last_rpu_trims.get("hdr_target_format", "HDR10+")
            summary = f"Auto: 🧬 Dolby Vision P20 -> {hdr_fmt} (RPU)"
        self.detected_source_hdr = src
        self.display_is_hdr = hdr_disp
        self.auto_conversion_summary = summary

        status = self.get_status_summary()
        if self.on_preset_change:
            try:
                self.on_preset_change(status)
            except Exception:
                pass
        return status

    def get_status_summary(self) -> Dict[str, Any]:
        preset_lbl = self.auto_conversion_summary or self.PRESETS.get(self.current_preset, self.current_preset)
        if self.current_preset == "dci_xyz_srgb" and not self.auto_conversion_summary:
            preset_lbl = "DCI-XYZ -> Rec.709 (Pure Standard)"
        if self.current_preset == "passthrough" and not getattr(self, "display_is_hdr", False):
            preset_lbl = "Pass-Through (No Tonemapping - HDR looks dim on SDR display)"
        if self.current_preset == "dv_p20_rpu_hdr" and self.last_rpu_trims and not self.auto_conversion_summary:
            hdr_fmt = self.last_rpu_trims.get("hdr_target_format", "HDR10+")
            preset_lbl = f"🧬 Dolby Vision P20 -> {hdr_fmt} (Dynamic RPU Trim)"

        prim_h = self.PRIM_NAMES.get(str(self.target_prim), str(self.target_prim))
        trc_h = self.TRC_NAMES.get(str(self.target_trc), str(self.target_trc))
        curve_h = self.CURVE_NAMES.get(str(self.current_algorithm), str(self.current_algorithm))

        return {
            "preset": self.current_preset,
            "preset_label": preset_lbl,
            "algorithm": self.current_algorithm,
            "curve_label": curve_h,
            "output_label": f"{prim_h} / {trc_h}",
            "target_peak": f"{self.target_peak} nits",
            "target_prim": self.target_prim,
            "target_trc": self.target_trc,
            "shader_active": bool(self.active_shader),
            "is_epiq": self.is_epiq,
            "lut_path": self.lut_path,
            "lut_enabled": self.lut_enabled,
            "hdr_passthrough": self.hdr_passthrough,
            "split_wipe_enabled": self.split_wipe_enabled,
            "split_wipe_pos": self.split_wipe_pos,
            "detected_source_hdr": getattr(self, "detected_source_hdr", "SDR"),
            "display_dynamic_range": "HDR" if getattr(self, "display_is_hdr", False) else "SDR",
            "auto_conversion_summary": getattr(self, "auto_conversion_summary", None),
            "rpu_trims": getattr(self, "last_rpu_trims", None),
            "adjustments": {
                "brightness": self.brightness,
                "contrast": self.contrast,
                "saturation": self.saturation,
                "gamma": self.gamma,
                "hue": self.hue,
            }
        }
