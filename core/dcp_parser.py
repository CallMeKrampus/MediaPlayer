"""
BOOB Player - Digital Cinema Package (DCP) Parser & Synchronizer
Parses SMPTE and Interop DCPs: ASSETMAP, PKL (Packing List), and CPL (Composition Playlist).
Resolves MXF picture and sound assets down to the exact frame for synchronized cinema playback.
"""

import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any


def _strip_ns(tag: str) -> str:
    """Strip XML namespace prefix from tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _clean_uuid(uuid_str: str) -> str:
    """Normalize UUID by removing 'urn:uuid:' prefix and lowering case."""
    if not uuid_str:
        return ""
    clean = uuid_str.strip()
    if clean.lower().startswith("urn:uuid:"):
        clean = clean[9:]
    return clean.lower()


def frames_to_timecode(frames: int, fps: float = 24.0) -> str:
    """Convert frame count to SMPTE Timecode HH:MM:SS:FF."""
    if fps <= 0:
        fps = 24.0
    int_fps = int(round(fps))
    total_sec = int(frames // int_fps)
    rem_frames = int(frames % int_fps)
    
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    seconds = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{rem_frames:02d}"


@dataclass
class DCPAsset:
    uuid: str
    relative_path: str
    absolute_path: str
    mime_type: str = ""
    size_bytes: int = 0
    is_pkl: bool = False
    expected_hash: str = ""
    hash_algorithm: str = "SHA-1"
    original_filename: str = ""


@dataclass
class DCPReel:
    reel_id: str
    index: int
    # Main Picture Asset
    picture_uuid: str = ""
    picture_path: str = ""
    picture_fps: float = 24.0
    picture_duration_frames: int = 0
    picture_entry_point: int = 0
    screen_aspect_ratio: str = "Flat (1.85:1)"
    
    # Main Sound Asset (PCM)
    sound_uuid: str = ""
    sound_path: str = ""
    sound_duration_frames: int = 0
    sound_entry_point: int = 0
    sound_channels: int = 6  # 5.1 default
    sound_language: str = "und"

    # Dolby Atmos / Immersive Audio (AuxData)
    atmos_uuid: str = ""
    atmos_path: str = ""
    
    # Main Subtitle Asset
    subtitle_uuid: str = ""
    subtitle_path: str = ""

    # IMAX & Anamorphic Delivery Flags
    is_imax: bool = False
    is_laser_squeezed: bool = False
    is_imax_gt_143: bool = False
    imax_audio_format: str = ""
    unsqueeze_to_143: bool = False
    is_stereoscopic_3d: bool = False

    # Dolby Cinema EDR / Dolby Vision Flags
    is_dolby_vision: bool = False
    target_luminance: int = 48
    transfer_function: str = "Gamma2.6"
    
    @property
    def duration_seconds(self) -> float:
        if self.picture_fps > 0:
            return self.picture_duration_frames / self.picture_fps
        return 0.0

    @property
    def timecode(self) -> str:
        return frames_to_timecode(self.picture_duration_frames, self.picture_fps)


@dataclass
class DCPComposition:
    cpl_id: str
    cpl_file_path: str
    title: str = "Untitled DCP"
    content_kind: str = "feature"
    standard: str = "SMPTE"
    creator: str = ""
    issue_date: str = ""
    edit_rate: Tuple[int, int] = (24, 1)
    issuer: str = ""
    annotation_text: str = ""
    is_imax: bool = False
    is_laser_squeezed: bool = False
    is_imax_gt_143: bool = False
    imax_audio_format: str = ""
    unsqueeze_to_143: bool = False
    is_3d: bool = False
    is_dolby_vision: bool = False
    target_luminance: int = 48
    transfer_function: str = "Gamma2.6"
    reels: List[DCPReel] = field(default_factory=list)

    @property
    def fps(self) -> float:
        num, den = self.edit_rate
        return num / den if den > 0 else 24.0

    @property
    def total_frames(self) -> int:
        return sum(reel.picture_duration_frames for reel in self.reels)

    @property
    def total_seconds(self) -> float:
        if self.fps > 0:
            return self.total_frames / self.fps
        return 0.0

    @property
    def total_timecode(self) -> str:
        return frames_to_timecode(self.total_frames, self.fps)


@dataclass
class DCPPackage:
    root_path: str
    asset_map_path: str
    standard: str
    assets: Dict[str, DCPAsset] = field(default_factory=dict)
    compositions: List[DCPComposition] = field(default_factory=list)
    pkl_files: List[str] = field(default_factory=list)
    pkl_records: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def default_composition(self) -> Optional[DCPComposition]:
        return self.compositions[0] if self.compositions else None

    def get_verifiable_assets(self) -> List[Dict[str, Any]]:
        """Return list of assets with expected hash, size, and absolute path for cryptographic verification."""
        results = []
        # First use pkl_records if populated
        if self.pkl_records:
            return self.pkl_records

        for uuid, asset in self.assets.items():
            if asset.is_pkl or asset.relative_path.lower().startswith("assetmap"):
                continue
            results.append({
                "uuid": asset.uuid,
                "original_filename": asset.original_filename or os.path.basename(asset.absolute_path),
                "file_path": asset.absolute_path,
                "size": asset.size_bytes,
                "expected_hash": asset.expected_hash,
                "hash_algo": asset.hash_algorithm,
            })
        return results


class DCPParser:
    @staticmethod
    def is_dcp_folder(folder_path: str) -> bool:
        """Check if folder contains DCP markers (ASSETMAP or ASSETMAP.xml)."""
        if not os.path.isdir(folder_path):
            return False
        for f in os.listdir(folder_path):
            f_lower = f.lower()
            if f_lower in ("assetmap", "assetmap.xml"):
                return True
        return False

    @classmethod
    def parse(cls, folder_path: str) -> DCPPackage:
        """Parse complete DCP folder and resolve all composition reels and assets."""
        if not os.path.isdir(folder_path):
            raise ValueError(f"Path is not a directory: {folder_path}")

        # 1. Locate ASSETMAP
        asset_map_name = None
        for f in os.listdir(folder_path):
            if f.lower() in ("assetmap", "assetmap.xml"):
                asset_map_name = f
                break

        if not asset_map_name:
            raise FileNotFoundError("DCP ASSETMAP not found in directory")

        asset_map_path = os.path.join(folder_path, asset_map_name)
        assets, standard = cls._parse_assetmap(asset_map_path, folder_path)

        # 2. Locate and parse PKL files
        pkl_files = []
        for asset in assets.values():
            if asset.is_pkl or asset.relative_path.lower().startswith("pkl"):
                pkl_files.append(asset.absolute_path)
                asset.mime_type = "text/xml"

        # Also search disk for PKL files if not flagged
        if not pkl_files:
            for f in os.listdir(folder_path):
                if f.lower().startswith("pkl") and f.lower().endswith(".xml"):
                    abs_p = os.path.join(folder_path, f)
                    if abs_p not in pkl_files:
                        pkl_files.append(abs_p)

        # Update asset mime types from PKL and extract verification records
        all_pkl_records: List[Dict[str, Any]] = []
        for pkl_p in pkl_files:
            recs = cls._enrich_assets_from_pkl(pkl_p, assets, folder_path)
            all_pkl_records.extend(recs)

        # 3. Locate and parse CPL files
        compositions = []
        cpl_paths = []
        
        # Check assets that are CPLs
        for asset in assets.values():
            p_lower = asset.relative_path.lower()
            if p_lower.startswith("cpl") and p_lower.endswith(".xml"):
                cpl_paths.append(asset.absolute_path)
            elif asset.mime_type in ("text/xml;charset=utf-8", "text/xml", "application/xml"):
                if p_lower.endswith(".xml") and not p_lower.startswith("pkl") and not p_lower.startswith("assetmap"):
                    cpl_paths.append(asset.absolute_path)

        # Check disk directly for CPL files
        for f in os.listdir(folder_path):
            if f.lower().startswith("cpl") and f.lower().endswith(".xml"):
                abs_p = os.path.join(folder_path, f)
                if abs_p not in cpl_paths:
                    cpl_paths.append(abs_p)

        for cpl_p in cpl_paths:
            try:
                cpl = cls._parse_cpl(cpl_p, assets, standard)
                if cpl:
                    compositions.append(cpl)
            except Exception as e:
                print(f"[DCPParser] Error parsing CPL {cpl_p}: {e}")

        return DCPPackage(
            root_path=folder_path,
            asset_map_path=asset_map_path,
            standard=standard,
            assets=assets,
            compositions=compositions,
            pkl_files=pkl_files,
            pkl_records=all_pkl_records,
        )

    @classmethod
    def _parse_assetmap(cls, asset_map_path: str, root_folder: str) -> Tuple[Dict[str, DCPAsset], str]:
        tree = ET.parse(asset_map_path)
        root = tree.getroot()
        standard = "SMPTE" if "smpte" in root.tag.lower() else "Interop"

        assets: Dict[str, DCPAsset] = {}

        for elem in root.iter():
            if _strip_ns(elem.tag) == "Asset":
                uuid = ""
                path = ""
                is_pkl = False

                for child in elem:
                    tag = _strip_ns(child.tag)
                    if tag == "Id":
                        uuid = _clean_uuid(child.text or "")
                    elif tag == "PackingList":
                        is_pkl = True
                    elif tag == "ChunkList":
                        for chunk in child:
                            if _strip_ns(chunk.tag) == "Chunk":
                                for chunk_child in chunk:
                                    if _strip_ns(chunk_child.tag) == "Path":
                                        path = (chunk_child.text or "").strip()

                if uuid and path:
                    # Unquote URL encoded filenames (e.g. %20 for space)
                    decoded_path = urllib.parse.unquote(path)
                    # Support file:/// prefix
                    if decoded_path.startswith("file://"):
                        decoded_path = decoded_path[7:]
                    
                    abs_path = os.path.join(root_folder, decoded_path)
                    assets[uuid] = DCPAsset(
                        uuid=uuid,
                        relative_path=decoded_path,
                        absolute_path=abs_path,
                        is_pkl=is_pkl,
                    )

        return assets, standard

    @classmethod
    def _enrich_assets_from_pkl(cls, pkl_path: str, assets: Dict[str, DCPAsset], root_folder: str = "") -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        if not os.path.exists(pkl_path):
            return records
        try:
            tree = ET.parse(pkl_path)
            root = tree.getroot()
            xml_str = ET.tostring(root).decode("latin-1", "ignore").lower()
            default_algo = "SHA-256" if "sha256" in xml_str else "SHA-1"

            for asset_elem in tree.getroot().iter():
                if _strip_ns(asset_elem.tag) == "Asset":
                    uuid = ""
                    mime = ""
                    size = 0
                    hash_val = ""
                    orig_fn = ""
                    hash_algo = default_algo

                    for child in asset_elem:
                        tag = _strip_ns(child.tag)
                        if tag == "Id":
                            uuid = _clean_uuid(child.text or "")
                        elif tag == "Type":
                            mime = (child.text or "").strip()
                        elif tag == "Size":
                            try:
                                size = int(child.text or 0)
                            except ValueError:
                                pass
                        elif tag == "Hash":
                            hash_val = (child.text or "").strip()
                        elif tag == "OriginalFileName":
                            orig_fn = (child.text or "").strip()
                        elif tag == "HashAlgorithm":
                            algo_text = (child.text or "").lower()
                            if "sha256" in algo_text:
                                hash_algo = "SHA-256"
                            elif "sha1" in algo_text:
                                hash_algo = "SHA-1"

                    file_p = ""
                    if uuid in assets:
                        assets[uuid].mime_type = mime
                        assets[uuid].size_bytes = size
                        assets[uuid].expected_hash = hash_val
                        assets[uuid].hash_algorithm = hash_algo
                        assets[uuid].original_filename = orig_fn
                        file_p = assets[uuid].absolute_path
                    elif orig_fn and root_folder:
                        cand = os.path.join(root_folder, orig_fn)
                        if os.path.exists(cand):
                            file_p = cand

                    records.append({
                        "uuid": uuid,
                        "original_filename": orig_fn or (os.path.basename(file_p) if file_p else uuid),
                        "file_path": file_p,
                        "size": size,
                        "expected_hash": hash_val,
                        "hash_algo": hash_algo,
                        "mime": mime,
                    })
        except Exception as e:
            print(f"[DCPParser] Error reading PKL {pkl_path}: {e}")
        return records

    @classmethod
    def _parse_cpl(cls, cpl_path: str, assets: Dict[str, DCPAsset], default_standard: str) -> Optional[DCPComposition]:
        tree = ET.parse(cpl_path)
        root = tree.getroot()
        standard = "SMPTE" if "smpte" in root.tag.lower() else default_standard

        cpl_id = ""
        title = "Untitled DCP"
        content_kind = "feature"
        creator = ""
        issuer = ""
        annotation_text = ""
        issue_date = ""
        edit_rate = (24, 1)
        signer_text = ""

        for child in root:
            tag = _strip_ns(child.tag)
            if tag == "Id":
                cpl_id = _clean_uuid(child.text or "")
            elif tag == "ContentTitleText":
                title = child.text or title
            elif tag == "AnnotationText":
                annotation_text = child.text or annotation_text
            elif tag == "Issuer":
                issuer = child.text or issuer
            elif tag == "ContentKind":
                content_kind = child.text or content_kind
            elif tag == "Creator":
                creator = child.text or creator
            elif tag == "IssueDate":
                issue_date = child.text or issue_date
            elif tag == "EditRate":
                edit_rate = cls._parse_rate(child.text or "24 1")
            elif tag == "Signer":
                signer_text = " ".join(t.strip() for t in child.itertext() if t and t.strip())

        cpl_folder = os.path.dirname(cpl_path)
        cpl_flags = cls.detect_imax_flags(cpl_folder, cpl_path, title, annotation_text, issuer, signer_text)

        # Detect Dolby Vision / Dolby Cinema EDR flags
        is_dolby_vision = False
        target_luminance = 48
        transfer_function = "Gamma2.6"

        for elem in root.iter():
            tag = _strip_ns(elem.tag)
            if tag == "Luminance":
                try:
                    lum = int(elem.text or 48)
                    if lum >= 100:
                        is_dolby_vision = True
                        target_luminance = lum
                        transfer_function = "PQ10K"
                except Exception:
                    pass
            elif tag == "ExtensionMetadata":
                scope = elem.attrib.get("scope", "").lower()
                if "edr-metadata" in scope or "dolby" in scope:
                    is_dolby_vision = True
                    for sub in elem.iter():
                        if _strip_ns(sub.tag) == "Value" and sub.text and "pq" in sub.text.lower():
                            transfer_function = sub.text.strip()
                            target_luminance = 108

        name_check = f"{title} {annotation_text} {cpl_path}".lower()
        if any(k in name_check for k in ["dvis", "dolbyvision", "dolby vision", "dolby-vision", "edr"]):
            is_dolby_vision = True
            if target_luminance == 48:
                target_luminance = 108
                transfer_function = "PQ10K"

        reels: List[DCPReel] = []
        reel_idx = 1

        for reel_elem in root.iter():
            if _strip_ns(reel_elem.tag) == "Reel":
                reel_id = ""
                pic_uuid = ""
                pic_fps = float(edit_rate[0]) / float(edit_rate[1])
                pic_dur = 0
                pic_entry = 0
                aspect_ratio = "Flat (1.85:1)"

                snd_uuid = ""
                snd_dur = 0
                snd_entry = 0
                snd_lang = "und"
                snd_channels = 0
                atmos_uuid = ""

                sub_uuid = ""
                is_stereo_reel = False

                for rchild in reel_elem:
                    rtag = _strip_ns(rchild.tag)
                    if rtag == "Id":
                        reel_id = _clean_uuid(rchild.text or "")
                    elif rtag == "AssetList":
                        for aelem in rchild:
                            atag = _strip_ns(aelem.tag)
                            if atag in ("MainPicture", "MainStereoscopicPicture"):
                                if atag == "MainStereoscopicPicture":
                                    is_stereo_reel = True
                                for pchild in aelem:
                                    ptag = _strip_ns(pchild.tag)
                                    if ptag == "Id":
                                        pic_uuid = _clean_uuid(pchild.text or "")
                                    elif ptag in ("EditRate", "FrameRate"):
                                        rate = cls._parse_rate(pchild.text or "24 1")
                                        pic_fps = float(rate[0]) / float(rate[1])
                                    elif ptag == "Duration":
                                        pic_dur = int(pchild.text or 0)
                                    elif ptag == "EntryPoint":
                                        pic_entry = int(pchild.text or 0)
                                    elif ptag == "ScreenAspectRatio":
                                        aspect_ratio = cls._format_aspect_ratio(pchild.text or "")

                            elif atag == "MainSound":
                                for schild in aelem:
                                    stag = _strip_ns(schild.tag)
                                    if stag == "Id":
                                        snd_uuid = _clean_uuid(schild.text or "")
                                    elif stag == "Duration":
                                        snd_dur = int(schild.text or 0)
                                    elif stag == "EntryPoint":
                                        snd_entry = int(schild.text or 0)
                                    elif stag == "Language":
                                        snd_lang = (schild.text or "").strip()
                                    elif stag == "ChannelCount":
                                        try:
                                            snd_channels = int(schild.text or 0)
                                        except ValueError:
                                            pass

                            elif atag == "AuxData":
                                for achild in aelem:
                                    atag_c = _strip_ns(achild.tag)
                                    if atag_c == "Id":
                                        atmos_uuid = _clean_uuid(achild.text or "")

                            elif atag == "MainSubtitle":
                                for subchild in aelem:
                                    if _strip_ns(subchild.tag) == "Id":
                                        sub_uuid = _clean_uuid(subchild.text or "")

                # Resolve file paths from asset map
                pic_path = assets[pic_uuid].absolute_path if pic_uuid in assets else ""
                snd_path = assets[snd_uuid].absolute_path if snd_uuid in assets else ""
                atmos_path = assets[atmos_uuid].absolute_path if atmos_uuid in assets else ""
                sub_path = assets[sub_uuid].absolute_path if sub_uuid in assets else ""

                reel_flags = cls.detect_imax_flags(
                    cpl_folder, cpl_path, title, annotation_text, issuer, signer_text, pic_path, snd_path
                )
                if reel_flags["unsqueeze_to_143"]:
                    is_2k = ("2048" in aspect_ratio) or ("2K" in (pic_path or title).upper() and "4K" not in (pic_path or title).upper())
                    aspect_ratio = "IMAX GT 1.43:1 (Laser Squeezed 2048x1432)" if is_2k else "IMAX GT 1.43:1 (Laser Squeezed 4096x2864)"

                reels.append(DCPReel(
                    reel_id=reel_id or f"reel-{reel_idx}",
                    index=reel_idx,
                    picture_uuid=pic_uuid,
                    picture_path=pic_path,
                    picture_fps=pic_fps,
                    picture_duration_frames=pic_dur,
                    picture_entry_point=pic_entry,
                    screen_aspect_ratio=aspect_ratio,
                    sound_uuid=snd_uuid,
                    sound_path=snd_path,
                    sound_duration_frames=snd_dur,
                    sound_entry_point=snd_entry,
                    sound_channels=snd_channels if snd_channels > 0 else (16 if reel_flags["imax_audio_format"] == "IMAX12" else 6),
                    sound_language=snd_lang,
                    atmos_uuid=atmos_uuid,
                    atmos_path=atmos_path,
                    subtitle_uuid=sub_uuid,
                    subtitle_path=sub_path,
                    is_imax=bool(reel_flags["is_imax"]),
                    is_laser_squeezed=bool(reel_flags["is_laser_squeezed"]),
                    is_imax_gt_143=bool(reel_flags["is_imax_gt_143"]),
                    imax_audio_format=str(reel_flags["imax_audio_format"]),
                    unsqueeze_to_143=bool(reel_flags["unsqueeze_to_143"]),
                    is_stereoscopic_3d=bool(is_stereo_reel),
                    is_dolby_vision=bool(is_dolby_vision),
                    target_luminance=int(target_luminance),
                    transfer_function=str(transfer_function),
                ))
                reel_idx += 1

        comp_is_imax = bool(cpl_flags["is_imax"] or any(r.is_imax for r in reels))
        comp_is_ls = bool(cpl_flags["is_laser_squeezed"] or any(r.is_laser_squeezed for r in reels))
        comp_is_c143 = bool(cpl_flags["is_imax_gt_143"] or any(r.is_imax_gt_143 for r in reels))
        comp_audio_fmt = str(cpl_flags["imax_audio_format"] or next((r.imax_audio_format for r in reels if r.imax_audio_format), ""))
        comp_unsqueeze = bool(cpl_flags["unsqueeze_to_143"] or any(r.unsqueeze_to_143 for r in reels))
        comp_is_3d = bool(any(r.is_stereoscopic_3d for r in reels) or ("_3D" in title.upper()) or ("3D" in annotation_text.upper()))

        return DCPComposition(
            cpl_id=cpl_id,
            cpl_file_path=cpl_path,
            title=title,
            content_kind=content_kind,
            standard=standard,
            creator=creator,
            issue_date=issue_date,
            edit_rate=edit_rate,
            issuer=issuer,
            annotation_text=annotation_text,
            is_imax=comp_is_imax,
            is_laser_squeezed=comp_is_ls,
            is_imax_gt_143=comp_is_c143,
            imax_audio_format=comp_audio_fmt,
            unsqueeze_to_143=comp_unsqueeze,
            is_3d=comp_is_3d,
            is_dolby_vision=bool(is_dolby_vision),
            target_luminance=int(target_luminance),
            transfer_function=str(transfer_function),
            reels=reels,
        )

    @staticmethod
    def detect_imax_flags(*texts: str) -> Dict[str, Any]:
        """Detect IMAX (IMX), Laser Squeezed (-LS-), IMAX GT 1.43:1 (C-143), and IMAX5/IMAX12 audio tokens."""
        combined = " ".join(str(t) for t in texts if t)
        upper = combined.upper()
        is_ls = bool(re.search(r"(?:^|[-_])LS(?:[-_]|$)", upper))
        is_c143 = bool(re.search(r"(?:^|[-_])(?:C-?143|AR143)(?:[-_]|$)", upper))
        is_imax12 = bool(re.search(r"(?:^|[-_])(?:IMAX-?12|IX12|120CH)(?:[-_]|$)", upper))
        is_imax5 = bool(re.search(r"(?:^|[-_])(?:IMAX-?5|IX5|50CH)(?:[-_]|$)", upper))
        is_imx = (
            is_ls or is_c143 or is_imax12 or is_imax5
            or bool(re.search(r"(?:^|[-_.])(?:IMX|IMAX)(?:[-_.]|$)", upper))
        )
        audio_fmt = "IMAX12" if is_imax12 else ("IMAX5" if is_imax5 else "")
        return {
            "is_imax": is_imx,
            "is_laser_squeezed": is_ls,
            "is_imax_gt_143": is_c143,
            "imax_audio_format": audio_fmt,
            "unsqueeze_to_143": bool(is_ls or is_c143),
        }

    @staticmethod
    def _parse_rate(rate_str: str) -> Tuple[int, int]:
        parts = rate_str.strip().split()
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                pass
        elif len(parts) == 1:
            try:
                val = float(parts[0])
                return int(round(val * 1000)), 1000
            except ValueError:
                pass
        return 24, 1

    @staticmethod
    def _format_aspect_ratio(ratio_str: str) -> str:
        s = ratio_str.strip()
        if "4096" in s and "2160" in s:
            return "Full 4K DCI (1.896:1)"
        if "2048" in s and "1080" in s:
            return "Full 2K DCI (1.896:1)"
        if "1.85" in s:
            return "Flat (1.85:1)"
        if "2.39" in s or "2.40" in s or "2.38" in s:
            return "Scope (2.39:1)"
        if "1.90" in s or "1.896" in s:
            return "Full Container (1.90:1)"
        return s or "16:9"
