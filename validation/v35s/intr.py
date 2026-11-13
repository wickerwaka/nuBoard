"""F3: interrupts (docs/v35s-function-plan.md, stage F3).

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, as validation/v35s/traps.py's F2 set (onchip.py's run_one is used).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.intr socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.intr sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.intr gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.intr show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.intr emit

The frame (every program): vector n points at a stub (0000:3000h + 12n) that records n and
enters the logging handler (0000:3800h). The handler pushes PSW AW BW BP IX DS1 and writes a log
entry (0000:8100h + 32k): the vector, the nesting depth, the test, the pushed PC, PS and PSW, the
handler's PSW, SP after the hardware pushes, ISPR, EXIC0-2, TMIC0, DIC0 at entry, the
interrupted AW CW IX IY, TBIC, SEIC0, DW. It then calls the test's action routine (the word at
8006h; the default executes FINT), restores and returns by RETI to the pushed PC. Requests are
raised through the event port (FF12h) with the harness's schedule (`<prog>.stim.json`), or by a
software store of an IF bit, and taken in HALT or behind a mask (DI or MK) released at a known
instruction: no result depends on the clock a request lands on.

A test sets the registers (Test.regs), its IC registers (`pre`), the PSW (POP PSW of `psw`), runs
`code` and a NOP sled, and at its continuation stores AW CW DW BW SP BP IX IY DS0 DS1 SS PSW,
ISPR, EXIC0-2, TMIC0 and the log count in its slot (0000:9000h + 32k); its scratch bytes are at
9800h + 16k. The continuation then masks every IC register (47h), clears INTM and ends any
level left in service (eight FINTs).

Receipts: validation/v35s/receipts/f3-<name>-<backend>.json (--tag adds a suffix).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

from .onchip import Program, run_one

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

LOG = 0x8000            # count (word), vector (byte at 8002h), test (8004h), action (8006h),
                        # depth (byte at 8008h); entries at 8100h + 32k
SLOTS = 0x9000          # the continuation's slots, 32 bytes per test
SCRATCH = 0x9800        # 16 bytes per test
DATA0 = 0xA000          # DS0 = 0A00h
DATA1 = 0xB000          # DS1 = 0B00h (the SFR page through DS1 = F000h where a test says)
STUBS = 0x3000
HANDLER = 0x3800
REGS = {"AW": 0x1234, "CW": 0x0003, "DW": 0x0024, "BW": 0x0010, "BP": 0x0020, "IX": 0x0030,
        "IY": 0x0040}
DS0, DS1 = 0x0A00, 0x0B00
SP0 = 0x7F00
PSW0 = 0x0002           # IE 0
PSW_IE = 0x0202

# SFR offsets (IDB:Fxx)
SFR = {"INTM": 0x40, "EXIC0": 0x4C, "EXIC1": 0x4D, "EXIC2": 0x4E, "SEIC0": 0x6C, "SRIC0": 0x6D,
       "STIC0": 0x6E, "SEIC1": 0x7C, "SRIC1": 0x7D, "STIC1": 0x7E, "TMIC0": 0x9C, "TMIC1": 0x9D,
       "TMIC2": 0x9E, "DIC0": 0xAC, "DIC1": 0xAD, "TBIC": 0xEC, "ISPR": 0xFC, "PMC1": 0x0A,
       "PM1": 0x09}
ICS = ("EXIC0", "EXIC1", "EXIC2", "SEIC0", "SRIC0", "STIC0", "SEIC1", "SRIC1", "STIC1", "TMIC0",
       "TMIC1", "TMIC2", "DIC0", "DIC1", "TBIC")


def _h(v, w=2):
    if isinstance(v, str):
        return v
    s = f"{v:0{w}X}h"
    return "0" + s if s[0] in "ABCDEF" else s


def sfr_wr(name, val):
    """A byte store to an SFR through DS1 (the test's DS1 = F000h)."""
    return f"    DB 26h\n    MOV byte [0FF{SFR[name]:02X}h], {_h(val)}\n"


def sfr_rd(name, at):
    """An SFR's byte into PS:at (AL clobbered)."""
    return f"    DB 26h\n    MOV AL, [0FF{SFR[name]:02X}h]\n    DB 2Eh\n    MOV [{_h(at, 4)}], AL\n"


def ev(name):
    """Announce event `name` (a placeholder the program numbers) through the event port;
    AW, DW and the flags kept."""
    return ("    PUSH AW\n    PUSH DW\n    MOV DW, 0FF12h\n    MOV AL, {" + name + "}\n"
            "    OUT DW, AL\n    POP DW\n    POP AW\n")


def wait(n, tag):
    """A loop of n DBNZ iterations (CW kept)."""
    return f"    PUSH CW\n    MOV CW, {n}\nwl_{tag}_{{k}}:\n    DBNZ wl_{tag}_{{k}}\n    POP CW\n"


HANDLER_SRC = """\
    PUSH PSW
    PUSH AW
    PUSH BW
    PUSH BP
    PUSH IX
    PUSH DS1
    MOV BP, SP
    DB 2Eh
    MOV IX, [8000h]
    MOV BW, IX
    INC BW
    DB 2Eh
    MOV [8000h], BW
    SHL IX, 1
    SHL IX, 1
    SHL IX, 1
    SHL IX, 1
    SHL IX, 1
    ADD IX, 8100h
    DB 2Eh
    MOV AL, [8002h]
    DB 2Eh
    MOV [IX], AL
    DB 2Eh
    MOV AL, [8008h]
    DB 2Eh
    MOV [IX+1], AL
    DB 2Eh
    INC byte [8008h]
    DB 2Eh
    MOV AW, [8004h]
    DB 2Eh
    MOV [IX+2], AW
    MOV AW, [BP+12]
    DB 2Eh
    MOV [IX+4], AW
    MOV AW, [BP+14]
    DB 2Eh
    MOV [IX+6], AW
    MOV AW, [BP+16]
    DB 2Eh
    MOV [IX+8], AW
    MOV AW, [BP+10]
    DB 2Eh
    MOV [IX+10], AW
    LDEA AW, [BP+12]
    DB 2Eh
    MOV [IX+12], AW
    MOV AW, 0F000h
    MOV DS1, AW
    DB 26h
    MOV AL, [0FFFCh]
    DB 2Eh
    MOV [IX+14], AL
    DB 26h
    MOV AL, [0FF4Ch]
    DB 2Eh
    MOV [IX+15], AL
    DB 26h
    MOV AL, [0FF4Dh]
    DB 2Eh
    MOV [IX+16], AL
    DB 26h
    MOV AL, [0FF4Eh]
    DB 2Eh
    MOV [IX+17], AL
    DB 26h
    MOV AL, [0FF9Ch]
    DB 2Eh
    MOV [IX+18], AL
    DB 26h
    MOV AL, [0FFACh]
    DB 2Eh
    MOV [IX+19], AL
    DB 26h
    MOV AL, [0FFECh]
    DB 2Eh
    MOV [IX+28], AL
    DB 26h
    MOV AL, [0FF6Ch]
    DB 2Eh
    MOV [IX+29], AL
    MOV AW, [BP+8]
    DB 2Eh
    MOV [IX+20], AW
    DB 2Eh
    MOV [IX+22], CW
    MOV AW, [BP+2]
    DB 2Eh
    MOV [IX+24], AW
    DB 2Eh
    MOV [IX+26], IY
    DB 2Eh
    MOV [IX+30], DW
    CMP BW, 3Fh
    BGE runaway
    MOV AW, [BP+8]
    MOV BW, [BP+6]
    MOV IX, [BP+2]
    DB 2Eh
    CALL word [8006h]
    DB 2Eh
    DEC byte [8008h]
    POP DS1
    POP IX
    POP BP
    POP BW
    POP AW
    POP PSW
    RETI
runaway:
    MOV AW, 0002h
    PUSH AW
    POP PSW
    MOV DW, 0FF02h
    OUT DW, AL
    HALT
rspin:
    BR rspin
"""


def vector_area() -> dict:
    """The vector table (every vector to its stub) and the stubs: stub n stores n at
    PS:8002h and jumps to the handler."""
    from .asm import assemble
    ivt = bytearray()
    for n in range(32):
        ivt += (STUBS + 12 * n).to_bytes(2, "little") + b"\x00\x00"
    stubs = bytearray()
    for n in range(32):
        at = STUBS + 12 * n
        rel = HANDLER - (at + 9)
        stubs += bytes([0x2E, 0xC6, 0x06, 0x02, 0x80, n, 0xE9, rel & 0xFF, (rel >> 8) & 0xFF,
                        0x90, 0x90, 0x90])
    return {0x0000: bytes(ivt), STUBS: bytes(stubs), HANDLER: assemble(HANDLER_SRC, org=HANDLER)}


def pattern(base: int, n=0x100) -> bytes:
    return bytes(((base >> 8) * 0x11 + 7 * i + 3) & 0xFF for i in range(n))


class Test:
    """One case: registers (REGS overridden by `regs`), `pre` (run with IE 0 before the PSW:
    the IC registers, the events), the PSW (POP PSW of `psw`), `code`, a sled of `sled` NOPs;
    `action` the handler's action routine (assembly, RET appended; default FINT); `stim` its
    schedule entries (dicts as runner.load_stimulus's, "event" a placeholder name used in the
    code as {name}, or None for a chained entry). In the code, {k} is the test's number, {S}
    its scratch area."""

    def __init__(self, name, code="", pre="", psw=PSW0, regs=None, sled=6, action="    FINT\n",
                 stim=(), note="", sfr=True, jitter=False):
        self.name = name
        self.code = code
        self.pre = pre
        self.psw = psw
        self.regs = dict(REGS, **(regs or {}))
        self.sled = sled
        self.action = action
        self.stim = list(stim)
        self.note = note
        self.sfr = sfr          # DS1 = F000h for the SFR page (else DS1 = 0B00h after `pre`)
        # the take point follows HALT with IE 1, or an NMI: silicon's lands one instruction
        # (or an absorber) later on some runs of the same program shape, by the clock phase of
        # the request (f3_vec: HALT + 1 or + 2 with a NOP sled); the gate masks these tests'
        # log entries but the vector, depth, test, ISPR and IC bytes (`jitter_bytes`)
        self.jitter = jitter


def _db(bs) -> str:
    return "    DB " + ", ".join(_h(b) for b in bs) + "\n"


SLOT_REGS = ("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY")


def test_source(k: int, t: Test, events: dict) -> str:
    fmt = dict(events, k=k, S=_h(SCRATCH + 16 * k, 4))

    def f(s):
        return s.replace("{k}", str(k)).format(**fmt) if s else ""
    L = [f"; ---- test {k}: {t.name}{' (' + t.note + ')' if t.note else ''}\n"]
    L.append(f"    DB 2Eh, 0C7h, 06h, 04h, 80h\n    DW {_h(k, 4)}\n")
    L.append(f"    DB 2Eh, 0C7h, 06h, 06h, 80h\n    DW act{k}\n")
    L.append("    DB 2Eh, 0C6h, 06h, 08h, 80h, 00h\n")
    L.append(f"""\
    XOR AW, AW
    MOV SS, AW
    MOV SP, {_h(SP0, 4)}
    MOV AW, {_h(DS0, 4)}
    MOV DS0, AW
    MOV AW, 0F000h
    MOV DS1, AW
""")
    for r in ("CW", "DW", "BW", "BP", "IX", "IY"):
        L.append(f"    MOV {r}, {_h(t.regs[r], 4)}\n")
    L.append(f"    MOV AW, {_h(t.regs['AW'], 4)}\n")
    L.append(f(t.pre))
    if not t.sfr:
        L.append(f"    PUSH AW\n    MOV AW, {_h(DS1, 4)}\n    MOV DS1, AW\n    POP AW\n")
    L.append(f"    PUSH AW\n    MOV AW, {_h(t.psw, 4)}\n    PUSH AW\n    POP PSW\n    POP AW\n")
    L.append(f"code{k}:\n")
    L.append(f(t.code.replace("    HALT\n", "hlt{k}:\n    HALT\n"))
             + ("" if not t.code or t.code.endswith("\n") else "\n"))
    if t.sled:
        L.append(_db([0x90] * t.sled))
    s = SLOTS + 32 * k
    L.append(f"cont{k}:\n")
    for i, r in enumerate(SLOT_REGS):
        L.append(f"    DB 2Eh\n    MOV [{_h(s + 2 * i, 4)}], {r}\n")
    L.append(f"""\
    PUSH PSW
    MOV AW, DS0
    DB 2Eh
    MOV [{_h(s + 16, 4)}], AW
    MOV AW, DS1
    DB 2Eh
    MOV [{_h(s + 18, 4)}], AW
    MOV AW, SS
    DB 2Eh
    MOV [{_h(s + 20, 4)}], AW
    POP AW
    DB 2Eh
    MOV [{_h(s + 22, 4)}], AW
    MOV AW, 0002h
    PUSH AW
    POP PSW
    XOR AW, AW
    MOV SS, AW
    MOV SP, {_h(SP0, 4)}
    MOV AW, 0F000h
    MOV DS1, AW
""")
    for i, nm in enumerate(("ISPR", "EXIC0", "EXIC1", "EXIC2", "TMIC0")):
        L.append(sfr_rd(nm, s + 24 + i))
    L.append(f"    DB 2Eh\n    MOV AW, [8000h]\n    DB 2Eh\n    MOV [{_h(s + 30, 4)}], AW\n")
    for nm in ICS:
        L.append(sfr_wr(nm, 0x47))
    L.append(sfr_wr("INTM", 0x00))
    L.append("    FINT\n" * 8)
    L.append(f"    BR next{k}\nact{k}:\n" + f(t.action) + "    RET\n" + f"next{k}:\n")
    return "".join(L)


EPILOGUE = """\
    NOP
    MOV DW, 0FF00h
    OUT DW, AL
    HALT
done:
    BR done
"""


def make_program(name, tests, note="", gate=True, extra=None, levels=None):
    """The program and its schedule: each test's events are numbered in order (1, 2, ...), its
    entries appended in order (at most 32 in all)."""
    from .runner import REST_LEVELS
    entries, n, srcs = [], 0, []
    for k, t in enumerate(tests):
        names = {}
        for e in t.stim:
            if e.get("event") is not None and e["event"] not in names:
                n += 1
                names[e["event"]] = n
        for e in t.stim:
            row = dict(e)
            if row.get("event") is not None:
                row["event"] = names[row["event"]]
            entries.append(row)
        srcs.append(test_source(k, t, {nm: _h(v) for nm, v in names.items()}))
    if len(entries) > 32:
        raise ValueError(f"{name}: {len(entries)} schedule entries (32 at most)")
    src = "    DI\n" + "".join(srcs) + EPILOGUE
    data = vector_area()
    data[DATA0] = pattern(DATA0)
    data[DATA1] = pattern(DATA1)
    data.update(extra or {})
    prog = Program(name, src, data=data,
                   results=[(LOG, 0x10), (LOG + 0x100, 0x800), (SLOTS, 32 * len(tests)),
                            (SCRATCH, 16 * len(tests)), (DATA0, 0x100), (DATA1, 0x100),
                            (0x7E00, 0x200)],
                   gate=gate, note=note)
    prog.tests = tests
    prog.levels = REST_LEVELS if levels is None else levels
    prog.stim = {"entries": entries} if entries else None
    return prog


# ------------------------------------------------------------------ schedule helpers
D_HALT = 12000          # ticks after the event's OUT: the CPU is in HALT by then (fX/8: ~375 clocks)
HOLD = 2000             # a pulse's length in ticks


def pulse(event, pin, delay=D_HALT, hold=HOLD):
    return {"event": event, "delay": delay, "hold": hold, "levels": {pin: 0}}


def level(event, pin, value, delay=D_HALT):
    return {"event": event, "delay": delay, "levels": {pin: value}}


INCS = "    INC AW\n" * 6
WAIT = 20               # DBNZ iterations of a masked window (~340 clocks: 11,000 ticks at fX/8)


def halted(pin, ic=None, icv=0x07, psw=PSW_IE, action="    FINT\n", note="", intm=None,
           after=""):
    """The request taken in HALT: the IC register set, the event, HALT."""
    pre = (sfr_wr("INTM", intm) if intm is not None else "") + (sfr_wr(ic, icv) if ic else "")
    return dict(pre=pre + ev("E0"), code="    HALT\n" + after, psw=psw, action=action,
                stim=[pulse("E0", pin)], note=note, jitter=pin == "NMI" or bool(psw & 0x0200))


# ------------------------------------------------------------------ part A: the programs
ABS = "    MULU CL\n"               # the absorber: 24 clocks, longer than the controller's latency
CHAIN = ABS * 4                  # an interrupted stream of absorbers (AW = AL * CL each)


def nmi_skip(extra=""):
    """An NMI action: silicon pushes the HALT's own offset for an NMI taken in HALT; the
    return skips it (the log has the pushed value)."""
    return ("    PUSH AW\n    MOV AW, [BP+12]\n    DB 3Dh\n    DW hlt{k}\n    BNE ns{k}\n"
            "    INC word [BP+12]\nns{k}:\n    POP AW\n" + extra)


def vec_tests():
    """The sources, the entry, the edges, HALT's wake."""
    T = [
        Test("intp0_halt", **halted("INTP0", "EXIC0", 0x07, note="vector 24, PR 7")),
        Test("intp1_halt", jitter=True, pre=sfr_wr("EXIC0", 0x43) + sfr_wr("EXIC1", 0x07) + ev("E0"),
             code="    HALT\n", psw=PSW_IE, stim=[pulse("E0", "INTP1")],
             note="vector 25; the group's level from EXIC0 (PR 3), INTP0 masked"),
        Test("intp2_halt", jitter=True, pre=sfr_wr("EXIC0", 0x45) + sfr_wr("EXIC2", 0x07) + ev("E0"),
             code="    HALT\n", psw=PSW_IE, stim=[pulse("E0", "INTP2")],
             note="vector 26; group level 5"),
        Test("intp2_halt_b", jitter=True, pre=sfr_wr("EXIC0", 0x47) + sfr_wr("EXIC2", 0x07) + ev("E0"),
             code="    HALT\n", psw=PSW_IE, stim=[pulse("E0", "INTP2")],
             note="vector 26; group level 7"),
        Test("nmi_halt", **halted("NMI", action=nmi_skip(), note="vector 2, no FINT")),
        Test("nmi_ie0_halt", **halted("NMI", psw=PSW0, action=nmi_skip(), note="IE 0: NMI taken")),
        Test("nmi_flags", **halted("NMI", psw=0x0ED7, action=nmi_skip(),
                                   note="the flags set: the pushed and handler PSW")),
        Test("intp0_flags", **halted("INTP0", "EXIC0", 0x02, psw=0x0AD7, note="the flags set, PR 2")),
        Test("intp0_rise", jitter=True,
             pre=sfr_wr("INTM", 0x04) + sfr_wr("EXIC0", 0x07) + ev("E0"),
             code=wait(WAIT, "a") + sfr_rd("EXIC0", "{S}") + ev("E1") + "    HALT\n",
             psw=PSW_IE, stim=[level("E0", "INTP0", 0, delay=200), level("E1", "INTP0", 1)],
             note="INTM ES0 = 1: no request at the fall, one at the rise"),
        Test("intp0_fall_hold", jitter=True,
             pre=sfr_wr("EXIC0", 0x07) + ev("E0"),
             code="    HALT\n" + wait(WAIT, "b") + sfr_rd("EXIC0", "{S}") + ev("E1")
                  + wait(WAIT, "c") + sfr_rd("EXIC0", "{S}+1"),
             psw=PSW_IE, stim=[level("E0", "INTP0", 0), level("E1", "INTP0", 1, delay=200)],
             note="ES0 = 0: the level held low gives one request, the rise none"),
        Test("nmi_rise", jitter=True,
             pre=sfr_wr("INTM", 0x01) + ev("E0"),
             code=wait(WAIT, "a") + ev("E1") + "    HALT\n",
             psw=PSW0, action=nmi_skip(),
             stim=[level("E0", "NMI", 0, delay=200), level("E1", "NMI", 1)],
             note="INTM ESNMI = 1: the rise"),
        Test("halt_ie0", pre=sfr_wr("EXIC0", 0x07) + ev("E0"),
             code="    HALT\n" + sfr_rd("EXIC0", "{S}") + "    EI\n" + CHAIN, psw=PSW0,
             stim=[pulse("E0", "INTP0")],
             note="IE 0: HALT resumes, IF kept; then EI takes it"),
        Test("intp1_halt_di", pre=sfr_wr("EXIC0", 0x43) + sfr_wr("EXIC1", 0x07) + ev("E0"),
             code="    HALT\n    EI\n" + CHAIN, psw=PSW0, stim=[pulse("E0", "INTP1")],
             note="IE 0: HALT resumes; EI and the absorber: vector 25 at a known point"),
        Test("intp2_halt_di", pre=sfr_wr("EXIC0", 0x46) + sfr_wr("EXIC2", 0x07) + ev("E0"),
             code="    HALT\n    EI\n" + CHAIN, psw=PSW0, stim=[pulse("E0", "INTP2")],
             note="IE 0: HALT resumes; vector 26 (group level 6)"),
        Test("halt_masked", jitter=True,
             pre=sfr_wr("EXIC0", 0x47) + ev("E0"),
             code="    HALT\n" + sfr_rd("EXIC0", "{S}") + wait(WAIT * 3, "a")
                  + "    DB 26h\n    AND byte [0FF4Ch], 0BFh\n" + CHAIN,
             psw=PSW_IE, action="    DB 2Eh\n    CMP byte [8002h], 2\n    BE hm{k}\n    FINT\n"
                                "    RET\nhm{k}:\n" + nmi_skip(),
             stim=[pulse("E0", "INTP0"), {"event": None, "delay": 20000, "hold": HOLD,
                                          "levels": {"NMI": 0}}],
             note="MK 1: no wake (the NMI 20,000 ticks later wakes it); IF set; MK cleared: taken"),
        Test("sw_if_exic0", code=sfr_wr("EXIC0", 0x87) + CHAIN, psw=PSW_IE,
             note="IF set by a store: a request?"),
        Test("sw_if_tmic0", code=sfr_wr("TMIC0", 0x86) + CHAIN, psw=PSW_IE,
             note="TMIC0 IF by a store: vector 28?"),
        Test("sw_if_dic1", code=sfr_wr("DIC0", 0x45) + sfr_wr("DIC1", 0x87) + CHAIN, psw=PSW_IE,
             note="DIC1 IF by a store, the group's level 5: vector 21?"),
        Test("sw_if_srics", code=sfr_wr("SEIC0", 0x44) + sfr_wr("SRIC0", 0x87) + CHAIN,
             psw=PSW_IE, note="SRIC0 IF by a store: vector 13?"),
        Test("sw_if_tbic", code=sfr_wr("TBIC", 0x87) + CHAIN, psw=PSW_IE,
             note="TBIC IF by a store: vector 31, level 7?"),
        Test("sw_if_masked", code=sfr_wr("TMIC0", 0xC7) + CHAIN + sfr_rd("TMIC0", "{S}")
             + "    DB 26h\n    AND byte [0FF9Ch], 0BFh\n" + CHAIN, psw=PSW_IE,
             note="IF with MK 1: none; then MK cleared (AND)"),
        Test("intp0_mk_if", pre=sfr_wr("EXIC0", 0x47) + ev("E0"),
             code=wait(WAIT, "a") + sfr_rd("EXIC0", "{S}") + sfr_wr("EXIC0", 0x47)
                  + sfr_rd("EXIC0", "{S}+1") + CHAIN,
             psw=PSW_IE, stim=[pulse("E0", "INTP0", delay=200)],
             note="IF set while masked; a store of IF 0 clears it"),
    ]
    return T


def _pend(ic="EXIC0", v=0x07):
    return sfr_wr(ic, v) + ev("E0") + wait(WAIT, "p")


_ST = [pulse("E0", "INTP0", delay=200)]


def order_tests():
    """The interrupted point: a request pending behind a mask, released at a known
    instruction and an absorber after it (MULU CL, 24 clocks)."""
    T = [
        Test("ei_abs", pre=_pend(), code="    EI\n" + CHAIN, stim=_ST,
             note="EI, MULU: taken after the MULU"),
        Test("popf_abs", pre=_pend(), code="    MOV BW, 0202h\n    PUSH BW\n    POP PSW\n" + CHAIN,
             stim=_ST, note="POP PSW sets IE"),
        Test("mk_abs", pre=sfr_wr("EXIC0", 0x47) + ev("E0") + wait(WAIT, "p"),
             code="    DB 26h\n    AND byte [0FF4Ch], 0BFh\n" + CHAIN, psw=PSW_IE, stim=_ST,
             note="IE 1, MK cleared by AND"),
        Test("reti_abs", pre=_pend(),
             code="    MOV AW, 0F202h\n    PUSH AW\n    XOR AW, AW\n    PUSH AW\n"
                  "    CALL rtgt{k}\nrtgt{k}:\n    POP AW\n    ADD AW, 9\n    PUSH AW\n"
                  "    MOV AW, 1234h\n    RETI\n" + CHAIN,
             stim=_ST, note="RETI to IE 1"),
        Test("ei_pfx_abs", pre=_pend(), code="    EI\n    DB 2Eh\n    MULU byte [9F00h]\n" + CHAIN,
             stim=_ST, note="EI, a prefixed MULU"),
        Test("ei_rep_abs", pre=_pend(), code="    EI\n" + ABS + "    DB 0F3h\n    MOVBKW\n" + CHAIN,
             regs={"CW": 0x0103, "IX": 0x0000, "IY": 0x0040}, stim=_ST, sfr=False,
             note="EI, MULU, REP MOVBKW: before the string"),
        Test("ei_di", pre=_pend(), code="    EI\n    DI\n" + CHAIN + sfr_rd("EXIC0", "{S}"),
             stim=_ST, note="EI, DI: not taken between"),
        Test("halt_pending_di", pre=_pend(), code="    HALT\n" + sfr_rd("EXIC0", "{S}") + "    EI\n"
             + CHAIN, psw=PSW0, stim=_ST, note="HALT with a request pending and IE 0: resumes"),
        Test("brk_abs", pre=_pend(), code="    EI\n" + ABS + "    BRK 3\n" + CHAIN,
             action="    DB 2Eh\n    CMP byte [8002h], 3\n    BE ba{k}\n    FINT\nba{k}:\n",
             stim=_ST, note="the request taken before BRK 3; BRK 3's frame"),
        Test("fint_abs",
             code=sfr_wr("EXIC0", 0x85) + "    EI\n" + ABS + CHAIN,
             action="    DB 2Eh\n    CMP byte [8002h], 18h\n    BNE fa{k}\n" + sfr_wr("TMIC0", 0x85)
             + "    EI\n" + ABS + _lg("{S}") + "    FINT\n" + ABS + ABS + _lg("{S}+1")
             + "    RET\nfa{k}:\n    FINT\n",
             note="an equal level waits; FINT then MULU: taken after the MULU"),
    ]
    return T


def lat_tests():
    """Measured only: the take point right after a release (the controller's latency in
    clocks: INC AW chains), mid-string, after MOV SS, prefixes and HALT."""
    T = [
        Test("halt_pending_ie", pre=_pend(), code="    HALT\n" + CHAIN, psw=PSW_IE,
             note="HALT with a request already pending and IE 1 (MK cleared before)"
                  " : vectored at once?", stim=_ST),
        Test("ei_incs", pre=_pend(), code="    EI\n" + INCS, stim=_ST),
        Test("popf_incs", pre=_pend(), code="    MOV BW, 0202h\n    PUSH BW\n    POP PSW\n" + INCS,
             stim=_ST),
        Test("mk_incs", pre=sfr_wr("EXIC0", 0x47) + ev("E0") + wait(WAIT, "p"),
             code="    DB 26h\n    AND byte [0FF4Ch], 0BFh\n" + INCS, psw=PSW_IE, stim=_ST),
        Test("ei_movss", pre=_pend(), code="    EI\n    MOV SS, AW\n" + INCS, regs={"AW": 0},
             stim=_ST),
        Test("ei_movds0", pre=_pend(), code="    EI\n    MOV DS0, AW\n" + INCS,
             regs={"AW": 0x0A00}, stim=_ST),
        Test("ei_nop_movss", pre=_pend(), code="    EI\n    NOP\n    NOP\n    MOV SS, AW\n" + INCS,
             regs={"AW": 0}, stim=_ST),
        Test("ei_nop_movds0", pre=_pend(), code="    EI\n    NOP\n    NOP\n    MOV DS0, AW\n" + INCS,
             regs={"AW": 0x0A00}, stim=_ST),
        Test("ei_popss", pre=_pend(), code="    PUSH SS\n    EI\n    POP SS\n" + INCS, stim=_ST),
        Test("ei_pfx", pre=_pend(), code="    EI\n    DB 2Eh\n    MOV CW, [9F00h]\n" + INCS, stim=_ST),
        Test("ei_nop_pfx", pre=_pend(), code="    EI\n    NOP\n    NOP\n    DB 2Eh, 26h, 2Eh\n"
             "    INC AW\n" + INCS, stim=_ST),
        Test("ei_rep", pre=_pend(), code="    EI\n    DB 0F3h\n    MOVBKW\n" + INCS,
             regs={"CW": 8, "IX": 0x0000, "IY": 0x0040}, stim=_ST, sfr=False),
        Test("mk_rep_long", pre=sfr_wr("EXIC0", 0x47) + ev("E0") + wait(WAIT, "p"),
             code="    DB 26h\n    AND byte [0FF4Ch], 0BFh\n    DB 0F3h\n    MOVBKW\n" + INCS,
             regs={"CW": 0x0040, "IX": 0x0000, "IY": 0x0080}, psw=PSW_IE, stim=_ST, sfr=False),
        Test("ei_rep_pfx", pre=_pend(), code="    EI\n    DB 0F3h, 26h\n    MOVBKW\n" + INCS,
             regs={"CW": 8, "IX": 0x0000, "IY": 0x0080}, stim=_ST, sfr=False),
        Test("ei_ei", pre=_pend(), code="    EI\n    EI\n" + INCS, stim=_ST),
        Test("ei_halt", pre=_pend(), code="    EI\n    HALT\n" + INCS, stim=_ST),
        Test("ei_nop_halt", pre=_pend(), code="    EI\n    NOP\n    HALT\n" + INCS, stim=_ST),
        Test("reti_incs", pre=_pend(),
             code="    MOV AW, 0F202h\n    PUSH AW\n    XOR AW, AW\n    PUSH AW\n"
                  "    CALL rtgt{k}\nrtgt{k}:\n    POP AW\n    ADD AW, 9\n    PUSH AW\n"
                  "    MOV AW, 1234h\n    RETI\n" + INCS, stim=_ST),
        Test("sw_if_incs", code=sfr_wr("EXIC0", 0x87) + INCS, psw=PSW_IE),
        Test("div_ok", code="    DIVU CL\n", regs={"AW": 0x1234, "CW": 0x0040},
             note="no error: the flags a DIVU leaves (silicon F002 from 0002; the RTL's DIVF "
                  "sets S P CY: outside F3)"),
    ]
    return T


def _lg(at):
    """ISPR into PS:at (an action routine's log byte)."""
    return sfr_rd("ISPR", at)


def _vis(v, label):
    """Branch to `label` unless the vector being handled is v."""
    return f"    DB 2Eh\n    CMP byte [8002h], {_h(v)}\n    BNE {label}\n"


def prio_tests():
    """Priority, nesting, FINT, ISPR (requests by software stores of IF unless named; the
    interrupted stream is MULU CL, longer than the controller's latency)."""
    rel = "    EI\n" + CHAIN
    T = [
        Test("grp_p_order", code=sfr_wr("EXIC2", 0x87) + sfr_wr("EXIC1", 0x87)
             + sfr_wr("EXIC0", 0x87) + rel, note="INTP2, INTP1, INTP0 pending (the group at 7)"),
        Test("grp_tu_order", code=sfr_wr("TMIC2", 0x87) + sfr_wr("TMIC1", 0x87)
             + sfr_wr("TMIC0", 0x87) + rel, note="TU2 TU1 TU0"),
        Test("grp_ser_order", code=sfr_wr("STIC0", 0x87) + sfr_wr("SRIC0", 0x87)
             + sfr_wr("SEIC0", 0x87) + rel, note="ST0 SR0 SER0"),
        Test("grp_ser1_d", code=sfr_wr("STIC1", 0x87) + sfr_wr("SRIC1", 0x87)
             + sfr_wr("SEIC1", 0x87) + sfr_wr("DIC1", 0x87) + sfr_wr("DIC0", 0x87) + rel + CHAIN,
             note="ST1 SR1 SER1, D1 D0"),
        Test("grp_default", code=sfr_wr("TBIC", 0x87) + sfr_wr("SEIC1", 0x87)
             + sfr_wr("SEIC0", 0x87) + sfr_wr("EXIC0", 0x87) + sfr_wr("DIC0", 0x87)
             + sfr_wr("TMIC0", 0x87) + rel + CHAIN,
             note="all groups at 7: TU D P SER0 SER1 TB"),
        Test("grp_levels", code=sfr_wr("TMIC0", 0x86) + sfr_wr("DIC0", 0x83)
             + sfr_wr("EXIC0", 0x85) + sfr_wr("SEIC0", 0x80) + rel,
             note="TU 6, D 3, P 5, SER0 0"),
        Test("grp_mk_one", code=sfr_wr("TMIC0", 0xC7) + sfr_wr("TMIC1", 0x87) + rel,
             note="TU0 masked, TU1 alone"),
        Test("nest_higher", code=sfr_wr("EXIC0", 0x85) + rel,
             action=_vis(0x18, "nh{k}") + sfr_wr("TMIC0", 0x82) + "    EI\n" + ABS + ABS
             + _lg("{S}") + "    FINT\n" + ABS + _lg("{S}+1") + "    RET\nnh{k}:\n    FINT\n",
             note="in P's handler (5) TU at 2 requested, EI: it nests"),
        Test("nest_equal", code=sfr_wr("EXIC0", 0x85) + rel,
             action=_vis(0x18, "nq{k}") + sfr_wr("TMIC0", 0x85) + "    EI\n" + ABS + ABS
             + _lg("{S}") + "    FINT\n" + ABS + ABS + _lg("{S}+1") + "    RET\nnq{k}:\n    FINT\n",
             note="TU at the same level 5: waits for FINT"),
        Test("nest_lower", code=sfr_wr("EXIC0", 0x85) + rel,
             action=_vis(0x18, "nl{k}") + sfr_wr("TMIC0", 0x86) + "    EI\n" + ABS + ABS
             + _lg("{S}") + "    FINT\n" + ABS + ABS + _lg("{S}+1") + "    RET\nnl{k}:\n    FINT\n",
             note="TU at 6 (lower): waits for FINT"),
        Test("reti_nofint",
             code=sfr_wr("EXIC0", 0x87) + rel + _lg("{S}") + sfr_wr("TMIC0", 0x87)
             + CHAIN + sfr_rd("TMIC0", "{S}+1") + sfr_wr("DIC0", 0x86) + CHAIN + _lg("{S}+2")
             + "    FINT\n" + CHAIN + _lg("{S}+3"),
             action="    DB 2Eh\n    CMP byte [8002h], 18h\n    BE nf{k}\n    FINT\nnf{k}:\n",
             note="P's handler without FINT: ISPR 80 kept; TU at 7 waits; D at 6 taken; "
                  "FINT outside: TU"),
        Test("fint_highest", code=sfr_wr("EXIC0", 0x85) + rel,
             action=_vis(0x18, "fh{k}") + sfr_wr("TMIC0", 0x82) + "    EI\n" + ABS + ABS
             + "    DI\n" + _lg("{S}") + "    FINT\n" + _lg("{S}+1") + "    FINT\n" + _lg("{S}+2")
             + "    RET\nfh{k}:\n",
             note="TU (2) nests and returns without FINT: ISPR 24; FINT clears 04; FINT 20"),
        Test("nmi_in_handler", jitter=True, code=sfr_wr("EXIC0", 0x87) + rel,
             action=_vis(0x18, "nm{k}") + ev("E1") + "ahl{k}:\n    HALT\n" + ABS + "    FINT\nnm{k}:\n",
             stim=[pulse("E1", "NMI")],
             note="NMI in P's handler (IE 0, in HALT): nests"),
        Test("nmi_in_nmi", jitter=True, code=ev("E1") + "    HALT\n" + wait(WAIT * 2, "w"),
             action=nmi_skip() + "    DB 2Eh\n    CMP byte [{S}+15], 0\n    BNE nn{k}\n"
             "    DB 2Eh\n    MOV byte [{S}+15], 1\n" + ev("E2") + "ahl{k}:\n    HALT\n" + ABS
             + "nn{k}:\n",
             stim=[pulse("E1", "NMI"), pulse("E2", "NMI")],
             note="a second NMI in the NMI handler (in HALT): nests?"),
        Test("int_in_nmi", jitter=True, code=ev("E0") + "    HALT\n" + CHAIN,
             action=_vis(2, "in{k}") + nmi_skip() + sfr_wr("EXIC0", 0x87) + "    EI\n" + ABS
             + ABS + "    DI\n    RET\nin{k}:\n    FINT\n",
             stim=[pulse("E0", "NMI")], note="a maskable request with EI in the NMI handler"),
        Test("pr0_vs_tb", code=sfr_wr("TBIC", 0x87) + sfr_wr("TMIC0", 0x80) + rel,
             note="TU at 0 and TB"),
        Test("ispr_read_fint0", code="    FINT\n" + _lg("{S}") + sfr_wr("EXIC0", 0x80) + rel
             + _lg("{S}+1"), note="FINT with nothing in service; ISPR"),
    ]
    return T


def trap_tests():
    """The divide error (vector 0), BRKV, 0F 9A."""
    fix = "    PUSH AW\n    DB 0B8h\n    DW cont{k}\n    MOV [BP+12], AW\n    POP AW\n"
    T = [
        Test("divu8_zero", code="    DIVU CL\n", regs={"AW": 0x1234, "CW": 0x0000}, action=fix,
             note="DIVU CL, CL 0"),
        Test("divu16_zero", code="    DIVU CW\n", regs={"AW": 0x1234, "CW": 0, "DW": 5},
             action=fix, note="DIVU CW, CW 0"),
        Test("divu8_ovf", code="    DIVU CL\n", regs={"AW": 0x1234, "CW": 0x0010}, action=fix,
             note="DIVU quotient 123h"),
        Test("divu16_ovf", code="    DIVU CW\n", regs={"AW": 0x0000, "DW": 0x0010, "CW": 0x0010},
             action=fix, note="DIVU 100000h / 10h"),
        Test("div16_ovf", code="    DIV CW\n", regs={"AW": 0x0000, "DW": 0x4000, "CW": 2},
             action=fix, note="DIV 40000000h / 2"),
        Test("div8_neg_ovf", code="    DIV CL\n", regs={"AW": 0x8000, "CW": 0x00FF},
             action=fix, note="DIV 8000h / -1"),
        Test("div16_min", code="    DIV CW\n", regs={"AW": 0x0000, "DW": 0x8000, "CW": 0xFFFF},
             action=fix, note="DIV 80000000h / -1"),
        Test("div8_zero", code="    DIV CL\n", regs={"AW": 0x0034, "CW": 0}, action=fix,
             note="DIV CL, 0"),
        Test("div16_zero", code="    DIV CW\n", regs={"AW": 0x0034, "DW": 0, "CW": 0},
             action=fix, note="DIV CW, 0"),
        Test("divu_m8", code="    DIVU byte [IX]\n", regs={"AW": 0x1234, "IX": 0x0010},
             pre="    MOV byte [IX], 00h\n", action=fix, sfr=False, note="DIVU [IX] = 0"),
        Test("divu_m16_pfx", code="    DB 26h\n    MOV word [IX+2], 0000h\n"
             "    DB 26h\n    DIVU word [IX+2]\n", regs={"IX": 0x0010}, action=fix, sfr=False,
             note="DS1: DIVU [IX+2] = 0"),
        Test("div_m16_d16", code="    DIV word [IX+0100h]\n", regs={"IX": 0x0010, "AW": 5},
             pre="    MOV word [IX+0100h], 0000h\n", action=fix, sfr=False,
             note="DIV [IX+100h] = 0"),
        Test("div_ie", code="    DIVU CL\n", regs={"AW": 0x1234, "CW": 0}, psw=0x0ED7,
             action=fix, note="the flags and IE: the pushed and handler PSW"),
        Test("brkv_v", code="    BRKV\n", psw=0x0802, action="", note="V set: vector 4"),
        Test("brkv_nv", code="    BRKV\n", psw=0x0002, action="", note="V clear"),
        Test("op_0f9a", code="    DB 0Fh, 9Ah\n    INC AW\n", action="", note="0F 9A (F2b: vector 1)"),
    ]
    return T


def step_tests():
    """Single step (PSW.BRK, vector 1)."""
    stop = "    PUSH AW\n    MOV AW, 0002h\n    PUSH AW\n    POP PSW\n    POP AW\n"
    go = "    PUSH AW\n    MOV AW, 0102h\n    PUSH AW\n    POP PSW\n    POP AW\n"
    T = [
        Test("step_incs", code=go + "    INC AW\n    INC AW\n" + stop + "    INC AW\n", action="",
             note="BRK set by POP PSW: the steps; cleared by POP PSW"),
        Test("step_pfx", code=go + "    NOP\n    DB 2Eh\n    MOV CW, [9F00h]\n    INC AW\n" + stop,
             action="", note="a prefixed instruction stepped"),
        Test("step_movss", code=go + "    NOP\n    MOV SS, BW\n    INC AW\n" + stop, regs={"BW": 0},
             action="", note="MOV SS stepped"),
        Test("step_popss", code="    PUSH SS\n" + go + "    NOP\n    POP SS\n    INC AW\n" + stop,
             action="", note="POP SS stepped"),
        Test("step_movds0", code=go + "    NOP\n    MOV DS0, BW\n    INC AW\n" + stop,
             regs={"BW": 0x0A00}, action="", note="MOV DS0 stepped (the control)"),
    ]
    return T


def step2_tests():
    """Single step (PSW.BRK, vector 1), part 2."""
    stop = "    PUSH AW\n    MOV AW, 0002h\n    PUSH AW\n    POP PSW\n    POP AW\n"
    go = "    PUSH AW\n    MOV AW, 0102h\n    PUSH AW\n    POP PSW\n    POP AW\n"
    T = [
        Test("step_rep", code=go + "    NOP\n    DB 0F3h\n    MOVBKW\n    INC AW\n" + stop,
             regs={"CW": 3, "IX": 0, "IY": 0x40}, action="", sfr=False,
             note="REP MOVBKW CW 3 stepped"),
        Test("step_brk3", code=go + "    NOP\n    BRK 3\n    INC AW\n" + stop, action="",
             note="BRK 3 stepped"),
        Test("step_intp", pre=sfr_wr("EXIC0", 0x07) + ev("E0") + wait(WAIT, "p"),
             code="    MOV BW, 0302h\n    PUSH BW\n    POP PSW\n" + ABS + "    INC AW\n" + stop,
             stim=[pulse("E0", "INTP0", delay=200)], action=_vis(0x18, "sp{k}") + "    FINT\nsp{k}:\n",
             note="BRK and IE set together with INTP0 pending"),
        Test("step_ei", code=go + "    NOP\n    EI\n    INC AW\n    DI\n" + stop, action="",
             note="EI stepped"),
        Test("step_sahf", code=go + "    NOP\n    MOV AH, 02h\n    MOV PSW, AH\n    INC AW\n" + stop,
             action="", note="SAHF does not touch BRK"),
    ]
    return T


def f5_step_tests():
    """(F5c) The single step and an interrupt at the boundary after each instruction that loads
    the PSW or the in-service state: POP PSW, RETI, MOV PSW,AH, FINT, the flag instructions
    (the fuzz's step programs: no step after POP PSW and FINT on silicon)."""
    stop = "    PUSH AW\n    MOV AW, 0002h\n    PUSH AW\n    POP PSW\n    POP AW\n"
    go = "    PUSH AW\n    MOV AW, 0102h\n    PUSH AW\n    POP PSW\n    POP AW\n"
    ret = ("    MOV AW, {psw}\n    PUSH AW\n    XOR AW, AW\n    PUSH AW\n    CALL rtgt{{k}}\n"
           "rtgt{{k}}:\n    POP AW\n    ADD AW, {d}\n    PUSH AW\n{mid}    RETI\n")
    T = [
        Test("st_popsw_keep", code=go + "    NOP\n    PUSH BW\n    POP PSW\n    INC AW\n    INC AW\n"
             + stop, regs={"BW": 0x0102}, action="", note="POP PSW keeping BRK 1 stepped"),
        Test("st_popsw_flags", code=go + "    NOP\n    PUSH BW\n    POP PSW\n    INC AW\n    INC AW\n"
             + stop, regs={"BW": 0x0DD7}, action="", note="POP PSW BRK 1, DIR and the flags"),
        Test("st_popsw_twice", code=go + "    NOP\n    PUSH BW\n    PUSH BW\n    POP PSW\n"
             "    POP PSW\n    INC AW\n" + stop, regs={"BW": 0x0103}, action="",
             note="two POP PSW in a row stepped"),
        Test("st_fint", code=go + "    NOP\n    FINT\n    INC AW\n    INC AW\n" + stop, action="",
             note="FINT stepped (nothing in service)"),
        Test("st_fint2", code=go + "    NOP\n    FINT\n    FINT\n    INC AW\n" + stop, action="",
             note="two FINTs stepped"),
        Test("st_reti", code=go + "    NOP\n" + ret.format(psw="0F103h", d=9, mid="    MOV AW, 1234h\n")
             + "    INC AW\n    INC AW\n" + stop, action="", note="RETI to BRK 1 stepped"),
        Test("st_sahf", code=go + "    NOP\n    MOV AH, 0D7h\n    MOV PSW, AH\n    INC AW\n" + stop,
             action="", note="MOV PSW,AH stepped"),
        Test("st_flagops", code=go + "    NOP\n" + _db([0xF9, 0xF8, 0xF5, 0xFD, 0xFC]) + "    INC AW\n"
             + stop, action="", note="SET1 CY, CLR1 CY, NOT1 CY, SET1 DIR, CLR1 DIR stepped"),
        Test("st_popsw_ie", code=go + "    NOP\n    PUSH BW\n    POP PSW\n    INC AW\n    DI\n"
             + stop, regs={"BW": 0x0302}, action="", note="POP PSW setting IE with BRK 1"),
        Test("st_popsw_fint", code=go + "    NOP\n    PUSH BW\n    POP PSW\n    FINT\n    INC AW\n"
             + stop, regs={"BW": 0x0102}, action="", note="POP PSW then FINT stepped"),
        Test("in_nop", pre=_pend(), code="    MOV BW, 0202h\n    PUSH BW\n    EI\n    NOP\n" + CHAIN,
             stim=_ST, note="the control: EI, NOP: taken after the NOP"),
        Test("in_popsw", pre=_pend(), code="    MOV BW, 0202h\n    PUSH BW\n    EI\n    POP PSW\n"
             + CHAIN, stim=_ST, note="EI, POP PSW (IE 1): taken after it or after the MULU"),
        Test("in_fint", pre=_pend(), code="    EI\n    FINT\n" + CHAIN, stim=_ST,
             note="EI, FINT (nothing in service)"),
        Test("in_sahf", pre=_pend(), code="    EI\n    MOV PSW, AH\n" + CHAIN, stim=_ST,
             note="EI, MOV PSW,AH"),
        Test("in_reti", pre=_pend(), code=ret.format(psw="0F202h", d=7, mid="    EI\n") + CHAIN,
             stim=_ST, note="EI, RETI (to IE 1): taken after the RETI or the MULU"),
        Test("in_flag", pre=_pend(), code="    EI\n" + _db([0xF9]) + CHAIN, stim=_ST,
             note="EI, SET1 CY"),
    ]
    return T


def programs():
    return {
        "f5_step": make_program("f5_step", f5_step_tests()[:5],
                                note="(F5c) the step after the PSW loaders, part 1"),
        "f5_step2": make_program("f5_step2", f5_step_tests()[5:10],
                                 note="(F5c) the step after the PSW loaders, part 2"),
        "f5_stepi": make_program("f5_stepi", f5_step_tests()[10:], gate=False,
                                 note="(F5c) measured only: an interrupt after the PSW loaders "
                                      "(the take lands after the MULU in every test, the NOP "
                                      "control's too: the controller's latency is longer than "
                                      "the instruction after EI, so these do not tell)"),
        "f3_vec": make_program("f3_vec", vec_tests(),
                               note="the sources, the entry, the edges, HALT's wake"),
        "f3_order": make_program("f3_order", order_tests(),
                                 note="the interrupted point after a release and an absorber"),
        "f3_prio": make_program("f3_prio", prio_tests(),
                                note="priority, nesting, FINT, ISPR, NMI"),
        "f3_trap": make_program("f3_trap", trap_tests(),
                                note="the divide error, BRKV, 0F 9A"),
        "f3_step": make_program("f3_step", step_tests(), note="single step"),
        "f3_step2": make_program("f3_step2", step2_tests(), note="single step, part 2"),
        "f3_lat": make_program("f3_lat", lat_tests(), gate=False,
                               note="measured only: the take point right after a release"),
    }


# ------------------------------------------------------------------ running
def receipt_path(name, backend):
    return RECEIPTS / f"f3-{name}-{backend}.json"


def save(rec, name, backend):
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt_path(name, backend).write_text(json.dumps(rec, indent=1) + "\n")


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def run_set(names, backend, tag="", progs=None, limit=40_000_000):
    from .traps import _board, _close_board, _sim, _stim
    progs = progs or programs()
    out = []
    lane = "socket" if backend == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    try:
        for name in names:
            if backend != "socket":
                transport, harness = _sim()
            try:
                _stim(harness, progs[name])
                rec = run_one(harness, progs[name], lane, limit=limit)
            finally:
                if backend != "socket":
                    transport.close()
            rec.update(backend=backend, date=datetime.datetime.now().isoformat(timespec="seconds"),
                       stim=progs[name].stim, levels=progs[name].levels)
            if backend == "socket":
                rec.update(cpu="uPD70337L-8", x_half=2)
            else:
                rec.update(core="v35", binary=os.environ.get(
                    "V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
            save(rec, name, backend + tag)
            out.append(rec)
            print(f"{name}: {backend} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} writes={len(rec['writes'])} total={rec['total']}",
                  flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)
    return out


# ------------------------------------------------------------------ reading a receipt
def _w(b, o):
    return b[o] | b[o + 1] << 8


def decode(rec):
    regs = rec["regions"]
    log = bytes.fromhex(regs[f"{LOG + 0x100:05X}"])
    count = _w(bytes.fromhex(regs[f"{LOG:05X}"]), 0)
    entries = []
    for k in range(min(count, len(log) // 32)):
        e = log[32 * k:32 * k + 32]
        entries.append({"vec": e[0], "depth": e[1], "test": _w(e, 2), "pc": _w(e, 4),
                        "ps": _w(e, 6), "psw": _w(e, 8), "hpsw": _w(e, 10), "sp": _w(e, 12),
                        "ispr": e[14], "exic0": e[15], "exic1": e[16], "exic2": e[17],
                        "tmic0": e[18], "dic0": e[19], "tbic": e[28], "seic0": e[29],
                        "AW": _w(e, 20), "CW": _w(e, 22), "IX": _w(e, 24), "IY": _w(e, 26),
                        "DW": _w(e, 30)})
    slots = bytes.fromhex(regs[f"{SLOTS:05X}"])
    scr = bytes.fromhex(regs[f"{SCRATCH:05X}"])
    out = []
    for k in range(len(slots) // 32):
        s = slots[32 * k:32 * k + 32]
        d = {r: _w(s, 2 * i) for i, r in enumerate(
            ("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY", "DS0", "DS1", "SS", "PSW"))}
        d.update(ispr=s[24], exic0=s[25], exic1=s[26], exic2=s[27], tmic0=s[28], count=_w(s, 30),
                 scratch=scr[16 * k:16 * k + 16].hex())
        out.append(d)
    return count, entries, out


def labels_of(prog):
    """Label -> address, from the assembler's own two passes."""
    from .asm import _assembler, _expand
    asm = _assembler()
    lines = asm._parse_lines(_expand(prog.source))
    labels = {}
    for _pass in (1, 2):
        pc = 0x100
        for ln, kind, payload in lines:
            if kind == "label":
                labels[payload] = pc
            elif kind == "org":
                pc = payload
            elif kind == "db":
                pc += len(payload)
            elif kind == "dw":
                pc += 2 * len(payload)
            else:
                pc += len(asm._encode(payload, pc, labels, _pass))
    return labels


def where(labels, pc):
    best = None
    for nm, a in labels.items():
        if a <= pc and (best is None or a > best[1]):
            best = (nm, a)
    return f"{best[0]}+{pc - best[1]}" if best else f"{pc:04X}"


def show(name, backend="socket", progs=None):
    progs = progs or programs()
    prog = progs[name]
    rec = load(name, backend)
    count, entries, slots = decode(rec)
    labels = labels_of(prog)
    print(f"{name} ({backend}): passed {rec['passed']} status {rec['status']:04x} log {count}")
    by_test = {}
    for e in entries:
        by_test.setdefault(e["test"], []).append(e)
    for k, t in enumerate(prog.tests):
        s = slots[k] if k < len(slots) else {}
        print(f"{k:2d} {t.name:18s} || " + " ".join(
            f"{r}={v:04X}" for r, v in s.items() if r in ("AW", "CW", "SP", "PSW"))
            + f" ispr={s.get('ispr', 0):02X} exic0={s.get('exic0', 0):02X}"
              f" tmic0={s.get('tmic0', 0):02X} n={s.get('count', 0)} scr={s.get('scratch', '')[:12]}")
        for e in by_test.get(k, []):
            print(f"     v{e['vec']:<2d} d{e['depth']} pc={e['ps']:04X}:{e['pc']:04X}"
                  f" [{where(labels, e['pc'])}] psw={e['psw']:04X}"
                  f" h={e['hpsw']:04X} sp={e['sp']:04X} ispr={e['ispr']:02X} ex0={e['exic0']:02X}"
                  f" ex1={e['exic1']:02X} ex2={e['exic2']:02X} tm0={e['tmic0']:02X} dic0={e['dic0']:02X}"
                  f" tb={e['tbic']:02X} se0={e['seic0']:02X} AW={e['AW']:04X} CW={e['CW']:04X}"
                  f" IX={e['IX']:04X} IY={e['IY']:04X}")


# ------------------------------------------------------------------ the gate
STACK = range(0x7E00, 0x7F00)


def jitter_bytes(name, ref="socket", progs=None):
    """The gate's masked bytes of a program: the stack's data (the log holds every frame
    pushed), and the log entries of the tests whose take point follows HALT with IE 1 or an NMI
    (Test.jitter) but their vector, depth, test, ISPR and IC bytes."""
    progs = progs or programs()
    prog = progs[name]
    ex = set(STACK)
    rec = load(name, ref)
    _, entries, _ = decode(rec)
    for i, e in enumerate(entries):
        if e["test"] < len(prog.tests) and prog.tests[e["test"]].jitter:
            base = LOG + 0x100 + 32 * i
            ex |= {base + j for j in range(32) if not (j < 4 or 14 <= j < 20 or 28 <= j < 30)}
    return ex


def compare_gate(names, ref="socket", cand="sim", exclude=None):
    """The write and I/O sequence and the result regions equal (the bytes in exclude(name)
    masked)."""
    from .onchip import _masked_writes
    ok_all = True
    for name in names:
        a, b = load(name, ref), load(name, cand)
        ex = exclude(name) if exclude else set()
        wa, wb = _masked_writes(a["writes"], ex), _masked_writes(b["writes"], ex)
        diffs = []
        for key in a["regions"]:
            base = int(key, 16)
            ra, rb = bytes.fromhex(a["regions"][key]), bytes.fromhex(b["regions"].get(key, ""))
            diffs += [(base + i, ra[i], rb[i] if i < len(rb) else -1) for i in range(len(ra))
                      if base + i not in ex and (i >= len(rb) or ra[i] != rb[i])]
        same_io = a["io_reads"] == b["io_reads"]
        ok = wa == wb and not diffs and a["passed"] == b["passed"]
        ok_all &= ok
        first = next((i for i, (x, y) in enumerate(zip(wa, wb)) if x != y), None)
        print(f"{name}: gate {'EQUAL' if ok else 'DIFFER'} writes {len(wa)}/{len(wb)}"
              + ("" if first is None else
                 f" first difference at {first}: {wa[first][0]:05X} {wa[first][1]:04X} "
                 f"{wa[first][2]:03X} / {wb[first][0]:05X} {wb[first][1]:04X} {wb[first][2]:03X}")
              + f" io_reads {'equal' if same_io else 'differ'} passed {a['passed']}/{b['passed']}"
              + ("" if not diffs else " result bytes differ: " +
                 ", ".join(f"{x:05X}:{y:02X}/{z:02X}" for x, y, z in diffs[:16])
                 + (f" (+{len(diffs) - 16})" if len(diffs) > 16 else "")))
    return ok_all


def emit(progs=None):
    for name, prog in (progs or programs()).items():
        path = PROGRAMS_DIR / f"{name}.s"
        path.write_text(f"; F3 ({prog.note}). Generated by validation/v35s/intr.py emit: the\n"
                        f"; image also preloads the vector stubs, the handler and the data.\n"
                        + prog.source)
        stim = PROGRAMS_DIR / f"{name}.stim.json"
        if prog.stim:
            stim.write_text(json.dumps(prog.stim, indent=1) + "\n")
        print(path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "gate", "show", "emit", "size"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    a = p.parse_args()
    progs = programs()
    names = a.names or [n for n, prog in progs.items() if a.action == "socket" or prog.gate]
    if a.action in ("socket", "sim"):
        run_set(names, a.action, a.tag, progs)
    elif a.action == "gate":
        return 0 if compare_gate(names, a.ref, a.cand,
                                 exclude=lambda n: jitter_bytes(n, a.ref, progs)) else 1
    elif a.action == "show":
        for n in names:
            show(n, a.ref, progs)
    elif a.action == "size":
        for n in names:
            code, _, _ = progs[n].image()
            print(n, f"{len(code)} bytes, {len(progs[n].tests)} tests, "
                  f"{len((progs[n].stim or {}).get('entries', []))} entries")
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
