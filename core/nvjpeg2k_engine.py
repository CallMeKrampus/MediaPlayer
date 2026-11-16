"""
BOOB Player - NVIDIA nvJPEG2000 GPU Decoding Engine & Cinema Player
Leverages NVIDIA CUDA Driver API (nvcuda.dll) and nvJPEG2000 (nvjpeg2k_0.dll)
to decode DCI Cinema 4K/2K 12-bit JPEG 2000 codestreams directly on NVIDIA RTX GPUs
and convert DCI-XYZ (SMPTE 428-1 Gamma 2.6) to Rec.709 with real-time GPU grading.
"""

import os
import sys
import struct
import time
import ctypes
import threading
from typing import Optional, Tuple, Dict, Any, List
import numpy as np

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt, QThread
from PyQt6.QtGui import QImage


class nvjpeg2kImage(ctypes.Structure):
    _fields_ = [
        ("pixel_data", ctypes.POINTER(ctypes.c_void_p)),
        ("pitch_in_bytes", ctypes.POINTER(ctypes.c_size_t)),
        ("pixel_type", ctypes.c_int),
        ("num_components", ctypes.c_uint32),
    ]


class nvjpeg2kImageInfo(ctypes.Structure):
    _fields_ = [
        ("image_width", ctypes.c_uint32),
        ("image_height", ctypes.c_uint32),
        ("tile_width", ctypes.c_uint32),
        ("tile_height", ctypes.c_uint32),
        ("num_tiles_x", ctypes.c_uint32),
        ("num_tiles_y", ctypes.c_uint32),
        ("num_components", ctypes.c_uint32),
    ]


