"""(S6) The core v2's function path: the whole-core function bench (fpga/v35s/v35_core2_tb.sv,
build_core2_tb.sh), its SingleStepTests and --regfile drivers (sst.py --rtl, rtl_vectors.py
--regfile: format V35SST-1), the functional reference's S6 forms (funcref.py: E3, E1, E0, EA, 9A,
C2, CA, CB, CF, CC, CD, 9C, 9D, 9E, 9F, C4, C5, F0, FF /2-/5) and the write-data scorer
(replay.py --score --data).

Offline: the reference on a fixed subset of the suite's files for the S6 forms, the V20 classes,
the C2Test text, c2_case. End to end (skipped when build/fpga/v35s/core2-tb/Vv35_core2_tb is
missing or older than its sources: fpga/v35s/build_core2_tb.sh): the first tests of a fixed set
of SingleStepTests files (skipped when the suite's files are not fetched:
tools/fetch_sst_v20.py) and code snippets (the LDEA -> OUT AL case among them) through the bench,
no test failing.

    PYTHONPATH=host/src:. python3 -m unittest validation.v35s.chains.test_sst_rtl
"""

import unittest

from validation.v35s.chains import funcref as fr, rtl_vectors as rv, sst

ROOT = rv.ROOT
BENCH_SOURCES = (["fpga/v35s/" + n for n in ("v35_core2_tb.sv", "v35_core2_tb.cpp",
                                              "v35_core2_tb.vlt", "build_core2_tb.sh")]
                 + [str(p.relative_to(ROOT)) for p in (ROOT / "fpga/v35s/core/v35").glob("*")
                    if p.suffix in (".sv", ".svh", ".hex")]
                 + ["fpga/v35s/core/v35_sfr.sv", "fpga/v35s/core/v35_refresh.sv"])
# the files and the tests of each the end-to-end test runs (the first N)
SUBSET = (("00", 60), ("05", 40), ("8D", 60), ("8E", 40), ("C6", 60), ("C7", 40), ("F6.1", 40),
          ("F7.6", 80), ("F7.7", 80), ("F6.6", 60), ("D3.4", 40), ("E3", 40), ("E1", 40),
          ("9C", 30), ("9D", 30), ("FF.2", 40), ("FF.4", 40), ("FF.3", 30), ("CC", 30),
          ("CF", 30), ("A4", 40), ("A6", 40), ("AA", 30), ("6C", 20), ("0F28", 40),
          ("0F33", 40), ("D4", 40), ("98", 20), ("99", 20), ("54", 20), ("C4", 30))
# (code, instructions, registers): the S6 bugs' snippets; the expected state the reference's
SNIPPETS = (
    ("e6208d07e621", 3, {}),            # OUT 20h,AL; LDEA AW,[BW]; OUT 21h,AL (AL = 00h)
    ("98e621", 2, {"AW": 0x8080}),      # CVTBW; OUT 21h,AL
    ("99e621", 2, {"AW": 0x8080}),      # CVTWL
    ("54e621", 2, {}),                  # PUSH SP (SP - 2)
    ("ff07ff37", 2, {}),                # INC [BW]; PUSH [BW] (the read's datum)
    ("c7073412", 1, {}),                # MOV [BW],1234h (the immediate at B2)
    ("c6940e0397", 1, {"IX": 0x2000}),  # MOV byte [IX+30Eh],97h (C6 /2: the alias)
)


def _bench_current() -> bool:
    b = rv.C2BENCH
    if not b.exists():
        return False
    t = b.stat().st_mtime
    return all((ROOT / s).stat().st_mtime <= t for s in BENCH_SOURCES if (ROOT / s).exists())


def _have(stem: str) -> bool:
    return (sst.SST_DIR / f"{stem}.json.gz").exists()


def snippet_test(code: bytes, n: int, extra: dict) -> rv.C2Test:
    """The whole-core test of a code snippet at 1000:0100 from a fixed register file, the
    expected state the reference's."""
    regs = {"AW": 0x1234, "CW": 0x0005, "DW": 0x5678, "BW": 0x0800, "SP": 0x0F00, "BP": 0x0A00,
            "IX": 0x0100, "IY": 0x0180, "DS1": 0x2000, "PS": 0x1000, "SS": 0x3000,
            "DS0": 0x4000, "PSW": 0xF002}
    regs.update(extra)
    ip = 0x0100
    mem = bytearray(b"\x90") * (1 << 20)
    base = (regs["PS"] << 4) + ip
    mem[base:base + len(code)] = code
    cpu = fr.Cpu(dict(regs), mem, 0xFFFF, 0)
    starts, pc = [], ip
    for _ in range(n):
        st = cpu.step(pc)
        starts.append(st)
        pc = st.target if st.taken else (pc + st.length) & 0xFFFF
    ram = {(base + i) & 0xFFFFF: b for i, b in enumerate(code)}
    for st in starts:
        for c in st.cycles:
            if c.kind in ("read", "write"):
                for a in (c.addr, (c.addr + 1) & 0xFFFFF):
                    ram.setdefault(a, 0x90)
    got = cpu.snapshot()
    fin = {a: cpu.mem[a] for a in set(ram) | rv.c2_written(starts)}
    return rv.C2Test(code.hex(), n, {k: regs[k] for k in rv.C2REGS}, ip, ram,
                     {k: got[k] for k in rv.C2REGS}, pc, fin, rv.c2_io(starts),
                     400 + 240 * n, clen=len(code))


