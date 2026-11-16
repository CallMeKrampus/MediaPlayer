"""
Unit tests for Uncompressed, Tonemapped Snapshot & Save-As Dialog Workflow.
"""

import os
import time
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication, QFileDialog

from core.mpv_engine import MPVEngine
from ui.main_window import MainWindow


class TestSnapshotWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.video_path = os.path.join(cls.base_dir, "assets", "sample_prores422.mov")

    def test_01_engine_uncompressed_png_and_tiff(self):
        engine = MPVEngine()
        try:
            engine.play(self.video_path)
            time.sleep(0.5)

            with tempfile.TemporaryDirectory() as tmpdir:
                # 1. Uncompressed PNG
                target_png = os.path.join(tmpdir, "snap_uncompressed.png")
                saved_png = engine.take_screenshot(target_png)
                self.assertEqual(os.path.normpath(saved_png), os.path.normpath(target_png))
                self.assertTrue(os.path.exists(target_png))
                self.assertGreater(os.path.getsize(target_png), 1000)
                self.assertEqual(engine.player["screenshot-format"], "png")
                self.assertEqual(engine.player["screenshot-png-compression"], 0)

                # 2. Uncompressed TIFF
                target_tiff = os.path.join(tmpdir, "snap_uncompressed.tiff")
                saved_tiff = engine.take_screenshot(target_tiff)
                self.assertEqual(os.path.normpath(saved_tiff), os.path.normpath(target_tiff))
                self.assertTrue(os.path.exists(target_tiff))
                self.assertGreater(os.path.getsize(target_tiff), 1000)

                # 3. Uncompressed BMP
                target_bmp = os.path.join(tmpdir, "snap_uncompressed.bmp")
                saved_bmp = engine.take_screenshot(target_bmp)
                self.assertEqual(os.path.normpath(saved_bmp), os.path.normpath(target_bmp))
                self.assertTrue(os.path.exists(target_bmp))
                self.assertGreater(os.path.getsize(target_bmp), 1000)
        finally:
            engine.stop()

    def test_02_main_window_prompt_and_save(self):
        win = MainWindow()
        try:
            win.engine.play(self.video_path)
            time.sleep(0.5)

            with tempfile.TemporaryDirectory() as tmpdir:
                dialog_target = os.path.join(tmpdir, "user_chosen_location.png")
                # User selects path in dialog with Original Resolution (default)
                with patch.object(QFileDialog, "getSaveFileName", return_value=(dialog_target, "Lossless PNG - Original Resolution (1280x720) (*.png)")):
                    saved = win.take_snapshot()
                    self.assertEqual(os.path.normpath(saved), os.path.normpath(dialog_target))
                    self.assertTrue(os.path.exists(dialog_target))
                    from PIL import Image
                    with Image.open(dialog_target) as im:
                        self.assertIn(im.size, [(100, 30), (1280, 720)])

                # User cancels dialog -> does not save
                with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                    cancel_res = win.take_snapshot()
                    self.assertIsNone(cancel_res)
        finally:
            win.close()

    def test_03_active_image_area_cropping_letterbox_and_pillarbox(self):
        import numpy as np
        from PIL import Image
        from PyQt6.QtGui import QImage
        from core.media_inspector import MediaInspector

        # 1. Test letterbox (top/bottom black bars, e.g. 2.39:1 scope in 16:9)
        # 1920x1080 canvas, active rows 140 to 940 (height 800)
        lb_arr = np.zeros((1080, 1920, 3), dtype=np.uint8)
        lb_arr[140:940, :, :] = 150  # Active picture
        lb_pil = Image.fromarray(lb_arr)

        top, bottom, left, right = MediaInspector.get_active_image_bounds(lb_pil)
        self.assertEqual(top, 140)
        self.assertEqual(bottom, 940)
        self.assertEqual(left, 0)
        self.assertEqual(right, 1920)

        cropped_pil = MediaInspector.crop_active_image_area(lb_pil)
        self.assertEqual(cropped_pil.size, (1920, 800))

        # 2. Test pillarbox (left/right black bars, e.g. 4:3 in 16:9)
        # 1920x1080 canvas, active cols 240 to 1680 (width 1440)
        pb_arr = np.zeros((1080, 1920, 3), dtype=np.uint8)
        pb_arr[:, 240:1680, :] = 160
        pb_pil = Image.fromarray(pb_arr)

        top, bottom, left, right = MediaInspector.get_active_image_bounds(pb_pil)
        self.assertEqual(top, 0)
        self.assertEqual(bottom, 1080)
        self.assertEqual(left, 240)
        self.assertEqual(right, 1680)

        cropped_pb = MediaInspector.crop_active_image_area(pb_pil)
        self.assertEqual(cropped_pb.size, (1440, 1080))

        # 3. Test QImage cropping for DCP canvas
        dcp_scope_arr = np.zeros((2160, 4096, 4), dtype=np.uint8)
        dcp_scope_arr[222:1938, :, :3] = 175  # 4096x1716 Scope
        dcp_scope_arr[:, :, 3] = 255
        dcp_qimage = QImage(dcp_scope_arr.data, 4096, 2160, 4096 * 4, QImage.Format.Format_RGBA8888)

        cropped_qimage = MediaInspector.crop_active_image_area(dcp_qimage)
        self.assertEqual(cropped_qimage.width(), 4096)
        self.assertEqual(cropped_qimage.height(), 1716)

    def test_04_dcp_canvas_rgb_channel_order_not_swapped(self):
        import numpy as np
        from PIL import Image
        from PyQt6.QtGui import QImage

        win = MainWindow()
        try:
            # Simulate active NVJPEG2K frame in Format_RGB32 (memory layout B, G, R, A on x86 Windows)
            # Gold / warm colors: R=240, G=180, B=30
            raw_buf = np.zeros((100, 100, 4), dtype=np.uint8)
            raw_buf[:, :, 0] = 30   # Byte 0 is Blue in Format_RGB32
            raw_buf[:, :, 1] = 180  # Byte 1 is Green
            raw_buf[:, :, 2] = 240  # Byte 2 is Red
            raw_buf[:, :, 3] = 255  # Alpha

            qimg = QImage(raw_buf.data, 100, 100, 100 * 4, QImage.Format.Format_RGB32)
            win.engine.nvjpeg2k_active = True
            win.video_widget.nv_viewport.current_frame = qimg

            with tempfile.TemporaryDirectory() as tmpdir:
                target = os.path.join(tmpdir, "gold_frame.png")
                with patch.object(QFileDialog, "getSaveFileName", return_value=(target, "PNG")):
                    saved = win.take_snapshot()
                    self.assertEqual(os.path.normpath(saved), os.path.normpath(target))
                    self.assertTrue(os.path.exists(target))

                    with Image.open(target) as im:
                        px = np.array(im)[0, 0]
                        # Red must be 240, Green must be 180, Blue must be 30
                        self.assertEqual(int(px[0]), 240, "Red channel was corrupted or swapped!")
                        self.assertEqual(int(px[1]), 180, "Green channel was corrupted!")
                        self.assertEqual(int(px[2]), 30, "Blue channel was corrupted or swapped!")
        finally:
            win.close()

    def test_05_manual_laser_unsqueeze_snapshot_nvjpeg2k(self):
        import numpy as np
        from PIL import Image
        from PyQt6.QtGui import QImage

        win = MainWindow()
        try:
            # Squeezed 4K laser frame (4096x2160)
            squeezed_arr = np.full((2160, 4096, 4), 200, dtype=np.uint8)
            squeezed_arr[:, :, 3] = 255
            qimg = QImage(squeezed_arr.data, 4096, 2160, 4096 * 4, QImage.Format.Format_RGB32)

            win.engine.nvjpeg2k_active = True
            win.video_widget.nv_viewport.current_frame = qimg

            # User manually applies 1.43:1 IMAX GT unsqueeze override
            win._set_aspect_ratio("1.43:1")
            self.assertTrue(win.video_widget.nv_viewport.is_anamorphic_143)
            self.assertEqual(win.video_widget.nv_viewport.aspect_override, 1.43)

            with tempfile.TemporaryDirectory() as tmpdir:
                target = os.path.join(tmpdir, "manual_unsqueezed_4k.png")
                with patch.object(QFileDialog, "getSaveFileName", return_value=(target, "Lossless PNG")):
                    saved = win.take_snapshot()
                    self.assertEqual(os.path.normpath(saved), os.path.normpath(target))
                    self.assertTrue(os.path.exists(target))

                    with Image.open(target) as im:
                        # Must be unsqueezed 4096x2864, not squeezed 4096x2160
                        self.assertEqual(im.size, (4096, 2864), "Snapshot did not unsqueeze manual laser squeeze!")

            # Also verify 2K manual unsqueeze: 2048x1080 -> 2048x1432
            squeezed_2k = np.full((1080, 2048, 4), 180, dtype=np.uint8)
            squeezed_2k[:, :, 3] = 255
            qimg_2k = QImage(squeezed_2k.data, 2048, 1080, 2048 * 4, QImage.Format.Format_RGB32)
            win.video_widget.nv_viewport.current_frame = qimg_2k

            with tempfile.TemporaryDirectory() as tmpdir:
                target_2k = os.path.join(tmpdir, "manual_unsqueezed_2k.png")
                with patch.object(QFileDialog, "getSaveFileName", return_value=(target_2k, "Lossless PNG")):
                    saved_2k = win.take_snapshot()
                    self.assertEqual(os.path.normpath(saved_2k), os.path.normpath(target_2k))
                    with Image.open(target_2k) as im2:
                        self.assertEqual(im2.size, (2048, 1432), "2K Snapshot did not unsqueeze to 2048x1432!")
        finally:
            win.close()

    def test_06_manual_laser_unsqueeze_snapshot_mpv(self):
        from PIL import Image

        engine = MPVEngine()
        try:
            # 1. Test get_target_aspect_ratio
            self.assertIsNone(engine.get_target_aspect_ratio())
            engine.set_aspect_ratio("1.43:1")
            self.assertAlmostEqual(engine.get_target_aspect_ratio(), 1.43, delta=0.01)

            # 2. Test take_screenshot with manual aspect override unsqueeze
            with tempfile.TemporaryDirectory() as tmpdir:
                # Mock screenshot-to-file to create a squeezed 4096x2160 PNG
                def fake_command(cmd, path, mode="video"):
                    if cmd == "screenshot-to-file":
                        squeezed = Image.new("RGB", (4096, 2160), color=(100, 150, 200))
                        squeezed.save(path, "PNG")

                with patch.object(engine.player, "command", side_effect=fake_command):
                    target_out = os.path.join(tmpdir, "mpv_unsqueezed.png")
                    saved = engine.take_screenshot(target_out)
                    self.assertEqual(os.path.normpath(saved), os.path.normpath(target_out))
                    self.assertTrue(os.path.exists(target_out))

                    with Image.open(target_out) as im:
                        self.assertEqual(im.size, (4096, 2864), "MPV screenshot failed to unsqueeze 4096x2160 to 4096x2864!")

            # 3. Test auto-detected anamorphic unsqueeze flag
            engine.set_aspect_ratio("-1")
            engine.is_anamorphic_143 = True
            self.assertAlmostEqual(engine.get_target_aspect_ratio(), 1.43, delta=0.01)

            with tempfile.TemporaryDirectory() as tmpdir:
                def fake_command_auto(cmd, path, mode="video"):
                    if cmd == "screenshot-to-file":
                        squeezed = Image.new("RGB", (3840, 2160), color=(120, 160, 210))
                        squeezed.save(path, "PNG")

                with patch.object(engine.player, "command", side_effect=fake_command_auto):
                    target_out2 = os.path.join(tmpdir, "mpv_auto_unsqueezed.png")
                    saved2 = engine.take_screenshot(target_out2)
                    self.assertTrue(os.path.exists(saved2))

                    with Image.open(saved2) as im2:
                        self.assertEqual(im2.size, (3840, 2685), "MPV auto-unsqueeze failed to stretch 3840x2160!")
        finally:
            engine.stop()


if __name__ == "__main__":
    unittest.main()
