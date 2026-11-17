"""
BOOB Player - Master Application Window
Hybrid of mpv, VLC, and KMPlayer.
Strict Dark Mode with floating OSC, dockable sidebars, and full format/color support.
"""

import os
import sys
import time
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDockWidget,
    QFileDialog, QInputDialog, QMessageBox, QMenuBar, QMenu,
    QStatusBar, QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSlot
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence, QIcon, QMouseEvent, QKeyEvent, QImage, QGuiApplication, QPainter, QColor, QPalette

from core.mpv_engine import MPVEngine
from core.dcp_parser import DCPParser, DCPPackage
from core.iptv_manager import IPTVManager, IPTVChannel
from core.playlist_manager import PlaylistManager, PlaylistItem
from core.media_inspector import MediaInspector
from core.gpu_detector import GPUDetector

from ui.video_widget import VideoWidget
from ui.osc_controls import OSCControls
from ui.iptv_drawer import IPTVDrawer
from ui.playlist_drawer import PlaylistDrawer
from ui.tonemap_dialog import TonemapControlDrawer
from ui.dcp_dialog import DCPInspectorDialog
from ui.codec_info_dialog import CodecInfoDialog
from ui.audio_sync_dialog import AudioSyncDialog
from ui.subtitle_sync_dialog import SubtitleSyncDialog
from ui.iab_visualizer_dialog import IABVisualizerDialog
from ui.tracks_dialog import TrackSelectorDialog
from ui.goto_dialog import GoToDialog
from ui.pns_dialog import PnSEditDialog
from ui.stereo3d_dialog import Stereo3DDialog
from ui.trim_dialog import LosslessTrimDialog
from core.thumbnail_generator import ThumbnailManager
from core.pns_controller import PnSController
from core.stereo3d_engine import Stereo3DEngine
from typing import Optional, Any
from ui.theme import DARK_THEME_QSS, get_theme_qss


