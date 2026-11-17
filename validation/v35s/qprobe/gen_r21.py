"""Round 21.

r21m  a read against the fetch chain behind an EU cycle (Q95): eight leads that leave an EU cycle
      in front of the subject's boundary (PUSH, a store, OUT imm8, POP, IN, PUSH ; NOP, OUT ; NOP,
      two PUSHes) x ten subjects whose read request ripens at different clocks of the chain.
      Separates "from the chain's second fetch on" from "behind a memory write only".
"""

from .gen import M1I, M1P, NOP, RI, RR, SLOW, q

PUSH, OUT22, POP, IN40, SACC = [0x50], [0xE6, 0x22], [0x58], [0xE4, 0x40], [0xA3, 0x00, 0x0C]
SUBJ = {"addi8x": [0x83, 0x06, 0x00, 0x0C, 0x01], "addi88": [0x83, 0x47, 0x10, 0x01],
        "addi8b": [0x83, 0x07, 0x01], "cmpi8x": [0x83, 0x3E, 0x00, 0x0C, 0x01],
        "add8": [0x01, 0x47, 0x10], "addbw": [0x01, 0x07], "ld16": [0x8B, 0x87, 0x10, 0x02],
        "ldir": [0x8B, 0x06, 0x00, 0x0C], "lacc": [0xA1, 0x00, 0x0C], "cmpm": [0x3B, 0x87, 0x10, 0x02]}
LEAD = {"p": [PUSH], "st": [SACC], "o": [OUT22], "pop": [POP], "in": [IN40], "pn": [PUSH, NOP],
        "on": [OUT22, NOP], "pp": [PUSH, PUSH]}


def round21m():
    v = []
    for sn, code in SUBJ.items():
        for ln, pcs in LEAD.items():
            v.append((f"m-{sn}-{ln}", [q(c, "lead") for c in pcs] + [q(code, sn)]))
    x = lambda: q(SUBJ["addi8x"], "addi8x")
    v.append(("m-addi8x-p-fn", [q(PUSH, "lead"), x(), q(NOP, "nop")]))
    v.append(("m-addi8x-p-fri", [q(PUSH, "lead"), x(), q(RI, "ri")]))
    v.append(("m-addi8x-p-fs", [q(PUSH, "lead"), x(), q(SLOW, "slow")]))
    return v


INC, PUSHI, MI16R = [0x43], [0x68, 0x34, 0x12], [0x69, 0xC3, 0x34, 0x12]
QL = {"0": [], "n": [NOP], "nn": [NOP, NOP], "nnn": [NOP] * 3, "p": [PUSH], "pn": [PUSH, NOP],
      "pnn": [PUSH, NOP, NOP], "o": [OUT22], "on": [OUT22, NOP], "onn": [OUT22, NOP, NOP],
      "st": [SACC], "stn": [SACC, NOP], "ri": [RI], "rr": [RR], "i": [INC], "pop": [POP],
      "x": None, "xx": None, "pi": [PUSH, INC], "oi": [OUT22, INC]}


def round21q():
    """A word-wide pop on a word that is not bus-idle (PUSH imm16's fifth word, MUL r,r,imm16's)
    against the first clock of a chained fetch: does every 16-bit queue read wait there, or only
    the bus-idle words that make one (Q96)."""
    v = []
    for sn, code in (("pushi", PUSHI), ("mi16", MI16R)):
        x = lambda: q(code, sn)
        for ln, pcs in QL.items():
            if ln == "x":
                body = [x(), x()]
            elif ln == "xx":
                body = [x(), x(), x()]
            else:
                body = [q(c, "lead") for c in pcs] + [x()]
            v.append((f"q-{sn}-{ln}", body))
            v.append((f"q-{sn}-{ln}-mi", (list(body), M1I)))
    return v


# ---- r21f: the corpus encodings with no probe (the round-21 split's "not probed" rows)
FF = {  # C7 with two registers and a displacement
      "stix16": [0xC7, 0x80, 0x10, 0x02, 0x34, 0x12], "stix8": [0xC7, 0x40, 0x10, 0x34, 0x12],
      # ALU [BW],r with write-back, other than ADD word (01 07 the control)
      "addw": [0x01, 0x07], "orw": [0x09, 0x07], "andw": [0x21, 0x07], "subw": [0x29, 0x07],
      "xorw": [0x31, 0x07], "adcw": [0x11, 0x07], "sbbw": [0x19, 0x07], "addb": [0x00, 0x07],
      "orb": [0x08, 0x07], "subb": [0x28, 0x07],
      # read-modify-write with d16: SHL 1, DEC
      "shl1d16": [0xD1, 0xA7, 0x10, 0x02], "decd16": [0xFF, 0x8F, 0x10, 0x02],
      # stores, loads, RMW and XCH with d16 / direct / two registers and d16
      "std16": [0x89, 0x87, 0x10, 0x02], "stx16": [0x89, 0x80, 0x10, 0x02], "stdir": [0x89, 0x06, 0x00, 0x0C],
      "rmwd16": [0x01, 0x87, 0x10, 0x02], "rmwx16": [0x01, 0x80, 0x10, 0x02], "rmwdir": [0x01, 0x06, 0x00, 0x0C],
      "ldpy16": [0x8B, 0x83, 0x10, 0x02], "ldix16": [0x8B, 0x84, 0x10, 0x02], "xchdir": [0x87, 0x06, 0x00, 0x0C],
      # SET1 / CLR1 / NOT1 word on memory by CL and by imm4
      "s1m": [0x0F, 0x15, 0x07], "s1mdir": [0x0F, 0x15, 0x06, 0x00, 0x0C], "s1md8": [0x0F, 0x15, 0x47, 0x10],
      "s1md16": [0x0F, 0x15, 0x87, 0x10, 0x02], "s1mx": [0x0F, 0x15, 0x00], "c1m": [0x0F, 0x13, 0x07],
      "c1mi": [0x0F, 0x1B, 0x07, 0x0F], "n1m": [0x0F, 0x17, 0x07],
      # accumulator immediates, CVTDB, DI, CMPBK alone
      "testai": [0xA9, 0x34, 0x12], "cmpai": [0x3D, 0x34, 0x12], "cvtdb": [0xD5, 0x0A], "di": [0xFA],
      "cmpbkw": [0xA7]}


