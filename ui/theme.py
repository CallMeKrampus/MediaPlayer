"""
BOOB Player - Studio Minimalist & Cyberpunk Dark Themes (QSS)
Includes:
- Minimalist Studio Dark (Default): Sleek neutral charcoal, 1px hairline borders,
  clean monochrome badges, subtle tactile controls, zero neon glare.
- Cyberpunk Dark: High-contrast obsidian, electric cyan and studio purple neon accents.
"""

MINIMALIST_THEME_QSS = """
/* Global Window & Widget Settings */
QWidget {
    background-color: #0d0e12;
    color: #f3f4f6;
    font-family: "Segoe UI", "SF Pro Display", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
    selection-background-color: #272833;
    selection-color: #ffffff;
}

QMainWindow {
    background-color: #0d0e12;
}

/* Menu Bar */
QMenuBar {
    background-color: #101115;
    color: #9ca3af;
    border-bottom: 1px solid #1c1d24;
    padding: 3px 6px;
    font-size: 12px;
}

QMenuBar::item {
    background-color: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #1b1c23;
    color: #ffffff;
}

QMenuBar::item:pressed {
    background-color: #232530;
    color: #ffffff;
}

/* Menus */
QMenu {
    background-color: #14151a;
    color: #f3f4f6;
    border: 1px solid #262732;
    border-radius: 8px;
    padding: 5px;
}

QMenu::item {
    padding: 6px 28px 6px 18px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #20222a;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #20222b;
    margin: 4px 8px;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
    margin-left: 6px;
}

/* Dock Widgets */
QDockWidget {
    color: #d1d5db;
    font-weight: 600;
    font-size: 12px;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}

QDockWidget::title {
    background-color: #121318;
    padding: 8px 12px;
    border-bottom: 1px solid #1f212a;
    text-align: left;
    color: #d1d5db;
}

QDockWidget > QWidget {
    background-color: #101115;
    border: 1px solid #1a1b22;
}

/* Push Buttons */
QPushButton {
    background-color: #17181f;
    color: #f3f4f6;
    border: 1px solid #282a35;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #22242e;
    border-color: #3b3e4d;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #14151b;
    border-color: #242631;
}

QPushButton:disabled {
    background-color: #101115;
    color: #4b5563;
    border-color: #191a20;
}

QPushButton:focus {
    outline: none;
}

/* Accent Buttons */
QPushButton#accentButton {
    background-color: #222530;
    color: #f3f4f6;
    border: 1px solid #3d4254;
    border-radius: 6px;
    font-weight: 600;
}

QPushButton#accentButton:hover {
    background-color: #2c303e;
    border-color: #4e546b;
    color: #ffffff;
}

QPushButton#cinemaButton {
    background-color: #1f212a;
    color: #f3f4f6;
    border: 1px solid #353846;
    border-radius: 6px;
    font-weight: 600;
}

QPushButton#cinemaButton:hover {
    background-color: #282b36;
    border-color: #444859;
    color: #ffffff;
}

/* Line Edits & Search Boxes */
QLineEdit {
    background-color: #131418;
    color: #f3f4f6;
    border: 1px solid #252630;
    border-radius: 6px;
    padding: 6px 10px;
}

QLineEdit:focus {
    border-color: #4b5563;
    background-color: #17181f;
}

/* Combo Boxes */
QComboBox {
    background-color: #14151a;
    color: #f3f4f6;
    border: 1px solid #252630;
    border-radius: 6px;
    padding: 5px 12px;
}

QComboBox:hover {
    border-color: #3b3e4d;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: none;
}

QComboBox QAbstractItemView {
    background-color: #14151a;
    color: #f3f4f6;
    border: 1px solid #252630;
    selection-background-color: #20222a;
    selection-color: #ffffff;
    padding: 4px;
}

/* Minimalist Sliders */
QSlider::groove:horizontal {
    height: 3px;
    background: #252732;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #e4e4e7;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #ffffff;
    border: 1px solid #4b5563;
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}

QSlider::handle:horizontal:hover {
    background: #ffffff;
    border-color: #9ca3af;
}

QSlider::handle:horizontal:pressed {
    background: #e5e7eb;
    border-color: #d1d5db;
}

QSlider::groove:vertical {
    width: 3px;
    background: #252732;
    border-radius: 2px;
}

QSlider::sub-page:vertical {
    background: #e4e4e7;
    border-radius: 2px;
}

QSlider::handle:vertical {
    background: #ffffff;
    border: 1px solid #4b5563;
    width: 12px;
    height: 12px;
    margin: 0 -5px;
    border-radius: 6px;
}

QSlider::handle:vertical:hover {
    background: #ffffff;
    border-color: #9ca3af;
}

QSlider::handle:vertical:pressed {
    background: #e5e7eb;
    border-color: #d1d5db;
}

/* List Widgets */
QListWidget {
    background-color: #0f1014;
    color: #f3f4f6;
    border: 1px solid #1c1d24;
    border-radius: 6px;
    padding: 4px;
}

QListWidget::item {
    padding: 8px 10px;
    border-radius: 5px;
    margin-bottom: 2px;
}

QListWidget::item:hover {
    background-color: #181920;
    color: #ffffff;
}

QListWidget::item:selected {
    background-color: #20222b;
    color: #ffffff;
    border-left: 2px solid #e4e4e7;
}

/* Tables */
QTableWidget, QTableView {
    background-color: #0f1014;
    color: #f3f4f6;
    gridline-color: #1a1b22;
    border: 1px solid #1c1d24;
    border-radius: 6px;
}

QHeaderView::section {
    background-color: #131419;
    color: #9ca3af;
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid #22232b;
    font-weight: 600;
}

QTableWidget::item:selected {
    background-color: #20222b;
    color: #ffffff;
}

/* Tab Widgets */
QTabWidget::pane {
    border: 1px solid #1c1d24;
    background-color: #101115;
    border-radius: 6px;
}

QTabBar::tab {
    background-color: #131419;
    color: #9ca3af;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
}

QTabBar::tab:selected {
    background-color: #1c1d24;
    color: #ffffff;
    border-bottom: 2px solid #e4e4e7;
}

QTabBar::tab:hover:!selected {
    background-color: #17181f;
    color: #f3f4f6;
}

/* Scroll Bars */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #252732;
    min-height: 25px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: #3c3f50;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: transparent;
    height: 6px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #252732;
    min-width: 25px;
    border-radius: 3px;
}

QScrollBar::handle:horizontal:hover {
    background: #3c3f50;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Status Bar */
QStatusBar {
    background-color: #0c0d10;
    color: #71717a;
    border-top: 1px solid #181920;
    font-size: 11px;
    padding: 2px 6px;
}

QStatusBar::item {
    border: none;
}

/* Tool Tips */
QToolTip {
    background-color: #16171d;
    color: #f3f4f6;
    border: 1px solid #2a2c38;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

/* Dialogs */
QDialog {
    background-color: #0f1014;
    border: 1px solid #242631;
    border-radius: 8px;
}

/* Message Boxes & Prompts */
QMessageBox {
    background-color: #0f1014;
    border: 1px solid #242631;
    border-radius: 8px;
    min-width: 480px;
    min-height: 140px;
}

QMessageBox QLabel {
    color: #e4e4e7;
    font-size: 11px;
    line-height: 1.4;
    padding: 6px;
    min-height: 48px;
}

QMessageBox QPushButton {
    min-width: 80px;
    min-height: 28px;
    font-size: 11px;
    font-weight: 500;
    padding: 4px 14px;
    border-radius: 5px;
    background: #1a1b24;
    border: 1px solid #2a2c38;
    color: #f4f4f5;
}

QMessageBox QPushButton:hover {
    background: #252734;
    border-color: #3f4255;
    color: #ffffff;
}

QInputDialog {
    background-color: #0f1014;
    border: 1px solid #242631;
    border-radius: 8px;
    min-width: 520px;
    min-height: 160px;
}

QInputDialog QLabel {
    color: #e4e4e7;
    font-size: 11.5px;
    font-weight: 500;
    min-height: 24px;
    padding-bottom: 4px;
}

QInputDialog QLineEdit {
    min-width: 460px;
    min-height: 32px;
    font-size: 12px;
    padding: 6px 10px;
    border: 1px solid #2e303d;
    border-radius: 5px;
    background-color: #15161e;
    color: #ffffff;
}

QInputDialog QPushButton {
    min-width: 80px;
    min-height: 28px;
    font-size: 11px;
    padding: 4px 14px;
    border-radius: 5px;
    background: #1a1b24;
    border: 1px solid #2a2c38;
    color: #f4f4f5;
}

QInputDialog QPushButton:hover {
    background: #252734;
    border-color: #3f4255;
    color: #ffffff;
}

/* Group Boxes */
QGroupBox {
    border: 1px solid #1f212a;
    border-radius: 6px;
    margin-top: 16px;
    padding-top: 10px;
    font-weight: 600;
    color: #9ca3af;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: #d1d5db;
}
"""

