"""Chain families F0-F9 (plan, "Families"). Each generator returns list[Chain].

Default sweep per chain: waits {0,1,2} x parity {even, odd}. waits is memory
waits only (WTC field 0); I/O stays at 0 waits unless io_waits is given. The "cost frame"
is PAD LS M0 X M1 LS END. F2-F8 are generated once per marker kind in
COST_MARKERS (push, then out), the kind in the id: F3-push-shl_cl16-k2-pE-w0.
parity is always that of the first body byte after the first LS, so with the
1-byte PUSH marker the X after M0 sits at the other parity (both are swept).
"""

from __future__ import annotations

from . import blocks
from .forms import (BW_ODD, DEFAULT_REGS, FORMS, IO, LOAD_ALU, LOADS_BY_MODE, PUSH_POP_MEM,
                    REGISTER_ONLY, RMW, STACK, STORES)
from .image import assign_offsets, needs_pad
from .types import PRC_FX2, RFM_OFF, RFM_ON, WTC_FOR_WAITS, WTC_IO_SHIFT, Chain, Instr

WAITS = (0, 1, 2)
PARITIES = ("even", "odd")


# Body pieces ---------------------------------------------------------------

def LS():
    return Instr(0, blocks.LS, "LS", "ls")


def M(i, kind="out"):
    return Instr(0, blocks.marker(kind, i), "M", "marker", marker_id=i)


def X(name, index):
    return Instr(0, FORMS[name].code, name, "x", index=index)


def D(i):
    return Instr(0, blocks.drainer(i), "D", "drain")


def D4(i):
    return Instr(0, blocks.drainer4(i), "D4", "drain")


def END():
    return Instr(0, blocks.END, "END", "end")


def xs(names):
    """X instructions for a list of form names, indexed in order."""
    return [X(name, i) for i, name in enumerate(names)]


def cost_frame(x_instrs, kind="out"):
    return [LS(), M(0, kind)] + x_instrs + [M(1, kind), LS(), END()]


def make_chain(family, name, knobs, body, waits, parity, marker_kind="out", regs=None,
               wtc=None, rfm=RFM_OFF, prc=PRC_FX2, io_waits=0,
               prelude_marker=None) -> Chain:
    """Prefix the parity PAD when needed and assign offsets.

    wtc defaults to WTC_FOR_WAITS[waits] (memory) with io_waits in field 7;
    an explicit wtc (F0w) overrides both.
    """
    regs = {**DEFAULT_REGS, **(regs or {})}
    for instr in body:
        if instr.role == "x":
            regs.update(dict(FORMS[instr.form].needs))
    if wtc is None:
        wtc = WTC_FOR_WAITS[waits] | (io_waits << WTC_IO_SHIFT)
    instrs = [Instr(i.offset, i.code, i.form, i.role, i.marker_id, i.index) for i in body]
    if needs_pad(regs, wtc, rfm, prc, parity, prelude_marker):
        instrs.insert(0, Instr(0, blocks.PAD, "PAD", "pad"))
    assign_offsets(instrs)
    p = "E" if parity == "even" else "O"
    suffix = f"-p{p}" + (f"-w{waits}" if waits >= 0 else "")
    return Chain(id=f"{family}-{name}{suffix}", family=family, knobs=dict(knobs),
                 waits=waits, parity=parity, marker_kind=marker_kind, instrs=instrs,
                 regs=regs, wtc=wtc, rfm=rfm, prc=prc, prelude_marker=prelude_marker)


def _sweep(family, variants, waits, parities, **kw):
    """variants: (name, knobs, body, extra) where extra is make_chain keywords."""
    chains = []
    for name, knobs, body, extra in variants:
        for w in waits:
            for p in parities:
                chains.append(make_chain(family, name, knobs, body, w, p, **{**kw, **extra}))
    return chains


# Marker kinds for the cost-frame families F2-F8, push first. F1 on the board:
# PUSH AW gives a constant marker interval (9 clocks at 0 waits, 10 at 1, both
# parities); OUT's varies 10-12 with fetch interleaving.
COST_MARKERS = ("push", "out")


def _remark(body, kind):
    """The body with every marker replaced by the same-numbered marker of kind."""
    return [M(i.marker_id, kind) if i.role == "marker" else i for i in body]


def _sweep_markers(family, variants, waits, parities, **kw):
    """_sweep once per marker kind in COST_MARKERS, the kind leading the name."""
    chains = []
    for kind in COST_MARKERS:
        marked = [(f"{kind}-{name}", {**knobs, "marker": kind}, _remark(body, kind), extra)
                  for name, knobs, body, extra in variants]
        chains += _sweep(family, marked, waits, parities, marker_kind=kind, **kw)
    return chains


def _align_regs(align):
    return {"BW": BW_ODD} if align == "odd" else {}


def _cost_variants(names, ks=(1,), align=False):
    """Cost-frame variants X^k for each form name; plus odd-word variants."""
    out = []
    for name in names:
        for k in ks:
            out.append((f"{name}-k{k}", {"x": name, "k": k}, cost_frame(xs([name] * k)), {}))
    if align:
        for name in names:
            if FORMS[name].align_ok:
                for k in (ks if align == "all" else ks[:1]):
                    out.append((f"{name}-k{k}-odd", {"x": name, "k": k, "align": "odd"},
                                cost_frame(xs([name] * k)), {"regs": _align_regs("odd")}))
    return out


EMPTY = ("empty", {"x": None, "k": 0}, cost_frame([]), {})


# Families ------------------------------------------------------------------

def f0(waits=WAITS, parities=PARITIES):
    """Idle: bus cadence, fill words past LS, fence history-independence."""
    variants = [
        ("ls", {"template": "LS END"}, [LS(), END()], {}),
        ("ls_ls", {"template": "LS LS END"}, [LS(), LS(), END()], {}),
        ("ls_nop_ls", {"template": "LS 90 LS END"}, [LS(), X("nop", 0), LS(), END()], {}),
    ]
    return _sweep("F0", variants, waits, parities)


def f0w(waits=WAITS, parities=PARITIES):
    """WTC map: one 2-bit field at 2 waits, the rest at 0; plus 0000/AAAA references."""
    del waits     # wtc is explicit
    values = [2 << (2 * field) for field in range(8)] + [0x0000, 0xAAAA]
    chains = []
    for wtc in values:
        body = [LS(), M(0), LS(), END()]
        field = (wtc.bit_length() - 1) // 2 if wtc not in (0, 0xAAAA) else None
        for p in parities:
            chains.append(make_chain("F0w", f"wtc{wtc:04X}", {"wtc": wtc, "field": field},
                                     body, -1, p, wtc=wtc))
    return chains


def f1(waits=WAITS, parities=PARITIES):
    """Marker control: 1, 2 and 4 markers between fences, three marker kinds."""
    variants = []
    for kind in blocks.MARKER_KINDS:
        for n in (1, 2, 4):
            body = [LS()] + [M(i, kind) for i in range(n)] + [LS(), END()]
            variants.append((f"{kind}-m{n}", {"marker": kind, "markers": n}, body,
                             {"marker_kind": kind}))
    return _sweep("F1", variants, waits, parities)


F2_X = [[], ["nop"], ["nop"] * 2, ["nop"] * 3, ["mov_aw_dw"], ["mov_aw_imm"], ["pfx_nop"],
        ["add_dw_imm"], ["pfx2_mov_aw_imm"], ["pfx3_mov_aw_imm"]]


def f2(waits=WAITS, parities=PARITIES):
    """Release: LS X M0 LS END, restart fetch vs bytes taken by the decoder."""
    variants = []
    for names in F2_X:
        label = "empty" if not names else f"{names[0]}{len(names) if len(names) > 1 else ''}"
        variants.append((label, {"x": names}, [LS()] + xs(names) + [M(0), LS(), END()], {}))
    return _sweep_markers("F2", variants, waits, parities)


def f3(waits=WAITS, parities=PARITIES):
    """EU cost of register-only forms, full queue, X^k for k in {1,2,4}."""
    variants = [EMPTY] + _cost_variants(REGISTER_ONLY, ks=(1, 2, 4))
    return _sweep_markers("F3", variants, waits, parities)


F4_K2 = ["ld_bw", "ld_bw_ix", "ld_dir", "ld_bw_d8", "ld_bw_ix_d8", "ld_bw_d16"]


def f4(waits=WAITS, parities=PARITIES):
    """Loads by addressing mode; k=2 for one mode per class; odd-word variants."""
    variants = [EMPTY] + _cost_variants(LOADS_BY_MODE + ["ld_acc_dir", "ldb_bw"])
    variants += [(f"{n}-k2", {"x": n, "k": 2}, cost_frame(xs([n] * 2)), {}) for n in F4_K2]
    # Alignment knob: the [BW]/[BW+d8] word loads at k=1 and k=2, and the byte
    # load at [0801h] as a no-split control.
    for name in ("ld_bw", "ld_bw_d8"):
        for k in (1, 2):
            variants.append((f"{name}-k{k}-odd", {"x": name, "k": k, "align": "odd"},
                             cost_frame(xs([name] * k)), {"regs": _align_regs("odd")}))
    variants.append(("ldb_bw-k1-odd", {"x": "ldb_bw", "k": 1, "align": "odd"},
                     cost_frame(xs(["ldb_bw"])), {"regs": _align_regs("odd")}))
    return _sweep_markers("F4", variants, waits, parities)


def f5(waits=WAITS, parities=PARITIES):
    """Order classes: stores, RMW, PUSH/POP mem, stack, I/O, load+ALU, k in {1,2}."""
    names = LOAD_ALU + STORES + RMW + PUSH_POP_MEM + STACK + IO
    variants = [EMPTY] + _cost_variants(names, ks=(1, 2), align="first")
    return _sweep_markers("F5", variants, waits, parities)


F6_X = ["ld_bw", "st_bw", "add_m_aw", "push_aw", "out_imm_al", "in_al_imm", "mov_aw_imm"]
F6_N = (0, 1, 2, 3, 4, 6)
F6_D4 = (["ld_bw", "st_bw", "out_imm_al"], (2, 4))


def f6(waits=WAITS, parities=PARITIES):
    """Arbitration at depth: LS M0 D^n X M1 LS END."""
    variants = []
    for name in F6_X:
        for n in F6_N:
            body = [LS(), M(0)] + [D(i) for i in range(n)] + [X(name, 0), M(1), LS(), END()]
            variants.append((f"{name}-n{n}", {"x": name, "n": n, "drain": "D"}, body, {}))
    for name in F6_D4[0]:
        for n in F6_D4[1]:
            body = [LS(), M(0)] + [D4(i) for i in range(n)] + [X(name, 0), M(1), LS(), END()]
            variants.append((f"{name}-n{n}d4", {"x": name, "n": n, "drain": "D4"}, body, {}))
    return _sweep_markers("F6", variants, waits, parities)


F7_X = ["ld_bw", "st_bw", "add_m_aw", "push_aw", "out_imm_al", "mov_aw_dw"]


def f7(waits=WAITS, parities=PARITIES):
    """Neighbours: X = A B over the 6x6 grid."""
    variants = [(f"{a}-{b}", {"a": a, "b": b}, cost_frame(xs([a, b])), {})
                for a in F7_X for b in F7_X]
    return _sweep_markers("F7", variants, waits, parities)


F8_X = ["nop", "ld_bw", "st_bw"]


def f8(waits=WAITS, parities=PARITIES):
    """Refresh on (RFM=FCh): cost frame, X^4, plus the empty frame."""
    variants = [("empty", {"x": None, "k": 0}, cost_frame([]), {})]
    variants += [(f"{n}-k4", {"x": n, "k": 4}, cost_frame(xs([n] * 4)), {}) for n in F8_X]
    return _sweep_markers("F8", variants, waits, parities, rfm=RFM_ON)


# F9 release series: LS X M0 LS END (PUSH marker) and the marker-less LS X LS END,
# X = a list of catalog forms. The restart fetch after the idle gap is the first
# queue room the decoder makes; the fetches from it to the next idle count the
# bytes consumed (the trailing LS's bytes are taken at once, then it runs ~70
# clocks with the queue full).
def _f9_x() -> list[tuple[str, list[str]]]:
    nops = lambda n: ["nop"] * n
    out = [(f"nop{n}" if n else "empty", nops(n)) for n in range(9)]
    out += [(f"movr_nop{n}", ["mov_aw_dw"] + nops(n)) for n in range(5)]
    out += [("nop_movr", nops(1) + ["mov_aw_dw"]), ("nop2_movr", nops(2) + ["mov_aw_dw"]),
            ("movr2", ["mov_aw_dw"] * 2)]
    out += [(f"imm_nop{n}", ["mov_aw_imm"] + nops(n)) for n in range(4)]
    out += [("nop_imm", nops(1) + ["mov_aw_imm"]), ("nop2_imm", nops(2) + ["mov_aw_imm"])]
    out += [(f"es_nop{n}", ["pfx_es"] + nops(n)) for n in range(4)]
    out += [("es2_nop", ["pfx_es", "pfx_es", "nop"]), ("es_movr", ["pfx_mov_aw_dw"]),
            ("es_imm", ["pfx_mov_aw_imm"]), ("es2_imm", ["pfx2_mov_aw_imm"]),
            ("es3_imm", ["pfx3_mov_aw_imm"]), ("addi", ["add_dw_imm"]),
            ("nop_addi", ["nop", "add_dw_imm"])]
    return out


F9_X = _f9_x()


def f9(waits=WAITS, parities=PARITIES):
    """Release series: LS X M0 LS END (PUSH) and LS X LS END (no marker) per X."""
    marked, bare = [], []
    for label, names in F9_X:
        knobs = {"x": names, "bytes": sum(FORMS[n].length for n in names)}
        marked.append((f"push-{label}", {**knobs, "marker": "push"},
                       [LS()] + xs(names) + [M(0, "push"), LS(), END()], {}))
        bare.append((f"none-{label}", {**knobs, "marker": "none"},
                     [LS()] + xs(names) + [LS(), END()], {}))
    return (_sweep("F9", marked, waits, parities, marker_kind="push")
            + _sweep("F9", bare, waits, parities, marker_kind="none"))


# F10 OUT DW interlock series: PAD LS M0 P X M1 LS END with the PUSH marker, X an IN or
# OUT DW form, P the instruction(s) before it: none (the F5 case), one that writes DW
# (the port register) or a control of the same format that writes another register,
# reads DW only, or is a NOP; MOV DW,imm16 followed by one or two NOPs (distance from
# the write); a DW load from memory and its AW control. The marker-less variant
# PAD LS P X LS END (the I/O cycle is its own anchor) for P = none and MOV DW,imm16.
# P = MOV DW,0FF04h (OUT only, both kinds) puts the port in the END's FF00h page, to
# separate the port from the HALT that follows the END's OUT DW,AL.
# Every chain presets AW = DW = 0040h (the port); the long shift clears AW, so MOV
# DW,AW and XCH AW,DW move the port to 0, MOV DW,[0C00h] to 9090h (the data fill).
F10_P = [("none", []), ("movdwi", ["mov_dw_imm"]), ("movawi", ["mov_aw_imm"]),
         ("movdwaw", ["mov_dw_aw"]), ("movcwaw", ["mov_cw_aw"]), ("xch", ["xch_aw_dw"]),
         ("nop", ["nop"]), ("adddwi", ["add_dw_imm0"]), ("addawi", ["add_aw_imm"]),
         ("movawdw", ["mov_aw_dw"]), ("movdwi_nop", ["mov_dw_imm", "nop"]),
         ("movdwi_nop2", ["mov_dw_imm", "nop", "nop"]), ("lddw", ["ld_dw_dir"]),
         ("ldaw", ["ld_dir"])]
F10_X = [("outdw", "out_dw_al"), ("indw", "in_al_dw")]
F10_BARE = ("none", "movdwi", "movdwff")
F10_HIGH = [("movdwff", ["mov_dw_ff04"])]       # OUT DW,AL only
F10_REGS = {"AW": 0x0040}


def f10(waits=WAITS, parities=PARITIES):
    """OUT DW interlock: LS M0 P X M1 LS END (PUSH) and LS P X LS END (no marker)."""
    marked, bare = [], []
    for plabel, pnames in F10_P + F10_HIGH:
        for xlabel, xname in F10_X[:1] if (plabel, pnames) in F10_HIGH else F10_X:
            names = pnames + [xname]
            knobs = {"p": pnames, "x": xname, "bytes": sum(FORMS[n].length for n in pnames)}
            marked.append((f"push-{plabel}-{xlabel}", {**knobs, "marker": "push"},
                           [LS(), M(0, "push")] + xs(names) + [M(1, "push"), LS(), END()],
                           {"regs": F10_REGS}))
            if plabel in F10_BARE:
                bare.append((f"none-{plabel}-{xlabel}", {**knobs, "marker": "none"},
                             [LS()] + xs(names) + [LS(), END()], {"regs": F10_REGS}))
    return (_sweep("F10", marked, waits, parities, marker_kind="push")
            + _sweep("F10", bare, waits, parities, marker_kind="none"))


# F11 take-phase series: PAD LS 90^n X LS END, marker-less, n = 0..5 NOPs between the
# fence and a 2-, 3- or 4-byte register form X (and the F9 miss MOV AW,DW twice), so the
# operand takes of X and of the trailing LS's MOV CL move across every phase of the
# fetch cadence; the model's misses there are the MOV CL immediate taken on the last
# clock of an in-flight fetch with the shift starting on the next fetch's issue clock.
F11_X = [("movr", ["mov_aw_dw"]), ("imm", ["mov_aw_imm"]), ("addi", ["add_dw_imm"]),
         ("movr2", ["mov_aw_dw", "mov_aw_dw"])]
F11_N = {"movr": range(6), "imm": range(6), "addi": range(6), "movr2": range(4)}


def f11(waits=WAITS, parities=PARITIES):
    """Take phase: LS 90^n X LS END, no marker."""
    variants = []
    for label, names in F11_X:
        for n in F11_N[label]:
            body = ["nop"] * n + names
            knobs = {"x": names, "n": n, "bytes": sum(FORMS[b].length for b in body),
                     "marker": "none"}
            variants.append((f"none-n{n}-{label}", knobs, [LS()] + xs(body) + [LS(), END()],
                             {}))
    return _sweep("F11", variants, waits, parities, marker_kind="none")


# F12, the two remaining parts of the eighth fit's finding 4. Two series, each a NOP^n
# lead-in (n NOPs between the fence's M0 and X) so X's operand takes move across the
# fetch cadence, with one thing varied at a time and a same-format control for each.
# Series A, the OUT after a register form: PAD LS M0 90^n X P LS END, the probe P the
# closing instruction. "out": M0 = OUT 20h,AL and P = OUT 40h,AL (an X form, so its I/O
# is the chain's own I/O cycle); X = none (NOP^n alone), MOV AW,DW (8B C2: the F7
# companion), SHL AW,1 (D1 E0: a group ModR/M form, the F3 OUT-marked SHL rows) or
# MOV AW,imm16 (B8 ii ii: OUT-marked exact in F3, the control). "pushout": M0 = PUSH AW,
# P = OUT 40h,AL: separates the M0 OUT's I/O from the closing OUT. "push": M0 = PUSH AW,
# P = the PUSH M1 marker: the PUSH-marked twin, exact today.
# Series B, the 4-byte register form: marker-less PAD LS 90^n X LS END at n = 2, 3 (the
# F11 miss cells, n2 at pE and n3 at pO, and their exact neighbours at the other parity),
# X = ADD DW,imm16 (81 C2 ii ii: opcode + ModR/M + imm16), ADD AW,imm16 in the same
# group format (81 C0 ii ii: the register control), ES: MOV AW,imm16 (26 B8 ii ii: four
# bytes, prefix + opcode + imm16, no ModR/M), SHL AW,4 (C1 E0 04: group opcode + ModR/M +
# imm8, three bytes); and the PUSH-marked PAD LS M0 X M1 LS END for the two 81 forms
# (the F3/F10 case where the instruction after ADD DW,imm16 starts late at pE).
F12_A_X = [("none", []), ("movr", ["mov_aw_dw"]), ("shl1", ["shl1"]), ("imm", ["mov_aw_imm"])]
F12_A_N = range(4)
F12_A_FRAMES = {"out": ("out", ["none", "movr", "shl1", "imm"]),
                "pushout": ("push", ["movr"]), "push": ("push", ["movr"])}
F12_B_X = [("addi", ["add_dw_imm"]), ("addiaw", ["add_aw_imm81"]),
           ("pfximm", ["pfx_mov_aw_imm"]), ("shli", ["shl_imm4"])]
F12_B_N = (2, 3)
F12_B_PUSH = ("addi", "addiaw")
F12_PROBE = "out_imm_al"


def f12(waits=WAITS, parities=PARITIES):
    """Series A: LS M0 90^n X P LS END; series B: LS 90^n X LS END and LS M0 X M1 LS END."""
    by_kind = {"out": [], "push": [], "none": []}
    ax = dict(F12_A_X)
    for frame, (m0, labels) in F12_A_FRAMES.items():
        for label in labels:
            for n in F12_A_N:
                names = ["nop"] * n + ax[label]
                body = [LS(), M(0, m0)] + xs(names + ([] if frame == "push" else [F12_PROBE]))
                body += ([M(1, "push")] if frame == "push" else []) + [LS(), END()]
                knobs = {"series": "a", "frame": frame, "n": n, "x": ax[label], "marker": m0,
                         "probe": "push" if frame == "push" else "out"}
                by_kind[m0].append((f"a-{frame}-n{n}-{label}", knobs, body, {}))
    for label, names in F12_B_X:
        for n in F12_B_N:
            knobs = {"series": "b", "frame": "none", "n": n, "x": names, "marker": "none",
                     "bytes": n + sum(FORMS[b].length for b in names)}
            by_kind["none"].append((f"b-none-n{n}-{label}", knobs,
                                    [LS()] + xs(["nop"] * n + names) + [LS(), END()], {}))
        if label in F12_B_PUSH:
            knobs = {"series": "b", "frame": "push", "n": 0, "x": names, "marker": "push"}
            by_kind["push"].append((f"b-push-n0-{label}", knobs,
                                    [LS(), M(0, "push")] + xs(names) + [M(1, "push"), LS(),
                                                                        END()], {}))
    return [c for kind in ("out", "push", "none")
            for c in _sweep("F12", by_kind[kind], waits, parities, marker_kind=kind)]


# F13, the refresh machine's EU side (WP17), all with refresh on (RFM FCh) unless stated.
# S: marker-less PAD LS X LS END, X = MOV CL,n ; SHL AW,CL, n = 1..31: the shift's end is
# the restart fetch when the second LS takes bytes, so against n it gives the stall per
# refresh and the loop's parity against the count. S0: the same with refresh off for six
# counts (the control). C: the cost frame PAD LS M0 X M1 LS END with the same X for 13
# counts, PUSH and OUT markers (PUSH against OUT right after a short shift across the
# timer phase). U: MULU DW in the cost frame, k = 1, 2, both markers, and marker-less (is
# a non-shift multi-clock instruction stalled). N: NOP^8 marker-less and PUSH-framed (the
# NOP train's small stall). R: the empty marker-less frame PAD LS LS END at every refresh
# interval RFM.RFT (bits 1-0: FCh..FFh) and, at RFT 0, every RFM.RFW (bits 3-2: F0h, F4h,
# F8h; FCh is RFW 3).
F13_S_N = range(1, 32)
F13_S0_N = (1, 2, 4, 8, 16, 31)
F13_C_N = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 31)
F13_U_K = (1, 2)
F13_R_RFT = (0, 1, 2, 3)
F13_R_RFW = (0, 1, 2)
F13_NOPS = 8


def f13(waits=WAITS, parities=PARITIES):
    """Refresh EU series S, S0, C, U, N, R (see the comment above)."""
    by_kind = {"none": [], "push": [], "out": []}
    on, off = {"rfm": RFM_ON}, {"rfm": RFM_OFF}

    def bare(name, knobs, names, extra):
        by_kind["none"].append((name, {**knobs, "marker": "none"},
                                [LS()] + xs(names) + [LS(), END()], extra))

    for n in F13_S_N:
        bare(f"s-shlcl{n}", {"series": "s", "n": n, "x": f"shl_cl{n}"}, [f"shl_cl{n}"], on)
    for n in F13_S0_N:
        bare(f"s0-shlcl{n}", {"series": "s0", "n": n, "x": f"shl_cl{n}"}, [f"shl_cl{n}"], off)
    for kind in COST_MARKERS:
        for n in F13_C_N:
            by_kind[kind].append((f"c-{kind}-shlcl{n}",
                                  {"series": "c", "n": n, "x": f"shl_cl{n}", "marker": kind},
                                  cost_frame(xs([f"shl_cl{n}"]), kind), on))
        for k in F13_U_K:
            by_kind[kind].append((f"u-{kind}-mulu-k{k}",
                                  {"series": "u", "k": k, "x": "mulu_dw", "marker": kind},
                                  cost_frame(xs(["mulu_dw"] * k), kind), on))
    bare("u-none-mulu", {"series": "u", "k": 1, "x": "mulu_dw"}, ["mulu_dw"], on)
    bare(f"n-none-nop{F13_NOPS}", {"series": "n", "k": F13_NOPS, "x": "nop"},
         ["nop"] * F13_NOPS, on)
    by_kind["push"].append((f"n-push-nop{F13_NOPS}",
                            {"series": "n", "k": F13_NOPS, "x": "nop", "marker": "push"},
                            cost_frame(xs(["nop"] * F13_NOPS), "push"), on))
    for rft in F13_R_RFT:
        rfm = (RFM_ON & ~0x03) | rft
        bare(f"r-rfm-f{rft}", {"series": "r", "rft": rft, "rfw": 3, "rfm": rfm}, [],
             {"rfm": rfm})
    for rfw in F13_R_RFW:
        rfm = (RFM_ON & ~0x0C) | (rfw << 2)
        bare(f"r-rfw-{rfw}", {"series": "r", "rft": 0, "rfw": rfw, "rfm": rfm}, [],
             {"rfm": rfm})
    return [c for kind in ("none", "push", "out")
            for c in _sweep("F13", by_kind[kind], waits, parities, marker_kind=kind)]


