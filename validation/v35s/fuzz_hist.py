"""F5: the first-difference histogram of a fuzz set (socket against the RTL).

For every program whose write sequence (or result region) differs, the RTL is run again with
`+v35_trace` (v35_trace.sv: each bus cycle's start and each instruction's start with its
address), which names the instruction executing at the first differing write. When that is an
observation (the PUSH PSW / registers after K fuzzed instructions), the differing word says what
differs (the PSW's bits, or a register) and the culprit is the last fuzzed instruction of the
window before it that writes it; when it is a fuzzed instruction's own write, the culprit is that
instruction. Classes are grouped by mnemonic x form x width x what differs.

    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz_hist SET [SET ...] [--ref socket]
        [--cand sim] [--jobs 8] [--show N] [--json FILE]
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import os
import re
import sys
import tempfile

from . import fuzz as F
from . import fuzz_gen as G

FLAGS = {0: "CY", 2: "P", 3: "F1", 4: "AC", 5: "F0", 6: "Z", 7: "S", 8: "BRK", 9: "IE", 10: "DIR",
         11: "V", 15: "MD"}
FULL_OBS = ["PSW", "AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY", "DS0", "DS1"]
HALF = {"AL": "AW", "AH": "AW", "CL": "CW", "CH": "CW", "DL": "DW", "DH": "DW", "BL": "BW",
        "BH": "BW"}
# registers a mnemonic writes besides its first operand
IMPLICIT = {
    "MUL": ("AW", "DW"), "MULU": ("AW", "DW"), "DIV": ("AW", "DW"), "DIVU": ("AW", "DW"),
    "CVTBD": ("AW",), "CVTDB": ("AW",), "CVTBW": ("AW",), "CVTWL": ("DW",),
    "ADJ4A": ("AW",), "ADJ4S": ("AW",), "ADJBA": ("AW",), "ADJBS": ("AW",), "TRANS": ("AW",),
    "MOVBKB": ("IX", "IY", "CW"), "MOVBKW": ("IX", "IY", "CW"), "CMPBKB": ("IX", "IY", "CW"),
    "CMPBKW": ("IX", "IY", "CW"), "CMPMB": ("IY", "CW"), "CMPMW": ("IY", "CW"),
    "LDMB": ("AW", "IX", "CW"), "LDMW": ("AW", "IX", "CW"), "STMB": ("IY", "CW"),
    "STMW": ("IY", "CW"), "INMB": ("IY", "CW"), "INMW": ("IY", "CW"), "OUTMB": ("IX", "CW"),
    "OUTMW": ("IX", "CW"), "IN": ("AW",), "DBNZ": ("CW",), "DBNZE": ("CW",), "DBNZNE": ("CW",),
    "BCWZ": (), "PREPARE": ("BP", "SP"), "DISPOSE": ("BP", "SP"), "LDS": ("DS1",),
    "LES": ("DS1",), "ADD4S": (), "SUB4S": (), "CMP4S": (), "ROL4": ("AW",), "ROR4": ("AW",),
    "INS": ("IY",), "EXT": ("AW", "IX"), "POP R": ("AW", "CW", "DW", "BW", "BP", "IX", "IY"),
    "XCH": (),
}
NO_FLAGS = {"MOV", "XCH", "LDEA", "LDS", "LES", "PUSH", "POP", "BR", "CALL", "RET", "Bcc", "BCWZ",
            "DBNZ", "DBNZE", "DBNZNE", "MOVBKB", "MOVBKW", "LDMB", "LDMW", "STMB", "STMW", "INMB",
            "INMW", "OUTMB", "OUTMW", "IN", "OUT", "TRANS", "CVTBW", "CVTWL", "NOT", "PREPARE",
            "DISPOSE", "INS", "EXT", "NOP", "DI", "EI", "PUSH R", "POP R", "PUSH PSW",
            "MOV AH,PSW", "BTCLR", "ROL4", "ROR4", "CHKIND", "BRKCS", "TSKSW", "MOVSPA", "MOVSPB",
            "FINT", "BRK", "BRKV", "BRKN", "FPO"}


def mnem(ins):
    return ins.key.split("|")[0] if ins.key else ins.text.split()[0]


def writes_reg(ins, reg):
    """Does the fuzzed instruction (by its text) write register `reg`?"""
    m = mnem(ins)
    if reg == "PSW":
        return m not in NO_FLAGS
    if reg in IMPLICIT.get(m, ()):
        return True
    t = ins.text
    ops = t.split(None, 1)[1] if " " in t else ""
    first = ops.split(",")[0].strip()
    first = first.split(":")[-1] if ":" not in first or "[" not in first else ""
    if HALF.get(first, first) == reg:
        return m not in ("CMP", "TEST", "PUSH", "OUT", "CHKIND", "TEST1")
    if m == "XCH":
        return any(HALF.get(o.strip(), o.strip()) == reg for o in ops.split(","))
    return False


def parse_trace(path):
    """External writes / I/O cycles in order, each with the instruction start's address."""
    out = []
    pc = None
    code_pc = None          # the last instruction started in the program's code (not a stub)
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            m = re.search(r" S:(?:u\d+|trap):([0-9A-Fa-f]{5})", line)
            for x in re.finditer(r" X:(write|io_read|io_write):([0-9A-Fa-f]{5}):(\w+)", line):
                a = int(x.group(2), 16)
                if x.group(1) == "write" and a >= G.IRAM:
                    continue            # on-chip: not a bus cycle
                out.append((pc, x.group(1), a, code_pc))
            if m:
                pc = int(m.group(1), 16)
                if G.CODE <= pc < G.CODE_END:
                    code_pc = pc
    return out


