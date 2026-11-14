"""(F5e) The generator's remaining coverage gaps (batch 4's list), as item kinds the third
generation draws (validation/v35s/fuzz_layers.py SETS f5j-f5n). Imported by fuzz_layers; every
kind raises Retry unless its set's options enable it, so the sets f5a-i (whose weights do not
name these kinds) are unchanged.

    f_spwrap  SP through 0000h / FFFFh (opts["gap2"]): SS 0600h, SP a few bytes from 0000h or
              FFFFh; PUSH / POP of registers, segment registers and immediates, PUSH PSW,
              CALL / RET, PUSH R / POP R, BRK n (the vectored frame through the wrap),
              PREPARE / DISPOSE; then SS 0 and SP as before. SS:0000h is 06000h (the stack page's
              first bytes, below the window the other items use), SS:FFFFh 15FFFh, an odd word's
              second half at FFFFh the linear address + 1 (16000h); the stubs' counts SS:[7E00h
              + n] land at 0DE00h + n: the pages 15h, 16h and 0DE00h-0DEFFh are loaded and
              compared (fuzz_gen.build, opts["gap2"])
    f_poll    POLL (P14 low: the INT pin at rest, PM1's bit 4 either way)
    f_illreg  the register forms silicon runs as two-byte NOPs: 62 / 8D / C4 / C5 mod 11, FF /3
              /5 /7 mod 11, FE /3 /5 /7 mod 11 (traps.py's modrm series)
    f_halt0   HALT with IE 0 left by INTP1 (EXIC1 MK 0 for the HALT, its IF cleared after: no
              take; the event port and a schedule entry per HALT); layers a, b, d
    (layer c, scenario mixd: deterministic interrupt combinations, opts["mixd"])
    f_stepint the single step and a maskable request on one boundary: the request pending
              (EXIC0's IF stored with IE 0), POP PSW setting IE and BRK, MULU CL (the absorber:
              longer than the release's latency on silicon, f3_step2 step_intp), stepped items,
              POP PSW clearing BRK
    f_halt1   HALT with IE 1 left by INTP2 (vectored, its handler counts and FINTs; a NOP sled:
              silicon's take lands HALT + 1 or + 2, the frame is filtered)
    f_repint  a request pending, EI, then a REP string with prefixes: the take after the first
              element (f5_si_ops), the vectored handler (INTP1) records the pushed PC and PSW in
              the count page

    (F5g) f_d6  D6 /r (opts["d6"]): CLR1 r/m8 with the bit number in the ModR/M reg field
              (silicon, validation/v35s/d6.py; built in F5g): a byte register or a memory
              operand of the generator's regions, every reg field (set f5v)

Not added: F1 BRKS (the handler runs in secure mode: the opcode translation, not self-contained) and
0F 9E STOP (released by NMI only after 2^19 clocks).
"""

from __future__ import annotations

from . import fuzz_gen as G
from .fuzz_gen import AW, BP, CW, DW, R16, Retry, SP, hx

WRAP_SS = 0x0600
WRAP_PAGES = (0x15000, 0x2000)          # SS:F000h-FFFFh and the odd word's second half
WRAP_CNT = 0x6000 + G.CNT               # the stubs' counts under SS 0600h (0DE00h)
EXIC0, EXIC1, EXIC2 = 0x4C, 0x4D, 0x4E
V_P1, V_P2 = 25, 26
REC = G.CNT + 0x80                      # f_repint's records (the count page: compared)


def _onchip_store(g, o, v, w=1, fz_key=None):
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


def new_event(g, pin, delay=12000):
    if AW in g.reserved or DW in g.reserved:
        raise Retry("rsv")
    n = g.opts.setdefault("ev_next", 8)
    if n > 31:
        raise Retry("events")
    g.opts["ev_next"] = n + 1
    g.events.append({"event": n, "delay": delay, "hold": 2000, "levels": {pin: 0}})
    return n


