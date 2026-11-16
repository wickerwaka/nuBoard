"""The merged clocked reading model of the V35S front end (model.py and model_e6.py in one).

A reading aid, not a reference: it starts at the end of the first long shift (queue full, bus
idle) and predicts every bus event to the program's end. One rule set, every rule a named option:

    python3 -m validation.v35s.qprobe.model_m [--id ...] [--waits ...] [-v] [--log] [--opt K=V ...]
    build/qp/merge/full.py      whole traces (to the END's OUT and HALT), per group
    build/qp/merge/sweep.py     option sets against the run-level union of both parents
    build/qp/merge/rivals.txt   the A-against-B rival rules, alone and combined (sweep.py input)

Notation. A routine is a list of words, one a clock; a word is a set of acts; the last word is
the boundary word (E): the staged opcode becomes the running instruction when it executes.
    N       pop the next opcode into staging            P, P2   pop one / two operand bytes
    X       post an I/O request                         Y       post a memory request
    D       wait for the EU's bus cycle to end          F       flush (a taken jump)
    B, S, A waits with no other effect: B and F for the pin cycle of a running fetch, S / A / X
            for the bus unit's setup slot (below); (G: a rejected rival, see RIVALS)
A fetch's pin cycle is 3 + w clocks, an I/O cycle 3, a memory cycle of the EU 3 + w.

THE RULES (option = default: mechanism)

Queue and prefetch
  IDLE_AT=4     a fetch starts from an idle bus when four or fewer bytes are held, on the clock
                of the pop that makes it so (seven places; a word needs two and one in hand)
  B2B_AT=5      on the clock after a fetch's last clock a fetch follows with five held (the
                word's second byte takes the seventh place) unless a boundary executes on that
                clock; with four or fewer the fetch starts and the boundary waits
  REQ_PRI=1     ... and the five-held continuation is not made when an EU request word executed
                on the fetch's last clock (five held is the lowest priority of the bus unit)
  FLUSH_LAT=5   a flush word waits for a running fetch; the target's fetch starts 5 clocks later

The instruction boundary
  (base)        no boundary while a fetch's pin cycle is in flight, except on its last clock
  E_EU=1        ... nor while an EU bus cycle is in flight, except on its last clock
  E_PEND=1      ... nor while a memory cycle is posted and not yet started (a routine with a
                memory cycle ends on that cycle's last clock at the earliest)
  FIRST_MIN=4   the first boundary after a flush waits for four bytes of the new stream
  EMIN_M=3      the boundary of a ModR/M opcode waits for three bytes behind the staged opcode
  EMIN=2        any boundary waits for two bytes behind the staged opcode

The EU's bus cycles
  POST_LAT=4    a request word's cycle starts four clocks later, or when the bus frees
  Y_LEFT=2      a memory request word (Y) is taken when the running fetch has at most one clock
                left after this one (in the fetch's last two clocks); it waits before that
  EU_HOLD=1     an I/O write's cycle starts no sooner than the clock after its routine's
                boundary (the cycle is issued by the routine's end; the request word only waits)
  EU_EPRI=1     on the clock after an EU cycle, a boundary that executes keeps the fetch that was
                pending under the cycle from starting on that clock (the fetch one clock later)

The bus unit's setup slot (what the S, A and X words wait for)
  S_LAG=2       a bus cycle's slot is its pin cycle, moved two clocks earlier for an EU cycle
                and for every fetch chained behind it (a fetch wanted while the EU cycle held the
                bus, and the fetches that follow back to back): from an EU cycle until the bus
                next goes idle the bus unit's sequencing runs two clocks ahead of the pins
  EU_SLOT=1     the EU cycle's own slot counts (OUT DW's first word waits on the first pin clock
                of the I/O cycle before it)
  LAG_ACTS=SXA  the words that wait by the slot: the long shift's 4th word (S), OUT DW's first
                word (A), an I/O request word (X); B and F words wait by the pin cycle
  LAG_FIRST=A   OUT DW's first word does not wait on the first clock of a lagged fetch's slot
  CHAIN_POP=1   a chained fetch whose first pin clock carries a pop is an ordinary fetch (its
                slot is its pin cycle): the pop restarts the request

The decode stage (runs from the pop of an opcode, before its boundary)
  LEAD_E6=3     OUT imm8 / OUT imm8,AW / IN imm8: boundary no sooner than 3 clocks after the pop
  LEAD_SR=2     MOV sreg,r16: no sooner than 2 clocks after the pop (every other opcode read: 1)
  LEAD_EPRI=1   a lead that ends on the very clock a back-to-back fetch would start: the boundary
                executes and the fetch starts one clock later
  HALT_STOP=1   HALT acts at its pop: nothing more is fetched
  HALT_HOLD=1   ... and an EU cycle not yet started is held one clock

The frame: TE / TE_W the first long shift's NXT clock; SHL_BASE=12 (+ 2 a count), SHL_B=4 the
long shift's waiting word, SHL_N=1 its NXT word from the end.

Function the model carries (not timing rules): CL and DW as the program loads them; Z after the
long shift (set) and after INC / DEC r16 (clear) chooses the taken / not-taken routine of JZ / JNZ;
the targets of JMP short / near / far, CALL near and RET.

Where the evidence is thin (build/qp/merge/drop.txt has every rule off alone): EMIN (3 runs),
LAG_FIRST and X in LAG_ACTS (one program at three waits), HALT_STOP (3), LEAD_EPRI (8, w0 only),
REQ_PRI (9), CHAIN_POP (10), EU_HOLD (16). Not read: SHL r,imm8, MULU, the read-modify-write form,
CALL / RET, the ModR/M forms of `em2-*` other than those above; JMP near, JMP far and Jcc taken
are reproduced in part only (their shapes below are the best found, not a reading).

RIVALS (rejected; kept as switches so the deciding counts can be re-run, build/qp/merge/rivals.txt)
  B_FROM=1      model.py's B_FROM=3: B words wait only from a fetch's third clock
  SHL_ACT=S     model.py's long shift waited as a B word ("B")
  Y_MODE=late   model.py's Y "none" (no wait); model_e6.py's "slot" (as X); "pin" (whole cycle)
  act G         model.py's OUT DW / store ending: the word completes the clock before the cycle
"""

