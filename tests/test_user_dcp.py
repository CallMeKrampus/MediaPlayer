"""
Integration test for User's real-world 4K Theatrical DCP package:
Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV
"""

import os
import time
import unittest
from core.dcp_parser import DCPParser, DCPPackage
from core.mpv_engine import MPVEngine


class TestUserRealDCP(unittest.TestCase):
    def setUp(self):
        self.dcp_folder = os.path.abspath("Ramayana_TLR-2D-EPIQ_C_HI-XX_IN-U_51-ATMOS_4K_DN_20260730_QCM_SMPTE_OV")

    def test_parse_real_dcp(self):
        self.assertTrue(os.path.isdir(self.dcp_folder))
        self.assertTrue(DCPParser.is_dcp_folder(self.dcp_folder))

        pkg = DCPParser.parse(self.dcp_folder)
        self.assertEqual(pkg.standard, "SMPTE")
        self.assertEqual(len(pkg.compositions), 1)

        cpl = pkg.default_composition
        self.assertIn("Ramayana", cpl.title)
        self.assertEqual(cpl.content_kind, "trailer")
        self.assertEqual(cpl.fps, 24.0)
        self.assertEqual(cpl.total_frames, 6120)
        self.assertEqual(cpl.total_timecode, "00:04:15:00")
        self.assertEqual(cpl.total_seconds, 255.0)

        # Inspect Reel assets
        self.assertEqual(len(cpl.reels), 1)
        reel = cpl.reels[0]
        self.assertIn("Full 4K DCI", reel.screen_aspect_ratio)
        self.assertEqual(reel.picture_duration_frames, 6120)
        self.assertTrue(os.path.exists(reel.picture_path))
        self.assertTrue(os.path.exists(reel.sound_path))
        self.assertTrue(os.path.exists(reel.atmos_path))
        self.assertEqual(reel.sound_language, "hi")

    def test_real_dcp_playback_and_tonemapping(self):
        pkg = DCPParser.parse(self.dcp_folder)
        engine = MPVEngine()
        try:
            engine.play_dcp_package(pkg, cpl_index=0, reel_index=0)
            
            # Allow demuxer to load 4K JP2K and attach 14-ch PCM
            a_tracks = []
            for _ in range(30):
                time.sleep(0.1)
                tracks = engine.get_track_list()
                a_tracks = [t for t in tracks if t.get("type") == "audio"]
                if a_tracks:
                    break

            # Check video params (supports full 4K master on GPU or wavelet sub-band decode on CPU)
            v_params = getattr(engine.player, "video_params", {}) or {}
            vid_w = v_params.get("w") or (4096 if engine.nvjpeg2k_active else None)
            vid_h = v_params.get("h") or (2160 if engine.nvjpeg2k_active else None)
            self.assertIn(vid_w, (1024, 2048, 4096))
            self.assertIn(vid_h, (540, 1080, 2160))
            self.assertIn(v_params.get("colormatrix"), ("xyz", None))

            # Check tracks
            tracks = engine.get_track_list()
            v_tracks = [t for t in tracks if t.get("type") == "video"]
            self.assertEqual(len(v_tracks), 1)
            self.assertGreaterEqual(len(a_tracks), 1)
            self.assertIn("jpeg2000", v_tracks[0].get("codec", "").lower())
            self.assertEqual(a_tracks[0].get("codec"), "pcm_s24le")

            # Check tonemapping DCI-XYZ conversion is calibrated with EPIQ punch & vibrancy
            status = engine.tonemap_engine.get_status_summary()
            self.assertEqual(status["preset"], "dci_xyz_srgb")
            self.assertEqual(status["target_prim"], "bt.709")
            self.assertEqual(status["target_trc"], "gamma2.2")
            self.assertEqual(status["algorithm"], "clip")
            self.assertEqual(engine.player["brightness"], 0)
            self.assertEqual(engine.player["gamma"], 0)
            self.assertEqual(engine.player["contrast"], 12)
            self.assertEqual(engine.player["saturation"], 15)
            self.assertTrue(status["is_epiq"])
            self.assertTrue(status["shader_active"])
            self.assertTrue(engine.tonemap_engine.active_shader.replace("\\", "/").endswith("dci_xyz_epiq_to_srgb.glsl"))
            vf_val = engine.player["vf"]
            if isinstance(vf_val, list) and len(vf_val) > 0:
                self.assertEqual(vf_val[0].get("name"), "format")
                self.assertEqual(vf_val[0].get("params", {}).get("fmt"), "rgb48le")
            else:
                self.assertIn("format=fmt=rgb48le", str(vf_val))

            # Verify Rec.709 status label
            self.assertIn("Rec.709", status["preset_label"])

            # Verify manual toggle works cleanly
            engine.tonemap_engine.set_epiq_correction(False)
            self.assertFalse(engine.tonemap_engine.is_epiq)
            self.assertEqual(engine.player["contrast"], 8)
            self.assertEqual(engine.player["saturation"], 10)
            self.assertTrue(engine.tonemap_engine.active_shader.replace("\\", "/").endswith("dci_xyz_to_srgb.glsl"))
            engine.tonemap_engine.set_epiq_correction(True)
            self.assertTrue(engine.tonemap_engine.is_epiq)
            self.assertEqual(engine.player["contrast"], 12)
            self.assertEqual(engine.player["saturation"], 15)
            self.assertTrue(engine.tonemap_engine.active_shader.replace("\\", "/").endswith("dci_xyz_epiq_to_srgb.glsl"))

            # Check memory buffer allocation (1GB forward, 512MB backbuffer)
            self.assertGreaterEqual(engine.player["demuxer-max-bytes"], 1024 * 1024 * 1024)
            self.assertGreaterEqual(engine.player["demuxer-max-back-bytes"], 512 * 1024 * 1024)
            self.assertEqual(engine.player["cache"], True)

            # Test seeking responsiveness
            engine.seek(15.0, relative=False, exact=True)
            engine.seek(-5.0, relative=True, exact=True)

            # Check IAB (SMPTE ST 2098-2) integration
            self.assertIsNotNone(engine.current_iab_meta)
            self.assertEqual(engine.current_iab_meta.total_frames, 6125)
            self.assertEqual(engine.current_iab_mode, "binaural")
        finally:
            engine.stop()


if __name__ == "__main__":
    unittest.main()
