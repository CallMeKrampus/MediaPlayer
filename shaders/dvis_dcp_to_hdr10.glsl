//!HOOK MAIN
//!BIND HOOKED
//!DESC Dolby Cinema / DVis (EDR) DCP (108-nit XYZ-PQ) to Consumer HDR10 (BT.2020 PQ) Converter

// SMPTE ST 2084 (PQ) constants
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

vec3 linear_to_pq(vec3 lin) {
    vec3 v = clamp(lin / 10000.0, 0.0, 1.0);
    vec3 y = pow(v, vec3(m1));
    vec3 num = c1 + c2 * y;
    vec3 den = 1.0 + c3 * y;
    return pow(num / den, vec3(m2));
}

vec4 hook() {
    vec4 c = HOOKED_tex(HOOKED_pos);

    // 1. Unpack 12-bit XYZ-PQ into absolute linear scene luminance (0 - 10,000 nits)
    vec3 xyz_lin = pq_to_linear(c.rgb);

    // 2. DCI HDR Addendum Annex C.5: DCI-XYZ (DCI white / D65) -> Linear BT.2020
    mat3 xyz_to_bt2020 = mat3(
         1.71665118, -0.66668435,  0.01763986,
        -0.35567078,  1.61648124, -0.04277061,
        -0.25336628,  0.01576855,  0.94210312
    );

    vec3 bt2020_lin = xyz_to_bt2020 * xyz_lin;
    bt2020_lin = max(bt2020_lin, vec3(0.0));

    // 3. Re-encode to SMPTE ST 2084 PQ in BT.2020 gamut (Consumer HDR10 standard)
    vec3 hdr10_pq = linear_to_pq(bt2020_lin);

    return vec4(clamp(hdr10_pq, 0.0, 1.0), c.a);
}
