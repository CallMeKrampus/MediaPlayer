"""
BOOB Player - Stereoscopic 3D Studio & Calibration Dialog
Provides complete controls for input 3D format selection, output viewing modes
(anaglyph, polarized, active shutter, eye isolators), and eye swapping.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QCheckBox, QPushButton, QGroupBox, QFrame, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.stereo3d_engine import Stereo3DEngine


class Stereo3DDialog(QDialog):
    """Studio control surface for Stereoscopic 3D presentation."""

    mode_changed = pyqtSignal(dict)

    def __init__(self, engine: Stereo3DEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Stereoscopic 3D Studio & Calibration")
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f1015;
                color: #e4e4e7;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QGroupBox {
                border: 1px solid #22242f;
                border-radius: 6px;
                margin-top: 14px;
                padding: 12px 10px 10px 10px;
                color: #d4d4d8;
                font-weight: 600;
                font-size: 11px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
            }
            QLabel {
                color: #a1a1aa;
                font-size: 11px;
            }
            QLabel.hintLabel {
                color: #71717a;
                font-size: 10px;
            }
            QComboBox {
                background-color: #15161f;
                color: #ffffff;
                border: 1px solid #272834;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 500;
                min-height: 24px;
            }
            QComboBox:focus {
                border-color: #4a4e63;
            }
            QComboBox QAbstractItemView {
                background-color: #15161f;
                color: #ffffff;
                selection-background-color: #272a38;
                border: 1px solid #22242f;
            }
            QCheckBox {
                color: #f4f4f5;
                font-size: 11px;
                font-weight: 600;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
            QPushButton {
                background: #1b1c26;
                color: #f4f4f5;
                border: 1px solid #2e303f;
                border-radius: 5px;
                padding: 5px 14px;
                font-size: 11px;
                font-weight: 600;
                min-height: 24px;
            }
            QPushButton:hover {
                background: #272938;
                border-color: #4a4e63;
                color: #ffffff;
            }
            QPushButton.primaryBtn {
                background: #272a38;
                border: 1px solid #52566b;
                color: #ffffff;
            }
            QPushButton.primaryBtn:hover {
                background: #333649;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Master Enable Toggle
        self.chk_enabled = QCheckBox("🥽 Enable Stereoscopic 3D Processing")
        self.chk_enabled.setChecked(self.engine.enabled)
        self.chk_enabled.toggled.connect(self._on_toggle_enabled)
        layout.addWidget(self.chk_enabled)

        # 2. Input 3D Encoding Format
        grp_in = QGroupBox("Source 3D Format / Encoding")
        grid_in = QGridLayout(grp_in)
        grid_in.setSpacing(6)

        grid_in.addWidget(QLabel("Input Geometry:"), 0, 0)
        self.cb_input = QComboBox()
        for k, name in Stereo3DEngine.INPUT_FORMATS.items():
            self.cb_input.addItem(name, k)
        # Select current
        idx_in = self.cb_input.findData(self.engine.input_format)
        if idx_in >= 0:
            self.cb_input.setCurrentIndex(idx_in)
        grid_in.addWidget(self.cb_input, 0, 1)

        self.lbl_auto_detected = QLabel(f"Detected: {Stere3D_format_name(self.engine.detected_input_format)}")
        self.lbl_auto_detected.setProperty("class", "hintLabel")
        grid_in.addWidget(self.lbl_auto_detected, 1, 1)

        layout.addWidget(grp_in)

        # 3. Output 3D Presentation Mode
        grp_out = QGroupBox("Display & Output Viewing Mode")
        grid_out = QGridLayout(grp_out)
        grid_out.setSpacing(6)

        grid_out.addWidget(QLabel("Presentation:"), 0, 0)
        self.cb_output = QComboBox()
        for k, name in Stereo3DEngine.OUTPUT_MODES.items():
            self.cb_output.addItem(name, k)
        idx_out = self.cb_output.findData(self.engine.output_mode)
        if idx_out >= 0:
            self.cb_output.setCurrentIndex(idx_out)
        grid_out.addWidget(self.cb_output, 0, 1)

        self.chk_swap = QCheckBox("Swap Left / Right Eyes (Invert Parallax)")
        self.chk_swap.setChecked(self.engine.swap_eyes)
        grid_out.addWidget(self.chk_swap, 1, 0, 1, 2)

        # Parallax / Horizontal Convergence Adjustment
        grid_out.addWidget(QLabel("Parallax Convergence:"), 2, 0)
        self.slider_parallax = QSlider(Qt.Orientation.Horizontal)
        self.slider_parallax.setRange(-60, 60)
        self.slider_parallax.setValue(getattr(self.engine, "parallax_offset", 0))
        self.slider_parallax.valueChanged.connect(self._on_parallax_changed)
        grid_out.addWidget(self.slider_parallax, 2, 1)

        p_row = QHBoxLayout()
        self.lbl_parallax_val = QLabel(f"{getattr(self.engine, 'parallax_offset', 0)} px (Screen Plane)")
        self.lbl_parallax_val.setProperty("class", "hintLabel")
        p_row.addWidget(self.lbl_parallax_val)
        p_row.addStretch(1)

        btn_reset_p = QPushButton("0 px")
        btn_reset_p.setToolTip("Reset convergence to zero parallax")
        btn_reset_p.setFixedSize(46, 22)
        btn_reset_p.clicked.connect(lambda: self.slider_parallax.setValue(0))
        p_row.addWidget(btn_reset_p)
        grid_out.addLayout(p_row, 3, 1)

        layout.addWidget(grp_out)

        # 4. Status Bar inside Dialog
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("""
            background: #0d0e12;
            color: #38bdf8;
            border: 1px solid #1e2433;
            border-radius: 4px;
            padding: 6px 10px;
            font-size: 11px;
            font-family: monospace;
        """)
        layout.addWidget(self.lbl_status)
        self._update_status_display()

        # 5. Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        btn_reset = QPushButton("Reset (2D)")
        btn_reset.clicked.connect(self._on_reset)
        btn_apply = QPushButton("Apply")
        btn_apply.setProperty("class", "primaryBtn")
        btn_apply.clicked.connect(self._on_apply)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        btn_box.addWidget(btn_reset)
        btn_box.addStretch(1)
        btn_box.addWidget(btn_apply)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def _on_toggle_enabled(self, checked: bool):
        self.engine.set_enabled(checked)
        self._update_status_display()
        self.mode_changed.emit(self.engine.get_status_summary())

    def _on_parallax_changed(self, val: int):
        if val > 0:
            txt = f"+{val} px (Convergence / In Front)"
        elif val < 0:
            txt = f"{val} px (Divergence / Behind Screen)"
        else:
            txt = "0 px (Screen Plane)"
        self.lbl_parallax_val.setText(txt)
        self.engine.set_parallax_offset(val)
        self.mode_changed.emit(self.engine.get_status_summary())

    def _on_apply(self):
        in_fmt = self.cb_input.currentData()
        out_mode = self.cb_output.currentData()
        swap = self.chk_swap.isChecked()
        enabled = self.chk_enabled.isChecked()
        parallax = self.slider_parallax.value()

        self.engine.input_format = in_fmt
        self.engine.output_mode = out_mode
        self.engine.swap_eyes = swap
        self.engine.enabled = enabled
        self.engine.parallax_offset = parallax
        self.engine.apply()
        self._update_status_display()
        self.mode_changed.emit(self.engine.get_status_summary())

    def _on_reset(self):
        self.engine.reset()
        self.chk_enabled.setChecked(False)
        self.chk_swap.setChecked(False)
        self.slider_parallax.setValue(0)
        idx_in = self.cb_input.findData("auto")
        if idx_in >= 0:
            self.cb_input.setCurrentIndex(idx_in)
        idx_out = self.cb_output.findData("anaglyph_arcd")
        if idx_out >= 0:
            self.cb_output.setCurrentIndex(idx_out)
        self._update_status_display()
        self.mode_changed.emit(self.engine.get_status_summary())

    def _update_status_display(self):
        summary = self.engine.get_status_summary()
        if not summary["enabled"]:
            self.lbl_status.setText("Status: Stereoscopic 3D Disabled (2D)")
        else:
            in_name = summary["input_label"]
            out_name = summary["output_label"]
            swap_str = " | Eyes Swapped" if summary["swap_eyes"] else ""
            self.lbl_status.setText(f"Status: {in_name} -> {out_name}{swap_str}")


def Stere3D_format_name(fmt_key: str) -> str:
    return Stereo3DEngine.INPUT_FORMATS.get(fmt_key, fmt_key)