# F14 (WP19), three series, refresh off, k = 1 unless stated, the cost frame
# PAD LS M0 X^k M1 LS END unless stated.
# T, the TEST/XCH format property: X over a ladder of [BW] forms that varies one format
# property at a time against ADD [BW],AW (01 07): the direction bit (01/03, 39/3B), read
# only against read-modify-write with a register operand (39 vs 01), the group read-only
# form against TEST's own (F7 /0 vs 85), XCH against ADD's write and XCH's register
# (87 07 / 87 0F), store and load (89 / 8B), the immediate RMW (81 /0), the group RMW forms
# (NOT, NEG, INC), the byte forms (84 86 00 38), the direct address (85 06, 87 06). PUSH
# marker at k = 1 and 2, OUT marker at k = 1; plus marker-less LS X LS END for TEST, XCH,
# ADD [BW],AW and CMP [BW],AW (their data cycles are the anchor).
# G, the group memory forms: MULU [BW] (and MULU AW, the register control), DIVU [BW],
# POP [BW], PUSH [BW], SHL [BW],1, SHL [BW],CL (CL = 31 from the fence), INC [BW], NOT [BW],
# PUSH marker at k = 1 and 2, OUT marker at k = 1 (and k = 2 for PUSH/POP/MULU [BW]).
# O, the OUT after a register form: X in {MOV AW,DW, twice, NOP before / after it, XCH
# AW,DW (92), MOV AW,imm16, ADD AW,DW, SHL AW,1, SHL AW,4, NOP, nothing} under the OUT
# marker and its PUSH twin; and marker-less LS X LS END for SHL AW,4, NOP SHL AW,4,
# SHL AW,8 and SHL AW,1.
F14_T_X = [("add_bw_aw", "add_m_aw"), ("add_aw_bw", "add_aw_m"), ("cmp_bw_aw", "cmp_m_aw"),
           ("cmp_aw_bw", "cmp_aw_m"), ("test_bw_aw", "test_m_aw"),
           ("test_bw_imm", "test_m_imm"), ("xch_bw_aw", "xch_m_aw"), ("xch_cw_bw", "xch_cw_m"),
           ("mov_bw_aw", "st_bw"), ("mov_aw_bw", "ld_bw"), ("add_bw_imm", "add_m_imm"),
           ("not_bw", "not_m"), ("neg_bw", "neg_m"), ("inc_bw", "inc_m"),
           ("test_bw_al", "test_m_al"), ("xch_bw_al", "xch_m_al"), ("add_bw_al", "add_m_al"),
           ("cmp_bw_al", "cmp_m_al"), ("test_dir_aw", "test_dir_aw"),
           ("xch_dir_aw", "xch_dir_aw")]
F14_T_FRAMES = (("push", 1), ("push", 2), ("out", 1))
F14_T_BARE = ("test_bw_aw", "xch_bw_aw", "add_bw_aw", "cmp_bw_aw")
F14_G_X = [("mulu_bw", "mulu_m"), ("mulu_aw", "mulu_aw"), ("divu_bw", "divu_m"),
           ("pop_bw", "pop_m"), ("push_bw", "push_m"), ("shl_bw_1", "shl_m1"),
           ("shl_bw_cl", "shl_m_cl"), ("inc_bw", "inc_m"), ("not_bw", "not_m")]
F14_G_FRAMES = (("push", 1), ("push", 2), ("out", 1))
F14_G_OUT_K2 = ("mulu_bw", "pop_bw", "push_bw")
F14_O_X = [("movr", ["mov_aw_dw"]), ("movr2", ["mov_aw_dw", "mov_aw_dw"]),
           ("nop_movr", ["nop", "mov_aw_dw"]), ("movr_nop", ["mov_aw_dw", "nop"]),
           ("xch", ["xch_aw_dw"]), ("imm", ["mov_aw_imm"]), ("addr", ["add_aw_dw"]),
           ("shl1", ["shl1"]), ("shl4", ["shl_imm4"]), ("nop", ["nop"]), ("empty", [])]
F14_O_BARE = [("shl4", ["shl_imm4"]), ("nop_shl4", ["nop", "shl_imm4"]),
              ("shl8", ["shl_imm8"]), ("shl1", ["shl1"])]


def f14(waits=WAITS, parities=PARITIES):
    """Series T (format ladder), G (group memory forms), O (OUT after a register form)."""
    by_kind = {"push": [], "out": [], "none": []}

    def framed(series, kind, label, names, k=1, x=None):
        knobs = {"series": series, "marker": kind, "k": k, "x": x if x is not None else names}
        name = f"{series}-{kind}-{label}" + (f"-k{k}" if k > 1 else "")
        by_kind[kind].append((name, knobs, cost_frame(xs(names * k), kind), {}))

    def bare(series, label, names, x=None):
        knobs = {"series": series, "marker": "none", "k": 1,
                 "x": x if x is not None else names}
        by_kind["none"].append((f"{series}-none-{label}", knobs,
                                [LS()] + xs(names) + [LS(), END()], {}))

    for kind in COST_MARKERS:
        framed("t", kind, "empty", [], 0, None)
    for kind, k in F14_T_FRAMES:
        for label, name in F14_T_X:
            framed("t", kind, label, [name], k, name)
    for label, name in F14_T_X:
        if label in F14_T_BARE:
            bare("t", label, [name], name)
    for kind, k in F14_G_FRAMES:
        for label, name in F14_G_X:
            framed("g", kind, label, [name], k, name)
    for label, name in F14_G_X:
        if label in F14_G_OUT_K2:
            framed("g", "out", label, [name], 2, name)
    for kind in ("out", "push"):
        for label, names in F14_O_X:
            framed("o", kind, label, names, 1 if names else 0)
    for label, names in F14_O_BARE:
        bare("o", label, names)
    return [c for kind in ("push", "out", "none")
            for c in _sweep("F14", by_kind[kind], waits, parities, marker_kind=kind)]


# F15 (WP20), four series, refresh off, the cost frame PAD LS M0 X M1 LS END unless stated.
# A, the AND control and the TEST ladder: PUSH and OUT frames over the 00-3F ALU forms at
# [BW] whose operation the opcode's bits 5:3 name (AND 21/23, OR 09, XOR 33, SUB 29: TEST's
# operation with a write and with a register destination, and three other operations),
# the group immediate forms AND [BW],imm16 (81 /4) and CMP [BW],imm16 (81 /7) against TEST
# [BW],imm16 (F7 /0), the direct forms of TEST, AND and CMP, the sign-extended imm8 forms
# (83 /0, 83 /4: the immediate's width), and TEST AL,imm8 / TEST AW,imm16 (A8, A9) as
# register-form controls; marker-less LS X LS END for TEST 85, AND 21 and TEST imm.
# P, POP [BW]: POP [BW] and PUSH [BW] at k = 1, 2, 3, POP [BW] in three other address
# modes, POP AW / POP CW at k = 1, 2, and POP [BW] beside PUSH [BW] and NOP, each under the
# PUSH frame, the OUT frame and marker-less.
# K, the k = 2 second instance: PUSH frame over X X, X NOP X, X INC [BW], INC [BW] X and
# X MOV AW,DW for X in MULU [BW], SHL [BW],1, PUSH [BW], NOT [BW].
# O, the OUT-frame remainder: the OUT frame and its PUSH twin over MOV AW,DW pairs, the
# register shifts and MULU AW with NOPs around them; marker-less shifts by 1, 4, 8, 16
# with NOPs and MOV AW,DW before or after.
F15_A_X = [("and_bw_aw", "and_m_aw"), ("and_aw_bw", "and_aw_m"), ("and_bw_imm", "and_m_imm"),
           ("test_bw_aw", "test_m_aw"), ("test_bw_imm", "test_m_imm"),
           ("cmp_bw_imm", "cmp_m_imm"), ("or_bw_aw", "or_m_aw"), ("xor_aw_bw", "xor_aw_m"),
           ("sub_bw_aw", "sub_m_aw"), ("test_dir_aw", "test_dir_aw"),
           ("and_dir_aw", "and_dir_aw"), ("cmp_dir_aw", "cmp_dir_aw"),
           ("test_al_imm", "test_al_imm"), ("test_aw_imm", "test_aw_imm"),
           ("add_bw_imm8", "add_m_imm8"), ("and_bw_imm8", "and_m_imm8")]
F15_A_BARE = ("test_bw_aw", "and_bw_aw", "test_bw_imm")
F15_FRAMES = ("push", "out", "none")
F15_P_K = [("pop_bw", "pop_m", (1, 2, 3)), ("push_bw", "push_m", (1, 2, 3)),
           ("pop_dir", "pop_m_dir", (1,)), ("pop_bw_d8", "pop_m_d8", (1,)),
           ("pop_ix", "pop_m_ix", (1,)), ("pop_aw", "pop_aw", (1, 2)),
           ("pop_cw", "pop_cw", (1, 2))]
F15_P_PAIRS = [("push_pop", ["push_m", "pop_m"]), ("pop_push", ["pop_m", "push_m"]),
               ("nop_pop", ["nop", "pop_m"]), ("pop_nop", ["pop_m", "nop"])]
F15_K_X = [("mulu", "mulu_m"), ("shl1", "shl_m1"), ("push", "push_m"), ("not", "not_m")]
F15_K_SHAPES = [("x_x", lambda x: [x, x]), ("x_nop_x", lambda x: [x, "nop", x]),
                ("x_inc", lambda x: [x, "inc_m"]), ("inc_x", lambda x: ["inc_m", x]),
                ("x_movr", lambda x: [x, "mov_aw_dw"])]
F15_O_X = [("movr2", ["mov_aw_dw", "mov_aw_dw"]), ("movr_nop", ["mov_aw_dw", "nop"]),
           ("nop_movr_nop", ["nop", "mov_aw_dw", "nop"]), ("movr_ld", ["mov_aw_dw", "ld_bw"]),
           ("movr_st", ["mov_aw_dw", "st_bw"]), ("movr_add", ["mov_aw_dw", "add_m_aw"]),
           ("shl1", ["shl1"]), ("nop_shl1", ["nop", "shl1"]), ("shl1_nop", ["shl1", "nop"]),
           ("mulu_aw", ["mulu_aw"]), ("nop_mulu_aw", ["nop", "mulu_aw"]),
           ("shl4", ["shl_imm4"])]
F15_O_BARE = [("nop_shl4", ["nop", "shl_imm4"]), ("nop2_shl4", ["nop", "nop", "shl_imm4"]),
              ("shl4_nop", ["shl_imm4", "nop"]), ("movr_shl4", ["mov_aw_dw", "shl_imm4"]),
              ("shl1", ["shl1"]), ("nop_shl1", ["nop", "shl1"]), ("shl8", ["shl_imm8"]),
              ("shl16", ["shl_imm16"])]


def f15(waits=WAITS, parities=PARITIES):
    """Series A (AND control), P (POP [BW]), K (k = 2 second instance), O (OUT frame)."""
    by_kind = {"push": [], "out": [], "none": []}

    def add(series, kind, label, names, k=1):
        knobs = {"series": series, "marker": kind, "k": k, "x": list(names)}
        name = f"{series}-{kind}-{label}" + (f"-k{k}" if k > 1 else "")
        body = (cost_frame(xs(names), kind) if kind != "none"
                else [LS()] + xs(names) + [LS(), END()])
        by_kind[kind].append((name, knobs, body, {}))

    for kind in COST_MARKERS:
        add("a", kind, "empty", [], 0)
    for kind in COST_MARKERS:
        for label, name in F15_A_X:
            add("a", kind, label, [name])
    for label, name in F15_A_X:
        if label in F15_A_BARE:
            add("a", "none", label, [name])
    for kind in F15_FRAMES:
        for label, name, ks in F15_P_K:
            for k in ks:
                add("p", kind, label, [name] * k, k)
        for label, names in F15_P_PAIRS:
            add("p", kind, label, names)
    for shape, make in F15_K_SHAPES:
        for label, name in F15_K_X:
            add("k", "push", f"{label}-{shape}", make(name))
    for kind in ("out", "push"):
        for label, names in F15_O_X:
            add("o", kind, label, names)
    for label, names in F15_O_BARE:
        add("o", "none", label, names)
    return [c for kind in ("push", "out", "none")
            for c in _sweep("F15", by_kind[kind], waits, parities, marker_kind=kind)]


# F16 (WP21), four series, refresh off, the cost frame PAD LS M0 X M1 LS END unless stated.
# R, the reg-field ladder: PUSH frame over X X and INC [BW] X for every reg value of the D1
# shift group, the F7 group and FF on [BW], and D0 /4, F6 /4 (byte) as width controls; X
# alone (k = 1) for the forms not in the corpus before; the empty frame.
# P, POP's held fetch: NOP^n POP [BW] (and POP AW, the control) under the PUSH frame
# (n = 0..3, also POP [BW+10h] and POP [0C00h]), the OUT frame (n = 0..2) and marker-less
# (n = 0..3).
# L, the long register forms after the OUT marker: the OUT frame and its PUSH twin over
# SHL AW,1, SHL AW,CL with MOV CL,n before M0 (n = 1, 2, 4, 8: the count in CL, no count
# byte), SHL AW,n (C1, n = 1, 2, 4, 8), MULU AW, MULU DW, DIVU IX (IX = 9090h; DIVU DW
# always traps), MULU AW with NOPs before or after; the empty OUT frame.
# S, the marker-less shift's count byte: LS NOP^n X LS END with X = SHL AW,m (C1 E0 mm),
# MOV CL,m ; SHL AW,CL, and MOV CL,m NOP^n SHL AW,CL (CL set before the NOPs), n = 0..3,
# m = 1, 2, 4, 8, 16; NOP^n MOV CL,4 alone.
F16_R_X = [("rol", "rol_m1"), ("ror", "ror_m1"), ("rcl", "rcl_m1"), ("rcr", "rcr_m1"),
           ("shl1", "shl_m1"), ("shr", "shr_m1"), ("sar", "sar_m1"),
           ("test_imm", "test_m_imm"), ("not", "not_m"), ("neg", "neg_m"), ("mulu", "mulu_m"),
           ("mul", "mul_m"), ("divu", "divu_m"), ("div", "div_m"),
           ("inc", "inc_m"), ("dec", "dec_m"), ("push", "push_m"),
           ("shlb", "shlb_m1"), ("mulub", "mulub_m")]
F16_R_NEW = ("rol", "ror", "rcl", "rcr", "shr", "sar", "mul", "div", "dec", "shlb", "mulub")
F16_P_PUSH = [("pop_bw", "pop_m"), ("pop_aw", "pop_aw"), ("pop_bw_d8", "pop_m_d8"),
              ("pop_dir", "pop_m_dir")]
F16_P_N = {"push": (0, 1, 2, 3), "out": (0, 1, 2), "none": (0, 1, 2, 3)}
F16_P_FRAME_X = {"push": F16_P_PUSH, "out": F16_P_PUSH[:2], "none": F16_P_PUSH[:2]}
F16_CL = {1: "mov_cl1", 2: "mov_cl2", 4: "mov_cl_imm", 8: "mov_cl8", 16: "mov_cl16"}
F16_L_N = (1, 2, 4, 8)
F16_L_X = ([("shl1", [], ["shl1"])]
           + [(f"shlcl{n}", [F16_CL[n]], ["shl_aw_cl"]) for n in F16_L_N]
           + [(f"shli{n}", [], [f"shl_imm{n}"]) for n in F16_L_N]
           + [("mulu_aw", [], ["mulu_aw"]), ("mulu_dw", [], ["mulu_dw"]),
              ("divu_ix", [], ["divu_ix"]), ("nop_mulu_aw", [], ["nop", "mulu_aw"]),
              ("nop2_mulu_aw", [], ["nop", "nop", "mulu_aw"]),
              ("mulu_aw_nop", [], ["mulu_aw", "nop"])])
F16_S_N = (0, 1, 2, 3)
F16_S_M = (1, 2, 4, 8, 16)


def f16(waits=WAITS, parities=PARITIES):
    """Series R (reg-field ladder), P (POP's held fetch), L (long register forms after the
    OUT marker), S (the marker-less shift's count byte)."""
    by_kind = {"push": [], "out": [], "none": []}

    def add(series, kind, label, names, k=1, pre=()):
        knobs = {"series": series, "marker": kind, "k": k, "x": list(pre) + list(names)}
        if pre:
            knobs["pre"] = list(pre)
        name = f"{series}-{kind}-{label}"
        if kind == "none":
            body = [LS()] + xs(names) + [LS(), END()]
        else:
            body = ([LS()] + xs(pre) + [M(0, kind)]
                    + [X(n, len(pre) + i) for i, n in enumerate(names)]
                    + [M(1, kind), LS(), END()])
        by_kind[kind].append((name, knobs, body, {}))

    add("r", "push", "empty", [], 0)
    for label, name in F16_R_X:
        add("r", "push", f"{label}-x_x", [name, name], 2)
        if name != "inc_m":
            add("r", "push", f"{label}-inc_x", ["inc_m", name], 2)
        if label in F16_R_NEW:
            add("r", "push", label, [name])
    for kind in ("push", "out", "none"):
        for label, name in F16_P_FRAME_X[kind]:
            for n in F16_P_N[kind]:
                add("p", kind, f"n{n}-{label}", ["nop"] * n + [name])
    add("l", "out", "empty", [], 0)
    for kind in ("out", "push"):
        for label, pre, names in F16_L_X:
            add("l", kind, label, names, pre=pre)
    for n in F16_S_N:
        for m in F16_S_M:
            add("s", "none", f"n{n}-shli{m}", ["nop"] * n + [f"shl_imm{m}"])
            add("s", "none", f"n{n}-shlcl{m}", ["nop"] * n + [F16_CL[m], "shl_aw_cl"])
            if n:
                add("s", "none", f"cl{m}-n{n}-shlcl", [F16_CL[m]] + ["nop"] * n + ["shl_aw_cl"])
        add("s", "none", f"n{n}-movcl", ["nop"] * n + ["mov_cl_imm"])
    return [c for kind in ("push", "out", "none")
            for c in _sweep("F16", by_kind[kind], waits, parities, marker_kind=kind)]


# F17 (WP23), the refresh fill phase made observable. The prelude leaves refresh off (RFM
# ECh) as in every refresh-off family, so the first LS and its fill are the refresh-off
# model's; the chain turns refresh on itself, with RFMON = DS1: MOV byte [0FFE1h],imm8
# (forms.rfm_*, 6 bytes, an on-chip store with no bus cycle) right after the first LS.
# S: marker-less PAD LS RFMON NOP^n X LS END, n = 0..3 (X moves a clock at a time against
# the refresh grid), RFMON FCh; E: the same with RFMON ECh (refresh stays off: the store's
# own cost and the control), n = 0..3 for four X and n = 0 for the rest; D: RFMON FDh
# (RFT 1, a 32-clock interval) for four X, n = 0..3 (the interval against the phase, and
# whether the timer restarts on the write); C: the PUSH cost frame PAD LS RFMON M0 X M1 LS
# END with RFMON FCh; P: the S chain with refresh on from the prelude (RFM FCh, as F8 and
# F13) and RFMON FCh, n = 0, 1 (does a write while refresh is on move the phase). W:
# PAD LS NOP^n RFMON LS END, n = 0..7, RFMON FCh and FDh: the NOPs move the write itself
# against t_fill (4 clocks each from a full queue), so a timer that restarts on the write
# moves its first refresh with n and a free-running one keeps its grid against t_fill
# (the S NOPs after RFMON cannot tell the two apart: the write does not move with them);
# and with RFMON ECh, the refresh-off control of the same shapes (added after the first
# acquisition: the W NOPs before the store are not in E).
F17_N = (0, 1, 2, 3)
F17_W_N = range(8)
F17_X = [("empty", []), ("shlcl1", ["shl_cl1"]), ("shlcl2", ["shl_cl2"]),
         ("shlcl4", ["shl_cl4"]), ("shlcl8", ["shl_cl8"]), ("shlcl16", ["shl_cl16"]),
         ("shlcl31", ["shl_cl31"]), ("mulu", ["mulu_dw"]), ("nop8", ["nop"] * 8),
         ("ld", ["ld_bw"]), ("st", ["st_bw"]), ("rmw", ["add_m_aw"]), ("out", ["out_imm_al"])]
F17_E_ALL_N = ("empty", "shlcl4", "shlcl31", "nop8")
F17_D_X = ("empty", "shlcl16", "shlcl31", "mulu")
F17_C_X = ("empty", "shlcl4", "shlcl16", "shlcl31", "mulu", "nop8")
F17_P_X = ("empty", "shlcl8", "shlcl31", "mulu", "nop8")
F17_P_N = (0, 1)


def f17(waits=WAITS, parities=PARITIES):
    """Series S, E, D, C, P (see the comment above)."""
    by_kind = {"none": [], "push": []}
    xmap = dict(F17_X)

    def bare(series, rfmw, n, label, names, rfm=RFM_OFF):
        knobs = {"series": series, "marker": "none", "n": n, "x": names, "rfmon": rfmw,
                 "rfm": rfm, "refresh_on": True}
        body = ([LS(), X(f"rfm_{rfmw:02x}", 0)] + [X("nop", 1 + i) for i in range(n)]
                + [X(nm, 1 + n + i) for i, nm in enumerate(names)] + [LS(), END()])
        by_kind["none"].append((f"{series}-n{n}-{label}", knobs, body, {"rfm": rfm}))

    for label, names in F17_X:
        for n in F17_N:
            bare("s", 0xFC, n, label, names)
    for label, names in F17_X:
        for n in (F17_N if label in F17_E_ALL_N else (0,)):
            bare("e", 0xEC, n, label, names)
    for label in F17_D_X:
        for n in F17_N:
            bare("d", 0xFD, n, label, xmap[label])
    for label in F17_P_X:
        for n in F17_P_N:
            bare("p", 0xFC, n, label, xmap[label], rfm=RFM_ON)
    for rfmw in (0xFC, 0xFD, 0xEC):
        for n in F17_W_N:
            knobs = {"series": "w", "marker": "none", "n": n, "x": [], "rfmon": rfmw,
                     "rfm": RFM_OFF, "refresh_on": True}
            body = ([LS()] + [X("nop", i) for i in range(n)] + [X(f"rfm_{rfmw:02x}", n)]
                    + [LS(), END()])
            by_kind["none"].append((f"w-{rfmw:02x}-n{n}", knobs, body, {}))
    for label in F17_C_X:
        names = xmap[label]
        body = ([LS(), X("rfm_fc", 0), M(0, "push")]
                + [X(nm, 1 + i) for i, nm in enumerate(names)] + [M(1, "push"), LS(), END()])
        by_kind["push"].append((f"c-push-{label}", {"series": "c", "marker": "push", "n": 0,
                                                    "x": names, "rfmon": 0xFC, "rfm": RFM_OFF,
                                                    "refresh_on": True}, body, {}))
    return [c for kind in ("none", "push")
            for c in _sweep("F17", by_kind[kind], waits, parities, marker_kind=kind)]


# F18 (WP24), finding 8 (a) and (b). A: the first LS's start under a refresh-on prelude made
# observable: the prelude ends with a marker (Chain.prelude_marker: PUSH AW, its stack
# write at 0EFEh, or OUT 20h,AL) directly before the PAD / first LS, and the chain is the
# marker-less PAD LS X LS END, prelude RFM ECh (the control: the marker's cost with refresh
# off), FCh and FDh (RFT 1). AC: the ECh prelude with the marker and RFMON FCh after the
# first LS (PAD LS RFMON LS END): the counter at clock 0 read off with the marker in place.
# B: the exec-boundary ladder, chain-enabled refresh as F17 S (prelude ECh): PAD LS
# RFMON(FCh) [STEP] NOP^n X LS END, n = 0..7: the NOPs move X 4 clocks a step against the
# first request after RFEN (n >= 4: the first falls in the NOPs and the second lands in
# X), STEP (MOV CL,4 or MOV AW,imm16... see F18_B_STEPS) the odd and 2-mod-4 clocks
# between; with RFMON FDh (RFT 1, the 32-clock grid) for two X.
F18_A_X = [("empty", []), ("shlcl4", ["shl_cl4"]), ("shlcl16", ["shl_cl16"]),
           ("shlcl31", ["shl_cl31"]), ("mulu", ["mulu_dw"]), ("nop8", ["nop"] * 8),
           ("ld", ["ld_bw"]), ("st", ["st_bw"])]
F18_A_RFM = (0xEC, 0xFC, 0xFD)
F18_MARKERS = ("push", "out")
F18_B_X = [("shlcl4", ["shl_cl4"]), ("shlcl16", ["shl_cl16"]), ("shli4", ["shl_imm4"]),
           ("shl1", ["shl1"]), ("mulu", ["mulu_dw"]), ("divu", ["divu_ix"]),
           ("shlmcl", ["shl_m_cl"])]
F18_B_N = range(8)
F18_B_STEPS = {"": [], "p": ["pfx_nop"]}   # ES: NOP, 7 clocks at 0 waits: no register written
F18_B_FD_X = ("shlcl4", "mulu")


def f18(waits=WAITS, parities=PARITIES):
    """Series A, AC, B, BD (see the comment above)."""
    out = []
    for marker in F18_MARKERS:
        variants = []
        for rfm in F18_A_RFM:
            for label, names in F18_A_X:
                knobs = {"series": "a", "marker": "none", "pre_marker": marker, "rfm": rfm,
                         "x": names, "n": 0, "refresh_on": rfm != RFM_OFF}
                body = [LS()] + xs(names) + [LS(), END()]
                variants.append((f"a-{marker}-{rfm:02x}-{label}", knobs, body, {"rfm": rfm}))
        knobs = {"series": "ac", "marker": "none", "pre_marker": marker, "rfm": RFM_OFF,
                 "x": [], "n": 0, "rfmon": 0xFC, "refresh_on": True}
        variants.append((f"ac-{marker}-fc", knobs, [LS(), X("rfm_fc", 0), LS(), END()], {}))
        out += _sweep("F18", variants, waits, parities, marker_kind="none",
                      prelude_marker=marker)
    xmap = dict(F18_B_X)
    variants = []
    for rfmw, labels in ((0xFC, [l for l, _ in F18_B_X]), (0xFD, F18_B_FD_X)):
        for label in labels:
            for step, pre in F18_B_STEPS.items():
                for n in F18_B_N:
                    names = pre + ["nop"] * n + xmap[label]
                    knobs = {"series": "b" if rfmw == 0xFC else "bd", "marker": "none",
                             "n": n, "step": step, "x": xmap[label], "rfmon": rfmw,
                             "rfm": RFM_OFF, "refresh_on": True}
                    body = ([LS(), X(f"rfm_{rfmw:02x}", 0)]
                            + [X(nm, 1 + i) for i, nm in enumerate(names)] + [LS(), END()])
                    s = f"-{step}" if step else ""
                    variants.append((f"{knobs['series']}{s}-n{n}-{label}", knobs, body, {}))
    out += _sweep("F18", variants, waits, parities, marker_kind="none")
    return out


