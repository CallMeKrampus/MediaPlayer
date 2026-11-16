"""
BOOB Player - Go To Precision Navigation Dialog
Supports jumping by timecode ([hh:]mm:ss.ms with or without explicit separators)
or frame number + frame rate (e.g. 109029, 23.976).
"""

import re
from typing import Optional, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal


def format_time_ms(seconds: float) -> str:
    """Format seconds into hh:mm:ss.ms (e.g. 01:15:47.376)."""
    if seconds is None or seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def parse_time_string(text: str) -> Optional[float]:
    """
    Parse a user time string into seconds.
    Supports:
      - '01:15:47.376' -> 4547.376
      - '15:47.376'    -> 947.376
      - '15:47'        -> 947.0
      - '47.376'       -> 47.376
      - Unseparated digits:
          '011547376' (8-9 digits) -> 01:15:47.376
          '011547'    (6 digits)   -> 01:15:47
          '1547'      (4 digits)   -> 15:47
          '47'        (1-2 digits) -> 47s
    """
    s = text.strip()
    if not s:
        return None

    # 1. Standard colon-separated format
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 3:
                h = float(parts[0])
                m = float(parts[1])
                sec = float(parts[2])
                return h * 3600.0 + m * 60.0 + sec
            elif len(parts) == 2:
                m = float(parts[0])
                sec = float(parts[1])
                return m * 60.0 + sec
            elif len(parts) == 1:
                return float(parts[0])
        except ValueError:
            return None

    # 2. Decimal seconds with dot (e.g. 75.32 or 4547.376)
    if "." in s:
        try:
            return float(s)
        except ValueError:
            pass

    # 3. Unseparated pure digits
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None

    # If user typed millisecond precision (e.g. 011547376 = 9 digits)
    if len(digits) >= 8:
        # Pad to 9 digits: hh (2) mm (2) ss (2) ms (3)
        d = digits.zfill(9)
        h = int(d[:2])
        m = int(d[2:4])
        sec = int(d[4:6])
        ms = int(d[6:9])
        return h * 3600.0 + m * 60.0 + sec + (ms / 1000.0)
    elif len(digits) == 6:  # hhmmss
        h = int(digits[:2])
        m = int(digits[2:4])
        sec = int(digits[4:6])
        return h * 3600.0 + m * 60.0 + sec
    elif len(digits) == 5:  # hmmss
        h = int(digits[:1])
        m = int(digits[1:3])
        sec = int(digits[3:5])
        return h * 3600.0 + m * 60.0 + sec
    elif len(digits) == 4:  # mmss
        m = int(digits[:2])
        sec = int(digits[2:4])
        return m * 60.0 + sec
    elif len(digits) == 3:  # mss
        m = int(digits[:1])
        sec = int(digits[1:3])
        return m * 60.0 + sec
    else:  # ss
        return float(digits)


def parse_frame_string(text: str, default_fps: float = 24.0) -> Optional[Tuple[int, float]]:
    """
    Parse a user frame string into (frame_number, frame_rate).
    Supports:
      - '109029, 23.976'
      - '109029 23.976'
      - '109029' (uses default_fps)
    """
    s = text.strip()
    if not s:
        return None

    # Split by comma or space
    parts = re.split(r"[,;\s]+", s)
    try:
        frame_num = int(float(parts[0]))
        if len(parts) >= 2 and float(parts[1]) > 0:
            fps = float(parts[1])
        else:
            fps = float(default_fps) if default_fps > 0 else 24.0
        return frame_num, fps
    except (ValueError, IndexError):
        return None