# ------------------------------------------------------------------ SP through 0000h / FFFFh
def f_spwrap(self):
    if not self.opts.get("gap2") or self.ctx or self.opts.get("scen") in ("intp", "nmi", "timer", "mix", "mixd"):
        raise Retry("spwrap")
    if "SPN" in self.reserved or "SS" in self.reserved:
        raise Retry("rsv")
    st = self.st
    sp0 = st.sp
    if sp0 is None:
        raise Retry("sp")
    self.load_seg("SS", WRAP_SS)
    start = self.r.choice((0x0000, 0x0002, 0x0004, 0x0006, 0x0001, 0x0003, 0x0005, 0xFFFE,
                           0xFFFC, 0xFFFF, 0xFFFD, 0xFFFA, 0x000A))
    self.setup(b"\xBC" + start.to_bytes(2, "little"), f"MOV SP, {hx(start)} (the wrap)")
    st.set16(SP, start, dirty=False)
    st.stack = {}
    sp = start

    def ok(v):
        return v <= 0x0080 or v >= 0xFF80
    free = [r for r in (0, 1, 2, 3, 5, 6, 7) if r not in self.reserved]
    for _ in range(self.r.randrange(3, 9)):
        kind = self.r.choice(("push", "push", "pop", "pop", "imm", "sreg", "psw", "call", "pusha",
                              "brk", "prepare", "pushsp"))
        if kind == "push":
            r = self.r.randrange(8)
            self.fz(bytes([0x50 + r]), f"PUSH {R16[r]} (wrap)", self.key("PUSH", "r16", "", "w", "wrap"))
            sp = (sp - 2) & 0xFFFF
        elif kind == "pushsp":
            self.fz(b"\xFF\xF4", "PUSH SP (FF /6, wrap)", self.key("PUSH", "rm", "reg", "w", "wrap"))
            sp = (sp - 2) & 0xFFFF
        elif kind == "pop":
            if not free:
                continue
            r = self.r.choice(free)
            self.fz(bytes([0x58 + r]), f"POP {R16[r]} (wrap)", self.key("POP", "r16", "", "w", "wrap"))
            st.set16(r, None)
            sp = (sp + 2) & 0xFFFF
        elif kind == "imm":
            v = self.r.randrange(0x10000)
            self.fz(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)} (wrap)", self.key("PUSH", "imm16", "", "w", "wrap"))
            sp = (sp - 2) & 0xFFFF
        elif kind == "sreg":
            s = self.r.randrange(4)
            self.fz(bytes([0x06 + 8 * s]), f"PUSH {G.SREG[s]} (wrap)", self.key("PUSH", "sreg", "", "w", "wrap"))
            sp = (sp - 2) & 0xFFFF
        elif kind == "psw":
            if not free:
                continue
            r = self.r.choice(free)
            self.fz(b"\x9C", "PUSH PSW (wrap)", self.key("PUSH PSW", "wrap", "", "", ""))
            self.fz(bytes([0x58 + r]), f"POP {R16[r]} (wrap)", self.key("POP", "r16", "", "w", "wrap"))
            st.set16(r, None)
        elif kind == "call":
            # CALL to a RET two bytes on; the return lands on a BR over it
            self.fz(b"\xE8\x02\x00\xEB\x01\xC3", "CALL +2; BR +1; RET (wrap)", self.key("CALL", "near", "", "", "wrap"))
        elif kind == "pusha":
            if any(r in self.reserved for r in range(8)):
                continue
            self.fz(b"\x60", "PUSH R (wrap)", self.key("PUSH R", "wrap", "", "", ""))
            if self.r.random() < 0.7:
                self.fz(b"\x61", "POP R (wrap)", self.key("POP R", "wrap", "", "", ""))
            else:
                sp = (sp - 16) & 0xFFFF
        elif kind == "brk":
            v = self.r.randrange(256)
            while v in (2, 7, 0x40, 0x41, V_P1, V_P2):
                v = self.r.randrange(256)
            self.fz(bytes([0xCD, v]), f"BRK {hx(v, 2)} (wrap: the frame)", self.key("BRK", "wrap", "", "", ""))
        elif kind == "prepare":
            if BP in self.reserved:
                continue
            lvl = self.r.choice((0, 1, 2, 3))
            size = self.r.choice((0, 2, 1, 4))
            bpv = self.r.choice(((sp + 2) & 0xFFFF, (sp + 4) & 0xFFFF, (sp + 1) & 0xFFFF))
            old = st.get16(BP)
            self.mov16(BP, bpv)
            self.fz(b"\xC8" + size.to_bytes(2, "little") + bytes([lvl]), f"PREPARE {size}, {lvl} (wrap)",
                    self.key("PREPARE", "wrap", "", "", ""))
            self.fz(b"\xC9", "DISPOSE (wrap)", self.key("DISPOSE", "wrap", "", "", ""))
            st.set16(BP, bpv)
            del old
            # DISPOSE: SP <- the frame + 2 = SP before PREPARE; BP <- the pushed BP (bpv)
        if not ok(sp):
            raise Retry("wrap range")
    # back: SS 0, SP as before
    self.setup(b"\x68\x00\x00", "PUSH 0000h")
    self.setup(b"\x17", "POP SS")
    self.setup(b"\xBC" + sp0.to_bytes(2, "little"), f"MOV SP, {hx(sp0)}")
    st.seg["SS"] = 0
    st.set16(SP, sp0, dirty=False)
    st.stack = {}


def f_poll(self):
    if not self.opts.get("gap2"):
        raise Retry("gap2")
    self.fz(b"\x9B", "POLL (P14 low)", self.key("POLL", "", "", "", ""))


