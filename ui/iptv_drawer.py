"""
BOOB Player - Live TV & IPTV Channel Drawer
Interactive channel navigation, categorization, live stream loading, and instant zapping.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog,
    QInputDialog, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.iptv_manager import IPTVManager, IPTVChannel


class IPTVChannelItemWidget(QWidget):
    """Custom list item widget displaying channel name, group tag, and resolution badge."""
    def __init__(self, channel: IPTVChannel, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # Name label
        name_lbl = QLabel(channel.name)
        name_lbl.setStyleSheet("color: #f1f5f9; font-weight: 600; font-size: 13px;")
        layout.addWidget(name_lbl, 1)

        # Group Pill
        group_lbl = QLabel(channel.group)
        group_lbl.setStyleSheet("""
            background: #1e2433;
            color: #94a3b8;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
        """)
        layout.addWidget(group_lbl)

        # Resolution Badge
        is_4k = "4k" in channel.resolution.lower() or "uhd" in channel.resolution.lower()
        badge_style = """
            background: #0284c7;
            color: #ffffff;
            font-size: 10px;
            font-weight: bold;
            padding: 2px 5px;
            border-radius: 3px;
        """ if not is_4k else """
            background: #a855f7;
            color: #ffffff;
            font-size: 10px;
            font-weight: bold;
            padding: 2px 5px;
            border-radius: 3px;
        """
        badge_lbl = QLabel(channel.resolution)
        badge_lbl.setStyleSheet(badge_style)
        layout.addWidget(badge_lbl)


class IPTVDrawer(QWidget):
    channel_selected = pyqtSignal(IPTVChannel)

    def __init__(self, iptv_manager: IPTVManager, parent=None):
        super().__init__(parent)
        self.manager = iptv_manager
        self._init_ui()
        self._populate_channels()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header Title
        title_row = QHBoxLayout()
        header = QLabel("📺 Live TV / IPTV Channels")
        header.setStyleSheet("color: #00d2ff; font-weight: bold; font-size: 14px;")
        title_row.addWidget(header)
        
        self.count_lbl = QLabel(f"{len(self.manager.channels)} channels")
        self.count_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        title_row.addWidget(self.count_lbl, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(title_row)

        # Search Bar
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search channels or categories...")
        self.search_box.textChanged.connect(self._filter_channels)
        layout.addWidget(self.search_box)

        # Category Selector
        self.category_combo = QComboBox()
        self.category_combo.addItem("All Categories")
        for g in self.manager.groups:
            self.category_combo.addItem(g)
        self.category_combo.currentTextChanged.connect(self._filter_channels)
        layout.addWidget(self.category_combo)

        # Channel List
        self.channel_list = QListWidget()
        self.channel_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.channel_list, 1)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.btn_load_file = QPushButton("📂 Open M3U...")
        self.btn_load_file.clicked.connect(self._load_file_dialog)
        btn_layout.addWidget(self.btn_load_file)

        self.btn_load_url = QPushButton("🌐 URL...")
        self.btn_load_url.clicked.connect(self._load_url_dialog)
        btn_layout.addWidget(self.btn_load_url)

        self.btn_add_custom = QPushButton("➕ Custom")
        self.btn_add_custom.clicked.connect(self._add_custom_dialog)
        btn_layout.addWidget(self.btn_add_custom)

        layout.addLayout(btn_layout)

    def _populate_channels(self, channels=None):
        self.channel_list.clear()
        target = channels if channels is not None else self.manager.channels
        self.count_lbl.setText(f"{len(target)} channels")

        for ch in target:
            item = QListWidgetItem(self.channel_list)
            widget = IPTVChannelItemWidget(ch)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self.channel_list.addItem(item)
            self.channel_list.setItemWidget(item, widget)

    def _filter_channels(self):
        query = self.search_box.text().strip()
        cat = self.category_combo.currentText()
        if cat == "All Categories":
            cat = "All"
        filtered = self.manager.filter_channels(query=query, group=cat)
        self._populate_channels(filtered)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        ch: IPTVChannel = item.data(Qt.ItemDataRole.UserRole)
        if ch:
            self.channel_selected.emit(ch)

    def _load_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open M3U/M3U8 Playlist", "", "Playlists (*.m3u *.m3u8);;All Files (*.*)"
        )
        if path:
            try:
                count = self.manager.load_m3u_file(path)
                self._refresh_categories()
                self._filter_channels()
                QMessageBox.information(self, "Success", f"Loaded {count} channels from playlist!")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load playlist: {e}")

    def _load_url_dialog(self):
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Open Remote M3U URL")
        dlg.setLabelText("Enter M3U/M3U8 Playlist URL:")
        dlg.setMinimumWidth(540)
        dlg.resize(560, 160)
        if dlg.exec():
            url = dlg.textValue().strip()
            if url:
                try:
                    count = self.manager.load_m3u_url(url)
                    self._refresh_categories()
                    self._filter_channels()
                    QMessageBox.information(self, "Success", f"Loaded {count} channels from remote playlist!")
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to download playlist: {e}")

    def _add_custom_dialog(self):
        dlg1 = QInputDialog(self)
        dlg1.setWindowTitle("Add Custom Stream")
        dlg1.setLabelText("Channel / Stream Name:")
        dlg1.setMinimumWidth(480)
        dlg1.resize(500, 150)
        if not dlg1.exec() or not dlg1.textValue().strip():
            return
        name = dlg1.textValue().strip()

        dlg2 = QInputDialog(self)
        dlg2.setWindowTitle("Add Custom Stream")
        dlg2.setLabelText("Live Stream URL (HLS/RTSP/RTMP/HTTP):")
        dlg2.setMinimumWidth(540)
        dlg2.resize(560, 160)
        if not dlg2.exec() or not dlg2.textValue().strip():
            return
        url = dlg2.textValue().strip()

        ch = self.manager.add_custom_channel(name.strip(), url.strip(), group="Custom")
        self._refresh_categories()
        self._filter_channels()
        self.channel_selected.emit(ch)

    def _refresh_categories(self):
        current = self.category_combo.currentText()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("All Categories")
        for g in self.manager.groups:
            self.category_combo.addItem(g)
        idx = self.category_combo.findText(current)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        self.category_combo.blockSignals(False)
