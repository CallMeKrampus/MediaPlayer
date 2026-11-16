"""
BOOB Player - MPV Playback Engine
Embeds libmpv with gpu-next, hardware decoding, libplacebo tonemapping,
and frame-accurate synchronization for DCP, video, audio, and subtitle assets.
"""

import os
import sys
import time
import threading
from typing import Optional, Callable, Dict, Any, List

# Pre-load PyQt6 core & widgets to prevent DLL search path hijacking by third-party packages
import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets
try:
    import PyQt6.QtOpenGL
    import PyQt6.QtOpenGLWidgets
except Exception:
    pass

# Locate and configure libmpv DLL path before importing mpv
# Prioritize local project lib/ with latest full-featured libmpv build (source or frozen)
from core.app_paths import ensure_portable_environment, get_app_base_dir, get_lib_dir

ensure_portable_environment()

DLL_PATHS = [
    get_lib_dir(),
    get_app_base_dir(),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"),
    r"C:\Program Files\Topaz Labs LLC\Topaz Video",
    os.path.abspath("."),
]

mpv_loaded = False
for p in DLL_PATHS:
    dll_candidate = os.path.join(p, "mpv-2.dll")
    if not os.path.exists(dll_candidate):
        dll_candidate = os.path.join(p, "libmpv-2.dll")
    if os.path.exists(dll_candidate):
        os.environ["PATH"] = p + ";" + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(p)
            except Exception:
                pass
        mpv_loaded = True
        break

import mpv
# Monkeypatch mpv-version-tuple compatibility with getter and setter
mpv.MPV.mpv_version_tuple = property(
    lambda self: getattr(self, "_mpv_version_tuple", (0, 42, 0)),
    lambda self, v: setattr(self, "_mpv_version_tuple", v)
)

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication

from core.dcp_parser import DCPParser, DCPPackage, DCPReel, DCPComposition
from core.dcp_subtitle_engine import DCPSubtitleEngine
from core.tonemap_engine import TonemapEngine
from core.iab_engine import IABEngine, IABTrackMetadata, IABSpatialObject
from core.nvjpeg2k_engine import NVJPEG2KEngine, NVJPEG2KPlaybackController, is_gpu_jp2k_available
from core.stereo3d_engine import Stereo3DEngine
from core.shader_integrity import ShaderIntegrityMonitor
from core.frame_sampler import FrameSampler


class MPVSignalBridge(QObject):
    """Thread-safe signal bridge marshaling libmpv worker thread events to Qt Main Thread."""
    time_pos_signal = pyqtSignal(float)
    duration_signal = pyqtSignal(float)
    pause_signal = pyqtSignal(bool)
    track_list_signal = pyqtSignal(list)
    file_loaded_signal = pyqtSignal(str)
    playback_end_signal = pyqtSignal()
    cache_buffering_signal = pyqtSignal(bool)
    cache_duration_signal = pyqtSignal(float)
    iab_status_signal = pyqtSignal(object, str)
    tonemap_status_signal = pyqtSignal(dict)
    nv_frame_ready = pyqtSignal(object, int, float)
    nv_active_signal = pyqtSignal(bool)
    nv_fps_signal = pyqtSignal(float)
    anamorphic_unsqueeze_signal = pyqtSignal(bool)
    eof_signal = pyqtSignal(int)
    defect_detected_signal = pyqtSignal(str, float)
    shader_miscompile_signal = pyqtSignal(dict)


