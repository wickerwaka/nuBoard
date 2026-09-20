"""The physical capture workflow must qualify BRAM geometry before powering the DUT."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from . import capture


class CaptureSafetyTests(unittest.TestCase):
    def failed_preflight(self, stage, cleanup_failure=False):
        before = {
            "link": True,
            "vccb": False,
            "rail_1v2": True,
            "rail_3v3": True,
            "selector_mv": 5000,
            "core_build": 14,
            "core_uuid": b"nuBoard-68000-v1".hex(),
            "sha256": "qualified-image",
        }
        after = dict(before, link=False, rail_1v2=False, rail_3v3=False)
        board = Mock()
        board.state.side_effect = [json.dumps(before), json.dumps(after)]
        if cleanup_failure:
            board.power_off.side_effect = RuntimeError("USB unavailable")
        scope = Mock()
        getattr(scope, stage).side_effect = RuntimeError(f"{stage} failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "build/fpga/m68000/receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"bitstream_sha256": "qualified-image"}))
            output = root / "failed-capture.json"
            arguments = [
                "capture", "--backend", "board", "--lane", "both",
                "--socket-fitted", "--output", str(output),
            ]
            with patch("sys.argv", arguments), \
                 patch.object(capture, "ROOT", root), \
                 patch.object(capture, "NuBoard", return_value=board), \
                 patch.object(capture, "Scope", return_value=scope), \
                 patch.object(capture, "Harness") as harness:
                with self.assertRaisesRegex(RuntimeError, f"{stage} failed"):
                    capture.main()
                harness.return_value.load.assert_not_called()
                harness.return_value.run.assert_not_called()
            report = json.loads(output.read_text())

        board.vccb_enable.assert_not_called()
        board.power_off.assert_called_once()
        board.close.assert_called_once()
        self.assertFalse(report["completed"])
        self.assertEqual(report["runs"], [])
        self.assertIn(f"{stage} failed", report["error"])
        if cleanup_failure:
            self.assertIn("USB unavailable", report["cleanup_error"])
            self.assertNotIn("shutdown_state", report)
        else:
            self.assertEqual(report["shutdown_state"], after)

    def test_initialization_failure_never_enables_vccb(self):
        self.failed_preflight("initialize")

    def test_disconnected_cleanup_preserves_failed_report(self):
        self.failed_preflight("initialize", cleanup_failure=True)


if __name__ == "__main__":
    unittest.main()
