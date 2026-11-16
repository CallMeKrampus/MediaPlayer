"""
BOOB Player - UI Package
"""
from ui.main_window import MainWindow
from ui.video_widget import VideoWidget
from ui.osc_controls import OSCControls
from ui.iptv_drawer import IPTVDrawer
from ui.playlist_drawer import PlaylistDrawer
from ui.tonemap_dialog import TonemapControlDrawer
from ui.dcp_dialog import DCPInspectorDialog
from ui.codec_info_dialog import CodecInfoDialog
from ui.audio_sync_dialog import AudioSyncDialog
from ui.subtitle_sync_dialog import SubtitleSyncDialog

__all__ = [
    "MainWindow",
    "VideoWidget",
    "OSCControls",
    "IPTVDrawer",
    "PlaylistDrawer",
    "TonemapControlDrawer",
    "DCPInspectorDialog",
    "CodecInfoDialog",
    "AudioSyncDialog",
    "SubtitleSyncDialog",
]
