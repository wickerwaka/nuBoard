"""Seeded 1 KiB mirrored-RAM fuzzing through the public debug bus.

The prelude initializes architectural registers through real instructions.
After handoff there are no collector instructions or reserved RAM locations.
We compare observable state, not a private fx68k register snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard

from .campaign import simulator_provenance, write_json
from .phase import from_report, meaningful
from .runner import CORE_BUILD, ROOT, Harness, SimulationTransport
from .scope import Scope
from .timing import decode_word

DEFAULT = ROOT / "build/validation/m68000/fuzz"
MAX_CYCLES = 4000
MIN_CYCLES = 16  # Include completion of the first test-PC fetch.
WATCHDOG_TICKS = 50000
BOOT_ADDRESS = 0xFF0000
POLICY = {
    "version": 1,
    "sample_period_ns": 20,
    "alignment": "first falling CPU edge after initial test-PC fetch recognition",
    "sample_before_edge_ticks": 1,
    "state": "all 1024 RAM bytes, selected bus data, address, FC and control pins",
    "register_readback": False,
    "undefined_flags": "not masked; differences require investigation",
}


def cpu_bytes(data):
    """Convert between CPU big-endian bytes and little-endian debug words."""
    if len(data) & 1:
        raise ValueError("word data must have even length")
    output = bytearray(len(data))
    output[0::2] = data[1::2]
    output[1::2] = data[0::2]
    return bytes(output)


def make_case(seed):
    if not 0 <= seed < 1 << 64:
        raise ValueError("seed must fit in 64 bits")
    stream = hashlib.shake_256(b"nuBoard-68000-fuzz-v1" + struct.pack("<Q", seed)).digest(1088)
    image = bytearray(stream[:1024])
    pc = 8 + 2 * (int.from_bytes(stream[1084:1088], "big") % 508)
    registers = list(struct.unpack(">15I", stream[1024:1084]))
    # Even, 24-bit initial addresses avoid alignment exceptions caused solely
    # by initial A-register values; the random program remains unconstrained.
    registers[8:] = [value & 0xFFFFFE for value in registers[8:]]
    struct.pack_into(">II", image, 0, 0x400, pc)
    return {"schema": 1, "seed": seed, "image_hex": image.hex(),
            "image_sha256": hashlib.sha256(image).hexdigest(), "pc": pc,
            "initial_d": registers[:8], "initial_a": registers[8:] + [0x400],
            "usp": 0x400, "sr": 0x2700}


def bootstrap(case):
    # MOVEA.L #USP,A0; MOVE A0,USP. No writes to the random image.
    code = bytearray(struct.pack(">HIH", 0x207C, case["usp"], 0x4E60))
    for register, value in enumerate(case["initial_d"]):
        code.extend(struct.pack(">HI", 0x203C | (register << 9), value))
    for register, value in enumerate(case["initial_a"][:7]):
        code.extend(struct.pack(">HI", 0x207C | (register << 9), value))
    code.extend(struct.pack(">HHHI", 0x46FC, case["sr"], 0x4EF9, case["pc"]))
    return bytes(code)


def load_case(debug, case, cycles):
    if not MIN_CYCLES <= cycles <= MAX_CYCLES:
        raise ValueError("cycle budget must be in 16..4000")
    image = bytes.fromhex(case["image_hex"])
    if len(image) != 1024 or hashlib.sha256(image).hexdigest() != case["image_sha256"]:
        raise ValueError("modified fuzz image")
    if struct.unpack_from(">II", image) != (case["initial_a"][7], case["pc"]):
        raise ValueError("reset vectors differ from bootstrap metadata")
    debug.write(0x80, struct.pack("<HH", 1, cycles))
    debug.write16(0x8C, case["pc"])
    # Both lane memories are initialized once; CPU writes stay private.
    debug.write(0x10000, cpu_bytes(image))
    debug.fill(0x18000, 1024, 0x4E71)
    debug.write(0x18000, cpu_bytes(bootstrap(case)))


def acquire(harness, scope, lane, case, cycles, evidence=None):
    run = {"lane": lane, "cycles": cycles}
    if evidence is not None:
        evidence.append(run)
    scope.configure(lane)
    result = harness.run(lane, limit=WATCHDOG_TICKS)
    run["result"] = result
    flags = harness.debug.read16(0x84)
    epoch = struct.unpack("<I", harness.debug.read(0x88, 4))[0]
    capture = scope.download()
    run.update(epoch=epoch, capture=capture.report(), budget_flags=flags)
    started_bit = 1 if lane == "model" else 2
    if (result["timeout"] or result["overflow"] or not result["trace_complete"] or
            flags & (12 | started_bit) != (12 | started_bit) or not capture.complete):
        raise RuntimeError("bootstrap/budget/capture qualification failed")
    if capture.last_tick < epoch + cycles * 10 - 1:
        raise RuntimeError("capture does not cover the complete fuzz clock budget")
    trace = result[f"{lane}_trace"]
    entries = [index for index, row in enumerate(trace)
               if row["address"] == case["pc"] and row["flags"] & 4 and
               (row["flags"] >> 3) & 7 == 6]
    if not entries or trace[entries[0]]["start"] >= epoch:
        raise RuntimeError("missing initial test-PC fetch before aligned epoch")
    base = 0x10000 if lane == "model" else 0x20000
    memory = cpu_bytes(harness.debug.read(base, 1024))
    run.update(trace=trace[entries[0]:], ram_hex=memory.hex(),
               ram_sha256=hashlib.sha256(memory).hexdigest(),
               budget_complete=True, stop_reason="fuzz_cycle_budget")
    observations(run)  # Check edge alignment even in single-lane acquisitions.
    return run


def observations(run):
    capture = from_report(run["capture"])
    epoch = run["epoch"]
    end = epoch + run["cycles"] * 10
    samples = {tick: decode_word(word) for tick, word in capture.window(epoch - 2, end)}
    rows = []
    for tick in range(epoch, end, 5):
        if samples[tick]["clock"] == samples[tick - 1]["clock"]:
            raise ValueError("epoch/window does not lie on the expected CPU edges")
        before = samples[tick - 1]
        guard = samples[tick - 2]
        signals = meaningful(before)
        guarded = meaningful(guard)
        unstable = [key for key in signals.keys() & guarded.keys()
                    if key not in ("data", "dtack_n", "berr_n") and
                    signals[key] != guarded[key]]
        mask = (0xFF00 if not before["uds_n"] else 0) | (0xFF if not before["lds_n"] else 0)
        if "data" in signals and (before["data"] ^ guard["data"]) & mask:
            unstable.append("data")
        rows.append({"edge": samples[tick]["clock"], "signals": signals,
                     "unstable": sorted(unstable)})
    return rows


def compare_runs(reference, candidate):
    left, right = observations(reference), observations(candidate)
    differences = []
    unresolved = []
    if len(left) != len(right):
        differences.append({"kind": "half_cycle_count", "values": [len(left), len(right)]})
    for index, (a, b) in enumerate(zip(left, right)):
        if a["unstable"] or b["unstable"]:
            unresolved.append({"phase": index, "reference": a["unstable"], "candidate": b["unstable"]})
        changed = {key: [a["signals"].get(key), b["signals"].get(key)]
                   for key in a["signals"].keys() | b["signals"].keys()
                   if a["signals"].get(key) != b["signals"].get(key)}
        if a["edge"] != b["edge"]:
            changed["clock"] = [a["edge"], b["edge"]]
        if changed:
            differences.append({"phase": index, "signals": changed})
    a_ram = bytes.fromhex(reference["ram_hex"])
    b_ram = bytes.fromhex(candidate["ram_hex"])
    ram_differences = [{"offset": index, "values": [a, b]}
                       for index, (a, b) in enumerate(zip(a_ram, b_ram)) if a != b]

    def transactions(run):
        return [(row["address"], row["flags"], row["data"] &
                 ((0xFF00 if row["flags"] & 2 else 0) | (0xFF if row["flags"] & 1 else 0)))
                for row in run["trace"]]

    trace_match = transactions(reference) == transactions(candidate)
    passed = not differences and not unresolved and not ram_differences and trace_match
    return {"passed": passed, "policy": POLICY, "phase_differences": differences,
            "unresolved": unresolved, "ram_differences": ram_differences,
            "transactions_match": trace_match,
            "verdict": "pass" if passed else "indeterminate" if unresolved else "difference"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("sim", "spi-sim", "board-pair"), default="sim")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--cycles", type=int, default=2000)
    parser.add_argument("--socket-fitted", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT / "run.json")
    args = parser.parse_args(argv)
    if (args.count < 1 or args.seed < 0 or args.seed + args.count > 1 << 64 or
            not MIN_CYCLES <= args.cycles <= MAX_CYCLES):
        parser.error("invalid seed/count/cycle range")
    if args.target == "board-pair" and not args.socket_fitted:
        parser.error("physical comparison requires --socket-fitted")
    if args.output.exists():
        parser.error("output exists; choose a new path to preserve evidence")
    report = {"schema": 1, "target": args.target, "cycles": args.cycles,
              "start_seed": args.seed, "requested_cases": args.count,
              "tests": [], "completed": False, "error": None, "cleanup_error": None,
              "qualification": "physical differential" if args.target == "board-pair"
              else "simulation acquisition only; not a silicon comparison"}
    transport = None
    started = time.monotonic()
    try:
        if args.target == "board-pair":
            subprocess.run([sys.executable, str(ROOT / "tools/check_m68000_build.py")], check=True)
            transport = NuBoard()
            state = json.loads(transport.state())
            receipt = json.loads((ROOT / "build/fpga/m68000/receipt.json").read_text())
            report.update(board_state=state, build_receipt=receipt)
            if (not state["link"] or state["vccb"] or state["selector_mv"] != 5000 or
                    state["core_build"] != CORE_BUILD or
                    state["core_uuid"] != b"nuBoard-68000-v1".hex() or
                    state["sha256"] != receipt["bitstream_sha256"]):
                raise RuntimeError("requires receipt-matched fuzz build with VCCB off and 5 V selected")
            exchange = lambda data: transport.fpga_exchange(CHANNEL, data)
        else:
            report["simulator"] = simulator_provenance(args.target)
            transport = SimulationTransport(spi=args.target == "spi-sim")
            exchange = transport.exchange
        debug = DebugClient(exchange)
        harness, scope = Harness(debug), Scope(debug)
        if struct.unpack("<HH", debug.read(8, 4)) != (5, 8):
            raise RuntimeError("requires qualified 5 MHz CPU and eight-tick ACK setting")
        if args.target == "board-pair":
            transport.vccb_enable()
            debug.write16(4, 1)
            time.sleep(0.01)
        lanes = ("model", "socket") if args.target == "board-pair" else ("model",)
        for seed in range(args.seed, args.seed + args.count):
            case = make_case(seed)
            entry = {"seed": seed, "case": case, "runs": [], "comparison": None}
            # Save the actual image even if acquisition is interrupted.
            path = args.output.with_suffix("") / f"seed-{seed:016x}.json"
            report["tests"].append({"seed": seed, "artifact": str(path), "passed": False})
            try:
                load_case(debug, case, args.cycles)
                for lane in lanes:
                    acquire(harness, scope, lane, case, args.cycles, entry["runs"])
                if len(entry["runs"]) == 2:
                    entry["comparison"] = compare_runs(entry["runs"][1], entry["runs"][0])
                passed = entry["comparison"] is None or entry["comparison"]["passed"]
                report["tests"][-1]["passed"] = passed
            finally:
                write_json(path, entry)
                report["tests"][-1]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                write_json(args.output, report)
            print(f"seed {seed}: {'PASS' if passed else 'DIFFERENCE'}", flush=True)
            if not passed:
                report["stop_reason"] = "first differential or unresolved sample"
                break
        report["completed"] = len(report["tests"]) == args.count and all(t["passed"] for t in report["tests"])
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if transport is not None:
            try:
                if args.target == "board-pair":
                    transport.power_off()
                    time.sleep(0.02)
                    report["shutdown_state"] = json.loads(transport.state())
                    if any(report["shutdown_state"][key] for key in ("vccb", "rail_1v2", "rail_3v3")):
                        raise RuntimeError("rails remain enabled")
            except Exception as exc:
                report["cleanup_error"] = str(exc)
            finally:
                try:
                    transport.close()
                except Exception as exc:
                    report["cleanup_error"] = f"{report['cleanup_error'] or ''}; close: {exc}"
        report["completed"] &= report["error"] is None and report["cleanup_error"] is None
        report["elapsed_seconds"] = time.monotonic() - started
        write_json(args.output, report)
    print(json.dumps({key: report.get(key) for key in ("completed", "error", "cleanup_error", "stop_reason")}))
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
