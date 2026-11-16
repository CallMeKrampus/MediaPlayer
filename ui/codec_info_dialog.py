"""
BOOB Player - VLC-Style Media & Codec Information Inspector
Provides deep analysis of container, video/audio/subtitle bitstreams, bit depths, and color science.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QGridLayout, QTextEdit, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt
from typing import Dict, Any


class CodecInfoDialog(QDialog):
    def __init__(self, media_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.data = media_data
        self.setWindowTitle("ℹ️ Media Information & Codec Details")
        self.setMinimumSize(740, 520)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        tabs = QTabWidget()

        # 1. General Tab
        tabs.addTab(self._build_general_tab(), "General")

        # 2. Video Codec Tab
        tabs.addTab(self._build_video_tab(), "Video Codec")

        # 3. Audio Codec Tab
        tabs.addTab(self._build_audio_tab(), "Audio Codec")

        # 4. Subtitles Tab
        tabs.addTab(self._build_subtitles_tab(), "Subtitles")

        layout.addWidget(tabs, 1)

        # Bottom Close Button
        btn_bar = QHBoxLayout()
        btn_bar.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(btn_close)
        layout.addLayout(btn_bar)

    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(8)

        fields = [
            ("File Name:", self.data.get("filename", "N/A")),
            ("Container / Format:", self.data.get("format_name", "N/A")),
            ("Duration:", f"{self.data.get('duration', 0):.2f} seconds"),
            ("File Size:", f"{self.data.get('size_mb', 0)} MB"),
            ("Total Bitrate:", f"{self.data.get('bitrate_kbps', 0)} kbps"),
        ]

        for row, (label, val) in enumerate(fields):
            lbl_key = QLabel(label)
            lbl_key.setStyleSheet("color: #94a3b8; font-weight: 600;")
            lbl_val = QLabel(str(val))
            lbl_val.setStyleSheet("color: #f1f5f9;")
            lbl_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(lbl_key, row, 0)
            grid.addWidget(lbl_val, row, 1)

        layout.addLayout(grid)

        # Metadata Tags box
        tags = self.data.get("tags", {})
        if tags:
            lbl_tags = QLabel("Metadata Tags:")
            lbl_tags.setStyleSheet("color: #00d2ff; font-weight: bold; margin-top: 10px;")
            layout.addWidget(lbl_tags)

            txt = QTextEdit()
            txt.setReadOnly(True)
            txt.setStyleSheet("background: #0f1218; border: 1px solid #1e2433; color: #94a3b8;")
            formatted_tags = "\n".join([f"{k}: {v}" for k, v in tags.items()])
            txt.setPlainText(formatted_tags)
            layout.addWidget(txt, 1)

        layout.addStretch(1)
        return widget

    def _build_video_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        videos = self.data.get("video_tracks", [])
        if not videos:
            layout.addWidget(QLabel("No video streams detected."))
            layout.addStretch(1)
            return widget

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        for i, v in enumerate(videos):
            frame = QFrame()
            frame.setStyleSheet("background: #12151c; border: 1px solid #202533; border-radius: 6px; padding: 10px;")
            f_layout = QGridLayout(frame)
            f_layout.setSpacing(6)

            title_lbl = QLabel(f"Video Stream #{v.get('index', i)}: {v.get('codec', 'Unknown')}")
            title_lbl.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 13px;")
            f_layout.addWidget(title_lbl, 0, 0, 1, 2)

            hdr_fmt = v.get("hdr_format", "SDR")
            if hdr_fmt == "DCI-XYZ":
                hdr_display = "No (Cinema DCI-XYZ / SMPTE 428-1 Gamma 2.6 Theatrical SDR)"
            elif hdr_fmt == "HDR10+":
                hdr_display = "Yes (HDR10+ / SMPTE 2094-40 PQ)"
            elif hdr_fmt == "HDR10":
                hdr_display = "Yes (HDR10 / Rec.2020 ST 2084 PQ)"
            elif hdr_fmt == "HLG":
                hdr_display = "Yes (HLG / Rec.2020 ARIB STD-B67)"
            elif str(hdr_fmt).startswith("Dolby Vision"):
                hdr_display = f"Yes ({hdr_fmt})"
            elif v.get("hdr"):
                hdr_display = f"Yes ({hdr_fmt})"
            else:
                hdr_display = "No (SDR)"

            prim_val = v.get("color_primaries", "Rec.709")
            if prim_val == "dci-p3":
                prim_val = "DCI-P3 (Cinema Gamut)"
            trc_val = v.get("color_transfer", "Rec.709 / sRGB")
            if trc_val == "smpte428":
                trc_val = "SMPTE 428-1 (DCI Gamma 2.6 Theatrical SDR)"
            matrix_val = v.get("color_space", "Rec.709")
            if matrix_val == "xyz":
                matrix_val = "DCI-XYZ (SMPTE 428-1 CIE 1931)"

            v_fields = [
                ("Codec / Driver:", v.get("codec_name", "N/A")),
                ("Profile:", v.get("profile", "N/A")),
                ("Resolution:", f"{v.get('width', 0)} x {v.get('height', 0)}"),
                ("Display Aspect Ratio:", v.get("aspect_ratio", "N/A")),
                ("Pixel Format:", v.get("pix_fmt", "N/A")),
                ("Color Primaries:", prim_val),
                ("Color Transfer:", trc_val),
                ("Color Space / Matrix:", matrix_val),
                ("Frame Rate:", f"{v.get('fps', 24.0):.3f} fps"),
                ("HDR Stream:", hdr_display),
            ]

            try:
                from core.nvjpeg2k_engine import NVJPEG2KEngine
                from core.grok_engine import GrokOpenCLEngine
                if "jpeg2000" in str(v.get("codec_name", "")).lower() or "jp2k" in str(v.get("codec_name", "")).lower():
                    if NVJPEG2KEngine.is_available():
                        engine = NVJPEG2KEngine.get_instance()
                        v_fields.append(("Hardware Acceleration:", f"⚡ NVIDIA nvJPEG2000 ({engine.gpu_name})"))
                    elif GrokOpenCLEngine.is_available():
                        grok_eng = GrokOpenCLEngine.get_instance()
                        v_fields.append(("Hardware Acceleration:", f"⚡ Grok OpenCL GPU Compute ({grok_eng.gpu_name})"))
            except Exception:
                pass

            for row, (k, val) in enumerate(v_fields, start=1):
                lk = QLabel(k)
                lk.setMinimumWidth(160)
                lk.setStyleSheet("color: #a1a1aa; font-size: 11px;")
                lv = QLabel(str(val))
                lv.setStyleSheet("color: #f4f4f5; font-weight: 500; font-size: 11px;")
                lv.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                f_layout.addWidget(lk, row, 0)
                f_layout.addWidget(lv, row, 1)

            scroll_layout.addWidget(frame)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        return widget

    def _build_audio_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        iab_meta = self.data.get("iab_meta")
        if iab_meta:
            frame_iab = QFrame()
            frame_iab.setStyleSheet("background: #0f172a; border: 1px solid #0284c7; border-radius: 6px; padding: 10px;")
            iab_layout = QGridLayout(frame_iab)
            iab_layout.setSpacing(6)

            lbl_iab_title = QLabel("🎧 Immersive Audio Bitstream (SMPTE ST 2098-2 / Dolby Atmos)")
            lbl_iab_title.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 13px;")
            iab_layout.addWidget(lbl_iab_title, 0, 0, 1, 2)

            iab_fields = [
                ("Atmos Master Allocation:", f"{iab_meta.max_rendered_channels} Total Tracks ({iab_meta.bed_channel_count} Bed + {iab_meta.max_audio_objects} Dynamic Objects)"),
                ("Dolby Atmos Objects Pool:", f"{iab_meta.max_audio_objects} Dynamic Sound Objects"),
                ("Sound Bed Layout:", f"7.1.2 Cinema Bed ({iab_meta.bed_channel_count} Channels)"),
                ("Essence Container:", "SMPTE ST 429-18 AuxData MXF"),
                ("Bitstream Standard:", "SMPTE ST 2098-2 Immersive Audio Bitstream"),
                ("Bitstream Total Frames:", f"{iab_meta.total_frames} frames ({iab_meta.duration_seconds:.2f}s)"),
                ("Average Bitrate:", f"{iab_meta.avg_bitrate_kbps} kbps"),
            ]
            for row, (k, val) in enumerate(iab_fields, start=1):
                lk = QLabel(k)
                lk.setStyleSheet("color: #94a3b8;")
                lv = QLabel(str(val))
                lv.setStyleSheet("color: #f1f5f9; font-weight: bold;")
                iab_layout.addWidget(lk, row, 0)
                iab_layout.addWidget(lv, row, 1)

            layout.addWidget(frame_iab)

        audios = self.data.get("audio_tracks", [])
        if not audios and not iab_meta:
            layout.addWidget(QLabel("No audio streams detected."))
            layout.addStretch(1)
            return widget

        for i, a in enumerate(audios):
            frame = QFrame()
            frame.setStyleSheet("background: #12151c; border: 1px solid #202533; border-radius: 6px; padding: 10px;")
            f_layout = QGridLayout(frame)
            f_layout.setSpacing(6)

            title_lbl = QLabel(f"Audio Stream #{a.get('index', i)}: {a.get('codec', 'Unknown')}")
            title_lbl.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 13px;")
            f_layout.addWidget(title_lbl, 0, 0, 1, 2)

            a_fields = [
                ("Codec:", a.get("codec_name", "N/A")),
                ("Channels:", f"{a.get('channels', 2)} ({a.get('channel_layout', 'stereo')})"),
                ("Sample Rate:", f"{a.get('sample_rate', 48000)} Hz"),
                ("Bitrate:", f"{a.get('bitrate_kbps', 0)} kbps"),
                ("Language:", a.get("language", "und")),
                ("Title:", a.get("title", f"Track {i+1}")),
            ]

            for row, (k, val) in enumerate(a_fields, start=1):
                lk = QLabel(k)
                lk.setStyleSheet("color: #94a3b8;")
                lv = QLabel(str(val))
                lv.setStyleSheet("color: #f1f5f9; font-weight: 500;")
                f_layout.addWidget(lk, row, 0)
                f_layout.addWidget(lv, row, 1)

            layout.addWidget(frame)

        layout.addStretch(1)
        return widget

    def _build_subtitles_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        subs = self.data.get("subtitle_tracks", [])
        if not subs:
            layout.addWidget(QLabel("No subtitle streams detected."))
            layout.addStretch(1)
            return widget

        for i, s in enumerate(subs):
            frame = QFrame()
            frame.setStyleSheet("background: #12151c; border: 1px solid #202533; border-radius: 6px; padding: 10px;")
            f_layout = QGridLayout(frame)
            f_layout.setSpacing(6)

            title_lbl = QLabel(f"Subtitle Stream #{s.get('index', i)}: {s.get('title', 'Subtitle')}")
            title_lbl.setStyleSheet("color: #a855f7; font-weight: bold; font-size: 13px;")
            f_layout.addWidget(title_lbl, 0, 0, 1, 2)

            s_fields = [
                ("Format / Codec:", s.get("codec", "N/A")),
                ("Language:", s.get("language", "und")),
            ]

            for row, (k, val) in enumerate(s_fields, start=1):
                lk = QLabel(k)
                lk.setStyleSheet("color: #94a3b8;")
                lv = QLabel(str(val))
                lv.setStyleSheet("color: #f1f5f9; font-weight: 500;")
                f_layout.addWidget(lk, row, 0)
                f_layout.addWidget(lv, row, 1)

            layout.addWidget(frame)

        layout.addStretch(1)
        return widget
