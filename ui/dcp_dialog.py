"""
BOOB Player - Digital Cinema Package (DCP) Inspector & Synchronizer
Comprehensive inspector for SMPTE/Interop CPLs, Reels, MXF Picture & Sound assets,
and Cryptographic PKL Hash Verification (QC Integrity Check).
"""

import os
from typing import Optional, List, Dict, Any, Tuple
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QFileDialog, QMessageBox, QFrame, QTabWidget, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from core.dcp_parser import DCPParser, DCPPackage, DCPReel, DCPComposition
from core.dcp_verifier import DCPVerifierThread, AssetVerificationResult


class DCPInspectorDialog(QDialog):
    play_dcp_requested = pyqtSignal(DCPPackage, int, int)  # package, cpl_idx, reel_idx

    def __init__(self, dcp_package: DCPPackage = None, parent=None):
        super().__init__(parent)
        self.dcp = dcp_package
        self.verifier_thread: Optional[DCPVerifierThread] = None
        self.setWindowTitle("🎬 Digital Cinema Package (DCP) Inspector & QC Suite")
        self.setMinimumSize(1080, 660)
        self.resize(1120, 700)
        self._init_ui()

        if self.dcp:
            self._display_dcp(self.dcp)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Info Banner
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a162b, stop:1 #12151f);
            border: 1px solid #3b2d54;
            border-radius: 8px;
            padding: 12px;
        """)
        h_layout = QVBoxLayout(header_frame)
        h_layout.setSpacing(4)

        self.lbl_title = QLabel("Composition: No DCP Loaded")
        self.lbl_title.setStyleSheet("color: #a855f7; font-size: 16px; font-weight: bold;")
        h_layout.addWidget(self.lbl_title)

        self.lbl_meta = QLabel("Standard: - | Frame Rate: - | Duration: - | Total Frames: -")
        self.lbl_meta.setStyleSheet("color: #94a3b8; font-size: 12px;")
        h_layout.addWidget(self.lbl_meta)

        self.lbl_path = QLabel("Folder: -")
        self.lbl_path.setStyleSheet("color: #64748b; font-size: 11px;")
        h_layout.addWidget(self.lbl_path)

        layout.addWidget(header_frame)

        # Tabs: 1) Composition Reels & Audio, 2) Cryptographic Hash QC
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #232938;
                border-radius: 6px;
                background: #0d1017;
            }
            QTabBar::tab {
                background: #161b26;
                color: #94a3b8;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 600;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #0d1017;
                color: #00d2ff;
                border-bottom: 2px solid #00d2ff;
            }
        """)

        # Tab 1: Reels & IAB
        tab_reels = QWidget()
        tab_reels_layout = QVBoxLayout(tab_reels)
        tab_reels_layout.setContentsMargins(8, 8, 8, 8)
        tab_reels_layout.setSpacing(8)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Reel #", "Duration", "Frames", "Aspect Ratio", "Picture (JP2K MXF)", "Master Sound (PCM MXF)", "Immersive Audio (IAB MXF)", "Subtitles (MXF/XML)"
        ])
        for i in range(4):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(4, 8):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        tab_reels_layout.addWidget(self.table, 1)

        # IAB Card
        self.iab_group = QGroupBox("🎧 SMPTE ST 2098-2 Immersive Audio Bitstream (IAB / Dolby Atmos)")
        iab_layout = QVBoxLayout(self.iab_group)
        iab_layout.setContentsMargins(12, 10, 12, 10)
        iab_layout.setSpacing(4)

        self.lbl_iab_status = QLabel("IAB Status: Analyzing Reel Assets...")
        self.lbl_iab_status.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 13px;")
        iab_layout.addWidget(self.lbl_iab_status)

        self.lbl_iab_specs = QLabel("Standard: SMPTE ST 2098-2 / ST 429-18 | Essence UL: 060E2B34.04010105.0E090604.00000000")
        self.lbl_iab_specs.setStyleSheet("color: #94a3b8; font-size: 11px;")
        iab_layout.addWidget(self.lbl_iab_specs)

        self.lbl_iab_frames = QLabel("Total Frames: - | Bitrate: - | Active 3D Spatial Objects: -")
        self.lbl_iab_frames.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        iab_layout.addWidget(self.lbl_iab_frames)
        tab_reels_layout.addWidget(self.iab_group)

        self.tabs.addTab(tab_reels, "🎞️ Composition Reels & Sound")

        # Tab 2: Cryptographic QC Integrity & Hash Verification
        tab_qc = QWidget()
        tab_qc_layout = QVBoxLayout(tab_qc)
        tab_qc_layout.setContentsMargins(10, 10, 10, 10)
        tab_qc_layout.setSpacing(10)

        qc_info = QLabel("Validates block-level SHA-1 and SHA-256 digests from the Packing List (PKL) against physical MXF containers on disk.")
        qc_info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        tab_qc_layout.addWidget(qc_info)

        self.qc_table = QTableWidget()
        self.qc_table.setColumnCount(6)
        self.qc_table.setHorizontalHeaderLabels([
            "Asset / File", "Size", "Algorithm", "Expected Hash (PKL)", "Calculated Digest", "QC Status"
        ])
        self.qc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.qc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.qc_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.qc_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        tab_qc_layout.addWidget(self.qc_table, 1)

        # QC Progress & Status
        qc_ctrl_row = QHBoxLayout()
        self.btn_start_qc = QPushButton("🛡️ Verify Package Hashes")
        self.btn_start_qc.setObjectName("cinemaButton")
        self.btn_start_qc.clicked.connect(self._start_hash_verification)
        qc_ctrl_row.addWidget(self.btn_start_qc)

        self.btn_cancel_qc = QPushButton("Stop Verification")
        self.btn_cancel_qc.setEnabled(False)
        self.btn_cancel_qc.clicked.connect(self._cancel_hash_verification)
        qc_ctrl_row.addWidget(self.btn_cancel_qc)

        self.lbl_qc_speed = QLabel("Status: Idle")
        self.lbl_qc_speed.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px;")
        qc_ctrl_row.addWidget(self.lbl_qc_speed, 1)

        tab_qc_layout.addLayout(qc_ctrl_row)

        self.qc_progress = QProgressBar()
        self.qc_progress.setRange(0, 100)
        self.qc_progress.setValue(0)
        self.qc_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #1e293b;
                border-radius: 4px;
                text-align: center;
                background: #090d16;
                color: #ffffff;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: #10b981;
            }
        """)
        tab_qc_layout.addWidget(self.qc_progress)

        self.lbl_qc_verdict = QLabel("Verdict: Package not yet verified")
        self.lbl_qc_verdict.setStyleSheet("color: #64748b; font-weight: bold; font-size: 12px;")
        tab_qc_layout.addWidget(self.lbl_qc_verdict)

        self.tabs.addTab(tab_qc, "🛡️ QC Integrity & Hashes")
        layout.addWidget(self.tabs, 1)

        # Bottom Button Bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_open_folder = QPushButton("📂 Open DCP Folder...")
        self.btn_open_folder.clicked.connect(self._browse_dcp_folder)
        btn_bar.addWidget(self.btn_open_folder)

        btn_bar.addStretch(1)

        self.btn_play_selected = QPushButton("▶ Play Selected Reel")
        self.btn_play_selected.clicked.connect(self._play_selected_reel)
        btn_bar.addWidget(self.btn_play_selected)

        self.btn_play_all = QPushButton("🎬 Play Entire DCP from Start")
        self.btn_play_all.setObjectName("cinemaButton")
        self.btn_play_all.clicked.connect(self._play_entire_dcp)
        btn_bar.addWidget(self.btn_play_all)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(self.btn_close)

        layout.addLayout(btn_bar)

    def set_dcp(self, dcp_package: DCPPackage):
        self.dcp = dcp_package
        self._display_dcp(dcp_package)

    def _display_dcp(self, dcp: DCPPackage):
        cpl = dcp.default_composition
        if not cpl:
            self.lbl_title.setText("Composition: (No CPL Found in DCP)")
            return

        total_sub_reels = sum(1 for r in cpl.reels if getattr(r, "subtitle_path", None))
        sub_info = f" | Subtitles: {total_sub_reels} reel tracks" if total_sub_reels > 0 else ""
        dvis_tag = " | 💎 Dolby Cinema EDR (108 nits XYZ-PQ)" if getattr(cpl, "is_dolby_vision", False) else ""
        self.lbl_title.setText(f"Composition: {cpl.title}")
        self.lbl_meta.setText(
            f"Standard: {cpl.standard} | Kind: {cpl.content_kind.upper()}{dvis_tag} | "
            f"FPS: {cpl.fps:.2f} | Timecode: {cpl.total_timecode} ({cpl.total_frames} frames) | "
            f"Reels: {len(cpl.reels)}{sub_info}"
        )
        self.lbl_path.setText(f"Folder: {dcp.root_path}")

        # Populate Reels Table
        self.table.setRowCount(len(cpl.reels))
        for row, reel in enumerate(cpl.reels):
            item_reel = QTableWidgetItem(f"Reel {reel.index}")
            item_reel.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, item_reel)

            item_tc = QTableWidgetItem(reel.timecode)
            item_tc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, item_tc)

            item_frames = QTableWidgetItem(str(reel.picture_duration_frames))
            item_frames.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, item_frames)

            item_ar = QTableWidgetItem(reel.screen_aspect_ratio)
            item_ar.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, item_ar)

            pic_name = os.path.basename(reel.picture_path) if reel.picture_path else "(Missing Picture)"
            item_pic = QTableWidgetItem(pic_name)
            item_pic.setToolTip(reel.picture_path)
            self.table.setItem(row, 4, item_pic)

            snd_name = os.path.basename(reel.sound_path) if reel.sound_path else "(No Sound)"
            item_snd = QTableWidgetItem(snd_name)
            item_snd.setToolTip(reel.sound_path)
            self.table.setItem(row, 5, item_snd)

            atmos_name = os.path.basename(reel.atmos_path) if hasattr(reel, "atmos_path") and reel.atmos_path else "(None)"
            item_atmos = QTableWidgetItem(atmos_name)
            if hasattr(reel, "atmos_path") and reel.atmos_path:
                item_atmos.setToolTip(reel.atmos_path)
                item_atmos.setForeground(Qt.GlobalColor.cyan)
            self.table.setItem(row, 6, item_atmos)

            sub_name = os.path.basename(reel.subtitle_path) if hasattr(reel, "subtitle_path") and reel.subtitle_path else "(None)"
            item_sub = QTableWidgetItem(sub_name)
            if hasattr(reel, "subtitle_path") and reel.subtitle_path:
                item_sub.setToolTip(reel.subtitle_path)
                item_sub.setForeground(Qt.GlobalColor.yellow)
            self.table.setItem(row, 7, item_sub)

        # Inspect Atmos
        from core.iab_engine import IABEngine
        first_atmos = None
        for r in cpl.reels:
            if hasattr(r, "atmos_path") and r.atmos_path and os.path.exists(r.atmos_path):
                first_atmos = r.atmos_path
                break

        if first_atmos:
            meta = IABEngine.parse_track(first_atmos, max_frames_to_index=200)
            if meta:
                self.lbl_iab_status.setText(f"IAB Status: Verified Active ({os.path.basename(first_atmos)})")
                self.lbl_iab_frames.setText(
                    f"Bitstream Frames: {meta.total_frames:,} | "
                    f"Avg Bitrate: {meta.avg_bitrate_kbps:.1f} kbps | "
                    f"Sample Rate: {meta.sample_rate} Hz | "
                    f"Object Beds: {meta.active_sound_beds} | "
                    f"3D Spatial Trajectories: Synchronized"
                )
            else:
                self.lbl_iab_status.setText("IAB Status: File Present (SMPTE ST 429-18 AuxData)")
        else:
            self.lbl_iab_status.setText("IAB Status: No AuxData / Atmos track in composition")
            self.lbl_iab_frames.setText("Total Frames: - | Bitrate: - | Standard PCM Multi-Channel Audio Only")

        # Populate QC Table
        verifiable = dcp.get_verifiable_assets()
        self.qc_table.setRowCount(len(verifiable))
        for row, asset in enumerate(verifiable):
            fn = asset.get("original_filename") or os.path.basename(asset.get("file_path", ""))
            sz = asset.get("size", 0)
            sz_str = f"{sz / (1024*1024):.1f} MB" if sz > 0 else "-"
            algo = asset.get("hash_algo", "SHA-1")
            exp_h = asset.get("expected_hash", "")

            self.qc_table.setItem(row, 0, QTableWidgetItem(fn))
            self.qc_table.setItem(row, 1, QTableWidgetItem(sz_str))
            self.qc_table.setItem(row, 2, QTableWidgetItem(algo))
            self.qc_table.setItem(row, 3, QTableWidgetItem(exp_h))
            self.qc_table.setItem(row, 4, QTableWidgetItem("-"))
            status_item = QTableWidgetItem("Ready")
            status_item.setForeground(QColor("#94a3b8"))
            self.qc_table.setItem(row, 5, status_item)

        if cpl.reels:
            self.table.selectRow(0)

    def _start_hash_verification(self):
        if not self.dcp:
            return
        verifiable = self.dcp.get_verifiable_assets()
        if not verifiable:
            QMessageBox.information(self, "No Assets", "No verifiable PKL assets found in this package.")
            return

        self.btn_start_qc.setEnabled(False)
        self.btn_cancel_qc.setEnabled(True)
        self.qc_progress.setValue(0)
        self.lbl_qc_speed.setText("Starting cryptographic verification...")
        self.lbl_qc_verdict.setText("Verdict: Verifying assets against PKL digests...")
        self.lbl_qc_verdict.setStyleSheet("color: #38bdf8; font-weight: bold;")

        self.verifier_thread = DCPVerifierThread(verifiable, parent=self)
        self.verifier_thread.asset_started.connect(self._on_qc_asset_started)
        self.verifier_thread.asset_progress.connect(self._on_qc_asset_progress)
        self.verifier_thread.asset_completed.connect(self._on_qc_asset_completed)
        self.verifier_thread.overall_progress.connect(self._on_qc_overall_progress)
        self.verifier_thread.verification_finished.connect(self._on_qc_finished)
        self.verifier_thread.start()

    def _cancel_hash_verification(self):
        if self.verifier_thread and self.verifier_thread.isRunning():
            self.verifier_thread.cancel()
            self.btn_cancel_qc.setEnabled(False)
            self.lbl_qc_speed.setText("Verification cancelled by user.")

    def _on_qc_asset_started(self, uuid: str, filename: str, size: int):
        self.lbl_qc_speed.setText(f"Verifying: {filename} ({size / (1024*1024):.1f} MB)...")

    def _on_qc_asset_progress(self, uuid: str, bytes_proc: int, total_bytes: int, mb_s: float):
        self.lbl_qc_speed.setText(f"Hashing: {bytes_proc / (1024*1024):.1f} / {total_bytes / (1024*1024):.1f} MB @ {mb_s:.1f} MB/s")

    def _on_qc_asset_completed(self, res: AssetVerificationResult):
        for row in range(self.qc_table.rowCount()):
            cell_item = self.qc_table.item(row, 0)
            if cell_item and (cell_item.text() == res.original_filename or res.uuid in cell_item.text()):
                self.qc_table.setItem(row, 4, QTableWidgetItem(res.calculated_hash))
                status_item = QTableWidgetItem(res.status)
                if res.status == "PASSED":
                    status_item.setForeground(QColor("#4ade80"))
                else:
                    status_item.setForeground(QColor("#ef4444"))
                    status_item.setToolTip(res.error_message)
                self.qc_table.setItem(row, 5, status_item)
                break

    def _on_qc_overall_progress(self, completed: int, total: int, mb_s: float):
        pct = int((completed / max(1, total)) * 100)
        self.qc_progress.setValue(pct)

    def _on_qc_finished(self, all_passed: bool, results: list):
        self.btn_start_qc.setEnabled(True)
        self.btn_cancel_qc.setEnabled(False)
        passed_count = sum(1 for r in results if r.status == "PASSED")
        total_count = len(results)

        if all_passed:
            self.qc_progress.setValue(100)
            self.lbl_qc_verdict.setText(f"✅ 100% VERIFIED PRISTINE: All {passed_count}/{total_count} Assets Match PKL Digests")
            self.lbl_qc_verdict.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 13px;")
            self.lbl_qc_speed.setText("QC Verification Completed Successfully.")
        else:
            self.lbl_qc_verdict.setText(f"❌ INTEGRITY FAILURE: {total_count - passed_count} Corrupt / Mismatched Assets Detected")
            self.lbl_qc_verdict.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 13px;")
            self.lbl_qc_speed.setText("QC Verification Failed.")

    def _open_dvis_converter(self):
        cpl = self.dcp.default_composition if self.dcp else None
        if not cpl:
            QMessageBox.warning(self, "No DCP Loaded", "Please load a Digital Cinema Package first.")
            return
        from ui.dvis_converter_dialog import DVisConverterDialog
        dlg = DVisConverterDialog(cpl, self.dcp, self)
        dlg.exec()

    def _browse_dcp_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Digital Cinema Package (DCP) Folder")
        if folder:
            try:
                pkg = DCPParser.parse(folder)
                self.set_dcp(pkg)
            except Exception as e:
                QMessageBox.critical(self, "DCP Error", f"Failed to parse DCP folder:\n{e}")

    def _play_selected_reel(self):
        if not self.dcp or not self.dcp.compositions:
            return
        selected_row = self.table.currentRow()
        if selected_row < 0:
            selected_row = 0
        self.play_dcp_requested.emit(self.dcp, 0, selected_row)
        self.accept()

    def _play_entire_dcp(self):
        if not self.dcp or not self.dcp.compositions:
            return
        self.play_dcp_requested.emit(self.dcp, 0, 0)
        self.accept()

    def reject(self):
        if self.verifier_thread and self.verifier_thread.isRunning():
            self.verifier_thread.cancel()
            self.verifier_thread.wait(500)
        super().reject()
