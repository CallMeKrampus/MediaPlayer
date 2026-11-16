import gc
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QImage, QMouseEvent
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.nvjpeg2k_engine import NVJPEG2KEngine, NVJPEG2KPlaybackController
from ui.osc_controls import OSCControls


_APP = QApplication.instance() or QApplication(sys.argv)


class _DummyNVEngine:
    """Thread-controllable fake NVJPEG2KEngine for seek generation and worker tests."""

    cuda = None
    ctx = None

    def __init__(self, width: int = 32, height: int = 18):
        self.w = width
        self.h = height
        self.initialized = True
        self.decode_started = threading.Event()
        self.release_slow_decode = threading.Event()
        self.slow_frame_idx = None
        self.calls = []
        self.index_calls = []

    def index_mxf(self, mxf_path: str):
        self.index_calls.append(mxf_path)
        return [(i * 1024, 512) for i in range(1000)]

    def decode_and_tonemap_frame(self, mxf_path: str, frame_idx: int, grading_params: dict):
        self.calls.append((mxf_path, frame_idx))
        if self.slow_frame_idx is not None and frame_idx == self.slow_frame_idx:
            self.decode_started.set()
            self.release_slow_decode.wait(timeout=3.0)
            fill = 0x11
        else:
            fill = 0xAA

        arr = np.full((self.h, self.w, 4), fill, dtype=np.uint8)
        qimg = QImage(arr.data, self.w, self.h, self.w * 4, QImage.Format.Format_RGB32)
        qimg.ndarray = arr
        return qimg


