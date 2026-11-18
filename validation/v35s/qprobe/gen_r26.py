"""Round 26.

r26a  the last string element (Q120): the seven word string forms single with the element's last
      cycle at an odd pointer and at even pointers (the control), behind eight leads (INC BW, CLC,
      CBW, NOP, JMP $+2, OUT imm8, PUSH, a store) and followed by nothing / NOP.
r26b  the byte string forms at odd pointers (one byte cycle at an odd address: not a pair).
r26c  REP forms with CW = 1, 2, 3 at odd and even pointers (the first element as the last one).
r26d  write / read pairs outside the string routines: SP odd against SP even for PUSHA, PUSHA ; POPA,
      CALL near, CALL / RET, PUSH imm16, PUSH [BW], POP [BW], PUSH PSW, CALL far.
r26e  INT stepped one clock at a time across a store through [BW] (BW even / odd), the same with
      OUT imm8 behind it, and MOVBK (IY even / odd): the pop of the next opcode as the interrupt
      sees it (Q75: the pop replaced is the first at or after the edge + 9.125).
r26f  INT 3 behind fourteen predecessors (vector stored before M0), 0 / 1 NOP at the handler.
r26g  MOV [d16],AW (A3) against 89 06 and [BW+d8]: behind pads at more queue fills.
r26i  EI in the body (its words' clocks known from the long shift), INTP0 at level 7 requested
      long before with IE = 0: EI behind pads of 0 to 17 clocks and behind JMP $+2 / OUT imm8 (a fetch
      in flight on EI's bus-idle third word), trains MOV AW,[BW] / INC BW / NOP behind it; the masked
      twin of each load-train run. Where the level scan's lattice stands against EI's words.
r26j  r26e's method on more tails: MOVBK (the window r26e missed), CMPBK (IX), LDM, CMPM, STM single at
      even / odd pointers, a read-modify-write through [BW] even / odd, and MOV [d16],imm16 directly
      behind OUT imm8 (Q125's state: the write behind a fetch).
r26k  the accumulator stores byte and word (A2 / A3) beside 88 06 / 89 06 behind the leads of r25b that
      leave no fetch on the displacement's pop (a load or PUSH and a pad): is A2 as A3 (f4_dma's stores
      are A2).
r26l  round 8's `ld-int3` frame (the two vector stores in the body, a predecessor, the subject) with nine
      subjects in INT 3's place: is the state the RTL misses (QPr8-ld-int3-n-pE-w0) INT 3's or the frame's.
r26m  the other transfers with a stack cycle, SP odd against SP even: CALL r16, CALL [d16], INT 3, BRK imm8,
      RETF, RET imm16, CALL near and CALL far behind a NOP (r26d: CALL near's push has the long wait,
      CALL far's has not).
r26n  relative transfers directly behind a store's pair (BW odd against even): JMP short, JMP near, JZ taken,
      CALL near, LOOP: does a word that forms PC + displacement wait behind a pair as CALL near's own does.
r26h  a DMA transfer (I/O to memory, DMARQ0 edge stepped one clock, DIC0 masked) across trains of
      A3 / 89 06 / [BW+d8] stores, alone and with a NOP between: where the store's request stands
      against an asynchronous claim (the forms side by side: differential).
"""

from .gen import BODY_AT, M1I, NOP, SLOW, q
from .gen_r25 import CBW, CLC, LDACC, NOPL, ODD, OUT22, POP, PTR, PUSH, SACC, STR, _p

INCBW, J0 = [0x43], [0xEB, 0x00]
STRW = dict(STR, outm=[0x6F])
STRB = {"movbkb": [0xA4], "cmpbkb": [0xA6], "stmb": [0xAA], "ldmb": [0xAC], "cmpmb": [0xAE],
        "inmb": [0x6C], "outmb": [0x6E]}
LASTP = {"movbk": "iy", "cmpbk": "ix", "inm": "iy", "stm": "iy", "ldm": "ix", "cmpm": "iy", "outm": "ix"}
A_LEADS = {"i": [INCBW], "c": [CLC], "k": [CBW], "n": [NOPL], "j": [J0], "o": [OUT22], "p": [PUSH],
           "s": [SACC]}


