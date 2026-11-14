"""F4q: requests among prefixes: what silicon takes inside a prefix chain, the PC it pushes, what
the returned-to instruction runs with, and the NMI the RTL lost after a take over a prefixed
instruction (the core README's "F4q").

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, in validation/v35s/prio.py's frame (periph.py's run, receipts and gate; intr.py's
Test, logging handler, slots and fast stubs; dma.py's write sequence):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.pfxtake socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.pfxtake sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.pfxtake gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.pfxtake show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.pfxtake log NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.pfxtake order NAME [--ref socket]

Every test labels its prefix chain's first byte `pa{k}` and the opcode after it `pz{k}`: the
logging handler's pushed PC reads as pa+i (the chain's byte i) or pz+j. A request is made
pending before or inside a chain by one of:
  - the maskable interrupt pending behind IE 0 (intr.py's `_pend`), released by EI right before
    the chain (the take falls due inside it: no clock decides where);
  - an NMI / INTP / DMARQ edge scheduled after an event announced right before a chain of 320
    prefixes (the edge lands inside the chain on every run; the chain is the hold);
  - PSW.BRK (the single step) set before the chain.
The results are the log (vector, pushed PC, the registers at the take), the continuation's
registers, the bytes a string moved (its source segment visible: PS:IX is the vector table,
DS0:IX the pattern at 0A000h) and, for the macro service and DMA, the order of the write
sequence (prio.py's tokens).

Receipts: validation/v35s/receipts/f4-<name>-<backend>.json (--tag adds a suffix).
"""

from __future__ import annotations

import argparse
import sys

from . import dma, periph, prio
from .intr import INCS, PSW_IE, _db, _h, _pend, _ST, ev, pulse
from .periph import PTest, _prog
from .serial import _fix, rd, swr
from .dma import ON0, OFF0, PINS, blk_w, cw, mask_rng

BRG, CLR, ms_set, msc_rd, edges = prio.BRG, prio.CLR, prio.ms_set, prio.msc_rd, prio.edges

PS_, DS1_, REP, LOCK, REPC = 0x2E, 0x26, 0xF3, 0xF0, 0x65
STOP = "    PUSH AW\n    MOV AW, 0002h\n    PUSH AW\n    POP PSW\n    POP AW\n"
GO = "    PUSH AW\n    MOV AW, 0102h\n    PUSH AW\n    POP PSW\n    POP AW\n"


def chain(bs):
    """The prefix bytes, 16 to a DB line."""
    out = ""
    for i in range(0, len(bs), 16):
        out += _db(bs[i:i + 16])
    return out


def body(pfx, op):
    """The labelled chain and its opcode (assembly)."""
    return "pa{k}:\n" + chain(pfx) + "pz{k}:\n" + op


LD = "    MOV AW, [IX]\n    DB 2Eh\n    MOV [{S}], AW\n"    # the load (its segment visible), stored
STR = {"CW": 0x0040, "IX": 0x0000, "IY": 0x0080}            # a 64-word MOVBKW: DS1:80h-FFh
LDR = {"IX": 0x0010}


def dcap(at="{S}+2", seg=0x26):
    """The string's destination elements 0, 1, 2 and 63 (DS1:80h, 82h, 84h, FEh) into PS:at..+7
    (AW kept): element 0 moved before the take, the others after the return (each one's source
    segment shows: PS:IX the vector table, DS0:IX the pattern)."""
    s = "    PUSH AW\n"
    for i, e in enumerate((0x80, 0x82, 0x84, 0xFE)):
        s += f"    DB {_h(seg)}\n    MOV AW, [{_h(e, 4)}]\n    DB 2Eh\n    MOV [{at}+{2 * i}], AW\n"
    return s + "    POP AW\n"


def s_test(name, pfx, op=0xA5, regs=None, note=""):
    """The maskable interrupt pending, EI, the chain, a string: taken at the string's take point
    (the first element's end)."""
    return PTest(name, jitter=False, pre=_pend(),
                 code="    EI\n" + body(pfx, _db([op])) + INCS + dcap(),
                 regs=dict(STR, **(regs or {})), stim=_ST, sfr=False, note=note)


def n_test(name, pfx, op=LD, note=""):
    """The maskable interrupt pending, EI, the chain, a load whose segment shows in AW."""
    return PTest(name, jitter=False, pre=_pend(), code="    EI\n" + body(pfx, op) + INCS,
                 regs=LDR, stim=_ST, sfr=False, note=note)


