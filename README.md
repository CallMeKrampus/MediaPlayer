# BOOB Player 🎬

A high-fidelity media workstation combining the rendering precision of **mpv** (`gpu-next`), the format versatility of **VLC**, the deep geometric controls of **MPC-HC**, and direct **NVIDIA nvJPEG2000 hardware acceleration** for theatrical Digital Cinema Packages (DCPs).

Engineered with a refined Minimalist Studio Dark aesthetic (`#0d0e12`), **BOOB Player** is designed for cinema professionals, colorists, projectionists, and power users seeking reference-grade, distraction-free playback.

---

## ✨ Comprehensive Feature Matrix

### 1. 🎞️ Theatrical Digital Cinema Package (DCP) Hardware Engine
* **NVIDIA nvJPEG2000 CUDA Hardware Acceleration (`core/nvjpeg2k_engine.py`)**:
  * Direct hardware decoding on NVIDIA GeForce / RTX GPUs via `nvjpeg2k_0.dll` and the CUDA driver runtime (`nvcuda.dll`).
  * Decodes 12-bit DCI-XYZ essence frames at Native 4K Master (`4096×2160`) at 24.0 and 48.0 fps (HFR) with zero UI-thread stutter (hardware ceiling ~56–58 FPS on RTX 5050; 150+ FPS in 2K mode).
  * **Dedicated Prefetch Worker Thread** (`NVJPEG2K-PrefetchWorker`): Proactively indexes MXF footers, parses KLV essence containers, and lookahead-prefetches frames.
  * **High-Precision 4ms Presentation Timer**: Synchronized with continuous display clock and audio PLL.
* **DCP Cryptographic Integrity & Hash Verification (`core/dcp_verifier.py`, `ui/dcp_dialog.py`)**:
  * Multi-threaded block-level SHA-1 and SHA-256 validation against the Packing List (`PKL.xml`).
  * Detects missing, corrupted, truncated, or tampered picture/sound/subtitle MXF containers.
  * Real-time throughput reporting (MB/s), per-asset verification status (`PASSED`, `FAILED`, `MISSING`, `SIZE_MISMATCH`), and one-click package QC verdict.
* **DCP Decoding Quality Selection**:
  * `Level 0`: Native 4K Master hardware decoding (`4096×2160`).
  * `Level 1`: Pixel-Perfect 2K Sub-Band Match (`2048×1080`).
  * `Level 2`: 1K Wavelet Proxy (`1024×540`) for ultra-low resource environments.
* **Universal DCP Parser (`core/dcp_parser.py`)**:
  * Traverses SMPTE and Interop packages: `ASSETMAP` / `ASSETMAP.xml`, `VOLINDEX`, and `PKL` (Packing List XML).
  * Resolves multi-reel Composition Playlists (`CPL`), extracting Content Title, Kind, Edit Rate/FPS, Entry Point, Duration, and Screen Aspect Ratio.
  * Maps UUIDs to physical 12-bit JPEG 2000 picture MXFs, 24-bit PCM audio MXFs, and Dolby Atmos/IAB bitstreams.
* **Seamless Multi-Reel Transitions**:
  * Background pre-warming and lookahead caching across multi-reel feature films, eliminating reel boundary playback freezes.
* **IMAX Theatrical GT 1.43:1 Support**:
  * Automatically detects laser-squeezed IMAX GT packages and performs real-time anamorphic unsqueezing on the GPU canvas (`4096×2864` / `2048×1432`).
* **Interactive DCP Inspector (`ui/dcp_dialog.py`)**:
  * Two-tab suite: 1) Composition Reels & Spatial Audio breakdown, 2) QC Integrity & Cryptographic Hash Verification.

---

