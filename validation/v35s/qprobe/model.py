"""A small clocked model of the front end, for reading the qprobe traces (not a reference).

It starts at the end of the first long shift (queue full, bus idle) and predicts the bus events
up to M1. Every rule is a named option so that one reading can be checked against all runs:

    python3 -m validation.v35s.qprobe.model [--id ...] [--waits ...] [-v] [--opt k=v ...]

Structure modelled (results.md has the measurement behind each):
  queue    `count` bytes fetched and not popped, at most 7
  fetch    from idle when count <= IDLE_AT on the clock of the pop; back to back, on the clock
           after a fetch's last clock, when count (with the delivered word, less this clock's
           pops) <= IDLE_AT, or <= B2B_AT when an instruction boundary (E) fell on that last
           clock (B2B_MODE elast); a cycle is 3 + w clocks, delivered at the end of its last
           clock
  staging  the next opcode, popped from the queue by the running routine's NXT word (N)
  E        the staged opcode becomes the running instruction on the routine's last word; it
           waits while a fetch cycle is in flight (one starting back to back included), except
           on that cycle's last clock; the first E after a flush waits for FIRST_MIN bytes
           delivered; the E of a ModR/M opcode waits for EMIN_M bytes in the queue
  post     an EU bus request (X) waits while a fetch is in flight; its cycle starts POST_LAT
           clocks later, or at the end of a fetch that started meanwhile; D waits for its end
  flush    F waits while a fetch is in flight; the target's fetch starts FLUSH_LAT clocks later
A routine is a list of words, one a clock; a word is a set of acts: N (NXT), P / P2 (one / two
operand bytes popped), X (post), D (wait for the EU's cycle), B (wait while a fetch is in
flight), F (flush). The routine's last word is the E word.
"""

from __future__ import annotations

import argparse
import sys

from . import read

DEFAULT = dict(IDLE_AT=4, B2B_AT=5, B2B_MODE="enow", POST_LAT=4, FLUSH_LAT=5, TE=79, TE_W=2,
               E_B2B=1, FIRST_MIN=4, EMIN_M=3, SHL_N=1, SHL_B=4, SHL_BASE=12, AFTER_EU=0, LEAD_E6=3, LEAD_SR=2, LEAD_NOLAST=0, LEAD_SOFT=0, HALT_STOP=1, HALT_HOLD=1, LATCH_BUSY="", B_FROM=3, B_ACTS="B", V1_EU=2,
               NOP="N...", INC="N.", RR="PN .", OUT="..X.NG", RI=". . . . BNPP2 .",
               MOVI8=". . . BNP .", JMP="...P..FN.", E6=". . B P . X . . N .", XCHG="N...", CLC="N.",
               CBW="N..", ADDI=". . . . BNPP2 .", ADD83="P . . BNP .", ADDRR="PN .", RR8="PN .",
               PFX="N.", SHL1="P . B . . . . N .", SHLI="PN P . .", MUL8="PN . . .", JN="...PP2..FN.",
               JZ=". . . P . . . . . . F N .", JNZ=". . . P . . BN .", LD=". . Y PP2 DN .", ST=". . Y PP2 G . . N",
               PUSH=". . Y . . . N .", POP=". . Y DN .", ADDAL=". . . BNP .", IN8=". . B P . X . . DN .",
               PUSHI=". . X PP2 . . N .", POPF=". . X D N", SR="PN .", CALL=". . X PP2 . F N .",
               RET=". . X D F N .", JFAR=". . . PP2 PP2 . F N .", XCHRR="PN .", TESTRR="PN . .",
               INCB="PN . . .", TEST1="PP2N . .", L_BW="P . X . . DN .", L_D8="PP2 . X . . DN .",
               L_D16="P PP2 X . . DN .", L_BI="P . X . . DN .", L_DIR="P PP2 X . . DN .",
               S_BW="P . X . . N .", S_D8="PP2 . X . . N .", S_DIR="P PP2 X . . N .",
               RMW="P . X . . D X . N .")

