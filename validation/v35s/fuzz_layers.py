"""F5: the fuzz's program sets, one per scenario layer (validation/v35s/fuzz.py runs them).

    f5a  plain: instructions only, interrupts off, peripherals idle
    f5b  register banks: f5a's instructions with RB changed between blocks (TSKSW, BRKCS /
         RETRBI, RETRBI one way, RETI into another bank, MOVSPA, MOVSPB, FINT)
    f5c  interrupts, four scenarios by program number (k mod 4):
           0 intp   INTP0 by the schedule (event 1), a bank-switch entry into a handler bank
           1 nmi    NMI by the schedule, vectored (the frame on the stack)
           2 timer  TM0 interval count-out, a bank-switch entry whose handler stops TM0
           3 step   the single step (BRK set by POP PSW) over a run of random instructions
    f5d  on-chip state: random stores to the writable SFRs among plain instructions, the SFR
         page (F1's comparable offsets) and the banks dumped at the end
    f5e-h (F5d) the second generation: f5a-d's layers with fresh seeds
    f5i  (F5d) the coverage gaps: f5a's layer with the gap forms (fuzz_gen opts["gap"])
    f5v  (F5g) D6 /r (CLR1 r/m8 by the reg field: fuzz_gap2 f_d6) in f5p's plain layer with
         the gap forms, a fresh seed
    f5x  the flag survey (validation/v35s/fuzz_flags.py)
    f5o  (F5c) measured, not gated: the OUT datum after CVTBD / CVTDB (fuzz_flags "outd")

The asynchronous take (intp, nmi, timer) does not depend on the boundary it lands on:
 - the bank-switch handlers (intp, timer) touch nothing but their count byte (SS:7E40h / 7E41h),
   ISPR (FINT) and, for the timer, TMC0; they push nothing. Their bank's PSW save and PC save
   (which hold the interrupted point) are masked in the bank dump; (F5b) the count byte's store
   (it sits where the take lands: the RTL's clocks are not silicon's) is dropped from both write
   sequences, its final value compared in the count page;
 - the NMI's frame (three pushes) and its stub's count store are dropped from both write
   sequences before they are compared (they sit where the take lands); the stack page's final
   contents are not compared (the frame's residue), its every write before and after is;
 - the program ends by waiting (a compare loop, no writes) for the handler's count to read 1
   with IE set, so the take happens on both sides before the final observation and dump.
"""

from __future__ import annotations

import random

from . import fuzz_gen as G
from . import fuzz_gap2 as G2
from .fuzz_gen import AW, DW, SLOT, hx

W_B = dict(G.WEIGHTS, f_bank=14)
W_C = {k: v for k, v in G.WEIGHTS.items() if k not in ("f_retiw",)}
W_D = dict({k: v for k, v in G.WEIGHTS.items()}, f_sfr=40)

