"""
BOOB Player - Application Path & Portable Runtime Resolution Utility
Resolves base directory, shader directory, bundled CLI tools, SSL certificates,
and native DLL paths for both source execution and standalone portable builds.
"""

import os
import shutil
import sys
from typing import Optional


def is_frozen() -> bool:
    """Return True when running inside a packaged executable bundle."""
    return bool(getattr(sys, "frozen", False) or ("__compiled__" in globals()))


def get_app_base_dir() -> str:
    """Return the root application directory for both source and frozen builds."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_lib_dir() -> str:
    return os.path.join(get_app_base_dir(), "lib")


def get_shaders_dir() -> str:
    return os.path.join(get_app_base_dir(), "shaders")


def find_external_tool(tool_name: str) -> Optional[str]:
    """Locate an external CLI binary (e.g., ffmpeg, ffprobe) without assuming host PATH."""
    base_name = os.path.basename(tool_name)
    exe_name = base_name if base_name.lower().endswith(".exe") else f"{base_name}.exe"

    candidates = [
        os.path.join(get_lib_dir(), exe_name),
        os.path.join(get_app_base_dir(), exe_name),
        os.path.join(get_lib_dir(), base_name),
        os.path.join(get_app_base_dir(), base_name),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand

    which_hit = shutil.which(base_name) or shutil.which(exe_name)
    if which_hit and os.path.isfile(which_hit):
        return which_hit

    fallback_dir = r"D:\ffmpeg\bin"
    fallback_exe = os.path.join(fallback_dir, exe_name)
    if os.path.isfile(fallback_exe):
        return fallback_exe

    return None


def get_tool_path(tool_name: str) -> str:
    """Return resolved executable path for a bundled/system tool, or tool_name as fallback."""
    return find_external_tool(tool_name) or tool_name


def ensure_portable_environment() -> None:
    """Prepare PATH, Windows DLL search directories, and TLS certificates for portable runs."""
    lib_dir = get_lib_dir()
    base_dir = get_app_base_dir()

    current_path = os.environ.get("PATH", "")
    path_parts = [p for p in current_path.split(os.pathsep) if p] if current_path else []
    for folder in (lib_dir, base_dir):
        if os.path.isdir(folder):
            if folder not in path_parts:
                path_parts.insert(0, folder)
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(folder)
                except Exception:
                    pass
    if path_parts:
        os.environ["PATH"] = os.pathsep.join(path_parts)

    cacert_cand = os.path.join(lib_dir, "cacert.pem")
    if not os.path.isfile(cacert_cand):
        try:
            import certifi
            cacert_cand = certifi.where()
        except Exception:
            cacert_cand = ""
    if cacert_cand and os.path.isfile(cacert_cand):
        os.environ.setdefault("SSL_CERT_FILE", cacert_cand)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", cacert_cand)
