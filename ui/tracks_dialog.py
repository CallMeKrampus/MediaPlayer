"""
BOOB Player - Unified Track & Stream Selection Dialog
Allows instant selection, toggling, and inspection of Video angles, Audio streams,
and Subtitle tracks with real-time MPV engine synchronization.
"""

import os
from typing import Optional, List, Dict, Any
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QHeaderView, QFileDialog, QAbstractItemView, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont


class TrackSelectorDialog(QDialog):
    track_changed = pyqtSignal(str, object)  # track_type ('video', 'audio', 'sub'), track_id (int or 'no')
    load_external_requested = pyqtSignal(str)  # 'video', 'audio', 'sub'

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Track & Stream Selector | BOOB Player")
        self.resize(800, 520)
        self.setMinimumSize(740, 460)

        self._init_ui()
        self._populate_all_tabs()

        # Connect live track updates if bridge is available
        if hasattr(self.engine, "bridge") and hasattr(self.engine.bridge, "track_list_signal"):
            self.engine.bridge.track_list_signal.connect(self._on_engine_tracks_updated)

    def _init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0b0e14;
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #1c2333;
                background-color: #0d111a;
                border-radius: 8px;
                top: -1px;
            }
            QTabBar::tab {
                background: #141924;
                color: #94a3b8;
                border: 1px solid #1c2333;
                border-bottom: none;
                padding: 8px 18px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 12px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background: #0284c7;
                color: #ffffff;
                border-color: #38bdf8;
            }
            QTabBar::tab:hover:!selected {
                background: #1c2333;
                color: #ffffff;
            }
            QTableWidget {
                background-color: #0b0e14;
                border: 1px solid #1c2333;
                border-radius: 6px;
                gridline-color: #161c28;
                color: #e2e8f0;
                selection-background-color: rgba(2, 132, 199, 0.4);
                selection-color: #ffffff;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QHeaderView::section {
                background-color: #131722;
                color: #94a3b8;
                border: none;
                border-bottom: 1px solid #1f2737;
                padding: 6px;
                font-weight: 700;
                font-size: 11px;
            }
            QPushButton {
                background-color: #171d2b;
                border: 1px solid #232c3f;
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 12px;
                font-weight: 600;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #202738;
                border-color: #00d2ff;
                color: #ffffff;
            }
            QPushButton.primaryBtn {
                background-color: #0284c7;
                border: 1px solid #38bdf8;
                color: #ffffff;
            }
            QPushButton.primaryBtn:hover {
                background-color: #0369a1;
            }
            QPushButton.dangerBtn {
                background-color: #1f1418;
                border: 1px solid #7f1d1d;
                color: #f87171;
            }
            QPushButton.dangerBtn:hover {
                background-color: #991b1b;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # Header Bar
        hdr_box = QHBoxLayout()
        lbl_icon = QLabel("🔀")
        lbl_icon.setStyleSheet("font-size: 18px;")
        lbl_title = QLabel("TRACK & STREAM SELECTOR")
        lbl_title.setStyleSheet("color: #00d2ff; font-weight: 800; font-size: 14px; letter-spacing: 0.8px;")
        hdr_box.addWidget(lbl_icon)
        hdr_box.addWidget(lbl_title)
        hdr_box.addStretch(1)

        badge = QLabel("STUDIO DEMUXER")
        badge.setStyleSheet("""
            background: rgba(2, 132, 199, 0.2);
            color: #38bdf8;
            border: 1px solid #0284c7;
            border-radius: 4px;
            padding: 3px 8px;
            font-size: 10px;
            font-weight: 700;
        """)
        hdr_box.addWidget(badge)
        layout.addLayout(hdr_box)

        # Tabs
        self.tabs = QTabWidget()
        
        # 1. Video Tracks Tab
        self.tab_video = QWidget()
        self._setup_video_tab(self.tab_video)
        self.tabs.addTab(self.tab_video, "📹 Video Tracks")

        # 2. Audio Tracks Tab
        self.tab_audio = QWidget()
        self._setup_audio_tab(self.tab_audio)
        self.tabs.addTab(self.tab_audio, "🔊 Audio Streams")

        # 3. Subtitles Tab
        self.tab_sub = QWidget()
        self._setup_sub_tab(self.tab_sub)
        self.tabs.addTab(self.tab_sub, "💬 Subtitles")

        layout.addWidget(self.tabs, 1)

        # Bottom Close Bar
        bottom_bar = QHBoxLayout()
        lbl_hint = QLabel("💡 Tip: Double-click any row to activate it instantly.")
        lbl_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        bottom_bar.addWidget(lbl_hint)
        bottom_bar.addStretch(1)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        layout.addLayout(bottom_bar)

    def _setup_video_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tbl_video = self._create_table([
            "State", "ID", "Angle / Title", "Codec", "Resolution", "FPS", "Source"
        ])
        self.tbl_video.doubleClicked.connect(lambda: self._select_current_row("video", self.tbl_video))
        layout.addWidget(self.tbl_video, 1)

        btn_bar = QHBoxLayout()
        btn_select = QPushButton("✓ Activate Selected Video Angle")
        btn_select.setProperty("class", "primaryBtn")
        btn_select.clicked.connect(lambda: self._select_current_row("video", self.tbl_video))
        btn_bar.addWidget(btn_select)

        btn_disable = QPushButton("Disable Video (Audio Only)")
        btn_disable.setProperty("class", "dangerBtn")
        btn_disable.clicked.connect(lambda: self._disable_track("video"))
        btn_bar.addWidget(btn_disable)

        btn_bar.addStretch(1)

        btn_add = QPushButton("➕ Add External Video Track...")
        btn_add.clicked.connect(lambda: self.load_external_requested.emit("video"))
        btn_bar.addWidget(btn_add)
        layout.addLayout(btn_bar)

    def _setup_audio_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tbl_audio = self._create_table([
            "State", "ID", "Language", "Title / Label", "Codec", "Channels", "Sample Rate", "Source"
        ])
        self.tbl_audio.doubleClicked.connect(lambda: self._select_current_row("audio", self.tbl_audio))
        layout.addWidget(self.tbl_audio, 1)

        btn_bar = QHBoxLayout()
        btn_select = QPushButton("✓ Activate Selected Audio Stream")
        btn_select.setProperty("class", "primaryBtn")
        btn_select.clicked.connect(lambda: self._select_current_row("audio", self.tbl_audio))
        btn_bar.addWidget(btn_select)

        btn_disable = QPushButton("Mute / Disable Audio Track")
        btn_disable.setProperty("class", "dangerBtn")
        btn_disable.clicked.connect(lambda: self._disable_track("audio"))
        btn_bar.addWidget(btn_disable)

        btn_bar.addStretch(1)

        btn_add = QPushButton("➕ Add External Audio File...")
        btn_add.clicked.connect(lambda: self.load_external_requested.emit("audio"))
        btn_bar.addWidget(btn_add)
        layout.addLayout(btn_bar)

    def _setup_sub_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tbl_sub = self._create_table([
            "State", "ID", "Language", "Title / Note", "Format", "Source"
        ])
        self.tbl_sub.doubleClicked.connect(lambda: self._select_current_row("sub", self.tbl_sub))
        layout.addWidget(self.tbl_sub, 1)

        btn_bar = QHBoxLayout()
        btn_select = QPushButton("✓ Activate Selected Subtitle")
        btn_select.setProperty("class", "primaryBtn")
        btn_select.clicked.connect(lambda: self._select_current_row("sub", self.tbl_sub))
        btn_bar.addWidget(btn_select)

        btn_disable = QPushButton("Disable Subtitles (Off)")
        btn_disable.setProperty("class", "dangerBtn")
        btn_disable.clicked.connect(lambda: self._disable_track("sub"))
        btn_bar.addWidget(btn_disable)

        btn_bar.addStretch(1)

        btn_add = QPushButton("➕ Add External Subtitle File...")
        btn_add.clicked.connect(lambda: self.load_external_requested.emit("sub"))
        btn_bar.addWidget(btn_add)
        layout.addLayout(btn_bar)

    @staticmethod
    def _create_table(headers: List[str]) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        return t

    def _populate_all_tabs(self):
        tracks = self.engine.get_track_list()
        self._populate_video_table(tracks)
        self._populate_audio_table(tracks)
        self._populate_sub_table(tracks)

    def _on_engine_tracks_updated(self, tracks):
        self._populate_all_tabs()

    def _populate_video_table(self, all_tracks: List[dict]):
        self.tbl_video.setRowCount(0)
        v_tracks = [t for t in all_tracks if t.get("type") == "video"]
        
        for r, t in enumerate(v_tracks):
            self.tbl_video.insertRow(r)
            is_sel = bool(t.get("selected"))
            tid = t.get("id", r + 1)
            
            # State
            state_str = "● ACTIVE" if is_sel else "○ Inactive"
            item_state = QTableWidgetItem(state_str)
            item_state.setData(Qt.ItemDataRole.UserRole, tid)
            if is_sel:
                item_state.setForeground(QColor("#00d2ff"))
                font = item_state.font()
                font.setBold(True)
                item_state.setFont(font)
            else:
                item_state.setForeground(QColor("#64748b"))
            self.tbl_video.setItem(r, 0, item_state)

            # ID
            self.tbl_video.setItem(r, 1, QTableWidgetItem(str(tid)))

            # Title
            title = t.get("title") or f"Video Angle #{tid}"
            self.tbl_video.setItem(r, 2, QTableWidgetItem(title))

            # Codec
            codec = (t.get("codec") or t.get("decoder") or "Unknown").upper()
            self.tbl_video.setItem(r, 3, QTableWidgetItem(codec))

            # Resolution
            w = t.get("demux-w") or t.get("width") or 0
            h = t.get("demux-h") or t.get("height") or 0
            res_str = f"{w}x{h}" if (w and h) else "N/A"
            if w == 4096:
                res_str += " (4K DCI)"
            elif w == 3840:
                res_str += " (4K UHD)"
            elif w == 2048:
                res_str += " (2K DCI)"
            elif w == 1920:
                res_str += " (1080p FHD)"
            self.tbl_video.setItem(r, 4, QTableWidgetItem(res_str))

            # FPS
            fps = t.get("demux-fps") or 0.0
            fps_str = f"{fps:.2f} fps" if fps > 0 else "24.00 fps (CPL)"
            self.tbl_video.setItem(r, 5, QTableWidgetItem(fps_str))

            # Source
            ext = "External File" if t.get("external") else "Internal / Container"
            self.tbl_video.setItem(r, 6, QTableWidgetItem(ext))

            if is_sel:
                self.tbl_video.selectRow(r)

    def _populate_audio_table(self, all_tracks: List[dict]):
        self.tbl_audio.setRowCount(0)
        a_tracks = [t for t in all_tracks if t.get("type") == "audio"]

        for r, t in enumerate(a_tracks):
            self.tbl_audio.insertRow(r)
            is_sel = bool(t.get("selected"))
            tid = t.get("id", r + 1)

            state_str = "● ACTIVE" if is_sel else "○ Inactive"
            item_state = QTableWidgetItem(state_str)
            item_state.setData(Qt.ItemDataRole.UserRole, tid)
            if is_sel:
                item_state.setForeground(QColor("#00d2ff"))
                font = item_state.font()
                font.setBold(True)
                item_state.setFont(font)
            else:
                item_state.setForeground(QColor("#64748b"))
            self.tbl_audio.setItem(r, 0, item_state)

            self.tbl_audio.setItem(r, 1, QTableWidgetItem(str(tid)))

            # Language
            lang = (t.get("lang") or "und").upper()
            self.tbl_audio.setItem(r, 2, QTableWidgetItem(lang))

            # Title
            title = t.get("title") or t.get("external-filename") or f"Audio Track #{tid}"
            title = os.path.basename(str(title))
            self.tbl_audio.setItem(r, 3, QTableWidgetItem(title))

            # Codec
            codec = (t.get("codec") or t.get("decoder") or "PCM").upper()
            self.tbl_audio.setItem(r, 4, QTableWidgetItem(codec))

            # Channels
            ch = t.get("demux-channel-count") or t.get("audio-channels") or 2
            if ch == 14:
                ch_str = "14 Ch (Dolby Atmos / IAB)"
            elif ch == 8:
                ch_str = "7.1 Surround (8 Ch)"
            elif ch == 6:
                ch_str = "5.1 Surround (6 Ch)"
            elif ch == 2:
                ch_str = "Stereo (2 Ch)"
            else:
                ch_str = f"{ch} Channels"
            self.tbl_audio.setItem(r, 5, QTableWidgetItem(ch_str))

            # Sample Rate
            sr = t.get("demux-samplerate") or 48000
            self.tbl_audio.setItem(r, 6, QTableWidgetItem(f"{sr // 1000} kHz"))

            # Source
            ext = "External File" if t.get("external") else "Internal"
            self.tbl_audio.setItem(r, 7, QTableWidgetItem(ext))

            if is_sel:
                self.tbl_audio.selectRow(r)

    def _populate_sub_table(self, all_tracks: List[dict]):
        self.tbl_sub.setRowCount(0)
        s_tracks = [t for t in all_tracks if t.get("type") == "sub"]

        # First row: Disabled / Off option
        self.tbl_sub.insertRow(0)
        any_sub_active = any(t.get("selected") for t in s_tracks)
        is_off_selected = not any_sub_active

        item_off = QTableWidgetItem("● ACTIVE (OFF)" if is_off_selected else "○ Inactive")
        item_off.setData(Qt.ItemDataRole.UserRole, "no")
        if is_off_selected:
            item_off.setForeground(QColor("#10b981"))
            font = item_off.font()
            font.setBold(True)
            item_off.setFont(font)
        else:
            item_off.setForeground(QColor("#64748b"))
        self.tbl_sub.setItem(0, 0, item_off)
        self.tbl_sub.setItem(0, 1, QTableWidgetItem("-"))
        self.tbl_sub.setItem(0, 2, QTableWidgetItem("None"))
        self.tbl_sub.setItem(0, 3, QTableWidgetItem("Subtitles Disabled (Off)"))
        self.tbl_sub.setItem(0, 4, QTableWidgetItem("None"))
        self.tbl_sub.setItem(0, 5, QTableWidgetItem("-"))

        if is_off_selected:
            self.tbl_sub.selectRow(0)

        for i, t in enumerate(s_tracks):
            r = i + 1
            self.tbl_sub.insertRow(r)
            is_sel = bool(t.get("selected"))
            tid = t.get("id", i + 1)

            state_str = "● ACTIVE" if is_sel else "○ Inactive"
            item_state = QTableWidgetItem(state_str)
            item_state.setData(Qt.ItemDataRole.UserRole, tid)
            if is_sel:
                item_state.setForeground(QColor("#00d2ff"))
                font = item_state.font()
                font.setBold(True)
                item_state.setFont(font)
            else:
                item_state.setForeground(QColor("#64748b"))
            self.tbl_sub.setItem(r, 0, item_state)

            self.tbl_sub.setItem(r, 1, QTableWidgetItem(str(tid)))

            lang = (t.get("lang") or "und").upper()
            self.tbl_sub.setItem(r, 2, QTableWidgetItem(lang))

            title = t.get("title") or t.get("external-filename") or f"Subtitle Track #{tid}"
            title = os.path.basename(str(title))
            self.tbl_sub.setItem(r, 3, QTableWidgetItem(title))

            codec = (t.get("codec") or t.get("format") or "SRT / XML").upper()
            self.tbl_sub.setItem(r, 4, QTableWidgetItem(codec))

            ext = "External File" if t.get("external") else "Internal"
            self.tbl_sub.setItem(r, 5, QTableWidgetItem(ext))

            if is_sel:
                self.tbl_sub.selectRow(r)

    def _select_current_row(self, track_type: str, table: QTableWidget):
        row = table.currentRow()
        if row < 0:
            return
        item = table.item(row, 0)
        if not item:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        self.engine.set_track(track_type, tid)
        self.track_changed.emit(track_type, tid)
        self._populate_all_tabs()

    def _disable_track(self, track_type: str):
        self.engine.set_track(track_type, "no")
        self.track_changed.emit(track_type, "no")
        self._populate_all_tabs()