def round21f():
    from .gen_r9 import probe
    from .gen_r12 import at_body
    from .gen_r8 import w16
    from .gen_r11 import with_regs
    v = []
    for name, code in FF.items():
        x = lambda: q(code, name)
        for pn, pc in (("i", INC), ("c", [0x98]), ("n", NOP), ("k", [0xF8])):
            v.append((f"fl-{name}-{pn}", [q(pc, "prev"), x()]))
        v += probe(f"f-{name}", code)
        v.append((f"f-{name}-p", [q(PUSH, "lead"), x()]))
        v.append((f"f-{name}-o", [q(OUT22, "lead"), x()]))
        v.append((f"f-{name}-mi", ([x()], M1I)))
        v.append((f"f-{name}-mp", ([x()], M1P)))
    # transfers through [BW]: the target stored first (near: the word; far: offset and segment)
    for n in (0, 1):
        t = [q(NOP, "nop")] * n
        for name, op in (("callmbw", 0x17), ("jmpmbw", 0x27)):
            v.append((f"t-{name}-{n}", at_body(lambda a, t=t, op=op, name=name: [
                q([0xC7, 0x07] + w16(a + 6), "st_imm"), q([0xFF, op], name)] + list(t))))
        for name, op in (("callfmbw", 0x1F), ("jmpfmbw", 0x2F)):
            v.append((f"t-{name}-{n}", at_body(lambda a, t=t, op=op, name=name: [
                q([0xC7, 0x07] + w16(a + 11), "st_imm"), q([0xC7, 0x47, 0x02, 0x00, 0x10], "st_seg"),
                q([0xFF, op], name)] + list(t))))
    # REP INM / OUTM word with CW = 0, 1, 2
    rio = []
    for n in (0, 1, 2):
        cw = [0xB9, n, 0x00]
        for name, op in (("rinmw", 0x6D), ("routmw", 0x6F)):
            rio.append((f"r-{name}{n}-a", [q(cw, "mov_cw"), q([0xF3, op], name)]))
            rio.append((f"r-{name}{n}-n", [q(cw, "mov_cw"), q(NOP, "nop"), q([0xF3, op], name)]))
            rio.append((f"r-{name}{n}-s", [q(cw, "mov_cw"), q([0xF3, op], name), q(SLOW, "slow")]))
    v += with_regs(rio, {"DW": 0x0022}, M1I)
    return v


# ---- r21c: the corpus frame itself (marker ; X ; marker behind the long shift) for the rows whose
# probes are exact in the model and in the RTL while the corpus runs diverge behind the marker
CF = ["mulu_aw", "mulu_dw", "mul_cw", "add_dw_imm0", "add_dw_imm2a01", "in_al_dw", "in_aw_dw", "pop_m",
      "test1_mw_cl", "cmp_aw_aw", "rol4_dl", "mov_aw_dw", "cvtwl", "ext_dl_bh", "ext_bl_dh", "ins_bl_dh",
      "shl_imm8", "shl_imm4", "st_imm_bw_d8", "add4s", "ld_bw_ix_d16", "or_m_aw", "set1_rw_cl", "ld_dir",
      "add_dw_imm", "cmp_aw_dw", "test_m_imm", "set1_rb_cl", "br_bw"]


def round21c():
    from ..chains.forms import FORMS
    v = []
    for name in CF:
        code = list(FORMS[name].code)
        if name == "br_bw":
            continue
        x = lambda: q(code, name)
        v.append((f"c-{name}-oo", ([q(OUT22, "lead"), x()], M1I)))
        v.append((f"c-{name}-pp", ([q(PUSH, "lead"), x()], M1P)))
        v.append((f"c-{name}-xo", ([x()], M1I)))
        v.append((f"c-{name}-xp", ([x()], M1P)))
    return v


ROUNDS = {"r21m": round21m, "r21q": round21q, "r21f": round21f, "r21c": round21c}
