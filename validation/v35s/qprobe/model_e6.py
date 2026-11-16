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
               E_B2B=1, FIRST_MIN=4, EMIN_M=3, SHL_N=1, SHL_B=4, SHL_BASE=12, AFTER_EU=0, LEAD_E6=3, LEAD_NOLAST=0, LEAD_SOFT=0,
               # after an EU bus cycle (rounds 2 / 4, the OUT imm8 reading):
               #   E_EU     a boundary waits while an EU cycle is in flight, except on its last clock
               #   EU_EPRI  on the clock after an EU cycle, a boundary that executes with this many
               #            bytes held (or more) keeps a pending fetch from starting on that clock
               #   SHL_ACT  the long shift's 4th word: "B", or "S" = a wait that sees a fetch that
               #            was pending under an EU cycle (and the fetches back to back after it)
               #            S_LAG clocks ahead of its pin cycle
               E_EU=1, EU_EPRI=0, EU_HOLD=1, EU_FIRST="A", PIN_X=1, EMIN=2, LAG_T3=0, LAG_EPRI=0, X_NEXT=0, SHL_ACT="S", S_LAG=2, LAG_ACTS="SXA", LAG_FIRST="AX", EU_ACTS="", EPRI_ALL=0, LEAD_EPRI=1,
               NOP="N...", INC="N.", RR="PN .", OUT="A . X . N .", OUTW="A . X . N .", RI=". . . . BNPP2 .",
               MOVI8=". . . BNP .", JMP="...P..FN.", E6=". . . BP . . X . N .", XCHG="N...", CLC="N.",
               CBW="N..", ADDI=". . . . BNPP2 .", ADD83="P . . BNP .", ADDRR="PN .", RR8="PN .",
               PFX="N.", SHL1="P . B . . . . N .", SHLI="PN P . .", MUL8="PN . . .", JN="...PP2..FN.",
               JZ=". . . P . . . . . . F N .", JNZ=". . . P . . BN .", LD="PP2 X . . . DN .", ST="PP2 X . . . N .",
               PUSH=". . X . . . N .", POP=". . X DN .", IN8=". . . BP . . X DN .",
               INCB="PN . . .")

# opcode -> (routine key, the kind of its bus request, has a ModR/M byte)
OPS = {0x90: ("NOP", None, 0), 0x43: ("INC", None, 0), 0x4B: ("INC", None, 0),
       0x8B: ("RR", None, 1), 0xEE: ("OUT", "O", 0), 0xEF: ("OUTW", "O", 0),
       0xE6: ("E6", "O", 0), 0xE7: ("E6", "O", 0), 0xE4: ("IN8", "I", 0),
       0xFE: ("INCB", None, 1), 0xBB: ("RI", None, 0), 0xBA: ("RI", None, 0),
       0xB1: ("MOVI8", None, 0), 0xB3: ("MOVI8", None, 0), 0xEB: ("JMP", None, 0),
       0x93: ("XCHG", None, 0), 0xF8: ("CLC", None, 0), 0x98: ("CBW", None, 0),
       0x05: ("ADDI", None, 0), 0x83: ("ADD83", None, 1), 0x03: ("ADDRR", None, 1),
       0x8A: ("RR8", None, 1), 0x26: ("PFX", None, 0), 0xD1: ("SHL1", None, 1),
       0xC1: ("SHLI", None, 1), 0xF6: ("MUL8", None, 1), 0xE9: ("JN", None, 0),
       0x74: ("JZ", None, 0), 0x75: ("JNZ", None, 0), 0xA1: ("LD", "R", 0),
       0xA3: ("ST", "W", 0), 0x50: ("PUSH", "W", 0), 0x58: ("POP", "R", 0),
       0xD3: ("SHL", None, 1), 0xF4: ("HALT", None, 0)}


# opcodes whose boundary comes LEAD_E6 clocks after their own pop, not on a fetch's last clock
LEADS = {0xE6, 0xE7, 0xE4}
# opcodes whose EU cycle starts no sooner than the clock after their routine's boundary
HOLDS = {0xE6, 0xE7, 0xEE, 0xEF}


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