def _regs(op, pn):
    return {**PTR[pn], **({"DW": 0x0040} if op[:3] in ("inm", "out") else {})}


def round26a():
    v = []
    for op, code in STRW.items():
        for pn in ("ev", LASTP[op]):
            for ln, lc in A_LEADS.items():
                v.append(_p(f"{ln}-{op}-{pn}-0", lc + [code], _regs(op, pn)))
                v.append(_p(f"{ln}-{op}-{pn}-nop", lc + [code, NOPL], _regs(op, pn)))
    return v


def round26b():
    v = []
    for op, pn in (("movbkb", "iy"), ("movbkb", "xy"), ("movbkb", "ev"), ("cmpbkb", "ix"), ("cmpbkb", "ev"),
                   ("stmb", "iy"), ("inmb", "iy"), ("ldmb", "ix"), ("cmpmb", "iy"), ("outmb", "ix")):
        v.append(_p(f"{op}-{pn}-0", [STRB[op]], _regs(op, pn)))
        v.append(_p(f"{op}-{pn}-nop", [STRB[op], NOPL], _regs(op, pn)))
    return v


def round26c():
    v = []
    forms = (("movbk", ("iy", "ix", "xy", "ev")), ("stm", ("iy", "ev")), ("ldm", ("ix", "ev")),
             ("cmpm", ("iy", "ev")), ("cmpbk", ("ix", "iy", "ev")), ("inm", ("iy", "ev")), ("outm", ("ix", "ev")))
    for op, ps in forms:
        for pn in ps:
            for n in (1, 2, 3):
                pre = [[0xB8, 0x90, 0x90]] if op == "cmpm" else []
                v.append(_p(f"rep{n}-{op}-{pn}", pre + [[0xB9, n, 0x00], [0xF3] + STRW[op], [0x42]], _regs(op, pn)))
    return v


def round26d():
    v = []
    for sn, sp in (("o", 0x0F01), ("e", 0x0F00)):
        r = {"SP": sp}
        progs = {"pusha": [[0x60]], "pusha-nop": [[0x60], NOPL], "pp": [[0x60], [0x61]], "pp-nop": [[0x60], [0x61], NOPL],
                 "call": [[0xE8, 0x00, 0x00]], "call-nop": [[0xE8, 0x00, 0x00], NOPL],
                 "cr": [[0xE8, 0x03, 0x00], NOPL, [0xEB, 0x01], [0xC3]],
                 "pushi": [[0x68, 0x34, 0x12]], "pushi-nop": [[0x68, 0x34, 0x12], NOPL],
                 "pushm": [[0xFF, 0x37]], "pushm-nop": [[0xFF, 0x37], NOPL],
                 "popm": [PUSH, [0x8F, 0x07]], "popm-nop": [PUSH, [0x8F, 0x07], NOPL],
                 "pushf": [[0x9C]], "pushf-nop": [[0x9C], NOPL]}
        v += [_p(f"{n}-{sn}", c, r) for n, c in progs.items()]
        for n, tail in (("callf", []), ("callf-nop", [NOPL])):
            def far(parity, tail=tail, r=r):
                at = BODY_AT[parity] + 5
                return ([q([0x9A, at & 0xFF, at >> 8, 0x00, 0x10], "callf")] + [q(c, "t") for c in tail], M1I, dict(r))
            v.append((f"{n}-{sn}", far))
    return v


def _irun(name, body, regs, d):
    from .gen_r15 import INT_STIM, handler, int_pre, pad_even
    st = dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": 0, "levels": {"INT": 1}}])
    extra = {"_pre": pad_even(list(int_pre())), "_post": handler(), "_stim": st, "_waits": (0,), **regs}
    return (name, ([q(c, "x") for c in body], None, extra))


