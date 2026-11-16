"""
BOOB Player - Lossless Stream Trimmer Dialog
Precision dialog for zero-reencode clipping of video segments with timestamp and frame controls.
"""

import os
from typing import Optional, Tuple, Any
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QProgressBar, QMessageBox, QFrame,
    QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.clip_trimmer import LosslessTrimWorker
from ui.goto_dialog import parse_time_string


class LosslessTrimDialog(QDialog):
    clip_exported = pyqtSignal(str)

    def __init__(
        self,
        source_path: str,
        start_pts: float = 0.0,
        end_pts: float = 0.0,
        total_duration: float = 0.0,
        fps: float = 24.0,
        parent=None
    ):
        super().__init__(parent)
        self.source_path = source_path
        self.start_pts = max(0.0, start_pts)
        self.total_duration = total_duration
        self.fps = fps if fps > 0 else 24.0
        self.end_pts = end_pts if end_pts > self.start_pts else (total_duration if total_duration > self.start_pts else self.start_pts + 10.0)
        self.worker: Optional[LosslessTrimWorker] = None

        self.setWindowTitle("✂️ Lossless Clip Trimmer (Zero Re-encode Stream Copy)")
        self.setMinimumWidth(700)
        self.setMinimumHeight(480)
        self.resize(740, 500)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Info Card
        header = QFrame()
        header.setStyleSheet("""
            background: #11141c;
            border: 1px solid #1e2638;
            border-radius: 8px;
            padding: 10px;
        """)
        h_box = QVBoxLayout(header)
        h_box.setSpacing(4)
        
        lbl_title = QLabel("✂️ Lossless Video Extractor (Fast FFmpeg Stream Copy)")
        lbl_title.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 14px;")
        h_box.addWidget(lbl_title)

        fn = os.path.basename(self.source_path) if self.source_path else "No file loaded"
        lbl_src = QLabel(f"Source: {fn}")
        lbl_src.setStyleSheet("color: #94a3b8; font-size: 11px; font-family: monospace;")
        h_box.addWidget(lbl_src)
        layout.addWidget(header)

        # Time range box
        range_grp = QGroupBox("Clip Range [In / Out Points]")
        range_layout = QVBoxLayout(range_grp)
        range_layout.setSpacing(8)

        # In Point
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("In Point (Start):"))
        self.txt_in = QLineEdit(self._format_pts(self.start_pts))
        self.txt_in.setStyleSheet("font-family: monospace; font-size: 13px; font-weight: bold; color: #38bdf8;")
        self.txt_in.textChanged.connect(self._update_duration_label)
        in_row.addWidget(self.txt_in)

        btn_cur_in = QPushButton("Current Time")
        btn_cur_in.setToolTip("Set In Point to current playback time")
        btn_cur_in.clicked.connect(lambda: self.txt_in.setText(self._format_pts(self.start_pts)))
        in_row.addWidget(btn_cur_in)
        range_layout.addLayout(in_row)

        # Out Point
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Out Point (End): "))
        self.txt_out = QLineEdit(self._format_pts(self.end_pts))
        self.txt_out.setStyleSheet("font-family: monospace; font-size: 13px; font-weight: bold; color: #38bdf8;")
        self.txt_out.textChanged.connect(self._update_duration_label)
        out_row.addWidget(self.txt_out)

        btn_cur_out = QPushButton("Current Time")
        btn_cur_out.setToolTip("Set Out Point to current playback time")
        btn_cur_out.clicked.connect(lambda: self.txt_out.setText(self._format_pts(self.end_pts)))
        out_row.addWidget(btn_cur_out)
        range_layout.addLayout(out_row)

        self.lbl_clip_dur = QLabel("Clip Duration: 00:00:00 (0 frames)")
        self.lbl_clip_dur.setStyleSheet("color: #a855f7; font-weight: 600; font-size: 12px;")
        range_layout.addWidget(self.lbl_clip_dur)
        layout.addWidget(range_grp)

        # Destination file path
        dst_grp = QGroupBox("Export Destination")
        dst_layout = QHBoxLayout(dst_grp)
        self.txt_dest = QLineEdit(self._default_output_path())
        self.txt_dest.setStyleSheet("font-family: monospace; font-size: 12px;")
        dst_layout.addWidget(self.txt_dest, 1)

        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._on_browse_destination)
        dst_layout.addWidget(btn_browse)
        layout.addWidget(dst_grp)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #1e293b;
                border-radius: 4px;
                text-align: center;
                background: #090d16;
                color: #ffffff;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: #00d2ff;
            }
        """)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ready to export lossless stream copy. No re-encoding.")
        self.lbl_status.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_export = QPushButton("🚀 Export Lossless Clip")
        self.btn_export.setObjectName("accentButton")
        self.btn_export.setStyleSheet("""
            QPushButton#accentButton {
                background: #0284c7;
                border: 1px solid #38bdf8;
                color: #ffffff;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 6px;
            }
            QPushButton#accentButton:hover {
                background: #0369a1;
            }
        """)
        self.btn_export.clicked.connect(self._start_export)
        btn_row.addWidget(self.btn_export)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        self._update_duration_label()

    def _default_output_path(self) -> str:
        if not self.source_path:
            return ""
        dirname = os.path.dirname(self.source_path)
        base, ext = os.path.splitext(os.path.basename(self.source_path))
        return os.path.join(dirname, f"{base}_clip{ext}")

    def _format_pts(self, pts: float) -> str:
        s = int(pts)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        ms = int((pts - int(pts)) * 1000)
        return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"

    def _parse_pts(self, text: str) -> Optional[float]:
        try:
            return parse_time_string(text.strip())
        except Exception:
            return None

    def _update_duration_label(self):
        in_s = self._parse_pts(self.txt_in.text())
        out_s = self._parse_pts(self.txt_out.text())
        if in_s is not None and out_s is not None and out_s > in_s:
            diff = out_s - in_s
            frames = int(round(diff * self.fps))
            self.lbl_clip_dur.setText(f"Clip Duration: {self._format_pts(diff)} ({frames:,} frames @ {self.fps:.2f} fps)")
            self.lbl_clip_dur.setStyleSheet("color: #a855f7; font-weight: 600; font-size: 12px;")
            self.btn_export.setEnabled(True)
        else:
            self.lbl_clip_dur.setText("Clip Duration: Invalid time range (Out point must be greater than In point)")
            self.lbl_clip_dur.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 12px;")
            self.btn_export.setEnabled(False)

    def _on_browse_destination(self):
        cur = self.txt_dest.text() or self._default_output_path()
        out, _ = QFileDialog.getSaveFileName(
            self,
            "Save Trimmed Clip As...",
            cur,
            "All Media Files (*.*)"
        )
        if out:
            self.txt_dest.setText(out)

    def _start_export(self):
        in_s = self._parse_pts(self.txt_in.text())
        out_s = self._parse_pts(self.txt_out.text())
        dest = self.txt_dest.text().strip()

        if in_s is None or out_s is None or out_s <= in_s:
            QMessageBox.warning(self, "Invalid Range", "Please enter a valid In and Out time range.")
            return

        if not dest:
            QMessageBox.warning(self, "No Destination", "Please choose an export destination path.")
            return

        self.btn_export.setEnabled(False)
        self.btn_cancel.setText("Cancel Export")
        self.progress_bar.setValue(15)
        self.lbl_status.setText("Exporting lossless stream copy via FFmpeg...")

        self.worker = LosslessTrimWorker(
            source_path=self.source_path,
            output_path=dest,
            start_time_sec=in_s,
            end_time_sec=out_s,
            parent=self
        )
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self._on_export_finished)
        self.worker.error.connect(lambda err: QMessageBox.critical(self, "Trim Error", err))
        self.worker.start()

    def _on_export_finished(self, success: bool, path: str, elapsed: float):
        self.btn_export.setEnabled(True)
        self.btn_cancel.setText("Close")
        if success:
            self.progress_bar.setValue(100)
            self.lbl_status.setText(f"Export Completed in {elapsed:.2f}s! Lossless copy saved.")
            self.lbl_status.setStyleSheet("color: #4ade80; font-weight: bold;")
            self.clip_exported.emit(path)
            QMessageBox.information(
                self,
                "Export Complete",
                f"Lossless clip successfully exported in {elapsed:.2f}s!\n\nFile: {path}"
            )
            self.accept()
        else:
            self.progress_bar.setValue(0)
            self.lbl_status.setText("Export failed or was cancelled.")
            self.lbl_status.setStyleSheet("color: #ef4444; font-weight: bold;")

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1000)
        super().reject()