def routine(op, o, cl=31):
    if op == 0xD3:
        w = [set() for _ in range(o["SHL_BASE"] + 2 * cl)]
        w[0] = {"P"}
        if o["SHL_B"]:
            w[o["SHL_B"] - 1] = w[o["SHL_B"] - 1] | {o["SHL_ACT"]}
        w[len(w) - 1 - o["SHL_N"]] = w[len(w) - 1 - o["SHL_N"]] | {"N"}
        return w
    if op == 0xF4:
        return [set() for _ in range(900)]
    return words(o[OPS[op][0]])


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
    dw = 0x20
    e_n = skips = 0
    f_lag = False                       # the latest fetch was pending under an EU cycle (or
                                        # follows such a fetch back to back)
    pend = False                        # a fetch is wanted while an EU cycle holds the bus
    skipped = False                     # the pending fetch gave way to a boundary last clock
    next_lag = False                    # the lagged slot in flight is followed by another
    eu_hold = False                     # the posted EU cycle waits for its routine's boundary
    x_clock = -9                        # the clock of the latest EU request word
    lead_pri = False                    # a led opcode's boundary executed on this clock
    while t < limit:
        in_fetch = f_end is not None and t <= f_end
        last_clock = f_end is not None and t == f_end
        eu_run = eu_end is not None and t <= eu_end
        after_eu = eu_end is not None and t == eu_end + 1
        just_ended = ((f_end is not None and t == f_end + 1)
                      or (o["AFTER_EU"] and after_eu))
        # ---- the EU's word
        acts = rt[ip]
        lead_pri = False
        is_last = ip == len(rt) - 1
        npop = ("P" in acts) + ("P2" in acts)
        stall = False
        # the bus unit's setup stage as the EU sees it: a fetch's slot is its pin cycle, or
        # S_LAG clocks ahead of it when the fetch was pending under an EU cycle (and for the
        # fetches back to back after such a fetch); a lagged slot is busy on all its clocks
        lag = o["S_LAG"]
        bus_idle = not in_fetch and not eu_run and not (eu_due is not None and t >= eu_due)
        setup = in_fetch
        first = False                   # the first clock of a lagged slot
        if lag and in_fetch and f_lag:
            if t <= f_end - lag:
                setup = True
            elif t == f_end - lag + 1:
                setup = first = pfp is not None and count + f_bytes <= o["B2B_AT"]
            else:
                setup = next_lag
        elif lag and not in_fetch and pend and pfp is not None and count <= o["IDLE_AT"]:
            setup = ((eu_run and t >= eu_end - lag + 1)
                     or (bus_idle and (after_eu or skipped)))
            first = eu_run and t == eu_end - lag + 1
        elif (lag and not in_fetch and f_lag and next_lag and bus_idle and f_end is not None
              and t == f_end + 1 and pfp is not None and count <= o["B2B_AT"]):
            setup = True
        for act in ("X", "B", "F", "S", "A"):
            by_slot = act in o["LAG_ACTS"] and not (act == "X" and o["PIN_X"]
                                                     and cur_op in LEADS)
            if act in acts and (setup if by_slot else in_fetch):
                if not (by_slot and first and act in o["LAG_FIRST"]):
                    stall = True
        if eu_run and any(act in acts for act in o["EU_ACTS"]):
            stall = True                # waits for an EU cycle in flight, its last clock included
        eu_starting = (eu_due is not None and t >= eu_due and not eu_hold
                       and not in_fetch and not eu_run)
        if eu_starting and any(act in acts for act in o["EU_FIRST"]):
            stall = True                # the cycle's own setup holds the stage on its first clock
        if "D" in acts and (eu_due is not None or eu_run):
            stall = True
        if count < npop + ("N" in acts):
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
            lag_pri = (b2b_now and o["LAG_EPRI"] and f_lag and next_lag
                       and count >= o["LAG_EPRI"])
            if stg is None and "N" not in acts:
                stall = True
            elif lag_pri and not (stg is not None and OPS[code[stg]][2]
                                  and count < o["EMIN_M"]) and not count < o["EMIN"]:
                lead_pri = True          # the boundary executes; the lagged fetch gives way
            elif soft and (in_fetch or t < stg_t + o["LEAD_E6"]):
                stall = True     # a led opcode: starts on an idle bus, LEAD clocks after its pop
            elif (not soft and b2b_now and o["LEAD_EPRI"] and stg is not None
                  and code[stg] in LEADS and t >= stg_t + o["LEAD_E6"]):
                lead_pri = True          # the boundary executes; the fetch gives way a clock
            elif not soft and (b2b_now or (in_fetch and not last_clock)):
                stall = True
            elif o["E_EU"] and eu_run and (t != eu_end or o["E_EU"] == 2):
                stall = True
            elif after_flush and delivered < o["FIRST_MIN"]:
                stall = True
            elif stg is not None and OPS[code[stg]][2] and count < o["EMIN_M"]:
                stall = True
            elif stg is not None and count < o["EMIN"]:
                stall = True
            elif (stg is not None and code[stg] in LEADS and t < stg_t + o["LEAD_E6"]):
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
                pc += 1
                pops += 1
            if "X" in acts:
                eu_hold = bool(o["EU_HOLD"]) and cur_op in HOLDS
                x_clock = t
                eu_due = t + o["POST_LAT"]
                eu_kind = OPS[cur_op][1]
                eu_where = (dw if cur_op in (0xEE, 0xEF)
                            else code[cur_at + 1] if cur_op in (0xE6, 0xE7) else None)
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
                eu_hold = False          # the routine has ended: its cycle may start next clock
                if eu_due is not None:
                    eu_due = max(eu_due, t + 1) if o["EU_HOLD"] and cur_op in HOLDS else eu_due
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
                rt = routine(cur_op, o, cl)
                after_flush = False
                ip = 0
                stg = None
            else:
                ip += 1
        count -= pops
        # ---- the bus unit
        bus_free = not in_fetch and not eu_run
        started = False
        if bus_free and eu_due is not None and t >= eu_due and not eu_hold:
            ev.append((t, eu_kind, eu_where))
            eu_end = t + (2 if eu_kind in ("O", "I") else cyc - 1)
            eu_due = None
            started = True
        if bus_free and not started and flush_due is not None and t >= flush_due:
            pfp = flush_to
            flush_due = None
        eu_started = started
        f_started = skipped_now = False
        if bus_free and not started and pfp is not None:
            lim = o["IDLE_AT"]
            if just_ended and (o["B2B_MODE"] == "plain"
                               or (o["B2B_MODE"] == "elast" and e_clock == f_end)
                               or (o["B2B_MODE"] == "enow" and e_clock != t)):
                lim = o["B2B_AT"]
            give_way = ((after_eu and not o["AFTER_EU"] and pend and e_clock == t
                         and count >= o["EU_EPRI"])
                        or (o["EPRI_ALL"] and e_clock == t)
                        or (lead_pri and e_clock == t))
            if o["X_NEXT"] and x_clock == t - 1:
                give_way = True
            if count <= lim and not give_way:
                addr = base + pfp
                f_bytes = 1 if addr & 1 else 2
                ev.append((t, "F", addr - b))
                f_lag = (pend or (f_lag and next_lag and f_end is not None and t == f_end + 1)
                         or bool(o["LAG_T3"] and after_eu))
                f_end = t + cyc - 1
                pfp += f_bytes
                f_started = True
            skipped_now = give_way and count <= lim
        skipped = skipped_now
        if f_end is not None and f_lag and t == f_end - o["S_LAG"] + 1 and not f_started:
            next_lag = pfp is not None and count + f_bytes <= o["B2B_AT"]
        if f_started:
            next_lag = False
        if eu_run or eu_started:
            # the EU cycle holds the bus: a wanted fetch is pending
            pend = pend or (pfp is not None and count <= o["IDLE_AT"])
        elif not skipped:
            pend = False
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
