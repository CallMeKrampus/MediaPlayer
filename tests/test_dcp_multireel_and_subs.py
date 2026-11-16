"""
Unit and Integration Tests for BOOB Player Multi-Reel DCP Playback and Subtitle Engine
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dcp_parser import DCPParser, DCPPackage, DCPReel, DCPComposition
from core.dcp_subtitle_engine import DCPSubtitleEngine, parse_dcp_timecode, format_srt_time


class TestDCPSubtitleEngine(unittest.TestCase):
    def test_timecode_parsing(self):
        # SMPTE HH:MM:SS:FF at 24fps
        self.assertAlmostEqual(parse_dcp_timecode("00:00:01:12", 24.0), 1.5)
        # Interop HH:MM:SS:TTT (250 ticks)
        self.assertAlmostEqual(parse_dcp_timecode("00:00:01:125", 24.0), 1.5)
        # Fractional seconds
        self.assertAlmostEqual(parse_dcp_timecode("00:01:00.500", 24.0), 60.5)

    def test_srt_formatting(self):
        self.assertEqual(format_srt_time(0.0), "00:00:00,000")
        self.assertEqual(format_srt_time(61.5), "00:01:01,500")
        self.assertEqual(format_srt_time(3665.123), "01:01:05,123")

    def test_xml_parsing_and_binary_search(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <SubtitleReel xmlns="http://www.smpte-ra.org/schemas/428-7/2010/DCST">
            <Id>urn:uuid:11111111-2222-3333-4444-555555555555</Id>
            <Language>en</Language>
            <SubtitleList>
                <Subtitle SpotNumber="1" TimeIn="00:00:05:00" TimeOut="00:00:08:00" FadeUpTime="00:00:00:00" FadeDownTime="00:00:00:00">
                    <Text Vposition="10" Valign="bottom">Hello World</Text>
                </Subtitle>
                <Subtitle SpotNumber="2" TimeIn="00:00:10:00" TimeOut="00:00:15:00" FadeUpTime="00:00:00:00" FadeDownTime="00:00:00:00">
                    <Text Vposition="14" Valign="bottom"><Font Italic="yes">Second Cue</Font></Text>
                    <Text Vposition="8" Valign="bottom"><Font Italic="yes">Second Line</Font></Text>
                </Subtitle>
            </SubtitleList>
        </SubtitleReel>
        """
        engine = DCPSubtitleEngine()
        cues, lang = engine._parse_xml_cues(xml_content, fps=24.0, offset_sec=100.0)
        self.assertEqual(lang, "en")
        self.assertEqual(len(cues), 2)
        # Cue 1: 5s + 100s offset = 105s
        self.assertAlmostEqual(cues[0].start_sec, 105.0)
        self.assertAlmostEqual(cues[0].end_sec, 108.0)
        self.assertEqual(cues[0].text, "Hello World")
        # Cue 2: 10s + 100s offset = 110s (with nested <Font Italic="yes">)
        self.assertAlmostEqual(cues[1].start_sec, 110.0)
        self.assertAlmostEqual(cues[1].end_sec, 115.0)
        self.assertEqual(cues[1].text, "<i>Second Cue</i>\n<i>Second Line</i>")

        # Test binary search
        engine.cues = cues
        engine._start_times = [c.start_sec for c in cues]
        self.assertIsNone(engine.get_text_at_pts(50.0))
        self.assertIsNone(engine.get_text_at_pts(104.9))
        self.assertEqual(engine.get_text_at_pts(106.0), "Hello World")
        self.assertIsNone(engine.get_text_at_pts(109.0))
        self.assertEqual(engine.get_text_at_pts(112.5), "<i>Second Cue</i>\n<i>Second Line</i>")
        self.assertIsNone(engine.get_text_at_pts(116.0))


class TestMultiReelDCPIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dcp_path = r"F:\LaBolaNegra"
        cls.has_dcp = os.path.exists(cls.dcp_path)

    def test_labolanegra_structure(self):
        if not self.has_dcp:
            self.skipTest("F:\\LaBolaNegra not found")

        pkg = DCPParser.parse(self.dcp_path)
        cpl = pkg.default_composition
        self.assertIsNotNone(cpl)
        self.assertEqual(len(cpl.reels), 6)
        self.assertAlmostEqual(cpl.fps, 24.0)

        # Check total composition duration (9569.25 seconds = 229,662 frames / 24 fps)
        total_frames = sum(r.picture_duration_frames for r in cpl.reels)
        self.assertEqual(total_frames, 229662)
        total_sec = total_frames / 24.0
        self.assertAlmostEqual(total_sec, 9569.25)

    def test_labolanegra_subtitles(self):
        if not self.has_dcp:
            self.skipTest("F:\\LaBolaNegra not found")

        pkg = DCPParser.parse(self.dcp_path)
        cpl = pkg.default_composition
        engine = DCPSubtitleEngine()
        srt_path = engine.load_composition_subtitles(cpl)

        self.assertIsNotNone(srt_path)
        self.assertTrue(os.path.exists(srt_path))
        self.assertEqual(len(engine.cues), 1998)
        self.assertEqual(engine.language, "en")

        # Verify per-reel SRT generation
        self.assertIn(2, engine.reel_srt_paths)
        self.assertIn(3, engine.reel_srt_paths)
        self.assertIn(4, engine.reel_srt_paths)
        self.assertTrue(os.path.exists(engine.reel_srt_paths[2]))

        # Test known cues at specific global composition PTS (including recovered italic dialogue)
        self.assertEqual(engine.get_text_at_pts(109.0), "<i>Spaniards, this is Radio Nacional</i>")
        self.assertEqual(engine.get_text_at_pts(112.0), "<i>talking from the liberated zone.</i>")
        self.assertEqual(engine.get_text_at_pts(121.0), "DAIRY")
        self.assertEqual(engine.get_text_at_pts(4618.0), "Why is this very new heart so upset?")

    def test_labolanegra_fast_footer_indexing(self):
        if not self.has_dcp:
            self.skipTest("F:\\LaBolaNegra not found")

        import time
        from core.nvjpeg2k_engine import NVJPEG2KEngine

        eng = NVJPEG2KEngine.get_instance()
        if not eng.initialized and not eng.initialize():
            self.skipTest("NVJPEG2000 engine not available")

        pkg = DCPParser.parse(self.dcp_path)
        cpl = pkg.default_composition
        for r in cpl.reels:
            eng._mxf_index_cache.pop(r.picture_path, None)
            t0 = time.perf_counter()
            offsets = eng.index_mxf(r.picture_path)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.assertLess(elapsed_ms, 200.0, f"Reel {r.index} took {elapsed_ms:.1f}ms to index")
            self.assertEqual(len(offsets), r.picture_duration_frames)

    def test_labolanegra_seamless_reel_transition(self):
        if not self.has_dcp:
            self.skipTest("F:\\LaBolaNegra not found")

        import time
        from PyQt6.QtWidgets import QApplication
        from ui.main_window import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        win = MainWindow()
        win.show()

        events = []
        win.play_dcp_folder(self.dcp_path, start_reel_index=0)
        if not win.engine.nvjpeg2k_active or win.engine.nv_controller is None:
            win.close()
            self.skipTest("NVJPEG2000 playback controller not active")

        win.engine.nv_controller.frame_ready.connect(
            lambda _img, idx, _pts: events.append((time.perf_counter(), win.engine.current_reel_index, idx))
        )
        win.engine.seek(7.3, relative=False)

        try:
            t0 = time.time()
            while time.time() - t0 < 6.0:
                app.processEvents()
                time.sleep(0.002)
                if any(e[1] == 1 for e in events) and len([e for e in events if e[1] == 1]) > 6:
                    break

            r0_frames = [e for e in events if e[1] == 0]
            r1_frames = [e for e in events if e[1] == 1]

            self.assertGreater(len(r0_frames), 0)
            self.assertGreater(len(r1_frames), 5)
            # Final frame of Reel 0 (frame 191 of 192) must be presented (no premature cutoff)
            self.assertEqual(r0_frames[-1][2], 191)
            # First frame of Reel 1 (frame 0) must follow within <= 120ms (~24fps cadence + OS timer jitter)
            self.assertEqual(r1_frames[0][2], 0)
            gap_ms = (r1_frames[0][0] - r0_frames[-1][0]) * 1000.0
            self.assertLess(gap_ms, 120.0, f"Reel 0 -> Reel 1 frame transition gap too large: {gap_ms:.1f}ms")
            # Strictly monotonic frames in Reel 1 (zero 0 -> 1 -> 0 backward stutter)
            r1_indices = [e[2] for e in r1_frames]
            self.assertEqual(r1_indices, sorted(r1_indices))
        finally:
            win.engine.stop()
            win.close()
            if win.engine.nv_controller:
                win.engine.nv_controller.close()
            if win.engine.player:
                win.engine.player.terminate()


if __name__ == "__main__":
    unittest.main()