from __future__ import annotations

import argparse
import sys

from . import read

DEFAULT = dict(
    IDLE_AT=4, B2B_AT=5, REQ_PRI=1, FLUSH_LAT=5,
    E_EU=1, E_PEND=1, FIRST_MIN=4, EMIN_M=3, EMIN=2,
    POST_LAT=4, Y_LEFT=2, EU_HOLD=1, EU_EPRI=1,
    S_LAG=2, EU_SLOT=1, LAG_ACTS="SXA", LAG_FIRST="A", CHAIN_POP=1,
    LEAD_E6=3, LEAD_SR=2, LEAD_EPRI=1, HALT_STOP=1, HALT_HOLD=1,
    TE=79, TE_W=2, SHL_N=1, SHL_B=4, SHL_BASE=12,
    # the rejected rivals (see the docstring)
    B_FROM=1, B_ACTS="B", SHL_ACT="S", Y_MODE="late",
    # routines, read in rounds 1-3 (model.py)
    NOP="N...", INC="N.", RR="PN .", RI=". . . . BNPP2 .", MOVI8=". . . BNP .", XCHG="N...",
    CLC="N.", CBW="N..", ADDI=". . . . BNPP2 .", ADD83="P . . BNP .", ADDRR="PN .", RR8="PN .",
    PFX="N.", SHL1="P . B . . . . N .", JMP="...P..FN.", JZ=". . . P . . . . . . F N .",
    JNZ=". . . P . . BN .", ADDAL=". . . BNP .", SR="PN .",
    # I/O (model_e6.py): port byte on word 4; `X . N .` and the cycle after the boundary
    OUT="A . X . N .", E6=". . . BP . . X . N .", IN8=". . . BP . . X DN .",
    # memory: the request (Y), then the datum's wait (D) or, for a write, the boundary's wait
    PUSH=". . Y . . . N .", POP=". . Y DN .", LD=". . Y PP2 DN .", ST=". . Y PP2 N",
    PUSHI=". . . . PP2 . Y N", POPF=". . Y D . N .",
    L_BW="P Y . DN .", L_BI="P Y . DN .", L_D8="P Y . P DN .", L_D16="P Y . PP2 DN .",
    L_DIR="P Y . PP2 DN .", S_BW="P Y . N", S_D8="P Y . P N", S_DIR="P Y . PP2 N",
    # jumps other than JMP short: best shapes found, reproduced in part (not a reading)
    JN=". . . . PP2 F N", JFAR=". . . . PP2 . . . PP2 . F N",
    # not read (placeholders: these groups are not reproduced)
    SHLI="PN P . .", MUL8="PN . . .", CALL=". . Y PP2 . F N .",
    RET=". . Y D F N .", XCHRR="PN .", TESTRR="PN . .",
    INCB="PN . . .", TEST1="PP2N . .", RMW="P Y . . D Y . N .")

