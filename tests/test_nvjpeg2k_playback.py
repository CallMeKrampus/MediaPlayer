"""
Unit Tests for NVIDIA nvJPEG2000 GPU Decoding & Native 4K Playback Engine in BOOB Player
"""

import os
import time
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage

from core.nvjpeg2k_engine import NVJPEG2KEngine, NVJPEG2KPlaybackController
from core.dcp_parser import DCPParser
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestNVJPEG2KPlayback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dcp_path = r"C:\Users\User\Downloads\MediaPlayer\Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV"
        cls.mxf_path = os.path.join(cls.dcp_path, "Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-jp2k.mxf")
        cls.engine = NVJPEG2KEngine.get_instance()

    def test_01_engine_ptx_color_pipeline(self):
        self.assertTrue(self.engine.is_available(), "NVIDIA nvJPEG2000 engine should be available")
        self.assertTrue(self.engine.initialize(), "CUDA context and PTX shader must compile successfully")
        self.assertIn("NVIDIA", self.engine.gpu_name)
        self.assertIsNotNone(self.engine.color_func)

    def test_02_mxf_fast_indexing(self):
        t0 = time.time()
        index = self.engine.index_mxf(self.mxf_path)
        elapsed = time.time() - t0
        self.assertGreater(len(index), 1000, "Should index all 4K cinema frames")
        self.assertLess(elapsed, 2.0, "MXF indexing should be ultra-fast")
        # Test offset validity
        offset, length = index[0]
        self.assertEqual(offset, 16544)
        self.assertGreater(length, 100000)

    def test_03_gpu_decode_and_tonemap_frame(self):
        t0 = time.time()
        qimg = self.engine.decode_and_tonemap_frame(self.mxf_path, 0)
        elapsed_ms = (time.time() - t0) * 1000.0
        self.assertIsNotNone(qimg)
        self.assertFalse(qimg.isNull())
        self.assertEqual(qimg.width(), 4096)
        self.assertEqual(qimg.height(), 2160)
        self.assertEqual(qimg.format(), QImage.Format.Format_RGB32)
        self.assertLess(elapsed_ms, 60.0, "Single 4K GPU frame decode + tonemap should be fast")

    def test_04_playback_controller_clock_and_sync(self):
        ctrl = NVJPEG2KPlaybackController()
        loaded = ctrl.load_reel(self.mxf_path, fps=24.0)
        self.assertTrue(loaded)
        self.assertEqual(ctrl.fps, 24.0)
        self.assertGreater(ctrl.total_frames, 1000)

        # Frame step forward & backward
        ctrl.step_frame(1)
        self.assertEqual(ctrl.current_frame_idx, 1)
        ctrl.step_frame(4)
        self.assertEqual(ctrl.current_frame_idx, 5)
        ctrl.step_frame(-2)
        self.assertEqual(ctrl.current_frame_idx, 3)

        # Seek time
        ctrl.seek_time(10.0) # 10s * 24fps = 240
        self.assertEqual(ctrl.current_frame_idx, 240)

        # Audio clock sync
        ctrl.play()
        ctrl.sync_audio_clock(12.5) # 12.5s * 24fps = 300
        self.assertEqual(ctrl.current_frame_idx, 300)
        ctrl.pause()
        self.assertFalse(ctrl.is_playing)

    def test_05_live_dcp_gpu_playback_in_main_window(self):
        win = MainWindow()
        win.show()

        # Play DCP package
        win.play_dcp_folder(self.dcp_path)
        self.assertTrue(win.engine.nvjpeg2k_active, "nvJPEG2000 active flag must be set for native 4K playback")
        self.assertTrue(win.video_widget.nv_viewport.isVisible(), "nv_viewport must be visible for GPU presentation")

        # Process playback events for 0.5s
        t0 = time.time()
        while time.time() - t0 < 0.5:
            app.processEvents()
            time.sleep(0.02)

        self.assertIn("NVJPEG2000 4K", win.current_source_codec_str)

        # Test seek and pause
        win.engine.seek(15.0, relative=False)
        app.processEvents()
        self.assertAlmostEqual(win.engine.nv_controller.current_pts, 15.0, delta=2.5)

        win.engine.stop()
        win.close()

    def test_06_dcp_live_tonemap_preset_and_target_peak_switching(self):
        win = MainWindow()
        win.show()
        win.play_dcp_folder(self.dcp_path)
        app.processEvents()

        ctrl = win.engine.nv_controller
        self.assertIsNotNone(ctrl)

        # 1. Switch to Pass-Through preset
        win._apply_tonemap_preset("passthrough")
        app.processEvents()
        self.assertEqual(ctrl.grading_params["preset_mode"], 2)
        self.assertEqual(ctrl.grading_params["preset"], "passthrough")

        # 2. Switch to Reinhard preset
        win._apply_tonemap_preset("reinhard_sdr")
        app.processEvents()
        self.assertEqual(ctrl.grading_params["preset_mode"], 6)

        # 3. Switch to Filmic Hable preset
        win._apply_tonemap_preset("filmic_hable")
        app.processEvents()
        self.assertEqual(ctrl.grading_params["preset_mode"], 3)

        # 4. Switch to DCI-XYZ standard and adjust target peak nits
        win.engine.tonemap_engine.set_epiq_correction(False)
        win._apply_tonemap_preset("dci_xyz_srgb")
        app.processEvents()
        self.assertEqual(ctrl.grading_params["preset_mode"], 0)

        # Change target peak to 400 nits via tonemap_engine
        win.engine.tonemap_engine.set_target_peak(400)
        app.processEvents()
        self.assertEqual(ctrl.grading_params["target_peak"], 400)
        self.assertEqual(ctrl.grading_params["peak_k1"], 8.80)
        self.assertEqual(ctrl.grading_params["peak_k2"], 3.90)

        # Change target peak to 80 nits (studio dark room)
        win.engine.tonemap_engine.set_target_peak(80)
        app.processEvents()
        self.assertEqual(ctrl.grading_params["target_peak"], 80)
        self.assertEqual(ctrl.grading_params["peak_k1"], 1.18)
        self.assertEqual(ctrl.grading_params["peak_k2"], 0.20)

        win.engine.stop()
        win.close()


if __name__ == "__main__":
    unittest.main()
