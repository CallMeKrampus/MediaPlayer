"""
Unit tests for Color Pipeline & Tonemapping Engine.
"""

import os
import unittest
from core.tonemap_engine import TonemapEngine


class DummyPlayer:
    def __init__(self):
        self.options = {}
        self.commands = []

    def __setitem__(self, key, val):
        self.options[key] = val

    def __getitem__(self, key):
        return self.options.get(key)

    def command(self, *args):
        self.commands.append(args)


class TestTonemapEngine(unittest.TestCase):
    def setUp(self):
        self.player = DummyPlayer()
        self.engine = TonemapEngine(self.player)

    def test_dv_profile5_preset(self):
        self.engine.apply_preset("dv_p5_sdr")
        self.assertEqual(self.player["tone-mapping"], "spline")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["target-peak"], 100)
        self.assertEqual(self.player["hdr-compute-peak"], "yes")
        self.assertEqual(self.player["gamut-mapping-mode"], "perceptual")
        self.assertEqual(self.player["contrast"], 8)
        self.assertEqual(self.player["saturation"], 10)
        self.assertIsNotNone(self.engine.active_shader)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("cinema_contrast_punch.glsl"))

    def test_dv_profile20_presets(self):
        # 1. Helper method test
        self.engine.enable_dv_profile20_mode(True, "sdr")
        self.assertEqual(self.engine.current_preset, "dv_p20_rpu_sdr")
        self.engine.enable_dv_profile20_mode(True, "hdr10")
        self.assertEqual(self.engine.current_preset, "dv_p20_rpu_hdr")
        self.engine.enable_dv_profile20_mode(False)
        self.assertEqual(self.engine.current_preset, "auto")

        # 2. Dynamic RPU L8 SDR Preset (100% native libplacebo, zero GLSL shaders)
        self.engine.apply_preset("dv_p20_rpu_sdr")
        self.assertEqual(self.player["tone-mapping"], "spline")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["target-peak"], 100)
        self.assertEqual(self.player["hdr-compute-peak"], "no")
        self.assertEqual(self.player["vo"], "gpu-next")
        self.assertIsNone(self.engine.active_shader)
        self.assertIsNotNone(self.engine.last_rpu_trims)
        self.assertTrue(self.engine.last_rpu_trims["has_l8"])

        # 3. Dynamic RPU HDR10 / HDR10+ Preset (100% native libplacebo, zero GLSL shaders)
        self.engine.apply_preset("dv_p20_rpu_hdr")
        self.assertEqual(self.player["tone-mapping"], "st2094-40")
        self.assertEqual(self.player["hdr-compute-peak"], "no")
        self.assertEqual(self.player["vo"], "gpu-next")
        self.assertIsNone(self.engine.active_shader)
        self.assertEqual(self.engine.last_rpu_trims["hdr_target_format"], "HDR10+")

        # 7. Verify static RPU (Level 1 only, no L8/L3/L2) selects HDR10 instead of HDR10+
        static_rpu = {
            "dovi_profile": 20,
            "vdr_dm_data": {
                "source_min_pq": 7,
                "source_max_pq": 1787,
                "cmv29_metadata": {"ext_metadata_blocks": [{"Level1": {"min_pq": 12, "max_pq": 2081, "avg_pq": 824}}]},
            },
        }
        parsed_static = TonemapEngine.parse_rpu_frame_dict(static_rpu)
        self.assertFalse(parsed_static["has_dynamic_trim"])
        self.assertEqual(parsed_static["hdr_target_format"], "HDR10")

    def test_hlg_sdr_punch_preset(self):
        # Dedicated HLG -> SDR preset with punchy filmic curve
        self.engine.apply_preset("hlg_sdr")
        self.assertEqual(self.player["tone-mapping"], "bt.2390")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["target-peak"], 100)
        self.assertEqual(self.player["hdr-compute-peak"], "yes")
        self.assertEqual(self.player["contrast"], 10)
        self.assertEqual(self.player["saturation"], 12)
        self.assertIsNotNone(self.engine.active_shader)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("cinema_contrast_punch.glsl"))
        self.assertEqual(self.engine.current_preset, "hlg_sdr")

    def test_is_display_hdr_detection(self):
        # Verify is_display_hdr returns boolean without crashing
        is_hdr = TonemapEngine.is_display_hdr()
        self.assertIsInstance(is_hdr, bool)

    def test_dv_p5_hdr10_and_hlg_presets(self):
        # Test DV P5 -> HDR10 (Rec.2020 PQ)
        self.engine.apply_preset("dv_p5_hdr10")
        self.assertEqual(self.player["tone-mapping"], "clip")
        self.assertEqual(self.player["target-prim"], "bt.2020")
        self.assertEqual(self.player["target-trc"], "pq")
        self.assertEqual(self.player["target-peak"], 1000)
        self.assertEqual(self.player["hdr-compute-peak"], "no")
        self.assertIsNone(self.engine.active_shader)

        # Test DV P5 -> HLG (SDR display -> Punchy HLG mode)
        self.engine.apply_preset("dv_p5_hlg")
        self.assertEqual(self.player["tone-mapping"], "bt.2390")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["contrast"], 10)
        self.assertEqual(self.player["saturation"], 12)
        self.assertIsNotNone(self.engine.active_shader)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("cinema_contrast_punch.glsl"))

    def test_libplacebo_knowledge_base_filters(self):
        f_hdr10 = TonemapEngine.get_libplacebo_filter("hdr10")
        self.assertIn("colorspace=9", f_hdr10)
        self.assertIn("color_primaries=9", f_hdr10)
        self.assertIn("color_trc=16", f_hdr10)
        self.assertIn("peak_detect=false", f_hdr10)

        f_sdr = TonemapEngine.get_libplacebo_filter("sdr")
        self.assertIn("colorspace=bt709", f_sdr)
        self.assertIn("color_primaries=bt709", f_sdr)
        self.assertIn("color_trc=bt709", f_sdr)
        self.assertIn("peak_detect=false", f_sdr)

        f_hlg = TonemapEngine.get_libplacebo_filter("hlg")
        self.assertIn("colorspace=9", f_hlg)
        self.assertIn("color_primaries=9", f_hlg)
        self.assertIn("color_trc=14", f_hlg)
        self.assertIn("peak_detect=false", f_hlg)

    def test_ffmpeg_colorspace_filter(self):
        vf_hdr10 = TonemapEngine.get_ffmpeg_colorspace_filter("hdr10")
        self.assertEqual(vf_hdr10, "colorspace=space=bt2020:primaries=bt2020:trc=smpte2084:format=p010le")

        vf_sdr = TonemapEngine.get_ffmpeg_colorspace_filter("sdr")
        self.assertEqual(vf_sdr, "colorspace=space=bt709:primaries=bt709:trc=iec61966-2-1:itp=bt2100:format=yuv420p")

    def test_ffmpeg_conversion_command(self):
        # SDR conversion with NVENC
        cmd_sdr = TonemapEngine.get_ffmpeg_conversion_command("in.mkv", "out_sdr.mkv", color_space="sdr")
        self.assertIn("-init_hw_device", cmd_sdr)
        self.assertIn("vulkan=vk", cmd_sdr)
        self.assertIn("-c:v", cmd_sdr)
        self.assertIn("hevc_nvenc", cmd_sdr)
        self.assertIn("-pix_fmt", cmd_sdr)
        self.assertIn("yuv420p", cmd_sdr)
        self.assertEqual(cmd_sdr[-1], "out_sdr.mkv")

        # HDR10 conversion with NVENC
        cmd_hdr10 = TonemapEngine.get_ffmpeg_conversion_command("in.mkv", "out_hdr.mkv", color_space="hdr10")
        self.assertIn("p010le", cmd_hdr10)
        self.assertIn("colorspace=9", " ".join(cmd_hdr10))
        self.assertEqual(cmd_hdr10[-1], "out_hdr.mkv")

    def test_hdr10_preset(self):
        self.engine.apply_preset("hdr10_sdr")
        self.assertEqual(self.player["tone-mapping"], "spline")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["target-peak"], 100)
        self.assertEqual(self.player["hdr-compute-peak"], "yes")
        self.assertAlmostEqual(self.player["hdr-contrast-recovery"], 0.35)
        self.assertIsNotNone(self.engine.active_shader)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("hdr_sdr_peak_100.glsl"))
        self.assertNotIn("2390", self.engine.get_status_summary()["preset_label"])
        self.assertEqual(self.engine.get_status_summary()["output_label"], "Rec.709 / Gamma 2.2")

    def test_target_peak_adjustment_updates_mpv_and_shader(self):
        self.engine.apply_preset("hdr10_sdr")
        self.engine.set_target_peak(200)
        self.assertEqual(self.player["target-peak"], 200)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("hdr_sdr_peak_200.glsl"))
        status = self.engine.get_status_summary()
        self.assertEqual(status["target_peak"], "200 nits")
        self.assertTrue(status["shader_active"])

    def test_all_sdr_curve_presets_end_at_bt709(self):
        for key in ("hdr10_sdr", "hdr10plus_sdr", "spline_sdr", "filmic_hable", "mobius_sdr", "reinhard_sdr"):
            self.engine.apply_preset(key)
            self.assertEqual(self.player["target-prim"], "bt.709", key)
            self.assertEqual(self.player["target-trc"], "gamma2.2", key)

    def test_bt2020_sdr_is_not_tonemapped(self):
        # Rec.2020 primaries with an SDR transfer (camera footage) must not be treated as HDR
        self.assertEqual(
            TonemapEngine.detect_source_hdr_format(probe_video_track={"color_transfer": "bt709", "color_primaries": "bt2020"}),
            "SDR",
        )
        self.assertEqual(
            TonemapEngine.detect_source_hdr_format(mpv_video_params={"gamma": "bt.1886", "primaries": "bt.2020"}),
            "SDR",
        )

    def test_color_science_page_lists_every_preset(self):
        from PyQt6.QtWidgets import QApplication
        from ui.tonemap_dialog import TonemapControlDrawer
        app = QApplication.instance() or QApplication([])
        drawer = TonemapControlDrawer(self.engine)
        self.assertEqual(set(drawer.preset_buttons.keys()), set(TonemapEngine.PRESETS.keys()))
        drawer.preset_buttons["mobius_sdr"].click()
        self.assertEqual(self.engine.current_preset, "mobius_sdr")

    def test_dci_xyz_preset(self):
        self.engine.apply_preset("dci_xyz_srgb")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["vf"], "format=rgb48le")
        self.assertEqual(self.player["tone-mapping"], "clip")
        self.assertEqual(self.player["brightness"], 0)
        self.assertEqual(self.player["gamma"], 0)
        self.assertEqual(self.player["contrast"], 8)
        self.assertEqual(self.player["saturation"], 10)
        # Verify calibrated punch shader is active
        self.assertIsNotNone(self.engine.active_shader)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("dci_xyz_to_srgb.glsl"))
        status = self.engine.get_status_summary()
        self.assertIn("Rec.709", status["preset_label"])
        self.assertTrue(status["shader_active"])
        self.assertEqual(status["adjustments"]["contrast"], 8)
        self.assertEqual(status["adjustments"]["saturation"], 10)

    def test_epiq_preset_and_toggle(self):
        # Enable DCI-XYZ with EPIQ flag
        callback_called = []
        self.engine.on_preset_change = lambda s: callback_called.append(s)

        self.engine.enable_dci_xyz_mode(True, is_epiq=True)
        self.assertTrue(self.engine.is_epiq)
        self.assertEqual(self.player["vf"], "format=rgb48le")
        self.assertEqual(self.player["tone-mapping"], "clip")
        self.assertEqual(self.player["contrast"], 12)
        self.assertEqual(self.player["saturation"], 15)
        self.assertIsNotNone(self.engine.active_shader)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("dci_xyz_epiq_to_srgb.glsl"))

        status = self.engine.get_status_summary()
        self.assertTrue(status["is_epiq"])
        self.assertIn("Rec.709", status["preset_label"])
        self.assertTrue(len(callback_called) > 0)

        # Toggle EPIQ correction off manually -> should switch back to standard punch
        self.engine.set_epiq_correction(False)
        self.assertFalse(self.engine.is_epiq)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("dci_xyz_to_srgb.glsl"))
        self.assertEqual(self.player["contrast"], 8)
        self.assertEqual(self.player["saturation"], 10)
        status2 = self.engine.get_status_summary()
        self.assertFalse(status2["is_epiq"])
        self.assertIn("Rec.709", status2["preset_label"])

        # Toggle EPIQ correction back on
        self.engine.set_epiq_correction(True)
        self.assertTrue(self.engine.is_epiq)
        self.assertTrue(self.engine.active_shader.replace("\\", "/").endswith("dci_xyz_epiq_to_srgb.glsl"))
        self.assertEqual(self.player["contrast"], 12)
        self.assertEqual(self.player["saturation"], 15)

    def test_adjustments(self):
        self.engine.set_adjustments(brightness=10, contrast=15, saturation=-5, gamma=2, hue=12)
        self.assertEqual(self.player["brightness"], 10)
        self.assertEqual(self.player["contrast"], 15)
        self.assertEqual(self.player["saturation"], -5)
        self.assertEqual(self.player["gamma"], 2)
        self.assertEqual(self.player["hue"], 12)

    def test_slider_resets(self):
        from PyQt6.QtWidgets import QApplication
        from ui.tonemap_dialog import TonemapControlDrawer
        app = QApplication.instance() or QApplication([])
        drawer = TonemapControlDrawer(self.engine)

        # Check reset buttons exist
        self.assertTrue(hasattr(drawer, "btn_rst_bright"))
        self.assertTrue(hasattr(drawer, "btn_rst_contrast"))
        self.assertTrue(hasattr(drawer, "btn_rst_sat"))
        self.assertTrue(hasattr(drawer, "btn_rst_gamma"))
        self.assertTrue(hasattr(drawer, "btn_rst_hue"))

        # Test individual reset button clicks
        drawer.slider_bright.setValue(25)
        drawer.btn_rst_bright.click()
        self.assertEqual(drawer.slider_bright.value(), 0)

        drawer.slider_contrast.setValue(-15)
        drawer.btn_rst_contrast.click()
        self.assertEqual(drawer.slider_contrast.value(), 0)

        drawer.slider_sat.setValue(40)
        drawer.btn_rst_sat.click()
        self.assertEqual(drawer.slider_sat.value(), 0)

        drawer.slider_gamma.setValue(30)
        drawer.btn_rst_gamma.click()
        self.assertEqual(drawer.slider_gamma.value(), 0)

        drawer.slider_hue.setValue(-50)
        drawer.btn_rst_hue.click()
        self.assertEqual(drawer.slider_hue.value(), 0)

    def test_auto_detect_and_convert_hdr_hdr10_hdr10plus_hlg(self):
        from PyQt6.QtWidgets import QApplication
        from core.media_inspector import MediaInspector
        from ui.osc_controls import OSCControls

        # 1. MediaInspector format_probe_data identifies HDR10+, HDR10, HLG, and HDR
        hdr10plus_probe = MediaInspector.format_probe_data({
            "format": {"filename": "movie.mkv"},
            "streams": [{
                "codec_type": "video",
                "codec_name": "hevc",
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "pix_fmt": "yuv420p10le",
                "side_data_list": [{"side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"}],
            }],
        })
        vt_plus = hdr10plus_probe["video_tracks"][0]
        self.assertEqual(vt_plus["hdr_format"], "HDR10+")
        self.assertTrue(vt_plus["is_hdr10plus"])

        hdr10_probe = MediaInspector.format_probe_data({
            "format": {"filename": "hdr10.mkv"},
            "streams": [{
                "codec_type": "video",
                "codec_name": "hevc",
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "pix_fmt": "yuv420p10le",
                "side_data_list": [{"side_data_type": "Mastering display metadata"}],
            }],
        })
        self.assertEqual(hdr10_probe["video_tracks"][0]["hdr_format"], "HDR10")

        # 2. TonemapEngine.detect_source_hdr_format across probe, video-params, and tracks
        self.assertEqual(TonemapEngine.detect_source_hdr_format(probe_video_track=vt_plus), "HDR10+")
        self.assertEqual(TonemapEngine.detect_source_hdr_format(probe_video_track=hdr10_probe["video_tracks"][0]), "HDR10")
        self.assertEqual(
            TonemapEngine.detect_source_hdr_format(mpv_video_params={"gamma": "pq", "primaries": "bt.2020"}),
            "HDR10",
        )
        self.assertEqual(
            TonemapEngine.detect_source_hdr_format(mpv_video_params={"gamma": "hlg", "primaries": "bt.2020"}),
            "HLG",
        )
        self.assertEqual(
            TonemapEngine.detect_source_hdr_format(mpv_video_params={"primaries": "bt.2020", "sig-peak": 4.0}),
            "HDR",
        )
        self.assertEqual(
            TonemapEngine.detect_source_hdr_format(mpv_tracks=[{"type": "video", "dolby-vision-profile": 5}]),
            "Dolby Vision P5",
        )
        self.assertEqual(
            TonemapEngine.detect_source_hdr_format(mpv_tracks=[{"type": "video", "dolby-vision-profile": 20}]),
            "Dolby Vision P20",
        )

        # DV Profile 20 probe detection
        dv20_probe = MediaInspector.format_probe_data({
            "format": {"filename": "mando_3d.mp4"},
            "streams": [{
                "codec_type": "video",
                "codec_name": "hevc",
                "side_data_list": [{"side_data_type": "DOVI configuration record", "dv_profile": 20}],
            }],
        })
        vt_dv20 = dv20_probe["video_tracks"][0]
        self.assertEqual(vt_dv20["hdr_format"], "Dolby Vision P20")
        self.assertTrue(vt_dv20["is_dv_p20"])
        self.assertTrue(vt_dv20["is_dv_profile_ipt"])
        self.assertEqual(TonemapEngine.detect_source_hdr_format(probe_video_track=vt_dv20), "Dolby Vision P20")

        # Auto-convert DV P20 for SDR display
        st_dv20_sdr = self.engine.auto_configure_for_source("Dolby Vision P20", is_hdr_display=False)
        self.assertEqual(self.engine.current_preset, "dv_p20_rpu_sdr")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["tone-mapping"], "spline")
        self.assertIsNone(self.engine.active_shader)
        self.assertEqual(st_dv20_sdr["preset_label"], "Auto: 🧬 Dolby Vision P20 -> Rec.709 SDR (RPU L8)")

        # Auto-convert DV P20 for HDR display
        st_dv20_hdr = self.engine.auto_configure_for_source("Dolby Vision P20", is_hdr_display=True)
        self.assertEqual(self.engine.current_preset, "dv_p20_rpu_hdr")
        self.assertEqual(self.player["target-prim"], "bt.2020")
        self.assertEqual(self.player["target-trc"], "pq")
        self.assertEqual(self.player["tone-mapping"], "st2094-40")
        self.assertIsNone(self.engine.active_shader)
        self.assertEqual(st_dv20_hdr["preset_label"], "Auto: 🧬 Dolby Vision P20 -> HDR10+ (RPU)")

        # Auto-convert HLG for SDR display
        st_hlg_sdr = self.engine.auto_configure_for_source("HLG", is_hdr_display=False)
        self.assertEqual(self.engine.current_preset, "hlg_sdr")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["tone-mapping"], "bt.2390")
        self.assertEqual(st_hlg_sdr["preset_label"], "Auto: ⚡ HLG (Rec.2100) -> Rec.709 SDR (Punchy Filmic)")

        # Auto-convert HLG for HDR display
        st_hlg_hdr = self.engine.auto_configure_for_source("HLG", is_hdr_display=True)
        self.assertEqual(self.engine.current_preset, "hdr10_hdr")
        self.assertEqual(self.player["target-prim"], "bt.2020")
        self.assertEqual(st_hlg_hdr["preset_label"], "Auto: HLG -> HDR Rec.2020 HLG (Display HDR)")

        # 3. Auto-convert HDR10+ for SDR display
        st_plus_sdr = self.engine.auto_configure_for_source("HDR10+", is_hdr_display=False)
        self.assertEqual(self.player["tone-mapping"], "spline")
        self.assertEqual(self.player["target-prim"], "bt.709")
        self.assertEqual(self.player["target-trc"], "gamma2.2")
        self.assertEqual(self.player["target-peak"], 100)
        self.assertEqual(self.player["hdr-compute-peak"], "yes")
        self.assertAlmostEqual(self.player["hdr-contrast-recovery"], 0.35)
        self.assertEqual(st_plus_sdr["preset_label"], "Auto: HDR10+ -> Rec.709 SDR (Gamma 2.2, Dynamic Peak)")
        self.assertEqual(st_plus_sdr["display_dynamic_range"], "SDR")

        # 4. Auto-convert HDR10 for SDR display
        st_hdr10_sdr = self.engine.auto_configure_for_source("HDR10", is_hdr_display=False)
        self.assertEqual(self.player["tone-mapping"], "spline")
        self.assertEqual(self.player["target-peak"], 100)
        self.assertAlmostEqual(self.player["hdr-contrast-recovery"], 0.35)
        self.assertEqual(st_hdr10_sdr["preset_label"], "Auto: HDR10 -> Rec.709 SDR (Gamma 2.2)")

        # 5. Auto-convert HDR10 for HDR display
        st_hdr10_hdr = self.engine.auto_configure_for_source("HDR10", is_hdr_display=True)
        self.assertEqual(self.player["target-prim"], "bt.2020")
        self.assertEqual(self.player["target-trc"], "pq")
        self.assertEqual(self.player["target-peak"], 1000)
        self.assertEqual(st_hdr10_hdr["preset_label"], "Auto: HDR10 -> HDR Rec.2020 PQ (Display HDR)")
        self.assertEqual(st_hdr10_hdr["display_dynamic_range"], "HDR")

        # 6. Bottom OSC color mapping badge updates cleanly
        app = QApplication.instance() or QApplication([])
        osc = OSCControls()
        osc.set_color_status(st_plus_sdr["preset_label"])
        self.assertEqual(osc.lbl_color_badge.text(), "COLOR: Auto: HDR10+ -> Rec.709 SDR (Gamma 2.2, Dynamic Peak)")

    def test_passthrough_disables_tonemapping_and_blocks_auto_override(self):
        from core.mpv_engine import MPVEngine

        class _DummyMPV:
            def __init__(self, tonemap_engine):
                self.is_dcp_playing = False
                self.nvjpeg2k_active = False
                self.tonemap_engine = tonemap_engine
                self.current_uri = "movie_hdr10plus.mkv"

        # 1. Passthrough disables tonemapping cleanly
        self.engine.apply_preset("passthrough")
        self.assertEqual(self.engine.current_preset, "passthrough")
        self.assertIsNone(self.engine.auto_conversion_summary)
        self.assertEqual(self.player["tone-mapping"], "clip")
        self.assertEqual(self.player["gamut-mapping-mode"], "clip")
        self.assertEqual(self.player["hdr-compute-peak"], "no")
        self.assertEqual(self.player["target-prim"], "auto")
        self.assertEqual(self.player["target-trc"], "auto")
        self.assertEqual(self.player["target-peak"], "auto")

        # 2. Auto-detection must not overwrite passthrough for HDR10+ or Dolby Vision P5
        dummy_mpv = _DummyMPV(self.engine)
        MPVEngine._auto_detect_and_apply_hdr(
            dummy_mpv,
            probe_track={"hdr_format": "HDR10+"},
            mpv_video_params={"gamma": "pq", "primaries": "bt.2020"},
        )
        self.assertEqual(self.engine.current_preset, "passthrough")
        self.assertEqual(self.player["tone-mapping"], "clip")

        MPVEngine._auto_detect_and_apply_hdr(
            dummy_mpv,
            mpv_tracks=[{"type": "video", "dolby-vision-profile": 5}],
        )
        self.assertEqual(self.engine.current_preset, "passthrough")
        self.assertEqual(self.player["tone-mapping"], "clip")


if __name__ == "__main__":
    unittest.main()
