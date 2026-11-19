"""Round 27 (the microcode-size round's probes; docs/v35s-urom-study.md section 7).

Frame of every program: loads (MOV r,imm: the same byte count whatever the operand), a lead, the
subject, the marker OUT 20h,AW (E7 20: AW's value on the pins). Leads: `q` the long shift SHL IX,CL
(CL = 31 from the frame: queue full, bus idle at the subject), `d` none (the subject directly
behind the loads).

r27a  ROL4 / ROR4 on BL and on [BW]: AL and the operand byte over 00, 0F, F0, FF, A5 (all 25 pairs).
r27b  MULU / MUL on BL and BW: zero, one, all-ones, 8000h, the sign combinations, zero halves.
r27d  DIVU BW with DW over 0000, 0001, 0020, 00FF, 7FFF, the divisor DW + 1 / DW + 2 / FFFFh.
r27e  DIV BW / DIV BL / DIV word [BW]: the sign grid, zero remainder, zero quotient.
r27s* the stall maps (tools/r27/): a JMP $+2 or pads in front of the subject, 0 / 1 / 2 waits.
"""

from .gen import q

OUTW = bytes([0xE7, 0x20])
QUIET = [0xD3, 0xE6]                 # SHL IX,CL (CL = 31)
LEADS = {"q": [QUIET], "d": []}


def w16(v):
    return [v & 0xFF, (v >> 8) & 0xFF]


def aw(v): return [0xB8] + w16(v)
def bw(v): return [0xBB] + w16(v)
def dw(v): return [0xBA] + w16(v)
def bl(v): return [0xB3, v & 0xFF]
def mb(v): return [0xC6, 0x07, v & 0xFF]            # MOV byte [BW],imm8
def mw(v): return [0xC7, 0x07] + w16(v)             # MOV word [BW],imm16


BW8 = bw(0x0800)


def _p(name, codes, regs=None):
    return (name, ([q(c, f"i{k}") for k, c in enumerate(codes)], OUTW, dict(regs or {})))


def _both(name, loads, subj):
    return [_p(f"{ln}-{name}", loads + lc + [subj]) for ln, lc in LEADS.items()]


D5 = (0x00, 0x0F, 0xF0, 0xFF, 0xA5)


def round27a():
    v = []
    for op, c in (("rol4", 0x28), ("ror4", 0x2A)):
        for a in D5:
            for b in D5:
                v += _both(f"{op}r-{a:02X}-{b:02X}", [aw(0x5A00 | a), bl(b)], [0x0F, c, 0xC3])
                v += _both(f"{op}m-{a:02X}-{b:02X}", [aw(0x5A00 | a), BW8, mb(b)], [0x0F, c, 0x07])
    return v


U8 = ((1, 1), (0, 0), (0xFF, 0xFF), (0x80, 0x80), (1, 0xFF), (0xFF, 1), (0, 0xFF), (0x55, 0xAA),
      (0x10, 0x10), (0x0F, 0x0F))
U16 = ((1, 1), (0, 0), (0xFFFF, 0xFFFF), (0x8000, 0x8000), (1, 0xFFFF), (0xFFFF, 1), (0, 0xFFFF),
       (0x5555, 0xAAAA), (0x00FF, 0x00FF), (0x0100, 0x0100), (0x8000, 0x0002))
S8 = ((3, 5), (0xFD, 5), (3, 0xFB), (0xFD, 0xFB), (0, 0), (0, 0xFF), (0xFF, 0), (1, 1), (0xFF, 0xFF),
      (0xFF, 1), (1, 0xFF), (0x7F, 0x7F), (0x80, 0x80), (0x80, 1), (0x80, 0xFF), (0x10, 0x10),
      (0xF0, 0x10), (0x10, 0xF0), (0xF0, 0xF0), (0x7F, 0x80), (0x80, 0x7F))
