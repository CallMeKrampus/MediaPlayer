"""
Unit tests for Next-Gen AOMedia AV2 Codec Support & Minimalist Studio Dark Theme.
"""

import os
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication

from core.media_inspector import MediaInspector
from ui.theme import MINIMALIST_THEME_QSS, CYBERPUNK_THEME_QSS, get_theme_qss
from ui.main_window import MainWindow


class TestAV2Support(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_av2_stream_detection_variants(self):
        """Verify AV2 recognition across different FourCC, codec_name and container tags."""
        variants = [
            {"codec_name": "av2", "codec_long_name": "AOMedia Video 2"},
            {"codec_name": "av02", "codec_long_name": "Alliance for Open Media Video 2"},
            {"codec_name": "aom-av2", "codec_long_name": "AOMedia Video 2 experimental"},
            {"codec_name": "libaom-av2", "codec_long_name": "libaom AV2"},
            {"codec_name": "unknown", "codec_tag_string": "av02", "codec_long_name": "MP4 ISO AV02"},
        ]

        for idx, var in enumerate(variants):
            mock_probe = {
                "format": {"filename": f"sample_stream_{idx}.mp4"},
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "video",
                        "codec_name": var.get("codec_name"),
                        "codec_long_name": var.get("codec_long_name"),
                        "codec_tag_string": var.get("codec_tag_string", ""),
                        "width": 3840,
                        "height": 2160,
                        "r_frame_rate": "60/1",
                        "pix_fmt": "yuv420p10le",
                        "bits_per_raw_sample": "10",
                        "color_space": "bt2020nc",
                        "color_primaries": "bt2020",
                        "color_transfer": "smpte2084",
                    }
                ]
            }

            with patch("os.path.exists", return_value=True), patch("subprocess.run") as mock_run:
                import json
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = json.dumps(mock_probe)

                info = MediaInspector.inspect_file("dummy_av2.mp4")
                self.assertNotIn("error", info, f"Probe returned error: {info.get('error')}")
                self.assertEqual(len(info["video_tracks"]), 1)
                vt = info["video_tracks"][0]
                self.assertEqual(vt["codec"], "AOMedia AV2 (Next-Gen)", f"Variant {var} failed to identify as AV2!")
                self.assertTrue(vt.get("is_av2"), f"Variant {var} did not set is_av2 flag!")

    def test_av2_source_summary_formatting(self):
        """Verify concise studio summary formatting for 4K 60fps 10-bit AV2 streams."""
        media_data = {
            "video_tracks": [
                {
                    "codec": "AOMedia AV2 (Next-Gen)",
                    "width": 3840,
                    "height": 2160,
                    "fps": 60.0,
                    "bits_per_raw_sample": "10",
                    "hdr": True,
                    "hdr_format": "HDR10",
                    "pix_fmt": "yuv420p10le",
                }
            ]
        }
        summary = MediaInspector.get_source_summary(media_data)
        self.assertIn("AOMedia AV2 (Next-Gen)", summary)
        self.assertIn("4K", summary)
        self.assertIn("@60fps", summary)
        self.assertIn("(10-bit HDR10)", summary)

    def test_av2_file_extensions_in_dialog(self):
        """Ensure .av2 and .obu (Open Bitstream Unit) are registered in open dialog filters."""
        win = MainWindow()
        try:
            # Check open file method exists and contains av2/obu
            import inspect
            src = inspect.getsource(win.action_open_file)
            self.assertIn("*.av2", src)
            self.assertIn("*.obu", src)
        finally:
            win.close()

    def test_dav2d_engine_status_and_discovery(self):
        """Verify Dav2dEngine exposes valid diagnostics and discovery mechanism."""
        from core.dav2d_engine import Dav2dEngine
        engine = Dav2dEngine.get_instance()
        status = engine.get_status_info()
        self.assertIn("available", status)
        self.assertIn("backend", status)
        self.assertIn("code.videolan.org/videolan/dav2d", status["repo_url"])
        self.assertIn(status["backend"], ("dll", "cli", "none"))

    def test_dav2d_mock_dll_binding(self):
        """Verify Dav2dEngine binds C API symbols properly when mock libdav2d is present."""
        from core.dav2d_engine import Dav2dEngine
        from unittest.mock import MagicMock
        import ctypes

        engine = Dav2dEngine()
        mock_lib = MagicMock()
        mock_lib.dav2d_version.return_value = b"dav2d 0.2.0-git"
        with patch("ctypes.CDLL", return_value=mock_lib):
            engine._load_dll("fake_dav2d.dll")
            self.assertTrue(engine.is_available())
            self.assertEqual(engine.get_backend_type(), "dll")
            self.assertEqual(engine.get_version(), "dav2d 0.2.0-git")

    def test_mainwindow_codec_display_with_dav2d(self):
        """Verify MainWindow formats source codec label with dav2d engine info for AV2."""
        win = MainWindow()
        try:
            win._update_source_codec_display("AOMedia AV2 (Next-Gen) 4K @60fps (10-bit HDR10)")
            self.assertIn("AV2", win.current_source_codec_str)
            self.assertIn("dav2d", win.current_source_codec_str)
        finally:
            win.close()


class TestMinimalistTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_qss_retrieval(self):
        """Verify theme stylesheet loading and defaults."""
        minimalist_qss = get_theme_qss("minimalist")
        self.assertEqual(minimalist_qss, MINIMALIST_THEME_QSS)
        self.assertIn("#0d0e12", minimalist_qss)
        self.assertIn("QSlider::groove:horizontal", minimalist_qss)

        cyber_qss = get_theme_qss("cyberpunk")
        self.assertEqual(cyber_qss, CYBERPUNK_THEME_QSS)
        self.assertIn("#00d2ff", cyber_qss)

    def test_mainwindow_default_and_switching(self):
        """Verify MainWindow defaults to Minimalist theme and can switch dynamically."""
        win = MainWindow()
        try:
            # Default theme must be minimalist
            self.assertEqual(win.current_theme, "minimalist")
            self.assertTrue(hasattr(win, "act_theme_minimalist"))
            self.assertTrue(win.act_theme_minimalist.isChecked())
            self.assertFalse(win.act_theme_cyberpunk.isChecked())

            # Switch to Cyberpunk
            win.set_theme("cyberpunk")
            self.assertEqual(win.current_theme, "cyberpunk")
            self.assertFalse(win.act_theme_minimalist.isChecked())
            self.assertTrue(win.act_theme_cyberpunk.isChecked())

            # Switch back to Minimalist
            win.set_theme("minimalist")
            self.assertEqual(win.current_theme, "minimalist")
            self.assertTrue(win.act_theme_minimalist.isChecked())
            self.assertFalse(win.act_theme_cyberpunk.isChecked())
        finally:
            win.close()

    def test_osc_minimalist_elements(self):
        """Verify OSC controls use refined minimalist styling without electric cyan borders."""
        win = MainWindow()
        try:
            play_btn_qss = win.osc.btn_play.styleSheet()
            # Must NOT have 2px neon cyan border
            self.assertNotIn("2px solid #00d2ff", play_btn_qss)
            self.assertIn("border-radius: 8px", play_btn_qss)

            codec_badge_qss = win.osc.lbl_codec_badge.styleSheet()
            # Badges should use clean semi-transparent background and subtle borders
            self.assertIn("rgba(255, 255, 255, 0.05)", codec_badge_qss)
            self.assertNotIn("#0284c7", codec_badge_qss)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
