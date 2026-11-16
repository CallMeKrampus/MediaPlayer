"""
Unit tests for DCP (Digital Cinema Package) parsing and asset resolution.
"""

import os
import tempfile
import unittest
from core.dcp_parser import DCPParser, DCPPackage, frames_to_timecode


class TestDCPParser(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.cpl_uuid = "urn:uuid:6a438722-1234-5678-90ab-cdef01234567"
        self.pic_uuid = "urn:uuid:11111111-2222-3333-4444-555555555555"
        self.snd_uuid = "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.pkl_uuid = "urn:uuid:99999999-8888-7777-6666-555555555555"

        # 1. Write dummy MXF files
        self.pic_path = os.path.join(self.test_dir, "picture_reel1.mxf")
        self.snd_path = os.path.join(self.test_dir, "sound_reel1.mxf")
        with open(self.pic_path, "wb") as f:
            f.write(b"MXF_PICTURE_JP2K_TEST")
        with open(self.snd_path, "wb") as f:
            f.write(b"MXF_SOUND_PCM_TEST")

        # 2. Write ASSETMAP.xml
        asset_map_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<AssetMap xmlns="http://www.smpte-ra.org/schemas/429-9/2007/AM">
  <Id>urn:uuid:00000000-0000-0000-0000-000000000001</Id>
  <Creator>BOOBCinema Test</Creator>
  <VolumeCount>1</VolumeCount>
  <IssueDate>2026-11-12T16:00:00+00:00</IssueDate>
  <AssetList>
    <Asset>
      <Id>{self.pkl_uuid}</Id>
      <PackingList/>
      <ChunkList>
        <Chunk>
          <Path>PKL_test.xml</Path>
        </Chunk>
      </ChunkList>
    </Asset>
    <Asset>
      <Id>{self.cpl_uuid}</Id>
      <ChunkList>
        <Chunk>
          <Path>CPL_test.xml</Path>
        </Chunk>
      </ChunkList>
    </Asset>
    <Asset>
      <Id>{self.pic_uuid}</Id>
      <ChunkList>
        <Chunk>
          <Path>picture_reel1.mxf</Path>
        </Chunk>
      </ChunkList>
    </Asset>
    <Asset>
      <Id>{self.snd_uuid}</Id>
      <ChunkList>
        <Chunk>
          <Path>sound_reel1.mxf</Path>
        </Chunk>
      </ChunkList>
    </Asset>
  </AssetList>
</AssetMap>"""
        with open(os.path.join(self.test_dir, "ASSETMAP.xml"), "w", encoding="utf-8") as f:
            f.write(asset_map_content)

        # 3. Write PKL_test.xml
        pkl_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<PackingList xmlns="http://www.smpte-ra.org/schemas/429-8/2007/PKL">
  <Id>{self.pkl_uuid}</Id>
  <AnnotationText>Test PKL</AnnotationText>
  <IssueDate>2026-11-12T16:00:00+00:00</IssueDate>
  <Issuer>BOOBCinema</Issuer>
  <AssetList>
    <Asset>
      <Id>{self.cpl_uuid}</Id>
      <Type>text/xml;charset=utf-8</Type>
      <Size>2048</Size>
    </Asset>
    <Asset>
      <Id>{self.pic_uuid}</Id>
      <Type>application/mxf</Type>
      <Size>1048576</Size>
    </Asset>
    <Asset>
      <Id>{self.snd_uuid}</Id>
      <Type>application/mxf</Type>
      <Size>524288</Size>
    </Asset>
  </AssetList>
</PackingList>"""
        with open(os.path.join(self.test_dir, "PKL_test.xml"), "w", encoding="utf-8") as f:
            f.write(pkl_content)

        # 4. Write CPL_test.xml
        cpl_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL">
  <Id>{self.cpl_uuid}</Id>
  <AnnotationText>CPL Test Composition</AnnotationText>
  <IssueDate>2026-11-12T16:00:00+00:00</IssueDate>
  <Creator>BOOBCinema Lab</Creator>
  <ContentTitleText>TEST_CINEMA_FEATURE_SCOPE_2K_51</ContentTitleText>
  <ContentKind>feature</ContentKind>
  <EditRate>24 1</EditRate>
  <ReelList>
    <Reel>
      <Id>urn:uuid:reel-0001</Id>
      <AssetList>
        <MainPicture>
          <Id>{self.pic_uuid}</Id>
          <EditRate>24 1</EditRate>
          <IntrinsicDuration>2880</IntrinsicDuration>
          <EntryPoint>0</EntryPoint>
          <Duration>2880</Duration>
          <ScreenAspectRatio>2.39</ScreenAspectRatio>
        </MainPicture>
        <MainSound>
          <Id>{self.snd_uuid}</Id>
          <EditRate>24 1</EditRate>
          <IntrinsicDuration>2880</IntrinsicDuration>
          <EntryPoint>0</EntryPoint>
          <Duration>2880</Duration>
        </MainSound>
      </AssetList>
    </Reel>
  </ReelList>
</CompositionPlaylist>"""
        with open(os.path.join(self.test_dir, "CPL_test.xml"), "w", encoding="utf-8") as f:
            f.write(cpl_content)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_dcp_folder(self):
        self.assertTrue(DCPParser.is_dcp_folder(self.test_dir))
        self.assertFalse(DCPParser.is_dcp_folder(tempfile.gettempdir()))

    def test_parse_dcp(self):
        pkg = DCPParser.parse(self.test_dir)
        self.assertIsInstance(pkg, DCPPackage)
        self.assertEqual(pkg.standard, "SMPTE")
        self.assertEqual(len(pkg.compositions), 1)

        cpl = pkg.default_composition
        self.assertIsNotNone(cpl)
        self.assertEqual(cpl.title, "TEST_CINEMA_FEATURE_SCOPE_2K_51")
        self.assertEqual(cpl.content_kind, "feature")
        self.assertEqual(cpl.fps, 24.0)
        self.assertEqual(cpl.total_frames, 2880)
        self.assertEqual(cpl.total_seconds, 120.0)  # 2 minutes
        self.assertEqual(cpl.total_timecode, "00:02:00:00")

        # Verify Reel and asset resolution
        self.assertEqual(len(cpl.reels), 1)
        reel = cpl.reels[0]
        self.assertEqual(reel.screen_aspect_ratio, "Scope (2.39:1)")
        self.assertEqual(reel.picture_duration_frames, 2880)
        self.assertEqual(reel.timecode, "00:02:00:00")
        self.assertEqual(os.path.normpath(reel.picture_path), os.path.normpath(self.pic_path))
        self.assertEqual(os.path.normpath(reel.sound_path), os.path.normpath(self.snd_path))

    def test_timecode_calculation(self):
        self.assertEqual(frames_to_timecode(0, 24), "00:00:00:00")
        self.assertEqual(frames_to_timecode(24, 24), "00:00:01:00")
        self.assertEqual(frames_to_timecode(36, 24), "00:00:01:12")
        self.assertEqual(frames_to_timecode(86400, 24), "01:00:00:00")


if __name__ == "__main__":
    unittest.main()
