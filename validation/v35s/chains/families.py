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


FAMILIES = {"F0": f0, "F0w": f0w, "F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5,
            "F6": f6, "F7": f7, "F8": f8,
            "F9": f9, "F10": f10, "F11": f11, "F12": f12, "F13": f13, "F14": f14,
            "F15": f15, "F16": f16, "F17": f17, "F18": f18, "F19": f19, "F20": f20, "F21": f21,
            "F22": f22}


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
