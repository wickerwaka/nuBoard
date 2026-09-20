"""Measure capture limits with finite CPU loops; never throttle the CPU."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard

from .runner import CORE_BUILD, ROOT, Harness, SimulationTransport, Transaction, compare_traces
from .scope import CAPACITY, Scope, events

DEFAULT_COUNTS = (64, 256, 512, 768, 1024, 1280, 1536, 2048, 4096, 8192, 16384)


def stress_image(iterations, pattern):
    """DBF runs exactly iterations times, then saves D1/D0 and writes PASS.

    NOP measures a fetch-heavy loop. READ adds a repeated word operand access.
    No clock-divider, wait-state, or recorder-filter settings change.
    """
    if not 1 <= iterations <= 65536 or pattern not in ("nop", "read"):
        raise ValueError("invalid stress iteration count or pattern")
    body = bytes.fromhex("4e71" if pattern == "nop" else "3238 0200")
    program = bytes.fromhex("303c") + struct.pack(">H", iterations - 1)
    program += bytes.fromhex("7200")  # MOVEQ #0,D1
    program += body + bytes.fromhex("51c8") + struct.pack(">h", -(len(body) + 2))
    program += bytes.fromhex("31c1 0300 31c0 0302 23fc 0000 0001 0010 0004 60fe")
    return {
        0: struct.pack(">II", 0x3F0, 0x10000),
        0x200: bytes.fromhex("a55a"),
        0x300: bytes.fromhex("bbbb bbbb"),
        0x10000: program,
    }


def check_execution(baseline, captured, lane):
    """Require identical CPU work and elapsed time; keep pin timing diagnostics."""
    if not baseline["passed"] or not captured["passed"]:
        raise RuntimeError("stress CPU program failed")
    fields = ("clock_divider", "wait_ticks", "elapsed_ticks",
              f"{lane}_total", f"{lane}_signature", f"{lane}_result")
    for field in fields:
        if baseline[field] != captured[field]:
            raise RuntimeError(f"capture changed CPU {field}: "
                               f"{baseline[field]} -> {captured[field]}")
    comparison = compare_traces(
        [Transaction(**row) for row in baseline[f"{lane}_trace"]],
        [Transaction(**row) for row in captured[f"{lane}_trace"]],
    )
    if not comparison["functional_match"]:
        raise RuntimeError("capture changed CPU transaction contents")
    return comparison


def capture_metrics(capture, cpu_ticks):
    if not 0 < capture.accepted == capture.committed:
        raise RuntimeError("capture has empty or undrained records")
    if capture.reason not in ("complete", "capacity"):
        raise RuntimeError(f"unexpected capture stop: {capture.reason}")
    if capture.reason != "complete" and capture.missed_tick != capture.last_tick + 1:
        raise RuntimeError("truncated capture does not identify its contiguous prefix")
    if capture.reason == "capacity" and capture.accepted != CAPACITY:
        raise RuntimeError("BRAM capacity reported before the record limit")
    if not 0 <= capture.buffer_used <= CAPACITY:
        raise RuntimeError("BRAM usage outside physical capacity")

    duration_ns = (capture.last_tick - capture.first_tick + 1) * 20
    transitions = []
    previous_clock = None
    for tick, signals in events(capture.raw, capture.first_tick):
        clock = (signals >> 49) & 1
        if previous_clock is not None and clock != previous_clock:
            transitions.append(tick)
        previous_clock = clock
    # The default 5 MHz CPU toggles every five 20 ns samples. These edges
    # impose an 80 MB/s minimum record stream, even during internal execution.
    intervals = [right - left for left, right in zip(transitions, transitions[1:])]
    if not intervals or any(interval != 5 for interval in intervals):
        raise RuntimeError("capture lost or corrupted a CPU clock edge")
    return {
        "cpu_duration_ms": cpu_ticks / 50000,
        "captured_duration_ms": duration_ns / 1_000_000,
        "records": capture.committed,
        "bytes": len(capture.raw),
        "input_MB_s": len(capture.raw) * 1000 / duration_ns,
        "buffer_used": capture.buffer_used,
        "buffer_utilization_percent": capture.buffer_used * 100 / CAPACITY,
        "reason": capture.reason,
        "clock_edges_checked": len(transitions),
        "clock_half_period_ticks": 5,
    }


def summarize_runs(runs):
    summary = []
    for lane, pattern in sorted({(run["lane"], run["pattern"]) for run in runs}):
        selected = [run for run in runs if (run["lane"], run["pattern"]) == (lane, pattern)]
        complete = [run for run in selected if run["capture"]["complete"]]
        limited = [run for run in selected if not run["capture"]["complete"]]
        largest = max(complete, key=lambda run: run["iterations"], default=None)
        first = min(limited, key=lambda run: run["iterations"], default=None)
        row = {"lane": lane, "pattern": pattern,
               "largest_complete_iterations": largest["iterations"] if largest else None,
               "largest_complete": largest["metrics"] if largest else None,
               "first_limited_iterations": first["iterations"] if first else None,
               "first_limited": first["metrics"] if first else None}
        summary.append(row)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sim", "board"), default="sim")
    parser.add_argument("--lane", choices=("model", "socket", "both"), default="model")
    parser.add_argument("--socket-fitted", action="store_true")
    parser.add_argument("--counts", nargs="+", type=int, default=DEFAULT_COUNTS)
    parser.add_argument("--patterns", nargs="+", choices=("nop", "read"), default=("nop", "read"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path,
                        help="completed simulation stress report for model waveform comparison")
    args = parser.parse_args()
    if args.lane != "model" and (args.backend != "board" or not args.socket_fitted):
        parser.error("socket stress requires --backend board --socket-fitted")
    if list(args.counts) != sorted(set(args.counts)) or not all(1 <= n <= 65536 for n in args.counts):
        parser.error("counts must be strictly increasing and within 1..65536")
    report = {"backend": args.backend, "counts": list(args.counts),
              "patterns": list(args.patterns), "runs": [], "completed": False}
    reference = {}
    if args.reference:
        reference_report = json.loads(args.reference.read_text())
        if not reference_report["completed"] or reference_report["backend"] != "sim":
            parser.error("reference must be a completed simulation stress report")
        if any(run["capture"]["scope_abi"] != 4 for run in reference_report["runs"]):
            parser.error("reference must use BRAM scope ABI 4")
        reference = {(run["pattern"], run["iterations"]): run
                     for run in reference_report["runs"] if run["lane"] == "model"}
        if any((pattern, count) not in reference
               for pattern in args.patterns for count in args.counts):
            parser.error("reference does not contain every requested pattern/count")
        report["reference"] = str(args.reference)
    transport = None
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, indent=2) + "\n")

    try:
        if args.backend == "board":
            transport = NuBoard()
            state = json.loads(transport.state())
            receipt = json.loads((ROOT / "build/fpga/m68000/receipt.json").read_text())
            report.update(board_state=state, build_receipt=receipt)
            if (not state["link"] or state["vccb"] or state["core_build"] != CORE_BUILD or
                    state["core_uuid"] != b"nuBoard-68000-v1".hex() or
                    state["sha256"] != receipt["bitstream_sha256"] or
                    receipt["capture_storage"] != "bram"):
                raise RuntimeError("configure the qualified BRAM image with VCCB off first")
            exchange = lambda data: transport.fpga_exchange(CHANNEL, data)
        else:
            transport = SimulationTransport()
            exchange = transport.exchange
        debug = DebugClient(exchange)
        harness = Harness(debug)
        scope = Scope(debug)
        scope.initialize()
        lanes = ("model", "socket") if args.lane == "both" else (args.lane,)
        for lane in lanes:
            if lane == "socket":
                if state["selector_mv"] != 5000:
                    raise RuntimeError("MC68000P12 requires exclusive 5 V selection")
                transport.vccb_enable()
                debug.write16(4, 1)
                time.sleep(0.01)
            for pattern in args.patterns:
                for iterations in args.counts:
                    entry = {"lane": lane, "pattern": pattern, "iterations": iterations}
                    report["runs"].append(entry)
                    image = stress_image(iterations, pattern)
                    entry["image_sha256"] = hashlib.sha256(b"".join(
                        address.to_bytes(4, "little") + data
                        for address, data in sorted(image.items())
                    )).hexdigest()
                    debug.write16(0x36, 0)
                    harness.load(image)
                    baseline = harness.run(lane)
                    entry["baseline"] = baseline
                    if not baseline["passed"]:
                        raise RuntimeError("capture-disabled stress CPU program failed")
                    scope.configure(lane)
                    harness.load(image)
                    result = harness.run(lane)
                    entry["result"] = result
                    capture = scope.download()
                    entry["capture"] = capture.report()
                    entry["execution_comparison"] = check_execution(baseline, result, lane)
                    observed = harness.read_memory(lane, 0x300, 4).hex()
                    entry["saved_words"] = observed
                    expected = "0000ffff" if pattern == "nop" else "a55affff"
                    if observed != expected:
                        raise RuntimeError(f"incorrect loop results: {observed}")
                    entry["metrics"] = capture_metrics(capture, result["elapsed_ticks"])
                    if reference and lane == "model":
                        golden = reference[pattern, iterations]
                        expected_raw = bytes.fromhex(golden["capture"]["records_hex"])
                        # Compare the stored records against the selected reference.
                        common = min(len(expected_raw), len(capture.raw))
                        if (golden["image_sha256"] != entry["image_sha256"] or
                                expected_raw[:common] != capture.raw[:common] or
                                capture.complete and golden["capture"]["complete"] and
                                len(expected_raw) != len(capture.raw)):
                            raise RuntimeError("model BRAM waveform differs from simulation")
                        entry["simulation_prefix_bytes_verified"] = common
                    save()
                    metrics = entry["metrics"]
                    print(f"{lane} {pattern} {iterations}: {capture.reason}, "
                          f"{capture.committed} records, "
                          f"{metrics['captured_duration_ms']:.3f} ms, "
                          f"BRAM {capture.buffer_used}/{CAPACITY}", flush=True)
        report["summary"] = summarize_runs(report["runs"])
        report["completed"] = True
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if transport is not None:
            try:
                if args.backend == "board":
                    transport.power_off()
                    time.sleep(0.02)
                    shutdown = json.loads(transport.state())
                    report["shutdown_state"] = shutdown
                    if any(shutdown[name] for name in ("vccb", "rail_1v2", "rail_3v3")):
                        raise RuntimeError("power-off did not disable all rails")
            except Exception as exc:
                report["completed"] = False
                report["cleanup_error"] = str(exc)
            finally:
                transport.close()
        save()
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
