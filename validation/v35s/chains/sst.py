"""(D2) SingleStepTests V20 adapter: initial registers and RAM to final registers and RAM.

The V20 suite (https://github.com/SingleStepTests/v20, v1_native/, fetched into
build/deps/sst-v20/ by tools/fetch_sst_v20.py) records, per opcode file, tests of one
instruction (any segment prefixes before it) from a random state: the registers, the RAM it
needs (the code at CS:IP, the operands, the stack), the registers and RAM bytes it changed.
No timing: the V20's bus is 8 bits and its queue 4 bytes, the V35's 16 and 6; the
architectural result is the same (build/deps/nuV30/docs/notes/singlesteptests_v20.md).

Two consumers. `funcref` (the default): the functional reference (funcref.Cpu) runs every test.
`--rtl`: the register file's unit bench (fpga/v35s/v35_rf_tb, rtl_vectors' --regfile format)
runs every test the RTL decodes, an instruction start at a time (a prefix is one), its reads
served from the test's RAM in the order the reference makes them, and its register file, its
transfer target and its writes (their data, applied to the test's RAM) compared with the test's
final state.

Mapping: AX..DI = AW CW DW BW SP BP IX IY, CS SS DS ES = PS SS DS0 DS1, FLAGS = PSW (the bits
the ALU writes are the same; the V20's fixed 15-12 = 1, 1 = 1, 5 = 3 = 0 pass through: no form
the RTL decodes writes them), IP = the next instruction's offset (or the target). I/O reads
return FFh per byte (the suite's rig had no device: FFFFh as a word).

Expected differences (not failures, counted apart): a divide error (the trap sequence is a
later item: the reference and the RTL raise the trap condition; the test must show the trap,
IP at the divide vector's target); a REP prefix before a non-string instruction and the string
forms (the RTL leaves them out, Phase E3); PREPARE with a level (the corpus's level is 0, the
RTL builds that); FF /2-/5 and /7 (transfers) and, in the RTL, F6/F7 /1 (TEST's alias) and the
register forms of F6/F7 /2 /3, FF /0 /1 /6, 8F and C6/C7 (the decoder gives them a memory or
read-modify-write template their semantics do not have: the RTL raises V35_EE_FUNC, which the
bench checks); an access to the V35's on-chip page (FFE00h-FFFFFh: the internal RAM's register
banks and the SFRs at IDB = FFh, memory on the V20); an operand read outside the test's RAM (the
suite's mirror-dependent cases; POP R's discarded SP word, which the V20 does not read and the
V35 does, excepted). The shift group's undocumented /6 is SHL's alias on the V20 (every test
passes so) and is built so.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.sst [--rtl] [--files 00 81.0 ...]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from . import funcref as fr

ROOT = Path(__file__).resolve().parents[3]
SST_DIR = ROOT / "build" / "deps" / "sst-v20" / "v1_native"
REGMAP = (("ax", "AW"), ("cx", "CW"), ("dx", "DW"), ("bx", "BW"), ("sp", "SP"), ("bp", "BP"),
          ("si", "IX"), ("di", "IY"), ("cs", "PS"), ("ss", "SS"), ("ds", "DS0"), ("es", "DS1"),
          ("flags", "PSW"))
PREFIXES = (0x26, 0x2E, 0x36, 0x3E)
IDA_PAGE = 0xFFE00          # the V35's internal RAM (the register banks) and SFRs at IDB = FFh


def _groups(op: int, regs) -> list[str]:
    return [f"{op:02X}.{r}" for r in regs]


# The opcode files of every instruction the RTL decodes (v35_eu_pkg eu_decode; D2 adds the
# 70-7F conditions): the ModR/M ALU rows, 05, A8, A9, the segment pushes and pops, PUSH AW,
# POP AW / CW, PUSH R / POP R, PUSH imm, the transfers, 84-8F, 81 and 83, NOP and XCH AW,DW,
# A1 / A3, MOV imm, C1 / D0 / D1 / D3, RET, MOV r/m,imm, PREPARE, DISPOSE, XLAT, the I/O forms,
# F6 /1-7, F7, FF.
RTL_FILES = tuple(
    [f"{b + k:02X}" for b in range(0x00, 0x40, 8) for k in range(4)]
    + ["05", "A8", "A9", "06", "07", "0E", "16", "17", "1E", "1F", "50", "58", "59", "60", "61",
       "68", "6A"] + [f"{0x70 + k:02X}" for k in range(16)]
    + ["84", "85", "86", "87", "88", "89", "8A", "8B", "8C", "8D", "8E", "8F"]
    + _groups(0x81, range(8)) + _groups(0x83, range(8))
    + ["90", "92", "A1", "A3"] + [f"{0xB0 + k:02X}" for k in range(16)]
    + _groups(0xC1, range(8)) + ["C3", "C6", "C7", "C8", "C9"]
    + _groups(0xD0, range(8)) + _groups(0xD1, range(8)) + _groups(0xD3, range(8))
    + ["D7", "E2", "E4", "E5", "E6", "E7", "E8", "E9", "EB", "EC", "ED", "EE", "EF"]
    + _groups(0xF6, range(1, 8)) + _groups(0xF7, range(8)) + _groups(0xFF, range(8)))

# the forms the decoder gives a template their semantics do not fit (V35_EE_FUNC)
NOT_FUNCTIONAL = frozenset(["FF.2", "FF.3", "FF.4", "FF.5", "FF.7", "F6.1", "F7.1"])


def load(stem: str) -> list[dict]:
    path = SST_DIR / f"{stem}.json.gz"
    with gzip.open(path, "rt") as f:
        return json.load(f)


class Unlisted(RuntimeError):
    """A test reads a byte its initial RAM does not list (a mirror-dependent case)."""


class _Mem(bytearray):
    """1 MB of RAM that remembers which bytes the test listed."""

    def __init__(self, ram):
        super().__init__(1 << 20)
        self.listed = bytearray(1 << 20)
        for a, b in ram:
            self[a] = b
            self.listed[a] = 1


def initial(test: dict) -> tuple[dict, _Mem, int]:
    r = test["initial"]["regs"]
    regs = {n: r[k] for k, n in REGMAP}
    return regs, _Mem(test["initial"]["ram"]), r["ip"]


def expected(test: dict) -> tuple[dict, int, dict]:
    """(final registers, final IP, {address: byte} of the final RAM's changed bytes)."""
    r = dict(test["initial"]["regs"])
    r.update(test["final"]["regs"])
    regs = {n: r[k] for k, n in REGMAP}
    return regs, r["ip"], {a: b for a, b in test["final"]["ram"]}


def classify(test: dict, stem: str, rtl: bool = False) -> str | None:
    """The expected-difference class of a test, or None (a test to pass)."""
    b = test["bytes"]
    k = 0
    while k < len(b) and b[k] in PREFIXES + (0xF0,):
        k += 1
    if k < len(b) and b[k] in fr.REP_PREFIXES:
        return "rep prefix"
    if stem in NOT_FUNCTIONAL and (rtl or stem.startswith("FF")):
        return "not functional (V35_EE_FUNC)"
    if stem == "C8" and b[k + 3] % 32 != 0 if k + 3 < len(b) else False:
        return "PREPARE level"
    if 0xF0 in b[:k]:
        return "LOCK prefix"
    return None


class _CheckedCpu(fr.Cpu):
    """funcref.Cpu whose reads must stay inside the test's listed RAM."""

    def read(self, base, off, w):
        for i in range(w if not self.discard else 0):
            a = self._lin(base, off + i)
            if not self.mem.listed[a]:
                raise Unlisted(f"read of {a:05X}")
        return super().read(base, off, w)


def run_funcref(test: dict, cpu_class=_CheckedCpu) -> tuple[str, list, object]:
    """('pass' | 'fail' | 'trap' | 'unlisted' | 'not modelled', [difference], the starts):
    the reference on one test."""
    regs, mem, ip = initial(test)
    cpu = cpu_class(regs, mem, 0xFFFF, 0)
    starts = []
    trap = False
    try:
        for _ in range(8):
            st = cpu.step(ip)
            starts.append(st)
            ip = st.target if st.taken else (ip + st.length) & 0xFFFF
            if cpu.pfx is None:
                break
    except fr.Trap as e:
        trap = True
        starts.append(e.start)
    except Unlisted as e:
        return "unlisted", [str(e)], starts
    except fr.NotModelled as e:
        return "not modelled", [str(e)], starts
    if any(c.kind in ("read", "write") and c.addr >= IDA_PAGE for st in starts
           for c in st.cycles):
        return "on-chip page", [], starts
    want, wip, wram = expected(test)
    if trap:
        # the suite's trap: the next IP is the divide vector's target, the flags pushed
        vec = (want["PS"] << 4) + wip
        return ("trap" if (wip, want["PS"]) == (_ivt(test, 0)) else "fail",
                [f"trap, the suite's CS:IP {want['PS']:04X}:{wip:04X}"], starts)
    got = cpu.snapshot()
    diffs = []
    for n in [n for _, n in REGMAP]:
        if got[n] != want[n]:
            diffs.append(f"{n} {got[n]:04X} (suite {want[n]:04X})")
    if ip != wip:
        diffs.append(f"IP {ip:04X} (suite {wip:04X})")
    init = {a: b for a, b in test["initial"]["ram"]}
    for a, b in wram.items():
        if mem[a] != b:
            diffs.append(f"[{a:05X}] {mem[a]:02X} (suite {b:02X})")
    for a, b0 in init.items():
        if a not in wram and mem[a] != b0:
            diffs.append(f"[{a:05X}] {mem[a]:02X} written (suite unchanged {b0:02X})")
    return ("fail" if diffs else "pass"), diffs, starts


def _ivt(test: dict, n: int) -> tuple[int, int]:
    """(IP, CS) of interrupt vector n from the test's initial RAM."""
    ram = {a: b for a, b in test["initial"]["ram"]}
    w = lambda a: ram.get(a, 0) | (ram.get(a + 1, 0) << 8)
    return w(4 * n), w(4 * n + 2)


def _funcref_file(args) -> tuple[str, dict, list]:
    stem, show = args
    counts: dict = {}
    fails = []
    for test in load(stem):
        c = classify(test, stem)
        if c is None:
            c, diffs, _ = run_funcref(test)
            if c == "fail" and len(fails) < show:
                fails.append(f"    {stem} #{test['idx']} {test['name']}: {'; '.join(diffs[:4])}")
        counts[c] = counts.get(c, 0) + 1
    return stem, counts, fails


def check_funcref(stems, show: int = 3, jobs: int = 8) -> dict:
    """{stem: {class: count}} of the reference over the files."""
    from multiprocessing import get_context
    out = {}
    with get_context("spawn").Pool(max(1, min(jobs, 8))) as pool:
        for stem, counts, fails in pool.imap(_funcref_file, [(s, show) for s in stems]):
            out[stem] = counts
            for line in fails:
                print(line)
            print(f"{stem:<5} " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items())),
                  flush=True)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m validation.v35s.chains.sst",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--files", nargs="+", help="opcode file stems (default: RTL_FILES)")
    p.add_argument("--rtl", action="store_true", help="the RTL's register file bench")
    p.add_argument("--show", type=int, default=3)
    p.add_argument("--keep", type=Path, help="(--rtl) keep the vector files and outputs here")
    p.add_argument("--jobs", type=int, default=8)
    args = p.parse_args(argv)
    stems = args.files or list(RTL_FILES)
    missing = [s for s in stems if not (SST_DIR / f"{s}.json.gz").exists()]
    if missing:
        print(f"error: missing {', '.join(missing[:5])}... (tools/fetch_sst_v20.py)",
              file=sys.stderr)
        return 2
    if args.rtl:
        from .rtl_vectors import check_sst
        res = check_sst(stems, args.keep, args.jobs, args.show)
    else:
        res = check_funcref(stems, args.show, args.jobs)
    tot: dict = {}
    for counts in res.values():
        for k, v in counts.items():
            tot[k] = tot.get(k, 0) + v
    print("all   " + "  ".join(f"{k} {v}" for k, v in sorted(tot.items())))
    return 1 if tot.get("fail", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
