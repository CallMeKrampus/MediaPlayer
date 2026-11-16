"""
BOOB Player - PnS (Pan & Scan) Frame Geometry & Adjust Engine
Coordinates real-time zoom, pan, stretch, rotation, and flipping across
both mpv video playback and NVIDIA nvJPEG2000 DCP cinema canvas.
"""

import math
from typing import Optional, Callable, Dict, Any


class PnSController:
    """Manages Pan & Scan state and applies transforms to mpv and NVJPEG2KCanvas."""

    def __init__(self, mpv_player=None, nv_canvas=None):
        self.player = mpv_player
        self.canvas = nv_canvas

        # Core Pan & Scan State
        self.zoom: float = 1.0           # Overall scale multiplier (1.0 = 100%)
        self.scale_x: float = 1.0        # Horizontal aspect stretch (1.0 = 100%)
        self.scale_y: float = 1.0        # Vertical aspect stretch (1.0 = 100%)
        self.pan_x: float = 0.0          # Horizontal offset (-1.0 to +1.0)
        self.pan_y: float = 0.0          # Vertical offset (-1.0 to +1.0)
        self.rotation: int = 0           # Degrees: 0, 90, 180, 270
        self.flip_h: bool = False        # Horizontal mirror
        self.flip_v: bool = False        # Vertical flip

        # Change listener callback: Callable[[str], None] where str is a toast description
        self.on_change: Optional[Callable[[str], None]] = None

    def set_player(self, mpv_player):
        self.player = mpv_player
        self._apply_all()

    def set_canvas(self, nv_canvas):
        self.canvas = nv_canvas
        self._apply_all()

    # --- Sizing & Scaling (Numpad 9, 1, 6, 4, 8, 2) ---

    def increase_size(self):
        """Increase Size (Zoom In, Numpad 9)."""
        self.zoom = min(5.0, round(self.zoom * 1.05, 4))
        self._notify_and_apply(f"PnS: Zoom {int(round(self.zoom * 100))}%")

    def decrease_size(self):
        """Decrease Size (Zoom Out, Numpad 1)."""
        self.zoom = max(0.2, round(self.zoom / 1.05, 4))
        self._notify_and_apply(f"PnS: Zoom {int(round(self.zoom * 100))}%")

    def increase_width(self):
        """Increase Width (Widen, Numpad 6)."""
        self.scale_x = min(5.0, round(self.scale_x * 1.02, 4))
        self._notify_and_apply(f"PnS: Width {int(round(self.scale_x * 100))}%")

    def decrease_width(self):
        """Decrease Width (Narrow, Numpad 4)."""
        self.scale_x = max(0.2, round(self.scale_x / 1.02, 4))
        self._notify_and_apply(f"PnS: Width {int(round(self.scale_x * 100))}%")

    def increase_height(self):
        """Increase Height (Taller, Numpad 8)."""
        self.scale_y = min(5.0, round(self.scale_y * 1.02, 4))
        self._notify_and_apply(f"PnS: Height {int(round(self.scale_y * 100))}%")

    def decrease_height(self):
        """Decrease Height (Shorter, Numpad 2)."""
        self.scale_y = max(0.2, round(self.scale_y / 1.02, 4))
        self._notify_and_apply(f"PnS: Height {int(round(self.scale_y * 100))}%")

    # --- Pan & Positioning (Ctrl+Numpad 4, 6, 8, 2, 5) ---

    def move_right(self):
        """Move Content Right (Ctrl+Numpad 6)."""
        self.pan_x = min(1.0, round(self.pan_x + 0.01, 3))
        self._notify_and_apply(f"PnS: Pan X {int(round(self.pan_x * 100))}%")

    def move_left(self):
        """Move Content Left (Ctrl+Numpad 4)."""
        self.pan_x = max(-1.0, round(self.pan_x - 0.01, 3))
        self._notify_and_apply(f"PnS: Pan X {int(round(self.pan_x * 100))}%")

    def move_up(self):
        """Move Content Up (Ctrl+Numpad 8)."""
        self.pan_y = max(-1.0, round(self.pan_y - 0.01, 3))
        self._notify_and_apply(f"PnS: Pan Y {int(round(-self.pan_y * 100))}%")

    def move_down(self):
        """Move Content Down (Ctrl+Numpad 2)."""
        self.pan_y = min(1.0, round(self.pan_y + 0.01, 3))
        self._notify_and_apply(f"PnS: Pan Y {int(round(-self.pan_y * 100))}%")

    def center(self):
        """Center Position (Ctrl+Numpad 5)."""
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._notify_and_apply("PnS: Centered")

    # --- Rotation & Flipping (Alt+Numpad 3, 1, 2, 6) ---

    def rotate_clockwise(self):
        """Rotate 90° Clockwise (Alt+Numpad 3)."""
        self.rotation = (self.rotation + 90) % 360
        self._notify_and_apply(f"PnS: Rotate {self.rotation}°")

    def rotate_counter_clockwise(self):
        """Rotate 90° Counter-Clockwise (Alt+Numpad 1)."""
        self.rotation = (self.rotation - 90) % 360
        self._notify_and_apply(f"PnS: Rotate {self.rotation}°")

    def flip_vertical(self):
        """Flip Vertically (Alt+Numpad 2)."""
        self.flip_v = not self.flip_v
        status = "Active" if self.flip_v else "Off"
        self._notify_and_apply(f"PnS: Vertical Flip {status}")

    def mirror(self):
        """Mirror / Flip Horizontally (Alt+Numpad 6)."""
        self.flip_h = not self.flip_h
        status = "Active" if self.flip_h else "Off"
        self._notify_and_apply(f"PnS: Mirror {status}")

    # --- Presets (16:9 TV, Widescreen, Ultra-Widescreen, 3D SBS/TB) ---

    def scale_to_16_9(self):
        """Scale / Stretch to 16:9 TV aspect."""
        self.scale_x = 1.0
        self.scale_y = 1.3333
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._notify_and_apply("PnS: Scale to 16:9 TV")

    def zoom_to_widescreen(self):
        """Zoom to 2.35:1 Widescreen (fills ultra-wide screen)."""
        self.zoom = 1.33
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._notify_and_apply("PnS: Zoom to Widescreen (2.35:1)")

    def zoom_to_ultra_widescreen(self):
        """Zoom to 2.39:1 Ultra-Widescreen."""
        self.zoom = 1.35
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._notify_and_apply("PnS: Zoom to Ultra-Widescreen (2.39:1)")

    def convert_3d_sbs_to_2d(self):
        """3D Side-By-Side -> 2D (crops left eye and stretches to 100%)."""
        self.zoom = 1.0
        self.scale_x = 2.0
        self.scale_y = 1.0
        self.pan_x = -0.5
        self.pan_y = 0.0
        self._notify_and_apply("PnS: 3D SBS > 2D")

    def convert_3d_tb_to_2d(self):
        """3D Top-Bottom -> 2D (crops top eye and stretches to 100%)."""
        self.zoom = 1.0
        self.scale_x = 1.0
        self.scale_y = 2.0
        self.pan_x = 0.0
        self.pan_y = -0.5
        self._notify_and_apply("PnS: 3D TB > 2D")

    def reset(self):
        """Reset all PnS adjustments to default (Numpad 5)."""
        self.zoom = 1.0
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.rotation = 0
        self.flip_h = False
        self.flip_v = False
        self._notify_and_apply("PnS: Reset")

    def get_state(self) -> Dict[str, Any]:
        """Return a snapshot of current Pan & Scan state."""
        return {
            "zoom": self.zoom,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "pan_x": self.pan_x,
            "pan_y": self.pan_y,
            "rotation": self.rotation,
            "flip_h": self.flip_h,
            "flip_v": self.flip_v,
        }

    def set_state(self, state: Dict[str, Any]):
        """Manually restore Pan & Scan state (e.g. from Edit dialog)."""
        self.zoom = float(state.get("zoom", self.zoom))
        self.scale_x = float(state.get("scale_x", self.scale_x))
        self.scale_y = float(state.get("scale_y", self.scale_y))
        self.pan_x = float(state.get("pan_x", self.pan_x))
        self.pan_y = float(state.get("pan_y", self.pan_y))
        self.rotation = int(state.get("rotation", self.rotation)) % 360
        self.flip_h = bool(state.get("flip_h", self.flip_h))
        self.flip_v = bool(state.get("flip_v", self.flip_v))
        self._notify_and_apply("PnS: Custom Edit Applied")

    # --- Internal hardware dispatch ---

    def _notify_and_apply(self, desc: str):
        self._apply_all()
        if self.on_change:
            try:
                self.on_change(desc)
            except Exception:
                pass

    def _apply_all(self):
        # 1. Dispatch to mpv player
        if self.player:
            try:
                # mpv video-zoom is log2(zoom) where 0 is 1.0x
                mpv_zoom = math.log2(max(0.01, self.zoom))
                self.player["video-zoom"] = mpv_zoom
                self.player["video-scale-x"] = self.scale_x
                self.player["video-scale-y"] = self.scale_y
                self.player["video-pan-x"] = self.pan_x
                # In mpv video-pan-y, positive moves content down
                self.player["video-pan-y"] = self.pan_y
                self.player["video-rotate"] = self.rotation

                # Flipping via video-filter
                vf_filters = []
                if self.flip_h:
                    vf_filters.append("hflip")
                if self.flip_v:
                    vf_filters.append("vflip")

                vf_str = ",".join(vf_filters)
                curr_vf = str(self.player.get("vf", "") or "")
                # Preserve existing format filters (like format=rgb48le)
                base_vf = ",".join([f for f in curr_vf.split(",") if "hflip" not in f and "vflip" not in f and f.strip()])
                combined_vf = ",".join(filter(None, [base_vf, vf_str]))
                self.player["vf"] = combined_vf
            except Exception:
                pass

        # 2. Dispatch to DCP OpenGL Canvas
        if self.canvas and hasattr(self.canvas, "set_pns_transform"):
            try:
                self.canvas.set_pns_transform(
                    zoom=self.zoom,
                    scale_x=self.scale_x,
                    scale_y=self.scale_y,
                    pan_x=self.pan_x,
                    pan_y=self.pan_y,
                    rotation=self.rotation,
                    flip_h=self.flip_h,
                    flip_v=self.flip_v
                )
            except Exception:
                pass
