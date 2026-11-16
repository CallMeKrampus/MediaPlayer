"""
BOOB Player - Standalone Portable Packaging & Pre-Flight Build Verification Tool (cx_Freeze)
Usage:
    python build_exe.py --check        # Verify cx_Freeze config, tools, DLLs, and zero DCP/media bundling
    python build_exe.py --build        # Build standalone portable executable into dist/BOOBPlayer
    python build_exe.py --archive      # Pack dist/BOOBPlayer into ultra-compact distribution archive (.7z / .zip)
    python build_exe.py --smoke-test   # Launch the built exe (must show its main window, no startup error)
    python build_exe.py --clean        # Clean previous build and dist artifacts
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Optional, List, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FORBIDDEN_DIR_NAMES = ("lostwolves", "ramayana", "sample_dcp", "assets")
FORBIDDEN_EXTS = (".mxf", ".mov", ".webm", ".mp4", ".mkv", ".wav")
REQUIRED_DESTS = (
    "shaders",
    "lib/libmpv-2.dll",
    "lib/mpv-2.dll",
    "lib/nvjpeg2k_0.dll",
    "lib/ffmpeg.exe",
    "lib/ffprobe.exe",
    "lib/dovi_tool.exe",
    "lib/dav2d.exe",
    "lib/rav2d.exe",
    "lib/cacert.pem",
    "lib/vcruntime140.dll",
    "lib/msvcp140.dll",
    "lib/d3dcompiler_47.dll",
    "lib/opengl32sw.dll",
)


REQUIRED_CORE_MODULES = (
    "core/shader_integrity.py",   # libmpv shader miscompile detector + OpenGL fallback trigger
    "core/frame_sampler.py",      # render-defect watchdog sampler
)
REMOVED_CORE_MODULES = ("core/debug_logger.py",)  # wrote to sys.stderr, which is None in the windowed exe

# The windowed (cx_Freeze "gui") executable starts with sys.stdout and sys.stderr set to None,
# so any direct write raises AttributeError and aborts startup with a modal error dialog.
_UNSAFE_STREAM_USE = re.compile(
    r"sys\.(stderr|stdout)\.(write|flush|buffer)|file\s*=\s*sys\.(stderr|stdout)|DebugLogger|core\.debug_logger"
)


def check_runtime_sources() -> List[str]:
    """Static checks on the files that get frozen into the app."""
    errors: List[str] = []
    for rel in REQUIRED_CORE_MODULES:
        if not os.path.isfile(os.path.join(BASE_DIR, rel)):
            errors.append(f"Missing required module: {rel}")
    for rel in REMOVED_CORE_MODULES:
        if os.path.isfile(os.path.join(BASE_DIR, rel)):
            errors.append(f"Removed module is back and would be frozen into the app: {rel}")

    sources = [os.path.join(BASE_DIR, "boob_player.py")]
    for sub in ("core", "ui"):
        d = os.path.join(BASE_DIR, sub)
        if os.path.isdir(d):
            sources += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".py")]
    for path in sources:
        try:
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if line.lstrip().startswith("#"):
                        continue
                    if _UNSAFE_STREAM_USE.search(line):
                        rel = os.path.relpath(path, BASE_DIR)
                        errors.append(
                            f"{rel}:{lineno}: writes to sys.stderr/stdout or uses the removed debug logger "
                            f"(both are None in the windowed exe): {line.strip()[:90]}"
                        )
        except OSError as e:
            errors.append(f"Cannot read {path}: {e}")
    return errors


def verify_packaging_readiness() -> int:
    """Validate that cx_Freeze bundles all runtime tools and excludes DCPs/media."""
    import cx_Freeze
    import setup as pkg_setup

    assert "PyInstaller" in pkg_setup.build_exe_options["excludes"]
    assert "pyinstaller" in pkg_setup.build_exe_options["excludes"]
    assert pkg_setup.executables[0].target_name in ("BOOBPlayer.exe", "BOOBPlayer")

    include_files = pkg_setup.build_exe_options["include_files"]
    dest_map = {dst.replace("\\", "/"): src for src, dst in include_files}

    errors = []
    for req in REQUIRED_DESTS:
        if req not in dest_map:
            errors.append(f"Missing required runtime asset in include_files: {req}")

    # Enforce strict exclusion of DCPs and sample/local media files
    for src, dst in include_files:
        norm_src = src.replace("\\", "/").lower()
        norm_dst = dst.replace("\\", "/").lower()
        for bad_dir in FORBIDDEN_DIR_NAMES:
            if f"/{bad_dir}/" in norm_src or norm_src.endswith(f"/{bad_dir}") or bad_dir in norm_dst:
                errors.append(f"Forbidden DCP/media folder included: {src} -> {dst}")
        if norm_src.endswith(FORBIDDEN_EXTS) or norm_dst.endswith(FORBIDDEN_EXTS):
            errors.append(f"Forbidden media file included: {src} -> {dst}")

    # Check shader directory contents
    shaders_src = os.path.join(BASE_DIR, "shaders")
    if not os.path.isdir(shaders_src):
        errors.append(f"Missing shaders directory: {shaders_src}")
    else:
        glsl_count = len([f for f in os.listdir(shaders_src) if f.endswith(".glsl")])
        if glsl_count < 10:
            errors.append(f"Insufficient GLSL shaders found in {shaders_src}: found {glsl_count}, expected >= 10")

    script_path = os.path.join(BASE_DIR, "boob_player.py")
    if not os.path.isfile(script_path):
        errors.append(f"Missing entry script: {script_path}")

    errors.extend(check_runtime_sources())

    print(f"[Packaging] Engine: cx_Freeze {cx_Freeze.__version__} (PyInstaller excluded)")
    print(f"[Packaging] Target GUI Executable: {pkg_setup.executables[0].target_name}")
    print(f"[Packaging] Output Directory: {pkg_setup.build_exe_options['build_exe']}")
    for src, dst in sorted(include_files, key=lambda x: x[1]):
        print(f"[Packaging] Asset: {dst} <- {src}")

    if errors:
        for err in errors:
            print(f"[Packaging] ERROR: {err}", file=sys.stderr)
        return 1

    print("[Packaging] Verified zero DCPs/media files bundled; all portable tools & DLLs ready.")
    return 0


def clean_build_artifacts() -> None:
    """Remove previous build and dist directories."""
    for folder in ("build", os.path.join("dist", "BOOBPlayer")):
        p = os.path.join(BASE_DIR, folder)
        if os.path.isdir(p):
            print(f"[Packaging] Cleaning: {p}")
            shutil.rmtree(p, ignore_errors=True)


GUI_ERROR_DIALOG_TITLES = (
    "cx_Freeze: Python error in main script",
    "cx_Freeze: Python error in startup script",
)
GUI_MAIN_WINDOW_TITLE = "BOOB Player"


def _top_level_window_titles() -> List[str]:
    """Titles of all visible top-level windows (Windows only)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    titles: List[str] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                titles.append(buf.value)
        return True

    user32.EnumWindows(enum_proc(_cb), 0)
    return titles


