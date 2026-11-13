"""F5: the flag survey (measured on the socket first; read by the F5 triage).

The fuzz's first differences were the flags the data book leaves undefined (AC after a shift, a
multiply, CVTBD; CY / P after EXT). This set measures them directly: per instruction class a
program of cases, each case loading the operand registers by MOV, the PSW by PUSH imm; POP PSW
(random flags, AC and the others both ways), running the instruction (register forms only), then
PUSH PSW and PUSH of the registers it writes. Every case's writes are therefore known in number,
and `cases()` parses the receipt into (inputs, PSW in, outputs, PSW out) per case.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.fuzz socket f5x
    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz sim f5x
    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz_flags [--ref socket] [--cand sim] [NAME ...]
"""

from __future__ import annotations

import random
import sys

from . import fuzz_gen as G
from .fuzz_gen import AW, BP, BW, CW, DW, IX, IY, R16, R8, SP

PSW_MASK = 0x0FD5          # the flag bits (V DIR IE BRK S Z AC P CY) and F0 / F1 below
FLAG_NAMES = {0: "CY", 2: "P", 3: "F1", 4: "AC", 5: "F0", 6: "Z", 7: "S", 11: "V"}


def _rv(r):
    """An operand value: edges and random."""
    x = r.random()
    if x < 0.15:
        return r.choice((0, 1, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF, 0xFF80, 0x0F, 0xF0,
                         0x0FFF, 0x00FF, 0x8001))
    return r.randrange(0x10000)


class Case:
    def __init__(self, op, data, regs, psw, writes, text):
        self.op, self.data, self.regs, self.psw, self.writes, self.text = op, data, regs, psw, writes, text


