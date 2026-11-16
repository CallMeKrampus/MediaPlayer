"""
BOOB Player - Digital Cinema Package (DCP) Subtitle Engine
Extracts SMPTE ST 428-7 / 429-5 and Interop Timed Text XML from MXF and XML assets,
calculates composition cumulative frame offsets across multi-reel DCPs,
generates unified high-precision SubRip (.srt) tracks, and provides sub-millisecond
timecode binary search for real-time GPU canvas presentation.
"""

import os
import re
import bisect
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass


TIME_PATTERN = re.compile(r'(\d+):(\d+):(\d+)([:.,])(\d+)')


def parse_dcp_timecode(tc_str: str, fps: float = 24.0) -> float:
    """Parse SMPTE HH:MM:SS:FF, HH:MM:SS.mmm, or Interop HH:MM:SS:TTT to float seconds."""
    if not tc_str:
        return 0.0
    m = TIME_PATTERN.fullmatch(tc_str.strip())
    if not m:
        return 0.0
    h, mn, sec, sep, f = m.groups()
    base = int(h) * 3600 + int(mn) * 60 + int(sec)
    if sep in '.,':
        return base + float('0.' + f)
    int_f = int(f)
    if len(f) == 3:  # 250 ticks per second (Interop)
        return base + (int_f / 250.0)
    return base + (int_f / (fps if fps > 0 else 24.0))


def format_srt_time(seconds: float) -> str:
    """Format float seconds to SRT timecode HH:MM:SS,mmm."""
    total_ms = max(0, int(round(seconds * 1000)))
    h = total_ms // 3600000
    rem = total_ms % 3600000
    m = rem // 60000
    rem = rem % 60000
    s = rem // 1000
    ms = rem % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@dataclass
class SubtitleCue:
    start_sec: float
    end_sec: float
    text: str


