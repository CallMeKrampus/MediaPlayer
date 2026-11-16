"""
Unit tests for Live TV / IPTV Manager & Playlist handling.
"""

import unittest
from core.iptv_manager import IPTVManager, IPTVChannel


class TestIPTVManager(unittest.TestCase):
    def setUp(self):
        self.mgr = IPTVManager()

    def test_default_channels(self):
        self.assertGreater(len(self.mgr.channels), 5)
        self.assertIn("News", self.mgr.groups)
        self.assertIn("Science & Tech", self.mgr.groups)

    def test_filter_channels(self):
        news = self.mgr.filter_channels(group="News")
        self.assertTrue(all(c.group == "News" for c in news))

        nasa = self.mgr.filter_channels(query="NASA")
        self.assertTrue(any("NASA" in c.name for c in nasa))

    def test_custom_m3u_parsing(self):
        sample_m3u = """#EXTM3U
#EXTINF:-1 tvg-id="test.1" tvg-name="Test 1" tvg-logo="http://logo.png" group-title="Cinema",Cinema Premium HD
http://stream.example.com/live/cinema.m3u8
#EXTINF:-1 group-title="Sports",Live Sports 4K
http://stream.example.com/live/sports.m3u8
"""
        initial_len = len(self.mgr.channels)
        count = self.mgr._parse_m3u_content(sample_m3u)
        self.assertEqual(count, 2)
        self.assertEqual(len(self.mgr.channels), initial_len + 2)

        cinema_ch = [c for c in self.mgr.channels if c.name == "Cinema Premium HD"][0]
        self.assertEqual(cinema_ch.group, "Cinema")
        self.assertEqual(cinema_ch.url, "http://stream.example.com/live/cinema.m3u8")


if __name__ == "__main__":
    unittest.main()