SETS = {
    "f5a": dict(layer="a", n=300, items=110, seed=0x5A000000),
    "f5b": dict(layer="b", n=150, items=110, seed=0x5B000000, weights=W_B),
    "f5c": dict(layer="c", n=160, items=90, seed=0x5C000000, weights=W_C),
    "f5d": dict(layer="d", n=100, items=90, seed=0x5D000000, weights=W_D),
    # (F5d) the second generation: the same layers and sizes, fresh seeds (f5a-d kept as they are)
    "f5e": dict(layer="a", n=300, items=110, seed=0x7E110000, weights=None),
    "f5f": dict(layer="b", n=150, items=110, seed=0x7F220000, weights=W_B),
    "f5g": dict(layer="c", n=160, items=90, seed=0x70330000, weights=W_C),
    "f5h": dict(layer="d", n=100, items=90, seed=0x71440000, weights=W_D),
    # (F5d) the coverage gaps (fuzz_gen opts["gap"]): REP then segment prefixes / BUSLOCK on
    # every string form, SP loaded (MOV SP,imm, POP SP, XCH AW,SP, XCH r,SP; odd values), MUL /
    # DIV edge operands, a word at offset FFFFh and STMW / LDMW through it (the segment wrap)
    "f5i": dict(layer="a", n=200, items=110, seed=0x72550000, opts={"gap": True},
                weights=dict(G.WEIGHTS, f_str=12, f_spld=3, f_mdedge=4, f_wrap=4)),
    # (F5e) the third generation: fresh seeds, every layer with the gap forms (fuzz_gap2: SP
    # through 0000h / FFFFh, POLL, the illegal register forms, HALT left by INTP1), layer c with
    # two more scenarios (mix: two or three asynchronous sources at once, nesting; mixd: the step
    # and a request on one boundary, HALT with IE 1, a take inside a REP string with prefixes)
    "f5j": dict(layer="a", n=300, items=110, seed=0x13A70000, opts={"gap": True, "gap2": True},
                weights=dict(G.WEIGHTS, f_str=8, f_spld=2, f_mdedge=2, f_wrap=2, f_spwrap=3,
                             f_poll=1, f_illreg=1, f_halt0=1)),
    "f5k": dict(layer="b", n=150, items=110, seed=0x14B80000, opts={"gap2": True},
                weights=dict(W_B, f_spwrap=2, f_poll=1, f_illreg=1, f_halt0=1)),
    "f5l": dict(layer="c", n=200, items=90, seed=0x15C90000, opts={"gap2": True, "no_md": True},
                scens=("intp", "nmi", "timer", "step", "mix", "mixd"),
                weights=dict(W_C, f_stepint=3, f_halt1=2, f_repint=4, f_spwrap=2, f_poll=1,
                             f_illreg=1)),
    "f5m": dict(layer="d", n=100, items=90, seed=0x16DA0000, opts={"gap2": True},
                weights=dict(W_D, f_spwrap=2, f_poll=1, f_illreg=1, f_halt0=1)),
    "f5n": dict(layer="a", n=250, items=110, seed=0x17EB0000, opts={"gap": True, "gap2": True},
                weights=dict(G.WEIGHTS, f_str=12, f_spld=3, f_mdedge=4, f_wrap=4, f_spwrap=8,
                             f_poll=2, f_illreg=3, f_halt0=3)),
    # (F5f) a small fourth generation after the string take point gained the macro service and
    # DMA: fresh seeds, every layer, the gap kinds of both earlier generations (300 programs)
    "f5p": dict(layer="a", n=100, items=110, seed=0x2A510000, opts={"gap": True, "gap2": True},
                weights=dict(G.WEIGHTS, f_str=8, f_spld=2, f_mdedge=2, f_wrap=2, f_spwrap=3,
                             f_poll=1, f_illreg=1, f_halt0=1)),
    "f5q": dict(layer="b", n=50, items=110, seed=0x2B620000, opts={"gap2": True},
                weights=dict(W_B, f_spwrap=2, f_poll=1, f_illreg=1, f_halt0=1)),
    "f5s": dict(layer="c", n=70, items=90, seed=0x2C730000, opts={"gap2": True, "no_md": True},
                scens=("intp", "nmi", "timer", "step", "mix", "mixd"),
                weights=dict(W_C, f_stepint=3, f_halt1=2, f_repint=4, f_spwrap=2, f_poll=1,
                             f_illreg=1)),
    "f5t": dict(layer="d", n=40, items=90, seed=0x2D840000, opts={"gap2": True, "intm_fall": True},
                weights=dict(W_D, f_spwrap=2, f_poll=1, f_illreg=1, f_halt0=1)),
    "f5u": dict(layer="a", n=40, items=110, seed=0x2E950000, opts={"gap": True, "gap2": True},
                weights=dict(G.WEIGHTS, f_str=12, f_spld=3, f_mdedge=4, f_wrap=4, f_spwrap=8,
                             f_poll=2, f_illreg=3, f_halt0=3)),
    # (F5g) D6 /r (CLR1 r/m8 by the reg field, built in F5g: fuzz_gap2 f_d6) in the plain
    # layer with the gap forms, a fresh seed
    "f5v": dict(layer="a", n=150, items=110, seed=0x3F6A0000,
                opts={"gap": True, "gap2": True, "d6": True},
                weights=dict(G.WEIGHTS, f_str=8, f_spld=2, f_mdedge=2, f_wrap=2, f_spwrap=3,
                             f_poll=1, f_illreg=1, f_halt0=1, f_d6=10)),
}
SCEN_C = ("intp", "nmi", "timer", "step")