S16 = ((3, 5), (0xFFFD, 5), (3, 0xFFFB), (0xFFFD, 0xFFFB), (0, 0), (0, 0xFFFF), (0xFFFF, 0), (1, 1),
       (0xFFFF, 0xFFFF), (0xFFFF, 1), (1, 0xFFFF), (0x7FFF, 0x7FFF), (0x8000, 0x8000), (0x8000, 1),
       (0x8000, 0xFFFF), (0x0100, 0x0100), (0xFF00, 0x0100), (0x0100, 0xFF00), (0xFF00, 0xFF00),
       (0x7FFF, 0x8000), (0x8000, 0x7FFF))


def round27b():
    v = []
    for op, modrm, g8, g16 in (("mulu", 0xE3, U8, U16), ("mul", 0xEB, S8, S16)):
        for a, b in g8:
            v += _both(f"{op}8-{a:02X}-{b:02X}", [aw(0x5A00 | a), bw(0xA500 | b)], [0xF6, modrm])
        for a, b in g16:
            v += _both(f"{op}16-{a:04X}-{b:04X}", [aw(a), bw(b)], [0xF7, modrm])
    return v


def round27d():
    v = []
    for d in (0x0000, 0x0001, 0x0020, 0x00FF, 0x7FFF):
        for b in sorted({d + 1, d + 2, 0xFFFF}):
            for a in (0x0000, 0xFFFF, 0x1234):
                v += _both(f"divu16-{d:04X}-{a:04X}-{b:04X}", [dw(d), aw(a), bw(b)], [0xF7, 0xF3])
    # the byte form with a non-zero high half (AH) as a control
    for ah in (0x00, 0x01, 0x20, 0x7F):
        for b in sorted({ah + 1, 0xFF}):
            v += _both(f"divu8-{ah:02X}34-{b:02X}", [aw(ah << 8 | 0x34), bw(0xA500 | b)], [0xF6, 0xF3])
    return v


def _s32(x): return x & 0xFFFFFFFF


# (dividend, divisor): the four sign combinations with a remainder, with none, with a zero quotient,
# a zero dividend, and a large pair
G16 = [(100, 7), (-100, 7), (100, -7), (-100, -7), (98, 7), (-98, 7), (98, -7), (-98, -7),
       (3, 7), (-3, 7), (3, -7), (-3, -7), (0, 7), (0, -7), (0x12345678, 0x7FFF),
       (-0x12345678, 0x7FFF), (0x12345678, -0x7FFF), (-0x12345678, -0x7FFF), (0x10000, 3),
       (-0x10000, 3), (-1, 1), (-1, -1), (127, -1)]
G8 = [(100, 7), (-100, 7), (100, -7), (-100, -7), (98, 7), (-98, 7), (98, -7), (-98, -7),
      (3, 7), (-3, 7), (3, -7), (-3, -7), (0, 7), (0, -7), (0x1234, 0x7F), (-0x1234, 0x7F),
      (-1, 1), (-1, -1), (127, -1)]


def _nm(x, bits):
    return ("m" if x < 0 else "p") + format(abs(x), "X")


def round27e():
    v = []
    for n, d in G16:
        nm = f"{_nm(n, 32)}-{_nm(d, 16)}"
        u = _s32(n)
        v += _both(f"div16-{nm}", [dw(u >> 16), aw(u & 0xFFFF), bw(d & 0xFFFF)], [0xF7, 0xFB])
        v += _both(f"div16m-{nm}", [dw(u >> 16), aw(u & 0xFFFF), BW8, mw(d & 0xFFFF)], [0xF7, 0x3F])
    for n, d in G8:
        nm = f"{_nm(n, 16)}-{_nm(d, 8)}"
        v += _both(f"div8-{nm}", [aw(n & 0xFFFF), bw(0xA500 | (d & 0xFF))], [0xF6, 0xFB])
    return v


ROUNDS = {"r27a": round27a, "r27b": round27b, "r27d": round27d, "r27e": round27e}


