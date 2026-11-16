"""
Hardware GPU Detection Engine for BOOB Player.
Detects active GPUs (NVIDIA, AMD, Intel, Generic) across system drivers, CUDA,
and Windows display devices without external dependencies.
"""

import os
import sys
import ctypes
from ctypes import wintypes
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class GPUInfo:
    name: str
    short_name: str
    vendor: str
    has_cuda: bool
    has_nvjpeg2k: bool
    is_nvidia: bool
    is_amd: bool
    is_intel: bool
    device_index: int = 0
    has_opencl: bool = False
    has_grok: bool = False
    jp2k_backend: str = "cpu"


class GPUDetector:
    _cached_info: Optional[GPUInfo] = None
    _cached_all: Optional[List[GPUInfo]] = None

    @classmethod
    def get_info(cls, force_refresh: bool = False) -> GPUInfo:
        """
        Returns primary detected GPU information (cached singleton).
        Prioritizes discrete/high-performance GPUs (NVIDIA, AMD) over integrated GPUs.
        """
        if cls._cached_info is not None and not force_refresh:
            return cls._cached_info

        all_gpus = cls.detect_all_gpus()
        if all_gpus:
            # Prefer NVIDIA (for nvJPEG2000 / CUDA), then AMD with Grok/OpenCL, then Intel Arc, then generic
            def _rank(g: GPUInfo) -> int:
                if g.has_cuda and g.has_nvjpeg2k:
                    return 100
                if g.is_amd and (g.has_opencl or g.has_grok):
                    return 95
                if g.is_intel and "arc" in g.name.lower() and (g.has_opencl or g.has_grok):
                    return 85
                if g.is_nvidia:
                    return 80
                if g.is_amd:
                    return 70
                if g.is_intel and "arc" in g.name.lower():
                    return 60
                if g.is_intel and (g.has_opencl or g.has_grok):
                    return 50
                if g.is_intel:
                    return 30
                return 10

            sorted_gpus = sorted(all_gpus, key=_rank, reverse=True)
            cls._cached_info = sorted_gpus[0]
        else:
            cls._cached_info = GPUInfo(
                name="Hardware GPU",
                short_name="GPU",
                vendor="Generic",
                has_cuda=False,
                has_nvjpeg2k=False,
                is_nvidia=False,
                is_amd=False,
                is_intel=False,
                device_index=0,
                has_opencl=False,
                has_grok=False,
                jp2k_backend="cpu",
            )

        return cls._cached_info

    @classmethod
    def get_jp2k_backend(cls) -> str:
        """Returns the active GPU hardware backend for JPEG 2000 ('nvjpeg2k', 'grok_opencl', or 'cpu')."""
        info = cls.get_info()
        return getattr(info, "jp2k_backend", "cpu")

    @classmethod
    def has_gpu_jp2k(cls) -> bool:
        """Returns True if any GPU JPEG 2000 hardware acceleration is active (CUDA or Grok OpenCL)."""
        info = cls.get_info()
        return bool(info.has_nvjpeg2k or info.has_grok or (info.has_opencl and (info.is_amd or info.is_intel)))

    @classmethod
    def detect_all_gpus(cls) -> List[GPUInfo]:
        """
        Enumerate all graphics adapters detected on the system.
        Queries CUDA driver API, Windows EnumDisplayDevices, and OpenCL compute platforms.
        """
        detected: List[GPUInfo] = []
        seen_names = set()

        # 1. Query NVIDIA CUDA Driver directly (nvcuda.dll)
        cuda_gpus = cls._query_cuda()
        for g in cuda_gpus:
            if g.name.lower() not in seen_names:
                detected.append(g)
                seen_names.add(g.name.lower())

        # 2. Query Windows Display Devices (EnumDisplayDevicesW)
        if sys.platform == "win32":
            win_gpus = cls._query_windows_display_devices()
            for g in win_gpus:
                # Deduplicate if CUDA already registered the same physical adapter
                norm = re.sub(r'[^a-zA-Z0-9]', '', g.name.lower())
                already_found = any(norm in re.sub(r'[^a-zA-Z0-9]', '', s) or re.sub(r'[^a-zA-Z0-9]', '', s) in norm for s in seen_names)
                if not already_found:
                    detected.append(g)
                    seen_names.add(g.name.lower())

        # 3. Query OpenCL Compute Platforms & Devices (OpenCL.dll for AMD, Intel, NVIDIA)
        opencl_gpus = cls._query_opencl()
        for g in opencl_gpus:
            norm = re.sub(r'[^a-zA-Z0-9]', '', g.name.lower())
            matched = False
            for existing in detected:
                ex_norm = re.sub(r'[^a-zA-Z0-9]', '', existing.name.lower())
                if norm in ex_norm or ex_norm in norm:
                    existing.has_opencl = True
                    existing.has_grok = g.has_grok
                    if existing.jp2k_backend == "cpu" and g.jp2k_backend != "cpu":
                        existing.jp2k_backend = g.jp2k_backend
                    matched = True
                    break
            if not matched:
                detected.append(g)
                seen_names.add(g.name.lower())

        return detected

    @classmethod
    def _query_cuda(cls) -> List[GPUInfo]:
        results: List[GPUInfo] = []
        try:
            cuda_lib = "nvcuda.dll" if sys.platform == "win32" else "libcuda.so"
            cuda = ctypes.CDLL(cuda_lib)
            if cuda.cuInit(0) != 0:
                return results

            num_devs = ctypes.c_int()
            if hasattr(cuda, "cuDeviceGetCount"):
                if cuda.cuDeviceGetCount(ctypes.byref(num_devs)) != 0:
                    num_devs.value = 1
            else:
                num_devs.value = 1

            has_nvjpeg2k = False
            try:
                from core.nvjpeg2k_engine import NVJPEG2KEngine
                has_nvjpeg2k = NVJPEG2KEngine.is_available()
            except Exception:
                pass

            for idx in range(max(1, num_devs.value)):
                dev = ctypes.c_int()
                if cuda.cuDeviceGet(ctypes.byref(dev), idx) == 0:
                    name_buf = (ctypes.c_char * 256)()
                    if cuda.cuDeviceGetName(name_buf, 256, dev) == 0:
                        raw_name = name_buf.value.decode("utf-8", errors="ignore").strip()
                        if raw_name:
                            short = cls.format_short_gpu_name(raw_name)
                            results.append(GPUInfo(
                                name=raw_name,
                                short_name=short,
                                vendor="NVIDIA",
                                has_cuda=True,
                                has_nvjpeg2k=has_nvjpeg2k,
                                is_nvidia=True,
                                is_amd=False,
                                is_intel=False,
                                device_index=idx,
                            ))
        except Exception:
            pass
        return results

    @classmethod
    def _query_windows_display_devices(cls) -> List[GPUInfo]:
        results: List[GPUInfo] = []
        try:
            user32 = ctypes.windll.user32

            class DISPLAY_DEVICE(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("DeviceName", ctypes.c_wchar * 32),
                    ("DeviceString", ctypes.c_wchar * 128),
                    ("StateFlags", wintypes.DWORD),
                    ("DeviceID", ctypes.c_wchar * 128),
                    ("DeviceKey", ctypes.c_wchar * 128),
                ]

            dd = DISPLAY_DEVICE()
            dd.cb = ctypes.sizeof(DISPLAY_DEVICE)
            i = 0
            seen_strings = set()

            while user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                d_str = dd.DeviceString.strip()
                if d_str and d_str.lower() not in seen_strings:
                    seen_strings.add(d_str.lower())
                    # Exclude virtual / remote desktop / dummy drivers
                    low = d_str.lower()
                    if not any(v in low for v in ["virtual", "basic render", "rdp", "mirage", "remote", "vnc"]):
                        vendor = "Generic"
                        is_nv = False
                        is_amd = False
                        is_intel = False

                        if any(k in low for k in ["nvidia", "geforce", "rtx", "gtx", "quadro", "tesla", "titan"]):
                            vendor = "NVIDIA"
                            is_nv = True
                        elif any(k in low for k in ["amd", "radeon", "firepro", "ryzen"]):
                            vendor = "AMD"
                            is_amd = True
                        elif any(k in low for k in ["intel", "arc", "iris", "uhd", "hd graphics"]):
                            vendor = "Intel"
                            is_intel = True

                        short = cls.format_short_gpu_name(d_str)
                        results.append(GPUInfo(
                            name=d_str,
                            short_name=short,
                            vendor=vendor,
                            has_cuda=False,
                            has_nvjpeg2k=False,
                            is_nvidia=is_nv,
                            is_amd=is_amd,
                            is_intel=is_intel,
                            device_index=i,
                        ))
                i += 1
        except Exception:
            pass
        return results

    @classmethod
    def _query_opencl(cls) -> List[GPUInfo]:
        results: List[GPUInfo] = []
        try:
            cl = ctypes.CDLL("OpenCL.dll")
            cl.clGetPlatformIDs.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
            cl.clGetPlatformIDs.restype = ctypes.c_int32
            cl.clGetPlatformInfo.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
            cl.clGetPlatformInfo.restype = ctypes.c_int32
            cl.clGetDeviceIDs.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
            cl.clGetDeviceIDs.restype = ctypes.c_int32
            cl.clGetDeviceInfo.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
            cl.clGetDeviceInfo.restype = ctypes.c_int32

            num_p = ctypes.c_uint32()
            if cl.clGetPlatformIDs(0, None, ctypes.byref(num_p)) != 0 or num_p.value == 0:
                return results

            platforms = (ctypes.c_void_p * num_p.value)()
            if cl.clGetPlatformIDs(num_p.value, platforms, None) != 0:
                return results

            grok_avail = False
            try:
                from core.grok_engine import GrokOpenCLEngine
                grok_avail = GrokOpenCLEngine.is_available()
            except Exception:
                pass

            dev_idx = 0
            for p in platforms:
                p_buf = (ctypes.c_char * 256)()
                cl.clGetPlatformInfo(p, 0x0902, 256, p_buf, None)
                p_name = p_buf.value.decode("utf-8", errors="ignore").strip()

                num_d = ctypes.c_uint32()
                if cl.clGetDeviceIDs(p, 0xFFFFFFFF, 0, None, ctypes.byref(num_d)) != 0 or num_d.value == 0:
                    continue
                devices = (ctypes.c_void_p * num_d.value)()
                if cl.clGetDeviceIDs(p, 0xFFFFFFFF, num_d.value, devices, None) != 0:
                    continue

                for d in devices:
                    d_buf = (ctypes.c_char * 256)()
                    cl.clGetDeviceInfo(d, 0x102B, 256, d_buf, None) # CL_DEVICE_NAME
                    d_name = d_buf.value.decode("utf-8", errors="ignore").strip()
                    if not d_name:
                        continue

                    v_buf = (ctypes.c_char * 256)()
                    cl.clGetDeviceInfo(d, 0x102C, 256, v_buf, None) # CL_DEVICE_VENDOR
                    d_vendor = v_buf.value.decode("utf-8", errors="ignore").strip()

                    low = (p_name + " " + d_name + " " + d_vendor).lower()
                    is_nv = any(k in low for k in ["nvidia", "geforce", "rtx", "gtx", "quadro", "tesla"])
                    is_amd = any(k in low for k in ["amd", "advanced micro devices", "radeon", "firepro", "ryzen"])
                    is_intel = any(k in low for k in ["intel", "arc", "iris", "uhd", "hd graphics"])

                    vendor = "NVIDIA" if is_nv else ("AMD" if is_amd else ("Intel" if is_intel else "Generic"))
                    short = cls.format_short_gpu_name(d_name)

                    has_cuda = is_nv
                    has_nvjpeg2k = False
                    if is_nv:
                        try:
                            from core.nvjpeg2k_engine import NVJPEG2KEngine
                            has_nvjpeg2k = NVJPEG2KEngine.is_available()
                        except Exception:
                            pass

                    backend = "cpu"
                    if is_nv and has_nvjpeg2k:
                        backend = "nvjpeg2k"
                    elif (is_amd or is_intel or is_nv) and grok_avail:
                        backend = "grok_opencl"

                    results.append(GPUInfo(
                        name=d_name,
                        short_name=short,
                        vendor=vendor,
                        has_cuda=has_cuda,
                        has_nvjpeg2k=has_nvjpeg2k,
                        is_nvidia=is_nv,
                        is_amd=is_amd,
                        is_intel=is_intel,
                        device_index=dev_idx,
                        has_opencl=True,
                        has_grok=grok_avail,
                        jp2k_backend=backend,
                    ))
                    dev_idx += 1
        except Exception:
            pass
        return results

    @staticmethod
    def format_short_gpu_name(full_name: str) -> str:
        """
        Cleans and formats a lengthy GPU device string into a concise, readable badge.
        Examples:
        - "NVIDIA GeForce RTX 5050 Laptop GPU" -> "RTX 5050"
        - "NVIDIA GeForce RTX 4090" -> "RTX 4090"
        - "NVIDIA GeForce GTX 1660 SUPER" -> "GTX 1660 SUPER"
        - "NVIDIA RTX A5000" -> "RTX A5000"
        - "AMD Radeon RX 7900 XTX" -> "RX 7900 XTX"
        - "AMD Radeon RX 6700 XT" -> "RX 6700 XT"
        - "Intel(R) Arc(TM) A770 Graphics" -> "Arc A770"
        - "Intel(R) Iris(R) Xe Graphics" -> "Iris Xe"
        """
        if not full_name or full_name == "Hardware GPU":
            return "GPU"

        name = full_name
        name = re.sub(r"[\(（](?:TM|tm|R|r)[\)）]", "", name)
        name = name.replace("™", "").replace("®", "").strip()

        # Specific GPU model match
        m = re.search(
            r"\b("
            r"RTX\s+[0-9A-Za-z]+(?:\s+Ti|\s+SUPER)?"
            r"|GTX\s+[0-9A-Za-z]+(?:\s+Ti|\s+SUPER)?"
            r"|RX\s+[0-9A-Za-z]+(?:\s+XTX|\s+XT|\s+GRE)?"
            r"|Arc\s+[0-9A-Za-z]+"
            r"|Iris\s+Xe"
            r"|Quadro\s+[0-9A-Za-z]+"
            r"|Tesla\s+[0-9A-Za-z]+"
            r")",
            name,
            re.IGNORECASE
        )
        if m:
            return m.group(1).strip()

        # Clean common prefixes and suffixes
        cleaned = re.sub(
            r"^(?:NVIDIA\s+(?:GeForce\s+)?|AMD\s+(?:Radeon\s+)?|Intel\s+)",
            "",
            name,
            flags=re.IGNORECASE
        ).strip()
        cleaned = re.sub(
            r"\s+(?:Graphics|Laptop GPU|Desktop|Adapter)$",
            "",
            cleaned,
            flags=re.IGNORECASE
        ).strip()

        return cleaned if cleaned else full_name
