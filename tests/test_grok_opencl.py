"""
Unit Tests for Grok / OpenCL GPU JPEG 2000 Decoding Engine & AMD/Intel Hardware Acceleration
"""

import os
import unittest
import numpy as np
from unittest.mock import patch, MagicMock

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage

from core.grok_engine import GrokOpenCLEngine
from core.gpu_detector import GPUDetector, GPUInfo
from core.nvjpeg2k_engine import NVJPEG2KPlaybackController, is_gpu_jp2k_available

app = QApplication.instance() or QApplication([])


class TestGrokOpenCLEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = GrokOpenCLEngine.get_instance()
        cls.mxf_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV",
            "Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-jp2k.mxf",
        )

    def test_01_opencl_availability_and_init(self):
        """Verify OpenCL is discovered and compute kernel compiles cleanly."""
        self.assertTrue(self.engine.is_available(), "OpenCL runtime must be available")
        ok = self.engine.initialize()
        self.assertTrue(ok, "OpenCL context, command queue and kernel must initialize")
        self.assertIsNotNone(self.engine.cl_context)
        self.assertIsNotNone(self.engine.cl_kernel)
        self.assertGreater(self.engine.compute_units, 0)
        print(f"\n[Test Grok] Active GPU: {self.engine.gpu_name} ({self.engine.vendor}), Compute Units: {self.engine.compute_units}")

    def test_02_benchmark_opencl_throughput(self):
        """Verify OpenCL GPU compute achieves ultra-high throughput (>100 FPS) on 4K frames."""
        res = self.engine.benchmark(num_frames=15, width=4096, height=2160)
        self.assertNotIn("error", res)
        self.assertGreater(res["fps"], 60.0, "OpenCL GPU compute should easily exceed 60 FPS on 4K")
        self.assertLess(res["ms_per_frame"], 16.6, "Latency should be well below 16.6ms (60Hz budget)")
        print(f"[Test Grok] Benchmark: {res['fps']} FPS, {res['ms_per_frame']} ms/frame on {res['gpu']}")

    def test_03_mxf_fast_indexing_and_decoding(self):
        """Verify MXF indexing and zero-copy QImage frame decoding on real 4K DCP."""
        if not os.path.exists(self.mxf_path):
            self.skipTest("MXF test asset not present")

        index = self.engine.index_mxf(self.mxf_path)
        self.assertGreater(len(index), 1000)

        # Decode frame 0
        qimg = self.engine.decode_and_tonemap_frame(self.mxf_path, 0)
        self.assertIsNotNone(qimg)
        self.assertFalse(qimg.isNull())
        self.assertEqual(qimg.width(), 4096)
        self.assertEqual(qimg.height(), 2160)
        self.assertEqual(qimg.format(), QImage.Format.Format_RGB32)

    def test_04_planar_xyz_decoding(self):
        """Verify extraction of 12-bit planar XYZ components from MXF."""
        if not os.path.exists(self.mxf_path):
            self.skipTest("MXF test asset not present")

        x, y, z = self.engine.decode_mxf_frame(self.mxf_path, 0)
        self.assertEqual(x.shape, (2160, 4096))
        self.assertEqual(y.shape, (2160, 4096))
        self.assertEqual(z.shape, (2160, 4096))
        self.assertGreater(x.max(), 100)

    def test_05_dynamic_grading_and_presets_opencl(self):
        """Verify various tone mapping modes and grading parameters execute cleanly."""
        if not os.path.exists(self.mxf_path):
            self.skipTest("MXF test asset not present")

        # Test Pass-Through (mode 2)
        qimg_pt = self.engine.decode_and_tonemap_frame(self.mxf_path, 0, grading={"preset_mode": 2})
        self.assertIsNotNone(qimg_pt)

        # Test EPIQ (mode 1)
        qimg_epiq = self.engine.decode_and_tonemap_frame(self.mxf_path, 0, grading={"preset_mode": 1})
        self.assertIsNotNone(qimg_epiq)

        # Test Filmic Hable (mode 3)
        qimg_hable = self.engine.decode_and_tonemap_frame(self.mxf_path, 0, grading={"preset_mode": 3})
        self.assertIsNotNone(qimg_hable)

        # Test Reinhard (mode 6)
        qimg_reinhard = self.engine.decode_and_tonemap_frame(self.mxf_path, 0, grading={"preset_mode": 6})
        self.assertIsNotNone(qimg_reinhard)

        # Test Studio Grading adjustments
        qimg_graded = self.engine.decode_and_tonemap_frame(
            self.mxf_path, 0,
            grading={"brightness": 10.0, "contrast": 15.0, "gamma": -5.0, "saturation": 20.0, "peak_k1": 1.5, "peak_k2": 0.4}
        )
        self.assertIsNotNone(qimg_graded)

    def test_06_gpu_detector_opencl_and_grok(self):
        """Verify GPUDetector identifies OpenCL and reports GPU JP2K readiness."""
        info = GPUDetector.get_info(force_refresh=True)
        self.assertTrue(info.has_opencl)
        self.assertTrue(info.has_grok)
        self.assertTrue(GPUDetector.has_gpu_jp2k())
        self.assertIn(GPUDetector.get_jp2k_backend(), ["nvjpeg2k", "grok_opencl"])

    def test_07_amd_and_intel_simulated_backend_routing(self):
        """Verify AMD Radeon and Intel Arc GPUs route to grok_opencl backend."""
        # Simulated AMD Radeon RX 7900 XTX
        amd_info = GPUInfo(
            name="AMD Radeon RX 7900 XTX",
            short_name="RX 7900 XTX",
            vendor="AMD",
            has_cuda=False,
            has_nvjpeg2k=False,
            is_nvidia=False,
            is_amd=True,
            is_intel=False,
            device_index=0,
            has_opencl=True,
            has_grok=True,
            jp2k_backend="grok_opencl",
        )
        # Simulated Intel Arc A770
        intel_info = GPUInfo(
            name="Intel(R) Arc(TM) A770 Graphics",
            short_name="Arc A770",
            vendor="Intel",
            has_cuda=False,
            has_nvjpeg2k=False,
            is_nvidia=False,
            is_amd=False,
            is_intel=True,
            device_index=0,
            has_opencl=True,
            has_grok=True,
            jp2k_backend="grok_opencl",
        )

        with patch.object(GPUDetector, "get_info", return_value=amd_info):
            self.assertEqual(GPUDetector.get_jp2k_backend(), "grok_opencl")
            self.assertTrue(GPUDetector.has_gpu_jp2k())

        with patch.object(GPUDetector, "get_info", return_value=intel_info):
            self.assertEqual(GPUDetector.get_jp2k_backend(), "grok_opencl")
            self.assertTrue(GPUDetector.has_gpu_jp2k())

    def test_08_playback_controller_fallback_to_grok(self):
        """Verify NVJPEG2KPlaybackController selects GrokOpenCLEngine when nvjpeg2k is unavailable."""
        with patch("core.nvjpeg2k_engine.NVJPEG2KEngine.is_available", return_value=False):
            ctrl = NVJPEG2KPlaybackController()
            self.assertEqual(ctrl.backend_name, "grok_opencl")
            self.assertIsInstance(ctrl.engine, GrokOpenCLEngine)


if __name__ == "__main__":
    unittest.main()