class DCPSubtitleEngine:
    def __init__(self):
        self.cues: List[SubtitleCue] = []
        self._start_times: List[float] = []
        self.reel_cues: Dict[int, List[SubtitleCue]] = {}
        self.reel_srt_paths: Dict[int, str] = {}
        self.srt_path: Optional[str] = None
        self.language: str = "en"
        self.title: str = "DCP Subtitles"

    @staticmethod
    def extract_xml_from_mxf(mxf_path: str) -> Optional[str]:
        """Extract embedded SMPTE/Interop Subtitle XML payload from an MXF file."""
        if not mxf_path or not os.path.exists(mxf_path):
            return None
        try:
            with open(mxf_path, 'rb') as f:
                data = f.read()
            s = data.find(b'<?xml')
            if s < 0:
                s = data.find(b'<SubtitleReel')
            if s < 0:
                s = data.find(b'<DCSubtitle')
            if s < 0:
                return None

            for end_tag in [b'</SubtitleReel>', b'</DCSubtitle>', b'</tt>']:
                e = data.find(end_tag, s)
                if e >= 0:
                    e += len(end_tag)
                    return data[s:e].decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[DCPSubtitleEngine] Error extracting XML from {mxf_path}: {e}")
        return None

    def load_composition_subtitles(self, cpl, cache_dir: Optional[str] = None) -> Optional[str]:
        """
        Parse all subtitle tracks across all reels in a DCP composition.
        Generates both per-reel SRT files (for mpv container-local clocks)
        and a unified SRT file (for full composition timeline and native GPU rendering).
        Offsets unified cues by the cumulative start time of the reel.
        Returns the path to the generated unified .srt file.
        """
        self.cues.clear()
        self._start_times.clear()
        self.reel_cues.clear()
        self.reel_srt_paths.clear()
        self.srt_path = None

        if not cpl or not getattr(cpl, "reels", None):
            return None

        fps = float(getattr(cpl, "fps", 24.0) or 24.0)
        cum_frames = 0
        detected_lang = "en"

        if not cache_dir:
            cache_dir = os.path.join(tempfile.gettempdir(), "boob_player_dcp_subs")
        os.makedirs(cache_dir, exist_ok=True)

        cpl_id = getattr(cpl, "cpl_id", "dcp") or "dcp"
        cpl_id_clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', cpl_id)

        for reel_idx, reel in enumerate(cpl.reels):
            offset_sec = cum_frames / fps
            sub_path = getattr(reel, "subtitle_path", "")

            if sub_path and os.path.exists(sub_path):
                xml_text = None
                if sub_path.lower().endswith(".mxf"):
                    xml_text = self.extract_xml_from_mxf(sub_path)
                elif sub_path.lower().endswith(".xml"):
                    try:
                        with open(sub_path, 'r', encoding='utf-8', errors='ignore') as f:
                            xml_text = f.read()
                    except Exception:
                        pass

                if xml_text:
                    # Parse reel-local cues (offset = 0)
                    local_cues, lang = self._parse_xml_cues(xml_text, fps, 0.0)
                    if lang and lang != "und":
                        detected_lang = lang

                    self.reel_cues[reel_idx] = local_cues

                    # Generate per-reel SRT for mpv
                    if local_cues:
                        reel_srt = os.path.join(cache_dir, f"{cpl_id_clean}_reel{reel_idx}_{detected_lang}.srt")
                        try:
                            with open(reel_srt, 'w', encoding='utf-8') as f:
                                for idx, cue in enumerate(local_cues, 1):
                                    f.write(f"{idx}\n")
                                    f.write(f"{format_srt_time(cue.start_sec)} --> {format_srt_time(cue.end_sec)}\n")
                                    f.write(f"{cue.text}\n\n")
                            self.reel_srt_paths[reel_idx] = reel_srt
                        except Exception as e:
                            print(f"[DCPSubtitleEngine] Error writing reel SRT {reel_srt}: {e}")

                    # Parse global cues (offset = cumulative offset_sec)
                    global_cues, _ = self._parse_xml_cues(xml_text, fps, offset_sec)
                    self.cues.extend(global_cues)

            cum_frames += getattr(reel, "picture_duration_frames", 0)

        if not self.cues:
            return None

        # Sort cues strictly chronologically
        self.cues.sort(key=lambda c: (c.start_sec, c.end_sec))
        self._start_times = [c.start_sec for c in self.cues]
        self.language = detected_lang
        self.title = f"DCP [{detected_lang.upper()}] Timed Text"

        # Generate unified composition SRT file
        out_srt = os.path.join(cache_dir, f"{cpl_id_clean}_{detected_lang}.srt")
        try:
            with open(out_srt, 'w', encoding='utf-8') as f:
                for idx, cue in enumerate(self.cues, 1):
                    f.write(f"{idx}\n")
                    f.write(f"{format_srt_time(cue.start_sec)} --> {format_srt_time(cue.end_sec)}\n")
                    f.write(f"{cue.text}\n\n")
            self.srt_path = out_srt
            return out_srt
        except Exception as e:
            print(f"[DCPSubtitleEngine] Error writing SRT {out_srt}: {e}")
            return None

    def get_reel_srt(self, reel_index: int) -> Optional[str]:
        """Return the per-reel SRT path matching the reel-local clock, or None."""
        return self.reel_srt_paths.get(reel_index)

    @staticmethod
    def _format_node_text(node, parent_italic: bool = False, parent_bold: bool = False) -> str:
        """Recursively extract and format text from a Text or Font node, handling nested styling and tails."""
        parts = []
        italic = parent_italic or (node.get('Italic', '').lower() in ('yes', 'true', '1'))
        bold = parent_bold or (
            node.get('Weight', '').lower() in ('bold', 'bolder')
            or node.get('Bold', '').lower() in ('yes', 'true', '1')
        )

        if node.text:
            txt = node.text.strip('\r\n')
            if txt:
                if italic:
                    txt = f"<i>{txt}</i>"
                if bold:
                    txt = f"<b>{txt}</b>"
                parts.append(txt)

        for child in node:
            parts.append(DCPSubtitleEngine._format_node_text(child, parent_italic=italic, parent_bold=bold))
            if child.tail:
                tail = child.tail.strip('\r\n')
                if tail:
                    if italic:
                        tail = f"<i>{tail}</i>"
                    if bold:
                        tail = f"<b>{tail}</b>"
                    parts.append(tail)

        joined = "".join(parts)
        joined = re.sub(r'</i>(\s*)<i>', r'\1', joined)
        joined = re.sub(r'</b>(\s*)<b>', r'\1', joined)
        return joined

    @classmethod
    def _parse_subtitle_element(cls, sub_elem) -> str:
        lines = []
        sub_italic = sub_elem.get('Italic', '').lower() in ('yes', 'true', '1')
        sub_bold = (
            sub_elem.get('Weight', '').lower() in ('bold', 'bolder')
            or sub_elem.get('Bold', '').lower() in ('yes', 'true', '1')
        )

        # Check all direct and nested Text elements
        for child in sub_elem:
            tag = child.tag.split('}')[-1]
            if tag == 'Text':
                t = cls._format_node_text(child, parent_italic=sub_italic, parent_bold=sub_bold).strip()
                if t:
                    lines.append(t)
            elif tag == 'Font':
                font_italic = sub_italic or (child.get('Italic', '').lower() in ('yes', 'true', '1'))
                font_bold = sub_bold or (
                    child.get('Weight', '').lower() in ('bold', 'bolder')
                    or child.get('Bold', '').lower() in ('yes', 'true', '1')
                )
                for fchild in child:
                    ftag = fchild.tag.split('}')[-1]
                    if ftag == 'Text':
                        t = cls._format_node_text(fchild, parent_italic=font_italic, parent_bold=font_bold).strip()
                        if t:
                            lines.append(t)

        # Fallback if no lines collected
        if not lines:
            for text_elem in sub_elem.iter():
                if text_elem.tag.split('}')[-1] == 'Text':
                    t = cls._format_node_text(text_elem, parent_italic=sub_italic, parent_bold=sub_bold).strip()
                    if t:
                        lines.append(t)

        return "\n".join(lines).strip()

    def _parse_xml_cues(self, xml_content: str, fps: float, offset_sec: float) -> Tuple[List[SubtitleCue], str]:
        cues = []
        lang = "und"
        try:
            root = ET.fromstring(xml_content)
            for child in root:
                tag = child.tag.split('}')[-1]
                if tag == "Language" and child.text:
                    lang = child.text.strip().lower()

            for elem in root.iter():
                tag = elem.tag.split('}')[-1]
                if tag == 'Subtitle':
                    t_in = elem.get('TimeIn')
                    t_out = elem.get('TimeOut')
                    if t_in and t_out:
                        start_sec = parse_dcp_timecode(t_in, fps) + offset_sec
                        end_sec = parse_dcp_timecode(t_out, fps) + offset_sec

                        cue_text = self._parse_subtitle_element(elem)
                        if cue_text and end_sec > start_sec:
                            cues.append(SubtitleCue(start_sec, end_sec, cue_text))
        except Exception as e:
            print(f"[DCPSubtitleEngine] XML Parse error: {e}")

        return cues, lang

    def get_text_at_pts(self, pts: float) -> Optional[str]:
        """Sub-millisecond binary search for active subtitle text at global PTS."""
        if not self.cues or not self._start_times:
            return None

        # Binary search rightmost cue whose start_sec <= pts
        idx = bisect.bisect_right(self._start_times, pts) - 1
        if idx < 0:
            return None

        # Check if pts falls within cue [start_sec, end_sec]
        # Also check nearby cues in case of overlapping subtitles (up to 30s duration)
        active_texts = []
        seen = set()
        check_idx = idx
        while check_idx >= 0 and self.cues[check_idx].start_sec >= pts - 30.0:
            cue = self.cues[check_idx]
            if cue.start_sec <= pts <= cue.end_sec and cue.text not in seen:
                active_texts.append(cue.text)
                seen.add(cue.text)
            check_idx -= 1

        if active_texts:
            active_texts.reverse()
            return "\n".join(active_texts)

        return None
