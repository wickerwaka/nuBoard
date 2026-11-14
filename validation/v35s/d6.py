"""(F5f) Opcode D6 measured on the socket (docs/v35s-function-plan.md, stage F5).

README F2b: D6 takes a ModR/M byte and makes a byte read and a byte write of its memory
operand, registers unchanged (the operand was on an unmapped page, the operation unknown). This
set runs D6 with every reg field on a mapped memory operand ([IX], DS0 = 0A00h) and several
operand values and flags, the register forms, a displacement form and CL counts, in
validation/v35s/intr.py's frame (the continuation stores AW CW DW BW SP BP IX IY DS0 DS1 SS PSW;
the operand bytes are in DATA0, compared; the write sequence shows the bus cycles):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.d6 socket [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.d6 sim
    PYTHONPATH=host/src:. python3 -m validation.v35s.d6 gate [--ref socket] [--cand sim]
    PYTHONPATH=host/src:. python3 -m validation.v35s.d6 show [--ref socket]

Each test is followed by two NOPs (90h 90h; the flags as D6 left them): the continuation shows
where execution went on. Receipts: validation/v35s/receipts/f3-f5_d6{,b}-<backend>.json.
"""

from __future__ import annotations

import argparse
import sys

from . import intr
from .intr import Test, _h, make_program

VALS = ((0xFF, 0x0002), (0x81, 0x0003), (0x00, 0x08D7), (0x7F, 0x0002))


def tests():
    T = []
    k = 0
    for reg in range(8):
        for v, psw in VALS:
            ix = 0x10 + 2 * k
            T.append(Test(f"m{reg}_{v:02X}_{psw:04X}", regs={"IX": ix}, psw=psw, sfr=False,
                          pre=f"    MOV byte [IX], {_h(v)}\n",
                          code=f"    DB 0D6h, {_h(0x04 | reg << 3)}, 90h, 90h\n",
                          action="", note=f"D6 /{reg} [IX] = {v:02X}h, PSW {psw:04X}h"))
            k += 1
    for reg in (0, 4):
        ix = 0x10 + 2 * k
        T.append(Test(f"m{reg}_cl1", regs={"IX": ix, "CW": 0x0001}, psw=0x0002, sfr=False,
                      pre="    MOV byte [IX], 81h\n",
                      code=f"    DB 0D6h, {_h(0x04 | reg << 3)}, 90h, 90h\n", action="",
                      note=f"D6 /{reg} [IX] = 81h, CL 1"))
        k += 1
    for reg in range(8):
        T.append(Test(f"r{reg}_cl", regs={"CW": 0x00FF}, psw=0x0002, sfr=False,
                      code=f"    DB 0D6h, {_h(0xC1 | reg << 3)}, 90h, 90h\n", action="",
                      note=f"D6 /{reg} CL (CL FFh): the register form"))
    for reg, rm, nm in ((7, 4, "AH"), (3, 7, "BH"), (5, 0, "AL")):
        T.append(Test(f"r{reg}_{nm}", regs={"AW": 0xFFFF, "BW": 0xFFFF}, psw=0x0002, sfr=False,
                      code=f"    DB 0D6h, {_h(0xC0 | reg << 3 | rm)}, 90h, 90h\n", action="",
                      note=f"D6 /{reg} {nm} (AW BW FFFFh)"))
    ix = 0x10 + 2 * k
    T.append(Test("m0_d8", regs={"IX": ix - 8}, psw=0x0002, sfr=False,
                  pre="    MOV byte [IX+8], 81h\n", code="    DB 0D6h, 44h, 08h, 90h, 90h\n",
                  action="", note="D6 /0 [IX+8] (a disp8 form)"))
    k += 1
    ix = 0x10 + 2 * k
    T.append(Test("m0_w", regs={"IX": ix}, psw=0x0002, sfr=False,
                  pre="    MOV word [IX], 8181h\n", code="    DB 0D6h, 04h, 90h, 90h\n",
                  action="", note="D6 /0 [IX] with 8181h: the second byte untouched?"))
    return T


NAMES = ("f5_d6", "f5_d6b")


def programs():
    """Two programs (the code must stay below the vector stubs at 3000h)."""
    T = tests()
    out = {}
    for nm, ts in zip(NAMES, (T[:20], T[20:])):
        out[nm] = make_program(nm, ts, note="(F5f) opcode D6 measured (every reg field, values, "
                               "flags, register forms)", gate=True)
        code, _, _ = out[nm].image()
        assert 0x100 + len(code) < intr.STUBS, (nm, len(code))
    return out


def show(ref="socket", name="f5_d6"):
    progs = programs()
    rec = intr.load(name, ref)
    _, _, slots = intr.decode(rec)
    d0 = bytes.fromhex(rec["regions"][f"{intr.DATA0:05X}"])
    prog = progs[name]
    for k, t in enumerate(prog.tests):
        s = slots[k]
        ix = t.regs["IX"] & 0xFE
        print(f"{k:2d} {t.name:16s} AW={s['AW']:04X} CW={s['CW']:04X} IX={s['IX']:04X} "
              f"SP={s['SP']:04X} PSW={s['PSW']:04X} mem[{ix:02X}]={d0[ix]:02X}{d0[ix + 1]:02X}"
              f"  ({t.note})")
    from .runner import FLAG_IO
    w = [(a, d, f) for a, d, f in rec["writes"] if 0xA000 <= a < 0xA100 and not f & FLAG_IO]
    print("writes at A0xx:", " ".join(f"{a:05X}={d:04X}/{f:03X}" for a, d, f in w))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "gate", "show", "emit"))
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    a = p.parse_args()
    progs = programs()
    if a.action in ("socket", "sim"):
        intr.run_set(list(NAMES), a.action, a.tag, progs)
    elif a.action == "gate":
        ok = intr.compare_gate(list(NAMES), a.ref, a.cand,
                               exclude=lambda n: intr.jitter_bytes(n, a.ref, progs))
        return 0 if ok else 1
    elif a.action == "show":
        for n in NAMES:
            show(a.ref, n)
    else:
        intr.emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