def case_list(kind, r, n):
    """(op class, bytes, input registers, the 16-bit registers written) per case."""
    out = []
    for _ in range(n):
        regs = {k: _rv(r) for k in (AW, CW, DW, BW)}
        if kind == "shift":
            op = r.randrange(8)
            if op == 6:
                op = 4
            w = r.randrange(2)
            how = r.choice(("1", "CL", "imm"))
            cnt = r.choice((0, 1, 2, 3, 7, 8, 9, 15, 16, 17, 31, 32, 33, r.randrange(256)))
            if how == "1":
                data = bytes([0xD0 + w, 0xC0 | op << 3 | AW])
            elif how == "CL":
                data = bytes([0xD2 + w, 0xC0 | op << 3 | AW])
                regs[CW] = (regs[CW] & 0xFF00) | cnt
            else:
                data = bytes([0xC0 + w, 0xC0 | op << 3 | AW, cnt])
            out.append((f"{G.SHF[op]}{'bw'[w]} {how}", data, regs, [AW]))
        elif kind == "mul":
            op = r.choice((4, 5))
            w = r.randrange(2)
            src = r.choice((BW, CW, DW))
            data = bytes([0xF6 + w, 0xC0 | op << 3 | (src if w else src)])
            out.append((f"{G.G3[op]}{'bw'[w]}", data, regs, [AW, DW]))
        elif kind == "mul3":
            op = r.choice((0x69, 0x6B))
            imm = r.randrange(0x10000 if op == 0x69 else 0x100)
            data = bytes([op, 0xC0 | DW << 3 | BW]) + imm.to_bytes(2 if op == 0x69 else 1, "little")
            out.append((f"MUL3 {op:02X}", data, regs, [DW]))
        elif kind == "div":
            op = r.choice((6, 7))
            w = r.randrange(2)
            # a divisor that does not overflow (mostly): AW / BL or DW:AW / BW
            if w:
                bwv = r.randrange(1, 0x10000)
                dwv = r.randrange(0, min(bwv, 0x7FFF)) if op == 6 else r.randrange(0, 0x40)
                if op == 7 and r.random() < 0.5:
                    dwv = 0xFFFF
                    regs[AW] |= 0x8000
                regs[BW], regs[DW] = bwv, dwv
            else:
                bl = r.randrange(1, 0x100)
                regs[BW] = (regs[BW] & 0xFF00) | bl
                if op == 6:
                    regs[AW] = r.randrange(0, bl << 8) if bl > 1 else r.randrange(0, 0x100)
                else:
                    regs[AW] = r.randrange(0, 0x40) if r.random() < 0.5 else (0xFFC0 | r.randrange(0x40))
            data = bytes([0xF6 + w, 0xC0 | op << 3 | BW])
            out.append((f"{G.G3[op]}{'bw'[w]}", data, regs, [AW, DW]))
        elif kind == "adj":
            op = r.choice((0x27, 0x2F, 0x37, 0x3F, 0xD4, 0xD5))
            data = bytes([op]) + (bytes([r.choice((10, 10, 16, 7, 255, r.randrange(1, 256)))])
                                  if op in (0xD4, 0xD5) else b"")
            name = {0x27: "ADJ4A", 0x2F: "ADJ4S", 0x37: "ADJBA", 0x3F: "ADJBS", 0xD4: "CVTBD",
                    0xD5: "CVTDB"}[op]
            out.append((name, data, regs, [AW]))
        elif kind == "logic":
            op = r.choice((1, 4, 6))
            w = r.randrange(2)
            how = r.choice(("rr", "imm", "test", "testimm"))
            if how == "rr":
                data = bytes([op * 8 + w, 0xC0 | BW << 3 | AW])
            elif how == "imm":
                data = bytes([0x80 + w, 0xC0 | op << 3 | AW]) + r.randrange(256 ** (1 + w)).to_bytes(1 + w, "little")
            elif how == "test":
                data = bytes([0x84 + w, 0xC0 | BW << 3 | AW])
                op = 8
            else:
                data = bytes([0xF6 + w, 0xC0 | AW]) + r.randrange(256 ** (1 + w)).to_bytes(1 + w, "little")
                op = 8
            out.append((f"{(G.ALU + ['TEST'])[op]}{'bw'[w]} {how}", data, regs, [AW]))
        elif kind == "arith":
            op = r.choice((0, 2, 3, 5, 7))
            w = r.randrange(2)
            data = bytes([op * 8 + w, 0xC0 | BW << 3 | AW])
            out.append((f"{G.ALU[op]}{'bw'[w]}", data, regs, [AW]))
        elif kind == "unary":
            op = r.choice(("INC", "DEC", "NEG", "INC8", "DEC8"))
            if op == "INC":
                data = b"\x40"
            elif op == "DEC":
                data = b"\x48"
            elif op == "NEG":
                w = r.randrange(2)
                data = bytes([0xF6 + w, 0xD8])
                op = f"NEG{'bw'[w]}"
            elif op == "INC8":
                data = b"\xFE\xC0"
            else:
                data = b"\xFE\xC8"
            out.append((op, data, regs, [AW]))
        elif kind == "bit":
            op = r.choice((0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B,
                           0x1C, 0x1D, 0x1E, 0x1F))
            nm = ["TEST1", "CLR1", "SET1", "NOT1"][(op >> 1) & 3]
            imm = bytes([r.randrange(256) if r.random() < 0.3 else r.randrange(16)]) if op >= 0x18 else b""
            data = bytes([0x0F, op, 0xC0 | AW]) + imm
            out.append((f"{nm}{'bw'[op & 1]} {'CL' if op < 0x18 else 'imm'}", data, regs, [AW]))
        elif kind == "rot4":
            op = r.choice((0x28, 0x2A))
            data = bytes([0x0F, op, 0xC0 | 3])          # BL
            out.append(("ROL4" if op == 0x28 else "ROR4", data, regs, [AW, BW]))
        elif kind == "ext":
            off = r.choice((0, 1, 2, 3, 7, 8, 12, 15, r.randrange(16)))
            wid = r.choice((0, 1, 3, 7, 8, 15, r.randrange(16)))
            regs[CW] = (regs[CW] & 0xFF00) | off
            regs[IX] = 0x0100 + 2 * r.randrange(0x700)
            if r.random() < 0.5:
                regs[BW] = (regs[BW] & 0xFF00) | wid
                data = bytes([0x0F, 0x33, 0xC0 | BW << 3 | CW])     # EXT CL, BL
                out.append(("EXT r,r", data, regs, [AW, CW, IX]))
            else:
                data = bytes([0x0F, 0x3B, 0xC0 | CW, wid])
                out.append(("EXT r,imm", data, regs, [AW, CW, IX]))
        elif kind == "ins":
            off = r.choice((0, 1, 2, 3, 7, 8, 12, 15, r.randrange(16)))
            wid = r.choice((0, 1, 3, 7, 8, 15, r.randrange(16)))
            regs[CW] = (regs[CW] & 0xFF00) | off
            regs[IY] = 0x0100 + 2 * r.randrange(0x700)
            if r.random() < 0.5:
                regs[BW] = (regs[BW] & 0xFF00) | wid
                data = bytes([0x0F, 0x31, 0xC0 | BW << 3 | CW])
                out.append(("INS r,r", data, regs, [CW, IY]))
            else:
                data = bytes([0x0F, 0x39, 0xC0 | CW, wid])
                out.append(("INS r,imm", data, regs, [CW, IY]))
        elif kind == "insal":
            # (F5 regression) INS with AL / AH as the offset register: AW read before the step
            rm = r.choice((0, 4))
            off, wid = r.randrange(16), r.randrange(16)
            regs[AW] = (regs[AW] & (0xFF00 if rm == 0 else 0x00FF)) | (off << (0 if rm == 0 else 8))
            regs[IY] = 0x0100 + 2 * r.randrange(0x700)
            if r.random() < 0.5:
                regs[BW] = (regs[BW] & 0xFF00) | wid
                data = bytes([0x0F, 0x31, 0xC0 | BW << 3 | rm])
            else:
                data = bytes([0x0F, 0x39, 0xC0 | rm, wid])
            out.append(("INS al/ah", data, regs, [AW, IY]))
        elif kind == "prepare":
            # PREPARE size, level over the whole level byte (the display copies and the frame
            # pointer's push; F5 finding 16): BP anywhere in the stack page's upper half
            lvl = r.choice(tuple(range(32)) + (32, 33, 34, 40, 63, 64, 65, 96, 127, 128, 160, 255))
            size = r.choice((0, 1, 2, 3, 6, 0x10, r.randrange(0x40)))
            regs[BP] = r.randrange(0x6600, 0x6F00) | (1 if r.random() < 0.2 else 0)
            data = b"\xC8" + size.to_bytes(2, "little") + bytes([lvl])
            out.append((f"PREPARE {lvl}", data, regs, [BP, SP]))
        elif kind == "divovf":
            # (F5 finding 18) DIV / DIVU whose quotient overflows: the trap (vector 0) and the
            # PSW it pushes; the stub returns, the observation shows the PSW and AW / DW after
            op = r.choice((6, 7, 7))
            w = r.randrange(2)
            if w:
                d = r.choice((0, 1, 2, 0x7FFF, 0x8000, 0xFFFF, r.randrange(0x10000), r.randrange(0x100)))
                if op == 6:
                    hi = r.randrange(d, 0x10000) if d else r.randrange(0x10000)
                    regs[DW], regs[BW] = hi, d
                else:
                    # a signed quotient outside -32768 .. 32767 (or a zero divisor)
                    sd = d - 0x10000 if d & 0x8000 else d
                    q = r.choice((0x8000, 0x8001, -0x8001, -0x8002, 0x10000, -0x10000)) if sd else 1
                    if r.random() < 0.3 and sd:
                        q = r.choice((1, -1)) * r.randrange(0x8000, 0x7FFFFFFF // max(1, abs(sd)) + 0x8001)
                    num = q * sd + (r.randrange(abs(sd)) * (1 if q * sd >= 0 else -1) if sd else r.randrange(-0x40000000, 0x40000000))
                    num = max(-0x80000000, min(0x7FFFFFFF, num)) & 0xFFFFFFFF
                    regs[DW], regs[AW], regs[BW] = num >> 16, num & 0xFFFF, d
            else:
                d = r.choice((0, 1, 2, 0x7F, 0x80, 0xFF, r.randrange(0x100)))
                if op == 6:
                    regs[AW] = (r.randrange(d, 0x100) << 8 if d else r.randrange(0x100) << 8) | r.randrange(0x100)
                else:
                    sd = d - 0x100 if d & 0x80 else d
                    q = r.choice((0x80, 0x81, -0x81, -0x82, 0x100, -0x100)) if sd else 1
                    if r.random() < 0.3 and sd:
                        q = r.choice((1, -1)) * r.randrange(0x80, 0x7FFF // max(1, abs(sd)) + 0x81)
                    num = q * sd + (r.randrange(abs(sd)) * (1 if q * sd >= 0 else -1) if sd else r.randrange(-0x4000, 0x4000))
                    regs[AW] = max(-0x8000, min(0x7FFF, num)) & 0xFFFF
                regs[BW] = (regs[BW] & 0xFF00) | d
            data = bytes([0xF6 + w, 0xC0 | op << 3 | BW])
            out.append((f"{G.G3[op]}{'bw'[w]} ovf", data, regs, [AW, DW]))
        elif kind == "bcd4s":
            # (F5 finding 17) ADD4S / SUB4S / CMP4S: the strings stored first (known digits,
            # some not BCD), CL 1-16; the observation shows the PSW and CW / IX / IY
            op = r.choice((0x20, 0x22, 0x26))
            n = r.choice((1, 2, 3, 4, 5, 8, 15, 16, r.randrange(1, 17)))
            regs[CW] = (regs[CW] & 0xFF00) | n
            regs[IX] = 0x0100 + 2 * r.randrange(0x300)
            regs[IY] = 0x0800 + 2 * r.randrange(0x300)
            pre = []
            nb = (n + 1) // 2
            for base, pfx, rm in ((regs[IX], b"", 0x44), (regs[IY], b"\x26", 0x45)):
                for k in range(0, nb, 2):
                    def dig():
                        return r.randrange(10) if r.random() < 0.85 else r.randrange(16)
                    v = sum((dig() << (4 * j)) for j in range(4))
                    if r.random() < 0.08:
                        v = r.choice((0, 0x9999))
                    pre.append((pfx + bytes([0xC7, rm, k]) + v.to_bytes(2, "little"),
                                f"MOV {'DS1:[IY' if pfx else '[IX'}+{k}], {v:04X}h"))
            nm = {0x20: "ADD4S", 0x22: "SUB4S", 0x26: "CMP4S"}[op]
            out.append((nm, bytes([0x0F, op]), regs, [CW, IX, IY], pre))
        elif kind == "extal":
            # (F5b) EXT with AL / AH as the offset register: the field written to AW and the
            # stepped offset to AL / AH, which wins (f5a_000: EXT AH, 10)
            rm = r.choice((0, 4))
            off, wid = r.randrange(16), r.randrange(16)
            regs[AW] = (regs[AW] & (0xFF00 if rm == 0 else 0x00FF)) | (off << (0 if rm == 0 else 8))
            regs[IX] = 0x0100 + 2 * r.randrange(0x700)
            if r.random() < 0.5:
                regs[BW] = (regs[BW] & 0xFF00) | wid
                data = bytes([0x0F, 0x33, 0xC0 | BW << 3 | rm])
            else:
                data = bytes([0x0F, 0x3B, 0xC0 | rm, wid])
            out.append(("EXT al/ah", data, regs, [AW, IX]))
        elif kind == "shm0":
            # (F5b) a memory operand shifted / rotated by CL or imm8, the count 0 often: silicon
            # reads and does not write back at count 0 (f5a_011)
            op = r.randrange(8)
            if op == 6:
                op = 4
            w = r.randrange(2)
            cnt = r.choice((0, 0, 0, 1, 2, 8, 16, 31, 32, 33, r.randrange(256)))
            regs[IX] = 0x0100 + 2 * r.randrange(0x700)
            d8 = r.randrange(0x80)
            if r.random() < 0.5:
                regs[CW] = (regs[CW] & 0xFF00) | cnt
                data = bytes([0xD2 + w, 0x44 | op << 3, d8])
                how = "CL"
            else:
                data = bytes([0xC0 + w, 0x44 | op << 3, d8, cnt])
                how = "imm"
            out.append((f"{G.SHF[op]}{'bw'[w]} mem,{how}", data, regs, [AW]))
        elif kind == "bitr":
            # (F5c) TEST1 on every register operand (SP's word excluded), byte and word, by CL
            # and by imm8 (any value): the fuzz's TEST1 IX / BW / BH differ in P and Z (f5b_087,
            # f5c_084, f5c_111; f5a_058's BPO after TEST1 DW)
            for k in (BP, IX, IY):
                regs[k] = _rv(r)
            w = r.randrange(2)
            rm = r.choice([x for x in range(8) if not (w and x == SP)])
            if r.random() < 0.5:
                op = 0x10 | w
                regs[CW] = (regs[CW] & 0xFF00) | r.randrange(256)
                imm = b""
            else:
                op = 0x18 | w
                imm = bytes([r.randrange(256)])
            data = bytes([0x0F, op, 0xC0 | rm]) + imm
            out.append((f"TEST1{'bw'[w]} {(R16 if w else R8)[rm]},{'imm' if imm else 'CL'}", data, regs, [AW]))
        elif kind == "resvodd":
            # (F5c) the reservation left standing by a routine that ends without its write (a
            # memory shift / rotate by a zero count: the F word's `resv`, no post), then a
            # transfer to an odd target: the refill's E waited on the request line the
            # reservation held back once q_low fell (the RTL hung: f5a_011, f5a_158, f5a_299,
            # f5b_078, f5b_145). Random leading NOPs give both target parities
            op = r.randrange(8)
            if op == 6:
                op = 4
            w = r.randrange(2)
            cnt = r.choice((0, 0, 0, 0, 1, 8, r.randrange(256)))
            regs[IX] = 0x0100 + 2 * r.randrange(0x700)
            d8 = r.randrange(0x80)
            if r.random() < 0.5:
                regs[CW] = (regs[CW] & 0xFF00) | cnt
                sh = bytes([0xD2 + w, 0x44 | op << 3, d8])
            else:
                sh = bytes([0xC0 + w, 0x44 | op << 3, d8, cnt])
            data = b"\x90" * r.randrange(3) + sh + bytes([0xEB, 1, 0x90]) + b"\x90" * r.randrange(2)
            out.append((f"{G.SHF[op]}{'bw'[w]} mem,0 + BR odd", data, regs, [AW]))
        elif kind == "outd":
            # (F5c) an OUT's datum (f5a_061: OUT 24h after REP? MOVBKB, MOV BL wrote 07h, the
            # next fetch word's low byte, with AL 1Dh): OUT imm8 / OUT DW, AL or AW, even and odd
            # ports, after a few preceding forms, a random instruction byte after it
            port = r.randrange(0x100)
            regs[DW] = r.randrange(0x10000)
            while 0xFF00 <= regs[DW] <= 0xFF20:
                regs[DW] = r.randrange(0x10000)
            regs[IX] = regs[IY] = 0x0100 + 2 * r.randrange(0x700)
            pre = r.choice((b"", b"\x90", bytes([0xB3, r.randrange(256)]), b"\x65\xA4", b"\xF3\xA4"))
            if pre[:1] in (b"\x65", b"\xF3"):
                regs[CW] = 1
            out_op = r.choice((0xE6, 0xE7, 0xEE, 0xEF))
            data = pre + (bytes([out_op, port]) if out_op < 0xEC else bytes([out_op]))
            nx = r.choice(("cvtbd", "cvtbd", "cvtdb", "mul", "addi", "movi", "nop", "inc", "movbl", "pushi"))
            imm = r.randrange(1, 256)
            data += {"cvtbd": bytes([0xD4, imm]), "cvtdb": bytes([0xD5, imm]),
                     "mul": bytes([0xF6, 0xE3]), "addi": bytes([0x04, imm]), "movi": bytes([0xB0, imm]),
                     "nop": b"\x90", "inc": b"\x40", "movbl": bytes([0xB3, imm]),
                     "pushi": bytes([0x6A, imm, 0x58])}[nx]          # PUSH imm8; POP AW
            out.append((f"OUT {out_op:02X} pre {pre.hex() or '-'} nx {nx}", data, regs, [AW]))
        elif kind == "outd2":
            # (F5d) which following instructions replace an OUT's datum (batch 3: CVTBD / CVTDB
            # drive their immediate): the OUT at every alignment (0-3 NOPs before it, a two-byte
            # MOV), every OUT form, then one of the forms whose first words take an immediate or
            # a stack datum (the PUSHes: batch 2's `iod` holds the datum against a PUSH)
            port = r.randrange(0x100)
            regs[DW] = r.randrange(0x10000)
            while 0xFF00 <= regs[DW] <= 0xFF20:
                regs[DW] = r.randrange(0x10000)
            regs[IX] = regs[IY] = 0x0100 + 2 * r.randrange(0x700)
            pre = b"\x90" * r.randrange(4) + (bytes([0xB3, r.randrange(256)]) if r.random() < 0.3 else b"")
            out_op = r.choice((0xE6, 0xE7, 0xEE, 0xEF))
            data = pre + (bytes([out_op, port]) if out_op < 0xEC else bytes([out_op]))
            imm = r.randrange(1, 256)
            i16 = r.randrange(0x10000)
            ad = 0x0100 + r.randrange(0xE00)
            fol = {"cvtbd": bytes([0xD4, imm]), "cvtdb": bytes([0xD5, imm]),
                   "mul3b": bytes([0x6B, 0xC3, imm]), "mul3w": bytes([0x69, 0xC3]) + i16.to_bytes(2, "little"),
                   "shlimm": bytes([0xC0, 0xE3, imm]), "inimm": bytes([0xE4, imm]),
                   "test1i": bytes([0x0F, 0x19, 0xC3, imm]),
                   "pushi16": bytes([0x68]) + i16.to_bytes(2, "little") + b"\x5B",
                   "pushi8": bytes([0x6A, imm, 0x5B]), "pushr": b"\x53\x5B", "pushpsw": b"\x9C\x5B",
                   "pushseg": b"\x1E\x5B", "pushm": bytes([0xFF, 0x36]) + ad.to_bytes(2, "little") + b"\x5B",
                   "pushar": b"\x60\x61", "movmi": bytes([0xC6, 0x06]) + ad.to_bytes(2, "little") + bytes([imm]),
                   "addri": bytes([0x80, 0xC3, imm]), "movri": bytes([0xB3, imm]), "nop": b"\x90"}
            nx = r.choice(sorted(fol))
            data += fol[nx]
            out.append((f"OUT {out_op:02X} pre {pre.hex() or '-'} nx {nx}", data, regs, [AW, BW]))
        elif kind == "test1bcc":
            # (F5c) TEST1 reg,imm followed by a short transfer (Bcc, DBNZ, DBNZNE / DBNZE, BCWZ,
            # BR short; displacement 0: the same path either way): its E pop loads the
            # displacement into IL before TEST1's word after E read the index there (f5c_084,
            # f5c_111, f5b_087, f5a_058, f5c_027)
            for k in (BP, IX, IY):
                regs[k] = _rv(r)
            regs[CW] = r.choice((0, 1, 2, r.randrange(0x10000)))
            w = r.randrange(2)
            rm = r.choice([x for x in range(8) if not (w and x == SP)])
            nx = r.choice((0x70 + r.randrange(16), 0xE0, 0xE1, 0xE2, 0xE3, 0xEB))
            data = bytes([0x0F, 0x18 | w, 0xC0 | rm, r.randrange(256), nx, 0x00])
            out.append((f"TEST1{'bw'[w]} imm + {nx:02X}", data, regs, [AW, CW]))
        elif kind == "repseg":
            # (F5c) REP / REPNE / REPC / REPNC then a segment prefix before a non-string opcode
            # (f5a_030: REP DS1: FPO1): which segment the read uses (the window's pattern at
            # DS0 = DS1 = 0400h against SS = PS = 0)
            rp = r.choice((0xF3, 0xF2, 0x65, 0x64))
            sp_ = r.choice((0x26, 0x2E, 0x36, 0x3E))
            regs[IX] = 0x0100 + 2 * r.randrange(0x700)
            data = bytes([rp, sp_, 0x8B, 0x44, r.randrange(0x80)])
            out.append((f"REP {rp:02X} {sp_:02X} MOV AW,m", data, regs, [AW, CW]))
        elif kind == "repsegstr":
            # (F5d) a REP prefix, then segment prefixes (and BUSLOCK), then a string opcode: the
            # REP page's prefix cells (batch 3's rep_nx ran the string once); every string op,
            # the four REP forms, counts 0-5, DIR either way (the PSW's random DIR)
            rp = r.choice((0xF3, 0xF2, 0x65, 0x64))
            mid = r.choice(([0x26], [0x2E], [0x36], [0x3E], [0x26], [0x2E], [0x36], [0x3E],
                            [r.choice((0x26, 0x2E, 0x36, 0x3E)), r.choice((0x26, 0x2E, 0x36, 0x3E))],
                            [0xF0, r.choice((0x26, 0x2E, 0x36, 0x3E))],
                            [r.choice((0x26, 0x2E, 0x36, 0x3E)), 0xF0]))
            op = r.choice((0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF,
                           0x6C, 0x6D, 0x6E, 0x6F))
            regs[CW] = r.choice((0, 1, 2, 3, 5))
            regs[IX] = 0x0100 + 2 * r.randrange(0x700) + r.randrange(2)
            regs[IY] = 0x0100 + 2 * r.randrange(0x700) + r.randrange(2)
            regs[DW] = r.randrange(0x10000)
            while 0xFEF0 <= regs[DW] <= 0xFF20:
                regs[DW] = r.randrange(0x10000)
            if r.random() < 0.3:
                regs[AW] = (regs[AW] & 0xFF00) | r.randrange(256)
            data = bytes([rp] + mid + [op])
            out.append((f"REP {rp:02X} {' '.join(f'{b:02X}' for b in mid)} {op:02X}", data, regs,
                        [AW, CW, IX, IY]))
        elif kind == "wrapw":
            # (F5d) a word at offset FFFFh (f5i: silicon's second half at the linear address + 1,
            # 16 x seg + 10000h, not the segment's offset 0000h): DS1 = F401h-F4FFh (the low byte
            # wraps the megabyte into the data window, the high byte lands at 04xx0h); a store, a
            # load, a read-modify-write, INC, PUSH, STMW / LDMW stepping through FFFFh
            sv = r.randrange(0xF401, 0xF500)
            pre = [(b"\x68" + sv.to_bytes(2, "little"), f"PUSH {sv:04X}h"), (b"\x07", "POP DS1")]
            regs[CW] = r.randrange(1, 4)
            regs[IX] = regs[IY] = r.choice((0xFFFF, 0xFFFE, 0x0001, 0x0000, 0xFFFD))
            f = r.choice(("st", "ld", "add", "inc", "push", "stm", "ldm"))
            data = {"st": b"\x26\x89\x06\xFF\xFF", "ld": b"\x26\x8B\x06\xFF\xFF",
                    "add": b"\x26\x01\x06\xFF\xFF", "inc": b"\x26\xFF\x06\xFF\xFF",
                    "push": b"\x26\xFF\x36\xFF\xFF\x58", "stm": b"\xF3\xAB",
                    "ldm": b"\x26\xF3\xAD"}[f]
            out.append((f"WRAP {f} DS1 {sv:04X}", data, regs, [AW, CW, IX, IY], pre))
        elif kind == "rot4al":
            # (F5b) ROL4 / ROR4 whose operand is AL itself (or AH): which of the two results AL
            # keeps (f5a_004, f5a_037)
            op = r.choice((0x28, 0x2A))
            rm = r.choice((0, 0, 0, 4))
            data = bytes([0x0F, op, 0xC0 | rm])
            out.append(("ROL4 al" if op == 0x28 else "ROR4 al", data, regs, [AW]))
        elif kind == "io":
            # (F5 regression) word I/O at odd and even ports: a pair of byte cycles at an odd one
            op = r.choice((0xED, 0xEF, 0xE5, 0xE7, 0xEC, 0xEE))
            port = r.randrange(0x10000) | (1 if r.random() < 0.7 else 0)
            while 0xFF00 <= port <= 0xFF20:
                port = r.randrange(0x10000)
            regs[DW] = port
            data = bytes([op]) if op >= 0xEC else bytes([op, port & 0xFF | (1 if r.random() < 0.7 else 0)])
            out.append((f"IO {op:02X}", data, regs, [AW]))
    return out


def case_list_str(r, n):
    """(F5 regression) INMW / OUTMW (REP, count 1-3) at odd and even ports."""
    out = []
    for _ in range(n):
        regs = {k: _rv(r) for k in (AW, CW, DW, BW)}
        op = r.choice((0x6D, 0x6F, 0x6C, 0x6E))
        regs[DW] = r.randrange(0x10000) | (1 if r.random() < 0.7 else 0)
        while 0xFF00 <= regs[DW] <= 0xFF20:
            regs[DW] = r.randrange(0x10000) | 1
        regs[CW] = r.randrange(1, 4)
        regs[IX] = regs[IY] = 0x0100 + 2 * r.randrange(0x700)
        out.append((f"STRIO {op:02X}", bytes([0xF3, op]), regs, [CW, IX, IY]))
    return out


KINDS = ("shift", "shift", "mul", "mul3", "div", "adj", "logic", "arith", "unary", "bit", "rot4",
         "ext", "ins", "prepare", "divovf", "bcd4s", "bitr")
KINDS_R = ("insal", "io", "strio", "extal", "shm0", "rot4al", "resvodd", "test1bcc", "repseg",
           "repsegstr", "wrapw")
KINDS_O = ("outd", "outd2")
N_CASES = 110


def build(name, kind, seed):
    """One program: N_CASES cases of `kind`. The data window at DS0 = DS1 = 0400h for EXT / INS."""
    r = random.Random(seed)
    g = G.Gen("x")
    g.r = random.Random(r.randrange(1 << 30))
    table = G.bank_table(r)
    G.prologue(g, g.r, table)
    g.load_seg("DS0", 0x0400)
    g.load_seg("DS1", 0x0400)
    meta = []
    for op, data, regs, wr, *pre in (case_list_str(r, N_CASES) if kind == "strio" else case_list(kind, r, N_CASES)):
        for k, v in regs.items():
            g.mov16(k, v)
        for d, t in (pre[0] if pre else ()):
            g.setup(d, t)
        psw = (r.randrange(0x1000) & ~0x0300) | 0x0002 | (r.randrange(2) << 10)
        g.setup(b"\x68" + psw.to_bytes(2, "little"), f"PUSH {psw:04X}h")
        g.setup(b"\x9D", "POP PSW")
        g.fz(data, op, f"{op}")
        sp = g.st.sp
        g.b.emit(b"\x9C" + bytes(0x50 + k for k in wr), "OBS PUSH PSW " + " ".join(R16[k] for k in wr), "obs")
        g.b.emit(b"\xBC" + sp.to_bytes(2, "little"), "OBS MOV SP", "obs")
        meta.append((op, data.hex(), {R16[k]: v for k, v in regs.items()}, psw, [R16[k] for k in wr]))
    G.epilogue(g)
    code = g.b.resolve()
    pr = random.Random(seed ^ 0x5A5A)
    end = (G.CODE + len(code) + 0xFFF) & ~0xFFF
    segs = {
        0x00000: G.low_page(),
        G.CODE: code + b"\xF4" * (end - G.CODE - len(code)),
        G.DATA_LO: bytes(pr.randrange(256) for _ in range(G.DATA_HI - G.DATA_LO)),
        G.STK_PAGE: bytes(pr.randrange(256) for _ in range(0x1000)),
        G.INIT_TBL: table + bytes(pr.randrange(256) for _ in range(G.CNT - G.INIT_TBL - len(table)))
        + bytes(0x200),
        G.DUMP: bytes(0x1000),
        0xFFFF0: bytes([0xEA, G.CODE & 0xFF, G.CODE >> 8, 0x00, 0x00]),
    }
    results = [(G.DATA_LO, G.DATA_HI - G.DATA_LO), (G.STK_PAGE, 0x1000), (G.CNT, 0x100), (G.DUMP, 0x200)]
    if kind == "wrapw":
        segs[0xF4000] = bytes(pr.randrange(256) for _ in range(0x2000))
        results.append((0xF4000, 0x2000))
    pages = sorted({a >> 12 for a in segs if a != 0xFFFF0} | set(range(G.CODE >> 12, end >> 12)) | {0xFF}
                   | ({0xF5} if kind == "wrapw" else set()))
    mask = {G.DUMP + 0x20 * g.st.rb + 0x1C, G.DUMP + 0x20 * g.st.rb + 0x1D}
    bt = G.Built(name, "x", seed, [], code, g.b.ins, segs, pages, results, g.cov, g.st.rb, mask,
                 meta={"fuzz": len(meta), "cases": meta})
    return bt


def makers():
    for k, kind in enumerate(KINDS):
        for rep in range(2):
            name = f"f5x_{kind}{rep}{k}"
            seed = 0x5F000000 + 16 * k + rep
            yield name, (lambda name=name, kind=kind, seed=seed: build(name, kind, seed))


def makers_r():
    """f5r: the directed regressions of the F5 fixes that are not flags (INS with AL / AH as the
    offset register; word I/O, IN / OUT / INMW / OUTMW, at odd and even ports; (F5c) the
    reservation after a zero-count memory shift with a transfer to an odd target, TEST1 imm
    before a short transfer, REP then a segment prefix)."""
    for k, kind in enumerate(KINDS_R):
        for rep in range(2):
            name = f"f5r_{kind}{rep}"
            seed = 0x5F100000 + 16 * k + rep
            yield name, (lambda name=name, kind=kind, seed=seed: build(name, kind, seed))


def makers_o():
    """(F5c) f5o: measured on the socket, not gated against the RTL (README "F5c"): an OUT's
    datum when CVTBD / CVTDB follows (silicon: their sign-extended immediate replaces it)."""
    for k, kind in enumerate(KINDS_O):
        for rep in range(2):
            name = f"f5o_{kind}{rep}"
            seed = 0x5F100000 + 16 * 7 + rep if k == 0 else 0x5F200000 + 16 * k + rep   # (outd: taken first as f5r kind 7)
            yield name, (lambda name=name, kind=kind, seed=seed: build(name, kind, seed))


def parse(prog, rec):
    """Per case (op, bytes, regs in, PSW in, {reg: out}, PSW out) from the receipt's writes."""
    w = [x for x in rec["writes"] if not x[2] & 0x02]       # memory writes only
    # the prologue: PUSH DS0 value, PUSH DS1 value (load_seg) x2, PUSH psw, the full OBS
    # (PSW + 8 + 2), then DS0 / DS1 loads (2); count from the first case's PUSH psw
    out = []
    cases = prog.meta["cases"]
    # find the first case: the write of its PSW push
    i = 2 + 1 + 11 + 2
    for op, data, regs, psw, wr in cases:
        if i >= len(w):
            break
        pin = w[i][1]
        i += 1
        if op.startswith("INS") or op.startswith("STRIO") or op.startswith("REP "):
            # INS writes one or two words (unknown count): skip memory writes outside the stack page
            while i < len(w) and not (G.STK_PAGE <= w[i][0] < G.STK_PAGE + 0x1000):
                i += 1
        if i + len(wr) >= len(w):
            break
        pout = w[i][1]
        vals = {}
        for k, rname in enumerate(wr):
            vals[rname] = w[i + 1 + k][1]
        i += 1 + len(wr)
        out.append((op, data, regs, psw, pin, vals, pout))
    return out


def compare(ref="socket", cand="sim", names=None):
    from .fuzz import load
    A, B = load("f5x", ref)["programs"], load("f5x", cand)["programs"]
    progs = dict(makers())
    stats = {}
    for name in sorted(A):
        if names and name not in names:
            continue
        prog = progs[name]()
        ca, cb = parse(prog, A[name]), parse(prog, B[name])
        for x, y in zip(ca, cb):
            op = x[0]
            s = stats.setdefault(op, {"n": 0, "flags": {}, "regs": 0, "ex": []})
            s["n"] += 1
            if x[4] != (x[3] | 0xF000) and x[4] != x[3]:
                pass
            d = (x[6] ^ y[6]) & 0xFFFF
            for b in range(16):
                if d >> b & 1:
                    s["flags"][b] = s["flags"].get(b, 0) + 1
            if x[5] != y[5]:
                s["regs"] += 1
            if (d or x[5] != y[5]) and len(s["ex"]) < 6:
                s["ex"].append((x[1], {k: f"{v:04X}" for k, v in x[2].items()}, f"{x[3]:04X}",
                                {k: f"{v:04X}" for k, v in x[5].items()}, f"{x[6]:04X}",
                                {k: f"{v:04X}" for k, v in y[5].items()}, f"{y[6]:04X}"))
    for op in sorted(stats):
        s = stats[op]
        fl = ", ".join(f"{FLAG_NAMES.get(b, b)} {c}" for b, c in sorted(s["flags"].items()))
        print(f"{op:20s} n={s['n']:4d} regs differ {s['regs']:3d}; flags differ: {fl or '-'}")
        for e in s["ex"][:3]:
            print("     ", e)
    return stats


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--ref", default="socket")
    ap.add_argument("--cand", default="sim")
    a = ap.parse_args()
    compare(a.ref, a.cand, a.names or None)
    sys.exit(0)
