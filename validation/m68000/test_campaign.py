"""Tests for corpus completeness accounting and propagation-tolerant comparison."""

from dataclasses import replace
from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .corpus import BEGIN, END, assembly, cases, defined_sr_mask
from .phase import compare, compare_state, phases
from .scope import Capture, encode_samples
from .campaign import load_manifest, merge, read_test, run, save_test, write_json
from .singlestep import register_instruction


def waveform(delay=0, extra=0, wrong_data=False, late=False):
    samples = []
    for tick in range(120 + extra):
        active = 20 + delay <= tick < 70 + extra + delay
        ack = 30 + delay <= tick < 70 + extra + delay
        word = (int(not active) << 40) | (int(not active) << 41) | (int(not active) << 42)
        word |= 1 << 43
        word |= int(not ack) << 44
        word |= 1 << 45
        word |= 5 << 46
        word |= ((tick // 5) & 1) << 49
        word |= 3 << 50
        word |= 0x2000
        word |= (0x1235 if wrong_data else 0x1234) << 24
        if late and tick == 33:
            word ^= 1 << 24
        samples.append(word)
    raw = encode_samples(samples)
    capture = Capture("model", "complete", 0, len(samples) - 1, 0,
                      len(raw) // 8, len(raw) // 8, len(raw) // 8, raw)
    trace = [{"address": BEGIN, "data": 0x1111, "flags": 3, "end": 10},
             {"address": END, "data": 0x2222, "flags": 3, "end": 90 + extra}]
    return {"capture": capture.report(), "trace": trace}


class PhaseTests(unittest.TestCase):
    def test_propagation_delay_is_not_a_cycle_difference(self):
        self.assertEqual(compare(waveform(), waveform(delay=1))["verdict"], "pass")
        self.assertEqual(compare(waveform(), waveform(delay=2))["verdict"], "pass")

    def test_half_cycle_and_full_cycle_are_not_hidden(self):
        for extra in (5, 10):
            self.assertEqual(compare(waveform(), waveform(extra=extra))["verdict"], "fail")

    def test_selected_data_is_checked(self):
        self.assertEqual(compare(waveform(), waveform(wrong_data=True))["verdict"], "fail")

    def test_explicit_undefined_data_bits_do_not_become_timing_failures(self):
        self.assertEqual(compare(waveform(), waveform(wrong_data=True),
                                 {0x2000: 0xFFFE})["verdict"], "pass")
        self.assertEqual(compare(waveform(), waveform(wrong_data=True),
                                 {0x2000: 0xFFF5})["verdict"], "fail")

    def test_unresolved_boundary_is_not_a_pass(self):
        self.assertEqual(compare(waveform(), waveform(late=True))["verdict"], "indeterminate")

    def test_capacity_prefix_is_not_a_timing_result(self):
        item = waveform()
        from .phase import from_report
        capture = replace(from_report(item["capture"]), reason="capacity")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            phases(capture, item["trace"])

    def test_wrong_or_missing_marker_is_invalid(self):
        item = waveform()
        item["trace"].pop()
        with self.assertRaisesRegex(ValueError, "marker"):
            compare(waveform(), item)

    def test_undefined_flags_are_separate(self):
        result = compare_state({"sr": 0x2700}, {"sr": 0x2708}, 0xFFF5)
        self.assertEqual(result["defined"], "pass")
        self.assertEqual(result["chip_compatibility"], "fail")

    def test_exception_pc_is_defined_not_blanket_masked(self):
        left = {"frame": "270000010000", "vector": 4, "ssp_at_collector": 0x3FEA}
        right = dict(left, frame="270000010002")
        self.assertEqual(compare_state(left, right, 0xFFFF)["defined"], "fail")

    def test_address_error_reserved_ssw_bits_are_chip_specific(self):
        left = {"frame": "0000" + "00" * 12, "vector": 3, "ssp_at_collector": 0x3FE2}
        right = dict(left, frame="f000" + "00" * 12)
        result = compare_state(left, right, 0xFFFF)
        self.assertEqual(result["defined"], "pass")
        self.assertEqual(result["chip_compatibility"], "fail")

    def test_unselected_byte_is_not_compared(self):
        from .phase import from_report

        def upper_only(item, change_low=False):
            capture = from_report(item["capture"])
            words = [(word | (1 << 42)) ^ (0xFF << 24 if change_low else 0)
                     for _, word in capture.window()]
            raw = encode_samples(words)
            item["capture"] = replace(capture, raw=raw, accepted=len(raw) // 8,
                                      committed=len(raw) // 8, buffer_used=len(raw) // 8).report()
            return item

        self.assertEqual(compare(upper_only(waveform()),
                                 upper_only(waveform(), True))["verdict"], "pass")


class CorpusTests(unittest.TestCase):
    def test_unique_deterministic_names(self):
        for profile in ("smoke", "full"):
            values = cases(profile)
            self.assertEqual(len(values), len({case.name for case in values}))
            self.assertEqual(values, cases(profile))

    def test_all_synchronous_vectors_have_directed_cases(self):
        vectors = {case.vector for case in cases()}
        self.assertTrue({3, 4, 5, 6, 7, 8, 9, 10, 11, *range(32, 48)} <= vectors)

    def test_snapshots_precede_flag_clobbering_markers(self):
        text = assembly(cases()[0])
        start = text.index("normal_exit:")
        self.assertLess(text.index("move.w %sr", start), text.index("move.w #0,", start))
        self.assertIn("-", assembly(cases()[0]))

    def test_imported_classifier_rejects_memory_and_faulting_instructions(self):
        for opcode in (0xD040, 0x9040, 0xC040, 0x8040, 0xB040, 0x7000):
            self.assertTrue(register_instruction(opcode), hex(opcode))
        for opcode in (0xD050, 0x80C0, 0x4E73, 0x4AFC, 0x4E72, 0x6000):
            self.assertFalse(register_instruction(opcode), hex(opcode))

    def test_division_masks_depend_on_overflow_not_only_mnemonic(self):
        from dataclasses import asdict
        case = asdict(next(case for case in cases() if case.name == "divu"))
        self.assertEqual(defined_sr_mask(case), 0xFFF3)
        case["operand"] = 10
        self.assertEqual(defined_sr_mask(case), 0xFFFF)
        result = compare_state({"sr": 0x2700}, {"sr": 0x2702}, 0xFFF3)
        self.assertEqual(result["defined"], "fail")


class EvidenceTests(unittest.TestCase):
    def test_modified_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "case.json", {})
            write_json(root / "manifest.json", {"schema": 1, "march": "68000", "cases": [
                {"name": "nop", "path": "case.json", "artifact_sha256": "wrong"}]})
            with self.assertRaisesRegex(ValueError, "modified"):
                load_manifest(root, None)

    def test_run_artifact_round_trip_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            entry = {"name": "nop", "stimulus_sha256": "123", "passed": True, "runs": []}
            index = save_test(path, entry)
            self.assertEqual(read_test(path, index), entry)
            (path.parent / index["artifact"]).write_text("{}")
            with self.assertRaisesRegex(ValueError, "modified"):
                read_test(path, index)

    def test_missing_shard_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shard.json"
            write_json(path, {"shard_count": 2, "shard_index": 0})
            with self.assertRaisesRegex(ValueError, "shard"):
                merge(Namespace(reports=[path], output=Path(directory) / "merged.json"))

    def test_disconnect_and_cleanup_failure_are_saved(self):
        class DisconnectedBoard:
            closed = False

            def state(self):
                raise RuntimeError("USB disconnected")

            def power_off(self):
                raise RuntimeError("USB unavailable during cleanup")

            def close(self):
                self.closed = True

        board = DisconnectedBoard()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_json(path / "manifest.json", {})
            args = Namespace(directory=path, case=None, target="board-pair", socket_fitted=True,
                             reference=None, shard_count=1, shard_index=0, output=path / "result.json")
            with patch("validation.m68000.campaign.load_manifest", return_value=(
                    {}, [{"case": {"name": "nop"}}])), \
                    patch("validation.m68000.campaign.subprocess.run"), \
                    patch("validation.m68000.campaign.NuBoard", return_value=board):
                self.assertEqual(run(args), 1)
            report = json.loads(args.output.read_text())
            self.assertFalse(report["completed"])
            self.assertIn("disconnected", report["error"])
            self.assertIn("cleanup", report["cleanup_error"])
            self.assertTrue(board.closed)


if __name__ == "__main__":
    unittest.main()
