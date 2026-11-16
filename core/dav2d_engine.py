"""
BOOB Player - VideoLAN dav2d AV2 Decoder Integration Engine
Interfaces with VideoLAN's next-generation AV2 software decoder (code.videolan.org/videolan/dav2d).
Supports dynamic ctypes binding to libdav2d.dll / dav2d.dll and CLI pipeline (dav2d.exe).
"""

import os
import sys
import ctypes
import shutil
import subprocess
from typing import Optional, Dict, Any, Tuple
from core.app_paths import get_lib_dir, get_app_base_dir, find_external_tool


class Dav2dSettings(ctypes.Structure):
    """C struct mapping for dav2d_default_settings."""
    _fields_ = [
        ("n_threads", ctypes.c_int),
        ("max_frame_delay", ctypes.c_int),
        ("apply_grain", ctypes.c_int),
        ("operating_point", ctypes.c_int),
        ("all_layers", ctypes.c_int),
        ("frame_size_limit", ctypes.c_uint),
        ("strict_std_compliance", ctypes.c_int),
        ("reserved", ctypes.c_uint8 * 32),
    ]


class Dav2dData(ctypes.Structure):
    """C struct mapping for dav2d input bitstream data."""
    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_uint8)),
        ("sz", ctypes.c_size_t),
        ("ref", ctypes.c_void_p),
        ("m", ctypes.c_void_p),
    ]


class Dav2dPicParameters(ctypes.Structure):
    """C struct mapping for picture geometry and bit depth."""
    _fields_ = [
        ("w", ctypes.c_int),
        ("h", ctypes.c_int),
        ("layout", ctypes.c_int),
        ("bpc", ctypes.c_int),
    ]


class Dav2dPicture(ctypes.Structure):
    """C struct mapping for decoded YUV frame buffer planes."""
    _fields_ = [
        ("seq_hdr", ctypes.c_void_p),
        ("frame_hdr", ctypes.c_void_p),
        ("data", ctypes.c_void_p * 3),
        ("stride", ctypes.c_ssize_t * 2),
        ("p", Dav2dPicParameters),
        ("m", ctypes.c_void_p),
        ("ref", ctypes.c_void_p),
        ("allocator_data", ctypes.c_void_p),
    ]