# opcode -> (routine key, the kind of its bus request, has a ModR/M byte)
OPS = {0x90: ("NOP", None, 0), 0x43: ("INC", None, 0), 0x4B: ("INC", None, 0),
       0x8B: ("RR", None, 1), 0xEE: ("OUT", "O", 0), 0xEF: ("OUT", "O", 0),
       0xE6: ("E6", "O", 0), 0xBB: ("RI", None, 0), 0xBA: ("RI", None, 0),
       0xB1: ("MOVI8", None, 0), 0xB3: ("MOVI8", None, 0), 0xEB: ("JMP", None, 0),
       0x93: ("XCHG", None, 0), 0xF8: ("CLC", None, 0), 0x98: ("CBW", None, 0),
       0x05: ("ADDI", None, 0), 0x83: ("ADD83", None, 1), 0x03: ("ADDRR", None, 1),
       0x8A: ("RR8", None, 1), 0x26: ("PFX", None, 0), 0xD1: ("SHL1", None, 1),
       0xC1: ("SHLI", None, 1), 0xF6: ("MUL8", None, 1), 0xE9: ("JN", None, 0),
       0x74: ("JZ", None, 0), 0x75: ("JNZ", None, 0), 0xA1: ("LD", "R", 0),
       0xA3: ("ST", "W", 0), 0x50: ("PUSH", "W", 0), 0x58: ("POP", "R", 0),
       0xD3: ("SHL", None, 1), 0xF4: ("HALT", None, 0)}


# opcodes whose boundary comes LEAD_E6 clocks after their own pop, not on a fetch's last clock
LEADS = {0xE6: "LEAD_E6", 0xE7: "LEAD_E6", 0xE4: "LEAD_E6", 0x8E: "LEAD_SR"}


def words(spec):
    """'PN .' -> [{'P','N'}, set()]. Words are separated by spaces when any word has more
    than one act, else one character each; '.' is a word with no act."""
    if isinstance(spec, list):
        return [set(w) for w in spec]

    def one(w):
        acts = set()
        if "P2" in w:
            acts.add("P2")
            w = w.replace("P2", "")
        return acts | set(w.replace(".", ""))
    if " " in spec:
        return [one(w) for w in spec.split(" ")]
    return [one(w) for w in spec]


# memory forms: (opcode, ModR/M byte) -> (routine key, bus kind, has ModR/M)
MEM = {(0x8B, 0x07): ("L_BW", "R", 1), (0x8B, 0x47): ("L_D8", "R", 1),
       (0x8B, 0x87): ("L_D16", "R", 1), (0x8B, 0x00): ("L_BI", "R", 1),
       (0x8B, 0x06): ("L_DIR", "R", 1), (0x89, 0x07): ("S_BW", "W", 1),
       (0x89, 0x47): ("S_D8", "W", 1), (0x89, 0x06): ("S_DIR", "W", 1),
       (0x01, 0x07): ("RMW", "R", 1)}
OPS.update({0x04: ("ADDAL", None, 0), 0xE4: ("IN8", "I", 0), 0xE7: ("E6", "O", 0),
            0x68: ("PUSHI", "W", 0), 0x9D: ("POPF", "R", 0), 0x8E: ("SR", None, 1),
            0xE8: ("CALL", "W", 0), 0xC3: ("RET", "R", 0), 0xEA: ("JFAR", None, 0),
            0x86: ("XCHRR", None, 1), 0x84: ("TESTRR", None, 1), 0xFE: ("INCB", None, 1),
            0x0F: ("TEST1", None, 1), 0xB8: ("RI", None, 0), 0x42: ("INC", None, 0),
            0x4A: ("INC", None, 0), 0xB2: ("MOVI8", None, 0)})


