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
    f5x  the flag survey (validation/v35s/fuzz_flags.py)

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
from .fuzz_gen import AW, DW, SLOT, hx

W_B = dict(G.WEIGHTS, f_bank=14)
W_C = {k: v for k, v in G.WEIGHTS.items() if k not in ("f_retiw",)}
W_D = dict({k: v for k, v in G.WEIGHTS.items()}, f_sfr=40)

SETS = {
    "f5a": dict(layer="a", n=300, items=110, seed=0x5A000000),
    "f5b": dict(layer="b", n=150, items=110, seed=0x5B000000, weights=W_B),
    "f5c": dict(layer="c", n=160, items=90, seed=0x5C000000, weights=W_C),
    "f5d": dict(layer="d", n=100, items=90, seed=0x5D000000, weights=W_D),
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
    if cfg["layer"] == "c":
        scen = SCEN_C[k % 4]
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
    """Drop the NMI's frame (the three pushes before the stub's count store) and the store."""
    out = list(writes)
    for i in range(len(out) - 1, -1, -1):
        if out[i][0] == G.CNT + 2 and not out[i][2] & 0x02:
            del out[max(0, i - 3):i + 1]
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
    bt.stim = stim
    bt.mask |= mask
    if filt:
        bt.write_filter = filt
    bt.meta["scen"] = opts.get("scen")
    return bt


def makers(set_name):
    if set_name in ("f5x", "f5r"):
        from . import fuzz_flags
        yield from (fuzz_flags.makers() if set_name == "f5x" else fuzz_flags.makers_r())
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
