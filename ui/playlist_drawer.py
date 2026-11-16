"""
BOOB Player - Playlist & Play Queue Drawer
Interactive queue management with drag-and-drop reordering, shuffle, repeat, and item deletion.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QInputDialog, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.playlist_manager import PlaylistManager, PlaylistItem


class PlaylistDrawer(QWidget):
    item_activated = pyqtSignal(int)
    item_added = pyqtSignal(str, str, str)  # uri, title, type

    def __init__(self, playlist_mgr: PlaylistManager, parent=None):
        super().__init__(parent)
        self.mgr = playlist_mgr
        self._init_ui()
        self.refresh_list()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header Title & Item Count
        header_row = QHBoxLayout()
        header = QLabel("📑 Play Queue")
        header.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 14px;")
        header_row.addWidget(header)

        self.count_lbl = QLabel("0 items")
        self.count_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        header_row.addWidget(self.count_lbl, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header_row)

        # List Widget
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

        # Transport Options (Shuffle, Repeat)
        opt_row = QHBoxLayout()
        opt_row.setSpacing(6)

        self.btn_repeat = QPushButton("🔁 Repeat: Off")
        self.btn_repeat.clicked.connect(self._cycle_repeat)
        opt_row.addWidget(self.btn_repeat)

        self.btn_shuffle = QPushButton("🔀 Shuffle: Off")
        self.btn_shuffle.clicked.connect(self._toggle_shuffle)
        opt_row.addWidget(self.btn_shuffle)

        layout.addLayout(opt_row)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_add = QPushButton("➕ Add File...")
        btn_add.clicked.connect(self._add_file_dialog)
        btn_row.addWidget(btn_add)

        btn_add_url = QPushButton("🌐 Add URL...")
        btn_add_url.clicked.connect(self._add_url_dialog)
        btn_row.addWidget(btn_add_url)

        btn_clear = QPushButton("🗑️ Clear")
        btn_clear.clicked.connect(self._clear_playlist)
        btn_row.addWidget(btn_clear)

        layout.addLayout(btn_row)

    def refresh_list(self):
        self.list_widget.clear()
        self.count_lbl.setText(f"{len(self.mgr.items)} items")

        for idx, item in enumerate(self.mgr.items):
            icon_tag = "🎬 " if item.item_type == "dcp" else ("🌐 " if item.item_type in ("url", "iptv") else "🎞️ ")
            prefix = "▶ " if idx == self.mgr.current_index else ""
            list_item = QListWidgetItem(f"{prefix}{icon_tag}{item.title}")
            if idx == self.mgr.current_index:
                list_item.setForeground(Qt.GlobalColor.cyan)
            self.list_widget.addItem(list_item)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        row = self.list_widget.row(item)
        if row >= 0:
            self.item_activated.emit(row)

    def _cycle_repeat(self):
        mode = self.mgr.cycle_repeat_mode()
        labels = {
            PlaylistManager.REPEAT_OFF: "🔁 Repeat: Off",
            PlaylistManager.REPEAT_ALL: "🔁 Repeat: All",
            PlaylistManager.REPEAT_ONE: "🔂 Repeat: One",
        }
        self.btn_repeat.setText(labels.get(mode, "🔁 Repeat: Off"))

    def _toggle_shuffle(self):
        enabled = self.mgr.toggle_shuffle()
        self.btn_shuffle.setText(f"🔀 Shuffle: {'On' if enabled else 'Off'}")
        if enabled:
            self.btn_shuffle.setStyleSheet("color: #00d2ff; font-weight: bold;")
        else:
            self.btn_shuffle.setStyleSheet("")

    def _add_file_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Media Files", "",
            "Media Files (*.mp4 *.mkv *.avi *.mov *.mxf *.webm *.flv *.ts *.mp3 *.flac *.wav);;All Files (*.*)"
        )
        for p in paths:
            self.item_added.emit(p, "", "file")
        self.refresh_list()

    def _add_url_dialog(self):
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Add Stream URL")
        dlg.setLabelText("Enter Network Stream / Video URL:")
        dlg.setMinimumWidth(520)
        dlg.resize(540, 160)
        if dlg.exec():
            url = dlg.textValue().strip()
            if url:
                self.item_added.emit(url, url, "url")
                self.refresh_list()

    def _clear_playlist(self):
        self.mgr.clear()
        self.refresh_list()
