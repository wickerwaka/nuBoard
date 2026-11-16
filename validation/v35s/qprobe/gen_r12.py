"""Round 12.

r12a  the unread families: the 80 / 81 / 83 / F6 / F7 immediate forms on a register, MUL / DIV
      on memory, DIV r16 with a negative dividend, DIVU r16 with DW not 0, MUL r,r/m,imm, the
      remaining 0F bit forms, ADD4S / SUB4S / CMP4S by digit count, PREPARE / DISPOSE, the
      transfer residue (CALL r16, CALL mem, JMP mem, RET imm16, BRK imm8)
r12i  interrupt recognition: an NMI or INTP0 edge scheduled a number of ticks after an event
      (OUT FF12h, made before M0) and stepped one clock (8 ticks) at a time across a target:
      a long shift, a train of two-clock instructions, NOPs, a REP MOVBK, a train of
      read-modify-writes, a segment prefix, MOV SS / MOV DS0, a MULU. The handler (behind END)
      makes a marker (OUT 23h) and ends the program.
"""

from ..chains import blocks
from .gen import M1I, NOP, SLOW, q, train
from .gen_r8 import at_body, w16
from .gen_r9 import probe
from .gen_r11 import SLOW_BP, _md, with_regs

CLC = [0xF8]


def round12a():
    v = []
    imm = {"ai16dw0": ([0x81, 0xC2, 0x00, 0x00], M1I), "ai16dw": ([0x81, 0xC2, 0x01, 0x2A], M1I),
           "ai16bw": ([0x81, 0xC3, 0x34, 0x12], None), "ai8bw": ([0x83, 0xC3, 0x01], None),
           "ci16bw": ([0x81, 0xFB, 0x34, 0x12], None), "ci8bw": ([0x83, 0xFB, 0x01], None),
           "ai8bl": ([0x80, 0xC3, 0x01], None), "ci8bl": ([0x80, 0xFB, 0x01], None),
           "ti16bw": ([0xF7, 0xC3, 0x34, 0x12], None), "ti8bl": ([0xF6, 0xC3, 0x01], None)}
    for name, (code, m1) in imm.items():
        v += probe(name, code, m1=m1)
    md = {"mulub": [0xF6, 0x27], "muluw": [0xF7, 0x27], "mulb": [0xF6, 0x2F], "mulw": [0xF7, 0x2F],
          "divub": [0xF6, 0x37], "divuw": [0xF7, 0x37], "divb": [0xF6, 0x3F], "divw": [0xF7, 0x3F]}
    for name, code in md.items():
        setup = [q([0xC7, 0x07, 0x03, 0x00], "st_imm"), q([0xB8, 0x05, 0x00], "mov_aw"),
                 q([0xBA, 0x00, 0x00], "mov_dw"), q(SLOW_BP, "slow")]
        x = lambda: q(code, name)
        v.append((f"mm-{name}-a", (setup + [x()], M1I)))
        v.append((f"mm-{name}-s", (setup + [x(), q(SLOW, "slow")], M1I)))
        v.append((f"mm-{name}-n", (setup + [q(NOP, "nop"), x(), q(SLOW, "slow")], M1I)))
    for i, (a, b, d) in enumerate([(0xFFFF, 1, 0xFFFF), (0xFFFF, 0xFFFF, 0xFFFF),
                                   (0x8001, 1, 0xFFFF), (0x8001, 0xFFFF, 0xFFFF)]):
        v.append(_md(f"divwn-{i}", [0xF7, 0xFB], a, b, dw=d))
    for i, (a, b, d) in enumerate([(0x1234, 0x0800, 0x0020), (0x0000, 0x0002, 0x0001),
                                   (0xFFFF, 0xFFFF, 0xFFFE)]):
        v.append(_md(f"divuwd-{i}", [0xF7, 0xF3], a, b, dw=d))
    v += probe("mi16", [0x69, 0xC3, 0x34, 0x12])
    v += probe("mi8", [0x6B, 0xC3, 0x12])
    v += probe("mi8n", [0x6B, 0xC3, 0xFE])
    v += probe("mi16m", [0x69, 0x07, 0x34, 0x12], pre=[[0xC7, 0x07, 0x03, 0x00]])
    v += probe("mi8m", [0x6B, 0x07, 0x12], pre=[[0xC7, 0x07, 0x03, 0x00]])
    bits = {"c1mcl": [0x0F, 0x12, 0x07], "n1mcl": [0x0F, 0x16, 0x07],
            "s1mi": [0x0F, 0x1C, 0x07, 0x03], "c1i": [0x0F, 0x1A, 0xC0, 0x03],
            "n1i": [0x0F, 0x1E, 0xC0, 0x03], "t1wmcl": [0x0F, 0x11, 0x07],
            "ror4m": [0x0F, 0x2A, 0x07]}
    for name, code in bits.items():
        v += probe(name, code)
    for n in (1, 2, 4, 8):
        for name, code in {"add4s": [0x0F, 0x20], "sub4s": [0x0F, 0x22],
                           "cmp4s": [0x0F, 0x26]}.items():
            v.append((f"{name}{n}-a", [q([0xB1, n], "mov_cl"), q(code, name)]))
            v.append((f"{name}{n}-s", [q([0xB1, n], "mov_cl"), q(code, name), q(SLOW, "slow")]))
    v += probe("prep1", [0xC8, 0x08, 0x00, 0x01])
    v += probe("prep2", [0xC8, 0x08, 0x00, 0x02])
    v += probe("disp", [0xC9], pre=[[0xC8, 0x08, 0x00, 0x00]])
    for n in (0, 1):
        t = train(NOP, "nop", n)
        v.append((f"tr-callr-{n}", at_body(lambda a, t=t: [
            q([0xBB] + w16(a + 5), "mov_bw"), q([0xFF, 0xD3], "callr")] + t)))
        v.append((f"tr-callm-{n}", at_body(lambda a, t=t: [
            q([0xC7, 0x06, 0x00, 0x0C] + w16(a + 10), "st_imm"),
            q([0xFF, 0x16, 0x00, 0x0C], "callm")] + t)))
        v.append((f"tr-jmpm-{n}", at_body(lambda a, t=t: [
            q([0xC7, 0x06, 0x00, 0x0C] + w16(a + 10), "st_imm"),
            q([0xFF, 0x26, 0x00, 0x0C], "jmpm")] + t)))
        v.append((f"tr-reti-{n}", at_body(lambda a, t=t: [
            q([0x68] + w16(a + 6), "pushi"), q([0xC2, 0x00, 0x00], "reti")] + t)))
        v.append((f"tr-brk-{n}", at_body(lambda a, t=t: [
            q([0xC7, 0x06, 0x00, 0x01] + w16(a + 14), "vec_ip"),
            q([0xC7, 0x06, 0x02, 0x01, 0x00, 0x10], "vec_ps"), q([0xCD, 0x40], "brk")] + t)))
    return v


