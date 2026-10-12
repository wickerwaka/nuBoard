"""Bus-timing characterization of the socketed V35S.

Each case runs a fixed access body under one PRC/WTC/RFM setting with CLKOUT
on P07 and the scope armed, then measures every bus cycle's edges in CLKOUT
states relative to the CLKOUT rising edge at or before /MREQ (or /REFRQ)
falls. Results go to build/validation/v35s/characterize.json.

    python -m validation.v35s.characterize --socket-fitted [--case NAME ...]
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .asm import assemble
from .runner import ROOT, Transaction, open_board, port_modes, reset_image, BANK_D, BANK_Z
from .scope import Scope, edges

# PRC 0x4C selects fX/2 and keeps RAMEN and the reset time-base setting.
CASES = {
    "reset-defaults": dict(prc=None, wtc=None, rfm=None),
    "fx2-wait2r-refresh": dict(prc=0x4C, wtc=None, rfm=None),
    "fx2-wait0-norefresh": dict(prc=0x4C, wtc=0x0000, rfm=0xEC),
    "fx2-wait1-norefresh": dict(prc=0x4C, wtc=0x5555, rfm=0xEC),
    "fx2-wait2-norefresh": dict(prc=0x4C, wtc=0xAAAA, rfm=0xEC),
    "fx2-wait0-refresh": dict(prc=0x4C, wtc=0x0000, rfm=0xFC),
    "fx4-wait0-norefresh": dict(prc=0x4D, wtc=0x0000, rfm=0xEC),
}

BODY = """
    XOR AW, AW
    MOV DS0, AW
    MOV AW, 1234h
    MOV [0400h], AW
    MOV [0403h], AW
    MOV AL, [0400h]
    MOV AW, [0403h]
    MOV DW, 0FF20h
    IN AW, DW
    OUT DW, AL
    MOV CW, 8
loop:
    NOP
    DBNZ loop
    MOV DW, 0FF00h
    OUT DW, AW
    HALT
spin:
    BR spin
"""


def program(prc=None, wtc=None, rfm=None):
    lines = [
        "    MOV DW, 0FF10h",
        f"    MOV AW, {port_modes(t2=BANK_Z):04X}h",
        "    OUT DW, AW",
        "    MOV AW, 0F000h",
        "    MOV DS0, AW",
        "    MOV byte [0FF00h], 00h",
        "    MOV byte [0FF01h], 00h",
        "    MOV byte [0FF02h], 80h",
    ]
    if wtc is not None:
        lines.append(f"    MOV word [0FFE8h], {wtc:04X}h")
    if rfm is not None:
        lines.append(f"    MOV byte [0FFE1h], {rfm:02X}h")
    if prc is not None:
        lines.append(f"    MOV byte [0FFEBh], {prc:02X}h")
    lines += [
        "    MOV DW, 0FF10h",
        f"    MOV AW, {port_modes(t2=BANK_D):04X}h",
        "    OUT DW, AW",
    ]
    return "\n".join(lines) + "\n" + BODY


def cycle_shapes(capture, trace):
    """Per-cycle edge times in CLKOUT states after the reference rising edge."""
    clock_rises = [e.tick for e in edges(capture, ["clkout"]) if e.value == 1]
    if len(clock_rises) < 4:
        return [], None
    period = Counter(b - a for a, b in zip(clock_rises, clock_rises[1:])).most_common(1)[0][0]
    signals = ["mreq_n", "mstb_n", "iostb_n", "refrq_n", "rw"]
    stream = edges(capture, signals)
    shapes = []
    for row in trace:
        # The lane timestamps a cycle two ticks after the pin changes.
        begin = row.start - 4
        finish = row.end + 4
        window = [e for e in stream if begin <= e.tick <= finish]
        first = next((e.tick for e in window if e.signal in ("mreq_n", "refrq_n")
                      and e.value == 0), None)
        if first is None:
            continue
        reference = max((t for t in clock_rises if t <= first), default=None)
        if reference is None:
            continue
        shape = tuple(
            (e.signal, e.value, round((e.tick - reference) / period * 4) / 4)
            for e in window)
        shapes.append({"kind": row.kind, "address": row.address,
                       "states": round((row.end - row.start) / period, 2),
                       "edges": shape})
    return shapes, period


def summarize(shapes):
    groups = {}
    for shape in shapes:
        key = (shape["kind"], shape["edges"])
        group = groups.setdefault(key, {"kind": shape["kind"], "count": 0,
                                        "states": shape["states"],
                                        "edges": [list(e) for e in shape["edges"]],
                                        "example_address": f"{shape['address']:05x}"})
        group["count"] += 1
    return sorted(groups.values(), key=lambda g: (g["kind"], -g["count"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-fitted", action="store_true", required=True)
    parser.add_argument("--case", nargs="*", choices=CASES)
    parser.add_argument("--x-half", type=int, default=2,
                        help="X1 half period in 30 ns ticks (X1 = 16.67 MHz / value, value >= 2)")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "build/validation/v35s/characterize.json")
    args = parser.parse_args()
    selected = args.case or list(CASES)

    transport, harness, state = open_board(True)
    report = {"board_state": state, "x_half": args.x_half, "cases": {}}
    try:
        transport.vccb_enable()
        harness.arm()
        time.sleep(0.05)
        for name in selected:
            source = program(**CASES[name])
            code = assemble(source, org=0x100)
            harness.configure(x_half=args.x_half)
            harness.load(reset_image(code))
            scope = Scope(harness.debug)
            scope.configure("socket")
            result = harness.run("socket", 2_000_000)
            capture = scope.download()
            trace = [Transaction(**row) for row in result["socket_trace"]]
            shapes, period = cycle_shapes(capture, trace)
            summary = summarize(shapes)
            report["cases"][name] = {
                "settings": CASES[name], "passed": result["passed"],
                "status": result["status"], "elapsed_ticks": result["elapsed_ticks"],
                "clkout_period_ticks": period, "capture_complete": capture.complete,
                "shapes": summary, "trace": [asdict(t) for t in trace],
            }
            print(f"== {name}: {'PASS' if result['passed'] else 'FAIL'} "
                  f"clkout={period} ticks cycles={len(trace)}")
            for group in summary:
                edges_text = " ".join(f"{s}{'↑' if v else '↓'}{t:g}"
                                      for s, v, t in group["edges"])
                print(f"  {group['kind']:<9} x{group['count']:<3} "
                      f"{group['states']:>5} states  {edges_text}")
    finally:
        try:
            harness.arm(False)
            transport.power_off()
        finally:
            transport.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
