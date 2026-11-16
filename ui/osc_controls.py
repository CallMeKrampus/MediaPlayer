"""
BOOB Player - On-Screen Controller (OSC) HUD
Floating, translucent glassmorphic control surface inspired by mpv, VLC, and KMPlayer.
"""

from typing import Optional, List, Dict, Any, Tuple
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QSlider, QLabel,
    QFrame, QSizePolicy, QToolTip, QStyleOptionSlider, QStyle,
    QGraphicsOpacityEffect, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QTimer, QRectF, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QMouseEvent, QCursor, QPainter, QColor, QPixmap, QPolygon
from core.thumbnail_generator import ThumbnailManager
from ui.icons import (
    draw_play_icon, draw_pause_icon, draw_stop_icon,
    draw_skip_back_icon, draw_skip_forward_icon,
    draw_frame_step_icon, draw_volume_icon, draw_fullscreen_icon
)


class HoverThumbnailPopup(QFrame):
    """Floating seekbar thumbnail preview tooltip."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            QFrame {
                background-color: #121318;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
            }
            QLabel {
                color: #f3f4f6;
                font-family: monospace;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.lbl_img = QLabel()
        self.lbl_img.setFixedSize(180, 101)
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setStyleSheet("background: #000000; border-radius: 4px; color: #71717a; font-size: 10px;")
        self.lbl_img.setText("Loading...")
        layout.addWidget(self.lbl_img)

        self.lbl_time = QLabel("00:00:00")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_time.setStyleSheet("font-weight: 600; font-size: 11px; color: #f3f4f6;")
        layout.addWidget(self.lbl_time)

        self.lbl_chapter = QLabel("")
        self.lbl_chapter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_chapter.setStyleSheet("font-size: 10px; color: #a1a1aa; font-weight: 500;")
        self.lbl_chapter.hide()
        layout.addWidget(self.lbl_chapter)

    def set_content(self, time_str: str, pixmap: Optional[QPixmap], chapter_str: str = ""):
        self.lbl_time.setText(time_str)
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                180, 101,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_img.setPixmap(scaled)
        else:
            self.lbl_img.clear()
            self.lbl_img.setText("Loading Frame...")

        if chapter_str:
            self.lbl_chapter.setText(chapter_str)
            self.lbl_chapter.show()
        else:
            self.lbl_chapter.hide()


class HoverScrubberSlider(QSlider):
    """Custom seek slider showing hover timestamp preview and instant click-to-seek."""
    hover_time_changed = pyqtSignal(float, float, QPoint)  # target_time, buffered_time, global_pos
    instant_seek_requested = pyqtSignal(float)
    hover_exited = pyqtSignal()

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.duration: float = 0.0
        self.buffered_duration: float = 0.0
        self.chapters: list = []
        self.ab_point_a: Optional[float] = None
        self.ab_point_b: Optional[float] = None

    def set_chapters(self, chapters: list):
        self.chapters = chapters or []
        self.update()

    def set_ab_repeat(self, a: Optional[float], b: Optional[float]):
        self.ab_point_a = a
        self.ab_point_b = b
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.duration <= 0 or self.width() <= 14:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pad = 7
        usable_w = max(1, self.width() - (2 * pad))
        y_track = (self.height() // 2) - 2

        # 1. A-B Repeat Loop Range Highlight
        if self.ab_point_a is not None:
            a_frac = max(0.0, min(1.0, self.ab_point_a / self.duration))
            a_x = pad + a_frac * usable_w
            b_val = self.ab_point_b if self.ab_point_b is not None else self.duration
            b_frac = max(0.0, min(1.0, b_val / self.duration))
            b_x = pad + b_frac * usable_w

            if b_x > a_x:
                painter.fillRect(QRectF(a_x, y_track - 2, b_x - a_x, 8), QColor(245, 158, 11, 90))

            # Point A Marker (Amber Triangle)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f59e0b"))
            tri_a = QPolygon([
                QPoint(int(a_x), y_track - 2),
                QPoint(int(a_x - 5), y_track - 10),
                QPoint(int(a_x + 5), y_track - 10),
            ])
            painter.drawPolygon(tri_a)

            # Point B Marker (Cyan Triangle)
            if self.ab_point_b is not None:
                painter.setBrush(QColor("#00d2ff"))
                tri_b = QPolygon([
                    QPoint(int(b_x), y_track - 2),
                    QPoint(int(b_x - 5), y_track - 10),
                    QPoint(int(b_x + 5), y_track - 10),
                ])
                painter.drawPolygon(tri_b)

        # 2. Demuxer RAM cache buffer
        if self.buffered_duration > 0:
            curr_sec = (self.value() / self.maximum()) * self.duration
            curr_x = pad + (curr_sec / self.duration) * usable_w
            buf_sec = min(self.duration, curr_sec + self.buffered_duration)
            buf_x = pad + (buf_sec / self.duration) * usable_w
            if buf_x > curr_x:
                painter.fillRect(QRectF(curr_x, y_track, buf_x - curr_x, 4), QColor(56, 189, 248, 140))

        # 3. Chapter Markers
        if self.chapters:
            for ch in self.chapters:
                ch_t = ch.get("time", 0.0)
                if 0 <= ch_t <= self.duration:
                    ch_x = pad + (ch_t / self.duration) * usable_w
                    painter.fillRect(QRectF(ch_x - 0.5, y_track - 3, 2.0, 10), QColor("#38bdf8"))

    def leaveEvent(self, ev):
        self.hover_exited.emit()
        super().leaveEvent(ev)

    def _pos_to_val(self, x: float) -> int:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        gr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        sr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)
        slider_length = sr.width()
        slider_min = gr.x()
        slider_max = gr.right() - slider_length + 1
        span = self.maximum() - self.minimum()
        if span <= 0:
            return self.minimum()
        if slider_max <= slider_min:
            fraction = max(0.0, min(1.0, x / max(1, self.width())))
        else:
            pos = x - slider_length / 2.0
            fraction = max(0.0, min(1.0, (pos - slider_min) / (slider_max - slider_min)))
        return int(round(self.minimum() + fraction * span))

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self.duration > 0 and self.width() > 0:
            val = self._pos_to_val(ev.position().x())
            span = max(1, self.maximum() - self.minimum())
            fraction = max(0.0, min(1.0, (val - self.minimum()) / span))
            target_time = fraction * self.duration
            global_pos = self.mapToGlobal(ev.position().toPoint())
            self.hover_time_changed.emit(target_time, self.buffered_duration, global_pos)
        if self.isSliderDown():
            val = self._pos_to_val(ev.position().x())
            self.setValue(val)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton and self.width() > 0:
            val = self._pos_to_val(ev.position().x())
            span = max(1, self.maximum() - self.minimum())
            fraction = max(0.0, min(1.0, (val - self.minimum()) / span))
            self.setValue(val)
            if self.duration > 0:
                self.instant_seek_requested.emit(fraction * self.duration)
            self.setSliderDown(True)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            val = self._pos_to_val(ev.position().x())
            self.setValue(val)
            self.setSliderDown(False)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


class OSCControls(QFrame):
    # Signals
    play_pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    seek_requested = pyqtSignal(float)
    skip_back_clicked = pyqtSignal()
    skip_forward_clicked = pyqtSignal()
    frame_back_clicked = pyqtSignal()
    frame_forward_clicked = pyqtSignal()
    volume_changed = pyqtSignal(int)
    mute_toggled = pyqtSignal()
    
    toggle_iptv_clicked = pyqtSignal()
    toggle_playlist_clicked = pyqtSignal()
    toggle_tonemap_clicked = pyqtSignal()
    open_dcp_clicked = pyqtSignal()
    open_codec_info_clicked = pyqtSignal()
    open_tracks_clicked = pyqtSignal()
    fullscreen_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("oscFrame")
        self.duration: float = 0.0
        self.current_time: float = 0.0
        self.buffered_duration: float = 0.0
        self.show_remaining: bool = False
        self.is_dragging: bool = False

        self._pending_scrub_target: float = 0.0
        self._last_seek_target: float | None = None
        self.scrub_timer = QTimer(self)
        self.scrub_timer.setInterval(70)
        self.scrub_timer.setSingleShot(True)
        self.scrub_timer.timeout.connect(self._do_scrub_seek)

        # Smooth fade & subtle vertical slide transition for floating OSC island
        self._resting_pos = QPoint(0, 0)
        self._is_fading_out = False
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)

        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("""
            QFrame#oscFrame {
                background: rgba(15, 16, 20, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 10px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 10, 16, 12)
        main_layout.setSpacing(6)

        # 1. Scrubber Row (Seekbar + Time Label + Source Codec Badge)
        scrubber_row = QHBoxLayout()
        scrubber_row.setSpacing(12)

        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setStyleSheet("color: #a1a1aa; font-size: 12px; font-weight: 600; font-family: monospace;")
        self.time_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.time_label.mousePressEvent = self._toggle_time_mode

        self.lbl_codec_badge = QLabel("SOURCE: --")
        self.lbl_codec_badge.setToolTip("Active Source File Codec, Native Resolution & Framerate")
        self.lbl_codec_badge.setStyleSheet("""
            QLabel {
                color: #e4e4e7;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 2px 7px;
                font-size: 11px;
                font-weight: 600;
                font-family: monospace;
            }
        """)

        self.lbl_color_badge = QLabel("COLOR: Auto")
        self.lbl_color_badge.setToolTip("Active HDR/SDR Color Mapping Pipeline (click to open Color Science Lab)")
        self.lbl_color_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_color_badge.mousePressEvent = lambda _e: self.toggle_tonemap_clicked.emit()
        self.lbl_color_badge.setStyleSheet("""
            QLabel {
                color: #e4e4e7;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 2px 7px;
                font-size: 11px;
                font-weight: 600;
                font-family: monospace;
            }
        """)

        self.slider = HoverScrubberSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.valueChanged.connect(self._on_slider_value_changed)
        self.slider.hover_time_changed.connect(self._show_hover_time)
        self.slider.hover_exited.connect(self._hide_hover_popup)
        self.slider.instant_seek_requested.connect(self._on_instant_seek)

        # Floating Hover Thumbnail Popup
        self.thumb_popup = HoverThumbnailPopup(self)
        self._hover_pts: float = -1.0
        ThumbnailManager.get_instance().thumbnail_available.connect(self._on_thumbnail_ready)

        scrubber_row.addWidget(self.slider, 1)
        scrubber_row.addWidget(self.time_label)
        scrubber_row.addWidget(self.lbl_codec_badge)
        scrubber_row.addWidget(self.lbl_color_badge)
        main_layout.addLayout(scrubber_row)

        # 2. Main Controls Row
        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)

        # Left side buttons: Quick Panels
        self.btn_iptv = QPushButton("📺 Live TV")
        self.btn_iptv.setToolTip("Open Live TV / IPTV Channels")
        self.btn_iptv.setFixedHeight(34)
        self.btn_iptv.clicked.connect(self.toggle_iptv_clicked.emit)

        self.btn_playlist = QPushButton("📑 Playlist")
        self.btn_playlist.setToolTip("Toggle Queue & Playlist")
        self.btn_playlist.setFixedHeight(34)
        self.btn_playlist.clicked.connect(self.toggle_playlist_clicked.emit)

        self.btn_tonemap = QPushButton("🎨 Tonemap HDR")
        self.btn_tonemap.setObjectName("accentButton")
        self.btn_tonemap.setToolTip("Dolby Vision, HDR10 & DCI-XYZ Color Management")
        self.btn_tonemap.setFixedHeight(34)
        self.btn_tonemap.clicked.connect(self.toggle_tonemap_clicked.emit)

        self.btn_dcp = QPushButton("🎬 DCP Cinema")
        self.btn_dcp.setObjectName("cinemaButton")
        self.btn_dcp.setToolTip("DCP Package Inspector & Reel Synchronizer")
        self.btn_dcp.setFixedHeight(34)
        self.btn_dcp.clicked.connect(self.open_dcp_clicked.emit)

        controls_row.addWidget(self.btn_iptv)
        controls_row.addWidget(self.btn_playlist)
        controls_row.addWidget(self.btn_tonemap)
        controls_row.addWidget(self.btn_dcp)
        controls_row.addStretch(1)

        # Center buttons: Playback transport (KMPlayer / mpv style)
        self.btn_frame_back = QPushButton()
        self.btn_frame_back.setIcon(draw_frame_step_icon(forward=False))
        self.btn_frame_back.setToolTip("Step Back 1 Frame (,)")
        self.btn_frame_back.setFixedSize(34, 34)
        self.btn_frame_back.clicked.connect(self.frame_back_clicked.emit)

        self.btn_skip_back = QPushButton()
        self.btn_skip_back.setIcon(draw_skip_back_icon())
        self.btn_skip_back.setToolTip("Seek -10s (Left Arrow)")
        self.btn_skip_back.setFixedSize(36, 34)
        self.btn_skip_back.clicked.connect(self.skip_back_clicked.emit)

        self.btn_play = QPushButton()
        self.btn_play.setIcon(draw_play_icon(size=28, color="#ffffff"))
        self.btn_play.setToolTip("Play / Pause (Space)")
        self.btn_play.setFixedSize(46, 36)
        self.btn_play.setStyleSheet("""
            QPushButton {
                background: #22242d;
                border: 1px solid #383b49;
                border-radius: 8px;
            }
            QPushButton:hover {
                background: #2e313d;
                border: 1px solid #52566b;
            }
            QPushButton:pressed {
                background: #1a1b22;
                border: 1px solid #282a35;
            }
            QPushButton:focus {
                outline: none;
            }
        """)
        self.btn_play.clicked.connect(self.play_pause_clicked.emit)

        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(draw_stop_icon())
        self.btn_stop.setToolTip("Stop")
        self.btn_stop.setFixedSize(34, 34)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)

        self.btn_skip_forward = QPushButton()
        self.btn_skip_forward.setIcon(draw_skip_forward_icon())
        self.btn_skip_forward.setToolTip("Seek +10s (Right Arrow)")
        self.btn_skip_forward.setFixedSize(36, 34)
        self.btn_skip_forward.clicked.connect(self.skip_forward_clicked.emit)

        self.btn_frame_forward = QPushButton()
        self.btn_frame_forward.setIcon(draw_frame_step_icon(forward=True))
        self.btn_frame_forward.setToolTip("Step Forward 1 Frame (.)")
        self.btn_frame_forward.setFixedSize(34, 34)
        self.btn_frame_forward.clicked.connect(self.frame_forward_clicked.emit)

        controls_row.addWidget(self.btn_frame_back)
        controls_row.addWidget(self.btn_skip_back)
        controls_row.addWidget(self.btn_play)
        controls_row.addWidget(self.btn_stop)
        controls_row.addWidget(self.btn_skip_forward)
        controls_row.addWidget(self.btn_frame_forward)
        controls_row.addStretch(1)

        # Right side: Volume & Codec Info & Fullscreen
        self.btn_vol = QPushButton()
        self.btn_vol.setIcon(draw_volume_icon(mute=False))
        self.btn_vol.setToolTip("Mute / Unmute (M)")
        self.btn_vol.setFixedSize(34, 34)
        self.btn_vol.clicked.connect(self.mute_toggled.emit)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 130)
        self.vol_slider.setValue(85)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.setToolTip("Volume: 85%")
        self.vol_slider.valueChanged.connect(self._on_vol_changed)

        self.btn_tracks = QPushButton("🔀")
        self.btn_tracks.setToolTip("Track & Stream Selector (Video, Audio, Subtitles) [Ctrl+T]")
        self.btn_tracks.setFixedSize(34, 34)
        self.btn_tracks.clicked.connect(self.open_tracks_clicked.emit)

        self.btn_info = QPushButton("ℹ️")
        self.btn_info.setToolTip("Media & Codec Information (Ctrl+I)")
        self.btn_info.setFixedSize(34, 34)
        self.btn_info.clicked.connect(self.open_codec_info_clicked.emit)

        self.btn_fs = QPushButton()
        self.btn_fs.setIcon(draw_fullscreen_icon(is_fullscreen=False, size=22, color="#cbd5e1"))
        self.btn_fs.setToolTip("Fullscreen Toggle (F)")
        self.btn_fs.setFixedSize(34, 34)
        self.btn_fs.clicked.connect(self.fullscreen_clicked.emit)

        controls_row.addWidget(self.btn_vol)
        controls_row.addWidget(self.vol_slider)
        controls_row.addWidget(self.btn_tracks)
        controls_row.addWidget(self.btn_info)
        controls_row.addWidget(self.btn_fs)

        main_layout.addLayout(controls_row)

        # Disable keyboard focus on all buttons/sliders to prevent focus rects or layout shifting
        for widget in [
            self.btn_iptv, self.btn_playlist, self.btn_tonemap, self.btn_dcp,
            self.btn_frame_back, self.btn_skip_back, self.btn_play, self.btn_stop,
            self.btn_skip_forward, self.btn_frame_forward, self.btn_vol,
            self.btn_tracks, self.btn_info, self.btn_fs, self.slider, self.vol_slider
        ]:
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_resting_geometry(self, x: int, y: int, w: int, h: int):
        """Set container layout geometry without snapping position mid fade-out."""
        self._resting_pos = QPoint(x, y)
        if self._is_fading_out:
            self.resize(w, h)
        else:
            self.setGeometry(x, y, w, h)

    def _on_fade_finished(self):
        if self._is_fading_out and self._opacity_effect.opacity() <= 0.01:
            self._is_fading_out = False
            self.hide()

    def fade_in(self, duration_ms: int = 140):
        """Quickly and smoothly fade & slide the floating OSC island back in."""
        was_hidden = not self.isVisible()
        self._is_fading_out = False
        self._fade_anim.stop()
        self._slide_anim.stop()

        start_opacity = 0.0 if was_hidden else float(self._opacity_effect.opacity())
        if start_opacity >= 0.99 and not was_hidden and self.pos() == self._resting_pos:
            self.raise_()
            return

        if was_hidden:
            self._opacity_effect.setOpacity(0.0)
            self.move(self._resting_pos + QPoint(0, 10))
            self.show()
        self.raise_()

        self._fade_anim.setDuration(duration_ms)
        self._fade_anim.setStartValue(start_opacity)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

        if self._resting_pos != QPoint(0, 0) and self.pos() != self._resting_pos:
            self._slide_anim.setDuration(duration_ms)
            self._slide_anim.setStartValue(self.pos())
            self._slide_anim.setEndValue(self._resting_pos)
            self._slide_anim.start()

    def fade_out(self, duration_ms: int = 180):
        """Quickly and smoothly fade & slide out the floating OSC island."""
        if not self.isVisible() or self._is_fading_out:
            return
        self._is_fading_out = True
        self._fade_anim.stop()
        self._slide_anim.stop()

        self._fade_anim.setDuration(duration_ms)
        self._fade_anim.setStartValue(float(self._opacity_effect.opacity()))
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

        if self._resting_pos != QPoint(0, 0):
            self._slide_anim.setDuration(duration_ms)
            self._slide_anim.setStartValue(self.pos())
            self._slide_anim.setEndValue(self._resting_pos + QPoint(0, 10))
            self._slide_anim.start()

    def set_source_codec(self, codec_text: str):
        if codec_text:
            self.lbl_codec_badge.setText(codec_text)
            self.lbl_codec_badge.setToolTip(f"Source Codec: {codec_text}")

    def set_color_status(self, color_text: str):
        if color_text:
            self.lbl_color_badge.setText(f"COLOR: {color_text}")
            self.lbl_color_badge.setToolTip(f"Active Color Mapping: {color_text}")
            self.btn_tonemap.setToolTip(f"Active Color Mapping: {color_text}")

    def set_play_state(self, is_playing: bool):
        if is_playing:
            self.btn_play.setIcon(draw_pause_icon(size=28, color="#ffffff"))
        else:
            self.btn_play.setIcon(draw_play_icon(size=28, color="#ffffff"))

    def set_fullscreen_state(self, is_fullscreen: bool):
        color = "#00d2ff" if is_fullscreen else "#cbd5e1"
        self.btn_fs.setIcon(draw_fullscreen_icon(is_fullscreen=is_fullscreen, size=22, color=color))
        self.btn_fs.setToolTip("Exit Fullscreen (F / Esc)" if is_fullscreen else "Fullscreen Toggle (F)")

    def update_position(self, current: float, duration: float, buffered: float = 0.0):
        self.duration = duration
        self.buffered_duration = buffered
        self.slider.duration = duration
        self.slider.buffered_duration = buffered

        if not self.is_dragging:
            self.current_time = current
            if duration > 0:
                fraction = current / duration
                self.slider.setValue(int(fraction * self.slider.maximum()))

        self._update_time_label()

    def set_mute_state(self, is_muted: bool):
        self.btn_vol.setIcon(draw_volume_icon(mute=is_muted))

    def _on_vol_changed(self, val: int):
        self.vol_slider.setToolTip(f"Volume: {val}%")
        self.volume_changed.emit(val)

    def _on_instant_seek(self, target: float):
        self.current_time = target
        self._last_seek_target = target
        self._update_time_label()
        self.seek_requested.emit(target)

    def _on_slider_pressed(self):
        self.is_dragging = True

    def _on_slider_released(self):
        self.is_dragging = False
        self.scrub_timer.stop()
        if self.duration > 0:
            target = (self.slider.value() / self.slider.maximum()) * self.duration
            if self._last_seek_target is None or abs(target - self._last_seek_target) > 0.05:
                self._last_seek_target = target
                self.seek_requested.emit(target)
        self._last_seek_target = None

    def _on_slider_value_changed(self, val: int):
        if self.is_dragging and self.duration > 0:
            target = (val / self.slider.maximum()) * self.duration
            self.current_time = target
            self._update_time_label()
            self._pending_scrub_target = target
            if not self.scrub_timer.isActive():
                self.scrub_timer.start()

    def _do_scrub_seek(self):
        if self.is_dragging and self.duration > 0:
            if self._last_seek_target is None or abs(self._pending_scrub_target - self._last_seek_target) > 0.05:
                self._last_seek_target = self._pending_scrub_target
                self.seek_requested.emit(self._pending_scrub_target)

    def set_chapters(self, chapters: list):
        """Set chapters list for seekbar markers and tooltips."""
        self.slider.set_chapters(chapters)

    def set_ab_repeat(self, a: Optional[float], b: Optional[float]):
        """Set or clear A-B Repeat loop region on the seekbar."""
        self.slider.set_ab_repeat(a, b)

    def _show_hover_time(self, target_time: float, buffered_sec: float, global_pos: QPoint):
        self._hover_pts = target_time
        formatted = self._format_time(target_time)
        buf_info = f" (RAM Cache: {buffered_sec:.1f}s)" if buffered_sec > 0 else ""
        time_text = f"{formatted}{buf_info}"

        # Match nearby chapter
        ch_text = ""
        if self.slider.chapters:
            for ch in self.slider.chapters:
                ch_t = ch.get("time", -999.0)
                if abs(target_time - ch_t) <= max(1.5, self.duration * 0.015):
                    ch_text = f"📍 {ch.get('title', 'Chapter')}"
                    break

        # Fetch / load thumbnail
        pix = ThumbnailManager.get_instance().get_thumbnail(target_time)
        self.thumb_popup.set_content(time_text, pix, ch_text)

        # Position popup centered over cursor X and above slider
        popup_w = self.thumb_popup.width() or 192
        popup_h = self.thumb_popup.height() or 140
        popup_x = global_pos.x() - (popup_w // 2)
        popup_y = global_pos.y() - popup_h - 14

        # Clamp within desktop screen bounds
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            popup_x = max(geo.left() + 10, min(geo.right() - popup_w - 10, popup_x))
            popup_y = max(geo.top() + 10, popup_y)

        self.thumb_popup.move(popup_x, popup_y)
        self.thumb_popup.show()
        self.thumb_popup.raise_()

    def _hide_hover_popup(self):
        self._hover_pts = -1.0
        if hasattr(self, "thumb_popup") and self.thumb_popup:
            self.thumb_popup.hide()

    def _on_thumbnail_ready(self, pts: float, pixmap: QPixmap):
        if self._hover_pts >= 0 and abs(self._hover_pts - pts) <= 2.0:
            formatted = self._format_time(self._hover_pts)
            ch_text = ""
            if self.slider.chapters:
                for ch in self.slider.chapters:
                    if abs(self._hover_pts - ch.get("time", -999.0)) <= 1.5:
                        ch_text = f"📍 {ch.get('title', 'Chapter')}"
                        break
            self.thumb_popup.set_content(formatted, pixmap, ch_text)

    def _toggle_time_mode(self, _ev):
        self.show_remaining = not self.show_remaining
        self._update_time_label()

    def _update_time_label(self):
        curr_str = self._format_time(self.current_time)
        if self.show_remaining and self.duration > 0:
            rem = max(0.0, self.duration - self.current_time)
            dur_str = f"-{self._format_time(rem)}"
        else:
            dur_str = self._format_time(self.duration)

        buf_str = f"  [RAM: {self.buffered_duration:.1f}s]" if self.buffered_duration > 0 else ""
        self.time_label.setText(f"{curr_str} / {dur_str}{buf_str}")

    @staticmethod
    def _format_time(seconds: float) -> str:
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"