# ------------------------------------------------------------------ layer d: the SFRs
# offset -> (width, the value constraint: (and-mask, or-bits)); the constraints keep every
# function idle: IC registers MK 1 IF 0, serial TxRDY / RxE 0, timers stopped (TS0 / MS0 / TS1
# 0), DMA EDMA / TDMA 0, INTM's ESNMI as at reset
SFR_D = {
    0x00: (1, 0xFF, 0), 0x08: (1, 0xFF, 0), 0x10: (1, 0xFF, 0), 0x3B: (1, 0xFF, 0),
    0x40: (1, 0xFE, 0), 0x44: (1, 0xFF, 0), 0x45: (1, 0xFF, 0), 0x46: (1, 0xFF, 0),
    # IC registers: MK 1, IF 0 and MS 0 (MS 1 runs macro service whatever MK: f5d_048 / f5d_055 of
    # the first sessions, the time base driving transfers through the random EMS pointers)
    **{o: (1, 0x1F, 0x40) for o in (0x4C, 0x4D, 0x4E, 0x6C, 0x6D, 0x6E, 0x7C, 0x7D, 0x7E,
                                    0x9C, 0x9D, 0x9E, 0xAC, 0xAD, 0xEC)},
    0x65: (1, 0xFF, 0), 0x66: (1, 0xFF, 0), 0x68: (1, 0x3F, 0), 0x69: (1, 0xFF, 0), 0x6A: (1, 0xFF, 0),
    0x75: (1, 0xFF, 0), 0x76: (1, 0xFF, 0), 0x78: (1, 0x3F, 0), 0x79: (1, 0xFF, 0), 0x7A: (1, 0xFF, 0),
    0x80: (2, 0xFFFF, 0), 0x82: (2, 0xFFFF, 0), 0x88: (2, 0xFFFF, 0), 0x8A: (2, 0xFFFF, 0),
    0x90: (1, 0x5F, 0), 0x91: (1, 0x7F, 0), 0x94: (1, 0xFF, 0), 0x95: (1, 0xFF, 0), 0x96: (1, 0xFF, 0),
    0xA0: (1, 0xFF, 0), 0xA1: (1, 0xF3, 0), 0xA2: (1, 0xFF, 0), 0xA3: (1, 0xF3, 0),
    0xE8: (2, 0xFFFF, 0), 0xEA: (1, 0xFF, 0),
}
# the dump: dump.DEFAULT_SFRS without the residue offsets (PM0-2, PMC0-2), TM0 / TM1 added
DUMP_D_BYTES = (0x3B, 0x40, 0x44, 0x45, 0x46, 0x4C, 0x4D, 0x4E, 0x68, 0x69, 0x6A, 0x6C, 0x6D, 0x6E,
                0x78, 0x79, 0x7A, 0x7C, 0x7D, 0x7E, 0x90, 0x91, 0x94, 0x95, 0x96, 0x9C, 0x9D, 0x9E,
                0xA0, 0xA1, 0xA2, 0xA3, 0xAC, 0xAD, 0xE0, 0xE1, 0xEA, 0xEB, 0xEC, 0xFC, 0xFF)
DUMP_D_WORDS = (0x80, 0x82, 0x88, 0x8A, 0xE8)


def sfr_value(r, o):
    w, am, ob = SFR_D[o]
    return (r.randrange(256 ** w) & am) | ob