# ---- the stall maps (r27s, r27t, r27c) -------------------------------------------------------------
# A fetch can only start while the queue has room, and the subjects pop two to four bytes in their first
# words: so the leads starve the queue (a train of NOPs behind the long shift, or JMP $+2 and a few NOPs)
# and the fetch cycle is made long. -nat: the frame's 0 / 1 / 2 waits (3 / 4 / 5 clocks a fetch).
# -yNNN: WTC block 0 = 3 (two waits and READY), PMC1 bit 7 (P17 = READY), the harness holding READY low
# NNN ticks from the column strobe (tools/r27/run27.py sets WTC and the hold from the name): fetch cycles
# of 5 to about 36 clocks. DS0 = F000h in those runs (the PMC1 store in front of M0).
NOPB = [0x90]
PMC1 = bytes([0xC6, 0x06, 0x0A, 0xFF, 0x80])       # MOV byte [0FF0Ah],80h
# name: (loads, the subject, registers, AW's value, BL's value): the leads' fillers reload AW (3 bytes) and BL (2)
S_SUBJ = {
    "mulu16": ([aw(0x1234), bw(0x5678)], [0xF7, 0xE3], {}, 0x1234, 0x78),
    "ror4r": ([aw(0x5AA5), bl(0x3C)], [0x0F, 0x2A, 0xC3], {}, 0x5AA5, 0x3C),
    "rol4r": ([aw(0x5AA5), bl(0x3C)], [0x0F, 0x28, 0xC3], {}, 0x5AA5, 0x3C),
    "divu16": ([dw(0x0001), aw(0x2345), bw(0x7777)], [0xF7, 0xF3], {}, 0x2345, 0x77),
    "div8": ([aw(0x0064), bw(0xA507)], [0xF6, 0xFB], {}, 0x0064, 0x07),
    "mulu8": ([aw(0x5A12), bw(0xA534)], [0xF6, 0xE3], {}, 0x5A12, 0x34),
    "insi": ([aw(0x0005), bl(0x03)], [0x0F, 0x39, 0xC3, 0x02], {"IY": 0x0C40}, 0x0005, 0x03),
}
J0 = [0xEB, 0x00]
SEQS = ("3", "2", "n", "n3", "33", "23", "32", "nn3", "3n", "22", "n2", "333", "233", "n33", "nn", "")
QSEQS = ("", "3", "33", "23", "333", "n3", "nn")


def s_leads(awv, blv):
    """q: the long shift (queue full, bus idle); qS: the shift and a sequence of fillers; jS: JMP $+2 and the
    sequence. Fillers: 3 = MOV AW,imm16, 2 = MOV BL,imm8 (the operands' own values), n = NOP. A boundary falls
    only on a fetch's last clock or an idle bus, so a train of NOPs does not starve the queue: an instruction
    that releases immediate bytes on its last words does."""
    f = {"3": aw(awv), "2": bl(blv), "n": NOPB}
    d = {"q" + k: [QUIET] + [f[c] for c in k] for k in QSEQS}
    d.update({"j" + k: [J0] + [f[c] for c in k] for k in SEQS})
    return d


S_TICKS = (8, 24, 56, 88, 120, 152, 184, 216, 248)      # fetch cycles of 6, 8, 12, ... 36 clocks at fX/2
S_CLK = "y"


def _stall(subjects, ticks=S_TICKS, leads=None, clk="y"):
    from ..chains.types import Instr
    v = []
    pre = [Instr(0, PMC1, "pmc1", "q"), Instr(0, bytes(NOPB), "nop", "q")]
    for sn in subjects:
        loads, code, regs, awv, blv = S_SUBJ[sn]
        for ln, lc in s_leads(awv, blv).items():
            if leads and ln not in leads:
                continue
            v.append(_p(f"{ln}-{sn}-nat", loads + lc + [code], regs))
            for n in ticks:
                for ck in clk:
                    r = {**regs, "DS0": 0xF000, "_waits": (2,), "_pre": pre}
                    v.append(_p(f"{ln}-{sn}-{ck}{n:03d}", loads + lc + [code], r))
    return v