### 2. 🎨 Color Science & Advanced Tonemapping Engine
* **NVIDIA nvJPEG2000 CUDA PTX Assembly Shader**:
  * Custom assembly PTX kernel (`xyz_to_rgb_graded`) running directly on GPU stream multiprocessors.
  * **Theatrical DCI-XYZ (SMPTE 428-1 Gamma 2.6) -> BT.709 / sRGB Conversion** matrix:
  * **EPIQ PLF Laser Cinema Calibration**: Calibrated red-boost scaling ($R_f \times 0.86$) reproducing high-contrast theatrical laser projection.
* **3D LUT Calibration Support (`.cube` / `.3dl`, `Ctrl+L`)**:
  * Load professional 3D Look-Up Tables for reference studio monitors or film-print emulations (Kodak 2383 / Fuji 3513).
  * Direct zero-overhead hardware application via mpv `gpu-next` and OpenGL presentation stage.
* **Windows 11 Direct HDR Pass-Through (`Ctrl+Shift+H`)**:
  * Automatically signals the Windows 11 HDR swapchain (`target-colorspace-hint=yes`), outputting native BT.2020 PQ directly to HDR displays without SDR clipping or unwanted re-quantization.
* **Split-Screen A/B Comparison Wipe Tool (`Ctrl+W`)**:
  * Interactive vertical divider wipe (0% to 100% position) comparing processed/graded video against raw original bypass.
  * Draggable center handle directly on the video viewport with neon status indicators.
* **Dynamic Target Peak Luminance Curves**:
  * Non-linear knee compression mapping HDR/XYZ dynamic range to target nits:
    $$f(x) = \frac{x \cdot k_1}{1.0 + x \cdot k_2}$$
  * Target Luminance Steps: 80, 100, 150, 200, 300, 400, 600, and 1000 nits.
* **HDR & Dolby Vision Conversion (`core/tonemap_engine.py`)**:
  * Automatic source identification: HDR10, HDR10+, HLG (Hybrid Log-Gamma), Dolby Vision Profile 5 (IPT / ICtCp), and Standard SDR.
  * Tonemapping Algorithms: `BT.2390` (ITU-R standard), `Hable / ACES Filmic`, `Spline`, `Reinhard`, `Mobius`, `Linear`, `Clip`, and `Pass-Through`.
* **Live Studio Grading Surface (`ui/tonemap_dialog.py`, `T`)**:
  * Real-time sliders for Brightness (-100 to +100), Contrast (-100 to +100), Gamma (-100 to +100), Saturation (-100 to +100), and Hue (-180° to +180°).

---

### 3. 🥽 Stereoscopic 3D Playback Engine
* **Supported 3D Input Formats (`core/stereo3d_engine.py`)**:
  * `Auto-Detection`: Parses filenames and CPL tags (`H-SBS`, `HSBS`, `Full-SBS`, `H-TAB`, `Half-OU`, `Top-and-Bottom`, `Frame-Sequential`, `3D-DCP`).
  * `Side-by-Side (SBS)`: Half-Width (`sbs2l`/`sbs2r`) and Full-Width (`sbsl`/`sbsr`).
  * `Top-and-Bottom / Over-Under (TB/OU)`: Half-Height (`ab2l`/`ab2r`) and Full-Height (`abl`/`abr`).
  * `Frame Interleaved / Alternating Frames` (`al`/`ar`).
  * `Line Interleaved / Row Interleaved` (`irl`/`irr`).
  * `Column Interleaved` (`icl`/`icr`).
* **Real-Time Parallax / Horizontal Convergence Adjustment (`Ctrl+Alt+Left` / `Ctrl+Alt+Right`)**:
  * Live horizontal convergence offset slider (-60 to +60 px) correcting stereoscopic parallax fatigue, eye strain, or misalignment.