# NVIDIA PTX kernel for ultra-fast GPU DCI-XYZ (Gamma 2.6) -> Rec.709 Linear -> Display Gamma 2.2 / sRGB
# with real-time studio grading controls (brightness, contrast, gamma, saturation),
# master pipeline presets (DCI-XYZ standard, EPIQ PLF laser, Pass-Through, Filmic Hable, Reinhard),
# and dynamic target peak nits luminance scaling.
PTX_XYZ_TO_RGB = """
.version 7.0
.target sm_50
.address_size 64

.visible .entry xyz_to_rgb_graded(
    .param .u64 d_x,
    .param .u64 d_y,
    .param .u64 d_z,
    .param .u64 d_out,
    .param .u32 total_pixels,
    .param .f32 brightness,
    .param .f32 contrast,
    .param .f32 gamma_val,
    .param .f32 saturation,
    .param .u32 preset_mode,
    .param .f32 peak_k1,
    .param .f32 peak_k2
) {
    .reg .b32 %t, %nt, %ct, %idx, %n_pix;
    .reg .pred %p0, %p_passthrough, %p_epiq, %p_peak, %p_hable, %p_reinhard;
    .reg .pred %p_dvis_sdr, %p_dvis_hdr10, %p_knee;
    .reg .b64 %x_ptr, %y_ptr, %z_ptr, %out_ptr, %offset;
    .reg .b64 %base_x, %base_y, %base_z, %base_out;
    .reg .b16 %x16, %y16, %z16;
    .reg .f32 %xf, %yf, %zf, %scale;
    .reg .f32 %x_lin, %y_lin, %z_lin, %gamma_in;
    .reg .f32 %rf, %gf, %bf, %zero, %one;
    .reg .f32 %t0, %t1, %t2;
    .reg .f32 %p_bright, %p_contrast, %p_gamma, %p_sat;
    .reg .u32 %p_mode;
    .reg .f32 %p_k1, %p_k2;
    .reg .f32 %lum, %diff_r, %diff_g, %diff_b;
    .reg .b32 %rb, %gb, %bb, %packed;
    .reg .f32 %den, %inv_den, %num;
    .reg .f32 %px, %py, %pz, %num_den, %mapped_luma, %luma_scale;

    mov.u32 %t, %tid.x;
    mov.u32 %nt, %ntid.x;
    mov.u32 %ct, %ctaid.x;
    mad.lo.u32 %idx, %ct, %nt, %t;

    ld.param.u32 %n_pix, [total_pixels];
    setp.ge.u32 %p0, %idx, %n_pix;
    @%p0 ret;

    ld.param.u64 %base_x, [d_x];
    ld.param.u64 %base_y, [d_y];
    ld.param.u64 %base_z, [d_z];
    ld.param.u64 %base_out, [d_out];

    ld.param.f32 %p_bright, [brightness];
    ld.param.f32 %p_contrast, [contrast];
    ld.param.f32 %p_gamma, [gamma_val];
    ld.param.f32 %p_sat, [saturation];
    ld.param.u32 %p_mode, [preset_mode];
    ld.param.f32 %p_k1, [peak_k1];
    ld.param.f32 %p_k2, [peak_k2];

    cvt.u64.u32 %offset, %idx;
    shl.b64 %offset, %offset, 1;
    add.u64 %x_ptr, %base_x, %offset;
    add.u64 %y_ptr, %base_y, %offset;
    add.u64 %z_ptr, %base_z, %offset;

    ld.global.u16 %x16, [%x_ptr];
    ld.global.u16 %y16, [%y_ptr];
    ld.global.u16 %z16, [%z_ptr];

    cvt.rn.f32.u16 %xf, %x16;
    cvt.rn.f32.u16 %yf, %y16;
    cvt.rn.f32.u16 %zf, %z16;

    mov.f32 %scale, 0f39800801; // 1.0f / 4095.0f
    mul.f32 %xf, %xf, %scale;
    mul.f32 %yf, %yf, %scale;
    mul.f32 %zf, %zf, %scale;

    // Mode 2: Pass-Through (Raw XYZ codestream directly mapped to display)
    setp.eq.u32 %p_passthrough, %p_mode, 2;
    @%p_passthrough bra PASSTHROUGH_BRANCH;

    // Mode 7: DVis (DCP) -> Rec.709 SDR (108 nits PQ -> 100 nits SDR)
    setp.eq.u32 %p_dvis_sdr, %p_mode, 7;
    @%p_dvis_sdr bra DVIS_SDR_BRANCH;

    // Mode 8: DVis (DCP) -> Consumer HDR10 (108 nits PQ -> Rec.2020)
    setp.eq.u32 %p_dvis_hdr10, %p_mode, 8;
    @%p_dvis_hdr10 bra DVIS_HDR10_BRANCH;

    max.f32 %xf, %xf, 0f358637bd; // 1e-6
    max.f32 %yf, %yf, 0f358637bd;
    max.f32 %zf, %zf, 0f358637bd;

    // SMPTE 428-1 DCI Gamma 2.6 expansion
    mov.f32 %gamma_in, 0f40266666; // 2.6f
    lg2.approx.f32 %x_lin, %xf;
    mul.f32 %x_lin, %x_lin, %gamma_in;
    ex2.approx.f32 %x_lin, %x_lin;

    lg2.approx.f32 %y_lin, %yf;
    mul.f32 %y_lin, %y_lin, %gamma_in;
    ex2.approx.f32 %y_lin, %y_lin;

    lg2.approx.f32 %z_lin, %zf;
    mul.f32 %z_lin, %z_lin, %gamma_in;
    ex2.approx.f32 %z_lin, %z_lin;

    // Rec.709 Matrix
    mul.f32 %rf, %x_lin, 0f404f6393; // 3.2404542
    mul.f32 %t0, %y_lin, 0fbfc4c10c; // -1.5371385
    add.f32 %rf, %rf, %t0;
    mul.f32 %t0, %z_lin, 0fbeff4031; // -0.4985314
    add.f32 %rf, %rf, %t0;

    mul.f32 %gf, %x_lin, 0fbf78216c; // -0.9692660
    mul.f32 %t1, %y_lin, 0f3ff02170; // 1.8760108
    add.f32 %gf, %gf, %t1;
    mul.f32 %t1, %z_lin, 0f3d2a3f81; // 0.0415560
    add.f32 %gf, %gf, %t1;

    mul.f32 %bf, %x_lin, 0f3d63e9f2; // 0.0556434
    mul.f32 %t2, %y_lin, 0fbe50ec7e; // -0.2040259
    add.f32 %bf, %bf, %t2;
    mul.f32 %t2, %z_lin, 0f3f875326; // 1.0572252
    add.f32 %bf, %bf, %t2;

    // DCI White luminance normalization (52.37 / 48.0 = 1.09104167)
    mul.f32 %rf, %rf, 0f3f8ba835;
    mul.f32 %gf, %gf, 0f3f8ba835;
    mul.f32 %bf, %bf, 0f3f8ba835;

    // Mode 1: EPIQ PLF Laser Red Balance Correction (rf *= 0.86f)
    setp.eq.u32 %p_epiq, %p_mode, 1;
    @%p_epiq mul.f32 %rf, %rf, 0f3f5c28f6;

    // Mode 3: Hable / ACES Filmic Curve
    setp.eq.u32 %p_hable, %p_mode, 3;
    @%p_hable fma.rn.f32 %t0, %rf, 0f4020a3d7, 0f3cf5c28f;
    @%p_hable mul.f32 %num, %rf, %t0;
    @%p_hable fma.rn.f32 %t1, %rf, 0f401b851f, 0f3f170a3d;
    @%p_hable fma.rn.f32 %den, %rf, %t1, 0f3e0f5c29;
    @%p_hable rcp.approx.f32 %inv_den, %den;
    @%p_hable mul.f32 %rf, %num, %inv_den;
    @%p_hable fma.rn.f32 %t0, %gf, 0f4020a3d7, 0f3cf5c28f;
    @%p_hable mul.f32 %num, %gf, %t0;
    @%p_hable fma.rn.f32 %t1, %gf, 0f401b851f, 0f3f170a3d;
    @%p_hable fma.rn.f32 %den, %gf, %t1, 0f3e0f5c29;
    @%p_hable rcp.approx.f32 %inv_den, %den;
    @%p_hable mul.f32 %gf, %num, %inv_den;
    @%p_hable fma.rn.f32 %t0, %bf, 0f4020a3d7, 0f3cf5c28f;
    @%p_hable mul.f32 %num, %bf, %t0;
    @%p_hable fma.rn.f32 %t1, %bf, 0f401b851f, 0f3f170a3d;
    @%p_hable fma.rn.f32 %den, %bf, %t1, 0f3e0f5c29;
    @%p_hable rcp.approx.f32 %inv_den, %den;
    @%p_hable mul.f32 %bf, %num, %inv_den;

    // Mode 6: Reinhard Curve: rf / (1.0f + rf)
    setp.eq.u32 %p_reinhard, %p_mode, 6;
    @%p_reinhard fma.rn.f32 %den, %rf, 0f3f800000, 0f3f800000;
    @%p_reinhard rcp.approx.f32 %inv_den, %den;
    @%p_reinhard mul.f32 %rf, %rf, %inv_den;
    @%p_reinhard fma.rn.f32 %den, %gf, 0f3f800000, 0f3f800000;
    @%p_reinhard rcp.approx.f32 %inv_den, %den;
    @%p_reinhard mul.f32 %gf, %gf, %inv_den;
    @%p_reinhard fma.rn.f32 %den, %bf, 0f3f800000, 0f3f800000;
    @%p_reinhard rcp.approx.f32 %inv_den, %den;
    @%p_reinhard mul.f32 %bf, %bf, %inv_den;

    // Target Peak modulation transfer (applied when peak_k1 > 0.0f)
    setp.gt.f32 %p_peak, %p_k1, 0f00000000;
    @%p_peak mul.f32 %num, %rf, %p_k1;
    @%p_peak fma.rn.f32 %den, %rf, %p_k2, 0f3f800000;
    @%p_peak rcp.approx.f32 %inv_den, %den;
    @%p_peak mul.f32 %rf, %num, %inv_den;

    @%p_peak mul.f32 %num, %gf, %p_k1;
    @%p_peak fma.rn.f32 %den, %gf, %p_k2, 0f3f800000;
    @%p_peak rcp.approx.f32 %inv_den, %den;
    @%p_peak mul.f32 %gf, %num, %inv_den;

    @%p_peak mul.f32 %num, %bf, %p_k1;
    @%p_peak fma.rn.f32 %den, %bf, %p_k2, 0f3f800000;
    @%p_peak rcp.approx.f32 %inv_den, %den;
    @%p_peak mul.f32 %bf, %num, %inv_den;

    bra COMMON_GRADING;

DVIS_SDR_BRANCH:
    max.f32 %xf, %xf, 0f358637bd;
    max.f32 %yf, %yf, 0f358637bd;
    max.f32 %zf, %zf, 0f358637bd;

    // PQ EOTF for X:
    lg2.approx.f32 %t0, %xf;
    mul.f32 %t0, %t0, 0f3c4fc316;
    ex2.approx.f32 %px, %t0;
    sub.f32 %num, %px, 0f3f560000;
    max.f32 %num, %num, 0f00000000;
    mul.f32 %den, %px, 0f41958000;
    mov.f32 %t1, 0f4196d000;
    sub.f32 %den, %t1, %den;
    rcp.approx.f32 %inv_den, %den;
    mul.f32 %num_den, %num, %inv_den;
    max.f32 %num_den, %num_den, 0f358637bd;
    lg2.approx.f32 %t0, %num_den;
    mul.f32 %t0, %t0, 0f40c8e063;
    ex2.approx.f32 %x_lin, %t0;
    mul.f32 %x_lin, %x_lin, 0f461c4000;

    // PQ EOTF for Y:
    lg2.approx.f32 %t0, %yf;
    mul.f32 %t0, %t0, 0f3c4fc316;
    ex2.approx.f32 %py, %t0;
    sub.f32 %num, %py, 0f3f560000;
    max.f32 %num, %num, 0f00000000;
    mul.f32 %den, %py, 0f41958000;
    mov.f32 %t1, 0f4196d000;
    sub.f32 %den, %t1, %den;
    rcp.approx.f32 %inv_den, %den;
    mul.f32 %num_den, %num, %inv_den;
    max.f32 %num_den, %num_den, 0f358637bd;
    lg2.approx.f32 %t0, %num_den;
    mul.f32 %t0, %t0, 0f40c8e063;
    ex2.approx.f32 %y_lin, %t0;
    mul.f32 %y_lin, %y_lin, 0f461c4000;

    // PQ EOTF for Z:
    lg2.approx.f32 %t0, %zf;
    mul.f32 %t0, %t0, 0f3c4fc316;
    ex2.approx.f32 %pz, %t0;
    sub.f32 %num, %pz, 0f3f560000;
    max.f32 %num, %num, 0f00000000;
    mul.f32 %den, %pz, 0f41958000;
    mov.f32 %t1, 0f4196d000;
    sub.f32 %den, %t1, %den;
    rcp.approx.f32 %inv_den, %den;
    mul.f32 %num_den, %num, %inv_den;
    max.f32 %num_den, %num_den, 0f358637bd;
    lg2.approx.f32 %t0, %num_den;
    mul.f32 %t0, %t0, 0f40c8e063;
    ex2.approx.f32 %z_lin, %t0;
    mul.f32 %z_lin, %z_lin, 0f461c4000;

    // Rec.709 Linear matrix (DCI HDR Addendum Annex C.5)
    mul.f32 %rf, %x_lin, 0f404f6bf2;
    mul.f32 %t0, %y_lin, 0fbfc4c798;
    add.f32 %rf, %rf, %t0;
    mul.f32 %t0, %z_lin, 0fbeffa8d0;
    add.f32 %rf, %rf, %t0;

    mul.f32 %gf, %x_lin, 0fbf782005;
    mul.f32 %t1, %y_lin, 0f3ff02008;
    add.f32 %gf, %gf, %t1;
    mul.f32 %t1, %z_lin, 0f3d2a3f47;
    add.f32 %gf, %gf, %t1;

    mul.f32 %bf, %x_lin, 0f3d63dd49;
    mul.f32 %t2, %y_lin, 0fbe50e32b;
    add.f32 %bf, %bf, %t2;
    mul.f32 %t2, %z_lin, 0f3f874b33;
    add.f32 %bf, %bf, %t2;

    max.f32 %rf, %rf, 0f00000000;
    max.f32 %gf, %gf, 0f00000000;
    max.f32 %bf, %bf, 0f00000000;

    // Highlight knee roll-off above 70 nits
    mul.f32 %t0, %rf, 0f3e59b3d0;
    mul.f32 %t1, %gf, 0f3f371759;
    add.f32 %lum, %t0, %t1;
    mul.f32 %t2, %bf, 0f3d93dc1a;
    add.f32 %lum, %lum, %t2;

    setp.gt.f32 %p_knee, %lum, 0f428c0000;
    @%p_knee sub.f32 %t0, %lum, 0f428c0000;
    @%p_knee mul.f32 %t0, %t0, 0fbd44fa40;
    @%p_knee ex2.approx.f32 %t1, %t0;
    @%p_knee mul.f32 %t1, %t1, 0f41f00000;
    @%p_knee mov.f32 %t2, 0f42c80000;
    @%p_knee sub.f32 %mapped_luma, %t2, %t1;
    @%p_knee max.f32 %t0, %lum, 0f3727c5ac;
    @%p_knee rcp.approx.f32 %inv_den, %t0;
    @%p_knee mul.f32 %luma_scale, %mapped_luma, %inv_den;
    @%p_knee mul.f32 %rf, %rf, %luma_scale;
    @%p_knee mul.f32 %gf, %gf, %luma_scale;
    @%p_knee mul.f32 %bf, %bf, %luma_scale;

    // Normalize 100 nits = 1.0
    mul.f32 %rf, %rf, 0f3c23d70a;
    mul.f32 %gf, %gf, 0f3c23d70a;
    mul.f32 %bf, %bf, 0f3c23d70a;
    bra COMMON_GRADING;

DVIS_HDR10_BRANCH:
    max.f32 %xf, %xf, 0f358637bd;
    max.f32 %yf, %yf, 0f358637bd;
    max.f32 %zf, %zf, 0f358637bd;

    lg2.approx.f32 %t0, %xf;
    mul.f32 %t0, %t0, 0f3c4fc316;
    ex2.approx.f32 %px, %t0;
    sub.f32 %num, %px, 0f3f560000;
    max.f32 %num, %num, 0f00000000;
    mul.f32 %den, %px, 0f41958000;
    mov.f32 %t1, 0f4196d000;
    sub.f32 %den, %t1, %den;
    rcp.approx.f32 %inv_den, %den;
    mul.f32 %num_den, %num, %inv_den;
    max.f32 %num_den, %num_den, 0f358637bd;
    lg2.approx.f32 %t0, %num_den;
    mul.f32 %t0, %t0, 0f40c8e063;
    ex2.approx.f32 %x_lin, %t0;
    mul.f32 %x_lin, %x_lin, 0f461c4000;

    lg2.approx.f32 %t0, %yf;
    mul.f32 %t0, %t0, 0f3c4fc316;
    ex2.approx.f32 %py, %t0;
    sub.f32 %num, %py, 0f3f560000;
    max.f32 %num, %num, 0f00000000;
    mul.f32 %den, %py, 0f41958000;
    mov.f32 %t1, 0f4196d000;
    sub.f32 %den, %t1, %den;
    rcp.approx.f32 %inv_den, %den;
    mul.f32 %num_den, %num, %inv_den;
    max.f32 %num_den, %num_den, 0f358637bd;
    lg2.approx.f32 %t0, %num_den;
    mul.f32 %t0, %t0, 0f40c8e063;
    ex2.approx.f32 %y_lin, %t0;
    mul.f32 %y_lin, %y_lin, 0f461c4000;

    lg2.approx.f32 %t0, %zf;
    mul.f32 %t0, %t0, 0f3c4fc316;
    ex2.approx.f32 %pz, %t0;
    sub.f32 %num, %pz, 0f3f560000;
    max.f32 %num, %num, 0f00000000;
    mul.f32 %den, %pz, 0f41958000;
    mov.f32 %t1, 0f4196d000;
    sub.f32 %den, %t1, %den;
    rcp.approx.f32 %inv_den, %den;
    mul.f32 %num_den, %num, %inv_den;
    max.f32 %num_den, %num_den, 0f358637bd;
    lg2.approx.f32 %t0, %num_den;
    mul.f32 %t0, %t0, 0f40c8e063;
    ex2.approx.f32 %z_lin, %t0;
    mul.f32 %z_lin, %z_lin, 0f461c4000;

    mul.f32 %rf, %x_lin, 0f3fdbba18;
    mul.f32 %t0, %y_lin, 0fbeb61a6b;
    add.f32 %rf, %rf, %t0;
    mul.f32 %t0, %z_lin, 0fbe81c97a;
    add.f32 %rf, %rf, %t0;

    mul.f32 %gf, %x_lin, 0fbf2aa1bb;
    mul.f32 %t1, %y_lin, 0f3fcf09b9;
    add.f32 %gf, %gf, %t1;
    mul.f32 %t1, %z_lin, 0f3c814421;
    add.f32 %gf, %gf, %t1;

    mul.f32 %bf, %x_lin, 0f3c9081e7;
    mul.f32 %t2, %y_lin, 0fbd2f306d;
    add.f32 %bf, %bf, %t2;
    mul.f32 %t2, %z_lin, 0f3f712dd5;
    add.f32 %bf, %bf, %t2;

    max.f32 %rf, %rf, 0f00000000;
    max.f32 %gf, %gf, 0f00000000;
    max.f32 %bf, %bf, 0f00000000;

    mul.f32 %rf, %rf, 0f3c23d70a;
    mul.f32 %gf, %gf, 0f3c23d70a;
    mul.f32 %bf, %bf, 0f3c23d70a;
    bra COMMON_GRADING;

PASSTHROUGH_BRANCH:
    // Pure raw XYZ without color matrix or gamma expansion
    mov.f32 %rf, %xf;
    mov.f32 %gf, %yf;
    mov.f32 %bf, %zf;

COMMON_GRADING:
    // Dynamic Grading: Brightness offset
    add.f32 %rf, %rf, %p_bright;
    add.f32 %gf, %gf, %p_bright;
    add.f32 %bf, %bf, %p_bright;

    // Dynamic Grading: Contrast scale around midpoint 0.18
    sub.f32 %rf, %rf, 0f3e3851ec;
    mul.f32 %rf, %rf, %p_contrast;
    add.f32 %rf, %rf, 0f3e3851ec;

    sub.f32 %gf, %gf, 0f3e3851ec;
    mul.f32 %gf, %gf, %p_contrast;
    add.f32 %gf, %gf, 0f3e3851ec;

    sub.f32 %bf, %bf, 0f3e3851ec;
    mul.f32 %bf, %bf, %p_contrast;
    add.f32 %bf, %bf, 0f3e3851ec;

    // Dynamic Grading: Saturation
    mul.f32 %t0, %rf, 0f3e59b3d0; // 0.2126f
    mul.f32 %t1, %gf, 0f3f371759; // 0.7152f
    add.f32 %lum, %t0, %t1;
    mul.f32 %t2, %bf, 0f3d93dc1a; // 0.0722f
    add.f32 %lum, %lum, %t2;

    sub.f32 %diff_r, %rf, %lum;
    mul.f32 %diff_r, %diff_r, %p_sat;
    add.f32 %rf, %lum, %diff_r;

    sub.f32 %diff_g, %gf, %lum;
    mul.f32 %diff_g, %diff_g, %p_sat;
    add.f32 %gf, %lum, %diff_g;

    sub.f32 %diff_b, %bf, %lum;
    mul.f32 %diff_b, %diff_b, %p_sat;
    add.f32 %bf, %lum, %diff_b;

    // Clamp [0.0, 1.0]
    mov.f32 %zero, 0f00000000;
    mov.f32 %one, 0f3f800000;
    max.f32 %rf, %rf, %zero;
    min.f32 %rf, %rf, %one;
    max.f32 %gf, %gf, %zero;
    min.f32 %gf, %gf, %one;
    max.f32 %bf, %bf, %zero;
    min.f32 %bf, %bf, %one;

    // Display Gamma 2.2 OETF modified by user gamma
    .reg .f32 %eff_gamma;
    mul.f32 %eff_gamma, %p_gamma, 0f3ee8ba2e; // 0.45454545f (1.0 / 2.2)

    max.f32 %rf, %rf, 0f358637bd;
    max.f32 %gf, %gf, 0f358637bd;
    max.f32 %bf, %bf, 0f358637bd;

    lg2.approx.f32 %rf, %rf;
    mul.f32 %rf, %rf, %eff_gamma;
    ex2.approx.f32 %rf, %rf;

    lg2.approx.f32 %gf, %gf;
    mul.f32 %gf, %gf, %eff_gamma;
    ex2.approx.f32 %gf, %gf;

    lg2.approx.f32 %bf, %bf;
    mul.f32 %bf, %bf, %eff_gamma;
    ex2.approx.f32 %bf, %bf;

    // Scale to 255.0 and convert to integer
    mul.f32 %rf, %rf, 0f437f0000;
    mul.f32 %gf, %gf, 0f437f0000;
    mul.f32 %bf, %bf, 0f437f0000;

    cvt.rzi.u32.f32 %rb, %rf;
    cvt.rzi.u32.f32 %gb, %gf;
    cvt.rzi.u32.f32 %bb, %bf;

    // Pack into ARGB32 (Qt Format_RGB32: B at byte 0, G at byte 1, R at byte 2, A=255 at byte 3)
    shl.b32 %rb, %rb, 16;
    shl.b32 %gb, %gb, 8;
    or.b32 %packed, %rb, %gb;
    or.b32 %packed, %packed, %bb;
    or.b32 %packed, %packed, 0xff000000;

    cvt.u64.u32 %offset, %idx;
    shl.b64 %offset, %offset, 2;
    add.u64 %out_ptr, %base_out, %offset;
    st.global.u32 [%out_ptr], %packed;
    ret;
}
"""


