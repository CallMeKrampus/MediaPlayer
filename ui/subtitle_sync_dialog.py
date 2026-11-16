"""
BOOB Player - Subtitle Manager & Synchronization Dialog
Supports loading external subtitles (SRT, ASS, SSA, VTT, SUB, IDX),
delay synchronization down to milliseconds, and typography styling.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QGroupBox, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Dict


class SubtitleSyncDialog(QDialog):
    load_external_sub = pyqtSignal(str)
    subtitle_track_changed = pyqtSignal(int)
    subtitle_delay_changed = pyqtSignal(float)
    subtitle_font_size_changed = pyqtSignal(int)

    def __init__(self, tracks: List[Dict], current_delay_sec: float = 0.0, parent=None):
        super().__init__(parent)
        self.tracks = tracks
        self.current_delay_ms = int(current_delay_sec * 1000)

        self.setWindowTitle("💬 Subtitle Tracks & Synchronization")
        self.setMinimumSize(640, 420)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Track Selection & Load External
        track_group = QGroupBox("Active Subtitle Track")
        t_layout = QHBoxLayout(track_group)
        t_layout.setSpacing(8)

        self.track_combo = QComboBox()
        self._populate_tracks()
        self.track_combo.currentIndexChanged.connect(self._on_track_selected)
        t_layout.addWidget(self.track_combo, 1)

        self.btn_load_ext = QPushButton("➕ Load External Sub...")
        self.btn_load_ext.setObjectName("accentButton")
        self.btn_load_ext.clicked.connect(self._browse_external_sub)
        t_layout.addWidget(self.btn_load_ext)

        layout.addWidget(track_group)

        # 2. Subtitle Delay Offset
        sync_group = QGroupBox("Subtitle Synchronization Delay Offset")
        s_layout = QVBoxLayout(sync_group)
        s_layout.setSpacing(8)

        sync_row = QHBoxLayout()
        self.lbl_delay_val = QLabel(f"{self.current_delay_ms} ms")
        self.lbl_delay_val.setStyleSheet("color: #e4e4e7; font-weight: bold; font-size: 13px; font-family: monospace;")
        sync_row.addWidget(QLabel("Offset:"))
        sync_row.addWidget(self.lbl_delay_val)
        sync_row.addStretch(1)

        btn_m500 = QPushButton("-500ms")
        btn_m500.clicked.connect(lambda: self._adjust_delay(-500))
        btn_m100 = QPushButton("-100ms")
        btn_m100.clicked.connect(lambda: self._adjust_delay(-100))
        btn_reset = QPushButton("0 ms")
        btn_reset.clicked.connect(lambda: self._set_delay(0))
        btn_p100 = QPushButton("+100ms")
        btn_p100.clicked.connect(lambda: self._adjust_delay(100))
        btn_p500 = QPushButton("+500ms")
        btn_p500.clicked.connect(lambda: self._adjust_delay(500))

        for b in [btn_m500, btn_m100, btn_reset, btn_p100, btn_p500]:
            b.setMinimumWidth(58)
            b.setStyleSheet("padding: 4px 8px; font-size: 11px;")
            sync_row.addWidget(b)
        s_layout.addLayout(sync_row)

        self.delay_slider = QSlider(Qt.Orientation.Horizontal)
        self.delay_slider.setRange(-10000, 10000)
        self.delay_slider.setValue(self.current_delay_ms)
        self.delay_slider.valueChanged.connect(self._on_slider_delay_changed)
        s_layout.addWidget(self.delay_slider)

        layout.addWidget(sync_group)

        # 3. Typography & Size
        style_group = QGroupBox("Subtitle Typography & Appearance")
        st_layout = QHBoxLayout(style_group)
        st_layout.addWidget(QLabel("Font Size:"))

        self.slider_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_size.setRange(16, 72)
        self.slider_size.setValue(36)
        self.lbl_size = QLabel("36 pt")
        self.slider_size.valueChanged.connect(self._on_size_changed)

        st_layout.addWidget(self.slider_size, 1)
        st_layout.addWidget(self.lbl_size)
        layout.addWidget(style_group)

        # Close Bar
        btn_bar = QHBoxLayout()
        btn_bar.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(btn_close)
        layout.addLayout(btn_bar)

    def _populate_tracks(self):
        self.track_combo.clear()
        self.track_combo.addItem("Subtitles Off", 0)

        sub_tracks = [t for t in self.tracks if t.get("type") == "sub"]
        for t in sub_tracks:
            t_id = t.get("id", 1)
            title = t.get("title") or t.get("lang") or f"Subtitle Track {t_id}"
            ext = " [External]" if t.get("external") else ""
            codec = f" ({t.get('codec', '')})" if t.get("codec") else ""
            label = f"#{t_id}: {title}{codec}{ext}"
            self.track_combo.addItem(label, t_id)
            if t.get("selected"):
                self.track_combo.setCurrentIndex(self.track_combo.count() - 1)

    def _on_track_selected(self, index: int):
        track_id = self.track_combo.currentData()
        if track_id is not None:
            self.subtitle_track_changed.emit(track_id)

    def _browse_external_sub(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select External Subtitle File", "",
            "Subtitles (*.srt *.ass *.ssa *.vtt *.sub *.idx *.sup);;All Files (*.*)"
        )
        if path:
            self.load_external_sub.emit(path)
            QMessageBox.information(self, "Success", f"Loaded external subtitle:\n{path}")
            self.accept()

    def _adjust_delay(self, delta_ms: int):
        self._set_delay(self.current_delay_ms + delta_ms)

    def _set_delay(self, ms: int):
        self.current_delay_ms = max(-10000, min(10000, ms))
        self.delay_slider.setValue(self.current_delay_ms)
        self.lbl_delay_val.setText(f"{self.current_delay_ms} ms")
        self.subtitle_delay_changed.emit(self.current_delay_ms / 1000.0)

    def _on_slider_delay_changed(self, val: int):
        self.current_delay_ms = val
        self.lbl_delay_val.setText(f"{self.current_delay_ms} ms")
        self.subtitle_delay_changed.emit(self.current_delay_ms / 1000.0)

    def _on_size_changed(self, val: int):
        self.lbl_size.setText(f"{val} pt")
        self.subtitle_font_size_changed.emit(val)