def nmi_test(name, pfx, op=LD, regs=None, delay=3000, note=""):
    """An NMI edge `delay` ticks after the event announced right before the chain."""
    return PTest(name, jitter=False, code=ev("E0") + body(pfx, op) + INCS
                 + (dcap() if op.startswith("    DB") else ""),
                 regs=dict(LDR, **(regs or {})), stim=[pulse("E0", "NMI", delay=delay)],
                 sfr=False, action="    NOP\n", note=note)


def step_test(name, pfx, op=LD, regs=None, note=""):
    """PSW.BRK set, a NOP, the chain and its opcode stepped, BRK cleared."""
    return PTest(name, jitter=False, code=GO + "    NOP\n" + body(pfx, op) + "    INC AW\n" + STOP,
                 regs=dict(LDR, **(regs or {})), sfr=False, action="", note=note)


def fpo_test(name, pfx, note=""):
    """The FPO escape D8 C0 (vector 7) after the chain: the PC pushed; the action returns past
    the escape (fz{k})."""
    return PTest(name, jitter=False, code=body(pfx, "    DB 0D8h, 0C0h\nfz{k}:\n") + INCS,
                 action="    DB 0C7h, 46h, 0Ch\n    DW fz{k}\n", note=note)


def fpo_tests():
    """The FPO trap's pushed PC against the chain's length (the instruction's start as a trap
    reads it)."""
    return [periph.init_test()] + [fpo_test(f"f{n}", [PS_] * n, note=f"PS x {n}, FPO D8")
                                   for n in (1, 2, 3, 4, 5, 7, 8, 9, 16, 17)] + [
        fpo_test("fr4", [REP] + [PS_] * 3, note="REP, PS x 3, FPO D8"),
        fpo_test("fr5", [REP] + [PS_] * 4, note="REP, PS x 4, FPO D8"),
        fpo_test("fl5", [LOCK] * 5, note="BUSLOCK x 5, FPO D8"),
    ]


P319 = [PS_] * 319
P320 = [PS_] * 320


def x_rep_tests(ns, init=True):
    """The pushed PC at a REP string's take point against the chain's length: n - 1 PS prefixes,
    REP, MOVBKW (the maskable interrupt)."""
    return [periph.init_test()] * init + [s_test(f"s{n}", [PS_] * (n - 1) + [REP], note=f"PS x {n - 1}, REP, MOVBKW")
            for n in ns]


def x_mix_tests():
    """REP first, other prefix kinds, other strings (the maskable interrupt at the take point)."""
    T = [periph.init_test()] + [s_test(f"r{n}", [REP] + [PS_] * (n - 1), note=f"REP, PS x {n - 1}, MOVBKW")
         for n in (2, 3, 9, 17, 33, 65, 257)]
    T += [
        s_test("l9", [LOCK] * 8 + [REP], note="BUSLOCK x 8, REP, MOVBKW"),
        s_test("ps_l8", [PS_] + [LOCK] * 7 + [REP], note="PS, BUSLOCK x 7, REP, MOVBKW"),
        s_test("ps_r8", [PS_] + [REP] * 8, note="PS, REP x 8, MOVBKW"),
        s_test("ps_l64", [PS_] + [LOCK] * 63 + [REP], note="PS, BUSLOCK x 63, REP, MOVBKW"),
        s_test("ps_d64", [PS_] + [DS1_] * 62 + [PS_, REP], note="PS, DS1 x 62, PS, REP, MOVBKW"),
        s_test("ps_rc64", [PS_] * 63 + [REPC], note="PS x 63, REPC, MOVBKW"),
        s_test("stm64", [PS_] * 63 + [REP], op=0xAB, note="PS x 63, REP, STMW"),
    ]
    return T


