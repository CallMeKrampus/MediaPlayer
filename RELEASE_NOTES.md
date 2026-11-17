# BOOB Player - Release Notes & Technical Briefing (v1.0.0)

**BOOB Player** is an open-source, reference-grade media workstation engineered for colorists, projectionists, audio engineers, and power users. It pairs the rendering fidelity of **mpv** (`gpu-next` / `libplacebo`) with **NVIDIA nvJPEG2000 hardware acceleration** for theatrical Digital Cinema Packages (DCPs), SMPTE ST 2098-2 spatial audio visualization, and MPC-HC style frame controls.

---

## 🚀 1. What's Possible (Core Tested Capabilities)

### 🎞️ Theatrical Digital Cinema Package (DCP) Hardware Engine
* **NVIDIA nvJPEG2000 Hardware Acceleration**: Direct CUDA decoding of 12-bit DCI-XYZ essence frames at Native 4K Master (`4096×2160`) at 24.0 and 48.0 fps (HFR). Real-world ceiling: ~56–58 FPS in 4K, 150+ FPS in 2K mode on RTX 50-series hardware.
* **Lookahead Prefetch Architecture**: Multi-threaded lookahead frame prefetching (`NVJPEG2K-PrefetchWorker`) with KLV essence indexing and memory-mapped lookahead buffers.
* **Cryptographic Integrity & Hash Verification**: Background multi-threaded SHA-1 and SHA-256 validation against the Packing List (`PKL.xml`). Accurately flags corrupted, truncated, or missing picture/audio/timed-text MXFs.
* **Universal SMPTE & Interop CPL Parsing**: Resolves multi-reel Composition Playlists, automatic UUID mapping, and anamorphic laser IMAX GT 1.43:1 aspect unsqueezing (`4096×2864`).
* **Quality Tiers**:
  * `Level 0`: Native 4K Master (`4096×2160`).
  * `Level 1`: 2K Sub-Band Match (`2048×1080`).
  * `Level 2`: 1K Wavelet Proxy (`1024×540`) for instant seek indexing.

### 🎨 Color Science & Dynamic Tonemapping Pipeline
* **Dolby Vision Profile 20 (MV-HEVC) & Profile 5**:
  * Dynamic RPU Level 1 (scene peak), Level 3 (dynamic offsets), and Level 8 (slope, offset, power, saturation) trim extraction via `dovi_tool` and libplacebo.
  * Direct Rec.709 SDR mapping utilizing algebraic trims without division spikes.
* **HDR10, HDR10+, and HLG Support**:
  * Dynamic tone mapping presets: `BT.2390` (ITU-R standard), `Hable / ACES Filmic`, `Spline`, `Mobius`, `Reinhard`, and `Clip`.
  * Non-linear dynamic target peak selection: 80, 100, 150, 200, 300, 400, 600, and 1000 nits.
* **Windows 11 Direct HDR Pass-Through (`Ctrl+Shift+H`)**: Signals the Windows display swapchain (`target-colorspace-hint=yes`) for uncompressed Rec.2020 PQ pass-through.
* **Split-Screen A/B Comparison Wipe (`Ctrl+W`)**: Interactive draggable divider comparing graded/processed video against raw bypass.

### 🎧 Immersive Audio (SMPTE ST 2098-2 IAB / Atmos) & Spatial Visualizer
* **Cinema Spatial Audio Ingestion**: Decodes discrete beds (5.1, 7.1, 9.1, 13.1) and dynamic spatial audio point objects with 3D Cartesian coordinates $(x, y, z)$, gain, and spread.
* **3D Wireframe Auditorium Visualizer (`Ctrl+M`)**: Interactive 3D RMU view, Top-Down plan, and Screen elevation with free orbit, pan, zoom, and live object tooltips.
* **Binaural Headphone Virtualization**: Built-in HRTF / SOFA spatial acoustic processing.
* **Theatrical Multi-Channel Routing**: IMAX 5.0 and IMAX 12.0 discrete theatrical mix downmixing and external audio ingestion (`Ctrl+A`).

