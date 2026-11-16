import unittest
import os
from core.nvjpeg2k_engine import NVJPEG2KEngine


class TestNVJPEG2KEngine(unittest.TestCase):
    def setUp(self):
        self.engine = NVJPEG2KEngine.get_instance()
        self.mxf_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV",
            "Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-jp2k.mxf",
        )

    def test_01_availability_and_initialization(self):
        self.assertTrue(NVJPEG2KEngine.is_available())
        ok = self.engine.initialize()
        self.assertTrue(ok)
        self.assertTrue(any(k in self.engine.gpu_name.lower() for k in ["nvidia", "geforce", "rtx", "gtx", "quadro", "tesla", "titan"]))
        print(f"\n[Test] GPU Detected: {self.engine.gpu_name}")

    def test_02_decode_4k_frame(self):
        if not os.path.exists(self.mxf_path):
            self.skipTest("MXF file not present")

        x, y, z = self.engine.decode_mxf_frame(self.mxf_path, frame_index=0)
        self.assertEqual(x.shape, (2160, 4096))
        self.assertEqual(y.shape, (2160, 4096))
        self.assertEqual(z.shape, (2160, 4096))
        self.assertGreater(x.max(), 1000)
        print(f"[Test] Decoded 4K Frame shape: {x.shape}, Max 12-bit values: X={x.max()}, Y={y.max()}, Z={z.max()}")

    def test_03_benchmark_performance(self):
        if not os.path.exists(self.mxf_path):
            self.skipTest("MXF file not present")

        res = self.engine.benchmark_mxf(self.mxf_path, num_frames=12)
        print(f"[Test] Benchmark Results: {res}")
        self.assertGreater(res["fps"], 30.0)


if __name__ == "__main__":
    unittest.main()