class NVJPEG2KEngine:
    """Hardware accelerated JPEG 2000 decoder utilizing NVIDIA nvJPEG2000 and CUDA."""

    _instance: Optional["NVJPEG2KEngine"] = None

    @classmethod
    def get_instance(cls) -> "NVJPEG2KEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _find_nvjpeg2k_dll() -> Optional[str]:
        """Locate nvjpeg2k_0.dll across frozen bundle paths and Python environment."""
        from core.app_paths import get_app_base_dir, get_lib_dir

        candidates = [
            os.path.join(get_lib_dir(), "nvjpeg2k_0.dll"),
            os.path.join(get_app_base_dir(), "nvjpeg2k_0.dll"),
            os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "nvjpeg2k", "bin", "nvjpeg2k_0.dll"),
        ]
        for cand in candidates:
            if cand and os.path.exists(cand):
                return cand

        try:
            from importlib.util import find_spec
            spec = find_spec("nvidia.nvjpeg2k")
            if spec and spec.origin:
                cand = os.path.join(os.path.dirname(spec.origin), "bin", "nvjpeg2k_0.dll")
                if os.path.exists(cand):
                    return cand
        except Exception:
            pass
        return None

    @staticmethod
    def is_available() -> bool:
        """Check if NVIDIA GPU, CUDA driver, and nvjpeg2k library are installed and functional."""
        try:
            cuda = ctypes.CDLL("nvcuda.dll")
            if cuda.cuInit(0) != 0:
                return False

            dll_path = NVJPEG2KEngine._find_nvjpeg2k_dll()
            if not dll_path or not os.path.exists(dll_path):
                return False

            os.add_dll_directory(os.path.dirname(dll_path))
            lib = ctypes.CDLL(dll_path)
            handle = ctypes.c_void_p()
            if lib.nvjpeg2kCreateSimple(ctypes.byref(handle)) != 0:
                return False
            lib.nvjpeg2kDestroy(handle)
            return True
        except Exception:
            return False

    def __init__(self):
        self.initialized = False
        try:
            from core.gpu_detector import GPUDetector
            self.gpu_name = GPUDetector.get_info().name
        except Exception:
            self.gpu_name = "NVIDIA GPU"
        self.cuda = None
        self.lib = None
        self.ctx = None
        self.handle = None
        self.decode_state = None
        self.stream = None
        self.d_ptrs = []
        self.d_out = None
        self.h_out = None
        self.allocated_w = 0
        self.allocated_h = 0
        self.allocated_plane_size = 0
        self.img_desc = None
        self.pixel_data_arr = None
        self.pitch_arr = None

        # GPU Color Transform Module
        self.color_mod = None
        self.color_func = None

        # MXF Frame indexing cache: mxf_path -> [(offset, length), ...]
        self._mxf_index_cache: Dict[str, List[Tuple[int, int]]] = {}
        self._lock = threading.Lock()
        self._tls = threading.local()
        self._fh_lock = threading.Lock()
        self._open_file_handles: List[Any] = []

    def initialize(self) -> bool:
        """Initialize CUDA device context, nvJPEG2000 library handles, and PTX color shaders."""
        if self.initialized:
            return True

        with self._lock:
            if self.initialized:
                return True

            try:
                # 1. Load CUDA Driver
                self.cuda = ctypes.CDLL("nvcuda.dll")
                if self.cuda.cuInit(0) != 0:
                    return False

                dev = ctypes.c_int()
                if self.cuda.cuDeviceGet(ctypes.byref(dev), 0) != 0:
                    return False

                name_buf = (ctypes.c_char * 256)()
                self.cuda.cuDeviceGetName(name_buf, 256, dev)
                self.gpu_name = name_buf.value.decode("utf-8")

                self.ctx = ctypes.c_void_p()
                if self.cuda.cuCtxCreate_v2(ctypes.byref(self.ctx), 0, dev) != 0:
                    return False

                # Configure driver function signatures
                self.cuda.cuMemAlloc_v2.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]
                self.cuda.cuMemFree_v2.argtypes = [ctypes.c_uint64]
                self.cuda.cuMemcpyDtoH_v2.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t]
                self.cuda.cuLaunchKernel.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                    ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)
                ]

                # 2. Compile PTX Color Transformation Module on the GPU
                self.color_mod = ctypes.c_void_p()
                err_buf = ctypes.create_string_buffer(4096)
                opts = (ctypes.c_int * 2)(5, 6) # CU_JIT_ERROR_LOG_BUFFER, CU_JIT_ERROR_LOG_BUFFER_SIZE_BYTES
                opt_vals = (ctypes.c_void_p * 2)(ctypes.cast(err_buf, ctypes.c_void_p), ctypes.c_void_p(4096))
                self.cuda.cuModuleLoadDataEx.argtypes = [
                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_uint,
                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p)
                ]

                res = self.cuda.cuModuleLoadDataEx(
                    ctypes.byref(self.color_mod), PTX_XYZ_TO_RGB.encode("utf-8"), 2, opts, opt_vals
                )
                if res != 0:
                    print(f"[NVJPEG2K] PTX compilation failed: {err_buf.value.decode('utf-8', errors='ignore')}")
                    return False

                self.color_func = ctypes.c_void_p()
                self.cuda.cuModuleGetFunction(ctypes.byref(self.color_func), self.color_mod, b"xyz_to_rgb_graded")

                # 3. Load nvJPEG2000 DLL
                dll_path = self._find_nvjpeg2k_dll()
                if not dll_path or not os.path.exists(dll_path):
                    return False

                os.add_dll_directory(os.path.dirname(dll_path))
                self.lib = ctypes.CDLL(dll_path)

                self.handle = ctypes.c_void_p()
                if self.lib.nvjpeg2kCreateSimple(ctypes.byref(self.handle)) != 0:
                    return False

                self.decode_state = ctypes.c_void_p()
                if self.lib.nvjpeg2kDecodeStateCreate(self.handle, ctypes.byref(self.decode_state)) != 0:
                    return False

                self.stream = ctypes.c_void_p()
                if self.lib.nvjpeg2kStreamCreate(ctypes.byref(self.stream)) != 0:
                    return False

                self.initialized = True
                print(f"[NVJPEG2K] Initialized hardware acceleration & GPU color pipeline on {self.gpu_name}")
                return True

            except Exception as e:
                print(f"[NVJPEG2K] Initialization error: {e}")
                self.close()
                return False

    def _ensure_buffers(self, width: int, height: int):
        """Allocate or reuse device memory buffers for 3 components (XYZ uint16) and 1 output (ARGB32)."""
        plane_size = width * 2 * height
        out_size = width * 4 * height
        if self.allocated_w == width and self.allocated_h == height and len(self.d_ptrs) == 3 and self.d_out is not None:
            return

        # Free previous allocations
        for p in self.d_ptrs:
            try:
                self.cuda.cuMemFree_v2(p)
            except Exception:
                pass
        self.d_ptrs = []
        if self.d_out:
            try:
                self.cuda.cuMemFree_v2(self.d_out)
            except Exception:
                pass
            self.d_out = None

        # Allocate 3 device planes for X, Y, Z
        for _ in range(3):
            ptr = ctypes.c_uint64()
            res = self.cuda.cuMemAlloc_v2(ctypes.byref(ptr), plane_size)
            if res != 0:
                raise MemoryError(f"CUDA Out of Memory allocating {plane_size} bytes on {self.gpu_name}")
            self.d_ptrs.append(ptr)

        # Allocate device output plane for 32-bit ARGB
        self.d_out = ctypes.c_uint64()
        res = self.cuda.cuMemAlloc_v2(ctypes.byref(self.d_out), out_size)
        if res != 0:
            raise MemoryError(f"CUDA Out of Memory allocating {out_size} bytes for output on {self.gpu_name}")

        self.allocated_w = width
        self.allocated_h = height
        self.allocated_plane_size = plane_size
        self._buffer_pool = [np.empty((height, width, 4), dtype=np.uint8) for _ in range(28)]
        self._pool_cursor = 0

        pitch = width * 2
        self.pixel_data_arr = (ctypes.c_void_p * 3)(self.d_ptrs[0].value, self.d_ptrs[1].value, self.d_ptrs[2].value)
        self.pitch_arr = (ctypes.c_size_t * 3)(pitch, pitch, pitch)

        self.img_desc = nvjpeg2kImage()
        self.img_desc.pixel_data = ctypes.cast(self.pixel_data_arr, ctypes.POINTER(ctypes.c_void_p))
        self.img_desc.pitch_in_bytes = ctypes.cast(self.pitch_arr, ctypes.POINTER(ctypes.c_size_t))
        self.img_desc.pixel_type = 1  # NVJPEG2K_UINT16
        self.img_desc.num_components = 3

    def _try_index_mxf_footer(
        self,
        f,
        file_size: int,
        first_pos: int,
        first_ber_hdr_size: int,
    ) -> List[Tuple[int, int]]:
        """
        Parse SMPTE 377M RandomIndexPack + Footer IndexTableSegments in O(footer_size)
        for near-instant frame indexing on multi-gigabyte 4K MXF reels.
        """
        try:
            tail_read = min(file_size, 4096)
            f.seek(file_size - tail_read)
            end_b = f.read(tail_read)
            rip_key = b"\x06\x0e\x2b\x34\x02\x05\x01\x01\x0d\x01\x02\x01\x01\x11\x01\x00"
            rip_pos = end_b.rfind(rip_key)
            if rip_pos == -1 or rip_pos + 17 >= len(end_b):
                return []

            rip = end_b[rip_pos:]
            lb = rip[16]
            hdr_len = 17 + (lb & 0x7F) if (lb & 0x80) else 17
            if len(rip) <= hdr_len + 4:
                return []
            body = rip[hdr_len:-4]
            if len(body) < 12 or len(body) % 12 != 0:
                return []

            parts = [struct.unpack(">IQ", body[i : i + 12]) for i in range(0, len(body), 12)]
            footer_off = parts[-1][1]
            footer_len = file_size - footer_off
            if footer_off <= first_pos or footer_off >= file_size or footer_len > 32 * 1024 * 1024:
                return []

            f.seek(footer_off)
            footer_data = f.read(footer_len)
            idx_key = b"\x06\x0e\x2b\x34\x02\x53\x01\x01\x0d\x01\x02\x01\x01\x10\x01\x00"
            pos = 0
            stream_offs: List[int] = []
            while True:
                kpos = footer_data.find(idx_key, pos)
                if kpos == -1 or kpos + 17 >= len(footer_data):
                    break
                lb = footer_data[kpos + 16]
                if lb & 0x80:
                    n = lb & 0x7F
                    if kpos + 17 + n > len(footer_data):
                        break
                    vlen = int.from_bytes(footer_data[kpos + 17 : kpos + 17 + n], "big")
                    vstart = kpos + 17 + n
                else:
                    vlen = lb
                    vstart = kpos + 17
                vend = min(len(footer_data), vstart + vlen)
                seg = footer_data[vstart:vend]
                p2 = 0
                while p2 + 4 <= len(seg):
                    tag, tlen = struct.unpack_from(">HH", seg, p2)
                    if p2 + 4 + tlen > len(seg):
                        break
                    if tag == 0x3F0A and tlen >= 8:
                        nb, elen = struct.unpack_from(">II", seg, p2 + 4)
                        arr_start = p2 + 12
                        if elen >= 11 and arr_start + nb * elen <= p2 + 4 + tlen:
                            for k in range(nb):
                                soff = struct.unpack_from(">Q", seg, arr_start + k * elen + 3)[0]
                                stream_offs.append(soff)
                    p2 += 4 + tlen
                pos = vend

            if not stream_offs or stream_offs[0] != 0:
                return []

            offsets: List[Tuple[int, int]] = []
            n_frames = len(stream_offs)
            for i in range(n_frames):
                klv_start = first_pos + stream_offs[i]
                klv_total = (stream_offs[i + 1] - stream_offs[i]) if (i + 1 < n_frames) else (footer_off - klv_start)
                if klv_total <= first_ber_hdr_size:
                    return []
                offsets.append((klv_start + first_ber_hdr_size, klv_total - first_ber_hdr_size))
            return offsets
        except Exception:
            return []

    def index_mxf(self, mxf_path: str) -> List[Tuple[int, int]]:
        """
        Fast scan and index all JPEG 2000 picture essence frames in an MXF container.
        Returns cached list of (offset, length) tuples for O(1) random access seeking.
        """
        if mxf_path in self._mxf_index_cache:
            return self._mxf_index_cache[mxf_path]

        essence_prefix = b"\x06\x0e\x2b\x34\x01\x02\x01\x01\x0d\x01\x03\x01\x15\x01\x08"
        offsets: List[Tuple[int, int]] = []

        with open(mxf_path, "rb") as f:
            file_size = f.seek(0, 2)
            f.seek(0)
            header_chunk = f.read(min(file_size, 65536))
            first_pos = header_chunk.find(essence_prefix)
            if first_pos == -1:
                # Seek across larger chunk if needed
                f.seek(0)
                first_pos = f.read(min(file_size, 524288)).find(essence_prefix)

            if first_pos == -1:
                return []

            essence_key = header_chunk[first_pos:first_pos + 16] if (first_pos + 16 <= len(header_chunk)) else (essence_prefix + b"\x01")

            f.seek(first_pos + 16)
            lb0_bytes = f.read(1)
            if lb0_bytes:
                lb0 = lb0_bytes[0]
                first_ber_hdr_size = 17 + (lb0 & 0x7F) if (lb0 & 0x80) else 17
                footer_offsets = self._try_index_mxf_footer(f, file_size, first_pos, first_ber_hdr_size)
                if footer_offsets:
                    self._mxf_index_cache[mxf_path] = footer_offsets
                    return footer_offsets

            f.seek(first_pos)
            while f.tell() < file_size - 32:
                pos = f.tell()
                klv_key = f.read(16)
                if not klv_key:
                    break
                if klv_key != essence_key:
                    # Non-essence KLV, skip or find next essence
                    chunk = f.read(65536)
                    rel = chunk.find(essence_key)
                    if rel == -1:
                        break
                    f.seek(pos + 16 + rel)
                    klv_key = f.read(16)

                len_byte = f.read(1)[0]
                if len_byte == 0x83:
                    flen = int.from_bytes(f.read(3), "big")
                elif len_byte == 0x84:
                    flen = int.from_bytes(f.read(4), "big")
                else:
                    flen = len_byte

                data_pos = f.tell()
                offsets.append((data_pos, flen))
                f.seek(data_pos + flen)

        self._mxf_index_cache[mxf_path] = offsets
        return offsets

    def _read_mxf_slice(self, mxf_path: str, offset: int, length: int) -> bytes:
        """Read a frame slice using a persistent per-thread buffered file handle (4 MB read-ahead)."""
        fh_cache: Optional[Dict[str, Any]] = getattr(self._tls, "fh_cache", None)
        if fh_cache is None:
            fh_cache = {}
            self._tls.fh_cache = fh_cache

        for attempt in range(2):
            f = fh_cache.get(mxf_path)
            if f is None or getattr(f, "closed", True):
                while len(fh_cache) >= 2:
                    old_key = next(iter(fh_cache))
                    old_f = fh_cache.pop(old_key)
                    try:
                        old_f.close()
                    except Exception:
                        pass
                f = open(mxf_path, "rb", buffering=4 * 1024 * 1024)
                fh_cache[mxf_path] = f
                with self._fh_lock:
                    self._open_file_handles.append(f)
            try:
                f.seek(offset)
                return f.read(length)
            except (OSError, ValueError):
                fh_cache.pop(mxf_path, None)
                try:
                    f.close()
                except Exception:
                    pass
                if attempt == 1:
                    raise
        return b""

    def decode_and_tonemap_frame(
        self,
        mxf_path: str,
        frame_index: int,
        grading: Optional[Dict[str, float]] = None,
        stereo_eye: str = "left",
    ) -> Optional[QImage]:
        """
        Extract frame at frame_index from MXF, decode 12-bit XYZ on NVIDIA GPU,
        run GPU color transform kernel, and return pristine high-res QImage.
        Supports stereoscopic 3D MXFs (SMPTE 429-10) with left/right eye selection.
        """
        if not self.initialized and not self.initialize():
            return None

        index = self.index_mxf(mxf_path)
        if not index or frame_index < 0 or frame_index >= len(index):
            return None

        offset, flen = index[frame_index]
        raw_j2c = self._read_mxf_slice(mxf_path, offset, flen)

        if not raw_j2c.startswith(b"\xff\x4f"):
            soc = raw_j2c.find(b"\xff\x4f", 0, 32)
            if soc > 0:
                raw_j2c = raw_j2c[soc:]

        # Detect and isolate stereoscopic 3D eye codestream if present (SMPTE 429-10)
        second_soc = raw_j2c.find(b"\xff\x4f\xff\x51", 4)
        if second_soc > 0:
            if stereo_eye == "right":
                raw_j2c = raw_j2c[second_soc:]
            else:
                raw_j2c = raw_j2c[:second_soc]

        with self._lock:
            try:
                if self.cuda and self.ctx:
                    self.cuda.cuCtxSetCurrent(self.ctx)

                c_buf = (ctypes.c_uint8 * len(raw_j2c)).from_buffer_copy(raw_j2c)
                res = self.lib.nvjpeg2kStreamParse(self.handle, c_buf, len(raw_j2c), 0, 0, self.stream)
                if res != 0:
                    return None

                info = nvjpeg2kImageInfo()
                self.lib.nvjpeg2kStreamGetImageInfo(self.stream, ctypes.byref(info))
                w, h = info.image_width, info.image_height
                self._ensure_buffers(w, h)

                ret = self.lib.nvjpeg2kDecode(
                    self.handle, self.decode_state, self.stream, ctypes.byref(self.img_desc), None
                )
                if ret != 0:
                    return None

                # Color Grading & Tonemapping Parameters
                grading = grading or {}
                # Brightness: -100 to +100 -> -0.2f to +0.2f
                c_bright = ctypes.c_float(float(grading.get("brightness", 0.0)) / 100.0 * 0.2)
                # Contrast: -100 to +100 -> 0.2f to 2.5f
                c_val = float(grading.get("contrast", 0.0))
                c_contrast = ctypes.c_float((1.0 + c_val / 100.0) if c_val >= 0 else (1.0 / (1.0 - c_val / 100.0)))
                # Gamma: -100 to +100 -> 0.4f to 2.5f
                g_val = float(grading.get("gamma", 0.0))
                c_gamma = ctypes.c_float((1.0 / (1.0 + g_val / 100.0)) if g_val >= 0 else (1.0 - g_val / 100.0))
                # Saturation: -100 to +100 -> 0.0f to 2.0f
                s_val = float(grading.get("saturation", 0.0))
                c_sat = ctypes.c_float(max(0.0, 1.0 + s_val / 100.0))

                # Preset mode: 0=DCI-XYZ standard, 1=EPIQ, 2=Pass-Through, 3=Hable/Filmic, 6=Reinhard
                c_preset_mode = ctypes.c_uint32(int(grading.get("preset_mode", 0)))
                # Target Peak luminance rational curve transfer constants (k1, k2)
                c_peak_k1 = ctypes.c_float(float(grading.get("peak_k1", 1.52)))
                c_peak_k2 = ctypes.c_float(float(grading.get("peak_k2", 0.45)))

                # Launch GPU Color Transformation Kernel
                n_pix = w * h
                threads_per_block = 256
                blocks = (n_pix + threads_per_block - 1) // threads_per_block
                c_total_pixels = ctypes.c_uint32(n_pix)

                args = [
                    ctypes.cast(ctypes.byref(self.d_ptrs[0]), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(self.d_ptrs[1]), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(self.d_ptrs[2]), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(self.d_out), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_total_pixels), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_bright), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_contrast), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_gamma), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_sat), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_preset_mode), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_peak_k1), ctypes.c_void_p),
                    ctypes.cast(ctypes.byref(c_peak_k2), ctypes.c_void_p),
                ]
                kernel_args = (ctypes.c_void_p * len(args))(*[ctypes.cast(a, ctypes.c_void_p) for a in args])

                self.cuda.cuLaunchKernel(
                    self.color_func, blocks, 1, 1, threads_per_block, 1, 1, 0, None, kernel_args, None
                )
                self.cuda.cuCtxSynchronize()

                h_frame = self._acquire_host_buffer(w, h)

                self.cuda.cuMemcpyDtoH_v2(h_frame.ctypes.data, self.d_out.value, n_pix * 4)
                self.cuda.cuCtxSynchronize()

                # Construct zero-copy QImage referencing contiguous numpy buffer
                qimg = QImage(h_frame.data, w, h, w * 4, QImage.Format.Format_RGB32)
                qimg.ndarray = h_frame  # Hold reference to prevent garbage collection
                return qimg

            except Exception as e:
                print(f"[NVJPEG2K] Decode & tonemap error: {e}")
                return None

    def _acquire_host_buffer(self, w: int, h: int) -> np.ndarray:
        """Return an unreferenced (h, w, 4) uint8 host RGBA buffer without aliasing live QImages."""
        if (
            not hasattr(self, "_buffer_pool")
            or len(self._buffer_pool) != 32
            or self._buffer_pool[0].shape[:2] != (h, w)
        ):
            self._buffer_pool = [np.empty((h, w, 4), dtype=np.uint8) for _ in range(32)]
            self._pool_cursor = 0

        pool_len = len(self._buffer_pool)
        cursor = getattr(self, "_pool_cursor", 0) % pool_len
        for _ in range(pool_len):
            # refcount == 2 means only self._buffer_pool and the getrefcount arg hold a reference
            if sys.getrefcount(self._buffer_pool[cursor]) <= 2:
                self._pool_cursor = (cursor + 1) % pool_len
                return self._buffer_pool[cursor]
            cursor = (cursor + 1) % pool_len

        return np.empty((h, w, 4), dtype=np.uint8)

    def decode_j2c(self, raw_bytes: bytes) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Decode a single raw JPEG 2000 codestream on the GPU into host numpy arrays (X, Y, Z)."""
        if not self.initialized and not self.initialize():
            raise RuntimeError("NVIDIA nvJPEG2000 Engine is not initialized")

        with self._lock:
            c_buf = (ctypes.c_uint8 * len(raw_bytes)).from_buffer_copy(raw_bytes)
            res = self.lib.nvjpeg2kStreamParse(self.handle, c_buf, len(raw_bytes), 0, 0, self.stream)
            if res != 0:
                raise ValueError(f"nvjpeg2kStreamParse failed with error code {res}")

            info = nvjpeg2kImageInfo()
            self.lib.nvjpeg2kStreamGetImageInfo(self.stream, ctypes.byref(info))
            w, h = info.image_width, info.image_height

            self._ensure_buffers(w, h)

            ret = self.lib.nvjpeg2kDecode(self.handle, self.decode_state, self.stream, ctypes.byref(self.img_desc), None)
            if ret != 0:
                raise RuntimeError(f"nvjpeg2kDecode failed with error code {ret}")

            self.cuda.cuCtxSynchronize()

            plane_size = w * 2 * h
            h_x = np.empty((h, w), dtype=np.uint16)
            h_y = np.empty((h, w), dtype=np.uint16)
            h_z = np.empty((h, w), dtype=np.uint16)

            self.cuda.cuMemcpyDtoH_v2(h_x.ctypes.data, self.d_ptrs[0].value, plane_size)
            self.cuda.cuMemcpyDtoH_v2(h_y.ctypes.data, self.d_ptrs[1].value, plane_size)
            self.cuda.cuMemcpyDtoH_v2(h_z.ctypes.data, self.d_ptrs[2].value, plane_size)
            self.cuda.cuCtxSynchronize()

            return h_x, h_y, h_z

    def decode_mxf_frame(self, mxf_path: str, frame_index: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Extract and decode frame at frame_index directly from MXF using nvJPEG2000."""
        index = self.index_mxf(mxf_path)
        if not index or frame_index < 0 or frame_index >= len(index):
            raise IndexError(f"Frame index {frame_index} out of range (total frames: {len(index)})")

        offset, flen = index[frame_index]
        raw_j2c = self._read_mxf_slice(mxf_path, offset, flen)

        if not raw_j2c.startswith(b"\xff\x4f"):
            soc = raw_j2c.find(b"\xff\x4f", 0, 32)
            if soc > 0:
                raw_j2c = raw_j2c[soc:]

        return self.decode_j2c(raw_j2c)

    def benchmark_mxf(self, mxf_path: str, num_frames: int = 24) -> Dict[str, Any]:
        """Run a high-speed decode benchmark on the RTX GPU."""
        if not self.initialized and not self.initialize():
            return {"error": "nvjpeg2k not available"}

        index = self.index_mxf(mxf_path)
        if not index:
            return {"error": "Could not index MXF essence frames"}

        frames_to_test = min(num_frames, len(index))
        t0 = time.time()
        with open(mxf_path, "rb") as f:
            for i in range(frames_to_test):
                offset, flen = index[i]
                f.seek(offset)
                raw_j2c = f.read(flen)
                c_buf = (ctypes.c_uint8 * len(raw_j2c)).from_buffer_copy(raw_j2c)
                self.lib.nvjpeg2kStreamParse(self.handle, c_buf, len(raw_j2c), 0, 0, self.stream)
                self._ensure_buffers(4096, 2160)
                self.lib.nvjpeg2kDecode(self.handle, self.decode_state, self.stream, ctypes.byref(self.img_desc), None)
                self.cuda.cuCtxSynchronize()

        elapsed = time.time() - t0
        fps = frames_to_test / max(elapsed, 0.001)
        ms_per_frame = (elapsed / frames_to_test) * 1000.0

        return {
            "gpu": self.gpu_name,
            "frames": frames_to_test,
            "elapsed_sec": round(elapsed, 3),
            "fps": round(fps, 1),
            "ms_per_frame": round(ms_per_frame, 2),
            "resolution": "4096x2160 (4K DCI)",
            "precision": "12-bit XYZ",
        }

    def close(self):
        """Release all allocated CUDA memory and handles."""
        with self._fh_lock:
            for fh in self._open_file_handles:
                try:
                    if not getattr(fh, "closed", True):
                        fh.close()
                except Exception:
                    pass
            self._open_file_handles.clear()
        with self._lock:
            if self.cuda and self.d_ptrs:
                for p in self.d_ptrs:
                    try:
                        self.cuda.cuMemFree_v2(p)
                    except Exception:
                        pass
                self.d_ptrs = []

            if self.cuda and self.d_out:
                try:
                    self.cuda.cuMemFree_v2(self.d_out)
                except Exception:
                    pass
                self.d_out = None

            if self.lib:
                if self.stream:
                    try:
                        self.lib.nvjpeg2kStreamDestroy(self.stream)
                    except Exception:
                        pass
                    self.stream = None

                if self.decode_state:
                    try:
                        self.lib.nvjpeg2kDecodeStateDestroy(self.decode_state)
                    except Exception:
                        pass
                    self.decode_state = None

                if self.handle:
                    try:
                        self.lib.nvjpeg2kDestroy(self.handle)
                    except Exception:
                        pass
                    self.handle = None

            if self.cuda and self.ctx:
                try:
                    self.cuda.cuCtxDestroy_v2(self.ctx)
                except Exception:
                    pass
                self.ctx = None

            self.initialized = False


