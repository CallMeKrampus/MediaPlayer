"""
BOOB Player - Live TV & IPTV Manager
Parses M3U / M3U8 playlists, manages channel categories, live stream URLs (HLS, RTSP, RTMP, UDP),
and provides built-in curated public high-definition channels.
"""

import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional


@dataclass
class IPTVChannel:
    name: str
    url: str
    group: str = "General"
    logo: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    country: str = "Global"
    language: str = "English"
    resolution: str = "1080p"


class IPTVManager:
    DEFAULT_CHANNELS: List[IPTVChannel] = [
        # News & World Broadcasts
        IPTVChannel(
            name="NASA TV Public HD",
            url="https://ntv1.akamaized.net/hls/live/2014075/NASA-NTV1-HLS/master.m3u8",
            group="Science & Tech",
            country="US",
            resolution="1080p",
            logo="https://raw.githubusercontent.com/iptv-org/epg/master/providers/directv.com/nasa.png"
        ),
        IPTVChannel(
            name="NASA TV Media HD",
            url="https://ntv2.akamaized.net/hls/live/2014076/NASA-NTV2-HLS/master.m3u8",
            group="Science & Tech",
            country="US",
            resolution="1080p"
        ),
        IPTVChannel(
            name="DW English HD",
            url="https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/master.m3u8",
            group="News",
            country="DE",
            resolution="1080p"
        ),
        IPTVChannel(
            name="France 24 English HD",
            url="https://static.france24.com/live/F24_EN_LO_HLS/live_web.m3u8",
            group="News",
            country="FR",
            resolution="1080p"
        ),
        IPTVChannel(
            name="Sky News UK HD",
            url="https://live.skynews.me.uk/hls/skynews_hd.m3u8",
            group="News",
            country="GB",
            resolution="1080p"
        ),
        IPTVChannel(
            name="Euronews English",
            url="https://euronews-euronews-world-1-au.samsung.wurl.tv/playlist.m3u8",
            group="News",
            country="EU",
            resolution="1080p"
        ),
        IPTVChannel(
            name="Al Jazeera English HD",
            url="https://live-hls-web-aje.getaj.net/AJE/01.m3u8",
            group="News",
            country="QA",
            resolution="1080p"
        ),
        IPTVChannel(
            name="Bloomberg Quicktake",
            url="https://bloomberg.com/media-manifest/streams/us.m3u8",
            group="Business",
            country="US",
            resolution="1080p"
        ),
        # Cinema, Movies & Culture
        IPTVChannel(
            name="Classic Cinema Network",
            url="https://classiccinema-stream.akamaized.net/hls/live/classic_cinema.m3u8",
            group="Movies",
            country="US",
            resolution="1080p"
        ),
        IPTVChannel(
            name="Red Bull TV Action Sports",
            url="https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8",
            group="Sports",
            country="AT",
            resolution="1080p"
        ),
        # Test & Calibration Streams (Codec & Tonemapping validation)
        IPTVChannel(
            name="Big Buck Bunny 4K 60fps (HLS Test)",
            url="https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
            group="4K Test & Benchmarks",
            country="Global",
            resolution="4K UHD"
        ),
        IPTVChannel(
            name="Tears of Steel 1080p (Cinema Test)",
            url="https://dash.akamaized.net/envivio/EnvivioDash3/manifest.mpd",
            group="4K Test & Benchmarks",
            country="Global",
            resolution="1080p"
        ),
        IPTVChannel(
            name="Sintel 4K Cinema Benchmark",
            url="https://bitmovin-a.akamaihd.net/content/sintel/hls/playlist.m3u8",
            group="4K Test & Benchmarks",
            country="Global",
            resolution="4K UHD"
        ),
    ]

    def __init__(self):
        self.channels: List[IPTVChannel] = list(self.DEFAULT_CHANNELS)
        self.groups: Set[str] = set()
        self._refresh_groups()

    def _refresh_groups(self):
        self.groups = sorted(list({ch.group for ch in self.channels if ch.group}))

    def load_m3u_file(self, file_path: str) -> int:
        """Parse local M3U/M3U8 file and add channels."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"M3U playlist file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        added = self._parse_m3u_content(content)
        return added

    def load_m3u_url(self, url: str) -> int:
        """Fetch and parse remote M3U/M3U8 playlist."""
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BOOBCinema/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode("utf-8", errors="ignore")

        added = self._parse_m3u_content(content)
        return added

    def _parse_m3u_content(self, text: str) -> int:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        new_channels: List[IPTVChannel] = []

        pending_name = ""
        pending_group = "General"
        pending_logo = ""
        pending_tvg_id = ""
        pending_country = "Global"

        for line in lines:
            if line.startswith("#EXTINF:"):
                # Parse attributes
                # Example: #EXTINF:-1 tvg-id="123" tvg-name="DW" tvg-logo="url" group-title="News",DW English
                info_match = re.search(r'#EXTINF:[^,]*,(.*)', line)
                pending_name = info_match.group(1).strip() if info_match else "Unknown Channel"

                # Extract tvg-logo
                logo_match = re.search(r'tvg-logo="([^"]*)"', line)
                pending_logo = logo_match.group(1) if logo_match else ""

                # Extract group-title
                group_match = re.search(r'group-title="([^"]*)"', line)
                pending_group = group_match.group(1) if group_match else "General"

                # Extract tvg-id
                id_match = re.search(r'tvg-id="([^"]*)"', line)
                pending_tvg_id = id_match.group(1) if id_match else ""

            elif line.startswith("#"):
                # Other metadata tags, skip
                continue
            else:
                # This line is the stream URL
                stream_url = line
                channel = IPTVChannel(
                    name=pending_name or "Live Stream",
                    url=stream_url,
                    group=pending_group or "General",
                    logo=pending_logo,
                    tvg_id=pending_tvg_id,
                    country=pending_country,
                )
                new_channels.append(channel)
                # Reset
                pending_name = ""
                pending_group = "General"
                pending_logo = ""
                pending_tvg_id = ""

        if new_channels:
            self.channels.extend(new_channels)
            self._refresh_groups()

        return len(new_channels)

    def filter_channels(self, query: str = "", group: str = "All") -> List[IPTVChannel]:
        results = self.channels
        if group and group != "All":
            results = [c for c in results if c.group.lower() == group.lower()]

        if query:
            q = query.lower()
            results = [
                c for c in results
                if q in c.name.lower() or q in c.group.lower() or q in c.country.lower()
            ]

        return results

    def add_custom_channel(self, name: str, url: str, group: str = "Custom") -> IPTVChannel:
        ch = IPTVChannel(name=name, url=url, group=group)
        self.channels.append(ch)
        self._refresh_groups()
        return ch