def x_ns_tests():
    """A non-string opcode after the chain (the maskable interrupt due inside the chain): is it
    taken between prefixes; which PC; the load's segment after RETI."""
    return [periph.init_test(),
        n_test("d8", [DS1_] * 8, note="DS1 x 8, MOV AW,[IX]"),
        n_test("d320", [DS1_] * 320, note="DS1 x 320, MOV AW,[IX]"),
        n_test("d_r319", [DS1_] + [REP] * 319, note="DS1, REP x 319, MOV AW,[IX]"),
        n_test("d_l319", [DS1_] + [LOCK] * 319, note="DS1, BUSLOCK x 319, MOV AW,[IX]"),
        n_test("d_m320", [DS1_, REP, LOCK, PS_] * 79 + [DS1_, REP, LOCK, DS1_],
               note="(DS1 REP BUSLOCK PS) x 79, DS1 REP BUSLOCK DS1, MOV AW,[IX]"),
        n_test("d_p319", [DS1_] + [PS_] * 318 + [DS1_], note="DS1, PS x 318, DS1, MOV AW,[IX]"),
    ]


def x_nmi_tests():
    """An NMI edge inside a 320-prefix chain (and inside a string)."""
    return [periph.init_test(),
        nmi_test("n_d320", [DS1_] * 320, note="DS1 x 320, MOV AW,[IX]"),
        nmi_test("n_dr", [DS1_] + [REP] * 319, note="DS1, REP x 319, MOV AW,[IX]"),
        nmi_test("n_dl", [DS1_] + [LOCK] * 319, note="DS1, BUSLOCK x 319, MOV AW,[IX]"),
        nmi_test("n_dp", [DS1_] + [PS_] * 318 + [DS1_], note="DS1, PS x 318, DS1, MOV AW,[IX]"),
        nmi_test("n_s320", P319 + [REP], op=_db([0xA5]), regs=STR,
                 note="PS x 319, REP, MOVBKW: the edge in the chain"),
        nmi_test("n_r320", [REP] + P319, op=_db([0xA5]), regs=STR,
                 note="REP, PS x 319, MOVBKW: the edge in the chain"),
        nmi_test("n_s321", P320 + [REP], op=_db([0xA5]), regs=STR,
                 note="PS x 320, REP, MOVBKW: the edge in the chain"),
        nmi_test("n_s322", [DS1_] * 320 + [REP, PS_], op=_db([0xA5]), regs=STR,
                 note="DS1 x 320, REP, PS, MOVBKW: the edge in the chain"),
    ]


def x_nmis_tests():
    """An NMI edge inside the string (the element it lands after is the clocks': measured
    only)."""
    return [periph.init_test(),
        nmi_test("n_s9", [PS_] * 8 + [REP], op=_db([0xA5]), regs=STR, delay=6000,
                 note="PS x 8, REP, MOVBKW: the edge in the string"),
        nmi_test("n_s65", [PS_] * 64 + [REP], op=_db([0xA5]), regs=STR, delay=9000,
                 note="PS x 64, REP, MOVBKW: the edge in the string"),
    ]


def x_step_tests():
    """The single step through chains."""
    return [periph.init_test(),
        step_test("t_d8", [DS1_] * 8, note="DS1 x 8, MOV AW,[IX] stepped"),
        step_test("t_mix", [DS1_, REP, LOCK, PS_, REP, LOCK, DS1_], note="a mixed chain stepped"),
        step_test("t_s9", [PS_] * 8 + [REP], op=_db([0xA5]), regs=dict(STR, CW=3),
                  note="PS x 8, REP, MOVBKW CW 3 stepped"),
    ]


