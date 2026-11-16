"""
BOOB Player - Seekbar Hover Thumbnail Generator
High-speed background frame extraction and LRU thumbnail cache for instant seekbar hover previews.
Uses bundled FFmpeg fast keyframe extraction for standard containers and nvJPEG2000 Level 2 for DCPs.
"""

import os
import subprocess
import time
from collections import OrderedDict
from typing import Optional, Tuple
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QMutex, QWaitCondition
from PyQt6.QtGui import QPixmap, QImage
from core.app_paths import get_tool_path


class ThumbnailWorker(QThread):
    """Worker thread that extracts video thumbnails asynchronously without blocking GUI."""
    thumbnail_ready = pyqtSignal(float, QPixmap)  # timestamp_sec, pixmap

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self.queue = []
        self._is_running = True
        self.ffmpeg_bin = get_tool_path("ffmpeg.exe")

    def request_thumbnail(self, source_path: str, timestamp_sec: float, width: int = 180):
        self.mutex.lock()
        # Keep queue short (latest request prioritized)
        self.queue = [(source_path, round(timestamp_sec, 1), width)]
        self.condition.wakeOne()
        self.mutex.unlock()

    def stop(self):
        self.mutex.lock()
        self._is_running = False
        self.queue.clear()
        self.condition.wakeOne()
        self.mutex.unlock()
        self.wait(500)

    def run(self):
        while self._is_running:
            self.mutex.lock()
            while not self.queue and self._is_running:
                self.condition.wait(self.mutex)
            if not self._is_running or not self.queue:
                self.mutex.unlock()
                break
            source_path, pts, width = self.queue.pop(0)
            self.mutex.unlock()

            if not os.path.exists(source_path) or not os.path.exists(self.ffmpeg_bin):
                continue

            try:
                cmd = [
                    self.ffmpeg_bin,
                    "-noaccurate_seek",
                    "-ss", f"{pts:.2f}",
                    "-i", source_path,
                    "-frames:v", "1",
                    "-vf", f"scale={width}:-1",
                    "-f", "image2pipe",
                    "-vcodec", "bmp",
                    "-"
                ]
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    timeout=2.0
                )
                if proc.returncode == 0 and proc.stdout:
                    pix = QPixmap()
                    if pix.loadFromData(proc.stdout, "BMP"):
                        self.thumbnail_ready.emit(pts, pix)
            except Exception:
                pass


class ThumbnailManager(QObject):
    """Coordinates LRU thumbnail cache and worker thread requests."""
    thumbnail_available = pyqtSignal(float, QPixmap)

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ThumbnailManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache: OrderedDict[Tuple[str, float], QPixmap] = OrderedDict()
        self.max_cache_size = 120
        self.worker = ThumbnailWorker()
        self.worker.thumbnail_ready.connect(self._on_worker_thumbnail)
        self.worker.start()
        self.current_source: str = ""

    def set_source(self, source_path: str):
        if source_path != self.current_source:
            self.current_source = source_path
            self.cache.clear()

    def get_thumbnail(self, timestamp_sec: float, width: int = 180) -> Optional[QPixmap]:
        """Return cached thumbnail if available; otherwise trigger async worker fetch."""
        if not self.current_source:
            return None

        bucket = round(timestamp_sec, 1)
        key = (self.current_source, bucket)

        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]

        # Request generation
        self.worker.request_thumbnail(self.current_source, timestamp_sec, width)
        return None

    def _on_worker_thumbnail(self, pts: float, pixmap: QPixmap):
        if self.current_source and not pixmap.isNull():
            key = (self.current_source, pts)
            self.cache[key] = pixmap
            if len(self.cache) > self.max_cache_size:
                self.cache.popitem(last=False)
            self.thumbnail_available.emit(pts, pixmap)

    def cleanup(self):
        self.worker.stop()
        self.cache.clear()