def info(code, at):
    """(routine key, bus kind, has ModR/M) of the instruction at `at`."""
    op = code[at]
    if (op, code[at + 1]) in MEM:
        return MEM[(op, code[at + 1])]
    return OPS[op]


def routine(op, o, cl=31, key=None):
    if op == 0xD3:
        w = [set() for _ in range(o["SHL_BASE"] + 2 * cl)]
        w[0] = {"P"}
        if o["SHL_B"]:
            w[o["SHL_B"] - 1] = w[o["SHL_B"] - 1] | {"B"}
        w[len(w) - 1 - o["SHL_N"]] = w[len(w) - 1 - o["SHL_N"]] | {"N"}
        return w
    if op == 0xF4:
        return [set() for _ in range(900)]
    return words(o[key or OPS[op][0]])


def simulate(run, o=DEFAULT, limit=600, log=None):
    """Bus events [(clock, kind, where)] from the end of the first LS, clocks from M0."""
    w = run["chain"]["waits"]
    cyc = 3 + w
    code = bytes.fromhex(run["code_hex"])
    base = 0x10000
    b = read.body_addr(run)
    pc = b - base                       # offset in code of the next byte to pop
    count = 7 if b & 1 else 6           # bytes held beyond the SHL
    pfp = pc + count                    # next byte to fetch (None: flushed, target pending)
    t = o["TE"] + o["TE_W"] * w - 1     # the first SHL's NXT clock
    ev = []
    stg = None                          # staged opcode (its offset) or None
    rt, ip = [set(), {"N"}, set()], 1   # the SHL's tail: NXT, then the E word
    cur_op, cur_at = 0xD3, None
    f_end = None                        # last clock of the latest fetch
    f_bytes = 0
    eu_due = eu_kind = eu_where = None  # the EU's request: earliest clock of its cycle
    eu_end = None                       # last clock of the EU's cycle in flight
    flush_due = flush_to = None
    after_flush = False
    delivered = 99
    e_clock = -9
    stg_t = -9
    cl = 31
    halted = False
    halt_pop = None
    dw = 0x20
    e_n = skips = 0
    while t < limit:
        in_fetch = f_end is not None and t <= f_end
        last_clock = f_end is not None and t == f_end
        eu_run = eu_end is not None and t <= eu_end
        just_ended = ((f_end is not None and t == f_end + 1)
                      or (o["AFTER_EU"] and eu_end is not None and t == eu_end + 1))
        # ---- the EU's word
        acts = rt[ip]
        is_last = ip == len(rt) - 1
        npop = ("P" in acts) + ("P2" in acts)
        stall = False
        # B_FROM: a bus-idle word waits only from the fetch's B_FROM-th clock on (1: the whole
        # cycle); which acts it applies to is B_ACTS
        late = in_fetch and t >= f_end - cyc + o["B_FROM"]
        # LATCH_BUSY: the clock after a fetch that leaves seven bytes held (the word's second
        # byte still in the bus unit's latch) is busy for these words too
        latch = bool(o["LATCH_BUSY"]) and f_end is not None and t == f_end + 1 and count >= 7
        if any(a in acts and ((late if a in o["B_ACTS"] else in_fetch)
                              or (latch and a in o["LATCH_BUSY"])) for a in "XBF"):
            stall = True
        if "D" in acts and (eu_due is not None or eu_run):
            stall = True
        if count < npop + ("N" in acts):
            stall = True
        if "G" in acts:
            # G: the word completes on the clock before the EU's cycle starts (the request
            # accepted): the cycle is due by the next clock and no fetch runs then
            f_now = (not in_fetch and not eu_run and pfp is not None and flush_due is None
                     and not (eu_due is not None and t >= eu_due)
                     and count <= o["IDLE_AT"])
            if (eu_due is None or eu_due > t + 1 or f_now
                    or (f_end is not None and f_end > t) or (eu_run and eu_end > t)):
                stall = True
        early = (stg is not None and "N" not in acts
                 and format(code[stg], "02X") in str(o.get("EARLY", "")).split(","))
        if early:
            is_last = True
        if is_last and early and not stall:
            pass
        elif is_last and not stall:
            # would a back-to-back fetch start this clock without this word's pops?
            lim = o["IDLE_AT"]
            if o["B2B_MODE"] == "plain" or (o["B2B_MODE"] == "elast" and e_clock == f_end):
                lim = o["B2B_AT"]
            soft = bool(o["LEAD_SOFT"]) and stg is not None and code[stg] in LEADS
            b2b_now = (o["E_B2B"] and just_ended and not eu_run and pfp is not None
                       and not (eu_due is not None and t >= eu_due) and count <= lim)
            if stg is None and "N" not in acts:
                stall = True
            elif soft and (in_fetch or t < stg_t + o["LEAD_E6"]):
                stall = True     # a led opcode: starts on an idle bus, LEAD clocks after its pop
            elif not soft and (b2b_now or (in_fetch and not last_clock)):
                stall = True
            elif (o["V1_EU"] and eu_run and t != eu_end
                  and (o["V1_EU"] == 2 or eu_kind in ("W", "R"))):
                stall = True     # the boundary waits for the EU's own cycle too (its last clock)
            elif after_flush and delivered < o["FIRST_MIN"]:
                stall = True
            elif stg is not None and info(code, stg)[2] and count < o["EMIN_M"]:
                stall = True
            elif (stg is not None and code[stg] in LEADS and t < stg_t + o[LEADS[code[stg]]]):
                stall = True
            elif (stg is not None and code[stg] in LEADS and o["LEAD_NOLAST"] and in_fetch):
                stall = True
            elif o.get("SKIP") and o["SKIP"][0] == e_n and skips < o["SKIP"][1]:
                skips += 1
                stall = True
        pops = 0
        if not stall:
            pops = npop
            pc += npop
            if "N" in acts:
                stg = pc
                stg_t = t
                if code[pc] == 0xF4 and o["HALT_STOP"]:
                    halted = True     # HALT popped: nothing more is fetched
                if code[pc] == 0xF4 and o["HALT_HOLD"]:
                    halt_pop = t      # HALT popped: an EU cycle not yet started is held a clock
                pc += 1
                pops += 1
            if "X" in acts or "Y" in acts:     # Y: as X, without the wait for a running fetch
                eu_due = t + o["POST_LAT"]
                eu_kind = info(code, cur_at)[1]
                eu_where = (dw if cur_op in (0xEE, 0xEF)
                            else code[cur_at + 1] if cur_op in (0xE6, 0xE7, 0xE4) else None)
            if "F" in acts:
                if cur_op == 0xE9:
                    d = code[pc - 2] | code[pc - 1] << 8
                    d -= 65536 if d >= 32768 else 0
                else:
                    d = code[pc - 1]
                    d -= 256 if d >= 128 else 0
                flush_due = t + o["FLUSH_LAT"]
                flush_to = pc + d
                count = pops = 0
                stg = None
                pc = flush_to
                pfp = None
                delivered = 0
                after_flush = True
            if is_last:
                if not (o["LEAD_SOFT"] and code[stg] in LEADS):
                    e_clock = t
                e_n += 1
                cur_op, cur_at = code[stg], stg
                if log is not None:
                    log.append((t, f"E{e_n} {cur_op:02X}@{stg + base - b:+d} c={count - pops}"
                                   f"{'L' if last_clock else 'f' if in_fetch else 'i'}"))
                if cur_op == 0xF4:
                    limit = t + 8
                if cur_op == 0xB1:
                    cl = code[stg + 1]
                if cur_op == 0xBA:
                    dw = code[stg + 1] | code[stg + 2] << 8
                rt = routine(cur_op, o, cl, info(code, stg)[0])
                after_flush = False
                ip = 0
                stg = None
            else:
                ip += 1
        count -= pops
        # ---- the bus unit
        bus_free = not in_fetch and not eu_run
        started = False
        if halt_pop is not None and eu_due is not None and eu_due > halt_pop:
            eu_due += o["HALT_HOLD"]
            halt_pop = None
        if bus_free and eu_due is not None and t >= eu_due:
            ev.append((t, eu_kind, eu_where))
            eu_end = t + (2 if eu_kind in ("O", "I") else cyc - 1)
            eu_due = None
            started = True
        if bus_free and not started and flush_due is not None and t >= flush_due:
            pfp = flush_to
            flush_due = None
        if bus_free and not started and pfp is not None and not halted:
            lim = o["IDLE_AT"]
            if just_ended and (o["B2B_MODE"] == "plain"
                               or (o["B2B_MODE"] == "elast" and e_clock == f_end)
                               or (o["B2B_MODE"] == "enow" and e_clock != t)):
                lim = o["B2B_AT"]
            if count <= lim:
                addr = base + pfp
                f_bytes = 1 if addr & 1 else 2
                ev.append((t, "F", addr - b))
                f_end = t + cyc - 1
                pfp += f_bytes
        if f_end is not None and t == f_end:    # delivered at the end of the last clock
            count += f_bytes
            delivered += f_bytes
        t += 1
    return ev