def _windows(ins):
    """For each instruction index: the fuzzed instructions of the window ending at the next
    observation (an observation's own index maps to the window before it)."""
    out = {}
    last = []
    for n, x in enumerate(ins):
        if x.tag == "obs":
            out[n] = list(last)
            if n + 1 < len(ins) and ins[n + 1].tag != "obs":
                last = []
        elif x.tag == "fuzz":
            last.append(x)
            out[n] = [x]
    return out


def classify(set_name, name, ref, cand):
    prog = F.programs(set_name, [name])[name]
    A = F.load(set_name, ref)["programs"][name]
    B = F.load(set_name, cand)["programs"][name]
    ok, msg = F.compare_rec(A, B, prog, prog.mask)
    if ok:
        return None
    filt = getattr(prog, "write_filter", None)
    idx_b = list(range(len(B["writes"])))
    wa, wb = A["writes"], [list(w) + [k] for k, w in enumerate(B["writes"])]
    if filt:
        wa, wb = filt(wa), filt(wb)
    idx_b = [w[3] for w in wb]
    ma = F.masked_writes(wa, prog.mask)
    mb = F.masked_writes([w[:3] for w in wb], prog.mask)
    first = next((k for k, (x, y) in enumerate(zip(ma, mb)) if x != y), None)
    if first is None and len(ma) != len(mb):
        first = min(len(ma), len(mb))
    rec = {"name": name, "msg": msg[:200]}
    if not B["passed"]:
        rec["what"] = "runaway (the RTL did not pass)"
    if first is None:
        rec.setdefault("what", "result region only")
        rec["culprit"] = "-"
        return rec
    x = ma[first] if first < len(ma) else None
    y = mb[first] if first < len(mb) else None
    if "what" not in rec:
        if x is None:
            rec["what"] = "extra write"
        elif y is None:
            rec["what"] = "missing write"
        elif x[0] != y[0] or x[2] != y[2]:
            rec["what"] = "address"
        else:
            rec["what"] = "data"
    rec["first"] = first
    rec["x"], rec["y"] = x, y
    # the RTL's trace: which instruction made the candidate's write `first`
    kb = idx_b[first] if first < len(idx_b) else (idx_b[-1] + 1 if idx_b else 0)
    fd, path = tempfile.mkstemp(prefix="f5h-", suffix=".trc", dir=os.environ.get("F5H_TMP"))
    os.close(fd)
    try:
        os.environ["V35_PLUSARGS"] = f"+v35_trace={path}"
        from .chains.acquire import sim_transport
        from .runner import Harness
        from nuboard.debug import DebugClient
        t = sim_transport("v35")
        try:
            h = Harness(DebugClient(t.exchange), strict=False)
            h.configure(x_half=2)
            F._stim(h, prog)
            code, segs, pages = prog.image()
            h.load(segs, pages)
            h.run("model", prog.limit)
        finally:
            t.close()
        tw = parse_trace(path)
    finally:
        os.unlink(path)
    if kb >= len(tw):
        kb = len(tw) - 1
    pc = tw[kb][0] if tw else None
    ins = prog.ins
    if pc is not None and not G.CODE <= pc < G.CODE_END:
        # a trap's stub (vector n: STUBS + 6n) or the FPO handler: the instruction before it
        vec = (pc - G.STUBS) // 6 if G.STUBS <= pc < G.STUBS + 0x600 else None
        rec["stub"] = f"vector {vec}" if vec is not None else f"handler {pc:05X}"
        pc = tw[kb][3]
    pos = max((n for n, i in enumerate(ins) if pc is not None and i.addr <= pc), default=None)
    if pos is None:
        rec["culprit"] = f"? pc {pc}"
        if rec.get("stub"):
            rec["culprit"] = rec["stub"]
        return rec
    here = ins[pos]
    rec["at"] = f"{here.addr:05X} {here.tag} {here.text}"
    win = _windows(ins).get(pos, [])
    if here.tag == "obs" and x is not None and y is not None and rec["what"] == "data":
        # the word of the observation: its writes since the block's first
        k0 = kb
        while k0 > 0 and tw[k0 - 1][0] == pc:
            k0 -= 1
        words, half = 0, 0
        k = k0
        while True:
            a = tw[k][2]
            pair = bool(a & 1) and k + 1 < len(tw) and tw[k + 1][2] == a + 1 and tw[k + 1][0] == pc
            if kb == k or (pair and kb == k + 1):
                half = 1 if (pair and kb == k + 1) else 0
                break
            k += 2 if pair else 1
            words += 1
        off = pc - here.addr                # each PUSH of the block is one byte
        if "R," in here.text:
            reg = ["PSW", None, "DS0", "DS1"][off] if off < 4 else "?"
            if reg is None:
                reg = ["AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY"][words] if words < 8 else "?"
        else:
            regs = here.text.replace("OBS PUSH ", "").split()
            reg = regs[off] if off < len(regs) else "?"
        d = (x[1] ^ y[1]) & 0xFFFF
        if x[0] & 1:
            d = (d >> 8) & 0xFF            # an odd word's first half: the low byte on the high lane
        elif half:
            d = (d & 0xFF) << 8            # its second half: the high byte on the low lane
        if reg == "PSW":
            names = [FLAGS.get(bit, str(bit)) for bit in range(16) if d >> bit & 1]
            what = "flags " + "+".join(names)
        else:
            what = f"reg {reg}"
        cands = [i for i in win if writes_reg(i, reg)] if reg != "?" else []
        cul = cands[-1] if cands else (win[-1] if win else None)
        rec["what"] = what
        rec["culprit"] = (f"{mnem(cul)}|{cul.key.split('|')[1] if cul.key else ''}|"
                          f"{cul.key.split('|')[3] if cul.key and len(cul.key.split('|')) > 3 else ''}"
                          if cul else "-")
        rec["window"] = [i.text for i in win]
    else:
        cul = here if here.tag == "fuzz" else (win[-1] if win else here)
        rec["culprit"] = (f"{mnem(cul)}|{cul.key.split('|')[1] if cul.key else ''}|"
                          f"{cul.key.split('|')[3] if cul.key and len(cul.key.split('|')) > 3 else ''}"
                          if cul.key else f"({cul.tag}) {cul.text}")
        rec["window"] = [i.text for i in win]
    return rec