### 📐 Geometric Control & MPC-HC Style Workflow
* **Pan & Scan (PnS) 10-Key Matrix**: 2D offset pan, independent width/height stretch, rotation (90° steps), vertical flip, horizontal mirror, and aspect ratio snapping (`Scale to 16:9`, `Zoom to 2.35:1`, `2.39:1 Scope`).
* **Seekbar Hover Thumbnail Previews**: Real-time floating thumbnail preview box with formatted timecodes and chapter names backed by a 120-item LRU cache.
* **Frame-Accurate "Go To..." Dialog (`Ctrl+G`)**: Accepts timecodes (`hh:mm:ss.ms` or unseparated digits like `011547376`) or frame counts (`frame, fps`).
* **Lossless Zero-Reencode Clip Trimmer (`Ctrl+Shift+E`)**: Stream-copies `[In, Out]` ranges into standalone files within seconds.
* **Tonemapped Native Snapshots (`Ctrl+S`)**: Captures active image raster (auto-detecting and stripping black letterbox bars) into uncompressed PNG/TIFF with color profile tags.

### 💬 Subtitle Engine & Timed Text
* **DCP Theatrical Subtitles**: Parses SMPTE 428-7 XML and Interop XML timed text subtitle reels with sub-millisecond binary search indexing.
* **External Subtitle File Ingestion (`Ctrl+U`)**: SubRip (`.srt`), Advanced SubStation Alpha (`.ass` / `.ssa`), WebVTT (`.vtt`), MicroDVD (`.sub`), and VobSub (`.idx`/`.sub`).
* **Independent Subtitle Control**: Toggle off/on via `V` (persists across seeks and file reloads without unintended reactivation); vector glyph rendering protected against HDR dimming.

---

## ⚠️ 2. Known Issues, Transient Defects & Self-Healing Architecture

> [!CAUTION]
> **Flat Purple / Red / Green / White Frame — Shader Constant Miscompile in the Bundled libmpv**
> * **Symptom**: Video opens as a flat or heavily tinted solid colour (purple and red are most common on Dolby Vision Profile 20) while audio, timeline and status bar behave normally. It is decided once per process, is far more likely when a file is opened after the player has sat idle, and survives seeking, preset changes and video output rebuilds.
> * **Mechanism**: With `vo=gpu-next` on Direct3D 11, libplacebo's GLSL is compiled to SPIR-V inside `mpv-2.dll`. The bundled build intermittently loses the leading characters of float literals with 16+ significant digits (`1.000962257385254` → `0.000962…` or `962257354752.0`; `49.261085510253906` → `0.261…`). Those literals are the P010 sample scale and the PQ scale, and compiled shaders are cached for the life of the video output. Player state is identical between good and bad runs; hardware vs. software decoding makes no difference.
> * **Mitigation (`core/shader_integrity.py`, `core/mpv_engine.py`)**: The engine reads libmpv's shader dumps and compares the translated HLSL constants against the GLSL literals. On a confirmed miscompile it rebuilds the video output on OpenGL (`gpu-api=opengl`, `gpu-context=win`), where GLSL goes straight to the GPU driver and the affected compiler is never used. The switch stays in effect until the player is restarted.
> * **No wrong-colour flash**: While the player is still on Direct3D 11, each newly opened file starts under an opaque black mpv OSD overlay. It is removed once the first frame has been presented and the shader compiler has been idle for 150 ms with no miscompile, or about half a second after the OpenGL switch. A 3-second cap guarantees the picture is never left blanked.
> * **Cost of the fallback**: Opening a file shows black slightly longer (a few tenths of a second on a clean open, up to roughly a second and a half when the renderer has to switch); hardware decoding moves from `d3d11va` to `nvdec` (other GPUs fall back to copy-back or software decoding); HDR pass-through is unavailable, so HDR sources are tone-mapped to SDR.
> * **Current default (`core/mpv_engine.py`)**: The player renders with **Vulkan** (`gpu-api=vulkan`, `gpu-context=winvk`), which does not use the affected translation step and can present HDR. Measured on this build: Direct3D 11 was wrong-coloured in about 1 of 5 idle-then-open launches (8 of 36); Vulkan was clean in 46 of 46. libplacebo constants are also passed as runtime values (`dynamic_constants=yes`), which removes most long literals from the shader text. If Vulkan cannot start (no loader, no device, or a libmpv without it) the player falls back to Direct3D 11 with the detection and OpenGL fallback described above, which are only active on that path.
> * **Permanent fix**: Replace `lib/mpv-2.dll` / `lib/libmpv-2.dll` with a libmpv build that does not have the defect. The detector stays silent on a healthy build and the player remains on Direct3D 11.