class MPVEngine:
    # Renderer used once the Direct3D 11 shader compiler is found to be corrupting
    # constants. "win" (WGL) is named explicitly: with gpu-context=auto libmpv
    # picks ANGLE, which crashes in the bundled build.
    GPU_FALLBACK_OPTS = {"gpu_api": "opengl", "gpu_context": "win"}

    def __init__(self, wid: Optional[int] = None):
        self.wid = wid
        self.bridge = MPVSignalBridge()
        self.player: Optional[mpv.MPV] = None
        self.tonemap_engine: Optional[TonemapEngine] = None
        
        # State tracking
        self.is_paused: bool = False
        self.current_uri: str = ""
        self.current_dcp: Optional[DCPPackage] = None
        self.current_reel_index: int = 0
        self.active_cpl: Optional[DCPComposition] = None
        self.is_dcp_playing: bool = False

        # Multi-Reel DCP Timeline & Subtitle Engine
        self.dcp_sub_engine = DCPSubtitleEngine()
        self.dcp_reel_offsets: List[float] = []
        self.dcp_reel_durations: List[float] = []
        self.dcp_total_duration: float = 0.0
        self._is_transitioning_reel: bool = False
        self._mpv_eof_armed: bool = False
        self._reel_transition_ts: float = 0.0
        self._current_reel_has_audio: bool = False
        self._last_applied_af: Optional[str] = None
        self._sound_channel_cache: Dict[str, int] = {}
        self._mpv_is_seeking: bool = False
        self._pending_seek_pts: Optional[float] = None
        self._pending_seek_until: float = 0.0

        # Immersive Audio Bitstream (IAB / SMPTE ST 2098-2) & IMAX Flags
        self.current_iab_meta: Optional[IABTrackMetadata] = None
        self.dcp_decode_level: int = 0  # Default: Native 4K Master hardware playback
        self.current_iab_mode: str = "binaural"
        self.current_imax_audio_format: str = ""
        self.current_sound_channels: int = 6
        self.is_anamorphic_143: bool = False
        self.aspect_ratio_override: Optional[str] = None

        # Playback speed & Pitch preservation
        self.playback_speed: float = 1.0

        # Subtitle state tracking
        self.subtitles_user_disabled: bool = False
        self._subtitles_initial_auto_selected: bool = False

        # A-B Repeat Looping
        self.ab_point_a: Optional[float] = None
        self.ab_point_b: Optional[float] = None
        self._last_ab_loop_time: float = 0.0

        # NVIDIA nvJPEG2000 & Grok OpenCL GPU Acceleration Engine & Playback Controller
        self.nvjpeg2k_engine = NVJPEG2KEngine.get_instance()
        self.nv_controller: Optional[NVJPEG2KPlaybackController] = None
        self.nvjpeg2k_active: bool = False

        if is_gpu_jp2k_available():
            self.nv_controller = NVJPEG2KPlaybackController()
            def _on_nv_frame(img, idx, pts):
                if self.is_dcp_playing and self.active_cpl and self.current_reel_index < len(self.dcp_reel_offsets):
                    global_pts = self.dcp_reel_offsets[self.current_reel_index] + pts
                else:
                    global_pts = pts
                self._safe_emit("nv_frame_ready", img, idx, global_pts)
                if not self.is_dcp_playing or not self._current_reel_has_audio:
                    self._safe_emit("time_pos_signal", global_pts)
                    if self.on_time_pos:
                        self.on_time_pos(global_pts)

            self.nv_controller.frame_ready.connect(_on_nv_frame)
            self.nv_controller.fps_updated.connect(
                lambda fps: self._safe_emit("nv_fps_signal", fps)
            )
            self.nv_controller.playback_ended.connect(
                lambda: self._handle_eof(self.current_reel_index)
            )

        self.bridge.eof_signal.connect(self._handle_eof)

        # Shader constant integrity monitor: detects libplacebo shaders that libmpv
        # miscompiled (corrupted float constants) and rebuilds the video output.
        self.shader_monitor = ShaderIntegrityMonitor(self._on_shader_miscompile)
        self._shader_heal_pending: bool = False
        # True once the renderer was moved off Direct3D 11 (sticky for the process)
        self.gpu_fallback_active: bool = False
        # Video stays blanked from loadfile until its shaders are verified
        self._video_concealed: bool = False
        self._conceal_started: float = 0.0
        self._conceal_first_frame_time: Optional[float] = None
        self._conceal_reveal_at: Optional[float] = None
        self.bridge.shader_miscompile_signal.connect(self._handle_shader_miscompile)

        # Callbacks
        self.on_time_pos: Optional[Callable[[float], None]] = None
        self.on_duration: Optional[Callable[[float], None]] = None
        self.on_pause_change: Optional[Callable[[bool], None]] = None
        self.on_track_list_change: Optional[Callable[[List[dict]], None]] = None
        self.on_file_loaded: Optional[Callable[[str], None]] = None
        self.on_playback_end: Optional[Callable[[], None]] = None
        self.on_iab_status: Optional[Callable[[Optional[IABTrackMetadata], str], None]] = None
        self.on_tonemap_status: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_cache_buffering: Optional[Callable[[bool], None]] = None
        self.on_cache_duration: Optional[Callable[[float], None]] = None
        self.on_defect_detected: Optional[Callable[[str, float], None]] = None

        self._init_mpv()
        if self.tonemap_engine:
            self.tonemap_engine.on_adjustments_change = self._on_color_adjustments_change
            self.tonemap_engine.on_preset_change = self._on_tonemap_preset_change

    def _on_tonemap_preset_change(self, status: Dict[str, Any]):
        if self.nvjpeg2k_active and self.nv_controller:
            try:
                redecode = not getattr(self, "_is_transitioning_reel", False)
                self.nv_controller.apply_tonemap_status(status, redecode_now=redecode)
            except Exception as e:
                print(f"[MPVEngine] Error applying tonemap to nv_controller: {e}")
        elif self.player and not getattr(self, "gpu_fallback_active", False):
            # A colour pipeline change recompiles shaders; watch that compile for corruption too
            self._shader_watch_on()
            if getattr(self, "is_paused", False):
                # For standard mpv playback when paused, trigger immediate repaint so tonemap shifts instantly
                try:
                    self.player.command("seek", 0, "relative", "exact")
                except Exception:
                    pass
        elif self.player and getattr(self, "is_paused", False):
            # (OpenGL fallback active) repaint so tonemap shifts instantly
            try:
                self.player.command("seek", 0, "relative", "exact")
            except Exception:
                pass

        self._safe_emit("tonemap_status_signal", status)
        if self.on_tonemap_status:
            try:
                self.on_tonemap_status(status)
            except Exception:
                pass

    def redetect_color_pipeline(self):
        """Re-run HDR auto-detection for the current file (used when the user picks 'Auto Detect')."""
        if not self.player or not self.tonemap_engine:
            return
        try:
            vp = self.player.video_params
        except Exception:
            vp = None
        try:
            tracks = self.player.track_list
        except Exception:
            tracks = None
        probe_track = getattr(self, "cached_probe_v_track", None)
        if tracks:
            self._auto_detect_and_apply_hdr(probe_track=probe_track, mpv_tracks=tracks)
        if vp:
            self._auto_detect_and_apply_hdr(probe_track=probe_track, mpv_video_params=vp)

    def _auto_detect_and_apply_hdr(
        self,
        probe_track: Optional[dict] = None,
        mpv_tracks: Optional[list] = None,
        mpv_video_params: Optional[dict] = None,
    ):
        """Auto-detect HDR / HDR10 / HDR10+ / HLG / DV P20 / DV P5 and adapt to display dynamic range."""
        if self.is_dcp_playing or getattr(self, "nvjpeg2k_active", False) or not self.tonemap_engine:
            return

        if probe_track is None:
            probe_track = getattr(self, "cached_probe_v_track", None)
        if mpv_tracks is None and getattr(self, "player", None):
            try:
                mpv_tracks = self.player.track_list
            except Exception:
                pass

        detected = TonemapEngine.detect_source_hdr_format(
            probe_video_track=probe_track,
            mpv_tracks=mpv_tracks,
            mpv_video_params=mpv_video_params,
            uri=self.current_uri,
        )

        curr_preset = self.tonemap_engine.current_preset
        is_auto_mode = (
            curr_preset == "auto"
            or bool(getattr(self.tonemap_engine, "auto_conversion_summary", None))
        )
        curr_src = getattr(self.tonemap_engine, "detected_source_hdr", "SDR")
        if curr_src in ("Dolby Vision P20", "Dolby Vision P5") and detected not in ("Dolby Vision P20", "Dolby Vision P5"):
            should_apply = False
        else:
            should_apply = (
                curr_preset == "auto"
                or (detected in ("Dolby Vision P20", "Dolby Vision P5") and curr_src != detected)
                or (detected == "HDR10+" and curr_src not in ("HDR10+", "Dolby Vision P5", "Dolby Vision P20"))
                or (detected in ("HDR10", "HLG") and curr_src in ("HDR", "SDR"))
            )


        if detected in ("SDR", "DCI-XYZ"):
            return

        if not is_auto_mode or curr_preset == "passthrough":
            return

        if should_apply:
            self.tonemap_engine.auto_configure_for_source(detected)

    def _on_color_adjustments_change(self, brightness: int, contrast: int, saturation: int, gamma: int, hue: int):
        if self.nvjpeg2k_active and self.nv_controller:
            self.nv_controller.set_grading(
                brightness=float(brightness),
                contrast=float(contrast),
                gamma=float(gamma),
                saturation=float(saturation),
            )
        elif self.player and getattr(self, "is_paused", False):
            try:
                self.player.command("seek", 0, "relative", "exact")
            except Exception:
                pass

    def _safe_emit(self, sig_name: str, *args):
        """Safely emit Qt signals across threads guarding against garbage collection during shutdown."""
        try:
            bridge = getattr(self, "bridge", None)
            if bridge is not None:
                sig = getattr(bridge, sig_name, None)
                if sig is not None:
                    sig.emit(*args)
        except (RuntimeError, AttributeError):
            pass

    def ensure_decoders_ready(self, timeout: float = 2.0) -> bool:
        """
        Verify that libmpv, hardware/software decoders, and the video output pipeline (vo=gpu-next)
        are properly initialized, responsive, and ready before accepting media load commands.
        """
        app = QApplication.instance()
        if app:
            try:
                app.processEvents()
            except Exception:
                pass

        if not self.player:
            self._init_mpv()

        start_t = time.time()
        while time.time() - start_t < timeout:
            try:
                vo_val = getattr(self.player, "vo", None)
                hwdec_val = getattr(self.player, "hwdec", None)
                if vo_val is not None:
                    try:
                        if (isinstance(hwdec_val, list) and "auto-safe" not in hwdec_val) or (isinstance(hwdec_val, str) and hwdec_val != "auto-safe"):
                            self.player["hwdec"] = "auto-safe"
                    except Exception:
                        pass
                    return True
            except Exception as e:
                pass
            if app:
                try:
                    app.processEvents()
                except Exception:
                    pass
            time.sleep(0.05)

        self.reinit_player()
        return bool(self.player is not None)

    def reinit_player(self):
        """Cleanly tear down and reinitialize the underlying libmpv instance and pipelines."""
        if self.player:
            try:
                self.player.command("stop")
            except Exception:
                pass
            try:
                self.player.terminate()
            except Exception:
                pass
            self.player = None

        self.shader_monitor.reset()
        self._init_mpv()
        if self.tonemap_engine:
            self.tonemap_engine.on_adjustments_change = self._on_color_adjustments_change
            self.tonemap_engine.on_preset_change = self._on_tonemap_preset_change

    # Shader compiles must have been idle this long before the picture is shown
    CONCEAL_QUIET_SECS = 0.15
    # Time given to the OpenGL output to come up after a fallback switch
    CONCEAL_FALLBACK_SETTLE_SECS = 0.5
    # Never keep the picture blanked longer than this
    CONCEAL_MAX_SECS = 3.0
    CONCEAL_OVERLAY_ID = 57
    CONCEAL_OVERLAY_ASS = r"{\an7\pos(0,0)\bord0\shad0\1c&H000000&\1a&H00&\p1}m 0 0 l 4000 0 4000 4000 0 4000{\p0}"

    def _begin_video_conceal(self):
        """
        Blank the video surface while a newly opened file compiles its shaders on
        Direct3D 11, so a miscompiled (wrong colour) picture is never shown. The
        surface is revealed once the compiles finish clean, or once the OpenGL
        fallback has taken over.
        """
        if not self.SHADER_WATCH_ENABLED or getattr(self, "gpu_fallback_active", True) or not self.player:
            return
        if not self._set_video_cover(True):
            return
        self._shader_watch_on(hold=1.0)
        self._video_concealed = True
        self._conceal_started = time.monotonic()
        self._conceal_first_frame_time = None
        self._conceal_reveal_at = None
        QTimer.singleShot(40, self._poll_video_conceal)

    def _end_video_conceal(self):
        if getattr(self, "_video_concealed", False):
            self._video_concealed = False
            self._set_video_cover(False)

    def _set_video_cover(self, enabled: bool) -> bool:
        """
        Draw (or remove) an opaque black rectangle over the whole picture as an mpv
        OSD overlay. It lives inside the renderer, so there is no window flicker,
        shaders keep compiling underneath, and it survives a video output rebuild.
        """
        if not self.player:
            return False
        try:
            self.player.command(
                "osd-overlay",
                id=self.CONCEAL_OVERLAY_ID,
                format="ass-events" if enabled else "none",
                data=self.CONCEAL_OVERLAY_ASS if enabled else "",
                res_x=1280,
                res_y=720,
                z=1000,
            )
            return True
        except Exception as e:
            return False

    def _poll_video_conceal(self):
        if not self._video_concealed:
            return
        now = time.monotonic()
        reveal = False
        if now - self._conceal_started >= self.CONCEAL_MAX_SECS:
            reveal = True
        elif self._shader_heal_pending:
            pass  # switching renderer; wait for it
        elif self._conceal_reveal_at is not None:
            reveal = now >= self._conceal_reveal_at
        elif self._conceal_first_frame_time is not None:
            reveal = (
                now - self._conceal_first_frame_time >= self.CONCEAL_QUIET_SECS
                and self.shader_monitor.is_quiet(self.CONCEAL_QUIET_SECS)
            )
        if reveal:
            self._end_video_conceal()
        else:
            QTimer.singleShot(40, self._poll_video_conceal)

    # --- Shader watch window -------------------------------------------------------------
    # libplacebo's shader dumps are only needed while shaders are being compiled (a file
    # opens, or the colour pipeline changes). Debug logging stays off the rest of the time,
    # because mpv formatting and delivering it to Python slowed content switching 3-6x.
    # Master switch for libmpv log access (shader miscompile detection, the OpenGL fallback
    # and the black overlay at file open). OFF: any libmpv log hook, even a windowed one,
    # made switching content freeze the UI for seconds, so mpv is created without one.
    SHADER_WATCH_ENABLED = False
    SHADER_WATCH_MSG_LEVEL = "all=no,vo/gpu-next/libplacebo=debug"
    SHADER_WATCH_MIN_SECS = 2.5

    def _shader_watch_on(self, hold: Optional[float] = None):
        """Start (or extend) the window in which libplacebo shader dumps are delivered."""
        # On the OpenGL fallback there is nothing left to detect (no GLSL -> SPIR-V step)
        if not self.SHADER_WATCH_ENABLED or not self.player or getattr(self, "gpu_fallback_active", False):
            return
        until = time.monotonic() + (hold if hold is not None else self.SHADER_WATCH_MIN_SECS)
        self._shader_watch_until = max(getattr(self, "_shader_watch_until", 0.0), until)
        if getattr(self, "_shader_watch_active", False):
            return
        try:
            self.player["msg-level"] = self.SHADER_WATCH_MSG_LEVEL
            self.player.set_loglevel("debug")
        except Exception:
            return
        self._shader_watch_active = True
        QTimer.singleShot(250, self._shader_watch_tick)

    def _shader_watch_tick(self):
        if not getattr(self, "_shader_watch_active", False):
            return
        if getattr(self, "gpu_fallback_active", False):
            self._shader_watch_off()
            return
        if (
            time.monotonic() >= self._shader_watch_until
            and not self._video_concealed
            and self.shader_monitor.is_quiet(0.4)
        ):
            self._shader_watch_off()
        else:
            QTimer.singleShot(250, self._shader_watch_tick)

    def _shader_watch_off(self):
        self._shader_watch_active = False
        if not self.player:
            return
        try:
            self.player.set_loglevel("no")
            self.player["msg-level"] = "all=no"
        except Exception:
            pass

    def _on_mpv_log(self, level: str, prefix: str, text: str):
        """libmpv log callback (mpv event thread). Must stay cheap."""
        monitor = getattr(self, "shader_monitor", None)
        if monitor is not None:
            monitor.feed(level, prefix, text)

    def _on_shader_miscompile(self, info: Dict[str, Any]):
        """Called on the mpv event thread; marshal to the Qt main thread."""
        self._safe_emit("shader_miscompile_signal", dict(info))

    def _handle_shader_miscompile(self, info: Dict[str, Any]):
        """
        libmpv compiled a libplacebo shader with a corrupted float constant
        (see core/shader_integrity.py). Compiled shaders are cached for the life
        of the video output, so the picture stays wrong (flat purple / red /
        green / white) for the whole session.

        Recompiling on Direct3D 11 does not help: once a process produces a
        corrupted constant it produces the same one on every recompile. The
        defect lives in the GLSL -> SPIR-V compiler that the D3D11 (and Vulkan)
        backends depend on, so the renderer is moved to OpenGL, where libplacebo
        hands its GLSL straight to the GPU driver.
        """
        if self._shader_heal_pending or self.gpu_fallback_active or not self.player:
            return
        if info.get("generation") != self.shader_monitor.generation:
            return  # report about a video output that was already rebuilt
        self._shader_heal_pending = True
        # Let the current burst of shader compiles finish before tearing down
        QTimer.singleShot(250, self._activate_gpu_fallback)

    def _activate_gpu_fallback(self):
        """Rebuild the gpu-next video output on OpenGL (WGL) for the rest of this process."""
        try:
            if not self.player:
                return
            self.shader_monitor.reset()
            self._shader_watch_off()
            was_paused = bool(getattr(self.player, "pause", False))
            hdr_output_was_active = bool(getattr(self.tonemap_engine, "display_is_hdr", False))

            self.player["vo"] = "null"
            for key, value in self.GPU_FALLBACK_OPTS.items():
                self.player[key.replace("_", "-")] = value
            self.player["vo"] = "gpu-next"
            self.gpu_fallback_active = True

            # A WGL swapchain is SDR-only: stop offering HDR output and, if an
            # HDR-display pipeline was active, reconfigure it for SDR output.
            TonemapEngine.sdr_output_only = True
            if hdr_output_was_active and self.tonemap_engine:
                try:
                    self.player["target-colorspace-hint"] = "no"
                    if self.tonemap_engine.auto_conversion_summary:
                        self.tonemap_engine.auto_configure_for_source(self.tonemap_engine.detected_source_hdr)
                    else:
                        self.tonemap_engine.apply_preset(self.tonemap_engine.current_preset)
                except Exception as e:
                    pass

            if was_paused:
                try:
                    self.player.command("seek", 0, "relative", "exact")
                except Exception:
                    pass
        except Exception as e:
            pass
        finally:
            self._shader_heal_pending = False
            if self._video_concealed:
                self._conceal_reveal_at = time.monotonic() + self.CONCEAL_FALLBACK_SETTLE_SECS

    def _trigger_defect_check(self, pts: Optional[float] = None, context: str = ""):
        """Trigger an automated background render inspection for visual defects."""
        if not self.player or getattr(self, "is_dcp_playing", False) or getattr(self, "nvjpeg2k_active", False):
            return
        if getattr(self, "_mpv_is_seeking", False) or getattr(self.player, "seeking", False):
            return
        if time.time() - getattr(self, "_last_seek_end_time", 0.0) < 1.2:
            return
        curr_pts = pts if pts is not None else float(getattr(self.player, "time_pos", 0.0) or 0.0)
        if curr_pts < 5.0:
            return

        def _on_defect_found(defect_type: str, defect_pts: float):
            self._safe_emit("defect_detected_signal", defect_type, defect_pts)
            if self.on_defect_detected:
                try:
                    self.on_defect_detected(defect_type, defect_pts)
                except Exception as ex:
                    print(f"[MPVEngine] Error in on_defect_detected callback: {ex}")

        FrameSampler.sample(self.player, curr_pts, on_defect=_on_defect_found)

    def _init_mpv(self):
        opts = {
            "vo": "gpu-next",
            "hwdec": "auto-safe",
            "keep_open": True,
            "force_window": "immediate",
            "background": "color",
            "background_color": "#FF000000",
            "tone_mapping": "clip",
            "hdr_compute_peak": False,
            "target_trc": "gamma2.2",
            "target_prim": "bt.709",
            "target_contrast": "inf",
            "volume": 85,
            "video_sync": "audio",
            "framedrop": "vo",
            "vd_lavc_threads": 8,
            "vd_lavc_fast": False,

            # --- Studio Reference Scalers & Presentation ---
            "scale": "spline36",
            "cscale": "spline36",
            "dscale": "mitchell",
            "correct_downscaling": True,
            "linear_downscaling": True,
            "sigmoid_upscaling": True,
            "hidpi_window_scale": True,

            # --- High Performance Memory Buffering & Deep Cache ---
            "demuxer_max_bytes": 1024 * 1024 * 1024,      # 1 GiB Forward RAM Buffer
            "demuxer_max_back_bytes": 512 * 1024 * 1024,  # 512 MiB Rewind Backbuffer
            "demuxer_readahead_secs": 15.0,              # Actively buffer 15s ahead
            "cache": "yes",                              # Force stream/file caching
            "cache_secs": 30.0,                          # Buffer up to 30s
            "cache_pause": False,                        # NEVER freeze playback on local media
            "cache_pause_wait": 0.0,                     # Zero pause wait
            "demuxer_hysteresis_secs": 1.0,              # Prevent buffer underrun jitter

            # --- High Resolution & Instant Seeking ---
            "hr_seek": "yes",                            # Frame-accurate seek
            "hr_seek_framedrop": True,                   # Responsive framedropping during seeks

            # --- Crisp, High-Contrast Subtitle Rendering & Language Auto-Selection ---
            "sub_visibility": True,                      # Subtitles always visible when track selected
            "sub_auto": "fuzzy",                         # Auto-load matching external subtitle files
            "slang": "en,eng,enUS,en-US,hin,hi",         # Default subtitle language priority
            "sub_font": "sans-serif",
            "sub_font_size": 44,
            "sub_border_size": 2.5,
            "sub_color": "#FFFFFF",
            "sub_border_color": "#000000",
            "sub_pos": 95,
            "blend_subtitles": "no",                     # Never dim subtitles through video tonemapping

            # --- Pristine Lossless Uncompressed Screenshots ---
            "screenshot_format": "png",
            "screenshot_png_compression": 0,             # 0 = Completely uncompressed raw deflate (lossless)
            "screenshot_png_filter": 0,
            "screenshot_tag_colorspace": True,           # Embed accurate sRGB/Rec.709 color metadata
            "screenshot_high_bit_depth": True,
        }
        if self.wid is not None:
            opts["wid"] = str(int(self.wid))
        if getattr(self, "gpu_fallback_active", False):
            opts.update(self.GPU_FALLBACK_OPTS)

        # The log hook feeds ShaderIntegrityMonitor. It starts silent; _shader_watch_on()
        # raises it to libplacebo-only debug output while shaders are compiling.
        self._shader_watch_active = False
        self._shader_watch_until = 0.0
        if self.SHADER_WATCH_ENABLED:
            opts["msg_level"] = "all=no"
            self.player = mpv.MPV(log_handler=self._on_mpv_log, loglevel="no", **opts)
        else:
            self.player = mpv.MPV(**opts)
        self.tonemap_engine = TonemapEngine(self.player)
        self.stereo3d_engine = Stereo3DEngine(self.player)

        # First frame of a newly loaded (or re-synced) file has reached the output
        @self.player.event_callback("playback-restart")
        def _playback_restart(_event):
            if self._video_concealed and self._conceal_first_frame_time is None:
                self._conceal_first_frame_time = time.monotonic()

        # Register mpv property observers
        @self.player.property_observer("seeking")
        def _seeking_observer(_name, val):
            was_seeking = getattr(self, "_mpv_is_seeking", False)
            self._mpv_is_seeking = bool(val)
            if self._mpv_is_seeking:
                self._last_seek_start_time = time.time()
            if was_seeking and not self._mpv_is_seeking:
                self._last_seek_end_time = time.time()
                QTimer.singleShot(1400, lambda: self._trigger_defect_check(context="POST_SEEK"))

        @self.player.property_observer("time-pos")
        def _time_observer(_name, val):
            if val is None:
                return
            if self.is_dcp_playing and getattr(self, "_is_transitioning_reel", False):
                return

            fval = float(val)
            if self.is_dcp_playing and self.active_cpl:
                r_off = self.dcp_reel_offsets[self.current_reel_index] if self.current_reel_index < len(self.dcp_reel_offsets) else 0.0
                emitted_pts = r_off + fval
            else:
                emitted_pts = fval

            # Ignore stale pre-seek mpv timestamps while mpv demuxer seeks to new target
            if self._pending_seek_pts is not None:
                now = time.perf_counter()
                if abs(emitted_pts - self._pending_seek_pts) <= 1.5 and not self._mpv_is_seeking:
                    self._pending_seek_pts = None
                    self._pending_seek_until = 0.0
                elif self._mpv_is_seeking or now < self._pending_seek_until:
                    return
                else:
                    self._pending_seek_pts = None
                    self._pending_seek_until = 0.0
            elif self._mpv_is_seeking:
                return

            self._mpv_eof_armed = True

            # A-B Repeat loop auto-seek
            if (
                self.ab_point_a is not None
                and self.ab_point_b is not None
                and self.ab_point_b > self.ab_point_a
            ):
                if emitted_pts >= self.ab_point_b:
                    now = time.perf_counter()
                    if now - self._last_ab_loop_time > 0.3:
                        self._last_ab_loop_time = now
                        self.seek(self.ab_point_a)
                        return

            self._safe_emit("time_pos_signal", emitted_pts)
            if self.on_time_pos:
                self.on_time_pos(emitted_pts)
            if self.nvjpeg2k_active and self.nv_controller:
                self.nv_controller.sync_audio_clock(fval)
            if getattr(self, "tonemap_engine", None):
                self.tonemap_engine.current_pts = emitted_pts
                if self.tonemap_engine.current_preset in ("dv_p20_rpu_sdr", "dv_p20_rpu_hdr"):
                    self.tonemap_engine.update_dynamic_rpu_async(self.current_uri, emitted_pts)

            # Automated color verification checks at key playback checkpoints & periodic watchdog
            if not getattr(self, "is_dcp_playing", False) and not getattr(self, "nvjpeg2k_active", False):
                if not hasattr(self, "_logged_color_checkpoints"):
                    self._logged_color_checkpoints = set()
                int_sec = int(emitted_pts)
                if int_sec not in self._logged_color_checkpoints:
                    if int_sec in (1, 2, 5, 10, 20, 30) or (int_sec > 0 and int_sec % 15 == 0):
                        self._logged_color_checkpoints.add(int_sec)
                        self._trigger_defect_check(emitted_pts, context=f"PTS_{int_sec}s")

        @self.player.property_observer("duration")
        def _dur_observer(_name, val):
            if val is not None:
                if self.is_dcp_playing and self.active_cpl and self.dcp_total_duration > 0:
                    dur_val = self.dcp_total_duration
                else:
                    dur_val = float(val)
                self._safe_emit("duration_signal", dur_val)
                if self.on_duration:
                    self.on_duration(dur_val)

        @self.player.property_observer("pause")
        def _pause_observer(_name, val):
            self.is_paused = bool(val)
            self._safe_emit("pause_signal", self.is_paused)
            if self.on_pause_change:
                self.on_pause_change(self.is_paused)
            if self.is_paused:
                QTimer.singleShot(1200, lambda: self._trigger_defect_check(context="PAUSED_FRAME"))

        @self.player.property_observer("track-list")
        def _track_observer(_name, val):
            if val is not None:
                tracks = self._augment_dcp_video_track(list(val))
                v_tracks = [t for t in tracks if t.get("type") == "video"]
                self._safe_emit("track_list_signal", tracks)
                if self.on_track_list_change:
                    self.on_track_list_change(tracks)

                # Auto-detect Dolby Vision / HDR / HDR10 / HDR10+ / HLG from tracks
                self._auto_detect_and_apply_hdr(mpv_tracks=tracks)

                if self.stereo3d_engine and not self.is_dcp_playing:
                    self.stereo3d_engine.configure_for_media(self.current_uri, is_dcp=False, mpv_tracks=tracks)

                # Auto-select best subtitle track once upon initial media load if subtitles exist and user hasn't disabled them
                sub_tracks = [t for t in tracks if t.get("type") == "sub"]
                if sub_tracks and self.player and not self._subtitles_initial_auto_selected and not self.subtitles_user_disabled:
                    self._subtitles_initial_auto_selected = True
                    any_sub_selected = any(bool(t.get("selected")) for t in sub_tracks)
                    current_sid = getattr(self.player, "sid", None)
                    if not any_sub_selected or current_sid in ("no", None, False):
                        pref_id = None
                        for st in sub_tracks:
                            lang = (st.get("lang") or "").lower()
                            if lang in ("en", "eng", "enus", "en-us"):
                                pref_id = st.get("id")
                                break
                        if pref_id is None:
                            pref_id = sub_tracks[0].get("id")
                        if pref_id is not None:
                            try:
                                self.player["sid"] = pref_id
                                self.player["sub-visibility"] = True
                            except Exception:
                                pass

        @self.player.property_observer("video-params")
        def _video_params_observer(_name, val):
            if isinstance(val, dict) and val:
                self._auto_detect_and_apply_hdr(mpv_video_params=val)

        @self.player.property_observer("paused-for-cache")
        def _cache_pause_observer(_name, val):
            if val is not None:
                bval = bool(val)
                self._safe_emit("cache_buffering_signal", bval)
                if self.on_cache_buffering:
                    self.on_cache_buffering(bval)

        @self.player.property_observer("demuxer-cache-duration")
        def _cache_dur_observer(_name, val):
            if val is not None:
                fval = float(val)
                self._safe_emit("cache_duration_signal", fval)
                if self.on_cache_duration:
                    self.on_cache_duration(fval)

        @self.player.property_observer("eof-reached")
        def _eof_observer(_name, val):
            if val is True:
                if self.is_dcp_playing and self.nvjpeg2k_active and self.nv_controller is not None and self.nv_controller.is_playing:
                    # Wait for NVJPEG2K presentation clock to display the final frame & match WASAPI drain
                    return
                if not self.is_dcp_playing or self._mpv_eof_armed:
                    self._safe_emit("eof_signal", self.current_reel_index)

    def _handle_eof(self, source_reel_idx: Optional[int] = None):
        if getattr(self, "_is_transitioning_reel", False):
            return
        if self.is_dcp_playing and self.active_cpl:
            if source_reel_idx is not None and source_reel_idx != self.current_reel_index:
                return
            if (time.perf_counter() - getattr(self, "_reel_transition_ts", 0.0)) < 0.25:
                return
            # Advance to next reel if available
            next_reel_idx = self.current_reel_index + 1
            if next_reel_idx < len(self.active_cpl.reels):
                self._mpv_eof_armed = False
                self._reel_transition_ts = time.perf_counter()
                self.play_dcp_reel(next_reel_idx, start_pos=0.0)
                return

        self._safe_emit("playback_end_signal")
        if self.on_playback_end:
            self.on_playback_end()

    def reset_playback_state(self):
        """
        Discard and flush all contents, tracks, external audio/subtitle files,
        custom filters, delays, and state from the previous file before loading new media.
        """
        self._logged_color_checkpoints = set()
        self._end_video_conceal()
        # 1. Stop NVJPEG2000 controller if running and clear active flag
        if self.nv_controller:
            try:
                self.nv_controller.set_next_reel("", "")
                self.nv_controller.stop()
            except Exception:
                pass
        self._last_applied_af = None
        self.nvjpeg2k_active = False
        self._safe_emit("nv_active_signal", False)

        # 2. Reset DCP package & composition state
        self.is_dcp_playing = False
        self.current_dcp = None
        self.active_cpl = None
        self.current_reel_index = 0
        self.dcp_reel_offsets = []
        self.dcp_reel_durations = []
        self.dcp_total_duration = 0.0
        self._is_transitioning_reel = False
        self._mpv_eof_armed = False
        self._reel_transition_ts = 0.0
        self._current_reel_has_audio = False
        self._mpv_is_seeking = False
        self._pending_seek_pts = None
        self._pending_seek_until = 0.0
        if hasattr(self, "dcp_sub_engine"):
            self.dcp_sub_engine.cues.clear()
            self.dcp_sub_engine._start_times.clear()
            self.dcp_sub_engine.reel_cues.clear()
            self.dcp_sub_engine.reel_srt_paths.clear()
            self.dcp_sub_engine.srt_path = None

        # 3. Discard IAB metadata, spatial objects & IMAX overrides
        self.current_iab_meta = None
        self.current_imax_audio_format = ""
        self.current_sound_channels = 6
        self.is_anamorphic_143 = False
        self.aspect_ratio_override = None
        self._safe_emit("anamorphic_unsqueeze_signal", False)
        self._safe_emit("iab_status_signal", None, self.current_iab_mode)
        if self.on_iab_status:
            try:
                self.on_iab_status(None, self.current_iab_mode)
            except Exception:
                pass

        # 4. Flush mpv internal external file lists, filters, track selections, delays, and aspect ratio
        if self.player:
            try:
                self.player["audio-files"] = []
            except Exception:
                pass
            try:
                self.player["sub-files"] = []
            except Exception:
                pass
            try:
                self.player["af"] = ""
            except Exception:
                pass
            try:
                self.player["vf"] = ""
            except Exception:
                pass
            try:
                self.player["vid"] = "auto"
                self.player["aid"] = "auto"
                self.player["sid"] = "auto"
            except Exception:
                pass
            try:
                self.player["audio-delay"] = 0.0
                self.player["sub-delay"] = 0.0
                self.player["start"] = "none"
            except Exception:
                pass
            try:
                self.player["video-aspect-override"] = "-1"
            except Exception:
                pass
            try:
                self.player["container-fps-override"] = 0.0
            except Exception:
                pass
            try:
                self.player.container_fps_override = None
            except Exception:
                pass

        # 5. Flush track lists to clear all track entries in UI selectors and menus
        self._safe_emit("track_list_signal", [])
        if self.on_track_list_change:
            try:
                self.on_track_list_change([])
            except Exception:
                pass

        # 6. Reset color pipeline preset to auto so new file detection operates cleanly
        #    (a manual preset such as passthrough applies to the current file only, so an
        #    HDR file opened later is never left un-tonemapped and dim on an SDR display).
        if getattr(self, "tonemap_engine", None):
            try:
                self.tonemap_engine.apply_preset("auto")
            except Exception:
                pass

        # 7. Reset subtitle auto-selection state for new media
        self._subtitles_initial_auto_selected = False
        self.subtitles_user_disabled = False

    # Playback Controls
    def play(self, uri: str, start_pos: Optional[float] = None):
        # 0. Ensure decoders and video output pipeline are verified and ready
        self.ensure_decoders_ready()

        # Discard previous contents and tracks before opening new file
        self.reset_playback_state()
        self.current_uri = uri
        if getattr(self, "tonemap_engine", None):
            self.tonemap_engine.current_uri = uri
            self.tonemap_engine.current_pts = float(start_pos) if start_pos else 0.0
            self.tonemap_engine._last_rpu_probe_bucket = None

        # Auto-detect EPIQ PLF & IMAX / Laser-Squeezed (1.43:1) flags from filename or URI
        is_epiq = bool(uri and ("EPIQ" in uri.upper() or "EPQ" in uri.upper()))
        imax_flags = DCPParser.detect_imax_flags(uri)
        self.is_anamorphic_143 = bool(imax_flags["unsqueeze_to_143"])
        self.current_imax_audio_format = str(imax_flags["imax_audio_format"])
        self._safe_emit("anamorphic_unsqueeze_signal", self.is_anamorphic_143)
        if self.is_anamorphic_143 and self.player:
            try:
                self.player["video-aspect-override"] = "4096:2864"
            except Exception:
                pass

        # Determine native framerate & HDR metadata if possible
        v_fps = 24.0
        probe_v_track = None
        try:
            from core.media_inspector import MediaInspector
            probe = MediaInspector.inspect_file(uri)
            if probe and probe.get("video_tracks"):
                probe_v_track = probe["video_tracks"][0]
                self.cached_probe_v_track = probe_v_track
                v_fps = probe_v_track.get("fps", 24.0)
                if v_fps > 0:
                    self.player.container_fps_override = v_fps
                self.player["video-sync"] = "audio"
                self.player["framedrop"] = "vo"
        except Exception:
            pass


        # If loading a standalone DCI cinema asset (MXF / JPEG 2000)
        if uri.lower().endswith((".mxf", ".j2k", ".jp2")) and is_gpu_jp2k_available() and self.nv_controller:
            self.nvjpeg2k_active = True
            self._current_reel_has_audio = False
            self._safe_emit("nv_active_signal", True)
            self.nv_controller.grading_params.update({
                "brightness": float(self.tonemap_engine.brightness),
                "contrast": float(self.tonemap_engine.contrast),
                "gamma": float(self.tonemap_engine.gamma),
                "saturation": float(self.tonemap_engine.saturation),
            })
            self.nv_controller.load_reel(uri, fps=v_fps)
            self.nv_controller.play()
            self.is_paused = False
            try:
                self.player["vid"] = "no"
                self.player.pause = False
            except Exception:
                pass
            dur = (self.nv_controller.total_frames / v_fps) if self.nv_controller else 0.0
            self._safe_emit("duration_signal", dur)
            self._safe_emit("file_loaded_signal", uri)
            if self.on_file_loaded:
                self.on_file_loaded(uri)
            return
        elif uri.lower().endswith((".mxf", ".j2k", ".jp2")):
            try:
                self.player["vd-lavc-o"] = "lowres=2"
                self.player["vd-lavc-threads"] = 8
                self.player["vd-lavc-fast"] = True
            except Exception:
                pass
            self.tonemap_engine.enable_dci_xyz_mode(True, is_epiq=is_epiq, fps=v_fps)
        else:
            if self.nvjpeg2k_active:
                if self.nv_controller:
                    self.nv_controller.stop()
                self.nvjpeg2k_active = False
                self._safe_emit("nv_active_signal", False)
            try:
                self.player["vid"] = "auto"
                self.player["vd-lavc-o"] = ""
            except Exception:
                pass
            self.tonemap_engine.is_epiq = is_epiq
            if self.tonemap_engine.current_preset == "dci_xyz_srgb":
                self.tonemap_engine.apply_preset("auto")
            self._auto_detect_and_apply_hdr(probe_track=probe_v_track)

        if self.stereo3d_engine:
            self.stereo3d_engine.configure_for_media(
                uri,
                is_dcp=False,
                probe_data=probe if 'probe' in locals() and isinstance(probe, dict) else None,
            )


        try:
            if start_pos is not None and float(start_pos) > 0.0:
                try:
                    self.player["start"] = f"{float(start_pos):.2f}"
                except Exception:
                    pass
            else:
                try:
                    self.player["start"] = "none"
                except Exception:
                    pass

            self._begin_video_conceal()
            self.player.command("loadfile", uri, "replace")
            self.player.pause = False
            self.is_paused = False
            self._safe_emit("file_loaded_signal", uri)
            if self.on_file_loaded:
                self.on_file_loaded(uri)
            self._safe_emit("iab_status_signal", None, self.current_iab_mode)
            if self.on_iab_status:
                self.on_iab_status(None, self.current_iab_mode)

            # Post-loadfile automated defect checks once decode starts
            QTimer.singleShot(600, lambda: self._trigger_defect_check(context="POST_LOADFILE_1"))
            QTimer.singleShot(1600, lambda: self._trigger_defect_check(context="POST_LOADFILE_2"))
        except Exception as e:
            self._end_video_conceal()
            print(f"[MPVEngine] Error playing {uri}: {e}")

    def play_dcp_package(self, dcp: DCPPackage, cpl_index: int = 0, reel_index: int = 0):
        """Start synchronized playback of a full multi-reel DCP package."""
        if not dcp.compositions:
            raise ValueError("DCP contains no compositions (CPL)")

        # Discard previous contents and tracks before opening new DCP package
        self.reset_playback_state()
        self.current_dcp = dcp
        self.active_cpl = dcp.compositions[min(cpl_index, len(dcp.compositions) - 1)]
        self.is_dcp_playing = True

        if self.stereo3d_engine:
            self.stereo3d_engine.configure_for_media(
                dcp.root_path,
                is_dcp=True,
                is_stereoscopic_dcp=bool(self.active_cpl and getattr(self.active_cpl, "is_3d", False))
            )

        # Precompute multi-reel composition timeline and cumulative start offsets
        self.dcp_reel_offsets = []
        self.dcp_reel_durations = []
        cum = 0.0
        fps = float(self.active_cpl.fps if self.active_cpl.fps > 0 else 24.0)
        for r in self.active_cpl.reels:
            self.dcp_reel_offsets.append(cum)
            r_dur = float(r.duration_seconds if r.duration_seconds > 0 else (r.picture_duration_frames / fps))
            self.dcp_reel_durations.append(r_dur)
            cum += r_dur
        self.dcp_total_duration = cum

        # Extract and parse composition subtitles across all reels
        self.dcp_sub_engine.load_composition_subtitles(self.active_cpl)

        # Emit full composition duration immediately
        self._safe_emit("duration_signal", self.dcp_total_duration)
        if self.on_duration:
            self.on_duration(self.dcp_total_duration)

        self.play_dcp_reel(reel_index, start_pos=0.0)

    def _loadfile_at_start(self, path: str, start_pos: Optional[float]):
        """Load media file at an exact optional start offset without clearing async options prematurely."""
        start_opt = f"start={float(start_pos):.3f}" if (start_pos is not None and start_pos > 0) else "start=none"
        try:
            self.player["start"] = "none"
        except Exception:
            pass
        try:
            self.player.command("loadfile", path, "replace", -1, start_opt)
        except Exception:
            if start_pos is not None and start_pos > 0:
                try:
                    self.player["start"] = f"{float(start_pos):.3f}"
                except Exception:
                    pass
            self.player.command("loadfile", path, "replace")

    @staticmethod
    def _prepare_dcp_sound_path(sound_path: Optional[str]) -> Optional[str]:
        """
        Verify if a DCP audio MXF has non-standard/unknown SMPTE 382M channel layouts
        (e.g. 16-channel DVis/Atmos beds with UNK tags) which cause libavcodec/mpv frame
        conversion aborts. If so, remux cleanly to a fast-seekable uncompressed WAV cache.
        """
        if not sound_path or not os.path.exists(sound_path):
            return sound_path
        if not sound_path.lower().endswith(".mxf"):
            return sound_path

        try:
            import hashlib, subprocess
            cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "dcp_audio")
            os.makedirs(cache_dir, exist_ok=True)
            fname_hash = hashlib.md5(sound_path.encode("utf-8")).hexdigest()[:12]
            base_name = os.path.splitext(os.path.basename(sound_path))[0]
            wav_path = os.path.join(cache_dir, f"{base_name}_{fname_hash}.wav")

            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1024:
                return wav_path

            # Fast lossless copy remux to WAV (takes ~200ms)
            cmd = ["ffmpeg", "-y", "-i", sound_path, "-c", "copy", wav_path]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if res.returncode == 0 and os.path.exists(wav_path) and os.path.getsize(wav_path) > 1024:
                return wav_path
        except Exception as e:
            print(f"[MPVEngine] Error preparing DCP sound path: {e}")
        return sound_path

    def play_dcp_reel(self, reel_index: int, start_pos: Optional[float] = None):
        """Load single DCP reel: picture MXF + sound MXF synchronized + DCI-XYZ color conversion + IAB."""
        if not self.active_cpl or reel_index >= len(self.active_cpl.reels):
            return

        self._is_transitioning_reel = True
        self._mpv_eof_armed = False
        self._reel_transition_ts = time.perf_counter()
        if self.nv_controller:
            try:
                self.nv_controller.pause()
            except Exception:
                pass
        self.current_reel_index = reel_index
        reel: DCPReel = self.active_cpl.reels[reel_index]

        if not reel.picture_path or not os.path.exists(reel.picture_path):
            self._is_transitioning_reel = False
            raise FileNotFoundError(f"DCP Picture MXF missing: {reel.picture_path}")

        # Exact native framerate from reel or CPL
        fps = float(getattr(reel, "picture_fps", 0) or (self.active_cpl.fps if self.active_cpl else 24.0) or 24.0)
        if fps <= 0:
            fps = 24.0

        # Check for EPIQ PLF & IMAX / Laser-Squeezed (1.43:1) mastering flags
        name_sources = [
            getattr(self.current_dcp, "root_path", ""),
            getattr(self.current_dcp, "folder_path", ""),
            getattr(self.current_dcp, "title", ""),
            getattr(self.active_cpl, "title", "") if self.active_cpl else "",
            getattr(self.active_cpl, "annotation_text", "") if self.active_cpl else "",
            getattr(self.active_cpl, "issuer", "") if self.active_cpl else "",
            getattr(reel, "picture_path", ""),
            getattr(reel, "sound_path", ""),
        ]
        is_epiq = any(src and ("EPIQ" in str(src).upper() or "EPQ" in str(src).upper()) for src in name_sources)

        imax_flags = DCPParser.detect_imax_flags(*(str(s) for s in name_sources if s))
        self.is_anamorphic_143 = bool(imax_flags["unsqueeze_to_143"] or getattr(reel, "unsqueeze_to_143", False))
        self.current_imax_audio_format = str(
            imax_flags["imax_audio_format"] or getattr(reel, "imax_audio_format", "") or ""
        )
        sound_path = reel.sound_path if (reel.sound_path and os.path.exists(reel.sound_path)) else None
        self._current_reel_has_audio = bool(sound_path)
        default_ch = 16 if self.current_imax_audio_format == "IMAX12" else 6
        cpl_ch = int(getattr(reel, "sound_channels", 0) or 0)
        self.current_sound_channels = cpl_ch if cpl_ch > 0 else default_ch
        if sound_path:
            if sound_path in self._sound_channel_cache:
                self.current_sound_channels = self._sound_channel_cache[sound_path]
            elif cpl_ch > 0:
                self._sound_channel_cache[sound_path] = cpl_ch
            else:
                try:
                    from core.media_inspector import MediaInspector
                    snd_probe = MediaInspector.inspect_file(sound_path)
                    if snd_probe and snd_probe.get("audio_tracks"):
                        ch = int(snd_probe["audio_tracks"][0].get("channels") or 0)
                        if ch > 0:
                            self.current_sound_channels = ch
                            self._sound_channel_cache[sound_path] = ch
                except Exception:
                    pass

        self._safe_emit("anamorphic_unsqueeze_signal", self.is_anamorphic_143)
        if self.is_anamorphic_143 and self.player:
            try:
                self.player["video-aspect-override"] = "4096:2864"
            except Exception:
                pass

        # Check for IAB / Dolby Atmos AuxData MXF
        if hasattr(reel, "atmos_path") and reel.atmos_path and os.path.exists(reel.atmos_path):
            try:
                self.current_iab_meta = IABEngine.parse_track(reel.atmos_path, max_frames_to_index=10000)
            except Exception as e:
                print(f"[MPVEngine] IAB Parse error: {e}")
                self.current_iab_meta = None
        else:
            self.current_iab_meta = None

        self._safe_emit("iab_status_signal", self.current_iab_meta, self.current_iab_mode)
        if self.on_iab_status:
            self.on_iab_status(self.current_iab_meta, self.current_iab_mode)

        # Pre-set audio downmix filter before sound is attached so libswresample never encounters unsupported multi-channel layout
        self.set_iab_mode(self.current_iab_mode)

        use_nvjpeg2k = (self.dcp_decode_level == 0) and is_gpu_jp2k_available() and (self.nv_controller is not None)
        self.nvjpeg2k_active = use_nvjpeg2k
        self._safe_emit("nv_active_signal", use_nvjpeg2k)

        sub_srt_path = self.dcp_sub_engine.get_reel_srt(reel_index) if self.dcp_sub_engine else None

        if use_nvjpeg2k:
            # GPU JPEG 2000 Acceleration (NVIDIA nvJPEG2000 / Grok OpenCL) handles 4K video decoding & tonemapping.
            # mpv handles audio playback (opening sound_path directly avoids demuxing/seeking the 70+ GB picture MXF).
            playable_sound = self._prepare_dcp_sound_path(sound_path) if sound_path else None
            has_sound = bool(playable_sound and os.path.exists(playable_sound))
            try:
                self.player["pause"] = True
                self.player["vid"] = "no"
                self.player["audio-files"] = []
                if sub_srt_path:
                    self.player["sub-files"] = [sub_srt_path]
                    if getattr(self, "subtitles_user_disabled", False):
                        self.player["sid"] = "no"
                        self.player["sub-visibility"] = False
                    else:
                        self.player["sid"] = 1
                        self.player["sub-visibility"] = True
            except Exception:
                pass

            primary_media = playable_sound if has_sound else reel.picture_path
            self._loadfile_at_start(primary_media, start_pos)

            if has_sound:
                try:
                    self.player["aid"] = "auto"
                    self.set_iab_mode(self.current_iab_mode)
                except Exception:
                    pass

            is_dvis = bool(self.active_cpl and getattr(self.active_cpl, "is_dolby_vision", False))
            self.tonemap_engine.enable_dci_xyz_mode(True, is_epiq=is_epiq, fps=fps, is_dolby_vision=is_dvis)

            init_status = self.tonemap_engine.get_status_summary()
            init_status["is_epiq"] = is_epiq
            init_status["is_dolby_vision"] = is_dvis
            self.nv_controller.apply_tonemap_status(init_status, redecode_now=False)
            self.nv_controller.load_reel(
                reel.picture_path,
                fps=fps,
                total_duration=reel.duration_seconds,
                initial_pts=float(start_pos or 0.0),
            )

            self.nv_controller.play()
            self.player.pause = False
            self.is_paused = False

            # Queue next reel for background pre-indexing & frame 0..7 pre-decoding
            if reel_index + 1 < len(self.active_cpl.reels):
                nxt = self.active_cpl.reels[reel_index + 1]
                self.nv_controller.set_next_reel(nxt.picture_path or "", nxt.sound_path or "")
            else:
                self.nv_controller.set_next_reel("", "")
        else:
            # Software or proxy resolution decoding via mpv (1080p / 720p / proxy)
            try:
                self.player["vid"] = "auto"
                self.player.container_fps_override = fps
                self.player["video-sync"] = "audio"
                self.player["framedrop"] = "vo"
                self.player["vd-lavc-o"] = f"lowres={self.dcp_decode_level}"
                self.player["vd-lavc-threads"] = 8
                self.player["vd-lavc-fast"] = True
                if sound_path:
                    playable_sound = self._prepare_dcp_sound_path(sound_path)
                    self.player["audio-files"] = [playable_sound] if playable_sound else [sound_path]
                else:
                    self.player["audio-files"] = []
                if sub_srt_path:
                    self.player["sub-files"] = [sub_srt_path]
                    if getattr(self, "subtitles_user_disabled", False):
                        self.player["sid"] = "no"
                        self.player["sub-visibility"] = False
                    else:
                        self.player["sid"] = 1
                        self.player["sub-visibility"] = True
            except Exception:
                pass

            self._loadfile_at_start(reel.picture_path, start_pos)

            if sound_path:
                try:
                    self.player["aid"] = "auto"
                    self.set_iab_mode(self.current_iab_mode)
                except Exception:
                    pass

            is_dvis = bool(self.active_cpl and getattr(self.active_cpl, "is_dolby_vision", False))
            self.tonemap_engine.enable_dci_xyz_mode(True, is_epiq=is_epiq, fps=fps, is_dolby_vision=is_dvis)
            self.player.pause = False
            self.is_paused = False

        # Maintain total composition duration on timeline
        dur = self.dcp_total_duration if self.dcp_total_duration > 0 else float(reel.duration_seconds)
        self._safe_emit("duration_signal", dur)
        if self.on_duration:
            self.on_duration(dur)

        r_off = self.dcp_reel_offsets[reel_index] if reel_index < len(self.dcp_reel_offsets) else 0.0
        initial_pts = r_off + (start_pos or 0.0)
        self._pending_seek_pts = initial_pts
        self._pending_seek_until = time.perf_counter() + 1.2
        self._safe_emit("time_pos_signal", initial_pts)
        if self.on_time_pos:
            self.on_time_pos(initial_pts)

        title = f"{self.active_cpl.title} [Reel {reel.index}/{len(self.active_cpl.reels)}]"
        self._safe_emit("file_loaded_signal", title)
        if self.on_file_loaded:
            self.on_file_loaded(title)

        self._is_transitioning_reel = False

    def _start_dcp_asset_loader(self, sound_path: Optional[str], sub_path: Optional[str]):
        """Asynchronously attach audio and subtitles without blocking main thread."""
        def _loader():
            start_t = time.time()
            attached_audio = False
            attached_sub = False

            while time.time() - start_t < 4.0:
                time.sleep(0.06)
                if not self.player:
                    break

                try:
                    dur = getattr(self.player, "duration", None)
                    if dur is not None and dur > 0:
                        if sound_path and not attached_audio:
                            self.player.command("audio-add", sound_path, "select")
                            time.sleep(0.04)
                            self.player["aid"] = 1
                            self.set_iab_mode(self.current_iab_mode)
                            attached_audio = True

                        if sub_path and not attached_sub:
                            self.player.command("sub-add", sub_path, "select")
                            attached_sub = True

                        if (not sound_path or attached_audio) and (not sub_path or attached_sub):
                            break
                except Exception:
                    pass

        t = threading.Thread(target=_loader, daemon=True)
        t.start()

    def set_iab_mode(self, mode: str):
        """
        Configure IAB / multi-channel audio spatialization mode:
        'binaural': 3D Headphone Spatializer with HRIR crossfeed (SMPTE ST 2098-2)
        'cinema_71': 7.1 Cinema Downmix
        'cinema_51': 5.1 Surround Downmix
        'stereo_dialog': Dialog Focus + Dynamic Range Control
        'pcm_direct': Unprocessed Direct Multi-Channel Bed
        """
        self.current_iab_mode = mode
        filter_str = ""
        imax_fmt = getattr(self, "current_imax_audio_format", "")
        if imax_fmt == "IMAX12":
            filter_str = IABEngine.get_imax12_filter(mode, getattr(self, "current_sound_channels", 16))
        elif imax_fmt == "IMAX5":
            filter_str = IABEngine.get_imax5_filter(mode, getattr(self, "current_sound_channels", 6))
        elif mode == "binaural":
            filter_str = IABEngine.get_binaural_3d_filter()
        elif mode == "cinema_71":
            filter_str = IABEngine.get_cinema_71_downmix_filter()
        elif mode == "cinema_51":
            filter_str = IABEngine.get_cinema_51_downmix_filter()
        elif mode == "stereo_dialog":
            filter_str = IABEngine.get_stereo_dialog_focus_filter()
        elif mode == "pcm_direct":
            filter_str = IABEngine.get_passthrough_filter()

        if self.player and filter_str != self._last_applied_af:
            try:
                self.player["af"] = filter_str
                self._last_applied_af = filter_str
            except Exception as e:
                print(f"[MPVEngine] Error setting audio filter {mode}: {e}")

        self._safe_emit("iab_status_signal", self.current_iab_meta, self.current_iab_mode)
        if self.on_iab_status:
            self.on_iab_status(self.current_iab_meta, self.current_iab_mode)

    def set_dcp_decode_quality(self, level: int):
        """
        Switch JPEG 2000 DWT wavelet decode resolution:
        level=0: Native 4K Master (⚡ NVIDIA GPU nvJPEG2000 @ 24fps)
        level=1: 2K Wavelet Sub-band (1080p match)
        level=2: 1K Wavelet Sub-band (Real-time proxy)
        """
        self.dcp_decode_level = level
        if self.player:
            try:
                self.player["vd-lavc-o"] = f"lowres={level}"
                if level == 0:
                    self.player["framedrop"] = "no"
                else:
                    self.player["framedrop"] = "vo"
            except Exception:
                pass

        curr_pos = getattr(self.player, "time_pos", None)
        if (curr_pos is None or curr_pos <= 0) and self.nvjpeg2k_active and self.nv_controller:
            curr_pos = self.nv_controller.current_pts

        if self.is_dcp_playing and self.active_cpl:
            # Reload active DCP reel with the new decode quality at current position
            self.play_dcp_reel(self.current_reel_index, start_pos=curr_pos)
        else:
            curr_path = self.current_uri or getattr(self.player, "path", None)
            if curr_path:
                self.play(curr_path)
                if curr_pos and curr_pos > 0:
                    self.seek(curr_pos, relative=False)

    def get_iab_metadata(self) -> Optional[IABTrackMetadata]:
        return self.current_iab_meta

    def get_active_spatial_objects(self) -> List[IABSpatialObject]:
        if not self.current_iab_meta:
            return []
        pos = getattr(self.player, "time_pos", 0.0) or 0.0
        if pos == 0.0 and self.nvjpeg2k_active and self.nv_controller:
            pos = self.nv_controller.current_pts
        return IABEngine.get_spatial_objects_at_time(self.current_iab_meta, pos)

    def pause(self):
        self.is_paused = True
        if self.nvjpeg2k_active and self.nv_controller:
            self.nv_controller.pause()
        if self.player:
            self.player.pause = True
        self._safe_emit("pause_signal", True)
        if self.on_pause_change:
            self.on_pause_change(True)

    def resume(self):
        self.is_paused = False
        if self.nvjpeg2k_active and self.nv_controller:
            self.nv_controller.play()
        if self.player:
            self.player.pause = False
        self._safe_emit("pause_signal", False)
        if self.on_pause_change:
            self.on_pause_change(False)

    def toggle_pause(self):
        if self.is_paused:
            self.resume()
        else:
            self.pause()

    def stop(self):
        self.reset_playback_state()
        if self.player:
            try:
                self.player.command("stop")
            except Exception:
                pass

    def set_speed(self, speed: float) -> float:
        """Set playback speed between 0.25x and 4.0x with scaletempo2 pitch preservation."""
        self.playback_speed = max(0.25, min(4.0, float(speed)))
        if self.player:
            try:
                self.player["speed"] = self.playback_speed
            except Exception:
                pass
        if self.nvjpeg2k_active and self.nv_controller:
            try:
                fps = getattr(self.nv_controller, "fps", 24.0) or 24.0
                self.nv_controller.frame_interval = 1.0 / (fps * self.playback_speed)
            except Exception:
                pass
        return self.playback_speed

    def adjust_speed(self, delta: float) -> float:
        new_speed = round(self.playback_speed + delta, 2)
        return self.set_speed(new_speed)

    def reset_speed(self) -> float:
        return self.set_speed(1.0)

    def set_ab_point_a(self, pts: Optional[float] = None) -> float:
        if pts is None:
            pts = self.get_current_pts()
        self.ab_point_a = max(0.0, float(pts))
        if self.ab_point_b is not None and self.ab_point_b <= self.ab_point_a:
            self.ab_point_b = None
        return self.ab_point_a

    def set_ab_point_b(self, pts: Optional[float] = None) -> Optional[float]:
        if pts is None:
            pts = self.get_current_pts()
        if self.ab_point_a is not None and pts > self.ab_point_a:
            self.ab_point_b = float(pts)
            return self.ab_point_b
        return None

    def clear_ab_repeat(self):
        self.ab_point_a = None
        self.ab_point_b = None

    def get_chapters(self) -> List[Dict[str, Any]]:
        """Return list of chapters/reels with time (seconds) and title."""
        if self.is_dcp_playing and self.active_cpl and self.dcp_reel_offsets:
            chapters = []
            for idx, r in enumerate(self.active_cpl.reels):
                off = self.dcp_reel_offsets[idx] if idx < len(self.dcp_reel_offsets) else 0.0
                chapters.append({
                    "index": idx,
                    "time": off,
                    "title": f"Reel {r.index} ({r.timecode})"
                })
            return chapters

        if self.player:
            try:
                cl = self.player.chapter_list
                if cl:
                    res = []
                    for i, ch in enumerate(cl):
                        t = float(ch.get("time", 0.0) or 0.0)
                        title = ch.get("title") or f"Chapter {i+1}"
                        res.append({"index": i, "time": t, "title": title})
                    return res
            except Exception:
                pass
        return []

    def next_chapter(self):
        chaps = self.get_chapters()
        if not chaps:
            return
        cur_t = self.get_current_pts()
        for ch in chaps:
            if ch["time"] > cur_t + 1.0:
                self.seek(ch["time"], relative=False)
                return

    def prev_chapter(self):
        chaps = self.get_chapters()
        if not chaps:
            return
        cur_t = self.get_current_pts()
        for ch in reversed(chaps):
            if ch["time"] < cur_t - 1.5:
                self.seek(ch["time"], relative=False)
                return
        if chaps:
            self.seek(chaps[0]["time"], relative=False)

    def get_duration(self) -> float:
        """Returns total duration of media in seconds (multi-reel composition total for DCP)."""
        if self.is_dcp_playing and self.active_cpl and self.dcp_total_duration > 0:
            return float(self.dcp_total_duration)
        try:
            return float(getattr(self.player, "duration", 0.0) or 0.0)
        except Exception:
            return 0.0

    def get_current_pts(self) -> float:
        """Returns current global playback position in seconds across multi-reel DCP or file."""
        if self.is_dcp_playing and self.active_cpl:
            r_off = self.dcp_reel_offsets[self.current_reel_index] if self.current_reel_index < len(self.dcp_reel_offsets) else 0.0
            local_pos = self.nv_controller.current_pts if (self.nvjpeg2k_active and self.nv_controller) else (getattr(self.player, "time_pos", 0.0) or 0.0)
            return r_off + float(local_pos)
        if self.nvjpeg2k_active and self.nv_controller:
            return float(self.nv_controller.current_pts)
        try:
            return float(getattr(self.player, "time_pos", 0.0) or 0.0)
        except Exception:
            return 0.0

    def seek(self, seconds: float, relative: bool = True, exact: bool = True):
        # 1. Multi-Reel DCP Seamless Cross-Reel Seeking
        if self.is_dcp_playing and self.active_cpl and self.dcp_reel_offsets:
            curr_pts = self.get_current_pts()
            target_pts = (curr_pts + seconds) if relative else seconds
            target_pts = max(0.0, min(target_pts, max(0.0, self.dcp_total_duration - 0.05)))

            # Identify target reel index
            target_reel = 0
            for i, r_off in enumerate(self.dcp_reel_offsets):
                if target_pts >= r_off:
                    target_reel = i
                else:
                    break
            local_offset = target_pts - self.dcp_reel_offsets[target_reel]

            if target_reel == self.current_reel_index:
                self._pending_seek_pts = target_pts
                self._pending_seek_until = time.perf_counter() + 1.0
                if self.player:
                    try:
                        self.player.command("seek", local_offset, "absolute+exact")
                    except Exception:
                        try:
                            self.player.time_pos = local_offset
                        except Exception:
                            pass
                if self.nvjpeg2k_active and self.nv_controller:
                    self.nv_controller.seek_time(local_offset)
            else:
                self.play_dcp_reel(target_reel, start_pos=local_offset)

            self._safe_emit("time_pos_signal", target_pts)
            if self.on_time_pos:
                self.on_time_pos(target_pts)
            return

        # 2. Standalone NVJPEG2000 seeking
        if self.nvjpeg2k_active and self.nv_controller:
            if relative:
                target = max(0.0, self.nv_controller.current_pts + seconds)
            else:
                target = max(0.0, seconds)
            self._pending_seek_pts = target
            self._pending_seek_until = time.perf_counter() + 1.0
            if self.player:
                try:
                    self.player.command("seek", target, "absolute+exact")
                except Exception:
                    try:
                        self.player.time_pos = target
                    except Exception:
                        pass
            self.nv_controller.seek_time(target)
            self._safe_emit("time_pos_signal", target)
            return

        # 3. Standard mpv seeking
        expected = seconds if not relative else (self.get_current_pts() + seconds)
        dur = self.get_duration()
        if dur > 0:
            expected = max(0.0, min(expected, dur))
        else:
            expected = max(0.0, expected)
        self._pending_seek_pts = expected
        self._pending_seek_until = time.perf_counter() + 0.8
        if self.tonemap_engine:
            self.tonemap_engine.current_pts = expected
            self.tonemap_engine.update_dynamic_rpu_async(self.current_uri, expected)

        mode = "relative" if relative else "absolute"
        precision = "exact" if exact else "keyframes"
        flag = f"{mode}+{precision}"
        try:
            self.player.command("seek", seconds, flag)
        except Exception:
            try:
                self.player.command("seek", seconds, mode, precision)
            except Exception as e:
                print(f"[MPVEngine] Seek error: {e}")

    def get_cache_duration(self) -> float:
        """Returns seconds of media buffered ahead in RAM."""
        try:
            return float(getattr(self.player, "demuxer_cache_duration", 0.0) or 0.0)
        except Exception:
            return 0.0

    def get_cache_state(self) -> dict:
        """Returns cache buffer statistics (bytes cached, backbuffer, underrun status)."""
        try:
            return getattr(self.player, "demuxer_cache_state", {}) or {}
        except Exception:
            return {}

    def frame_step(self):
        """Step exactly one video frame forward (KMPlayer / mpv style)."""
        if self.nvjpeg2k_active and self.nv_controller:
            self.nv_controller.step_frame(1)
            pts = self.get_current_pts()
            self._safe_emit("time_pos_signal", pts)
            return

        try:
            self.player.command("frame-step")
        except Exception:
            pass

    def frame_back_step(self):
        """Step exactly one video frame backward."""
        if self.nvjpeg2k_active and self.nv_controller:
            self.nv_controller.step_frame(-1)
            pts = self.get_current_pts()
            self._safe_emit("time_pos_signal", pts)
            return

        try:
            self.player.command("frame-back-step")
        except Exception:
            pass

    def set_volume(self, val: int):
        try:
            self.player.volume = max(0, min(150, val))
        except Exception:
            pass

    def toggle_mute(self):
        try:
            self.player.mute = not self.player.mute
        except Exception:
            pass

    # External Assets Integration
    def add_external_subtitle(self, sub_path: str, select: bool = True):
        if not os.path.exists(sub_path):
            raise FileNotFoundError(f"Subtitle file not found: {sub_path}")
        flag = "select" if select else "auto"
        self.player.command("sub-add", sub_path, flag)

    def set_sub_delay(self, seconds: float):
        try:
            self.player["sub-delay"] = seconds
        except Exception:
            pass

    def add_external_audio(self, audio_path: str, select: bool = True):
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        flag = "select" if select else "auto"
        self.player.command("audio-add", audio_path, flag)

    def set_audio_delay(self, seconds: float):
        try:
            self.player["audio-delay"] = seconds
        except Exception:
            pass

    def add_external_video(self, video_path: str, select: bool = False):
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        flag = "select" if select else "auto"
        self.player.command("video-add", video_path, flag)

    def set_aspect_ratio(self, ratio_str: str):
        """Aspect ratio override (e.g. '16:9', '4:3', '1.43:1', '2.39:1', '1.85:1', '-1' for default)."""
        self.aspect_ratio_override = ratio_str if ratio_str and ratio_str != "-1" else None
        try:
            self.player["video-aspect-override"] = ratio_str
        except Exception:
            pass

    def get_target_aspect_ratio(self) -> Optional[float]:
        """Return the active aspect ratio if an override or anamorphic unsqueeze is active."""
        if self.is_anamorphic_143:
            return 1.43
        override = self.aspect_ratio_override
        if not override and self.player:
            try:
                raw = self.player["video-aspect-override"]
                if raw and raw not in ("-1", "-2", "-1.0", "-2.0", "no", "default"):
                    override = str(raw)
            except Exception:
                pass
        if override:
            try:
                if ":" in override:
                    num, den = override.split(":", 1)
                    val = float(num) / float(den)
                else:
                    val = float(override)
                if val > 0:
                    return val
            except Exception:
                pass
        return None

    def toggle_stats_overlay(self):
        """Toggle mpv's detailed on-screen statistics display (Shift+I HUD)."""
        try:
            self.player.command("script-binding", "stats/display-stats-toggle")
        except Exception:
            try:
                self.player.command("show-text", f"FPS: {self.player.estimated_vf_fps} | Cache: {self.player.demuxer_cache_duration}s", 3000)
            except Exception:
                pass

    def take_screenshot(self, output_path: Optional[str] = None, crop_active_area: bool = False) -> str:
        if not output_path:
            pictures_dir = os.path.join(os.path.expanduser("~"), "Pictures")
            os.makedirs(pictures_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(pictures_dir, f"BOOBSnapshot_{timestamp}.png")
        
        norm_path = os.path.abspath(output_path).replace("\\", "/")
        ext = os.path.splitext(norm_path)[1].lower()

        # Always capture to a temporary PNG first so we can crop active picture area losslessly
        # and export uncompressed into target format (PNG, TIFF, BMP)
        import tempfile
        from PIL import Image
        from core.media_inspector import MediaInspector

        fd, temp_png = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        temp_png_norm = temp_png.replace("\\", "/")

        try:
            if self.player:
                self.player["screenshot-format"] = "png"
                self.player["screenshot-png-compression"] = 0
                self.player["screenshot-png-filter"] = 0
                self.player["screenshot-tag-colorspace"] = "yes"
                self.player["screenshot-high-bit-depth"] = "yes"

                # Always capture at full NATIVE video resolution (e.g. 4K 3840x2160) using "subtitles" mode
                # so that native libplacebo tonemapping, color conversions, and subtitle layers are baked in.
                # Mode "window" must NEVER be used because it degrades snapshots to the window resolution (720p).
                mode = "subtitles"
                prev_trc = None
                if getattr(self, "tonemap_engine", None) and not getattr(self.tonemap_engine, "display_is_hdr", False):
                    try:
                        prev_trc = self.player["target-trc"]
                        if prev_trc == "bt.1886":
                            self.player["target-trc"] = "gamma2.2"
                    except Exception:
                        prev_trc = None

                try:
                    self.player.command("screenshot-to-file", temp_png_norm, mode)
                except Exception:
                    self.player.command("screenshot-to-file", temp_png_norm, "video")
                finally:
                    if prev_trc == "bt.1886":
                        try:
                            self.player["target-trc"] = prev_trc
                        except Exception:
                            pass

            if os.path.exists(temp_png):
                with Image.open(temp_png) as img:
                    img_to_save = img.copy()

                try:
                    os.remove(temp_png)
                except Exception:
                    pass

                # Unsqueeze anamorphic / aspect ratio override to match display presentation
                target_ar = self.get_target_aspect_ratio()
                if target_ar and target_ar > 0:
                    cur_w, cur_h = img_to_save.size
                    if cur_w > 0 and cur_h > 0:
                        cur_ar = cur_w / cur_h
                        if abs(cur_ar - target_ar) > 0.02:
                            if abs(target_ar - 1.43) < 0.02:
                                const_w = 4096 if cur_w == 4096 else (2048 if cur_w == 2048 else cur_w)
                                target_h = int(round(const_w / 1.43))
                                img_to_save = img_to_save.resize((const_w, target_h), Image.Resampling.LANCZOS)
                            else:
                                target_h = int(round(cur_w / target_ar))
                                img_to_save = img_to_save.resize((cur_w, target_h), Image.Resampling.LANCZOS)

                # Crop strictly active image area (removes letterboxing / pillarboxing)
                if crop_active_area:
                    img_to_save = MediaInspector.crop_active_image_area(img_to_save)

                os.makedirs(os.path.dirname(norm_path), exist_ok=True)
                if ext == ".bmp":
                    img_to_save.convert("RGB").save(norm_path, "BMP")
                elif ext in (".tiff", ".tif"):
                    img_to_save.save(norm_path, "TIFF", compression=None)
                else:
                    img_to_save.save(norm_path, "PNG", compress_level=0)

                return norm_path

            return ""
        except Exception as e:
            print(f"[MPVEngine] Screenshot error: {e}")
            if os.path.exists(temp_png):
                try:
                    os.remove(temp_png)
                except Exception:
                    pass
            return ""

    def _augment_dcp_video_track(self, tracks: List[dict]) -> List[dict]:
        """Expose active NVJPEG2000 GPU JPEG2000 track when mpv opens audio MXF directly."""
        if self.is_dcp_playing and self.nvjpeg2k_active and not any(t.get("type") == "video" for t in tracks):
            v_track = {
                "id": 1,
                "type": "video",
                "codec": "jpeg2000 (NVIDIA nvJPEG2000 GPU)",
                "title": "DCI 4K JPEG2000 Master",
                "selected": True,
                "demux-w": 4096,
                "demux-h": 2160,
                "demux-fps": float(self.active_cpl.fps) if self.active_cpl else 24.0,
            }
            return [v_track] + list(tracks)
        return tracks

    def get_track_list(self) -> List[dict]:
        try:
            tracks = list(self.player.track_list or [])
            return self._augment_dcp_video_track(tracks)
        except Exception:
            return []

    def set_track(self, track_type: str, track_id: Any):
        """Select track by type ('audio', 'sub', 'video') and ID. Pass 0, 'no', or None to disable."""
        prop = {"audio": "aid", "sub": "sid", "video": "vid"}.get(track_type)
        if prop and self.player:
            try:
                if track_id in (0, "no", "off", None, False):
                    self.player[prop] = "no"
                    if track_type == "sub":
                        self.subtitles_user_disabled = True
                        self.player["sub-visibility"] = False
                        if getattr(self, "is_paused", False) or getattr(self.player, "pause", False):
                            try:
                                self.player.command("seek", 0, "relative", "exact")
                            except Exception:
                                pass
                elif track_id == "auto":
                    self.player[prop] = "auto"
                    if track_type == "sub":
                        self.subtitles_user_disabled = False
                        self.player["sub-visibility"] = True
                        if getattr(self, "is_paused", False) or getattr(self.player, "pause", False):
                            try:
                                self.player.command("seek", 0, "relative", "exact")
                            except Exception:
                                pass
                else:
                    self.player[prop] = int(track_id)
                    if track_type == "sub":
                        self.subtitles_user_disabled = False
                        self.player["sub-visibility"] = True
                        if getattr(self, "is_paused", False) or getattr(self.player, "pause", False):
                            try:
                                self.player.command("seek", 0, "relative", "exact")
                            except Exception:
                                pass
            except Exception as e:
                print(f"[MPVEngine] Error setting {track_type} track {track_id}: {e}")

    def cycle_track(self, track_type: str, direction: str = "up") -> Optional[int]:
        """Cycle through available tracks for 'video', 'audio', or 'sub'."""
        prop = {"audio": "aid", "sub": "sid", "video": "vid"}.get(track_type)
        if prop and self.player:
            try:
                if direction == "down":
                    self.player.command("cycle", prop, "down")
                else:
                    self.player.command("cycle", prop)
                res = getattr(self.player, prop, None)
                if track_type == "sub":
                    if res in ("no", None, False, 0):
                        self.subtitles_user_disabled = True
                        self.player["sub-visibility"] = False
                    else:
                        self.subtitles_user_disabled = False
                        self.player["sub-visibility"] = True
                    if getattr(self, "is_paused", False) or getattr(self.player, "pause", False):
                        try:
                            self.player.command("seek", 0, "relative", "exact")
                        except Exception:
                            pass
                return res
            except Exception as e:
                print(f"[MPVEngine] Error cycling {track_type} track: {e}")
        return None

    def toggle_subtitles(self) -> bool:
        """Toggle subtitle visibility on/off. Returns True if subtitles are now visible, False otherwise."""
        if not self.player:
            return False
        try:
            try:
                current_vis = bool(self.player["sub-visibility"])
            except Exception:
                current_vis = True
            current_sid = getattr(self.player, "sid", None)
            if current_vis and current_sid not in ("no", None, False, 0):
                self.subtitles_user_disabled = True
                self.player["sub-visibility"] = False
                self.player["sid"] = "no"
                if getattr(self, "is_paused", False) or getattr(self.player, "pause", False):
                    try:
                        self.player.command("seek", 0, "relative", "exact")
                    except Exception:
                        pass
                return False
            else:
                self.subtitles_user_disabled = False
                if current_sid in ("no", None, False, 0):
                    sub_tracks = [t for t in self.get_tracks_by_type("sub")]
                    pref_id = None
                    for st in sub_tracks:
                        lang = (st.get("lang") or "").lower()
                        if lang in ("en", "eng", "enus", "en-us"):
                            pref_id = st.get("id")
                            break
                    if pref_id is None and sub_tracks:
                        pref_id = sub_tracks[0].get("id")
                    if pref_id is not None:
                        self.player["sid"] = pref_id
                self.player["sub-visibility"] = True
                if getattr(self, "is_paused", False) or getattr(self.player, "pause", False):
                    try:
                        self.player.command("seek", 0, "relative", "exact")
                    except Exception:
                        pass
                return True
        except Exception as e:
            print(f"[MPVEngine] Error toggling subtitles: {e}")
            return False

    def get_tracks_by_type(self, track_type: str) -> List[dict]:
        """Return tracks filtered by type ('video', 'audio', 'sub')."""
        return [t for t in self.get_track_list() if t.get("type") == track_type]

    def get_selected_track_id(self, track_type: str) -> Optional[int]:
        """Return the ID of the currently active track for a given type, or None if disabled."""
        prop = {"audio": "aid", "sub": "sid", "video": "vid"}.get(track_type)
        if not prop or not self.player:
            return None
        val = getattr(self.player, prop, None)
        if val in ("no", None, False):
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            for t in self.get_tracks_by_type(track_type):
                if t.get("selected"):
                    return t.get("id")
            return None
