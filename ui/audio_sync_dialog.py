"""
BOOB Player - External Audio Loader & Real-time Audio Sync
Supports loading external audio tracks (WAV, FLAC, MP3, AC3, DTS, etc.),
delay synchronization down to milliseconds, and 10-band equalizer.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QGroupBox, QGridLayout, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Dict


class AudioSyncDialog(QDialog):
    load_external_audio = pyqtSignal(str)
    audio_track_changed = pyqtSignal(int)
    audio_delay_changed = pyqtSignal(float)
    equalizer_changed = pyqtSignal(list)
    iab_mode_changed = pyqtSignal(str)

    EQ_FREQS = ["31Hz", "62Hz", "125Hz", "250Hz", "500Hz", "1kHz", "2kHz", "4kHz", "8kHz", "16kHz"]

    EQ_PRESETS = {
        "Flat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "Cinema / Movie": [4, 3, 1, 0, -1, 1, 3, 4, 3, 2],
        "Rock": [5, 4, 2, -1, -2, 1, 3, 4, 5, 5],
        "Pop": [-1, 1, 3, 4, 3, 0, -1, 1, 3, 3],
        "Bass Boost": [8, 6, 4, 2, 0, 0, 0, 0, 0, 0],
        "Vocal Clarity": [-2, -2, 0, 2, 4, 4, 3, 1, 0, -1],
    }

    IAB_MODES = [
        ("binaural", "🎧 Binaural 3D Headphone Spatializer (SMPTE ST 2098-2)"),
        ("cinema_71", "🔊 Cinema 7.1 Immersive Downmix (Height Elevation)"),
        ("cinema_51", "🔊 Cinema 5.1 Surround Downmix"),
        ("stereo_dialog", "🗣️ Stereo Dialog Focus (+85% Center Boost + DRC)"),
        ("pcm_direct", "🎵 Direct Multi-Channel Bed (14-Ch Unprocessed)"),
    ]

    def __init__(self, tracks: List[Dict], current_delay_sec: float = 0.0, current_iab_mode: str = "binaural", parent=None):
        super().__init__(parent)
        self.tracks = tracks
        self.current_delay_ms = int(current_delay_sec * 1000)
        self.current_iab_mode = current_iab_mode
        self.eq_sliders: List[QSlider] = []

        self.setWindowTitle("🔊 Audio Tracks, Immersive IAB & Sync")
        self.setMinimumSize(680, 580)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Track Selection & External Audio Loading
        track_group = QGroupBox("Active Audio Track")
        t_layout = QHBoxLayout(track_group)
        t_layout.setSpacing(8)

        self.track_combo = QComboBox()
        self._populate_tracks()
        self.track_combo.currentIndexChanged.connect(self._on_track_selected)
        t_layout.addWidget(self.track_combo, 1)

        self.btn_load_ext = QPushButton("➕ Load External Audio...")
        self.btn_load_ext.setObjectName("accentButton")
        self.btn_load_ext.clicked.connect(self._browse_external_audio)
        t_layout.addWidget(self.btn_load_ext)

        layout.addWidget(track_group)

        # 2. Immersive Audio / IAB Spatial Rendering Mode
        iab_group = QGroupBox("🎧 Immersive Audio / IAB Spatial Processing (SMPTE ST 2098-2)")
        iab_layout = QHBoxLayout(iab_group)
        iab_layout.setSpacing(8)

        self.combo_iab_mode = QComboBox()
        for mode_key, mode_title in self.IAB_MODES:
            self.combo_iab_mode.addItem(mode_title, mode_key)
            if mode_key == self.current_iab_mode:
                self.combo_iab_mode.setCurrentIndex(self.combo_iab_mode.count() - 1)
        self.combo_iab_mode.currentIndexChanged.connect(self._on_iab_mode_changed)
        iab_layout.addWidget(self.combo_iab_mode, 1)

        layout.addWidget(iab_group)

        # 3. Audio Synchronization (Delay offset)
        sync_group = QGroupBox("Audio Synchronization Offset (Millisecond Precision)")
        s_layout = QVBoxLayout(sync_group)
        s_layout.setSpacing(8)

        sync_row = QHBoxLayout()
        self.lbl_delay_val = QLabel(f"{self.current_delay_ms} ms")
        self.lbl_delay_val.setStyleSheet("color: #e4e4e7; font-weight: bold; font-size: 13px; font-family: monospace;")
        sync_row.addWidget(QLabel("Offset:"))
        sync_row.addWidget(self.lbl_delay_val)
        sync_row.addStretch(1)

        btn_m100 = QPushButton("-100ms")
        btn_m100.clicked.connect(lambda: self._adjust_delay(-100))
        btn_m50 = QPushButton("-50ms")
        btn_m50.clicked.connect(lambda: self._adjust_delay(-50))
        btn_reset = QPushButton("0 ms")
        btn_reset.clicked.connect(lambda: self._set_delay(0))
        btn_p50 = QPushButton("+50ms")
        btn_p50.clicked.connect(lambda: self._adjust_delay(50))
        btn_p100 = QPushButton("+100ms")
        btn_p100.clicked.connect(lambda: self._adjust_delay(100))

        for b in [btn_m100, btn_m50, btn_reset, btn_p50, btn_p100]:
            b.setMinimumWidth(58)
            b.setStyleSheet("padding: 4px 8px; font-size: 11px;")
            sync_row.addWidget(b)
        s_layout.addLayout(sync_row)

        self.delay_slider = QSlider(Qt.Orientation.Horizontal)
        self.delay_slider.setRange(-5000, 5000)
        self.delay_slider.setValue(self.current_delay_ms)
        self.delay_slider.valueChanged.connect(self._on_slider_delay_changed)
        s_layout.addWidget(self.delay_slider)

        layout.addWidget(sync_group)

        # 3. 10-Band Graphic Equalizer
        eq_group = QGroupBox("10-Band Graphic Equalizer")
        eq_layout = QVBoxLayout(eq_group)
        eq_layout.setSpacing(8)

        # Preset row
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("EQ Preset:"))
        self.combo_eq_preset = QComboBox()
        for p in self.EQ_PRESETS.keys():
            self.combo_eq_preset.addItem(p)
        self.combo_eq_preset.currentTextChanged.connect(self._apply_eq_preset)
        preset_row.addWidget(self.combo_eq_preset, 1)
        preset_row.addStretch(1)
        eq_layout.addLayout(preset_row)

        # Sliders grid
        eq_grid = QHBoxLayout()
        eq_grid.setSpacing(10)
        self.eq_sliders.clear()

        for f_name in self.EQ_FREQS:
            col = QVBoxLayout()
            col.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            s = QSlider(Qt.Orientation.Vertical)
            s.setRange(-12, 12)
            s.setValue(0)
            s.setFixedHeight(120)
            s.valueChanged.connect(self._emit_eq_change)
            self.eq_sliders.append(s)
            
            lbl_f = QLabel(f_name)
            lbl_f.setStyleSheet("color: #64748b; font-size: 10px;")
            col.addWidget(s, 0, Qt.AlignmentFlag.AlignCenter)
            col.addWidget(lbl_f, 0, Qt.AlignmentFlag.AlignCenter)
            eq_grid.addLayout(col)

        eq_layout.addLayout(eq_grid)
        layout.addWidget(eq_group)

        # Close
        btn_bar = QHBoxLayout()
        btn_bar.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(btn_close)
        layout.addLayout(btn_bar)

    def _populate_tracks(self):
        self.track_combo.clear()
        audio_tracks = [t for t in self.tracks if t.get("type") == "audio"]
        if not audio_tracks:
            self.track_combo.addItem("No Audio Tracks Available", -1)
            return

        for t in audio_tracks:
            t_id = t.get("id", 1)
            title = t.get("title") or t.get("lang") or f"Audio Track {t_id}"
            channels = t.get("demux-channels") or t.get("audio-channels") or ""
            codec = t.get("codec", "")
            ext = " [External]" if t.get("external") else ""
            label = f"#{t_id}: {title} ({codec} {channels}){ext}"
            self.track_combo.addItem(label, t_id)
            if t.get("selected"):
                self.track_combo.setCurrentIndex(self.track_combo.count() - 1)

    def _on_track_selected(self, index: int):
        track_id = self.track_combo.currentData()
        if track_id is not None and track_id >= 0:
            self.audio_track_changed.emit(track_id)

    def _on_iab_mode_changed(self, index: int):
        mode_key = self.combo_iab_mode.currentData()
        if mode_key:
            self.current_iab_mode = mode_key
            self.iab_mode_changed.emit(mode_key)

    def _browse_external_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select External Audio File", "",
            "Audio Files (*.wav *.flac *.mp3 *.aac *.ac3 *.dts *.m4a *.opus *.ogg *.mxf);;All Files (*.*)"
        )
        if path:
            self.load_external_audio.emit(path)
            QMessageBox.information(self, "Success", f"Loaded external audio:\n{path}")
            self.accept()

    def _adjust_delay(self, delta_ms: int):
        self._set_delay(self.current_delay_ms + delta_ms)

    def _set_delay(self, ms: int):
        self.current_delay_ms = max(-5000, min(5000, ms))
        self.delay_slider.setValue(self.current_delay_ms)
        self.lbl_delay_val.setText(f"{self.current_delay_ms} ms")
        self.audio_delay_changed.emit(self.current_delay_ms / 1000.0)

    def _on_slider_delay_changed(self, val: int):
        self.current_delay_ms = val
        self.lbl_delay_val.setText(f"{self.current_delay_ms} ms")
        self.audio_delay_changed.emit(self.current_delay_ms / 1000.0)

    def _apply_eq_preset(self, preset_name: str):
        values = self.EQ_PRESETS.get(preset_name, [0]*10)
        for s, v in zip(self.eq_sliders, values):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)
        self._emit_eq_change()

    def _emit_eq_change(self):
        gains = [s.value() for s in self.eq_sliders]
        self.equalizer_changed.emit(gains)
