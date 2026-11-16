"""
BOOB Player - Digital Cinema Package (DCP) Cryptographic Integrity Verifier
Validates SHA-1 and SHA-256 essence checksums against the Packing List (PKL.xml).
Detects missing, corrupted, truncated, or tampered picture/sound/subtitle MXF assets.
"""

import os
import base64
import hashlib
import time
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable, Any
from PyQt6.QtCore import QThread, pyqtSignal


@dataclass
class AssetVerificationResult:
    uuid: str
    original_filename: str
    file_path: str
    expected_size: int
    actual_size: int
    expected_hash: str
    calculated_hash: str
    hash_algorithm: str
    status: str  # "PASSED", "FAILED", "MISSING", "SIZE_MISMATCH"
    error_message: str = ""
    duration_sec: float = 0.0
    throughput_mb_s: float = 0.0


class DCPVerifierThread(QThread):
    """
    Background worker thread calculating block-level SHA-1 / SHA-256 checksums
    across multi-gigabyte theatrical MXF containers without freezing the UI.
    """
    # Signals
    asset_started = pyqtSignal(str, str, int)                 # uuid, filename, size_bytes
    asset_progress = pyqtSignal(str, int, int, float)         # uuid, bytes_processed, total_bytes, mb_s
    asset_completed = pyqtSignal(object)                      # AssetVerificationResult
    overall_progress = pyqtSignal(int, int, float)            # completed_assets, total_assets, overall_mb_s
    verification_finished = pyqtSignal(bool, list)            # all_passed, list of AssetVerificationResult

    CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB read blocks for maximum NVMe/SATA throughput

    def __init__(self, pkl_assets: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.pkl_assets = pkl_assets
        self._is_cancelled = False

    def cancel(self):
        """Request immediate thread cancellation."""
        self._is_cancelled = True

    def run(self):
        results: List[AssetVerificationResult] = []
        total_assets = len(self.pkl_assets)
        total_bytes_processed = 0
        overall_start_time = time.perf_counter()

        for idx, asset in enumerate(self.pkl_assets):
            if self._is_cancelled:
                break

            uuid = asset.get("uuid", "")
            filename = asset.get("original_filename") or os.path.basename(asset.get("file_path", ""))
            file_path = asset.get("file_path", "")
            expected_size = asset.get("size", 0)
            expected_hash = asset.get("expected_hash", "").strip()
            hash_algo = asset.get("hash_algo", "SHA-1").upper()

            self.asset_started.emit(uuid, filename, expected_size)

            # Check existence
            if not file_path or not os.path.exists(file_path):
                res = AssetVerificationResult(
                    uuid=uuid,
                    original_filename=filename,
                    file_path=file_path,
                    expected_size=expected_size,
                    actual_size=0,
                    expected_hash=expected_hash,
                    calculated_hash="",
                    hash_algorithm=hash_algo,
                    status="MISSING",
                    error_message="Asset file not found on disk"
                )
                results.append(res)
                self.asset_completed.emit(res)
                self.overall_progress.emit(idx + 1, total_assets, 0.0)
                continue

            # Check size
            actual_size = os.path.getsize(file_path)
            if expected_size > 0 and actual_size != expected_size:
                res = AssetVerificationResult(
                    uuid=uuid,
                    original_filename=filename,
                    file_path=file_path,
                    expected_size=expected_size,
                    actual_size=actual_size,
                    expected_hash=expected_hash,
                    calculated_hash="",
                    hash_algorithm=hash_algo,
                    status="SIZE_MISMATCH",
                    error_message=f"Size mismatch: expected {expected_size:,} bytes, found {actual_size:,} bytes"
                )
                results.append(res)
                self.asset_completed.emit(res)
                self.overall_progress.emit(idx + 1, total_assets, 0.0)
                continue

            # Compute Hash
            hasher = hashlib.sha256() if "256" in hash_algo else hashlib.sha1()
            bytes_read = 0
            asset_start_time = time.perf_counter()
            error_msg = ""
            status = "FAILED"
            calc_hash_b64 = ""

            try:
                with open(file_path, "rb") as f:
                    while True:
                        if self._is_cancelled:
                            break
                        chunk = f.read(self.CHUNK_SIZE)
                        if not chunk:
                            break
                        hasher.update(chunk)
                        bytes_read += len(chunk)
                        total_bytes_processed += len(chunk)

                        elapsed = max(0.001, time.perf_counter() - asset_start_time)
                        cur_mb_s = (bytes_read / (1024 * 1024)) / elapsed
                        self.asset_progress.emit(uuid, bytes_read, actual_size, cur_mb_s)

                if self._is_cancelled:
                    break

                digest = hasher.digest()
                calc_hash_b64 = base64.b64encode(digest).decode("ascii")
                calc_hash_hex = hasher.hexdigest().lower()

                # Compare against expected hash
                # Expected hash in PKL is standard base64 string, occasionally hex in non-standard tools
                exp_clean = expected_hash.strip()
                if exp_clean == calc_hash_b64 or exp_clean.lower() == calc_hash_hex:
                    status = "PASSED"
                elif not exp_clean:
                    status = "PASSED"  # No expected hash specified in PKL
                else:
                    status = "FAILED"
                    error_msg = "Hash mismatch: file contents have been modified or corrupted"

            except Exception as e:
                status = "FAILED"
                error_msg = f"Read error: {str(e)}"

            asset_elapsed = max(0.001, time.perf_counter() - asset_start_time)
            mb_s = (bytes_read / (1024 * 1024)) / asset_elapsed

            res = AssetVerificationResult(
                uuid=uuid,
                original_filename=filename,
                file_path=file_path,
                expected_size=expected_size,
                actual_size=actual_size,
                expected_hash=expected_hash,
                calculated_hash=calc_hash_b64,
                hash_algorithm=hash_algo,
                status=status,
                error_message=error_msg,
                duration_sec=asset_elapsed,
                throughput_mb_s=mb_s
            )
            results.append(res)
            self.asset_completed.emit(res)

            overall_elapsed = max(0.001, time.perf_counter() - overall_start_time)
            overall_mb_s = (total_bytes_processed / (1024 * 1024)) / overall_elapsed
            self.overall_progress.emit(idx + 1, total_assets, overall_mb_s)

        all_passed = (
            len(results) == total_assets
            and all(r.status == "PASSED" for r in results)
            and not self._is_cancelled
        )
        self.verification_finished.emit(all_passed, results)