> [!CAUTION]
> **Dolby Vision Profile 20 D3D11 Surface Blowouts (Solid White / Red Viewport)**
> * **Symptom**: Pausing or seeking into complex Dolby Vision Profile 20 files (e.g. 4K MV-HEVC stereoscopic streams) could previously cause the video viewport to freeze into solid white (`[255, 255, 255]`) or saturated red (`[255, 0, 0]`).
> * **Mechanism**: In `vo="gpu-next"`, Direct3D 11 hardware decoding (`d3d11va`/`p010`) enters an uninitialized hardware texture state if seeking occurs while D3D11 swapchains or decoder handles are still allocating surfaces, or if dynamic runtime mutation of the `vo` driver property re-initializes D3D11 device contexts.
> * **Self-Healing Watchdog & 3-Strike Confirmation**: The player automatically samples decoded frames in memory via `screenshot-raw`. A **3-strike confirmation filter** requires 3 consecutive defect samples spaced at least 0.6s apart before triggering auto-recovery, preventing transient preroll buffers from triggering spurious restarts. When a persistent blowout is confirmed, the engine auto-recovers: it preserves the exact timestamp, audio track, and subtitle state, cleanly reinitializes the mpv player and D3D11 pipeline (`reinit_player()`), and reloads the file atomically via mpv's `start` property. A toast notification will alert you: `⚠️ Confirmed render defect (DEFECT: SOLID WHITE). Auto-restarting engine...` followed by `✅ Playback cleanly auto-recovered at MM:SS.`
> * **Win32 Canvas Zero-White Guarantee**: Viewport child widgets enforce `WA_NoSystemBackground` and explicit `#000000` canvas palettes, preventing Windows GDI from flashing unpainted white surfaces.

> [!CAUTION]
> **The Fluorescent Green / False Color Defect (Unshaped IPTPQc2 Color Matrix)**
> * **Symptom**: Characters and environments render in an intense, electric fluorescent green tint (green-to-red ratio $> 7:1$).
> * **Mechanism**: Dolby Vision Profile 20 and Profile 5 use the **IPTPQc2** color space ($I$: Intensity, $P$: Protoc [Green-Magenta], $T$: Tritan [Yellow-Blue]). If raw Protoc chroma passes unshaped without Dolby Vision matrix transforms, or if an erroneous external GLSL shader re-treats converted RGB as IPT, intense green saturation occurs.
> * **Level 8 Dynamic RPU Extraction**: The engine extracts dynamic Level 1, Level 3, and Level 8 trims in real time via `dovi_tool` using dedicated video stream mapping (`-map 0:v:0 -an -sn -dn`). This maps IPTPQc2 to Rec.709 SDR directly using the master grade's trim slope (gain) and power (exponent) without manual shaders or distortion.
> * **Protected Opening Logos**: Video timestamps below 5.0 seconds (e.g. Lucasfilm emerald green logo, Disney blue castle) are protected from defect classification, eliminating false-positive restart loops on opening titles.

