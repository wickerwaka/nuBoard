"""Repeat a tiny reset executable and capture actual sampled bus signals.

The scope is passive. Its 20 ns samples are FPGA-level digital observations,
not oscilloscope measurements at the CPU package pins. Both lanes use the same
two-register observation pipeline and the same continuously running CPU clock.
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

SIGNAL_BITS = {
    "as_n": 40,
    "uds_n": 41,
    "lds_n": 42,
    "read": 43,
    "dtack_n": 44,
    "berr_n": 45,
    "clock": 49,
    "reset_n": 50,
    "halt_n": 51,
}


def minimal_image():
    # Reset vectors, NOP, MOVE.L #1,$100004 (pass marker), BRA.S to itself.
    # The timing comparison only needs the first two reset-vector reads; no
    # instruction-specific CPU behaviour is needed to provoke the mismatch.
    return {
        0: struct.pack(">II", 0x3F0, 0x10000),
        0x10000: bytes.fromhex("4e71 23fc 0000 0001 0010 0004 60fe"),
    }


def memory_moves_image():
    # Assembled from memory_moves.s with GNU as -march=68000. Source and
    # destination are ordinary RAM, separate from the reset vectors/code.
    # Start destination with a different value to detect a missing write.
    return {
        0: struct.pack(">II", 0x3F0, 0x10000),
        0x200: bytes.fromhex("a55a 5aa5"),
        0x10000: bytes.fromhex("3038 0200 31c0 0202 23fc 0000 0001 0010 0004 60fe"),
    }


def decode_word(word):
    signals = {name: (word >> bit) & 1 for name, bit in SIGNAL_BITS.items()}
    signals["address"] = word & 0xFFFFFF
    signals["data"] = (word >> 24) & 0xFFFF
    signals["fc"] = (word >> 46) & 7
    return signals


def decode_capture(raw):
    return [
        {"model": decode_word(model), "socket": decode_word(socket)}
        for model, socket in struct.iter_unpack("<QQ", raw)
    ]


def read_scope(debug):
    if debug.read16(0x30) not in (1, 2):
        raise RuntimeError("unsupported or missing passive scope ABI")
    count = debug.read16(0x2E)
    if count != 512:
        raise RuntimeError(f"incomplete waveform: {count}/512 samples")
    return debug.read(0x50000, count * 16)


def read_intervals(samples, lane):
    """Return observed AS-low reads, excluding invalid reset-time levels."""
    result = []
    start = None
    for tick in range(1, len(samples)):
        before = samples[tick - 1][lane]
        now = samples[tick][lane]
        if before["as_n"] and not now["as_n"] and now["read"] and now["fc"] == 6:
            start = tick
        if start is not None and not before["as_n"] and now["as_n"]:
            active = [sample[lane] for sample in samples[start:tick]]
            ack = next((offset for offset, row in enumerate(active) if not row["dtack_n"]), None)
            if ack is None:
                raise RuntimeError("read ended without captured DTACK")
            result.append({
                "start_tick": start,
                "end_tick": tick,
                "dtack_tick": start + ack,
                "address": active[ack]["address"],
                "data": active[-1]["data"],
                "as_low_ns": (tick - start) * 20,
            })
            start = None
    return result


def operand_intervals(samples, lane):
    """Decode complete ordinary data cycles; AS and data strobes may differ.

    This is deliberately not a TAS/read-modify-write decoder. Each selected
    cycle must have one contiguous assertion of each word data strobe.
    """
    intervals = []
    start = None
    for tick in range(1, len(samples)):
        previous = samples[tick - 1][lane]
        current = samples[tick][lane]
        if previous["as_n"] and not current["as_n"]:
            start = tick
        if start is None or previous["as_n"] or not current["as_n"]:
            continue
        end = tick
        start_tick = start
        start = None
        active = [sample[lane] for sample in samples[start_tick:end]]
        acknowledgements = [i for i, row in enumerate(active) if not row["dtack_n"]]
        if not acknowledgements:
            continue
        ack_tick = start_tick + acknowledgements[0]
        transaction = samples[ack_tick][lane]
        if transaction["fc"] != 5 or transaction["address"] not in (0x200, 0x202):
            continue
        entry = {
            "start_tick": start_tick,
            "end_tick": end,
            "dtack_tick": ack_tick,
            "address": transaction["address"],
            "data": active[-1]["data"],
            "read": transaction["read"],
            "fc": transaction["fc"],
            "as_low_ns": (end - start_tick) * 20,
            "as_to_dtack_ns": (ack_tick - start_tick) * 20,
        }
        for signal in ("uds_n", "lds_n"):
            low_ticks = [start_tick + i for i, row in enumerate(active) if not row[signal]]
            if not low_ticks or low_ticks != list(range(low_ticks[0], low_ticks[-1] + 1)):
                raise RuntimeError(f"{lane}: missing or non-contiguous {signal} in word transfer")
            entry[f"{signal}_start_tick"] = low_ticks[0]
            entry[f"{signal}_end_tick"] = low_ticks[-1] + 1
            entry[f"{signal}_low_ns"] = len(low_ticks) * 20
        intervals.append(entry)
    return intervals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sim", "board"), default="sim")
    parser.add_argument("--socket-fitted", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--program", choices=("reset", "memory"), default="reset")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be between 1 and 10")
    if args.backend == "board" and not args.socket_fitted:
        parser.error("physical timing capture requires --socket-fitted")

    transport = None
    runs = []
    state = None
    failure = None
    cleanup_error = None
    shutdown_state = None
    build_receipt = None
    image = memory_moves_image() if args.program == "memory" else minimal_image()
    scope_start = 256 if args.program == "memory" else 0
    scope_abi = None
    try:
        if args.backend == "board":
            transport = NuBoard()
            state = json.loads(transport.state())
            if (not state["link"] or state["core_uuid"] != b"nuBoard-68000-v1".hex()
                    or state["core_build"] not in (3, 4, 5, 6)):
                raise RuntimeError("configure the timing-checked build 3/4/5/6 harness first")
            if state["vccb"] or state["selector_mv"] != 5000:
                raise RuntimeError("capture requires VCCB initially off and exclusive 5 V")
            build_receipt = json.loads((ROOT / "build/fpga/m68000/receipt.json").read_text())
            if state["sha256"] != build_receipt["bitstream_sha256"]:
                raise RuntimeError("configured image does not match the checked build receipt")
            debug = DebugClient(lambda data: transport.fpga_exchange(CHANNEL, data))
        else:
            transport = SimulationTransport()
            debug = DebugClient(transport.exchange)
        harness = Harness(debug)
        scope_abi = debug.read16(0x30)
        if scope_abi not in (1, 2):
            raise RuntimeError("passive scope ABI mismatch")
        if scope_start and scope_abi != 2:
            raise RuntimeError("memory operand capture requires build 4 / scope ABI 2")
        if scope_abi == 2:
            debug.write(0x32, struct.pack("<I", scope_start))
        if args.backend == "board":
            transport.vccb_enable()
            debug.write16(4, 1)
            time.sleep(0.01)

        for index in range(args.repeats):
            harness.load(image)
            result = harness.run("both" if args.backend == "board" else "model")
            raw = read_scope(debug)
            samples = decode_capture(raw)
            lanes = ("model", "socket") if args.backend == "board" else ("model",)
            intervals = {lane: read_intervals(samples, lane) for lane in lanes}
            run = {
                "repeat": index + 1,
                "result": result,
                "scope_hex": raw.hex(),
                "scope_sha256": hashlib.sha256(raw).hexdigest(),
                "read_intervals": intervals,
            }
            runs.append(run)
            if not result["passed"] or not result["trace_complete"]:
                raise RuntimeError("minimal program or functional comparison failed; stopping")
            if args.program == "memory":
                run["operand_intervals"] = {}
                run["ram_after"] = {}
                for lane in lanes:
                    operands = operand_intervals(samples, lane)
                    run["operand_intervals"][lane] = operands
                    memory = harness.read_memory(lane, 0x200, 4)
                    run["ram_after"][lane] = memory.hex()
                    if memory != bytes.fromhex("a55a a55a"):
                        raise RuntimeError(f"{lane}: RAM read/write result differs")
                    observed = [(row["address"], row["read"], row["data"]) for row in operands]
                    if observed != [(0x200, 1, 0xA55A), (0x202, 0, 0xA55A)]:
                        raise RuntimeError(f"{lane}: both memory operands were not captured correctly")
                    print(f"repeat {index + 1} {lane}: {operands}", flush=True)
            else:
                for lane in lanes:
                    if [read["address"] for read in intervals[lane][:2]] != [0, 2]:
                        raise RuntimeError(f"{lane}: first reset reads were not captured")
                    print(f"repeat {index + 1} {lane}: {intervals[lane][:2]}", flush=True)
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if transport is not None:
            try:
                if args.backend == "board":
                    transport.power_off()
                    time.sleep(0.02)
                    shutdown_state = json.loads(transport.state())
                    if any(shutdown_state[key] for key in ("vccb", "rail_1v2", "rail_3v3")):
                        raise RuntimeError("power-off state was not confirmed")
            except Exception as exc:
                cleanup_error = str(exc)
            finally:
                try:
                    transport.close()
                except Exception as exc:
                    cleanup_error = f"{cleanup_error or ''}; transport close failed: {exc}"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "backend": args.backend,
            "cpu_marking": "MC68000P12" if args.backend == "board" else None,
            "sample_period_ns": 20,
            "scope_abi": scope_abi,
            "scope_start_tick": scope_start,
            "program": args.program,
            "build_receipt": build_receipt,
            "image_segments": {f"{address:06x}": data.hex() for address, data in image.items()},
            "board_state_before_run": state,
            "completed": failure is None and cleanup_error is None and len(runs) == args.repeats,
            "error": failure,
            "cleanup_error": cleanup_error,
            "shutdown_state": shutdown_state,
            "runs": runs,
        }, indent=2) + "\n")
    if cleanup_error:
        raise RuntimeError(f"capture cleanup failed: {cleanup_error}")


if __name__ == "__main__":
    main()
