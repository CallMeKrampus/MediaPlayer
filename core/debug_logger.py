"""
MediaPlayer - Dedicated DV P20 & Color Pipeline Debug Logger
Saves each playback/opening instance as a completely separate log file in 'debug_logs/'
(e.g., 'debug_logs/instance_001_20261116_103000_media.log' and 'debug_logs/latest_instance.log')
while also maintaining the consolidated master log 'dv_p20_debug.log' and live stderr.
"""

import os
import re
import sys
import time
import json
import shutil
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable


class DebugLogger:
    _lock = threading.Lock()
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _logs_dir = os.path.join(_base_dir, "debug_logs")
    _master_log_file = os.path.join(_base_dir, "dv_p20_debug.log")
    _latest_log_file = os.path.join(_logs_dir, "latest_instance.log")
    
    _session_id = f"SES-{int(time.time())}"
    _instance_counter = 0
    _current_instance_id = 0
    _current_instance_file: Optional[str] = None
    _current_uri = ""
    _initialized = False
    _startup_buffer: List[str] = []

    @classmethod
    def get_logs_dir(cls) -> str:
        os.makedirs(cls._logs_dir, exist_ok=True)
        return cls._logs_dir

    @classmethod
    def get_master_log_path(cls) -> str:
        return cls._master_log_file

    @classmethod
    def get_current_instance_log_path(cls) -> str:
        with cls._lock:
            if cls._current_instance_file:
                return cls._current_instance_file
            cls.get_logs_dir()
            return os.path.join(cls._logs_dir, f"session_{cls._session_id}.log")

    @classmethod
    def _sanitize_filename(cls, name: str, max_len: int = 35) -> str:
        if not name:
            return "idle"
        base = os.path.splitext(os.path.basename(name))[0]
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', base)
        return clean[:max_len].strip('_') or "media"

    @classmethod
    def _write_raw(cls, text: str):
        with cls._lock:
            # 1. Always append to master consolidated log
            try:
                with open(cls._master_log_file, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            except Exception as e:
                sys.stderr.write(f"[DebugLogger Master Write Error]: {e}\n")

            # 2. Append to current instance-specific log file
            target_instance_file = cls._current_instance_file
            if target_instance_file:
                try:
                    with open(target_instance_file, "a", encoding="utf-8") as f:
                        f.write(text + "\n")
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except Exception:
                            pass
                except Exception as e:
                    sys.stderr.write(f"[DebugLogger Instance Write Error]: {e}\n")

                # Update latest_instance.log copy
                try:
                    shutil.copyfile(target_instance_file, cls._latest_log_file)
                except Exception:
                    pass
            else:
                cls._startup_buffer.append(text)

            # 3. Echo to console/stderr for live terminal monitoring
            sys.stderr.write(text + "\n")
            sys.stderr.flush()

    @classmethod
    def start_session(cls):
        if cls._initialized:
            return
        cls._initialized = True
        cls.get_logs_dir()

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        banner = (
            f"\n"
            f"################################################################################\n"
            f"# MEDIAPLAYER DEBUG SESSION STARTED: {now_str}\n"
            f"# Session ID: {cls._session_id} | PID: {os.getpid()} | Python: {sys.version.split()[0]}\n"
            f"# Individual Logs Directory: {cls._logs_dir}\n"
            f"# Master Consolidated Log:  {cls._master_log_file}\n"
            f"################################################################################\n"
        )
        cls._write_raw(banner)

    @classmethod
    def start_instance(cls, trigger: str, uri: str) -> int:
        cls.start_session()
        cls.get_logs_dir()

        with cls._lock:
            cls._instance_counter += 1
            inst_id = cls._instance_counter
            cls._current_instance_id = inst_id
            cls._current_uri = uri

            now = datetime.now()
            time_tag = now.strftime("%Y%m%d_%H%M%S")
            now_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            clean_name = cls._sanitize_filename(uri)

            instance_filename = f"instance_{inst_id:03d}_{time_tag}_{clean_name}.log"
            instance_filepath = os.path.join(cls._logs_dir, instance_filename)
            cls._current_instance_file = instance_filepath

        # Initialize instance log with session banner and any buffered pre-open logs
        header = (
            f"################################################################################\n"
            f"# MEDIAPLAYER INSTANCE LOG #{inst_id:03d}\n"
            f"# Session ID: {cls._session_id} | PID: {os.getpid()} | Created: {now_str}\n"
            f"# Trigger:    {trigger}\n"
            f"# URI:        {uri}\n"
            f"# File:       {instance_filename}\n"
            f"################################################################################\n"
        )

        with cls._lock:
            try:
                with open(instance_filepath, "w", encoding="utf-8") as f:
                    f.write(header + "\n")
                    if cls._startup_buffer:
                        f.write("# --- Pre-instance initialization logs ---\n")
                        for line in cls._startup_buffer[-20:]:  # include recent pre-open logs
                            f.write(line + "\n")
                        f.write("# ----------------------------------------\n\n")
                    f.flush()
            except Exception as e:
                sys.stderr.write(f"[DebugLogger Instance Init Error]: {e}\n")

            try:
                shutil.copyfile(instance_filepath, cls._latest_log_file)
            except Exception:
                pass

        divider = (
            f"\n"
            f"================================================================================\n"
            f">>> [INSTANCE #{inst_id:03d}] SEPARATE LOG FILE CREATED\n"
            f">>> LOG PATH: {instance_filepath}\n"
            f">>> TRIGGER:  {trigger}\n"
            f">>> URI:      {uri}\n"
            f"================================================================================"
        )
        cls._write_raw(divider)
        return inst_id

    @classmethod
    def log(cls, stage: str, message: str, **details):
        cls.start_session()
        now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        inst_str = f"INST #{cls._current_instance_id:03d}" if cls._current_instance_id > 0 else "GLOBAL"

        detail_lines = []
        for k, v in details.items():
            if isinstance(v, (dict, list)):
                try:
                    formatted_val = json.dumps(v, default=str, indent=2)
                    detail_lines.append(f"    {k} = {formatted_val}")
                except Exception:
                    detail_lines.append(f"    {k} = {v}")
            else:
                detail_lines.append(f"    {k} = {v}")

        detail_text = ("\n" + "\n".join(detail_lines)) if detail_lines else ""
        entry = f"[{now_str}] [{inst_str}] [{stage.upper()}] {message}{detail_text}"
        cls._write_raw(entry)

    @classmethod
    def log_mpv_state(cls, stage: str, player, note: str = ""):
        if not player:
            cls.log(stage, f"{note} (player is None)")
            return

        state = {}
        props = [
            "path", "time-pos", "vo-configured", "pause", "hwdec", "hwdec-current",
            "tone-mapping", "target-prim", "target-trc", "target-peak", "target-contrast",
            "hdr-compute-peak", "hdr-contrast-recovery", "gamut-mapping-mode",
            "colormatrix", "colormatrix-input-range", "colorlevels", "primaries",
            "gamma", "sig-peak", "vf", "glsl-shaders", "brightness", "contrast",
            "saturation", "gamma"
        ]
        for p in props:
            try:
                val = player[p]
                if val is not None:
                    state[p] = val
            except Exception:
                pass

        try:
            vp = player.video_params
            if isinstance(vp, dict):
                state["video-params"] = vp
        except Exception:
            pass

        try:
            tracks = player.track_list
            if tracks:
                v_tracks = [t for t in tracks if t.get("type") == "video"]
                state["video_tracks_summary"] = [
                    {
                        "id": t.get("id"),
                        "codec": t.get("codec"),
                        "dolby-vision-profile": t.get("dolby-vision-profile"),
                        "dolby-vision-level": t.get("dolby-vision-level"),
                        "demux-dolby-vision-profile": t.get("demux-dolby-vision-profile"),
                        "pixelformat": t.get("pixelformat"),
                        "ff-index": t.get("ff-index"),
                    }
                    for t in v_tracks
                ]
        except Exception:
            pass

        cls.log(stage, f"MPV Live State {f'({note})' if note else ''}", **state)

    @classmethod
    def log_tonemap_state(cls, stage: str, tonemap_engine, note: str = ""):
        if not tonemap_engine:
            cls.log(stage, f"{note} (tonemap_engine is None)")
            return

        state = {
            "current_preset": tonemap_engine.current_preset,
            "detected_source_hdr": getattr(tonemap_engine, "detected_source_hdr", None),
            "target_peak": getattr(tonemap_engine, "target_peak", None),
            "current_algorithm": getattr(tonemap_engine, "current_algorithm", None),
            "target_prim": getattr(tonemap_engine, "target_prim", None),
            "target_trc": getattr(tonemap_engine, "target_trc", None),
            "hdr_compute_peak": getattr(tonemap_engine, "hdr_compute_peak", None),
            "gamma": getattr(tonemap_engine, "gamma", None),
            "contrast": getattr(tonemap_engine, "contrast", None),
            "brightness": getattr(tonemap_engine, "brightness", None),
            "saturation": getattr(tonemap_engine, "saturation", None),
            "display_is_hdr": getattr(tonemap_engine, "display_is_hdr", None),
            "auto_conversion_summary": getattr(tonemap_engine, "auto_conversion_summary", None),
            "last_rpu_trims": getattr(tonemap_engine, "last_rpu_trims", None),
        }
        cls.log(stage, f"Tonemap Engine State {f'({note})' if note else ''}", **state)

    @classmethod
    def log_stereo_state(cls, stage: str, stereo3d_engine, note: str = ""):
        if not stereo3d_engine:
            cls.log(stage, f"{note} (stereo3d_engine is None)")
            return

        state = {
            "enabled": getattr(stereo3d_engine, "enabled", None),
            "input_format": getattr(stereo3d_engine, "input_format", None),
            "detected_input_format": getattr(stereo3d_engine, "detected_input_format", None),
            "output_mode": getattr(stereo3d_engine, "output_mode", None),
            "swap_eyes": getattr(stereo3d_engine, "swap_eyes", None),
            "is_dcp": getattr(stereo3d_engine, "is_dcp", None),
        }
        cls.log(stage, f"Stereo3D Engine State {f'({note})' if note else ''}", **state)

    @classmethod
    def sample_and_log_color(
        cls,
        player,
        time_pos: float,
        context: str = "",
        on_defect: Optional[Callable[[str, float], None]] = None,
    ):
        """
        Grab a background frame sample via mpv screenshot, compute BGR channel means,
        log render state, and notify on_defect callback if corruption (white, blue, green) is detected.
        """
        if not player or not getattr(player, "vo_configured", False):
            return
        if getattr(player, "seeking", False) or getattr(player, "_mpv_is_seeking", False):
            return

        def _worker():
            import numpy as np
            try:
                if not player or getattr(player, "seeking", False) or getattr(player, "_mpv_is_seeking", False):
                    return
                res = None
                try:
                    res = player.command("screenshot-raw")
                except Exception as raw_err:
                    cls.log("COLOR_SAMPLE_ERR", f"screenshot-raw failed: {raw_err}")
                    return

                if res and isinstance(res, dict) and "data" in res and "w" in res and "h" in res:
                    w = int(res["w"])
                    h = int(res["h"])
                    stride = int(res.get("stride", w * 4))
                    raw_data = res["data"]
                    arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((h, stride // 4, 4))[:, :w, :3]
                    center = arr[int(h*0.25):int(h*0.75), int(w*0.25):int(w*0.75)]
                    b_mean = float(center[:, :, 0].mean())
                    g_mean = float(center[:, :, 1].mean())
                    r_mean = float(center[:, :, 2].mean())
                    arr_min = float(arr.min())

                    is_protected_intro = (time_pos < 5.0)

                    # True hardware surface blowout: the entire viewport (including letterboxes) is blown white
                    is_white = (b_mean > 238.0 and g_mean > 238.0 and r_mean > 238.0 and arr_min > 220.0)
                    # Unshaped IPTPQc2 corruption: intense fluorescent radioactive green across raster
                    is_green = (g_mean > 85.0 and (g_mean / max(r_mean, 0.1)) > 7.0 and (g_mean / max(b_mean, 0.1)) > 1.8 and (r_mean + g_mean + b_mean) > 100.0)
                    is_blue = (b_mean > 80.0 and (b_mean / max(r_mean, 0.1)) > 3.0 and (b_mean / max(g_mean, 0.1)) > 2.0 and (r_mean + g_mean + b_mean) > 100.0)
                    is_red = (r_mean > 180.0 and (r_mean / max(b_mean, 0.1)) > 3.0 and (r_mean / max(g_mean, 0.1)) > 3.0)

                    if is_protected_intro:
                        status = "INTRO / LOGO (PROTECTED)"
                    elif is_white:
                        status = "DEFECT: SOLID WHITE"
                    elif is_blue:
                        status = "DEFECT: BLUE / PURPLE DOMINANCE"
                    elif is_green:
                        status = "DEFECT: FLUORESCENT GREEN"
                    elif is_red:
                        status = "DEFECT: RED DOMINANCE / BLOWOUT"
                    else:
                        status = "NORMAL COLOR"

                    cls.log(
                        "COLOR_SAMPLE",
                        f"Live Render Inspection [{context}] at PTS={time_pos:.2f}s -> {status}",
                        b_mean=round(b_mean, 2),
                        g_mean=round(g_mean, 2),
                        r_mean=round(r_mean, 2),
                        b_to_r_ratio=round(b_mean / max(r_mean, 0.01), 2),
                        status=status,
                        dimensions=f"{w}x{h}"
                    )

                    if "DEFECT:" in status and on_defect and not is_protected_intro:
                        try:
                            on_defect(status, time_pos)
                        except Exception as cb_err:
                            cls.log("COLOR_SAMPLE_ERR", f"on_defect callback error: {cb_err}")
            except Exception as e:
                cls.log("COLOR_SAMPLE_ERR", f"Failed to sample color: {e}")

        threading.Thread(target=_worker, daemon=True).start()
