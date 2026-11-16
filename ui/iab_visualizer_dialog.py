"""
BOOB Player - 3D IAB / Dolby Atmos Spatial Audio Object Visualizer
Renders real-time 3D interactive holographic auditorium view of SMPTE ST 2098-2
Immersive Audio Bitstream (IAB) spatial sound objects during playback.
"""

import math
import time
from typing import List, Optional, Tuple, Dict
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QCheckBox,
    QComboBox, QSplitter
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient,
    QLinearGradient, QPainterPath, QMouseEvent, QWheelEvent
)

from core.iab_engine import IABTrackMetadata, IABSpatialObject, IABEngine


# Color palette for 3D spatial objects (Dolby Atmos RMU green/yellow accents + fallback colors)
OBJECT_COLORS = [
    QColor(31, 214, 24),    # Dolby Atmos Active Green
    QColor(232, 222, 30),   # Dolby Atmos Yellow Core
    QColor(15, 122, 24),    # Deep Spatial Green
    QColor(72, 218, 52),    # Neon Z-Axis Green
    QColor(0, 210, 255),    # Cyan
    QColor(232, 36, 184),   # Magenta Origin
    QColor(168, 56, 140),   # Screen Magenta
    QColor(245, 158, 11),   # Amber
    QColor(16, 185, 129),   # Emerald
    QColor(56, 189, 248),   # Sky
    QColor(132, 204, 22),   # Lime
    QColor(234, 179, 8),    # Yellow
]


def _register_entity(
    rendered: List[Dict[str, object]],
    cache: Dict[str, Dict[str, object]],
    entity_id: str,
    label: str,
    px: float,
    py: float,
    r: float,
    sc: float,
):
    if not entity_id:
        return
    entry = {
        "id": entity_id,
        "label": label or entity_id,
        "px": float(px),
        "py": float(py),
        "r": float(r),
        "sc": float(sc),
    }
    rendered.append(entry)
    cache[entity_id] = entry