def f_illreg(self):
    if not self.opts.get("gap2"):
        raise Retry("gap2")
    op, reg = self.r.choice(((0x62, None), (0x8D, None), (0xC4, None), (0xC5, None), (0xFF, 3),
                             (0xFF, 5), (0xFF, 7), (0xFE, 3), (0xFE, 5), (0xFE, 7)))
    reg = self.r.randrange(8) if reg is None else reg
    rm = self.r.randrange(8)
    self.fz(bytes([op, 0xC0 | reg << 3 | rm]), f"{op:02X} /{reg} reg {rm} (a two-byte NOP)",
            self.key("ILLREG", f"{op:02X}", "reg", "", f"{reg}"))


def f_d6(self):
    """(F5g) D6 /r: CLR1 r/m8, the bit number in the reg field (d6.py: the memory form always
    writes the byte back; the flags unchanged)."""
    if not self.opts.get("d6"):
        raise Retry("d6")
    m, rr, t = self.rm_operand(1, write=True)
    reg = self.r.randrange(8)
    data = (m.pfx if m else b"") + bytes([0xD6]) + self.modrm_bytes(m, rr, reg)
    self.fz(data, f"D6 /{reg} {t} (CLR1 {t}, {reg})",
            self.key("D6", f"{reg}", m.mode if m else "reg", "b", m.region if m else ""))
    if m:
        self.wrote_mem(m)
    else:
        self.reg_write(1, rr)


def f_halt0(self):
    if not self.opts.get("gap2") or self.ctx or self.layer == "c":
        raise Retry("halt0")
    st = self.st
    if st.ie is None:
        raise Retry("ie")
    n = new_event(self, "INTP1")
    if st.ie:
        self.setup(b"\xFA", "DI")
    _onchip_store(self, EXIC1, 0x07)
    _event(self, n)
    self.fz(b"\xF4", "HALT (IE 0: INTP1 releases it)", self.key("HALT", "ie0", "", "", ""))
    self.setup(b"\x90", "NOP")
    _onchip_store(self, EXIC1, 0x47)
    if st.ie:
        self.setup(b"\xFB", "EI")


# ------------------------------------------------------------------ layer c: mixd
def _vec_handler(g, v, record=False, nest=0):
    """A vectored handler placed in the code (a BR over it), vector v's entry pointed at it:
    SS: INC byte [7E00h + v]; (record: the pushed PC and PSW into REC + 4k); (nest: EI and
    `nest` NOPs, a higher level or NMI may nest there; DI); FINT; RETI."""
    b = g.b
    over, h = b.label(), b.label()
    j = b.emit(b"\xE9\0\0", "BR over the handler", "setup")
    b.fixup(j, 1, "rel16", over)
    b.place(h)
    b.emit(b"\x36\xFE\x06" + (G.CNT + v).to_bytes(2, "little"), f"H{v}: INC byte SS:[{hx(G.CNT + v)}]", "setup")
    if record:
        # PUSH BP; MOV BP,SP; PUSH AW; PUSH BW; MOV BW,SS:[7E7Eh]; MOV AW,[BP+2]; MOV SS:[BW+7E80h],AW;
        # MOV AW,[BP+6]; MOV SS:[BW+7E82h],AW; ADD BW,4; MOV SS:[7E7Eh],BW; POP BW; POP AW; POP BP
        b.emit(bytes.fromhex("55" "8BEC" "50" "53" "368B1E7E7E" "8B4602" "368987807E"
                             "8B4606" "368987827E" "83C304" "36891E7E7E" "5B" "58" "5D"),
               f"H{v}: the pushed PC and PSW recorded", "setup")
    if nest:
        b.emit(b"\xFB" + b"\x90" * nest + b"\xFA", f"H{v}: EI; NOP x {nest}; DI", "setup")
    b.emit(b"\x0F\x92\xCF", f"H{v}: FINT; RETI", "setup")
    b.place(over)
    i = b.emit(b"\x36\xC7\x06" + (4 * v).to_bytes(2, "little") + b"\0\0", f"MOV SS:[{hx(4 * v)}], H{v}", "setup")
    b.fixup(i, len(i.data) - 2, "abs", h, 0)
    b.emit(b"\x36\xC7\x06" + (4 * v + 2).to_bytes(2, "little") + b"\0\0", f"MOV SS:[{hx(4 * v + 2)}], 0", "setup")


def _need_mixd(g):
    if not g.opts.get("mixd") or g.ctx:
        raise Retry("mixd")
    if any(r in g.reserved for r in (AW, CW, DW)) or "DIR" in g.reserved:
        raise Retry("rsv")


