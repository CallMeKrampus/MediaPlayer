"""
BOOB Player - Standalone Portable Executable Packaging Configuration (cx_Freeze)
Packages BOOB Player and every runtime tool/dependency into a self-contained
portable folder without PyInstaller, excluding all local DCP/media assets.
"""

import os
import sys
from cx_Freeze import setup, Executable

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.app_paths import find_external_tool
from core.nvjpeg2k_engine import NVJPEG2KEngine


REDIST_DLLS = (
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "vcruntime140_threads.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll",
    "concrt140.dll",
    "vccorlib140.dll",
    "d3dcompiler_47.dll",
    "opengl32sw.dll",
)


def _find_redist_dll(dll_name: str):
    """Locate MSVC C/C++ runtime and D3D/OpenGL fallback DLLs from Qt6 or Python."""
    candidates = []
    try:
        import PyQt6
        candidates.append(os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "bin", dll_name))
    except Exception:
        pass
    candidates.extend([
        os.path.join(sys.prefix, dll_name),
        os.path.join(sys.prefix, "DLLs", dll_name),
        os.path.join(os.path.dirname(sys.executable), dll_name),
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", dll_name),
    ])
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def collect_include_files():
    """Collect GLSL shaders, native libraries, CLI media tools, and runtime DLLs (never DCPs/media)."""
    files = []

    # 1. GLSL Tonemapping & DCI-XYZ Shaders
    shaders_dir = os.path.join(BASE_DIR, "shaders")
    if os.path.isdir(shaders_dir):
        files.append((shaders_dir, "shaders"))

    # 2. Core playback engine DLL (libmpv)
    # Include single pristine DLL instance to avoid 116MB duplicate file bloat
    for dll_name in ("libmpv-2.dll", "mpv-2.dll"):
        dll_src = os.path.join(BASE_DIR, "lib", dll_name)
        if os.path.isfile(dll_src):
            files.append((dll_src, os.path.join("lib", "libmpv-2.dll")))
            break

    # 3. Hardware JPEG 2000 decoder DLL (nvJPEG2000)
    nv_dll = NVJPEG2KEngine._find_nvjpeg2k_dll()
    if nv_dll and os.path.isfile(nv_dll):
        files.append((nv_dll, os.path.join("lib", os.path.basename(nv_dll))))

    # 4. Standalone FFmpeg & FFprobe CLI tools
    for tool_name in ("ffmpeg", "ffprobe"):
        tool_src = find_external_tool(tool_name)
        if tool_src and os.path.isfile(tool_src):
            files.append((tool_src, os.path.join("lib", f"{tool_name}.exe")))

    # 5. Complete MSVC C/C++ runtime + D3D/OpenGL software fallback DLLs
    for dll_name in REDIST_DLLS:
        dll_src = _find_redist_dll(dll_name)
        if dll_src and os.path.isfile(dll_src):
            files.append((dll_src, os.path.join("lib", dll_name)))

    # 6. TLS/SSL root CA certificates for HTTPS IPTV streams
    try:
        import certifi
        cacert = certifi.where()
        if cacert and os.path.isfile(cacert):
            files.append((cacert, os.path.join("lib", "cacert.pem")))
    except Exception:
        pass

    return files


build_exe_options = {
    "build_exe": os.path.join(BASE_DIR, "dist", "BOOBPlayer"),
    "packages": [
        "core",
        "ui",
        "PyQt6",
        "mpv",
        "numpy",
        "requests",
        "certifi",
        "urllib",
        "xml",
        "json",
        "ctypes",
        "ssl",
    ],
    "includes": [
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtOpenGL",
        "PyQt6.QtOpenGLWidgets",
    ],
    "excludes": [
        # Prune completely unused 3rd party frameworks & legacy Qt5
        "cv2",
        "PyQt5",
        "PyQt6.QtQuick",
        "PyQt6.QtQml",
        "PyQt6.QtDesigner",
        "PyQt6.QtSql",
        "PyQt6.QtTest",
        "PyQt6.QtPdf",
        "PyQt6.QtSvg",
        "PyQt6.QtPrintSupport",
        "PyQt6.QtNetworkAuth",
        "torch",
        "torchvision",
        "transformers",
        "diffusers",
        "scipy",
        "matplotlib",
        "pandas",
        "IPython",
        "jupyter",
        "gradio",
        "fastapi",
        "uvicorn",
        "pyinstaller",
        "PyInstaller",
        "tkinter",
        "unittest",
        "test",
    ],
    "include_files": collect_include_files(),
    "include_msvcr": True,
}

executables = [
    Executable(
        script=os.path.join(BASE_DIR, "boob_player.py"),
        base="gui" if sys.platform == "win32" else None,
        target_name="BOOBPlayer.exe" if sys.platform == "win32" else "BOOBPlayer",
    )
]

if __name__ == "__main__":
    setup(
        name="BOOB Player",
        version="2.0.0",
        description="BOOB Player - Cinema DCP, IAB Atmos & HDR Reference Media Player",
        options={"build_exe": build_exe_options},
        executables=executables,
    )
