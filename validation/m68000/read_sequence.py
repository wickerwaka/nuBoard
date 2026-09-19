"""Measure the accumulated cost of eight consecutive reads against a baseline.

The timed region is bracketed by identical word-write markers. A zero-read
program measures marker/prefetch overhead. All register-result stores are
after the closing marker and are excluded from the timing calculation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard

from .runner import ROOT, Harness, SimulationTransport
from .timing import read_scope

SOURCE_WORDS = tuple(range(0xA550, 0xA558))


def sequence_image(count):
    if count not in (0, 8):
        raise ValueError("the qualified read counts are 0 and 8")
    # GNU as -march=68000 output from read_sequence.s, checked independently.
    program = bytes.fromhex("41f8 0200 31fc 1111 0400")
    if count:
        program += struct.pack(">8H", *(0x3018 + (register << 9) for register in range(8)))
    program += bytes.fromhex("31fc 2222 0402")
    if count:
        program += bytes.fromhex("48b8 00ff 0300")
    program += bytes.fromhex("23fc 0000 0001 0010 0004 60fe")
    return {
        0: struct.pack(">II", 0x3F0, 0x10000),
        0x200: struct.pack(">8H", *SOURCE_WORDS),
        0x300: bytes.fromhex("bbbb") * 8,
        0x10000: program,
    }


def measure_lane(trace, count):
    def marker(address, data):
        matches = [row for row in trace if row["address"] == address
                   and row["data"] == data and row["flags"] == 0x2B]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one marker write at {address:#x}")
        return matches[0]

    begin = marker(0x400, 0x1111)["end"]
    end = marker(0x402, 0x2222)["end"]
    if end <= begin:
        raise RuntimeError("closing marker did not follow opening marker")
    window = [row for row in trace if row["start"] >= begin and row["end"] <= end]
    operands = [row for row in window if row["flags"] == 0x2F]
    expected = [(0x200 + i * 2, SOURCE_WORDS[i]) for i in range(count)]
    if [(row["address"], row["data"]) for row in operands] != expected:
        raise RuntimeError("operand reads are missing, out of order, or incorrect")
    fetches = [row for row in window if row["flags"] == 0x37]
    writes = [row for row in window if row["flags"] == 0x2B]
    if len(writes) != 1 or writes[0]["address"] != 0x402:
        raise RuntimeError("unexpected store in the timed region")
    if len(window) != len(operands) + len(fetches) + len(writes):
        raise RuntimeError("unclassified bus transfer in the timed region")

    gaps = []
    previous_end = begin
    for row in window:
        gaps.append((row["start"] - previous_end) * 20)
        previous_end = row["end"]
    periods = [(right["start"] - left["start"]) * 20
               for left, right in zip(operands, operands[1:])]
    return {
        "marker_start_tick": begin,
        "marker_end_tick": end,
        "marker_elapsed_ns": (end - begin) * 20,
        "operand_reads": operands,
        "instruction_fetches": fetches,
        "closing_marker_write": writes[0],
        "operand_start_intervals_ns": periods,
        "operand_active_ns": [(row["end"] - row["start"]) * 20 for row in operands],
        "fetch_active_ns": [(row["end"] - row["start"]) * 20 for row in fetches],
        "gaps_ns": gaps,
        "sum_bus_active_ns": sum((row["end"] - row["start"]) * 20 for row in window),
        "sum_gap_ns": sum(gaps),
        "first_to_last_operand_ns": (
            (operands[-1]["end"] - operands[0]["start"]) * 20 if operands else None
        ),
    }


def summarize(runs, lanes):
    summary = {}
    for lane in lanes:
        measurements = {}
        for count in (0, 8):
            selected = [run for run in runs if run["read_count"] == count]
            values = [run["measurements"][lane] for run in selected]
            if not values or any(value != values[0] for value in values[1:]):
                raise RuntimeError(f"{lane}: timing did not repeat identically for count={count}")
            measurements[count] = values[0]
        baseline, reads = measurements[0], measurements[8]
        elapsed = reads["marker_elapsed_ns"] - baseline["marker_elapsed_ns"]
        extra_fetches = len(reads["instruction_fetches"]) - len(baseline["instruction_fetches"])
        if extra_fetches != 8:
            raise RuntimeError("baseline subtraction does not isolate eight additional fetches")
        extra_active = reads["sum_bus_active_ns"] - baseline["sum_bus_active_ns"]
        extra_gaps = reads["sum_gap_ns"] - baseline["sum_gap_ns"]
        if elapsed != extra_active + extra_gaps:
            raise RuntimeError("bus-time accounting does not match marker elapsed time")
        summary[lane] = {
            "baseline_marker_ns": baseline["marker_elapsed_ns"],
            "eight_read_marker_ns": reads["marker_elapsed_ns"],
            "eight_read_increment_ns": elapsed,
            "eight_read_increment_cpu_clocks": elapsed / 200,
            "per_instruction_increment_ns": elapsed / 8,
            "operand_start_intervals_ns": reads["operand_start_intervals_ns"],
            "operand_active_ns": reads["operand_active_ns"],
            "extra_operand_reads": 8,
            "extra_instruction_fetches": extra_fetches,
            "extra_bus_active_ns": extra_active,
            "extra_gap_ns": extra_gaps,
            "first_to_last_operand_ns": reads["first_to_last_operand_ns"],
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sim", "board"), default="sim")
    parser.add_argument("--socket-fitted", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be between 1 and 10")
    if args.backend == "board" and not args.socket_fitted:
        parser.error("physical measurement requires --socket-fitted")

    transport = None
    state = None
    build_receipt = None
    shutdown_state = None
    error = None
    cleanup_error = None
    summary = None
    runs = []
    lanes = ("model", "socket") if args.backend == "board" else ("model",)
    try:
        if args.backend == "board":
            transport = NuBoard()
            state = json.loads(transport.state())
            if (not state["link"] or state["core_uuid"] != b"nuBoard-68000-v1".hex()
                    or state["core_build"] not in (4, 5, 6)):
                raise RuntimeError("configure the checked build 4/5/6 image first")
            if state["vccb"] or state["selector_mv"] != 5000:
                raise RuntimeError("measurement requires VCCB off and exclusive 5 V selection")
            build_receipt = json.loads((ROOT / "build/fpga/m68000/receipt.json").read_text())
            if state["sha256"] != build_receipt["bitstream_sha256"]:
                raise RuntimeError("configured image does not match the checked build")
            debug = DebugClient(lambda data: transport.fpga_exchange(CHANNEL, data))
        else:
            transport = SimulationTransport()
            debug = DebugClient(transport.exchange)
        harness = Harness(debug)
        if (debug.read16(8), debug.read16(10), debug.read16(0x30)) != (5, 8, 2):
            raise RuntimeError("unexpected clock/wait settings or scope ABI")
        debug.write(0x32, struct.pack("<I", 512))
        if args.backend == "board":
            transport.vccb_enable()
            debug.write16(4, 1)
            time.sleep(0.01)

        for repeat in range(1, args.repeats + 1):
            for count in (0, 8):
                harness.load(sequence_image(count))
                result = harness.run("both" if args.backend == "board" else "model")
                run = {"repeat": repeat, "read_count": count, "result": result}
                runs.append(run)
                if not result["passed"] or not result["trace_complete"]:
                    raise RuntimeError("functional run failed; stopping without retry")
                run["measurements"] = {}
                run["register_words"] = {}
                for lane in lanes:
                    saved = harness.read_memory(lane, 0x300, 16)
                    expected = struct.pack(">8H", *SOURCE_WORDS) if count else bytes.fromhex("bbbb") * 8
                    run["register_words"][lane] = saved.hex()
                    if saved != expected:
                        raise RuntimeError(f"{lane}: saved register values differ")
                    measured = measure_lane(result[f"{lane}_trace"], count)
                    run["measurements"][lane] = measured
                    print(f"repeat={repeat} reads={count} {lane}: "
                          f"marker={measured['marker_elapsed_ns']} ns "
                          f"operand cadence={measured['operand_start_intervals_ns']}", flush=True)
                # This diagnostic window is supplementary. Elapsed time and
                # every operand/fetch are measured by the complete bus trace.
                raw = read_scope(debug)
                run["scope_hex"] = raw.hex()
                run["scope_sha256"] = hashlib.sha256(raw).hexdigest()
        summary = summarize(runs, lanes)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if transport is not None:
            try:
                if args.backend == "board":
                    transport.power_off()
                    time.sleep(0.02)
                    shutdown_state = json.loads(transport.state())
                    if any(shutdown_state[key] for key in ("vccb", "rail_1v2", "rail_3v3")):
                        raise RuntimeError("power-off was not confirmed")
            except Exception as exc:
                cleanup_error = str(exc)
            finally:
                try:
                    transport.close()
                except Exception as exc:
                    cleanup_error = f"{cleanup_error or ''}; close failed: {exc}"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "backend": args.backend,
            "cpu_marking": "MC68000P12" if args.backend == "board" else None,
            "sample_period_ns": 20,
            "scope_start_tick": 512,
            "completed": error is None and cleanup_error is None and summary is not None,
            "error": error,
            "cleanup_error": cleanup_error,
            "board_state_before_run": state,
            "build_receipt": build_receipt,
            "shutdown_state": shutdown_state,
            "programs": {
                str(count): {f"{address:06x}": data.hex() for address, data in sequence_image(count).items()}
                for count in (0, 8)
            },
            "summary": summary,
            "runs": runs,
        }, indent=2) + "\n")
    if cleanup_error:
        raise RuntimeError(f"shutdown failed: {cleanup_error}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