# F19 (WP25), findings 1 and 3 of the fifteenth fit, refresh off. Two series.
# I, the immediate memory forms: PAD LS M0 L X^k M1 LS END (PUSH and OUT frames) and the
# marker-less PAD LS L X LS END, X over MOV [BW],imm16 (C7 07), MOV byte [BW],imm8 (C6 07:
# one immediate byte), MOV [BW+10h],imm16 (C7 47 d8), MOV [BW+200h],imm16 (C7 87 d16),
# CMP [BW],imm16 (81 /7: reads, no write), ADD [BW],imm16 (81 /0: read-modify-write),
# CMP [BW],imm8 (83 /7: one sign-extended immediate byte); the lead-in L in {none, NOP,
# NOP NOP, NOP NOP NOP, ES: NOP}: each NOP moves X one byte (its alignment, so whether the
# immediate straddles two words) and 4 clocks against the marker's cycle and the fetch
# cadence; ES: NOP keeps n = 0's alignment at 7 clocks (n = 2's at 8), so it separates the
# clock from the alignment. k = 1 at every L, k = 2 at L = none in the frames; marker-less
# at L in {none, NOP, ES: NOP}.
# D, the DW I/O forms: PAD LS M0 P [NOP] Y M1 LS END (PUSH and OUT) and the marker-less
# PAD LS P Y LS END, Y over OUT DW,AL (EE), OUT DW,AW (EF, the catalog's out_dw_al), IN
# AL,DW (EC), IN AW,DW (ED); P a register form of 1 to 4 bytes: none, NOP, XCH AW,DW,
# MOV DW,AW, MOV AW,DW, MOV CW,AW (8B: the register written; the port is DW), MOV
# AW,imm16, ADD DW,imm16 (81 C2 0000h: DW stays the port), SHL AW,1 (D1 E0), MOV CL,imm8;
# with one NOP between P and Y for the 2- to 4-byte P of the F10 misses; the byte forms
# EE and EC over every P, the word forms over none, NOP, MOV AW,DW, ADD DW,imm16; and the
# DW form after a DW form (Y Y) and after a port-form OUT 40h,AL (the OUT frame's own
# case: M0 then Y). AW = DW = 0040h as in F10 (the shift clears AW, so MOV DW,AW and XCH
# AW,DW move the port to 0; the normaliser tracks it).
F19_I_X = [("stimm", "st_imm_bw"), ("stimm8", "st_imm8_bw"), ("stimmd8", "st_imm_bw_d8"),
           ("stimmd16", "st_imm_bw_d16"), ("cmpimm", "cmp_m_imm"), ("addimm", "add_m_imm"),
           ("cmpimm8", "cmp_m_imm8")]
F19_I_LEADS = {"l0": [], "n1": ["nop"], "n2": ["nop"] * 2, "n3": ["nop"] * 3, "es": ["pfx_nop"]}
F19_I_BARE_LEADS = ("l0", "n1", "es")
F19_D_Y = [("outb", "out_dw_b"), ("outw", "out_dw_al"), ("inb", "in_al_dw"), ("inw", "in_aw_dw")]
F19_D_P = [("none", []), ("nop", ["nop"]), ("xch", ["xch_aw_dw"]), ("movdwaw", ["mov_dw_aw"]),
           ("movawdw", ["mov_aw_dw"]), ("movcwaw", ["mov_cw_aw"]), ("movawi", ["mov_aw_imm"]),
           ("adddwi", ["add_dw_imm0"]), ("shl1", ["shl1"]), ("movcl", ["mov_cl_imm"])]
F19_D_SPACED = ("movawdw", "movawi", "adddwi", "shl1")      # P NOP Y as well
F19_D_WORD_P = ("none", "nop", "movawdw", "adddwi")          # the EF / ED forms' P
F19_D_PAIRS = ("outb", "outw", "inb")                        # Y Y (framed)
F19_D_PORT = ("outb", "inb")                                 # OUT 40h,AL ; Y (PUSH, none)
F19_REGS = {"AW": 0x0040}


def f19(waits=WAITS, parities=PARITIES):
    """Series I and D (see the comment above)."""
    by_kind = {"push": [], "out": [], "none": []}

    def add(series, kind, label, names, knobs):
        knobs = {"series": series, "marker": kind, **knobs}
        if kind == "none":
            body = [LS()] + xs(names) + [LS(), END()]
        else:
            body = [LS(), M(0, kind)] + xs(names) + [M(1, kind), LS(), END()]
        extra = {"regs": F19_REGS} if series == "d" else {}
        by_kind[kind].append((f"{series}-{kind}-{label}", knobs, body, extra))

    for kind in ("push", "out", "none"):
        for xlabel, x in F19_I_X:
            for lead, pre in F19_I_LEADS.items():
                if kind == "none" and lead not in F19_I_BARE_LEADS:
                    continue
                ks = (1, 2) if kind != "none" and lead == "l0" else (1,)
                for k in ks:
                    add("i", kind, f"{lead}-{xlabel}" + (f"-k{k}" if k > 1 else ""),
                        pre + [x] * k, {"x": x, "k": k, "lead": lead, "n": len(pre)})
    ymap, pmap = dict(F19_D_Y), dict(F19_D_P)
    for kind in ("push", "out", "none"):
        for ylabel, y in F19_D_Y:
            word = ylabel in ("outw", "inw")
            if kind == "none" and word:
                continue
            for plabel, p in F19_D_P:
                if word and plabel not in F19_D_WORD_P:
                    continue
                spacings = (False, True) if kind != "none" and plabel in F19_D_SPACED else (
                    False,)
                for spaced in spacings:
                    names = p + (["nop"] if spaced else []) + [y]
                    add("d", kind, f"{plabel}{'_nop' if spaced else ''}-{ylabel}", names,
                        {"x": y, "p": p, "spaced": spaced, "k": 1,
                         "bytes": sum(FORMS[n].length for n in p)})
        if kind != "none":
            for ylabel in F19_D_PAIRS:
                add("d", kind, f"pair-{ylabel}", [ymap[ylabel]] * 2,
                    {"x": ymap[ylabel], "p": [ymap[ylabel]], "spaced": False, "k": 2})
        if kind != "out":
            for ylabel in F19_D_PORT:
                add("d", kind, f"outimm-{ylabel}", ["out_imm_al", ymap[ylabel]],
                    {"x": ymap[ylabel], "p": ["out_imm_al"], "spaced": False, "k": 1})
    return [c for kind in ("push", "out", "none")
            for c in _sweep("F19", by_kind[kind], waits, parities, marker_kind=kind)]


# F20 (WP26: finding 4, the register form before a load, a store, an RMW, a DW I/O form, a
# port-form I/O or another register form). Series R: a lead-in (none, NOP^1..2, ES: NOP: each
# NOP moves P one byte and 4 clocks, ES: NOP keeps l0's alignment at 7 clocks), a register
# form P of 1-4 bytes whose last byte is the opcode, a ModR/M byte or an immediate (none,
# NOP, XCH AW,DW, MOV AW,DW, MOV DW,AW, MOV AW,imm16, ADD AW,imm16 (05), ADD DW,0 (81 C2: DW
# stays the port), ES: NOP, ES: MOV AW,DW, ES: MOV AW,imm16), then X; the OUT frame with
# every X and lead, the PUSH frame (l0, n1, ES) and marker-less (l0, n1) without the RMW.
# Series N, the F6 drain frame M0 D^n P X M1 (D = F6's MOV AW/DW,imm16 drainers; at n = 2
# the second sets DW, so a DW form goes to port 5678h), OUT n = 1, 2 and PUSH n = 1. AW = DW
# = 0040h throughout (the shift clears AW before the body, so MOV DW,AW sets the port to 0).
F20_P = [("none", []), ("nop", ["nop"]), ("xch", ["xch_aw_dw"]), ("movawdw", ["mov_aw_dw"]),
         ("movdwaw", ["mov_dw_aw"]), ("movawi", ["mov_aw_imm"]), ("addawi", ["add_aw_imm"]),
         ("adddwi", ["add_dw_imm0"]), ("pfxnop", ["pfx_nop"]), ("pfxmovr", ["pfx_mov_aw_dw"]),
         ("pfxmovi", ["pfx_mov_aw_imm"])]
F20_X = [("ld", "ld_bw"), ("st", "st_bw"), ("rmw", "add_m_aw"), ("outdw", "out_dw_b"),
         ("outimm", "out_imm_al"), ("movr", "mov_aw_dw")]
F20_LEADS = {"l0": [], "n1": ["nop"], "n2": ["nop"] * 2, "es": ["pfx_nop"]}
F20_R_FRAMES = {"out": (("l0", "n1", "n2", "es"), ("ld", "st", "rmw", "outdw", "outimm", "movr")),
                "push": (("l0", "n1", "es"), ("ld", "st", "outdw", "outimm", "movr")),
                "none": (("l0", "n1"), ("ld", "st", "outdw", "outimm", "movr"))}
F20_N_P = ("none", "nop", "movawdw", "movawi", "adddwi")
F20_N_X = ("ld", "st", "outdw", "movr")
F20_N_FRAMES = {"out": (1, 2), "push": (1,)}
F20_REGS = {"AW": 0x0040}


def _f20_last(names) -> str:
    """The register form's last byte: op (one byte), modrm or imm (a format property)."""
    if not names:
        return "-"
    f = FORMS[names[-1]]
    code = f.code[1:] if f.cls == "prefix" else f.code
    if len(code) == 1:
        return "op"
    return "modrm" if code[0] in (0x8B, 0x81) and len(code) == 2 else "imm"


def f20(waits=WAITS, parities=PARITIES):
    """Series R and N (see the comment above)."""
    by_kind = {"push": [], "out": [], "none": []}
    pmap, xmap = dict(F20_P), dict(F20_X)

    def add(label, kind, names, knobs):
        knobs = {"marker": kind, **knobs}
        mid = [Instr(0, i.code, i.form, i.role, i.marker_id, i.index) for i in names]
        if kind == "none":
            body = [LS()] + mid + [LS(), END()]
        else:
            body = [LS(), M(0, kind)] + mid + [M(1, kind), LS(), END()]
        by_kind[kind].append((label, knobs, body, {"regs": F20_REGS}))

    for kind, (leads, xlabels) in F20_R_FRAMES.items():
        for lead in leads:
            for plabel, p in F20_P:
                for xlabel in xlabels:
                    names = F20_LEADS[lead] + p + [xmap[xlabel]]
                    add(f"r-{kind}-{lead}-{plabel}-{xlabel}", kind, xs(names),
                        {"series": "r", "lead": lead, "n": len(F20_LEADS[lead]), "p": plabel,
                         "x": xlabel, "bytes": sum(FORMS[n].length for n in p),
                         "last": _f20_last(p)})
    for kind, ns in F20_N_FRAMES.items():
        for n in ns:
            for plabel in F20_N_P:
                p = pmap[plabel]
                for xlabel in F20_N_X:
                    body = [D(i) for i in range(n)] + xs(p + [xmap[xlabel]])
                    add(f"n-{kind}-d{n}-{plabel}-{xlabel}", kind, body,
                        {"series": "n", "drain": n, "p": plabel, "x": xlabel,
                         "bytes": sum(FORMS[q].length for q in p), "last": _f20_last(p)})
    return [c for kind in ("push", "out", "none")
            for c in _sweep("F20", by_kind[kind], waits, parities, marker_kind=kind)]


# F21 (WP27: the effective-address path), refresh off. PAD LS M0 L X^k M1 LS END (PUSH and
# OUT frames) and the marker-less PAD LS L X LS END. X: five consumers of a ModR/M memory
# operand (MOV AW,r/m 8B, MOV r/m,AW 89, MOV r/m,imm16 C7 /0, ADD r/m,AW 01, POP r/m 8F /0)
# over seven modes (forms.F21_MODES: [BW], [BW+10h], [BW+200h], [BW+IX], [BW+IX+10h],
# [BW+IX+200h], [0C00h]): the mode class (base, base+index, direct), the displacement's
# width (none, d8, d16) and, with the lead-in, its alignment: L in {none, NOP, NOP NOP,
# NOP NOP NOP, ES: NOP} moves X one byte (whether the displacement's first byte shares the
# ModR/M byte's word, and whether a d16 straddles two words) and 4 clocks against the
# marker and the fetch cadence; ES: NOP keeps none's alignment at 7 clocks. Every lead in
# the frames, none/NOP/NOP NOP/ES: NOP marker-less. k = 2 with no lead-in for the displaced
# modes in both frames. Controls: the load in the index-alone ([IX+10h], [IX+200h]) and the
# other base+index ([BP+IY+10h], [BP+IY+200h]) modes at every lead and frame.
F21_LEADS = {"l0": [], "n1": ["nop"], "n2": ["nop"] * 2, "n3": ["nop"] * 3, "es": ["pfx_nop"]}
F21_FRAME_LEADS = {"push": ("l0", "n1", "n2", "n3", "es"), "out": ("l0", "n1", "n2", "n3", "es"),
                   "none": ("l0", "n1", "n2", "es")}
F21_K2_MODES = ("bw_d8", "bw_d16", "bw_ix_d8", "bw_ix_d16", "dir")


def f21(waits=WAITS, parities=PARITIES):
    """The EA ladder (see the comment above)."""
    from .forms import F21_CONSUMERS, F21_CONTROL_MODES, F21_FORM, F21_MODES, MODE
    by_kind = {"push": [], "out": [], "none": []}

    def add(kind, lead, cons, mode, k):
        x = F21_FORM[(cons, mode)]
        pre = F21_LEADS[lead]
        names = pre + [x] * k
        if kind == "none":
            body = [LS()] + xs(names) + [LS(), END()]
        else:
            body = [LS(), M(0, kind)] + xs(names) + [M(1, kind), LS(), END()]
        m = MODE[mode]
        knobs = {"marker": kind, "lead": lead, "n": len(pre), "cons": cons, "mode": mode,
                 "mode_class": m.mode_class, "disp": len(m.disp), "x": x, "k": k}
        by_kind[kind].append((f"{kind}-{lead}-{cons}-{mode}" + (f"-k{k}" if k > 1 else ""),
                              knobs, body, {}))

    for kind, leads in F21_FRAME_LEADS.items():
        for lead in leads:
            for cons in F21_CONSUMERS:
                for mode in F21_MODES:
                    add(kind, lead, cons, mode, 1)
            for mode in F21_CONTROL_MODES:
                add(kind, lead, "ld", mode, 1)
        if kind != "none":
            for cons in F21_CONSUMERS:
                for mode in F21_K2_MODES:
                    add(kind, "l0", cons, mode, 2)
    return [c for kind in ("push", "out", "none")
            for c in _sweep("F21", by_kind[kind], waits, parities, marker_kind=kind)]


# F22 (the immediate forms' post against the fetch run), refresh off, 0 and 1 waits only.
# PAD LS M0 L X^k M1 LS END (PUSH and OUT frames) and the marker-less PAD LS L X^k LS END,
# k in {1, 2}. X: one immediate memory form (forms.F22_FORM): the immediate RMW ADD r/m,imm16
# at [BW+200h], [BW+10h], [BW] and [0C00h], ADD [BW+200h],imm8, the left-out write CMP
# [BW+200h],imm16 and TEST [BW+200h],imm16, and the immediate store MOV r/m,imm16 in the
# four modes. The lead-in L (F21's: none, NOP, NOP NOP, NOP NOP NOP, ES: NOP) moves X's start
# one byte and 4 clocks against the fetch cadence (ES: NOP keeps none's alignment at 7
# clocks), so the data request is posted at every distance from a fetch run's delivery
# clock: the store's write and the RMW's read in the state of ADD [BW+200h],imm16's idle
# clock at 0 waits (posted 2 clocks before a run's delivery-clock fetch that goes first),
# the 1-wait twins the controls. Every lead, form and k in all three frames (marker-less
# k = 2 is in no other family). Run ids F22-<frame>-<lead>-<form>[-k2]-p?-w?.
F22_LEADS = F21_LEADS
F22_FRAMES = ("push", "out", "none")
F22_KS = (1, 2)
F22_WAITS = (0, 1)


def f22(waits=WAITS, parities=PARITIES):
    """The immediate forms' post ladder (see the comment above); waits 2 is not generated."""
    from .forms import F22_FORM, F22_FORMS, MODE
    waits = tuple(w for w in waits if w in F22_WAITS)
    by_kind = {kind: [] for kind in F22_FRAMES}
    for kind in F22_FRAMES:
        for lead, pre in F22_LEADS.items():
            for label, x in F22_FORM.items():
                cls, opcode, reg, mode, tail, counts = F22_FORMS[label]
                for k in F22_KS:
                    names = pre + [x] * k
                    if kind == "none":
                        body = [LS()] + xs(names) + [LS(), END()]
                    else:
                        body = [LS(), M(0, kind)] + xs(names) + [M(1, kind), LS(), END()]
                    knobs = {"marker": kind, "lead": lead, "n": len(pre), "form": label,
                             "x": x, "k": k, "op": label.split("_")[0], "mode": mode,
                             "disp": len(MODE[mode].disp), "imm": len(tail),
                             "reads": counts.get("reads", 0), "writes": counts.get("writes", 0)}
                    by_kind[kind].append((f"{kind}-{lead}-{label}" + (f"-k{k}" if k > 1 else ""),
                                          knobs, body, {}))
    return [c for kind in F22_FRAMES
            for c in _sweep("F22", by_kind[kind], waits, parities, marker_kind=kind)]


# F23 (WP49: control flow inside the chain), refresh off. The cost frame
# PAD LS M0 [CMP AW,AW] X M1 LS END under PUSH and OUT markers; CMP AW,AW (3B C0) sets Z = 1.
# Controls: the empty frame and CMP AW,AW alone (a branch's cost is the frame's less the
# control's). Taken: CMP ; BE +n ; NOP^n (74 n) and BR short +n ; NOP^n (EB n) for n = 0..7,
# BR near +n ; NOP^n (E9 n 00) for n = 0..3: the n NOPs are chain bytes that never execute
# (knob skipped = n), so the target's alignment moves with n and the parity pad. Not taken:
# CMP ; BNE +n ; NOP^n (75 n) for n = 0, 2 (the NOPs execute) and the pair CMP ; BNE +0
# twice. DBNZ (E2 n) after MOV CW,1 (not taken: CW becomes 0) or MOV CW,2 (taken once, n = 0
# and 2). CALL +0 (E8 00 00: the stack write and the flush, falling through) and the pair
# CALL +2 ; BR +1 ; RET (E8 02 00 EB 01 C3: CALL to the RET, RET back to the BR, the BR
# over the RET); BR +1 ; NOP, the third control, is the taken series' br-n1. Knobs: x the
# form names in chain order, exec the X indices in execution order, skipped the X bytes
# that never execute (NOPs), taken whether the branch transfers.
F23_CMP = "cmp_aw_aw"


def f23(waits=WAITS, parities=PARITIES):
    """Control flow inside the chain (see the comment above)."""
    from .forms import F23_BE_N, F23_BNE_N, F23_BR_N, F23_BR_NEAR_N
    variants = []

    def add(name, group, names, exec_order, taken=None, n=None, k=1):
        knobs = {"group": group, "x": list(names), "k": k, "n": n, "taken": taken,
                 "skipped": len(names) - len(exec_order), "exec": list(exec_order)}
        variants.append((name, knobs, cost_frame(xs(names)), {}))

    add("empty", "control", [], [])
    add("cmp", "control", [F23_CMP], [0])
    for n in F23_BE_N:
        add(f"be-n{n}", "be", [F23_CMP, f"be_n{n}"] + ["nop"] * n, [0, 1], True, n)
    for n in F23_BR_N:
        add(f"br-n{n}", "br", [f"br_n{n}"] + ["nop"] * n, [0], True, n)
    for n in F23_BR_NEAR_N:
        add(f"brnear-n{n}", "br_near", [f"br_near_n{n}"] + ["nop"] * n, [0], True, n)
    for n in F23_BNE_N:
        names = [F23_CMP, f"bne_n{n}"] + ["nop"] * n
        add(f"bne-n{n}" + ("-k1" if n == 0 else ""), "bne", names, range(len(names)), False, n)
    add("bne-n0-k2", "bne", [F23_CMP, "bne_n0"] * 2, range(4), False, 0, 2)
    add("dbnz-c1-n0", "dbnz", ["mov_cw_imm1", "dbnz_n0"], [0, 1], False, 0)
    for n in (0, 2):
        add(f"dbnz-c2-n{n}", "dbnz", ["mov_cw_imm2", f"dbnz_n{n}"] + ["nop"] * n, [0, 1],
            True, n)
    add("call", "call", ["call_n0"], [0], True, 0)
    add("callret", "callret", ["call_n2", "br_n1", "ret"], [0, 2, 1], True)
    return _sweep_markers("F23", variants, waits, parities)


# F25 (WP49: EA alone, and the stack frame), refresh off. The cost frame PAD LS M0 X^k M1 LS
# END under PUSH and OUT markers. LDEA AW,r/m (8D /0) in all 24 memory modes at k = 1 and,
# for [BW], [BW+10h], [BW+200h], [BW+IX], [BW+IX+10h] and [0C00h], k = 2 (no memory cycle:
# the EA path alone). XLAT (D7, a byte read at BW + AL = 0800h). PUSH imm16 (68) and PUSH
# imm8 (6A) at k = 1, 2. PUSH R (60) alone and PUSH R ; POP R (61) (POP R only after PUSH R:
# it loads BW, BP, IX and IY). PREPARE 0,0 (C8 00 00 00) alone and PREPARE 0,0 ; DISPOSE
# (C9) (DISPOSE only after PREPARE: it loads SP from BP). The segment registers: PUSH DS1,
# PUSH DS1 ; POP DS1, PUSH DS0, PUSH DS0 ; POP DS0, PUSH PS, MOV DS1,AW, MOV AW,DS1,
# MOV DS1,[BW] and MOV [BW],DS0 (DS0, SS and PS are never loaded with an unknown value).
# The empty frame is the control.
F25_LDEA_K2 = ("bw", "bw_d8", "bw_d16", "bw_ix", "bw_ix_d8", "dir")
F25_STACK = {"xlat": ("xlat", ["xlat"]),
             "push_imm16": ("push_imm", ["push_imm16"]),
             "push_imm16-k2": ("push_imm", ["push_imm16"] * 2),
             "push_imm8": ("push_imm", ["push_imm8"]),
             "push_imm8-k2": ("push_imm", ["push_imm8"] * 2),
             "pushr": ("push_r", ["push_r"]),
             "pushr_popr": ("push_r", ["push_r", "pop_r"]),
             "prepare": ("frame", ["prepare_00"]),
             "prepare_dispose": ("frame", ["prepare_00", "dispose"]),
             "push_ds1": ("seg", ["push_ds1"]),
             "push_ds1_pop_ds1": ("seg", ["push_ds1", "pop_ds1"]),
             "push_ds0": ("seg", ["push_ds0"]),
             "push_ds0_pop_ds0": ("seg", ["push_ds0", "pop_ds0"]),
             "push_ps": ("seg", ["push_ps"]),
             "mov_ds1_aw": ("seg", ["mov_ds1_aw"]),
             "mov_aw_ds1": ("seg", ["mov_aw_ds1"]),
             "mov_ds1_m": ("seg", ["mov_ds1_m"]),
             "mov_m_ds0": ("seg", ["mov_m_ds0"])}


def f25(waits=WAITS, parities=PARITIES):
    """EA alone and the stack frame (see the comment above)."""
    from .forms import F25_LDEA, MODE, MODES
    variants = [("empty", {"group": "control", "x": [], "k": 0}, cost_frame([]), {})]
    for m in MODES:
        for k in (1, 2) if m.name in F25_LDEA_K2 else (1,):
            x = F25_LDEA[m.name]
            knobs = {"group": "lea", "x": [x] * k, "k": k, "mode": m.name,
                     "mode_class": m.mode_class, "disp": len(MODE[m.name].disp)}
            variants.append((f"ldea-{m.name}" + (f"-k{k}" if k > 1 else ""), knobs,
                             cost_frame(xs([x] * k)), {}))
    for name, (group, names) in F25_STACK.items():
        knobs = {"group": group, "x": list(names),
                 "k": len(names) if len(set(names)) == 1 else 1}
        variants.append((name, knobs, cost_frame(xs(names)), {}))
    return _sweep_markers("F25", variants, waits, parities)


FAMILIES = {"F0": f0, "F0w": f0w, "F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5,
            "F6": f6, "F7": f7, "F8": f8,
            "F9": f9, "F10": f10, "F11": f11, "F12": f12, "F13": f13, "F14": f14,
            "F15": f15, "F16": f16, "F17": f17, "F18": f18, "F19": f19, "F20": f20, "F21": f21,
            "F22": f22, "F23": f23, "F25": f25}

# Families the simulator cannot run yet (WP49): their forms (forms.UNMODELLED_FORMS: the
# control-flow forms, LDEA, XLAT, the stack-frame and segment-register forms) have no
# template in sim/templates.py, so sim.templates.decode raises on them. Generator-only until
# the simulator learns them: the tests that simulate every generated chain skip these, and
# the fitter loads only families with corpus data. (WP52) F25 and (WP55) F23 are modelled.
# (WP58) F27, the refresh-on probes, is modelled: under the thirty-fourth fit 16 FCh IN cells
# overfilled the queue (a refresh beating the fetch held by the IN's I/O, then that fetch's
# back-to-back pair); the I/O steps' enums (sim/config.py, WP58) run every F27 chain within
# the six bytes, and the fit that sets them is the one test_fit's overfill test reads.
UNMODELLED = ()


def generate(families=None, waits=WAITS, parities=PARITIES) -> list[Chain]:
    """Chains of the named families (all by default); ids are asserted unique."""
    chains = []
    for name in families or FAMILIES:
        chains += FAMILIES[name](waits=tuple(waits), parities=tuple(parities))
    ids = [c.id for c in chains]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise AssertionError(f"duplicate chain ids: {dup[:5]}")
    return chains