def round26e():
    from .gen_r17 import tick
    st = [0x89, 0x07]
    progs = {"st-e": ([NOPL, NOPL, st] + [NOPL] * 8, {"BW": 0x0800}), "st-o": ([NOPL, NOPL, st] + [NOPL] * 8, ODD),
             "sto-e": ([NOPL, NOPL, st, OUT22] + [NOPL] * 8, {"BW": 0x0800}),
             "sto-o": ([NOPL, NOPL, st, OUT22] + [NOPL] * 8, ODD),
             "mv-e": ([NOPL, NOPL, [0xA5]] + [NOPL] * 8, PTR["ev"]), "mv-o": ([NOPL, NOPL, [0xA5]] + [NOPL] * 8, PTR["iy"])}
    v = []
    for n, (body, regs) in progs.items():
        for e in range(68, 100):
            v.append(_irun(f"{n}-e{e}", body, regs, tick(e)))
    return v


def round26f():
    w16 = lambda x: [x & 0xFF, x >> 8]
    vec = lambda a: [q([0xC7, 0x06, 0x0C, 0x00] + w16(a), "vec_ip"), q([0xC7, 0x06, 0x0E, 0x00, 0x00, 0x10], "vec_ps")]
    preds = {"0": [], "i": [INCBW], "k": [CBW], "n": [NOPL], "c": [CLC], "rr": [[0x8B, 0xC3]], "ri": [[0xBB, 0x00, 0x08]],
             "st": [SACC], "ld": [LDACC], "pu": [PUSH], "o": [OUT22], "j": [J0], "nn": [NOPL, NOPL], "ii": [INCBW, INCBW],
             "sb": [[0x89, 0x07]], "jn": [J0, NOPL]}
    v = []
    for pn, pad in preds.items():
        for n in (0, 1):
            def f(parity, pad=pad, n=n):
                a = BODY_AT[parity] + 12 + sum(len(c) for c in pad) + 1
                return ([q(c, "pad") for c in pad] + [q([0xCC], "int3")] + [q(NOP, "nop")] * n, None, {"_pre": vec(a)})
            v.append((f"i3-{pn}-{n}", f))
    return v


G_FORMS = {"sacc": SACC, "sdir": [0x89, 0x06, 0x00, 0x0C], "s8": [0x89, 0x47, 0x10]}


def round26g():
    pads = {"i": [INCBW], "ii": [INCBW] * 2, "iii": [INCBW] * 3, "rr": [[0x8B, 0xC3]], "rr2": [[0x8B, 0xC3]] * 2,
            "ri": [[0xB8, 0x34, 0x12]], "j": [J0], "jn": [J0, NOPL], "ji": [J0, INCBW]}
    v = []
    for pn, pc in pads.items():
        for fn, fc in G_FORMS.items():
            v.append(_p(f"{pn}-{fn}", pc + [fc]))
            v.append(_p(f"{pn}-{fn}-sh", pc + [fc, SLOW]))
    return v


def round26h(which):
    from .gen_r15 import run
    from .gen_r17 import tick
    from .gen_r23 import hnd, pre_a, rq
    tr = {"sacc": [SACC] * 30, "sdir": [G_FORMS["sdir"]] * 26, "s8": [G_FORMS["s8"]] * 30,
          "sacb": [[0xA2, 0x00, 0x0C]] * 30, "saccn": [SACC, NOPL] * 18, "sdirn": [G_FORMS["sdir"], NOPL] * 16}[which]
    return [run(f"h-{which}-e{e}", pre_a(0x47), tr, rq(tick(e)), hnd(True)) for e in range(60, 97)]


def round26i():
    from .gen_r14 import EI, sfr_b
    from .gen_r15 import DS1F, HND, event_tail, run, vec
    from .gen_r17 import DS1Z, pulse, tick
    from .gen_r18 import PADS
    trains = {"ld": [[0x8B, 0x07]] * 24, "inc": [INCBW] * 50, "nop": [NOPL] * 20}
    leads = {f"k{k}": list(c) for k, c in PADS.items() if k <= 17}
    leads.update({"j": [J0], "jc": [J0, CLC], "jk": [J0, CBW], "o": [OUT22], "oc": [OUT22, CLC], "ok": [OUT22, CBW]})
    v = []
    for tn, tr in trains.items():
        for ln, lc in leads.items():
            for tag, ic in (("u", 0x07), ("m", 0x47)):
                if tag == "m" and tn != "ld":
                    continue
                pre = vec(0x60) + DS1F + [sfr_b(0x4C, ic)] + DS1Z + event_tail(ei=False)
                v.append(run(f"{tn}-{ln}-{tag}", pre, lc + [EI] + tr, pulse("INTP0", tick(20)), HND))
    return v