def _one(args):
    try:
        return classify(*args)
    except Exception as e:      # noqa: BLE001
        return {"name": args[1], "what": f"error {e!r}", "culprit": "?"}


def histogram(sets, ref="socket", cand="sim", jobs=8, show=2, out_json=None):
    todo = []
    for s in sets:
        A = F.load(s, ref)["programs"]
        for n in sorted(A):
            todo.append((s, n, ref, cand))
    recs = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as ex:
        for r in ex.map(_one, todo, chunksize=4):
            if r:
                recs.append(r)
    groups = collections.defaultdict(list)
    for r in recs:
        what = r["what"] + (f" (in {r['stub']})" if r.get("stub") else "")
        x, y = r.get("x"), r.get("y")
        if r["what"] == "address" and x and y and (x[2] ^ y[2]) & 0x08 and x[0] & ~1 == y[0] & ~1:
            what = "width (word / byte pair)"
        groups[(r.get("culprit", "?"), what)].append(r)
    total = len(todo)
    print(f"{', '.join(sets)}: {total} programs, {len(recs)} differ ({ref} vs {cand})")
    for (cul, what), rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"{len(rs):4d}  {cul:28s} {what}")
        for r in rs[:show]:
            print(f"        {r['name']}: {r.get('at', '')}; {r.get('msg', '')[:150]}")
            if r.get("window"):
                print(f"          window: {' / '.join(r['window'])}")
    if out_json:
        with open(out_json, "w") as f:
            json.dump(recs, f, indent=1)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sets", nargs="+")
    ap.add_argument("--ref", default="socket")
    ap.add_argument("--cand", default="sim")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--show", type=int, default=2)
    ap.add_argument("--json")
    a = ap.parse_args()
    histogram(a.sets, a.ref, a.cand, a.jobs, a.show, a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