# F26 and F27 (WP56; spec "Decisions (overseer, 2026-10-27)", "M, 10 fields: two probe
# families, then decide"). Ten rules of the model are pinned by one or two cells each; every
# probe below puts the rule's deciding state in many cells so the fit can tell the candidate
# mechanisms (the rule's OPTIONS in sim/config.py) apart. Every probe is the cost frame
# PAD LS M0 NOP^n X^k M1 LS END unless stated: n NOPs (one byte, a decode slot and about 4
# clocks each from a full queue) between M0 and X move X's operand takes one byte and a few
# clocks at a time across the fetch cadence and against M0's cycle; k repeats X. The fence
# before M0 leaves AW = 0 and CW = 001Fh; the other registers keep the prelude's values (BW
# 0800h, DW 5678h, SP 0F00h, BP 0A00h, IX 0100h, IY 0180h; DW 0040h for the DW I/O forms).
# Knobs on every chain: probe (the rule), series (the id's short tag), marker, n, k, form (the
# probed X form, None for the empty frame), x (every form between M0 and M1, in order), rfm
# (the prelude's RFM) and refresh_on; shape for port_issue. The empty frame of each marker
# (and, in F27, of each RFM) is the dM baseline (derive.BASELINES).
#
# F26, refresh off (RFM ECh), run ids F26-<marker>-<series>-<label>-n<n>[-k<k>]-p<E|O>-w<N>.
# pi (port_issue: a port byte taken on a fetch's issue clock holds the waiting I/O a clock
#   longer, the relatch, against taking it on time; pinned by F7-out-out_imm_al-out_imm_al-pO-w0
#   alone). Shape oo, M0 OUT 40h,AL NOP^n X OUT 40h,AL M1 under both markers: the first OUT's
#   I/O is the waiting one, and X ∈ {none, XCH AW,DW (92), MOV AW,DW (8B C2), ADD AW,DW
#   (03 C2), MOV CL,imm8 (B1 04)} with n = 0..3 (n = 0..1 for ADD AW,DW and MOV CL,imm8)
#   moves the second OUT's port take across a fetch's issue clock, the 1- and 2-byte forms
#   in between differing in length (the byte the port takes is the word's first or second)
#   and clocks (the phase): the cells where the take lands on an issue clock with the I/O
#   still waiting are the rule's state, the rest (take on an idle bus or with an older fetch
#   in flight) its control. Shape o, M0 NOP^n X OUT 40h,AL M1, X ∈ {NOP, XCH, MOV AW,DW,
#   ADD AW,DW, MOV CL,imm8}: under the OUT marker (n = 0, 1) the marker's I/O is the waiting
#   one; the PUSH twin (n = 0) has no I/O waiting at the take (the relatch cannot matter).
# fib (free_idle_b2b: the idle clock after a fetch the bus unit committed back to back at the
#   free clocks' eve of a request; pinned by two k = 2 F21 base+index+d16 immediate stores).
#   MOV [BW+IX+200h],imm16 (C7 80 00 02 34 12) at k = 1, 2, 3 under both markers (each further
#   store posts its write beside the fetch run the previous one left: k = 3 makes the state a
#   second time in one frame), NOP^n for n = 1, 2 before the k = 2 pair (the pair's d16 take
#   against the run's delivery clock), and at k = 2 the comparison forms MOV [BW+200h],imm16,
#   MOV [BW+IX],imm16, MOV [BW+IX+10h],imm16 (no index clock, no displacement, d8): which EA
#   shapes put a back-to-back fetch on the write's eve, at every wait (the rule claims 1 and
#   2 waits as well).
# gih (grp_io_hold: a group form's request whose next setup clock is a bus-free group clock
#   holds a fetch first requested on or after an I/O cycle's issue until the recovery's end,
#   against letting it run as any request does; pinned by six F14 TEST [0C00h],AW cells under
#   OUT at pO). Under the OUT marker, NOP^n (n = 0..2) then a group memory form with a
#   bus-free group clock at M0's I/O recovery: INC [BW] (FF 07), NOT [BW] (F7 17), SHL [BW],1
#   (D1 27), NEG [BW] (F7 1F), DEC [BW] (FF 0F), the controls TEST [0C00h],AW (85 06 00 0C,
#   the pinned form) and TEST [BW],AW (85 07, not a group form); the ladder moves the fetch's
#   request before, on and after the I/O's issue clock (the rule's older-fetch exception
#   against its hold). The PUSH twin at n = 0: no I/O recovery to hold through.
# dio (disp_io: a displacement taken on the clock an I/O cycle issues holds that I/O a clock
#   longer, against no effect; only base+index+d16 took on the issue clock in the corpus).
#   Under the OUT marker, NOP^n for n = 0..3 then X ∈ {MOV AW,[BW+10h] (8B 47 10), MOV
#   AW,[BW+200h] (8B 87 00 02), MOV AW,[BW+IX+10h] (8B 40 10), MOV AW,[BW+IX+200h] (8B 80 00
#   02), MOV AW,[0C00h] (8B 06 00 0C), MOV AW,[BW] (8B 07, no displacement: the control)}:
#   the ladder times the displacement's take against the marker I/O's issue clock for every
#   displacement width and mode class, so d8, base+d16 and direct takes land on the issue
#   clock too (the rule says any displacement; the corpus only had the base+index one).
# lks (lookup_start: TEST 84/85's lookup runs one clock more when a fetch issued on its start
#   clock, against a fixed lookup; pinned by TEST [0C00h],AW k = 2 pE/pO under PUSH).
#   TEST [0C00h],AW at k = 1, 2 with NOP^n for n = 0..2 before it and at k = 3 (n = 0), both
#   markers: each instance's start clock with and without a fetch issuing on it, the second
#   and third instances in the state the first leaves; controls TEST [BW],AW (85 07, no
#   displacement) and TEST [BW+200h],AW (85 87 00 02, base+d16) at k = 1, 2.
# cnt (the C0/C1 count mask, spec Open items: the model takes a C0/C1 count byte unmasked, so
#   a count of 255 runs 510 clocks, where silicon may mask it to 5 bits). SHL AW,n (C1 E0 nn)
#   for n = 31, 32, 33, 255: masked, 32 is a zero count (no loop) and 33 is 1, 255 is 31, the
#   same as n = 31; unmasked they run 2n clocks of loop. MOV CL,n ; SHL AW,CL (B1 nn D3 E0)
#   for n = 32, 255: the CL path, which the model masks already (the control). PUSH marker
#   primary, the OUT frame for every one as well (a 255-count unmasked shift is ~510 clocks,
#   inside the harness's 2,000,000-tick budget; the closing LS and END follow as usual).
F26_RFM = RFM_OFF
F26_PI_X = {"none": [], "nop": ["nop"], "xch": ["xch_aw_dw"], "movr": ["mov_aw_dw"],
            "addr": ["add_aw_dw"], "movcl": ["mov_cl_imm"]}
F26_PI_PORT = "out_imm_al"                    # OUT 40h,AL (not a marker's 20h+i, not END's)
F26_PI_OO_N = {"none": range(4), "xch": range(4), "movr": range(4), "addr": range(2),
               "movcl": range(2)}
F26_PI_O_X = ("nop", "xch", "movr", "addr", "movcl")
F26_PI_O_N = {"out": (0, 1), "push": (0,)}
F26_FIB_X = {"bixd16": "st_imm_bw_ix_d16", "bd16": "st_imm_bw_d16", "bix": "st_imm_bw_ix",
             "bixd8": "st_imm_bw_ix_d8"}
F26_FIB_K = (1, 2, 3)                         # bixd16 at n = 0
F26_FIB_N = (1, 2)                            # bixd16 at k = 2
F26_FIB_CMP = ("bd16", "bix", "bixd8")        # k = 2, n = 0
F26_GIH_X = {"inc": "inc_m", "not": "not_m", "shl1": "shl_m1", "neg": "neg_m", "dec": "dec_m",
             "testdir": "test_dir_aw", "testbw": "test_m_aw"}
F26_GIH_N = {"out": (0, 1, 2), "push": (0,)}
F26_DIO_X = {"bwd8": "ld_bw_d8", "bwd16": "ld_bw_d16", "bixd8": "ld_bw_ix_d8",
             "bixd16": "ld_bw_ix_d16", "dir": "ld_dir", "bw": "ld_bw"}
F26_DIO_N = range(4)                          # OUT marker only
F26_LKS_X = {"testdir": "test_dir_aw", "testbw": "test_m_aw", "testbwd16": "test_m_aw_bw_d16"}
F26_LKS_KN = {"testdir": {1: (0, 1, 2), 2: (0, 1, 2), 3: (0,)},
              "testbw": {1: (0,), 2: (0,)}, "testbwd16": {1: (0,), 2: (0,)}}
F26_CNT_X = {"shli31": "shl_imm31", "shli32": "shl_imm32", "shli33": "shl_imm33",
             "shli255": "shl_imm255", "shlcl32": "shl_cl32", "shlcl255": "shl_cl255"}


def _probe_frame(kind, names):
    """PAD LS M0 <names> M1 LS END (PAD added by make_chain)."""
    return [LS(), M(0, kind)] + xs(names) + [M(1, kind), LS(), END()]


def _probe_knobs(probe, series, kind, n, k, form, names, rfm, **extra):
    return {"probe": probe, "series": series, "marker": kind, "n": n, "k": k, "form": form,
            "x": list(names), "rfm": rfm, "refresh_on": rfm != RFM_OFF, **extra}


def f26(waits=WAITS, parities=PARITIES):
    """The refresh-off probes pi, fib, gih, dio, lks, cnt (see the comment above)."""
    by_kind = {"push": [], "out": []}
    rfm = F26_RFM

    def add(kind, probe, series, label, n, k, form, names, **extra):
        name = f"{kind}-{series}-{label}-n{n}" + (f"-k{k}" if series in ("fib", "lks") else "")
        by_kind[kind].append((name, _probe_knobs(probe, series, kind, n, k, form, names, rfm,
                                                 **extra), _probe_frame(kind, names), {}))

    for kind in COST_MARKERS:
        by_kind[kind].append((f"{kind}-empty", _probe_knobs("empty", "empty", kind, 0, 0, None,
                                                            [], rfm), _probe_frame(kind, []), {}))
    for kind in COST_MARKERS:
        for label, ns in F26_PI_OO_N.items():
            x = F26_PI_X[label]
            for n in ns:
                add(kind, "port_issue", "pi", f"oo-{label}", n, 1, F26_PI_PORT,
                    [F26_PI_PORT] + ["nop"] * n + x + [F26_PI_PORT], shape="oo")
        for label in F26_PI_O_X:
            x = F26_PI_X[label]
            for n in F26_PI_O_N[kind]:
                add(kind, "port_issue", "pi", f"o-{label}", n, 1, F26_PI_PORT,
                    ["nop"] * n + x + [F26_PI_PORT], shape="o")
    for kind in COST_MARKERS:
        x = F26_FIB_X["bixd16"]
        for k in F26_FIB_K:
            add(kind, "free_idle_b2b", "fib", "bixd16", 0, k, x, [x] * k)
        for n in F26_FIB_N:
            add(kind, "free_idle_b2b", "fib", "bixd16", n, 2, x, ["nop"] * n + [x] * 2)
        for label in F26_FIB_CMP:
            x = F26_FIB_X[label]
            add(kind, "free_idle_b2b", "fib", label, 0, 2, x, [x] * 2)
    for kind in ("out", "push"):
        for label, x in F26_GIH_X.items():
            for n in F26_GIH_N[kind]:
                add(kind, "grp_io_hold", "gih", label, n, 1, x, ["nop"] * n + [x])
    for label, x in F26_DIO_X.items():
        for n in F26_DIO_N:
            add("out", "disp_io", "dio", label, n, 1, x, ["nop"] * n + [x])
    for kind in COST_MARKERS:
        for label, kn in F26_LKS_KN.items():
            x = F26_LKS_X[label]
            for k, ns in kn.items():
                for n in ns:
                    add(kind, "lookup_start", "lks", label, n, k, x, ["nop"] * n + [x] * k)
    for kind in COST_MARKERS:
        for label, x in F26_CNT_X.items():
            add(kind, "count_mask", "cnt", label, 0, 1, x, [x])
    return [c for kind in COST_MARKERS
            for c in _sweep("F26", by_kind[kind], waits, parities, marker_kind=kind, rfm=rfm)]


# F27, refresh on from the prelude (RFM FCh, as F8 and F13), every variant at every wait, with
# a refresh-off twin (RFM ECh) of every variant at 0 waits as the control (as F18 A's ECh
# prelude); run ids F27-<marker>-<fc|ec>-<series>-<label>-n<n>[-k<k>]-p<E|O>-w<N>. Both
# markers throughout. The refresh timer runs free from the prelude, so the chain's offset to
# the refresh grid is the prelude's length plus the parity pad plus the body, fixed per cell:
# the ladders move the body's state across the grid a few clocks a step.
# room (room_ir_imm: the IR counts as a seventh queue slot whenever the decoder is not
#   mid-take, for every class, against not while a MOV r16,imm16 runs; keyed on class imm and
#   seen only in the prelude's MOV r16,imm16 train). In the chain body: MOV AW,imm16^k (B8 34
#   12) and MOV DW,imm16^k (BA 40 00) for k = 1..4 (the train: each takes its last immediate
#   byte and loads the IR with the queue one byte short of a word, a refresh request standing
#   on some of those clocks), against MOV CL,imm8^k (B1 04, class imm with one immediate byte)
#   k = 1..4 and ADD DW,imm16^k (81 C2 34 12, ModR/M + imm16) k = 1..3: which forms' last
#   immediate take raises a request on the IR's slot alone.
# unit (refresh_drop_unit: a fetch request raised on a delivery clock with room for exactly a
#   word is lost to a refresh taking the bus there while the EU is inside a register unit's
#   clocks, against only with odd room; pinned by nine F17 runs at 2 waits). NOP^n (n = 0..2)
#   then MOV CL,n ; SHL AW,CL for n = 4, 8, 16, MULU DW (F7 E2), SHL AW,8 (C1 E0 08), k = 1:
#   the unit's exec and count-loop clocks cover more refresh slots as the count grows, the
#   NOPs move the delivery clocks against the grid, so refreshes on room-2 delivery clocks
#   fall inside the unit (the rule) and outside it (the control) in the same chain.
# port (refresh_drop_post: a fetch request a refresh takes the bus from on the port byte's take
#   of a port-form IN/OUT stays raised and runs on the I/O lead's first clock, against lost;
#   refresh_lead_port: for the port form a refresh may start on the lead's first clock and the
#   I/O follows it, against no refresh in the whole lead). NOP^n for n = 0..5 then OUT 40h,AL
#   (E6 40), OUT 40h,AW (E7 40), IN AL,40h (E4 40): port 40h, not a marker's 20h+i nor END's
#   FF00h; the ladder moves the port byte's take and the lead's two clocks across the refresh
#   grid so a refresh lands on the take, the lead's first clock and its last. DW-form controls
#   OUT DW,AW (EF, the catalog's out_dw_al) and IN AL,DW (EC) at n = 0, 2, 4 with DW = 0040h
#   (the rules keep both lead clocks closed for the DW form and the post on its own start).
# beat (refresh_beat_t4: a 3-clock fetch run right after a refresh beat it keeps the bus unit
#   busy on its delivery clock, so the next instruction's fetch requested there starts a clock
#   later, against free on delivery; pinned by F13's prelude cells at 0 waits, the prelude's
#   MOV DS1,AW ; MOV AW,imm16). NOP^n for n = 0..5 then MOV DS1,AW (8E C0, the prelude's own
#   form: DS1 := 0, unchanged) ; MOV AW,imm16, and NOP^n then MOV AW,DW ; MOV DW,imm16 (BA 40
#   00), the same 2-byte-ModR/M-then-3-byte-immediate shape with register forms: the ladder
#   moves the beaten fetch over the refresh grid so the MOV r16,imm16 starts on a beaten 3-clock
#   fetch's delivery in some cells; the rule needs 0 waits, the 1- and 2-wait cells (4- and
#   5-clock fetches) are the control, as are the ECh twins.
F27_RFM = (RFM_ON, RFM_OFF)
F27_OFF_WAITS = (0,)                          # the ECh twins
F27_ROOM_X = {"movawi": ("mov_aw_imm", range(1, 5)), "movdwi": ("mov_dw_imm", range(1, 5)),
              "movcl": ("mov_cl_imm", range(1, 5)), "adddwi": ("add_dw_imm", range(1, 4))}
F27_UNIT_X = {"shlcl4": "shl_cl4", "shlcl8": "shl_cl8", "shlcl16": "shl_cl16",
              "mulu": "mulu_dw", "shli8": "shl_imm8"}
F27_UNIT_N = range(3)
F27_PORT_X = {"outb": "out_imm_al", "outw": "out_imm_aw", "inb": "in_al_imm"}
F27_PORT_N = range(6)
F27_PORT_DW_X = {"outdw": "out_dw_al", "indw": "in_al_dw"}
F27_PORT_DW_N = (0, 2, 4)
F27_PORT_PROBE = "refresh_drop_post/refresh_lead_port"
F27_BEAT_X = {"ds1": ["mov_ds1_aw", "mov_aw_imm"], "movr": ["mov_aw_dw", "mov_dw_imm"]}
F27_BEAT_N = range(6)


def f27(waits=WAITS, parities=PARITIES):
    """The refresh-on probes room, unit, port, beat (see the comment above)."""
    chains = []
    for rfm in F27_RFM:
        ws = tuple(w for w in waits if rfm == RFM_ON or w in F27_OFF_WAITS)
        by_kind = {"push": [], "out": []}

        def add(kind, probe, series, label, n, k, form, names):
            name = (f"{kind}-{rfm:02x}-{series}-{label}-n{n}"
                    + (f"-k{k}" if series == "room" else ""))
            by_kind[kind].append((name, _probe_knobs(probe, series, kind, n, k, form, names,
                                                     rfm), _probe_frame(kind, names),
                                  {"rfm": rfm}))

        for kind in COST_MARKERS:
            by_kind[kind].append((f"{kind}-{rfm:02x}-empty",
                                  _probe_knobs("empty", "empty", kind, 0, 0, None, [], rfm),
                                  _probe_frame(kind, []), {"rfm": rfm}))
            for label, (x, ks) in F27_ROOM_X.items():
                for k in ks:
                    add(kind, "room_ir_imm", "room", label, 0, k, x, [x] * k)
            for label, x in F27_UNIT_X.items():
                for n in F27_UNIT_N:
                    add(kind, "refresh_drop_unit", "unit", label, n, 1, x, ["nop"] * n + [x])
            for label, x in F27_PORT_X.items():
                for n in F27_PORT_N:
                    add(kind, F27_PORT_PROBE, "port", label, n, 1, x, ["nop"] * n + [x])
            for label, x in F27_PORT_DW_X.items():
                for n in F27_PORT_DW_N:
                    add(kind, F27_PORT_PROBE, "port", label, n, 1, x, ["nop"] * n + [x])
            for label, pair in F27_BEAT_X.items():
                for n in F27_BEAT_N:
                    add(kind, "refresh_beat_t4", "beat", label, n, 1, pair[-1],
                        ["nop"] * n + pair)
        chains += [c for kind in COST_MARKERS
                   for c in _sweep("F27", by_kind[kind], ws, parities, marker_kind=kind)]
    return chains


FAMILIES.update({"F26": f26, "F27": f27})


# F28 and F29 (WP59; the open states the thirty-sixth fit left, docs "The I/O sequencer's
# steps under a refresh", the 294 misses). Both are the probe frame PAD LS M0 <x> M1 LS END
# with the F26/F27 knobs (probe, series, marker, n, k, form, x, rfm, refresh_on), the empty
# frame of each marker and RFM the dM baseline. F28 is refresh on from the prelude (RFM FCh,
# every wait) with a refresh-off twin (ECh) of every variant at 0 waits, as F27; F29 is
# refresh off (ECh) at every wait, as F26. Run ids
# F28-<push|out>-<fc|ec>-<series>-<label>-n<n>[-k<k>]-p<E|O>-w<N> and
# F29-<push|out>-ec-<series>-<label>-n<n>-p<E|O>-w<N>.
#
# F28, refresh on.
# fence (the M0 marker OUT at pO w2 under FCh: every F27 OUT-frame run of that cell, 67, and
#   the same state in 4 F8 and 15 F13 runs, silicon R81 F94 R99 I104 from t_fill, the model
#   F96 R101 I106; the refresh 81-85 lies inside the fence's SHL AW,CL tail and over the
#   OUT's start, the model holds the EU 83-86, silicon's first fetch after the marker's post
#   two clocks earlier, a port take at 89 against the model's 91). The empty frame with the
#   fence's count CL = 24..30 (B1 nn D3 E0; 31 is the empty frame itself): each count moves
#   the fence's end, and with it M0's OUT, two clocks against the refresh timer, which runs
#   free from the prelude, so the marker OUT starts at every offset to the refresh within
#   seven counts (14 clocks, about a refresh interval). Both markers (PUSH: the same fence
#   tail before a PUSH, the control). Deciding runs: F27-out-fc-empty-pO-w2 (count 31).
# tail (the same state in the chain body: an OUT that follows a register unit's tail with a
#   refresh in the tail or over the OUT's start). NOP^n then a unit then OUT 40h,AL (E6 40)
#   at once: MOV CL,c ; SHL AW,CL for c = 8, 16, 24, 31 (B1 cc D3 E0) at n = 0..5, SHL AW,8
#   (C1 E0 08) and MULU DW (F7 E2) at n = 0, 2, 4; the count moves the tail's end 16 clocks
#   a step (about a refresh interval, so the counts repeat the phase with a longer unit
#   before it), the NOPs a few clocks a step; OUT 40h,AW (E7 40) and OUT DW,AL (EE, DW =
#   0040h) behind the count-31 shift (the fence's own unit) at n = 0, 2, 4: the word port
#   form and the DW form, whose lead has no port take. Both markers: under OUT the
#   marker's I/O is in flight before the unit, under PUSH a write.
# beat (refresh_beat_t4 for back-to-back fetches: the fetch after a 3-clock beaten fetch a
#   clock late in silicon, 19 F27 runs, e.g. F27-out-fc-room-movawi-n0-k2-pE-w0, silicon r103
#   f108 f112 f115, the model f111; t4 for back-to-back fetches loses 272 corpus runs). Under
#   the OUT marker, NOP^n (n = 0..3) then MOV AW,imm16^k (B8 34 12), MOV DW,imm16^k (BA 40 00)
#   or ADD DW,imm16^k (81 C2 34 12) for k = 1..4: the train's immediate takes leave the queue
#   at different occupancies when the refresh beats a fetch, the NOPs move the refresh against
#   the train, so the second fetch's lateness can be read against the beaten fetch's room and
#   the running instruction's take on its delivery clock. Every wait (the 1- and 2-wait
#   cells, 4- and 5-clock fetches, and the ECh twins are the control).
F28_RFM = (RFM_ON, RFM_OFF)
F28_OFF_WAITS = (0,)                          # the ECh twins
F28_FENCE_CL = range(24, 31)                  # 31: the empty frame
F28_TAIL_UNIT = {"shlcl8": "shl_cl8", "shlcl16": "shl_cl16", "shlcl24": "shl_cl24",
                 "shlcl31": "shl_cl31", "shli8": "shl_imm8", "mulu": "mulu_dw"}
F28_TAIL_N = {"shlcl8": range(6), "shlcl16": range(6), "shlcl24": range(6),
              "shlcl31": range(6), "shli8": (0, 2, 4), "mulu": (0, 2, 4)}
F28_TAIL_OUT = "out_imm_al"                   # OUT 40h,AL behind every unit
F28_TAIL_PORT = {"outw": "out_imm_aw", "outdwb": "out_dw_b"}   # behind shlcl31
F28_TAIL_PORT_N = (0, 2, 4)
F28_TAIL_PROBE = "tail_out"
F28_BEAT_X = {"movawi": "mov_aw_imm", "movdwi": "mov_dw_imm", "adddwi": "add_dw_imm"}
F28_BEAT_K = range(1, 5)
F28_BEAT_N = range(4)
F28_BEAT_PROBE = "refresh_beat_t4/b2b"


def _fence(cl):
    """The first LS with the shift count cl (B1 cl D3 E0), the same four bytes' shape."""
    return Instr(0, bytes([0xB1, cl, 0xD3, 0xE0]), "LS", "ls")


def f28(waits=WAITS, parities=PARITIES):
    """The refresh-on probes fence, tail, beat (see the comment above)."""
    chains = []
    for rfm in F28_RFM:
        ws = tuple(w for w in waits if rfm == RFM_ON or w in F28_OFF_WAITS)
        by_kind = {"push": [], "out": []}

        def add(kind, probe, series, label, n, k, form, names, frame=None, **extra):
            name = (f"{kind}-{rfm:02x}-{series}-{label}-n{n}"
                    + (f"-k{k}" if series == "beat" else ""))
            by_kind[kind].append((name, _probe_knobs(probe, series, kind, n, k, form, names,
                                                     rfm, **extra),
                                  frame or _probe_frame(kind, names), {"rfm": rfm}))

        for kind in COST_MARKERS:
            by_kind[kind].append((f"{kind}-{rfm:02x}-empty",
                                  _probe_knobs("empty", "empty", kind, 0, 0, None, [], rfm),
                                  _probe_frame(kind, []), {"rfm": rfm}))
            for cl in F28_FENCE_CL:
                frame = [_fence(cl)] + _probe_frame(kind, [])[1:]
                add(kind, "fence_out", "fence", f"cl{cl}", 0, 0, None, [], frame=frame,
                    fence_cl=cl)
            for label, unit in F28_TAIL_UNIT.items():
                for n in F28_TAIL_N[label]:
                    add(kind, F28_TAIL_PROBE, "tail", f"{label}-outb", n, 1, F28_TAIL_OUT,
                        ["nop"] * n + [unit, F28_TAIL_OUT], unit=unit)
            for label, port in F28_TAIL_PORT.items():
                for n in F28_TAIL_PORT_N:
                    add(kind, F28_TAIL_PROBE, "tail", f"shlcl31-{label}", n, 1, port,
                        ["nop"] * n + ["shl_cl31", port], unit="shl_cl31")
        for label, x in F28_BEAT_X.items():
            for k in F28_BEAT_K:
                for n in F28_BEAT_N:
                    add("out", F28_BEAT_PROBE, "beat", label, n, k, x, ["nop"] * n + [x] * k)
        chains += [c for kind in COST_MARKERS
                   for c in _sweep("F28", by_kind[kind], ws, parities, marker_kind=kind)]
    return chains


# F29, refresh off (RFM ECh), every wait: the F26 reads "confirmed where seen; the other modes
# and forms as a state read".
# dio (disp_io: a displacement taken on the clock an I/O cycle issues holds that I/O a clock
#   longer; F26 decided it on base+index+d16 alone, 42 cells, the d8, base+d16 and direct
#   loads exact under both values). Under the OUT marker, NOP^n (n = 0..3) then the stores
#   MOV [BW+10h],AW (89 47 10), MOV [BW+200h],AW (89 87 00 02), MOV [0C00h],AW (89 06 00 0C)
#   and the control MOV [BW+IX+200h],AW (89 80 00 02): the store's displacement take against
#   the marker I/O's issue clock for each width and mode class, the loads' ladder being
#   F26's. In the model these takes land a clock or two before the issue (base+index+d16 on
#   it, the index's EA clock), so the dw cells put them on a later issue clock: OUT DW,AL
#   (EE, DW = 0040h) right after M0, then X for the four stores and the loads MOV AW,[BW+10h],
#   MOV AW,[BW+200h], MOV AW,[0C00h], MOV AW,[BW+IX+200h] (n = 0): the take on the DW OUT's
#   issue clock at pO, a clock after it at pE, every wait (in the model the hold changes no
#   later cycle in these cells: the read is whether silicon's does).
# gih (grp_io_hold: a group form's request whose next setup clock is a bus-free group clock
#   holds a fetch first requested on or after an I/O's issue until the recovery's end; F26
#   saw it with TEST's fixed lookup only, INC, NOT, SHL, NEG, DEC [BW] exact under both).
#   Under the OUT marker, NOP^n (n = 0..2) then INC, NOT, SHL ,1, NEG, DEC [BW+200h] (FF 87,
#   F7 97, D1 A7, F7 9F, FF 8F, d16 0200h): the group forms with a two-byte displacement,
#   whose take moves the request against M0's I/O as TEST [0C00h]'s does ([BW] at n = 0..2
#   is F26's). The dw cells: OUT DW,AL (EE) right after M0, then the five [BW+200h] forms and
#   the controls TEST [0C00h],AW and TEST [BW+200h],AW (n = 0): the TEST take three clocks
#   after the DW OUT's issue, where in the model the hold decides at both parities and every
#   wait (TEST under M0 alone decides at pO only); the model never holds for the RMW forms.
# pi (port_issue: a port byte taken on a fetch's issue clock holds the waiting I/O a clock
#   longer; pinned by F7-out-out_imm_al-out_imm_al-pO-w0 and F26-out-pi-oo-none-n0-pO-w0).
#   Shape oo, OUT 40h,AL NOP^n X OUT 40h,AL with the 3- and 4-byte register forms X = MOV
#   AW,imm16 (B8 34 12) and ADD DW,imm16 (81 C2 34 12) at n = 0..3 (a longer X moves the
#   second OUT's port take by a byte and its clocks); shape noo, NOP^n OUT 40h,AL OUT 40h,AL
#   at n = 0..5 (the pair after a NOP run: the fetch run's issue clocks against the second
#   port take). Both markers.
F29_RFM = RFM_OFF
F29_DIO_X = {"stbwd8": "st_bw_d8", "stbwd16": "st_bw_d16", "stdir": "st_dir",
             "stbixd16": "st_bw_ix_d16"}
