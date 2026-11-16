"""
Unit tests for Hardware GPU Detection Engine in BOOB Player.
"""

import unittest
from core.gpu_detector import GPUDetector, GPUInfo


class TestGPUDetector(unittest.TestCase):
    def test_01_get_info_structure(self):
        info = GPUDetector.get_info()
        self.assertIsInstance(info, GPUInfo)
        self.assertTrue(len(info.name) > 0, "GPU name should not be empty")
        self.assertTrue(len(info.short_name) > 0, "GPU short name should not be empty")
        self.assertIn(info.vendor, ["NVIDIA", "AMD", "Intel", "Generic"])
        self.assertIsInstance(info.has_cuda, bool)
        self.assertIsInstance(info.has_nvjpeg2k, bool)
        self.assertIsInstance(info.is_nvidia, bool)
        self.assertIsInstance(info.is_amd, bool)
        self.assertIsInstance(info.is_intel, bool)

    def test_02_detect_all_gpus(self):
        all_gpus = GPUDetector.detect_all_gpus()
        self.assertIsInstance(all_gpus, list)
        for g in all_gpus:
            self.assertIsInstance(g, GPUInfo)
            self.assertTrue(len(g.name) > 0)

    def test_03_format_short_gpu_name_nvidia(self):
        cases = [
            ("NVIDIA GeForce RTX 4090", "RTX 4090"),
            ("NVIDIA GeForce RTX 4080 Laptop GPU", "RTX 4080"),
            ("NVIDIA GeForce RTX 3070 Ti", "RTX 3070 Ti"),
            ("NVIDIA GeForce RTX 2060 SUPER", "RTX 2060 SUPER"),
            ("NVIDIA GeForce GTX 1660 Ti", "GTX 1660 Ti"),
            ("NVIDIA GeForce GTX 1080", "GTX 1080"),
            ("NVIDIA RTX A5000", "RTX A5000"),
            ("NVIDIA Quadro P5000", "Quadro P5000"),
        ]
        for raw, expected in cases:
            self.assertEqual(GPUDetector.format_short_gpu_name(raw), expected, f"Failed for {raw}")

    def test_04_format_short_gpu_name_amd(self):
        cases = [
            ("AMD Radeon RX 7900 XTX", "RX 7900 XTX"),
            ("AMD Radeon RX 6800 XT", "RX 6800 XT"),
            ("AMD Radeon RX 7600", "RX 7600"),
            ("AMD Radeon RX 7900 GRE", "RX 7900 GRE"),
        ]
        for raw, expected in cases:
            self.assertEqual(GPUDetector.format_short_gpu_name(raw), expected, f"Failed for {raw}")

    def test_05_format_short_gpu_name_intel(self):
        cases = [
            ("Intel(R) Arc(TM) A770 Graphics", "Arc A770"),
            ("Intel(R) Arc(TM) A380 Graphics", "Arc A380"),
            ("Intel(R) Iris(R) Xe Graphics", "Iris Xe"),
        ]
        for raw, expected in cases:
            self.assertEqual(GPUDetector.format_short_gpu_name(raw), expected, f"Failed for {raw}")

    def test_06_format_short_gpu_name_fallbacks(self):
        self.assertEqual(GPUDetector.format_short_gpu_name("Hardware GPU"), "GPU")
        self.assertEqual(GPUDetector.format_short_gpu_name(""), "GPU")
        self.assertEqual(GPUDetector.format_short_gpu_name(None), "GPU")

    def test_07_main_window_integration(self):
        from PyQt6.QtWidgets import QApplication
        from ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        win = MainWindow()
        try:
            info = GPUDetector.get_info()
            # Verify status bar uses detected GPU name, not hardcoded 5050
            self.assertIn(info.short_name, win.lbl_status_hw.text())
            # Verify menu action uses detected GPU name
            self.assertIn(info.short_name, win.dcp_q_actions[0].text())
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