* **Output Presentation & Viewing Modes**:
  * **2D Mono Isolators**: Left Eye Only or Right Eye Only at full display resolution.
  * **Anaglyph (Glasses-Based 3D on Standard Displays)**:
    * `Anaglyph Red-Cyan (Dubois High-Quality Matrix)`: Least-squares color cross-talk elimination.
    * `Anaglyph Red-Cyan (Half Color & Full Color)`.
    * `Anaglyph Green-Magenta (Dubois)`.
    * `Anaglyph Amber-Blue (ColorCode 3D)`.
  * **Hardware 3D Displays & Projectors**:
    * `Line Interleaved (Row / Passive 3D)`: For passive polarized 3D TVs & monitors.
    * `Column Interleaved`: For autostereoscopic / glasses-free 3D screens.
    * `Checkerboard 3D`: For DLP 3D Ready projectors and televisions.
    * `Side-by-Side (SBS)` & `Top-and-Bottom (TB)`: For VR headsets and 3D TV inputs.
    * `Frame Interleaved / Sequential (120Hz/144Hz)`: For active shutter stereoscopic glasses.
  * **Swap Left / Right Eyes**: Instantly invert stereo parallax to correct inverted 3D media.
* **3D DCP Theatrical Support**:
  * Parses `<MainStereoscopicPicture>` tracks in SMPTE 429-10 / Interop 3D packages.
  * Dual-Codestream JPEG 2000 MXF extraction: reads paired Left and Right eye codestreams and dispatches the active eye on the GPU canvas.
* **Stereo 3D Studio Dialog (`Ctrl+Alt+3`, `ui/stereo3d_dialog.py`)**:
  * Dedicated calibration dialog for input format selection, presentation mode, eye swapping, and real-time parallax slider.

---

### 4. 📐 Pan & Scan (PnS) Frame Adjust System
* **MPC-HC Style Geometric Transform Matrix (`core/pns_controller.py`, `ui/pns_dialog.py`)**:
  * **Increase / Decrease Size**: Zoom in/out around screen center in 5% increments (`Num 9` / `Num 1`).
  * **Increase / Decrease Width**: Anamorphic horizontal stretching/shrinking in 2% increments (`Num 6` / `Num 4`).
  * **Increase / Decrease Height**: Anamorphic vertical stretching/shrinking in 2% increments (`Num 8` / `Num 2`).
  * **Move Right / Left / Up / Down**: Precision 2D pan offset navigation (`Ctrl+Num 6`, `4`, `8`, `2`).
  * **Center**: Snaps video back to display center (`Ctrl+Num 5`).
  * **Rotate Clockwise / Counter-Clockwise**: 90° stepped rotation around viewport center (`Alt+Num 3` / `Alt+Num 1`).
  * **Flip Vertically**: Vertical inverted mirror (`Alt+Num 2`).
  * **Mirror**: Horizontal flip (`Alt+Num 6`).
  * **Reset**: Restores 100% 1:1 original source geometry (`Num 5`).
* **Geometric Aspect Presets**:
  * `Scale to 16:9 TV`: Stretches 4:3 legacy content to 16:9 widescreen.
  * `Zoom to Widescreen`: 2.35:1 zoom removing letterbox bars.
  * `Zoom to Ultra-Widescreen`: 2.39:1 CinemaScope crop.
  * `3D SBS > 2D`: Crops and scales half side-by-side 3D to full 2D screen.
  * `3D TB > 2D`: Crops and scales top-and-bottom 3D to full 2D screen.
* **PnS Edit Dialog**:
  * Numerical spinbox control for Zoom (0.2x – 5.0x), Width Scale (0.2x – 5.0x), Height Scale (0.2x – 5.0x), Pan X (-1.0 to +1.0), Pan Y (-1.0 to +1.0), Rotation (0° – 359°), and Flip Checkboxes.

---

### 5. ⏱️ Navigation, Timeline & Usability (MPC-HC Essentials)
* **Seekbar Hover Thumbnail Preview (`core/thumbnail_generator.py`)**:
  * Hovering cursor over the seekbar displays an instantaneous floating preview box with a thumbnail image, formatted timecode, and chapter/reel title.
  * Multi-threaded background extraction and 120-item LRU cache using bundled FFmpeg and nvJPEG2000 Level 2.