# opcode -> (routine key, the kind of its bus request, has a ModR/M byte)
OPS = {0x90: ("NOP", None, 0), 0x43: ("INC", None, 0), 0x4B: ("INC", None, 0),
       0x42: ("INC", None, 0), 0x4A: ("INC", None, 0),
       0x8B: ("RR", None, 1), 0xEE: ("OUT", "O", 0), 0xEF: ("OUT", "O", 0),
       0xE6: ("E6", "O", 0), 0xE7: ("E6", "O", 0), 0xE4: ("IN8", "I", 0),
       0xBB: ("RI", None, 0), 0xBA: ("RI", None, 0), 0xB8: ("RI", None, 0),
       0xB1: ("MOVI8", None, 0), 0xB3: ("MOVI8", None, 0), 0xB2: ("MOVI8", None, 0),
       0xEB: ("JMP", None, 0), 0x93: ("XCHG", None, 0), 0xF8: ("CLC", None, 0),
       0x98: ("CBW", None, 0), 0x05: ("ADDI", None, 0), 0x83: ("ADD83", None, 1),
       0x03: ("ADDRR", None, 1), 0x8A: ("RR8", None, 1), 0x26: ("PFX", None, 0),
       0xD1: ("SHL1", None, 1), 0xC1: ("SHLI", None, 1), 0xF6: ("MUL8", None, 1),
       0xE9: ("JN", None, 0), 0x74: ("JZ", None, 0), 0x75: ("JNZ", None, 0),
       0xA1: ("LD", "R", 0), 0xA3: ("ST", "W", 0), 0x50: ("PUSH", "W", 0),
       0x58: ("POP", "R", 0), 0xD3: ("SHL", None, 1), 0xF4: ("HALT", None, 0),
       0x04: ("ADDAL", None, 0), 0x68: ("PUSHI", "W", 0), 0x9D: ("POPF", "R", 0),
       0x8E: ("SR", None, 1), 0xE8: ("CALL", "W", 0), 0xC3: ("RET", "R", 0),
       0xEA: ("JFAR", None, 0), 0x86: ("XCHRR", None, 1), 0x84: ("TESTRR", None, 1),
       0xFE: ("INCB", None, 1), 0x0F: ("TEST1", None, 1)}

# memory forms: (opcode, ModR/M byte) -> (routine key, bus kind, has ModR/M)
MEM = {(0x8B, 0x07): ("L_BW", "R", 1), (0x8B, 0x47): ("L_D8", "R", 1),
       (0x8B, 0x87): ("L_D16", "R", 1), (0x8B, 0x00): ("L_BI", "R", 1),
       (0x8B, 0x06): ("L_DIR", "R", 1), (0x89, 0x07): ("S_BW", "W", 1),
       (0x89, 0x47): ("S_D8", "W", 1), (0x89, 0x06): ("S_DIR", "W", 1),
       (0x01, 0x07): ("RMW", "R", 1)}

