"""Prefetch-queue and reset-exit probes of the socketed V35S.

    python -m validation.v35s.prefetch --socket-fitted

Prefetch scenarios run inside the timing probe's window (fX/2, no waits, no
refresh, a saturated queue at the start; see timing.py). Each one begins with
a jump to the next instruction so the queue starts empty, then gives the bus
unit long instructions that use no bus cycle, so the fetches it makes are
visible on their own. The report lists every bus cycle in clocks from the
jump's last fetch, for the chip and for the model lane (V30 policy).

The reset probe runs the smoke program at several reset lengths and X1 rates
and records when the first refresh and the first fetch begin after /RESET
rises, in X1 periods.

--wtc, --rfm and --ready-ticks rerun the scenarios with waits, refresh or a
held READY (READY only counts when WTC selects it and PMC1 bit 7 makes P17
READY: --wtc FFFF --pmc1 80).

--refresh runs the refresh probe instead (M7): for each RFM value and clock
rate, a stretch with no bus cycles of its own, then HALT, and reports the
refresh intervals in each.

Results: build/validation/v35s/prefetch.json.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .asm import assemble
from .runner import (FLAG_IO, FLAG_READ, FLAG_REFRESH, FLAG_STROBE, ROOT, Transaction,
                     open_board, reset_image)
from .timing import DEFAULT_SETTINGS, TICKS_PER_CLOCK, X_HALF, Case, build, markers

LONG = "    SHL AW, 16\n"          # 3 bytes, no bus cycle, fixed duration

SCENARIOS = {
    # Queue depth: how far the bus unit fetches while the EU is busy.
    "depth-even": ("    BR t\nt:\n" + LONG + "    NOP\n" * 12, False),
    "depth-odd": ("    BR t\nt:\n" + LONG + "    NOP\n" * 12, True),
    "depth-2byte": ("    BR t\nt:\n    MULU CW\n" + "    NOP\n" * 12, False),
    # Refill threshold: one, two and three bytes consumed between long ones.
    "threshold": ("    BR t\nt:\n" + LONG + "    NOP\n" + LONG + "    NOP\n    NOP\n" + LONG
                  + "    NOP\n    NOP\n    NOP\n" + LONG + "    NOP\n" * 8, False),
    # Data cycles against prefetch.
    "load": ("    BR t\nt:\n" + LONG + "    MOV DW, [BW]\n" + LONG + "    NOP\n" * 8, False),
    "store": ("    BR t\nt:\n" + LONG + "    MOV [BW], DW\n" + LONG + "    NOP\n" * 8, False),
    "rmw": ("    BR t\nt:\n" + LONG + "    ADD [BW], DW\n" + LONG + "    NOP\n" * 8, False),
    "odd-word": ("    BR t\nt:\n" + LONG + "    MOV DW, [IX]\n" + LONG + "    NOP\n" * 8, False),
    # Taken branch from a full queue.
    "branch": ("    " + LONG.strip() + "\n    BR t\n" + "    NOP\n" * 6 + "t:\n" + LONG
               + "    NOP\n" * 8, False),
    "branch-odd-target": ("    " + LONG.strip() + "\n    BR t\n" + "    NOP\n" * 5 + "t:\n" + LONG
                          + "    NOP\n" * 8, False),
}
# A taken branch to each byte alignment of a 4-byte group, from both parities.
for _skip in range(4, 8):
    for _odd in (False, True):
        SCENARIOS[f"branch-skip{_skip}{'-odd' if _odd else ''}"] = (
            "    " + LONG.strip() + "\n    BR t\n" + "    NOP\n" * _skip + "t:\n" + LONG
            + "    NOP\n" * 8, _odd)
# Long stretches with no bus cycles: where fetches and refreshes land.
SCENARIOS["idle-long"] = ("    BR t\nt:\n" + LONG * 12 + "    NOP\n" * 8, False)

REFRESH_RFM = (0xFC, 0xFD, 0xFE, 0xFF, 0xF0, 0xF4, 0xF8)
REFRESH_PRC = (0x4C, 0x4D, 0x4E)

RESET_SWEEP = [(reset, x_half) for x_half in (2, 3, 4) for reset in (167, 1_667, 16_667)]


def describe(trace, origin, code_base):
    rows = []
    for t in trace:
        if not t.flags & (FLAG_STROBE | FLAG_REFRESH):
            continue
        clock = (t.start - origin) / TICKS_PER_CLOCK
        if t.flags & FLAG_REFRESH:
            kind = "refresh"
        elif t.flags & FLAG_IO:
            kind = "io-" + ("read" if t.flags & FLAG_READ else "write")
        else:
            kind = "read" if t.flags & FLAG_READ else "write"
        address = t.address - code_base if code_base <= t.address < code_base + 0x10000 else t.address
        rows.append({"clock": clock, "kind": kind, "address": address,
                     "length": (t.end - t.start) / TICKS_PER_CLOCK})
    return rows


def run_scenarios(harness, settings=DEFAULT_SETTINGS, ready_ticks=0):
    report = {}
    for name, (body, odd) in SCENARIOS.items():
        case = Case(name=name, target=body, odd=odd,
                    regs={"BW": 0x0800, "IX": 0x0801, "CW": 5, "AW": 7, "DW": 0x1234})
        image, target_offset, next_offset, code = build(case, settings)
        harness.configure(x_half=X_HALF, ready_ticks=ready_ticks)
        harness.load(image)
        result = harness.run("both", 2_000_000)
        entry = {"target_offset": target_offset, "code_hex": code.hex(),
                 "status": result["status"]}
        for lane in ("socket", "model"):
            trace = [Transaction(**r) for r in result[f"{lane}_trace"]]
            found = markers(trace)
            if len(found) != 2:
                entry[lane] = None
                continue
            inside = [t for t in trace if found[0].start <= t.start <= found[1].start]
            # Clock zero is the read of the jump's own target word.
            code_base = 0x10000
            first = next((t for t in inside if t.flags & FLAG_READ and not t.flags & FLAG_IO
                          and t.address - code_base >= target_offset + 2), inside[0])
            entry[lane] = describe(inside, first.start, code_base)
        report[name] = entry
        print(f"== {name} (target at {target_offset:#x})")
        for lane in ("socket", "model"):
            rows = entry[lane] or []
            print(f"  {lane:<6} " + " ".join(
                f"{r['clock']:g}:{r['kind'][0]}{r['address']:x}" for r in rows if r["clock"] >= -2))
    return report


def _intervals(starts):
    return [b - a for a, b in zip(starts, starts[1:])]


def run_refresh(harness):
    """Refresh intervals while the EU runs without bus cycles, and in HALT."""
    report = []
    running = "    BR t\nt:\n" + LONG * 24 + "    NOP\n" * 4
    for prc in REFRESH_PRC:
        for rfm in REFRESH_RFM if prc == 0x4C else (0xFC,):
            settings = dict(DEFAULT_SETTINGS, prc=prc, rfm=rfm)
            entry = {"prc": prc, "rfm": rfm}
            for label, body in (("running", running), ("halt", "    HALT\n")):
                image, _, _, _ = build(Case(name=label, target=body), settings)
                harness.configure(x_half=X_HALF)
                harness.load(image)
                result = harness.run("socket", 400_000)
                trace = [Transaction(**r) for r in result["socket_trace"]]
                first = markers(trace)[:1]
                start = first[0].start if first else 0
                refresh = [t.start for t in trace if t.flags & FLAG_REFRESH and t.start > start]
                fetches = [t.start for t in trace if t.flags & FLAG_STROBE
                           and not t.flags & FLAG_REFRESH and t.start > start]
                if label == "halt" and fetches:
                    refresh = [r for r in refresh if r > fetches[-1]]
                widths = sorted({(t.end - t.start) for t in trace if t.flags & FLAG_REFRESH})
                entry[label] = {"status": result["status"], "refresh_ticks": refresh[:64],
                                "intervals_ticks": _intervals(refresh[:64]),
                                "refresh_length_ticks": widths}
            report.append(entry)
            print(f"prc={prc:02X} rfm={rfm:02X}: " + "  ".join(
                f"{label} {sorted(set(entry[label]['intervals_ticks']))[:6]} ticks"
                for label in ("running", "halt")), flush=True)
    return report


def run_reset(harness):
    source = (ROOT / "validation/v35s/programs/smoke.s").read_text()
    code = assemble(source, org=0x100)
    report = []
    for reset_ticks, x_half in RESET_SWEEP:
        harness.configure(x_half=x_half, reset_ticks=reset_ticks)
        harness.load(reset_image(code))
        result = harness.run("both", 2_000_000)
        entry = {"reset_ticks": reset_ticks, "x_half": x_half, "status": result["status"]}
        x1 = 2 * x_half
        for lane in ("socket", "model"):
            trace = [Transaction(**r) for r in result[f"{lane}_trace"]]
            refresh = next((t.start for t in trace if t.flags & FLAG_REFRESH), None)
            fetch = next((t.start for t in trace if t.flags & FLAG_STROBE
                          and not t.flags & FLAG_REFRESH), None)
            entry[lane] = {
                "first_refresh_ticks": refresh, "first_fetch_ticks": fetch,
                "first_refresh_x1": None if refresh is None else refresh / x1,
                "first_fetch_x1": None if fetch is None else fetch / x1,
                "first_cycles": [Transaction(**r).describe() for r in result[f"{lane}_trace"][:12]],
            }
        report.append(entry)
        print(f"reset={reset_ticks:>6} x_half={x_half}: "
              + "  ".join(f"{lane} refresh {entry[lane]['first_refresh_x1']} fetch "
                          f"{entry[lane]['first_fetch_x1']} X1" for lane in ("socket", "model")))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--socket-fitted", action="store_true", required=True)
    parser.add_argument("--skip-reset", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="run the refresh probe only")
    parser.add_argument("--wtc", type=lambda v: int(v, 16), default=DEFAULT_SETTINGS["wtc"])
    parser.add_argument("--rfm", type=lambda v: int(v, 16), default=DEFAULT_SETTINGS["rfm"])
    parser.add_argument("--pmc1", type=lambda v: int(v, 16), help="80 selects READY on P17")
    parser.add_argument("--ready-ticks", type=int, default=0)
    parser.add_argument("--output", type=Path, default=ROOT / "build/validation/v35s/prefetch.json")
    args = parser.parse_args()
    transport, harness, state = open_board(True)
    settings = dict(DEFAULT_SETTINGS, wtc=args.wtc, rfm=args.rfm, pmc1=args.pmc1)
    report = {"board_state": state, "settings": settings, "ready_ticks": args.ready_ticks}
    try:
        transport.vccb_enable()
        harness.arm()
        time.sleep(0.05)
        if args.refresh:
            report["refresh"] = run_refresh(harness)
        else:
            report["scenarios"] = run_scenarios(harness, settings, args.ready_ticks)
            if not args.skip_reset:
                report["reset"] = run_reset(harness)
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