def f_sfr(g):
    """A store of a constrained random value to a writable SFR: MOV imm or MOV from a register."""
    o = g.r.choice(sorted(SFR_D))
    w = SFR_D[o][0]
    v = sfr_value(g.r, o)
    if o == 0x40 and g.opts.get("intm_fall"):
        # (F5f) INTM's ES0-2 kept falling (as at reset): f_halt0's INTP1 pulse ends at a clock
        # the program does not wait for, so with ES1 made rising between its fall and its rise
        # the rise set EXIC1's IF on one side only (f5t_005 of the first session)
        v &= ~0x54
    lin = G.SFRB + o
    if g.r.random() < 0.5:
        s = g.onchip_seg(lin)
        off = lin - 16 * g.st.seg[s]
        pfx = b"" if s == "DS0" else bytes([G.SEGPFX[s]])
        g.fz(pfx + bytes([0xC5 + w]) + b"\x06" + off.to_bytes(2, "little") + v.to_bytes(w, "little"),
             f"MOV {s}:[{hx(off)}], {hx(v, 2 * w)} (SFR {o:02X}h)", g.key("MOV", "sfr,imm", "dir", "bw"[w - 1], f"{o:02X}"))
    else:
        if w == 2:
            r = g.r.choice([x for x in (0, 1, 2, 3, 5, 6, 7) if x not in g.reserved])
            m = g.mem(w, write=True, lin=lin, exclude=(r,))
            g.mov16(r, v)
        else:
            r = g.r.randrange(8)
            m = g.mem(w, write=True, lin=lin, exclude=(r & 3,))
            g.mov8(r, v)
        g.fz(m.pfx + bytes([0x88 + w - 1]) + m.modrm(r) + m.disp,
             f"MOV {m.text}, {(G.R8 if w == 1 else G.R16)[r]} (SFR {o:02X}h)",
             g.key("MOV", "sfr,r", m.mode, "bw"[w - 1], f"{o:02X}"))


G.Gen.f_sfr = f_sfr


# ------------------------------------------------------------------ layer c bodies
def _onchip_store(g, o, v, w=1):
    lin = G.SFRB + o
    s = g.onchip_seg(lin)
    off = lin - 16 * g.st.seg[s]
    pfx = b"" if s == "DS0" else bytes([G.SEGPFX[s]])
    g.setup(pfx + bytes([0xC5 + w]) + b"\x06" + off.to_bytes(2, "little") + v.to_bytes(w, "little"),
            f"MOV {s}:[{hx(off)}], {hx(v, 2 * w)} (SFR {o:02X}h)")


def _event(g, n):
    g.mov16(DW, 0xFF12)
    g.mov8(0, n)
    g.setup(b"\xEE", f"OUT DW, AL (event {n})")


def _handler(g, p, cnt, stop_timer=False):
    """BR over a bank-switch handler: [MOV byte [0090h], 0;] SS: INC byte [cnt]; FINT; RETRBI."""
    b = g.b
    over, h = b.label(), b.label()
    j = b.emit(b"\xE9\0\0", "BR over the handler", "setup")
    b.fixup(j, 1, "rel16", over)
    b.place(h)
    if stop_timer:
        b.emit(b"\xC6\x06\x90\x00\x00", "H: MOV byte [0090h], 0 (TMC0: stop)", "setup")
    b.emit(b"\x36\xFE\x06" + cnt.to_bytes(2, "little"), f"H: INC byte SS:[{hx(cnt)}]", "setup")
    b.emit(b"\x0F\x92\x0F\x91", "H: FINT; RETRBI", "setup")
    b.place(over)
    g.ready_bank(p, 0)
    lin = G.IRAM + 0x20 * p + SLOT["VPC"]
    s = g.onchip_seg(lin)
    off = lin - 16 * g.st.seg[s]
    pfx = b"" if s == "DS0" else bytes([G.SEGPFX[s]])
    i = b.emit(pfx + b"\xC7\x06" + off.to_bytes(2, "little") + b"\0\0", f"MOV {s}:[{hx(off)}], H (bank {p} vector PC)", "setup")
    b.fixup(i, len(i.data) - 2, "abs", h, 0)
    if stop_timer:
        g.bank_set(p, SLOT["DS0"], 0xFFF0)


