"""
BOOB Player - Native Video Viewport Widget
Hosts mpv vo=gpu-next rendering and NVIDIA nvJPEG2000 hardware-accelerated 4K canvas,
handles mouse hover gestures, auto-hiding OSC, and drag-and-drop ingestion of DCPs, videos, and audio.
"""

import sys
import os
import re
from typing import Optional, Tuple, Any
from PyQt6.QtWidgets import QWidget
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRect
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QDragEnterEvent, QDropEvent, QPainter, QColor, QImage, QFont, QPen, QPalette


class NVJPEG2KCanvas(QOpenGLWidget):
    """Dedicated hardware-accelerated OpenGL presentation surface for NVIDIA nvJPEG2000 GPU 4K frames."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.current_frame: Optional[QImage] = None
        self.subtitle_engine = None
        self.current_subtitle: Optional[str] = None
        self.subtitles_visible: bool = True
        self.anamorphic_unsqueeze_143: bool = False
        self.aspect_override: Optional[float] = None

        # Pan & Scan (PnS) Transform State
        self.pns_zoom: float = 1.0
        self.pns_scale_x: float = 1.0
        self.pns_scale_y: float = 1.0
        self.pns_pan_x: float = 0.0
        self.pns_pan_y: float = 0.0
        self.pns_rotate: int = 0
        self.pns_flip_h: bool = False
        self.pns_flip_v: bool = False

        # Split-Screen Comparison Wipe State
        self.split_wipe_enabled: bool = False
        self.split_wipe_pos: float = 0.5
        self.is_dragging_wipe: bool = False
        self.bypass_frame: Optional[QImage] = None

    def set_split_wipe(self, enabled: bool, pos: float = 0.5):
        """Set Split-Screen Comparison Wipe mode and vertical divider position (0.05 to 0.95)."""
        self.split_wipe_enabled = bool(enabled)
        self.split_wipe_pos = max(0.05, min(0.95, float(pos)))
        self.update()

    def set_pns_transform(
        self,
        zoom: float = 1.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        pan_x: float = 0.0,
        pan_y: float = 0.0,
        rotation: int = 0,
        flip_h: bool = False,
        flip_v: bool = False
    ):
        """Update live Pan & Scan transformation matrix for DCP presentation."""
        self.pns_zoom = float(zoom)
        self.pns_scale_x = float(scale_x)
        self.pns_scale_y = float(scale_y)
        self.pns_pan_x = float(pan_x)
        self.pns_pan_y = float(pan_y)
        self.pns_rotate = int(rotation) % 360
        self.pns_flip_h = bool(flip_h)
        self.pns_flip_v = bool(flip_v)
        self.update()

    def set_anamorphic_unsqueeze(self, enabled: bool):
        self.anamorphic_unsqueeze_143 = bool(enabled)
        self.update()

    def set_aspect_override(self, ratio: Any):
        if ratio is None or ratio == "-1":
            self.aspect_override = None
        elif isinstance(ratio, (int, float)):
            self.aspect_override = float(ratio)
        elif isinstance(ratio, str):
            try:
                if ":" in ratio:
                    num, den = ratio.split(":", 1)
                    self.aspect_override = float(num) / float(den)
                else:
                    self.aspect_override = float(ratio)
            except Exception:
                self.aspect_override = None
        else:
            self.aspect_override = None
        self.update()

    @property
    def is_anamorphic_143(self) -> bool:
        """True if either automatic IMAX Laser anamorphic flag or manual 1.43:1 aspect ratio is active."""
        return bool(self.anamorphic_unsqueeze_143 or (self.aspect_override is not None and abs(self.aspect_override - 1.43) < 0.02))

    def get_unsqueezed_dimensions(self, img_w: int, img_h: int) -> Tuple[int, int]:
        """
        Compute target display dimensions when anamorphic 1.43:1 unsqueeze or aspect override is active.
        Keeps width constant at 4096 (4K) or 2048 (2K) and stretches vertically to match 1.43:1.
        """
        if img_w <= 0 or img_h <= 0:
            return img_w, img_h
        if self.anamorphic_unsqueeze_143 or (self.aspect_override and abs(self.aspect_override - 1.43) < 0.02):
            const_w = 4096 if img_w == 4096 else (2048 if img_w == 2048 else img_w)
            stretched_h = int(round(const_w / 1.43))
            return const_w, stretched_h
        if self.aspect_override and self.aspect_override > 0:
            return img_w, int(round(img_w / self.aspect_override))
        return img_w, img_h

    def unsqueeze_qimage(self, qimg: QImage) -> QImage:
        """Return a QImage stretched to get_unsqueezed_dimensions()."""
        if qimg is None or qimg.isNull():
            return qimg
        target_w, target_h = self.get_unsqueezed_dimensions(qimg.width(), qimg.height())
        if target_w == qimg.width() and target_h == qimg.height():
            return qimg
        return qimg.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def set_subtitle_engine(self, engine):
        self.subtitle_engine = engine

    def set_subtitles_visible(self, visible: bool):
        self.subtitles_visible = visible
        self.update()

    def set_current_pts(self, pts: float):
        if self.subtitle_engine and self.subtitles_visible:
            new_sub = self.subtitle_engine.get_text_at_pts(pts)
            if new_sub != self.current_subtitle:
                self.current_subtitle = new_sub
                self.update()
        elif self.current_subtitle is not None:
            self.current_subtitle = None
            self.update()

    def set_image(self, img: QImage):
        self.current_frame = img
        self.update()

    def clear(self):
        self.current_frame = None
        self.current_subtitle = None
        self.update()

    def paintGL(self):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        if self.current_frame and not self.current_frame.isNull():
            img_w = self.current_frame.width()
            img_h = self.current_frame.height()
            w = self.width()
            h = self.height()

            if img_w > 0 and img_h > 0 and w > 0 and h > 0:
                eff_w, eff_h = self.get_unsqueezed_dimensions(img_w, img_h)
                scale = min(w / eff_w, h / eff_h)
                draw_w = int(eff_w * scale)
                draw_h = int(eff_h * scale)
                x = (w - draw_w) // 2
                y = (h - draw_h) // 2
                target_rect = QRect(x, y, draw_w, draw_h)

                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

                # Apply Pan & Scan center-anchored affine transform
                painter.save()
                cx = (w / 2.0) + (self.pns_pan_x * w)
                cy = (h / 2.0) + (self.pns_pan_y * h)
                painter.translate(cx, cy)
                if self.pns_rotate != 0:
                    painter.rotate(self.pns_rotate)

                sx = self.pns_zoom * self.pns_scale_x * (-1.0 if self.pns_flip_h else 1.0)
                sy = self.pns_zoom * self.pns_scale_y * (-1.0 if self.pns_flip_v else 1.0)
                painter.scale(sx, sy)

                pns_target_rect = QRect(-draw_w // 2, -draw_h // 2, draw_w, draw_h)
                painter.drawImage(pns_target_rect, self.current_frame)
                painter.restore()

                # Render active SMPTE/Interop DCP subtitle overlay
                if self.subtitles_visible and self.current_subtitle:
                    clean_text = re.sub(r'</?[ibu]>', '', self.current_subtitle)
                    font_size = max(18, int(draw_h * 0.038))
                    font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
                    if "<i>" in self.current_subtitle:
                        font.setItalic(True)
                    painter.setFont(font)

                    line_count = max(1, clean_text.count('\n') + 1)
                    sub_box_h = int(font_size * (1.5 * line_count + 0.8))
                    bottom_margin = max(24, int(draw_h * 0.05))
                    sub_rect = QRect(
                        x + int(draw_w * 0.05),
                        y + draw_h - sub_box_h - bottom_margin,
                        int(draw_w * 0.9),
                        sub_box_h
                    )

                    # High-contrast 2px dark drop shadow/outline for cinema readability
                    painter.setPen(QColor(0, 0, 0, 230))
                    for dx in (-2, -1, 0, 1, 2):
                        for dy in (-2, -1, 0, 1, 2):
                            if dx != 0 or dy != 0:
                                painter.drawText(
                                    sub_rect.translated(dx, dy),
                                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                                    clean_text
                                )
                    # Crisp cinema white text
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(
                        sub_rect,
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                        clean_text
                    )

                # Render Split-Screen Comparison Wipe Divider & Badges
                if self.split_wipe_enabled:
                    wipe_x = int(w * self.split_wipe_pos)
                    # Minimalist Crisp Hairline Separator Line
                    painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
                    painter.drawLine(wipe_x, 0, wipe_x, h)

                    # Center Draggable Minimalist Handle
                    handle_rect = QRect(wipe_x - 14, (h // 2) - 18, 28, 36)
                    painter.fillRect(handle_rect, QColor(18, 19, 24, 235))
                    painter.setPen(QColor(255, 255, 255, 140))
                    painter.drawRect(handle_rect)
                    painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                    painter.drawText(handle_rect, Qt.AlignmentFlag.AlignCenter, "⮜ ⮞")

                    # Minimalist Studio QC Badges
                    badge_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
                    painter.setFont(badge_font)

                    # Left Badge
                    lbl_left_rect = QRect(max(10, wipe_x - 110), 18, 95, 24)
                    painter.fillRect(lbl_left_rect, QColor(18, 19, 24, 230))
                    painter.setPen(QColor(255, 255, 255, 80))
                    painter.drawRect(lbl_left_rect)
                    painter.setPen(QColor("#f3f4f6"))
                    painter.drawText(lbl_left_rect, Qt.AlignmentFlag.AlignCenter, "◀ GRADED")

                    # Right Badge
                    lbl_right_rect = QRect(min(w - 105, wipe_x + 15), 18, 95, 24)
                    painter.fillRect(lbl_right_rect, QColor(18, 19, 24, 230))
                    painter.setPen(QColor(255, 255, 255, 80))
                    painter.drawRect(lbl_right_rect)
                    painter.setPen(QColor("#9ca3af"))
                    painter.drawText(lbl_right_rect, Qt.AlignmentFlag.AlignCenter, "ORIGINAL ▶")

        painter.end()

    # Forward UI interaction events to parent VideoWidget
    def mousePressEvent(self, ev: QMouseEvent):
        if self.split_wipe_enabled and ev.button() == Qt.MouseButton.LeftButton:
            wipe_x = int(self.width() * self.split_wipe_pos)
            if abs(ev.position().x() - wipe_x) <= 30:
                self.is_dragging_wipe = True
                ev.accept()
                return
        p = self.parentWidget()
        if p and hasattr(p, "mousePressEvent"):
            p.mousePressEvent(ev)
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if self.is_dragging_wipe:
            self.is_dragging_wipe = False
            ev.accept()
            return
        p = self.parentWidget()
        if p and hasattr(p, "mouseReleaseEvent"):
            p.mouseReleaseEvent(ev)
        super().mouseReleaseEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self.split_wipe_enabled and self.is_dragging_wipe and self.width() > 0:
            new_pos = max(0.05, min(0.95, ev.position().x() / float(self.width())))
            self.split_wipe_pos = new_pos
            self.update()
            ev.accept()
            return
        p = self.parentWidget()
        if p and hasattr(p, "mouseMoveEvent"):
            p.mouseMoveEvent(ev)
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, ev: QMouseEvent):
        p = self.parentWidget()
        if p and hasattr(p, "mouseDoubleClickEvent"):
            p.mouseDoubleClickEvent(ev)
        super().mouseDoubleClickEvent(ev)

    def wheelEvent(self, ev: QWheelEvent):
        p = self.parentWidget()
        if p and hasattr(p, "wheelEvent"):
            p.wheelEvent(ev)
        super().wheelEvent(ev)

    def dragEnterEvent(self, ev: QDragEnterEvent):
        p = self.parentWidget()
        if p and hasattr(p, "dragEnterEvent"):
            p.dragEnterEvent(ev)
        else:
            ev.ignore()

    def dropEvent(self, ev: QDropEvent):
        p = self.parentWidget()
        if p and hasattr(p, "dropEvent"):
            p.dropEvent(ev)

    def contextMenuEvent(self, ev):
        p = self.parentWidget()
        if p and hasattr(p, "contextMenuEvent"):
            p.contextMenuEvent(ev)
        else:
            super().contextMenuEvent(ev)


class NativeViewportWidget(QWidget):
    """Direct native hardware viewport widget for mpv Direct3D 11 swapchain."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0))
        self.setPalette(pal)
        self.setStyleSheet("background-color: #000000;")
        self.setMouseTracking(True)

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))