> [!CAUTION]
> **Blue / Cyan Highlight Shift on Near-Zero Black Transitions**
> * **Symptom**: High-contrast white/colored elements in deep black scenes (e.g. logo fades in space) can briefly flare with an unnatural cyan/blue glow.
> * **Mechanism**: Libplacebo's dynamic peak estimation divider (`max_pq - min_pq`) approaches zero on multi-AU stereoscopic RPUs containing near-zero black frames (`0.000104 nits`), causing temporary gamut clipping in tone-mapping curve calculations.
> * **Status**: Mitigated by locking `hdr-compute-peak="no"` and routing tone curves through explicit Level 8 trims and calibrated curve knees (`target-peak=100`, `gamut-mapping-mode=perceptual`, `target-contrast=auto`).

> [!CAUTION]
> **Asynchronous Demuxer Seek Timing (`Error running mpv command: -12`)**
> * **Symptom**: Rapid programmatic seeks immediately after opening a file can trigger an `MPV_ERROR_COMMAND` (-12) exception if the container demuxer has not yet mapped the stream headers.
> * **Mitigation**: The player sets `player["start"] = f"{start_pos:.2f}"` prior to issuing `loadfile`, eliminating seek race conditions. Manual rapid seeking immediately upon file open should be avoided until initial playback begins.

---

## 🔬 3. Untested Features & Experimental Capabilities

The following features have been implemented in the codebase but **have not yet undergone rigorous production testing, hardware stress testing, or multi-environment verification**:

