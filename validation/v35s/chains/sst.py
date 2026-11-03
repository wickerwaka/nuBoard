"""(D2) SingleStepTests V20 adapter: initial registers and RAM to final registers and RAM.

The V20 suite (https://github.com/SingleStepTests/v20, v1_native/, fetched into
build/deps/sst-v20/ by tools/fetch_sst_v20.py) records, per opcode file, tests of one
instruction (any segment prefixes before it) from a random state: the registers, the RAM it
needs (the code at CS:IP, the operands, the stack), the registers and RAM bytes it changed.
No timing: the V20's bus is 8 bits and its queue 4 bytes, the V35's 16 and 6; the
architectural result is the same (build/deps/nuV30/docs/notes/singlesteptests_v20.md).

Two consumers. `funcref` (the default): the functional reference (funcref.Cpu) runs every test.
`--rtl` (S6): the core v2's whole-core function bench (fpga/v35s/v35_core2_tb, format V35SST-1:
rtl_vectors.sst_file) runs every test from its initial state, v35_top fetching the instruction
and its prefixes from the test's RAM, to the next instruction's start; its register file, PSW,
segment registers, IP, memory writes and I/O writes are compared with the test's final state
(the V20 classes' with the V35 reference's). Default files RTL_FILES and S6_FILES (`--all` runs
the reference over both).

Mapping: AX..DI = AW CW DW BW SP BP IX IY, CS SS DS ES = PS SS DS0 DS1, FLAGS = PSW (the bits
the ALU writes are the same; the V20's fixed 15-12 = 1, 1 = 1, 5 = 3 = 0 pass through: no form
the RTL decodes writes them), IP = the next instruction's offset (or the target). I/O reads
return FFh per byte (the suite's rig had no device: FFFFh as a word).

Expected differences (not failures, counted apart): a divide error (the trap sequence is a
later item: the reference and the RTL raise the trap condition; the test must show the trap,
IP at the divide vector's target); for the reference, a REP prefix before a non-string
instruction (the suite's: before IDIV only) and FF /7 (undefined); PREPARE with a level (the
corpus's level is 0, the RTL builds that); (S6, --rtl) the forms the core v2 decodes as
trap_nop (reported by form: the register halves the model has no template for, F6 /0, a REP
prefix before a non-string byte) and the forms whose decode is not the V20's
(rtl_vectors.DECODE_DIVERGENCE: F6 / F7 /1 and FF /7 with a memory operand); an access to the V35's on-chip page (FFE00h-FFFFFh: the internal RAM's register
banks and the SFRs at IDB = FFh, memory on the V20); an operand read outside the test's RAM (the
suite's mirror-dependent cases; POP R's discarded SP word, which the V20 does not read and the
V35 does, excepted). The shift group's undocumented /6 is SHL's alias on the V20 (every test
passes so) and is built so. (WP79) ROL4 / ROR4 leave AL differently on the V20 (ROL4: AL << 4 |
the operand's high digit; ROR4: the operand) and the V35 (the data book: AL's high digit kept,
F32's silicon): a test passing only with the V20's AL is counted apart (V20_DIGITS). (S6) POP
PSW, RETI and SAHF load the PSW's bits 1, 3 and 5 (BRKI, F0, F1 on the V35) from the word / AH,
where the V20 forces 1, 0, 0: a test passing only with the V20's bits is counted apart
(V20_FLAGS); a REP compare's overrun read (the V35's, F24 silicon) is not checked against the
suite's RAM (the V20 does not make it). An INS
with offset 0 and width field 15 replaces the whole word: the V20 does not read it (the suite
lists no RAM there: "unlisted"), the frozen model's template does.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.sst [--rtl | --all] [--files 00 81.0 ...]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import dataclass
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
    + _groups(0xF6, range(1, 8)) + _groups(0xF7, range(8)) + _groups(0xFF, range(8))
    # (WP79) the 0F page (F32: the bit ops, the BCD strings, the digit rotates, the bit
    # fields) and the register miscellany (F33: INC / DEC, the adjusts, the converts, the flag
    # forms, FE /0 /1, MUL imm)
    + [f"0F{s:02X}" for s in range(0x10, 0x20)]
    + ["0F20", "0F22", "0F26", "0F28", "0F2A", "0F31", "0F33", "0F39", "0F3B"]
    + ["27", "2F", "37", "3F"] + [f"{0x40 + k:02X}" for k in range(16)]
    + ["98", "99", "D4", "D5", "F5", "F8", "F9", "FA", "FB", "FC", "FD", "FE.0", "FE.1",
       "69", "6B"])
# (S6) the files the core v2's whole-core bench runs beyond RTL_FILES (the reference models them:
# the ALU's AL / AW,imm rows, the immediate groups 80 / 82, the shifts C0 / D2, PUSH / POP r16,
# XCH AW,r16, MOV AL,[d16] / [d16],AL, the string forms (with and without a REP prefix), the far
# transfers, RET imm16 / far, RETI, BRK, PUSH / POP PSW, SAHF / LAHF, LES / LDS, DBNZNE / DBNZE /
# BCWZ, TEST r/m8,imm8 (F6 /0): `tools/fetch_sst_v20.py` fetches them with RTL_FILES)
S6_FILES = tuple(
    [f"{b + k:02X}" for b in range(0x00, 0x40, 8) for k in (4, 5) if b + k != 0x05]
    + [f"{0x50 + k:02X}" for k in range(1, 8)] + [f"{0x58 + k:02X}" for k in range(2, 8)]
    + _groups(0x80, range(8)) + _groups(0x82, range(8))
    + ["91", "93", "94", "95", "96", "97", "9A", "9C", "9D", "9E", "9F", "A0", "A2"]
    + ["A4", "A5", "A6", "A7", "AA", "AB", "AC", "AD", "AE", "AF", "6C", "6D", "6E", "6F"]
    + _groups(0xC0, range(8)) + _groups(0xD2, range(8))
    + ["C2", "C4", "C5", "CA", "CB", "CC", "CD", "CF", "E0", "E1", "E3", "EA", "F6.0"])
# (WP79) ROL4 / ROR4: the V20 leaves AL as the V35 does not (funcref.Cpu.v20_digits); a test
# that fails with the V35's AL and passes with the V20's is counted apart
V20_DIGIT_FILES = frozenset(["0F28", "0F2A"])
V20_DIGITS = "V20's ROL4 / ROR4 AL"
# (S6) POP PSW, RETI, SAHF: the V35 loads the PSW's bits 1, 3 and 5 (BRKI, F0, F1) from the
# word (AH), the V20 forces them (1, 0, 0: funcref.Cpu.v20_flags); counted apart as V20_DIGITS
V20_FLAG_FILES = frozenset(["9D", "CF", "9E"])
V20_FLAGS = "V20's fixed PSW bits"

# the forms the old core's decoder gave a template their semantics did not fit (V35_EE_FUNC);
# (S6) the reference models FF /2-/5 now, the whole-core bench runs them all: the class is
# FF /7's (undefined) for the reference only
NOT_FUNCTIONAL = frozenset(["FF.7"])
# (S6) the string opcodes a REP prefix repeats (funcref._string)
STRING_OPS = frozenset([0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF, 0x6C, 0x6D,
                        0x6E, 0x6F])


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
    """The expected-difference class of a test, or None (a test to pass). rtl (S6, the
    whole-core bench): only PREPARE with a level and the LOCK prefix are counted apart here;
    a REP prefix before a non-string form, FF /7 and the rest run (the reference's classes and
    the RTL's trap_nop are rtl_vectors.sst_file's)."""
    b = test["bytes"]
    k = 0
    while k < len(b) and b[k] in PREFIXES + (0xF0,):
        k += 1
    if (not rtl and k < len(b) and b[k] in fr.REP_PREFIXES
            and not (k + 1 < len(b) and b[k + 1] in STRING_OPS)):
        return "rep prefix"
    if stem in NOT_FUNCTIONAL and not rtl:
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


@dataclass
class RefRun:
    """(S6) the reference's run of one test: its class, the differences from the suite, the
    starts, the CPU after (its registers and memory), the next IP."""
    cls: str
    diffs: list
    starts: list
    cpu: object = None
    ip: int = 0


def run_funcref(test: dict, cpu_class=_CheckedCpu) -> tuple[str, list, object]:
    """('pass' | 'fail' | 'trap' | 'unlisted' | 'not modelled', [difference], the starts):
    the reference on one test."""
    r = reference(test, cpu_class)
    return r.cls, r.diffs, r.starts


def reference(test: dict, cpu_class=_CheckedCpu) -> RefRun:
    """run_funcref's run with the CPU kept (S6: the expected state of a test the V35 and the
    V20 end differently, the I/O writes, the starts)."""
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
        return RefRun("unlisted", [str(e)], starts, cpu, ip)
    except fr.NotModelled as e:
        return RefRun("not modelled", [str(e)], starts, cpu, ip)
    if any(c.kind in ("read", "write") and c.addr >= IDA_PAGE for st in starts
           for c in st.cycles):
        return RefRun("on-chip page", [], starts, cpu, ip)
    want, wip, wram = expected(test)
    if trap:
        # the suite's trap: the next IP is the divide vector's target, the flags pushed
        return RefRun("trap" if (wip, want["PS"]) == (_ivt(test, 0)) else "fail",
                      [f"trap, the suite's CS:IP {want['PS']:04X}:{wip:04X}"], starts, cpu, ip)
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
    return RefRun("fail" if diffs else "pass", diffs, starts, cpu, ip)


def _ivt(test: dict, n: int) -> tuple[int, int]:
    """(IP, CS) of interrupt vector n from the test's initial RAM."""
    ram = {a: b for a, b in test["initial"]["ram"]}
    w = lambda a: ram.get(a, 0) | (ram.get(a + 1, 0) << 8)
    return w(4 * n), w(4 * n + 2)