F29_DIO_N = range(4)                          # OUT marker only
F29_GIH_X = {"incd16": "inc_m_bw_d16", "notd16": "not_m_bw_d16", "shl1d16": "shl_m1_bw_d16",
             "negd16": "neg_m_bw_d16", "decd16": "dec_m_bw_d16"}
F29_GIH_N = range(3)                          # OUT marker only
F29_DW = "out_dw_b"                           # OUT DW,AL before the dw cells' X
F29_DIO_DW_X = dict(F29_DIO_X, ldbwd8="ld_bw_d8", ldbwd16="ld_bw_d16", lddir="ld_dir",
                    ldbixd16="ld_bw_ix_d16")
F29_GIH_DW_X = dict(F29_GIH_X, testdir="test_dir_aw", testbwd16="test_m_aw_bw_d16")
F29_PI_PORT = F26_PI_PORT
F29_PI_OO_X = {"movawi": "mov_aw_imm", "adddwi": "add_dw_imm"}
F29_PI_OO_N = range(4)
F29_PI_NOO_N = range(6)


def f29(waits=WAITS, parities=PARITIES):
    """The refresh-off probes dio, gih, pi (see the comment above)."""
    by_kind = {"push": [], "out": []}
    rfm = F29_RFM

    def add(kind, probe, series, label, n, k, form, names, **extra):
        name = f"{kind}-{rfm:02x}-{series}-{label}-n{n}"
        by_kind[kind].append((name, _probe_knobs(probe, series, kind, n, k, form, names, rfm,
                                                 **extra), _probe_frame(kind, names), {}))

    for kind in COST_MARKERS:
        by_kind[kind].append((f"{kind}-{rfm:02x}-empty",
                              _probe_knobs("empty", "empty", kind, 0, 0, None, [], rfm),
                              _probe_frame(kind, []), {}))
    for label, x in F29_DIO_X.items():
        for n in F29_DIO_N:
            add("out", "disp_io", "dio", label, n, 1, x, ["nop"] * n + [x])
    for label, x in F29_DIO_DW_X.items():
        add("out", "disp_io", "dio", f"dw-{label}", 0, 1, x, [F29_DW, x], shape="dw")
    for label, x in F29_GIH_X.items():
        for n in F29_GIH_N:
            add("out", "grp_io_hold", "gih", label, n, 1, x, ["nop"] * n + [x])
    for label, x in F29_GIH_DW_X.items():
        add("out", "grp_io_hold", "gih", f"dw-{label}", 0, 1, x, [F29_DW, x], shape="dw")
    port = F29_PI_PORT
    for kind in COST_MARKERS:
        for label, x in F29_PI_OO_X.items():
            for n in F29_PI_OO_N:
                add(kind, "port_issue", "pi", f"oo-{label}", n, 1, port,
                    [port] + ["nop"] * n + [x, port], shape="oo")
        for n in F29_PI_NOO_N:
            add(kind, "port_issue", "pi", "noo", n, 1, port, ["nop"] * n + [port, port],
                shape="noo")
    return [c for kind in COST_MARKERS
            for c in _sweep("F29", by_kind[kind], waits, parities, marker_kind=kind, rfm=rfm)]


FAMILIES.update({"F28": f28, "F29": f29})


# F24 (WP66; HDL plan Phase E item 3: the string and block forms, sustained data demand
# through the arbiter), refresh off (RFM ECh), the OUT marker only (an I/O write at port 20h /
# 21h, never a data or stack cycle, so every data cycle in the frame is the string form's),
# every wait and parity. The cost frame PAD [P] LS M0 X M1 LS END; X's cost is
# dM(X) - dM(baseline), the baseline named by the knob `baseline` (the x_variant of the chain
# whose frame holds X less the string form: the empty frame, or MOV CW,n [D^d] alone), and the
# trailing LS shows the queue occupancy at M1.
#
# Registers (presets, _f24_regs, every F24 chain, so the prelude is the same family-wide):
# IX = 0A40h (the source, DS0:IX), IY = 0C40h (the destination, DS1:IY), DW = 0040h (INM /
# OUTM's port, IO_PORT as the DW I/O forms); DS0 = DS1 = SS = 0 (the prelude's, so offsets
# are linear), PSW 0002h (DIR clear: every element steps IX / IY upward by its width). The
# fence (MOV CL,31 ; SHL AW,CL) leaves AW = 0 and CW = 001Fh, so CMPM compares 0000h / 00h
# with the 90h fill (never equal) and the REP count is set in the frame by MOV CW,n (B9 nn nn,
# a preset CW would be lost to the fence's MOV CL). The ranges: the source reads 0A40h-0A5Fh
# at most, the destination 0C40h-0C5Fh, both in the data page (classified data, under 1000h),
# clear of every EA the other forms use (0800h, 0810h, 0900h-0990h, 0A00h, 0A10h, 0B00h-0B90h,
# 0C00h, 0D00h, 0D80h), of the store marker's 0C00h, the stack (0E00h-0F00h) and the code.
#
# s (singles, no prefix): MOVBK, CMPBK, STM, LDM, CMPM, INM, OUTM, byte and word, X^k for
#   k = 1, 2: one element's cost, its read / write order and issue points, the back-to-back
#   pair. Baseline: the empty frame.
# r (repeat): M0 MOV CW,n ; REP X M1 for n = 0, 1, 2, 3, 4, 8: REP STM, REP MOVBK, REP INM, REP
#   OUTM byte and word, REP LDM word, REPNE CMPM word and REPE CMPBK word (the compares that
#   run CW out on the fill), and n = 16 for REP STM and REP MOVBK word (the long run): the
#   per-element cadence, the first element's setup, n = 0's check, the fetches the stream
#   lets in as the queue drains, where fetching restarts after the last element. Controls
#   MOV CW,n alone for every n (the baseline of the r, a and t chains with that n).
# a (alignment): REP forms over odd addresses, n = 1, 2, 4: MOVBK with IX odd (0A41h), IY odd
#   (0C41h) and both; REPE CMPBK with both; REP STM and REPNE CMPM with IY odd; REP LDM and
#   REP OUTM with IX odd; REP INM with IY odd: the odd word's split per element.
# t (termination): the compares' early exit, word at n = 2, 4 and byte at n = 4. On the fill
#   REPE CMPM stops after element 1 (0 != 9090h) and REPNE CMPBK after element 1 (fill =
#   fill); with the pattern (P = MOV word [0C42h],0 before the first LS: the destination word
#   at IY + 2 reads 0000h, the fence erases the store's cost) REPE CMPBK stops after element 2
#   (9090h != 0000h; byte: element 3, 0C42h) and REPNE CMPM after element 2 (0 = 0000h; byte:
#   element 3). At n = 2 the word pattern exits coincide with CW reaching 0. Control: the
#   pattern store with the empty frame. (Acquired: CMPBK reads IY before IX, and every REP
#   compare reads one element more after the one that ends it, the overrun; iters counts
#   the compared elements, normalize.StringRun keeps the overrun apart.)
# d (drain): M0 MOV CW,4 D^d REP X M1, d = 0, 2, 4 (the F6 drainers, MOV AW,1234h / MOV
#   DW,5678h alternating: AW = 1234h for STM's datum after D0, DW changes but no I/O form
#   follows), X = REP STM word and REP MOVBK word: the string form starting from an emptier
#   queue. Controls MOV CW,4 D^d alone (d = 2, 4; d = 0 is r's MOV CW,4).
# Knobs: series, marker, op, width (1 / 2), rep (None, rep, repe, repne), n (the REP count,
# None for singles), k (instances), iters (the elements expected, _f24_iters; test_chains
# checks it against normalize.string_elements), align (even, ix, iy, ixiy), pattern, drain, form (the string form, None
# for a control), x (every form between M0 and M1 in order), pre (the forms before the first
# LS), ix / iy (the presets), baseline. Run ids
# F24-out-<series>-[<rep>-]<op>-<b|w>-(k<k>|n<n>)[-<align>|-<fill|pat>|-d<d>]-p<E|O>-w<N>, the
# controls F24-out-empty, F24-out-r-movcw-n<n>, F24-out-t-pat-empty, F24-out-d-movcw-n4-d<d>.
F24_RFM = RFM_OFF
F24_KIND = "out"
F24_S_K = (1, 2)
F24_R_N = (0, 1, 2, 3, 4, 8)
F24_R_X = (("rep", "stm", 2), ("rep", "stm", 1), ("rep", "movbk", 2), ("rep", "movbk", 1),
           ("rep", "ldm", 2), ("repne", "cmpm", 2), ("repe", "cmpbk", 2), ("rep", "inm", 2),
           ("rep", "inm", 1), ("rep", "outm", 2), ("rep", "outm", 1))
F24_R_LONG = (16, (("rep", "stm", 2), ("rep", "movbk", 2)))
F24_A_N = (1, 2, 4)
F24_A_X = (("rep", "movbk", "ix"), ("rep", "movbk", "iy"), ("rep", "movbk", "ixiy"),
           ("repe", "cmpbk", "ixiy"), ("rep", "stm", "iy"), ("repne", "cmpm", "iy"),
           ("rep", "ldm", "ix"), ("rep", "outm", "ix"), ("rep", "inm", "iy"))
F24_T_X = (("repe", "cmpm", False), ("repne", "cmpbk", False), ("repe", "cmpbk", True),
           ("repne", "cmpm", True))
F24_T_N = {2: (2, 4), 1: (4,)}                # width: n
F24_D_N = (0, 2, 4)
F24_D_CW = 4
F24_D_X = (("rep", "stm", 2), ("rep", "movbk", 2))


def _f24_regs(align="even"):
    from .forms import F24_IX, F24_IY, IO_PORT
    return {"IX": F24_IX + (align in ("ix", "ixiy")), "IY": F24_IY + (align in ("iy", "ixiy")),
            "DW": IO_PORT}


def _f24_iters(op, width, rep, n, pattern):
    """The elements one REP form runs: n, or the compare's exit on the fill / the pattern."""
    if rep is None:
        return 1
    if op not in ("cmpbk", "cmpm"):
        return n
    # on the fill: CMPM (0 vs 90h) differs at once, CMPBK (fill vs fill) never differs; the
    # pattern zeroes the destination word at IY + 2 (element 2 of a word form, 3 of a byte form)
    stop_on_diff, stop_on_same = rep == "repe", rep == "repne"
    at = 2 if width == 2 else 3
    for e in range(1, n + 1):
        dst_zero = pattern and e == at
        same = (not dst_zero) if op == "cmpbk" else dst_zero
        if (stop_on_diff and not same) or (stop_on_same and same):
            return e
    return n


def f24(waits=WAITS, parities=PARITIES):
    """The string and block forms (see the comment above)."""
    from .forms import F24_MOV_CW, F24_PATTERN_STORE, f24_form_name
    variants = []
    kind = F24_KIND

    def add(name, series, x, baseline, op=None, width=None, rep=None, n=None, k=None,
            align="even", pattern=False, drain=0, form=None):
        regs = _f24_regs(align)
        pre = [F24_PATTERN_STORE] if pattern else []
        body = [Instr(0, FORMS[p].code, p, "x") for p in pre]
        body += [LS(), M(0, kind)]
        idx = 0
        for name_x in x:
            if name_x == "D":
                body.append(D(len([i for i in body if i.role == "drain"])))
                continue
            body.append(X(name_x, idx))
            idx += 1
        body += [M(1, kind), LS(), END()]
        iters = (None if form is None else
                 (k or 1) * _f24_iters(op, width, rep, n, pattern))
        knobs = {"series": series, "marker": kind, "op": op, "width": width, "rep": rep,
                 "n": n, "k": k, "iters": iters, "align": align, "pattern": pattern,
                 "drain": drain, "form": form, "x": [v for v in x if v != "D"], "pre": pre,
                 "ix": regs["IX"], "iy": regs["IY"], "baseline": baseline}
        variants.append((f"{kind}-{name}", knobs, body, {"regs": regs}))

    add("empty", "empty", [], None)
    w_tag = {1: "b", 2: "w"}
    for op in ("movbk", "cmpbk", "stm", "ldm", "cmpm", "inm", "outm"):
        for width in (1, 2):
            form = f24_form_name(op, width)
            for k in F24_S_K:
                add(f"s-{op}-{w_tag[width]}-k{k}", "s", [form] * k, "empty", op, width,
                    None, None, k, form=form)
    r_n = {n: F24_R_X for n in F24_R_N}
    r_n[F24_R_LONG[0]] = F24_R_LONG[1]
    for n, xs_ in r_n.items():
        cw = F24_MOV_CW[n]
        add(f"r-movcw-n{n}", "r", [cw], None, n=n)
        for rep, op, width in xs_:
            form = f24_form_name(op, width, rep)
            add(f"r-{rep}-{op}-{w_tag[width]}-n{n}", "r", [cw, form], f"r-movcw-n{n}", op,
                width, rep, n, 1, form=form)
    for rep, op, align in F24_A_X:
        form = f24_form_name(op, 2, rep)
        for n in F24_A_N:
            add(f"a-{rep}-{op}-w-n{n}-{align}", "a", [F24_MOV_CW[n], form], f"r-movcw-n{n}",
                op, 2, rep, n, 1, align=align, form=form)
    add("t-pat-empty", "t", [], None, pattern=True)
    for width, ns in F24_T_N.items():
        for rep, op, pattern in F24_T_X:
            form = f24_form_name(op, width, rep)
            for n in ns:
                add(f"t-{rep}-{op}-{w_tag[width]}-n{n}-{'pat' if pattern else 'fill'}", "t",
                    [F24_MOV_CW[n], form], f"r-movcw-n{n}", op, width, rep, n, 1,
                    pattern=pattern, form=form)
    cw = F24_MOV_CW[F24_D_CW]
    for d in F24_D_N:
        if d:
            add(f"d-movcw-n{F24_D_CW}-d{d}", "d", [cw] + ["D"] * d, None, n=F24_D_CW, drain=d)
        for rep, op, width in F24_D_X:
            form = f24_form_name(op, width, rep)
            add(f"d-{rep}-{op}-{w_tag[width]}-n{F24_D_CW}-d{d}", "d", [cw] + ["D"] * d + [form],
                f"d-movcw-n{F24_D_CW}-d{d}" if d else f"r-movcw-n{F24_D_CW}", op, width, rep,
                F24_D_CW, 1, drain=d, form=form)
    return _sweep("F24", variants, waits, parities, marker_kind=kind, rfm=F24_RFM)


FAMILIES.update({"F24": f24})
# (WP66) F24 was generator-only until the simulator learned the string forms; (WP67) the
# simulator runs them (sim/templates.py, _string_steps): F24 is modelled.


# F30 (WP73: the facts-only shapes the thirty-ninth and fortieth fits left, docs/v35s-chains.md
# "The thirty-ninth fit" Misses left and "The fortieth fit" Facts left), refresh off (RFM ECh),
# every wait and parity. Each probe varies one thing against a control in the frame
# PAD LS [pre] M0 X M1 LS END; pre (NOPs between the first LS and M0) only in the br probe.
# Run ids F30-<frame>-<probe>-<label>-p<E|O>-w<N>, frame out (OUT 20h+i,AL), push (PUSH AW) or
# store (MOV [0C00h],AW, br only); the empty frame of each is the dM baseline.
#
# str (shape 1, REP INM / OUTM at pE w1/w2: one wait clock of the second, back-to-back refill
#   fetch counts in the first element's position, STM's none). OUT marker, the F24 presets
#   (IX 0A40h, IY 0C40h, DW 0040h). REP INM, REP OUTM, REP STM after MOV CW,n for n = 0, 1, 2
#   (word) and n = 1 (byte, lead l0 only), each behind six leads that change the refill the
#   form starts beside: l0 (M0 MOV CW,n REP X, F24's r cell), d (a drainer MOV AW,1234h
#   before MOV CW,n), d4 (ADD DW,0, the 4-byte drainer that keeps the port, before it), nop1
#   and nop2 (one and two NOPs between MOV CW,n and the REP form) and sep (SHL AW,8 between
#   MOV CW,n and the REP form: the refill completes under the shift, so no refill fetch is
#   back to back in the form's window). Ids out-str-<op>-<b|w>-n<n>-<lead>.
# odd (shape 2, the odd last operand at w0: the fetch after a split last write a clock later
#   at w0 only). OUT marker, F24 presets with IX and / or IY odd. Every REP form with IX odd
#   alone and IY odd alone wherever it has that operand (MOVBK, CMPBK both, STM IY, CMPM IY,
#   LDM IX, OUTM IX, INM IY) and MOVBK / CMPBK both odd, n = 1, 2, nothing after (end); then
#   for STM-iy, INM-iy, MOVBK-iy, CMPBK-ixiy and the controls LDM-ix, CMPM-iy at n = 1 the
#   form followed by NOP (nop), MOV AW,DW (reg), MOV AW,[BW] (ld), and for the non-compares
#   MOV CW,1 then the same REP form again (rep: a second stream, still odd); STM-iy also at
#   n = 2 with nop and rep. Ids out-odd-<op>-<align>-n<n>-<follower>.
# seg (F25 E: the M0 OUT's I/O a clock later at pE when 8E follows it; MOV [BW],DS0 at pO
#   storing a clock late). OUT and PUSH frames: 8E with every legal sreg field from AW
#   (DS1, SS, DS0) and from memory ([IX] for all three, [BW] for DS1 as F25), 8C with every
#   sreg to AW and to [BW]; n = 0, NOP between the marker and the form (n = 1) for the 8E
#   forms and MOV [BW],DS1 / DS0, k = 2 for the three 8E register forms; PUSH SS ; POP SS.
#   Ids <frame>-seg-<8e|8c>-<dst>-<src>-n<n>[-k2], <frame>-seg-pair-ss-n0.
# br (F23 A, BR short under OUT at pO: the model's extra fetch at the I/O's end). OUT frame:
#   BR short +n (the n NOPs skipped) for n = 0..3 behind a NOP (nop), BR near +0 / +1 behind
#   a NOP, BR short +0 / +1 with one and two NOPs before the marker (pad1, pad2: M0 and BR one
#   and two bytes later, so BR's address parity flips against l0 with the same frame; the
#   model starts BR on the I/O's issue clock with room 3 in every pad cell), and BR short +0
#   bare (l0,
#   F23's cell); the MOV-direct frame: BR short +n, n = 0..3, and +0 behind a NOP. Ids
#   <frame>-br-<short|near>-n<n>-<lead>.
# nt (F23 C/D, BNE and DBNZ not taken). OUT and PUSH frames: CMP AW,AW then BNE +0 k times
#   then n NOPs (k = 1: n = 0..3; k = 2: n = 0, 2; k = 3: n = 0); MOV CW,1 ; DBNZ +0 then n
#   NOPs (n = 0..3) and the pair twice (k = 2). Ids <frame>-nt-<bne|dbnz>-k<k>-n<n>.
# cr (F23 E, callret). OUT and PUSH frames: CALL +2 ; BR +(a+1) ; NOP^a ; RET ; NOP^b, run
#   CALL, NOP^a, RET, BR, NOP^b: a NOPs between the CALL's target and the RET, b after the
#   BR's target, (a, b) = (0, 0) (F23's callret), (1, 0), (2, 0), (0, 1), (0, 2); and shl8,
#   SHL AW,8 in place of the NOPs (CALL +2 ; BR +4 ; SHL AW,8 ; RET), so the RET starts from
#   a full queue, its return address pushed long before (a RET after a PUSH imm16 needs a
#   per-parity absolute address, which breaks the pE / pO byte identity, and the model's RET
#   takes its address from a CALL). Ids <frame>-cr-a<a>-b<b>, <frame>-cr-shl8.
# lea (F25 B and C, LDEA). OUT and PUSH frames: LDEA AW,m behind a NOP (nopb: the parity
#   flipped inside the frame) for [BW], [BW+IX], [BW+10h], [BW+200h], [BW+IX+200h], [0C00h];
#   followed by a NOP (nopa) for [BW], [BW+200h], [0C00h]; alone (k1) for those three;
#   k = 2 for [BP+200h] and [BW+IX+200h]; [BW] behind a drainer D (MOV AW,1234h) and D4
#   (ADD DW,1234h). Ids <frame>-lea-<mode>-<shape>.
# Knobs: probe, series (= probe), marker, n, k, form (the probed form, None for the empty
# frame), x (every X form in chain order), exec (the X indices in execution order), rfm,
# refresh_on, and per probe: str/odd op, width, rep, lead / follower, align, iters (the
# elements the string forms run in all), ix, iy; seg opcode, sreg, operand; br branch, lead,
# pre; nt branch; cr a, b; lea mode, shape.
F30_RFM = RFM_OFF
F30_STR_X = (("rep", "inm"), ("rep", "outm"), ("rep", "stm"))
F30_STR_LEADS = ("l0", "d", "d4", "nop1", "nop2", "sep")
F30_STR_CELLS = ((2, 0), (2, 1), (2, 2))      # (width, n) at every lead; byte n = 1 at l0
F30_ODD_ALL = (("rep", "movbk", "ix"), ("rep", "movbk", "iy"), ("rep", "movbk", "ixiy"),
               ("repe", "cmpbk", "ix"), ("repe", "cmpbk", "iy"), ("repe", "cmpbk", "ixiy"),
               ("rep", "stm", "iy"), ("repne", "cmpm", "iy"), ("rep", "ldm", "ix"),
               ("rep", "outm", "ix"), ("rep", "inm", "iy"))
F30_ODD_N = (1, 2)
F30_ODD_FOLLOW_X = (("rep", "stm", "iy"), ("rep", "inm", "iy"), ("rep", "movbk", "iy"),
                    ("repe", "cmpbk", "ixiy"), ("rep", "ldm", "ix"), ("repne", "cmpm", "iy"))
F30_ODD_FOLLOW = {"nop": ["nop"], "reg": ["mov_aw_dw"], "ld": ["ld_bw"]}
F30_SEG_8E = {"8e-ds1-aw": "mov_ds1_aw", "8e-ss-aw": "mov_ss_aw", "8e-ds0-aw": "mov_ds0_aw",
              "8e-ds1-bw": "mov_ds1_m", "8e-ds1-ix": "mov_ds1_ix", "8e-ss-ix": "mov_ss_ix",
              "8e-ds0-ix": "mov_ds0_ix"}
F30_SEG_8C = {"8c-aw-ds1": "mov_aw_ds1", "8c-aw-ps": "mov_aw_ps", "8c-aw-ss": "mov_aw_ss",
              "8c-aw-ds0": "mov_aw_ds0", "8c-bw-ds1": "mov_m_ds1", "8c-bw-ps": "mov_m_ps",
              "8c-bw-ss": "mov_m_ss", "8c-bw-ds0": "mov_m_ds0"}
F30_SEG_N1 = tuple(F30_SEG_8E) + ("8c-bw-ds1", "8c-bw-ds0")
F30_SEG_K2 = ("8e-ds1-aw", "8e-ss-aw", "8e-ds0-aw")
F30_BR_OUT = (tuple(("short", n, "nop") for n in range(4)) + tuple(("near", n, "nop") for n in (0, 1))
              + tuple(("short", n, f"pad{p}") for p in (1, 2) for n in (0, 1))
              + (("short", 0, "l0"),))
F30_BR_STORE = tuple(("short", n, "l0") for n in range(4)) + (("short", 0, "nop"),)
F30_NT_BNE = {1: (0, 1, 2, 3), 2: (0, 2), 3: (0,)}
F30_NT_DBNZ = {1: (0, 1, 2, 3), 2: (0,)}
F30_CR_AB = ((0, 0), (1, 0), (2, 0), (0, 1), (0, 2))
F30_LEA_NOPB = ("bw", "bw_ix", "bw_d8", "bw_d16", "bw_ix_d16", "dir")
F30_LEA_NOPA = ("bw", "bw_d16", "dir")
F30_LEA_K1 = ("bw", "bw_d16", "dir")
F30_LEA_K2 = ("bp_d16", "bw_ix_d16")
F30_LEA_DRAIN = ("d", "d4")


def _f30_instrs(names, start=0):
    """X / drainer instrs for a list of form names, "D" (MOV AW,1234h), "D4" (ADD DW,1234h)
    and "D4z" (ADD DW,0); X indices from start in order."""
    out, idx = [], start
    for name in names:
        if name == "D":
            out.append(D(0))
        elif name == "D4":
            out.append(D4(0))
        elif name == "D4z":
            out.append(Instr(0, blocks.drainer4_zero(), "D4", "drain"))
        else:
            out.append(X(name, idx))
            idx += 1
    return out