def x_svc_tests():
    """A macro service (INTP0, channel 2) or a DMA single transfer (DMARQ0, channel 0, I/O to
    memory at D000h) requested inside a 320-prefix chain whose opcode is a marker store
    (MOV byte, PS:), or a REP MOVBKW (64 words, DS1:80h): served between prefixes (before the
    marker) or after the opcode (after it); a string resumed from which prefix (the
    destination's bytes: PS:IX the vector table)."""
    T = [periph.init_test()]
    DD = 0xD000

    def t(name, pins, pfx, string=False, note=""):
        x = mask_rng(PTest(name, jitter=False, stim=[edges("E0", pins, 6000, 2000)],
                           note=note), DD, 0x10)

        def code(k):
            s = (BRG + ms_set("P0", 2) + ON0 + blk_w(0, 0, 0x0000, 0x0F, 0x0D, 2)
                 + swr("DMAC0", 0x11) + swr("DMAM0", 0xA8))
            if string:
                s += ("    PUSH DS1\n    PUSH CW\n    PUSH IX\n    PUSH IY\n    MOV AW, 0B00h\n"
                      "    MOV DS1, AW\n    MOV CW, 0040h\n    XOR IX, IX\n    MOV IY, 0080h\n")
            s += ev("E0") + cw(k, 0, 0xA0) + "pa{k}:\n" + chain(pfx) + "pz{k}:\n"
            if string:
                s += _db([0xA5]) + ("    DB 2Eh\n    MOV [{S}], CW\n    DB 2Eh\n    MOV [{S}+2], IX\n"
                                    + dcap("{S}+4") +
                                    "    POP IY\n    POP IX\n    POP CW\n    POP DS1\n")
                s += cw(k, 1, 0xA1)
            else:
                s += "    MOV byte [" + _h(dma.RES + 0x20 * k + 0x18 + 1, 4) + "], 0A1h\n"
            s += (cw(k, 2, 0xA2) + msc_rd(2, k, 0) + rd("EXIC0", k, 1) + swr("DMAM0", 0x00)
                  + OFF0 + CLR)
            return s
        x.codef = code
        return x
    T += [
        t("m_ps", ["INTP0"], P320, note="macro service; PS x 320, PS: MOV byte (the marker)"),
        t("m_rep", ["INTP0"], [PS_] + [REP] * 319, note="macro service; PS, REP x 319, marker"),
        t("m_lock", ["INTP0"], [PS_] + [LOCK] * 319, note="macro service; PS, BUSLOCK x 319, marker"),
        t("d_ps", ["DMARQ0"], P320, note="DMA; PS x 320, marker"),
        t("d_rep", ["DMARQ0"], [PS_] + [REP] * 319, note="DMA; PS, REP x 319, marker"),
        t("d_lock", ["DMARQ0"], [PS_] + [LOCK] * 319, note="DMA; PS, BUSLOCK x 319, marker"),
        t("m_str", ["INTP0"], P319 + [REP], True, note="macro service; PS x 319, REP MOVBKW"),
        t("d_str", ["DMARQ0"], P319 + [REP], True, note="DMA; PS x 319, REP MOVBKW"),
        t("m_str1", ["INTP0"], P320 + [REP], True, note="macro service; PS x 320, REP MOVBKW"),
        t("d_str1", ["DMARQ0"], P320 + [REP], True, note="DMA; PS x 320, REP MOVBKW"),
        t("nm_str", ["NMI", "INTP0"], P319 + [REP], True,
          note="NMI and macro service; PS x 319, REP MOVBKW"),
    ]
    for x in T[1:]:
        if "NMI" in str(x.stim):
            x.action = prio.act_skip_nmi()
    return _fix(T)


def l_tests():
    """(Finding 1) NMI and a macro service pending together at the start of a segment-prefixed
    instruction: NMI's frame pushed, the macro service at its handler's first instruction, then
    NMI's handler (the stub's store V2). The hold is a 320-PS chain before a NOP; the instruction
    after the NOP is a PS: store (the take lands there). The RTL before F4q lost the NMI
    handler: the macro service resumed at the interrupted instruction."""
    T = [periph.init_test()]

    def t(name, pins, ms="P0", tail=""):
        x = PTest(name, jitter=False, psw=PSW_IE, action=prio.act_skip_nmi(),
                  stim=[edges("E0", pins, 6000, 2000)])
        x.codef = lambda k: (BRG + ms_set(ms, 2) + swr("EXIC1", 0x07) + ev("E0") + cw(k, 0, 0xA0)
                             + chain(P320) + "    NOP\n" + tail + cw(k, 1, 0xA1) + cw(k, 2, 0xA2)
                             + msc_rd(2, k, 0) + rd("EXIC0", k, 1) + rd("EXIC1", k, 2) + CLR)
        return x
    T += [
        t("nmi_ms", ["NMI", "INTP0"]),
        t("nmi_ms_ds", ["NMI", "INTP0"], tail="    DB 26h\n    MOV AL, [0FF4Ch]\n"),
        t("nmi_only", ["NMI"]),
        t("ms_only", ["INTP0"]),
    ]
    return _fix(T)