class TestReference(unittest.TestCase):
    """funcref's S6 forms against the V20 suite (the first tests of each file)."""

    def test_s6_forms(self):
        for stem in ("E3", "E1", "E0", "9C", "9D", "9E", "9F", "C2", "CA", "CB", "CF", "CC",
                     "CD", "EA", "9A", "C4", "C5", "FF.2", "FF.3", "FF.4", "FF.5"):
            if not _have(stem):
                continue
            with self.subTest(stem=stem):
                bad = []
                for test in sst.load(stem)[:150]:
                    if sst.classify(test, stem) is not None:
                        continue
                    c, d, _ = sst.run_v35_or_v20(test, stem)
                    if c in ("fail", "not modelled"):
                        bad.append(f"#{test['idx']} {test['name']}: {c} {d[:2]}")
                self.assertEqual(bad, [])

    def test_classify(self):
        t = {"bytes": [0xF3, 0x01, 0xC0]}
        self.assertEqual(sst.classify(t, "01"), "rep prefix")
        self.assertIsNone(sst.classify(t, "01", rtl=True))
        t = {"bytes": [0xF3, 0xA4]}
        self.assertIsNone(sst.classify(t, "A4"))
        self.assertEqual(sst.classify({"bytes": [0xFF, 0x38]}, "FF.7"),
                         "not functional (V35_EE_FUNC)")
        self.assertIsNone(sst.classify({"bytes": [0xFF, 0x10]}, "FF.2"))
        self.assertEqual(sst.classify({"bytes": [0xC8, 1, 0, 3]}, "C8", rtl=True),
                         "PREPARE level")


class TestFormat(unittest.TestCase):
    def test_text(self):
        t = rv.C2Test("7", 2, {n: i for i, n in enumerate(rv.C2REGS)}, 0x100, {5: 1, 9: 2},
                      {n: 2 * i for i, n in enumerate(rv.C2REGS)}, 0x104, {9: 3},
                      [(0x21, 2, 0x8000)], 900)
        a, b = t.text().split("\n")
        self.assertEqual(a.split()[:4], ["T", "7", "2", "900"])
        self.assertEqual(a.split()[4:4 + 14], [str(i) for i in range(13)] + ["256"])
        self.assertEqual(a.split()[18:], ["0", "65535", "2", "5", "1", "9", "2"])  # clen, I/O
        f = b.split()
        self.assertEqual(f[:2], ["E", "0"])
        self.assertEqual(f[2:16], [str(2 * i) for i in range(13)] + ["260"])
        self.assertEqual(f[16:], ["1", "9", "3", "1", "33", "2", "32768"])
        t.out, t.io = None, None
        self.assertEqual(t.text().split("\n")[1].split()[:2], ["E", "1"])
        self.assertEqual(t.text().split("\n")[1].split()[-1], "-1")

    def test_c2_case(self):
        regs = {"AW": 1, "CW": 2, "DW": 3, "BW": 0x10, "SP": 0x100, "BP": 6, "IX": 7, "IY": 8,
                "DS1": 0, "PS": 0x20, "SS": 0, "DS0": 0x30, "PSW": 0xF002, "pfx": 3}
        mem = bytearray(1 << 20)
        code = bytes([0x8B, 0x07, 0x90, 0x90, 0x90, 0x90])     # MOV AW,[BW] (DS0 prefix)
        st, after, trap = rv.single_step(regs, code, mem, 0x40)
        t = rv.c2_case(regs, code, 0x40, st, after, trap)
        self.assertEqual((t.starts, t.ip), (2, 0x3F))
        self.assertEqual(t.ram[0x200 + 0x3F], 0x3E)            # the DS0 prefix byte
        self.assertIn(0x310, t.ram)                            # the read's word
        self.assertEqual(t.out_ip, 0x42)


class TestDataScore(unittest.TestCase):
    """replay.score_data: the silicon corpus's own records, read as replays, agree on every write;
    a missing replay is reported."""

    def test_self(self):
        import json
        import tempfile
        from pathlib import Path

        from validation.v35s.chains import replay
        from validation.v35s.chains.normalize import load_runs
        try:
            runs = load_runs("F25", (0,))
        except FileNotFoundError:
            self.skipTest("no corpus")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "F25-w0.json").write_text(json.dumps({"runs": runs[1:]}))
            res = replay.score_data(["F25"], (0,), Path(tmp), 1, 0, log=lambda *a: None)
            rs = res["F25"]
            self.assertEqual(len(rs), len(runs))
            self.assertEqual(rs[0]["status"], "no RTL")
            self.assertTrue(all(r["status"] == "ok" and r["agree"] == r["writes"]
                                for r in rs[1:]))
            self.assertGreater(sum(r["writes"] for r in rs), 0)


@unittest.skipUnless(_bench_current(), "the whole-core bench is missing or older than its "
                     "sources (fpga/v35s/build_core2_tb.sh)")
class TestBench(unittest.TestCase):
    def test_snippets(self):
        tests = [snippet_test(bytes.fromhex(c), n, r) for c, n, r in SNIPPETS]
        sm, res = rv.run_core2(tests)
        self.assertEqual(sm["tests"], len(tests))
        self.assertEqual(res, {})

    def test_sst_subset(self):
        tests, kinds = [], {}
        for stem, n in SUBSET:
            if not _have(stem):
                continue
            for test in sst.load(stem)[:n]:
                c, kind, t = rv.sst_test(test, stem)
                if t is None:
                    continue
                t.tid = f"{stem}#{test['idx']}"
                tests.append(t)
                kinds[t.tid] = kind
        if not tests:
            self.skipTest("the SingleStepTests files are not fetched (tools/fetch_sst_v20.py)")
        sm, res = rv.run_core2(tests)
        fails = {k: v[1] for k, v in res.items() if v[0] != "TRAPNOP"
                 and kinds[k] not in rv.DECODE_DIVERGENCE.values()}
        self.assertEqual(fails, {})
        self.assertGreater(sm["pass"], len(tests) // 2)


if __name__ == "__main__":
    unittest.main()