def _wait(g, cnt):
    g.setup(b"\xFB", "EI")
    g.setup(b"\x36\x80\x3E" + cnt.to_bytes(2, "little") + b"\x00\x74\xF8", f"W: CMP byte SS:[{hx(cnt)}], 0; BE W")


def _items(g, items, K, lo=0, hi=None):
    for kind, s in items[lo:hi]:
        g.r = random.Random(s)
        g.one(kind)
        if g.fuzz_since >= K:
            g.observe(full=g.obs_n % 4 == 3)


def body_c(scen, r):
    def body(g, items, K):
        if scen == "step":
            i0 = r.randrange(5, 20)
            n = r.randrange(15, 30)
            _items(g, items, K, 0, i0)
            g.observe()
            v = g.psw_value() | 0x0100
            g.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
            g.setup(b"\x9D", "POP PSW (BRK 1: the single step)")
            g.st.dir, g.st.ie = (v >> 10) & 1, (v >> 9) & 1
            _items(g, items, K, i0, i0 + n)
            g.observe()
            v = g.psw_value()
            g.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
            g.setup(b"\x9D", "POP PSW (BRK 0)")
            g.st.dir, g.st.ie = (v >> 10) & 1, (v >> 9) & 1
            _items(g, items, K, i0 + n)
            return
        p = g.opts["protect_bank"]
        cnt = G.CNT + {"intp": 0x40, "timer": 0x41, "nmi": 2}[scen]
        if scen == "intp":
            _handler(g, p, cnt)
            _onchip_store(g, 0x4C, 0x10 | p)        # EXIC0: ENCS, MK 0, PR p
        elif scen == "timer":
            _handler(g, p, cnt, stop_timer=True)
            _onchip_store(g, 0x82, r.randrange(1500, 6000), 2)   # MD0 (>= 9,000 clocks: one count-out)
            _onchip_store(g, 0x9C, 0x10 | p)        # TMIC0: ENCS, MK 0, PR p
        g.setup(b"\xFB", "EI")
        g.st.ie = 1
        g.observe(full=True)
        if scen == "timer":
            _onchip_store(g, 0x90, 0x80)            # TMC0: TS0, interval, SCLK/6
        else:
            _event(g, 1)
        _items(g, items, K)
        _wait(g, cnt)
    return body


# ------------------------------------------------------------------ the sets
def _seed(set_name, k):
    return SETS[set_name]["seed"] + k


def _opts(set_name, k):
    cfg = SETS[set_name]
    r = random.Random(_seed(set_name, k) ^ 0xC0FFEE)
    opts = dict(cfg.get("opts") or {})
    body = None
    stim = None
    mask = set()
    filt = None
    scens = cfg.get("scens", SCEN_C)
    if cfg["layer"] == "c" and scens[k % len(scens)] in ("mix", "mixd"):
        return _opts_mix(scens[k % len(scens)], r, opts)
    if cfg["layer"] == "c":
        scen = scens[k % len(scens)]
        opts["scen"] = scen
        if scen in ("intp", "timer"):
            p = r.randrange(1, 7)
            opts["protect_bank"] = p
            opts["keep_ie"] = True
            mask |= {G.DUMP + 0x20 * p + o for o in range(4, 8)}
            # (F5b) the handler's count store sits where the take lands: dropped from both
            # write sequences (its final value is still compared in the count page)
            filt = _count_filter(G.CNT + (0x40 if scen == "intp" else 0x41))
        if scen == "nmi":
            opts["keep_ie"] = False
        body = body_c(scen, r)
        d = r.randrange(3000, 120000)
        if scen == "intp":
            stim = {"entries": [{"event": 1, "delay": d, "hold": 2000, "levels": {"INTP0": 0}}]}
        elif scen == "nmi":
            stim = {"entries": [{"event": 1, "delay": d, "hold": 2000, "levels": {"NMI": 0}}]}
            mask |= set(range(G.STK_PAGE, G.STK_PAGE + 0x1000))
            filt = _nmi_filter
            body = _nmi_body(body)
    if cfg["layer"] == "d":
        opts["dump_sfr"] = (DUMP_D_BYTES, DUMP_D_WORDS)
        body = body_d
    return opts, body, stim, mask, filt