class GoToDialog(QDialog):
    """
    Precision Go-To dialog replicating MPC-HC style:
    - Time jump with flexible separator parsing
    - Frame jump with frame number & framerate
    """
    seek_requested = pyqtSignal(float)  # PTS in seconds
    frame_seek_requested = pyqtSignal(int, float)  # (frame_number, fps)

    parse_time_string = staticmethod(parse_time_string)
    parse_frame_string = staticmethod(parse_frame_string)

    def __init__(self, current_pts: float = 0.0, current_frame: int = 0, fps: float = 24.0, parent=None):
        super().__init__(parent)
        self.current_pts = max(0.0, current_pts)
        self.fps = fps if fps > 0 else 24.0
        self.current_frame = current_frame if current_frame >= 0 else int(self.current_pts * self.fps)

        self.setWindowTitle("Go To...")
        self.setMinimumWidth(480)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f1015;
                color: #e4e4e7;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QLabel {
                color: #e4e4e7;
                font-size: 11px;
            }
            QLabel.hintLabel {
                color: #a1a1aa;
                font-size: 10.5px;
                line-height: 1.4;
            }
            QLineEdit {
                background-color: #15161f;
                color: #ffffff;
                border: 1px solid #272834;
                border-radius: 5px;
                padding: 6px 10px;
                font-family: monospace;
                font-size: 11.5px;
                font-weight: bold;
                selection-background-color: #2b2d3c;
            }
            QLineEdit:focus {
                border-color: #4a4e63;
                background-color: #191a24;
            }
            QPushButton.goBtn {
                background: #1b1c26;
                color: #f4f4f5;
                border: 1px solid #2e303f;
                border-radius: 5px;
                padding: 4px 16px;
                font-size: 11px;
                font-weight: 600;
                min-width: 65px;
                min-height: 28px;
            }
            QPushButton.goBtn:hover {
                background: #272938;
                border-color: #4a4e63;
                color: #ffffff;
            }
            QPushButton.goBtn:pressed {
                background: #333649;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # 1. Timecode section
        lbl_time_desc = QLabel(
            "Enter a timecode using the format [hh:]mm:ss.ms to jump to a specified time. "
            "You do not need to enter the separators explicitly."
        )
        lbl_time_desc.setProperty("class", "hintLabel")
        lbl_time_desc.setWordWrap(True)
        layout.addWidget(lbl_time_desc)

        row_time = QHBoxLayout()
        row_time.setSpacing(10)
        lbl_time = QLabel("Time")
        lbl_time.setFixedWidth(55)
        self.edit_time = QLineEdit(format_time_ms(self.current_pts))
        self.btn_time_go = QPushButton("Go!")
        self.btn_time_go.setProperty("class", "goBtn")
        self.btn_time_go.clicked.connect(self._on_time_go)
        self.edit_time.returnPressed.connect(self._on_time_go)

        row_time.addWidget(lbl_time)
        row_time.addWidget(self.edit_time, 1)
        row_time.addWidget(self.btn_time_go)
        layout.addLayout(row_time)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #232530; margin: 4px 0;")
        layout.addWidget(sep)

        # 2. Frame section
        lbl_frame_desc = QLabel(
            "Enter two numbers to jump to a specified frame, the first is the frame number, "
            "the second is the frame rate."
        )
        lbl_frame_desc.setProperty("class", "hintLabel")
        lbl_frame_desc.setWordWrap(True)
        layout.addWidget(lbl_frame_desc)

        row_frame = QHBoxLayout()
        row_frame.setSpacing(10)
        lbl_frame = QLabel("Frame")
        lbl_frame.setFixedWidth(55)
        self.edit_frame = QLineEdit(f"{self.current_frame}, {self.fps:.3f}")
        self.btn_frame_go = QPushButton("Go!")
        self.btn_frame_go.setProperty("class", "goBtn")
        self.btn_frame_go.clicked.connect(self._on_frame_go)
        self.edit_frame.returnPressed.connect(self._on_frame_go)

        row_frame.addWidget(lbl_frame)
        row_frame.addWidget(self.edit_frame, 1)
        row_frame.addWidget(self.btn_frame_go)
        layout.addLayout(row_frame)

        # Highlight Time field on show
        self.edit_time.selectAll()
        self.edit_time.setFocus()

    def _on_time_go(self):
        pts = parse_time_string(self.edit_time.text())
        if pts is not None and pts >= 0:
            self.seek_requested.emit(pts)
            self.accept()

    def _on_frame_go(self):
        res = parse_frame_string(self.edit_frame.text(), default_fps=self.fps)
        if res is not None:
            f_num, fps = res
            self.frame_seek_requested.emit(f_num, fps)
            pts = f_num / fps if fps > 0 else 0.0
            self.seek_requested.emit(pts)
            self.accept()
