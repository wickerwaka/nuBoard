"""Run one program on the socket V35S with the scope armed and save the capture.

    python -m validation.v35s.capture --socket-fitted validation/v35s/programs/clocks.s

The capture, the bus trace and a text waveform of the first cycles are written
to build/validation/v35s/captures/<program>.json and printed.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from .asm import assemble
from .runner import ROOT, Transaction, open_board, reset_image
from .scope import TICK_NS, Scope, edges, periods, waveform


def capture_program(harness, transport, source: str, x_half: int, limit: int,
                    ready_ticks: int = 0, start_ports: int = 0):
    code = assemble(source, org=0x100)
    harness.configure(x_half=x_half, ready_ticks=ready_ticks, start_ports=start_ports)
    harness.load(reset_image(code))
    scope = Scope(harness.debug)
    scope.initialize()
    scope.configure("socket")
    result = harness.run("socket", limit)
    capture = scope.download()
    return code, result, capture


def summarize(capture, trace):
    summary = {}
    x1 = periods(capture, "x1")
    if x1:
        summary["x1_period_ticks"] = sorted(set(x1))
    clkout = periods(capture, "clkout")
    if clkout:
        summary["clkout_period_ticks"] = sorted(set(clkout))
    kinds = {}
    for row in trace:
        kinds.setdefault(row.kind, set()).add((row.end - row.start, row.strobe))
    summary["cycle_shapes"] = {kind: sorted(shapes) for kind, shapes in kinds.items()}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path)
    parser.add_argument("--socket-fitted", action="store_true", required=True)
    parser.add_argument("--x-half", type=int, default=2,
                        help="X1 half period in 30 ns ticks (X1 = 16.67 MHz / value, value >= 2)")
    parser.add_argument("--ready-ticks", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2_000_000)
    parser.add_argument("--window", type=int, default=0,
                        help="trace index whose cycle the waveform starts at")
    parser.add_argument("--columns", type=int, default=400)
    parser.add_argument("--step", type=int, default=1)
    args = parser.parse_args()

    transport, harness, state = open_board(True)
    try:
        transport.vccb_enable()
        harness.arm()
        time.sleep(0.05)
        code, result, capture = capture_program(
            harness, transport, args.program.read_text(), args.x_half, args.limit,
            args.ready_ticks)
    finally:
        try:
            harness.arm(False)
            transport.power_off()
        finally:
            transport.close()

    trace = [Transaction(**row) for row in result["socket_trace"]]
    summary = summarize(capture, trace)
    output = ROOT / "build/validation/v35s/captures" / f"{args.program.stem}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "program": args.program.name, "code_hex": code.hex(),
        "x_half": args.x_half, "ready_ticks": args.ready_ticks,
        "board_state": state, "result": {k: v for k, v in result.items()
                                         if not k.endswith("_trace")},
        "trace": [asdict(row) for row in trace], "summary": summary,
        "capture": {**capture.report(), "sample_period_ns": TICK_NS},
    }, indent=1) + "\n")

    print(f"{args.program.stem}: {'PASS' if result['passed'] else 'FAIL'} "
          f"status=0x{result['status']:04x} cycles={len(trace)} "
          f"capture={capture.committed} records ({capture.reason})")
    print(json.dumps(summary))
    for row in trace[:60]:
        print("  " + row.describe())
    if trace:
        start = trace[min(args.window, len(trace) - 1)].start - 20
        print(waveform(capture, start, start + args.columns * args.step, args.step))
    print(f"saved {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
