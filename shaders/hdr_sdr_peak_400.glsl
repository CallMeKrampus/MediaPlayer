//!HOOK MAIN
//!BIND HOOKED
//!DESC HDR-to-SDR 400 Nits Reference Luminance Curve
vec4 hook() {
    vec4 c = HOOKED_tex(HOOKED_pos);
    vec3 lin = pow(max(c.rgb, vec3(0.0)), vec3(2.2));
    vec3 mapped = (lin * 8.8000) / (vec3(1.0) + lin * 3.9000);
    c.rgb = pow(clamp(mapped, 0.0, 1.0), vec3(1.0 / 2.2));
    return c;
}
