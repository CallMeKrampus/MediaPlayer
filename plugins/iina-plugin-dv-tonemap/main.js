/**
 * Dolby Vision Profile 5 (IPTPQc2) to SDR/HDR Tonemapper for IINA
 * Developed by BOOB Player Team
 * 
 * Auto-detects Dolby Vision Profile 5 streams, reshapes IPTPQc2 color space,
 * and fixes green/purple color distortion on macOS using hardware GLSL shaders
 * and libplacebo tuning.
 */

const { core, mpv, event, menu, preferences, file, utils, console } = iina;

// Embedded reference GLSL shader for zero-dependency standalone installation
const GLSL_SHADER_SOURCE = `//!HOOK MAIN
//!BIND HOOKED
//!DESC Dolby Vision Profile 5 (IPTPQc2) to Rec.709 SDR Reshaper & Tonemapper

// PQ (SMPTE ST 2084) constants
const float m1 = 2610.0 / 4096.0 / 4.0;
const float m2 = 2523.0 / 4096.0 * 128.0;
const float c1 = 3424.0 / 4096.0;
const float c2 = 2413.0 / 4096.0 * 32.0;
const float c3 = 2392.0 / 4096.0 * 32.0;

vec3 pq_to_linear(vec3 pq) {
    vec3 p = pow(clamp(pq, 0.0, 1.0), vec3(1.0 / m2));
    vec3 num = max(p - c1, 0.0);
    vec3 den = c2 - c3 * p;
    return pow(num / den, vec3(1.0 / m1)) * 10000.0;
}

vec4 hook() {
    vec4 c = HOOKED_tex(HOOKED_pos);
    
    // c.rgb represents IPTPQc2 components (I in [0,1], P and T centered around 0.5)
    float I = c.r;
    float P = c.g - 0.5;
    float T = c.b - 0.5;
    
    // Matrix: IPT-PQ -> LMS_PQ (Dolby ICtCp / IPTPQc2 inverse matrix)
    float L_pq = I + 0.097569 * P + 0.205226 * T;
    float M_pq = I - 0.113880 * P + 0.133217 * T;
    float S_pq = I + 0.032615 * P - 0.676890 * T;
    
    vec3 lms_pq = vec3(L_pq, M_pq, S_pq);
    vec3 lms_lin = pq_to_linear(lms_pq);
    
    // LMS to Rec.2020 Matrix
    mat3 lms_to_bt2020 = mat3(
         3.224645, -0.627763,  0.076044,
        -1.748318,  1.678015, -0.284856,
        -0.476327, -0.050252,  1.208812
    );
    vec3 bt2020_lin = max(lms_to_bt2020 * lms_lin, vec3(0.0));
    
    // Rec.2020 to Rec.709 Matrix
    mat3 bt2020_to_rec709 = mat3(
         1.6605, -0.1246, -0.0182,
        -0.5876,  1.1329, -0.1006,
        -0.0728, -0.0083,  1.1187
    );
    vec3 rec709_lin = max(bt2020_to_rec709 * bt2020_lin, vec3(0.0));
    
    // Highlights roll-off tonemapper (1000 nits -> 100 nits SDR)
    vec3 x = rec709_lin / 100.0;
    vec3 mapped = x / (1.0 + x * 0.4);
    
    // Rec.709 transfer curve
    vec3 sdr;
    sdr.r = (mapped.r <= 0.0031308) ? (mapped.r * 12.92) : (1.055 * pow(mapped.r, 1.0 / 2.4) - 0.055);
    sdr.g = (mapped.g <= 0.0031308) ? (mapped.g * 12.92) : (1.055 * pow(mapped.g, 1.0 / 2.4) - 0.055);
    sdr.b = (mapped.b <= 0.0031308) ? (mapped.b * 12.92) : (1.055 * pow(mapped.b, 1.0 / 2.4) - 0.055);
    
    return vec4(clamp(sdr, 0.0, 1.0), c.a);
}
`;

// State tracking
let isApplied = false;
let appliedShaderPath = null;
let originalProps = null;

/**
 * Ensures the GLSL shader file is available on disk under plugin data directory.
 */
