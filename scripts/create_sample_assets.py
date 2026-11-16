"""
Creates real sample assets:
1. Complete SMPTE DCP folder (ASSETMAP, PKL, CPL, video_reel1.mxf [JP2K], audio_reel1.mxf [PCM 24-bit])
2. Apple ProRes 422 test video
3. Google VP9 test video
4. External Subtitle file (.srt)
5. External Audio file (.wav)
"""

import os
import subprocess

def run_cmd(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    dcp_dir = os.path.join(assets_dir, "sample_dcp")
    os.makedirs(dcp_dir, exist_ok=True)

    print("1. Creating DCP Picture MXF (JPEG 2000)...")
    pic_mxf = os.path.join(dcp_dir, "video_reel1.mxf")
    if not os.path.exists(pic_mxf):
        run_cmd([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=1920x1080:rate=24",
            "-c:v", "jpeg2000", "-pix_fmt", "yuv422p10le", pic_mxf
        ])

    print("2. Creating DCP Sound MXF (PCM 24-bit uncompressed)...")
    snd_mxf = os.path.join(dcp_dir, "audio_reel1.mxf")
    if os.path.exists(snd_mxf):
        os.remove(snd_mxf)
    run_cmd([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=48000",
        "-c:a", "pcm_s24le", "-mxf_audio_edit_rate", "24/1", "-f", "mxf_opatom", snd_mxf
    ])

    print("3. Generating DCP XML metadata (ASSETMAP, PKL, CPL)...")
    cpl_uuid = "urn:uuid:e3b0c442-98fc-1c14-9afb-f4c8996fb924"
    pkl_uuid = "urn:uuid:7c4a8d09-ca37-495c-9c17-48f88997ef81"
    pic_uuid = "urn:uuid:550e8400-e29b-41d4-a716-446655440000"
    snd_uuid = "urn:uuid:6ba7b810-9dad-11d1-80b4-00c04fd430c8"

    assetmap = f"""<?xml version="1.0" encoding="UTF-8"?>
<AssetMap xmlns="http://www.smpte-ra.org/schemas/429-9/2007/AM">
  <Id>urn:uuid:11111111-2222-3333-4444-555555555555</Id>
  <Creator>BOOBCinema Demo</Creator>
  <VolumeCount>1</VolumeCount>
  <IssueDate>2026-11-12T16:00:00+00:00</IssueDate>
  <AssetList>
    <Asset>
      <Id>{pkl_uuid}</Id>
      <PackingList/>
      <ChunkList>
        <Chunk><Path>PKL.xml</Path></Chunk>
      </ChunkList>
    </Asset>
    <Asset>
      <Id>{cpl_uuid}</Id>
      <ChunkList>
        <Chunk><Path>CPL.xml</Path></Chunk>
      </ChunkList>
    </Asset>
    <Asset>
      <Id>{pic_uuid}</Id>
      <ChunkList>
        <Chunk><Path>video_reel1.mxf</Path></Chunk>
      </ChunkList>
    </Asset>
    <Asset>
      <Id>{snd_uuid}</Id>
      <ChunkList>
        <Chunk><Path>audio_reel1.mxf</Path></Chunk>
      </ChunkList>
    </Asset>
  </AssetList>
</AssetMap>"""
    with open(os.path.join(dcp_dir, "ASSETMAP.xml"), "w", encoding="utf-8") as f:
        f.write(assetmap)

    pkl = f"""<?xml version="1.0" encoding="UTF-8"?>
<PackingList xmlns="http://www.smpte-ra.org/schemas/429-8/2007/PKL">
  <Id>{pkl_uuid}</Id>
  <AnnotationText>BOOBCinema Sample PKL</AnnotationText>
  <IssueDate>2026-11-12T16:00:00+00:00</IssueDate>
  <Issuer>BOOBCinema</Issuer>
  <AssetList>
    <Asset>
      <Id>{cpl_uuid}</Id>
      <Type>text/xml;charset=utf-8</Type>
      <Size>2048</Size>
    </Asset>
    <Asset>
      <Id>{pic_uuid}</Id>
      <Type>application/mxf</Type>
      <Size>{os.path.getsize(pic_mxf)}</Size>
    </Asset>
    <Asset>
      <Id>{snd_uuid}</Id>
      <Type>application/mxf</Type>
      <Size>{os.path.getsize(snd_mxf)}</Size>
    </Asset>
  </AssetList>
</PackingList>"""
    with open(os.path.join(dcp_dir, "PKL.xml"), "w", encoding="utf-8") as f:
        f.write(pkl)

    cpl = f"""<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL">
  <Id>{cpl_uuid}</Id>
  <AnnotationText>BOOBCinema 2K DCI Test Reel</AnnotationText>
  <IssueDate>2026-11-12T16:00:00+00:00</IssueDate>
  <Creator>BOOBCinema</Creator>
  <ContentTitleText>BOOB_CINEMA_SMPTE_2K_24P_51</ContentTitleText>
  <ContentKind>feature</ContentKind>
  <EditRate>24 1</EditRate>
  <ReelList>
    <Reel>
      <Id>urn:uuid:reel-0001-demo</Id>
      <AssetList>
        <MainPicture>
          <Id>{pic_uuid}</Id>
          <EditRate>24 1</EditRate>
          <IntrinsicDuration>48</IntrinsicDuration>
          <EntryPoint>0</EntryPoint>
          <Duration>48</Duration>
          <ScreenAspectRatio>1.85</ScreenAspectRatio>
        </MainPicture>
        <MainSound>
          <Id>{snd_uuid}</Id>
          <EditRate>24 1</EditRate>
          <IntrinsicDuration>48</IntrinsicDuration>
          <EntryPoint>0</EntryPoint>
          <Duration>48</Duration>
        </MainSound>
      </AssetList>
    </Reel>
  </ReelList>
</CompositionPlaylist>"""
    with open(os.path.join(dcp_dir, "CPL.xml"), "w", encoding="utf-8") as f:
        f.write(cpl)

    print("4. Generating ProRes 422 test video...")
    prores_file = os.path.join(assets_dir, "sample_prores422.mov")
    if not os.path.exists(prores_file):
        run_cmd([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=24",
            "-c:v", "prores_ks", "-profile:v", "3", prores_file
        ])

    print("5. Generating VP9 test video...")
    vp9_file = os.path.join(assets_dir, "sample_vp9.webm")
    if not os.path.exists(vp9_file):
        run_cmd([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=24",
            "-c:v", "libvpx-vp9", "-b:v", "1M", vp9_file
        ])

    print("6. Generating external audio track (WAV)...")
    wav_file = os.path.join(assets_dir, "sample_external_audio.wav")
    if not os.path.exists(wav_file):
        run_cmd([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
            "-c:a", "pcm_s16le", wav_file
        ])

    print("7. Generating external subtitle file (SRT)...")
    srt_file = os.path.join(assets_dir, "sample_external_subtitles.srt")
    with open(srt_file, "w", encoding="utf-8") as f:
        f.write("""1
00:00:00,000 --> 00:00:01,500
[BOOB Player] External Subtitle Track Loaded

2
00:00:01,500 --> 00:00:03,000
Frame-Accurate Synchronization & Tonemapping Active
""")

    print("All sample assets generated successfully!")

if __name__ == "__main__":
    main()