def round26j():
    from .gen_r17 import tick
    n8 = [NOPL] * 8
    progs = {"mv-e": ([[0xA5]], PTR["ev"], 92), "mv-o": ([[0xA5]], PTR["iy"], 92),
             "cb-e": ([[0xA7]], PTR["ev"], 96), "cb-o": ([[0xA7]], PTR["ix"], 96),
             "ld-e": ([[0xAD]], PTR["ev"], 84), "ld-o": ([[0xAD]], PTR["ix"], 84),
             "cm-e": ([[0xAF]], PTR["ev"], 86), "cm-o": ([[0xAF]], PTR["iy"], 86),
             "sm-e": ([[0xAB]], PTR["ev"], 80), "sm-o": ([[0xAB]], PTR["iy"], 80),
             "rmw-e": ([[0x01, 0x07]], {"BW": 0x0800}, 84), "rmw-o": ([[0x01, 0x07]], ODD, 84)}
    v = []
    for n, (x, regs, lo) in progs.items():
        for e in range(lo, lo + 16):
            v.append(_irun(f"{n}-e{e}", [NOPL, NOPL] + x + n8, regs, tick(e)))
    for e in range(80, 100):
        v.append(_irun(f"wl-e{e}", [OUT22, [0xC7, 0x06, 0x00, 0x0C, 0x34, 0x12]] + n8, {}, tick(e)))
    return v


def round26k():
    forms = {"a2": [0xA2, 0x00, 0x0C], "a3": SACC, "m88": [0x88, 0x06, 0x00, 0x0C], "m89": G_FORMS["sdir"]}
    leads = {"lc": [LDACC, CLC], "lk": [LDACC, CBW], "ln": [LDACC, NOPL], "lcc": [LDACC, CLC, CLC], "lnn": [LDACC, NOPL, NOPL],
             "pc": [PUSH, CLC], "pk": [PUSH, CBW], "pcc": [PUSH, CLC, CLC], "sh": [SLOW], "nn": [NOPL, NOPL]}
    v = []
    for ln, lc in leads.items():
        for fn, fc in forms.items():
            v.append(_p(f"{ln}-{fn}", lc + [fc]))
            v.append(_p(f"{ln}-{fn}-2", lc + [fc, fc]))
    return v


def round26l():
    w16 = lambda x: [x & 0xFF, x >> 8]
    subj = {"int3": [0xCC], "nop": NOPL, "inc": INCBW, "clc": CLC, "rr": [0x8B, 0xC3], "push": PUSH, "out": OUT22,
            "ld": LDACC, "ri": [0xBB, 0x00, 0x08]}
    preds = {"n": NOPL, "i": INCBW, "k": CBW, "c": CLC}
    v = []
    for pn, pc in preds.items():
        for sn, sc in subj.items():
            def f(parity, pc=pc, sc=sc):
                a = BODY_AT[parity] + 12 + len(pc) + len(sc)
                return [q([0xC7, 0x06, 0x0C, 0x00] + w16(a), "vec_ip"), q([0xC7, 0x06, 0x0E, 0x00, 0x00, 0x10], "vec_ps"),
                        q(pc, "prev"), q(sc, "subj")]
            v.append((f"v-{pn}-{sn}", f))
    return v


