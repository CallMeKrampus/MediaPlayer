import os
import sys
import time
import unittest

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.dcp_parser import DCPParser
from core.iab_engine import IABEngine
from ui.main_window import MainWindow
from ui.video_widget import NVJPEG2KCanvas


_APP = QApplication.instance() or QApplication(sys.argv)


class TestIMAXAndOSCTransition(unittest.TestCase):
    LOST_WOLVES_DCP = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "LostWolves-IMX_TLR-1-LS-2D_C-143_EN-XX_INT_IMAX12_4K_IMX_20251022_IMX_SMPTE_OV",
        )
    )

    def test_lost_wolves_imax_flag_detection(self):
        # Unit check for IMAX5 & IMAX12 tokens
        flags_5 = DCPParser.detect_imax_flags("SomeFilm-IMX_FTR_C-143_EN-XX_IMAX5_2K_IMX_OV")
        self.assertTrue(flags_5["is_imax"])
        self.assertFalse(flags_5["is_laser_squeezed"])
        self.assertTrue(flags_5["is_imax_gt_143"])
        self.assertEqual(flags_5["imax_audio_format"], "IMAX5")
        self.assertTrue(flags_5["unsqueeze_to_143"])

        if not os.path.exists(self.LOST_WOLVES_DCP):
            self.skipTest("Lost Wolves DCP folder not found")

        pkg = DCPParser.parse(self.LOST_WOLVES_DCP)
        cpl = pkg.default_composition
        self.assertIsNotNone(cpl)
        self.assertEqual(len(cpl.reels), 3)
        self.assertTrue(cpl.is_imax)
        self.assertTrue(cpl.is_laser_squeezed)
        self.assertTrue(cpl.is_imax_gt_143)
        self.assertEqual(cpl.imax_audio_format, "IMAX12")
        self.assertTrue(cpl.unsqueeze_to_143)
        self.assertIn("1.43:1", cpl.reels[0].screen_aspect_ratio)
        self.assertIn("4096x2864", cpl.reels[0].screen_aspect_ratio)

    def test_anamorphic_143_unsqueeze_4k_and_2k(self):
        canvas = NVJPEG2KCanvas()
        canvas.set_anamorphic_unsqueeze(True)

        w4k, h4k = canvas.get_unsqueezed_dimensions(4096, 2160)
        self.assertEqual(w4k, 4096)
        self.assertEqual(h4k, 2864)
        self.assertAlmostEqual(w4k / h4k, 1.43, delta=0.005)

        w2k, h2k = canvas.get_unsqueezed_dimensions(2048, 1080)
        self.assertEqual(w2k, 2048)
        self.assertEqual(h2k, 1432)
        self.assertAlmostEqual(w2k / h2k, 1.43, delta=0.005)

        img_4k = QImage(4096, 2160, QImage.Format.Format_RGB32)
        stretched = canvas.unsqueeze_qimage(img_4k)
        self.assertEqual((stretched.width(), stretched.height()), (4096, 2864))

        if os.path.exists(self.LOST_WOLVES_DCP):
            win = MainWindow()
            win.show()
            win.play_dcp_folder(self.LOST_WOLVES_DCP)
            t0 = time.time()
            while time.time() - t0 < 0.8:
                _APP.processEvents()
                time.sleep(0.02)

            self.assertTrue(win.engine.is_anamorphic_143)
            self.assertTrue(win.video_widget.nv_viewport.anamorphic_unsqueeze_143)
            self.assertEqual(win.engine.current_imax_audio_format, "IMAX12")
            self.assertEqual(win.engine.current_sound_channels, 16)
            self.assertIn("1.43:1", win.current_source_codec_str)

            win.engine.stop()
            win.close()
            if win.engine.nv_controller:
                win.engine.nv_controller.close()
            if win.engine.player:
                win.engine.player.terminate()

    def test_imax5_and_imax12_audio_channel_mapping(self):
        # IMAX5: standard 5.1 layout with c3 (LFE) left empty
        f5_smpte = IABEngine.get_imax5_filter("cinema_51", num_channels=6)
        self.assertEqual(f5_smpte, "lavfi=[pan=5.1|c0=c0|c1=c1|c2=c2|c4=c4|c5=c5]")
        self.assertNotIn("c3=", f5_smpte)

        f5_contig = IABEngine.get_imax5_filter("cinema_51", num_channels=5)
        self.assertEqual(f5_contig, "lavfi=[pan=5.1|c0=c0|c1=c1|c2=c2|c4=c3|c5=c4]")
        self.assertNotIn("c3=", f5_contig)

        # IMAX12: 16-ch SMPTE MXF (LostWolves) skips c6/c7 HI/VI-N and leaves c3 LFE empty
        f12_71 = IABEngine.get_imax12_filter("cinema_71", num_channels=16)
        self.assertIn("pan=7.1|", f12_71)
        self.assertNotIn("c3=", f12_71)
        for ch_tok in ("c8", "c9", "c10", "c11", "c12", "c13"):
            self.assertIn(ch_tok, f12_71)
        self.assertNotIn("c6+", f12_71)
        self.assertNotIn("c7+", f12_71)

        # IMAX12: 12-ch contiguous IX12 order (L, R, C, Ch, Lrs, Rrs, Lss, Rss, Ltfs, Rtfs, Ltrs, Rtrs)
        f12_contig = IABEngine.get_imax12_filter("cinema_71", num_channels=12)
        self.assertIn("c6=c6+0.5*c8", f12_contig)
        self.assertIn("c4=c4+0.707*c10", f12_contig)
        self.assertNotIn("c3=", f12_contig)

    def test_lost_wolves_continuous_reel_transition_no_freeze(self):
        if not os.path.exists(self.LOST_WOLVES_DCP):
            self.skipTest("Lost Wolves DCP folder not found")

        win = MainWindow()
        win.show()
        win.play_dcp_folder(self.LOST_WOLVES_DCP)

        # Wait ~3.2s so playback crosses the 2.0s (48-frame) Reel 0 -> Reel 1 boundary
        t0 = time.time()
        while time.time() - t0 < 3.2:
            _APP.processEvents()
            time.sleep(0.02)

        nv = win.engine.nv_controller
        self.assertEqual(win.engine.current_reel_index, 1)
        if nv is not None:
            self.assertTrue(nv.is_playing)
            self.assertTrue(nv._presentation_timer.isActive())
            self.assertGreater(nv.current_frame_idx, 10)
        self.assertEqual(win.video_widget.nv_viewport.get_unsqueezed_dimensions(4096, 2160), (4096, 2864))

        win.engine.stop()
        win.close()
        if win.engine.nv_controller:
            win.engine.nv_controller.close()
        if win.engine.player:
            win.engine.player.terminate()

    def test_osc_fast_smooth_fade_transition(self):
        win = MainWindow()
        win.show()
        _APP.processEvents()

        # Inactivity hide timer must be fast (< 1s)
        self.assertLessEqual(win.video_widget.hide_timer.interval(), 1000)

        win.osc.fade_out(duration_ms=80)
        t0 = time.time()
        while time.time() - t0 < 0.25:
            _APP.processEvents()
            time.sleep(0.02)

        self.assertAlmostEqual(win.osc._opacity_effect.opacity(), 0.0, delta=0.05)
        self.assertFalse(win.osc.isVisible())

        win.osc.fade_in(duration_ms=80)
        t0 = time.time()
        while time.time() - t0 < 0.25:
            _APP.processEvents()
            time.sleep(0.02)

        self.assertTrue(win.osc.isVisible())
        self.assertAlmostEqual(win.osc._opacity_effect.opacity(), 1.0, delta=0.05)

        win.close()
        if win.engine.nv_controller:
            win.engine.nv_controller.close()
        if win.engine.player:
            win.engine.player.terminate()


if __name__ == "__main__":
    unittest.main()
