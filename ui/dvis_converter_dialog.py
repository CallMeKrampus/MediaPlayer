"""
BOOB Player - Dolby Vision / EDR Digital Cinema (DVis DCP) Conversion Dialog
Interactive Studio Dark UI for transcoding DCI 108-nit XYZ-PQ codestreams
into Consumer HDR10 (Rec.2020 PQ) and Rec.709 SDR deliverables.
"""

import os
import sys
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QComboBox, QLineEdit, QFileDialog,
    QProgressBar, QGroupBox, QSpinBox, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.dcp_parser import DCPComposition, DCPPackage
from core.dvis_converter import DVisConversionConfig, DVisConversionWorker
from core.gpu_detector import GPUDetector
from core.nvjpeg2k_engine import is_gpu_jp2k_available


class DVisConverterDialog(QDialog):
    """
    Studio-grade conversion dialog for DVis DCPs.
    Converts 12-bit DCI XYZ-PQ packages to Consumer HDR10 or Rec.709 SDR.
    """

    def __init__(self, composition: DCPComposition, dcp_package: Optional[DCPPackage] = None, parent=None):
        super().__init__(parent)
        self.cpl = composition
        self.dcp = dcp_package
        self.worker: Optional[DVisConversionWorker] = None

        self.setWindowTitle("💎 Dolby Vision DCP Converter (DVis → HDR10 / SDR)")
        self.setMinimumSize(680, 600)
        self.resize(720, 640)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Header Banner
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            background: #121319;
            border: 1px solid #22242f;
            border-radius: 8px;
            padding: 12px;
        """)
        h_layout = QVBoxLayout(header_frame)
        h_layout.setSpacing(4)

        title_row = QHBoxLayout()
        self.lbl_title = QLabel("💎 Dolby Cinema EDR Master")
        self.lbl_title.setStyleSheet("color: #e4e4e7; font-size: 15px; font-weight: bold;")
        title_row.addWidget(self.lbl_title)

        self.badge_edr = QLabel("108-nit XYZ-PQ")
        self.badge_edr.setStyleSheet("""
            background: #272a38;
            color: #a78bfa;
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 4px;
            border: 1px solid #3b3f52;
        """)
        title_row.addWidget(self.badge_edr)
        title_row.addStretch(1)
        h_layout.addLayout(title_row)

        cpl_name = self.cpl.title if self.cpl else "Dolby Vision DCP"
        self.lbl_cpl = QLabel(f"Source: {cpl_name}")
        self.lbl_cpl.setStyleSheet("color: #a1a1aa; font-size: 11.5px;")
        self.lbl_cpl.setWordWrap(True)
        h_layout.addWidget(self.lbl_cpl)

        gpu_info = GPUDetector.get_info()
        gpu_txt = f"⚡ Hardware Decoder: {gpu_info.name} (Active)" if is_gpu_jp2k_available() else "ℹ️ Decoder: Multi-threaded CPU Fallback"
        self.lbl_gpu = QLabel(gpu_txt)
        self.lbl_gpu.setStyleSheet("color: #10b981; font-size: 11px; font-weight: 500;" if is_gpu_jp2k_available() else "color: #94a3b8; font-size: 11px;")
        h_layout.addWidget(self.lbl_gpu)

        layout.addWidget(header_frame)

        # 1. Target Color Science Mode
        grp_target = QGroupBox("1. Target Color Science & Gamut")
        grp_target.setStyleSheet("QGroupBox { font-weight: bold; color: #e4e4e7; border: 1px solid #22242f; border-radius: 6px; margin-top: 6px; padding-top: 14px; }")
        t_layout = QVBoxLayout(grp_target)
        t_layout.setSpacing(8)

        self.btn_grp_target = QButtonGroup(self)
        self.rad_hdr10 = QRadioButton("Consumer HDR10 (Rec.2020 PQ, 10-bit) — For 4K HDR TVs, OLEDs & Apple XDR Displays")
        self.rad_hdr10.setChecked(True)
        self.rad_hdr10.setStyleSheet("color: #e4e4e7; font-size: 12px;")
        self.btn_grp_target.addButton(self.rad_hdr10)
        t_layout.addWidget(self.rad_hdr10)

        self.rad_sdr = QRadioButton("Studio Rec.709 SDR (BT.1886 Gamma 2.4, 100 nits) — Highlight Shoulder Preserved")
        self.rad_sdr.setStyleSheet("color: #e4e4e7; font-size: 12px;")
        self.btn_grp_target.addButton(self.rad_sdr)
        t_layout.addWidget(self.rad_sdr)

        layout.addWidget(grp_target)

        # 2. Output Format & Audio
        grp_format = QGroupBox("2. Encoding Format & Multichannel Sound")
        grp_format.setStyleSheet("QGroupBox { font-weight: bold; color: #e4e4e7; border: 1px solid #22242f; border-radius: 6px; margin-top: 6px; padding-top: 14px; }")
        f_layout = QVBoxLayout(grp_format)
        f_layout.setSpacing(8)

        f_row = QHBoxLayout()
        f_row.addWidget(QLabel("Video Codec / Container:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems([
            "HEVC / H.265 10-bit (.mp4) — High-Efficiency Consumer Playback",
            "Apple ProRes 422 HQ (.mov) — Broadcast Archival / Mastering Grade",
            "H.264 8-bit (.mp4) — Universal Legacy SDR Compatibility"
        ])
        f_row.addWidget(self.combo_format, 1)
        f_layout.addLayout(f_row)

        a_row = QHBoxLayout()
        a_row.addWidget(QLabel("DCP Sound Track (PCM):"))
        self.combo_audio = QComboBox()
        self.combo_audio.addItems([
            "5.1 Surround Sound (AAC 448k) — Recommended",
            "Stereo Downmix (AAC 256k)",
            "Uncompressed 5.1 PCM (24-bit 48kHz)",
            "None (Video Only)"
        ])
        a_row.addWidget(self.combo_audio, 1)
        f_layout.addLayout(a_row)

        layout.addWidget(grp_format)

        # 3. Render Range
        grp_range = QGroupBox("3. Render Range")
        grp_range.setStyleSheet("QGroupBox { font-weight: bold; color: #e4e4e7; border: 1px solid #22242f; border-radius: 6px; margin-top: 6px; padding-top: 14px; }")
        r_layout = QVBoxLayout(grp_range)
        r_layout.setSpacing(6)

        total_f = self.cpl.total_frames if self.cpl else 5233
        dur_tc = self.cpl.total_timecode if self.cpl else "03:38"

        self.btn_grp_range = QButtonGroup(self)
        self.rad_full = QRadioButton(f"Full Feature ({total_f:,} frames / {dur_tc})")
        self.rad_full.setChecked(True)
        self.rad_full.setStyleSheet("color: #e4e4e7; font-size: 12px;")
        self.btn_grp_range.addButton(self.rad_full)
        r_layout.addWidget(self.rad_full)

        self.rad_sample = QRadioButton("Sample Preview (120 frames / 5.0 seconds test)")
        self.rad_sample.setStyleSheet("color: #e4e4e7; font-size: 12px;")
        self.btn_grp_range.addButton(self.rad_sample)
        r_layout.addWidget(self.rad_sample)

        custom_row = QHBoxLayout()
        self.rad_custom = QRadioButton("Custom Frame Range:")
        self.rad_custom.setStyleSheet("color: #e4e4e7; font-size: 12px;")
        self.btn_grp_range.addButton(self.rad_custom)
        custom_row.addWidget(self.rad_custom)

        custom_row.addWidget(QLabel("Start:"))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, total_f)
        self.spin_start.setValue(0)
        self.spin_start.setEnabled(False)
        custom_row.addWidget(self.spin_start)

        custom_row.addWidget(QLabel("End:"))
        self.spin_end = QSpinBox()
        self.spin_end.setRange(1, total_f)
        self.spin_end.setValue(min(total_f, 120))
        self.spin_end.setEnabled(False)
        custom_row.addWidget(self.spin_end)
        custom_row.addStretch(1)

        self.rad_custom.toggled.connect(self._toggle_custom_range)
        r_layout.addLayout(custom_row)

        layout.addWidget(grp_range)

        # 4. Destination File
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output File:"))
        self.txt_out = QLineEdit()
        default_name = f"{os.path.splitext(cpl_name)[0]}_HDR10.mp4"
        self.txt_out.setText(os.path.join(os.path.expanduser("~"), "Videos", default_name))
        out_row.addWidget(self.txt_out, 1)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.btn_browse)
        layout.addLayout(out_row)

        # Progress Section
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #22242f;
                border-radius: 4px;
                text-align: center;
                background: #0f1015;
                color: #e4e4e7;
                font-weight: bold;
                height: 18px;
            }
            QProgressBar::chunk {
                background: #8b5cf6;
            }
        """)
        layout.addWidget(self.progress_bar)

        self.lbl_stats = QLabel("Status: Ready to convert.")
        self.lbl_stats.setStyleSheet("color: #a1a1aa; font-size: 11.5px;")
        layout.addWidget(self.lbl_stats)

        # Bottom Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_start = QPushButton("🚀 Start Conversion")
        self.btn_start.setObjectName("cinemaButton")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: #7c3aed;
                color: #ffffff;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #6d28d9;
            }
            QPushButton:disabled {
                background: #3b3f52;
                color: #64748b;
            }
        """)
        self.btn_start.clicked.connect(self._start_conversion)
        btn_bar.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("Stop")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_conversion)
        btn_bar.addWidget(self.btn_cancel)

        btn_bar.addStretch(1)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_close)

        layout.addLayout(btn_bar)

        # Update output extension when target or format changes
        self.rad_hdr10.toggled.connect(self._update_default_filename)
        self.rad_sdr.toggled.connect(self._update_default_filename)
        self.combo_format.currentIndexChanged.connect(self._update_default_filename)

    def _toggle_custom_range(self, checked: bool):
        self.spin_start.setEnabled(checked)
        self.spin_end.setEnabled(checked)

    def _update_default_filename(self):
        cpl_name = self.cpl.title if self.cpl else "DVis_Converted"
        base = os.path.splitext(cpl_name)[0]
        mode_str = "HDR10" if self.rad_hdr10.isChecked() else "SDR_BT709"
        fmt_idx = self.combo_format.currentIndex()
        ext = ".mov" if fmt_idx == 1 else ".mp4"

        curr_dir = os.path.dirname(self.txt_out.text()) or os.path.expanduser("~")
        self.txt_out.setText(os.path.join(curr_dir, f"{base}_{mode_str}{ext}"))

    def _browse_output(self):
        fmt_idx = self.combo_format.currentIndex()
        filt = "QuickTime Movie (*.mov)" if fmt_idx == 1 else "MP4 Video (*.mp4)"
        path, _ = QFileDialog.getSaveFileName(self, "Save Converted Master As", self.txt_out.text(), filt)
        if path:
            self.txt_out.setText(path)

    def _start_conversion(self):
        # Resolve picture and audio MXF paths
        reel = self.cpl.reels[0] if self.cpl and len(self.cpl.reels) > 0 else None
        if not reel or not reel.picture_path or not os.path.isfile(reel.picture_path):
            QMessageBox.warning(self, "Missing Picture Asset", "The composition's picture MXF could not be found.")
            return

        out_path = self.txt_out.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Missing Output File", "Please specify a destination file path.")
            return

        target_mode = "hdr10" if self.rad_hdr10.isChecked() else "sdr"
        fmt_idx = self.combo_format.currentIndex()
        fmt_type = "mp4_hevc" if fmt_idx == 0 else "prores" if fmt_idx == 1 else "mp4_h264"

        aud_idx = self.combo_audio.currentIndex()
        aud_mode = "5.1_aac" if aud_idx == 0 else "stereo_aac" if aud_idx == 1 else "pcm_copy" if aud_idx == 2 else "none"

        start_f = 0
        end_f = 0
        if self.rad_sample.isChecked():
            start_f = 0
            end_f = 120
        elif self.rad_custom.isChecked():
            start_f = self.spin_start.value()
            end_f = self.spin_end.value()

        config = DVisConversionConfig(
            input_video_mxf=reel.picture_path,
            output_file=out_path,
            target_mode=target_mode,
            format_type=fmt_type,
            audio_mxf=reel.sound_path if reel.sound_path and os.path.isfile(reel.sound_path) else None,
            audio_mode=aud_mode,
            start_frame=start_f,
            end_frame=end_f,
            fps=self.cpl.fps if self.cpl else 24.0,
            width=4096,
            height=1716,
            prefer_gpu=True,
        )

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_close.setEnabled(False)
        self.progress_bar.setValue(0)
        self.lbl_stats.setText("Starting conversion worker...")

        self.worker = DVisConversionWorker(config)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.status_message.connect(self._on_status)
        self.worker.conversion_finished.connect(self._on_finished)
        self.worker.start()

    def _cancel_conversion(self):
        if self.worker and self.worker.isRunning():
            self.lbl_stats.setText("Stopping worker...")
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)

    def _on_progress(self, current: int, total: int, fps: float, eta_sec: float):
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(pct)
        eta_m, eta_s = divmod(int(eta_sec), 60)
        self.lbl_stats.setText(f"Frame {current:,} / {total:,} ({pct}%) | {fps:.1f} FPS | ETA: {eta_m:02d}:{eta_s:02d}")

    def _on_status(self, msg: str):
        self.lbl_stats.setText(msg)

    def _on_finished(self, success: bool, out_file: str, msg: str):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)

        if success:
            self.progress_bar.setValue(100)
            self.lbl_stats.setText(f"Finished: {msg}")
            res = QMessageBox.information(
                self, "Conversion Complete",
                f"Successfully converted Dolby Vision DCP to {self.btn_grp_target.checkedButton().text().split('—')[0].strip()}!\n\n"
                f"File: {out_file}\n\n{msg}",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Ok
            )
            if res == QMessageBox.StandardButton.Open:
                folder = os.path.dirname(out_file)
                if os.path.isdir(folder):
                    os.startfile(folder)
        else:
            self.lbl_stats.setText(f"Error: {msg}")
            QMessageBox.critical(self, "Conversion Error", f"Conversion could not be completed:\n\n{msg}")
