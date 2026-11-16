"""
BOOB Player - Color Science & Tonemapping Lab
Symmetrical, studio-grade control surface for DCI-XYZ, Dolby Vision Profile 5,
HDR10 to SDR Rec.709, and precision color science grading.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSlider, QGroupBox, QGridLayout, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.tonemap_engine import TonemapEngine
from ui.icons import draw_reset_icon


class TonemapControlDrawer(QWidget):
    preset_changed = pyqtSignal(str)

    PRESET_ORDER = [
        "auto", "passthrough",
        "dvis_dcp_sdr", "dvis_dcp_hdr10",
        "dci_xyz_srgb", "dv_p5_sdr",
        "dv_p5_hdr10", "dv_p5_hlg",
        "dv_p20_rpu_sdr", "dv_p20_rpu_hdr",
        "hlg_sdr",
        "hdr10_sdr", "hdr10plus_sdr",
        "hdr10_hdr", "hdr10plus_hdr",
        "spline_sdr", "filmic_hable",
        "mobius_sdr", "reinhard_sdr",
    ]
    PRESET_TITLES = {
        "auto": "🤖 Auto Detect",
        "passthrough": "⚡ Pass-Through",
        "dvis_dcp_sdr": "💎 DVis (DCP) → SDR",
        "dvis_dcp_hdr10": "💎 DVis (DCP) → HDR10",
        "dci_xyz_srgb": "🎬 DCI-XYZ → BT.709",
        "dv_p5_sdr": "💎 DV P5 → BT.709",
        "dv_p5_hdr10": "💎 DV P5 → HDR10",
        "dv_p5_hlg": "💎 DV P5 → HLG",
        "dv_p20_rpu_sdr": "🧬 DV P20 → SDR (RPU L8)",
        "dv_p20_rpu_hdr": "🧬 DV P20 → HDR10/10+ (RPU)",
        "hlg_sdr": "⚡ HLG → BT.709 (Punch)",
        "hdr10_sdr": "☀️ HDR10 → BT.709",
        "hdr10plus_sdr": "🌟 HDR10+ → BT.709",
        "hdr10_hdr": "🖥️ HDR10 → HDR Display",
        "hdr10plus_hdr": "🖥️ HDR10+ → HDR Display",
        "spline_sdr": "🌊 Spline → BT.709",
        "filmic_hable": "🎞️ Hable → BT.709",
        "mobius_sdr": "🌀 Mobius → BT.709",
        "reinhard_sdr": "📷 Reinhard → BT.709",
    }

    def __init__(self, tonemap_engine: TonemapEngine, parent=None):
        super().__init__(parent)
        self.engine = tonemap_engine
        self.setMinimumWidth(390)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #0f1015;
                color: #e4e4e7;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QGroupBox {
                border: 1px solid #22242f;
                border-radius: 6px;
                margin-top: 14px;
                padding: 12px 10px 10px 10px;
                background-color: #121319;
                font-weight: 600;
                font-size: 11px;
                color: #d4d4d8;
                letter-spacing: 0.3px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
                color: #d4d4d8;
            }
            QPushButton.presetCard {
                background: #171821;
                border: 1px solid #262734;
                border-radius: 5px;
                color: #d4d4d8;
                font-size: 11px;
                font-weight: 500;
                padding: 8px 6px;
                text-align: center;
            }
            QPushButton.presetCard:hover {
                background: #20222d;
                border: 1px solid #3c3f50;
                color: #ffffff;
            }
            QPushButton.presetCard:pressed {
                background: #2b2e3c;
                color: #ffffff;
            }
            QPushButton.presetActive {
                background: #272a38;
                border: 1px solid #52566b;
                color: #ffffff;
                font-weight: 600;
            }
            QComboBox {
                background-color: #15161f;
                color: #f4f4f5;
                border: 1px solid #262734;
                border-radius: 5px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 500;
            }
            QComboBox:hover {
                border-color: #3f4255;
            }
            QComboBox QAbstractItemView {
                background-color: #15161f;
                color: #f4f4f5;
                selection-background-color: #272a38;
                border: 1px solid #262734;
            }
            QSlider::groove:horizontal {
                height: 3px;
                background: #222430;
                border-radius: 1.5px;
            }
            QSlider::sub-page:horizontal {
                background: #474d61;
                border-radius: 1.5px;
            }
            QSlider::handle:horizontal {
                background: #e4e4e7;
                border: 1px solid #1c1d25;
                width: 12px;
                height: 12px;
                margin: -4.5px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
            QPushButton.btnResetSlider {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 1px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton.btnResetSlider:hover {
                background: #1e202a;
                border: 1px solid #353849;
            }
            QPushButton.btnResetSlider:pressed {
                background: #2a2c3a;
            }
            QLabel.valBadge {
                background: #161720;
                border: 1px solid #252633;
                border-radius: 4px;
                color: #e4e4e7;
                font-family: monospace;
                font-size: 10.5px;
                font-weight: 600;
                padding: 2px 5px;
                min-width: 34px;
                qproperty-alignment: AlignCenter;
            }
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        container.setObjectName("tonemapContainer")
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # 1. Header Bar
        header_bar = QHBoxLayout()
        header_icon = QLabel("🎨")
        header_icon.setStyleSheet("font-size: 14px;")
        header_title = QLabel("COLOR SCIENCE & TONEMAPPING")
        header_title.setStyleSheet("color: #e4e4e7; font-weight: 600; font-size: 12px; letter-spacing: 0.5px;")
        header_bar.addWidget(header_icon)
        header_bar.addWidget(header_title)
        header_bar.addStretch(1)
        
        badge_hdr = QLabel("16-BIT STUDIO")
        badge_hdr.setStyleSheet("""
            background: #171822;
            color: #a1a1aa;
            border: 1px solid #272836;
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 9px;
            font-weight: 600;
            letter-spacing: 0.5px;
        """)
        header_bar.addWidget(badge_hdr)
        main_layout.addLayout(header_bar)

        # 2. Master Presets Grid - every preset the engine supports, 2 columns
        preset_group = QGroupBox("Master Pipeline Presets")
        preset_grid = QGridLayout(preset_group)
        preset_grid.setContentsMargins(10, 14, 10, 10)
        preset_grid.setHorizontalSpacing(10)
        preset_grid.setVerticalSpacing(8)

        self.preset_buttons = {}
        for idx, key in enumerate(self.PRESET_ORDER):
            if key not in self.engine.PRESETS:
                continue
            title = self.PRESET_TITLES.get(key, key)
            btn = QPushButton(title)
            btn.setProperty("class", "presetCard")
            btn.setToolTip(self.engine.PRESETS[key])
            btn.clicked.connect(lambda _=False, k=key: self._select_preset(k))
            preset_grid.addWidget(btn, idx // 2, idx % 2)
            self.preset_buttons[key] = btn
        # Any preset added to the engine later still shows up
        extra = [k for k in self.engine.PRESETS if k not in self.preset_buttons]
        for k in extra:
            idx = len(self.preset_buttons)
            btn = QPushButton(self.engine.PRESETS[k])
            btn.setProperty("class", "presetCard")
            btn.clicked.connect(lambda _=False, kk=k: self._select_preset(kk))
            preset_grid.addWidget(btn, idx // 2, idx % 2)
            self.preset_buttons[k] = btn

        # Backwards-compatible attribute aliases
        self.btn_dvis_sdr = self.preset_buttons.get("dvis_dcp_sdr")
        self.btn_dvis_hdr10 = self.preset_buttons.get("dvis_dcp_hdr10")
        self.btn_dci = self.preset_buttons.get("dci_xyz_srgb")
        self.btn_dv = self.preset_buttons.get("dv_p5_sdr")
        self.btn_dv_hdr10 = self.preset_buttons.get("dv_p5_hdr10")
        self.btn_dv_hlg = self.preset_buttons.get("dv_p5_hlg")
        self.btn_dv_p20_rpu_sdr = self.preset_buttons.get("dv_p20_rpu_sdr")
        self.btn_dv_p20_rpu_hdr = self.preset_buttons.get("dv_p20_rpu_hdr")
        self.btn_dv_p20 = self.btn_dv_p20_rpu_sdr
        self.btn_dv_p20_hdr10 = self.btn_dv_p20_rpu_hdr
        self.btn_hdr10 = self.preset_buttons.get("hdr10_sdr")
        self.btn_hable = self.preset_buttons.get("filmic_hable")
        self.btn_spline = self.preset_buttons.get("spline_sdr")
        self.btn_passthrough = self.preset_buttons.get("passthrough")

        main_layout.addWidget(preset_group)

        # 3. Symmetrical 2-Column Engine Parameters
        params_group = QGroupBox("Tonemapping Engine")
        params_grid = QGridLayout(params_group)
        params_grid.setContentsMargins(10, 14, 10, 10)
        params_grid.setHorizontalSpacing(12)
        params_grid.setVerticalSpacing(8)

        lbl_algo = QLabel("Algorithm:")
        lbl_algo.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        self.combo_algo = QComboBox()
        for key, label in self.engine.ALGORITHMS:
            self.combo_algo.addItem(label, key)
        self.combo_algo.currentIndexChanged.connect(self._on_algo_changed)

        params_grid.addWidget(lbl_algo, 0, 0)
        params_grid.addWidget(self.combo_algo, 1, 0)

        lbl_peak = QLabel("Target Peak (Nits):")
        lbl_peak.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        self.combo_peak = QComboBox()
        for nits, label in self.engine.TARGET_PEAKS:
            self.combo_peak.addItem(label, nits)
        self.combo_peak.setCurrentIndex(1)  # 100 nits default
        self.combo_peak.currentIndexChanged.connect(self._on_peak_changed)

        params_grid.addWidget(lbl_peak, 0, 1)
        params_grid.addWidget(self.combo_peak, 1, 1)

        main_layout.addWidget(params_group)

        # 4. Symmetrical Precision Color Grader
        adj_group = QGroupBox("Precision Studio Grader")
        adj_grid = QGridLayout(adj_group)
        adj_grid.setContentsMargins(10, 14, 10, 10)
        adj_grid.setHorizontalSpacing(8)
        adj_grid.setVerticalSpacing(8)

        # Allow sliders to expand symmetrically
        adj_grid.setColumnStretch(1, 1)
        adj_grid.setColumnStretch(5, 1)

        # Left Column: Brightness, Contrast, Saturation
        adj_grid.addWidget(self._make_label("Brightness:"), 0, 0)
        self.slider_bright = self._create_adj_slider(-100, 100, -6)
        self.lbl_bright = self._make_val_badge("-6")
        self.btn_rst_bright = self._create_reset_btn(lambda: self._reset_single_slider(self.slider_bright, 0))
        self.slider_bright.valueChanged.connect(lambda v: self._on_adj_slider(self.lbl_bright, v))
        adj_grid.addWidget(self.slider_bright, 0, 1)
        adj_grid.addWidget(self.lbl_bright, 0, 2)
        adj_grid.addWidget(self.btn_rst_bright, 0, 3)

        adj_grid.addWidget(self._make_label("Contrast:"), 1, 0)
        self.slider_contrast = self._create_adj_slider(-100, 100, 0)
        self.lbl_contrast = self._make_val_badge("0")
        self.btn_rst_contrast = self._create_reset_btn(lambda: self._reset_single_slider(self.slider_contrast, 0))
        self.slider_contrast.valueChanged.connect(lambda v: self._on_adj_slider(self.lbl_contrast, v))
        adj_grid.addWidget(self.slider_contrast, 1, 1)
        adj_grid.addWidget(self.lbl_contrast, 1, 2)
        adj_grid.addWidget(self.btn_rst_contrast, 1, 3)

        adj_grid.addWidget(self._make_label("Saturation:"), 2, 0)
        self.slider_sat = self._create_adj_slider(-100, 100, 0)
        self.lbl_sat = self._make_val_badge("0")
        self.btn_rst_sat = self._create_reset_btn(lambda: self._reset_single_slider(self.slider_sat, 0))
        self.slider_sat.valueChanged.connect(lambda v: self._on_adj_slider(self.lbl_sat, v))
        adj_grid.addWidget(self.slider_sat, 2, 1)
        adj_grid.addWidget(self.lbl_sat, 2, 2)
        adj_grid.addWidget(self.btn_rst_sat, 2, 3)

        # Right Column: Gamma, Hue, Reset All
        adj_grid.addWidget(self._make_label("Gamma:"), 0, 4)
        self.slider_gamma = self._create_adj_slider(-100, 100, -5)
        self.lbl_gamma = self._make_val_badge("-5")
        self.btn_rst_gamma = self._create_reset_btn(lambda: self._reset_single_slider(self.slider_gamma, 0))
        self.slider_gamma.valueChanged.connect(lambda v: self._on_adj_slider(self.lbl_gamma, v))
        adj_grid.addWidget(self.slider_gamma, 0, 5)
        adj_grid.addWidget(self.lbl_gamma, 0, 6)
        adj_grid.addWidget(self.btn_rst_gamma, 0, 7)

        adj_grid.addWidget(self._make_label("Hue:"), 1, 4)
        self.slider_hue = self._create_adj_slider(-180, 180, 0)
        self.lbl_hue = self._make_val_badge("0°")
        self.btn_rst_hue = self._create_reset_btn(lambda: self._reset_single_slider(self.slider_hue, 0))
        self.slider_hue.valueChanged.connect(lambda v: self._on_adj_slider(self.lbl_hue, v, "°"))
        adj_grid.addWidget(self.slider_hue, 1, 5)
        adj_grid.addWidget(self.lbl_hue, 1, 6)
        adj_grid.addWidget(self.btn_rst_hue, 1, 7)

        btn_reset = QPushButton("Reset All to 0")
        btn_reset.setIcon(draw_reset_icon(14))
        btn_reset.setToolTip("Reset all grader sliders back to 0")
        btn_reset.setFixedHeight(24)
        btn_reset.setStyleSheet("""
            QPushButton {
                background: #171822;
                border: 1px solid #262735;
                border-radius: 5px;
                color: #a1a1aa;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: #20222e;
                border-color: #3b3e50;
                color: #ffffff;
            }
        """)
        btn_reset.clicked.connect(self._reset_adjustments)
        adj_grid.addWidget(btn_reset, 2, 4, 1, 4)

        main_layout.addWidget(adj_group)

        # 5. Live Color Telemetry Console Card
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet("""
            QFrame {
                background-color: #121319;
                border: 1px solid #22242f;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        status_layout = QVBoxLayout(self.status_frame)
        status_layout.setContentsMargins(6, 6, 6, 6)
        status_layout.setSpacing(4)

        top_status_row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #22c55e; font-size: 11px;")
        self.status_lbl = QLabel("Mode: DCI-XYZ (CIE 1931) → Rec.709")
        self.status_lbl.setStyleSheet("color: #e4e4e7; font-size: 11px; font-weight: 600;")
        top_status_row.addWidget(self.status_dot)
        top_status_row.addWidget(self.status_lbl)
        top_status_row.addStretch(1)
        status_layout.addLayout(top_status_row)

        self.details_lbl = QLabel("Primaries: BT.709 | TRC: Gamma 2.2 | Algorithm: Clip | Peak: 100 nits")
        self.details_lbl.setStyleSheet("color: #71717a; font-size: 10px; font-family: monospace;")
        status_layout.addWidget(self.details_lbl)

        main_layout.addWidget(self.status_frame)
        main_layout.addStretch(1)

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

        self._update_status_display()

    @staticmethod
    def _make_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #a1a1aa; font-size: 10.5px; font-weight: 500;")
        return lbl

    @staticmethod
    def _make_val_badge(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", "valBadge")
        return lbl

    def _create_reset_btn(self, on_click) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("class", "btnResetSlider")
        btn.setIcon(draw_reset_icon(14))
        btn.setToolTip("Reset to 0")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(22, 22)
        btn.clicked.connect(on_click)
        return btn

    def _reset_single_slider(self, slider: QSlider, target_val: int = 0):
        if slider.value() == target_val:
            self._apply_color_adjustments()
        else:
            slider.setValue(target_val)

    def _create_adj_slider(self, min_val: int, max_val: int, default: int) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(min_val, max_val)
        s.setValue(default)
        return s

    def _on_adj_slider(self, label: QLabel, val: int, suffix: str = ""):
        label.setText(f"{val}{suffix}")
        self._apply_color_adjustments()

    def _apply_color_adjustments(self):
        self.engine.set_adjustments(
            brightness=self.slider_bright.value(),
            contrast=self.slider_contrast.value(),
            saturation=self.slider_sat.value(),
            gamma=self.slider_gamma.value(),
            hue=self.slider_hue.value()
        )

    def _reset_adjustments(self):
        self.slider_bright.setValue(0)
        self.slider_contrast.setValue(0)
        self.slider_sat.setValue(0)
        self.slider_gamma.setValue(0)
        self.slider_hue.setValue(0)
        self._apply_color_adjustments()

    def _select_preset(self, preset_key: str):
        self.engine.apply_preset(preset_key)
        self.preset_changed.emit(preset_key)
        self._update_status_display()

    def _on_algo_changed(self):
        algo = self.combo_algo.currentData()
        if algo:
            self.engine.set_algorithm(algo)
            self._update_status_display()

    def _on_peak_changed(self):
        peak = self.combo_peak.currentData()
        if peak:
            self.engine.set_target_peak(int(peak))
            self._update_status_display()

    def refresh_from_engine(self):
        self._update_status_display()

    def _update_status_display(self):
        info = self.engine.get_status_summary()
        self.status_lbl.setText(f"Mode: {info['preset_label']}")
        shader_txt = " | Shader: Active" if info.get("shader_active") else ""
        lut_txt = f" | 3D LUT: Active" if info.get("lut_enabled") else ""
        hdr_txt = " | HDR Direct" if info.get("hdr_passthrough") else ""
        rpu_trims = info.get("rpu_trims") or {}
        rpu_txt = ""
        if info.get("preset") in ("dv_p20_rpu_sdr", "dv_p20_rpu_hdr") and rpu_trims:
            rpu_txt = (
                f" | RPU L1:{rpu_trims.get('l1_max_pq', 2081)} "
                f"L3:{rpu_trims.get('l3_max_pq_offset', 0):+d} "
                f"L8:S={rpu_trims.get('slope_gain', 1.0):.2f}/P={rpu_trims.get('power_gain', 1.0):.2f}"
            )
        self.details_lbl.setText(
            f"Output: {info.get('output_label', info['target_prim'])} | "
            f"Tone curve: {info.get('curve_label', info['algorithm'])} | "
            f"Peak: {info.get('target_peak', '100 nits')}{rpu_txt}{shader_txt}{lut_txt}{hdr_txt}"
        )

        if hasattr(self, "combo_algo"):
            idx = self.combo_algo.findData(info.get("algorithm"))
            if idx >= 0:
                self.combo_algo.blockSignals(True)
                self.combo_algo.setCurrentIndex(idx)
                self.combo_algo.blockSignals(False)
        if hasattr(self, "combo_peak"):
            cur_peak = getattr(self.engine, "target_peak", 100)
            idx = self.combo_peak.findData(cur_peak)
            self.combo_peak.blockSignals(True)
            if idx >= 0:
                self.combo_peak.setCurrentIndex(idx)
            elif cur_peak:
                # Dynamic peak from RPU L8 trim not in static presets
                label = f"{cur_peak} nits (Dynamic RPU)"
                # If already inserted, update its text
                if self.combo_peak.itemData(0) == cur_peak:
                    self.combo_peak.setItemText(0, label)
                    self.combo_peak.setCurrentIndex(0)
                else:
                    self.combo_peak.insertItem(0, label, cur_peak)
                    self.combo_peak.setCurrentIndex(0)
            self.combo_peak.blockSignals(False)

        # Highlight active preset card
        current = info.get("preset", "") or info.get("preset_key", "")
        preset_buttons = getattr(self, "preset_buttons", {})
        for k, btn in preset_buttons.items():
            if k == current:
                btn.setStyleSheet("""
                    QPushButton {
                        background: #272a38;
                        border: 1px solid #52566b;
                        color: #ffffff;
                        font-weight: 600;
                    }
                """)
            else:
                btn.setStyleSheet("")

        adjs = info.get("adjustments", {})
        if hasattr(self, "slider_bright"):
            self.slider_bright.blockSignals(True)
            self.slider_bright.setValue(adjs.get("brightness", 0))
            self.lbl_bright.setText(str(adjs.get("brightness", 0)))
            self.slider_bright.blockSignals(False)
        if hasattr(self, "slider_contrast"):
            self.slider_contrast.blockSignals(True)
            self.slider_contrast.setValue(adjs.get("contrast", 0))
            self.lbl_contrast.setText(str(adjs.get("contrast", 0)))
            self.slider_contrast.blockSignals(False)
        if hasattr(self, "slider_sat"):
            self.slider_sat.blockSignals(True)
            self.slider_sat.setValue(adjs.get("saturation", 0))
            self.lbl_sat.setText(str(adjs.get("saturation", 0)))
            self.slider_sat.blockSignals(False)
        if hasattr(self, "slider_gamma"):
            self.slider_gamma.blockSignals(True)
            self.slider_gamma.setValue(adjs.get("gamma", 0))
            self.lbl_gamma.setText(str(adjs.get("gamma", 0)))
            self.slider_gamma.blockSignals(False)
        if hasattr(self, "slider_hue"):
            self.slider_hue.blockSignals(True)
            self.slider_hue.setValue(adjs.get("hue", 0))
            self.lbl_hue.setText(f"{adjs.get('hue', 0)}°")
            self.slider_hue.blockSignals(False)