def compare(run, o=DEFAULT):
    """Silicon's and the model's events from the first LS's end to M1 (inclusive)."""
    si = read.events(run)
    t0 = o["TE"] + o["TE_W"] * run["chain"]["waits"] - 1
    si = [(c, k, (wh if k in "FO" else None)) for c, k, wh in si if c >= t0]
    mo = simulate(run, o)
    m1 = next(bytes.fromhex(i["code"]) for i in run["chain"]["instrs"] if i["form"] == "M1")
    if m1[0] == 0x50:
        stop = lambda e: e[1] == "W"
    else:
        stop = lambda e: e[1] == "O" and e[2] == 0x20

    def cut(ev):
        out = []
        for e in ev:
            out.append(e)
            if stop(e):
                break
        return out
    return cut(si), cut(mo)


def fmt(ev):
    return " ".join(f"{c}:{format(wh, '+d') if k == 'F' else k}" for c, k, wh in ev)


def options(pairs):
    o = dict(DEFAULT)
    for kv in pairs:
        k, v = kv.split("=", 1)
        o[k] = int(v) if v.lstrip("-").isdigit() else v
    return o


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", nargs="+", dest="ids")
    ap.add_argument("--waits", nargs="+", type=int)
    ap.add_argument("--parity", nargs="+")
    ap.add_argument("--opt", nargs="+", default=[])
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--log", action="store_true")
    args = ap.parse_args(argv)
    o = options(args.opt)
    runs = read.load("socket")
    n = ok = 0
    groups = {}
    for cid, run in read.select(runs, args.ids, args.waits, args.parity):
        try:
            a, m = compare(run, o)
        except (KeyError, IndexError, TypeError) as exc:
            a, m = [], [(0, "?", repr(exc))]
        n += 1
        same = a == m
        ok += same
        g = cid.split("-")[0][2:] + ":" + cid.split("-")[1]
        groups.setdefault(g, [0, 0])
        groups[g][0] += same
        groups[g][1] += 1
        if args.v or (not same and args.ids):
            print(f"{cid:<22} {'=' if same else 'X'}\n   si {fmt(a)}\n   mo {fmt(m)}")
            if args.log:
                log = []
                simulate(run, o, log=log)
                print("   " + " | ".join(f"{t}:{s}" for t, s in log[:14]))
    print(" ".join(f"{g}:{a}/{b}" for g, (a, b) in groups.items()))
    print(f"{ok} / {n} runs: the model's events from the first LS's end to M1 are silicon's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