def f_stepint(self):
    _need_mixd(self)
    st = self.st
    p = self.opts["protect_bank"]
    self.setup(b"\xFA", "DI")
    _onchip_store(self, EXIC0, 0x90 | p)           # IF 1, ENCS 1, MK 0, PR p: pending
    v = self.psw_value() | 0x0300                    # IE 1, BRK 1
    self.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
    self.setup(b"\x9D", "POP PSW (IE 1 and BRK 1 with the request pending)")
    st.dir, st.ie = (v >> 10) & 1, 1
    self.fz(b"\xF6\xE1", "MULU CL (the absorber: the take after it)", self.key("MULU", "stepint", "reg", "b", ""))
    st.set16(AW, None)
    for _ in range(self.r.randrange(2, 6)):
        self.one(self.r.choice(("f_alu", "f_mov", "f_incdec", "f_shift", "f_pushpop", "f_str")))
    v = self.psw_value() | 0x0200
    self.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
    self.setup(b"\x9D", "POP PSW (BRK 0)")
    st.dir, st.ie = (v >> 10) & 1, 1
    self.opts["n_p0"] = self.opts.get("n_p0", 0) + 1


def f_halt1(self):
    _need_mixd(self)
    n = new_event(self, "INTP2")
    self.setup(b"\xFB", "EI")
    self.st.ie = 1
    _onchip_store(self, EXIC2, 0x07)
    _event(self, n)
    self.fz(b"\xF4", "HALT (IE 1: INTP2 vectored)", self.key("HALT", "ie1", "", "", ""))
    self.setup(b"\x90\x90\x90", "NOP x 3 (the take lands HALT + 1 or + 2)")
    _onchip_store(self, EXIC2, 0x47)
    self.opts["n_p2"] = self.opts.get("n_p2", 0) + 1


def f_repint(self):
    _need_mixd(self)
    st = self.st
    if any(r in self.reserved for r in (G.IX, G.IY)):
        raise Retry("rsv")
    if self.opts.get("n_p1", 0) >= 24:
        raise Retry("records")
    self.setup(b"\xFA", "DI")
    _onchip_store(self, EXIC1, 0x87)               # IF 1, MK 0: pending (vectored)
    op = self.r.choice((0xA4, 0xA5, 0xAA, 0xAB, 0xAC, 0xAD, 0xA6, 0xA7, 0xAE, 0xAF))
    n = self.r.randrange(2, 9)
    pf = self.r.choice(([], [0x2E], [0x26], [0x36], [0x3E], [0xF0]))
    rep = self.r.choice((0xF3, 0xF2) if op in (0xA6, 0xA7, 0xAE, 0xAF) else (0xF3,))
    pfx = bytes(pf + [rep]) if self.r.random() < 0.5 else bytes([rep] + pf)
    # the operands in the data window, DIR 0
    self.setup(b"\xFC", "CLR1 DIR")
    st.dir = 0
    self.mov16(CW, n)
    self.mov16(G.IX, self.r.randrange(0, 0x200) & ~1)
    self.mov16(G.IY, self.r.randrange(0x200, 0x400) & ~1)
    for s, v in (("DS0", G.DATA_LO >> 4), ("DS1", G.DATA_LO >> 4)):
        if s in self.reserved:
            raise Retry("rsv")
        if st.seg[s] != v:
            self.load_seg(s, v)
    if 0x26 in pf or 0x2E in pf or 0x36 in pf or 0x3E in pf:
        seg = {0x26: "DS1", 0x2E: "PS", 0x36: "SS", 0x3E: "DS0"}[[x for x in pf if x != 0xF0][0]]
        # the override's segment reaches the data window: PS and SS are 0 (the window at
        # 04000h + IX: offsets 4000h-41FFh)
        if seg in ("PS", "SS"):
            self.mov16(G.IX, 0x4000 + (self.r.randrange(0, 0x200) & ~1))
    self.setup(b"\xFB", "EI")
    st.ie = 1
    self.fz(pfx + bytes([op]), f"{pfx.hex(' ')} {op:02X} (the take after the first element)",
            self.key("REPINT", f"{op:02X}", "", "", ""))
    for r in (CW, G.IX, G.IY):
        st.set16(r, None)
    if op in (0xAC, 0xAD):
        st.set16(AW, None)
    _onchip_store(self, EXIC1, 0x47)
    self.opts["n_p1"] = self.opts.get("n_p1", 0) + 1


for _f in (f_spwrap, f_poll, f_illreg, f_halt0, f_stepint, f_halt1, f_repint, f_d6):
    setattr(G.Gen, _f.__name__, _f)

_one = G.Gen.one


def _one_events(self, name, tries=6):
    """Gen.one with the schedule entries an item announced dropped with its retry (an entry
    left without its event's OUT would hold every later entry: the schedule runs in order)."""
    n = len(self.events)
    snap = [n]

    def keep():
        del self.events[snap[0]:]
    ok = False
    for _ in range(tries):
        if _one(self, name, tries=1):
            ok = True
            break
        keep()
    return ok


G.Gen.one = _one_events