function ensureShaderOnDisk() {
  try {
    const dataShaderPath = "@data/dolby_vision_p5.glsl";
    if (!file.exists(dataShaderPath)) {
      file.write(dataShaderPath, GLSL_SHADER_SOURCE);
      console.log(`[DV-Tonemap] Wrote shader to ${dataShaderPath}`);
    }
    return utils.resolvePath(dataShaderPath);
  } catch (e) {
    console.error(`[DV-Tonemap] Failed to ensure shader on disk: ${e}`);
    return null;
  }
}

/**
 * Detects whether the currently playing video is Dolby Vision Profile 5.
 */
function isDolbyVisionProfile5() {
  try {
    // 1. mpv colormatrix inspection
    const colormatrix = (mpv.getString("video-params/colormatrix") || "").toLowerCase();
    if (colormatrix.includes("dolbyvision") || colormatrix.includes("dovi") || colormatrix.includes("ipt")) {
      return true;
    }

    // 2. mpv video format FourCC tag
    const videoFormat = (mpv.getString("video-format") || "").toLowerCase();
    if (videoFormat === "dvh1" || videoFormat === "dvhe") {
      return true;
    }

    // 3. Track-list metadata & side data inspection
    const trackList = mpv.getNative("track-list");
    if (Array.isArray(trackList)) {
      for (const track of trackList) {
        if (track.type === "video") {
          const title = (track.title || "").toLowerCase();
          const codec = (track.codec || "").toLowerCase();
          if (
            title.includes("dovi") ||
            title.includes("dolby vision") ||
            title.includes("profile 5") ||
            title.includes("dv_hevc")
          ) {
            return true;
          }
          if (codec === "dvh1" || codec === "dvhe") {
            return true;
          }
        }
      }
    }

    // 4. Filename & path heuristic fallback
    const path = (mpv.getString("path") || "").toLowerCase();
    const filename = (mpv.getString("filename") || "").toLowerCase();
    const mediaName = `${path} ${filename}`;
    if (/(?:dv[._-]?(?:p|profile)?0?5|dovi[._-]?0?5|dolby[._-]?vision[._-]?profile[._-]?0?5)/i.test(mediaName)) {
      return true;
    }
  } catch (err) {
    console.error(`[DV-Tonemap] Detection error: ${err}`);
  }
  return false;
}

/**
 * Saves original player property states before overriding.
 */
function captureOriginalProperties() {
  if (originalProps !== null) return; // already captured
  try {
    originalProps = {
      toneMapping: mpv.getString("tone-mapping") || "auto",
      targetPrim: mpv.getString("target-prim") || "auto",
      targetTrc: mpv.getString("target-trc") || "auto",
      targetPeak: mpv.getString("target-peak") || "auto",
      hdrComputePeak: mpv.getString("hdr-compute-peak") || "auto",
      gamutMappingMode: mpv.getString("gamut-mapping-mode") || "auto",
      glslShaders: mpv.getString("glsl-shaders") || ""
    };
  } catch (e) {
    console.warn(`[DV-Tonemap] Could not capture all properties: ${e}`);
  }
}

/**
 * Restores original player property states.
 */
function restoreOriginalProperties() {
  if (!isApplied && originalProps === null) return;

  try {
    // Remove GLSL shader if active
    if (appliedShaderPath) {
      removeShader(appliedShaderPath);
      appliedShaderPath = null;
    }

    if (originalProps) {
      if (originalProps.toneMapping) mpv.set("tone-mapping", originalProps.toneMapping);
      if (originalProps.targetPrim) mpv.set("target-prim", originalProps.targetPrim);
      if (originalProps.targetTrc) mpv.set("target-trc", originalProps.targetTrc);
      if (originalProps.targetPeak) mpv.set("target-peak", originalProps.targetPeak);
      if (originalProps.hdrComputePeak) mpv.set("hdr-compute-peak", originalProps.hdrComputePeak);
      if (originalProps.gamutMappingMode) mpv.set("gamut-mapping-mode", originalProps.gamutMappingMode);
      originalProps = null;
    }
    console.log("[DV-Tonemap] Original player properties restored.");
  } catch (e) {
    console.error(`[DV-Tonemap] Failed to restore properties: ${e}`);
  }
  isApplied = false;
}