def round27s(): return _stall(("mulu16", "ror4r"), clk=S_CLK)
def round27t(): return _stall(("divu16", "div8"), clk=S_CLK)
def round27u(): return _stall(("rol4r", "mulu8"), clk=S_CLK)
def round27v(): return _stall(("insi",), clk=S_CLK)
def round27x(): return _stall(("mulu16",), ticks=(0, 40, 100, 160, 255), clk="z")
def round27cal(): return _stall(("mulu16",), ticks=(0, 1, 8, 16, 17, 24, 40, 100, 200, 255), leads=("q", "j", "j3"), clk="yzx")


# ---- the refresh maps (r27r*) ------------------------------------------------------------------------
# The other interleaved bus event: a refresh cycle (RFM = F2h: every 64 clocks, RFW = 0). Frame of the body:
# [x] OUT 22h,AL ; MOV CL,k ; SHL IX,CL ; subject ; marker. The shift's count k slides the subject against the
# refresh timer (-rg: RFM = F3h, every 128 clocks) two clocks a step; x (nothing, NOP, NOP NOP, CLC in front of the first marker) and the
# alignment give the other phase. Each program runs with refresh off (-nat, the baseline) and on (-rf: run27.py
# sets RFM from the name); read by r27.py from the two markers' distance. W = 0 only.
R_X = {"": [], "n": [NOPB]}
R_K = tuple(range(4, 32))
R_SUBJ = dict(S_SUBJ, shl=([], [0xD3, 0xE5], {}, 0, 0))     # SHL BP,CL: the long shift as a subject (count k too)


def _refresh(subjects, ks=R_K, xs=R_X, tags=("nat", "rf", "rg")):
    v = []
    for sn in subjects:
        loads, code, regs = R_SUBJ[sn][:3]
        for xn, xc in xs.items():
            for k in ks:
                body = loads + xc + [[0xE6, 0x22], [0xB1, k], QUIET, code]
                for tag in tags:
                    v.append(_p(f"k{k:02d}{xn}-{sn}-{tag}", body, {**regs, "_waits": (0,)}))
    return v


# a long shift in front of the first marker moves the refresh timer's phase 74 clocks: the later clocks of the subject
R_X2 = {"s": [QUIET], "sn": [QUIET, NOPB]}


def round27ra(): return _refresh(("mulu16", "ror4r"))                                   # nat, rf (64), rg (128)
def round27rb(): return _refresh(("divu16", "div8"), xs={**R_X, **R_X2}, tags=("nat", "rg"))
def round27rd(): return _refresh(("mulu16", "ror4r"), xs=R_X2, tags=("nat", "rg"))
def round27re(): return _refresh(("insi", "rol4r", "mulu8"), xs={**R_X, **R_X2}, tags=("nat", "rg"))
R_X3 = {"ss": [QUIET, QUIET], "ssn": [QUIET, QUIET, NOPB]}        # two long shifts: the phase for clocks 66 to 120
def round27rf(): return _refresh(("insi",), xs={**R_X, **R_X2, **R_X3}, tags=("nat", "rg"))
def round27rg(): return _refresh(("mulu8",), xs={**R_X, **R_X2}, tags=("nat", "rg"))
def round27rcal(): return _refresh(("mulu16",), ks=(4, 5, 12, 20, 31), xs={"": [], "n": [NOPB]}, tags=("nat", "rf"))


ROUNDS.update({"r27ra": round27ra, "r27rb": round27rb, "r27rcal": round27rcal, "r27rd": round27rd, "r27rf": round27rf, "r27rg": round27rg, "r27re": round27re})
ROUNDS.update({"r27s": round27s, "r27t": round27t, "r27u": round27u, "r27v": round27v, "r27x": round27x, "r27cal": round27cal})