class Dav2dEngine:
    """
    Hardware-accelerated and multi-threaded CPU video decoder for AOMedia AV2
    powered by VideoLAN's dav2d engine.
    """

    _instance: Optional["Dav2dEngine"] = None

    def __init__(self):
        self.dll_path: Optional[str] = self._find_dav2d_dll()
        self.cli_path: Optional[str] = self._find_dav2d_cli()
        self.lib: Optional[ctypes.CDLL] = None
        self._version_str: str = ""
        self.init_error: Optional[str] = None

        if self.dll_path:
            self._load_dll(self.dll_path)

    @classmethod
    def get_instance(cls) -> "Dav2dEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _find_dav2d_dll() -> Optional[str]:
        """Locate libdav2d.dll or dav2d.dll across library directories, app root, and PATH."""
        candidates = [
            os.path.join(get_lib_dir(), "dav2d.dll"),
            os.path.join(get_lib_dir(), "libdav2d.dll"),
            os.path.join(get_lib_dir(), "libdav2d-0.dll"),
            os.path.join(get_app_base_dir(), "dav2d.dll"),
            os.path.join(get_app_base_dir(), "libdav2d.dll"),
            os.path.join(sys.prefix, "dav2d.dll"),
            os.path.join(sys.prefix, "libdav2d.dll"),
        ]

        # Check system PATH
        path_env = os.environ.get("PATH", "")
        for p in path_env.split(os.pathsep):
            p = p.strip('"').strip()
            if p:
                candidates.append(os.path.join(p, "dav2d.dll"))
                candidates.append(os.path.join(p, "libdav2d.dll"))

        for c in candidates:
            if c and os.path.isfile(c):
                return os.path.abspath(c)
        return None

    @staticmethod
    def _find_dav2d_cli() -> Optional[str]:
        """Locate standalone dav2d CLI executable."""
        found = find_external_tool("dav2d")
        if found and os.path.isfile(found):
            return found
        cli_cand = shutil.which("dav2d") or shutil.which("dav2d.exe")
        if cli_cand and os.path.isfile(cli_cand):
            return os.path.abspath(cli_cand)
        return None

    def _load_dll(self, path: str):
        """Bind C export functions from libdav2d DLL."""
        try:
            self.lib = ctypes.CDLL(path)

            # Set function signatures if available
            if hasattr(self.lib, "dav2d_version"):
                self.lib.dav2d_version.restype = ctypes.c_char_p
                self.lib.dav2d_version.argtypes = []
                ver_raw = self.lib.dav2d_version()
                self._version_str = ver_raw.decode("utf-8", errors="replace") if ver_raw else "dav2d (git)"
            else:
                self._version_str = "dav2d 0.1.0-dev"

            if hasattr(self.lib, "dav2d_default_settings"):
                self.lib.dav2d_default_settings.restype = None
                self.lib.dav2d_default_settings.argtypes = [ctypes.POINTER(Dav2dSettings)]

            if hasattr(self.lib, "dav2d_open"):
                self.lib.dav2d_open.restype = ctypes.c_int
                self.lib.dav2d_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(Dav2dSettings)]

            if hasattr(self.lib, "dav2d_send_data"):
                self.lib.dav2d_send_data.restype = ctypes.c_int
                self.lib.dav2d_send_data.argtypes = [ctypes.c_void_p, ctypes.POINTER(Dav2dData)]

            if hasattr(self.lib, "dav2d_get_picture"):
                self.lib.dav2d_get_picture.restype = ctypes.c_int
                self.lib.dav2d_get_picture.argtypes = [ctypes.c_void_p, ctypes.POINTER(Dav2dPicture)]

            if hasattr(self.lib, "dav2d_picture_unref"):
                self.lib.dav2d_picture_unref.restype = None
                self.lib.dav2d_picture_unref.argtypes = [ctypes.POINTER(Dav2dPicture)]

            if hasattr(self.lib, "dav2d_close"):
                self.lib.dav2d_close.restype = None
                self.lib.dav2d_close.argtypes = [ctypes.POINTER(ctypes.c_void_p)]

        except Exception as e:
            self.init_error = str(e)
            self.lib = None

    def is_available(self) -> bool:
        """True if either dynamic C library (libdav2d.dll) or standalone CLI (dav2d.exe) is present."""
        return bool(self.lib is not None or (self.cli_path and os.path.exists(self.cli_path)))

    def get_backend_type(self) -> str:
        """Return the active decoder backend: 'dll', 'cli', or 'none'."""
        if self.lib is not None:
            return "dll"
        if self.cli_path and os.path.exists(self.cli_path):
            return "cli"
        return "none"

    def get_version(self) -> str:
        """Return dav2d version string or build status."""
        if self._version_str:
            return self._version_str
        if self.cli_path and os.path.exists(self.cli_path):
            try:
                out = subprocess.check_output([self.cli_path, "--version"], text=True, timeout=3)
                lines = out.strip().splitlines()
                return lines[0] if lines else "dav2d CLI"
            except Exception:
                return "dav2d CLI"
        return "dav2d (Not Installed - code.videolan.org/videolan/dav2d)"

    def get_status_info(self) -> Dict[str, Any]:
        """Return comprehensive status dictionary for diagnostics and UI HUD."""
        return {
            "available": self.is_available(),
            "backend": self.get_backend_type(),
            "version": self.get_version(),
            "dll_path": self.dll_path,
            "cli_path": self.cli_path,
            "repo_url": "https://code.videolan.org/videolan/dav2d.git",
            "error": self.init_error,
        }
