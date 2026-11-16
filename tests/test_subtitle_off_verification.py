import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['PATH'] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib') + os.pathsep + os.environ['PATH']

import time
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow


class TestSubtitleDisablingAndToggling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_subtitle_turn_off_and_stay_off(self):
        win = MainWindow()
        win.show()

        test_file = 'E:/Star.Wars.The.Mandalorian.and.Grogu.2026.2160p.3D.DSNP.WEB-DL.English.DDP5.1.Atmos.DV.H.265-JeRi.mp4'
        if not os.path.exists(test_file):
            win.close()
            win.engine.stop()
            self.skipTest(f"Media file not found: {test_file}")

        # 1. Play media
        win.play_media(test_file)
        for _ in range(40):
            self.app.processEvents()
            time.sleep(0.05)

        # 2. Check initial auto-selection
        self.assertIn(win.engine.player.sid, (1, '1'))
        self.assertTrue(win.engine.player['sub-visibility'])
        self.assertFalse(win.engine.subtitles_user_disabled)

        # 3. Disabling subtitles
        win._select_track_and_notify('sub', 'no')
        for _ in range(30):
            self.app.processEvents()
            time.sleep(0.05)

        # 4. Verify subtitles stayed OFF
        self.assertIn(win.engine.player.sid, ('no', False, None))
        self.assertFalse(win.engine.player['sub-visibility'])
        self.assertTrue(win.engine.subtitles_user_disabled)

        # 5. Toggle ON via V
        win.action_toggle_subtitles()
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.05)
        self.assertIn(win.engine.player.sid, (1, '1'))
        self.assertTrue(win.engine.player['sub-visibility'])
        self.assertFalse(win.engine.subtitles_user_disabled)

        # 6. Toggle OFF via V
        win.action_toggle_subtitles()
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.05)
        self.assertIn(win.engine.player.sid, ('no', False, None))
        self.assertFalse(win.engine.player['sub-visibility'])
        self.assertTrue(win.engine.subtitles_user_disabled)

        win.close()
        win.engine.stop()


if __name__ == '__main__':
    unittest.main()
