"""
Unit tests for Video, Audio, Subtitle Track Selection and DCP Quality Switcher.
"""

import unittest
from PyQt6.QtWidgets import QApplication
from ui.tracks_dialog import TrackSelectorDialog
from ui.main_window import MainWindow


class TestTrackSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindow()

    def tearDown(self):
        self.win.close()

    def test_track_selector_dialog_init(self):
        dlg = TrackSelectorDialog(self.win.engine, self.win)
        self.assertEqual(dlg.tabs.count(), 3)
        self.assertIn("Video", dlg.tabs.tabText(0))
        self.assertIn("Audio", dlg.tabs.tabText(1))
        self.assertIn("Subtitle", dlg.tabs.tabText(2))
        dlg.close()

    def test_dynamic_track_menus_exist(self):
        self.assertTrue(hasattr(self.win, "menu_video_tracks"))
        self.assertTrue(hasattr(self.win, "menu_audio_tracks"))
        self.assertTrue(hasattr(self.win, "menu_sub_tracks"))

        # Trigger dynamic population
        self.win._populate_video_tracks_menu()
        self.win._populate_audio_tracks_menu()
        self.win._populate_sub_tracks_menu()

        self.assertGreater(len(self.win.menu_video_tracks.actions()), 0)
        self.assertGreater(len(self.win.menu_audio_tracks.actions()), 0)
        self.assertGreater(len(self.win.menu_sub_tracks.actions()), 0)

    def test_set_track_and_cycle(self):
        # Test setting and cycling without crash
        self.win.engine.set_track("video", "no")
        self.win.engine.set_track("audio", "no")
        self.win.engine.set_track("sub", "no")

        self.win.engine.cycle_track("video")
        self.win.engine.cycle_track("audio")
        self.win.engine.cycle_track("sub")

    def test_dcp_quality_switch_level0(self):
        # Test switching to Native 4K Master level 0 without crash
        self.win._on_dcp_quality_selected(0)
        self.assertEqual(self.win.engine.dcp_decode_level, 0)
        self.assertEqual(self.win.engine.player["vd-lavc-o"], {"lowres": "0"})
        self.assertIn(self.win.engine.player["framedrop"], ("no", False))

        # Switch back to Level 2 (Proxy)
        self.win._on_dcp_quality_selected(2)
        self.assertEqual(self.win.engine.dcp_decode_level, 2)
        self.assertEqual(self.win.engine.player["vd-lavc-o"], {"lowres": "2"})
        self.assertIn(self.win.engine.player["framedrop"], ("vo", True))


if __name__ == "__main__":
    unittest.main()
