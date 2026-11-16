"""
BOOB Player - Playlist & Queue Manager
Supports individual video/audio files, network URLs, IPTV channels, and multi-reel DCP packages.
"""

import os
import random
from dataclasses import dataclass
from typing import List, Optional, Callable


@dataclass
class PlaylistItem:
    title: str
    uri: str
    item_type: str = "file"  # "file", "url", "dcp", "iptv"
    duration: float = 0.0
    extra_data: Optional[dict] = None


class PlaylistManager:
    REPEAT_OFF = 0
    REPEAT_ALL = 1
    REPEAT_ONE = 2

    def __init__(self):
        self.items: List[PlaylistItem] = []
        self.current_index: int = -1
        self.repeat_mode: int = self.REPEAT_OFF
        self.shuffle_enabled: bool = False
        self._history: List[int] = []

    def add_item(self, uri: str, title: str = "", item_type: str = "file", extra: dict = None) -> PlaylistItem:
        if not title:
            if item_type == "dcp":
                title = f"[DCP] {os.path.basename(uri.rstrip(r'\/'))}"
            elif item_type == "url":
                title = uri
            else:
                title = os.path.basename(uri)

        item = PlaylistItem(title=title, uri=uri, item_type=item_type, extra_data=extra or {})
        self.items.append(item)
        return item

    def remove_item(self, index: int):
        if 0 <= index < len(self.items):
            del self.items[index]
            if self.current_index >= len(self.items):
                self.current_index = len(self.items) - 1
            elif index < self.current_index:
                self.current_index -= 1

    def clear(self):
        self.items.clear()
        self.current_index = -1
        self._history.clear()

    def get_current(self) -> Optional[PlaylistItem]:
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    def set_current(self, index: int) -> Optional[PlaylistItem]:
        if 0 <= index < len(self.items):
            self.current_index = index
            self._history.append(index)
            return self.items[index]
        return None

    def next(self) -> Optional[PlaylistItem]:
        if not self.items:
            return None

        if self.repeat_mode == self.REPEAT_ONE and self.current_index != -1:
            return self.items[self.current_index]

        if self.shuffle_enabled and len(self.items) > 1:
            idx = random.randint(0, len(self.items) - 1)
            # Try to avoid immediate repeat if possible
            if idx == self.current_index:
                idx = (idx + 1) % len(self.items)
            self.current_index = idx
            self._history.append(idx)
            return self.items[idx]

        next_idx = self.current_index + 1
        if next_idx >= len(self.items):
            if self.repeat_mode == self.REPEAT_ALL:
                next_idx = 0
            else:
                return None

        self.current_index = next_idx
        self._history.append(next_idx)
        return self.items[next_idx]

    def previous(self) -> Optional[PlaylistItem]:
        if not self.items:
            return None

        if self.repeat_mode == self.REPEAT_ONE and self.current_index != -1:
            return self.items[self.current_index]

        prev_idx = self.current_index - 1
        if prev_idx < 0:
            if self.repeat_mode == self.REPEAT_ALL:
                prev_idx = len(self.items) - 1
            else:
                prev_idx = 0

        self.current_index = prev_idx
        self._history.append(prev_idx)
        return self.items[prev_idx]

    def cycle_repeat_mode(self) -> int:
        self.repeat_mode = (self.repeat_mode + 1) % 3
        return self.repeat_mode

    def toggle_shuffle(self) -> bool:
        self.shuffle_enabled = not self.shuffle_enabled
        return self.shuffle_enabled