class VideoOverlayContainer(QWidget):
    """Central container that hosts the full-size video viewport with floating overlays."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0))
        self.setPalette(pal)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #000000;")
        self.video_widget: Optional[VideoWidget] = None
        self.osc: Optional[OSCControls] = None
        self.toast_lbl: Optional[QLabel] = None

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

    def setup_children(self, video_widget: VideoWidget, osc: OSCControls, toast_lbl: QLabel):
        self.video_widget = video_widget
        self.osc = osc
        self.toast_lbl = toast_lbl
        self.update_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_layout()

    def contextMenuEvent(self, ev):
        p = self.parentWidget()
        if p and hasattr(p, "contextMenuEvent"):
            p.contextMenuEvent(ev)
        else:
            super().contextMenuEvent(ev)

    def update_layout(self):
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        # 1. Video widget ALWAYS covers the entire container (0, 0, w, h) - never resized by OSC
        if self.video_widget:
            self.video_widget.setGeometry(0, 0, w, h)

        # 2. Floating OSC Controller HUD centered above the bottom edge
        if self.osc:
            osc_w = min(max(w - 40, 500), 1200)
            osc_h = 92
            osc_x = max(10, (w - osc_w) // 2)
            osc_y = max(10, h - osc_h - 20)
            self.osc.set_resting_geometry(osc_x, osc_y, osc_w, osc_h)
            self.osc.raise_()

        # 3. Toast label at top left
        if self.toast_lbl:
            self.toast_lbl.move(24, 24)
            self.toast_lbl.raise_()

    def mouseMoveEvent(self, ev):
        if self.osc:
            self.osc.fade_in()
        if self.video_widget:
            self.video_widget.setCursor(Qt.CursorShape.ArrowCursor)
            self.video_widget.hide_timer.start()
        super().mouseMoveEvent(ev)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BOOB Player")
        self.resize(1280, 768)
        self.current_theme: str = "minimalist"
        self.setStyleSheet(DARK_THEME_QSS)

        # Managers
        self.iptv_mgr = IPTVManager()
        self.playlist_mgr = PlaylistManager()
        self.current_media_path: str = ""
        self.current_source_codec_str: str = ""
        self.iab_visualizer: Optional[IABVisualizerDialog] = None

        # Central video viewport and layout
        self._init_central_widget()

        # Initialize MPV engine embedded into VideoWidget
        self.engine = MPVEngine(wid=self.video_widget.get_mpv_wid())
        self._connect_engine_signals()

        # Pan & Scan (PnS) Frame Controller & Actions
        self._init_pns_system()

        # Side Docks
        self._init_docks()

        # Menu Bar
        self._init_menus()

        # Status Bar
        self._init_status_bar()

        # Keyboard shortcuts
        self._init_shortcuts()

        # Drag and drop connections
        self.video_widget.file_dropped.connect(self._handle_file_dropped)
        self.video_widget.folder_dropped.connect(self._handle_folder_dropped)
        self.video_widget.double_clicked.connect(self.toggle_fullscreen)
        self.video_widget.context_menu_requested.connect(self._show_context_menu)
        self.video_widget.mouse_moved_signal.connect(self._on_video_mouse_move)
        self.video_widget.wheel_scrolled.connect(self._on_wheel_scroll)
        self.video_widget.hide_timer.timeout.connect(self._on_inactivity_timeout)

        # Preload first sample channel or ready message
        self.show_toast("BOOB Player Ready | Dark Mode")

    def _init_central_widget(self):
        self.central_container = VideoOverlayContainer(self)
        self.setCentralWidget(self.central_container)

        # Video viewport - child of central_container, occupies full 100% geometry
        self.video_widget = VideoWidget(self.central_container)

        # Floating Toast Notification Label (Top Left)
        self.toast_lbl = QLabel(self.central_container)
        self.toast_lbl.setStyleSheet("""
            background: rgba(18, 19, 24, 0.94);
            color: #f3f4f6;
            font-weight: 600;
            font-size: 13px;
            padding: 7px 16px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 6px;
        """)
        self.toast_lbl.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setInterval(2500)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast_lbl.hide)

        # Bottom Floating OSC Bar - pure overlay, not in any resizing layout
        self.osc = OSCControls(self.central_container)
        self.central_container.setup_children(self.video_widget, self.osc, self.toast_lbl)

        # OSC Signal connections
        self.osc.play_pause_clicked.connect(self.toggle_play_pause)
        self.osc.stop_clicked.connect(self.stop_playback)
        self.osc.seek_requested.connect(self.seek_absolute)
        self.osc.skip_back_clicked.connect(lambda: self.seek_relative(-10))
        self.osc.skip_forward_clicked.connect(lambda: self.seek_relative(10))
        self.osc.frame_back_clicked.connect(self.frame_back_step)
        self.osc.frame_forward_clicked.connect(self.frame_step)
        self.osc.volume_changed.connect(self.set_volume)
        self.osc.mute_toggled.connect(self.toggle_mute)

        self.osc.toggle_iptv_clicked.connect(self.toggle_iptv_dock)
        self.osc.toggle_playlist_clicked.connect(self.toggle_playlist_dock)
        self.osc.toggle_tonemap_clicked.connect(self.toggle_tonemap_dock)
        self.osc.open_dcp_clicked.connect(self.open_dcp_dialog)
        self.osc.open_tracks_clicked.connect(self.action_track_selector)
        self.osc.open_codec_info_clicked.connect(self.open_codec_info_dialog)
        self.osc.fullscreen_clicked.connect(self.toggle_fullscreen)

    def _init_docks(self):
        # 1. IPTV Dock
        self.iptv_dock = QDockWidget("Live TV / IPTV Channels", self)
        self.iptv_drawer = IPTVDrawer(self.iptv_mgr, self.iptv_dock)
        self.iptv_drawer.channel_selected.connect(self.play_iptv_channel)
        self.iptv_dock.setWidget(self.iptv_drawer)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.iptv_dock)
        self.iptv_dock.hide()

        # 2. Playlist Dock
        self.playlist_dock = QDockWidget("Play Queue & History", self)
        self.playlist_drawer = PlaylistDrawer(self.playlist_mgr, self.playlist_dock)
        self.playlist_drawer.item_activated.connect(self._play_playlist_index)
        self.playlist_drawer.item_added.connect(self._add_playlist_item)
        self.playlist_dock.setWidget(self.playlist_drawer)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)
        self.playlist_dock.hide()

        # 3. Tonemapping Dock
        self.tonemap_dock = QDockWidget("Color Science & Tonemapping", self)
        self.tonemap_drawer = TonemapControlDrawer(self.engine.tonemap_engine, self.tonemap_dock)
        self.tonemap_drawer.preset_changed.connect(self._on_drawer_preset_changed)
        self.tonemap_dock.setWidget(self.tonemap_drawer)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.tonemap_dock)
        self.tonemap_dock.hide()

    def _init_menus(self):
        mb = self.menuBar()

        # --- FILE MENU ---
        file_menu = mb.addMenu("&File")

        act_open_file = QAction("Open &File...", self)
        act_open_file.setShortcut(QKeySequence("Ctrl+O"))
        act_open_file.triggered.connect(self.action_open_file)
        file_menu.addAction(act_open_file)

        act_open_dcp = QAction("Open &DCP Cinema Folder...", self)
        act_open_dcp.setShortcut(QKeySequence("Ctrl+D"))
        act_open_dcp.triggered.connect(self.action_open_dcp)
        file_menu.addAction(act_open_dcp)

        act_open_url = QAction("Open &Network Stream / URL...", self)
        act_open_url.setShortcut(QKeySequence("Ctrl+N"))
        act_open_url.triggered.connect(self.action_open_url)
        file_menu.addAction(act_open_url)

        file_menu.addSeparator()

        act_snapshot = QAction("Take &Snapshot", self)
        act_snapshot.setShortcut(QKeySequence("Ctrl+S"))
        act_snapshot.triggered.connect(self.take_snapshot)
        file_menu.addAction(act_snapshot)

        act_trim = QAction("✂️ Export &Lossless Clip...", self)
        act_trim.setShortcut(QKeySequence("Ctrl+Shift+E"))
        act_trim.triggered.connect(self.open_trim_dialog)
        file_menu.addAction(act_trim)

        file_menu.addSeparator()

        act_exit = QAction("E&xit", self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # --- PLAYBACK MENU ---
        play_menu = mb.addMenu("&Playback")

        act_play_pause = QAction("Play / Pause", self)
        act_play_pause.setShortcut(QKeySequence("Space"))
        act_play_pause.triggered.connect(self.toggle_play_pause)
        play_menu.addAction(act_play_pause)

        act_stop = QAction("Stop", self)
        act_stop.setShortcut(QKeySequence("S"))
        act_stop.triggered.connect(self.stop_playback)
        play_menu.addAction(act_stop)

        play_menu.addSeparator()

        act_frame_next = QAction("Next Frame", self)
        act_frame_next.setShortcut(QKeySequence("."))
        act_frame_next.triggered.connect(self.frame_step)
        play_menu.addAction(act_frame_next)

        act_frame_prev = QAction("Previous Frame", self)
        act_frame_prev.setShortcut(QKeySequence(","))
        act_frame_prev.triggered.connect(self.frame_back_step)
        play_menu.addAction(act_frame_prev)

        act_seek_fwd = QAction("Jump Forward 10s", self)
        act_seek_fwd.setShortcut(QKeySequence("Right"))
        act_seek_fwd.triggered.connect(lambda: self.seek_relative(10))
        play_menu.addAction(act_seek_fwd)

        act_seek_back = QAction("Jump Backward 10s", self)
        act_seek_back.setShortcut(QKeySequence("Left"))
        act_seek_back.triggered.connect(lambda: self.seek_relative(-10))
        play_menu.addAction(act_seek_back)

        play_menu.addSeparator()

        act_goto = QAction("Go To...", self)
        act_goto.setShortcut(QKeySequence("Ctrl+G"))
        act_goto.triggered.connect(self.open_goto_dialog)
        play_menu.addAction(act_goto)

        # Chapters / Reels Submenu
        self.menu_chapters = play_menu.addMenu("📍 Chapters / Reels")
        self.menu_chapters.aboutToShow.connect(self._populate_chapters_menu)

        # A-B Repeat Submenu
        ab_menu = play_menu.addMenu("🔁 A-B Repeat Loop")
        act_set_a = QAction("Set Point A", self)
        act_set_a.setShortcut(QKeySequence("["))
        act_set_a.triggered.connect(self.action_set_ab_point_a)
        ab_menu.addAction(act_set_a)

        act_set_b = QAction("Set Point B (Start Loop)", self)
        act_set_b.setShortcut(QKeySequence("]"))
        act_set_b.triggered.connect(self.action_set_ab_point_b)
        ab_menu.addAction(act_set_b)

        act_clear_ab = QAction("Clear A-B Repeat", self)
        act_clear_ab.setShortcut(QKeySequence("\\"))
        act_clear_ab.triggered.connect(self.action_clear_ab_repeat)
        ab_menu.addAction(act_clear_ab)

        play_menu.addSeparator()

        speed_menu = play_menu.addMenu("Playback Speed (Pitch Preserved)")
        act_spd_up = QAction("Speed Up (+0.1x)", self)
        act_spd_up.setShortcut(QKeySequence("Ctrl+Up"))
        act_spd_up.triggered.connect(lambda: self.adjust_speed(0.1))
        speed_menu.addAction(act_spd_up)

        act_spd_down = QAction("Slow Down (-0.1x)", self)
        act_spd_down.setShortcut(QKeySequence("Ctrl+Down"))
        act_spd_down.triggered.connect(lambda: self.adjust_speed(-0.1))
        speed_menu.addAction(act_spd_down)

        act_spd_reset = QAction("Reset Speed (1.0x Normal)", self)
        act_spd_reset.setShortcut(QKeySequence("Ctrl+0"))
        act_spd_reset.triggered.connect(self.reset_speed)
        speed_menu.addAction(act_spd_reset)

        speed_menu.addSeparator()

        for spd in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0]:
            act_spd = QAction(f"{spd}x", self)
            act_spd.triggered.connect(lambda checked, s=spd: self.set_speed(s))
            speed_menu.addAction(act_spd)

        # --- AUDIO MENU ---
        audio_menu = mb.addMenu("&Audio")

        self.menu_audio_tracks = audio_menu.addMenu("🔊 Audio Tracks")
        self.menu_audio_tracks.aboutToShow.connect(self._populate_audio_tracks_menu)

        act_cycle_audio = QAction("Cycle Audio Track", self)
        act_cycle_audio.setShortcut(QKeySequence("#"))
        act_cycle_audio.triggered.connect(lambda: self._cycle_track("audio"))
        audio_menu.addAction(act_cycle_audio)

        audio_menu.addSeparator()

        act_load_audio = QAction("Add External &Audio File...", self)
        act_load_audio.setShortcut(QKeySequence("Ctrl+A"))
        act_load_audio.triggered.connect(self.action_load_external_audio)
        audio_menu.addAction(act_load_audio)

        act_audio_dialog = QAction("Audio Tracks & Equalizer...", self)
        act_audio_dialog.triggered.connect(self.action_audio_dialog)
        audio_menu.addAction(act_audio_dialog)

        # 3D IAB / Dolby Atmos Object Visualizer
        act_iab_vis = QAction("🎧 3D IAB / Dolby Atmos Object Visualizer...", self)
        act_iab_vis.setShortcut(QKeySequence("Ctrl+Alt+A"))
        act_iab_vis.triggered.connect(self.open_iab_visualizer)
        audio_menu.addAction(act_iab_vis)

        audio_menu.addSeparator()

        # Immersive Audio / IAB Submenu
        iab_menu = audio_menu.addMenu("🎧 Immersive Audio / IAB (Dolby Atmos)")

        act_iab_vis_sub = QAction("🌐 Open 3D Spatial Object HUD...", self)
        act_iab_vis_sub.triggered.connect(self.open_iab_visualizer)
        iab_menu.addAction(act_iab_vis_sub)
        iab_menu.addSeparator()
        
        act_iab_binaural = QAction("🎧 Binaural 3D Headphone Spatializer", self)
        act_iab_binaural.triggered.connect(lambda: self._set_iab_mode("binaural"))
        iab_menu.addAction(act_iab_binaural)

        act_iab_71 = QAction("🔊 Cinema 7.1 Immersive Downmix", self)
        act_iab_71.triggered.connect(lambda: self._set_iab_mode("cinema_71"))
        iab_menu.addAction(act_iab_71)

        act_iab_51 = QAction("🔊 Cinema 5.1 Surround Downmix", self)
        act_iab_51.triggered.connect(lambda: self._set_iab_mode("cinema_51"))
        iab_menu.addAction(act_iab_51)

        act_iab_dialog = QAction("🗣️ Stereo Dialog Focus (Center Boost + DRC)", self)
        act_iab_dialog.triggered.connect(lambda: self._set_iab_mode("stereo_dialog"))
        iab_menu.addAction(act_iab_dialog)

        act_iab_direct = QAction("🎵 Direct Multi-Channel Bed (14-Ch Unprocessed)", self)
        act_iab_direct.triggered.connect(lambda: self._set_iab_mode("pcm_direct"))
        iab_menu.addAction(act_iab_direct)

        audio_menu.addSeparator()

        act_audio_delay_plus = QAction("Audio Delay: +50ms", self)
        act_audio_delay_plus.setShortcut(QKeySequence("Ctrl+]"))
        act_audio_delay_plus.triggered.connect(lambda: self._adjust_audio_delay(0.05))
        audio_menu.addAction(act_audio_delay_plus)

        act_audio_delay_minus = QAction("Audio Delay: -50ms", self)
        act_audio_delay_minus.setShortcut(QKeySequence("Ctrl+["))
        act_audio_delay_minus.triggered.connect(lambda: self._adjust_audio_delay(-0.05))
        audio_menu.addAction(act_audio_delay_minus)

        audio_menu.addSeparator()

        act_mute = QAction("Mute", self)
        act_mute.setShortcut(QKeySequence("M"))
        act_mute.triggered.connect(self.toggle_mute)
        audio_menu.addAction(act_mute)

        # --- VIDEO MENU ---
        video_menu = mb.addMenu("&Video")

        self.menu_video_tracks = video_menu.addMenu("📹 Video Tracks / Angles")
        self.menu_video_tracks.aboutToShow.connect(self._populate_video_tracks_menu)

        act_cycle_video = QAction("Cycle Video Angle / Track", self)
        act_cycle_video.setShortcut(QKeySequence("_"))
        act_cycle_video.triggered.connect(lambda: self._cycle_track("video"))
        video_menu.addAction(act_cycle_video)

        video_menu.addSeparator()

        act_load_video = QAction("Add External Video Track / Multi-Angle...", self)
        act_load_video.triggered.connect(self.action_load_external_video)
        video_menu.addAction(act_load_video)

        ar_menu = video_menu.addMenu("Aspect Ratio")
        aspects = [
            ("Default / Container", "-1"),
            ("16:9 Widescreen", "16:9"),
            ("4:3 Standard", "4:3"),
            ("1.43:1 IMAX GT (Anamorphic Unsqueeze)", "1.43:1"),
            ("2.39:1 CinemaScope", "2.39:1"),
            ("1.85:1 Theatrical Flat", "1.85:1"),
        ]
        for label, ratio_val in aspects:
            act_ar = QAction(label, self)
            act_ar.triggered.connect(lambda checked, r=ratio_val: self._set_aspect_ratio(r))
            ar_menu.addAction(act_ar)

        # Pan & Scan (PnS) Frame Adjust Submenu
        self.menu_pns = video_menu.addMenu("PnS Frame Adjust")
        self._populate_pns_menu(self.menu_pns)

        # Stereoscopic 3D Submenu
        self.menu_stereo3d = video_menu.addMenu("🥽 Stereoscopic 3D")
        self.menu_stereo3d.aboutToShow.connect(lambda: self._populate_stereo3d_menu(self.menu_stereo3d))

        # 3D LUT (Look-Up Table) Submenu
        lut_menu = video_menu.addMenu("🎨 3D LUT Calibration (.cube / .3dl)")
        act_load_lut = QAction("Load Custom 3D LUT...", self)
        act_load_lut.triggered.connect(self.load_3d_lut)
        lut_menu.addAction(act_load_lut)

        self.act_enable_lut = QAction("Enable 3D LUT", self)
        self.act_enable_lut.setCheckable(True)
        self.act_enable_lut.setShortcut(QKeySequence("Ctrl+L"))
        self.act_enable_lut.triggered.connect(self.toggle_3d_lut)
        lut_menu.addAction(self.act_enable_lut)

        act_clear_lut = QAction("Clear 3D LUT", self)
        act_clear_lut.triggered.connect(self.clear_3d_lut)
        lut_menu.addAction(act_clear_lut)

        # Windows 11 Direct HDR Pass-Through
        self.act_hdr_passthrough = QAction("📺 Direct HDR Pass-Through (Windows 11 / HDR Displays)", self)
        self.act_hdr_passthrough.setCheckable(True)
        self.act_hdr_passthrough.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.act_hdr_passthrough.triggered.connect(self.toggle_hdr_passthrough)
        video_menu.addAction(self.act_hdr_passthrough)

        # Split-Screen Comparison Wipe
        self.act_split_wipe = QAction("🪟 Split-Screen Comparison Wipe", self)
        self.act_split_wipe.setCheckable(True)
        self.act_split_wipe.setShortcut(QKeySequence("Ctrl+W"))
        self.act_split_wipe.triggered.connect(self.toggle_split_wipe)
        video_menu.addAction(self.act_split_wipe)

        video_menu.addSeparator()

        # DCP JPEG 2000 Decoding Quality & Acceleration
        dcp_q_menu = video_menu.addMenu("DCP Decoding Quality & GPU Acceleration")
        self.dcp_q_actions = {}
        gpu_info = GPUDetector.get_info()
        has_gpu = gpu_info.has_nvjpeg2k or getattr(gpu_info, "has_grok", False) or getattr(gpu_info, "has_opencl", False)
        backend_tag = "nvJPEG2000" if gpu_info.has_nvjpeg2k else ("Grok OpenCL" if (getattr(gpu_info, "has_grok", False) or getattr(gpu_info, "has_opencl", False)) else "GPU")
        native_label = (
            f"⚡ Native 4K Master (4096x2160, {gpu_info.short_name} {backend_tag} @ 24fps)"
            if has_gpu else
            f"⚡ Native 4K Master (4096x2160, {gpu_info.short_name} GPU @ 24fps)"
        )
        qualities = [
            (native_label, 0),
            ("🎯 Pixel-Perfect 2K (2048x1080 Match)", 1),
            ("🎞️ 1K Wavelet Proxy (1024x540 Proxy)", 2),
        ]
        for label, lvl in qualities:
            act_q = QAction(label, self)
            act_q.setCheckable(True)
            act_q.setChecked(lvl == 0)
            act_q.triggered.connect(lambda checked, l=lvl: self._on_dcp_quality_selected(l))
            dcp_q_menu.addAction(act_q)
            self.dcp_q_actions[lvl] = act_q

        # --- SUBTITLES MENU ---
        sub_menu = mb.addMenu("&Subtitles")

        act_toggle_sub = QAction("Toggle Subtitles On/Off", self)
        act_toggle_sub.setShortcut(QKeySequence("V"))
        act_toggle_sub.triggered.connect(self.action_toggle_subtitles)
        sub_menu.addAction(act_toggle_sub)

        sub_menu.addSeparator()

        self.menu_sub_tracks = sub_menu.addMenu("💬 Subtitle Tracks")
        self.menu_sub_tracks.aboutToShow.connect(self._populate_sub_tracks_menu)

        act_cycle_sub = QAction("Next Subtitle Track", self)
        act_cycle_sub.setShortcut(QKeySequence("J"))
        act_cycle_sub.triggered.connect(lambda: self._cycle_track("sub", "up"))
        sub_menu.addAction(act_cycle_sub)

        act_cycle_sub_prev = QAction("Previous Subtitle Track", self)
        act_cycle_sub_prev.setShortcut(QKeySequence("Shift+J"))
        act_cycle_sub_prev.triggered.connect(lambda: self._cycle_track("sub", "down"))
        sub_menu.addAction(act_cycle_sub_prev)

        sub_menu.addSeparator()

        act_load_sub = QAction("Add External &Subtitle File...", self)
        act_load_sub.setShortcut(QKeySequence("Ctrl+U"))
        act_load_sub.triggered.connect(self.action_load_external_sub)
        sub_menu.addAction(act_load_sub)

        act_sub_dialog = QAction("Subtitle Tracks & Sync...", self)
        act_sub_dialog.triggered.connect(self.action_sub_dialog)
        sub_menu.addAction(act_sub_dialog)

        sub_menu.addSeparator()

        act_sub_delay_plus = QAction("Subtitle Delay: +100ms", self)
        act_sub_delay_plus.setShortcut(QKeySequence("X"))
        act_sub_delay_plus.triggered.connect(lambda: self._adjust_sub_delay(0.1))
        sub_menu.addAction(act_sub_delay_plus)

        act_sub_delay_minus = QAction("Subtitle Delay: -100ms", self)
        act_sub_delay_minus.setShortcut(QKeySequence("Z"))
        act_sub_delay_minus.triggered.connect(lambda: self._adjust_sub_delay(-0.1))
        sub_menu.addAction(act_sub_delay_minus)

        # --- COLOR & TONEMAPPING MENU ---
        color_menu = mb.addMenu("&Color && Tonemap")

        from core.tonemap_engine import TonemapEngine
        _menu_groups = [
            ["auto", "passthrough"],
            ["dvis_dcp_sdr", "dvis_dcp_hdr10"],
            ["dci_xyz_srgb"],
            ["dv_p5_sdr", "dv_p5_hdr10", "dv_p5_hlg"],
            ["dv_p20_rpu_sdr", "dv_p20_rpu_hdr"],
            ["hlg_sdr", "hdr10_sdr", "hdr10plus_sdr", "hdr10_hdr", "hdr10plus_hdr"],
            ["spline_sdr", "filmic_hable", "mobius_sdr", "reinhard_sdr"],
        ]
        for gi, group in enumerate(_menu_groups):
            if gi:
                color_menu.addSeparator()
            for pkey in group:
                if pkey not in TonemapEngine.PRESETS:
                    continue
                title = TonemapControlDrawer.PRESET_TITLES.get(pkey, pkey)
                act = QAction(f"{title}   ({TonemapEngine.PRESETS[pkey]})", self)
                act.triggered.connect(lambda _=False, k=pkey: self._apply_tonemap_preset(k))
                color_menu.addAction(act)

        color_menu.addSeparator()

        act_tonemap_panel = QAction("Open Color Science Drawer", self)
        act_tonemap_panel.setShortcut(QKeySequence("T"))
        act_tonemap_panel.triggered.connect(self.toggle_tonemap_dock)
        color_menu.addAction(act_tonemap_panel)

        # --- TOOLS MENU ---
        tools_menu = mb.addMenu("&Tools")

        act_tracks_dialog = QAction("🔀 Track & Stream Selector...", self)
        act_tracks_dialog.setShortcut(QKeySequence("Ctrl+T"))
        act_tracks_dialog.triggered.connect(self.action_track_selector)
        tools_menu.addAction(act_tracks_dialog)

        tools_menu.addSeparator()

        act_codec_info = QAction("ℹ️ Media & Codec Information", self)
        act_codec_info.setShortcut(QKeySequence("Ctrl+I"))
        act_codec_info.triggered.connect(self.open_codec_info_dialog)
        tools_menu.addAction(act_codec_info)

        act_dcp_inspector = QAction("🎬 DCP Cinema Package Inspector...", self)
        act_dcp_inspector.triggered.connect(self.open_dcp_dialog)
        tools_menu.addAction(act_dcp_inspector)

        act_stats = QAction("📊 Video Rendering Stats Overlay", self)
        act_stats.setShortcut(QKeySequence("Shift+I"))
        act_stats.triggered.connect(self.engine.toggle_stats_overlay)
        tools_menu.addAction(act_stats)

        tools_menu.addSeparator()

        gpu_info = GPUDetector.get_info()
        has_gpu = gpu_info.has_nvjpeg2k or getattr(gpu_info, "has_grok", False) or getattr(gpu_info, "has_opencl", False)
        backend_name = "NVIDIA nvJPEG2000" if gpu_info.has_nvjpeg2k else ("Grok OpenCL" if (getattr(gpu_info, "has_grok", False) or getattr(gpu_info, "has_opencl", False)) else "GPU Acceleration")
        bench_label = (
            f"⚡ Benchmark {backend_name} ({gpu_info.short_name})..."
            if has_gpu else
            f"⚡ Benchmark GPU Acceleration ({gpu_info.short_name})..."
        )
        act_nvjpeg2k = QAction(bench_label, self)
        act_nvjpeg2k.triggered.connect(self.action_benchmark_nvjpeg2k)
        tools_menu.addAction(act_nvjpeg2k)

        # --- VIEW MENU ---
        view_menu = mb.addMenu("&View")

        act_fs = QAction("Fullscreen Toggle", self)
        act_fs.setShortcut(QKeySequence("F11"))
        act_fs.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(act_fs)

        act_ontop = QAction("Always on Top", self)
        act_ontop.setCheckable(True)
        act_ontop.triggered.connect(self.toggle_always_on_top)
        view_menu.addAction(act_ontop)

        # Window Size Submenu (MPC-HC / KMPlayer style)
        winsize_menu = view_menu.addMenu("📐 Window Size")
        act_fit = QAction("Fit to Video / Screen", self)
        act_fit.setShortcut(QKeySequence("Ctrl+0"))
        act_fit.triggered.connect(lambda: self.fit_window_to_video(1.0))
        winsize_menu.addAction(act_fit)

        act_orig = QAction("Original 100%", self)
        act_orig.setShortcut(QKeySequence("Ctrl+1"))
        act_orig.triggered.connect(lambda: self.fit_window_to_video(1.0))
        winsize_menu.addAction(act_orig)

        act_half = QAction("Half 50%", self)
        act_half.setShortcut(QKeySequence("Ctrl+2"))
        act_half.triggered.connect(lambda: self.fit_window_to_video(0.5))
        winsize_menu.addAction(act_half)

        act_double = QAction("Double 200%", self)
        act_double.setShortcut(QKeySequence("Ctrl+3"))
        act_double.triggered.connect(lambda: self.fit_window_to_video(2.0))
        winsize_menu.addAction(act_double)

        view_menu.addSeparator()

        # Theme Submenu
        theme_menu = view_menu.addMenu("🎨 Theme")
        self.act_theme_minimalist = QAction("Minimalist Studio Dark", self)
        self.act_theme_minimalist.setCheckable(True)
        self.act_theme_minimalist.setChecked(True)
        self.act_theme_minimalist.triggered.connect(lambda: self.set_theme("minimalist"))
        theme_menu.addAction(self.act_theme_minimalist)

        self.act_theme_cyberpunk = QAction("Cyberpunk Dark", self)
        self.act_theme_cyberpunk.setCheckable(True)
        self.act_theme_cyberpunk.setChecked(False)
        self.act_theme_cyberpunk.triggered.connect(lambda: self.set_theme("cyberpunk"))
        theme_menu.addAction(self.act_theme_cyberpunk)

        view_menu.addSeparator()
        view_menu.addAction(self.iptv_dock.toggleViewAction())
        view_menu.addAction(self.playlist_dock.toggleViewAction())
        view_menu.addAction(self.tonemap_dock.toggleViewAction())

        # Register all menu shortcuts directly on MainWindow so hiding menuBar() in fullscreen never disables them
        for menu in mb.findChildren(QMenu):
            for act in menu.actions():
                if not act.shortcut().isEmpty():
                    self.addAction(act)

    def _init_status_bar(self):
        sb = self.statusBar()
        self.lbl_status_media = QLabel("No Media Loaded")
        self.lbl_status_media.setStyleSheet("color: #9ca3af; font-weight: 500;")
        sb.addWidget(self.lbl_status_media, 1)

        self.lbl_status_iab = QLabel("IAB: Inactive")
        self.lbl_status_iab.setStyleSheet("color: #cbd5e1; font-weight: 600; margin-right: 12px;")
        self.lbl_status_iab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_status_iab.setToolTip("Click to open 3D IAB / Dolby Atmos Object Visualizer (Ctrl+Alt+A)")
        self.lbl_status_iab.mousePressEvent = lambda e: self.open_iab_visualizer()
        sb.addPermanentWidget(self.lbl_status_iab)

        self.lbl_status_codec = QLabel("Codec: None")
        self.lbl_status_codec.setStyleSheet("color: #e4e4e7; font-weight: 600; margin-right: 12px;")
        sb.addPermanentWidget(self.lbl_status_codec)

        gpu_info = GPUDetector.get_info()
        self.lbl_status_hw = QLabel(f"⚡ {gpu_info.short_name}")
        self.lbl_status_hw.setStyleSheet("color: #a1a1aa; font-weight: 600; margin-right: 12px;")
        self.lbl_status_hw.setToolTip(f"Active Hardware GPU: {gpu_info.name}")
        sb.addPermanentWidget(self.lbl_status_hw)

        self.lbl_status_color = QLabel("Color: Auto")
        self.lbl_status_color.setStyleSheet("color: #cbd5e1; font-weight: 600; margin-right: 12px;")
        sb.addPermanentWidget(self.lbl_status_color)

    def _init_shortcuts(self):
        # Quick hotkey for fullscreen toggle
        act_f = QAction(self)
        act_f.setShortcut(QKeySequence("F"))
        act_f.triggered.connect(self.toggle_fullscreen)
        self.addAction(act_f)

        # Escape key exits fullscreen (never enters fullscreen)
        self.act_escape_fs = QAction("Exit Fullscreen", self)
        self.act_escape_fs.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.act_escape_fs.triggered.connect(self.exit_fullscreen)
        self.addAction(self.act_escape_fs)

    def set_theme(self, theme_name: str):
        """Switch player theme between 'minimalist' and 'cyberpunk'."""
        self.current_theme = theme_name
        is_minimalist = (theme_name == "minimalist")
        if hasattr(self, "act_theme_minimalist"):
            self.act_theme_minimalist.setChecked(is_minimalist)
        if hasattr(self, "act_theme_cyberpunk"):
            self.act_theme_cyberpunk.setChecked(not is_minimalist)
        self.setStyleSheet(get_theme_qss(theme_name))
        theme_label = "Minimalist Studio Dark" if is_minimalist else "Cyberpunk Dark"
        self.show_toast(f"Theme: {theme_label}")

    def _connect_engine_signals(self):
        # Use thread-safe Qt Signals to marshal MPV background thread events to the Qt Main Thread
        self.engine.bridge.time_pos_signal.connect(self._on_engine_time)
        self.engine.bridge.duration_signal.connect(self._on_engine_duration)
        self.engine.bridge.pause_signal.connect(self._on_engine_pause)
        self.engine.bridge.file_loaded_signal.connect(self._on_engine_file_loaded)
        self.engine.bridge.playback_end_signal.connect(self._on_engine_playback_end)
        self.engine.bridge.iab_status_signal.connect(self._on_iab_status_changed)
        self.engine.bridge.cache_duration_signal.connect(self._on_engine_cache_duration)
        self.engine.bridge.cache_buffering_signal.connect(self._on_engine_cache_buffering)
        self.engine.bridge.nv_frame_ready.connect(self.video_widget.present_frame)
        self.engine.bridge.nv_active_signal.connect(self._on_nv_active_changed)
        self.engine.bridge.nv_fps_signal.connect(self._on_nv_fps_updated)
        self.engine.bridge.anamorphic_unsqueeze_signal.connect(self.video_widget.set_anamorphic_unsqueeze)
        self.engine.bridge.track_list_signal.connect(self._on_engine_track_list_changed)
        self.engine.bridge.tonemap_status_signal.connect(self._on_tonemap_status_changed)
        self.engine.bridge.defect_detected_signal.connect(self._handle_defect_detected)
        self.engine.bridge.video_cover_signal.connect(self.video_widget.set_switch_cover)
        self._last_auto_color_toast = None

    def _on_engine_track_list_changed(self, tracks: list):
        if not tracks:
            # Immediately clear dynamic track menus when media is unloaded/reset
            self.menu_video_tracks.clear()
            self.menu_audio_tracks.clear()
            self.menu_sub_tracks.clear()

    def _on_nv_active_changed(self, active: bool):
        if active:
            gpu_info = GPUDetector.get_info()
            self.video_widget.show_nv_viewport()
            self._update_source_codec_display(f"⚡ NVJPEG2000 4K @ 24fps [{gpu_info.short_name} GPU] (12-bit XYZ)")
            self.show_toast(f"⚡ Active: NVIDIA nvJPEG2000 Hardware Acceleration ({gpu_info.short_name})")
        else:
            self.video_widget.show_mpv_viewport()

    def _on_nv_fps_updated(self, fps: float):
        if self.engine.nvjpeg2k_active:
            gpu_info = GPUDetector.get_info()
            self.lbl_status_hw.setText(f"⚡ {gpu_info.short_name} | {fps:.1f} fps")

    def _on_tonemap_status_changed(self, status: dict):
        label = status.get("preset_label", "Auto")
        self.lbl_status_color.setText(f"Color: {label}")
        if hasattr(self, "osc") and self.osc:
            self.osc.set_color_status(label)
        if hasattr(self, "tonemap_drawer") and self.tonemap_drawer:
            self.tonemap_drawer._update_status_display()
        auto_summary = status.get("auto_conversion_summary")
        if auto_summary and auto_summary != getattr(self, "_last_auto_color_toast", None):
            self._last_auto_color_toast = auto_summary
            self.show_toast(f"🎨 {auto_summary}")

    def _update_source_codec_display(self, codec_text: str):
        if "av2" in codec_text.lower():
            from core.dav2d_engine import Dav2dEngine
            dav2d = Dav2dEngine.get_instance()
            if dav2d.is_available():
                codec_text = f"⚡ AV2 | dav2d ({dav2d.get_version()})"
            else:
                codec_text = f"{codec_text} | dav2d bridge"
        self.current_source_codec_str = codec_text
        self.lbl_status_codec.setText(codec_text)
        self.osc.set_source_codec(codec_text)

    def _handle_defect_detected(self, defect_type: str, pts: float):
        """
        Automated self-healing recovery mechanism:
        When a persistent render defect (solid white, blue dominance, fluorescent green)
        is confirmed across 3 consecutive frame samples during active playback,
        cleanly restart the mpv engine, reinitialize decoders, and reload the file of its own accord
        at the current position.
        """
        now = time.time()
        if not hasattr(self, "_defect_strikes"):
            self._defect_strikes = {"type": None, "count": 0, "first_time": 0.0, "last_time": 0.0, "pts": -1.0}

        # Multi-strike confirmation filter: require 3 consecutive samples spaced > 0.6s apart
        # within a 6-second window at approximately the same timeline region
        if (
            self._defect_strikes["type"] != defect_type
            or (now - self._defect_strikes["last_time"]) > 6.0
            or abs(pts - self._defect_strikes["pts"]) > 5.0
        ):
            self._defect_strikes = {
                "type": defect_type,
                "count": 1,
                "first_time": now,
                "last_time": now,
                "pts": pts,
            }
            return
        else:
            if now - self._defect_strikes["last_time"] < 0.6:
                return
            self._defect_strikes["count"] += 1
            self._defect_strikes["last_time"] = now
            if self._defect_strikes["count"] < 3:
                return

        # 3-strike threshold reached! Reset strike counter
        self._defect_strikes["count"] = 0

        if not hasattr(self, "_last_defect_recovery"):
            self._last_defect_recovery = {"time": 0.0, "pts": -1.0, "count": 0}

        # Guard against infinite recovery loops (max 2 restarts within 30s for the same scene position)
        if (
            now - self._last_defect_recovery["time"] < 30.0
            and abs(pts - self._last_defect_recovery["pts"]) < 4.0
        ):
            self._last_defect_recovery["count"] += 1
            if self._last_defect_recovery["count"] > 2:
                return
        else:
            self._last_defect_recovery = {"time": now, "pts": pts, "count": 1}

        media_uri = getattr(self, "current_media_path", None)
        if not media_uri or not os.path.exists(media_uri):
            return

        self.show_toast(f"⚠️ Confirmed render defect ({defect_type}). Auto-restarting engine...")

        # 1. Capture exact playback state
        saved_pos = max(0.0, float(pts))
        saved_paused = getattr(self.engine, "is_paused", False)
        saved_audio = self.engine.get_selected_track_id("audio")
        saved_sub = self.engine.get_selected_track_id("sub")
        saved_sub_disabled = getattr(self.engine, "subtitles_user_disabled", False)

        # 2. Cleanly restart the mpv player and decoder pipeline
        self.engine.reinit_player()
        if hasattr(self, "tonemap_drawer") and self.tonemap_drawer:
            self.tonemap_drawer.engine = self.engine.tonemap_engine

        # 3. Reload the file of its own accord at exact position
        self.engine.play(media_uri, start_pos=saved_pos)
        if saved_paused:
            self.engine.pause()
        if saved_sub_disabled:
            self.engine.disable_subtitles()
        elif saved_sub is not None:
            self.engine.set_track("sub", saved_sub)
        if saved_audio is not None:
            self.engine.set_track("audio", saved_audio)

        mins = int(saved_pos // 60)
        secs = int(saved_pos % 60)
        self.show_toast(f"✅ Playback cleanly auto-recovered at {mins:02d}:{secs:02d}.")

    # Playback Actions
    def play_media(self, uri: str, title: str = "", item_type: str = "file"):
        # Ensure decoders and video output pipeline are verified and ready before loading media
        self.engine.ensure_decoders_ready()

        # Discard all contents and tracks loaded for the previous file
        self.menu_video_tracks.clear()
        self.menu_audio_tracks.clear()
        self.menu_sub_tracks.clear()
        self.video_widget.set_subtitle_engine(None)
        if getattr(self, "iab_visualizer", None) and self.iab_visualizer.isVisible():
            self.iab_visualizer.set_metadata(None)
        self.osc.update_position(0.0, 0.0, 0.0)
        self._update_source_codec_display("Loading...")
        self._last_auto_color_toast = None

        self.current_media_path = uri
        self.playlist_mgr.add_item(uri, title, item_type)
        self.playlist_drawer.refresh_list()
        self.engine.play(uri)
        self.lbl_status_media.setText(f"Playing: {title or os.path.basename(uri)}")
        self.video_widget.hide_timer.start()

        if item_type == "iptv" or uri.startswith(("http://", "https://", "rtmp://", "rtsp://")):
            self._update_source_codec_display("Live Stream")
        else:
            try:
                probe = MediaInspector.inspect_file(uri)
                summary = MediaInspector.get_source_summary(probe)
                self._update_source_codec_display(summary)
            except Exception:
                self._update_source_codec_display("Media File")

    def play_iptv_channel(self, channel: IPTVChannel):
        self.show_toast(f"Tuning Live TV: {channel.name} ({channel.resolution})")
        self.play_media(channel.url, channel.name, "iptv")
        self._update_source_codec_display(f"Live Stream | {channel.resolution}")

    @staticmethod
    def _dcp_badge_suffix(cpl) -> str:
        badges = []
        if cpl and getattr(cpl, "is_dolby_vision", False):
            badges.append("💎 Dolby Cinema EDR 108nits")
        if cpl and getattr(cpl, "is_3d", False):
            badges.append("3D Cinema")
        if cpl and getattr(cpl, "is_imax", False):
            badges.append("IMAX")
        if cpl and getattr(cpl, "unsqueeze_to_143", False):
            badges.append("1.43:1 GT Unsqueeze")
        if cpl and getattr(cpl, "imax_audio_format", ""):
            badges.append(cpl.imax_audio_format)
        return f" [{' | '.join(badges)}]" if badges else " [Rec.709]"

    @staticmethod
    def _dcp_source_notes(cpl) -> str:
        if not cpl:
            return ""
        dvis_note = " | 💎 108-nit XYZ-PQ EDR" if getattr(cpl, "is_dolby_vision", False) else ""
        ar_note = " | 1.43:1 Anamorphic 4096x2864" if getattr(cpl, "unsqueeze_to_143", False) else ""
        aud_note = f" | {cpl.imax_audio_format}" if getattr(cpl, "imax_audio_format", "") else ""
        return f"{dvis_note}{ar_note}{aud_note}"

    def play_dcp_folder(self, folder_path: str, start_reel_index: int = 0):
        try:
            # Discard all contents and tracks loaded for the previous file
            self.menu_video_tracks.clear()
            self.menu_audio_tracks.clear()
            self.menu_sub_tracks.clear()
            if getattr(self, "iab_visualizer", None) and self.iab_visualizer.isVisible():
                self.iab_visualizer.set_metadata(None)
            self.osc.update_position(0.0, 0.0, 0.0)
            self._update_source_codec_display("Loading DCP...")

            self.current_media_path = folder_path
            pkg = DCPParser.parse(folder_path)
            cpl = pkg.default_composition
            safe_reel_idx = max(0, min(start_reel_index, len(cpl.reels) - 1)) if (cpl and cpl.reels) else 0
            self.engine.play_dcp_package(pkg, 0, safe_reel_idx)
            self.lbl_status_media.setText(f"DCP Cinema: {cpl.title}")
            self.show_toast(f"Loaded DCP: {cpl.title}{self._dcp_badge_suffix(cpl)}")
            if cpl and getattr(cpl, "is_dolby_vision", False):
                preset = "dvis_dcp_hdr10" if self.engine.tonemap_engine.display_is_hdr else "dvis_dcp_sdr"
                self.lbl_status_color.setText("Color: 💎 DVis DCP -> " + ("HDR10" if preset == "dvis_dcp_hdr10" else "Rec.709 SDR"))
                self.osc.set_color_status("💎 DVis DCP -> " + ("HDR10" if preset == "dvis_dcp_hdr10" else "SDR"))
            else:
                self.lbl_status_color.setText("Color: DCI-XYZ -> Rec.709")
                self.osc.set_color_status("DCI-XYZ -> Rec.709")
            self.video_widget.hide_timer.start()

            if self.engine.dcp_sub_engine:
                self.video_widget.set_subtitle_engine(self.engine.dcp_sub_engine)
            else:
                self.video_widget.set_subtitle_engine(None)

            # Extract source codec details from DCP inspection
            if self.engine.nvjpeg2k_active:
                gpu_info = GPUDetector.get_info()
                self._update_source_codec_display(
                    f"⚡ NVJPEG2000 4K @ 24fps [{gpu_info.short_name} GPU]{self._dcp_source_notes(cpl)}"
                )
            else:
                try:
                    probe = MediaInspector.inspect_dcp(folder_path)
                    codec_summary = MediaInspector.get_source_summary(probe)
                    self._update_source_codec_display(codec_summary)
                except Exception:
                    fps = cpl.fps if cpl else 24.0
                    self._update_source_codec_display(f"JPEG 2000 4K @ {fps:.2f}fps (12-bit XYZ)")

            # Set reel boundary chapters on seekbar
            chapters = self.engine.get_chapters()
            self.osc.set_chapters(chapters)
            if hasattr(self, "menu_chapters"):
                self._populate_chapters_menu()

            # Set first picture MXF for thumbnail preview
            if cpl and cpl.reels and cpl.reels[0].picture_path:
                ThumbnailManager.get_instance().set_source(cpl.reels[0].picture_path)
        except Exception as e:
            QMessageBox.critical(self, "DCP Parse Error", f"Failed to parse DCP package:\n{e}")

    def toggle_play_pause(self):
        self.engine.toggle_pause()
        self.osc.set_play_state(not self.engine.is_paused)
        self.show_toast("Paused" if self.engine.is_paused else "Playing")

    def stop_playback(self):
        self.engine.stop()
        self.video_widget.set_subtitle_engine(None)
        self.osc.set_play_state(False)
        self.lbl_status_media.setText("Stopped")

    def seek_relative(self, seconds: float):
        self.engine.seek(seconds, relative=True)
        self.show_toast(f"Seek: {'+' if seconds > 0 else ''}{int(seconds)}s")

    def seek_absolute(self, seconds: float):
        self.engine.seek(seconds, relative=False)

    def frame_step(self):
        self.engine.frame_step()
        self.show_toast("Frame Step Forward (+1 Frame)")

    def frame_back_step(self):
        self.engine.frame_back_step()
        self.show_toast("Frame Step Backward (-1 Frame)")

    def set_speed(self, speed: float):
        self.engine.set_speed(speed)
        self.show_toast(f"Speed: {speed}x")

    def set_volume(self, val: int):
        self.engine.set_volume(val)

    def toggle_mute(self):
        self.engine.toggle_mute()
        is_muted = getattr(self.engine.player, "mute", False)
        self.osc.set_mute_state(is_muted)
        self.show_toast("Audio Muted" if is_muted else "Audio Unmuted")

    def take_snapshot(self):
        # 1. Determine if active video exists
        has_media = bool(self.current_media_path or self.engine.is_dcp_playing or self.engine.current_uri)
        has_nv_frame = bool(
            self.engine.nvjpeg2k_active
            and getattr(self.video_widget, "nv_viewport", None)
            and self.video_widget.nv_viewport.current_frame
        )
        if not has_media and not has_nv_frame:
            self.show_toast("⚠️ No active video frame to capture")
            return

        # 2. Compute default save directory and default filename
        default_dir = getattr(self, "_last_snapshot_dir", None)
        if not default_dir or not os.path.isdir(default_dir):
            default_dir = os.path.join(os.path.expanduser("~"), "Pictures")
        os.makedirs(default_dir, exist_ok=True)

        # Determine source video dimensions
        src_w, src_h = 3840, 2160
        active_w, active_h = src_w, src_h
        if has_nv_frame:
            frame = self.video_widget.nv_viewport.current_frame
            if frame and hasattr(self.video_widget.nv_viewport, "unsqueeze_qimage"):
                frame = self.video_widget.nv_viewport.unsqueeze_qimage(frame)
            src_w, src_h = frame.width(), frame.height()
            from core.media_inspector import MediaInspector
            top, bottom, left, right = MediaInspector.get_active_image_bounds(frame)
            if top > 0 or bottom < src_h or left > 0 or right < src_w:
                active_w, active_h = (right - left), (bottom - top)
            else:
                active_w, active_h = src_w, src_h
        else:
            vp = getattr(self.engine.player, "video_params", None) or {}
            w_val = vp.get("w") or getattr(self.engine.player, "dwidth", 0)
            h_val = vp.get("h") or getattr(self.engine.player, "dheight", 0)
            if w_val and h_val:
                src_w, src_h = int(w_val), int(h_val)
            # Check if active anamorphic unsqueeze or aspect ratio override is set
            target_ar = self.engine.get_target_aspect_ratio() if hasattr(self.engine, "get_target_aspect_ratio") else None
            if target_ar and target_ar > 0 and src_w > 0 and src_h > 0:
                cur_ar = src_w / src_h
                if abs(cur_ar - target_ar) > 0.02:
                    if abs(target_ar - 1.43) < 0.02:
                        const_w = 4096 if src_w == 4096 else (2048 if src_w == 2048 else src_w)
                        src_h = int(round(const_w / 1.43))
                        src_w = const_w
                    else:
                        src_h = int(round(src_w / target_ar))
            active_w, active_h = src_w, src_h

        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        title_hint = "Snapshot"
        if self.engine.is_dcp_playing and self.engine.active_cpl and self.engine.active_cpl.title:
            clean_title = "".join(c for c in self.engine.active_cpl.title if c.isalnum() or c in (" ", "_", "-")).strip()
            if clean_title:
                title_hint = clean_title.replace(" ", "_")
        elif self.current_media_path:
            base = os.path.splitext(os.path.basename(self.current_media_path))[0]
            clean_base = "".join(c for c in base if c.isalnum() or c in (" ", "_", "-")).strip()
            if clean_base:
                title_hint = clean_base.replace(" ", "_")

        default_filename = f"{title_hint}_{src_w}x{src_h}_{timestamp}.png"
        default_full_path = os.path.join(default_dir, default_filename)

        # 3. Prompt user for save destination (Defaults to exact source resolution)
        file_filters = [
            f"Lossless PNG - Original Resolution ({src_w}x{src_h}) (*.png)",
        ]
        if has_nv_frame and (active_w != src_w or active_h != src_h):
            file_filters.append(f"Lossless PNG - Cropped Active Area ({active_w}x{active_h}) (*.png)")
        else:
            file_filters.append("Lossless PNG - Cropped Active Area (*.png)")

        file_filters.extend([
            f"Uncompressed TIFF - Original Resolution ({src_w}x{src_h}) (*.tiff *.tif)",
            "Uncompressed TIFF - Cropped Active Area (*.tiff *.tif)",
            f"Uncompressed BMP - Original Resolution ({src_w}x{src_h}) (*.bmp)",
            "All Files (*.*)"
        ])
        filter_str = ";;".join(file_filters)

        save_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            f"Save Tonemapped Snapshot ({src_w}x{src_h})",
            default_full_path,
            filter_str
        )
        if not save_path:
            return  # User cancelled

        should_crop = "Cropped Active Area" in selected_filter

        # Remember directory for subsequent snapshots
        self._last_snapshot_dir = os.path.dirname(save_path)
        os.makedirs(self._last_snapshot_dir, exist_ok=True)

        ext = os.path.splitext(save_path)[1].lower()
        if not ext:
            save_path += ".png"
            ext = ".png"

        # 4. Save frame based on active pipeline
        if has_nv_frame:
            frame = self.video_widget.nv_viewport.current_frame
            if frame and hasattr(self.video_widget.nv_viewport, "unsqueeze_qimage"):
                frame = self.video_widget.nv_viewport.unsqueeze_qimage(frame)

            if should_crop:
                from core.media_inspector import MediaInspector
                frame = MediaInspector.crop_active_image_area(frame)

            saved_w = frame.width()
            saved_h = frame.height()

            # Convert QImage to canonical RGBA8888 byte-order so R and B channels are never inverted
            import numpy as np
            conv = frame.convertToFormat(QImage.Format.Format_RGBA8888)
            ptr = conv.constBits()
            ptr.setsize(conv.sizeInBytes())
            arr = np.frombuffer(ptr, np.uint8).reshape((conv.height(), conv.width(), 4))

            from PIL import Image
            pil_img = Image.fromarray(arr[:, :, :3])

            if ext in (".tif", ".tiff"):
                pil_img.save(save_path, "TIFF", compression=None)
            elif ext == ".bmp":
                pil_img.save(save_path, "BMP")
            else:
                pil_img.save(save_path, "PNG", compress_level=0)

            mode_label = "Active Area" if should_crop else "Original Resolution"
            self.show_toast(f"📸 Tonemapped {mode_label} ({saved_w}x{saved_h}) Saved: {os.path.basename(save_path)}")
            return save_path
        else:
            path = self.engine.take_screenshot(save_path, crop_active_area=should_crop)
            if path and os.path.exists(path):
                from PIL import Image
                with Image.open(path) as im:
                    w, h = im.size
                mode_label = "Active Area" if should_crop else "Original Resolution"
                self.show_toast(f"📸 Tonemapped {mode_label} ({w}x{h}) Saved: {os.path.basename(path)}")
                return path
            else:
                self.show_toast("⚠️ Failed to capture snapshot")
                return ""

    # Engine Callbacks
    def _on_engine_time(self, t: float):
        dur = self.engine.get_duration()
        buf_dur = self.engine.get_cache_duration()
        self.osc.update_position(t, dur, buf_dur)
        if getattr(self, "iab_visualizer", None) and self.iab_visualizer.isVisible():
            self.iab_visualizer.update_time_pos(t)

    def _on_engine_duration(self, d: float):
        pos = self.engine.get_current_pts()
        buf_dur = self.engine.get_cache_duration()
        self.osc.update_position(pos, d, buf_dur)

    def _on_engine_cache_duration(self, buf_sec: float):
        pos = self.engine.get_current_pts()
        dur = self.engine.get_duration()
        self.osc.update_position(pos, dur, buf_sec)

    def _on_engine_cache_buffering(self, is_buffering: bool):
        if is_buffering:
            self.show_toast("⚡ Pre-buffering memory cache...")

    def _on_engine_pause(self, is_paused: bool):
        self.osc.set_play_state(not is_paused)
        if is_paused:
            self.osc.fade_in()
            self.video_widget.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.video_widget.hide_timer.start()

    def _set_aspect_ratio(self, ratio_val: str):
        self.engine.set_aspect_ratio(ratio_val)
        if ratio_val == "-1":
            self.video_widget.set_anamorphic_unsqueeze(self.engine.is_anamorphic_143)
        self.video_widget.set_aspect_override(ratio_val)
        self.show_toast("Aspect Ratio: Default" if ratio_val == "-1" else f"Aspect Ratio: {ratio_val}")

    def _on_engine_file_loaded(self, uri: str):
        self.osc.set_play_state(True)
        self.lbl_status_media.setText(f"Loaded: {os.path.basename(uri)}")
        
        # Probe source codec if not already populated or if playing DCP
        if self.engine.nvjpeg2k_active:
            gpu_info = GPUDetector.get_info()
            self._update_source_codec_display(
                f"⚡ NVJPEG2000 4K @ 24fps [{gpu_info.short_name} GPU]{self._dcp_source_notes(self.engine.active_cpl)}"
            )
        elif self.engine.is_dcp_playing:
            fps = self.engine.active_cpl.fps if (self.engine.active_cpl and self.engine.active_cpl.fps) else 24.0
            self._update_source_codec_display(f"JPEG 2000 4K @ {fps:.0f}fps (12-bit XYZ)")
        elif not self.current_source_codec_str and os.path.exists(uri):
            try:
                probe = MediaInspector.inspect_file(uri)
                summary = MediaInspector.get_source_summary(probe)
                self._update_source_codec_display(summary)
            except Exception:
                pass

        # Update chapters and seekbar markers
        chapters = self.engine.get_chapters()
        self.osc.set_chapters(chapters)
        if hasattr(self, "menu_chapters"):
            self._populate_chapters_menu()

        # Update seekbar hover thumbnail source
        ThumbnailManager.get_instance().set_source(uri)

        # Auto-fit window to video resolution and aspect ratio (MPC-HC / KMPlayer behavior)
        QTimer.singleShot(150, lambda: self.fit_window_to_video(1.0))

    def fit_window_to_video(self, scale: float = 1.0):
        """Auto-fit player window to video resolution and aspect ratio (like MPC-HC / KMPlayer)."""
        if self.isFullScreen() or self.isMaximized():
            return

        vw = 0
        vh = 0
        if self.engine and self.engine.player:
            try:
                vp = self.engine.player.video_params
                if vp:
                    vw = int(vp.get("dw") or vp.get("w") or 0)
                    vh = int(vp.get("dh") or vp.get("h") or 0)
            except Exception:
                pass

        if vw <= 0 or vh <= 0:
            probe_track = getattr(self.engine, "cached_probe_v_track", None)
            if probe_track:
                vw = int(probe_track.get("width") or 0)
                vh = int(probe_track.get("height") or 0)

        if vw <= 0 or vh <= 0:
            return

        screen = self.screen() or QGuiApplication.primaryScreen()
        if not screen:
            return

        avail = screen.availableGeometry()
        max_w = int(avail.width() * 0.90)
        max_h = int(avail.height() * 0.90)

        chrome_h = 0
        if self.menuBar() and self.menuBar().isVisible():
            chrome_h += self.menuBar().height() or 28
        if self.statusBar() and self.statusBar().isVisible():
            chrome_h += self.statusBar().height() or 24

        target_w = int(vw * scale)
        target_h = int(vh * scale)

        if target_w > max_w or (target_h + chrome_h) > max_h:
            ratio = min(max_w / float(target_w), (max_h - chrome_h) / float(target_h))
            target_w = max(640, int(target_w * ratio))
            target_h = max(360, int(target_h * ratio))

        total_w = target_w
        total_h = target_h + chrome_h

        pos_x = avail.x() + (avail.width() - total_w) // 2
        pos_y = avail.y() + (avail.height() - total_h) // 2

        self.setGeometry(pos_x, pos_y, total_w, total_h)
        if hasattr(self, "central_container") and hasattr(self.central_container, "update_layout"):
            self.central_container.update_layout()

    def _on_engine_playback_end(self):
        # Auto advance playlist
        next_item = self.playlist_mgr.next()
        if next_item:
            self.play_media(next_item.uri, next_item.title, next_item.item_type)
        else:
            self.osc.set_play_state(False)

    def _try_play_mxf_as_dcp_reel(self, file_path: str) -> bool:
        """If file_path is a picture/sound MXF inside a DCP folder, open the DCP at that reel."""
        parent_dir = os.path.dirname(file_path)
        if not (file_path.lower().endswith(".mxf") and DCPParser.is_dcp_folder(parent_dir)):
            return False
        matched_reel = 0
        try:
            pkg = DCPParser.parse(parent_dir)
            cpl = pkg.default_composition
            if cpl and cpl.reels:
                norm_target = os.path.normcase(os.path.abspath(file_path))
                for idx, r in enumerate(cpl.reels):
                    for cand in (r.picture_path, r.sound_path):
                        if cand and os.path.normcase(os.path.abspath(cand)) == norm_target:
                            matched_reel = idx
                            break
                    else:
                        continue
                    break
        except Exception:
            matched_reel = 0
        self.play_dcp_folder(parent_dir, start_reel_index=matched_reel)
        return True

    # File Opening Actions
    def action_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Media File", "",
            "Video & Audio Files (*.mp4 *.mkv *.avi *.mov *.mxf *.webm *.ts *.flv *.j2k *.jp2 *.av2 *.obu *.mp3 *.wav *.flac);;All Files (*.*)"
        )
        if path:
            if self._try_play_mxf_as_dcp_reel(path):
                return
            self.play_media(path)
        else:
            pass

    def action_open_dcp(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Digital Cinema Package (DCP) Folder")
        if folder:
            self.play_dcp_folder(folder)

    def action_open_url(self):
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Open Stream / URL")
        dlg.setLabelText("Enter Streaming / Video / IPTV URL:")
        dlg.setMinimumWidth(540)
        dlg.resize(560, 160)
        if dlg.exec():
            url = dlg.textValue().strip()
            if url:
                self.play_media(url, url, "url")

    def action_load_external_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add External Audio Track", "",
            "Audio Files (*.wav *.flac *.mp3 *.aac *.ac3 *.dts *.m4a *.opus *.ogg *.mxf);;All Files (*.*)"
        )
        if path:
            self.engine.add_external_audio(path, select=True)
            self.show_toast(f"Loaded External Audio: {os.path.basename(path)}")

    def action_load_external_sub(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add External Subtitle File", "",
            "Subtitles (*.srt *.ass *.ssa *.vtt *.sub *.idx *.sup);;All Files (*.*)"
        )
        if path:
            self.engine.add_external_subtitle(path, select=True)
            self.show_toast(f"Loaded External Subtitle: {os.path.basename(path)}")

    def action_load_external_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add External Video Track", "",
            "Video Files (*.mp4 *.mkv *.mov *.mxf *.avi *.webm *.av2 *.obu);;All Files (*.*)"
        )
        if path:
            self.engine.add_external_video(path, select=False)
            self.show_toast(f"Added External Video Angle: {os.path.basename(path)}")

    def _on_dcp_quality_selected(self, level: int):
        for lvl, act in getattr(self, "dcp_q_actions", {}).items():
            act.setChecked(lvl == level)
        self.engine.set_dcp_decode_quality(level)
        gpu_info = GPUDetector.get_info()
        has_gpu = gpu_info.has_nvjpeg2k or getattr(gpu_info, "has_grok", False) or getattr(gpu_info, "has_opencl", False)
        backend_tag = "nvJPEG2000" if gpu_info.has_nvjpeg2k else ("Grok OpenCL" if (getattr(gpu_info, "has_grok", False) or getattr(gpu_info, "has_opencl", False)) else "GPU")
        labels = {
            0: (
                f"⚡ Native 4K Master ({gpu_info.short_name} GPU {backend_tag} @ 24fps)"
                if has_gpu else
                f"⚡ Native 4K Master ({gpu_info.short_name} @ 24fps)"
            ),
            1: "2K Pixel-Perfect (2048x1080 Match)",
            2: "1K Wavelet Proxy (1024x540)",
        }
        lbl = labels.get(level, f"Level {level}")
        self.show_toast(f"DCP Quality: {lbl}")
        self.engine.resume()

        # Update source codec badge
        if level == 0:
            self._update_source_codec_display(f"⚡ {backend_tag.upper()} 4K @ 24fps [{gpu_info.short_name} GPU] (12-bit XYZ)")
        elif level == 1:
            self._update_source_codec_display("JPEG 2000 [2048x1080 2K Match]")
        else:
            self._update_source_codec_display("JPEG 2000 [1024x540 1K Proxy]")

    def action_track_selector(self):
        """Open the unified studio Track & Stream Selector dialog."""
        dlg = TrackSelectorDialog(self.engine, self)
        dlg.load_external_requested.connect(self._on_load_external_track_requested)
        dlg.track_changed.connect(self._on_dialog_track_changed)
        dlg.exec()

    def _on_load_external_track_requested(self, track_type: str):
        if track_type == "video":
            self.action_load_external_video()
        elif track_type == "audio":
            self.action_load_external_audio()
        elif track_type == "sub":
            self.action_load_external_sub()

    def _on_dialog_track_changed(self, track_type: str, track_id: Any):
        if track_type == "sub":
            self.video_widget.set_subtitles_visible(track_id not in ("no", 0, None, False))
        name = "Disabled" if track_id in ("no", 0, None) else f"Track #{track_id}"
        self.show_toast(f"Active {track_type.capitalize()} Track: {name}")

    def _populate_video_tracks_menu(self):
        self.menu_video_tracks.clear()
        tracks = self.engine.get_tracks_by_type("video")
        if not tracks:
            act_none = QAction("(No Video Tracks Available)", self)
            act_none.setEnabled(False)
            self.menu_video_tracks.addAction(act_none)
            return

        grp = QActionGroup(self.menu_video_tracks)
        grp.setExclusive(True)

        for t in tracks:
            tid = t.get("id")
            title = t.get("title") or f"Angle #{tid}"
            w = t.get("demux-w") or 0
            h = t.get("demux-h") or 0
            codec = (t.get("codec") or "").upper()
            res_txt = f"{w}x{h}" if (w and h) else ""
            lbl = f"Track {tid}: {title} [{codec} {res_txt}]".strip()

            act = QAction(lbl, self.menu_video_tracks)
            act.setCheckable(True)
            act.setChecked(bool(t.get("selected")))
            act.triggered.connect(lambda checked, i=tid: self._select_track_and_notify("video", i))
            grp.addAction(act)
            self.menu_video_tracks.addAction(act)

        self.menu_video_tracks.addSeparator()
        act_dis = QAction("Disable Video (Audio Only)", self.menu_video_tracks)
        act_dis.triggered.connect(lambda: self._select_track_and_notify("video", "no"))
        self.menu_video_tracks.addAction(act_dis)

    def _populate_audio_tracks_menu(self):
        self.menu_audio_tracks.clear()
        tracks = self.engine.get_tracks_by_type("audio")
        if not tracks:
            act_none = QAction("(No Audio Tracks Available)", self)
            act_none.setEnabled(False)
            self.menu_audio_tracks.addAction(act_none)
            return

        grp = QActionGroup(self.menu_audio_tracks)
        grp.setExclusive(True)

        for t in tracks:
            tid = t.get("id")
            lang = (t.get("lang") or "und").upper()
            title = t.get("title") or t.get("external-filename") or f"Audio #{tid}"
            title = os.path.basename(str(title))
            codec = (t.get("codec") or "PCM").upper()
            ch = t.get("demux-channel-count") or t.get("audio-channels") or 2
            ch_desc = "Atmos 14-Ch" if ch == 14 else (f"{ch} Ch")
            lbl = f"Track {tid}: [{lang}] {title} ({codec}, {ch_desc})"

            act = QAction(lbl, self.menu_audio_tracks)
            act.setCheckable(True)
            act.setChecked(bool(t.get("selected")))
            act.triggered.connect(lambda checked, i=tid: self._select_track_and_notify("audio", i))
            grp.addAction(act)
            self.menu_audio_tracks.addAction(act)

        self.menu_audio_tracks.addSeparator()
        act_dis = QAction("Mute / Disable Audio Track", self.menu_audio_tracks)
        act_dis.triggered.connect(lambda: self._select_track_and_notify("audio", "no"))
        self.menu_audio_tracks.addAction(act_dis)

    def _populate_sub_tracks_menu(self):
        self.menu_sub_tracks.clear()
        tracks = self.engine.get_tracks_by_type("sub")

        grp = QActionGroup(self.menu_sub_tracks)
        grp.setExclusive(True)

        is_dcp_subs = (
            self.engine.is_dcp_playing
            and bool(getattr(self.engine, "dcp_sub_engine", None))
            and bool(self.engine.dcp_sub_engine.cues)
        )
        dcp_visible = (
            self.video_widget.nv_viewport.subtitles_visible
            if self.engine.nvjpeg2k_active
            else True
        )

        any_selected = any(bool(t.get("selected")) for t in tracks) or (is_dcp_subs and dcp_visible)
        is_sub_disabled = (
            getattr(self.engine, "subtitles_user_disabled", False)
            or not any_selected
        )

        act_off = QAction("Off (Disable Subtitles)", self.menu_sub_tracks)
        act_off.setCheckable(True)
        act_off.setChecked(is_sub_disabled)
        act_off.triggered.connect(lambda: (self._select_track_and_notify("sub", "no"), self.video_widget.set_subtitles_visible(False)))
        grp.addAction(act_off)
        self.menu_sub_tracks.addAction(act_off)

        if is_dcp_subs:
            self.menu_sub_tracks.addSeparator()
            sub_eng = self.engine.dcp_sub_engine
            lbl = f"🎬 DCP Cinema: [{sub_eng.language.upper()}] Timed Text ({len(sub_eng.cues)} cues)"
            act_dcp = QAction(lbl, self.menu_sub_tracks)
            act_dcp.setCheckable(True)
            act_dcp.setChecked(dcp_visible)

            def _toggle_dcp_sub():
                self.video_widget.set_subtitles_visible(True)
                if not self.engine.nvjpeg2k_active:
                    self.engine.set_track("sub", 1)
                self.show_toast(f"Active Subtitle: {lbl}")

            act_dcp.triggered.connect(_toggle_dcp_sub)
            grp.addAction(act_dcp)
            self.menu_sub_tracks.addAction(act_dcp)

        if not tracks and not is_dcp_subs:
            self.menu_sub_tracks.addSeparator()
            act_none = QAction("(No Subtitle Tracks Found)", self)
            act_none.setEnabled(False)
            self.menu_sub_tracks.addAction(act_none)
            return

        if tracks:
            self.menu_sub_tracks.addSeparator()
            for t in tracks:
                tid = t.get("id")
                lang = (t.get("lang") or "und").upper()
                title = t.get("title") or t.get("external-filename") or f"Sub #{tid}"
                title = os.path.basename(str(title))
                codec = (t.get("codec") or t.get("format") or "SUB").upper()
                lbl = f"Track {tid}: [{lang}] {title} ({codec})"

                act = QAction(lbl, self.menu_sub_tracks)
                act.setCheckable(True)
                act.setChecked(bool(t.get("selected")) and not is_sub_disabled)
                act.triggered.connect(lambda checked, i=tid: self._select_track_and_notify("sub", i))
                grp.addAction(act)
                self.menu_sub_tracks.addAction(act)

    def _select_track_and_notify(self, track_type: str, track_id: Any):
        self.engine.set_track(track_type, track_id)
        if track_type == "sub":
            self.video_widget.set_subtitles_visible(track_id not in ("no", 0, None, False))
        name = "Disabled / Off" if track_id in ("no", 0, None) else f"Track #{track_id}"
        self.show_toast(f"Active {track_type.capitalize()} Track: {name}")

    def _cycle_track(self, track_type: str, direction: str = "up"):
        res = self.engine.cycle_track(track_type, direction)
        if track_type == "sub":
            self.video_widget.set_subtitles_visible(res not in ("no", 0, None, False))
        val = "Disabled" if res in ("no", None, False) else f"Track #{res}"
        self.show_toast(f"Cycled {track_type.capitalize()} Track: {val}")

    def action_audio_dialog(self):
        tracks = self.engine.get_track_list()
        delay = getattr(self.engine.player, "audio_delay", 0.0) or 0.0
        dlg = AudioSyncDialog(tracks, delay, current_iab_mode=self.engine.current_iab_mode, parent=self)
        dlg.load_external_audio.connect(lambda p: self.engine.add_external_audio(p, select=True))
        dlg.audio_track_changed.connect(lambda tid: self.engine.set_track("audio", tid))
        dlg.audio_delay_changed.connect(self.engine.set_audio_delay)
        dlg.iab_mode_changed.connect(self._set_iab_mode)
        dlg.exec()

    def open_iab_visualizer(self):
        """Open or toggle the 3D IAB / Dolby Atmos spatial audio visualizer HUD."""
        if self.iab_visualizer is None:
            self.iab_visualizer = IABVisualizerDialog(self.engine.current_iab_meta, self)
            self.iab_visualizer.mode_changed.connect(self._set_iab_mode)
        else:
            self.iab_visualizer.set_metadata(self.engine.current_iab_meta)

        # Sync active routing mode in combobox
        idx = self.iab_visualizer.combo_mode.findData(self.engine.current_iab_mode)
        if idx >= 0:
            self.iab_visualizer.combo_mode.blockSignals(True)
            self.iab_visualizer.combo_mode.setCurrentIndex(idx)
            self.iab_visualizer.combo_mode.blockSignals(False)

        pos = getattr(self.engine.player, "time_pos", 0.0) or 0.0
        self.iab_visualizer.update_time_pos(pos)

        if not self.iab_visualizer.isVisible():
            self.iab_visualizer.show()
        self.iab_visualizer.raise_()
        self.iab_visualizer.activateWindow()

    def _set_iab_mode(self, mode: str):
        self.engine.set_iab_mode(mode)
        mode_labels = {
            "binaural": "Binaural 3D Headphones",
            "cinema_71": "Cinema 7.1 Downmix",
            "cinema_51": "Cinema 5.1 Downmix",
            "stereo_dialog": "Stereo Dialog Focus",
            "pcm_direct": "Direct Multi-Channel Bed",
        }
        lbl = mode_labels.get(mode, mode)
        self.show_toast(f"IAB Mode: {lbl}")
        self.lbl_status_iab.setText(f"IAB: {lbl}")

        if getattr(self, "iab_visualizer", None):
            idx = self.iab_visualizer.combo_mode.findData(mode)
            if idx >= 0:
                self.iab_visualizer.combo_mode.blockSignals(True)
                self.iab_visualizer.combo_mode.setCurrentIndex(idx)
                self.iab_visualizer.combo_mode.blockSignals(False)

    def _on_iab_status_changed(self, meta, mode: str):
        mode_labels = {
            "binaural": "Binaural 3D",
            "cinema_71": "Cinema 7.1",
            "cinema_51": "Cinema 5.1",
            "stereo_dialog": "Dialog Focus",
            "pcm_direct": "14-Ch Direct",
        }
        lbl = mode_labels.get(mode, mode)
        if meta:
            self.lbl_status_iab.setText(f"IAB [ST 2098-2]: {lbl}")
            self.show_toast(f"ST 2098-2 IAB (Dolby Atmos) Active | Mode: {lbl}")
        else:
            self.lbl_status_iab.setText(f"Audio Mode: {lbl}")

        if getattr(self, "iab_visualizer", None):
            self.iab_visualizer.set_metadata(meta)
            idx = self.iab_visualizer.combo_mode.findData(mode)
            if idx >= 0:
                self.iab_visualizer.combo_mode.blockSignals(True)
                self.iab_visualizer.combo_mode.setCurrentIndex(idx)
                self.iab_visualizer.combo_mode.blockSignals(False)

    def action_sub_dialog(self):
        tracks = self.engine.get_track_list()
        delay = getattr(self.engine.player, "sub_delay", 0.0) or 0.0
        dlg = SubtitleSyncDialog(tracks, delay, self)
        dlg.load_external_sub.connect(lambda p: self.engine.add_external_subtitle(p, select=True))
        dlg.subtitle_track_changed.connect(
            lambda tid: (
                self.engine.set_track("sub", tid),
                self.video_widget.set_subtitles_visible(tid not in ("no", 0, None, False))
            )
        )
        dlg.subtitle_delay_changed.connect(self.engine.set_sub_delay)
        dlg.exec()

    def action_toggle_subtitles(self):
        """Toggle subtitle visibility on/off (Hotkey: V)."""
        if self.engine.nvjpeg2k_active:
            curr = self.video_widget.nv_viewport.subtitles_visible
            new_state = not curr
            self.video_widget.set_subtitles_visible(new_state)
            self.show_toast(f"DCP Subtitles: {'Enabled' if new_state else 'Disabled'}")
            return
        is_on = self.engine.toggle_subtitles()
        self.video_widget.set_subtitles_visible(is_on)
        self.show_toast(f"Subtitles: {'On' if is_on else 'Off'}")

    def open_dcp_dialog(self):
        pkg = self.engine.current_dcp
        dlg = DCPInspectorDialog(pkg, self)
        dlg.play_dcp_requested.connect(self._on_play_dcp_requested)
        dlg.exec()

    def open_dvis_converter_dialog(self):
        pkg = self.engine.current_dcp
        if not pkg:
            folder = QFileDialog.getExistingDirectory(self, "Select Dolby Vision / EDR DCP Folder")
            if not folder:
                return
            try:
                pkg = DCPParser.parse(folder)
            except Exception as e:
                QMessageBox.critical(self, "DCP Error", f"Failed to parse DCP package:\n{e}")
                return
        cpl = pkg.default_composition if pkg else None
        if not cpl:
            QMessageBox.warning(self, "No Composition", "No valid CPL composition found in DCP folder.")
            return
        from ui.dvis_converter_dialog import DVisConverterDialog
        dlg = DVisConverterDialog(cpl, pkg, self)
        dlg.exec()

    def _on_play_dcp_requested(self, pkg: DCPPackage, cpl_idx: int, reel_idx: int):
        self.engine.play_dcp_package(pkg, cpl_idx, reel_idx)
        cpl = pkg.compositions[cpl_idx] if cpl_idx < len(pkg.compositions) else None
        cpl_title = cpl.title if cpl else "DCP"
        fps = cpl.fps if cpl else 24.0
        self.lbl_status_media.setText(f"DCP Cinema: {cpl_title}")
        self.show_toast(f"Playing DCP Reel {reel_idx+1}{self._dcp_badge_suffix(cpl)}")
        self.lbl_status_color.setText("Color: DCI-XYZ -> Rec.709")
        self.osc.set_color_status("DCI-XYZ -> Rec.709")
        self.video_widget.hide_timer.start()
        if self.engine.nvjpeg2k_active:
            gpu_info = GPUDetector.get_info()
            self._update_source_codec_display(
                f"⚡ NVJPEG2000 4K @ {fps:.0f}fps [{gpu_info.short_name} GPU]{self._dcp_source_notes(cpl)}"
            )
        else:
            self._update_source_codec_display(f"JPEG 2000 4K @ {fps:.2f}fps{self._dcp_source_notes(cpl)}")
        if self.engine.dcp_sub_engine:
            self.video_widget.set_subtitle_engine(self.engine.dcp_sub_engine)
        else:
            self.video_widget.set_subtitle_engine(None)

    def open_codec_info_dialog(self):
        data = {}
        if self.engine.is_dcp_playing and self.engine.current_dcp:
            pkg = self.engine.current_dcp
            if pkg.root_path and os.path.isdir(pkg.root_path):
                data = MediaInspector.inspect_dcp(pkg.root_path)
            elif self.engine.active_cpl and self.engine.active_cpl.reels:
                reel = self.engine.active_cpl.reels[self.engine.current_reel_index]
                if reel.picture_path:
                    data = MediaInspector.inspect_file(reel.picture_path)
        elif self.current_media_path and os.path.exists(self.current_media_path):
            data = MediaInspector.inspect_file(self.current_media_path)
        
        if not data or "error" in data:
            data = MediaInspector.extract_from_mpv(self.engine.player)
            data["filename"] = os.path.basename(self.current_media_path) if self.current_media_path else "Live Stream"

        if self.engine.current_iab_meta:
            data["iab_meta"] = self.engine.current_iab_meta
        
        dlg = CodecInfoDialog(data, self)
        dlg.exec()

    def action_benchmark_nvjpeg2k(self):
        try:
            from core.nvjpeg2k_engine import NVJPEG2KEngine
            from core.grok_engine import GrokOpenCLEngine

            engine = None
            backend_label = "GPU Acceleration"
            if NVJPEG2KEngine.is_available():
                engine = NVJPEG2KEngine.get_instance()
                backend_label = "NVIDIA nvJPEG2000"
            elif GrokOpenCLEngine.is_available():
                engine = GrokOpenCLEngine.get_instance()
                backend_label = "Grok OpenCL Compute"

            if not engine:
                QMessageBox.warning(self, "GPU Acceleration Not Available", "Neither NVIDIA nvJPEG2000 nor Grok OpenCL GPU compute detected.")
                return

            mxf_path = None
            if self.engine.is_dcp_playing and self.engine.active_cpl and self.engine.active_cpl.reels:
                reel = self.engine.active_cpl.reels[self.engine.current_reel_index]
                if reel.picture_path and os.path.exists(reel.picture_path):
                    mxf_path = reel.picture_path

            if not mxf_path:
                from core.app_paths import get_app_base_dir
                candidate = os.path.join(
                    get_app_base_dir(),
                    "Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV",
                    "Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-jp2k.mxf"
                )
                if os.path.exists(candidate):
                    mxf_path = candidate

            if not mxf_path:
                QMessageBox.information(self, "No DCP Loaded", "Please load a DCP cinema package or picture MXF first.")
                return

            gpu_info = GPUDetector.get_info()
            self.show_toast(f"⚡ Benchmarking {backend_label} on {gpu_info.short_name}...")
            res = engine.benchmark_mxf(mxf_path, num_frames=24)
            msg = (
                f"GPU: {res.get('gpu')}\n"
                f"Backend: {res.get('backend', backend_label)}\n"
                f"Resolution: {res.get('resolution')} {res.get('precision')}\n"
                f"Processed: {res.get('frames')} frames in {res.get('elapsed_sec')}s\n"
                f"Throughput: {res.get('fps')} FPS\n"
                f"Latency: {res.get('ms_per_frame')} ms/frame\n\n"
                f"Status: Real-Time Hardware Acceleration Active ({res.get('fps', 24.0)/24.0:.1f}x real-time speed)!"
            )
            QMessageBox.information(self, f"⚡ {backend_label} Hardware Benchmark", msg)
        except Exception as e:
            QMessageBox.critical(self, "Benchmark Error", f"GPU benchmark failed:\n{e}")

    def _apply_tonemap_preset(self, preset_key: str):
        self.engine.tonemap_engine.apply_preset(preset_key)
        self._on_drawer_preset_changed(preset_key)

    def _on_drawer_preset_changed(self, preset_key: str):
        """Preset picked from the menu or the Color Science drawer."""
        if preset_key == "auto" and hasattr(self.engine, "redetect_color_pipeline"):
            try:
                self.engine.redetect_color_pipeline()
            except Exception:
                pass
        label = self.engine.tonemap_engine.get_status_summary().get("preset_label", preset_key)
        self.lbl_status_color.setText(f"Color: {label}")
        if hasattr(self, "tonemap_drawer"):
            try:
                self.tonemap_drawer._update_status_display()
            except Exception:
                pass
        self.show_toast(f"Color: {label}")

    def _adjust_audio_delay(self, delta_sec: float):
        cur = getattr(self.engine.player, "audio_delay", 0.0) or 0.0
        new_d = cur + delta_sec
        self.engine.set_audio_delay(new_d)
        self.show_toast(f"Audio Delay: {int(new_d * 1000)}ms")

    def _adjust_sub_delay(self, delta_sec: float):
        cur = getattr(self.engine.player, "sub_delay", 0.0) or 0.0
        new_d = cur + delta_sec
        self.engine.set_sub_delay(new_d)
        self.show_toast(f"Sub Delay: {int(new_d * 1000)}ms")

    # Docks Toggles
    def toggle_iptv_dock(self):
        self.iptv_dock.setVisible(not self.iptv_dock.isVisible())

    def toggle_playlist_dock(self):
        self.playlist_dock.setVisible(not self.playlist_dock.isVisible())

    def toggle_tonemap_dock(self):
        self.tonemap_dock.setVisible(not self.tonemap_dock.isVisible())

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
            self.statusBar().show()
            self.osc.set_fullscreen_state(False)
            self.osc.show()
            self.osc.raise_()
        else:
            self.showFullScreen()
            self.menuBar().hide()
            self.statusBar().hide()
            self.osc.set_fullscreen_state(True)
            self.osc.show()
            self.osc.raise_()
        if hasattr(self, "central_container") and hasattr(self.central_container, "update_layout"):
            self.central_container.update_layout()

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.toggle_fullscreen()

    def _init_pns_system(self):
        """Initialize Pan & Scan (PnS) Frame Controller and window-wide shortcuts."""
        self.pns_controller = PnSController(
            mpv_player=self.engine.player,
            nv_canvas=self.video_widget.nv_viewport
        )
        self.pns_controller.on_change = lambda msg: self.show_toast(f"📐 {msg}")

        # Exact structure matching MPC-HC Pan & Scan Frame Adjust menu
        items = [
            ("Increase Size", "Num+9", self.pns_controller.increase_size),
            ("Decrease Size", "Num+1", self.pns_controller.decrease_size),
            ("Increase Width", "Num+6", self.pns_controller.increase_width),
            ("Decrease Width", "Num+4", self.pns_controller.decrease_width),
            ("Increase Height", "Num+8", self.pns_controller.increase_height),
            ("Decrease Height", "Num+2", self.pns_controller.decrease_height),
            None,  # Separator
            ("Move Right", "Ctrl+Num+6", self.pns_controller.move_right),
            ("Move Left", "Ctrl+Num+4", self.pns_controller.move_left),
            ("Move Up", "Ctrl+Num+8", self.pns_controller.move_up),
            ("Move Down", "Ctrl+Num+2", self.pns_controller.move_down),
            ("Center", "Ctrl+Num+5", self.pns_controller.center),
            None,  # Separator
            ("Rotate Clockwise", "Alt+Num+3", self.pns_controller.rotate_clockwise),
            ("Rotate Counter-Clockwise", "Alt+Num+1", self.pns_controller.rotate_counter_clockwise),
            ("Flip Vertically", "Alt+Num+2", self.pns_controller.flip_vertical),
            ("Mirror", "Alt+Num+6", self.pns_controller.mirror),
            None,  # Separator
            ("Scale to 16:9 TV", None, self.pns_controller.scale_to_16_9),
            ("Zoom to Widescreen", None, self.pns_controller.zoom_to_widescreen),
            ("Zoom to Ultra-Widescreen", None, self.pns_controller.zoom_to_ultra_widescreen),
            ("3D SBS > 2D", None, self.pns_controller.convert_3d_sbs_to_2d),
            ("3D TB > 2D", None, self.pns_controller.convert_3d_tb_to_2d),
            ("Edit...", None, self.open_pns_dialog),
            None,  # Separator
            ("Reset", "Num+5", self.pns_controller.reset),
        ]

        self._pns_actions = []
        for it in items:
            if it is None:
                self._pns_actions.append(None)
            else:
                title, shortcut, cb = it
                act = QAction(title, self)
                if shortcut:
                    act.setShortcut(QKeySequence(shortcut))
                act.triggered.connect(cb)
                self.addAction(act)
                self._pns_actions.append(act)

    def _populate_pns_menu(self, menu: QMenu):
        for act in self._pns_actions:
            if act is None:
                menu.addSeparator()
            else:
                menu.addAction(act)

    def open_pns_dialog(self):
        dlg = PnSEditDialog(pns_controller=self.pns_controller, parent=self)
        dlg.exec()

    def get_fps(self) -> float:
        """Returns effective video frame rate for time/frame conversion."""
        if self.engine.is_dcp_playing and self.engine.active_cpl:
            fps = float(self.engine.active_cpl.fps or 24.0)
            return fps if fps > 0 else 24.0
        if self.engine.nvjpeg2k_active and self.engine.nv_controller:
            fps = float(self.engine.nv_controller.current_fps or 24.0)
            return fps if fps > 0 else 24.0
        try:
            fps = float(getattr(self.engine.player, "container_fps", 0.0) or getattr(self.engine.player, "estimated_vf_fps", 0.0) or 24.0)
            return fps if fps > 0 else 24.0
        except Exception:
            return 24.0

    def open_goto_dialog(self):
        curr_pts = self.engine.get_current_pts()
        fps = self.get_fps()
        dlg = GoToDialog(current_pts=curr_pts, fps=fps, parent=self)
        dlg.seek_requested.connect(lambda pts: self.engine.seek(pts, relative=False))
        dlg.exec()

    def _populate_stereo3d_menu(self, menu: QMenu):
        menu.clear()
        s3d = getattr(self.engine, "stereo3d_engine", None)
        if not s3d:
            return

        summary = s3d.get_status_summary()

        act_enable = QAction("Enable Stereoscopic 3D", self)
        act_enable.setCheckable(True)
        act_enable.setChecked(summary["enabled"])
        act_enable.triggered.connect(lambda chk: self._set_stereo3d_enabled(chk))
        menu.addAction(act_enable)

        menu.addSeparator()

        modes = [
            ("Left Eye Only (2D Mono)", "mono_l"),
            ("Right Eye Only (2D Mono)", "mono_r"),
            ("Anaglyph Red-Cyan (Dubois 3D)", "anaglyph_arcd"),
            ("Anaglyph Red-Cyan (Half Color)", "anaglyph_arch"),
            ("Anaglyph Green-Magenta", "anaglyph_agmd"),
            ("Line Interleaved (Row / Passive 3D)", "interleave_rows"),
            ("Column Interleaved (Autostereoscopic)", "interleave_cols"),
            ("Checkerboard (DLP 3D)", "checkerboard"),
            ("Side-by-Side (SBS 3D)", "sbs2l"),
            ("Top-and-Bottom (Over-Under 3D)", "ab2l"),
            ("Frame Interleaved (Alternating 120Hz/144Hz)", "frame_interleaved"),
        ]

        for label, mkey in modes:
            act_m = QAction(label, self)
            act_m.setCheckable(True)
            act_m.setChecked(summary["enabled"] and summary["output_mode"] == mkey)
            act_m.triggered.connect(lambda chk, k=mkey: self._set_stereo3d_output_mode(k))
            menu.addAction(act_m)

        menu.addSeparator()

        act_swap = QAction("Swap Left / Right Eyes", self)
        act_swap.setCheckable(True)
        act_swap.setChecked(summary["swap_eyes"])
        act_swap.triggered.connect(self._toggle_stereo3d_swap_eyes)
        menu.addAction(act_swap)

        menu.addSeparator()

        act_settings = QAction("Stereoscopic 3D Settings & Calibration...", self)
        act_settings.setShortcut(QKeySequence("Ctrl+Alt+3"))
        act_settings.triggered.connect(self.open_stereo3d_dialog)
        menu.addAction(act_settings)

    def _set_stereo3d_enabled(self, enabled: bool):
        s3d = getattr(self.engine, "stereo3d_engine", None)
        if s3d:
            s3d.set_enabled(enabled)
            self._update_stereo3d_toast()

    def _set_stereo3d_output_mode(self, mode_key: str):
        s3d = getattr(self.engine, "stereo3d_engine", None)
        if s3d:
            if self.engine.is_dcp_playing and self.engine.nv_controller:
                if mode_key == "mono_r":
                    self.engine.nv_controller.set_stereo_eye("right")
                else:
                    self.engine.nv_controller.set_stereo_eye("left")
            s3d.set_output_mode(mode_key)
            self._update_stereo3d_toast()

    def _toggle_stereo3d_swap_eyes(self):
        s3d = getattr(self.engine, "stereo3d_engine", None)
        if s3d:
            s3d.toggle_swap_eyes()
            if self.engine.is_dcp_playing and self.engine.nv_controller:
                eye = "right" if s3d.swap_eyes else "left"
                self.engine.nv_controller.set_stereo_eye(eye)
            self._update_stereo3d_toast()

    def _update_stereo3d_toast(self):
        s3d = getattr(self.engine, "stereo3d_engine", None)
        if not s3d:
            return
        summary = s3d.get_status_summary()
        if not summary["enabled"]:
            self.show_toast("🥽 Stereoscopic 3D: Disabled (2D)")
        else:
            out_lbl = summary["output_label"]
            swap_str = " (Swapped)" if summary["swap_eyes"] else ""
            self.show_toast(f"🥽 3D: {out_lbl}{swap_str}")

    def open_stereo3d_dialog(self):
        s3d = getattr(self.engine, "stereo3d_engine", None)
        if not s3d:
            return
        dlg = Stereo3DDialog(engine=s3d, parent=self)
        dlg.mode_changed.connect(lambda s: self._update_stereo3d_toast())
        dlg.exec()

    def open_trim_dialog(self):
        """Open the Lossless Clip Trimmer dialog (fast stream copy)."""
        src = self.current_media_path
        if not src or not os.path.exists(src):
            QMessageBox.information(self, "No Media Loaded", "Please load a video file first to trim.")
            return
        in_pts = self.engine.ab_point_a if self.engine.ab_point_a is not None else self.engine.get_current_pts()
        out_pts = self.engine.ab_point_b if self.engine.ab_point_b is not None else self.engine.get_duration()
        dur = self.engine.get_duration()
        dlg = LosslessTrimDialog(src, start_pts=in_pts, end_pts=out_pts, total_duration=dur, parent=self)
        dlg.clip_exported.connect(lambda path: self.show_toast(f"✂️ Trimmed clip saved: {os.path.basename(path)}"))
        dlg.exec()

    def load_3d_lut(self):
        """Open file dialog to load custom .cube or .3dl 3D Look-Up Table."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load 3D LUT File",
            "",
            "3D LUT Files (*.cube *.3dl);;All Files (*.*)"
        )
        if path:
            self.engine.tonemap_engine.set_3d_lut(path)
            fn = os.path.basename(path)
            self.show_toast(f"🎨 Loaded 3D LUT: {fn}")
            if hasattr(self, "act_enable_lut"):
                self.act_enable_lut.setChecked(True)

    def toggle_3d_lut(self):
        """Toggle active 3D Look-Up Table on or off."""
        enabled = self.engine.tonemap_engine.toggle_3d_lut()
        state = "Enabled" if enabled else "Disabled"
        lut_fn = os.path.basename(self.engine.tonemap_engine.lut_path or "")
        self.show_toast(f"3D LUT: {state} ({lut_fn or 'No LUT file'})")
        if hasattr(self, "act_enable_lut"):
            self.act_enable_lut.setChecked(enabled)

    def clear_3d_lut(self):
        """Clear active 3D LUT."""
        self.engine.tonemap_engine.clear_3d_lut()
        self.show_toast("3D LUT Cleared")
        if hasattr(self, "act_enable_lut"):
            self.act_enable_lut.setChecked(False)

    def toggle_hdr_passthrough(self):
        """Toggle Windows 11 direct HDR swapchain pass-through."""
        cur = getattr(self.engine.tonemap_engine, "hdr_passthrough", False)
        new_val = not cur
        self.engine.tonemap_engine.set_hdr_passthrough(new_val)
        if hasattr(self, "act_hdr_passthrough"):
            self.act_hdr_passthrough.setChecked(new_val)
        txt = "Direct HDR Pass-Through: Active (PQ)" if new_val else "Direct HDR Pass-Through: Disabled (SDR Tonemapped)"
        self.show_toast(f"📺 {txt}")

    def toggle_split_wipe(self):
        """Toggle Split-Screen A/B Comparison Wipe."""
        cur = getattr(self.video_widget.nv_viewport, "split_wipe_enabled", False)
        new_val = not cur
        self.video_widget.nv_viewport.set_split_wipe(new_val)
        self.engine.tonemap_engine.set_split_wipe(new_val)
        if hasattr(self, "act_split_wipe"):
            self.act_split_wipe.setChecked(new_val)
        txt = "Split-Screen Wipe: ON (Drag line to compare)" if new_val else "Split-Screen Wipe: OFF"
        self.show_toast(f"🪟 {txt}")

    def action_set_ab_point_a(self):
        """Set A-B Repeat loop Point A to current playback time."""
        a = self.engine.set_ab_point_a()
        self.osc.set_ab_repeat(self.engine.ab_point_a, self.engine.ab_point_b)
        tc = OSCControls._format_time(a)
        self.show_toast(f"🔁 A-B Repeat: Point A set to {tc}")

    def action_set_ab_point_b(self):
        """Set A-B Repeat loop Point B to current playback time."""
        b = self.engine.set_ab_point_b()
        if b is not None:
            self.osc.set_ab_repeat(self.engine.ab_point_a, self.engine.ab_point_b)
            tc_a = OSCControls._format_time(self.engine.ab_point_a or 0.0)
            tc_b = OSCControls._format_time(b)
            self.show_toast(f"🔁 A-B Repeat: Looping {tc_a} -> {tc_b}")
        else:
            self.show_toast("⚠️ Set Point A first before setting Point B")

    def action_clear_ab_repeat(self):
        """Clear active A-B Repeat loop."""
        self.engine.clear_ab_repeat()
        self.osc.set_ab_repeat(None, None)
        self.show_toast("🔁 A-B Repeat Cleared")

    def adjust_speed(self, delta: float):
        """Adjust playback speed with pitch preservation."""
        spd = self.engine.adjust_speed(delta)
        self.show_toast(f"⚡ Speed: {spd:.2f}x (Pitch Preserved)")

    def set_speed(self, speed: float):
        """Set playback speed with pitch preservation."""
        spd = self.engine.set_speed(speed)
        self.show_toast(f"⚡ Speed: {spd:.2f}x (Pitch Preserved)")

    def reset_speed(self):
        """Reset playback speed to 1.0x."""
        spd = self.engine.reset_speed()
        self.show_toast(f"⚡ Speed Reset: {spd:.1f}x Normal")

    def action_next_chapter(self):
        """Jump to next chapter or reel."""
        self.engine.next_chapter()
        cur = self.engine.get_current_pts()
        self.show_toast(f"📍 Next Chapter / Reel ({OSCControls._format_time(cur)})")

    def action_prev_chapter(self):
        """Jump to previous chapter or reel."""
        self.engine.prev_chapter()
        cur = self.engine.get_current_pts()
        self.show_toast(f"📍 Previous Chapter / Reel ({OSCControls._format_time(cur)})")

    def _populate_chapters_menu(self):
        """Dynamically populate Chapters menu."""
        if not hasattr(self, "menu_chapters"):
            return
        self.menu_chapters.clear()
        act_prev = QAction("Previous Chapter / Reel", self)
        act_prev.setShortcut(QKeySequence("Page_Up"))
        act_prev.triggered.connect(self.action_prev_chapter)
        self.menu_chapters.addAction(act_prev)

        act_next = QAction("Next Chapter / Reel", self)
        act_next.setShortcut(QKeySequence("Page_Down"))
        act_next.triggered.connect(self.action_next_chapter)
        self.menu_chapters.addAction(act_next)

        self.menu_chapters.addSeparator()

        chaps = self.engine.get_chapters()
        if not chaps:
            act_none = QAction("(No Chapters / Single Reel)", self)
            act_none.setEnabled(False)
            self.menu_chapters.addAction(act_none)
            return

        for ch in chaps:
            t = ch.get("time", 0.0)
            tc = OSCControls._format_time(t)
            lbl = f"{ch.get('title', 'Chapter')} [{tc}]"
            act = QAction(lbl, self)
            act.triggered.connect(lambda checked, pts=t: self.engine.seek(pts, relative=False))
            self.menu_chapters.addAction(act)

    def adjust_parallax(self, delta: int):
        """Adjust stereoscopic 3D horizontal convergence in pixels."""
        s3d = getattr(self.engine, "stereo3d_engine", None)
        if not s3d:
            return
        cur = getattr(s3d, "parallax_offset", 0)
        new_val = cur + delta
        s3d.set_parallax_offset(new_val)
        self.show_toast(f"🥽 3D Convergence: {new_val:+d} px")

    def contextMenuEvent(self, ev):
        pos = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
        self._show_context_menu(pos)
        ev.accept()

    def _show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #14151a;
                color: #f3f4f6;
                border: 1px solid #262732;
                border-radius: 8px;
                padding: 4px 0px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 12px;
            }
            QMenu::item {
                padding: 5px 24px 5px 20px;
            }
            QMenu::item:selected {
                background-color: #20222a;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #20222b;
                margin: 4px 8px;
            }
        """)

        # PnS Frame Adjust Submenu (exact match to user's screenshot)
        pns_sub = menu.addMenu("PnS Frame Adjust")
        self._populate_pns_menu(pns_sub)

        # Stereoscopic 3D Submenu
        s3d_sub = menu.addMenu("🥽 Stereoscopic 3D")
        self._populate_stereo3d_menu(s3d_sub)

        # Subtitles Submenu
        sub_sub = menu.addMenu("💬 Subtitles")
        act_ctx_toggle = sub_sub.addAction("Toggle Subtitles On/Off [V]")
        act_ctx_toggle.triggered.connect(self.action_toggle_subtitles)
        act_ctx_off = sub_sub.addAction("Disable Subtitles (Off)")
        act_ctx_off.triggered.connect(lambda: (self._select_track_and_notify("sub", "no"), self.video_widget.set_subtitles_visible(False)))
        sub_sub.addSeparator()
        sub_tracks = self.engine.get_tracks_by_type("sub")
        if sub_tracks:
            is_sub_disabled = getattr(self.engine, "subtitles_user_disabled", False)
            for t in sub_tracks:
                tid = t.get("id")
                lang = (t.get("lang") or "und").upper()
                title = t.get("title") or t.get("external-filename") or f"Sub #{tid}"
                title = os.path.basename(str(title))
                codec = (t.get("codec") or t.get("format") or "SUB").upper()
                lbl = f"Track {tid}: [{lang}] {title} ({codec})"
                act_t = sub_sub.addAction(lbl)
                act_t.setCheckable(True)
                act_t.setChecked(bool(t.get("selected")) and not is_sub_disabled)
                act_t.triggered.connect(lambda checked, i=tid: self._select_track_and_notify("sub", i))
        else:
            act_none = sub_sub.addAction("(No Subtitles Loaded)")
            act_none.setEnabled(False)
        sub_sub.addSeparator()
        act_ctx_sync = sub_sub.addAction("Subtitle Tracks & Sync... [Ctrl+U]")
        act_ctx_sync.triggered.connect(self.action_sub_dialog)

        # On Top Submenu
        ontop_sub = menu.addMenu("On Top")
        is_on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        act_ot_never = ontop_sub.addAction("Never")
        act_ot_never.setCheckable(True)
        act_ot_never.setChecked(not is_on_top)
        act_ot_never.triggered.connect(lambda: self.toggle_always_on_top(False))

        act_ot_always = ontop_sub.addAction("Always")
        act_ot_always.setCheckable(True)
        act_ot_always.setChecked(is_on_top)
        act_ot_always.triggered.connect(lambda: self.toggle_always_on_top(True))

        act_ot_playing = ontop_sub.addAction("While Playing")
        act_ot_playing.triggered.connect(lambda: self.toggle_always_on_top(True))

        menu.addSeparator()

        # Playback controls
        act_play = menu.addAction("Play / Pause")
        act_play.setShortcut(QKeySequence("Space"))
        act_play.triggered.connect(self.toggle_play_pause)

        act_stop = menu.addAction("Stop")
        act_stop.setShortcut(QKeySequence("S"))
        act_stop.triggered.connect(self.stop_playback)

        act_goto = menu.addAction("Go To...")
        act_goto.setShortcut(QKeySequence("Ctrl+G"))
        act_goto.triggered.connect(self.open_goto_dialog)

        menu.addSeparator()

        act_snap = menu.addAction("Take Snapshot...")
        act_snap.setShortcut(QKeySequence("Ctrl+S"))
        act_snap.triggered.connect(self.take_snapshot)

        act_trim = menu.addAction("Export Lossless Clip...")
        act_trim.setShortcut(QKeySequence("Ctrl+Shift+E"))
        act_trim.triggered.connect(self.open_trim_dialog)

        act_wipe = menu.addAction("Split-Screen Comparison Wipe")
        act_wipe.setShortcut(QKeySequence("Ctrl+W"))
        act_wipe.triggered.connect(self.toggle_split_wipe)

        act_info = menu.addAction("Media & Codec Information...")
        act_info.setShortcut(QKeySequence("Ctrl+I"))
        act_info.triggered.connect(self.open_codec_info_dialog)

        act_fs = menu.addAction("Fullscreen Toggle")
        act_fs.setShortcut(QKeySequence("F"))
        act_fs.triggered.connect(self.toggle_fullscreen)

        menu.exec(pos)

    def keyPressEvent(self, ev: QKeyEvent):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self.toggle_play_pause()
            ev.accept()
            return
        if ev.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.exit_fullscreen()
            ev.accept()
            return

        # Numpad / PnS Key Handling
        mod = ev.modifiers()
        has_ctrl = bool(mod & Qt.KeyboardModifier.ControlModifier)
        has_alt = bool(mod & Qt.KeyboardModifier.AltModifier)
        key = ev.key()

        if has_ctrl and not has_alt:
            if key in (Qt.Key.Key_6, Qt.Key.Key_Right) and (mod & Qt.KeyboardModifier.KeypadModifier or key == Qt.Key.Key_Right):
                self.pns_controller.move_right()
                ev.accept()
                return
            elif key in (Qt.Key.Key_4, Qt.Key.Key_Left) and (mod & Qt.KeyboardModifier.KeypadModifier or key == Qt.Key.Key_Left):
                self.pns_controller.move_left()
                ev.accept()
                return
            elif key in (Qt.Key.Key_8, Qt.Key.Key_Up) and (mod & Qt.KeyboardModifier.KeypadModifier or key == Qt.Key.Key_Up):
                self.pns_controller.move_up()
                ev.accept()
                return
            elif key in (Qt.Key.Key_2, Qt.Key.Key_Down) and (mod & Qt.KeyboardModifier.KeypadModifier or key == Qt.Key.Key_Down):
                self.pns_controller.move_down()
                ev.accept()
                return
            elif key in (Qt.Key.Key_5, Qt.Key.Key_Clear):
                self.pns_controller.center()
                ev.accept()
                return
        elif has_alt and not has_ctrl:
            if key in (Qt.Key.Key_3, Qt.Key.Key_PageDown):
                self.pns_controller.rotate_clockwise()
                ev.accept()
                return
            elif key in (Qt.Key.Key_1, Qt.Key.Key_End):
                self.pns_controller.rotate_counter_clockwise()
                ev.accept()
                return
            elif key in (Qt.Key.Key_2, Qt.Key.Key_Down):
                self.pns_controller.flip_vertical()
                ev.accept()
                return
            elif key in (Qt.Key.Key_6, Qt.Key.Key_Right):
                self.pns_controller.mirror()
                ev.accept()
                return
        elif not has_ctrl and not has_alt:
            if key in (Qt.Key.Key_9, Qt.Key.Key_PageUp):
                self.pns_controller.increase_size()
                ev.accept()
                return
            elif key in (Qt.Key.Key_1, Qt.Key.Key_End):
                self.pns_controller.decrease_size()
                ev.accept()
                return
            elif key == Qt.Key.Key_6 and (mod & Qt.KeyboardModifier.KeypadModifier):
                self.pns_controller.increase_width()
                ev.accept()
                return
            elif key == Qt.Key.Key_4 and (mod & Qt.KeyboardModifier.KeypadModifier):
                self.pns_controller.decrease_width()
                ev.accept()
                return
            elif key == Qt.Key.Key_8 and (mod & Qt.KeyboardModifier.KeypadModifier):
                self.pns_controller.increase_height()
                ev.accept()
                return
            elif key == Qt.Key.Key_2 and (mod & Qt.KeyboardModifier.KeypadModifier):
                self.pns_controller.decrease_height()
                ev.accept()
                return
            elif key in (Qt.Key.Key_5, Qt.Key.Key_Clear):
                self.pns_controller.reset()
                ev.accept()
                return

        # Navigation, Speed & A-B Repeat Keys
        if not has_ctrl and not has_alt:
            if key == Qt.Key.Key_V:
                self.action_toggle_subtitles()
                ev.accept()
                return
            elif key == Qt.Key.Key_BracketLeft:
                self.action_set_ab_point_a()
                ev.accept()
                return
            elif key == Qt.Key.Key_BracketRight:
                self.action_set_ab_point_b()
                ev.accept()
                return
            elif key == Qt.Key.Key_Backslash:
                self.action_clear_ab_repeat()
                ev.accept()
                return
            elif key == Qt.Key.Key_PageUp:
                self.action_prev_chapter()
                ev.accept()
                return
            elif key == Qt.Key.Key_PageDown:
                self.action_next_chapter()
                ev.accept()
                return
        elif has_ctrl and not has_alt:
            if key == Qt.Key.Key_Up and not (mod & Qt.KeyboardModifier.KeypadModifier):
                self.adjust_speed(0.1)
                ev.accept()
                return
            elif key == Qt.Key.Key_Down and not (mod & Qt.KeyboardModifier.KeypadModifier):
                self.adjust_speed(-0.1)
                ev.accept()
                return
            elif key == Qt.Key.Key_0 and not (mod & Qt.KeyboardModifier.KeypadModifier):
                self.reset_speed()
                ev.accept()
                return
        elif has_ctrl and has_alt:
            if key == Qt.Key.Key_Left:
                self.adjust_parallax(-4)
                ev.accept()
                return
            elif key == Qt.Key.Key_Right:
                self.adjust_parallax(4)
                ev.accept()
                return

        super().keyPressEvent(ev)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "central_container") and hasattr(self.central_container, "update_layout"):
            self.central_container.update_layout()

    def toggle_always_on_top(self, checked: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    def show_toast(self, text: str):
        self.toast_lbl.setText(text)
        self.toast_lbl.adjustSize()
        self.toast_lbl.move(24, 24)
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self.toast_timer.start()

    # Viewport Events
    def _on_video_mouse_move(self):
        self.osc.fade_in()
        self.video_widget.hide_timer.start()

    def _on_inactivity_timeout(self):
        if not self.engine.is_paused and not self.osc.underMouse() and not self.osc.is_dragging:
            self.osc.fade_out()
            self.video_widget.setCursor(Qt.CursorShape.BlankCursor)

    def _on_wheel_scroll(self, delta: int):
        vol = getattr(self.engine.player, "volume", 85) or 85
        step = 5 if delta > 0 else -5
        new_vol = max(0, min(130, int(vol + step)))
        self.set_volume(new_vol)
        self.osc.vol_slider.setValue(new_vol)
        self.show_toast(f"Volume: {new_vol}%")

    def _handle_file_dropped(self, file_path: str):
        # 1. Check if dropped file is part of a DCP Cinema package
        base_lower = os.path.basename(file_path).lower()
        parent_dir = os.path.dirname(file_path)
        if base_lower in ("assetmap", "assetmap.xml", "volindex.xml") or (base_lower.startswith("cpl") and base_lower.endswith(".xml")):
            if DCPParser.is_dcp_folder(parent_dir):
                self.play_dcp_folder(parent_dir)
                return
        if self._try_play_mxf_as_dcp_reel(file_path):
            return

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"):
            self.engine.add_external_subtitle(file_path, select=True)
            self.show_toast(f"Attached Subtitle: {os.path.basename(file_path)}")
        elif ext in (".wav", ".flac", ".mp3", ".aac", ".ac3", ".dts", ".m4a", ".opus", ".ogg"):
            if self.current_media_path:
                self.engine.add_external_audio(file_path, select=True)
                self.show_toast(f"Attached Audio: {os.path.basename(file_path)}")
            else:
                self.play_media(file_path)
        elif ext in (".m3u", ".m3u8"):
            count = self.iptv_mgr.load_m3u_file(file_path)
            self.iptv_drawer._refresh_categories()
            self.iptv_drawer._filter_channels()
            self.iptv_dock.show()
            self.show_toast(f"Imported {count} IPTV Channels")
        else:
            self.play_media(file_path)

    def _handle_folder_dropped(self, folder_path: str):
        if DCPParser.is_dcp_folder(folder_path):
            self.play_dcp_folder(folder_path)
        else:
            # Add all media files in folder to playlist
            count = 0
            for root, _, files in os.walk(folder_path):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in (".mp4", ".mkv", ".avi", ".mov", ".mxf", ".webm", ".ts", ".mp3", ".flac"):
                        full_p = os.path.join(root, f)
                        self.playlist_mgr.add_item(full_p)
                        count += 1
            self.playlist_drawer.refresh_list()
            self.playlist_dock.show()
            self.show_toast(f"Queued {count} files from folder")

    def _play_playlist_index(self, idx: int):
        item = self.playlist_mgr.set_current(idx)
        if item:
            self.play_media(item.uri, item.title, item.item_type)

    def _add_playlist_item(self, uri: str, title: str, itype: str):
        self.playlist_mgr.add_item(uri, title, itype)