* **Timeline Chapter & Reel Markers**:
  * Renders vertical tick marks along the seekbar for media chapters and DCP reel boundaries.
  * Chapter navigation: `Page Down` (Next Chapter), `Page Up` (Previous Chapter).
* **A-B Repeat Looping**:
  * Set Point A (`[`), Point B (`]`), or Clear (`\`).
  * High-visibility glowing amber range highlighted on the seekbar with triangular markers.
  * Automatic instantaneous loop-back seeking when playback reaches Point B.
* **Speed-Preserving Pitch Audio Correction (`Ctrl+Up` / `Ctrl+Down` / `Ctrl+0`)**:
  * Real-time playback speed control from `0.25x` to `4.0x` in `0.1x` steps.
  * Utilizes `scaletempo2` audio filtering to preserve natural vocal and music pitch without octave shift distortion.
* **MPC-HC Style Go To Dialog (`ui/goto_dialog.py`, `Ctrl+G`)**:
  * **Timecode Mode (`[hh:]mm:ss.ms`)**: Jump to specified times with explicit separators (e.g. `01:15:47.376`) or unseparated digits (e.g. typing `011547376` parses directly into `01:15:47.376`).
  * **Frame Mode (`frame, fps`)**: Takes two values separated by comma or space (e.g. `109029, 23.976` or `2400 24`). If only a frame number is entered, the active media's container frame rate is used automatically.

---

### 6. ✂️ Quick Extraction Tools: Lossless Stream Trimmer
* **Lossless Video Extractor (`core/clip_trimmer.py`, `ui/trim_dialog.py`, `Ctrl+Shift+E`)**:
  * Zero-reencode fast FFmpeg stream copy (`-c copy`) extracting designated `[In, Out]` time ranges in seconds.
  * Automatically pre-populates with active A-B repeat markers if set.
  * Preserves multi-channel audio tracks, HDR metadata, and subtitles with zero quality loss.
  * Background non-blocking execution with real-time progress bar.

---

### 7. 📸 Lossless Tonemapped Snapshot System
* **Native Resolution Capture (`core/mpv_engine.py`, `ui/main_window.py`)**:
  * Captures strictly at native source raster dimensions (e.g. 4096×2160 DCI 4K or 4096×1716 Scope) regardless of viewport display scaling or window resizing.
* **Active Image Area Bounding Box Cropping**:
  * Automatically detects and removes letterboxing (black bars top/bottom) and pillarboxing (black bars left/right).
* **Uncompressed Tonemapped Storage**:
  * Saved as raw uncompressed PNG (`screenshot_png_compression=0`) or uncompressed TIFF.
  * Retains applied tonemapping curves (HDR10, DV P5, DCI-XYZ -> sRGB) and user grading adjustments with RGB channel protection.
* **Save Prompt & Directory Memory**:
  * Interactive file save dialog defaulting to timestamped filename (`Snapshot_YYYYMMDD_HHMMSS.png`), remembering the last destination directory (`Ctrl+S`).

---

### 8. 🎧 Immersive Audio Bitstream (IAB / Atmos) & Spatial Visualizer
* **SMPTE ST 2098-2 Cinema Sound (`core/iab_engine.py`)**:
  * Decodes bed channels (5.1, 7.1, 9.1, 13.1) and dynamic spatial audio point objects with 3D cartesian coordinates $(x, y, z)$, gain, and spread.
  * Real-time binaural headphone virtualization (`sofalizer` / HRTF) and 5.1/7.1 speaker downmixing.
* **Interactive 3D Auditorium Visualizer (`ui/iab_visualizer_dialog.py`, `Ctrl+M`)**:
  * 3D wireframe auditorium rendering stage, screen, surround speakers, ceiling speakers, and listener position.
  * **View Presets**: Dolby RMU (3D Perspective), Top-Down (Auditorium Plan), Front Screen, Side Elevation.
  * **Interactive Mouse Controls**: Left-drag to orbit/rotate, right-drag to pan, mouse wheel for infinite smooth zoom.
  * Hover tooltips showing Object ID, Gain (dB), Spatial Coordinates, and Spread.

---

### 9. 🎚️ Audio Pipeline & Multi-Angle Track Management
* **Format Support**: Linear PCM (up to 24-bit 96kHz 16-channel), Dolby TrueHD, Dolby Digital Plus / Atmos (E-AC-3), DTS-HD Master Audio, FLAC, ALAC, AAC, MP3, Opus.
* **IMAX Theatrical Audio Mapping**: IMAX 5.0 and IMAX 12.0 (12-channel discrete theatrical mix) automatic channel routing and center/top-surround downmixing.
* **External Audio Loading (`Ctrl+A`)**: Ingest commentary, alternate dubs, or separate cinema sound tracks (.wav, .flac, .mp3, .m4a, .ac3, .dts).
* **Audio Track Cycling & Selector**: Cycle audio tracks with `#`; Track Selector Dialog (`Ctrl+T`).
* **Audio Synchronization (`ui/audio_sync_dialog.py`)**: Millisecond-accurate audio delay adjustment (-10,000ms to +10,000ms).

---

### 10. 💬 Subtitle Engine & Timed Text Synchronization
* **DCP Theatrical Subtitles (`core/dcp_subtitle_engine.py`)**: Parses SMPTE 428-7 XML and Interop XML timed text subtitle reels with sub-millisecond binary search indexing.
* **External Subtitle File Ingestion (`Ctrl+U`)**: SubRip (`.srt`), Advanced SubStation Alpha (`.ass` / `.ssa`), WebVTT (`.vtt`), MicroDVD (`.sub`), and VobSub (`.idx`/`.sub`).
* **Subtitle Styling & Protection**: Vector glyph rendering on OpenGL viewport with dark drop shadows; never dimmed by HDR tonemapping curves.
* **Subtitle Controls**: Next track: `J`; Previous track: `Shift+J`; Live delay: `+100ms` (`X`), `-100ms` (`Z`); Subtitle Sync Dialog (`ui/subtitle_sync_dialog.py`).

---

### 11. 📺 IPTV Live TV & Playlist Management
* **IPTV Streaming Drawer (`core/iptv_manager.py`, `ui/iptv_drawer.py`)**:
  * Loads M3U / M3U8 playlists with `#EXTINF` metadata parsing (channel title, category group, logo, resolution).
  * Category filtering (News, Sports, Cinema, Entertainment) and live search bar.
  * Protocols: HLS (`.m3u8`), RTSP, RTMP, UDP, RTP, HTTP/HTTPS progressive, and `yt-dlp` stream extraction.
* **Persistent Playlist Drawer (`core/playlist_manager.py`, `ui/playlist_drawer.py`)**:
  * Drag-and-drop file adding, reordering, duplicate removal, search, and loop/shuffle modes.

---

### 12. 🔍 Diagnostic Tools, Next-Gen Codecs & Codec Inspection
* **Next-Gen AOMedia Video 2 (AV2) Codec Architecture**:
  * Direct ingestion and playback of AV2 bitstreams and containers (`.obu`, `.av2`, `.mp4`, `.mkv`, `.webm`).
  * Deep container FourCC & tag recognition (`av02`, `av2`, `aom-av2`, `libaom-av2`, `V_AV2`, `V_AOM_AV2`).
  * Optimized multi-threaded CPU software decoding fallback (`vd-lavc-threads=8`) with safe hardware probing.
  * Real-time metadata inspection, HUD telemetry, and OSD display badge: `AOMedia AV2 (Next-Gen)`.
* **Codec Information Dialog (`ui/codec_info_dialog.py`, `Ctrl+I`)**:
  * Container details: Format, duration, bitrate, file size.
  * Video streams: Codec, resolution, aspect ratio, frame rate, pixel format, bit depth, color space, transfer characteristics (TRC), color primaries, HDR status (PQ, HLG, SDR, DCI-XYZ).
  * Audio streams: Codec, channels, sample rate, bit depth, language.
  * Subtitle streams: Codec, language, track index.
* **Minimalist Studio Dark Theme & Dynamic Engine (`ui/theme.py`, `View → Theme`)**:
  * Precision-engineered neutral charcoal & obsidian palette (`#0d0e12`), hairline 1px borders (`#262732`), and subtle monochrome controls.
  * Zero neon glare, distraction-free playback surface, and sleek semi-transparent floating OSC island.
  * Live Theme Switcher (`View → 🎨 Theme`): Toggle on-the-fly between **Minimalist Studio Dark** (Default) and **Cyberpunk Dark**.
* **GPU Hardware Detection (`core/gpu_detector.py`)**: Identifies NVIDIA GeForce/RTX, AMD Radeon, and Intel Arc/Iris GPUs, reporting CUDA/nvJPEG2000 acceleration status.
* **DCP Benchmark Utility**: Real-time decode benchmark measuring GPU throughput (fps) and milliseconds per frame across native 4K DCI-XYZ frames.
* **Video Rendering Stats Overlay (`Shift+I`)**: Real-time HUD showing frame drop rate, display FPS, demuxer buffer, and GPU shader performance.

---

### 13. 📦 Portable Build & Ultra-Compression Packaging
* **cx_Freeze Distribution (`setup.py`, `build_exe.py`)**:
  * Completely self-contained standalone executable bundle without PyInstaller.
  * Bundles portable runtime DLLs, GLSL shaders, and standalone FFmpeg/FFprobe binaries with strict exclusion of local media and test DCPs.
  * Deadweight pruned: removes duplicate 116MB DLLs, unused OpenCV (`cv2`), and unused Qt5/QML modules, reducing uncompressed directory size from ~990 MB to ~650 MB.
  * **Automated 7-Zip LZMA2 Solid Archiving** (`python build_exe.py --build --archive`): Produces an ultra-compact **~175–190 MB** distribution archive (75%+ space saved) with 100% lossless binary integrity.

---

## ⌨️ Complete Keyboard Shortcut Reference

| Category | Shortcut | Action |
| :--- | :--- | :--- |
| **Playback & Speed** | `Space` | Play / Pause |
| | `S` | Stop Playback |
| | `Ctrl + Up` | **Speed Up (+0.1x)** (Natural Pitch Preserved) |
| | `Ctrl + Down` | **Slow Down (-0.1x)** (Natural Pitch Preserved) |
| | `Ctrl + 0` | **Reset Speed** to 1.0x Normal |
| | `.` | Next Frame (Frame Step Forward) |
| | `,` | Previous Frame (Frame Step Backward) |
| | `Right Arrow` | Jump Forward 10 seconds |
| | `Left Arrow` | Jump Backward 10 seconds |
| | `Ctrl + G` | **Go To... Precision Navigation Dialog** (Timecode or Frame Jump) |
| | `Page Down` | **Next Chapter / Reel** |
| | `Page Up` | **Previous Chapter / Reel** |
| **A-B Repeat & Trimmer** | `[` | **Set Point A** (Start of Repeat Loop) |
| | `]` | **Set Point B** (Start Looping A-B) |
| | `\` | **Clear A-B Repeat Loop** |
| | `Ctrl + Shift + E`| **Lossless Clip Trimmer** (Zero-Reencode Stream Copy) |
| **Color & QC** | `Ctrl + L` | **Toggle 3D LUT** (.cube / .3dl Look-Up Table) |
| | `Ctrl + Shift + H`| **Toggle Windows 11 Direct HDR Pass-Through** |
| | `Ctrl + W` | **Toggle Split-Screen A/B Comparison Wipe** |
| | `T` | Toggle Color Science & Tonemapping Drawer |
| **Stereoscopic 3D** | `Ctrl + Alt + 3` | Open Stereoscopic 3D Studio & Calibration Dialog |
| | `Ctrl + Alt + Right`| **Increase 3D Convergence / Parallax** (+4 px) |
| | `Ctrl + Alt + Left` | **Decrease 3D Convergence / Parallax** (-4 px) |
| **Pan & Scan (PnS)** | `Num 9` | Increase Size (+5% Zoom) |
| | `Num 1` | Decrease Size (-5% Zoom) |
| | `Num 6` | Increase Width (+2% Aspect Stretch) |
| | `Num 4` | Decrease Width (-2% Aspect Shrink) |
| | `Num 8` | Increase Height (+2% Aspect Stretch) |
| | `Num 2` | Decrease Height (-2% Aspect Shrink) |
| | `Ctrl + Num 6` | Pan Viewport Right |
| | `Ctrl + Num 4` | Pan Viewport Left |
| | `Ctrl + Num 8` | Pan Viewport Up |
| | `Ctrl + Num 2` | Pan Viewport Down |
| | `Ctrl + Num 5` | Center Viewport (Pan X=0, Y=0) |
| | `Alt + Num 3` | Rotate 90° Clockwise |
| | `Alt + Num 1` | Rotate 90° Counter-Clockwise |
| | `Alt + Num 2` | Flip Vertically |
| | `Alt + Num 6` | Mirror (Horizontal Flip) |
| | `Num 5` | Reset PnS Geometry to 100% 1:1 |
| **Snapshot** | `Ctrl + S` | **Take Tonemapped Lossless Snapshot** (Active Image Area) |
| **Tracks & Media** | `_` | Cycle Video Track / Multi-Angle |
| | `#` | Cycle Audio Track |
| | `Ctrl + A` | Add External Audio File... |
| | `J` | Next Subtitle Track |
| | `Shift + J` | Previous Subtitle Track |
| | `Ctrl + U` | Add External Subtitle File... |
| | `Z` | Subtitle Delay: -100ms |
| | `X` | Subtitle Delay: +100ms |
| | `Ctrl + T` | Open Track & Stream Selector Dialog |
| **Audio Spatializer** | `Ctrl + M` | Open IAB / Atmos Spatial Audio Visualizer |
| **Diagnostics & DCP** | `Ctrl + D` | **DCP Inspector & QC Cryptographic Hash Verification** |
| | `Ctrl + I` | Open Media & Codec Information Dialog |
| | `Shift + I` | Toggle Video Rendering Stats Overlay |
| **View & Docks** | `F` or `F11` | Toggle Fullscreen |
| | `Escape` | Exit Fullscreen |
| | Mouse Wheel | Volume Up / Down (0% – 130%) |

---

## 🚀 Packaging & Launch Commands

```powershell
# Launch default player from source
python boob_player.py

# Verify cx_Freeze packaging readiness and asset inventory
python build_exe.py --check

# Build standalone portable executable into dist/BOOBPlayer
python build_exe.py --build

# Build and generate ultra-compact LZMA2 .7z distribution archive
python build_exe.py --build --archive

# Run all 128 automated unit tests
python -m unittest discover tests -v
```

---

## 📂 Project Architecture

```
MediaPlayer/
├── boob_player.py              # Application entry point & CLI options
├── build_exe.py                # Standalone packager, pre-flight check, and 7z compressor
├── setup.py                    # cx_Freeze packaging configuration
├── core/
│   ├── mpv_engine.py           # Embedded libmpv backend (gpu-next, hwdec, 1GB cache, speed/A-B/chapters)
│   ├── nvjpeg2k_engine.py      # NVIDIA nvJPEG2000 CUDA hardware engine & PTX color shader
│   ├── dcp_parser.py           # SMPTE & Interop DCP parser, CPL/PKL/ASSETMAP resolver
│   ├── dcp_verifier.py         # Multi-threaded cryptographic PKL hash verification engine
│   ├── dcp_subtitle_engine.py  # SMPTE 428-7 / Interop XML subtitle parser
│   ├── stereo3d_engine.py      # Stereoscopic 3D engine (SBS, TB, Dubois, polarized, parallax, 3D DCP)
│   ├── clip_trimmer.py         # Zero-reencode fast FFmpeg stream copy trimmer
│   ├── thumbnail_generator.py  # Asynchronous frame extractor and LRU seekbar thumbnail cache
│   ├── pns_controller.py       # Pan & Scan geometry controller (mpv properties & OpenGL matrix)
│   ├── iab_engine.py           # SMPTE ST 2098-2 IAB bitstream parser & 3D spatial routing
│   ├── iptv_manager.py         # M3U/M3U8 parser & live stream manager
│   ├── tonemap_engine.py       # Color pipeline (3D LUT, HDR direct pass-through, DV P5, HDR10, DCI-XYZ)
│   ├── playlist_manager.py     # Play queue, repeat, shuffle, history
│   ├── gpu_detector.py         # GPU detection (NVIDIA RTX, AMD Radeon, Intel Arc)
│   ├── media_inspector.py      # VLC-style deep ffprobe stream inspector
│   └── app_paths.py            # Runtime path and portable DLL resolver
├── ui/
│   ├── main_window.py          # Master dark studio window, menus & context menu
│   ├── video_widget.py         # Native video viewport, NVJPEG2KCanvas & comparison wipe
│   ├── osc_controls.py         # Floating on-screen controller HUD, seekbar thumbnails & chapters
│   ├── goto_dialog.py          # MPC-HC style Go To navigation dialog
│   ├── pns_dialog.py           # Pan & Scan numerical edit dialog
│   ├── stereo3d_dialog.py      # Stereoscopic 3D studio & parallax calibration dialog
│   ├── trim_dialog.py          # Lossless Clip Trimmer dialog
│   ├── iab_visualizer_dialog.py# 3D interactive spatial audio auditorium visualizer
│   ├── iptv_drawer.py          # Live TV channel drawer & category selector
│   ├── tonemap_dialog.py       # Color & tonemapping drawer with live sliders
│   ├── dcp_dialog.py           # Digital Cinema Package inspector & cryptographic QC suite
│   ├── codec_info_dialog.py    # VLC-style stream and codec information dialog
│   ├── audio_sync_dialog.py    # External audio loader & delay sync
│   ├── subtitle_sync_dialog.py # External subtitle loader & delay sync
│   ├── tracks_dialog.py        # Track and stream selector dialog
│   └── theme.py                # Strict Dark Mode QSS stylesheet
├── shaders/
│   ├── dci_xyz_to_srgb.glsl    # High-precision GLSL shader for DCP DCI-XYZ to sRGB
│   └── dolby_vision_p5.glsl    # GLSL shader for Dolby Vision P5 IPTPQc2
└── tests/
    ├── test_dcp_verifier.py       # Cryptographic PKL SHA-1 / SHA-256 QC verification tests
    ├── test_features_suite.py     # 3D LUT, HDR pass-through, split wipe, speed, A-B, parallax tests
    ├── test_nvjpeg2k_playback.py  # nvJPEG2000 real-time playback & tonemapping tests
    ├── test_goto_and_pns.py       # Go To dialog & PnS geometric transform tests
    ├── test_stereo3d.py           # Stereoscopic 3D & 3D DCP tests
    ├── test_snapshot.py           # Lossless active-area tonemapped snapshot tests
    ├── test_iab_visualizer.py     # 3D spatial audio visualizer tests
    └── ...                        # 128 total automated unit tests
```
