//!HOOK MAIN
//!BIND HOOKED
//!DESC DCI-XYZ (SMPTE 428-1) to Rec.709 with Cinema Contrast Punch & Color Vibrancy
vec4 hook() {
    vec4 color = HOOKED_tex(HOOKED_pos);
    
    // 1. Decode SMPTE 428-1 Transfer Function (DCI Gamma 2.6) to Linear XYZ
    vec3 xyz = pow(clamp(color.rgb, 0.0, 1.0), vec3(2.6));
    
    // 2. DCI-XYZ (SMPTE 428-1) to Linear Rec.709 matrix
    // Bradford chromatic adaptation (DCI x=0.314, y=0.351 -> D65)
    // and SMPTE 428-1 luminance scaling (52.37 / 48.0).
    mat3 dci_xyz_to_rec709 = mat3(
         3.5762208, -1.0306787,  0.0638439,
        -1.5710741,  1.9740581, -0.2296737,
        -0.5627783,  0.0408787,  1.3239526
    );
    
    vec3 linear_rgb = dci_xyz_to_rec709 * xyz;
    linear_rgb = max(linear_rgb, vec3(0.0));
    
    // 3. Cinema S-Curve & Contrast Punch:
    // Anchors the black toe eliminating milky haze, adds midtone dynamic punch,
    // and recovers wide DCI-P3 color vibrancy into Rec.709
    float luma = dot(linear_rgb, vec3(0.2126, 0.7152, 0.0722));
    if (luma > 0.0) {
        // Filmic S-curve tone punch around 0.18 mid-gray
        float punched_luma = (luma * (luma * 1.45 + 0.025)) / (luma * 1.38 + 0.035);
        linear_rgb *= (punched_luma / luma);
    }
    
    // Gamut saturation punch (+12% color volume recovery)
    float luma_final = dot(linear_rgb, vec3(0.2126, 0.7152, 0.0722));
    linear_rgb = max(mix(vec3(luma_final), linear_rgb, 1.12), vec3(0.0));
    linear_rgb = clamp(linear_rgb, 0.0, 1.0);
    
    // 4. Standard BT.1886 / Rec.709 Display Gamma 2.4 OETF
    vec3 out_rgb = pow(linear_rgb, vec3(1.0 / 2.4));
    
    return vec4(out_rgb, color.a);
}
