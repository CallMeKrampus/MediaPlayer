"""
Unit tests for MPC-HC Style 'Go To...' Dialog (Ctrl+G) and 'PnS Frame Adjust' System.
Verifies timecode/frame parsing, geometric pan & scan operations on mpv and NVJPEG2KCanvas,
menu actions, and shortcut routing.
"""

import unittest
from unittest.mock import MagicMock
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from ui.goto_dialog import GoToDialog
from core.pns_controller import PnSController
from ui.video_widget import NVJPEG2KCanvas

# Ensure QApplication exists for GUI tests
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestGoToNavigation(unittest.TestCase):
    def test_parse_time_string_separated(self):
        # [hh:]mm:ss.ms
        self.assertAlmostEqual(GoToDialog.parse_time_string("01:15:47.376"), 4547.376, places=3)
        self.assertAlmostEqual(GoToDialog.parse_time_string("15:47.376"), 947.376, places=3)
        self.assertAlmostEqual(GoToDialog.parse_time_string("47.5"), 47.5, places=3)
        self.assertAlmostEqual(GoToDialog.parse_time_string("00:00:10"), 10.0, places=3)
        self.assertAlmostEqual(GoToDialog.parse_time_string("1:2:3"), 3723.0, places=3)

    def test_parse_time_string_unseparated(self):
        # MPC-HC feature: users do not need to enter separators explicitly
        # 011547376 -> 01h 15m 47s 376ms -> 4547.376s
        self.assertAlmostEqual(GoToDialog.parse_time_string("011547376"), 4547.376, places=3)
        # 1547 -> 15m 47s -> 947.0s
        self.assertAlmostEqual(GoToDialog.parse_time_string("1547"), 947.0, places=3)
        # 47 -> 47s
        self.assertAlmostEqual(GoToDialog.parse_time_string("47"), 47.0, places=3)

    def test_parse_time_invalid(self):
        self.assertIsNone(GoToDialog.parse_time_string(""))
        self.assertIsNone(GoToDialog.parse_time_string("invalid_time"))

    def test_parse_frame_string(self):
        # Format: frame, fps
        res = GoToDialog.parse_frame_string("109029, 23.976", default_fps=24.0)
        self.assertIsNotNone(res)
        f_num, fps = res
        self.assertEqual(f_num, 109029)
        self.assertAlmostEqual(fps, 23.976, places=3)
        self.assertAlmostEqual(f_num / fps, 109029 / 23.976, places=3)

        # Space separated
        res2 = GoToDialog.parse_frame_string("2400 24.0")
        self.assertIsNotNone(res2)
        f_num2, fps2 = res2
        self.assertEqual(f_num2, 2400)
        self.assertAlmostEqual(fps2, 24.0)

        # Single number uses default_fps
        res3 = GoToDialog.parse_frame_string("480", default_fps=24.0)
        self.assertIsNotNone(res3)
        f_num3, fps3 = res3
        self.assertEqual(f_num3, 480)
        self.assertAlmostEqual(fps3, 24.0)

    def test_dialog_seek_emission(self):
        dlg = GoToDialog(current_pts=10.0, fps=24.0)
        sought = []
        dlg.seek_requested.connect(lambda s: sought.append(s))

        dlg.edit_time.setText("00:01:30.000")
        dlg._on_time_go()
        self.assertEqual(len(sought), 1)
        self.assertAlmostEqual(sought[0], 90.0, places=3)

        dlg.edit_frame.setText("240, 24.0")
        dlg._on_frame_go()
        self.assertEqual(len(sought), 2)
        self.assertAlmostEqual(sought[1], 10.0, places=3)