def is_gpu_jp2k_available() -> bool:
    """Check if any GPU hardware acceleration for JPEG 2000 is available (NVIDIA nvJPEG2000 or Grok OpenCL)."""
    if NVJPEG2KEngine.is_available():
        return True
    try:
        from core.grok_engine import GrokOpenCLEngine
        return GrokOpenCLEngine.is_available()
    except Exception:
        return False


class NVJPEG2KPlaybackController(QObject):
    """
    Coordinates real-time Native 4K DCP playback powered by NVIDIA nvJPEG2000 or Grok OpenCL.
    Decouples frame decoding from audio clock and GUI presentation using a dedicated
    background prefetch worker thread and a main-thread presentation timer.
    Guarantees 100% fluid 24.0 FPS playback with ZERO UI thread blocking.
    """
    frame_ready = pyqtSignal(QImage, int, float) # (qimage, frame_index, pts_seconds)
    fps_updated = pyqtSignal(float)
    playback_ended = pyqtSignal()
    _start_timer_sig = pyqtSignal()
    _stop_timer_sig = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.winmm.timeBeginPeriod(1)
            except Exception:
                pass

        if NVJPEG2KEngine.is_available():
            self.engine = NVJPEG2KEngine.get_instance()
            self.backend_name = "nvjpeg2k"
        else:
            try:
                from core.grok_engine import GrokOpenCLEngine
                if GrokOpenCLEngine.is_available():
                    self.engine = GrokOpenCLEngine.get_instance()
                    self.backend_name = "grok_opencl"
                else:
                    self.engine = NVJPEG2KEngine.get_instance()
                    self.backend_name = "nvjpeg2k"
            except Exception:
                self.engine = NVJPEG2KEngine.get_instance()
                self.backend_name = "nvjpeg2k"
        self.mxf_path: str = ""
        self.fps: float = 24.0
        self.total_frames: int = 0
        self.duration: float = 0.0

        self.is_playing: bool = False
        self.current_frame_idx: int = 0
        self.current_pts: float = 0.0
        self._last_presented_frame_idx: int = -1

        # High-capacity lookahead prefetch ring buffer (thread-safe, up to 12 frames ahead)
        self._frame_cache: Dict[int, QImage] = {}
        self._cache_lock = threading.Lock()
        self.max_cache_frames: int = 12

        # Sequential background prefetch pointer & seek epoch guard
        self._next_decode_idx: int = 0
        self._seek_gen: int = 0
        self._seek_settle_until: float = 0.0
        self._seek_expected_pts: Optional[float] = None

        # Seamless Next-Reel Pre-Indexing & Lookahead Cache
        self._next_mxf_path: str = ""
        self._next_sound_path: str = ""
        self._next_reel_cache: Dict[int, QImage] = {}
        self._next_reel_decode_idx: int = 0
        self.next_reel_predecode_frames: int = 8

        # High-precision Continuous Display Clock & Audio PLL
        self._base_pts: float = 0.0
        self._t_start: float = time.perf_counter()
        self._last_emit_time: float = 0.0
        self._audio_synced: bool = False

        # Live shader color grading & pipeline tonemapping parameters
        self.grading_params: Dict[str, Any] = {
            "brightness": 0.0,
            "contrast": 0.0,
            "gamma": 0.0,
            "saturation": 0.0,
            "preset_mode": 0,
            "peak_k1": 1.52,
            "peak_k2": 0.45,
            "preset": "dci_xyz_srgb",
            "target_peak": 100,
        }

        # Thread synchronization events
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()

        # Background decoding prefetch thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="NVJPEG2K-PrefetchWorker", daemon=True
        )
        self._worker_thread.start()

        # High-precision presentation timer (4ms tick rate)
        self._presentation_timer = QTimer(self)
        self._presentation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._presentation_timer.setInterval(4)
        self._presentation_timer.timeout.connect(self._on_presentation_tick)
        self._start_timer_sig.connect(self._start_presentation_timer_slot)
        self._stop_timer_sig.connect(self._presentation_timer.stop)

        # Performance monitoring
        self._frame_counter = 0
        self._last_fps_report = time.time()
        self.stereo_eye: str = "left"

    def set_stereo_eye(self, eye: str = "left"):
        """Set stereoscopic eye decode target ('left' or 'right') for 3D DCPs."""
        if eye in ("left", "right") and eye != self.stereo_eye:
            self.stereo_eye = eye
            with self._cache_lock:
                mxf_path = self.mxf_path
                target_idx = self.current_frame_idx
                pts = self.current_pts
                grading_snapshot = dict(self.grading_params)
                self._seek_gen += 1
                gen = self._seek_gen
                self._frame_cache.clear()
                self._next_reel_cache.clear()

            if mxf_path and self.total_frames > 0:
                qimg = self._decode_frame(mxf_path, target_idx, grading_snapshot)
                if qimg and not qimg.isNull():
                    with self._cache_lock:
                        if gen == self._seek_gen and mxf_path == self.mxf_path:
                            self._frame_cache[target_idx] = qimg
                            self.frame_ready.emit(qimg, target_idx, pts)
            self._wake_event.set()

    def _decode_frame(self, mxf_path: str, frame_idx: int, grading_snapshot: dict) -> Optional[QImage]:
        """Decode frame with stereoscopic eye support, falling back if mock engine lacks stereo_eye."""
        try:
            return self.engine.decode_and_tonemap_frame(
                mxf_path, frame_idx, grading_snapshot, stereo_eye=self.stereo_eye
            )
        except TypeError:
            return self.engine.decode_and_tonemap_frame(
                mxf_path, frame_idx, grading_snapshot
            )

    def set_next_reel(self, mxf_path: str = "", sound_path: str = ""):
        """Register the upcoming DCP reel for background pre-indexing and frame 0..7 pre-decoding."""
        with self._cache_lock:
            mxf_path = mxf_path or ""
            sound_path = sound_path or ""
            if mxf_path != self._next_mxf_path:
                self._next_mxf_path = mxf_path
                self._next_sound_path = sound_path
                self._next_reel_cache.clear()
                self._next_reel_decode_idx = 0
            else:
                self._next_sound_path = sound_path
        self._wake_event.set()

    def _prewarm_file_head(self, file_path: str):
        """Pre-warm OS page cache for seamless reel startup."""
        if not file_path or not os.path.exists(file_path):
            return
        try:
            with open(file_path, "rb") as pf:
                pf.read(262144)
        except Exception:
            pass

    def _worker_loop(self):
        """Dedicated background thread managing GPU decoding, current-reel prefetch, and next-reel lookahead."""
        if getattr(self.engine, "cuda", None) and getattr(self.engine, "ctx", None):
            try:
                self.engine.cuda.cuCtxSetCurrent(self.engine.ctx)
            except Exception:
                pass

        while not self._stop_event.is_set():
            next_mxf = ""
            next_snd = ""
            nf = -1
            with self._cache_lock:
                mxf_path = self.mxf_path
                total_frames = self.total_frames
                gen = self._seek_gen
                head = self._last_presented_frame_idx
                if not mxf_path or total_frames == 0:
                    f_to_decode = -1
                else:
                    if self._next_decode_idx <= head:
                        self._next_decode_idx = head + 1
                    cached_ahead = sum(1 for k in self._frame_cache.keys() if k > head)
                    if cached_ahead < self.max_cache_frames and self._next_decode_idx < total_frames:
                        f_to_decode = self._next_decode_idx
                    else:
                        f_to_decode = -1

                remaining_frames = total_frames - max(0, head)
                near_reel_end = total_frames > 0 and remaining_frames <= max(24, int(self.fps * 3.0))
                if (
                    f_to_decode < 0
                    and near_reel_end
                    and self._next_mxf_path
                    and self._next_reel_decode_idx < self.next_reel_predecode_frames
                ):
                    next_mxf = self._next_mxf_path
                    next_snd = self._next_sound_path
                    nf = self._next_reel_decode_idx

                grading_snapshot = dict(self.grading_params)

            if f_to_decode >= 0:
                qimg = self._decode_frame(mxf_path, f_to_decode, grading_snapshot)
                if qimg and not qimg.isNull():
                    with self._cache_lock:
                        # Commit only if no seek or reel switch happened while decoding this frame
                        if gen == self._seek_gen and mxf_path == self.mxf_path:
                            self._frame_cache[f_to_decode] = qimg
                            cur_head = self._last_presented_frame_idx
                            old_keys = [k for k in self._frame_cache.keys() if k < cur_head - 4]
                            for k in old_keys:
                                del self._frame_cache[k]
                            if self._next_decode_idx == f_to_decode:
                                self._next_decode_idx = f_to_decode + 1
                else:
                    time.sleep(0.002)
                continue

            if nf >= 0 and next_mxf:
                if nf == 0:
                    self._prewarm_file_head(next_mxf)
                    if next_snd:
                        self._prewarm_file_head(next_snd)
                next_index = self.engine.index_mxf(next_mxf)
                if nf < len(next_index):
                    qimg_next = self._decode_frame(next_mxf, nf, grading_snapshot)
                    with self._cache_lock:
                        if next_mxf == self._next_mxf_path:
                            if qimg_next and not qimg_next.isNull():
                                self._next_reel_cache[nf] = qimg_next
                                if self._next_reel_decode_idx == nf:
                                    self._next_reel_decode_idx = nf + 1
                            else:
                                self._next_reel_decode_idx = self.next_reel_predecode_frames
                else:
                    with self._cache_lock:
                        if next_mxf == self._next_mxf_path:
                            self._next_reel_decode_idx = self.next_reel_predecode_frames
                continue

            self._wake_event.wait(timeout=0.05 if not mxf_path else 0.005)
            self._wake_event.clear()

    def load_reel(
        self,
        mxf_path: str,
        fps: float = 24.0,
        total_duration: Optional[float] = None,
        initial_pts: float = 0.0,
    ) -> bool:
        """Prepare picture MXF for native 4K GPU playback, optionally starting at initial_pts."""
        if not os.path.exists(mxf_path):
            return False

        if not self.engine.initialized and not self.engine.initialize():
            return False

        new_fps = fps if fps > 0 else 24.0
        index = self.engine.index_mxf(mxf_path)
        new_total = len(index)
        new_dur = total_duration if total_duration else (new_total / new_fps)
        init_idx = max(0, min(max(0, new_total - 1), int(initial_pts * new_fps))) if new_total > 0 else 0
        predecoded_qimg0: Optional[QImage] = None

        with self._cache_lock:
            self._seek_gen += 1
            gen = self._seek_gen
            self.mxf_path = mxf_path
            self.fps = new_fps
            self.total_frames = new_total
            self.duration = new_dur

            use_predecoded = (
                initial_pts == 0.0
                and mxf_path == self._next_mxf_path
                and 0 in self._next_reel_cache
            )
            if use_predecoded:
                self._frame_cache = dict(self._next_reel_cache)
                self._next_reel_cache.clear()
                self._next_mxf_path = ""
                self._next_sound_path = ""
                self._next_reel_decode_idx = 0
                predecoded_qimg0 = self._frame_cache.get(0)
                max_cached = max(self._frame_cache.keys()) if self._frame_cache else 0
                self._last_presented_frame_idx = 0
                self._next_decode_idx = max_cached + 1
            else:
                self._frame_cache.clear()
                self._last_presented_frame_idx = init_idx if new_total > 0 else -1
                self._next_decode_idx = (init_idx + 1) if new_total > 0 else 0

            self.current_frame_idx = init_idx
            self.current_pts = float(initial_pts)
            self._base_pts = float(initial_pts)
            now = time.perf_counter()
            self._t_start = now
            self._last_emit_time = now
            self._audio_synced = False
            if initial_pts > 0.0:
                self._seek_expected_pts = float(initial_pts)
                self._seek_settle_until = now + 1.0
            else:
                self._seek_expected_pts = None
                self._seek_settle_until = 0.0
            grading_snapshot = dict(self.grading_params)

        if predecoded_qimg0 is not None and not predecoded_qimg0.isNull():
            self.frame_ready.emit(predecoded_qimg0, 0, 0.0)
        elif new_total > 0:
            # Synchronously decode the initial frame (avoids flashing frame 0 when seeking into a reel)
            qimg = self._decode_frame(mxf_path, init_idx, grading_snapshot)
            if qimg and not qimg.isNull():
                with self._cache_lock:
                    if gen == self._seek_gen and mxf_path == self.mxf_path:
                        now = time.perf_counter()
                        self._frame_cache[init_idx] = qimg
                        self._last_presented_frame_idx = init_idx
                        if self._next_decode_idx <= init_idx:
                            self._next_decode_idx = init_idx + 1
                        self._t_start = now
                        self._last_emit_time = now
                        if initial_pts > 0.0:
                            self._seek_settle_until = now + 1.0
                        self.frame_ready.emit(qimg, init_idx, float(initial_pts))

        self._wake_event.set()
        return True

    def set_grading(self, brightness: float = 0.0, contrast: float = 0.0, gamma: float = 0.0, saturation: float = 0.0):
        """Update live color grading parameters applied inside the RTX GPU shader."""
        with self._cache_lock:
            self.grading_params["brightness"] = brightness
            self.grading_params["contrast"] = contrast
            self.grading_params["gamma"] = gamma
            self.grading_params["saturation"] = saturation
            mxf_path = self.mxf_path
            target_idx = self.current_frame_idx
            pts = self.current_pts
            grading_snapshot = dict(self.grading_params)
            self._next_reel_cache.clear()
            self._next_reel_decode_idx = 0
            if mxf_path:
                self._seek_gen += 1
                gen = self._seek_gen
                self._frame_cache.clear()
                if self.total_frames > 0:
                    self._last_presented_frame_idx = target_idx
                    self._next_decode_idx = target_idx + 1
                else:
                    self._last_presented_frame_idx = target_idx - 1
                    self._next_decode_idx = target_idx
            else:
                gen = self._seek_gen

        if mxf_path and self.total_frames > 0:
            qimg = self._decode_frame(mxf_path, target_idx, grading_snapshot)
            if qimg and not qimg.isNull():
                with self._cache_lock:
                    if gen == self._seek_gen and mxf_path == self.mxf_path:
                        now = time.perf_counter()
                        self._frame_cache[target_idx] = qimg
                        self._last_presented_frame_idx = target_idx
                        if self._next_decode_idx <= target_idx:
                            self._next_decode_idx = target_idx + 1
                        self._t_start = now
                        self._last_emit_time = now
                        self.frame_ready.emit(qimg, target_idx, pts)
            self._wake_event.set()

    def apply_tonemap_status(self, status: Dict[str, Any], redecode_now: bool = True):
        """
        Apply live color tonemap preset, tone curve algorithm, and target peak nits
        directly to the NVIDIA GPU JPEG 2000 cinema decoding pipeline in real time.
        """
        with self._cache_lock:
            grading_before = dict(self.grading_params)
            preset = status.get("preset", "dci_xyz_srgb")
            is_epiq = bool(status.get("is_epiq", False))
            algo = status.get("algorithm", "clip")

            # Preset mode resolution for PTX kernel:
            # 0: DCI-XYZ to Rec.709 standard cinema
            # 1: EPIQ PLF Laser Red neutralization
            # 2: Pass-Through (Raw XYZ codestream)
            # 3: Hable / ACES Filmic curve
            # 6: Reinhard curve
            # 7: DVis (DCP) -> Rec.709 SDR (108 nits PQ -> 100 nits SDR)
            # 8: DVis (DCP) -> Consumer HDR10 (108 nits PQ -> Rec.2020)
            if preset in ("dvis_dcp_sdr", "dvis_sdr"):
                mode = 7
                k1, k2 = 0.0, 0.0
            elif preset in ("dvis_dcp_hdr10", "dvis_hdr10"):
                mode = 8
                k1, k2 = 0.0, 0.0
            elif preset == "passthrough":
                mode = 2
                k1, k2 = 0.0, 0.0
            elif preset == "epiq" or (is_epiq and preset in ("dci_xyz_srgb", "auto")):
                mode = 1
            elif algo in ("hable", "filmic_hable") or preset == "filmic_hable":
                mode = 3
            elif algo == "reinhard" or preset == "reinhard_sdr":
                mode = 6
            else:
                mode = 0

            # Target peak nits -> calibrated rational luminance transfer constants (k1, k2)
            raw_peak = status.get("target_peak", 100)
            try:
                nits = int(str(raw_peak).split()[0])
            except Exception:
                nits = 100

            if mode != 2:
                from core.tonemap_engine import TonemapEngine
                closest_peak = min(TonemapEngine.PEAK_CURVE_PARAMS.keys(), key=lambda k: abs(k - nits))
                k1, k2 = TonemapEngine.PEAK_CURVE_PARAMS[closest_peak]

            # Adjustments
            adj = status.get("adjustments", {})
            b = float(adj.get("brightness", self.grading_params.get("brightness", 0.0)))
            c = float(adj.get("contrast", self.grading_params.get("contrast", 0.0)))
            g = float(adj.get("gamma", self.grading_params.get("gamma", 0.0)))
            s = float(adj.get("saturation", self.grading_params.get("saturation", 0.0)))

            self.grading_params["brightness"] = b
            self.grading_params["contrast"] = c
            self.grading_params["gamma"] = g
            self.grading_params["saturation"] = s
            self.grading_params["preset_mode"] = mode
            self.grading_params["peak_k1"] = k1
            self.grading_params["peak_k2"] = k2
            self.grading_params["preset"] = preset
            self.grading_params["target_peak"] = nits

            mxf_path = self.mxf_path
            target_idx = self.current_frame_idx
            pts = self.current_pts
            grading_snapshot = dict(self.grading_params)
            # Pre-decoded next-reel frames were graded with the old parameters, so they are
            # only stale if the grading actually changed. play_dcp_reel re-applies the same
            # status on every reel switch; discarding the cache then forced a synchronous
            # decode of frame 0 (~50 ms) at exactly the moment the reel boundary is crossed.
            if self.grading_params != grading_before:
                self._next_reel_cache.clear()
                self._next_reel_decode_idx = 0
            if redecode_now and mxf_path:
                self._seek_gen += 1
                gen = self._seek_gen
                self._frame_cache.clear()
                if self.total_frames > 0:
                    self._last_presented_frame_idx = target_idx
                    self._next_decode_idx = target_idx + 1
                else:
                    self._last_presented_frame_idx = target_idx - 1
                    self._next_decode_idx = target_idx
            else:
                gen = self._seek_gen

        if redecode_now and mxf_path and self.total_frames > 0:
            qimg = self._decode_frame(mxf_path, target_idx, grading_snapshot)
            if qimg and not qimg.isNull():
                with self._cache_lock:
                    if gen == self._seek_gen and mxf_path == self.mxf_path:
                        now = time.perf_counter()
                        self._frame_cache[target_idx] = qimg
                        self._last_presented_frame_idx = target_idx
                        if self._next_decode_idx <= target_idx:
                            self._next_decode_idx = target_idx + 1
                        self._t_start = now
                        self._last_emit_time = now
                        self.frame_ready.emit(qimg, target_idx, pts)
            self._wake_event.set()

    def _start_presentation_timer_slot(self):
        """Ensure presentation timer runs whenever playback is active."""
        if self.is_playing and not self._presentation_timer.isActive():
            self._presentation_timer.start()

    def _start_presentation_timer(self):
        """Thread-safe start for the Qt presentation timer."""
        if QThread.currentThread() == self.thread():
            self._start_presentation_timer_slot()
        else:
            self._start_timer_sig.emit()

    def _stop_presentation_timer(self):
        """Thread-safe stop for the Qt presentation timer."""
        if QThread.currentThread() == self.thread():
            self._presentation_timer.stop()
        else:
            self._stop_timer_sig.emit()

    def play(self):
        """Start or resume playback."""
        with self._cache_lock:
            self.is_playing = True
            self._base_pts = self.current_pts
            self._t_start = time.perf_counter()
        self._start_presentation_timer()
        self._wake_event.set()

    def pause(self):
        """Pause playback."""
        with self._cache_lock:
            self.is_playing = False
            self._audio_synced = False
        self._stop_presentation_timer()

    def stop(self):
        """Stop playback and reset to start."""
        self.pause()
        with self._cache_lock:
            self._seek_gen += 1
            gen = self._seek_gen
            self.current_frame_idx = 0
            self.current_pts = 0.0
            self._last_presented_frame_idx = 0 if (self.mxf_path and self.total_frames > 0) else -1
            self._next_decode_idx = 1 if (self.mxf_path and self.total_frames > 0) else 0
            self._last_emit_time = 0.0
            self._seek_expected_pts = None
            self._seek_settle_until = 0.0
            self._frame_cache.clear()
            self._next_mxf_path = ""
            self._next_sound_path = ""
            self._next_reel_cache.clear()
            self._next_reel_decode_idx = 0
            mxf_path = self.mxf_path
            total_frames = self.total_frames
            grading_snapshot = dict(self.grading_params)

        if mxf_path and total_frames > 0:
            qimg = self._decode_frame(mxf_path, 0, grading_snapshot)
            if qimg and not qimg.isNull():
                with self._cache_lock:
                    if gen == self._seek_gen and mxf_path == self.mxf_path:
                        now = time.perf_counter()
                        self._frame_cache[0] = qimg
                        self._last_presented_frame_idx = 0
                        if self._next_decode_idx <= 0:
                            self._next_decode_idx = 1
                        self._t_start = now
                        self._last_emit_time = now
                        self.frame_ready.emit(qimg, 0, 0.0)

    def seek_time(self, pts_seconds: float):
        """Instant seek to timestamp with generation barrier and audio settle guard."""
        with self._cache_lock:
            if not self.mxf_path or self.total_frames == 0:
                return
            self._seek_gen += 1
            gen = self._seek_gen
            target_idx = max(0, min(self.total_frames - 1, int(pts_seconds * self.fps)))
            self.current_frame_idx = target_idx
            self.current_pts = float(pts_seconds)
            self._last_presented_frame_idx = target_idx
            self._next_decode_idx = target_idx + 1

            now = time.perf_counter()
            self._base_pts = float(pts_seconds)
            self._t_start = now
            self._last_emit_time = now
            self._audio_synced = False
            if self.is_playing:
                self._seek_expected_pts = float(pts_seconds)
                self._seek_settle_until = now + 1.0
            else:
                self._seek_expected_pts = None
                self._seek_settle_until = 0.0

            self._frame_cache.clear()
            mxf_path = self.mxf_path
            grading_snapshot = dict(self.grading_params)

        qimg = self._decode_frame(mxf_path, target_idx, grading_snapshot)
        if qimg and not qimg.isNull():
            with self._cache_lock:
                if gen == self._seek_gen and mxf_path == self.mxf_path:
                    now = time.perf_counter()
                    self._frame_cache[target_idx] = qimg
                    self._last_presented_frame_idx = target_idx
                    if self._next_decode_idx <= target_idx:
                        self._next_decode_idx = target_idx + 1
                    self._t_start = now
                    self._last_emit_time = now
                    if self.is_playing:
                        self._seek_settle_until = now + 1.0
                    self.frame_ready.emit(qimg, target_idx, float(pts_seconds))

        self._wake_event.set()
        try:
            if self.is_playing and not self._presentation_timer.isActive():
                self._start_presentation_timer()
        except (RuntimeError, AttributeError):
            pass

    def step_frame(self, delta: int = 1):
        """Advance or rewind by delta frames."""
        with self._cache_lock:
            if not self.mxf_path or self.total_frames == 0:
                return
            target_idx = max(0, min(self.total_frames - 1, self.current_frame_idx + delta))
            self.current_frame_idx = target_idx
            self.current_pts = target_idx / self.fps
            self._last_presented_frame_idx = target_idx - 1
            self._next_decode_idx = target_idx
            self._base_pts = self.current_pts
            self._t_start = time.perf_counter()
            gen = self._seek_gen
            mxf_path = self.mxf_path
            grading_snapshot = dict(self.grading_params)
            qimg = self._frame_cache.get(target_idx)

        if qimg is None:
            qimg = self._decode_frame(mxf_path, target_idx, grading_snapshot)
            if qimg and not qimg.isNull():
                with self._cache_lock:
                    if gen == self._seek_gen and mxf_path == self.mxf_path:
                        self._frame_cache[target_idx] = qimg

        if qimg and not qimg.isNull():
            with self._cache_lock:
                if gen == self._seek_gen and mxf_path == self.mxf_path:
                    self._last_presented_frame_idx = target_idx
                    self._next_decode_idx = target_idx + 1
                    self.frame_ready.emit(qimg, target_idx, self.current_pts)

        self._wake_event.set()

    def sync_audio_clock(self, audio_pts: float):
        """
        Called by mpv audio observer (~12.5 Hz).
        Updates master continuous display clock with PLL phase-lock drift correction.
        Filters out stale pre-seek audio timestamps right after seeks/reel switches.
        """
        with self._cache_lock:
            if not self.is_playing or not self.mxf_path or self.total_frames == 0:
                return

            now = time.perf_counter()

            # Reject stale pre-seek mpv timestamps while demuxer audio is settling
            if self._seek_expected_pts is not None:
                if abs(audio_pts - self._seek_expected_pts) <= 1.5:
                    # Audio has reached the seek target; clear barrier and phase-lock cleanly
                    self._seek_expected_pts = None
                    self._seek_settle_until = 0.0
                elif now < self._seek_settle_until:
                    return
                else:
                    # Settle window expired; resume normal audio sync so A/V never diverges
                    self._seek_expected_pts = None
                    self._seek_settle_until = 0.0

            current_display_pts = self._base_pts + (now - self._t_start)
            drift = audio_pts - current_display_pts

            if abs(drift) > 0.15:
                # Large discontinuity or post-seek offset: re-anchor video clock immediately
                self._base_pts = audio_pts
                self._t_start = now
                self._audio_synced = True
                target_idx = max(0, min(self.total_frames - 1, int(audio_pts * self.fps)))
                self.current_frame_idx = target_idx
                self.current_pts = float(audio_pts)
                if target_idx < self._last_presented_frame_idx - 4 or target_idx > self._last_presented_frame_idx + 3:
                    self._last_presented_frame_idx = target_idx - 1
                    self._next_decode_idx = target_idx
            elif not self._audio_synced:
                # Initial post-seek / startup lock: gently phase-lock without rewinding presented frames
                self._audio_synced = True
                self._base_pts += drift * 0.25
            else:
                # Continuous PLL phase correction: smoothly eliminate clock drift without skipping
                self._base_pts += drift * 0.1

        self._wake_event.set()
        try:
            if self.is_playing and not self._presentation_timer.isActive():
                self._start_presentation_timer()
        except (RuntimeError, AttributeError):
            pass

    def _on_presentation_tick(self):
        """
        High-precision presentation tick: advances continuous display PTS
        and emits decoded frames at exact 24.0 FPS native cadence without dropping.
        """
        ended = False
        emit_args = None

        with self._cache_lock:
            if not self.is_playing or not self.mxf_path or self.total_frames == 0:
                return

            now = time.perf_counter()
            display_pts = self._base_pts + (now - self._t_start)
            raw_idx = int(display_pts * self.fps)
            target_idx = max(0, min(self.total_frames - 1, raw_idx))

            if target_idx > self._last_presented_frame_idx:
                lag = target_idx - self._last_presented_frame_idx
                next_seq = self._last_presented_frame_idx + 1
                if lag <= 3 and next_seq in self._frame_cache:
                    # Enforce minimum inter-frame spacing to prevent compressed bursts after a seek/jitter
                    if self._last_emit_time > 0.0 and (now - self._last_emit_time) < (0.72 / self.fps):
                        return
                    target_idx = next_seq
                    qimg = self._frame_cache.get(target_idx)
                else:
                    qimg = self._frame_cache.get(target_idx)
                    if qimg is None and lag > 3:
                        # True clock jump ahead (e.g. post-seek or audio resync): fast-forward worker target
                        self._last_presented_frame_idx = target_idx - 1
                        if self._next_decode_idx < target_idx:
                            self._next_decode_idx = target_idx

                if qimg is not None:
                    self._last_presented_frame_idx = target_idx
                    self._last_emit_time = now
                    self.current_frame_idx = target_idx
                    self.current_pts = target_idx / self.fps
                    emit_args = (qimg, target_idx, self.current_pts)

            if raw_idx >= self.total_frames and emit_args is None:
                self.is_playing = False
                self._audio_synced = False
                ended = True

        if ended:
            self._stop_presentation_timer()
            self.playback_ended.emit()
            return

        if emit_args is not None:
            self.frame_ready.emit(*emit_args)
            self._frame_counter += 1
            t_now = time.time()
            if t_now - self._last_fps_report >= 1.0:
                measured_fps = self._frame_counter / (t_now - self._last_fps_report)
                self.fps_updated.emit(measured_fps)
                self._frame_counter = 0
                self._last_fps_report = t_now

        self._wake_event.set()

    def close(self):
        """Cleanly stop worker thread and free cache."""
        self.pause()
        self._stop_event.set()
        self._wake_event.set()
        with self._cache_lock:
            self._frame_cache.clear()