class VideoWidget(QWidget):
    double_clicked = pyqtSignal()
    mouse_moved_signal = pyqtSignal()
    file_dropped = pyqtSignal(str)
    folder_dropped = pyqtSignal(str)
    wheel_scrolled = pyqtSignal(int)
    context_menu_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0))
        self.setPalette(pal)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background-color: #000000;")

        # Inactivity auto-hide timer for floating OSC HUD
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(850)
        self.hide_timer.setSingleShot(True)

        # 1. Child viewport for MPV vo=gpu-next
        self.mpv_viewport = NativeViewportWidget(self)

        # 2. Child viewport for NVIDIA nvJPEG2000 native 4K GPU rendering
        self.nv_viewport = NVJPEG2KCanvas(self)
        self.nv_viewport.hide()

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

    def get_mpv_wid(self) -> int:
        """Return the window handle (HWND) dedicated to mpv video presentation."""
        return int(self.mpv_viewport.winId())

    def show_nv_viewport(self):
        """Activate NVIDIA nvJPEG2000 presentation surface."""
        self.nv_viewport.setGeometry(self.rect())
        self.nv_viewport.show()
        self.nv_viewport.raise_()
        self.mpv_viewport.hide()

    def show_mpv_viewport(self):
        """Activate standard mpv presentation surface."""
        self.mpv_viewport.setGeometry(self.rect())
        self.mpv_viewport.show()
        self.mpv_viewport.raise_()
        self.nv_viewport.hide()
        self.nv_viewport.clear()

    def set_subtitle_engine(self, engine):
        """Bind DCP subtitle engine to the native GPU viewport."""
        self.nv_viewport.set_subtitle_engine(engine)

    def set_subtitles_visible(self, visible: bool):
        """Toggle subtitle rendering visibility on native GPU viewport."""
        self.nv_viewport.set_subtitles_visible(visible)

    def set_anamorphic_unsqueeze(self, enabled: bool):
        """Toggle vertical 1.43:1 anamorphic unsqueeze on the native GPU viewport."""
        self.nv_viewport.set_anamorphic_unsqueeze(enabled)

    def set_aspect_override(self, ratio_str: str):
        """Apply explicit display aspect ratio override on the native GPU viewport."""
        ratio_val: Optional[float] = None
        if ratio_str and ratio_str != "-1":
            try:
                if ":" in ratio_str:
                    num, den = ratio_str.split(":", 1)
                    ratio_val = float(num) / float(den)
                else:
                    ratio_val = float(ratio_str)
            except Exception:
                ratio_val = None
        self.nv_viewport.set_aspect_override(ratio_val)

    def present_frame(self, qimage: QImage, frame_idx: int = 0, pts: float = 0.0):
        """Deliver decoded 4K frame and synchronized PTS to the GPU presentation canvas."""
        self.nv_viewport.set_current_pts(pts)
        self.nv_viewport.set_image(qimage)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        r = self.rect()
        self.mpv_viewport.setGeometry(r)
        self.nv_viewport.setGeometry(r)

    def mouseMoveEvent(self, ev: QMouseEvent):
        self.mouse_moved_signal.emit()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide_timer.start()
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(ev)

    def contextMenuEvent(self, ev):
        pos = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
        self.context_menu_requested.emit(pos)
        ev.accept()

    def wheelEvent(self, ev: QWheelEvent):
        delta = ev.angleDelta().y()
        self.wheel_scrolled.emit(delta)
        super().wheelEvent(ev)

    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev: QDropEvent):
        urls = ev.mimeData().urls()
        if not urls:
            return

        for url in urls:
            local_path = url.toLocalFile()
            if os.path.isdir(local_path):
                self.folder_dropped.emit(local_path)
            elif os.path.isfile(local_path):
                self.file_dropped.emit(local_path)
        ev.acceptProposedAction()