def f30(waits=WAITS, parities=PARITIES):
    """The facts-only shapes' probes str, odd, seg, br, nt, cr, lea (see the comment above)."""
    from .forms import F24_MOV_CW, F25_LDEA, f24_form_name
    rfm = F30_RFM
    by_kind = {"out": [], "push": [], "store": []}

    def add(kind, probe, label, names, n=0, k=1, form=None, pre=(), regs=None, exec_=None,
            **extra):
        xnames = [v for v in names if not v.startswith("D")]
        body = ([LS()] + _f30_instrs(pre) + [M(0, kind)]
                + _f30_instrs(names, start=len(pre)) + [M(1, kind), LS(), END()])
        knobs = {"probe": probe, "series": probe, "marker": kind, "n": n, "k": k,
                 "form": form, "x": list(pre) + xnames, "rfm": rfm, "refresh_on": False,
                 "exec": list(exec_ if exec_ is not None
                              else range(len(pre) + len(xnames))), **extra}
        name = f"{kind}-{probe}-{label}" if probe != "empty" else f"{kind}-empty"
        by_kind[kind].append((name, knobs, body, {"regs": regs} if regs else {}))

    for kind in by_kind:
        add(kind, "empty", "", [], k=0)
    wtag = {1: "b", 2: "w"}

    # str
    lead_names = {"l0": ([], []), "d": (["D"], []), "d4": (["D4z"], []),
                  "nop1": ([], ["nop"]), "nop2": ([], ["nop", "nop"]),
                  "sep": ([], ["shl_imm8"])}
    for rep, op in F30_STR_X:
        cells = [(lead, w, n) for lead in F30_STR_LEADS for w, n in F30_STR_CELLS]
        cells.append(("l0", 1, 1))
        for lead, width, n in cells:
            form = f24_form_name(op, width, rep)
            before, between = lead_names[lead]
            names = before + [F24_MOV_CW[n]] + between + [form]
            add("out", "str", f"{op}-{wtag[width]}-n{n}-{lead}", names, n=n, form=form,
                regs=_f24_regs("even"), op=op, width=width, rep=rep, lead=lead,
                align="even", iters=n, ix=_f24_regs()["IX"], iy=_f24_regs()["IY"])
    # odd
    for rep, op, align in F30_ODD_ALL:
        form = f24_form_name(op, 2, rep)
        for n in F30_ODD_N:
            regs = _f24_regs(align)
            add("out", "odd", f"{op}-{align}-n{n}-end", [F24_MOV_CW[n], form], n=n, form=form,
                regs=regs, op=op, width=2, rep=rep, follower="end", align=align, iters=n,
                ix=regs["IX"], iy=regs["IY"])
    for rep, op, align in F30_ODD_FOLLOW_X:
        form = f24_form_name(op, 2, rep)
        regs = _f24_regs(align)
        follows = dict(F30_ODD_FOLLOW)
        if op not in ("cmpbk", "cmpm"):
            follows["rep"] = [F24_MOV_CW[1], form]
        for n in (1, 2) if op == "stm" else (1,):
            for follower, after in follows.items():
                if n == 2 and follower not in ("nop", "rep"):
                    continue
                add("out", "odd", f"{op}-{align}-n{n}-{follower}", [F24_MOV_CW[n], form] + after,
                    n=n, form=form, regs=regs, op=op, width=2, rep=rep, follower=follower,
                    align=align, iters=n + (follower == "rep"), ix=regs["IX"], iy=regs["IY"])
    # seg
    for kind in ("out", "push"):
        for label, x in {**F30_SEG_8E, **F30_SEG_8C}.items():
            opc, dst, src = label.split("-")
            sreg, operand = (dst, src) if opc == "8e" else (src, dst)
            seg = dict(opcode=opc, sreg=sreg, operand="reg" if operand == "aw" else operand)
            add(kind, "seg", f"{label}-n0", [x], form=x, **seg)
            if label in F30_SEG_N1:
                add(kind, "seg", f"{label}-n1", ["nop", x], n=1, form=x, **seg)
            if label in F30_SEG_K2:
                add(kind, "seg", f"{label}-n0-k2", [x, x], k=2, form=x, **seg)
        add(kind, "seg", "pair-ss-n0", ["push_ss", "pop_ss"], form="push_ss", opcode="pair",
            sreg="ss", operand="stack")
    # br
    for kind, cells in (("out", F30_BR_OUT), ("store", F30_BR_STORE)):
        for branch, n, lead in cells:
            form = f"br_n{n}" if branch == "short" else f"br_near_n{n}"
            pre = ["nop"] * int(lead[3:]) if lead.startswith("pad") else []
            lead_x = ["nop"] if lead == "nop" else []
            names = lead_x + [form] + ["nop"] * n
            first = len(pre)
            exec_ = list(range(first + len(lead_x) + 1))
            add(kind, "br", f"{branch}-n{n}-{lead}", names, n=n, form=form, pre=pre,
                exec_=exec_, branch=branch, lead=lead, skipped=n)
    # nt
    for kind in ("out", "push"):
        for k, ns in F30_NT_BNE.items():
            for n in ns:
                add(kind, "nt", f"bne-k{k}-n{n}", [F23_CMP] + ["bne_n0"] * k + ["nop"] * n,
                    n=n, k=k, form="bne_n0", branch="bne", skipped=0)
        for k, ns in F30_NT_DBNZ.items():
            for n in ns:
                add(kind, "nt", f"dbnz-k{k}-n{n}", ["mov_cw_imm1", "dbnz_n0"] * k + ["nop"] * n,
                    n=n, k=k, form="dbnz_n0", branch="dbnz", skipped=0)
    # cr
    for kind in ("out", "push"):
        for a, b in F30_CR_AB:
            names = ["call_n2", f"br_n{a + 1}"] + ["nop"] * a + ["ret"] + ["nop"] * b
            exec_ = [0] + list(range(2, 3 + a)) + [1] + list(range(3 + a, 3 + a + b))
            add(kind, "cr", f"a{a}-b{b}", names, form="ret", exec_=exec_, a=a, b=b, skipped=0)
        add(kind, "cr", "shl8", ["call_n2", "br_n4", "shl_imm8", "ret"], form="ret",
            exec_=[0, 2, 3, 1], a="shl8", b=0, skipped=0)
    # lea
    for kind in ("out", "push"):
        def lea(mode, shape, names, k=1, n=0):
            add(kind, "lea", f"{mode}-{shape}", names, n=n, k=k, form=F25_LDEA[mode], mode=mode,
                shape=shape)
        for mode in F30_LEA_NOPB:
            lea(mode, "nopb", ["nop", F25_LDEA[mode]], n=1)
        for mode in F30_LEA_NOPA:
            lea(mode, "nopa", [F25_LDEA[mode], "nop"])
        for mode in F30_LEA_K1:
            lea(mode, "k1", [F25_LDEA[mode]])
        for mode in F30_LEA_K2:
            lea(mode, "k2", [F25_LDEA[mode]] * 2, k=2)
        lea("bw", "d", ["D", F25_LDEA["bw"]])
        lea("bw", "d4", ["D4", F25_LDEA["bw"]])
    return [c for kind in by_kind
            for c in _sweep("F30", by_kind[kind], waits, parities, marker_kind=kind, rfm=rfm)]


FAMILIES.update({"F30": f30})


# F31 (WP73 follow-up: the two controls F30's readings lacked), refresh off, the OUT marker, the
# F24 presets, every wait and parity; ids F31-out-<probe>-<label>-p<E|O>-w<N>, the empty frame
# the dM baseline; knobs as F30's.
# alf (shape 2's aligned-follower control): REP STM, INM, MOVBK, CMPBK (REPE), LDM, CMPM
#   (REPNE), word, IX and IY even, n = 1, followed by NOP (nop), MOV AW,DW (reg), MOV AW,[BW]
#   (ld) and, for the non-compares, MOV CW,1 and the same REP form (rep); STM also at n = 2
#   with nop and rep; STM and LDM at n = 1 with nothing after (end). Against F30's odd cells:
#   whether the next fetch the models put late after any follower needs an odd operand.
#   Ids out-alf-<op>-n<n>-<follower>.
# lone (shape 1's lone-fetch control): REP INM, OUTM, STM, word, n = 1, behind leads that leave
#   exactly one refill fetch, not back to back with another cycle, inside the REP form's setup
#   (the fortieth candidate's clock log): b<b>a<a> = b NOPs before MOV CW,1 and a NOPs between
#   it and the REP form; b1a4 (the lone fetch at pE, none at pO), b0a5 (lone at pE, back to
#   back at pO), b0a4 (lone at pO, none at pE), b2a4 (lone at pO, back to back at pE), at
#   w1 / w2 (w0 has no wait clock to absorb). Ids out-lone-<op>-w-n1-b<b>a<a>.
F31_ALF_X = (("rep", "stm"), ("rep", "inm"), ("rep", "movbk"), ("repe", "cmpbk"), ("rep", "ldm"),
             ("repne", "cmpm"))
F31_LONE_X = (("rep", "inm"), ("rep", "outm"), ("rep", "stm"))
F31_LONE_LEADS = ((1, 4), (0, 5), (0, 4), (2, 4))


def f31(waits=WAITS, parities=PARITIES):
    """F30's missing controls alf and lone (see the comment above)."""
    from .forms import F24_MOV_CW, f24_form_name
    kind, rfm, variants = "out", RFM_OFF, []
    regs = _f24_regs("even")

    def add(probe, label, names, n=0, form=None, **extra):
        xnames = [v for v in names if not v.startswith("D")]
        body = [LS(), M(0, kind)] + _f30_instrs(names) + [M(1, kind), LS(), END()]
        knobs = {"probe": probe, "series": probe, "marker": kind, "n": n, "k": 1, "form": form,
                 "x": xnames, "exec": list(range(len(xnames))), "rfm": rfm,
                 "refresh_on": False, **extra}
        name = f"{kind}-{probe}-{label}" if probe != "empty" else f"{kind}-empty"
        variants.append((name, knobs, body, {"regs": regs} if form else {}))

    add("empty", "", [])
    strx = dict(width=2, align="even", ix=regs["IX"], iy=regs["IY"])
    for rep, op in F31_ALF_X:
        form = f24_form_name(op, 2, rep)
        follows = dict(F30_ODD_FOLLOW)
        if op not in ("cmpbk", "cmpm"):
            follows["rep"] = [F24_MOV_CW[1], form]
        cells = [(1, f) for f in follows]
        if op == "stm":
            cells += [(2, "nop"), (2, "rep")]
        if op in ("stm", "ldm"):
            cells.append((1, "end"))
        for n, follower in cells:
            after = [] if follower == "end" else follows[follower]
            add("alf", f"{op}-n{n}-{follower}", [F24_MOV_CW[n], form] + after, n=n, form=form,
                op=op, rep=rep, follower=follower, iters=n + (follower == "rep"), **strx)
    for rep, op in F31_LONE_X:
        form = f24_form_name(op, 2, rep)
        for b, a in F31_LONE_LEADS:
            add("lone", f"{op}-w-n1-b{b}a{a}", ["nop"] * b + [F24_MOV_CW[1]] + ["nop"] * a + [form],
                n=1, form=form, op=op, rep=rep, lead=f"b{b}a{a}", iters=1, **strx)
    return _sweep("F31", variants, waits, parities, marker_kind=kind, rfm=rfm)


FAMILIES.update({"F31": f31})


# F32 and F33 (WP74; HDL plan Phase E items 4 and 5: the 0F page and the register miscellany),
# refresh off (RFM ECh), every wait and parity. Generator-only until WP78 (UNMODELLED: the
# simulator decoded none of the new forms, forms.UNMODELLED_FORMS), acquired and read as facts;
# (WP78) modelled (sim/templates.py, the 0F page and the register miscellany; fit stage 16). The
# cost frame PAD [P] LS M0 [lead] X^k M1 LS END with the OUT marker for every variant and the
# PUSH marker for a subset (the F5 cross-check, the same ids with push for out); X's cost is
# dM(X) - dM(baseline), the baseline named by the knob `baseline` (the x_variant of the chain
# whose frame holds X's lead alone: the empty frame, MOV CL,n, the multiply / divide lead,
# STC / CLC ; MOV CW,n), k = 1, 2 (INC / DEC r16 also 4). P (before the first LS, erased by
# the fence) only in F33's pattern cells. The fence leaves AW = 0 and CW = 001Fh; the presets
# are the defaults (BW 0800h, DW 5678h, IX 0100h, IY 0180h) except where a form names IX /
# IY (forms' needs: IX = 0A40h, IY = 0C40h, F24's), and F16's div_m (DW = 0100h, overwritten
# by the lead). Memory operands are in the data page (the 90h fill, packed BCD 90).
# Run ids F3x-<out|push>-<label>-p<E|O>-w<N>, the label the form name, its lead / count and
# k (F32-out-set1_mw_cl-k2, F32-out-add4s-n8-k1, F33-out-divu_m-ld-k2,
# F33-out-repc-cmpm-w-n4-stc). Knobs on every chain: group (= series), marker, form (the
# measured X, None for a control), x (every form between M0 and M1 in order), k, lead (the
# forms before X in the frame), pre (the forms before the first LS), baseline, and per group
# the form's properties (op, operand, width, index / n / iters / rep / pattern / mode).
#
# F32 (the 0F page):
# bit: TEST1 / CLR1 / SET1 / NOT1 on AL / AW and at [BW], byte and word, the index in CL (31,
#   masked to bit 7 / 15) and as imm3 / imm4 (the same bit), k = 1, 2 (32 forms).
# mode: SET1 [m],CL word at [BW+10h], [BW+200h], [BW+IX] (0900h) and [0C00h], k = 1 (the mode
#   sweep's representative; [BW] is the bit group's).
# bcd: MOV CL,n ; ADD4S / SUB4S / CMP4S for n = 2, 4, 8, 16 digits (1, 2, 4, 8 byte pairs),
#   k = 1, and k = 2 at n = 2, 4; controls MOV CL,n alone. IX 0A40h, IY 0C40h.
# rot4: ROL4 / ROR4 on DL and at [BW] (byte), k = 1, 2.
# bitfield: EXT and INS, register width (0F 33 / 0F 31) and imm4 width (0F 3B / 0F 39), offset
#   in BL (0), DL (8) or BH (8) with DW = 0608h, the seven (offset, width) cases of
#   forms.F32_BITFIELD, k = 1, 2 (the second instance at the offset and IX / IY the first
#   leaves). EXT reads DS0:IX (0A40h), INS reads and writes DS1:IY (0C40h).
# pfx: DS1: (26h) before TEST1 [BW],CL word, SET1 [BW],7 byte, ROL4 [BW], and ADD4S after MOV
#   CL,4, k = 1.
# PUSH subset (k = 1): TEST1 / SET1 [BW],CL word, CLR1 AW,CL, NOT1 [BW],7 byte, MOV CL,4 and
#   ADD4S / CMP4S at n = 4, ROL4 [BW], ROR4 DL, EXT DL,7 and INS DL,7, the empty frame.
F32_RFM = RFM_OFF
F32_BCD_K2_N = (2, 4)
F32_PUSH = ("empty", "test1_mw_cl-k1", "set1_mw_cl-k1", "clr1_rw_cl-k1", "not1_mb_imm-k1",
            "movcl-n4", "add4s-n4-k1", "cmp4s-n4-k1", "rol4_m-k1", "ror4_dl-k1", "ext_dl_i7-k1",
            "ins_dl_i7-k1")


def _f3x_variants(family, out_specs, push_labels, waits, parities, rfm):
    """out_specs: [(label, group, names, pre, baseline, form, k, extra knobs)], every one under
    the OUT marker and those in push_labels under PUSH as well."""
    chains = []
    for kind in ("out", "push"):
        variants = []
        for label, group, names, pre, baseline, form, k, extra in out_specs:
            if kind == "push" and label not in push_labels:
                continue
            body = [Instr(0, FORMS[p].code, p, "x") for p in pre]
            body += [LS(), M(0, kind)] + xs(names) + [M(1, kind), LS(), END()]
            lead = list(names[:len(names) - k]) if form else list(names)
            knobs = {"group": group, "series": group, "marker": kind, "form": form,
                     "x": list(names), "k": k, "lead": lead, "pre": list(pre),
                     "baseline": baseline, "rfm": rfm, "refresh_on": False, **extra}
            variants.append((f"{kind}-{label}", knobs, body, {}))
        missing = set(push_labels) - {v[0][len(kind) + 1:] for v in variants}
        if kind == "push" and missing:
            raise AssertionError(f"{family}: PUSH labels without an OUT twin: {sorted(missing)}")
        chains += _sweep(family, variants, waits, parities, marker_kind=kind, rfm=rfm)
    return chains


