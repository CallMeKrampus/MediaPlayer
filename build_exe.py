"""
BOOB Player - Non-PyInstaller Portable Packaging & Pre-Flight Build Verification Tool (cx_Freeze)
Usage:
    python build_exe.py --check   # Verify cx_Freeze config, tools, DLLs, and zero DCP/media bundling
    python build_exe.py --build   # Build standalone portable executable into dist/BOOBPlayer
"""

import argparse
import os
import shutil
import subprocess
import sys
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FORBIDDEN_DIR_NAMES = ("lostwolves", "ramayana", "sample_dcp", "assets")
FORBIDDEN_EXTS = (".mxf", ".mov", ".webm", ".mp4", ".mkv", ".wav")
REQUIRED_DESTS = (
    "shaders",
    "lib/libmpv-2.dll",
    "lib/nvjpeg2k_0.dll",
    "lib/ffmpeg.exe",
    "lib/ffprobe.exe",
    "lib/cacert.pem",
    "lib/vcruntime140.dll",
    "lib/msvcp140.dll",
    "lib/d3dcompiler_47.dll",
    "lib/opengl32sw.dll",
)


def verify_packaging_readiness() -> int:
    """Validate that cx_Freeze (not PyInstaller) bundles all runtime tools and excludes DCPs/media."""
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

    script_path = os.path.join(BASE_DIR, "boob_player.py")
    if not os.path.isfile(script_path):
        errors.append(f"Missing entry script: {script_path}")

    print(f"[Packaging] Engine: cx_Freeze {cx_Freeze.__version__} (PyInstaller excluded)")
    print(f"[Packaging] Target Executable: {pkg_setup.executables[0].target_name}")
    print(f"[Packaging] Output Directory: {pkg_setup.build_exe_options['build_exe']}")
    for src, dst in include_files:
        print(f"[Packaging] Asset: {dst} <- {src}")

    if errors:
        for err in errors:
            print(f"[Packaging] ERROR: {err}", file=sys.stderr)
        return 1

    print("[Packaging] Verified zero DCPs/media files bundled; all portable tools & DLLs ready.")
    return 0


def run_build(archive_after: bool = False) -> int:
    """Invoke setup.py build_exe to generate the standalone portable executable bundle."""
    rc = verify_packaging_readiness()
    if rc != 0:
        return rc

    cmd = [sys.executable, os.path.join(BASE_DIR, "setup.py"), "build_exe"]
    print(f"[Packaging] Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=BASE_DIR)
    if proc.returncode != 0:
        return proc.returncode

    if archive_after:
        return create_compressed_archive()
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
    import time

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
    args = parser.parse_args()

    if args.build:
        sys.exit(run_build(archive_after=args.archive))
    elif args.archive:
        sys.exit(create_compressed_archive())
    else:
        sys.exit(verify_packaging_readiness())


if __name__ == "__main__":
    main()
