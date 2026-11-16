"""
Unit tests verifying that when a new file is opened, all contents, tracks,
external files, filters, delays, and state loaded for the previous file are completely discarded.
"""

import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QAction
from core.mpv_engine import MPVEngine
from core.iab_engine import IABTrackMetadata
from ui.main_window import MainWindow


class DummyMpvPlayer:
    def __init__(self):
        self.options = {
            "audio-files": [],
            "sub-files": [],
            "af": "",
            "vf": "",
            "vid": "auto",
            "aid": "auto",
            "sid": "auto",
            "audio-delay": 0.0,
            "sub-delay": 0.0,
            "video-aspect-override": "-1",
        }
        self.commands = []
        self.pause = False
        self.container_fps_override = None

    def __setitem__(self, key, val):
        self.options[key] = val

    def __getitem__(self, key):
        return self.options.get(key)

    def command(self, *args):
        self.commands.append(args)


class TestFileStateDiscard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_engine_reset_playback_state(self):
        engine = MPVEngine.__new__(MPVEngine)
        engine.player = DummyMpvPlayer()
        engine.nv_controller = None
        engine.nvjpeg2k_active = True
        engine.is_dcp_playing = True
        engine.current_dcp = "dummy_dcp"
        engine.active_cpl = "dummy_cpl"
        engine.current_reel_index = 3
        engine.current_iab_meta = IABTrackMetadata(file_path="dummy.mxf")
        engine.current_iab_mode = "binaural"
        engine.on_track_list_change = None
        engine.on_iab_status = None

        # Simulate previous file loading dirty state
        engine.player["audio-files"] = ["/path/commentary.wav"]
        engine.player["sub-files"] = ["/path/subs.srt"]
        engine.player["af"] = "lavfi=[loudnorm]"
        engine.player["vf"] = "format=rgb48le"
        engine.player["aid"] = 2
        engine.player["sid"] = 3
        engine.player["vid"] = 1
        engine.player["audio-delay"] = 0.25
        engine.player["sub-delay"] = -0.5
        engine.player["video-aspect-override"] = "16:9"
        engine.player.container_fps_override = 24.0

        # Track signals emitted
        track_signals = []
        engine.bridge = type("Bridge", (), {"track_list_signal": type("Sig", (), {"emit": lambda s, v: track_signals.append(v)})()})()
        engine._safe_emit = lambda sig, *args: track_signals.append((sig, args))

        # Perform complete reset
        engine.reset_playback_state()

        # Verify all options and tracks are flushed
        self.assertEqual(engine.player["audio-files"], [])
        self.assertEqual(engine.player["sub-files"], [])
        self.assertEqual(engine.player["af"], "")
        self.assertEqual(engine.player["vf"], "")
        self.assertEqual(engine.player["aid"], "auto")
        self.assertEqual(engine.player["sid"], "auto")
        self.assertEqual(engine.player["vid"], "auto")
        self.assertEqual(engine.player["audio-delay"], 0.0)
        self.assertEqual(engine.player["sub-delay"], 0.0)
        self.assertEqual(engine.player["video-aspect-override"], "-1")
        self.assertIn(engine.player.container_fps_override, (None, 0.0, 0))

        self.assertFalse(engine.nvjpeg2k_active)
        self.assertFalse(engine.is_dcp_playing)
        self.assertIsNone(engine.current_dcp)
        self.assertIsNone(engine.active_cpl)
        self.assertEqual(engine.current_reel_index, 0)
        self.assertIsNone(engine.current_iab_meta)

        # Ensure track_list_signal was emitted with empty list to clear UI
        self.assertTrue(any(sig == "track_list_signal" and args == ([],) for sig, args in track_signals))

    def test_mainwindow_clears_tracks_on_new_file(self):
        win = MainWindow()
        try:
            # Simulate dirty track menus from previous file
            act1 = QAction("Track 1: Previous Hindi Audio", win.menu_audio_tracks)
            win.menu_audio_tracks.addAction(act1)
            act2 = QAction("Track 1: Previous English Subtitle", win.menu_sub_tracks)
            win.menu_sub_tracks.addAction(act2)
            act3 = QAction("Track 1: Previous Angle 1", win.menu_video_tracks)
            win.menu_video_tracks.addAction(act3)

            self.assertGreater(len(win.menu_audio_tracks.actions()), 0)
            self.assertGreater(len(win.menu_sub_tracks.actions()), 0)
            self.assertGreater(len(win.menu_video_tracks.actions()), 0)

            # When a new file is opened via play_media, previous menus must be wiped immediately
            win.play_media("http://localhost/new_sample_video.mp4", "New Media")

            self.assertEqual(len(win.menu_audio_tracks.actions()), 0)
            self.assertEqual(len(win.menu_sub_tracks.actions()), 0)
            self.assertEqual(len(win.menu_video_tracks.actions()), 0)
            self.assertIn("New Media", win.lbl_status_media.text())
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