def f32(waits=WAITS, parities=PARITIES):
    """The 0F page (see the comment above)."""
    from .forms import (F32_BCD, F32_BCD_N, F32_BIT, F32_BITFIELD, F32_MOV_CL, F32_PFX,
                        F32_SET1_MODES)
    specs = [("empty", "empty", [], (), None, None, 0, {})]
    for name, (op, operand, width, index) in F32_BIT.items():
        if name in F32_PFX or name.startswith("set1_mw_cl_"):
            continue
        for k in (1, 2):
            specs.append((f"{name}-k{k}", "bit", [name] * k, (), "empty", name, k,
                          dict(op=op, operand=operand, width=width, index=index)))
    for m in F32_SET1_MODES:
        name = f"set1_mw_cl_{m}"
        specs.append((f"{name}-k1", "mode", [name], (), "empty", name, 1,
                      dict(op="set1", operand="m", width=2, index="cl", mode=m)))
    for n in F32_BCD_N:
        cl = F32_MOV_CL[n]
        specs.append((f"movcl-n{n}", "bcd", [cl], (), "empty", None, 0, dict(n=n)))
        for op in ("add4s", "sub4s", "cmp4s"):
            for k in (1, 2) if n in F32_BCD_K2_N else (1,):
                specs.append((f"{op}-n{n}-k{k}", "bcd", [cl] + [op] * k, (), f"movcl-n{n}", op,
                              k, dict(op=op, n=n, bytes=(n + 1) // 2)))
    for name in ("rol4_dl", "ror4_dl", "rol4_m", "ror4_m"):
        for k in (1, 2):
            specs.append((f"{name}-k{k}", "rot4", [name] * k, (), "empty", name, k,
                          dict(op=name[:4], operand="m" if name.endswith("_m") else "r")))
    for name, (op, off, wid, imm) in F32_BITFIELD.items():
        for k in (1, 2):
            specs.append((f"{name}-k{k}", "bitfield", [name] * k, (), "empty", name, k,
                          dict(op=op, offset_reg=off, width_reg=wid, imm=imm)))
    for name in F32_PFX:
        if name in F32_BCD:
            specs.append((f"{name}-n4-k1", "pfx", [F32_MOV_CL[4], name], (), "movcl-n4", name,
                          1, dict(op="add4s", n=4, bytes=2)))
        else:
            specs.append((f"{name}-k1", "pfx", [name], (), "empty", name, 1, {}))
    return _f3x_variants("F32", specs, F32_PUSH, waits, parities, F32_RFM)


FAMILIES.update({"F32": f32})


# F33 (the register miscellany and REPC / REPNC):
# incdec: INC / DEC r16 (40-4F) for every register, k = 1, 2, 4; INC / DEC AL and DH (FE /0,
#   /1), INC / DEC byte and word [BW] (FE / FF /0 /1), k = 1, 2.
# adjust: ADJ4A, ADJ4S, ADJBA, ADJBS (AL = 0 after the fence), k = 1, 2.
# convert: CVTBD, CVTDB, k = 1, 2. extend: CVTBW (CBW), CVTWL (CWD) at AW = 0, k = 1, 2, and at
#   AW = 8080h behind MOV AW,8080h (k = 1; the control MOV AW,8080h alone).
# muldiv: behind the lead MOV AW,1234h ; MOV DW,0 (the control: the lead alone) MUL CW and MUL
#   [BW] (signed: 1234h x 001Fh, 1234h x 9090h), DIV / DIVU CW (0000:1234h / 001Fh = 150 rem
#   10; the second instance 000Ah:0096h / 001Fh = 21145) and DIV / DIVU [BW] (/ 9090h: 0 rem
#   1234h, then 1234h:0000h / 9090h, -10705 signed, 8252 unsigned), k = 1, 2, no divide
#   trap; MUL CW and MUL [BW] at AW = 0 (no lead), k = 1.
# mulimm: MUL AW,CW,1234h, MUL AW,[BW],1234h, MUL AW,CW,5, MUL AW,[BW],5, k = 1, 2.
# flag: CLC, STC, CMC, CLI, STI, CLD, STD, k = 1, 2.
# rep: STC or CLC ; MOV CW,n ; REPC / REPNC CMPM / CMPBK word for n = 1, 2, 4 (IX 0A40h, IY
#   0C40h): on the fill REPNC CMPM and REPC CMPBK stop after element 1 (the carry exit), REPC
#   CMPM and REPNC CMPBK run CW out; the patterns (P before the first LS): REPC CMPM with
#   [0C42h] = 0 and REPNC CMPBK with [0A42h] = 0 stop after element 2, n = 2 (with the count's
#   end) and 4, after CLC; n = 0 for REPC / REPNC CMPM after CLC. Controls: STC / CLC ; MOV
#   CW,n alone for every n, and each pattern store with the empty frame. iters counts the
#   compared elements (_f33_iters; test_chains checks it against normalize.string_elements).
# PUSH subset (k = 1): INC AW, DEC BW, INC AL, DEC [BW], ADJ4A, CVTBD, CVTWL, the muldiv lead,
#   MUL CW and DIVU [BW] behind it, MUL AW,CW,1234h, STC, CLC ; MOV CW,2 and REPC CMPM n = 2
#   after it, the empty frame.
F33_RFM = RFM_OFF
F33_R16_K = (1, 2, 4)
F33_LEAD = ["mov_aw_imm", "mov_dw_imm0"]
F33_REP_N = (1, 2, 4)
F33_PAT_N = (2, 4)
F33_PATTERN = {("repc", "cmpm"): ("dst", "st_imm0_dir_c42"), ("repnc", "cmpbk"): ("src", "st_imm0_dir_a42")}
F33_PUSH = ("empty", "inc_aw-k1", "dec_bw-k1", "inc_al-k1", "dec_m-k1", "adj4a-k1", "cvtbd-k1",
            "cvtwl-k1", "lead-muldiv", "mul_cw-ld-k1", "divu_m-ld-k1", "mul_aw_cw_imm16-k1",
            "stc-k1", "clc-movcw-n2", "repc-cmpm-w-n2-clc")


def _f33_iters(rep, op, n, pattern):
    """The elements REPC / REPNC CMPM / CMPBK word compare: n, or the carry exit. CMPM is
    AW (0) - [IY] (9090h fill, 0 at the dst pattern's element 2): CY = 1 except there; CMPBK
    [IX] - [IY] (fill - fill, 0 - 9090h at the src pattern's element 2): CY = 0 except
    there. REPC stops after an element with CY = 0, REPNC after one with CY = 1."""
    for e in range(1, n + 1):
        at_pattern = pattern and e == 2
        cy = (not at_pattern) if op == "cmpm" else at_pattern
        if (rep == "repc" and not cy) or (rep == "repnc" and cy):
            return e
    return n


def f33(waits=WAITS, parities=PARITIES):
    """The register miscellany and REPC / REPNC (see the comment above)."""
    from .forms import _R16, F24_MOV_CW, F33_FLAGS, f24_form_name
    specs = [("empty", "empty", [], (), None, None, 0, {})]

    def ks(group, names, kk=(1, 2), **extra):
        for name in names:
            for k in kk:
                specs.append((f"{name}-k{k}", group, [name] * k, (), "empty", name, k, extra))

    ks("incdec", [f"{op}_{r}" for op in ("inc", "dec") for r in _R16], F33_R16_K, operand="r16")
    ks("incdec", ["inc_al", "dec_al", "inc_dh", "dec_dh"], operand="r8")
    ks("incdec", ["incb_m", "decb_m", "inc_m", "dec_m"], operand="m")
    ks("adjust", ["adj4a", "adj4s", "adjba", "adjbs"])
    ks("convert", ["cvtbd", "cvtdb"])
    ks("extend", ["cvtbw", "cvtwl"], aw=0)
    specs.append(("lead-aw8080", "extend", ["mov_aw_8080"], (), "empty", None, 0, dict(aw=0x8080)))
    for name in ("cvtbw", "cvtwl"):
        specs.append((f"{name}-a8080-k1", "extend", ["mov_aw_8080", name], (), "lead-aw8080",
                      name, 1, dict(aw=0x8080)))
    specs.append(("lead-muldiv", "muldiv", list(F33_LEAD), (), "empty", None, 0, dict(aw=0x1234)))
    for name in ("mul_cw", "mul_m", "div_cw", "divu_cw", "div_m", "divu_m"):
        for k in (1, 2):
            specs.append((f"{name}-ld-k{k}", "muldiv", F33_LEAD + [name] * k, (), "lead-muldiv",
                          name, k, dict(aw=0x1234)))
    for name in ("mul_cw", "mul_m"):
        specs.append((f"{name}-k1", "muldiv", [name], (), "empty", name, 1, dict(aw=0)))
    ks("mulimm", ["mul_aw_cw_imm16", "mul_aw_m_imm16", "mul_aw_cw_imm8", "mul_aw_m_imm8"])
    ks("flag", list(F33_FLAGS))
    for lead in ("stc", "clc"):
        for n in F33_REP_N + ((0,) if lead == "clc" else ()):
            specs.append((f"{lead}-movcw-n{n}", "rep", [lead, F24_MOV_CW[n]], (), "empty", None,
                          0, dict(n=n, carry_lead=lead)))
    for rep in ("repc", "repnc"):
        for op in ("cmpm", "cmpbk"):
            form = f24_form_name(op, 2, rep)
            cells = [(lead, n, False) for lead in ("stc", "clc") for n in F33_REP_N]
            if op == "cmpm":
                cells.append(("clc", 0, False))
            if (rep, op) in F33_PATTERN:
                cells += [("clc", n, True) for n in F33_PAT_N]
            for lead, n, pattern in cells:
                where, store = F33_PATTERN.get((rep, op), (None, None)) if pattern else (None, None)
                specs.append((f"{rep}-{op}-w-n{n}-{lead}" + ("-pat" if pattern else ""), "rep",
                              [lead, F24_MOV_CW[n], form], (store,) if pattern else (),
                              f"{lead}-movcw-n{n}", form, 1,
                              dict(op=op, width=2, rep=rep, n=n, carry_lead=lead,
                                   pattern=where, iters=_f33_iters(rep, op, n, pattern))))
    for where, store in (("dst", "st_imm0_dir_c42"), ("src", "st_imm0_dir_a42")):
        specs.append((f"pat-{where}-empty", "rep", [], (store,), "empty", None, 0,
                      dict(pattern=where)))
    return _f3x_variants("F33", specs, F33_PUSH, waits, parities, F33_RFM)


FAMILIES.update({"F33": f33})
# (WP74) F32 and F33 were generator-only (facts, no model); (WP78) modelled: UNMODELLED stays ()


# F34 (WP80: probes for the forty-second fit's miss shapes, designed as F30 was: per shape one
# probe that varies one thing against a control), refresh off (RFM ECh), every wait and parity,
# the OUT marker with a PUSH subset; ids F34-<out|push>-<probe>-<label>-p<E|O>-w<N>. The frame is
# PAD LS M0 <lead> X^k <follow> M1 LS END; the leads (forms between M0 and X, shared by every
# probe): l0 none, nop / nop2 / nop3 one to three NOPs (X a byte later per NOP, a fetch in
# flight at X's start), d / d2 / d3 one to three MOV AW,1234h (B8 34 12, the F6 drainer: the
# queue drained by 3 bytes each), sep SHL AW,8 (C1 E0 08: a long EU form that lets the queue
# fill before X), cl MOV CL,4 (B1 04: CL written just before a CL-index form). The controls in
# every probe: the empty frame and each lead alone (probe lead, ids <marker>-lead-<lead>), the
# baseline (knob baseline) of every chain whose X has that lead. Every byte string is one the
# earlier families already run (forms.F34_FORMS adds CMP AW,DW, a reg form as CMP AW,AW).
# bf (the bit fields' +-1: at pE the model's word read before silicon's back-to-back refill
#   fetch, at pO the imm forms' late successor opcode). EXT BL,DH (0F 33, offset 0, width 6,
#   within a word), EXT DL,BH (offset 8, width 8, crossing), EXT BL,7 (0F 3B, within), EXT
#   DL,11 (crossing), and the same four INS (0F 31 / 0F 39); DW = 0608h, IX 0A40h, IY 0C40h
#   (the F32 presets): behind every lead l0, nop, nop2, d, sep at k = 1, and k = 2 behind a NOP;
#   for the within-word forms also followed by a NOP (fnop), MOV AW,DW (freg) or MOV AW,[0C00h]
#   (fld: the direct load, as the bit field leaves BL, the offset register, at 7 or 8, so [BW]
#   would read 0807h or 0808h). Ids <marker>-bf-<form>-<lead>-k<k>[-f<follow>].
# rbit (the register bit ops: the CL index at pO, silicon's back-to-back fetch the room rule
#   does not raise; the k = 2 second-instance offsets). SET1 AL,CL / AW,CL / AL,7 / AW,15 behind
#   l0, nop, nop2, d, sep at k = 1; k = 2 behind l0 and nop; the pair with a NOP between (gap);
#   the CL forms behind MOV CL,4 (cl); TEST1 AW,CL behind l0 and sep and at k = 2 (the op
#   control). Ids <marker>-rbit-<form>-<lead>-k<k>[-gap].
# mbit (the memory bit ops' parity- and wait-dependent misses). TEST1 / SET1 / CLR1 [BW],CL
#   word, SET1 / CLR1 [BW],15 word: behind l0, nop, nop2, d, sep at k = 1, k = 2 and the pair with
#   a NOP between; SET1 [m],CL word in [BW+10h], [BW+200h], [BW+IX], [0C00h] behind l0, nop, d
#   (the mode against the lead); SET1 [BW],CL byte behind l0 and nop (the width control).
# inc (INC / DEC r16 and the flag forms: -1 on the first fetch after the OUT at pE, -4 at
#   k = 2). OUT ; INC AW^k ; NOP^n for k = 1..4, n = 0..2; behind a NOP for k = 1..4 (n = 0);
#   CLC^k ; NOP^n for k = 1, 2, n = 0, 1. The NOP trains (lead nop..nop3) are the controls.
#   Ids <marker>-inc-<form>-<lead>-k<k>-n<n>.
# mul (MUL imm memory at pE: silicon fetches near the end). MUL AW,[BW],5 (6B 07 05) and MUL
#   AW,[BW],1234h (69 07 34 12) behind l0, nop, nop2, d, sep at k = 1 and k = 2 behind l0, nop;
#   the register form MUL AW,CW,5 behind l0 (the control without a read).
# nt (BNE / DBNZ not taken, and BE). CMP AW,AW ; BNE +0 (bne), MOV CW,1 ; DBNZ +0 (dbnz), CMP
#   AW,DW ; BE +0 (be, not taken: Z = 0), and the twin CMP AW,AW ; MOV AW,DW (twin: the same
#   lengths, no branch) behind l0, the drainers d, d2, d3 (the queue at known fill levels) and
#   the NOP trains nop, nop2, nop3 (a fetch in flight at the start); BE also twice (k = 2).
#   Ids <marker>-nt-<branch>-<lead>-k<k>.
# cr (the RET's refill from a full queue: F30 cr shl8 -1 at every cell). CALL +2 ; BR +(f+1) ;
#   <filler of f bytes> ; RET behind l0 or a NOP (the RET's target, the BR after the CALL, at
#   chain offset 3 or 4: both target parities in each chain parity), the filler none, NOP,
#   SHL AW,8, SHL AW,8 ; NOP, NOP ; SHL AW,8, SHL AW,4 (the RET's own address and the queue's
#   fill at its start varied against the target's). Ids <marker>-cr-<filler>-<lead>.
# PUSH subset: the empty frame, lead nop; bf EXT BL,DH and EXT BL,7 behind l0 / nop; rbit SET1
#   AW,CL and AW,15 behind l0 / nop; mbit TEST1 and SET1 [BW],CL behind l0 / nop; inc INC AW
#   k = 1, 2 and behind a NOP; mul MUL AW,[BW],5 behind l0 / nop and AW,[BW],1234h behind l0;
#   nt bne, dbnz, be behind l0 / nop and the twin behind l0; cr none, nop, shl8, shl8nop behind
#   l0 / nop.
# Knobs: probe, series (= probe), marker, form (the probed X, None for a control), x (every X
#   form in chain order), k, lead and follow (form lists), lead_name, follow_name, baseline (the
#   x_variant of the lead alone, or empty), exec (X indices in execution order), skipped, rfm,
#   refresh_on, and per probe op / operand / width / index / mode (bit ops), op / cross / imm
#   (bit fields), n (NOPs after INC), branch (nt), filler / target (cr: the RET target's chain
#   offset).
F34_RFM = RFM_OFF
F34_LEADS = {"l0": [], "nop": ["nop"], "nop2": ["nop"] * 2, "nop3": ["nop"] * 3,
             "d": ["mov_aw_imm"], "d2": ["mov_aw_imm"] * 2,
             "d3": ["mov_aw_imm"] * 3, "sep": ["shl_imm8"], "cl": ["mov_cl_imm"]}
F34_STD_LEADS = ("l0", "nop", "nop2", "d", "sep")
F34_FOLLOW = {"nop": ["nop"], "reg": ["mov_aw_dw"], "ld": ["ld_dir"]}
F34_BF = ("ext_bl_dh", "ext_dl_bh", "ext_bl_i7", "ext_dl_i11",
          "ins_bl_dh", "ins_dl_bh", "ins_bl_i7", "ins_dl_i11")
F34_BF_FOLLOW = ("ext_bl_dh", "ext_bl_i7", "ins_bl_dh", "ins_bl_i7")
F34_RBIT = ("set1_rb_cl", "set1_rw_cl", "set1_rb_imm", "set1_rw_imm")
F34_MBIT = ("test1_mw_cl", "set1_mw_cl", "clr1_mw_cl", "set1_mw_imm", "clr1_mw_imm")
F34_MBIT_MODES = ("bw_d8", "bw_d16", "bw_ix", "dir")
F34_MUL = ("mul_aw_m_imm8", "mul_aw_m_imm16")
F34_NT = {"bne": ["cmp_aw_aw", "bne_n0"], "dbnz": ["mov_cw_imm1", "dbnz_n0"],
          "be": ["cmp_aw_dw", "be_n0"], "twin": ["cmp_aw_aw", "mov_aw_dw"]}
F34_NT_LEADS = ("l0", "d", "d2", "d3", "nop", "nop2", "nop3")
F34_CR_FILL = {"none": [], "nop": ["nop"], "shl8": ["shl_imm8"], "shl8nop": ["shl_imm8", "nop"],
               "nopshl8": ["nop", "shl_imm8"], "shl4": ["shl_imm4"]}
F34_PUSH = {"lead-nop", "bf-ext_bl_dh-l0-k1", "bf-ext_bl_dh-nop-k1", "bf-ext_bl_i7-l0-k1",
            "bf-ext_bl_i7-nop-k1", "rbit-set1_rw_cl-l0-k1", "rbit-set1_rw_cl-nop-k1",
            "rbit-set1_rw_imm-l0-k1", "rbit-set1_rw_imm-nop-k1", "mbit-test1_mw_cl-l0-k1",
            "mbit-test1_mw_cl-nop-k1", "mbit-set1_mw_cl-l0-k1", "mbit-set1_mw_cl-nop-k1",
            "inc-inc_aw-l0-k1-n0", "inc-inc_aw-l0-k2-n0", "inc-inc_aw-nop-k1-n0",
            "mul-mul_aw_m_imm8-l0-k1", "mul-mul_aw_m_imm8-nop-k1", "mul-mul_aw_m_imm16-l0-k1",
            "nt-bne-l0-k1", "nt-bne-nop-k1", "nt-dbnz-l0-k1", "nt-dbnz-nop-k1", "nt-be-l0-k1",
            "nt-be-nop-k1", "nt-twin-l0-k1", "cr-none-l0", "cr-none-nop", "cr-nop-l0",
            "cr-nop-nop", "cr-shl8-l0", "cr-shl8-nop", "cr-shl8nop-l0", "cr-shl8nop-nop"}


def _f34_specs():
    """[(label, knobs-without-marker, x names)] for the OUT frame, in family order."""
    from .forms import F32_BIT, F32_BITFIELD
    specs = []

    def add(probe, label, lead, xs_, k=1, form=None, follow=(), exec_=None, skipped=0, **extra):
        lead_names, follow_names = F34_LEADS[lead], list(follow)
        names = lead_names + list(xs_) + follow_names
        knobs = {"probe": probe, "series": probe, "form": form, "x": names, "k": k,
                 "lead": list(lead_names), "follow": follow_names, "lead_name": lead,
                 "baseline": None if probe in ("empty", "lead") else
                 ("empty" if lead == "l0" else f"lead-{lead}"),
                 "exec": list(exec_ if exec_ is not None else range(len(names))),
                 "skipped": skipped, "rfm": F34_RFM, "refresh_on": False, **extra}
        specs.append((label if probe == "empty" else f"{probe}-{label}", knobs, names))

    add("empty", "empty", "l0", [], k=0)
    for lead in ("nop", "nop2", "nop3", "d", "d2", "d3", "sep", "cl"):
        add("lead", lead, lead, [], k=0)
    # bf
    for form in F34_BF:
        op, off, wid, imm = F32_BITFIELD[form]
        bf = dict(op=op, imm=imm is not None, follow_name=None)
        cells = [(lead, 1, None) for lead in F34_STD_LEADS] + [("nop", 2, None)]
        if form in F34_BF_FOLLOW:
            cells += [("l0", 1, f) for f in F34_FOLLOW]
        for lead, k, f in cells:
            add("bf", f"{form}-{lead}-k{k}" + (f"-f{f}" if f else ""), lead, [form] * k, k=k,
                form=form, follow=F34_FOLLOW[f] if f else (), **{**bf, "follow_name": f})
    # rbit
    for form in F34_RBIT + ("test1_rw_cl",):
        op, operand, width, index = F32_BIT[form]
        bit = dict(op=op, operand=operand, width=width, index=index)
        if form == "test1_rw_cl":
            cells = [("l0", 1, False), ("sep", 1, False), ("l0", 2, False)]
        else:
            cells = ([(lead, 1, False) for lead in F34_STD_LEADS]
                     + [("l0", 2, False), ("nop", 2, False), ("l0", 2, True)]
                     + ([("cl", 1, False)] if index == "cl" else []))
        for lead, k, gap in cells:
            xs_ = [form, "nop", form] if gap else [form] * k
            add("rbit", f"{form}-{lead}-k{k}" + ("-gap" if gap else ""), lead, xs_, k=k,
                form=form, gap=gap, **bit)
    # mbit
    for form in F34_MBIT:
        op, operand, width, index = F32_BIT[form]
        bit = dict(op=op, operand=operand, width=width, index=index, mode="bw")
        cells = ([(lead, 1, False) for lead in F34_STD_LEADS]
                 + [("l0", 2, False), ("l0", 2, True)])
        for lead, k, gap in cells:
            xs_ = [form, "nop", form] if gap else [form] * k
            add("mbit", f"{form}-{lead}-k{k}" + ("-gap" if gap else ""), lead, xs_, k=k,
                form=form, gap=gap, **bit)
    for m in F34_MBIT_MODES:
        form = f"set1_mw_cl_{m}"
        for lead in ("l0", "nop", "d"):
            add("mbit", f"{form}-{lead}-k1", lead, [form], form=form, gap=False, op="set1",
                operand="m", width=2, index="cl", mode=m)
    for lead in ("l0", "nop"):
        add("mbit", f"set1_mb_cl-{lead}-k1", lead, ["set1_mb_cl"], form="set1_mb_cl", gap=False,
            op="set1", operand="m", width=1, index="cl", mode="bw")
    # inc
    cells = ([("inc_aw", "l0", k, n) for k in (1, 2, 3, 4) for n in (0, 1, 2)]
             + [("inc_aw", "nop", k, 0) for k in (1, 2, 3, 4)]
             + [("clc", "l0", k, n) for k in (1, 2) for n in (0, 1)])
    for form, lead, k, n in cells:
        add("inc", f"{form}-{lead}-k{k}-n{n}", lead, [form] * k, k=k, form=form,
            follow=["nop"] * n, n=n)
    # mul
    for form in F34_MUL:
        for lead, k in [(lead, 1) for lead in F34_STD_LEADS] + [("l0", 2), ("nop", 2)]:
            add("mul", f"{form}-{lead}-k{k}", lead, [form] * k, k=k, form=form, operand="m")
    add("mul", "mul_aw_cw_imm8-l0-k1", "l0", ["mul_aw_cw_imm8"], form="mul_aw_cw_imm8",
        operand="r")
    # nt
    for branch, pair in F34_NT.items():
        cells = [(lead, 1) for lead in F34_NT_LEADS]
        if branch == "be":
            cells.append(("l0", 2))
        for lead, k in cells:
            add("nt", f"{branch}-{lead}-k{k}", lead, pair * k, k=k, form=pair[1], branch=branch)
    # cr
    for filler, fill in F34_CR_FILL.items():
        nbytes = sum(len(FORMS[f].code) for f in fill)
        for lead in ("l0", "nop"):
            lead_n = len(F34_LEADS[lead])
            body = ["call_n2", f"br_n{nbytes + 1}"] + fill + ["ret"]
            first = lead_n
            exec_ = (list(range(lead_n)) + [first] + list(range(first + 2, first + 3 + len(fill)))
                     + [first + 1])
            add("cr", f"{filler}-{lead}", lead, body, form="ret", exec_=exec_, filler=filler,
                target=lead_n + 3)
    return specs


def f34(waits=WAITS, parities=PARITIES):
    """The forty-second fit's miss shapes' probes bf, rbit, mbit, inc, mul, nt, cr (see the
    comment above)."""
    specs = _f34_specs()
    labels = {label for label, _, _ in specs}
    missing = F34_PUSH - labels
    if missing:
        raise AssertionError(f"F34: PUSH labels without an OUT twin: {sorted(missing)}")
    chains = []
    for kind in ("out", "push"):
        variants = []
        for label, knobs, names in specs:
            if kind == "push" and label not in F34_PUSH and label != "empty":
                continue
            body = [LS(), M(0, kind)] + xs(names) + [M(1, kind), LS(), END()]
            variants.append((f"{kind}-{label}", {**knobs, "marker": kind}, body, {}))
        chains += _sweep("F34", variants, waits, parities, marker_kind=kind, rfm=F34_RFM)
    return chains


FAMILIES.update({"F34": f34})


# F35 and F36 (WP87: two refresh-off coverage families). The census of forms.py's first bytes
# left 124 of 256 opcode bytes no family ran; the model's classes assume an untested form costs
# what its class's tested forms cost. Both families are the cost frame PAD LS M0 X M1 LS END,
# refresh off (RFM ECh), every wait and parity, the OUT and the PUSH marker (the PUSH frame on a
# subset where stated); X's cost is dM(X) - dM(baseline), the baseline the knob `baseline` names
# (the x_variant of the chain whose frame holds X's lead alone: the empty frame, a flag control,
# MOV CW,n, MOV BW,imm16). Generator-only: the simulator decodes few of the new forms
# (forms.UNMODELLED_FORMS), so both families are in UNMODELLED until a template learns them.
# Run ids F35-<out|push>-<series>-<label>-p<E|O>-w<N> and F36-<out|push>-<series>-<label>-...;
# the empty frame F3x-<marker>-empty. Knobs on every chain: series (= probe), marker, form (the
# measured X, None for a control), x (every X form in chain order), k, lead (the forms before X),
# baseline, exec (X indices in execution order, repeats included), skipped (X never executed,
# the NOPs a taken transfer jumps), taken (whether X transfers; None for a non-transfer), rfm,
# refresh_on; F35 adds cond / control / flags (cc), cw (cw, loop), target_rel (the transfer's
# target as an offset from the first X: ind, far).
#
# F35 (control flow completed; precedent F23). The register-indirect and far forms carry an
# absolute code offset (forms.F35_ABS), so their bytes depend on the pad and the marker's
# length: f35 builds each chain's body for its own parity, and a variant's pE and pO chains
# differ in that one form (test_chains checks the target, not the bytes).
# ctl: the empty frame and the three flag controls alone, CMP AW,AW (cmpaa: Z), CMP AW,DW
#   (cmpad: CY, S; AW = 0 after the fence) and ADD DW,2A01h (adddw: S, V, not P).
# cc: the sixteen conditional branches 70-7F, each taken and not taken, behind the control
#   forms.F35_CC names for that outcome, +n with n = 0, 2 (taken: n NOPs the branch jumps, never
#   executed; not taken: the NOPs run). Ids cc-<cond>-<t|nt>-n<n>. PUSH frame: n = 0.
# cw: BCWZ +0 / +2 after MOV CW,0 (taken) and +0 after MOV CW,1 (not taken); DBNZE +0 and
#   DBNZNE +0 after MOV CW,1 or MOV CW,2 and CMP AW,AW (Z = 1) or CMP AW,DW (Z = 0): DBNZE taken
#   at CW 2 with Z, DBNZNE at CW 2 without; controls MOV CW,0 / 1 alone and MOV CW,c ; CMP.
# loop: MOV CW,2 ; <body> ; DBNZ back over the body (E2 FD / FC), body NOP or MOV AW,DW: the body
#   and the DBNZ run twice (exec 0 1 2 1 2), the backward transfer once; controls MOV CW,2 ;
#   <body>.
# ret: RET imm16 as F23's callret: CALL +2 ; BR +3 ; RET 0 (C2 00 00, run 0 2 1) and PUSH AW ;
#   CALL +2 ; BR +3 ; RET 2 (the pushed word dropped by the immediate, run 0 1 3 2); F23's
#   CALL +2 ; BR +1 ; RET and PUSH AW alone as controls.
# ind: MOV BW,t ; CALL BW (FF D3) to the next instruction; MOV BW,t ; CALL BW ; BR +1 ; RET (t
#   the RET, run 0 1 3 2); MOV BW,t ; BR BW (FF E3) to the next instruction and over one NOP;
#   control MOV BW,0800h.
# far: BR far (EA t 1000h) to the next instruction and over one NOP; CALL far (9A t 1000h) to the
#   next instruction; CALL far ; BR +1 ; RET far (CB, run 0 2 1); PUSH AW ; CALL far ; BR +3 ;
#   RET far 2 (CA 02 00, run 0 1 3 2).
# Left out: memory-indirect transfers (the data fill is 9090h), BRK 3 / BRK imm8 / RETI (the
# vector table is zeroed and image.py has no hook for a family to set a vector word).
F35_RFM = RFM_OFF
F35_FAMILY_REGS = {}            # the default presets: the prelude's length is F35_PRELUDE_LEN


def _f35_flags_after(ctl):
    from .forms import F35_CONTROLS
    return dict(F35_CONTROLS[ctl][1])


def _f35_specs(first_x):
    """[(label, knobs-without-marker, x names, push)] for the frame whose first X sits at code
    offset first_x (the absolute targets), in family order."""
    from .forms import (F35_ABS_FORMS, F35_CC, F35_CC_N, F35_COND, F35_CONTROLS, f35_cc_form,
                        f35_cond_taken)
    specs = []

    def add(series, label, names, lead=0, baseline="empty", exec_=None, taken=None,
            push=True, form=None, **extra):
        names = list(names)
        ex = list(exec_ if exec_ is not None else range(len(names)))
        knobs = {"probe": series, "series": series, "form": form, "x": names,
                 "k": 1 if form else 0, "lead": names[:lead], "baseline": baseline,
                 "exec": ex, "skipped": len(names) - len(set(ex)), "taken": taken,
                 "rfm": F35_RFM, "refresh_on": False, **extra}
        specs.append((label if series == "empty" else f"{series}-{label}", knobs, names, push))

    def tgt(kind, rel):
        return F35_ABS_FORMS[kind][first_x + rel]

    add("empty", "empty", [], baseline=None)
    for ctl, (name, flags) in F35_CONTROLS.items():
        add("ctl", ctl, [name], flags=flags, control=ctl)
    for cond in F35_COND:
        for outcome, ctl in zip(("t", "nt"), F35_CC[cond]):
            flags = _f35_flags_after(ctl)
            taken = f35_cond_taken(cond, flags)
            if taken != (outcome == "t"):
                raise AssertionError(f"F35 {cond} under {ctl}: taken {taken}")
            for n in F35_CC_N:
                names = [F35_CONTROLS[ctl][0], f35_cc_form(cond, n)] + ["nop"] * n
                add("cc", f"{cond}-{outcome}-n{n}", names, lead=1, baseline=f"ctl-{ctl}",
                    exec_=[0, 1] if taken else None, taken=taken, push=n == 0,
                    form=names[1], cond=cond, control=ctl, flags=flags, n=n)
    # cw
    for c in (0, 1):
        add("cw", f"movcw{c}", [f"mov_cw_imm{c}"], cw=c)
    add("cw", "bcwz-t-n0", ["mov_cw_imm0", "bcwz_n0"], 1, "cw-movcw0", [0, 1], True,
        form="bcwz_n0", cw=0, n=0)
    add("cw", "bcwz-t-n2", ["mov_cw_imm0", "bcwz_n2", "nop", "nop"], 1, "cw-movcw0", [0, 1], True,
        form="bcwz_n2", cw=0, n=2)
    add("cw", "bcwz-nt-n0", ["mov_cw_imm1", "bcwz_n0"], 1, "cw-movcw1", [0, 1], False,
        form="bcwz_n0", cw=1, n=0)
    for c in (1, 2):
        for ctl in ("cmpaa", "cmpad"):
            lead = [f"mov_cw_imm{c}", F35_CONTROLS[ctl][0]]
            add("cw", f"c{c}-{ctl}", lead, cw=c, control=ctl, flags=_f35_flags_after(ctl))
    for op in ("dbnze", "dbnzne"):
        for c in (1, 2):
            for ctl in ("cmpaa", "cmpad"):
                z = _f35_flags_after(ctl)["Z"]
                taken = c - 1 != 0 and z == (op == "dbnze")
                add("cw", f"{op}-c{c}-{ctl}", [f"mov_cw_imm{c}", F35_CONTROLS[ctl][0],
                                               f"{op}_n0"], 2, f"cw-c{c}-{ctl}", [0, 1, 2],
                    taken, form=f"{op}_n0", cw=c, control=ctl, flags=_f35_flags_after(ctl), n=0)
    # loop
    for body, back in (("nop", "dbnz_m3"), ("reg", "dbnz_m4")):
        body_form = "nop" if body == "nop" else "mov_aw_dw"
        add("loop", f"c2-{body}", ["mov_cw_imm2", body_form], cw=2)
        add("loop", f"dbnz-{body}", ["mov_cw_imm2", body_form, back], 2, f"loop-c2-{body}",
            [0, 1, 2, 1, 2], True, form=back, cw=2)
    # ret
    add("ret", "pushaw", ["push_aw"])
    add("ret", "callret", ["call_n2", "br_n1", "ret"], 0, "empty", [0, 2, 1], True, form="ret")
    add("ret", "imm0", ["call_n2", "br_n3", "ret_imm0"], 0, "empty", [0, 2, 1], True,
        form="ret_imm0")
    add("ret", "imm2", ["push_aw", "call_n2", "br_n3", "ret_imm2"], 0, "empty", [0, 1, 3, 2],
        True, form="ret_imm2")
    # ind
    add("ind", "movbw", ["mov_bw_imm"])
    add("ind", "callr", [tgt("mov_bw", 5), "call_bw"], 1, "ind-movbw", [0, 1], True,
        form="call_bw", target_rel=5)
    add("ind", "callr-ret", [tgt("mov_bw", 7), "call_bw", "br_n1", "ret"], 1, "ind-movbw",
        [0, 1, 3, 2], True, form="call_bw", target_rel=7)
    add("ind", "brr-n0", [tgt("mov_bw", 5), "br_bw"], 1, "ind-movbw", [0, 1], True,
        form="br_bw", target_rel=5)
    add("ind", "brr-n1", [tgt("mov_bw", 6), "br_bw", "nop"], 1, "ind-movbw", [0, 1], True,
        form="br_bw", target_rel=6)
    # far
    add("far", "brf-n0", [tgt("brf", 5)], 0, "empty", [0], True, form="brf", target_rel=5)
    add("far", "brf-n1", [tgt("brf", 6), "nop"], 0, "empty", [0], True, form="brf",
        target_rel=6)
    add("far", "callf", [tgt("callf", 5)], 0, "empty", [0], True, form="callf", target_rel=5)
    add("far", "callf-retf", [tgt("callf", 7), "br_n1", "retf"], 0, "empty", [0, 2, 1], True,
        form="retf", target_rel=7)
    add("far", "callf-retf2", ["push_aw", tgt("callf", 8), "br_n3", "retf_imm2"], 0, "empty",
        [0, 1, 3, 2], True, form="retf_imm2", target_rel=8)
    return specs


def _f3536_chains(family, specs_for, waits, parities, rfm, regs=None):
    """Chains of F35 / F36: specs_for(kind, parity) -> [(label, knobs, names, push)], built per
    marker kind (out, then push: the labels with push set) and per parity, so a body may depend
    on the pad; chain order variant, then waits, then parity, as _sweep's."""
    regs = dict(regs or {})
    chains = []
    for kind in ("out", "push"):
        per_parity = {p: [s for s in specs_for(kind, p) if kind == "out" or s[3]]
                      for p in parities}
        labels = [[s[0] for s in v] for v in per_parity.values()]
        if any(lab != labels[0] for lab in labels):
            raise AssertionError(f"{family}: the variants differ between parities")
        for j in range(len(labels[0]) if labels else 0):
            for w in waits:
                for p in parities:
                    label, knobs, names, _ = per_parity[p][j]
                    body = [LS(), M(0, kind)] + xs(names) + [M(1, kind), LS(), END()]
                    chains.append(make_chain(family, f"{kind}-{label}",
                                             {**knobs, "marker": kind}, body, w, p,
                                             marker_kind=kind, regs=regs, rfm=rfm))
    return chains


def f35_first_x(kind, parity, regs=None, rfm=F35_RFM):
    """The code offset (in PS 1000h) of the first X of an F35 frame: the prelude, the parity
    pad, the first LS and M0."""
    from .forms import DEFAULT_REGS as _R, F35_PRELUDE_LEN
    from .image import prelude
    regs = {**_R, **(regs or {})}
    wtc = WTC_FOR_WAITS[0]
    n = len(prelude(regs, wtc, rfm, PRC_FX2))
    if n != F35_PRELUDE_LEN:
        raise AssertionError(f"F35: the prelude is {n} bytes, forms.F35_PRELUDE_LEN "
                             f"{F35_PRELUDE_LEN}")
    pad = int(needs_pad(regs, wtc, rfm, PRC_FX2, parity))
    return n + pad + len(blocks.LS) + len(blocks.marker(kind, 0))


def f35(waits=WAITS, parities=PARITIES):
    """Control flow completed (see the comment above)."""
    return _f3536_chains("F35", lambda kind, p: _f35_specs(f35_first_x(kind, p)), waits,
                         parities, F35_RFM, F35_FAMILY_REGS)


# F36 (the data forms no family ran; precedents F24, F25, F33), k = 1, every form against the
# empty frame (baseline empty) unless stated:
# mov: MOV AL,[0C00h] (A0), MOV [0C00h],AL (A2); MOV r8,imm8 for AL DL BL AH CH DH BH (B0,
#   B2-B7, 12h); MOV r16,imm16 for BW, BP, IX, IY (BB, BD-BF, each register's preset) and SP
#   (BC 00 0F, the OUT frame only: under PUSH M0 has moved SP).
# shift: SHL AL,CL (D2 E0) and SHL byte [BW],CL (D2 27), CL = 31 from the fence.
# test: TEST DL,AL (84 C2).
# xch: XCH AW,r for CW BW BP IX IY (91 93 95-97) and SP (94, the OUT frame only: SP becomes 0).
# stack: PUSH r for CW DW BW SP BP IX IY (51-57); PUSH r ; POP r for CW DW BW BP IX IY (POP CW
#   59, 5A 5B 5D-5F; baseline PUSH r alone) and SP (54 ; 5C, the OUT frame only: what POP SP
#   leaves in SP depends on the value PUSH SP stores); PUSH PSW ; POP PSW (9C ; 9D, the pair
#   against the empty frame).
# alu: OR / ADDC / SUBC / AND / SUB / XOR AW,DW (0B 13 1B 23 2B 33, C2); OR / ADDC / SUBC / AND /
#   SUB / XOR / CMP AW,1234h (0D 15 1D 25 2D 35 3D); ADD / CMP byte [BW],5 in the 80 group and
#   its 82 alias (80 07, 80 3F, 82 07, 82 3F).
# psw: LAHF (9F) alone; LAHF ; SAHF (9E, baseline LAHF alone: SAHF only with AH = the PSW's low
#   byte, so BRKI stays set).
# lock: BUSLOCK MOV AW,DW (F0 8B C2) and BUSLOCK ADD [BW],AW (F0 01 07), with MOV AW,DW and ADD
#   [BW],AW unprefixed as their controls (knob control the unprefixed variant).
# ptr: LES AW,[IX] (C4 04) and LDS AW,[IX] (C5 04): the pointer at 0100h, in the zeroed vector
#   table (offset and segment 0000h).
# Left out: the word strings (F24 runs them), INC / DEC r16 (F33), IN AW,DW (F19), anything
#   that traps or depends on a pin.
F36_RFM = RFM_OFF
F36_OUT_ONLY = ("mov-mov_sp_imm16", "xch-xch_aw_sp", "stack-push_sp-pop_sp")


def _f36_specs():
    from .forms import F36_ALU, F36_MOV16, F36_MOV16_FORM, F36_R8, F36_R16
    specs = []

    def add(series, names, form=None, label=None, lead=0, baseline="empty", **extra):
        names = list(names)
        label = label or "-".join(names)
        full = label if series == "empty" else f"{series}-{label}"
        knobs = {"probe": series, "series": series, "form": form, "x": names,
                 "k": 1 if form else 0, "lead": names[:lead], "baseline": baseline,
                 "exec": list(range(len(names))), "skipped": 0, "taken": None,
                 "rfm": F36_RFM, "refresh_on": False, **extra}
        specs.append((full, knobs, names, full not in F36_OUT_ONLY))

    add("empty", [], label="empty", baseline=None)
    for name in ("ld_al_dir", "st_al_dir"):
        add("mov", [name], name)
    for r in F36_R8:
        add("mov", [f"mov_{r}_imm8"], f"mov_{r}_imm8")
    for r in F36_MOV16:
        add("mov", [F36_MOV16_FORM[r]], F36_MOV16_FORM[r])
    for name in ("shl_al_cl", "shlb_m_cl"):
        add("shift", [name], name)
    add("test", ["test_dl_al"], "test_dl_al")
    for r in F36_R16:
        if r != "dw":
            add("xch", [f"xch_aw_{r}"], f"xch_aw_{r}")
    for r in F36_R16:
        add("stack", [f"push_{r}"], f"push_{r}")
    for r in F36_R16:
        add("stack", [f"push_{r}", f"pop_{r}"], f"pop_{r}", lead=1, baseline=f"stack-push_{r}")
    add("stack", ["push_psw", "pop_psw"], "pop_psw")
    for op in F36_ALU:
        if op != "cmp":
            add("alu", [f"{op}_aw_dw"], f"{op}_aw_dw")
    for op in F36_ALU:
        add("alu", [f"{op}_aw_imm16"], f"{op}_aw_imm16")
    for g in (0x80, 0x82):
        for op in ("add", "cmp"):
            name = f"{op}b_m_imm8_{g:02x}"
            add("alu", [name], name, group_opcode=g)
    add("psw", ["lahf"], "lahf")
    add("psw", ["lahf", "sahf"], "sahf", lead=1, baseline="psw-lahf")
    for name, ctl in (("lock_mov_aw_dw", "mov_aw_dw"), ("lock_add_m_aw", "add_m_aw")):
        add("lock", [ctl], ctl)
        add("lock", [name], name, control=f"lock-{ctl}")
    for name in ("les_aw_ix", "lds_aw_ix"):
        add("ptr", [name], name)
    return specs


def f36(waits=WAITS, parities=PARITIES):
    """The data forms no family ran (see the comment above)."""
    specs = _f36_specs()
    missing = set(F36_OUT_ONLY) - {s[0] for s in specs}
    if missing:
        raise AssertionError(f"F36: OUT-only labels without a variant: {sorted(missing)}")
    return _f3536_chains("F36", lambda kind, p: specs, waits, parities, F36_RFM)


FAMILIES.update({"F35": f35, "F36": f36})
# (WP87) generator-only (forms.UNMODELLED_FORMS held the forms the simulator did not decode);
# (WP88) read as facts and modelled: none
UNMODELLED = ()


# F37 (WP90: one refresh-off coverage family; precedents F23, F35). The two groups F35 left out:
# the memory-indirect transfers (a pointer word) and BRK / RETI (a vector). The chain's lead
# writes the word: DS0 = 0, so MOV AW,imm16 ; MOV [d16],AW stores anywhere in page 0 (AW is 0
# after the fence and is reloaded by the lead, as F35's MOV BW,t): the pointer at 0C00h (the
# segment at 0C02h) in the data area, the vector at 4n / 4n+2 in the zeroed vector table. No
# image.py or blocks.py change. The cost frame PAD LS M0 X M1 LS END, refresh off (RFM ECh), every
# wait and parity, the OUT and the PUSH marker on every variant; run ids
# F37-<out|push>-<series>-<label>-p<E|O>-w<N>, the empty frame F37-<marker>-empty. Every
# transfer's baseline is the frame with its lead alone (the ctl series: the lead stores, with
# MOV AW,1234h for the target word); X's cost is dM(X) - dM(baseline). The pointer and vector
# targets are absolute code offsets in PS 1000h (forms.F37_ABS: MOV AW,t built per parity from
# f35_first_x, the prelude a constant 71 bytes checked at generation), so a variant's pE and pO
# chains differ in that one form. Knobs as F35's (series = probe, marker, form, x, k, lead,
# baseline, exec, skipped, taken, rfm, refresh_on) and: stores (the [address, word] pairs the
# lead writes, in order), target (the X index the pointer / vector names; len(x) is M1),
# target_rel (its offset from the first X), mode_class (direct or base: the transfer's EA),
# ret (the return form a call or BRK reaches), vector (BRK's n) and handler (the X indices run
# between BRK and its return, RETI last, from exec).
# ctl: the empty frame; the lead stores alone: one word to 0C00h (ptr), the same after MOV
#   BW,0C00h (ptrbw), two words to 0C00h / 0C02h (far, and farbw after MOV BW,0C00h), the vector
#   pairs to 0Ch / 0Eh (vec3) and 14h / 16h (vec5); ptr, far, vec3 and vec5 again with a NOP
#   after them (-sep, the baselines of the sep cells). MOV AW,imm16 ; MOV [0C00h],AW is F5's
#   store class: the controls are modelled already.
# indm: CALL near [0C00h] (FF 16 00 0C) to the next instruction, to a RET (CALL ; BR +1 ; RET,
#   F23's callret: run 0 1 2 4 3) and after a NOP (sep: the store's write and the pointer's read
#   one instruction apart); BR near [0C00h] (FF 26 00 0C) to the next instruction, over one NOP
#   (the target's parity) and after a NOP; CALL and BR through [BW] (FF 17, FF 27; MOV BW,0C00h
#   in the lead, the pointer written direct), to the next instruction, to a RET (CALL) and over
#   a NOP (BR), so the mode class varies (direct, base).
# farm: BR far [0C00h] (FF 2E 00 0C, offset at 0C00h, segment 1000h at 0C02h) to the next
#   instruction, over one NOP and after a NOP; CALL far [0C00h] (FF 1E 00 0C) to the next
#   instruction and to a RETF (CALL ; BR +1 ; RETF); through [BW] (FF 1F, FF 2F): CALL far to
#   the next instruction and to a RETF, BR far to the next instruction and over a NOP.
# brk: BRK 3 (CC) and BRK 5 (CD 05), the vector written by the lead to the chain offset of the
#   handler: a RETI (CF) after BR +1 (BRK ; BR +1 ; RETI: RETI returns to the BR, the
#   instruction after the BRK, and the BR jumps the RETI); NOP ; RETI (BRK ; BR +2 ; NOP ; RETI:
#   the handler runs between BRK and the return, exec order marks it); each after a NOP (sep).
#   BRK pushes PSW, PS, PC (three stack words: writes 3) and RETI pops PC, PS, PSW (reads 3),
#   sp_adjust 0; the PSW is the harness's F002h both ways (forms, F37).
# Left out: a handler directly after its BRK (BRK's return address is the next instruction, so
#   the RETI would run twice, the second popping what the frame never pushed); a handler or a
#   RET placed before its BRK / CALL (BR +1 ; RETI ; BRK, returning straight to M1):
#   normalize.expected_accesses walks the stack cycles in chain order, and such a chain pops
#   before it pushes in chain order; anything else that traps (CHKIND, FPO1, POLL, BRKV); RETI
#   without a BRK before it; a handler with an I/O form; a pointer at an odd address.
#   Generator-only (UNMODELLED) until WP91 (sim/templates.py _wp91_steps): the transfers'
#   classes had no template (forms.UNMODELLED_FORMS). (WP90) Acquired 2026-10-31 (432 runs); normalize expects the
#   pointer and vector reads in silicon's order (normalize.VECTORED_ACCESSES) and derive costs
#   every cell against the baseline its knob names.
F37_RFM = RFM_OFF
F37_IMM = 0x1234                # the controls' target word: MOV AW,1234h (mov_aw_imm)


def _f37_specs(first_x):
    """[(label, knobs-without-marker, x names, push)] for the frame whose first X sits at code
    offset first_x (the absolute targets), in family order."""
    from .forms import F37_ABS_FORMS, F37_PTR, F37_SEG, F37_STORE, F37_VECTORS
    specs = []

    def lead_of(kind, n=None):
        """The lead's stores [(address, word)] in order, "T" the target's offset word."""
        if kind == "ptr":
            pairs = [(F37_PTR, "T")]
        elif kind == "far":
            pairs = [(F37_PTR, "T"), (F37_PTR + 2, F37_SEG)]
        else:
            pairs = [(F37_VECTORS[n], "T"), (F37_VECTORS[n] + 2, F37_SEG)]
        return pairs

    def add(series, label, names, lead=0, baseline="empty", exec_=None, taken=None, form=None,
            pairs=(), target=None, **extra):
        names = list(names)
        rel = (sum(len(FORMS[n].code) if n != "T" else 3 for n in names[:target])
               if target is not None else None)
        word = first_x + rel if rel is not None else F37_IMM
        names = [F37_ABS_FORMS["mov_aw"][word] if n == "T" else n for n in names]
        ex = list(exec_ if exec_ is not None else range(len(names)))
        knobs = {"probe": series, "series": series, "form": form, "x": names,
                 "k": 1 if form else 0, "lead": names[:lead], "baseline": baseline,
                 "exec": ex, "skipped": len(names) - len(set(ex)), "taken": taken,
                 "rfm": F37_RFM, "refresh_on": False,
                 "stores": [[a, word if w == "T" else w] for a, w in pairs],
                 "target": target, "target_rel": rel, **extra}
        specs.append((label if series == "empty" else f"{series}-{label}", knobs, names, True))

    def stores(pairs):
        """The lead's forms for pairs: MOV AW,t ("T") or MOV AW,1000h ; MOV [a],AW."""
        out = []
        for a, w in pairs:
            out += ["T" if w == "T" else "mov_aw_1000", F37_STORE[a]]
        return out

    add("empty", "empty", [], baseline=None)
    # ctl: the lead stores alone (the target word MOV AW,1234h)
    ctl = {"ptr": (lead_of("ptr"), []), "ptrbw": (lead_of("ptr"), ["mov_bw_c00"]),
           "far": (lead_of("far"), []), "farbw": (lead_of("far"), ["mov_bw_c00"]),
           "vec3": (lead_of("vec", 3), []), "vec5": (lead_of("vec", 5), [])}
    for label, (pairs, pre) in ctl.items():
        names = pre + ["mov_aw_imm" if n == "T" else n for n in stores(pairs)]
        add("ctl", label, names, pairs=pairs)
        if label in ("ptr", "far", "vec3", "vec5"):
            add("ctl", f"{label}-sep", names + ["nop"], pairs=pairs)

    # indm: the near pointer at 0C00h
    def indm(label, pre, body, target, exec_, form, mode_class, ret=None, sep=False,
             base="ptr"):
        lead = pre + stores(lead_of("ptr")) + (["nop"] if sep else [])
        names = lead + body
        add("indm", label, names, len(lead), f"ctl-{base}" + ("-sep" if sep else ""),
            exec_, True, form, lead_of("ptr"), len(lead) + target, mode_class=mode_class,
            ret=ret)

    indm("callm-n0", [], ["call_m_dir"], 1, [0, 1, 2], "call_m_dir", "direct")
    indm("callm-ret", [], ["call_m_dir", "br_n1", "ret"], 2, [0, 1, 2, 4, 3], "call_m_dir",
         "direct", "ret")
    indm("callm-sep", [], ["call_m_dir"], 1, [0, 1, 2, 3], "call_m_dir", "direct", sep=True)
    indm("brm-n0", [], ["br_m_dir"], 1, [0, 1, 2], "br_m_dir", "direct")
    indm("brm-n1", [], ["br_m_dir", "nop"], 2, [0, 1, 2], "br_m_dir", "direct")
    indm("brm-sep", [], ["br_m_dir"], 1, [0, 1, 2, 3], "br_m_dir", "direct", sep=True)
    bw = ["mov_bw_c00"]
    indm("callbw-n0", bw, ["call_m_bw"], 1, [0, 1, 2, 3], "call_m_bw", "base", base="ptrbw")
    indm("callbw-ret", bw, ["call_m_bw", "br_n1", "ret"], 2, [0, 1, 2, 3, 5, 4], "call_m_bw",
         "base", "ret", base="ptrbw")
    indm("brbw-n0", bw, ["br_m_bw"], 1, [0, 1, 2, 3], "br_m_bw", "base", base="ptrbw")
    indm("brbw-n1", bw, ["br_m_bw", "nop"], 2, [0, 1, 2, 3], "br_m_bw", "base", base="ptrbw")

    # farm: the far pointer at 0C00h / 0C02h
    def farm(label, pre, body, target, exec_, form, mode_class, ret=None, sep=False,
             base="far"):
        lead = pre + stores(lead_of("far")) + (["nop"] if sep else [])
        names = lead + body
        add("farm", label, names, len(lead), f"ctl-{base}" + ("-sep" if sep else ""),
            exec_, True, form, lead_of("far"), len(lead) + target, mode_class=mode_class,
            ret=ret)

    l4 = [0, 1, 2, 3]
    farm("brfm-n0", [], ["brf_m_dir"], 1, l4 + [4], "brf_m_dir", "direct")
    farm("brfm-n1", [], ["brf_m_dir", "nop"], 2, l4 + [4], "brf_m_dir", "direct")
    farm("brfm-sep", [], ["brf_m_dir"], 1, l4 + [4, 5], "brf_m_dir", "direct", sep=True)
    farm("callfm-n0", [], ["callf_m_dir"], 1, l4 + [4], "callf_m_dir", "direct")
    farm("callfm-retf", [], ["callf_m_dir", "br_n1", "retf"], 2, l4 + [4, 6, 5],
         "callf_m_dir", "direct", "retf")
    farm("callfbw-n0", bw, ["callf_m_bw"], 1, l4 + [4, 5], "callf_m_bw", "base", base="farbw")
    farm("callfbw-retf", bw, ["callf_m_bw", "br_n1", "retf"], 2, l4 + [4, 5, 7, 6],
         "callf_m_bw", "base", "retf", base="farbw")
    farm("brfbw-n0", bw, ["brf_m_bw"], 1, l4 + [4, 5], "brf_m_bw", "base", base="farbw")
    farm("brfbw-n1", bw, ["brf_m_bw", "nop"], 2, l4 + [4, 5], "brf_m_bw", "base", base="farbw")

    # brk: the vector at 4n / 4n+2 names the handler
    def brk(label, n, body, target, exec_, sep=False):
        lead = stores(lead_of("vec", n)) + (["nop"] if sep else [])
        names = lead + body
        exec_ = list(exec_)
        at = names.index(f"brk{n}")
        reti = names.index("reti")
        handler = exec_[exec_.index(at) + 1:exec_.index(reti) + 1]
        add("brk", label, names, len(lead), f"ctl-vec{n}" + ("-sep" if sep else ""), exec_,
            True, f"brk{n}", lead_of("vec", n), len(lead) + target, vector=n, ret="reti",
            handler=handler, mode_class=None)

    for n in (3, 5):
        b = f"brk{n}"
        brk(f"brk{n}", n, [b, "br_n1", "reti"], 2, l4 + [4, 6, 5])
        brk(f"brk{n}-nop", n, [b, "br_n2", "nop", "reti"], 2, l4 + [4, 6, 7, 5])
        brk(f"brk{n}-sep", n, [b, "br_n1", "reti"], 2, l4 + [4, 5, 7, 6], sep=True)
    return specs


def f37(waits=WAITS, parities=PARITIES):
    """Memory-indirect transfers, BRK and RETI through a word the chain writes (see the comment
    above)."""
    return _f3536_chains("F37", lambda kind, p: _f37_specs(f35_first_x(kind, p)), waits,
                         parities, F37_RFM)


FAMILIES.update({"F37": f37})
# (WP90) F37 was generator-only: its transfers (forms.UNMODELLED_FORMS) had no template, and the
# scorer, the fitter and freeze skipped it. (WP91) modelled (sim/templates.py _wp91_steps)
UNMODELLED = ()


# F38 (WP97: one refresh-off coverage family; precedent F36, a class-equivalence family). The
# first bytes no family had run that a straight-line chain can run: the ALU operations' memory,
# byte and immediate forms, the SS: / DS0: / PS: prefixes, the byte shift by imm8 (forms, F38).
# The model gives every ALU operation one class per operand shape (rmw, load_alu, rmw_imm, imm)
# and every segment prefix the prefix class; F38 measures each new form beside its class mate in
# the same frame. The cost frame PAD LS M0 X M1 LS END, k = 1, refresh off (RFM ECh), every wait
# and parity, the OUT and the PUSH marker on every variant (no X touches SP); run ids
# F38-<out|push>-<series>-<label>-p<E|O>-w<N>, the label X's form name, the empty frame
# F38-<marker>-empty. Every X against the empty frame (baseline empty). Knobs as F36's (series =
# probe, marker, form, x, k, lead, baseline, exec, skipped, taken, rfm, refresh_on) and: control
# (the label of the variant whose X is the class mate the form is measured against, in the same
# series; None for a mate that is itself a catalog form some family already ran), shape (the
# operand shape, forms.F38_FORM's key), op (the ALU operation, the segment, or the shift form),
# width (the operand width in bytes), group_opcode (grp) and modelled (False where X is in
# forms.UNMODELLED_FORMS). Controls (catalog forms already run unless said):
# rmw: op [BW],AW for ADD (control) OR ADDC SUBC AND SUB XOR (01 09 11 19 21 29 31 07), mate
#   rmw-add_m_aw; op byte [BW],AL (00 08 10 18 20 28 30 07), mate rmw-add_m_al (F14's).
# ldalu: op AW,[BW] (03 0B 13 1B 23 2B 33 07), mate ldalu-add_aw_m, CMP AW,[BW] (3B 07) a second
#   control; op AL,[BW] (0A 12 1A 22 2A 32 07), mate ldalu-add_al_m (02 07, new: its mate
#   ldalu-add_aw_m), CMP AL,[BW] (3A 07, new: its mate ldalu-cmp_aw_m).
# imm8: op AL,34h (0C 14 1C 24 2C 34 3C), mate imm8-add_al_imm8 (04 34, new: its mate
#   imm8-test_al_imm, TEST AL,34h A8, F15's).
# grp: 80 /1-/6 at [BW],5, mate grp-addb_m_imm8_80 (80 /0; 80 /7 CMP, F36's, the read-only
#   control); 83 /1-/6 at [BW],5, mate grp-add_m_imm8 (83 /0, F15's); 81 /1 and /4 at [BW],1234h,
#   mate grp-add_m_imm (81 /0).
# pfx: SS: / DS0: / PS: MOV AW,DW (36 3E 2E 8B C2), mate pfx-pfx_mov_aw_dw (DS1: 26 8B C2, F3's);
#   SS: / DS0: MOV AW,[BW] (36 3E 8B 07), mate pfx-pfx_ld_bw (DS1: 26 8B 07, new: its mate the
#   unprefixed pfx-ld_bw); MOV AW,DW and MOV AW,[BW] unprefixed beside them.
# shb: SHL AL,4 (C0 E0 04), mate shb-shl_imm4 (C1 E0 04); SHL byte [BW],4 (C0 27 04), mate
#   shb-shl_m_imm4 (C1 27 04, new: its mate shb-shl_m1, D1 27).
# Left out: a PS:-prefixed load (PS = 1000h: it reads 10800h, the code page, which the
#   normaliser classifies as a fetch); 80 / 83 /7 and the 81 group's other operations (CMP and
#   F15's AND ran; the other 81 operations are one immediate width of the 83 rows); CHKIND (62),
#   POLL (9B), BRKV (CE), FPO1 (D8-DF), the undefined 63 66 67 D6 F1, and HALT (F4, the END).
# Generator-only (UNMODELLED): eleven forms do not decode to their class and length
# (forms.F38_UNMODELLED: the AL,imm8 forms and C0 raise in sim/templates.decode, C1 with a
# memory operand decodes to a register shift), so the scorer, the fitter and freeze skip F38
# until a template learns them; every other F38 form decodes to its catalog class and length.
F38_RFM = RFM_OFF


def _f38_specs():
    from .forms import F38_FORM, F38_OPS, F38_SEGS, FORMS as _FORMS, UNMODELLED_FORMS
    specs = []

    def add(series, shape, key, control=None, label=None, width=None, **extra):
        if series == "empty":
            names, form, full = [], None, "empty"
        else:
            form = F38_FORM[(shape, key)]
            names, full = [form], f"{series}-{label or form}"
        knobs = {"probe": series, "series": series, "form": form, "x": names,
                 "k": 1 if form else 0, "lead": [], "baseline": None if form is None else "empty",
                 "exec": list(range(len(names))), "skipped": 0, "taken": None,
                 "rfm": F38_RFM, "refresh_on": False,
                 "control": control and f"{series}-{F38_FORM[control]}",
                 "shape": shape, "op": key,
                 "width": None if form is None else (
                     _FORMS[form].width or (1 if shape == "imm8" or key == "al_imm" else 2)),
                 "modelled": form not in UNMODELLED_FORMS, **extra}
        specs.append((full, knobs, names, True))

    alu = [op for op in F38_OPS if op != "cmp"]
    add("empty", None, None)
    for w in ("w", "b"):
        for op in alu:
            add("rmw", f"rmw_{w}", op, None if op == "add" else (f"rmw_{w}", "add"))
    add("ldalu", "ldalu_w", "add")
    for op in alu[1:]:
        add("ldalu", "ldalu_w", op, ("ldalu_w", "add"))
    add("ldalu", "ldalu_w", "cmp")
    add("ldalu", "ldalu_b", "add", ("ldalu_w", "add"))
    for op in alu[1:]:
        add("ldalu", "ldalu_b", op, ("ldalu_b", "add"))
    add("ldalu", "ldalu_b", "cmp", ("ldalu_w", "cmp"))
    add("imm8", "imm8", "test")
    add("imm8", "imm8", "add", ("imm8", "test"))
    for op in list(F38_OPS)[1:]:
        add("imm8", "imm8", op, ("imm8", "add"))
    for g, ops in ((0x80, list(F38_OPS)), (0x83, alu), (0x81, ["add", "or", "and"])):
        shape = f"g{g:02x}"
        for op in ops:
            add("grp", shape, op, None if op in ("add", "cmp") else (shape, "add"),
                group_opcode=g)
    for shape, segs in (("pfx_reg", (None, "ds1", "ss", "ds0", "ps")),
                        ("pfx_ld", (None, "ds1", "ss", "ds0"))):
        for seg in segs:
            if seg is None or (seg == "ds1" and shape == "pfx_reg"):
                control = None
            elif seg == "ds1":
                control = (shape, None)
            else:
                control = (shape, "ds1")
            add("pfx", shape, seg, control, segment=seg,
                prefix=None if seg is None else F38_SEGS[seg])
    for key, control in (("aw_imm", None), ("al_imm", "aw_imm"), ("m1", None),
                         ("m_imm", "m1"), ("mb_imm", "m_imm")):
        add("shb", "shb", key, control and ("shb", control))
    return specs


def f38(waits=WAITS, parities=PARITIES):
    """The ALU operations' memory, byte and immediate forms, the segment prefixes, the byte
    shift by imm8 (see the comment above)."""
    specs = _f38_specs()
    labels = [s[0] for s in specs]
    if len(set(labels)) != len(labels):
        raise AssertionError("F38: duplicate labels")
    for label, knobs, _, _ in specs:
        if knobs["control"] is not None and knobs["control"] not in labels:
            raise AssertionError(f"F38 {label}: control {knobs['control']} has no variant")
    return _f3536_chains("F38", lambda kind, p: specs, waits, parities, F38_RFM)


FAMILIES.update({"F38": f38})
# (WP97) generator-only: eleven of its forms do not decode (forms.F38_UNMODELLED)
UNMODELLED = ("F38",)
