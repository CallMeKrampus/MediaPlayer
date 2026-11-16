//!HOOK MAIN
//!BIND HOOKED
//!DESC Dolby Cinema / DVis (EDR) DCP (108-nit XYZ-PQ) to Studio Rec.709 SDR (BT.1886 100-nit) Converter

// SMPTE ST 2084 (PQ) decoding constants
const float m1 = 2610.0 / 4096.0 / 4.0;
const float m2 = 2523.0 / 4096.0 * 128.0;
const float c1 = 3424.0 / 4096.0;
const float c2 = 2413.0 / 4096.0 * 32.0;
const float c3 = 2392.0 / 4096.0 * 32.0;

vec3 pq_to_linear(vec3 pq) {
    vec3 p = pow(clamp(pq, 0.0, 1.0), vec3(1.0 / m2));
    vec3 num = max(p - c1, 0.0);
    vec3 den = max(c2 - c3 * p, 1e-6);
    return pow(num / den, vec3(1.0 / m1)) * 10000.0; // Linear nits (0 to 10000)
}

vec4 hook() {
    vec4 c = HOOKED_tex(HOOKED_pos);

    // 1. Unpack 12-bit XYZ-PQ into absolute linear scene luminance (0 - 10,000 nits)
    vec3 xyz_lin = pq_to_linear(c.rgb);

    // 2. DCI HDR Addendum Annex C.5: DCI-XYZ (DCI white / D65) -> Linear Rec.709
    mat3 xyz_to_rec709 = mat3(
         3.24096994, -0.96924364,  0.05563008,
        -1.53738318,  1.87596750, -0.20397696,
        -0.49861076,  0.04155506,  1.05697151
    );

    vec3 rec709_lin = xyz_to_rec709 * xyz_lin;
    rec709_lin = max(rec709_lin, vec3(0.0));

    // 3. Highlight knee roll-off above 70 nits to 100 nits (SDR reference peak)
    // Preserves hue and chromaticity by scaling RGB by Y_mapped / Y
    float luma = dot(rec709_lin, vec3(0.2126, 0.7152, 0.0722));
    if (luma > 70.0) {
        float mapped_luma = 100.0 - 30.0 * exp(-(luma - 70.0) / 30.0);
        rec709_lin *= (mapped_luma / max(luma, 1e-4));
    }

    // 4. Normalize to 100 nits = 1.0
    vec3 sdr_norm = rec709_lin * (1.0 / 100.0);
    sdr_norm = clamp(sdr_norm, 0.0, 1.0);

    // 5. Standard BT.1886 / Rec.709 Display Gamma 2.2 / 2.4 OETF
    vec3 sdr_out = pow(sdr_norm, vec3(1.0 / 2.2));

    return vec4(sdr_out, c.a);
}
