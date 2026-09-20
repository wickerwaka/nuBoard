"""Stress accounting must distinguish complete captures from valid prefixes."""

import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from . import stress
from .scope import Capture, encode_samples


class StressTests(unittest.TestCase):
    def test_execution_gate_rejects_timing_or_signature_changes(self):
        result = {"passed": True, "clock_divider": 5, "wait_ticks": 8,
                  "elapsed_ticks": 1000, "model_total": 8,
                  "model_signature": 42, "model_result": 1, "model_trace": []}
        self.assertTrue(stress.check_execution(result, result, "model")["functional_match"])
        for field in ("elapsed_ticks", "model_total", "model_signature"):
            changed = dict(result, **{field: result[field] + 1})
            with self.assertRaisesRegex(RuntimeError, field):
                stress.check_execution(result, changed, "model")

    def test_program_bounds_and_branch_displacements(self):
        for pattern, displacement in (("nop", -4), ("read", -6)):
            image = stress.stress_image(65536, pattern)
            program = image[0x10000]
            self.assertEqual(program[:4], bytes.fromhex("303c ffff"))
            branch = program.index(bytes.fromhex("51c8"))
            offset = struct.unpack_from(">h", program, branch + 2)[0]
            self.assertEqual(offset, displacement)
            self.assertEqual(branch + 2 + offset, 6)
        for count in (0, 65537):
            with self.assertRaises(ValueError):
                stress.stress_image(count, "nop")

    def test_metrics_check_clock_edges_and_truncation(self):
        raw = encode_samples([((tick // 5) & 1) << 49 for tick in range(100)])
        capture = Capture("model", "complete", 0, 99, 0, len(raw)//8,
                          len(raw)//8, 10, raw)
        metrics = stress.capture_metrics(capture, 100)
        self.assertEqual(metrics["captured_duration_ms"], 0.002)
        self.assertEqual(metrics["clock_edges_checked"], 19)
        corrupted = encode_samples([((tick // 6) & 1) << 49 for tick in range(100)])
        capture = Capture("model", "complete", 0, 99, 0, len(corrupted)//8,
                          len(corrupted)//8, 10, corrupted)
        with self.assertRaisesRegex(RuntimeError, "clock edge"):
            stress.capture_metrics(capture, 100)

    def test_failed_geometry_never_powers_socket_and_saves_failure(self):
        state = {"link": True, "vccb": False, "core_build": 14,
                 "core_uuid": b"nuBoard-68000-v1".hex(), "sha256": "checked"}
        off = {"vccb": False, "rail_1v2": False, "rail_3v3": False}
        board = Mock()
        board.state.side_effect = [json.dumps(state), json.dumps(off)]
        scope = Mock()
        scope.initialize.side_effect = RuntimeError("memory failed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "build/fpga/m68000/receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"capture_storage": "bram", "bitstream_sha256": "checked"}))
            output = root / "stress.json"
            with patch("sys.argv", ["stress", "--backend", "board", "--lane", "both",
                                    "--socket-fitted", "--output", str(output)]), \
                 patch.object(stress, "ROOT", root), \
                 patch.object(stress, "NuBoard", return_value=board), \
                 patch.object(stress, "Scope", return_value=scope), \
                 patch.object(stress, "Harness") as harness:
                with self.assertRaisesRegex(RuntimeError, "memory failed"):
                    stress.main()
                harness.return_value.run.assert_not_called()
            report = json.loads(output.read_text())
        self.assertFalse(report["completed"])
        self.assertEqual(report["shutdown_state"], off)
        board.vccb_enable.assert_not_called()
        board.power_off.assert_called_once()
        board.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