# ------------------------------------------------------------------ (F5e) layer c: mix, mixd
def _vframe_filter(counts):
    """Drop every vectored take's frame and count store (the take lands where the clocks put
    it): in the order they appear, each count store of a vectored handler (`counts`: NMI's stub,
    the INTP1 / INTP2 handlers) and the six frame bytes before it (a nested take's frame lies
    between an outer frame and the outer count store, and its count store comes first)."""
    def filt(writes):
        out = list(writes)
        i = 0
        while i < len(out):
            a, f = out[i][0], out[i][2]
            if a in counts and not f & 0x02:
                j, n = i, 0
                while j > 0 and n < 6:
                    j -= 1
                    aa, ff = out[j][0], out[j][2]
                    n += 1 if (aa & 1 or ff & 0x08) else 2
                del out[j:i + 1]
                i = j
            else:
                i += 1
        return out
    return filt


def _chain(*fs):
    def filt(writes):
        for f in fs:
            writes = f(writes)
        return writes
    return filt


def _opts_mix(scen, r, opts):
    """mix: two or three of INTP0 (a bank-switch entry, bank p0 = its level), TM0 (bank-switch,
    bank p1), NMI (vectored: the stub), INTP1 (vectored, its handler enables interrupts for a few
    NOPs: a higher level or NMI nests there; INTP1 runs at EXIC0's level), each at a random
    delay; the program waits for every count. mixd: no asynchronous source; the items f_stepint
    (INTP0's bank switch at a known boundary), f_halt1 (INTP2 vectored, out of HALT), f_repint
    (INTP1 vectored inside a REP string, its handler recording the pushed PC and PSW)."""
    opts["scen"] = scen
    opts["keep_ie"] = True
    p0 = r.randrange(1, 7)
    p1 = r.choice([x for x in range(1, 7) if x != p0])
    mask = set()
    entries = []
    if scen == "mixd":
        srcs = ("p0", "p1v", "p2v")
        opts["mixd"] = True
    else:
        srcs = tuple(sorted(r.sample(("p0", "t0", "nmi", "p1v"), r.choice((2, 2, 3)))))
    banks = {p0} | ({p1} if "t0" in srcs else set())
    opts["protect_bank"] = p0
    opts["protect_banks"] = tuple(sorted(banks))
    for p in banks:
        mask |= {G.DUMP + 0x20 * p + o for o in range(4, 8)}
    cnts = {"p0": G.CNT + 0x40, "t0": G.CNT + 0x41, "nmi": G.CNT + 2, "p1v": G.CNT + 25,
            "p2v": G.CNT + 26}
    filts = [_count_filter(cnts[s]) for s in srcs if s in ("p0", "t0")]
    vec = {cnts[s] for s in srcs if s in ("nmi", "p1v", "p2v")}
    if vec:
        filts.append(_vframe_filter(vec))
        mask |= set(range(G.STK_PAGE, G.STK_PAGE + 0x1000))
    nest = r.randrange(1, 5)
    ev = {"p0": (1, "INTP0"), "nmi": (2, "NMI"), "p1v": (3, "INTP1")}
    if scen == "mix":
        # the schedule runs its entries in order (docs/v35s-harness.md): one event, the other
        # sources chained after it (each a random delay after the last one's pulse)
        first = True
        for s in srcs:
            if s in ev:
                entries.append({"event": 1 if first else None,
                                "delay": r.randrange(3000, 120000) if first else r.randrange(10, 20000),
                                "hold": 2000, "levels": {ev[s][1]: 0}})
                first = False
    md0 = r.randrange(1500, 6000)

    def body(g, items, K):
        if "p0" in srcs:
            _handler(g, p0, cnts["p0"])
            _onchip_store(g, 0x4C, 0x10 | p0)        # EXIC0: ENCS, MK 0, PR p0
        else:
            _onchip_store(g, 0x4C, 0x40 | p0)        # EXIC0: MK 1, PR p0 (INTP1 / INTP2's level)
        if "t0" in srcs:
            _handler(g, p1, cnts["t0"], stop_timer=True)
            _onchip_store(g, 0x82, md0, 2)          # MD0 (>= 9,000 clocks: one count-out)
            _onchip_store(g, 0x9C, 0x10 | p1)       # TMIC0: ENCS, MK 0, PR p1
        if "p1v" in srcs:
            G2._vec_handler(g, 25, record=scen == "mixd", nest=0 if scen == "mixd" else nest)
            if scen == "mix":
                _onchip_store(g, 0x4D, 0x07)        # EXIC1: MK 0, vectored
        if "p2v" in srcs:
            G2._vec_handler(g, 26)
        g.setup(b"\xFB", "EI")
        g.st.ie = 1
        g.observe(full=True)
        if scen == "mix":
            if "t0" in srcs:
                _onchip_store(g, 0x90, 0x80)        # TMC0: TS0, interval, SCLK/6
            if any(s in ev for s in srcs):
                _event(g, 1)
        _items(g, items, K)
        if scen == "mix":
            for s in srcs:
                _wait(g, cnts[s])
    stim = {"entries": entries} if entries else None
    return opts, body, stim, mask, _chain(*filts)