/**
 * Appends a shader path to mpv's glsl-shaders property.
 */
function appendShader(shaderPath) {
  try {
    const current = mpv.getString("glsl-shaders") || "";
    if (!current.includes(shaderPath)) {
      mpv.command("change-list", ["glsl-shaders", "append", shaderPath]);
    }
  } catch (e) {
    try {
      mpv.set("glsl-shaders", shaderPath);
    } catch (e2) {
      console.error(`[DV-Tonemap] Failed to set shader: ${e2}`);
    }
  }
}

/**
 * Removes a shader path from mpv's glsl-shaders property.
 */
function removeShader(shaderPath) {
  try {
    mpv.command("change-list", ["glsl-shaders", "remove", shaderPath]);
  } catch (e) {
    try {
      const current = mpv.getString("glsl-shaders") || "";
      if (current.includes(shaderPath)) {
        const parts = current.split(":").filter(p => p && p !== shaderPath);
        mpv.set("glsl-shaders", parts.join(":"));
      }
    } catch (e2) {}
  }
}

/**
 * Applies Dolby Vision Profile 5 tonemapping based on user preferences.
 */
function applyDVTonemapping() {
  const enabled = preferences.get("enabled");
  if (enabled === false) {
    restoreOriginalProperties();
    return;
  }

  const mode = preferences.get("mode") || "auto";
  const target = preferences.get("target") || "sdr";
  const algorithm = preferences.get("algorithm") || "clip";
  const showOSD = preferences.get("show_osd") !== false;

  captureOriginalProperties();

  try {
    // 1. Target Color Space Configuration
    if (target === "hdr10") {
      mpv.set("target-prim", "bt.2020");
      mpv.set("target-trc", "pq");
      mpv.set("target-peak", 1000);
      mpv.set("tone-mapping", algorithm);
      mpv.set("gamut-mapping-mode", "clip");
      mpv.set("hdr-compute-peak", "no");
    } else if (target === "hlg") {
      mpv.set("target-prim", "bt.2020");
      mpv.set("target-trc", "hlg");
      mpv.set("target-peak", 1000);
      mpv.set("tone-mapping", algorithm);
      mpv.set("gamut-mapping-mode", "clip");
      mpv.set("hdr-compute-peak", "no");
    } else {
      // SDR Rec.709
      mpv.set("target-prim", "bt.709");
      mpv.set("target-trc", "auto");
      mpv.set("target-peak", "auto");
      mpv.set("tone-mapping", algorithm);
      mpv.set("gamut-mapping-mode", "clip");
      mpv.set("hdr-compute-peak", "no");
    }

    // 2. Hardware GLSL Shader Reshaper
    // In 'shader' mode, or in 'auto' mode when mapping to SDR, apply custom reshaper
    if (mode === "shader" || (mode === "auto" && target === "sdr")) {
      const shaderDiskPath = ensureShaderOnDisk();
      if (shaderDiskPath) {
        appendShader(shaderDiskPath);
        appliedShaderPath = shaderDiskPath;
      }
    } else if (appliedShaderPath) {
      removeShader(appliedShaderPath);
      appliedShaderPath = null;
    }

    isApplied = true;
    console.log(`[DV-Tonemap] Applied: mode=${mode}, target=${target}, algorithm=${algorithm}`);

    if (showOSD) {
      const targetLabel = target === "hdr10" ? "HDR10 (Rec.2020 PQ)" : target === "hlg" ? "HLG (Rec.2020)" : "Rec.709 SDR";
      core.osd(`💎 Dolby Vision P5 → ${targetLabel} Applied`);
    }
  } catch (err) {
    console.error(`[DV-Tonemap] Error applying tonemap: ${err}`);
  }
}

/**
 * Handles media inspection and automatic triggering.
 */