# the decode stage's leads: the boundary no sooner than this many clocks after the opcode's pop
LEADS = {0xE6: "LEAD_E6", 0xE7: "LEAD_E6", 0xE4: "LEAD_E6", 0x8E: "LEAD_SR"}


def info(code, at):
    """(routine key, bus kind, has ModR/M) of the instruction at `at`."""
    op = code[at]
    if (op, code[at + 1]) in MEM:
        return MEM[(op, code[at + 1])]
    return OPS[op]


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


def routine(op, o, cl=31, key=None):
    if op == 0xD3:
        w = [set() for _ in range(o["SHL_BASE"] + 2 * cl)]
        w[0] = {"P"}
        if o["SHL_B"]:
            w[o["SHL_B"] - 1] = w[o["SHL_B"] - 1] | {o["SHL_ACT"]}
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
    stg_t = -9                          # the clock of its pop
    rt, ip = [set(), {"N"}, set()], 1   # the SHL's tail: NXT, then the E word
    cur_op, cur_at = 0xD3, None
    cl, dw = 31, 0x20                   # CL and DW as the program sets them
    e_n = 0                             # boundaries so far
    e_clock = -9                        # the clock of the latest boundary
    after_flush = False
    delivered = 99                      # bytes delivered since the latest flush
    f_end = None                        # last pin clock of the latest fetch
    f_bytes = 0
    flush_due = flush_to = None
    eu_due = eu_kind = eu_where = None  # the EU's request: earliest clock of its cycle
    eu_end = None                       # last pin clock of the EU's cycle
    eu_hold = False                     # an I/O write posted, its routine not yet ended
    req_clock = -9                      # the clock of the latest request word
    pend = False                        # a fetch is wanted while an EU cycle holds the bus
    skipped = False                     # that fetch gave way to a boundary on the last clock
    f_lag = False                       # the latest fetch's slot is ahead of its pin cycle
    next_lag = False                    # ... and another fetch is chained behind it
    halted = False
    halt_pop = None
    calls = []                          # return offsets of the near calls made
    zf = True                           # Z as the long shift leaves it (JZ taken, JNZ not)
    forced = 0
    lag = o["S_LAG"]
    while t < limit:
        in_fetch = f_end is not None and t <= f_end
        last_clock = f_end is not None and t == f_end
        eu_run = eu_end is not None and t <= eu_end
        after_eu = eu_end is not None and t == eu_end + 1
        just_ended = f_end is not None and t == f_end + 1
        # ---- the EU's word
        acts = rt[ip]
        is_last = ip == len(rt) - 1
        npop = ("P" in acts) + ("P2" in acts)
        stall = lead_pri = False
        # the setup slot of the fetch in flight or about to start (S_LAG): `first` its first clock
        bus_idle = not in_fetch and not eu_run and not (eu_due is not None and t >= eu_due)
        slot, first = in_fetch, False
        if lag and in_fetch and f_lag:
            if t <= f_end - lag:
                slot = True
            elif t == f_end - lag + 1:
                slot = first = pfp is not None and count + f_bytes <= o["B2B_AT"]
            else:
                slot = next_lag
        elif lag and not in_fetch and pend and pfp is not None and count <= o["IDLE_AT"]:
            slot = (eu_run and t >= eu_end - lag + 1) or (bus_idle and (after_eu or skipped))
            first = eu_run and t == eu_end - lag + 1
        elif (lag and not in_fetch and f_lag and next_lag and bus_idle and f_end is not None
              and t == f_end + 1 and pfp is not None and count <= o["B2B_AT"]):
            slot = True
        # the EU cycle's own slot: its pin cycle moved S_LAG clocks earlier (EU_SLOT)
        eu_slot = bool(o["EU_SLOT"]) and (
            (eu_due is not None and not eu_hold and t >= eu_due - lag)
            or (eu_run and t <= eu_end - lag))
        for act in "XSABFY":
            if act not in acts:
                continue
            kind = o["Y_MODE"] if act == "Y" else "slot" if act in o["LAG_ACTS"] else "pin"
            if kind == "slot":
                busy = (slot and not (first and act in o["LAG_FIRST"])) or eu_slot
            elif kind == "late":
                busy = in_fetch and f_end - t >= o["Y_LEFT"]
            elif kind == "pin":
                busy = in_fetch and (act not in o["B_ACTS"] or t >= f_end - cyc + o["B_FROM"])
            else:
                busy = False
            stall = stall or busy
        if acts & set("XSABFY"):
            # measurement hook (not a rule): FORCE = (instruction number, word, n) makes that
            # word's bus wait exactly n clocks; DBG collects (instruction, word, clock, waited)
            fo = o.get("FORCE")
            if fo and fo[0] == e_n and fo[1] == ip:
                stall = forced < fo[2]
                forced += 1
            if o.get("DBG") is not None:
                o["DBG"].append((e_n, ip, t, stall, cur_op))
        if "D" in acts and (eu_due is not None or eu_run):
            stall = True
        if count < npop + ("N" in acts):
            stall = True
        if "G" in acts:
            # rival: the word completes on the clock before the EU's cycle starts
            f_now = (not in_fetch and not eu_run and pfp is not None and flush_due is None
                     and not (eu_due is not None and t >= eu_due)
                     and count <= o["IDLE_AT"])
            if (eu_due is None or eu_due > t + 1 or f_now
                    or (f_end is not None and f_end > t) or (eu_run and eu_end > t)):
                stall = True
        if is_last and not stall:
            # would a back-to-back fetch start this clock without this word's pops?
            b2b_now = (just_ended and not eu_run and pfp is not None
                       and not (eu_due is not None and t >= eu_due) and count <= o["IDLE_AT"])
            led = stg is not None and code[stg] in LEADS
            lead_t = stg_t + o[LEADS[code[stg]]] if led else None
            if stg is None and "N" not in acts:
                stall = True
            elif b2b_now and o["LEAD_EPRI"] and led and t == lead_t:
                lead_pri = True          # the boundary executes; the fetch gives way a clock
            elif b2b_now or (in_fetch and not last_clock):
                stall = True
            elif o["E_EU"] and eu_run and (t != eu_end or o["E_EU"] == 2):
                stall = True
            elif o["E_PEND"] and eu_due is not None and eu_kind in "WR":
                stall = True
            elif after_flush and delivered < o["FIRST_MIN"]:
                stall = True
            elif stg is not None and info(code, stg)[2] and count < o["EMIN_M"]:
                stall = True
            elif stg is not None and count < o["EMIN"]:
                stall = True
            elif led and t < lead_t:
                stall = True
        pops = 0
        if not stall:
            pops = npop
            pc += npop
            if "N" in acts:
                stg = pc
                stg_t = t
                if code[pc] == 0xF4 and o["HALT_STOP"]:
                    halted = True
                if code[pc] == 0xF4 and o["HALT_HOLD"]:
                    halt_pop = t
                pc += 1
                pops += 1
            if "X" in acts or "Y" in acts:
                req_clock = t
                eu_due = t + o["POST_LAT"]
                eu_kind = info(code, cur_at)[1]
                eu_hold = bool(o["EU_HOLD"]) and eu_kind == "O"
                eu_where = (dw if cur_op in (0xEE, 0xEF)
                            else code[cur_at + 1] if cur_op in (0xE6, 0xE7) else None)
            if "F" in acts:
                if cur_op in (0xE9, 0xE8):                  # near: a 16-bit displacement
                    d = code[pc - 2] | code[pc - 1] << 8
                    flush_to = pc + d - (65536 if d >= 32768 else 0)
                    if cur_op == 0xE8:
                        calls.append(pc)
                elif cur_op == 0xEA:                        # far: offset : segment (1000h here)
                    flush_to = code[pc - 4] | code[pc - 3] << 8
                elif cur_op == 0xC3:
                    flush_to = calls.pop()
                else:
                    d = code[pc - 1]
                    flush_to = pc + d - (256 if d >= 128 else 0)
                flush_due = t + o["FLUSH_LAT"]
                count = pops = 0
                stg = None
                pc = flush_to
                pfp = None
                delivered = 0
                after_flush = True
            if is_last:
                if eu_hold:              # the routine has ended: its I/O cycle on the next clock
                    eu_due = max(eu_due, t + 1)
                    eu_hold = False
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
                key = info(code, stg)[0]
                if cur_op in (0x42, 0x43, 0x4A, 0x4B):
                    zf = False           # INC / DEC r16 of a register that does not reach zero
                if cur_op in (0x74, 0x75) and not zf:
                    key = "JNZ" if cur_op == 0x74 else "JZ"     # the other outcome's routine
                rt = routine(cur_op, o, cl, key)
                after_flush = False
                ip = 0
                stg = None
            else:
                ip += 1
        count -= pops
        # ---- the bus unit
        bus_free = not in_fetch and not eu_run
        eu_started = f_started = gave_way = False
        if halt_pop is not None and eu_due is not None and eu_due > halt_pop:
            eu_due += o["HALT_HOLD"]
            halt_pop = None
        if bus_free and eu_due is not None and t >= eu_due and not eu_hold:
            ev.append((t, eu_kind, eu_where))
            eu_end = t + (2 if eu_kind in ("O", "I") else cyc - 1)
            eu_due = None
            eu_started = True
        if bus_free and not eu_started and flush_due is not None and t >= flush_due:
            pfp = flush_to
            flush_due = None
        if bus_free and not eu_started and pfp is not None and not halted:
            lim = o["IDLE_AT"]
            if just_ended and e_clock != t and not (o["REQ_PRI"] and req_clock == t - 1):
                lim = o["B2B_AT"]
            give_way = ((o["EU_EPRI"] and after_eu and pend and e_clock == t)
                        or (lead_pri and e_clock == t))
            if count <= lim and not give_way:
                addr = base + pfp
                f_bytes = 1 if addr & 1 else 2
                ev.append((t, "F", addr - b))
                # the slot stays ahead of the pins for a fetch that was pending under an EU
                # cycle and for one chained to such a fetch (unless a pop falls on this clock)
                f_lag = pend or (f_lag and next_lag and f_end is not None and t == f_end + 1
                                 and not (o["CHAIN_POP"] and pops))
                f_end = t + cyc - 1
                pfp += f_bytes
                f_started = True
                if o.get("DBGF") is not None:
                    o["DBGF"][t] = f_lag
            gave_way = give_way and count <= lim
        skipped = gave_way
        if f_end is not None and f_lag and t == f_end - lag + 1 and not f_started:
            # the chained slot's decision, S_LAG clocks ahead of the pins
            next_lag = pfp is not None and count + f_bytes <= o["B2B_AT"]
        if f_started:
            next_lag = False
        if eu_run or eu_started:
            pend = pend or (pfp is not None and count <= o["IDLE_AT"])
        elif not skipped:
            pend = False
        if f_end is not None and t == f_end:    # delivered at the end of the last clock
            count += f_bytes
            delivered += f_bytes
        t += 1
    return ev


def silicon(run, o=DEFAULT):
    """Silicon's events from the first LS's end, in the model's form."""
    t0 = o["TE"] + o["TE_W"] * run["chain"]["waits"] - 1
    return [(c, k, (wh if k in "FO" else None)) for c, k, wh in read.events(run) if c >= t0]


def compare(run, o=DEFAULT):
    """Silicon's and the model's events from the first LS's end to M1 (inclusive)."""
    si = silicon(run, o)
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
    n = ok = okw = 0
    groups = {}
    for cid, run in read.select(runs, args.ids, args.waits, args.parity):
        try:
            a, m = compare(run, o)
            whole = silicon(run, o) == simulate(run, o)
        except (KeyError, IndexError, TypeError) as exc:
            a, m, whole = [], [(0, "?", repr(exc))], False
        n += 1
        same = a == m
        ok += same
        okw += whole
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
    print(f"{ok} / {n} runs: the model's events from the first LS's end to M1 are silicon's; "
          f"{okw} / {n} to the program's end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
