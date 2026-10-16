"""Per-instruction timing of the socketed V35S against the V30.

    python -m validation.v35s.timing --socket-fitted [--case SUBSTRING ...]

The cases are the 306 instruction forms nuV30 measured on a real µPD70116
(build/deps/nuV30/docs/facts/timing_measured.json): the same bytes, the same
operands and the same memory fill, so each V35S figure sits beside a V30
silicon figure. Every case runs on its own from reset, in both lanes, so the
model lane (the nuV30 V20 microcode behind the V35 bus shell) is measured by
the same program.

Method. The prelude selects fX/2, zero waits and no refresh, then loads the
case's registers. The measured window is

    OUT 20h,AL / 16 NOPs / target / 16 NOPs / OUT 20h,AL

The NOP runway fills the prefetch queue (a NOP takes longer than a fetch), so
the target starts from a full queue as in nuV30's F-to-F method. A case's
cost is the time between the two marker writes minus the same window with no
target, so it is the target's retirement-to-retirement time including any
queue refill it forces. Control-transfer cases branch to the next instruction,
so taken and not-taken paths run the same bytes.

Other suites (validation/v35s/probes.py) reuse the same window: register
access, EA modes, data-dependent forms, internal RAM, PSW and undefined
opcodes. --prc, --wtc, --rfm and --ready-ticks change the settings the
prelude loads, so the same cases run with waits, refresh or RAMEN = 0.

Results: build/validation/v35s/timing.json, with both lanes' full traces.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .asm import assemble
from nuboard.debug import DebugClient

from .runner import (FLAG_IO, FLAG_READ, FLAG_STROBE, ROOT, Harness, SimulationTransport,
                     Transaction, open_board, reset_image)

FACTS = ROOT / "build/deps/nuV30/docs/facts/timing_measured.json"
CODE_SEGMENT = 0x1000
CODE_BASE = CODE_SEGMENT << 4
MARKER_PORT = 0x20
RUNWAY = 16
X_HALF = 2
# fX/2 with X1 = 16.67 MHz / X_HALF: one CPU clock is 2 X1 periods.
TICKS_PER_CLOCK = 4 * X_HALF

PRC_FX2 = 0x4C       # fX/2, RAMEN and the reset time-base setting
WTC_ZERO = 0x0000    # no waits for memory or I/O
RFM_OFF = 0xEC       # refresh disabled
DEFAULT_SETTINGS = {"prc": PRC_FX2, "wtc": WTC_ZERO, "rfm": RFM_OFF}

# With Case.stubs, every vector from 0 to 31 enters a stub that loads PSW
# F002h (so BRKI = 1 and its own OUT cannot trap), reports the vector number on
# this port and jumps to the instruction after the target.
TRAP_PORT = 0x24
STUB_SIZE = 16

REGS16 = ("BW", "CW", "DW", "SP", "BP", "IX", "IY")
SEGMENTS = ("DS0", "DS1", "SS")


@dataclass
class Case:
    name: str
    target: str                  # assembly for the target, at its own org
    regs: dict = field(default_factory=dict)
    ram: dict = field(default_factory=dict)   # byte address -> value
    odd: bool = False            # target at an odd address
    vector: int | None = None    # trap vector hooked to the next instruction
    v30: int | None = None       # nuV30's V30 silicon measurement
    v30_doc: list = field(default_factory=list)
    form: str = ""
    group: str = ""              # cases that differ only in placement
    stubs: bool = False          # hook vectors 0-31 to reporting stubs
    bank: int | None = None      # run the case in this register bank
    suite: str = ""


def _hex(value: str) -> int:
    return int(value, 16)


def facts_cases() -> list[Case]:
    """Each distinct nuV30 form, placed at an even and at an odd address."""
    data = json.loads(FACTS.read_text())
    groups = {}
    for entry in data["results"]:
        if not entry["bytes"] or entry["asm"] == "HALT":
            continue
        regs = {k: _hex(v) for k, v in entry["operands"].items()}
        ram = {_hex(a): _hex(v) for a, v in entry.get("ram", [])}
        key = (entry["bytes"], tuple(sorted(regs.items())), tuple(sorted(ram.items())))
        group = groups.setdefault(key, {"entry": entry, "regs": regs, "ram": ram})
        group["odd" if entry.get("anchor") == "0x0501" else "even"] = entry
    cases = []
    for (raw, _, _), group in groups.items():
        entry, regs, ram = group["entry"], group["regs"], group["ram"]
        name = entry["asm"]
        tags = []
        if regs:
            tags.append(" ".join(f"{k}={v:04X}" for k, v in sorted(regs.items())
                                 if k not in ("IX", "DS0", "SS", "SP", "DS1")
                                 or entry.get("odd_operand")))
        if ram:
            tags.append("ram")
        tags = [t for t in tags if t]
        if tags:
            name += f" [{'; '.join(tags)}]"
        target = "    DB " + ", ".join(f"0x{b}" for b in raw.split())
        for odd in (False, True):
            reference = group.get("odd" if odd else "even")
            cases.append(Case(name=name, target=target, regs=regs, ram=ram, odd=odd,
                              v30=reference and reference["measured_cycles"],
                              v30_doc=entry["documented_values"], form=entry["nec_form"],
                              group=name))
    return cases


def _v30_flow(data):
    return {e["asm"]: e for e in data["results"] if not e["bytes"]}


def flow_cases() -> list[Case]:
    """Control transfers, rebuilt to land on the next instruction."""
    flow = _v30_flow(json.loads(FACTS.read_text()))
    stack = {"SS": 0, "SP": 0x0F00}
    mem = {"BW": 0x0800, "DS0": 0}

    def case(name, target, regs=None, ram=None, odd=False, vector=None, v30_name=None):
        reference = flow.get(v30_name or name, {})
        return Case(name=name, target=target, regs=dict(regs or {}), ram=dict(ram or {}),
                    odd=odd, vector=vector, v30=reference.get("measured_cycles"),
                    v30_doc=reference.get("documented_values", []),
                    form=reference.get("nec_form", ""))

    cases = []
    conditions = [
        ("BZ", {"PSW": 0x0040}, True), ("BZ", {"PSW": 0}, False),
        ("BNZ", {"PSW": 0}, True), ("BNZ", {"PSW": 0x0040}, False),
        ("BC", {"PSW": 0x0001}, True), ("BC", {"PSW": 0}, False),
        ("BNC", {"PSW": 0}, True), ("BNC", {"PSW": 0x0001}, False),
        ("BCWZ", {"CW": 0}, True), ("BCWZ", {"CW": 5}, False),
        ("DBNZ", {"CW": 3}, True), ("DBNZ", {"CW": 1}, False),
        ("DBNZE", {"CW": 3, "PSW": 0x0040}, True), ("DBNZE", {"CW": 3, "PSW": 0}, False),
        ("DBNZNE", {"CW": 3, "PSW": 0}, True), ("DBNZNE", {"CW": 3, "PSW": 0x0040}, False),
    ]
    for mnemonic, regs, taken in conditions:
        name = f"{mnemonic} t ({'taken' if taken else 'not-taken'})"
        cases.append(case(name, f"    {mnemonic} t\nt:\n", regs))
    cases.append(case("BZ t (taken, odd target)", "    BZ t\nt:\n", {"PSW": 0x0040},
                      odd=True))
    cases += [
        case("BR t (short)", "    BR t\nt:\n"),
        case("BR t (short, odd target)", "    BR t\nt:\n", odd=True),
        # A 3-byte jump at an even address lands on an odd one.
        case("BR t (near, disp16)", "    DB 0xE9, 0x00, 0x00\n"),
        case("BR t (near, even target)", "    DB 0xE9, 0x00, 0x00\n", odd=True),
        case("BR DW", "    BR DW\n", {"DW": "next"}),
        case("BR [BW]", "    BR word [BW]\n", mem, {"word:0x0800": "next"}),
        case("BR far 0:0x0514", "    BR 0x{seg}:0x{next}\n"),
        case("CALL 0x0600", "    CALL t\nt:\n", stack),
        case("CALL DW", "    CALL DW\n", dict(stack, DW="next")),
        case("CALL [BW]", "    CALL word [BW]\n", dict(stack, **mem), {"word:0x0800": "next"}),
        case("CALL far 0:0x0600", "    CALL 0x{seg}:0x{next}\n", stack),
        case("RET", "    RET\n", stack, {"word:0x0F00": "next"}),
        case("RET 4", "    RET 4\n", stack, {"word:0x0F00": "next"}),
        case("RETI", "    RETI\n", stack,
             {"word:0x0F00": "next", "word:0x0F02": CODE_SEGMENT, "word:0x0F04": 0xF002}),
        case("BRK 3 (trap)", "    BRK 3\n", stack, vector=3),
        case("BRKV (V=1, trap)", "    BRKV\n", dict(stack, PSW=0x0800), vector=4),
        case("CHKIND DW,[BW] (trap)", "    DB 0x62, 0x17\n", dict(stack, DW=5, **mem),
             {"word:0x0800": 0, "word:0x0802": 4}, vector=5),
    ]
    return cases


def baseline_cases() -> list[Case]:
    return [Case(name="(baseline)", target=""),
            Case(name="(baseline, odd)", target="", odd=True)]


def _bank_switch(bank: int) -> list[str]:
    """RETI into another register bank (RB in the popped PSW), MD kept 1.

    CALL pushes the address of the BR that follows and jumps to the RETI
    after it; RETI returns to the BR with the new bank selected, and the BR
    skips the RETI. Everything after this runs in the new bank, whose
    registers the rest of the prelude loads.
    """
    psw = 0x8002 | (bank << 12)
    return [
        "    MOV AW, 0", "    MOV SS, AW", "    MOV SP, 0F00h",
        f"    DB 0x68, 0x{psw & 0xFF:02X}, 0x{psw >> 8:02X}",      # PUSH PSW image
        "    DB 0x0E",                                            # PUSH PS
        "    DB 0xE8, 0x02, 0x00",                                # CALL +2
        "    DB 0xEB, 0x01",                                      # BR over the RETI
        "    DB 0xCF",                                            # RETI
    ]


def _setup(case: Case, next_value: int, settings: dict) -> str:
    regs = {k: (next_value if v == "next" else v) for k, v in case.regs.items()}
    lines = (_bank_switch(case.bank) if case.bank is not None else []) + [
        "    MOV AW, 0F000h",
        "    MOV DS0, AW",
        f"    MOV word [0FFE8h], {settings['wtc']:04X}h",
        f"    MOV byte [0FFE1h], {settings['rfm']:02X}h",
        f"    MOV byte [0FFEBh], {settings['prc']:02X}h",
    ] + ([f"    MOV byte [0FF0Ah], {settings['pmc1']:02X}h"]    # PMC1 bit 7: READY
         if settings.get("pmc1") is not None else []) + [
        "    MOV AW, 0",
        "    MOV SS, AW",
        "    MOV SP, 0F00h",
        # Bit 1 is BRKI on the V35; clearing it would trap every IN/OUT.
        f"    PUSH {(regs.get('PSW', 0) | 0x0002):04X}h",
        "    POP PSW",
    ]
    for name in SEGMENTS:
        lines += [f"    MOV AW, {regs.get(name, 0):04X}h", f"    MOV {name}, AW"]
    for name in REGS16:
        default = 0x0F00 if name == "SP" else 0
        lines.append(f"    MOV {name}, {regs.get(name, default):04X}h")
    lines.append(f"    MOV AW, {regs.get('AW', 0):04X}h")
    if settings.get("resync") == 2:
        # ROL AW,16 leaves AW, runs long enough with no bus cycle of its own for
        # the queue to fill and the bus to idle, and costs what the tail's
        # SHL AW,16 does. It changes CY and V, so the case's PSW is pushed
        # before it and popped after.
        lines += [f"    PUSH {(regs.get('PSW', 0) | 0x0002):04X}h", "    ROL AW, 16", "    POP PSW"]
    elif settings.get("resync"):
        # Three ROL4 CL (0F 28 C1) restore AL and CL and leave the flags.
        lines += ["    DB 0x0F, 0x28, 0xC1"] * 3
    return "\n".join(lines) + "\n"


def _window_head(pad: bool) -> str:
    return ("    NOP\n" if pad else "") + f"    OUT {MARKER_PORT:02X}h, AL\n" + "    NOP\n" * RUNWAY


# The shift before the closing marker runs long enough, with no bus cycle of
# its own and a duration fixed by its immediate count, for the queue to fill
# and the bus to go idle, so the marker's I/O cycle starts as soon as the EU
# reaches it. It follows the saturated NOPs directly, so it starts the same
# number of clocks after the target retires whatever the tail's alignment.
TAIL = ("    NOP\n" * RUNWAY + "    SHL AW, 16\n"
        f"    OUT {MARKER_PORT:02X}h, AL\n"
        "    MOV DW, 0FF00h\n    OUT DW, AL\n    HALT\nspin:\n    BR spin\n")


def build(case: Case, settings: dict = DEFAULT_SETTINGS):
    """Assemble a case. Returns (image, target_offset, next_offset, code)."""
    head_probe = assemble(_setup(case, 0x1234, settings) + _window_head(False), org=0)
    target_offset = len(head_probe)
    pad = (target_offset & 1) != case.odd
    target_offset += pad
    probe = case.target.format(seg=f"{CODE_SEGMENT:04X}", next="1234")
    target_length = len(assemble(probe, org=target_offset)) if case.target else 0
    next_offset = target_offset + target_length
    head = assemble(_setup(case, next_offset, settings) + _window_head(pad), org=0)
    if len(head) != target_offset:
        raise RuntimeError(f"{case.name}: head length moved")
    target = assemble(case.target.format(seg=f"{CODE_SEGMENT:04X}", next=f"{next_offset:04X}"),
                      org=target_offset) if case.target else b""
    if len(target) != target_length:
        raise RuntimeError(f"{case.name}: target length moved")
    tail = assemble(TAIL, org=next_offset)
    code = head + target + tail
    stub_base = None
    if case.stubs:
        code += b"\x90" * (-len(code) % STUB_SIZE)
        stub_base = len(code)
        for vector in range(32):
            here = stub_base + vector * STUB_SIZE
            rel = (next_offset - (here + 11)) & 0xFFFF
            code += (bytes([0x68, 0x02, 0xF0, 0x9D, 0xB0, vector, 0xE6, TRAP_PORT, 0xE9])
                     + rel.to_bytes(2, "little") + b"\x90" * 5)

    memory = bytearray(b"\x90" * 0x800)          # 0x0800-0x0FFF, nuV30's fill
    vectors = bytearray(0x400)
    for key, value in case.ram.items():
        value = next_offset if value == "next" else value
        if isinstance(key, str):
            address = int(key.split(":")[1], 16)
            memory[address - 0x800:address - 0x800 + 2] = value.to_bytes(2, "little")
        else:
            memory[key - 0x800] = value
    if case.vector is not None:
        vectors[case.vector * 4:case.vector * 4 + 4] = (
            next_offset.to_bytes(2, "little") + CODE_SEGMENT.to_bytes(2, "little"))
    if stub_base is not None:
        for vector in range(32):
            if vector != case.vector:
                vectors[vector * 4:vector * 4 + 4] = (
                    (stub_base + vector * STUB_SIZE).to_bytes(2, "little")
                    + CODE_SEGMENT.to_bytes(2, "little"))
    image = reset_image(code, origin=CODE_BASE, segment=CODE_SEGMENT)
    image[0x00000] = bytes(vectors)
    image[0x00800] = bytes(memory)
    return image, target_offset, next_offset, code


def markers(trace):
    return [t for t in trace if t.flags & FLAG_STROBE and t.flags & FLAG_IO
            and not t.flags & FLAG_READ and t.address == MARKER_PORT]


def window(trace):
    found = markers(trace)
    if len(found) != 2:
        return None
    return found[1].start - found[0].start


def mode_lanes(mode):
    return {"model": ("model",), "socket": ("socket",), "both": ("model", "socket")}[mode]


def io_writes(trace):
    """I/O writes between the markers, other than the markers: the dumps."""
    found = markers(trace)
    if len(found) != 2:
        return None
    return [(t.address, t.data) for t in trace
            if found[0].start < t.start < found[1].start and t.flags & FLAG_STROBE
            and t.flags & FLAG_IO and not t.flags & FLAG_READ]


def run_cases(harness, cases, mode="both", settings=DEFAULT_SETTINGS, ready_ticks=0):
    results = []
    for case in cases:
        image, target_offset, next_offset, code = build(case, settings)
        harness.configure(x_half=X_HALF, ready_ticks=ready_ticks)
        harness.load(image)
        result = harness.run(mode, 2_000_000)
        row = {"case": asdict(case), "target_offset": target_offset,
               "next_offset": next_offset, "code_hex": code.hex(),
               "passed": not result["timeout"] and all(
                   result[f"{lane}_result"] == 1 for lane in mode_lanes(mode)),
               "status": result["status"],
               "complete": result["trace_complete"]}
        for lane in ("model", "socket"):
            trace = [Transaction(**r) for r in result[f"{lane}_trace"]]
            row[f"{lane}_trace"] = result[f"{lane}_trace"]
            row[f"{lane}_window"] = window(trace) if trace else None
            row[f"{lane}_io"] = io_writes(trace) if trace else None
        results.append(row)
        dumps = row["socket_io"] or row["model_io"]
        print(f"  {case.name:<44} socket={row['socket_window']} model={row['model_window']}"
              + (" io=" + " ".join(f"{a:x}:{d:04x}" for a, d in dumps) if dumps else "")
              + ("" if row["passed"] else " FAIL"), flush=True)
    return results


def analyse(results):
    """Clocks per case: the window minus the empty window at the same parity.

    A target of odd length moves everything after it to the other parity,
    and the closing sequence costs a clock more or less there, so a single
    placement of an odd-length target reads one clock high or low (NOP reads
    3 and 5, two NOPs 8 and 8). The mean of the two placements cancels that;
    even-length targets read exactly at either placement.
    """
    base = {}
    for row in results:
        if row["case"]["name"].startswith("(baseline"):
            base[row["case"]["odd"]] = row
    groups = {}
    for row in results:
        case = row["case"]
        if case["name"].startswith("(baseline"):
            continue
        key = case["group"] or case["name"]
        entry = groups.setdefault(key, {
            "name": key, "form": case["form"], "v30_doc": case["v30_doc"],
            "length": row["next_offset"] - row["target_offset"],
            "flow": not case["group"]})
        place = "odd" if case["odd"] and case["group"] else "even"
        entry[f"v30_{place}"] = case["v30"]
        reference = base.get(case["odd"])
        for lane in ("socket", "model"):
            span, zero = row[f"{lane}_window"], reference and reference[f"{lane}_window"]
            value = None if span is None or zero is None else (span - zero) / TICKS_PER_CLOCK
            entry[f"{lane}_{place}"] = value
    rows = []
    for entry in groups.values():
        entry.setdefault("v30_odd", None)
        for lane in ("socket", "model"):
            even, odd = entry.get(f"{lane}_even"), entry.get(f"{lane}_odd")
            entry.setdefault(f"{lane}_odd", None)
            if even is not None and odd is not None:
                entry[lane] = (even + odd) / 2 if entry["length"] & 1 else even
            else:
                entry[lane] = even
        entry["v30"] = entry["v30_even"] if entry.get("v30_even") is not None else entry["v30_odd"]
        rows.append(entry)
    return rows


def main():
    from .probes import SUITES
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--socket-fitted", action="store_true")
    parser.add_argument("--backend", choices=("board", "sim"), default="board",
                        help="sim runs the model lane alone in Verilator")
    parser.add_argument("--case", nargs="*", help="run cases whose name contains any of these")
    parser.add_argument("--suite", default="a6",
                        help="comma-separated: a6 (the nuV30 forms and flow), or a "
                             "suite from probes.py: " + ", ".join(SUITES))
    parser.add_argument("--lanes", choices=("both", "socket", "model"), default="both")
    parser.add_argument("--prc", type=_hex, default=PRC_FX2)
    parser.add_argument("--wtc", type=_hex, default=WTC_ZERO)
    parser.add_argument("--rfm", type=_hex, default=RFM_OFF)
    parser.add_argument("--pmc1", type=_hex, help="PMC1 value; 80 selects READY on P17")
    parser.add_argument("--ready-ticks", type=int, default=0)
    parser.add_argument("--resync", type=int, default=0,
                        help="1: end the prelude with three ROL4 CL; 2: with PUSH PSW, ROL AW,16, POP PSW")
    parser.add_argument("--output", type=Path, default=ROOT / "build/validation/v35s/timing.json")
    args = parser.parse_args()
    settings = {"prc": args.prc, "wtc": args.wtc, "rfm": args.rfm, "pmc1": args.pmc1}
    if args.resync:
        settings["resync"] = args.resync

    cases = baseline_cases()
    for suite in args.suite.split(","):
        cases += facts_cases() + flow_cases() if suite == "a6" else SUITES[suite]()
    if args.case:
        cases = baseline_cases() + [c for c in cases[2:]
                                    if any(s.lower() in c.name.lower() for s in args.case)]

    results = []
    state = None
    try:
        if args.backend == "sim":
            transport = SimulationTransport("direct")
            try:
                results = run_cases(Harness(DebugClient(transport.exchange)), cases,
                                    mode="model", settings=settings,
                                    ready_ticks=args.ready_ticks)
            finally:
                transport.close()
        else:
            if not args.socket_fitted:
                parser.error("board runs power the socket: pass --socket-fitted")
            transport, harness, state = open_board(True)
            try:
                transport.vccb_enable()
                harness.arm()
                time.sleep(0.05)
                results = run_cases(harness, cases, args.lanes, settings, args.ready_ticks)
            finally:
                try:
                    harness.arm(False)
                    transport.power_off()
                finally:
                    transport.close()
    finally:
        rows = analyse(results)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "backend": args.backend, "board_state": state, "x_half": X_HALF,
            "ticks_per_clock": TICKS_PER_CLOCK,
            "suite": args.suite, "settings": settings, "ready_ticks": args.ready_ticks,
            "summary": rows, "runs": results}, indent=1) + "\n")
    def show(value):
        return "-" if value is None else f"{value:g}"
    print(f"\n{'case':<48} {'V30':>5} {'V35S':>6} {'even':>5} {'odd':>5} {'model':>6}")
    for row in rows:
        print(f"{row['name']:<48} {show(row['v30']):>5} {show(row['socket']):>6} "
              f"{show(row['socket_even']):>5} {show(row['socket_odd']):>5} {show(row['model']):>6}")


if __name__ == "__main__":
    main()