class Auditorium3DCanvas(QWidget):
    """Interactive 3D Dolby Atmos RMU / Cinema Monitor auditorium rendering spatial sound objects."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(460, 380)

        # 3D View Angles (degrees) — opens in symmetric Dolby Atmos RMU perspective
        self.yaw: float = 0.0       # Orbit around center (-180 to 180)
        self.pitch: float = 22.0    # Elevation tilt (0 to 90)
        self.zoom: float = 1.0      # Zoom scale factor
        self.show_trails: bool = True

        # Mouse interaction state
        self.last_mouse_pos: Optional[QPoint] = None
        self.is_dragging: bool = False

        # Spatial data
        self.current_objects: List[IABSpatialObject] = []
        # Object history for trajectory trails: obj_id -> list of (x, y, z)
        self.trails_history: Dict[int, List[Tuple[float, float, float]]] = {}
        self.max_audio_objects: int = 118
        self.max_rendered_channels: int = 128

        # Hover entity tracking & smooth inward/outward label transition state
        self._rendered_entities: List[Dict[str, object]] = []
        self.hover_mouse_pos: Optional[QPoint] = None
        self.hovered_entity_id: Optional[str] = None
        self._hover_progress: Dict[str, float] = {}
        self._hover_entity_cache: Dict[str, Dict[str, object]] = {}
        self._hover_anim_timer = QTimer(self)
        self._hover_anim_timer.setInterval(16)  # ~60 FPS smooth transition
        self._hover_anim_timer.timeout.connect(self._on_hover_anim_tick)

    def set_objects(self, objects: List[IABSpatialObject]):
        self.current_objects = list(objects) if objects else []
        # Update trails history
        active_ids = set()
        for obj in self.current_objects:
            active_ids.add(obj.object_id)
            if obj.object_id not in self.trails_history:
                self.trails_history[obj.object_id] = []
            hist = self.trails_history[obj.object_id]
            hist.append((obj.x, obj.y, obj.z))
            if len(hist) > 12:
                hist.pop(0)

        # Prune old inactive objects
        for oid in list(self.trails_history.keys()):
            if oid not in active_ids:
                del self.trails_history[oid]

        self.update()

    def set_view_preset(self, preset: str):
        if preset == "dolby":
            self.yaw = 0.0
            self.pitch = 22.0
        elif preset == "3d":
            self.yaw = 24.0
            self.pitch = 22.0
        elif preset == "top":
            self.yaw = 0.0
            self.pitch = 88.0
        elif preset == "front":
            self.yaw = 0.0
            self.pitch = 2.0
        elif preset == "side":
            self.yaw = 90.0
            self.pitch = 2.0
        self.update()

    def reset_view(self):
        self.zoom = 1.0
        self.set_view_preset("dolby")

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.last_mouse_pos = ev.pos()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent):
        self.hover_mouse_pos = ev.pos()
        if self.is_dragging and self.last_mouse_pos is not None:
            delta = ev.pos() - self.last_mouse_pos
            self.last_mouse_pos = ev.pos()
            self.yaw = (self.yaw + delta.x() * 0.7) % 360.0
            if self.yaw > 180:
                self.yaw -= 360
            self.pitch = max(0.0, min(89.0, self.pitch + delta.y() * 0.7))
            self.update()
        else:
            self._update_hovered_entity(ev.pos())
        super().mouseMoveEvent(ev)

    def leaveEvent(self, event):
        self.hover_mouse_pos = None
        self._update_hovered_entity(None)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        self.is_dragging = False
        self.last_mouse_pos = None
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev: QWheelEvent):
        delta = ev.angleDelta().y()
        if delta != 0:
            steps = delta / 120.0
            factor = math.pow(1.15, steps)
            self.zoom = max(0.25, self.zoom * factor)
            self.update()
        super().wheelEvent(ev)

    def project_3d(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        """Public alias for 3D perspective projection."""
        return self._project(x, y, z)

    def _project(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        """
        Project 3D coordinate (-1..1) into 1-point Dolby Atmos RMU auditorium perspective.
        Coordinate system:
        X: Left (-1) to Right (+1)
        Y: Rear / Audience (-1) to Front / Screen (+1)
        Z: Floor (-1) to Ceiling (+1)
        """
        yaw_rad = math.radians(self.yaw)
        pitch_eff = math.radians(self.pitch if self.pitch >= 70.0 else (self.pitch + 6.0))
        z_scaled = z * 0.45

        # 1. Rotate around Z axis (yaw)
        x1 = x * math.cos(yaw_rad) - y * math.sin(yaw_rad)
        y1 = x * math.sin(yaw_rad) + y * math.cos(yaw_rad)

        # 2. Elevate & tilt camera downward along X axis (y=+1 far, y=-1 near; +z above)
        y2 = y1 * math.cos(pitch_eff) - z_scaled * math.sin(pitch_eff)
        z2 = -y1 * math.sin(pitch_eff) - z_scaled * math.cos(pitch_eff)

        # 3. Perspective Projection (fov scales linearly with zoom for unbounded zoom-in)
        cam_dist = 2.45
        dist = max(0.35, cam_dist + y2)
        fov = min(self.width(), self.height()) * 0.72 * self.zoom
        scale = fov / dist

        cx = self.width() / 2.0
        cy = self.height() * 0.50

        px = cx + (x1 * scale)
        py = cy + (z2 * scale)

        return px, py, scale

    def _inner_viewport_rect(self) -> QRectF:
        mx = self.width() * 0.065
        my = self.height() * 0.045
        return QRectF(mx, my, max(10.0, self.width() - 2 * mx), max(10.0, self.height() - 2 * my))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Reset entity list each paint pass for crisp hover hit-testing
        self._rendered_entities = []

        # 1. Outer solid black cinema monitor frame + shaded grey inner viewport
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        vp = self._inner_viewport_rect()
        bg = QLinearGradient(0, vp.top(), 0, vp.bottom())
        bg.setColorAt(0.0, QColor(20, 21, 23))
        bg.setColorAt(0.68, QColor(58, 60, 63))
        bg.setColorAt(1.0, QColor(40, 42, 45))
        painter.fillRect(vp, bg)

        # Clip 3D auditorium content cleanly to inner monitor viewport
        painter.save()
        painter.setClipRect(vp)

        # 2. Draw Auditorium Wireframe Box
        self._draw_auditorium_wireframe(painter)

        # 3. Draw Magenta Screen Frame
        self._draw_cinema_screen(painter)

        # 4. Draw Reference Axes & Pink/Magenta Origin Marker
        self._draw_listener_seat(painter)

        # 5. Draw Circular Surround Speakers & Yellow Bed Perimeter Nodes
        self._draw_speakers(painter)

        # 6. Draw Circular Green Spatial Pads & Live IAB Spatial Objects
        self._draw_spatial_objects(painter)

        # 7. Draw Hover-Only Labels with Smooth Inward/Outward Transition
        self._draw_hover_labels(painter)

        painter.restore()

        # 8. Subtle HUD Telemetry in Outer Black Frame
        self._draw_hud(painter)

    def _draw_auditorium_wireframe(self, painter: QPainter):
        """Draw crisp 12-edge Dolby Atmos auditorium bounding wireframe."""
        wire_pen = QPen(QColor(186, 190, 196, 220), 1.4, Qt.PenStyle.SolidLine)
        painter.setPen(wire_pen)

        corners = [
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),  # 0..3 Floor
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),      # 4..7 Ceiling
        ]
        proj = [self._project(*c) for c in corners]

        for i in range(4):
            painter.drawLine(int(proj[i][0]), int(proj[i][1]), int(proj[(i + 1) % 4][0]), int(proj[(i + 1) % 4][1]))
            painter.drawLine(int(proj[i][0]), int(proj[i][1]), int(proj[i + 4][0]), int(proj[i + 4][1]))
            painter.drawLine(int(proj[i + 4][0]), int(proj[i + 4][1]), int(proj[((i + 1) % 4) + 4][0]), int(proj[((i + 1) % 4) + 4][1]))

    def _draw_cinema_screen(self, painter: QPainter):
        """Draw magenta screen rectangle outline on front wall (Y = +1.0)."""
        p_tl = self._project(-0.88, 1.0, 0.62)
        p_tr = self._project(0.88, 1.0, 0.62)
        p_br = self._project(0.88, 1.0, -0.28)
        p_bl = self._project(-0.88, 1.0, -0.28)

        poly = QPainterPath()
        poly.moveTo(p_tl[0], p_tl[1])
        poly.lineTo(p_tr[0], p_tr[1])
        poly.lineTo(p_br[0], p_br[1])
        poly.lineTo(p_bl[0], p_bl[1])
        poly.closeSubpath()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(168, 56, 140, 235), 2.0))
        painter.drawPath(poly)

    def _max_entity_radius(self) -> float:
        return max(40.0, max(self.width(), self.height()) * 0.45)

    def _draw_listener_seat(self, painter: Optional[QPainter]):
        """Draw Dolby RMU center origin sphere, vertical green Z-axis, and horizontal red X-axis."""
        vp = self._inner_viewport_rect()
        origin = self._project(0.0, 0.66, -1.0)
        left_x = self._project(-1.55, 0.66, -1.0)

        r = max(4.0, min(self._max_entity_radius(), 0.048 * origin[2]))
        _register_entity(
            self._rendered_entities,
            self._hover_entity_cache,
            "origin_listener",
            "Reference Origin / Listener",
            origin[0],
            origin[1],
            r,
            origin[2],
        )
        if painter is None:
            return

        # Horizontal red-orange X-axis to the left
        painter.setPen(QPen(QColor(180, 68, 42, 210), 1.5))
        painter.drawLine(int(left_x[0]), int(left_x[1]), int(origin[0]), int(origin[1]))

        # Vertical bright green Z-axis straight up to top edge of viewport
        painter.setPen(QPen(QColor(72, 218, 52, 220), 1.5))
        painter.drawLine(int(origin[0]), int(origin[1]), int(origin[0]), int(vp.top()))

        # Pink / magenta circular reference sphere at origin
        painter.setPen(QPen(QColor(255, 130, 225, 200), 1.0))
        painter.setBrush(QColor(232, 36, 184))
        painter.drawEllipse(QRectF(origin[0] - r, origin[1] - r, r * 2.0, r * 2.0))

    def _object_proximity(self, sx: float, sy: float, sz: float, radius: float = 0.55) -> float:
        """Return peak 0..1 activation weight of active IAB spatial objects near (sx, sy, sz)."""
        best = 0.0
        for obj in self.current_objects:
            d = math.sqrt((obj.x - sx) ** 2 + (obj.y - sy) ** 2 + (obj.z - sz) ** 2)
            if d < radius:
                best = max(best, 1.0 - (d / radius))
        return best

    def _draw_speaker_box(
        self,
        painter: Optional[QPainter],
        x: float,
        y: float,
        z: float,
        size_scale: float = 1.0,
        active_level: float = 0.0,
        yellow_core: bool = False,
        entity_id: str = "",
        label: str = "",
    ):
        """Draw a matte black or active-green circular Dolby RMU speaker node at (x, y, z)."""
        px, py, sc = self._project(x, y, z)
        r = max(3.5, min(self._max_entity_radius(), 0.062 * sc * size_scale))
        _register_entity(
            self._rendered_entities,
            self._hover_entity_cache,
            entity_id,
            label,
            px,
            py,
            r,
            sc,
        )
        if painter is None:
            return

        if active_level >= 0.75:
            fill = QColor(31, 214, 24)
            edge = QColor(52, 235, 45)
        elif active_level > 0.2:
            fill = QColor(15, 122, 24)
            edge = QColor(31, 165, 38)
        else:
            fill = QColor(7, 8, 9)
            edge = QColor(18, 20, 23)

        painter.setPen(QPen(edge, 1.0))
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(px - r, py - r, r * 2.0, r * 2.0))

        if yellow_core:
            cr = max(2.0, r * 0.46)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(232, 222, 30))
            painter.drawEllipse(QRectF(px - cr, py - cr, cr * 2.0, cr * 2.0))

    def _draw_speakers(self, painter: Optional[QPainter]):
        """Draw circular front screen array, wall surrounds, and rear floor speakers."""
        # 1. Upper & lower front wall speakers
        front_specs = [
            (-0.58, 1.0, 0.96, 0.88, 0.85, False, "spk_top_front_l", "Top Front Left (Ltf)"),
            (0.58, 1.0, 0.96, 0.88, 0.85, True, "spk_top_front_r", "Top Front Right (Rtf)"),
            (-0.78, 1.0, 0.82, 1.12, 0.0, False, "spk_upper_l", "Front Height Left (Lh)"),
            (0.78, 1.0, 0.82, 1.12, 0.0, False, "spk_upper_r", "Front Height Right (Rh)"),
        ]
        for sx, sy, sz, ss, base, ycore, eid, lbl in front_specs:
            act = max(base, self._object_proximity(sx, sy, sz))
            self._draw_speaker_box(
                painter, sx, sy, sz, size_scale=ss, active_level=act, yellow_core=ycore, entity_id=eid, label=lbl
            )

        # 2. 7 Screen array speakers across middle of magenta screen
        screen_specs = [
            (-0.72, "spk_scr_l", "Screen Left (L)"),
            (-0.48, "spk_scr_lc", "Screen Left-Center (Lc)"),
            (-0.24, "spk_scr_cl", "Screen Inner Left"),
            (0.0, "spk_scr_c", "Screen Center (C)"),
            (0.24, "spk_scr_cr", "Screen Inner Right"),
            (0.48, "spk_scr_rc", "Screen Right-Center (Rc)"),
            (0.72, "spk_scr_r", "Screen Right (R)"),
        ]
        for idx, (sx, eid, lbl) in enumerate(screen_specs):
            base = 0.85 if idx in (0, 3, 6) else 0.0
            act = max(base, self._object_proximity(sx, 1.0, 0.14))
            self._draw_speaker_box(
                painter, sx, 1.0, 0.14, size_scale=0.85, active_level=act, yellow_core=(idx == 3), entity_id=eid, label=lbl
            )

        # Center lower subwoofer on green vertical axis
        self._draw_speaker_box(
            painter,
            0.0,
            0.88,
            -0.68,
            size_scale=0.85,
            active_level=max(0.85, self._object_proximity(0.0, 0.88, -0.68)),
            entity_id="spk_lfe",
            label="Subwoofer (LFE)",
        )

        # 3. Side-wall surround speakers (5 left + 5 right along wall slopes)
        side_coords = [
            (0.68, 0.36, 1.08, 1),
            (0.32, 0.10, 1.08, 2),
            (-0.04, -0.18, 1.08, 3),
            (-0.42, -0.46, 1.12, 4),
            (-0.80, -0.76, 1.18, 5),
        ]
        for sy, sz, ss, idx in side_coords:
            self._draw_speaker_box(
                painter, -1.06, sy, sz, size_scale=ss,
                active_level=self._object_proximity(-1.06, sy, sz),
                entity_id=f"spk_lss_{idx}",
                label=f"Left Side Surround #{idx}",
            )
            self._draw_speaker_box(
                painter, 1.06, sy, sz, size_scale=ss,
                active_level=self._object_proximity(1.06, sy, sz),
                entity_id=f"spk_rss_{idx}",
                label=f"Right Side Surround #{idx}",
            )

        # 4. Rear floor speakers (3 centered + 2 outer corner housings)
        rear_specs = [
            (-0.68, 1.22, "spk_rear_l", "Left Rear Surround (Lrs)"),
            (-0.35, 1.02, "spk_rear_lc", "Rear Back Left (Lb)"),
            (0.0, 1.02, "spk_rear_c", "Rear Back Center (Cb)"),
            (0.35, 1.02, "spk_rear_rc", "Rear Back Right (Rb)"),
            (0.68, 1.22, "spk_rear_r", "Right Rear Surround (Rrs)"),
        ]
        for rx, ss, eid, lbl in rear_specs:
            self._draw_speaker_box(
                painter, rx, -0.84, -0.80, size_scale=ss,
                active_level=self._object_proximity(rx, -0.84, -0.80),
                entity_id=eid,
                label=lbl,
            )

    def _draw_yellow_bed_nodes(self, painter: Optional[QPainter]):
        """Draw yellow circular bed nodes along the perimeter wireframe rails."""
        yellow_nodes = [
            (-1.0, 1.0, 1.0, 4.8, "bed_ltf", "Bed Top Front Left (Ltf)"),
            (1.0, 1.0, 1.0, 4.8, "bed_rtf", "Bed Top Front Right (Rtf)"),
            (-1.0, 0.40, 1.0, 5.4, "bed_ltm", "Bed Top Side Left (Ltm)"),
            (1.0, 0.40, 1.0, 5.4, "bed_rtm", "Bed Top Side Right (Rtm)"),
            (-1.0, -1.0, 1.0, 11.2, "bed_ltr", "Bed Top Rear Left (Ltr)"),
            (1.0, -1.0, 1.0, 11.2, "bed_rtr", "Bed Top Rear Right (Rtr)"),
            (-1.0, -1.0, -0.45, 7.2, "bed_lrs", "Bed Rear Corner Left (Lrs)"),
            (1.0, -1.0, -0.45, 7.2, "bed_rrs", "Bed Rear Corner Right (Rrs)"),
            (-1.0, 1.0, 0.14, 4.4, "bed_lw", "Bed Front Wide Left (Lw)"),
            (1.0, 1.0, 0.14, 4.4, "bed_rw", "Bed Front Wide Right (Rw)"),
        ]
        max_r = self._max_entity_radius()
        for nx, ny, nz, base_r, eid, lbl in yellow_nodes:
            px, py, sc = self._project(nx, ny, nz)
            r = max(3.0, min(max_r, base_r * (sc / 145.0)))
            _register_entity(
                self._rendered_entities,
                self._hover_entity_cache,
                eid,
                lbl,
                px,
                py,
                r,
                sc,
            )
            if painter is None:
                continue
            painter.setPen(QPen(QColor(175, 165, 20, 220), 1.0))
            painter.setBrush(QColor(232, 222, 30))
            painter.drawEllipse(QRectF(px - r, py - r, r * 2.0, r * 2.0))

    def _draw_green_pad(
        self,
        painter: Optional[QPainter],
        x: float,
        y: float,
        z: float,
        radius_factor: float = 1.0,
        bright: bool = True,
        yellow_core: bool = False,
        entity_id: str = "",
        label: str = "",
    ):
        """Draw a circular Dolby RMU green spatial zone/object pad."""
        px, py, sc = self._project(x, y, z)
        r = max(4.5, min(self._max_entity_radius(), 0.088 * sc * radius_factor))
        _register_entity(
            self._rendered_entities,
            self._hover_entity_cache,
            entity_id,
            label,
            px,
            py,
            r,
            sc,
        )
        if painter is None:
            return

        fill = QColor(31, 214, 24) if bright else QColor(15, 122, 24)
        edge = QColor(56, 232, 48) if bright else QColor(24, 155, 36)

        painter.setPen(QPen(edge, 1.0))
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(px - r, py - r, r * 2.0, r * 2.0))

        if yellow_core:
            cr = max(2.6, r * 0.56)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(232, 222, 30))
            painter.drawEllipse(QRectF(px - cr, py - cr, cr * 2.0, cr * 2.0))

    def _draw_spatial_objects(self, painter: Optional[QPainter]):
        """Draw circular green spatial pads, yellow perimeter bed nodes, and live IAB spatial objects."""
        # 1. Baseline symmetric cinema bed / spatial zone pads
        zone_pads = [
            (-0.92, 0.55, 0.50, 0.88, True, False, "zone_front_top_l", "Front Elevated Zone Left"),
            (0.92, 0.55, 0.50, 0.88, True, False, "zone_front_top_r", "Front Elevated Zone Right"),
            (-0.72, 0.14, -0.18, 0.82, True, True, "zone_mid_l", "Mid Surround Zone Left"),
            (0.72, 0.14, -0.18, 0.82, True, True, "zone_mid_r", "Mid Surround Zone Right"),
            (-0.82, 0.02, 0.16, 1.15, True, False, "zone_side_l", "Side Array Zone Left"),
            (0.82, 0.02, 0.16, 1.15, True, False, "zone_side_r", "Side Array Zone Right"),
            (-0.74, -0.56, -0.45, 0.88, False, False, "zone_rear_l", "Rear Surround Zone Left"),
            (0.74, -0.56, -0.45, 0.88, False, False, "zone_rear_r", "Rear Surround Zone Right"),
        ]
        for zx, zy, zz, rf, is_bright, has_y, eid, lbl in zone_pads:
            prox = self._object_proximity(zx, zy, zz, radius=0.8)
            self._draw_green_pad(
                painter,
                zx,
                zy,
                zz,
                radius_factor=rf * (1.0 + 0.12 * prox),
                bright=(is_bright or prox > 0.4),
                yellow_core=has_y,
                entity_id=eid,
                label=lbl,
            )

        # Draw yellow perimeter nodes above green pads so front-post and corner nodes remain crisp
        self._draw_yellow_bed_nodes(painter)

        # 2. Trajectory trails for active IAB objects (subtle green lines)
        if painter is not None and self.show_trails:
            for oid, hist in list(self.trails_history.items()):
                hist_copy = list(hist)
                if len(hist_copy) > 1:
                    for step_i in range(len(hist_copy) - 1):
                        alpha = int(50 + (150 * (step_i / len(hist_copy))))
                        painter.setPen(QPen(QColor(31, 214, 24, alpha), 1.3))
                        p_a = self._project(*hist_copy[step_i])
                        p_b = self._project(*hist_copy[step_i + 1])
                        painter.drawLine(int(p_a[0]), int(p_a[1]), int(p_b[0]), int(p_b[1]))

        # 3. Active dynamic IAB spatial objects depth-sorted back-to-front (labels appear ONLY on hover)
        rendered_objs = []
        for obj in self.current_objects:
            p = self._project(obj.x, obj.y, obj.z)
            rendered_objs.append((p[2], obj, p))

        rendered_objs.sort(key=lambda item: item[0])

        for scale, obj, p in rendered_objs:
            is_bright = getattr(obj, "gain_db", 0.0) >= -2.5
            has_yellow = getattr(obj, "spread", 0.0) >= 0.25 or getattr(obj, "gain_db", 0.0) >= -1.0
            obj_lbl = (
                f"Object #{obj.object_id} ({obj.x:+.2f}, {obj.y:+.2f}, {obj.z:+.2f}) "
                f"| {getattr(obj, 'gain_db', 0.0):.1f} dB"
            )
            self._draw_green_pad(
                painter,
                obj.x,
                obj.y,
                obj.z,
                radius_factor=0.72,
                bright=is_bright,
                yellow_core=has_yellow,
                entity_id=f"obj_{obj.object_id}",
                label=obj_lbl,
            )

    def _rebuild_entities_for_hit_test(self):
        """Recompute projected entity positions without painting when hit-testing before first paint."""
        self._rendered_entities = []
        self._draw_listener_seat(None)
        self._draw_speakers(None)
        self._draw_spatial_objects(None)

    def _update_hovered_entity(self, pos: Optional[QPoint]):
        """Hit-test all rendered 3D circular entities under cursor and start smooth hover animation."""
        if pos is None:
            best_id = None
        else:
            if not self._rendered_entities:
                self._rebuild_entities_for_hit_test()

            mx, my = float(pos.x()), float(pos.y())
            best_id = None
            best_dist_sq = float("inf")
            for ent in self._rendered_entities:
                px = float(ent["px"])
                py = float(ent["py"])
                r = float(ent["r"])
                hit_r = max(10.0, r + 4.0)
                dx = mx - px
                dy = my - py
                d2 = dx * dx + dy * dy
                if d2 <= (hit_r * hit_r) and d2 <= best_dist_sq:
                    best_dist_sq = d2
                    best_id = str(ent["id"])

        if best_id != self.hovered_entity_id:
            self.hovered_entity_id = best_id

        if (self.hovered_entity_id is not None or self._hover_progress) and not self._hover_anim_timer.isActive():
            self._hover_anim_timer.start()

    def set_hovered_entity(self, entity_id: Optional[str]):
        """Programmatically hover/unhover an entity by ID and trigger smooth transition."""
        self.hovered_entity_id = entity_id
        if (self.hovered_entity_id is not None or self._hover_progress) and not self._hover_anim_timer.isActive():
            self._hover_anim_timer.start()

    def _on_hover_anim_tick(self):
        """Advance smooth inward (0->1) and outward (1->0) hover label transitions."""
        in_step = 0.14
        out_step = 0.12

        if self.hovered_entity_id:
            cur = self._hover_progress.get(self.hovered_entity_id, 0.0)
            self._hover_progress[self.hovered_entity_id] = min(1.0, cur + in_step)

        for eid in list(self._hover_progress.keys()):
            if eid != self.hovered_entity_id:
                new_v = self._hover_progress[eid] - out_step
                if new_v <= 0.001:
                    del self._hover_progress[eid]
                else:
                    self._hover_progress[eid] = new_v

        self.update()

        is_idle = (
            (self.hovered_entity_id is None and not self._hover_progress)
            or (
                self.hovered_entity_id is not None
                and len(self._hover_progress) == 1
                and self._hover_progress.get(self.hovered_entity_id, 0.0) >= 1.0
            )
        )
        if is_idle and self._hover_anim_timer.isActive():
            self._hover_anim_timer.stop()

    def _draw_hover_labels(self, painter: QPainter):
        """Render entity labels ONLY when hovered, with smooth inward/outward fade and slide."""
        if not self._hover_progress:
            return

        vp = self._inner_viewport_rect()
        font = QFont("Arial", 8, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()

        for eid, prog in list(self._hover_progress.items()):
            if prog <= 0.001:
                continue
            ent = self._hover_entity_cache.get(eid)
            if not ent:
                continue

            px = float(ent["px"])
            py = float(ent["py"])
            r = float(ent["r"])
            label = str(ent["label"])

            # Smooth cubic ease for inward/outward motion
            ease = prog * prog * (3.0 - 2.0 * prog)

            # Circular highlight halo expanding gently around hovered circle
            ring_r = r + 3.5 * ease
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(232, 222, 30, int(210 * ease)), 1.6))
            painter.drawEllipse(QRectF(px - ring_r, py - ring_r, ring_r * 2.0, ring_r * 2.0))

            # Scaled & smoothly sliding label pill
            scale = 0.72 + 0.28 * ease
            text_w = fm.horizontalAdvance(label)
            text_h = fm.height()
            pad_x = 8.0
            pad_y = 4.0
            box_w = (text_w + pad_x * 2.0) * scale
            box_h = (text_h + pad_y * 2.0) * scale

            cy_label = py - (r + 12.0 + box_h * 0.5) * ease
            bx = max(vp.left() + 4.0, min(vp.right() - box_w - 4.0, px - box_w * 0.5))
            by = max(vp.top() + 4.0, min(vp.bottom() - box_h - 4.0, cy_label - box_h * 0.5))
            pill = QRectF(bx, by, box_w, box_h)

            painter.setPen(QPen(QColor(31, 214, 24, int(225 * ease)), 1.2))
            painter.setBrush(QColor(11, 14, 20, int(230 * ease)))
            painter.drawRoundedRect(pill, 6.0 * scale, 6.0 * scale)

            painter.setPen(QColor(241, 245, 249, int(250 * ease)))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_hud(self, painter: QPainter):
        """Subtle telemetry placed in the outer black frame so the grey monitor viewport remains clean."""
        painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))
        painter.setPen(QColor(148, 163, 184, 185))
        bar_h = max(16, int(self.height() * 0.045))
        zoom_str = f"{self.zoom:.1f}x" if self.zoom < 1000.0 else f"{self.zoom:.0f}x"
        text = f"Orbit: {int(self.yaw)}° | Tilt: {int(self.pitch)}° | Zoom: {zoom_str}"
        painter.drawText(int(self.width() * 0.065), 1, 260, bar_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        total_pool = getattr(self, "max_audio_objects", 118)
        max_tracks = getattr(self, "max_rendered_channels", 128)
        bed_count = max(0, max_tracks - total_pool)

        obj_count = len(self.current_objects)
        cnt_text = (
            f"● {obj_count} Active / {total_pool} Atmos Objects ({bed_count} Bed)"
            if obj_count > 0 else f"○ {bed_count}-Ch Bed + {total_pool} Object Pool"
        )
        col = QColor(31, 214, 24) if obj_count > 0 else QColor(148, 163, 184, 185)
        painter.setPen(col)
        painter.drawText(
            int(self.width() * 0.065),
            1,
            int(self.width() * 0.87),
            bar_h,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            cnt_text,
        )


class IABVisualizerDialog(QDialog):
    """Floating 3D IAB / Dolby Atmos Object Trajectory HUD Window."""

    mode_changed = pyqtSignal(str)

    def __init__(self, iab_meta: Optional[IABTrackMetadata] = None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.iab_meta = iab_meta
        self.setWindowTitle("🎧 3D IAB / Dolby Atmos Spatial Audio Visualizer")
        self.resize(880, 520)
        self.setMinimumSize(680, 420)

        # Allow keeping window always on top for concurrent playback monitoring
        self.is_pinned = False
        self._latest_time_pos: float = 0.0
        self._last_table_update_time: float = -1.0
        self._init_ui()

        # Decoupled GUI refresh timer (30 FPS render loop on Main Qt Thread)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(33)  # ~30 FPS
        self.refresh_timer.timeout.connect(self._on_refresh_tick)

        if self.iab_meta:
            self.set_metadata(self.iab_meta)

    def _init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0b0e14;
                color: #f1f5f9;
            }
            QPushButton {
                background-color: #171b26;
                color: #cbd5e1;
                border: 1px solid #232938;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: 500;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #202636;
                border-color: #00d2ff;
                color: #ffffff;
            }
            QComboBox {
                background-color: #131722;
                color: #f1f5f9;
                border: 1px solid #232938;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QTableWidget {
                background-color: #0f131c;
                gridline-color: #1c2230;
                border: 1px solid #1c2230;
                border-radius: 6px;
                font-family: monospace;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #171c28;
                color: #00d2ff;
                border: none;
                padding: 4px;
                font-weight: bold;
                font-size: 10px;
            }
            QCheckBox {
                color: #94a3b8;
                font-size: 11px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 3D Canvas
        self.canvas = Auditorium3DCanvas()

        # Top Bar: Presets & Controls
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        lbl_title = QLabel("ST 2098-2 IAB Hologram")
        lbl_title.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 13px;")
        top_bar.addWidget(lbl_title)

        top_bar.addSpacing(12)

        # Camera presets
        btn_dolby = QPushButton("🎛️ Dolby RMU")
        btn_dolby.clicked.connect(lambda: self.canvas.set_view_preset("dolby"))
        top_bar.addWidget(btn_dolby)

        btn_3d = QPushButton("🌐 3D Perspective")
        btn_3d.clicked.connect(lambda: self.canvas.set_view_preset("3d"))
        top_bar.addWidget(btn_3d)

        btn_top = QPushButton("📐 Top-Down 2D")
        btn_top.clicked.connect(lambda: self.canvas.set_view_preset("top"))
        top_bar.addWidget(btn_top)

        btn_front = QPushButton("🎬 Screen View")
        btn_front.clicked.connect(lambda: self.canvas.set_view_preset("front"))
        top_bar.addWidget(btn_front)

        btn_side = QPushButton("↔️ Side Profile")
        btn_side.clicked.connect(lambda: self.canvas.set_view_preset("side"))
        top_bar.addWidget(btn_side)

        btn_reset = QPushButton("↺ Reset")
        btn_reset.clicked.connect(self.canvas.reset_view)
        top_bar.addWidget(btn_reset)

        top_bar.addStretch(1)

        # Trajectory Trails checkbox
        self.chk_trails = QCheckBox("Motion Trails")
        self.chk_trails.setChecked(True)
        self.chk_trails.toggled.connect(self._toggle_trails)
        top_bar.addWidget(self.chk_trails)

        # Pin Always on Top
        self.btn_pin = QPushButton("📌 Pin on Top")
        self.btn_pin.setCheckable(True)
        self.btn_pin.clicked.connect(self._toggle_pin)
        top_bar.addWidget(self.btn_pin)

        main_layout.addLayout(top_bar)

        # Splitter: 3D Canvas (Left) + Telemetry Table (Right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #1c2230; width: 2px; }")

        # 3D Canvas
        splitter.addWidget(self.canvas)

        # Right Telemetry Side Panel
        side_panel = QFrame()
        side_panel.setMinimumWidth(300)
        side_panel.setMaximumWidth(380)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(8, 0, 0, 0)
        side_layout.setSpacing(8)

        self.lbl_panel_title = QLabel("Active Audio Objects Telemetry")
        self.lbl_panel_title.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 11px;")
        side_layout.addWidget(self.lbl_panel_title)

        # Object Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "X (L/R)", "Y (F/B)", "Z (Hgt)", "Pan Zone"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        side_layout.addWidget(self.table, 1)

        # Downmix mode switcher
        mode_box = QHBoxLayout()
        lbl_mode = QLabel("Audio Route:")
        lbl_mode.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("🎧 Binaural 3D Headphone", "binaural")
        self.combo_mode.addItem("🔊 Cinema 7.1 Downmix", "cinema_71")
        self.combo_mode.addItem("📻 Cinema 5.1 Surround", "cinema_51")
        self.combo_mode.addItem("🗣️ Dialog Focus (+85% Center)", "stereo_dialog")
        self.combo_mode.addItem("🎚️ PCM Direct Bed", "pcm_direct")
        self.combo_mode.currentIndexChanged.connect(self._on_mode_combo_changed)
        mode_box.addWidget(lbl_mode)
        mode_box.addWidget(self.combo_mode, 1)
        side_layout.addLayout(mode_box)

        splitter.addWidget(side_panel)
        splitter.setSizes([560, 320])

        main_layout.addWidget(splitter, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_timer.start()

    def hideEvent(self, event):
        self.refresh_timer.stop()
        super().hideEvent(event)

    def set_metadata(self, meta: Optional[IABTrackMetadata]):
        self.iab_meta = meta
        pool = meta.max_audio_objects if meta else 118
        tracks = meta.max_rendered_channels if meta else 128
        bed = meta.bed_channel_count if meta else 10
        self.canvas.max_audio_objects = pool
        self.canvas.max_rendered_channels = tracks
        if hasattr(self, "lbl_panel_title"):
            self.lbl_panel_title.setText(f"Active Objects Telemetry (Pool: {pool} Objects | {tracks} Tracks)")
        if not meta:
            self.canvas.set_objects([])
            self.table.setRowCount(0)

    def update_time_pos(self, time_pos: float):
        """Thread-safe time position setter."""
        self._latest_time_pos = time_pos

    def _on_refresh_tick(self, force: bool = False):
        """Runs strictly on the Qt GUI Main Thread at 30 FPS."""
        if not self.iab_meta or not self.isVisible():
            return

        objects = IABEngine.get_spatial_objects_at_time(self.iab_meta, self._latest_time_pos)
        self.canvas.set_objects(objects)

        now = time.time()
        if force or (now - self._last_table_update_time >= 0.10):  # 10 Hz throttled text table
            self._last_table_update_time = now
            self._update_table_recycled(objects)

    def _update_table_recycled(self, objects: List[IABSpatialObject]):
        num_objs = len(objects)
        if self.table.rowCount() != num_objs:
            self.table.setRowCount(num_objs)

        for row, obj in enumerate(objects):
            # Col 0: ID
            it0 = self.table.item(row, 0)
            if it0 is None:
                it0 = QTableWidgetItem()
                self.table.setItem(row, 0, it0)
            it0.setText(f"#{obj.object_id}")
            col = OBJECT_COLORS[(obj.object_id - 1) % len(OBJECT_COLORS)]
            it0.setForeground(col)

            # Col 1: X
            it1 = self.table.item(row, 1)
            if it1 is None:
                it1 = QTableWidgetItem()
                self.table.setItem(row, 1, it1)
            it1.setText(f"{obj.x:+.2f}")

            # Col 2: Y
            it2 = self.table.item(row, 2)
            if it2 is None:
                it2 = QTableWidgetItem()
                self.table.setItem(row, 2, it2)
            it2.setText(f"{obj.y:+.2f}")

            # Col 3: Z
            it3 = self.table.item(row, 3)
            if it3 is None:
                it3 = QTableWidgetItem()
                self.table.setItem(row, 3, it3)
            it3.setText(f"{obj.z:+.2f}")

            # Col 4: Human-readable Pan Zone
            it4 = self.table.item(row, 4)
            if it4 is None:
                it4 = QTableWidgetItem()
                self.table.setItem(row, 4, it4)
            it4.setText(self._compute_zone_desc(obj.x, obj.y, obj.z))
            it4.setForeground(QColor(203, 213, 225))

    @staticmethod
    def _compute_zone_desc(x: float, y: float, z: float) -> str:
        h_str = "Overhead" if z > 0.4 else ("Elevated" if z > 0.0 else "Floor")
        lr_str = "Left" if x < -0.3 else ("Right" if x > 0.3 else "Center")
        fb_str = "Screen" if y > 0.4 else ("Surround" if y < -0.3 else "Mid")
        return f"{h_str} {lr_str} {fb_str}".strip()

    def _toggle_trails(self, checked: bool):
        self.canvas.show_trails = checked
        self.canvas.update()

    def _toggle_pin(self, checked: bool):
        self.is_pinned = checked
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
            self.btn_pin.setText("📌 Pinned")
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self.btn_pin.setText("📌 Pin on Top")
        self.setWindowFlags(flags)
        self.show()

    def _on_mode_combo_changed(self):
        mode = self.combo_mode.currentData()
        self.mode_changed.emit(mode)
