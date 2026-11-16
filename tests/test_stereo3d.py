"""
Unit tests for BOOB Player Stereoscopic 3D Engine and Dialog.
Tests 3D format detection, ffmpeg stereo3d filter mapping, eye swapping,
3D DCP CPL parsing, and nvJPEG2000 eye extraction.
"""

import unittest
from unittest.mock import MagicMock
import sys
import tempfile
import os

from PyQt6.QtWidgets import QApplication
from core.stereo3d_engine import Stereo3DEngine
from ui.stereo3d_dialog import Stereo3DDialog
from core.dcp_parser import DCPParser, DCPComposition, DCPReel
from core.nvjpeg2k_engine import NVJPEG2KPlaybackController

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestStereo3DEngine(unittest.TestCase):
    def setUp(self):
        self.mock_player = MagicMock()
        self.mock_player.vf = []
        self.engine = Stereo3DEngine(self.mock_player)

    def test_default_state(self):
        self.assertFalse(self.engine.enabled)
        self.assertEqual(self.engine.input_format, "auto")
        self.assertEqual(self.engine.output_mode, "anaglyph_arcd")
        self.assertFalse(self.engine.swap_eyes)

    def test_filename_detection(self):
        # Half SBS
        self.assertEqual(Stereo3DEngine.detect_3d_format_from_filename("Avatar.2009.H-SBS.1080p.mkv"), "sbs2l")
        self.assertEqual(Stereo3DEngine.detect_3d_format_from_filename("Gravity_HSBS.mp4"), "sbs2l")

        # Full SBS
        self.assertEqual(Stereo3DEngine.detect_3d_format_from_filename("Dune.Full-SBS.mkv"), "sbsl")

        # Top-and-Bottom / Over-Under
        self.assertEqual(Stereo3DEngine.detect_3d_format_from_filename("LifeOfPi_H-TAB.mkv"), "ab2l")
        self.assertEqual(Stereo3DEngine.detect_3d_format_from_filename("Pacific_Rim_Top-and-Bottom.mkv"), "abl")

        # Frame Interleaved
        self.assertEqual(Stereo3DEngine.detect_3d_format_from_filename("Demo_Frame-Sequential.ts"), "al")

        # Non-3D file
        self.assertIsNone(Stereo3DEngine.detect_3d_format_from_filename("Matrix_1999_1080p.mkv"))
        # Generic 3D in filename without packing tag is NOT considered 3D
        self.assertIsNone(Stereo3DEngine.detect_3d_format_from_filename("Star.Wars.The.Mandalorian.and.Grogu.2026.2160p.3D.DSNP.mp4"))

    def test_dual_video_streams_same_index_check(self):
        # 1 video stream only -> strictly 2D
        probe_single = {"streams": [{"codec_type": "video", "index": 0}, {"codec_type": "audio", "index": 1}]}
        self.assertFalse(Stereo3DEngine.check_has_dual_video_streams_same_index(probe_data=probe_single))

        # 2 video streams with DIFFERENT indices -> 2D
        probe_diff = {"streams": [{"codec_type": "video", "index": 0}, {"codec_type": "video", "index": 1}]}
        self.assertFalse(Stereo3DEngine.check_has_dual_video_streams_same_index(probe_data=probe_diff))

        # 2 video streams with the SAME index (e.g. MVC / stereoscopic multi-view) -> 3D
        probe_same = {"streams": [{"codec_type": "video", "index": 0}, {"codec_type": "video", "index": 0}]}
        self.assertTrue(Stereo3DEngine.check_has_dual_video_streams_same_index(probe_data=probe_same))

        # configure_for_media on single stream file renders as 2D
        self.engine.configure_for_media("Movie.3D.mp4", is_dcp=False, probe_data=probe_single)
        self.assertFalse(self.engine.enabled)
        self.assertIsNone(self.engine.detected_input_format)

        # configure_for_media on dual stream same index enables 3D
        self.engine.configure_for_media("Movie_HSBS.mp4", is_dcp=False, probe_data=probe_same)
        self.assertTrue(self.engine.enabled)
        self.assertEqual(self.engine.detected_input_format, "sbs2l")

    def test_filter_generation_and_application(self):
        self.engine.set_input_format("sbs2l")
        self.engine.set_output_mode("anaglyph_arcd")
        self.engine.set_enabled(True)

        self.mock_player.__setitem__.assert_called_with("vf", "stereo3d=in=sbs2l:out=arcd")

    def test_eye_swapping(self):
        self.engine.input_format = "sbs2l"
        self.assertFalse(self.engine.swap_eyes)
        self.assertEqual(self.engine.get_effective_input_format(), "sbs2l")

        self.engine.toggle_swap_eyes()
        self.assertTrue(self.engine.swap_eyes)
        # sbs2l with swap becomes sbs2r
        self.assertEqual(self.engine.get_effective_input_format(), "sbs2r")

        # ab2l with swap becomes ab2r
        self.engine.input_format = "ab2l"
        self.assertEqual(self.engine.get_effective_input_format(), "ab2r")

    def test_mono_isolators(self):
        self.engine.input_format = "sbs2l"
        self.engine.set_output_mode("mono_l")
        self.assertEqual(Stereo3DEngine.FFMPEG_OUT_MAP["mono_l"], "ml")

        self.engine.set_output_mode("mono_r")
        self.assertEqual(Stereo3DEngine.FFMPEG_OUT_MAP["mono_r"], "mr")

    def test_reset(self):
        self.engine.set_enabled(True)
        self.engine.set_input_format("ab2l")
        self.engine.set_output_mode("mono_r")
        self.engine.set_swap_eyes(True)

        self.engine.reset()
        self.assertFalse(self.engine.enabled)
        self.assertEqual(self.engine.input_format, "auto")
        self.assertEqual(self.engine.output_mode, "anaglyph_arcd")
        self.assertFalse(self.engine.swap_eyes)