function checkAndProcessMedia() {
  const enabled = preferences.get("enabled");
  if (enabled === false) {
    if (isApplied) restoreOriginalProperties();
    return;
  }

  const isDV = isDolbyVisionProfile5();
  if (isDV) {
    console.log("[DV-Tonemap] Dolby Vision Profile 5 detected!");
    applyDVTonemapping();
  } else {
    if (isApplied) {
      console.log("[DV-Tonemap] Non-DV stream loaded. Restoring default color pipeline.");
      restoreOriginalProperties();
    }
  }
}

/**
 * Builds dynamic interactive menu for IINA Plugin menu.
 */
function buildMenu() {
  const rootMenu = menu.item("💎 Dolby Vision Tonemapper");

  const enabled = preferences.get("enabled") !== false;
  const currentMode = preferences.get("mode") || "auto";
  const currentTarget = preferences.get("target") || "sdr";
  const currentAlgorithm = preferences.get("algorithm") || "clip";

  // Toggle enabled
  rootMenu.addSubmenuItem(
    menu.item(
      enabled ? "Enabled (Active)" : "Disabled",
      () => {
        preferences.set("enabled", !enabled);
        preferences.sync();
        if (!enabled) checkAndProcessMedia();
        else restoreOriginalProperties();
        updateMenu();
      },
      { selected: enabled }
    )
  );

  // Mode Submenu
  const modeMenu = menu.item("Processing Mode");
  const modes = [
    { key: "auto", label: "Smart Auto (Recommended)" },
    { key: "shader", label: "Hardware GLSL Shader (Fixes Green/Purple)" },
    { key: "libplacebo", label: "Native libplacebo Pipeline" }
  ];
  modes.forEach(m => {
    modeMenu.addSubmenuItem(
      menu.item(m.label, () => {
        preferences.set("mode", m.key);
        preferences.sync();
        checkAndProcessMedia();
        updateMenu();
      }, { selected: currentMode === m.key })
    );
  });
  rootMenu.addSubmenuItem(modeMenu);

  // Target Display Submenu
  const targetMenu = menu.item("Target Display");
  const targets = [
    { key: "sdr", label: "Rec.709 SDR (Standard Display)" },
    { key: "hdr10", label: "HDR10 (Rec.2020 PQ)" },
    { key: "hlg", label: "HLG (Rec.2020 HLG)" }
  ];
  targets.forEach(t => {
    targetMenu.addSubmenuItem(
      menu.item(t.label, () => {
        preferences.set("target", t.key);
        preferences.sync();
        checkAndProcessMedia();
        updateMenu();
      }, { selected: currentTarget === t.key })
    );
  });
  rootMenu.addSubmenuItem(targetMenu);

  // Algorithm Submenu
  const algoMenu = menu.item("Tonemap Curve");
  const algos = [
    { key: "clip", label: "Clip (Highest Contrast Highlights)" },
    { key: "spline", label: "Spline (Smooth Natural Roll-off)" },
    { key: "bt.2390", label: "BT.2390 EETF" },
    { key: "reinhard", label: "Reinhard" },
    { key: "mobius", label: "Mobius" }
  ];
  algos.forEach(a => {
    algoMenu.addSubmenuItem(
      menu.item(a.label, () => {
        preferences.set("algorithm", a.key);
        preferences.sync();
        checkAndProcessMedia();
        updateMenu();
      }, { selected: currentAlgorithm === a.key })
    );
  });
  rootMenu.addSubmenuItem(algoMenu);

  // Force Re-check Action
  rootMenu.addSubmenuItem(
    menu.item("Re-evaluate Current Stream", () => {
      checkAndProcessMedia();
      core.osd(isApplied ? "💎 DV Tonemapper Applied" : "ℹ️ Non-DV or Already Normal");
    })
  );

  return rootMenu;
}

let activeRootMenuItem = null;

function updateMenu() {
  try {
    if (activeRootMenuItem) {
      // If updating, rebuild menu item
    }
  } catch (e) {}
}

// Initial setup
ensureShaderOnDisk();
activeRootMenuItem = buildMenu();
menu.addItem(activeRootMenuItem);

// Event Listeners
event.on("iina.file-loaded", () => {
  checkAndProcessMedia();
});

event.on("mpv.video-params.changed", () => {
  checkAndProcessMedia();
});

event.on("mpv.track-list.changed", () => {
  checkAndProcessMedia();
});
