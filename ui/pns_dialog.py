"""
BOOB Player - Pan & Scan Edit Dialog
Allows precise numerical adjustment of Zoom, Aspect Scaling, Pan Offset,
Rotation Angle, and Mirroring.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QDoubleSpinBox,
    QSpinBox, QCheckBox, QPushButton, QGroupBox
)
from PyQt6.QtCore import Qt
from core.pns_controller import PnSController


class PnSEditDialog(QDialog):
    """Studio control surface for precise Pan & Scan parameters."""

    def __init__(self, pns_controller: PnSController, parent=None):
        super().__init__(parent)
        self.pns = pns_controller
        self.setWindowTitle("Pan & Scan (PnS) Frame Adjust")
        self.setMinimumWidth(440)
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
            QDoubleSpinBox, QSpinBox {
                background-color: #15161f;
                color: #ffffff;
                border: 1px solid #272834;
                border-radius: 5px;
                padding: 4px 8px;
                font-family: monospace;
                font-size: 11.5px;
                font-weight: 600;
                min-width: 85px;
                min-height: 24px;
            }
            QDoubleSpinBox:focus, QSpinBox:focus {
                border-color: #4a4e63;
            }
            QCheckBox {
                color: #d4d4d8;
                font-size: 11px;
            }
            QPushButton {
                background: #1b1c26;
                color: #f4f4f5;
                border: 1px solid #2e303f;
                border-radius: 5px;
                padding: 5px 14px;
                font-size: 11px;
                font-weight: 600;
                min-height: 26px;
            }
            QPushButton:hover {
                background: #272938;
                border-color: #4a4e63;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # 1. Size & Scale Group
        grp_scale = QGroupBox("Zoom & Aspect Scaling")
        grid_scale = QGridLayout(grp_scale)
        grid_scale.setSpacing(6)

        grid_scale.addWidget(QLabel("Zoom Factor:"), 0, 0)
        self.sp_zoom = QDoubleSpinBox()
        self.sp_zoom.setRange(0.2, 5.0)
        self.sp_zoom.setSingleStep(0.05)
        self.sp_zoom.setValue(self.pns.zoom)
        grid_scale.addWidget(self.sp_zoom, 0, 1)

        grid_scale.addWidget(QLabel("Width Scale (X):"), 1, 0)
        self.sp_scale_x = QDoubleSpinBox()
        self.sp_scale_x.setRange(0.2, 5.0)
        self.sp_scale_x.setSingleStep(0.02)
        self.sp_scale_x.setValue(self.pns.scale_x)
        grid_scale.addWidget(self.sp_scale_x, 1, 1)

        grid_scale.addWidget(QLabel("Height Scale (Y):"), 2, 0)
        self.sp_scale_y = QDoubleSpinBox()
        self.sp_scale_y.setRange(0.2, 5.0)
        self.sp_scale_y.setSingleStep(0.02)
        self.sp_scale_y.setValue(self.pns.scale_y)
        grid_scale.addWidget(self.sp_scale_y, 2, 1)

        layout.addWidget(grp_scale)

        # 2. Position & Pan Group
        grp_pan = QGroupBox("Pan Position & Orientation")
        grid_pan = QGridLayout(grp_pan)
        grid_pan.setSpacing(6)

        grid_pan.addWidget(QLabel("Pan X (Horiz):"), 0, 0)
        self.sp_pan_x = QDoubleSpinBox()
        self.sp_pan_x.setRange(-1.0, 1.0)
        self.sp_pan_x.setSingleStep(0.01)
        self.sp_pan_x.setValue(self.pns.pan_x)
        grid_pan.addWidget(self.sp_pan_x, 0, 1)

        grid_pan.addWidget(QLabel("Pan Y (Vert):"), 1, 0)
        self.sp_pan_y = QDoubleSpinBox()
        self.sp_pan_y.setRange(-1.0, 1.0)
        self.sp_pan_y.setSingleStep(0.01)
        self.sp_pan_y.setValue(self.pns.pan_y)
        grid_pan.addWidget(self.sp_pan_y, 1, 1)

        grid_pan.addWidget(QLabel("Rotation Angle:"), 2, 0)
        self.sp_rot = QSpinBox()
        self.sp_rot.setRange(0, 359)
        self.sp_rot.setSingleStep(90)
        self.sp_rot.setValue(self.pns.rotation)
        grid_pan.addWidget(self.sp_rot, 2, 1)

        self.chk_flip_h = QCheckBox("Mirror / Horizontal Flip")
        self.chk_flip_h.setChecked(self.pns.flip_h)
        grid_pan.addWidget(self.chk_flip_h, 3, 0, 1, 2)

        self.chk_flip_v = QCheckBox("Flip Vertically")
        self.chk_flip_v.setChecked(self.pns.flip_v)
        grid_pan.addWidget(self.chk_flip_v, 4, 0, 1, 2)

        layout.addWidget(grp_pan)

        # 3. Action buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        btn_reset = QPushButton("Reset to 100%")
        btn_reset.clicked.connect(self._on_reset)
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._on_apply)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        btn_box.addWidget(btn_reset)
        btn_box.addStretch(1)
        btn_box.addWidget(btn_apply)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def _on_apply(self):
        state = {
            "zoom": self.sp_zoom.value(),
            "scale_x": self.sp_scale_x.value(),
            "scale_y": self.sp_scale_y.value(),
            "pan_x": self.sp_pan_x.value(),
            "pan_y": self.sp_pan_y.value(),
            "rotation": self.sp_rot.value(),
            "flip_h": self.chk_flip_h.isChecked(),
            "flip_v": self.chk_flip_v.isChecked(),
        }
        self.pns.set_state(state)

    def _on_reset(self):
        self.pns.reset()
        self.sp_zoom.setValue(1.0)
        self.sp_scale_x.setValue(1.0)
        self.sp_scale_y.setValue(1.0)
        self.sp_pan_x.setValue(0.0)
        self.sp_pan_y.setValue(0.0)
        self.sp_rot.setValue(0)
        self.chk_flip_h.setChecked(False)
        self.chk_flip_v.setChecked(False)