CYBERPUNK_THEME_QSS = """
/* Global Window & Widget Settings */
QWidget {
    background-color: #0c0d12;
    color: #e2e8f0;
    font-family: "Segoe UI", "SF Pro Display", -apple-system, Roboto, sans-serif;
    font-size: 13px;
    selection-background-color: #00d2ff;
    selection-color: #000000;
}

QMainWindow {
    background-color: #0c0d12;
}

/* Menu Bar */
QMenuBar {
    background-color: #10131a;
    color: #cbd5e1;
    border-bottom: 1px solid #1e232e;
    padding: 3px 6px;
    font-size: 12px;
}

QMenuBar::item {
    background-color: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #1e2430;
    color: #00d2ff;
}

QMenuBar::item:pressed {
    background-color: #272f3e;
    color: #ffffff;
}

/* Menus */
QMenu {
    background-color: #13161f;
    color: #e2e8f0;
    border: 1px solid #242936;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    padding: 6px 28px 6px 20px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #1f2533;
    color: #00d2ff;
}

QMenu::separator {
    height: 1px;
    background-color: #222633;
    margin: 4px 8px;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
    margin-left: 6px;
}

/* Dock Widgets */
QDockWidget {
    color: #00d2ff;
    font-weight: 600;
    font-size: 12px;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}

QDockWidget::title {
    background-color: #12151c;
    padding: 8px 12px;
    border-bottom: 1px solid #202531;
    text-align: left;
}

QDockWidget > QWidget {
    background-color: #101218;
    border: 1px solid #1a1e28;
}

/* Push Buttons */
QPushButton {
    background-color: #181c25;
    color: #e2e8f0;
    border: 1px solid #262c3b;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #202633;
    border-color: #00d2ff;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #141822;
    border-color: #00b4db;
}

QPushButton:disabled {
    background-color: #101319;
    color: #4b5563;
    border-color: #1b1f28;
}

QPushButton:focus {
    outline: none;
}

/* Accent Buttons */
QPushButton#accentButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b4db, stop:1 #0083b0);
    color: #ffffff;
    border: none;
    font-weight: 600;
}

QPushButton#accentButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d2ff, stop:1 #0099cc);
}

QPushButton#cinemaButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9333ea, stop:1 #7c3aed);
    color: #ffffff;
    border: none;
    font-weight: 600;
}

QPushButton#cinemaButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a855f7, stop:1 #8b5cf6);
}

/* Line Edits & Search Boxes */
QLineEdit {
    background-color: #13161f;
    color: #f1f5f9;
    border: 1px solid #242936;
    border-radius: 6px;
    padding: 6px 10px;
}

QLineEdit:focus {
    border-color: #00d2ff;
    background-color: #171b26;
}

/* Combo Boxes */
QComboBox {
    background-color: #141821;
    color: #e2e8f0;
    border: 1px solid #262c3b;
    border-radius: 6px;
    padding: 5px 12px;
}

QComboBox:hover {
    border-color: #00d2ff;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: none;
}

QComboBox QAbstractItemView {
    background-color: #141821;
    color: #e2e8f0;
    border: 1px solid #242936;
    selection-background-color: #1f2635;
    selection-color: #00d2ff;
    padding: 4px;
}

/* Sliders */
QSlider::groove:horizontal {
    height: 4px;
    background: #242937;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #0284c7;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #00d2ff;
    border: none;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #38bdf8;
}

QSlider::handle:horizontal:pressed {
    background: #00b4db;
}

QSlider::groove:vertical {
    width: 4px;
    background: #242937;
    border-radius: 2px;
}

QSlider::sub-page:vertical {
    background: #0284c7;
    border-radius: 2px;
}

QSlider::handle:vertical {
    background: #00d2ff;
    border: none;
    width: 14px;
    height: 14px;
    margin: 0 -5px;
    border-radius: 7px;
}

QSlider::handle:vertical:hover {
    background: #38bdf8;
}

QSlider::handle:vertical:pressed {
    background: #00b4db;
}

/* List Widgets */
QListWidget {
    background-color: #0f1218;
    color: #e2e8f0;
    border: 1px solid #1c202a;
    border-radius: 6px;
    padding: 4px;
}

QListWidget::item {
    padding: 8px 10px;
    border-radius: 5px;
    margin-bottom: 2px;
}

QListWidget::item:hover {
    background-color: #181d27;
    color: #00d2ff;
}

QListWidget::item:selected {
    background-color: #1e2637;
    color: #00d2ff;
    border-left: 3px solid #00d2ff;
}

/* Tables */
QTableWidget, QTableView {
    background-color: #0f1218;
    color: #e2e8f0;
    gridline-color: #1c202a;
    border: 1px solid #1c202a;
    border-radius: 6px;
}

QHeaderView::section {
    background-color: #141821;
    color: #94a3b8;
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid #242936;
    font-weight: 600;
}

QTableWidget::item:selected {
    background-color: #1e2637;
    color: #00d2ff;
}

/* Tab Widgets */
QTabWidget::pane {
    border: 1px solid #1e232e;
    background-color: #10131a;
    border-radius: 6px;
}

QTabBar::tab {
    background-color: #141720;
    color: #94a3b8;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
}

QTabBar::tab:selected {
    background-color: #1e2430;
    color: #00d2ff;
    border-bottom: 2px solid #00d2ff;
}

QTabBar::tab:hover:!selected {
    background-color: #181d26;
    color: #ffffff;
}

/* Scroll Bars */
QScrollBar:vertical {
    border: none;
    background: #0c0d12;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #252b39;
    min-height: 25px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #00d2ff;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #0c0d12;
    height: 8px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #252b39;
    min-width: 25px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: #00d2ff;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Status Bar */
QStatusBar {
    background-color: #0a0b0f;
    color: #64748b;
    border-top: 1px solid #181c25;
    font-size: 11px;
    padding: 2px 6px;
}

QStatusBar::item {
    border: none;
}

/* Tool Tips */
QToolTip {
    background-color: #181d26;
    color: #f1f5f9;
    border: 1px solid #00d2ff;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

/* Dialogs */
QDialog {
    background-color: #0e1017;
    border: 1px solid #262c3b;
    border-radius: 8px;
}

QMessageBox {
    background-color: #0e1017;
    border: 1px solid #262c3b;
    border-radius: 8px;
    min-width: 480px;
    min-height: 140px;
}

QMessageBox QLabel {
    color: #e2e8f0;
    font-size: 11px;
    line-height: 1.4;
    padding: 6px;
    min-height: 48px;
}

QMessageBox QPushButton {
    min-width: 80px;
    min-height: 28px;
    font-size: 11px;
    font-weight: 500;
    padding: 4px 14px;
    border-radius: 5px;
    background: #161b26;
    border: 1px solid #262c3b;
    color: #ffffff;
}

QMessageBox QPushButton:hover {
    background: #1e2433;
    border-color: #00d2ff;
    color: #ffffff;
}

QInputDialog {
    background-color: #0e1017;
    border: 1px solid #262c3b;
    border-radius: 8px;
    min-width: 520px;
    min-height: 160px;
}

QInputDialog QLabel {
    color: #e2e8f0;
    font-size: 11.5px;
    font-weight: 500;
    min-height: 24px;
    padding-bottom: 4px;
}

QInputDialog QLineEdit {
    min-width: 460px;
    min-height: 32px;
    font-size: 12px;
    padding: 6px 10px;
    border: 1px solid #262c3b;
    border-radius: 5px;
    background-color: #11141d;
    color: #ffffff;
}

QInputDialog QPushButton {
    min-width: 80px;
    min-height: 28px;
    font-size: 11px;
    padding: 4px 14px;
    border-radius: 5px;
    background: #161b26;
    border: 1px solid #262c3b;
    color: #ffffff;
}

QInputDialog QPushButton:hover {
    background: #1e2433;
    border-color: #00d2ff;
    color: #ffffff;
}

/* Group Boxes */
QGroupBox {
    border: 1px solid #202532;
    border-radius: 6px;
    margin-top: 16px;
    padding-top: 10px;
    font-weight: 600;
    color: #94a3b8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: #00d2ff;
}
"""

# Default application theme is Minimalist Studio Dark
DARK_THEME_QSS = MINIMALIST_THEME_QSS


def get_theme_qss(theme_name: str = "minimalist") -> str:
    """Return the stylesheet string for the requested theme ('minimalist' or 'cyberpunk')."""
    if theme_name and theme_name.lower().strip() in ("cyberpunk", "neon", "cyber"):
        return CYBERPUNK_THEME_QSS
    return MINIMALIST_THEME_QSS