def _nmi_body(inner):
    def body(g, items, K):
        g.observe(full=True)
        _event(g, 1)
        _items(g, items, K)
        _wait(g, G.CNT + 2)
    return body


def _count_filter(cnt):
    def filt(writes):
        return [w for w in writes if not (w[0] == cnt and not w[2] & 0x02)]
    return filt


def _nmi_filter(writes):
    """Drop the NMI's frame (the three pushes before the stub's count store) and the store.
    (F5c) The frame is six bytes: three records at an even SP, six byte records at an odd SP (a
    word at an odd address is two byte cycles; the fuzz's INC SP / DEC SP leave SP odd): the
    records are counted back by their bytes (one at an odd address or with /UBE high, else
    two)."""
    out = list(writes)
    for i in range(len(out) - 1, -1, -1):
        if out[i][0] == G.CNT + 2 and not out[i][2] & 0x02:
            j, n = i, 0
            while j > 0 and n < 6:
                j -= 1
                a, f = out[j][0], out[j][2]
                n += 1 if (a & 1 or f & 0x08) else 2
            del out[j:i + 1]
            break
    return out


def body_d(g, items, K):
    for o in (0x80, 0x88):              # TM0 / TM1 defined (the timers stopped)
        _onchip_store(g, o, g.r.randrange(0x10000), 2)
    _items(g, items, K)


def _mk(set_name, name, seed, items, k):
    cfg = SETS[set_name]
    opts, body, stim, mask, filt = _opts(set_name, k)
    bt = G.build(name, cfg["layer"], seed, items, opts, body)
    if stim and bt.stim:
        bt.stim = {"entries": stim["entries"] + bt.stim["entries"]}     # (F5e) the items' events
    elif stim or not bt.stim:
        bt.stim = stim
    bt.mask |= mask
    if filt:
        bt.write_filter = filt
    bt.meta["scen"] = opts.get("scen")
    return bt


def makers(set_name):
    if set_name in ("f5x", "f5r", "f5o"):
        from . import fuzz_flags
        yield from {"f5x": fuzz_flags.makers, "f5r": fuzz_flags.makers_r,
                    "f5o": fuzz_flags.makers_o}[set_name]()
        return
    cfg = SETS[set_name]
    for k in range(cfg["n"]):
        name = f"{set_name}_{k:03d}"
        seed = _seed(set_name, k)
        items = G.draw_items(seed, cfg["items"], cfg.get("weights"))
        yield name, (lambda name=name, seed=seed, items=items, k=k: _mk(set_name, name, seed, items, k))


def rebuild(set_name, name):
    k = int(name.rsplit("_", 1)[1])
    seed = _seed(set_name, k)
    return lambda items: _mk(set_name, name, seed, items, k)