def round26m():
    w16 = lambda x: [x & 0xFF, x >> 8]
    vec = lambda a, at: [q([0xC7, 0x06, at & 0xFF, at >> 8] + w16(a), "vec_ip"),
                         q([0xC7, 0x06, (at + 2) & 0xFF, (at + 2) >> 8, 0x00, 0x10], "vec_ps")]
    v = []
    for sn, sp in (("o", 0x0F01), ("e", 0x0F00)):
        for tn, tail in (("0", []), ("nop", [NOPL])):
            t = lambda tail=tail: [q(c, "t") for c in tail]
            def callr(parity, t=t, sp=sp):
                a = BODY_AT[parity]
                return ([q([0xBB] + w16(a + 5), "mov_bw"), q([0xFF, 0xD3], "callr")] + t(), M1I, {"SP": sp})
            def callm(parity, t=t, sp=sp):
                a = BODY_AT[parity] + 12
                return ([q([0xFF, 0x16, 0x00, 0x0C], "callm")] + t(), M1I, {"SP": sp, "_pre": vec(a + 4, 0xC00)})
            def int3(parity, t=t, sp=sp):
                a = BODY_AT[parity] + 12
                return ([q([0xCC], "int3")] + t(), M1I, {"SP": sp, "_pre": vec(a + 1, 0x0C)})
            def brk(parity, t=t, sp=sp):
                a = BODY_AT[parity] + 12
                return ([q([0xCD, 0x40], "brk")] + t(), M1I, {"SP": sp, "_pre": vec(a + 2, 0x100)})
            def retf(parity, t=t, sp=sp):
                a = BODY_AT[parity]
                return ([q([0x68, 0x00, 0x10], "pushi"), q([0x68] + w16(a + 7), "pushi"), q([0xCB], "retf")] + t(), M1I, {"SP": sp})
            def reti(parity, t=t, sp=sp):
                a = BODY_AT[parity]
                return ([q([0x68] + w16(a + 6), "pushi"), q([0xC2, 0x00, 0x00], "reti16")] + t(), M1I, {"SP": sp})
            def ncall(parity, t=t, sp=sp):
                return ([q(NOP, "nop"), q([0xE8, 0x00, 0x00], "call")] + t(), M1I, {"SP": sp})
            def ncallf(parity, t=t, sp=sp):
                at = BODY_AT[parity] + 6
                return ([q(NOP, "nop"), q([0x9A, at & 0xFF, at >> 8, 0x00, 0x10], "callf")] + t(), M1I, {"SP": sp})
            def jcall(parity, t=t, sp=sp):
                return ([q(J0, "jmp"), q([0xE8, 0x00, 0x00], "call")] + t(), M1I, {"SP": sp})
            def rcall(parity, t=t, sp=sp):
                return ([q([0xB8, 0x34, 0x12], "ri"), q([0xB8, 0x34, 0x12], "ri"), q([0xE8, 0x00, 0x00], "call")] + t(), M1I, {"SP": sp})
            def pcall(parity, t=t, sp=sp):
                return ([q(PUSH, "push"), q([0xE8, 0x00, 0x00], "call")] + t(), M1I, {"SP": sp})
            v += [(f"jcall-{tn}-{sn}", jcall), (f"rcall-{tn}-{sn}", rcall), (f"pcall-{tn}-{sn}", pcall)]
            for n, f in (("callr", callr), ("callm", callm), ("int3", int3), ("brk", brk), ("retf", retf), ("reti", reti),
                         ("ncall", ncall), ("ncallf", ncallf)):
                v.append((f"{n}-{tn}-{sn}", f))
    return v


def round26n():
    st = [0x89, 0x07]
    fol = {"js": [[0xEB, 0x00]], "jn": [[0xE9, 0x00, 0x00]], "jz": [[0x74, 0x00]], "call": [[0xE8, 0x00, 0x00]],
           "loop": [[0xE2, 0x00]], "js1": [[0xEB, 0x01], NOPL], "pjs": None}
    v = []
    for bn, regs in (("o", ODD), ("e", {"BW": 0x0800})):
        for fn, fc in fol.items():
            if fc is None:      # PUSH with SP odd, then JMP short
                v.append(_p(f"pjs-{bn}", [PUSH, [0xEB, 0x00]], {"SP": 0x0F01 if bn == "o" else 0x0F00}))
                continue
            v.append(_p(f"so-{fn}-{bn}", [st] + fc, regs))
            v.append(_p(f"so-{fn}-nop-{bn}", [st] + fc + [NOPL], regs))
    return v


ROUNDS = {"r26n": round26n, "r26m": round26m, "r26l": round26l, "r26k": round26k, "r26j": round26j, "r26i": round26i, "r26a": round26a, "r26b": round26b, "r26c": round26c, "r26d": round26d, "r26e": round26e,
          "r26f": round26f, "r26g": round26g,
          **{f"r26h{t}": (lambda t=t: round26h(t)) for t in ("sacc", "sdir", "s8", "saccn", "sdirn", "sacb")}}