class TestPnSController(unittest.TestCase):
    def setUp(self):
        self.mock_player = MagicMock()
        self.mock_canvas = MagicMock()
        self.pns = PnSController(mpv_player=self.mock_player, nv_canvas=self.mock_canvas)

    def test_size_adjustments(self):
        self.pns.reset()
        self.assertAlmostEqual(self.pns.zoom, 1.0)

        # Increase Size (Num 9)
        self.pns.increase_size()
        self.assertAlmostEqual(self.pns.zoom, 1.05)

        # Decrease Size (Num 1)
        self.pns.decrease_size()
        self.assertAlmostEqual(self.pns.zoom, 1.0)

    def test_aspect_adjustments(self):
        self.pns.reset()
        self.pns.increase_width()
        self.assertAlmostEqual(self.pns.scale_x, 1.02)

        self.pns.decrease_width()
        self.assertAlmostEqual(self.pns.scale_x, 1.0)

        self.pns.increase_height()
        self.assertAlmostEqual(self.pns.scale_y, 1.02)

        self.pns.decrease_height()
        self.assertAlmostEqual(self.pns.scale_y, 1.0)

    def test_pan_adjustments(self):
        self.pns.reset()
        self.pns.move_right()
        self.assertAlmostEqual(self.pns.pan_x, 0.01)

        self.pns.move_left()
        self.assertAlmostEqual(self.pns.pan_x, 0.0)

        self.pns.move_up()
        self.assertAlmostEqual(self.pns.pan_y, -0.01)

        self.pns.move_down()
        self.assertAlmostEqual(self.pns.pan_y, 0.0)

        self.pns.move_right()
        self.pns.move_up()
        self.pns.center()
        self.assertAlmostEqual(self.pns.pan_x, 0.0)
        self.assertAlmostEqual(self.pns.pan_y, 0.0)

    def test_rotation_and_flip(self):
        self.pns.reset()
        self.pns.rotate_clockwise()
        self.assertEqual(self.pns.rotation, 90)

        self.pns.rotate_clockwise()
        self.assertEqual(self.pns.rotation, 180)

        self.pns.rotate_counter_clockwise()
        self.assertEqual(self.pns.rotation, 90)

        self.pns.flip_vertical()
        self.assertTrue(self.pns.flip_v)

        self.pns.mirror()
        self.assertTrue(self.pns.flip_h)

    def test_presets_and_reset(self):
        self.pns.scale_to_16_9()
        self.assertAlmostEqual(self.pns.scale_x, 1.0)
        self.assertAlmostEqual(self.pns.scale_y, 4.0 / 3.0, places=3)

        self.pns.zoom_to_widescreen()
        self.assertAlmostEqual(self.pns.zoom, 1.33)

        self.pns.zoom_to_ultra_widescreen()
        self.assertAlmostEqual(self.pns.zoom, 1.35)

        self.pns.convert_3d_sbs_to_2d()
        self.assertAlmostEqual(self.pns.scale_x, 2.0)

        self.pns.convert_3d_tb_to_2d()
        self.assertAlmostEqual(self.pns.scale_y, 2.0)

        self.pns.reset()
        self.assertAlmostEqual(self.pns.zoom, 1.0)
        self.assertAlmostEqual(self.pns.scale_x, 1.0)
        self.assertAlmostEqual(self.pns.scale_y, 1.0)
        self.assertAlmostEqual(self.pns.pan_x, 0.0)
        self.assertAlmostEqual(self.pns.pan_y, 0.0)
        self.assertEqual(self.pns.rotation, 0)
        self.assertFalse(self.pns.flip_h)
        self.assertFalse(self.pns.flip_v)

    def test_state_roundtrip(self):
        original = {
            "zoom": 1.25,
            "scale_x": 1.10,
            "scale_y": 0.95,
            "pan_x": 0.05,
            "pan_y": -0.05,
            "rotation": 90,
            "flip_h": True,
            "flip_v": False,
        }
        self.pns.set_state(original)
        state = self.pns.get_state()
        self.assertEqual(state, original)

    def test_nv_canvas_dispatch(self):
        self.pns.reset()
        self.mock_canvas.set_pns_transform.assert_called_with(
            zoom=1.0, scale_x=1.0, scale_y=1.0, pan_x=0.0, pan_y=0.0,
            rotation=0, flip_h=False, flip_v=False
        )


class TestNVJPEG2KCanvasPnS(unittest.TestCase):
    def test_canvas_pns_state(self):
        canvas = NVJPEG2KCanvas()
        canvas.set_pns_transform(
            zoom=1.5, scale_x=1.2, scale_y=0.8, pan_x=0.1, pan_y=-0.2,
            rotation=90, flip_h=True, flip_v=False
        )
        self.assertAlmostEqual(canvas.pns_zoom, 1.5)
        self.assertAlmostEqual(canvas.pns_scale_x, 1.2)
        self.assertAlmostEqual(canvas.pns_scale_y, 0.8)
        self.assertAlmostEqual(canvas.pns_pan_x, 0.1)
        self.assertAlmostEqual(canvas.pns_pan_y, -0.2)
        self.assertEqual(canvas.pns_rotate, 90)
        self.assertTrue(canvas.pns_flip_h)
        self.assertFalse(canvas.pns_flip_v)


class TestMainWindowIntegration(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.win = MainWindow()

    def tearDown(self):
        self.win.close()

    def test_pns_menu_and_actions(self):
        self.assertIsNotNone(self.win.menu_pns)
        self.assertEqual(self.win.menu_pns.title(), "PnS Frame Adjust")
        self.assertEqual(len(self.win._pns_actions), 26)

    def test_numpad_keypress_routing(self):
        self.win.pns_controller.reset()
        self.assertAlmostEqual(self.win.pns_controller.zoom, 1.0)

        # Simulate Numpad 9 (Increase Size)
        ev9 = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_9,
            Qt.KeyboardModifier.KeypadModifier,
            "9"
        )
        self.win.keyPressEvent(ev9)
        self.assertAlmostEqual(self.win.pns_controller.zoom, 1.05)

        # Simulate Numpad 1 (Decrease Size)
        ev1 = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_1,
            Qt.KeyboardModifier.KeypadModifier,
            "1"
        )
        self.win.keyPressEvent(ev1)
        self.assertAlmostEqual(self.win.pns_controller.zoom, 1.0)

        # Simulate Numpad 5 (Reset)
        ev5 = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_5,
            Qt.KeyboardModifier.KeypadModifier,
            "5"
        )
        self.win.keyPressEvent(ev5)
        self.assertAlmostEqual(self.win.pns_controller.zoom, 1.0)

    def test_get_fps_fallback(self):
        fps = self.win.get_fps()
        self.assertGreater(fps, 0.0)


if __name__ == "__main__":
    unittest.main()