class TestSeekAndBufferSafety(unittest.TestCase):
    def setUp(self):
        self._controllers = []

    def tearDown(self):
        for ctrl in self._controllers:
            ctrl._stop_event.set()
            ctrl._wake_event.set()
            ctrl._worker_thread.join(timeout=2.0)

    def test_buffer_pool_never_aliases_live_qimages(self):
        engine = NVJPEG2KEngine()
        w, h = 64, 36
        held_qimages = []

        # Hold more frames than the pool size (28) to force both pool reuse scanning and fallback allocs.
        for marker in range(36):
            buf = engine._acquire_host_buffer(w, h)
            buf.fill(marker % 250)
            qimg = QImage(buf.data, w, h, w * 4, QImage.Format.Format_RGB32)
            qimg.ndarray = buf
            held_qimages.append((marker % 250, qimg))
            del buf

        # Verify none of the earlier QImage buffers were overwritten by subsequent acquisitions.
        for expected_val, qimg in held_qimages:
            self.assertEqual(int(qimg.ndarray[0, 0, 0]), expected_val)

        # Release references and confirm pool slots are recycled once refcount drops back to 2.
        held_ptrs = {id(q.ndarray) for _, q in held_qimages}
        held_qimages.clear()
        gc.collect()

        reused = engine._acquire_host_buffer(w, h)
        self.assertIn(id(reused), {id(slot) for slot in engine._buffer_pool})
        self.assertTrue(len(held_ptrs) == 36)

    def test_seek_gen_discards_stale_worker_frames(self):
        dummy = _DummyNVEngine()
        dummy.slow_frame_idx = 0

        with patch.object(NVJPEG2KEngine, "get_instance", return_value=dummy):
            ctrl = NVJPEG2KPlaybackController()
        self._controllers.append(ctrl)

        received = []
        ctrl.frame_ready.connect(lambda _img, idx, pts: received.append((idx, pts)))

        # Freeze prefetcher while decoding frame 0, then seek far ahead to t=120s (frame 2880).
        ctrl.mxf_path = "fake_reel.mxf"
        ctrl.fps = 24.0
        ctrl.total_frames = 5000
        ctrl._last_presented_frame_idx = -1
        ctrl._next_decode_idx = 0
        ctrl._wake_event.set()

        self.assertTrue(dummy.decode_started.wait(timeout=2.0), "Worker did not begin slow decode")

        ctrl.seek_time(120.0)
        dummy.release_slow_decode.set()
        time.sleep(0.15)
        _APP.processEvents()

        with ctrl._cache_lock:
            self.assertNotIn(0, ctrl._frame_cache)
            self.assertIn(2880, ctrl._frame_cache)
        self.assertTrue(any(idx == 2880 for idx, _ in received))
        self.assertFalse(any(idx == 0 for idx, _ in received))

    def test_sync_audio_clock_settle_gate_and_expiry_fallback(self):
        dummy = _DummyNVEngine()
        with patch.object(NVJPEG2KEngine, "get_instance", return_value=dummy):
            ctrl = NVJPEG2KPlaybackController()
        self._controllers.append(ctrl)

        ctrl.mxf_path = "fake_reel.mxf"
        ctrl.fps = 24.0
        ctrl.total_frames = 10000
        ctrl.duration = 10000 / 24.0
        ctrl.is_playing = True

        ctrl.seek_time(200.0)

        # Stale pre-seek audio callback (e.g. 5.0s) during settle window must be ignored.
        ctrl.sync_audio_clock(5.0)
        with ctrl._cache_lock:
            self.assertAlmostEqual(ctrl._base_pts, 200.0, places=3)
            self.assertFalse(ctrl._audio_synced)
            self.assertIsNotNone(ctrl._seek_expected_pts)

        # Once audio arrives near the target, barrier clears and clock phase-locks immediately.
        ctrl.sync_audio_clock(200.25)
        with ctrl._cache_lock:
            self.assertIsNone(ctrl._seek_expected_pts)
            self.assertTrue(ctrl._audio_synced)
            self.assertAlmostEqual(ctrl._base_pts, 200.25, places=3)

        # After settle window expires, even a large divergence must re-anchor so A/V never diverges permanently.
        ctrl.seek_time(300.0)
        with ctrl._cache_lock:
            ctrl._seek_settle_until = time.perf_counter() - 0.05
        ctrl.sync_audio_clock(280.0)
        with ctrl._cache_lock:
            self.assertIsNone(ctrl._seek_expected_pts)
            self.assertTrue(ctrl._audio_synced)
            self.assertAlmostEqual(ctrl._base_pts, 280.0, places=3)

    def test_osc_slider_single_click_emits_single_exact_seek(self):
        osc = OSCControls()
        osc.resize(900, 120)
        osc.show()
        _APP.processEvents()

        duration = 1600.0
        osc.update_position(0.0, duration)

        emitted = []
        osc.seek_requested.connect(emitted.append)

        slider = osc.slider
        click_x = slider.width() * 0.5
        click_pos = QPointF(click_x, slider.height() / 2.0)
        expected_val = slider._pos_to_val(click_x)
        expected_sec = (expected_val / slider.maximum()) * duration

        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            click_pos,
            slider.mapToGlobal(click_pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            click_pos,
            slider.mapToGlobal(click_pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        slider.mousePressEvent(press)
        slider.mouseReleaseEvent(release)
        _APP.processEvents()

        self.assertEqual(len(emitted), 1, f"Expected single seek emit, got {emitted}")
        self.assertAlmostEqual(emitted[0], expected_sec, delta=1.0)
        osc.close()

    def test_post_seek_no_duplicate_decode_no_midreel_lookahead_and_smooth_cadence(self):
        dummy = _DummyNVEngine()
        with patch.object(NVJPEG2KEngine, "get_instance", return_value=dummy):
            ctrl = NVJPEG2KPlaybackController()
        self._controllers.append(ctrl)

        ctrl.mxf_path = "reel1.mxf"
        ctrl.fps = 24.0
        ctrl.total_frames = 1000
        ctrl.duration = 1000 / 24.0
        ctrl.set_next_reel("reel2.mxf", "sound2.mxf")
        ctrl.is_playing = True

        emitted = []
        ctrl.frame_ready.connect(lambda _img, idx, pts: emitted.append((time.perf_counter(), idx, pts)))

        # 1. Seek mid-reel (frame 240, > 3s remaining): must not duplicate-decode 240 or touch reel2.mxf
        dummy.calls.clear()
        dummy.index_calls.clear()
        ctrl.seek_time(10.0)
        with ctrl._cache_lock:
            self.assertGreaterEqual(ctrl._next_decode_idx, 241)

        time.sleep(0.15)
        _APP.processEvents()

        target_decodes = [c for c in dummy.calls if c == ("reel1.mxf", 240)]
        self.assertEqual(len(target_decodes), 1, f"Target frame 240 decoded multiple times: {dummy.calls}")
        self.assertFalse(any(c[0] == "reel2.mxf" for c in dummy.calls), f"Unexpected mid-reel lookahead: {dummy.calls}")
        self.assertNotIn("reel2.mxf", dummy.index_calls)

        # 2. Simulate mild negative audio drift during initial post-seek lock and verify monotonic +1 cadence (>= 30ms)
        emitted.clear()
        ctrl.sync_audio_clock(9.96)
        ctrl.play()
        t_end = time.time() + 0.35
        while time.time() < t_end:
            _APP.processEvents()
            time.sleep(0.005)
        ctrl.pause()

        indices = [idx for _, idx, _ in emitted]
        self.assertGreaterEqual(len(indices), 5)
        self.assertEqual(indices, list(range(indices[0], indices[0] + len(indices))), f"Non-sequential post-seek frames: {indices}")
        dts = [(emitted[i][0] - emitted[i - 1][0]) * 1000.0 for i in range(1, len(emitted))]
        self.assertTrue(all(dt >= 28.0 for dt in dts), f"Compressed frame burst detected (<28ms): {dts}")

        # 3. Near end of reel (remaining <= 3s = 72 frames): next-reel lookahead must activate
        dummy.calls.clear()
        ctrl.seek_time((1000 - 24) / 24.0)
        time.sleep(0.25)
        _APP.processEvents()
        self.assertTrue(any(c[0] == "reel2.mxf" for c in dummy.calls), "Expected next-reel predecode near reel end")


if __name__ == "__main__":
    unittest.main()
