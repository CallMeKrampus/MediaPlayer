"""
End-to-end integration tests for BOOB Player.
Tests playback of JP2K, ProRes, VP9, DCP package synchronization,
external audio/subtitles, and color tonemapping.
"""

import os
import time
import unittest
from core.mpv_engine import MPVEngine
from core.dcp_parser import DCPParser
from core.media_inspector import MediaInspector


class TestPlayerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = MPVEngine()
        cls.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.assets_dir = os.path.join(cls.base_dir, "assets")
        cls.dcp_dir = os.path.join(cls.assets_dir, "sample_dcp")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.engine.stop()
        except Exception:
            pass

    def test_01_play_prores(self):
        prores_p = os.path.join(self.assets_dir, "sample_prores422.mov")
        self.assertTrue(os.path.exists(prores_p))
        self.engine.play(prores_p)
        time.sleep(0.6)
        dur = getattr(self.engine.player, "duration", 0)
        self.assertGreater(dur, 1.0)
        
        # Test inspector
        info = MediaInspector.inspect_file(prores_p)
        self.assertEqual(len(info["video_tracks"]), 1)
        self.assertIn("prores", info["video_tracks"][0]["codec_name"].lower())

    def test_02_play_vp9(self):
        vp9_p = os.path.join(self.assets_dir, "sample_vp9.webm")
        self.assertTrue(os.path.exists(vp9_p))
        self.engine.play(vp9_p)
        time.sleep(0.6)
        dur = getattr(self.engine.player, "duration", 0)
        self.assertGreater(dur, 1.0)

        info = MediaInspector.inspect_file(vp9_p)
        self.assertEqual(len(info["video_tracks"]), 1)
        self.assertIn("vp9", info["video_tracks"][0]["codec_name"].lower())

    def test_03_external_audio_and_subtitles(self):
        prores_p = os.path.join(self.assets_dir, "sample_prores422.mov")
        self.engine.play(prores_p)
        time.sleep(0.5)

        # Attach external audio
        wav_p = os.path.join(self.assets_dir, "sample_external_audio.wav")
        self.assertTrue(os.path.exists(wav_p))
        self.engine.add_external_audio(wav_p, select=True)
        time.sleep(0.3)

        # Attach external subtitle
        srt_p = os.path.join(self.assets_dir, "sample_external_subtitles.srt")
        self.assertTrue(os.path.exists(srt_p))
        self.engine.add_external_subtitle(srt_p, select=True)
        time.sleep(0.3)

        tracks = self.engine.get_track_list()
        audio_ext = [t for t in tracks if t.get("type") == "audio" and t.get("external")]
        sub_ext = [t for t in tracks if t.get("type") == "sub" and t.get("external")]
        self.assertGreaterEqual(len(audio_ext), 1)
        self.assertGreaterEqual(len(sub_ext), 1)

        # Test sync adjustments
        self.engine.set_audio_delay(0.150)
        self.engine.set_sub_delay(-0.250)
        self.assertAlmostEqual(self.engine.player["audio-delay"], 0.150, places=2)
        self.assertAlmostEqual(self.engine.player["sub-delay"], -0.250, places=2)

    def test_04_play_dcp_cinema_package_with_sync_and_xyz(self):
        self.assertTrue(DCPParser.is_dcp_folder(self.dcp_dir))
        pkg = DCPParser.parse(self.dcp_dir)
        self.assertEqual(pkg.default_composition.title, "BOOB_CINEMA_SMPTE_2K_24P_51")
        
        # Start synchronized DCP playback
        self.engine.play_dcp_package(pkg, cpl_index=0, reel_index=0)
        time.sleep(0.8)

        # Verify picture is playing
        dur = getattr(self.engine.player, "duration", 0)
        self.assertGreater(dur, 1.0)

        # Verify audio track was bound
        tracks = self.engine.get_track_list()
        audio_tracks = [t for t in tracks if t.get("type") == "audio"]
        self.assertGreaterEqual(len(audio_tracks), 1)

        # Verify DCI-XYZ color conversion is active with cinematic punch
        status = self.engine.tonemap_engine.get_status_summary()
        self.assertEqual(status["preset"], "dci_xyz_srgb")
        self.assertEqual(status["target_prim"], "bt.709")
        self.assertEqual(status["target_trc"], "gamma2.2")
        self.assertEqual(status["algorithm"], "clip")
        self.assertTrue(status["shader_active"])

        # Verify high performance memory buffers and seeking
        self.assertGreaterEqual(self.engine.player["demuxer-max-bytes"], 1024 * 1024 * 1024)
        self.assertGreaterEqual(self.engine.player["demuxer-max-back-bytes"], 512 * 1024 * 1024)
        self.assertEqual(self.engine.player["cache"], True)
        self.assertEqual(self.engine.player["hr-seek"], True)
        self.engine.seek(1.0, relative=True)

    def test_05_tonemapping_presets(self):
        # Test Dolby Vision Profile 5 mode
        self.engine.tonemap_engine.apply_preset("dv_p5_sdr")
        self.assertEqual(self.engine.player["tone-mapping"], "spline")
        self.assertEqual(self.engine.player["target-prim"], "bt.709")
        self.assertEqual(self.engine.player["target-trc"], "gamma2.2")
        self.assertIn(self.engine.player["hdr-compute-peak"], ("yes", True))

        # Test DV Profile 5 to HDR10
        self.engine.tonemap_engine.apply_preset("dv_p5_hdr10")
        self.assertEqual(self.engine.player["target-prim"], "bt.2020")
        self.assertEqual(self.engine.player["target-trc"], "pq")

        # Test HDR10 mode
        self.engine.tonemap_engine.apply_preset("hdr10_sdr")
        self.assertEqual(self.engine.player["target-peak"], 100)

        # Test Filmic Hable
        self.engine.tonemap_engine.apply_preset("filmic_hable")
        self.assertEqual(self.engine.player["tone-mapping"], "hable")


if __name__ == "__main__":
    unittest.main()