# ---- interrupts

def _setup(src):
    vec = 0x08 if src == "nmi" else 0x60
    s = [q([0xC7, 0x06, vec, 0x00, 0x00, 0x00], "vec"),
         q([0xC7, 0x06, vec + 2, 0x00, 0x00, 0x10], "vec_ps")]
    if src == "intp0":
        s += [q([0xB8, 0x00, 0xF0], "mov_aw"), q([0x8E, 0xC0], "mov_ds1"),
              q([0x26, 0xC6, 0x06, 0x4C, 0xFF, 0x07], "exic0"),
              q([0xB8, 0x00, 0x00], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
    s += [q([0xBA, 0x12, 0xFF], "mov_dw"), q([0xB0, 0x01], "mov_al")]
    if src == "intp0":
        s.append(q([0xFB], "ei"))
    s += [q([0xEE], "event"), q([0xBA, 0x20, 0x00], "mov_dw")]
    if sum(len(i.code) for i in s) & 1:         # an even length keeps the frame's parity
        s.insert(0, q(NOP, "nop"))
    return s


HANDLER = [q([0xE6, 0x23] + list(blocks.END), "handler")]


def irq(name, src, body, delays, waits=None):
    """One program per delay (ticks from the event's OUT to the edge at the pins, less 4)."""
    out = []
    level = "NMI" if src == "nmi" else "INTP0"
    for d in delays:
        stim = {"entries": [{"event": 1, "delay": d, "hold": 400, "levels": {level: 0}}]}
        extra = {"_pre": _setup(src), "_post": HANDLER, "_stim": stim}
        tag = ""
        if waits is not None:
            extra["_waits"] = waits
            tag = f"-v{waits[0]}"
        out.append((f"{name}-{src}{tag}-d{d}", ([q(c, "x") for c in body], None, extra)))
    return out


TARGETS = {
    "ls": [SLOW, NOP, NOP, NOP],
    "clc": [CLC] * 20,
    "nop": [NOP] * 12,
    "rep": [[0xB9, 0x03, 0x00], [0xF3, 0xA5], NOP, NOP],
    "rmw": [[0x01, 0x07]] * 4 + [NOP],
    "pfx": [NOP, NOP, [0x26, 0x8B, 0x07], NOP, NOP, NOP],
    "ss": [NOP, NOP, [0x8E, 0xD0], NOP, NOP, NOP],
    "ds": [NOP, NOP, [0x8E, 0xD8], NOP, NOP, NOP],
    "mul": [[0xF6, 0xE3], [0xF6, 0xE3], NOP],
}


def round12cal():
    v = []
    for src in ("nmi", "intp0"):
        v += irq("cal-nop", src, TARGETS["nop"], (400, 800, 1200))
    return v


# windows in clocks after the first long shift's end (W = 0 lengths; longer with waits), and
# the delay that puts the edge on that clock (from r12cal in simulation: K clocks at each wait)
WIN = {"ls": (56, 90), "clc": (-2, 22), "nop": (-2, 22), "rep": (22, 72), "rmw": (-2, 30),
       "pfx": (0, 24), "ss": (0, 24), "ds": (0, 24), "mul": (0, 30)}
K = {0: 94, 1: 98, 2: 103}


def round12i(only=None):
    v = []
    for src in ("nmi", "intp0"):
        for t, body in TARGETS.items():
            if only is not None and t != only:
                continue
            lo, hi = WIN[t]
            for w in (0, 1, 2):
                top = hi + (w * (hi - lo)) // 4
                v += irq(f"i-{t}", src, body, [8 * (r + K[w]) for r in range(lo, top)], (w,))
    return v


# second pass: silicon recognises the edge about 20 clocks later than the RTL the first windows
# were laid out with; the same programs with the edge that much earlier
WIN2 = {"ls": (60, 90), "clc": (-2, 26), "nop": (-2, 22), "rep": (22, 86), "rmw": (-2, 34),
        "pfx": (0, 26), "ss": (0, 26), "ds": (0, 26), "mul": (0, 34)}


def round12j(only, step=1):
    v = []
    for src in ("nmi", "intp0"):
        lo, hi = WIN2[only]
        for w in (0, 1, 2):
            top = hi + (w * (hi - lo)) // 4
            v += irq(f"j-{only}", src, TARGETS[only],
                     [8 * (r + K[w] - 20) for r in range(lo, top, step)], (w,))
    return v


def round12b():
    """EXT / INS by bit offset (BL, set before M0) and length (imm4 + 1)."""
    v = []
    for off in (0, 5, 12):
        for ln in (0, 3, 7, 15):
            pre = {"_pre": [q([0xB3, off], "mov_bl")]}
            v.append((f"ext-o{off}-l{ln}", ([q([0x0F, 0x3B, 0xC3, ln], "exti")], None, pre)))
            v.append((f"ins-o{off}-l{ln}", ([q([0x0F, 0x39, 0xC3, ln], "insi")], None, pre)))
    return v


ROUNDS = {**{f"r12j{t}": (lambda t=t: round12j(t)) for t in TARGETS},
          **{f"r12k{t}": (lambda t=t: round12j(t, 7)) for t in TARGETS},
          **{f"r12i{t}": (lambda t=t: round12i(t)) for t in TARGETS}, "r12b": round12b, "r12a": round12a, "r12cal": round12cal, "r12i": round12i}
