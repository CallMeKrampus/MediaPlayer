"""
BOOB Player - Vector / SVG Icon Generator
Generates high-DPI, crisp dark-theme icons using QPainter and vector geometry.
"""

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QPolygonF
from PyQt6.QtCore import Qt, QPointF, QRectF


def draw_play_icon(size: int = 24, color: str = "#ffffff") -> QIcon:
    """Crisp high-contrast pure white play triangle."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    
    # Triangle pointing right
    poly = QPolygonF([
        QPointF(size * 0.28, size * 0.20),
        QPointF(size * 0.82, size * 0.50),
        QPointF(size * 0.28, size * 0.80),
    ])
    p.drawPolygon(poly)
    p.end()
    return QIcon(pix)


def draw_pause_icon(size: int = 24, color: str = "#ffffff") -> QIcon:
    """Crisp high-contrast pure white pause bars."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    
    w = size * 0.18
    gap = size * 0.16
    h = size * 0.60
    y = size * 0.20
    x1 = (size - (2 * w + gap)) / 2.0
    x2 = x1 + w + gap
    
    p.drawRoundedRect(QRectF(x1, y, w, h), 2, 2)
    p.drawRoundedRect(QRectF(x2, y, w, h), 2, 2)
    p.end()
    return QIcon(pix)


def draw_stop_icon(size: int = 24, color: str = "#ef4444") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    side = size * 0.50
    offset = (size - side) / 2.0
    p.drawRoundedRect(QRectF(offset, offset, side, side), 3, 3)
    p.end()
    return QIcon(pix)


def draw_skip_back_icon(size: int = 24, color: str = "#94a3b8") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    
    # Left pointing double triangle
    poly1 = QPolygonF([
        QPointF(size * 0.50, size * 0.25),
        QPointF(size * 0.15, size * 0.50),
        QPointF(size * 0.50, size * 0.75),
    ])
    poly2 = QPolygonF([
        QPointF(size * 0.85, size * 0.25),
        QPointF(size * 0.50, size * 0.50),
        QPointF(size * 0.85, size * 0.75),
    ])
    p.drawPolygon(poly1)
    p.drawPolygon(poly2)
    p.end()
    return QIcon(pix)


def draw_skip_forward_icon(size: int = 24, color: str = "#94a3b8") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    
    # Right pointing double triangle
    poly1 = QPolygonF([
        QPointF(size * 0.15, size * 0.25),
        QPointF(size * 0.50, size * 0.50),
        QPointF(size * 0.15, size * 0.75),
    ])
    poly2 = QPolygonF([
        QPointF(size * 0.50, size * 0.25),
        QPointF(size * 0.85, size * 0.50),
        QPointF(size * 0.50, size * 0.75),
    ])
    p.drawPolygon(poly1)
    p.drawPolygon(poly2)
    p.end()
    return QIcon(pix)


def draw_frame_step_icon(forward: bool = True, size: int = 24, color: str = "#94a3b8") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    
    if forward:
        poly = QPolygonF([
            QPointF(size * 0.25, size * 0.30),
            QPointF(size * 0.60, size * 0.50),
            QPointF(size * 0.25, size * 0.70),
        ])
        p.drawPolygon(poly)
        p.drawRoundedRect(QRectF(size * 0.68, size * 0.30, size * 0.12, size * 0.40), 1, 1)
    else:
        p.drawRoundedRect(QRectF(size * 0.20, size * 0.30, size * 0.12, size * 0.40), 1, 1)
        poly = QPolygonF([
            QPointF(size * 0.75, size * 0.30),
            QPointF(size * 0.40, size * 0.50),
            QPointF(size * 0.75, size * 0.70),
        ])
        p.drawPolygon(poly)
        
    p.end()
    return QIcon(pix)


