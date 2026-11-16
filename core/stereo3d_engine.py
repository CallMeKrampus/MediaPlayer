"""
BOOB Player - Stereoscopic 3D Engine
Supports full stereoscopic 3D video playback:
- Input formats: Side-by-Side (Half/Full), Top-and-Bottom / Over-Under (Half/Full),
  Frame Interleaved / Alternating, Line Interleaved (Row/Column), Frame Packed.
- Output viewing modes:
  - 2D Mono (Left Eye Only / Right Eye Only)
  - Anaglyph Red/Cyan (Dubois High-Quality / Half-Color / Full-Color)
  - Anaglyph Green/Magenta (Dubois)
  - Anaglyph Amber/Blue (ColorCode 3D)
  - Line Interleaved / Row Interleaved (Passive Polarized 3D TVs & Monitors)
  - Column Interleaved (Autostereoscopic 3D)
  - Checkerboard (DLP 3D Ready Projectors)
  - Side-by-Side (VR headsets / 3D TVs)
  - Top-and-Bottom (Over-Under)
  - Frame Interleaved / Alternating Sequential 3D (120Hz / 144Hz Active Shutter)
  - Swap Left / Right Eyes
"""

import os
import re
from typing import Optional, Dict, Any, Tuple, List


class Stereo3DEngine:
    """Core controller for stereoscopic 3D decoding, conversion, and presentation."""

    INPUT_FORMATS = {
        "auto": "Auto-Detect Format",
        "sbs2l": "Side-by-Side (Half Width, Left First)",
        "sbs2r": "Side-by-Side (Half Width, Right First)",
        "sbsl": "Side-by-Side (Full Width, Left First)",
        "sbsr": "Side-by-Side (Full Width, Right First)",
        "ab2l": "Top-and-Bottom / Over-Under (Half Height, Left First)",
        "ab2r": "Top-and-Bottom / Over-Under (Half Height, Right First)",
        "abl": "Top-and-Bottom / Over-Under (Full Height, Left First)",
        "abr": "Top-and-Bottom / Over-Under (Full Height, Right First)",
        "al": "Frame Interleaved / Alternating (Left First)",
        "ar": "Frame Interleaved / Alternating (Right First)",
        "irl": "Line Interleaved / Row (Left First)",
        "irr": "Line Interleaved / Row (Right First)",
        "icl": "Column Interleaved (Left First)",
        "icr": "Column Interleaved (Right First)",
    }

    OUTPUT_MODES = {
        "mono_l": "Left Eye Only (2D Mono)",
        "mono_r": "Right Eye Only (2D Mono)",
        "anaglyph_arcd": "Anaglyph Red-Cyan (Dubois High-Quality)",
        "anaglyph_arch": "Anaglyph Red-Cyan (Half Color)",
        "anaglyph_arcc": "Anaglyph Red-Cyan (Full Color)",
        "anaglyph_agmd": "Anaglyph Green-Magenta (Dubois)",
        "anaglyph_aybd": "Anaglyph Amber-Blue (ColorCode 3D)",
        "interleave_rows": "Line Interleaved (Row / Passive Polarized 3D)",
        "interleave_cols": "Column Interleaved (Autostereoscopic)",
        "checkerboard": "Checkerboard (DLP 3D Ready)",
        "sbs2l": "Side-by-Side (Half Width for 3D TV / VR)",
        "ab2l": "Top-and-Bottom (Half Height)",
        "frame_interleaved": "Frame Interleaved (120Hz/144Hz Active Shutter)",
    }

    # Mapping internal output mode keys to ffmpeg stereo3d out parameter values
    FFMPEG_OUT_MAP = {
        "mono_l": "ml",
        "mono_r": "mr",
        "anaglyph_arcd": "arcd",
        "anaglyph_arch": "arch",
        "anaglyph_arcc": "arcc",
        "anaglyph_agmd": "agmd",
        "anaglyph_aybd": "aybd",
        "interleave_rows": "irl",
        "interleave_cols": "icl",
        "checkerboard": "chl",
        "sbs2l": "sbs2l",
        "ab2l": "ab2l",
        "frame_interleaved": "al",
    }

    def __init__(self, mpv_player=None):
        self.player = mpv_player
        self.enabled: bool = False
        self.input_format: str = "auto"
        self.output_mode: str = "anaglyph_arcd"
        self.swap_eyes: bool = False
        self.detected_input_format: str = "sbs2l"
        self.current_uri: str = ""
        self.is_dcp: bool = False
        self.parallax_offset: int = 0  # Horizontal convergence offset (-60 to +60 pixels)
        self.on_mode_change = None

    def set_player(self, mpv_player):
        self.player = mpv_player

    @staticmethod
    def detect_3d_format_from_filename(filename: str) -> Optional[str]:
        """Auto-detect explicit 3D packing format from file path or title tags."""
        if not filename:
            return None
        fn = os.path.basename(filename).upper()

        # Side-by-side matches
        if any(tag in fn for tag in ["H-SBS", "HSBS", "HALF-SBS", "HALF.SBS", "H_SBS"]):
            return "sbs2l"
        if any(tag in fn for tag in [".SBS.", "-SBS.", "_SBS.", " SBS ", "FULL-SBS", "FULLSBS"]):
            return "sbsl"

        # Top-and-Bottom / Over-Under matches
        if any(tag in fn for tag in ["H-TAB", "HTAB", "HALF-TAB", "HALF-OU", "HOU", "H-OU"]):
            return "ab2l"
        if any(tag in fn for tag in [".TAB.", "-TAB.", ".OU.", "-OU.", "TOP-AND-BOTTOM", "OVER-UNDER"]):
            return "abl"

        # Frame interleaved / Sequential
        if any(tag in fn for tag in ["FRAME-SEQUENTIAL", "FRAMESEQUENTIAL", "INTERLEAVED-3D"]):
            return "al"

        return None

    @classmethod
    def check_has_dual_video_streams_same_index(
        cls,
        probe_data: Optional[Dict[str, Any]] = None,
        mpv_tracks: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Check whether the media has 2 video streams sharing the same stream index.
        Unless there are 2 video streams with the same index, media is not considered 3D.
        """
        if probe_data:
            raw_streams = probe_data.get("streams", [])
            v_indices = []
            if raw_streams:
                for s in raw_streams:
                    if s.get("codec_type") == "video":
                        idx = s.get("index")
                        if idx is not None:
                            v_indices.append(idx)
            elif "video_tracks" in probe_data:
                for t in probe_data["video_tracks"]:
                    idx = t.get("index")
                    if idx is not None:
                        v_indices.append(idx)

            if len(v_indices) >= 2 and len(v_indices) > len(set(v_indices)):
                return True

        if mpv_tracks:
            v_ff_indices = []
            for t in mpv_tracks:
                if t.get("type") == "video":
                    ff_idx = t.get("ff-index")
                    if ff_idx is not None:
                        v_ff_indices.append(ff_idx)
            if len(v_ff_indices) >= 2 and len(v_ff_indices) > len(set(v_ff_indices)):
                return True

        return False

    def configure_for_media(
        self,
        uri: str,
        is_dcp: bool = False,
        is_stereoscopic_dcp: bool = False,
        probe_data: Optional[Dict[str, Any]] = None,
        mpv_tracks: Optional[List[Dict[str, Any]]] = None,
    ):
        """Analyze newly opened media and verify if stereoscopic 3D streams exist."""
        self.current_uri = uri
        self.is_dcp = is_dcp

        if is_dcp:
            if is_stereoscopic_dcp:
                self.detected_input_format = "al"
                self.enabled = True
            else:
                self.detected_input_format = None
                self.enabled = False
            return

        # Unless there are 2 video streams with the same index, media is strictly 2D.
        has_dual = self.check_has_dual_video_streams_same_index(probe_data=probe_data, mpv_tracks=mpv_tracks)
        if not has_dual:
            was_enabled = self.enabled
            self.detected_input_format = None
            self.enabled = False
            # Only trigger mpv filter cleanup if 3D was enabled or vf holds stereo3d filters
            if self.player:
                self._apply_mpv_filter()
            return

        # If dual streams with same index are present, detect packing format or default to Half SBS
        detected = self.detect_3d_format_from_filename(uri)
        self.detected_input_format = detected or "sbs2l"
        self.enabled = True

    def get_effective_input_format(self) -> str:
        """Resolve 'auto' to actual detected input format, with eye swapping if requested."""
        raw_in = (self.detected_input_format or "sbs2l") if self.input_format == "auto" else self.input_format

        if not self.swap_eyes:
            return raw_in

        # Swap L <-> R in input tag
        swap_map = {
            "sbs2l": "sbs2r",
            "sbs2r": "sbs2l",
            "sbsl": "sbsr",
            "sbsr": "sbsl",
            "ab2l": "ab2r",
            "ab2r": "ab2l",
            "abl": "abr",
            "abr": "abl",
            "al": "ar",
            "ar": "al",
            "irl": "irr",
            "irr": "irl",
            "icl": "icr",
            "icr": "icl",
        }
        return swap_map.get(raw_in, raw_in)

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        self.apply()

    def set_input_format(self, in_fmt: str):
        if in_fmt in self.INPUT_FORMATS:
            self.input_format = in_fmt
            self.apply()

    def set_output_mode(self, out_mode: str):
        if out_mode in self.OUTPUT_MODES:
            self.output_mode = out_mode
            if not self.enabled:
                self.enabled = True
            self.apply()

    def toggle_swap_eyes(self):
        self.swap_eyes = not self.swap_eyes
        self.apply()

    def set_swap_eyes(self, swap: bool):
        self.swap_eyes = bool(swap)
        self.apply()

    def set_parallax_offset(self, offset_px: int):
        """Set horizontal parallax convergence offset in pixels (-60 to +60 px)."""
        self.parallax_offset = max(-60, min(60, int(offset_px)))
        self.apply()

    def reset_parallax(self):
        """Reset parallax convergence to neutral screen plane (0 px)."""
        self.parallax_offset = 0
        self.apply()

    def reset(self):
        self.enabled = False
        self.input_format = "auto"
        self.output_mode = "anaglyph_arcd"
        self.swap_eyes = False
        self.parallax_offset = 0
        self.apply()

    def get_status_summary(self) -> Dict[str, Any]:
        eff_in = self.get_effective_input_format()
        in_name = self.INPUT_FORMATS.get(eff_in, eff_in)
        out_name = self.OUTPUT_MODES.get(self.output_mode, self.output_mode)
        return {
            "enabled": self.enabled,
            "input_format": self.input_format,
            "effective_input": eff_in,
            "input_label": in_name,
            "output_mode": self.output_mode,
            "output_label": out_name,
            "swap_eyes": self.swap_eyes,
            "parallax_offset": self.parallax_offset,
            "is_dcp": self.is_dcp,
        }

    def apply(self):
        """Apply stereoscopic 3D filter to mpv or notify callbacks."""
        summary = self.get_status_summary()

        if self.player and not self.is_dcp:
            self._apply_mpv_filter()

        if callable(self.on_mode_change):
            try:
                self.on_mode_change(summary)
            except Exception:
                pass

    def _apply_mpv_filter(self):
        if not self.player:
            return

        try:
            current_vf = getattr(self.player, "vf", None) or []
            # Keep non-stereo3d filters (e.g. hflip, vflip)
            cleaned_vf = []
            if isinstance(current_vf, list):
                for f in current_vf:
                    if isinstance(f, dict) and f.get("name") != "stereo3d":
                        cleaned_vf.append(f)
                    elif isinstance(f, str) and not f.startswith("stereo3d"):
                        cleaned_vf.append(f)
            elif isinstance(current_vf, str) and current_vf:
                parts = [p.strip() for p in current_vf.split(",") if p.strip()]
                cleaned_vf = [p for p in parts if not p.startswith("stereo3d")]

            if self.enabled:
                in_code = self.get_effective_input_format()
                out_code = self.FFMPEG_OUT_MAP.get(self.output_mode, "arcd")
                s3d_filter = f"stereo3d=in={in_code}:out={out_code}"

                if isinstance(cleaned_vf, list) and all(isinstance(x, str) for x in cleaned_vf):
                    new_vf = ",".join(cleaned_vf + [s3d_filter]) if cleaned_vf else s3d_filter
                    self.player["vf"] = new_vf
                else:
                    # Append dict form if list of dicts
                    cleaned_vf.append({"name": "stereo3d", "params": {"in": in_code, "out": out_code}})
                    self.player["vf"] = cleaned_vf
            else:
                has_s3d = False
                if isinstance(current_vf, list):
                    has_s3d = any(
                        (isinstance(f, dict) and f.get("name") == "stereo3d")
                        or (isinstance(f, str) and f.startswith("stereo3d"))
                        for f in current_vf
                    )
                elif isinstance(current_vf, str) and current_vf:
                    has_s3d = any(p.strip().startswith("stereo3d") for p in current_vf.split(",") if p.strip())

                # Only re-assign player["vf"] if a stereo3d filter was actually present and needs to be stripped.
                # Never assign to player["vf"] when it is already clean 2D, avoiding decoder pipeline flushes.
                if has_s3d:
                    if isinstance(cleaned_vf, list) and all(isinstance(x, str) for x in cleaned_vf):
                        self.player["vf"] = ",".join(cleaned_vf)
                    else:
                        self.player["vf"] = cleaned_vf
                else:
                    pass
        except Exception:
            pass
