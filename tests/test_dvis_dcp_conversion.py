"""
Unit Tests for Dolby Vision DCP (DVis / EDR 108 nits XYZ-PQ) Detection and Conversion Suite.
Tests DCP parsing on SSRajamouliVar, color matrix transforms, and DVisConverterDialog.
"""

import os
import unittest
import numpy as np
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from core.dcp_parser import DCPParser, DCPComposition, DCPPackage
from core.dvis_converter import (
    XYZ_TO_2020, XYZ_TO_709,
    pq_eotf, pq_oetf, sdr_bt1886_oetf, tonemap_sdr_luma_preserve,
    DVisConversionConfig, DVisConversionWorker
)
from core.tonemap_engine import TonemapEngine
from ui.dvis_converter_dialog import DVisConverterDialog
from ui.dcp_dialog import DCPInspectorDialog
from ui.tonemap_dialog import TonemapControlDrawer
from core.nvjpeg2k_engine import NVJPEG2KEngine

app = QApplication.instance() or QApplication([])


class DummyPlayer:
    def __init__(self):
        self.options = {}
    def __setitem__(self, key, val):
        self.options[key] = val
    def __getitem__(self, key):
        return self.options.get(key)


class TestDVisDCPConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cls.dvis_folder = os.path.join(cls.repo_root, "SSRajamouliVAR")

    def test_01_ssrajamoulivar_cpl_detection(self):
        """Verify DCPParser detects SSRajamouliVar as a genuine Dolby Vision / EDR 108-nit DCP."""
        self.assertTrue(os.path.isdir(self.dvis_folder), f"SSRajamouliVAR folder must exist at {self.dvis_folder}")
        pkg = DCPParser.parse(self.dvis_folder)
        self.assertIsNotNone(pkg.default_composition)
        cpl = pkg.default_composition

        self.assertTrue(cpl.is_dolby_vision, "SSRajamouliVar must be flagged as Dolby Vision / EDR")
        self.assertEqual(cpl.target_luminance, 108, "Target luminance must be 108 nits for Dolby Cinema EDR")
        self.assertEqual(cpl.transfer_function, "PQ10K", "Image transfer function must be PQ10K")
        self.assertGreater(len(cpl.reels), 0)

        reel0 = cpl.reels[0]
        self.assertTrue(reel0.is_dolby_vision)
        self.assertTrue(os.path.isfile(reel0.picture_path), "Picture MXF must resolve to a valid file")
        self.assertTrue(os.path.isfile(reel0.sound_path), "Sound MXF must resolve to a valid file")

    def test_02_color_math_white_point_and_inversion(self):
        """Verify D65 white point transforms and PQ EOTF/OETF roundtrip accuracy."""
        # D65 standard reference white (normalized Y=1.0)
        # In CIE 1931: X = 0.95047, Y = 1.00000, Z = 1.08883
        xyz_d65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)

        # 1. Test D65 -> BT.709: Should map cleanly to [1.0, 1.0, 1.0]
        rgb709 = xyz_d65 @ XYZ_TO_709.T
        np.testing.assert_allclose(rgb709, [1.0, 1.0, 1.0], atol=1e-3)

        # 2. Test D65 -> BT.2020: Should map cleanly to [1.0, 1.0, 1.0]
        rgb2020 = xyz_d65 @ XYZ_TO_2020.T
        np.testing.assert_allclose(rgb2020, [1.0, 1.0, 1.0], atol=1e-3)

        # 3. Test PQ roundtrip: nits -> PQ -> nits
        test_nits = np.array([0.005, 1.0, 18.0, 100.0, 108.0, 600.0, 1000.0], dtype=np.float32)
        encoded_pq = pq_oetf(test_nits)
        decoded_nits = pq_eotf(encoded_pq)
        np.testing.assert_allclose(decoded_nits, test_nits, rtol=1e-4)

    def test_03_sdr_highlight_knee_preservation(self):
        """Verify tonemap_sdr_luma_preserve preserves hue and caps highlights at 100 nits."""
        # Frame with specular highlight at 120 nits
        rgb = np.full((10, 10, 3), 120.0, dtype=np.float32)
        mapped = tonemap_sdr_luma_preserve(rgb, knee=70.0, peak=100.0)

        # Highlights must be rolled off below 100 nits
        self.assertLessEqual(mapped.max(), 100.0)
        self.assertGreater(mapped.min(), 70.0)

        # Color channels must remain identical (no hue shift)
        self.assertTrue(np.allclose(mapped[..., 0], mapped[..., 1]))
        self.assertTrue(np.allclose(mapped[..., 1], mapped[..., 2]))

    def test_04_tonemap_engine_dvis_presets(self):
        """Verify TonemapEngine registers and applies dvis_dcp_hdr10 and dvis_dcp_sdr."""
        engine = TonemapEngine(DummyPlayer())
        self.assertIn("dvis_dcp_hdr10", engine.PRESETS)
        self.assertIn("dvis_dcp_sdr", engine.PRESETS)

        # Apply HDR10 preset
        engine.apply_preset("dvis_dcp_hdr10")
        self.assertEqual(engine.target_prim, "bt.2020")
        self.assertEqual(engine.target_trc, "pq")
        self.assertEqual(engine.target_peak, 1000)

        # Apply SDR preset
        engine.apply_preset("dvis_dcp_sdr")
        self.assertEqual(engine.target_prim, "bt.709")
        self.assertEqual(engine.target_peak, 100)

        # Test command generator
        cmd = TonemapEngine.get_dvis_conversion_command(
            input_picture_mxf="fake_video.mxf",
            output_path="test_out.mp4",
            target_mode="hdr10",
            frames=10
        )
        self.assertIn("test_out.mp4", cmd)
        self.assertIn("-color_primaries", cmd)
        self.assertIn("bt2020", cmd)

    def test_05_color_science_page_presets(self):
        """Verify Color Science page (TonemapControlDrawer) defines and activates DVis DCP presets in real time."""
        engine = TonemapEngine(DummyPlayer())
        drawer = TonemapControlDrawer(engine)
        try:
            self.assertIn("dvis_dcp_sdr", drawer.preset_buttons)
            self.assertIn("dvis_dcp_hdr10", drawer.preset_buttons)
            self.assertEqual(drawer.preset_buttons["dvis_dcp_sdr"].text(), "💎 DVis (DCP) → SDR")
            self.assertEqual(drawer.preset_buttons["dvis_dcp_hdr10"].text(), "💎 DVis (DCP) → HDR10")

            # Click DVis SDR preset in real time
            drawer.preset_buttons["dvis_dcp_sdr"].click()
            self.assertEqual(engine.current_preset, "dvis_dcp_sdr")
            self.assertEqual(engine.target_prim, "bt.709")
            self.assertIsNotNone(engine.active_shader)
            self.assertTrue(engine.active_shader.endswith("dvis_dcp_to_sdr.glsl"))

            # Click DVis HDR10 preset in real time
            drawer.preset_buttons["dvis_dcp_hdr10"].click()
            self.assertEqual(engine.current_preset, "dvis_dcp_hdr10")
            self.assertEqual(engine.target_prim, "bt.2020")
            self.assertEqual(engine.target_trc, "pq")
            self.assertIsNotNone(engine.active_shader)
            self.assertTrue(engine.active_shader.endswith("dvis_dcp_to_hdr10.glsl"))
        finally:
            drawer.close()

    def test_06_dvis_realtime_gpu_pipeline(self):
        """Verify NVJPEG2KEngine GPU pipeline applies real-time DVis SDR and HDR10 tonemapping modes."""
        eng = NVJPEG2KEngine.get_instance()
        if eng.initialize():
            mxf = os.path.join(
                self.dvis_folder,
                "SSRajamouliVaranasi_TSR-V4_TE-XX_4K-DOM_S-DVis_SMPTEB21_20260203_video.mxf"
            )
            if os.path.exists(mxf):
                # Test real-time SDR decode mode 7
                qimg_sdr = eng.decode_and_tonemap_frame(mxf, 15, {"preset_mode": 7})
                self.assertIsNotNone(qimg_sdr)
                self.assertEqual(qimg_sdr.width(), 4096)
                self.assertEqual(qimg_sdr.height(), 1716)

                # Test real-time HDR10 decode mode 8
                qimg_hdr = eng.decode_and_tonemap_frame(mxf, 15, {"preset_mode": 8})
                self.assertIsNotNone(qimg_hdr)
                self.assertEqual(qimg_hdr.width(), 4096)
                self.assertEqual(qimg_hdr.height(), 1716)

    def test_07_dcp_inspector_displays_edr_tag(self):
        """Verify DCPInspectorDialog displays EDR 108 nits tag without offline conversion prompts."""
        pkg = DCPParser.parse(self.dvis_folder)
        dlg = DCPInspectorDialog(pkg)
        try:
            self.assertIn("108 nits XYZ-PQ", dlg.lbl_meta.text())
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