def draw_volume_icon(mute: bool = False, size: int = 24, color: str = "#cbd5e1") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    
    # Speaker cone
    p.drawRoundedRect(QRectF(size * 0.15, size * 0.38, size * 0.18, size * 0.24), 2, 2)
    cone = QPolygonF([
        QPointF(size * 0.30, size * 0.38),
        QPointF(size * 0.55, size * 0.20),
        QPointF(size * 0.55, size * 0.80),
        QPointF(size * 0.30, size * 0.62),
    ])
    p.drawPolygon(cone)
    
    if mute:
        pen = QPen(QColor("#ef4444"), 2)
        p.setPen(pen)
        p.drawLine(int(size * 0.65), int(size * 0.35), int(size * 0.85), int(size * 0.65))
        p.drawLine(int(size * 0.85), int(size * 0.35), int(size * 0.65), int(size * 0.65))
    else:
        pen = QPen(QColor(color), 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(size * 0.45, size * 0.30, size * 0.35, size * 0.40), -45 * 16, 90 * 16)
        
    p.end()
    return QIcon(pix)


def draw_fullscreen_icon(is_fullscreen: bool = False, size: int = 24, color: str = "#cbd5e1") -> QIcon:
    """
    Clean, coherent cinema fullscreen corner bracket vector icon.
    In windowed mode: 4 outward corner brackets (Expand).
    In fullscreen mode: 4 inward corner brackets (Compress / Exit).
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    arm = size * 0.22
    if not is_fullscreen:
        # Expanding outward corner brackets
        pad = size * 0.20
        r = size - pad
        # Top-Left
        p.drawLine(QPointF(pad, pad + arm), QPointF(pad, pad))
        p.drawLine(QPointF(pad, pad), QPointF(pad + arm, pad))
        # Top-Right
        p.drawLine(QPointF(r - arm, pad), QPointF(r, pad))
        p.drawLine(QPointF(r, pad), QPointF(r, pad + arm))
        # Bottom-Left
        p.drawLine(QPointF(pad, r - arm), QPointF(pad, r))
        p.drawLine(QPointF(pad, r), QPointF(pad + arm, r))
        # Bottom-Right
        p.drawLine(QPointF(r - arm, r), QPointF(r, r))
        p.drawLine(QPointF(r, r), QPointF(r, r - arm))
    else:
        # Collapsing inward corner brackets (Exit)
        mid = size * 0.50
        gap = size * 0.12
        # Top-Left inward
        p.drawLine(QPointF(mid - gap - arm, mid - gap), QPointF(mid - gap, mid - gap))
        p.drawLine(QPointF(mid - gap, mid - gap), QPointF(mid - gap, mid - gap - arm))
        # Top-Right inward
        p.drawLine(QPointF(mid + gap + arm, mid - gap), QPointF(mid + gap, mid - gap))
        p.drawLine(QPointF(mid + gap, mid - gap), QPointF(mid + gap, mid - gap - arm))
        # Bottom-Left inward
        p.drawLine(QPointF(mid - gap - arm, mid + gap), QPointF(mid - gap, mid + gap))
        p.drawLine(QPointF(mid - gap, mid + gap), QPointF(mid - gap, mid + gap + arm))
        # Bottom-Right inward
        p.drawLine(QPointF(mid + gap + arm, mid + gap), QPointF(mid + gap, mid + gap))
        p.drawLine(QPointF(mid + gap, mid + gap), QPointF(mid + gap, mid + gap + arm))

    p.end()
    return QIcon(pix)


def draw_reset_icon(size: int = 16, color: str = "#94a3b8", hover_color: str = "#00d2ff") -> QIcon:
    """
    Crisp circular undo/reset vector icon (counter-clockwise circular arrow).
    Returns a QIcon with Normal and Active (hover) states.
    """
    def _render_pix(clr: str) -> QPixmap:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        pen = QPen(QColor(clr), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        
        center = size / 2.0
        radius = size * 0.32
        rect = QRectF(center - radius, center - radius, radius * 2.0, radius * 2.0)
        
        # 260 degree arc leaving an opening at the top-right for the arrow head
        p.drawArc(rect, int(50 * 16), int(260 * 16))
        
        # Vector arrow head pointing counter-clockwise
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(clr)))
        arrow = QPolygonF([
            QPointF(center + radius - 3.5, center - radius + 1.0),
            QPointF(center + radius + 1.2, center - radius - 3.2),
            QPointF(center + radius + 3.2, center - radius + 2.5),
        ])
        p.drawPolygon(arrow)
        p.end()
        return pix

    icon = QIcon()
    icon.addPixmap(_render_pix(color), QIcon.Mode.Normal)
    icon.addPixmap(_render_pix(hover_color), QIcon.Mode.Active)
    return icon
