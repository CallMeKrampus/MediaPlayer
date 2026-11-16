"""
Unit tests for newly added features:
- 3D LUT Support (.cube / .3dl)
- Windows 11 Direct HDR Pass-Through
- Split-Screen Comparison Wipe Tool
- A-B Repeat Looping
- Speed-Preserving Pitch Audio Correction
- Chapter Navigation and Seekbar Markers
- Seekbar Hover Thumbnail Generator and Tooltip
- Stereoscopic 3D Real-Time Parallax / Convergence
- Lossless Clip Trimmer
"""

import os
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPoint

app = QApplication.instance() or QApplication([])

from core.tonemap_engine import TonemapEngine
from core.stereo3d_engine import Stereo3DEngine
from core.clip_trimmer import LosslessTrimWorker
from core.thumbnail_generator import ThumbnailManager
from ui.osc_controls import HoverScrubberSlider, HoverThumbnailPopup
from ui.video_widget import NVJPEG2KCanvas
from ui.stereo3d_dialog import Stereo3DDialog


class DummyMPV:
    def __init__(self):
        self.props = {}
        self.commands = []
        self.speed = 1.0
        self.time_pos = 10.0
        self.duration = 100.0
        self.chapter_list = [
            {"time": 0.0, "title": "Intro"},
            {"time": 30.0, "title": "Part 1"},
            {"time": 75.0, "title": "Climax"},
        ]

    def __getitem__(self, key):
        return self.props.get(key)

    def __setitem__(self, key, value):
        self.props[key] = value

    def command(self, *args):
        self.commands.append(args)


class TestColorAndQCFeatures(unittest.TestCase):
    def setUp(self):
        self.dummy_mpv = DummyMPV()
        self.engine = TonemapEngine(self.dummy_mpv)

    def test_3d_lut_controls(self):
        # 1. Set 3D LUT with non-existent file
        self.engine.set_3d_lut("non_existent_lut.cube")
        self.assertFalse(self.engine.lut_enabled)
        self.assertEqual(self.dummy_mpv["lut"], "")

        # 2. Toggle without valid file
        self.assertFalse(self.engine.toggle_3d_lut())

        # 3. Clear LUT
        self.engine.clear_3d_lut()
        self.assertIsNone(self.engine.lut_path)
        self.assertFalse(self.engine.lut_enabled)

    def test_windows11_hdr_passthrough(self):
        self.engine.set_hdr_passthrough(True)
        self.assertTrue(self.engine.hdr_passthrough)
        self.assertEqual(self.dummy_mpv["target-colorspace-hint"], "yes")
        self.assertEqual(self.dummy_mpv["tone-mapping"], "passthrough")

        self.engine.set_hdr_passthrough(False)
        self.assertFalse(self.engine.hdr_passthrough)
        self.assertEqual(self.dummy_mpv["target-colorspace-hint"], "no")

    def test_split_wipe_canvas(self):
        canvas = NVJPEG2KCanvas()
        canvas.set_split_wipe(True, 0.65)
        self.assertTrue(canvas.split_wipe_enabled)
        self.assertAlmostEqual(canvas.split_wipe_pos, 0.65, places=2)

        # Clamping test
        canvas.set_split_wipe(True, 1.5)
        self.assertLessEqual(canvas.split_wipe_pos, 0.95)
        canvas.set_split_wipe(True, -0.2)
        self.assertGreaterEqual(canvas.split_wipe_pos, 0.05)


class TestPlaybackAndNavigationFeatures(unittest.TestCase):
    def setUp(self):
        from core.mpv_engine import MPVEngine
        self.mpv_eng = MPVEngine()
        self.mpv_eng.player = DummyMPV()

    def test_speed_controls_pitch_preserved(self):
        # Test default speed
        self.assertEqual(self.mpv_eng.playback_speed, 1.0)

        # Set speed
        spd = self.mpv_eng.set_speed(1.5)
        self.assertEqual(spd, 1.5)
        self.assertEqual(self.mpv_eng.player["speed"], 1.5)

        # Adjust speed
        spd = self.mpv_eng.adjust_speed(0.1)
        self.assertAlmostEqual(spd, 1.6, places=2)

        # Speed clamp
        spd = self.mpv_eng.set_speed(10.0)
        self.assertEqual(spd, 4.0)
        spd = self.mpv_eng.set_speed(0.01)
        self.assertEqual(spd, 0.25)

        # Reset speed
        spd = self.mpv_eng.reset_speed()
        self.assertEqual(spd, 1.0)
        self.assertEqual(self.mpv_eng.player["speed"], 1.0)

    def test_ab_repeat_loop(self):
        self.mpv_eng.clear_ab_repeat()
        self.assertIsNone(self.mpv_eng.ab_point_a)
        self.assertIsNone(self.mpv_eng.ab_point_b)

        # Set Point A at 15.0s
        self.mpv_eng.set_ab_point_a(15.0)
        self.assertEqual(self.mpv_eng.ab_point_a, 15.0)
        self.assertIsNone(self.mpv_eng.ab_point_b)

        # Invalid Point B (less than A) should be rejected
        res = self.mpv_eng.set_ab_point_b(10.0)
        self.assertIsNone(res)
        self.assertIsNone(self.mpv_eng.ab_point_b)

        # Valid Point B
        res = self.mpv_eng.set_ab_point_b(35.5)
        self.assertEqual(res, 35.5)
        self.assertEqual(self.mpv_eng.ab_point_b, 35.5)

        # Clear
        self.mpv_eng.clear_ab_repeat()
        self.assertIsNone(self.mpv_eng.ab_point_a)
        self.assertIsNone(self.mpv_eng.ab_point_b)

    def test_chapter_navigation(self):
        chaps = self.mpv_eng.get_chapters()
        self.assertEqual(len(chaps), 3)
        self.assertEqual(chaps[0]["title"], "Intro")
        self.assertEqual(chaps[1]["time"], 30.0)


class TestSeekbarAndStereo3D(unittest.TestCase):
    def test_slider_chapters_and_ab_repeat(self):
        slider = HoverScrubberSlider()
        slider.duration = 120.0
        slider.set_chapters([{"time": 20.0, "title": "Scene 1"}])
        self.assertEqual(len(slider.chapters), 1)

        slider.set_ab_repeat(10.0, 45.0)
        self.assertEqual(slider.ab_point_a, 10.0)
        self.assertEqual(slider.ab_point_b, 45.0)

    def test_stereo3d_parallax(self):
        dummy_mpv = DummyMPV()
        s3d = Stereo3DEngine(dummy_mpv)

        # Default parallax is 0
        self.assertEqual(s3d.parallax_offset, 0)

        # Set parallax offset
        s3d.set_parallax_offset(15)
        self.assertEqual(s3d.parallax_offset, 15)
        summary = s3d.get_status_summary()
        self.assertEqual(summary["parallax_offset"], 15)

        # Clamping
        s3d.set_parallax_offset(100)
        self.assertEqual(s3d.parallax_offset, 60)
        s3d.set_parallax_offset(-100)
        self.assertEqual(s3d.parallax_offset, -60)

        # Reset
        s3d.reset_parallax()
        self.assertEqual(s3d.parallax_offset, 0)

    def test_lossless_trim_worker_init(self):
        worker = LosslessTrimWorker(
            source_path="video.mp4",
            output_path="out.mp4",
            start_time_sec=10.5,
            end_time_sec=25.0
        )
        self.assertEqual(worker.start_time, 10.5)
        self.assertEqual(worker.end_time, 25.0)
        self.assertEqual(worker.output_path, "out.mp4")


if __name__ == "__main__":
    unittest.main()
