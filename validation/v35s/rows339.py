"""F5: socket rows for the corpus groups of build/overseer/miss339 (the f5_wy_* program set;
build/overseer/miss339-rows). r1left's frame (a lead, the subject Y, MOV AW,[0890h], INC AW x 6, the filler)
with PRC = 4Eh, refresh off, code, stack and data in block 0.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.rows339 socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.rows339 sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.rows339 repeat | gate [-v] | show [--be socket] | emit

Groups (programs f5_wy_<group>_r1):
    p       MOV PS,AW and MOV PS,[mem] with a value that maps the same code 10h lower (segment 0FFFh): does
            the fetch address change at once, at a flush, or never before the next transfer? The sixteen bytes
            in front of the instruction's end are NOPs and one increment of the source, so a stream that
            re-runs them (an immediate change, or a flush) loads PS with 1000h again; forty NOPs behind it
            absorb a stream that skips sixteen bytes; BR far 1000h:next closes the window
    q       MOV PS,AW (0FFFh) ; NOP x 20 ; BR $+2: the short branch is the first flush behind the load (its
            target is among the NOPs if PS took the value: the branch then runs twice)
Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import sys

from . import onchip_t as oc
from . import phase as ph
from . import r1left as r1
from . import wstore2 as w2
from . import wstore4 as w4

PFX = "f5_wy"
SEG, ALT, PTR = r1.SEG, r1.ALT, r1.PTR
_w = r1._w
P = _w(PTR)
NOP = 0x90

YS = {
    # ---- group p: MOV PS,r/m (the bytes are several instructions: the subject is the last before the pad)
    "ps": ([0xB8] + _w(ALT - 1) + [NOP] * 13 + [0x40, 0x8E, 0xC8] + [NOP] * 40,
           f"MOV AW,{ALT - 1:04X}h ; NOP x 13 ; INC AW ; MOV PS,AW ; NOP x 40", {"alt": 1}),
    "pm": ([0xC7, 0x06] + P + _w(ALT - 1) + [NOP] * 8 + [0xFF, 0x06] + P + [0x8E, 0x0E] + P + [NOP] * 40,
           f"MOV word [{PTR:04X}h],{ALT - 1:04X}h ; NOP x 8 ; INC word [{PTR:04X}h] ; MOV PS,[{PTR:04X}h] ; NOP x 40",
           {"alt": 1}),
    "pj": ([0xB8] + _w(ALT) + [NOP] * 14 + [0x8E, 0xC8] + [NOP] * 20 + [0xEB, 0x00] + [NOP] * 40,
           f"MOV AW,{ALT:04X}h ; NOP x 14 ; MOV PS,AW ; NOP x 20 ; BR $+2 ; NOP x 40", {"alt": 1}),
}

# ---- groups b1, b2: a word string element's write across a WTC block boundary (blocks are 20000h long)
BADDR = {"a": 0x1FFFD, "b": 0x1FFFE, "c": 0x1FFFF, "d": 0x20000, "e": 0x20001, "f": 0x3FFFD, "g": 0x3FFFF,
         "h": 0x40001}
BNOTE = {"a": "odd, 0 / 0 waits", "b": "even, 0", "c": "odd, 0 / w", "d": "even, w", "e": "odd, w / w",
         "f": "odd, w / w", "g": "odd, w / 0", "h": "odd, 0 / 0"}
_FILB = [0xC1, 0xC5, 0x10]
BFORMS = {"r1": ([0xF3, 0xAB], "REP STMW (CW 1)", 1), "r2": ([0xF3, 0xAB], "REP STMW (CW 2)", 2),
          "st": ([0xAB], "STMW", 1), "mk": ([0xF3, 0xA5], "REP MOVBKW (CW 1)", 1)}


def _bstr(form, key):
    lin = BADDR[key]
    op, txt, n = BFORMS[form]
    start = lin - 2 * (n - 1)
    seg = (lin & ~0xFFF) - 0x1000 >> 4          # the element's page and the one below it in one segment
    iy = start - (seg << 4)
    return ([0xB8] + _w(seg) + [0x8E, 0xC0, 0xBF] + _w(iy) + [0xB9] + _w(n) + _FILB + op,
            f"MOV AW,{seg:04X}h ; MOV DS1,AW ; MOV IY,{iy:04X}h ; MOV CW,{n} ; ROL BP,16 ; {txt}"
            f"   ; the last element at {lin:05X}h ({BNOTE[key]})", {})


for _f in BFORMS:
    for _k in BADDR:
        YS[f"{_f}{_k}"] = _bstr(_f, _k)
r1.YS.update(YS)

GROUPS = {
    "p": ([(y, l, al, 0) for y in ("ps", "pm") for l in ("f0", "f1", "j0", "j1") for al in (0, 1)]
          + [(y, "f0", al, w) for y in ("ps", "pm") for w in (1, 2) for al in (0, 1)]),
    "q": [("pj", l, al, 0) for l in ("f0", "j0") for al in (0, 1)],
    # (the window's w is the raw WTC word here: block 1's field alone, w << 2)
    "b1": [(f"{f}{k}", "f0", al, 1 << 2) for f in BFORMS for k in BADDR for al in (0, 1)],
    "b2": [(f"{f}{k}", "f0", al, 2 << 2) for f in BFORMS for k in BADDR for al in (0, 1)],
}
NOTES = {
    "p": "MOV PS,AW / MOV PS,[mem] into segment 0FFFh (the same code 10h lower)",
    "q": "MOV PS,AW (0FFFh), twenty NOPs, BR $+2: the first flush behind the load",
    "b1": "word string elements across a WTC block boundary, block 1 at 1 wait (WTC 0004h)",
    "b2": "word string elements across a WTC block boundary, block 1 at 2 waits (WTC 0008h)",
}
PAGES = (0x1E, 0x1F, 0x20, 0x3E, 0x40)      # data pages mapped beside the frame's (00h, 3Fh, FFh)
PAGED = ("b1", "b2")


class Program(ph.Program):
    def build(self):
        if not self._built:
            b = super().build()
            for p in PAGES:
                b["segments"].setdefault(p << 12, bytes(ph.pat(p << 12 | o) for o in range(0x1000)))
            b["text"] += b"pages" + bytes(PAGES)
        return self._built


# ---- the groups in wstore4's frame (xwindow: block 0 at w waits, or at 2 waits and READY)
_OUT = ([0xE6, 0x20], "OUT 20h, AL   ; lead: an I/O write")
_MRR = ([0x8B, 0xC8], "MOV CW, AW   ; lead")
_MI = ([0xB8, 0x34, 0x12], "MOV AW, 1234h   ; lead")
_PU = ([0x53], "PUSH BW   ; lead")
_NOPL = ([0x90], "NOP   ; lead")
_F = w2._FIL
w4.XLEADS.update({
    "o0": (_F, _OUT), "o1": (_F, _OUT, _NOPL), "od": (_F, _OUT, _MI), "om": (_F, _OUT, _MRR),
    "ox": (_F, _OUT, _MRR, _NOPL), "pm": (_F, _PU, _MRR),
})
STO = [0xC7, 0x80, 0x00, 0xFB, 0x34, 0x12]          # MOV word [BW+IX-0500h],1234h: 0B80h
STR = [0x89, 0x80, 0x00, 0xFB]
A8 = [0x83, 0x87, 0x00, 0x01, 0x05]                 # ADD word [BW+0100h],5: 0980h
XS = {
    # A / K: the commit words
    "xi": ([0x0F, 0x3B, 0xC1, 0x07], "EXT CL, 7", {"cw": 0}),
    "ni": ([0x0F, 0x39, 0xC1, 0x07], "INS CL, 7", {"cw": 0}),
    "r4": ([0x0F, 0x28, 0xC1], "ROL4 CL", {"cw": 0}),
    "sh": ([0xC1, 0xE3, 0x04], "SHL BW, 4", {}),
    "s1": ([0x0F, 0x1D, 0x07, 0x0F], "SET1 word [BW], 15", {}),
    "c1": ([0x0F, 0x1B, 0x07, 0x0F], "CLR1 word [BW], 15", {}),
    # E: IN acc,DW (DW is the frame's marker port FE40h) and SHL [m],CL
    "in": ([0xEC], "IN AL, DW", {}),
    "iw": ([0xED], "IN AW, DW", {}),
    "sc": ([0xD3, 0x27], "SHL word [BW], CL", {"cw": 1}),
    # F and the request word behind the EU's own I/O write: stack forms
    "ps": ([0x1E], "PUSH DS0", {}),
    "pi": ([0x6A, 0x12], "PUSH 12h", {}),
    "pa": ([0x50], "PUSH AW", {}),
    "po": ([0x5B], "POP BW", {}),
    "cn": ([0xE8, 0x00, 0x00], "CALL $+3", {}),
    "cr": ([0xE8, 0x02, 0x00, 0xEB, 0x03, 0xC2, 0x00, 0x00], "CALL $+5 ; BR $+5 ; RET 0   ; the corpus's frame", {}),
    # G: forms whose two operand bytes are released on their last word
    "ad": ([0x81, 0xC3, 0x34, 0x12], "ADD BW, 1234h", {}),
    "si": (STO, "MOV word [BW+IX-0500h], 1234h", {}),
    "le": ([0x8D, 0x98, 0x00, 0x02], "LDEA BW, [BW+IX+0200h]", {}),
    "mu": ([0x69, 0xC1, 0x34, 0x12], "MUL AW, CW, 1234h", {}),
    # H / I: d16 stores and read-modify-write in a row
    "s2": (STO * 2, "MOV word [BW+IX-0500h], 1234h x 2", {}),
    "s3": (STO * 3, "MOV word [BW+IX-0500h], 1234h x 3", {}),
    "x2": (STR * 2, "MOV [BW+IX-0500h], AW x 2", {}),
    "a8": (A8, "ADD word [BW+0100h], 5", {}),
    "a9": (A8 * 2, "ADD word [BW+0100h], 5 x 2", {}),
}
w4.XS.update(XS)
AY = ("xi", "ni", "r4", "sh", "s1", "c1")
W3 = (0, 1, 2)
XGROUPS = {     # name: (windows (y, lead, al, w), READY, note)
    "an": ([(y, l, al, w) for y in AY for w in W3 for l in ("o0", "o1", "od", "pu", "f0") for al in (0, 1)], False,
           "commit words (EXT / INS, ROL4, SHL r,imm8, SET1 / CLR1 [m],imm) behind an I/O write, a push and the "
           "filler at 0, 1, 2 waits"),
    "e": ([(y, l, al, w) for y in ("in", "iw", "sc") for w in W3 for l in ("om", "pm", "o0", "pu", "ox")
           for al in (0, 1)], False, "IN acc,DW and SHL [m],CL behind OUT / PUSH and MOV r,r at 0, 1, 2 waits"),
    "f": ([(y, l, al, w) for y in ("ps", "pi", "pa", "po", "cn", "cr") for w in W3
           for l in ("pu", "o0", "o1", "f0", "f1", "f2") for al in (0, 1)], False,
          "stack forms behind a push, an I/O write and the filler at 0, 1, 2 waits"),
    "g": ([(y, l, al, w) for y in ("ad", "si", "le", "mu") for w in (0, 1)
           for l in ("f0", "f1", "f2", "o0", "o1", "pu") for al in (0, 1)], False,
          "forms with two late-released operand bytes behind NOPs, an I/O write and a push at 0, 1 waits"),
    "h": ([(y, l, al, w) for y in ("s2", "s3", "x2", "a8", "a9") for w in (0, 1)
           for l in ("pu", "o0", "o1", "f0") for al in (0, 1)], False,
          "d16 stores and read-modify-write in a row at 0, 1 waits"),
}
AREADY = {"a0": None, "a1": 1.0, "a2": 2.0, "a3": 3.0, "a4": 4.0, "a5": 5.0}
for _g, _h in AREADY.items():
    XGROUPS[_g] = ([(y, l, al, 2) for y in AY for l in ("o0", "od") for al in (0, 1)], True,
                   f"group an's commit words with the code at 2 waits and READY, READY low {_h or 0} clocks from "
                   f"/MREQ's fall of a block-0 cycle")
# (item 5) BR far [mem] / CALL far [mem] in r1left's frame behind more leads and at waits
GROUPS["m"] = [(y, l, al, w) for y in ("jm", "cm") for w in W3
               for l in ("j0", "j1", "j2", "j3", "f0", "f1", "f2", "f3") for al in (0, 1)]
NOTES["m"] = "BR far [mem] / CALL far [mem] into segment 0FFFh behind eight leads at 0, 1, 2 waits"


# ================================================================== the second session (miss339-rows2)
import itertools

_INCB = ([0x43], "INC BW   ; lead")
SEQS = [""] + ["".join(s) for n in (1, 2, 3, 4) for s in itertools.product("IN", repeat=n)]    # I: INC BW, N: NOP
_SEQ = {"I": _INCB, "N": _NOPL}
for _s in SEQS:
    _t = tuple(_SEQ[c] for c in _s)
    w4.XLEADS[f"F{_s}"] = (_F,) + _t                 # the filler, then the sequence
    w4.XLEADS[f"O{_s}"] = (_F, _OUT) + _t            # an I/O write in front
    w4.XLEADS[f"P{_s}"] = (_F, _PU) + _t             # a push in front
    w4.XLEADS[f"M{_s}"] = (_F, _OUT, _MRR) + _t      # OUT ; MOV r,r in front
    w4.XLEADS[f"Q{_s}"] = (_F, _PU, _MRR) + _t       # PUSH ; MOV r,r in front
S2 = [s for s in SEQS if len(s) <= 2]
S3 = [s for s in SEQS if len(s) <= 3]
DIRW = [w2.DIR & 0xFF, w2.DIR >> 8]
XS2 = {
    "sa": ([0xA3] + DIRW, f"MOV [{w2.DIR:04X}h], AW", {}),
    "la": ([0xA1] + DIRW, f"MOV AW, [{w2.DIR:04X}h]", {}),
}
# group j: the wait behind an instruction's last EU cycle, a single cycle (even) against a no-wait pair (odd)
_SEGW = _w(SEG)
JF = {      # name: (register, even value, subject bytes or a function of the next offset, text, CW)
    "r1": ("IY", w2.DST, [0xF3, 0xAB], "REP STMW", 1), "r2": ("IY", w2.DST, [0xF3, 0xAB], "REP STMW", 2),
    "st": ("IY", w2.DST, [0xAB], "STMW", 1), "mk": ("IY", w2.DST, [0xF3, 0xA5], "REP MOVBKW", 1),
    "m1": ("IY", w2.DST, [0xA5], "MOVBKW", 1), "ni": ("IY", w2.DST, [0x6D], "INMW", 1),
    "rn": ("IY", w2.DST, [0xF3, 0x6D], "REP INMW", 1), "cb": ("IY", w2.DST, [0xA7], "CMPBKW", 1),
    "rc": ("IY", w2.DST, [0xF3, 0xA7], "REPE CMPBKW", 1), "cs": ("IY", w2.DST, [0xAF], "CMPMW", 1),
    "rs": ("IY", w2.DST, [0xF3, 0xAF], "REPE CMPMW", 1), "lm": ("IX", w2.SRC, [0xAD], "LDMW", 1),
    "rl": ("IX", w2.SRC, [0xF3, 0xAD], "REP LDMW", 1),
    "pa": ("SP", oc.STACK_TOP, [0x50], "PUSH AW", 1), "po": ("SP", oc.STACK_TOP - 8, [0x5B], "POP BW", 1),
    "cn": ("SP", oc.STACK_TOP, [0xE8, 0x00, 0x00], "CALL $+3", 1),
    "cf": ("SP", oc.STACK_TOP, lambda n: [0x9A] + _w(n) + _SEGW, "CALL far next", 1),
    "cr": ("SP", oc.STACK_TOP, [0xE8, 0x02, 0x00, 0xEB, 0x03, 0xC2, 0x00, 0x00], "CALL $+5 ; BR $+5 ; RET 0", 1),
    "i3": ("SP", oc.STACK_TOP, [0xCC], "BRK 3", 1), "ua": ("SP", oc.STACK_TOP, [0x60], "PUSH R", 1),
    "pm": ("SP", oc.STACK_TOP, [0xFF, 0x34], "PUSH word [IX]", 1),
    "qm": ("SP", oc.STACK_TOP - 8, [0x8F, 0x04], "POP word [IX]", 1),
    "sw": ("IX", w2.SRC, [0x89, 0x04], "MOV [IX], AW", 1), "ad": ("IX", w2.SRC, [0x01, 0x04], "ADD [IX], AW", 1),
    "xc": ("IX", w2.SRC, [0x87, 0x04], "XCH AW, [IX]", 1), "ld": ("IX", w2.SRC, [0x8B, 0x04], "MOV AW, [IX]", 1),
}
_RMOV = {"IY": 0xBF, "IX": 0xBE, "SP": 0xBC}


def _jform(name, odd):
    reg, ev, sub, txt, n = JF[name]
    v = ev + 1 if odd and reg != "SP" else ev - 1 if odd else ev
    pre = [_RMOV[reg]] + _w(v) + [0xB9] + _w(n) + _FILB
    text = f"MOV {reg},{v:04X}h ; MOV CW,{n} ; ROL BP,16 ; {txt}   ; {'odd' if odd else 'even'}"
    if callable(sub):
        return (lambda nx: pre + sub(nx), text, {})
    return (pre + sub, text, {})


for _n in JF:
    XS2[f"{_n}e"] = _jform(_n, 0)
    XS2[f"{_n}o"] = _jform(_n, 1)
w4.XS.update(XS2)
PY = ("ps", "pi", "pa", "po", "cn", "cr", "sa", "la")
XG2 = {     # name: (windows (y, lead, al, w, wl), note); wl << 2 is ORed into WTC: 1000h per I/O wait
    "j": ([(f"{n}{p}", "f0", al, 0, 0) for n in JF for p in "eo" for al in (0, 1)],
          "the wait behind the last EU cycle of 26 forms, a single cycle against a no-wait pair"),
    "s2": ([(y, f"{h}{s}", al, 2, 0) for y in ("ps", "pi", "cr", "pa") for h in "FP" for s in SEQS for al in (0, 1)],
           "stack forms behind the filler / a push and every sequence of up to four INC BW / NOP at 2 waits"),
    "s1": ([(y, f"{h}{s}", al, 1, 0) for y in ("ps", "pi", "cr", "pa") for h in "FP" for s in S3 for al in (0, 1)],
           "the same with sequences of up to three at 1 wait"),
    "gs": ([(y, f"{h}{s}", al, 0, 0) for y in ("ad", "le", "si", "mu") for h in "OPF" for s in S3 for al in (0, 1)],
           "forms with two late-released operand bytes behind OUT / PUSH / the filler and sequences of up to three"),
    "hs": ([(y, f"{h}{s}", al, 0, 0) for y in ("s2", "x2", "a8", "a9") for h in "OPF" for s in S2 for al in (0, 1)],
           "d16 stores and read-modify-write in a row behind OUT / PUSH / the filler and sequences of up to two"),
    "es": ([(y, f"{h}{s}", al, w, 0) for y in ("in",) for w in W3 for h in "MQOP" for s in S2 for al in (0, 1)],
           "IN AL,DW behind OUT / PUSH, with and without MOV r,r, and sequences of up to two at 0, 1, 2 waits"),
}
for _io in (0, 1, 2):
    XG2[f"i{_io}"] = ([(y, l, al, w, _io << 12) for y in PY for w in (0, 2) for l in ("o0", "o1") for al in (0, 1)],
                      f"request words behind OUT 20h,AL with the I/O field at {_io} waits, memory at 0 and 2 waits")
# READY on the pair's second half: block 1 at 2 waits and READY (WTC 000Ch, PMC1 bit 7 set in the prelude)
BREADY = {"br2": 2.0, "br3": 3.0, "br4": 4.0}
BRY = [(f"{f}{k}", "f0", al, 0x0C) for f in ("r1", "mk", "r2") for k in ("a", "c", "e", "g") for al in (0, 1)]


def _pmc1(m):
    oc.es_store(m, 0xFF0A, 0x80)


class ProgramR(Program):
    m = None


def programs():
    progs = {}
    for g, (wins, note) in XG2.items():
        name = f"{PFX}_{g}_r1"
        p = w4.Program(name, [w4.xwindow(y, l, al, 1, w, wl, 0) for y, l, al, w, wl in wins],
                       f"group {g}: {note}, PRC = 4Eh")
        p.m = None
        progs[name] = p
    for g, hold in BREADY.items():
        name = f"{PFX}_{g}_r1"
        p = ProgramR(name, [r1.window(y, l, al, w) for y, l, al, w in BRY],
                     f"group {g}: group b's elements with block 1 at 2 waits and READY, READY low {hold} clocks "
                     f"from /MREQ's fall of a block-1 cycle, PRC = 4Eh", init=_pmc1)
        p.m = (0, round(hold * w4.CLK), 3, 0x02)
        progs[name] = p
    for g, wins in GROUPS.items():
        name = f"{PFX}_{g}_r1"
        cls = Program if g in PAGED else ph.Program
        progs[name] = cls(name, [r1.window(y, l, al, w) for y, l, al, w in wins],
                          f"group {g}: {NOTES[g]}, PRC = 4Eh")
    for g, (wins, ready, note) in XGROUPS.items():
        name = f"{PFX}_{g}_r1"
        p = w4.Program(name, [w4.xwindow(y, l, al, 1, w, 0, 0, ready=ready) for y, l, al, w in wins],
                       f"group {g}: {note}, PRC = 4Eh")
        hold = AREADY.get(g)
        p.m = (0, round(hold * w4.CLK), 3, 0x01) if hold else None
        progs[name] = p
    return progs


def run_set(names, backend, tag, progs):
    """wstore4.run_set (the /MREQ-timed READY registers written per program) for every program."""
    for p in progs.values():
        if not hasattr(p, "m"):
            p.m = None
    w4.run_set(names, backend, tag, progs)


windows, fmt, cell, kind_of, compare, line = w2.windows, w2.fmt, w2.cell, w2.kind_of, w2.compare, w2.line


def show(names, progs, backends, only=None):
    """Every window's cycles (kind, low 12 address bits, clock after the marker) per backend."""
    for n in names:
        prog = progs[n]
        recs = {}
        for be in backends:
            try:
                recs[be] = windows(ph.load(n, be), prog)
            except FileNotFoundError:
                pass
        for k, pw in enumerate(prog.windows):
            m = pw.meta
            if only and m["y"] not in only:
                continue
            head = f"{n[len(PFX) + 1:]} w{k} {m['y']} {m['lead']} al {m['al']} w{m['w']}"
            lines = {be: (line(w[k]) if k in w else "missing") for be, w in recs.items()}
            if len(set(lines.values())) == 1 and len(lines) > 1:
                print(f"{head} [{' = '.join(lines)}] {next(iter(lines.values()))}")
            else:
                for be, t in lines.items():
                    print(f"{head} [{be}] {t}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "repeat", "gate", "show", "emit"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--be", nargs="+", default=["socket", "sim"])
    p.add_argument("--y", nargs="+")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    names = a.names or list(progs)
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        run_set(names, "socket", a.tag, progs)
    elif a.action == "sim":
        run_set(names, "sim", a.tag, progs)
    elif a.action == "show":
        show(names, progs, a.be, a.y)
    elif a.action in ("repeat", "gate"):
        ref, cand = ("socket", "socket-2") if a.action == "repeat" else (a.ref, a.cand)
        ok = True
        for n in names:
            ok &= compare(n, ref, cand, progs, verbose=a.verbose)
        return 0 if ok else 1
    else:
        ph.emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
