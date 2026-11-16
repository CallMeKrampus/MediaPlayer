"""
Unit tests for DCP Cryptographic Hash Verification (PKL SHA-1 / SHA-256 QC Integrity).
"""

import os
import tempfile
import base64
import hashlib
import unittest
from PyQt6.QtWidgets import QApplication

# Ensure QApplication exists for QThread signals
app = QApplication.instance() or QApplication([])

from core.dcp_verifier import DCPVerifierThread, AssetVerificationResult
from core.dcp_parser import DCPPackage, DCPAsset


class TestDCPVerifier(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dcp_dir = self.temp_dir.name

        # Create dummy MXF file
        self.mxf_file = os.path.join(self.dcp_dir, "test_reel_pic.mxf")
        self.mxf_content = b"DCI_JPEG2000_TEST_ESSENCE_BLOCK_CONTENT_12345" * 100
        with open(self.mxf_file, "wb") as f:
            f.write(self.mxf_content)

        # Expected SHA-1
        raw_sha1 = hashlib.sha1(self.mxf_content).digest()
        self.expected_b64_sha1 = base64.b64encode(raw_sha1).decode("ascii")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_verify_valid_asset_sha1(self):
        assets = [{
            "uuid": "test-uuid-1",
            "original_filename": "test_reel_pic.mxf",
            "file_path": self.mxf_file,
            "size": len(self.mxf_content),
            "expected_hash": self.expected_b64_sha1,
            "hash_algo": "SHA-1",
        }]

        verifier = DCPVerifierThread(assets)
        results = []
        verifier.asset_completed.connect(results.append)
        verifier.run()

        self.assertEqual(len(results), 1)
        res: AssetVerificationResult = results[0]
        self.assertEqual(res.status, "PASSED")
        self.assertEqual(res.calculated_hash, self.expected_b64_sha1)
        self.assertEqual(res.actual_size, len(self.mxf_content))
        self.assertGreater(res.throughput_mb_s, 0.0)

    def test_verify_corrupted_hash_mismatch(self):
        assets = [{
            "uuid": "test-uuid-2",
            "original_filename": "test_reel_pic.mxf",
            "file_path": self.mxf_file,
            "size": len(self.mxf_content),
            "expected_hash": "WRONG_BASE64_HASH_VALUE==",
            "hash_algo": "SHA-1",
        }]

        verifier = DCPVerifierThread(assets)
        results = []
        verifier.asset_completed.connect(results.append)
        verifier.run()

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.status, "FAILED")
        self.assertIn("Hash mismatch", res.error_message)

    def test_verify_missing_file(self):
        assets = [{
            "uuid": "test-uuid-missing",
            "original_filename": "non_existent.mxf",
            "file_path": os.path.join(self.dcp_dir, "non_existent.mxf"),
            "size": 5000,
            "expected_hash": "ANY_HASH==",
            "hash_algo": "SHA-1",
        }]

        verifier = DCPVerifierThread(assets)
        results = []
        verifier.asset_completed.connect(results.append)
        verifier.run()

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.status, "MISSING")
        self.assertIn("not found", res.error_message)

    def test_verify_size_mismatch(self):
        assets = [{
            "uuid": "test-uuid-size",
            "original_filename": "test_reel_pic.mxf",
            "file_path": self.mxf_file,
            "size": len(self.mxf_content) + 999,
            "expected_hash": self.expected_b64_sha1,
            "hash_algo": "SHA-1",
        }]

        verifier = DCPVerifierThread(assets)
        results = []
        verifier.asset_completed.connect(results.append)
        verifier.run()

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.status, "SIZE_MISMATCH")
        self.assertIn("Size mismatch", res.error_message)

    def test_package_get_verifiable_assets(self):
        pkg = DCPPackage(
            root_path=self.dcp_dir,
            asset_map_path=os.path.join(self.dcp_dir, "ASSETMAP.xml"),
            standard="SMPTE",
            assets={
                "u1": DCPAsset(
                    uuid="u1",
                    relative_path="test_reel_pic.mxf",
                    absolute_path=self.mxf_file,
                    size_bytes=len(self.mxf_content),
                    expected_hash=self.expected_b64_sha1,
                    hash_algorithm="SHA-1"
                ),
                "u2": DCPAsset(
                    uuid="u2",
                    relative_path="ASSETMAP.xml",
                    absolute_path=os.path.join(self.dcp_dir, "ASSETMAP.xml"),
                    is_pkl=False
                )
            }
        )
        verifiable = pkg.get_verifiable_assets()
        self.assertEqual(len(verifiable), 1)
        self.assertEqual(verifiable[0]["uuid"], "u1")
        self.assertEqual(verifiable[0]["expected_hash"], self.expected_b64_sha1)

    def test_dcp_inspector_dialog_empty_launch(self):
        """Verify DCPInspectorDialog instantiates cleanly without a loaded package."""
        from ui.dcp_dialog import DCPInspectorDialog
        dlg = DCPInspectorDialog(dcp_package=None)
        self.assertIsNone(dlg.dcp)
        self.assertEqual(dlg.lbl_title.text(), "Composition: No DCP Loaded")
        dlg.close()

    def test_mainwindow_dcp_cinema_button_click(self):
        """Verify clicking 🎬 DCP Cinema button opens DCPInspectorDialog without crashing."""
        from unittest.mock import patch
        from PyQt6.QtWidgets import QDialog
        from ui.main_window import MainWindow

        win = MainWindow()
        try:
            with patch.object(QDialog, "exec", return_value=0):
                # Emit open_dcp_clicked signal as triggered by btn_dcp
                win.osc.open_dcp_clicked.emit()
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
