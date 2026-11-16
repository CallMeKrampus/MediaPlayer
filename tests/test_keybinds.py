import os
import sys
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ui.main_window import MainWindow


_APP = QApplication.instance() or QApplication(sys.argv)


class TestKeybinds(unittest.TestCase):
    def setUp(self):
        self.win = MainWindow()
        self.win.show()
        self.win.activateWindow()
        _APP.processEvents()

    def tearDown(self):
        if self.win.isFullScreen():
            self.win.showNormal()
        self.win.close()
        if getattr(self.win.engine, "nv_controller", None):
            self.win.engine.nv_controller.close()
        if getattr(self.win.engine, "player", None):
            self.win.engine.player.terminate()
        _APP.processEvents()

    def test_space_toggles_play_pause_windowed(self):
        self.win.engine.is_paused = False
        QTest.keyClick(self.win, Qt.Key.Key_Space)
        _APP.processEvents()
        self.assertTrue(self.win.engine.is_paused)

        QTest.keyClick(self.win, Qt.Key.Key_Space)
        _APP.processEvents()
        self.assertFalse(self.win.engine.is_paused)

    def test_space_toggles_play_pause_fullscreen_with_hidden_menubar(self):
        self.win.toggle_fullscreen()
        _APP.processEvents()
        self.assertTrue(self.win.isFullScreen())
        self.assertFalse(self.win.menuBar().isVisible())

        self.win.engine.is_paused = False
        QTest.keyClick(self.win, Qt.Key.Key_Space)
        _APP.processEvents()
        self.assertTrue(self.win.engine.is_paused)

        QTest.keyClick(self.win, Qt.Key.Key_Space)
        _APP.processEvents()
        self.assertFalse(self.win.engine.is_paused)

    def test_escape_exits_fullscreen(self):
        self.win.toggle_fullscreen()
        _APP.processEvents()
        self.assertTrue(self.win.isFullScreen())

        QTest.keyClick(self.win, Qt.Key.Key_Escape)
        _APP.processEvents()
        self.assertFalse(self.win.isFullScreen())
        self.assertTrue(self.win.menuBar().isVisible())

    def test_escape_in_windowed_mode_stays_windowed(self):
        self.assertFalse(self.win.isFullScreen())
        QTest.keyClick(self.win, Qt.Key.Key_Escape)
        _APP.processEvents()
        self.assertFalse(self.win.isFullScreen())


if __name__ == "__main__":
    unittest.main()