def programs():
    progs = {
        "f4q_l": _prog("f4q_l", l_tests(), pins=PINS, fast=(20, 21, 28),
                       note="NMI and a macro service at a prefixed instruction (the lost NMI)"),
        "f4q_rep1": _prog("f4q_rep1", x_rep_tests((1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16, 17)),
                          note="the PC pushed at a REP string's take point against the chain's "
                               "length (1-17); the string's elements after the return"),
        "f4q_rep2": _prog("f4q_rep2", x_rep_tests((31, 32, 33, 63, 64, 65, 127, 128, 129)),
                          note="as f4q_rep1, 31-129"),
        "f4q_rep3": _prog("f4q_rep3", x_rep_tests((255, 256, 257, 320)),
                          note="as f4q_rep1, 255-320"),
        "f4q_mix": _prog("f4q_mix", x_mix_tests(),
                         note="REP first, BUSLOCK, REPC, STMW at the take point"),
        "f4q_ns": _prog("f4q_ns", x_ns_tests(),
                        note="the maskable interrupt due inside a chain before a load"),
        "f4q_nmi": _prog("f4q_nmi", x_nmi_tests(),
                         note="NMI inside chains (non-string, and before a string)"),
        "f4q_nmis": _prog("f4q_nmis", x_nmis_tests(), gate=False,
                          note="measured only: NMI inside a string (the element: the clocks')"),
        "f4q_step": _prog("f4q_step", x_step_tests(),
                          note="the single step through chains"),
        "f4q_fpo": _prog("f4q_fpo", fpo_tests(),
                         note="the FPO trap's pushed PC after chains"),
        "f4q_svc": _prog("f4q_svc", x_svc_tests(), pins=PINS, fast=(20, 21, 28),
                         note="macro service and DMA inside chains (orders; a string's resume)"),
    }
    for p in progs.values():
        p.data.update(dma.pages())
        p.results += [(0xD000, 0x100), (dma.SRC, 0x100), (dma.DST, 0x100),
                      (dma.RES, 0x20 * len(p.tests))]
    return progs


def show(name, backend, progs):
    """The slots (AW CW IX IY at the continuation), the log (vector, the pushed PC by label, the
    registers at the take) and the string's destination (DS1:80h, 16 bytes)."""
    from . import intr
    rec = periph.load(name, backend)
    prog = progs[name]
    count, entries, slots = intr.decode(rec)
    labels = intr.labels_of(prog)
    d1 = bytes.fromhex(rec["regions"].get(f"{intr.DATA1:05X}", ""))
    print(f"{name} ({backend}): passed {rec['passed']} status {rec['status']:04x} log {count}")
    by = {}
    for e in entries:
        by.setdefault(e["test"], []).append(e)
    for k, t in enumerate(prog.tests):
        s = slots[k] if k < len(slots) else {}
        print(f"{k:2d} {t.name:9s} AW={s.get('AW', 0):04X} CW={s.get('CW', 0):04X}"
              f" IX={s.get('IX', 0):04X} IY={s.get('IY', 0):04X} PSW={s.get('PSW', 0):04X}"
              f" n={s.get('count', 0)} scr={s.get('scratch', '')[:8]}  {t.note}")
        for e in by.get(k, []):
            print(f"     v{e['vec']:<2d} d{e['depth']} pc={e['pc']:04X} [{intr.where(labels, e['pc'])}]"
                  f" AW={e['AW']:04X} CW={e['CW']:04X} IX={e['IX']:04X} IY={e['IY']:04X}")
    if d1:
        print(f"   DS1:80h.. {d1[0x80:0x90].hex(' ')} .. {d1[0xF0:0x100].hex(' ')}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "gate", "show", "order", "log", "size"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--all", action="store_true", help="socket / sim: every program")
    a = p.parse_args()
    progs = programs()
    names = a.names or [n for n, prog in progs.items() if prog.gate or a.all]
    if a.action in ("socket", "sim"):
        dma._with_dma_reads()
        dma._ready_stim(0)
        dma._keep_trace(())
        periph.run_set(names, a.action, a.tag, progs)
    elif a.action == "gate":
        dma._gate_setup(progs)
        return 0 if periph.compare_gate(names, a.ref, a.cand, progs) else 1
    elif a.action == "show":
        for n in names:
            show(n, a.ref + a.tag, progs)
    elif a.action == "log":
        for n in names:
            prio.show_log(n, a.ref + a.tag, progs)
    elif a.action == "order":
        for n in names:
            prio.show_order(n, a.ref + a.tag, progs)
    else:
        for n in names:
            code, _, _ = progs[n].image()
            print(n, f"{len(code)} bytes, {len(progs[n].tests)} tests, "
                  f"{len((progs[n].stim or {}).get('entries', []))} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
