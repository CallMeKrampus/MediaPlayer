# 💎 Dolby Vision Tonemapper Plugin for IINA

A professional Dolby Vision Profile 5 (IPTPQc2) to Rec.709 SDR & HDR Tonemapper plugin for **IINA** on macOS.

---

## 🌟 Why This Plugin is Essential for IINA

Dolby Vision **Profile 5** streams (commonly found in Web-DL releases from Netflix, Disney+, Apple TV+, and Max) use the proprietary **IPTPQc2** color space with SMPTE ST 2084 (PQ) dynamic transfer curves instead of standard Rec.709 or Rec.2020 YCbCr. 

When played on standard Mac players or versions of IINA/mpv without a working DOVI RPU pipeline:
* **The Infamous Purple & Green Screen**: The player treats IPT channels as YCbCr, causing actors' faces and skies to turn intense magenta and green.
* **Overly Dark / Washed-Out Highlights**: Even when detected, default generic tonemappers clip or darken the midtones severely.

### ✨ What This Plugin Does
1. **Zero-Lag Auto-Detection**: Monitors stream metadata (`video-params/colormatrix`, `dvh1`/`dvhe` FourCC tags, and track side-data).
2. **Hardware GLSL Reshaper**: Hooks directly into mpv's GPU render pipeline (`MAIN` hook) to convert IPTPQc2 $\to$ LMS $\to$ BT.2020 $\to$ Rec.709 Linear with calibrated soft-knee tonemapping and sRGB transfer functions.
3. **libplacebo Optimization**: Sets optimal `tone-mapping=clip`, `target-prim=bt.709`, and `gamut-mapping-mode=clip` to prevent peak dimming.
4. **Target Color Space Flexibility**:
   * **Rec.709 SDR**: For standard Mac displays (MacBook Air, iMac) and external monitors.
   * **HDR10 (BT.2020 PQ)**: For MacBook Pro Liquid Retina XDR and Apple Pro Display XDR.
   * **HLG (BT.2020 HLG)**: For broadcast workflows.
5. **Clean Revert**: Instantly restores default player properties when switching to standard SDR or HDR10 videos.

---

## 🚀 Installation Guide

### Method 1: Install Local Package (`.iinaplgz`) — Recommended
1. Locate the packaged `iina-plugin-dv-tonemap.iinaplgz` file.
2. Open **IINA**.
3. Open **Settings** (`Cmd + ,`) and navigate to the **Plugins** tab.
4. Click **Install from a local package...** (or simply drag and drop the `.iinaplgz` file into the IINA window).
5. Enable the plugin!

### Method 2: Manual Folder Install (macOS)
1. In Finder, press `Cmd + Shift + G` (Go to Folder) and enter:
   ```text
   ~/Library/Application Support/com.colliderli.iina/plugins/
   ```
2. Copy the `iina-plugin-dv-tonemap` folder into this directory.
3. Restart IINA.

---

## ⚙️ Configuration & Menu Controls

### IINA Settings Panel
Navigate to **IINA Settings → Plugins → Dolby Vision Tonemapper**:
* **Enable / Disable**: Global toggle for auto-detection.
* **Processing Mode**:
  * `Smart Auto (Recommended)`: Auto-applies optimal libplacebo settings and the hardware shader.
  * `Force GLSL Shader`: Directly fixes purple/green tint on any display.
  * `Native libplacebo`: mpv built-in pipeline.
* **Target Output**: Rec.709 SDR, HDR10, or HLG.
* **Tonemap Roll-Off**: `Clip` (punchy SDR highlights), `Spline`, `BT.2390`, or `Reinhard`.

### Quick Menu
Access **Plugin → 💎 Dolby Vision Tonemapper** in IINA's menu bar to switch modes or re-evaluate the currently loaded stream on the fly.
