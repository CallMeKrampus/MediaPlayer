"""
BOOB Player - Main Application Launcher
Hybrid of mpv, VLC, and KMPlayer.
Strict dark mode, live TV/IPTV, streaming, external audio/subs/video,
JP2K/ProRes/H266/AV2/VP9, full DCP folder parsing & synchronized playback,
and advanced Dolby Vision / HDR10 / DCI-XYZ tonemapping.
"""

import sys
import os
import argparse
import multiprocessing
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow
from core.dcp_parser import DCPParser
from core.app_paths import ensure_portable_environment
from core.debug_logger import DebugLogger


def parse_args():
    parser = argparse.ArgumentParser(
        description="BOOB Player - mpv/VLC/KMPlayer Hybrid Dark Mode Media Player"
    )
    parser.add_argument("media", nargs="?", default=None, help="File, stream URL, or DCP folder to play")
    parser.add_argument("--dcp", action="store_true", help="Force treat media path as a DCP Cinema Package folder")
    parser.add_argument("--iptv", type=str, default=None, help="Load custom M3U/M3U8 IPTV playlist")
    parser.add_argument("--sub", type=str, default=None, help="Attach external subtitle file (.srt, .ass, etc.)")
    parser.add_argument("--audio", type=str, default=None, help="Attach external audio track (.wav, .flac, etc.)")
    parser.add_argument("--tonemap", type=str, default=None,
                        choices=["dv_p5_sdr", "hdr10_sdr", "dci_xyz_srgb", "filmic_hable", "spline_sdr", "passthrough"],
                        help="Initial tonemapping preset")
    parser.add_argument("--fullscreen", action="store_true", help="Start directly in fullscreen mode")
    return parser.parse_args()


def main():
    multiprocessing.freeze_support()
    ensure_portable_environment()
    DebugLogger.start_session()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

    args = parse_args()
    DebugLogger.log(
        "APP_STARTUP",
        "BOOB Player process initialized",
        args_media=args.media,
        args_tonemap=args.tonemap,
        args_dcp=args.dcp,
        args_iptv=args.iptv,
        args_sub=args.sub,
        args_audio=args.audio,
        args_fullscreen=args.fullscreen,
        pid=os.getpid()
    )

    # Enable High-DPI scaling with unscaled pass-through rounding
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    
    app = QApplication(sys.argv)
    app.setApplicationName("BOOB Player")
    app.setOrganizationName("BOOBPlayer")

    # Set dark application palette so Windows and native viewports default to black (#000000 / #0d0e12)
    from PyQt6.QtGui import QPalette, QColor
    dark_pal = QPalette()
    dark_pal.setColor(QPalette.ColorRole.Window, QColor("#0d0e12"))
    dark_pal.setColor(QPalette.ColorRole.WindowText, QColor("#f3f4f6"))
    dark_pal.setColor(QPalette.ColorRole.Base, QColor("#000000"))
    dark_pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#101115"))
    dark_pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#181d26"))
    dark_pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#f1f5f9"))
    dark_pal.setColor(QPalette.ColorRole.Text, QColor("#f3f4f6"))
    dark_pal.setColor(QPalette.ColorRole.Button, QColor("#17181f"))
    dark_pal.setColor(QPalette.ColorRole.ButtonText, QColor("#f3f4f6"))
    dark_pal.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    dark_pal.setColor(QPalette.ColorRole.Highlight, QColor("#272833"))
    dark_pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(dark_pal)

    window = MainWindow()

    # Apply tonemap preset if specified
    if args.tonemap:
        window._apply_tonemap_preset(args.tonemap)

    # Load custom IPTV if requested
    if args.iptv and os.path.exists(args.iptv):
        window.iptv_mgr.load_m3u_file(args.iptv)
        window.iptv_drawer._refresh_categories()
        window.iptv_drawer._filter_channels()

    # Load media if provided
    if args.media:
        target = os.path.abspath(args.media) if os.path.exists(args.media) else args.media
        if args.dcp or (os.path.isdir(target) and DCPParser.is_dcp_folder(target)):
            window.play_dcp_folder(target)
        elif os.path.isfile(target) and (os.path.basename(target).lower() in ("assetmap", "assetmap.xml") or target.lower().endswith(".mxf")):
            parent_dir = os.path.dirname(target)
            if DCPParser.is_dcp_folder(parent_dir):
                window.play_dcp_folder(parent_dir)
            else:
                window.play_media(target)
        else:
            window.play_media(target)

        # Attach external audio or subtitle if specified
        if args.audio and os.path.exists(args.audio):
            window.engine.add_external_audio(args.audio, select=True)
        if args.sub and os.path.exists(args.sub):
            window.engine.add_external_subtitle(args.sub, select=True)

    if args.fullscreen:
        window.showFullScreen()
    else:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
