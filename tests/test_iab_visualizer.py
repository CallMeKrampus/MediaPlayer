import unittest
import subprocess
import sys
import os
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QWheelEvent

from core.iab_engine import IABTrackMetadata, IABFrameInfo, IABSpatialObject, IABEngine
from core.app_paths import get_app_base_dir, get_lib_dir, get_shaders_dir, find_external_tool
from ui.iab_visualizer_dialog import Auditorium3DCanvas, IABVisualizerDialog, OBJECT_COLORS

# Ensure offscreen Qt application exists
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)


class TestIABVisualizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create synthetic IAB metadata
        cls.meta = IABTrackMetadata(
            file_path="mock_atmos.mxf",
            format_name="SMPTE ST 2098-2 Immersive Audio Bitstream (IAB)",
            total_frames=100,
            duration_seconds=4.16,
            frame_rate=24.0,
            has_spatial_objects=True,
        )
        # Frame 0: Bed only (no objects)
        cls.meta.frames.append(IABFrameInfo(0, 0, 1500, 1, 48000, 24.0, []))
        # Frame 60 (t=2.5s): 4 spatial objects
        objs = [
            IABSpatialObject(object_id=1, x=-0.8, y=0.5, z=0.7, gain_db=-1.2),  # Overhead Left Screen
            IABSpatialObject(object_id=2, x=0.7, y=-0.6, z=0.0, gain_db=-3.0),  # Elevated Right Surround
            IABSpatialObject(object_id=3, x=0.0, y=0.9, z=0.1, gain_db=0.0),    # Center Front Screen
            IABSpatialObject(object_id=4, x=0.0, y=-0.9, z=0.9, gain_db=-2.5),  # Overhead Center Back
        ]
        cls.meta.frames.append(IABFrameInfo(60, 60000, 4800, 1, 48000, 24.0, objs))

    def test_auditorium_canvas_projection(self):
        canvas = Auditorium3DCanvas()
        canvas.resize(600, 400)

        # Test perspective projection with standard yaw and pitch
        sx, sy, scale = canvas.project_3d(0.0, 0.0, 0.0)
        self.assertIsInstance(sx, float)
        self.assertIsInstance(sy, float)
        self.assertGreater(scale, 0.0)

        # Extreme boundaries
        for x in [-1.0, 1.0]:
            for y in [-1.0, 1.0]:
                for z in [-1.0, 1.0]:
                    px, py, sc = canvas.project_3d(x, y, z)
                    self.assertFalse(math_isnan(px))
                    self.assertFalse(math_isnan(py))

        # Test rendering of active spatial objects and trails
        canvas.set_objects([
            IABSpatialObject(1, -0.5, 0.2, 0.8),
            IABSpatialObject(2, 0.4, -0.3, 0.1),
        ])
        pixmap = canvas.grab()
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), 600)
        self.assertEqual(pixmap.height(), 400)

    def test_auditorium_view_presets(self):
        canvas = Auditorium3DCanvas()
        canvas.set_view_preset("top")
        self.assertEqual(canvas.pitch, 88.0)
        self.assertEqual(canvas.yaw, 0.0)

        canvas.set_view_preset("front")
        self.assertEqual(canvas.pitch, 2.0)
        self.assertEqual(canvas.yaw, 0.0)

        canvas.set_view_preset("side")
        self.assertEqual(canvas.pitch, 2.0)
        self.assertEqual(canvas.yaw, 90.0)

        canvas.set_view_preset("3d")
        self.assertEqual(canvas.pitch, 22.0)
        self.assertEqual(canvas.yaw, 24.0)

    def test_visualizer_dialog_time_updates(self):
        dlg = IABVisualizerDialog(self.meta)
        dlg.show()

        # At t=0.0s (bed only)
        dlg.update_time_pos(0.0)
        dlg._on_refresh_tick(force=True)
        self.assertEqual(dlg.table.rowCount(), 0)

        # At t=2.5s (active objects)
        dlg.update_time_pos(2.5)
        dlg._on_refresh_tick(force=True)
        self.assertEqual(dlg.table.rowCount(), 4)

        # Verify object 1 values in telemetry table
        item_id = dlg.table.item(0, 0)
        self.assertEqual(item_id.text(), "#1")
        item_x = dlg.table.item(0, 1)
        self.assertEqual(item_x.text(), "-0.80")
        item_zone = dlg.table.item(0, 4)
        self.assertIn("Overhead Left", item_zone.text())

        # Test mode change signal
        emitted_modes = []
        dlg.mode_changed.connect(lambda m: emitted_modes.append(m))
        dlg.combo_mode.setCurrentIndex(1)  # cinema_71
        self.assertIn("cinema_71", emitted_modes)

        dlg.close()

    def test_infinite_zoom_no_upper_clamp(self):
        canvas = Auditorium3DCanvas()
        canvas.resize(600, 400)

        # Repeatedly scroll wheel up well past the old 2.5x ceiling
        for _ in range(30):
            ev = QWheelEvent(
                QPointF(300.0, 200.0),
                QPointF(300.0, 200.0),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            canvas.wheelEvent(ev)

        self.assertGreater(canvas.zoom, 10.0)

        # Explicit high zoom levels grow scale monotonically without near-plane clamping
        prev_scale = 0.0
        for z in (1.0, 5.0, 50.0, 500.0, 5000.0):
            canvas.zoom = z
            _, _, scale = canvas.project_3d(0.0, 0.0, 0.0)
            self.assertGreater(scale, prev_scale)
            prev_scale = scale

    def test_hover_only_labels_and_smooth_inward_outward_transition(self):
        canvas = Auditorium3DCanvas()
        canvas.resize(640, 480)
        canvas.set_objects([
            IABSpatialObject(1, -0.35, 0.25, 0.45, gain_db=-1.0),
            IABSpatialObject(2, 0.45, -0.20, 0.15, gain_db=-3.0),
        ])

        # Force initial render pass so all entities are projected & registered
        pixmap = canvas.grab()
        self.assertFalse(pixmap.isNull())

        # All entity categories must be registered, and hover progress starts empty
        ids = {str(e["id"]) for e in canvas._rendered_entities}
        self.assertIn("origin_listener", ids)
        self.assertTrue(any(eid.startswith("spk_") for eid in ids))
        self.assertTrue(any(eid.startswith("bed_") for eid in ids))
        self.assertTrue(any(eid.startswith("zone_") for eid in ids))
        self.assertIn("obj_1", ids)
        self.assertEqual(canvas._hover_progress, {})

        # Hover onto object #1 and verify smooth inward animation (0 -> 1)
        obj_ent = next(e for e in canvas._rendered_entities if e["id"] == "obj_1")
        canvas._update_hovered_entity(QPoint(int(round(obj_ent["px"])), int(round(obj_ent["py"]))))
        self.assertEqual(canvas.hovered_entity_id, "obj_1")

        canvas._on_hover_anim_tick()
        p1 = canvas._hover_progress.get("obj_1", 0.0)
        self.assertGreater(p1, 0.0)
        self.assertLess(p1, 1.0)

        canvas._on_hover_anim_tick()
        p2 = canvas._hover_progress.get("obj_1", 0.0)
        self.assertGreater(p2, p1)

        for _ in range(15):
            canvas._on_hover_anim_tick()
        self.assertEqual(canvas._hover_progress.get("obj_1"), 1.0)
        # Render while fully hovered to verify label drawing works without error
        self.assertFalse(canvas.grab().isNull())

        # Move pointer away and verify smooth outward animation (1 -> 0)
        canvas._update_hovered_entity(None)
        self.assertIsNone(canvas.hovered_entity_id)

        canvas._on_hover_anim_tick()
        p_out = canvas._hover_progress.get("obj_1", 0.0)
        self.assertGreater(p_out, 0.0)
        self.assertLess(p_out, 1.0)

        for _ in range(15):
            canvas._on_hover_anim_tick()
        self.assertNotIn("obj_1", canvas._hover_progress)
        canvas._hover_anim_timer.stop()

    def test_frozen_path_resolution_and_cx_freeze_packaging_check(self):
        # Source execution resolves project root
        base_dir = get_app_base_dir()
        self.assertTrue(os.path.isdir(get_shaders_dir()))
        self.assertTrue(os.path.isdir(get_lib_dir()))
        self.assertTrue(os.path.isfile(os.path.join(base_dir, "boob_player.py")))
        self.assertTrue(find_external_tool("ffmpeg"))
        self.assertTrue(find_external_tool("ffprobe"))

        # Mock frozen executable environment
        fake_exe = r"C:\Temp\BOOBPlayerDist\BOOBPlayer.exe"
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", fake_exe):
            self.assertEqual(os.path.normpath(get_app_base_dir()), os.path.normpath(r"C:\Temp\BOOBPlayerDist"))

        # Run non-PyInstaller cx_Freeze pre-flight verification
        proc = subprocess.run(
            [sys.executable, os.path.join(base_dir, "build_exe.py"), "--check"],
            capture_output=True,
            text=True,
            cwd=base_dir,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)
        self.assertIn("cx_Freeze", proc.stdout)
        self.assertIn("PyInstaller excluded", proc.stdout)
        for expected in (
            r"lib\ffmpeg.exe",
            r"lib\ffprobe.exe",
            r"lib\libmpv-2.dll",
            r"lib\nvjpeg2k_0.dll",
            r"lib\cacert.pem",
            r"lib\opengl32sw.dll",
            "Verified zero DCPs/media files bundled",
        ):
            self.assertIn(expected, proc.stdout)


def math_isnan(val: float) -> bool:
    import math
    return math.isnan(val)


if __name__ == "__main__":
    unittest.main()
