"""Capture model/socket runs separately into BRAM, then download exact changes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard

from .runner import ROOT, Harness, SimulationTransport, Transaction, compare_traces
from .scope import CAPACITY, Scope
from .timing import memory_moves_image
from .read_sequence import SOURCE_WORDS, sequence_image, measure_lane


def capacity_image():
    """Finite CPU-only stress loop; the pass marker still terminates normally."""
    # GNU as -march=68000 encoding of capacity.s. No hardware clock or wait-state
    # settings change. The recorder must stop itself, not slow down this loop.
    return {
        0: struct.pack(">II", 0x3F0, 0x10000),
        0x10000: bytes.fromhex("303c 1fff 4e71 51c8 fffc 23fc 0000 0001 0010 0004 60fe"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sim", "spi-sim", "board"), default="sim")
    parser.add_argument("--lane", choices=("model", "socket", "both"), default="model")
    parser.add_argument("--socket-fitted", action="store_true")
    parser.add_argument("--program", choices=("memory", "reads", "baseline", "capacity"), default="memory")
    parser.add_argument("--start", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--end", type=lambda text: int(text, 0), default=0xFFFFFFFF)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.lane != "model" and (args.backend != "board" or not args.socket_fitted):
        parser.error("socket capture requires --backend board --socket-fitted")
    if args.program == "capacity" and args.lane != "model":
        parser.error("the deliberate capacity test uses the model lane with VCCB off")
    report = {"backend": args.backend, "program": args.program, "runs": [], "completed": False}
    transport = None
    try:
        if args.backend == "board":
            transport = NuBoard()
            state = json.loads(transport.state())
            report["board_state"] = state
            if (not state["link"] or state["vccb"] or state["core_build"] != 8 or
                    state["core_uuid"] != b"nuBoard-68000-v1".hex()):
                raise RuntimeError("configure the qualified build-8 harness with VCCB off first")
            receipt = json.loads((ROOT / "build/fpga/m68000/receipt.json").read_text())
            if state["sha256"] != receipt["bitstream_sha256"]:
                raise RuntimeError("configured bitstream differs from the checked receipt")
            report["build_receipt"] = receipt
            exchange = lambda data: transport.fpga_exchange(CHANNEL, data)
        else:
            transport = SimulationTransport(spi=args.backend == "spi-sim")
            exchange = transport.exchange
        debug = DebugClient(exchange)
        harness = Harness(debug)
        scope = Scope(debug)
        scope.initialize()
        if args.program == "capacity":
            image = capacity_image()
            debug.write16(0x36, 0)
            harness.load(image)
            report["uncaptured_baseline"] = harness.run("model")
        elif args.program == "memory":
            image = memory_moves_image()
        else:
            image = sequence_image(8 if args.program == "reads" else 0)
        report["image_sha256"] = hashlib.sha256(b"".join(
            address.to_bytes(4, "little") + data for address, data in sorted(image.items())
        )).hexdigest()
        lanes = ("model", "socket") if args.lane == "both" else (args.lane,)
        for lane in lanes:
            scope.configure(lane, args.start, args.end)
            if lane == "socket":
                if state["selector_mv"] != 5000:
                    raise RuntimeError("MC68000P12 requires exclusive 5 V selection")
                transport.vccb_enable()
                debug.write16(4, 1)
                time.sleep(0.01)
            # Reload all mapped memory for each independent CPU run.
            harness.load(image)
            result = harness.run(lane)
            capture = scope.download()
            entry = {"lane": lane, "result": result, "capture": capture.report()}
            report["runs"].append(entry)
            if args.program in ("reads", "baseline"):
                entry["measurement"] = measure_lane(result[f"{lane}_trace"],
                                                     8 if args.program == "reads" else 0)
                expected = (struct.pack(">8H", *SOURCE_WORDS) if args.program == "reads"
                            else bytes.fromhex("bbbb") * 8)
                observed = harness.read_memory(lane, 0x300, 16)
                entry["saved_register_words"] = observed.hex()
                if observed != expected:
                    raise RuntimeError(f"{lane}: saved register words differ from expected values")
            elif args.program == "memory":
                observed = harness.read_memory(lane, 0x200, 4)
                entry["operand_words"] = observed.hex()
                if observed != bytes.fromhex("a55aa55a"):
                    raise RuntimeError(f"{lane}: memory MOVE result is incorrect")
            print(f"{lane}: {capture.committed} records, {len(capture.raw)} bytes, "
                  f"BRAM used {capture.buffer_used}, {capture.reason}", flush=True)
            if args.program == "capacity":
                baseline = report["uncaptured_baseline"]
                if (not result["passed"] or not baseline["passed"] or
                        result != baseline or capture.reason != "capacity" or
                        not capture.accepted == capture.committed == CAPACITY or
                        capture.missed_tick != capture.last_tick + 1):
                    raise RuntimeError("capacity did not preserve the prefix and unchanged CPU execution")
                report["capacity_test_passed"] = True
            elif not result["passed"] or not result["trace_complete"] or not capture.complete:
                raise RuntimeError(f"{lane}: CPU run or capture incomplete")
        if len(report["runs"]) == 2:
            model, socket = report["runs"]
            report["comparison"] = compare_traces(
                [Transaction(**row) for row in socket["result"]["socket_trace"]],
                [Transaction(**row) for row in model["result"]["model_trace"]],
            )
            if not report["comparison"]["functional_match"]:
                raise RuntimeError("sequential CPU runs differ functionally")
        report["completed"] = True
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if transport is not None:
            try:
                if args.backend == "board":
                    transport.power_off()
                    # POWER_OFF acknowledges the request before the MCU's
                    # nonblocking 5 ms rail-down sequence has completed.
                    time.sleep(0.02)
                    report["shutdown_state"] = json.loads(transport.state())
                    shutdown = report["shutdown_state"]
                    if any(shutdown[name] for name in ("vccb", "rail_1v2", "rail_3v3")):
                        raise RuntimeError("power-off did not leave all rails disabled")
            except Exception as exc:
                report["completed"] = False
                report["cleanup_error"] = str(exc)
            finally:
                transport.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
