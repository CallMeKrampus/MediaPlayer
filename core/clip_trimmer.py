"""
BOOB Player - Lossless Stream Trimmer
Performs instantaneous zero-reencode stream copy clipping of active media using bundled FFmpeg.
Preserves original bitstream quality, multi-channel audio tracks, HDR metadata, and subtitles.
"""

import os
import subprocess
import time
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal
from core.app_paths import get_tool_path


class LosslessTrimWorker(QThread):
    """
    Background worker that invokes FFmpeg with stream copy (-c copy)
    to losslessly extract a designated [In, Out] time segment in seconds.
    """
    progress = pyqtSignal(float)            # percentage (0.0 to 100.0)
    finished = pyqtSignal(bool, str, float) # success, output_path, elapsed_sec
    error = pyqtSignal(str)                 # error message

    def __init__(
        self,
        source_path: str,
        output_path: str,
        start_time_sec: float,
        end_time_sec: float,
        parent=None
    ):
        super().__init__(parent)
        self.source_path = source_path
        self.output_path = output_path
        self.start_time = max(0.0, float(start_time_sec))
        self.end_time = max(self.start_time + 0.1, float(end_time_sec))
        self.process: Optional[subprocess.Popen] = None
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass

    def run(self):
        start_t = time.perf_counter()
        duration_sec = self.end_time - self.start_time

        ffmpeg_bin = get_tool_path("ffmpeg.exe")
        if not os.path.exists(ffmpeg_bin):
            self.error.emit(f"FFmpeg binary not found at: {ffmpeg_bin}")
            self.finished.emit(False, "", 0.0)
            return

        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss", f"{self.start_time:.3f}",
            "-to", f"{self.end_time:.3f}",
            "-i", self.source_path,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            "-map", "0",
            self.output_path
        ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            # Wait for FFmpeg to finish
            stdout, stderr = self.process.communicate()

            if self._is_cancelled:
                if os.path.exists(self.output_path):
                    try:
                        os.remove(self.output_path)
                    except OSError:
                        pass
                self.finished.emit(False, "", 0.0)
                return

            if self.process.returncode == 0 and os.path.exists(self.output_path):
                elapsed = time.perf_counter() - start_t
                self.progress.emit(100.0)
                self.finished.emit(True, self.output_path, elapsed)
            else:
                err_lines = [l for l in stderr.splitlines() if "Error" in l or "failed" in l]
                err_msg = err_lines[-1] if err_lines else (stderr[-300:] if stderr else "Unknown FFmpeg error")
                self.error.emit(f"FFmpeg trim error (code {self.process.returncode}): {err_msg}")
                self.finished.emit(False, "", 0.0)

        except Exception as e:
            self.error.emit(f"Failed to execute lossless trim: {str(e)}")
            self.finished.emit(False, "", 0.0)