class TestStereo3DDialog(unittest.TestCase):
    def setUp(self):
        self.mock_player = MagicMock()
        self.engine = Stereo3DEngine(self.mock_player)
        self.dlg = Stereo3DDialog(self.engine)

    def test_dialog_apply_and_reset(self):
        self.dlg.chk_enabled.setChecked(True)
        idx_in = self.dlg.cb_input.findData("sbs2l")
        self.dlg.cb_input.setCurrentIndex(idx_in)
        idx_out = self.dlg.cb_output.findData("interleave_rows")
        self.dlg.cb_output.setCurrentIndex(idx_out)
        self.dlg.chk_swap.setChecked(True)

        self.dlg._on_apply()
        self.assertTrue(self.engine.enabled)
        self.assertEqual(self.engine.input_format, "sbs2l")
        self.assertEqual(self.engine.output_mode, "interleave_rows")
        self.assertTrue(self.engine.swap_eyes)

        self.dlg._on_reset()
        self.assertFalse(self.engine.enabled)
        self.assertEqual(self.engine.input_format, "auto")
        self.assertEqual(self.engine.output_mode, "anaglyph_arcd")
        self.assertFalse(self.engine.swap_eyes)


class TestStereoscopicDCP(unittest.TestCase):
    def test_cpl_3d_tag_parsing(self):
        # Create minimal 3D CPL XML with MainStereoscopicPicture
        cpl_xml = """<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL">
  <Id>urn:uuid:11111111-2222-3333-4444-555555555555</Id>
  <AnnotationText>Avatar 3D Feature</AnnotationText>
  <ContentTitleText>Avatar_FTR_3D_S_EN-XX_51_2K_20091218</ContentTitleText>
  <ContentKind>feature</ContentKind>
  <ReelList>
    <Reel>
      <Id>urn:uuid:aaaaaaa1-aaaa-aaaa-aaaa-aaaaaaaaaaaa</Id>
      <AssetList>
        <MainStereoscopicPicture>
          <Id>urn:uuid:bbbbbbb1-bbbb-bbbb-bbbb-bbbbbbbbbbbb</Id>
          <EditRate>24 1</EditRate>
          <FrameRate>48 1</FrameRate>
          <Duration>1440</Duration>
          <EntryPoint>0</EntryPoint>
          <ScreenAspectRatio>2.39</ScreenAspectRatio>
        </MainStereoscopicPicture>
        <MainSound>
          <Id>urn:uuid:ccccccc1-cccc-cccc-cccc-cccccccccccc</Id>
          <Duration>1440</Duration>
          <EntryPoint>0</EntryPoint>
        </MainSound>
      </AssetList>
    </Reel>
  </ReelList>
</CompositionPlaylist>"""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
            f.write(cpl_xml)
            cpl_file = f.name

        try:
            cpl = DCPParser._parse_cpl(cpl_file, {}, "SMPTE")
            self.assertTrue(cpl.is_3d)
            self.assertEqual(len(cpl.reels), 1)
            self.assertTrue(cpl.reels[0].is_stereoscopic_3d)
            self.assertEqual(cpl.reels[0].picture_uuid, "bbbbbbb1-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
            self.assertEqual(cpl.reels[0].picture_duration_frames, 1440)
        finally:
            if os.path.exists(cpl_file):
                os.remove(cpl_file)

    def test_nvjpeg2k_stereo_eye_selection(self):
        controller = NVJPEG2KPlaybackController()
        self.assertEqual(controller.stereo_eye, "left")
        controller.set_stereo_eye("right")
        self.assertEqual(controller.stereo_eye, "right")
        controller.set_stereo_eye("left")
        self.assertEqual(controller.stereo_eye, "left")


class TestMainWindowStereo3DIntegration(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.win = MainWindow()

    def tearDown(self):
        self.win.close()

    def test_stereo3d_menu_exists(self):
        self.assertIsNotNone(self.win.menu_stereo3d)
        self.win._populate_stereo3d_menu(self.win.menu_stereo3d)
        actions = self.win.menu_stereo3d.actions()
        self.assertGreater(len(actions), 5)
        # First action is Enable
        self.assertIn("Enable Stereoscopic 3D", actions[0].text())

    def test_mode_switching_updates_toast(self):
        self.win._set_stereo3d_output_mode("anaglyph_arcd")
        self.assertTrue(self.win.engine.stereo3d_engine.enabled)
        self.assertEqual(self.win.engine.stereo3d_engine.output_mode, "anaglyph_arcd")

        self.win._set_stereo3d_enabled(False)
        self.assertFalse(self.win.engine.stereo3d_engine.enabled)


if __name__ == "__main__":
    unittest.main()