### 🥽 Stereoscopic 3D Playback Engine (Untested)
* **Status**: Implemented in [core/stereo3d_engine.py](file:///c:/Users/User/Downloads/MediaPlayer/core/stereo3d_engine.py) and [ui/stereo3d_dialog.py](file:///c:/Users/User/Downloads/MediaPlayer/ui/stereo3d_dialog.py), but **untested on physical 3D hardware**.
* **Untested Areas**:
  * Real-world 3D input format auto-detection across non-standard container tags (`H-SBS`, `Full-SBS`, `H-TAB`, `Half-OU`, `al`/`ar`).
  * Output presentation modes: Dubois Anaglyph (Red-Cyan, Amber-Blue, Green-Magenta), Row/Passive line-interleaved 3D displays, autostereoscopic column displays, and active 120Hz/144Hz sequential shutter glasses.
  * Real-time horizontal convergence / parallax adjustment slider (`Ctrl+Alt+Left` / `Ctrl+Alt+Right`, -60px to +60px) during high-bitrate playback.
  * Theatrical 3D DCP dual-codestream JPEG 2000 MXF extraction under sustained real-time playback.

### 🎨 3D LUT Calibration Support (Untested)
* **Status**: Implemented in [core/tonemap_engine.py](file:///c:/Users/User/Downloads/MediaPlayer/core/tonemap_engine.py) via `set_3d_lut()` / `toggle_3d_lut()` (`Ctrl+L`), but **untested with reference studio hardware**.
* **Untested Areas**:
  * Ingestion of third-party `.cube` and `.3dl` files with varying grid resolutions (17×17×17, 33×33×33, 65×65×65).
  * Film-print emulation LUTs (e.g. Kodak 2383 / Fuji 3513) stacked on top of active HDR tone-mapping curves.
  * Render latency, VRAM footprint, and gamut boundary clipping when 3D LUTs are combined with custom GLSL shaders or Direct HDR pass-through.

### 📺 IPTV Live TV & Streaming Engine (Untested)
* **Status**: Implemented in [core/iptv_manager.py](file:///c:/Users/User/Downloads/MediaPlayer/core/iptv_manager.py) and [ui/iptv_drawer.py](file:///c:/Users/User/Downloads/MediaPlayer/ui/iptv_drawer.py), but **completely untested in live streaming conditions**.
* **Untested Areas**:
  * Ingestion and parsing of large multi-thousand-channel M3U / M3U8 playlists with `#EXTINF` metadata.
  * Live streaming protocol resilience: HLS (`.m3u8`), RTSP, RTMP, UDP, and RTP under network latency, packet loss, or bitrate jitter.
  * Live category filtering, instant channel switching responsiveness, and memory retention during extended streaming sessions.
  * Streams requiring DRM (Widevine / FairPlay) or custom authentication tokens (unsupported).

### 🖥️ Hardware & Platform Edge Cases (Untested)
* **Non-NVIDIA Hardware (AMD Radeon & Intel Arc)**:
  * The `nvjpeg2k` hardware engine specifically leverages CUDA (`nvcuda.dll` / `nvjpeg2k_0.dll`). On AMD RDNA and Intel Arc GPUs, the system falls back to CPU / OpenCL. High-bitrate 4K 48fps HFR DCP playback on non-NVIDIA GPUs under sustained thermal load remains untested.
* **Multi-Monitor Mixed-DPI & Dynamic SDR/HDR Handoff**:
  * Dragging an active Dolby Vision or HDR10 playback window across a multi-monitor boundary (e.g. from an SDR Rec.709 60Hz display to an HDR10 Rec.2020 144Hz display) during live playback has not been verified for D3D11 swapchain re-negotiation.
* **True Physical 16+ Channel Cinema Sound Processors**:
  * Multi-channel IAB and IMAX 12.0 downmixing has been validated on 5.1/7.1 speaker systems and binaural headphones, but physical 16-to-32 discrete channel cinema hardware processors (QSC Q-SYS, Dolby CP950, Trinnov Ovation) via ASIO / WASAPI Exclusive remain untested in commercial theater auditoriums.
* **Encrypted Commercial DCPs (KDM RSA/AES Decryption)**:
  * The DCP engine currently ingests unencrypted (clear) DCPs (OV/VF). Decryption of commercial theatrical DCPs using KDMs (Key Delivery Messages) and Security Managers is not implemented.
* **Native AV2 Hardware Decoding**:
  * AOMedia Video 2 (AV2) runs on optimized multi-threaded CPU software decoding (`vd-lavc-threads=8`). Dedicated hardware ASIC acceleration for AV2 will require future GPU silicon drivers.
* **Cross-Platform OS (Linux / macOS)**:
  * The current binary distribution is engineered and optimized strictly for Windows 10/11 x64 (Direct3D 11, Win32 HWND embedding, and NVIDIA CUDA).

---

## ⌨️ 4. Essential Hotkey Cheat Sheet

| Category | Shortcut | Action | Status |
| :--- | :--- | :--- | :--- |
| **Playback & Speed** | `Space` | Play / Pause | Tested |
| | `S` | Stop Playback | Tested |
| | `Ctrl + Up` | Speed Up (+0.1x) (Natural Pitch Preserved) | Tested |
| | `Ctrl + Down` | Slow Down (-0.1x) (Natural Pitch Preserved) | Tested |
| | `Ctrl + 0` | Reset Speed to 1.0x Normal | Tested |
| | `.` / `,` | Next / Previous Frame (Frame Step) | Tested |
| | `Right` / `Left` | Jump Forward / Backward 10 seconds | Tested |
| | `Ctrl + G` | Go To... Precision Navigation (Timecode or Frame Jump) | Tested |
| | `Page Down` / `Up` | Next / Previous Chapter or DCP Reel | Tested |
| **A-B Loop & Trimmer** | `[` / `]` | Set Point A / Set Point B (Loop Range) | Tested |
| | `\` | Clear A-B Repeat Loop | Tested |
| | `Ctrl + Shift + E` | Lossless Clip Trimmer (Zero-Reencode Stream Copy) | Tested |
| **Color & QC** | `Ctrl + Shift + H` | Toggle Windows 11 Direct HDR Pass-Through | Tested |
| | `Ctrl + W` | Toggle Split-Screen A/B Comparison Wipe | Tested |
| | `T` | Toggle Color Science & Tonemapping Drawer | Tested |
| | `Ctrl + L` | Toggle 3D LUT (.cube / .3dl Look-Up Table) | **Untested** |
| **Stereoscopic 3D** | `Ctrl + Alt + 3` | Open Stereoscopic 3D Studio Dialog | **Untested** |
| | `Ctrl + Alt + Right`| Increase 3D Convergence / Parallax (+4 px) | **Untested** |
| | `Ctrl + Alt + Left` | Decrease 3D Convergence / Parallax (-4 px) | **Untested** |
| **Pan & Scan (PnS)** | `Num 9` / `Num 1` | Increase / Decrease Size (+5% / -5% Zoom) | Tested |
| | `Num 6` / `Num 4` | Increase / Decrease Width (+2% / -2% Aspect) | Tested |
| | `Num 8` / `Num 2` | Increase / Decrease Height (+2% / -2% Aspect) | Tested |
| | `Ctrl + Num 6/4/8/2`| Pan Viewport Right / Left / Up / Down | Tested |
| | `Ctrl + Num 5` | Center Viewport (Pan X=0, Y=0) | Tested |
| | `Alt + Num 3` / `1` | Rotate 90° Clockwise / Counter-Clockwise | Tested |
| | `Alt + Num 2` / `6` | Flip Vertically / Mirror (Horizontal Flip) | Tested |
| | `Num 5` | Reset PnS Geometry to 100% 1:1 | Tested |
| **Snapshot** | `Ctrl + S` | Lossless Tonemapped Active Image Area Snapshot | Tested |
| **Tracks & Subtitles**| `#` | Cycle Audio Track | Tested |
| | `Ctrl + A` | Add External Audio File... | Tested |
| | `J` / `Shift + J` | Next / Previous Subtitle Track | Tested |
| | `V` | Toggle Subtitles On / Off | Tested |
| | `Ctrl + U` | Add External Subtitle File... | Tested |
| | `Z` / `X` | Subtitle Delay (-100ms / +100ms) | Tested |

---

## ⚡ 5. Hardware Dependency

> [!IMPORTANT]
> **Hard Requirement for Theatrical DCP Playback: NVIDIA RTX 20-Series or Above**
> An **NVIDIA GPU (GeForce RTX 20-series / Turing architecture or newer)** is a **strict, non-negotiable hard requirement** for Digital Cinema Package (DCP) playback.
>
> * **Underlying Architecture**: The DCP playback engine relies on direct **NVIDIA nvJPEG2000 CUDA hardware acceleration** (`nvjpeg2k_0.dll` and `nvcuda.dll`) paired with custom assembly GPU PTX kernels (`xyz_to_rgb_graded`) to decode 12-bit DCI-XYZ JPEG 2000 codestreams in real time.
> * **Unsupported Hardware**: Legacy NVIDIA GPUs (GTX 10-series Pascal or earlier), AMD Radeon GPUs, and Intel Arc/Iris graphics **cannot** run the nvJPEG2000 hardware acceleration pipeline and will not achieve real-time 24.0/48.0 fps playback on Native 4K or 2K theatrical packages.

---

## 📦 6. Running from Source & Binary Prerequisites

> [!WARNING]
> **Mandatory Extraction of Binaries When Running From Source**:
> If you are running the program from source (e.g. via `python boob_player.py` or cloned from git):
> * The `lib/` folder contained inside the `binaries.zip` archive **must be extracted directly into the main root folder of the program working directory** (`MediaPlayer/lib/`).
> * **Why**: Core compiled dependencies (`mpv-2.dll`, `libmpv-2.dll`, `dovi_tool.exe`, `dav2d.exe`, `rav2d.exe`) exceed GitHub's 100MB per-file limit and cannot be stored uncompressed in git.
> * **Fatal Startup Error**: If this folder is not extracted into the main working directory, the player **will not run** and will immediately exit with `OSError: Cannot find mpv-1.dll, mpv-2.dll or libmpv-2.dll in your system %PATH%`.
