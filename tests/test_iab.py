"""
Unit and integration tests for SMPTE ST 2098-2 Immersive Audio Bitstream (IAB) Engine.
"""

import os
import unittest
from core.iab_engine import IABEngine, IABTrackMetadata, IABSpatialObject


class TestIABEngine(unittest.TestCase):
    def setUp(self):
        self.atmos_mxf = os.path.abspath(
            r"Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV\Ramayana_TLR-2D_HI_EPQ_QCM_4K-reel-1-dolbyatmos.mxf"
        )

    def test_01_is_iab_file(self):
        self.assertTrue(os.path.exists(self.atmos_mxf))
        self.assertTrue(IABEngine.is_iab_file(self.atmos_mxf))

        # Non-IAB file check
        fake_path = os.path.abspath("README.md")
        self.assertFalse(IABEngine.is_iab_file(fake_path))

    def test_02_parse_iab_track(self):
        meta = IABEngine.parse_track(self.atmos_mxf, max_frames_to_index=150)
        self.assertIsNotNone(meta)
        self.assertIsInstance(meta, IABTrackMetadata)
        self.assertEqual(meta.total_frames, 6125)
        self.assertAlmostEqual(meta.duration_seconds, 255.208, places=2)
        self.assertGreater(meta.file_size_mb, 200.0)
        self.assertGreater(meta.avg_bitrate_kbps, 5000.0)
        self.assertEqual(meta.sample_rate, 48000)
        self.assertEqual(meta.frame_rate, 24.0)
        self.assertEqual(meta.max_rendered_channels, 128)
        self.assertEqual(meta.max_audio_objects, 118)
        self.assertEqual(meta.bed_channel_count, 10)

        # Inspect indexed frames
        self.assertEqual(len(meta.frames), 150)
        frame0 = meta.frames[0]
        self.assertEqual(frame0.frame_index, 0)
        self.assertGreater(frame0.payload_size, 0)

    def test_03_spatial_objects_at_time(self):
        meta = IABEngine.parse_track(self.atmos_mxf, max_frames_to_index=50)
        objects = IABEngine.get_spatial_objects_at_time(meta, 1.0)
        self.assertIsInstance(objects, list)
        if objects:
            obj = objects[0]
            self.assertIsInstance(obj, IABSpatialObject)
            self.assertTrue(-1.0 <= obj.x <= 1.0)
            self.assertTrue(-1.0 <= obj.y <= 1.0)
            self.assertTrue(-1.0 <= obj.z <= 1.0)

    def test_04_audio_filters(self):
        binaural = IABEngine.get_binaural_3d_filter()
        self.assertIn("pan=stereo", binaural)

        c71 = IABEngine.get_cinema_71_downmix_filter()
        self.assertIn("pan=7.1", c71)

        c51 = IABEngine.get_cinema_51_downmix_filter()
        self.assertIn("pan=5.1", c51)

        stereo = IABEngine.get_stereo_dialog_focus_filter()
        self.assertIn("dynaudnorm", stereo)
        self.assertIn("pan=stereo", stereo)


if __name__ == "__main__":
    unittest.main()
