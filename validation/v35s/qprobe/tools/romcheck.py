#!/usr/bin/env python3
"""romcheck.py: check the core v2 microcode ROM against the clocked reading model's routine
strings, mechanically, per instruction encoding.

    PYTHONPATH=host/src:. python3 TOOLS/romcheck.py [--rom-root DIR] [--cl N] [--jobs 3]
        [--cache CORPUS_CHAINS.json] [--out ROMCHECK.json] [--top N] [--enc "01 m0r7" ...] [-v]

Run from a repo checkout root (the model, validation/v35s/qprobe/model_m.py, is this tree's).
--rom-root is the tree whose fpga/v35s/core/v35/urom/*.uasm, v35_pkg.sv and
validation/v35s/chains/uasm.py are read (default: this tree). The assembler is imported and its
`assemble()` run in memory (parse and lay out only; nothing is written; `uasm` is never run).

For every encoding the corpus holds as a subject (role x; prefixes stripped: the model runs a
prefix as an instruction of its own) the tool takes:

  model   model_m's routine: info() -> key, routine(op, DEFAULT, cl, key) -> words (acts).
  ROM     the words the sequencer executes for the encoding: the decode's cell (v35_udec1 /
          v35_udec2 by assemble()'s cells), the dispatch's EA head for a memory cell (and the
          0F page's EAC word's call), calls, jumps, loops (the counter from CL = --cl, the
          immediate byte, the width's bit count), the conditions it can evaluate (CNTZ, WORD,
          XC = taken / not taken by the model key), up to the E word and its post-E word (the
          model's boundary word). Each ROM word is turned into the model's acts:
            ro -> N; rl=1 -> P; rl=2 -> P P2; the loader's ModR/M (0F second byte) release on
            the first word after the dispatch -> P;
            the releases of one word added up (two -> P P2);
            bi -> B, bi+alt -> C (the commit word), bi+alt on an rl=2 word -> B I (the main
            tree's `strict`, which assembles to exactly those bits); rl=x+bi -> the Y wait,
            +alt -> V; rl=x alone -> the slot wait (X with an I/O request, else S), +alt -> A;
            f -> D; flush -> F (its bi dropped: the model's F waits as B does);
            MEMWD's arming word (the first later word loading OPRW) -> K; bus=RSV posts nothing;
            a request post on word p: the routine's first post -> its request act on word p-3
            (the deferred post "Y + 3": the model's request with POST_LAT 4), composed with
            that word's wait (Y / V as they are, B -> BY, C -> CY, X / A for I/O); a later post
            -> Z (a write) / U (a read) on word p-1 (the model's second request, Z_LAT 2); a
            post three words after an rl=x word is always the deferred kind.
          No ROM bit gives the model's G (the word that completes the clock before the EU's
          cycle) or Q (a request seen by the bus unit, no cycle): they appear as shape
          differences and the sim check judges them. At ce9ea43 there is no strict word, so
          the model's I words show as B there.

Checks, per encoding:
  shape    the literal word strings, model against ROM (acts sorted within a word).
  sim      timing equivalence in the model's own machine: the model run on synthetic programs
           (the subject in seven contexts x 3 waits x 2 parities) and on up to --corpus-runs
           corpus runs holding the encoding, once with its own routine and once with the
           ROM-derived one substituted for the subject (cl / the immediate from the run's
           state at the boundary); a difference in any bus event = `sim differs`.
  decode   the decode facts the model reads beside the routine: the lead (LEADS against the
           routine header's lead=) and the three-bytes wait (model: info()'s ModR/M flag with
           EMIN_M; ROM: udec1's m3).
  consistency  encodings the model maps to one routine key whose ROM strings differ (the
           build faults of the kind "a form not using the routine its group uses").
Mismatches are ranked by the corpus run count of the encoding (a run counts once per encoding
it holds as a subject).
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import multiprocessing
import sys
from pathlib import Path

sys.path[:0] = ["host/src", "."]

from validation.v35s.qprobe import model_m  # noqa: E402

PREFIXES = (0x26, 0x2E, 0x36, 0x3E, 0xF0)
REPS = (0xF2, 0xF3, 0x64, 0x65)
# model keys whose routine() is a placeholder rebuilt inside simulate() from run state
BUILT = {"EXT", "INS", "EXTI", "INSI", "PREP", "ADD4S", "SUB4S", "CMP4S", "HALT"}
NOT_TAKEN = {"JNZ", "LOOPN", "JCXZ", "LOOPZF", "LOOPZ0", "LOOPZ00"}
U = None            # the uasm module (of --rom-root)
PROG = None


def load_uasm(root: Path):
    path = root / "validation/v35s/chains/uasm.py"
    spec = importlib.util.spec_from_file_location("uasm_snapshot", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["uasm_snapshot"] = mod
    spec.loader.exec_module(mod)
    return mod


def strip_prefixes(code: bytes) -> tuple[bytes, bool]:
    k = 0
    rep = False
    while k < len(code) and code[k] in PREFIXES + REPS:
        rep = rep or code[k] in REPS
        k += 1
    return code[k:], rep


def enc_key(code: bytes) -> str:
    op = code[0]
    if op == 0x0F:
        mb = code[2]
        return f"0F {code[1]:02X} " + (f"m{mb >> 6}r{mb & 7}" if mb < 0xC0 else "reg")
    if op in U.MODRM_OPS:
        mb = code[1]
        grp = op in (0x80, 0x81, 0x82, 0x83, 0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3, 0xF6, 0xF7,
                     0xFE, 0xFF, 0x8F, 0xC6, 0xC7, 0xD6)
        reg = f"/{(mb >> 3) & 7} " if grp else ""
        return f"{op:02X} {reg}" + (f"m{mb >> 6}r{mb & 7}" if mb < 0xC0 else "reg")
    return f"{op:02X}"


# ------------------------------------------------------------------------- the ROM side
def rom_cell(code: bytes):
    """(routine name, start pc, return register, ModR/M byte or None, page) for the encoding."""
    op = code[0]
    p = PROG
    if op == 0x0F:
        name = p.cells2.get((0x0F, code[1]))
        mb = code[2] if code[1] in U.PAGE1_MODRM else None
        if name is None:
            return None
        return name, p.labels[name], None, mb, True
    if op in U.MODRM_OPS:
        mb = code[1]
        name = p.cells2.get((op, mb))
        if name is None:
            return None
        r = p.routine(name)
        pc, retr = r.base, None
        if U.is_mem(r) and mb >> 6 != 3:
            h = dispatch_head(r, mb)
            if h is not None:
                pc, retr = p.labels[h], r.base
        return name, pc, retr, mb, False
    name = p.cells1.get(op)
    if name is None:
        return None
    return name, p.labels[name], None, None, False


def dispatch_head(r, m):
    """The EA head the dispatch calls for a memory cell (v35_loader.sv's `hd` / `dsp_f.call`),
    or None (the routine's entry directly)."""
    eaq = r.head.get("ea") == "q"
    eab = r.head.get("ea", "book") == "book"
    md, mdir = m >> 6, (m >> 6) == 0 and (m & 7) == 6
    if not (md != 0 or mdir or eab or eaq):
        return None
    if eaq:
        return ("eaq8" if md == 1 else "eaq16x" if md == 2 and not m & 4
                else "eaq16" if md == 2 or mdir else "eaq0")
    return ("eab8" if eab else "ea8") if md == 1 else "eab16" if md == 2 and eab else \
        "ead" if md == 2 or mdir else "eab0"


def eac_head(r, m):
    """The 0F page's EAC word's call (v35_loader.sv's `ech` / `ecc`), or None (go on)."""
    if r.head.get("ea") == "s":      # (r22 builder's scratch patch) the hold heads
        md, mdir = m >> 6, (m >> 6) == 0 and (m & 7) == 6
        return "eas8" if md == 1 else "eas16" if md == 2 or mdir else "eas0"
    eab = r.head.get("ea", "book") == "book"
    md, mdir = m >> 6, (m >> 6) == 0 and (m & 7) == 6
    if not (md != 0 or mdir or eab):
        return None
    return ("eab8" if eab else "ea8") if md == 1 else "eab16" if md == 2 and eab else \
        "ead" if md == 2 or mdir else "eab0"


def imm_byte(code: bytes) -> int:
    op = code[0]
    if op == 0x0F:
        at = 3 + (U.disp_bytes(code[2]) if code[1] in U.PAGE1_MODRM else 0)
    elif op in U.MODRM_OPS:
        at = 2 + U.disp_bytes(code[1])
    else:
        at = 1
    return code[at] if at < len(code) else 0


def rom_walk(code: bytes, cl: int, taken: bool, limit: int = 4000):
    """[(routine name, fields)] the sequencer executes from the dispatch's target to the E word's
    post-E word; notes on what it had to assume."""
    cell = rom_cell(code)
    notes = set()
    if cell is None:
        return None, {"no ROM cell (trap)"}
    name, pc, retr, mb, page = cell
    if name.startswith("trap"):
        return None, {"trap routine"}
    r = PROG.routine(name)
    op = code[0]
    if page:
        width = 16 if U.page_w(code[1]) else 8
    else:
        width = 16 if U.fmt_of(op)["w"] else 8
    E = U.enum_value
    cnt = 0
    out = []
    il = imm_byte(code)
    seen_dd = False
    while limit:
        limit -= 1
        rr, w = PROG.words[pc]
        f = w.fields
        out.append((rr.name, f))
        if f.get("e"):
            # (work order 24) the post-E word: the next address, or the stored one the E word
            # jumps to (uasm's tail sharing)
            rr2, w2 = PROG.words[f["tgt"] if f.get("seq") == E("v35_seq_e", "jmp") else pc + 1]
            out.append((rr2.name, w2.fields))
            return out, notes
        if f.get("halt"):
            notes.add("halt")
            return out, notes
        c = f.get("cnt", 0)
        newcnt = None
        if c == E("v35_cnt_e", "rb"):
            newcnt = cl
        elif c == E("v35_cnt_e", "il"):
            newcnt = il
        elif c == E("v35_cnt_e", "clh"):
            newcnt = max(1, (cl + 1) // 2)
        elif c == E("v35_cnt_e", "bits"):
            newcnt = width
        elif c == E("v35_cnt_e", "len"):
            newcnt = 0
        elif c == E("v35_cnt_e", "sig"):
            newcnt = cl
            notes.add("counter from SIGMA (taken as CL)")
        seq = f.get("seq", 0)
        nxt = pc + 1
        cond = f.get("cond", 0)
        cv = {E("v35_cond_e", "cntz"): cnt == 0, E("v35_cond_e", "word"): width == 16,
              E("v35_cond_e", "xc"): taken, E("v35_cond_e", "snz"): taken}.get(cond)
        if seq in (E("v35_seq_e", "jc"), E("v35_seq_e", "jnc")) and cv is None:
            cv = False
            if not seen_dd:
                notes.add("data-dependent condition taken false")
                seen_dd = True
        if seq == E("v35_seq_e", "jmp"):
            nxt = f["tgt"]
        elif seq == E("v35_seq_e", "jc"):
            nxt = f["tgt"] if cv else pc + 1
        elif seq == E("v35_seq_e", "jnc"):
            nxt = pc + 1 if cv else f["tgt"]
        elif seq == E("v35_seq_e", "call"):
            retr, nxt = pc + 1, f["tgt"]
        elif seq == E("v35_seq_e", "ret"):
            if retr is None:
                return None, notes | {"return with no call"}
            nxt, retr = retr, None
        elif seq == E("v35_seq_e", "loop"):
            cnt -= 1
            nxt = f["tgt"] if cnt != 0 else pc + 1
        elif seq == E("v35_seq_e", "eac"):
            if mb is None or mb >> 6 == 3:
                nxt = f["tgt"]
            else:
                h = eac_head(r, mb)
                if h is not None:
                    retr, nxt = pc + 1, PROG.labels[h]
        elif seq in (E("v35_seq_e", "disp"), E("v35_seq_e", "dispm")):
            return None, notes | {"reached a dispatch before E"}
        if newcnt is not None:
            cnt = newcnt
        pc = nxt
    return None, notes | {"no E reached"}


def rom_acts(code: bytes, cl: int, taken: bool):
    """The ROM path as model acts: ([set], notes) or (None, notes)."""
    path, notes = rom_walk(code, cl, taken)
    if path is None:
        return None, notes
    E = U.enum_value
    RLX = U.RL_X
    n = len(path)
    acts = [set() for _ in range(n)]
    wait = [None] * n
    op = code[0]
    mra = op == 0x0F or op in U.MODRM_OPS
    rel = [0] * n                   # operand bytes released per word (the model: P, P2)
    if mra:
        rel[0] += 1
    oprw = E("v35_mvd_e", "oprw")
    memw = {E("v35_bus_e", "memw"), E("v35_bus_e", "memwd")}
    memr = {E("v35_bus_e", "memr")}
    io = {E("v35_bus_e", "ior"), E("v35_bus_e", "iow")}
    inta = E("v35_bus_e", "inta")
    rsv = U.ENUMS["v35_bus_e"][1].get("BQ_RSV", -1)      # (main, round 18) posts nothing
    posts = []
    arm_pending = False
    for i, (_, f) in enumerate(path):
        if f.get("ro"):
            acts[i].add("N")
        rl = f.get("rl", 0)
        if rl in (1, 2):
            rel[i] += rl
        if f.get("pop") == getattr(U, "PP_RD", -1) and getattr(U, "PP_RD", None) is not None:
            rel[i] += U.disp_bytes(code[2]) if op == 0x0F else U.disp_bytes(code[1])
        alt = bool(f.get("vk"))
        if rl == RLX:
            wait[i] = ("V" if alt else "Y") if f.get("bi") else ("A" if alt else "X")
        elif f.get("bi"):
            # (main, round 20) `strict` assembles as bi + the second kind on an rl=2 word: the
            # model's I; elsewhere bi + the second kind is the commit word C
            wait[i] = ("I" if rl == 2 else "C") if alt else "B"
        if f.get("f"):
            acts[i].add("D")
        if f.get("flush"):
            acts[i].add("F")
        if arm_pending and (f.get("d1") == oprw or f.get("d2") == oprw):
            acts[i].add("K")
            arm_pending = False
        b = f.get("bus", 0)
        if b and b not in (inta, rsv):
            posts.append((i, b))
            if b == E("v35_bus_e", "memwd"):
                arm_pending = True
    for i, k in enumerate(rel):
        if k >= 1:
            acts[i].add("P")
        if k >= 2:
            acts[i].add("P2")
        if k > 2:
            notes.add("three bytes released on one word (the model releases two at most)")
    req = {}
    for k, (i, b) in enumerate(posts):
        rq_word = i >= 3 and path[i - 3][1].get("rl", 0) == RLX
        if rq_word or k == 0 or b in io:
            j = i - 3
            if j < 0:
                notes.add("a first post within three words of the entry")
                j = 0
            req[j] = "io" if b in io else "mem"
        else:
            j = max(i - 1, 0)
            acts[j].add("Z" if b in memw else "U" if b in memr else "X")
    for i in range(n):
        wk, rq = wait[i], req.get(i)
        if rq == "mem":
            acts[i] |= ({"Y"} if wk in (None, "Y") else {"V"} if wk == "V" else
                        {wk, "Y"} if wk != "I" else {"B", "I", "Y"})
            if wk is None:
                notes.add("a request with no wait flag on its word")
        elif rq == "io":
            acts[i] |= {"X"} if wk in (None, "X") else {"A", "X"} if wk == "A" else {wk, "X"}
            if wk is None:
                notes.add("an I/O request with no wait flag on its word")
        elif wk in ("Y", "V", "X"):
            if wk != "X":
                notes.add(f"a {wk} request word with no post three words later")
            acts[i].add({"Y": "B", "V": "B", "X": "S"}[wk])     # its wait only (approximate)
        elif wk:
            acts[i].add(wk)
    for w in acts:
        if "I" in w:
            w.add("B")              # the model's I word is written BI (I implies the B wait)
        if "F" in w:
            w.discard("B")          # the model's F waits for a running fetch's pin cycle (B's)
    return acts, notes


# ------------------------------------------------------------------------- the model side
def model_key(code: bytes):
    pad = code + bytes(8)
    k = model_m.info(pad, 0)
    return k


def model_acts(code: bytes, key: str, cl: int):
    op = code[0]
    c = imm_byte(code) & 31 if op in (0xC0, 0xC1) else cl
    if key in BUILT:
        return None
    return model_m.routine(op, model_m.DEFAULT, c, key)


def fmt(acts) -> str:
    order = "BCIYVXASLHTGDPKNZUFQ"

    def one(w):
        s = "".join(a for a in order if a in w)
        if "P2" in w:
            s = s.replace("P", "PP2", 1) if "P" in s else s + "P2"
        return s or "."
    return " ".join(one(w) for w in acts)


def norm(acts):
    return [frozenset(w) for w in acts]


def diff_kinds(m, r):
    """What differs between two act lists: the word count, then per act letter the positions
    counted from the end (the boundary word)."""
    out = []
    if len(m) != len(r):
        out.append(f"words {len(m)} vs {len(r)}")
    letters = set().union(*m, *r) if (m or r) else set()
    for a in sorted(letters):
        pm = [len(m) - 1 - i for i, w in enumerate(m) if a in w]
        pr = [len(r) - 1 - i for i, w in enumerate(r) if a in w]
        if pm != pr:
            out.append(f"{a}@end-{pm} vs {pr}")
    return out


# ------------------------------------------------------------------------- the sim check
_INFO = model_m.info
_ROUTINE = model_m.routine
_KEY_LINE = next(i for i, ln in enumerate(Path(model_m.__file__).read_text().splitlines(), 1)
                 if "key = info(code, stg)[0]" in ln)
_SUBJ = {"code": None, "on": False}


def _p_info(code, at):
    k = _INFO(code, at)
    s = _SUBJ
    if s["on"] and sys._getframe(1).f_lineno == _KEY_LINE and _same_enc(code, at):
        s["hit"] = True
        s["orig_key"] = k[0]
        s["cur_code"] = bytes(code[at:at + 8])
        return ("__ROM__", k[1], k[2])
    return k


def _same_enc(code, at):
    sc = _SUBJ["code"]
    op = code[at]
    if op != sc[0]:
        return False
    if op == 0x0F:
        return code[at + 1] == sc[1] and (code[at + 2] >= 0xC0) == (sc[2] >= 0xC0) and \
            (sc[2] >= 0xC0 or code[at + 2] & 0xC7 == sc[2] & 0xC7)
    if op in U.MODRM_OPS:
        return code[at + 1] == sc[1]
    return True


def _p_routine(op, o, cl=31, key=None):
    s = _SUBJ
    if s["on"] and (key == "__ROM__" or (key in NOT_TAKEN | {"JZ", "LOOPZ", "JCXZT"}
                                         and op == s["code"][0])):
        taken = (s.get("orig_key") if key == "__ROM__" else key) not in NOT_TAKEN
        acts, _ = rom_acts(s.get("cur_code") or s["code"], cl, taken)
        if acts is None:
            raise RuntimeError("no ROM path")
        return [set(w) for w in acts]
    return _ROUTINE(op, o, cl, key)


model_m.info = _p_info
model_m.routine = _p_routine


def sim_pair(run, code, limit=900):
    """(own events, ROM-substituted events) or None when either raises."""
    _SUBJ["on"] = False
    try:
        a = model_m.simulate(run, dict(model_m.DEFAULT), limit=limit)
    except Exception:      # noqa: BLE001
        return None
    _SUBJ.update(on=True, code=code, hit=False)
    try:
        b = model_m.simulate(run, dict(model_m.DEFAULT), limit=limit)
    except Exception:      # noqa: BLE001
        b = "error"
    finally:
        _SUBJ["on"] = False
    if not _SUBJ.get("hit"):
        return None
    return a, b


def synthetic_runs(code: bytes):
    from validation.v35s.chains.families import make_chain
    from validation.v35s.chains.image import build_image
    from validation.v35s.qprobe import gen

    def q(c, n):
        return gen.q(c, n)
    S = q(code, "subj")
    fill = {0x90, 0x43, 0xBB, 0xE6, 0x50}
    ctx = {"x1": [S], "x3": [S, q(code, "subj"), q(code, "subj")],
           "nop": [q(gen.NOP, "nop"), S, q(gen.NOP, "nop"), q(gen.NOP, "nop")],
           "ri": [q(gen.RI, "ri"), S, q(gen.NOP, "nop"), q(gen.NOP, "nop")],
           "out": [q([0xE6, 0x22], "out22"), S, q(gen.NOP, "nop")],
           "push": [q([0x50], "push"), S, q(gen.NOP, "nop")],
           "inc": [q(gen.INC, "inc"), S, q(gen.INC, "inc"), q(code, "subj")]}
    runs = []
    for name, body in ctx.items():
        if code[0] in fill and name != "x1" and name != "x3":
            continue
        for w in (0, 1, 2):
            for p in ("even", "odd"):
                c = make_chain("RC", name, {}, gen.frame(body), w, p, regs=gen.REGS)
                b = build_image(c)
                runs.append({"chain": c.to_json(), "code_hex": b.code.hex(),
                             "chain_base": b.chain_base})
    return runs


# ------------------------------------------------------------------------- the corpus
def _load_family(fam):
    from validation.v35s.chains.normalize import load_runs
    try:
        rs = load_runs(fam, (0, 1, 2))
    except FileNotFoundError:
        return []
    return [{"chain": r["chain"], "code_hex": r["code_hex"], "chain_base": r["chain_base"]}
            for r in rs]


def corpus_chains(cache: Path, families, jobs):
    if cache.exists():
        return json.loads(cache.read_text())
    out = []
    with multiprocessing.get_context("fork").Pool(jobs) as pool:
        for rs in pool.imap(_load_family, families):
            out += rs
    cache.write_text(json.dumps(out))
    return out


def subjects(run):
    """(encoding key, code) of every role-x instruction of a corpus run, prefixes stripped."""
    out = []
    for i in run["chain"]["instrs"]:
        if i["role"] != "x":
            continue
        code, rep = strip_prefixes(bytes.fromhex(i["code"]))
        if not code:
            continue
        out.append((("REP " if rep else "") + enc_key(code + bytes(4)), code, i["form"]))
    return out


# ------------------------------------------------------------------------- driver
def check_one(item):
    key, code, n_runs, forms, cl, runs = item
    row = {"enc": key, "runs": n_runs, "forms": forms[:6], "code": code.hex()}
    if key.startswith("REP "):
        row["status"] = "not covered: REP string (the model's REP construction)"
        return row
    try:
        mk = model_key(code)
    except KeyError:
        row["status"] = "model has no routine"
        return row
    row["model_key"] = mk[0]
    taken = mk[0] not in NOT_TAKEN
    ra, rnotes = rom_acts(code, cl, taken)
    row["rom_notes"] = sorted(rnotes)
    cell = rom_cell(code)
    row["rom_routine"] = cell[0] if cell else None
    if ra is None:
        row["status"] = "no ROM path: " + ", ".join(sorted(rnotes))
        return row
    row["rom"] = fmt(ra)
    ma = model_acts(code, mk[0], cl)
    row["model"] = fmt(ma) if ma is not None else None
    if ma is None:
        row["shape"] = "n/a (model routine built in simulate)"
    else:
        row["shape"] = "same" if norm(ma) == norm(ra) else "differs"
        row["shape_diff"] = diff_kinds(norm(ma), norm(ra))
    # decode facts
    op = code[0]
    d = []
    if op != 0x0F:
        f1 = U.udec1(PROG, op)
        ml = model_m.DEFAULT[model_m.LEADS[op]] if op in model_m.LEADS else 1
        rl = f1.get("lead", 0) or 1
        if ml != rl:
            d.append(f"lead model {ml} ROM {rl}")
        mm3 = bool(mk[2])
        rm3 = bool(f1.get("m3")) or (len(code) > 1 and hasattr(U, "uml") and bool(U.uml(PROG, op, code[1])))
        if mm3 != rm3:
            d.append(f"three-bytes wait model {int(mm3)} ROM {int(rm3)}")
    row["decode"] = d
    # the sim check
    tot = dif = err = 0
    ex = []
    for run in runs:
        res = sim_pair(run, code)
        if res is None:
            continue
        tot += 1
        a, b = res
        if b == "error":
            err += 1
        elif a != b:
            dif += 1
            if len(ex) < 2:
                k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                ex.append({"run": run["chain"]["id"], "index": k,
                           "model": a[k] if k < len(a) else None,
                           "rom": b[k] if k < len(b) else None})
    row["sim"] = {"runs": tot, "differ": dif, "errors": err, "examples": ex}
    dd = [x for x in rnotes if x.startswith(("counter from SIGMA", "data-dependent"))]
    gap = mk[1] is None and any(a & {"Y", "V", "Z", "U"} for a in ra)
    if gap:
        row["status"] = "model gap: a register routine for a memory encoding"
        return row
    row["status"] = ("ok" if row.get("shape") in ("same",) and not dif and not err and not d
                     else "mismatch")
    if row.get("shape") == "differs" and tot and not dif and not err and not d:
        row["status"] = "equivalent (shape differs, sim same)"
    if row.get("shape", "").startswith("n/a") and tot and not dif and not err and not d:
        row["status"] = "ok (sim)"
    if row["status"] == "mismatch" and row.get("shape") == "differs" and not tot and not d:
        row["status"] = "shape differs, no sim run (transfers / stack state)"
    if row["status"] == "mismatch" and row.get("shape") in ("same", "differs") and not dif \
            and not err and d and (tot or row.get("shape") == "same"):
        row["status"] = "decode only: " + "; ".join(d)
    if row["status"] == "mismatch" and row.get("shape", "").startswith("n/a") and not tot:
        row["status"] = "not covered: model routine built in simulate, no sim run"
    if row["status"] == "mismatch" and dd and (mk[0] in BUILT or row.get("shape") != "differs"):
        row["status"] = "not covered: data-dependent ROM path (" + "; ".join(dd) + ")"
    return row


def main(argv=None):
    global U, PROG
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 2)[2])
    ap.add_argument("--rom-root", type=Path, default=Path("."),
                    help="the tree whose urom / v35_pkg.sv / uasm.py are read")
    ap.add_argument("--cl", type=int, default=5, help="CL for the counter loads (RB)")
    ap.add_argument("--cache", type=Path, default=Path("romcheck_chains.json"),
                    help="corpus chains cache (built from the corpus when missing)")
    ap.add_argument("--families", nargs="+", help="corpus families (default: every chains-F*)")
    ap.add_argument("--corpus-runs", type=int, default=24,
                    help="corpus runs per encoding for the sim check")
    ap.add_argument("--no-synthetic", action="store_true")
    ap.add_argument("--enc", nargs="+", help="only these encoding keys (e.g. '01 m0r7')")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("romcheck.json"))
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("-v", action="store_true", help="print every encoding")
    a = ap.parse_args(argv)
    U = load_uasm(a.rom_root.resolve())
    PROG = U.assemble()
    fams = a.families
    if not fams:
        from validation.v35s import corpus
        fams = sorted({n.split("-")[1] for n in corpus.manifest()["entries"]
                       if n.startswith("chains-F") and "iowait" not in n},
                      key=lambda f: (len(f), f))
        fams = [f for f in fams if f not in ("F0w",)]
    runs = corpus_chains(a.cache, fams, a.jobs)
    by = collections.OrderedDict()
    for r in runs:
        seen = set()
        for k, code, form in subjects(r):
            e = by.setdefault(k, {"code": code, "runs": 0, "forms": collections.Counter(),
                                  "sample": []})
            e["forms"][form] += 1
            if k not in seen:
                e["runs"] += 1
                seen.add(k)
                if len(e["sample"]) < 4 * a.corpus_runs:
                    e["sample"].append(r)
    items = []
    for k, e in sorted(by.items(), key=lambda kv: -kv[1]["runs"]):
        if a.enc and k not in a.enc:
            continue
        smp = e["sample"][::4][:a.corpus_runs] if a.corpus_runs else []
        syn = [] if a.no_synthetic or k.startswith("REP ") else synthetic_runs(e["code"])
        items.append((k, e["code"], e["runs"], [f for f, _ in e["forms"].most_common()], a.cl,
                      smp + syn))
    with multiprocessing.get_context("fork").Pool(a.jobs) as pool:
        rows = pool.map(check_one, items, chunksize=2)
    # consistency: one model key, several ROM strings
    groups = collections.defaultdict(list)
    for r in rows:
        if r.get("rom") and r.get("model_key"):
            groups[r["model_key"]].append(r)
    incons = []
    for k, rs in groups.items():
        shapes = collections.defaultdict(list)
        for r in rs:
            shapes[(r["rom"], r["rom_routine"])].append(r)
        if len({s for s, _ in shapes}) > 1:
            tot = sum(r["runs"] for r in rs)
            incons.append({"model_key": k, "runs": tot, "rom_shapes": [
                {"rom": s, "routine": rt, "runs": sum(x["runs"] for x in v),
                 "encs": [x["enc"] for x in sorted(v, key=lambda x: -x["runs"])][:8]}
                for (s, rt), v in sorted(shapes.items(), key=lambda kv: -sum(x["runs"] for x in kv[1]))]})
    incons.sort(key=lambda x: -x["runs"])
    a.out.write_text(json.dumps({"rows": rows, "inconsistent": incons}, indent=1, default=str))
    st = collections.Counter(r["status"].split(":")[0] for r in rows)
    print(f"{len(rows)} encodings ({sum(r['runs'] for r in rows)} subject-runs); status:")
    for k, v in st.most_common():
        print(f"  {k:<44} {v:>4} encodings  {sum(r['runs'] for r in rows if r['status'].split(':')[0] == k):>6} runs")
    print(f"\nmismatches by corpus runs (top {a.top}):")
    mm = [r for r in rows if r["status"] == "mismatch"]
    for r in sorted(mm, key=lambda r: -r["runs"])[:a.top]:
        s = r.get("sim", {})
        print(f"  {r['runs']:>5}  {r['enc']:<14} {r['model_key']:<10} ROM {r['rom_routine']:<14}"
              f" shape {r.get('shape')}; sim {s.get('differ')}/{s.get('runs')} differ"
              f"{'; ' + '; '.join(r['decode']) if r.get('decode') else ''}  [{', '.join(r['forms'][:2])}]")
        print(f"         model {r.get('model')}\n         rom   {r.get('rom')}")
        if r.get("rom_notes"):
            print(f"         notes {'; '.join(r['rom_notes'])}")
    print(f"\none model routine, several ROM routines / shapes (top {a.top}):")
    for x in incons[:a.top]:
        print(f"  {x['runs']:>5}  model {x['model_key']}")
        for s in x["rom_shapes"]:
            print(f"         {s['runs']:>5}  ROM {s['routine']:<14} {s['rom']}   {' | '.join(s['encs'][:5])}")
    if a.v:
        for r in rows:
            print(json.dumps(r, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