class _V20DigitsCpu(_CheckedCpu):
    """(WP79) _CheckedCpu with ROL4 / ROR4's AL as the V20 leaves it."""
    v20_digits = True


class _V20FlagsCpu(_CheckedCpu):
    """(S6) _CheckedCpu with POP PSW / RETI / SAHF's fixed bits as the V20 forces them."""
    v20_flags = True


def run_v35_or_v20(test: dict, stem: str) -> tuple[str, list, object]:
    """(WP79) run_funcref; a ROL4 / ROR4 test failing with the V35's AL and passing with the
    V20's is the class V20_DIGITS; (S6) a POP PSW / RETI / SAHF test failing with the V35's
    PSW bits 1, 3 and 5 (BRKI, F0, F1: loaded from the word or AH) and passing with the V20's
    fixed ones (1, 0, 0) is the class V20_FLAGS."""
    r = reference_v35_or_v20(test, stem)
    return r.cls, r.diffs, r.starts


def reference_v35_or_v20(test: dict, stem: str) -> RefRun:
    """run_v35_or_v20 with the V35's run kept (S6): a V20 class's RefRun is the V35
    reference's (its CPU the V35's state after the test), its class the V20 class."""
    r = reference(test)
    for files, cpu_class, name in ((V20_DIGIT_FILES, _V20DigitsCpu, V20_DIGITS),
                                   (V20_FLAG_FILES, _V20FlagsCpu, V20_FLAGS)):
        if r.cls == "fail" and stem in files:
            r2 = reference(test, cpu_class)
            if r2.cls == "pass":
                return RefRun(name, r2.diffs, r.starts, r.cpu, r.ip)
    return r


def _funcref_file(args) -> tuple[str, dict, list]:
    stem, show = args
    counts: dict = {}
    fails = []
    for test in load(stem):
        c = classify(test, stem)
        if c is None:
            c, diffs, _ = run_v35_or_v20(test, stem)
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
    p.add_argument("--files", nargs="+", help="opcode file stems (default: RTL_FILES; with "
                   "--rtl or --all, RTL_FILES and S6_FILES)")
    p.add_argument("--rtl", action="store_true",
                   help="(S6) the core v2's whole-core bench (fpga/v35s/build_core2_tb.sh)")
    p.add_argument("--all", action="store_true",
                   help="(S6) the reference over RTL_FILES and S6_FILES")
    p.add_argument("--show", type=int, default=3)
    p.add_argument("--keep", type=Path, help="(--rtl) keep the vector files and outputs here")
    p.add_argument("--jobs", type=int, default=8)
    args = p.parse_args(argv)
    stems = args.files or list(RTL_FILES) + (list(S6_FILES) if args.rtl or args.all else [])
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
    return 1 if any(k == "fail" or k.startswith("rtl fail") for k in tot) else 0


if __name__ == "__main__":
    sys.exit(main())
