//!HOOK MAIN
//!BIND HOOKED
//!DESC Fixed DaVinci CST Filmic Tone Mapping & Controlled Highlights

float cst_filmic_curve(float x) {
    if (x <= 0.0) return 0.0;
    if (x >= 1.0) return 1.0;
    return x * x * (3.0 - 2.0 * x);
}

vec4 hook() {
    vec4 c = HOOKED_tex(HOOKED_pos);
    
    // 1. Gentle Black Toe Anchoring (pulls milky shadow floor down cleanly)
    vec3 col = max(c.rgb - 0.005, vec3(0.0)) / 0.995;
    
    // (Removed the reckless 2.40 pre-gain and 1.44 gamma crunch that caused the blowout)

    // 2. DaVinci CST Filmic Contrast S-Curve (balanced 35% blend for rich midtone separation)
    vec3 scurve = vec3(
        cst_filmic_curve(clamp(col.r, 0.0, 1.0)),
        cst_filmic_curve(clamp(col.g, 0.0, 1.0)),
        cst_filmic_curve(clamp(col.b, 0.0, 1.0))
    );
    col = mix(col, scurve, 0.35);
    
    // 3. Proper Highlight Soft-Knee Roll-Off (triggered at 0.68 luma to preserve lamp shape & details)
    float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
    if (luma > 0.68) {
        float knee = 0.68;
        float ceiling = 0.95; 
        float scale = ceiling - knee;
        float delta = luma - knee;
        float mapped_luma = knee + scale * (delta / (delta + scale * 0.50));
        col *= (mapped_luma / max(luma, 1e-4));
    }
    col = clamp(col, 0.0, 1.0);
    
    // 4. Subtle Color Volume Punch (+8%)
    float final_luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
    col = mix(vec3(final_luma), col, 1.08);
    
    return vec4(clamp(col, 0.0, 1.0), c.a);
}
