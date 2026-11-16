//!HOOK MAIN
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
    return pow(num / den, vec3(1.0 / m1)) * 10000.0; // Linear nits (0 to 10000)
}

vec4 hook() {
    vec4 c = HOOKED_tex(HOOKED_pos);
    
    // c.rgb represents IPTPQc2 components (I in [0,1], P and T centered around 0.5)
    float I = c.r;
    float P = c.g - 0.5;
    float T = c.b - 0.5;
    
    // Matrix: IPT-PQ -> LMS_PQ (Dolby ICtCp / IPTPQc2 inverse matrix)
    // [L, M, S]_PQ = Inv_M_IPT * [I, P, T]
    float L_pq = I + 0.097569 * P + 0.205226 * T;
    float M_pq = I - 0.113880 * P + 0.133217 * T;
    float S_pq = I + 0.032615 * P - 0.676890 * T;
    
    vec3 lms_pq = vec3(L_pq, M_pq, S_pq);
    
    // Convert LMS in PQ to LMS Linear (0 - 10000 nits)
    vec3 lms_lin = pq_to_linear(lms_pq);
    
    // Convert LMS Linear to BT.2020 Linear:
    // Standard LMS to BT.2020 matrix
    mat3 lms_to_bt2020 = mat3(
         3.224645, -0.627763,  0.076044,
        -1.748318,  1.678015, -0.284856,
        -0.476327, -0.050252,  1.208812
    );
    vec3 bt2020_lin = lms_to_bt2020 * lms_lin;
    bt2020_lin = max(bt2020_lin, vec3(0.0));
    
    // Convert BT.2020 Linear to Rec.709 Linear:
    mat3 bt2020_to_rec709 = mat3(
         1.6605, -0.1246, -0.0182,
        -0.5876,  1.1329, -0.1006,
        -0.0728, -0.0083,  1.1187
    );
    vec3 rec709_lin = bt2020_to_rec709 * bt2020_lin;
    rec709_lin = max(rec709_lin, vec3(0.0));
    
    // Normalize nits (reference peak 1000 nits -> SDR 100 nits)
    // Reinhard / Hable Tonemapping for highlights roll-off
    vec3 x = rec709_lin / 100.0; // 1.0 = 100 nits
    vec3 mapped = x / (1.0 + x * 0.4); // soft knee roll-off
    
    // Rec.709 / sRGB transfer curve to SDR
    vec3 sdr;
    sdr.r = (mapped.r <= 0.0031308) ? (mapped.r * 12.92) : (1.055 * pow(mapped.r, 1.0 / 2.4) - 0.055);
    sdr.g = (mapped.g <= 0.0031308) ? (mapped.g * 12.92) : (1.055 * pow(mapped.g, 1.0 / 2.4) - 0.055);
    sdr.b = (mapped.b <= 0.0031308) ? (mapped.b * 12.92) : (1.055 * pow(mapped.b, 1.0 / 2.4) - 0.055);
    
    return vec4(clamp(sdr, 0.0, 1.0), c.a);
}