def run_gui_smoke_test(base_dist: str, timeout: float = 25.0) -> int:
    """
    Launch the windowed executable (sys.stderr/sys.stdout are None there) and require its
    main window to appear. A startup exception shows a modal cx_Freeze error dialog and the
    process stays alive, so the dialog title is checked as well as the process state.
    """
    if sys.platform != "win32":
        return 0
    exe = os.path.join(base_dist, "BOOBPlayer.exe")
    if not os.path.isfile(exe):
        print(f"[SmokeTest] ERROR: GUI executable not found: {exe}", file=sys.stderr)
        return 1

    print(f"[SmokeTest] Launching windowed executable: {exe}")
    proc = subprocess.Popen(
        [exe], cwd=base_dist, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            if proc.poll() is not None:
                print(f"[SmokeTest] FAILED: GUI executable exited during startup with code {proc.returncode}.", file=sys.stderr)
                return 1
            titles = _top_level_window_titles()
            bad = [t for t in titles if t in GUI_ERROR_DIALOG_TITLES]
            if bad:
                print(f"[SmokeTest] FAILED: startup error dialog shown: '{bad[0]}'", file=sys.stderr)
                return 1
            if any(t.startswith(GUI_MAIN_WINDOW_TITLE) for t in titles):
                time.sleep(2.0)  # let deferred startup work run, then re-check
                titles = _top_level_window_titles()
                if proc.poll() is None and not any(t in GUI_ERROR_DIALOG_TITLES for t in titles):
                    print("[SmokeTest] PASS: windowed executable started and showed its main window.")
                    return 0
                print("[SmokeTest] FAILED: windowed executable failed right after showing its window.", file=sys.stderr)
                return 1
        print(f"[SmokeTest] FAILED: main window did not appear within {timeout:.0f}s.", file=sys.stderr)
        return 1
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass


def run_smoke_test(dist_dir: str = "") -> int:
    """Run non-blocking startup smoke test on the built standalone executable."""
    base_dist = dist_dir or os.path.join(BASE_DIR, "dist", "BOOBPlayer")
    return run_gui_smoke_test(base_dist)


def run_build(archive_after: bool = False, clean_first: bool = False) -> int:
    """Invoke setup.py build_exe to generate the standalone portable executable bundle."""
    if clean_first:
        clean_build_artifacts()

    rc = verify_packaging_readiness()
    if rc != 0:
        return rc

    cmd = [sys.executable, os.path.join(BASE_DIR, "setup.py"), "build_exe"]
    print(f"[Packaging] Running: {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=BASE_DIR)
    if proc.returncode != 0:
        print(f"[Packaging] ERROR: Build failed with exit code {proc.returncode}", file=sys.stderr)
        return proc.returncode
    build_dur = time.time() - t0
    print(f"[Packaging] Compilation and packaging finished in {build_dur:.1f}s.")

    # Post-build validation and file integrity checks
    dist_dir = os.path.join(BASE_DIR, "dist", "BOOBPlayer")
    lib_dist = os.path.join(dist_dir, "lib")

    # Ensure mpv-2.dll and libmpv-2.dll symmetry
    f1 = os.path.join(lib_dist, "libmpv-2.dll")
    f2 = os.path.join(lib_dist, "mpv-2.dll")
    if os.path.isfile(f1) and not os.path.isfile(f2):
        shutil.copyfile(f1, f2)
        print("[Packaging] Post-build: Created mpv-2.dll from libmpv-2.dll")
    elif os.path.isfile(f2) and not os.path.isfile(f1):
        shutil.copyfile(f2, f1)
        print("[Packaging] Post-build: Created libmpv-2.dll from mpv-2.dll")

    # Post-build smoke test
    smoke_rc = run_smoke_test(dist_dir)
    if smoke_rc != 0:
        print("[Packaging] ERROR: Post-build smoke test failed; the build is not usable, skipping archive.", file=sys.stderr)
        return smoke_rc

    if archive_after:
        return create_compressed_archive(dist_dir=dist_dir)
    return 0


def find_7z_executable() -> Optional[str]:
    candidates = [
        shutil.which("7z"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def create_compressed_archive(dist_dir: str = "", output_archive: str = "") -> int:
    """Pack dist/BOOBPlayer into an ultra-compressed portable distribution archive (.7z or .zip)."""
    import zipfile

    base_dist = dist_dir or os.path.join(BASE_DIR, "dist", "BOOBPlayer")
    if not os.path.isdir(base_dist):
        print(f"[Compress] ERROR: Build directory does not exist: {base_dist}", file=sys.stderr)
        return 1

    t0 = time.time()
    seven_zip = find_7z_executable()
    target_7z = output_archive or os.path.join(BASE_DIR, "dist", "BOOBPlayer-v2.0-Portable.7z")
    target_zip = os.path.splitext(target_7z)[0] + ".zip"

    # Calculate uncompressed size
    uncomp_bytes = sum(
        os.path.getsize(os.path.join(r, f))
        for r, _, files in os.walk(base_dist)
        for f in files
    )
    uncomp_mb = uncomp_bytes / (1024 * 1024)

    if seven_zip:
        print(f"[Compress] Found 7-Zip at {seven_zip}")
        print(f"[Compress] Creating ultra-compressed LZMA2 7z archive: {target_7z}")
        if os.path.exists(target_7z):
            try:
                os.remove(target_7z)
            except Exception:
                pass

        cmd = [
            seven_zip, "a",
            "-t7z",
            "-m0=lzma2",
            "-mx=9",       # Maximum / Ultra compression
            "-mfb=64",     # 64 fast bytes
            "-md=64m",     # 64MB dictionary
            "-ms=on",      # Solid block archiving
            target_7z,
            os.path.join(base_dist, "*"),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode == 0 and os.path.isfile(target_7z):
            comp_mb = os.path.getsize(target_7z) / (1024 * 1024)
            ratio = (1.0 - (comp_mb / max(uncomp_mb, 0.001))) * 100.0
            print(f"[Compress] SUCCESS in {time.time() - t0:.1f}s!")
            print(f"[Compress] Uncompressed: {uncomp_mb:.1f} MB -> 7z Archive: {comp_mb:.1f} MB ({ratio:.1f}% space saved)")
            return 0
        else:
            print(f"[Compress] 7-Zip returned code {proc.returncode}, falling back to Python zipfile...")

    # Fallback: Python standard zipfile with Deflate Level 9
    print(f"[Compress] Creating high-compression portable ZIP: {target_zip}")
    if os.path.exists(target_zip):
        try:
            os.remove(target_zip)
        except Exception:
            pass

    with zipfile.ZipFile(target_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _, files in os.walk(base_dist):
            for file in files:
                abs_f = os.path.join(root, file)
                rel_f = os.path.relpath(abs_f, base_dist)
                zf.write(abs_f, arcname=os.path.join("BOOBPlayer", rel_f))

    comp_mb = os.path.getsize(target_zip) / (1024 * 1024)
    ratio = (1.0 - (comp_mb / max(uncomp_mb, 0.001))) * 100.0
    print(f"[Compress] SUCCESS in {time.time() - t0:.1f}s!")
    print(f"[Compress] Uncompressed: {uncomp_mb:.1f} MB -> ZIP Archive: {comp_mb:.1f} MB ({ratio:.1f}% space saved)")
    return 0


def main():
    parser = argparse.ArgumentParser(description="BOOB Player cx_Freeze Portable Packager")
    parser.add_argument("--check", action="store_true", help="Verify cx_Freeze packaging configuration and assets")
    parser.add_argument("--build", action="store_true", help="Build standalone portable executable in dist/BOOBPlayer")
    parser.add_argument("--archive", action="store_true", help="Compress dist/BOOBPlayer into ultra-compact distribution archive (.7z / .zip)")
    parser.add_argument("--smoke-test", action="store_true", help="Run automated startup smoke test on built executable")
    parser.add_argument("--clean", action="store_true", help="Clean previous build and dist directories")
    args = parser.parse_args()

    if args.clean:
        clean_build_artifacts()
        if not (args.build or args.check or args.archive or args.smoke_test):
            return 0

    if args.build:
        sys.exit(run_build(archive_after=args.archive, clean_first=args.clean))
    elif args.archive:
        sys.exit(create_compressed_archive())
    elif args.smoke_test:
        sys.exit(run_smoke_test())
    else:
        sys.exit(verify_packaging_readiness())


if __name__ == "__main__":
    main()
