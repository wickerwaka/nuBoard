"""C1 and C2, the bus unit and the queue in RTL (HDL plan, Phase C): the vectors the frozen
model gives the benches (rtl_vectors.py), and, when a bench is built
(fpga/v35s/build_biu_tb.sh, build_queue_tb.sh), the RTL against them on sample runs.

C1: v35_biu.sv, every cycle's start, length, kind, address, width, data and delivery clock,
every clock's window signals and state bundle, and the pins. C2: v35_queue.sv, the state
after the delivery, after each op the other machines make and at the end of every clock, and
every read; then the queue and the bus unit together (the fetches the RTL queue's), the
cycles as the model's. C3: v35_eu.sv (the decoder and the EU), the state after every phase
and every queue op it makes, alone and with the RTL queue and bus unit. C4: v35_arbiter.sv and
the core v35_chain_core.sv (the five machines together, the arbiter's decisions in RTL), every
machine's state after every phase of every clock and the cycles. The gates' full runs:
python -m validation.v35s.chains.rtl_vectors --family F0 F0w, --queue --family F0 F2 F9 F11,
--joint --family F0 F2 F9 F11, --eu / --joint3 --family F1 F2 F3 F9 F11 F12 F20, --core
--family F4 F5 F6 F7 F10 F14 F15 F16 F19 F21 F22 F26 F29."""

from __future__ import annotations

import re
import unittest

from validation.v35s.chains import rtl_vectors
from validation.v35s.chains.normalize import load_runs, normalize
from validation.v35s.chains.sim.config import Config

# (family, run id): F0 and F0w (the gate), a refresh-on run with the RFM store (F17),
# refresh lengths 3 and 4 from the prelude's RFM (F13 series R), and disp_io's extension
SAMPLE = (("F0", "F0-ls-pO-w2"), ("F0w", "F0w-wtc8000-pE"), ("F2", None), ("F17", None),
          ("F13", "F13-r-"), ("F21", "F21-out-l0-ld-bw_ix_d16-pE-w0"))


def _run(family, part):
    runs = load_runs(family)
    return next(r for r in runs if part is None or part in r["chain"]["id"])


class Vectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.fitted()

    def _vec(self, family, part):
        s = normalize(_run(family, part))
        text, cycles = rtl_vectors.vectors(s.chain, self.cfg, s.chain_base)
        lines = text.splitlines()
        head = lines[0].split()
        self.assertEqual(head[0], rtl_vectors.FORMAT)
        n = int(head[4])
        rows = [dict(zip(rtl_vectors.COLUMNS, map(int, x.split()))) for x in lines[1:1 + n]]
        clist = lines[1 + n:]
        self.assertEqual(len(clist), len(cycles))
        return s, rows, cycles

    def test_one_start_per_cycle_and_deliveries(self):
        s, rows, cycles = self._vec("F0", "F0-ls-pO-w2")
        starts = [r["t"] for r in rows if r["start"]]
        self.assertEqual(starts, [c.start for c in cycles])
        dones = [r["t"] for r in rows if r["done"]]
        self.assertEqual(dones, sorted(c.end + 1 for c in cycles))
        # clock 0: the prelude's POP PSW stack read (prelude_anchor=pop), no latch fill
        self.assertEqual((rows[0]["start"], rtl_vectors.KINDS[rows[0]["kind"]], rows[0]["latch"]),
                         (1, "read", 0))
        # a start only on a free clock
        self.assertTrue(all(r["free"] for r in rows if r["start"]))

    def test_disp_io_extension(self):
        _, rows, _ = self._vec("F21", "F21-out-l0-ld-bw_ix_d16-pE-w0")
        ext = [r for r in rows if r["ext"]]
        self.assertTrue(ext)
        for r in ext:
            self.assertTrue(rtl_vectors.KINDS[r["kind"]].startswith("io"))
            t = r["t"] + next(x["len"] for x in rows if x["t"] == r["t"])
            after = next(x for x in rows if x["t"] == t)
            self.assertFalse(after["free"])           # nothing starts after its last clock

    def test_refresh_lengths(self):
        s, rows, cycles = self._vec("F13", "F13-r-")
        from validation.v35s.chains.types import refresh_length
        self.assertTrue(all(r["rlen"] == refresh_length(s.chain.rfm) for r in rows if r["has_row"]))
        self.assertTrue(all(c.length == refresh_length(s.chain.rfm)
                            for c in cycles if c.kind == "refresh"))


@unittest.skipUnless(rtl_vectors.BENCH.exists(), "bench not built: fpga/v35s/build_biu_tb.sh")
class Bench(unittest.TestCase):
    def test_sample_runs_exact(self):
        cfg = Config.fitted()
        for family, part in SAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_run(rec, cfg)
                self.assertEqual(r.error, "")
                self.assertTrue(r.ok, f"{r.first} cycles {r.exact_cycles}/{r.cycles}")
                self.assertEqual(r.rtl_cycles, r.cycles)
                self.assertTrue(r.rtl_model_exact)
                self.assertEqual(r.rtl_exact, r.model_exact)

    def test_bench_catches_a_wrong_expectation(self):
        import subprocess
        import tempfile
        from pathlib import Path
        s = normalize(_run("F0", "F0-ls-pO-w2"))
        text, _ = rtl_vectors.vectors(s.chain, Config.fitted(), s.chain_base)
        lines = text.splitlines()
        i = rtl_vectors.COLUMNS.index("free")
        row = lines[5].split()
        row[i] = str(1 - int(row[i]))
        lines[5] = " ".join(row)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.vec"
            path.write_text("\n".join(lines) + "\n")
            p = subprocess.run([str(rtl_vectors.BENCH), str(path)], capture_output=True,
                               text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL clock 4 free", p.stdout)



# C2 ------------------------------------------------------------------------------------------

QUEUE_SV = rtl_vectors.ROOT / "fpga" / "v35s" / "core" / "v35_queue.sv"

# the gate's families, a refresh-on run (F13 series C: the beaten fetch, refresh_io_run), an
# F23 transfer (the flush), an aborted cycle's family (F16 S) and refresh_beat_t4's (F13 R)
QSAMPLE = (("F0", "F0-ls-pO-w2"), ("F2", None), ("F9", "F9-push-empty-pE-w0"), ("F11", None),
           ("F13", "F13-c-out-shlcl2-pE-w2"), ("F23", "F23-push-br-n1-pO-w0"),
           ("F16", "F16-s-none-cl4-n1-shlcl-pO-w0"), ("F13", "F13-r-rfm-f2-pE-w0"),
           ("F29", "F29-out-ec-gih-incd16-n0-pE-w0"))


def _parse_qvec(text):
    lines = text.splitlines()
    head = lines[0].split()
    n = int(head[2])
    clocks, i = [], 3
    for _ in range(n):
        k = list(map(int, lines[i].split()[1:]))
        i += 2                                  # K, S after C
        ops = []
        for _ in range(k[-1]):
            ops.append(list(map(int, lines[i].split()[1:])))
            i += 2
        end = list(map(int, lines[i].split()[1:]))
        i += 1
        clocks.append((k, ops, end))
    return head, lines, clocks


class QueueVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.fitted()

    def _qvec(self, family, part):
        s = normalize(_run(family, part))
        text, cycles = rtl_vectors.queue_vectors(s.chain, self.cfg, s.chain_base)
        return s, text, cycles

    def test_fields_and_ops_are_the_rtls(self):
        """QFIELDS is v35_qstate_t's declaration order and QOPS the V35_QOP_* codes."""
        import re
        sv = QUEUE_SV.read_text()
        body = sv.split("typedef struct packed {", 2)[2].split("} v35_qstate_t;", 1)[0]
        names = re.findall(r"^\s*logic(?:\s*\[[^\]]*\])?\s+(\w+);", body, re.M)
        self.assertEqual(names, [k for k, _ in rtl_vectors.QFIELDS])
        self.assertIn(f"parameter int STATE_W = {rtl_vectors.QSTATE_W}", sv)
        self.assertIn(f"parameter int NSLOT = {rtl_vectors.NSLOT}", sv)
        codes = dict((n.lower(), int(v)) for n, v in
                     re.findall(r"localparam logic \[5:0\] V35_QOP_(\w+) = 6'd(\d+);", sv))
        self.assertEqual(codes, {n: i for i, n in enumerate(rtl_vectors.QOPS)})
        snap = sv.split("typedef struct packed {", 1)[1].split("} v35_qsnap_t;", 1)[0]
        bits = re.findall(r"^\s*logic\s+(\w+);", snap, re.M)
        self.assertEqual(bits[::-1], list(rtl_vectors.DSNAP))       # declared MSB first

    def test_ops_follow_the_bus(self):
        """Every fetch the model starts is an issue op on its clock (a slot fetch's included),
        every aborted cycle an abort op, every delivery phase C's, and no clock overflows the
        RTL's op chain."""
        s, text, cycles = self._qvec("F9", "F9-push-empty-pE-w0")
        head, lines, clocks = _parse_qvec(text)
        self.assertEqual(head[0], rtl_vectors.QFORMAT)
        self.assertEqual(int(head[3]), rtl_vectors.NSLOT)
        issue, take, irload = (rtl_vectors.QOPS.index(n) for n in ("issue", "take", "irload"))
        issues = [k[0] for k, ops, _ in clocks if any(o[0] == issue for o in ops)]
        self.assertEqual(issues, [c.start for c in cycles if c.kind == "fetch"])
        dones = [k[0] for k, _, _ in clocks if k[1]]
        ends = sorted(c.end + 1 for c in cycles)
        self.assertEqual(dones, [t for t in ends if t < len(clocks)])
        self.assertTrue(all(len(ops) <= rtl_vectors.NSLOT for _, ops, _ in clocks))
        # the bytes the decoder takes are the chain's, in order from the tail's first
        got = [o[5] for _, ops, _ in clocks for o in ops if o[0] in (take, irload)]
        m = rtl_vectors.run_queue_model(s.chain, self.cfg, s.chain_base)[0]
        code = bytes(m.queue.code)
        self.assertEqual(bytes(got), code[:len(got)])

    def test_state_reaches_its_edges(self):
        """Inside a clock the queue may hold eight bytes (a word delivered into six stored ones,
        taken from on that clock: F13 C under the thirty-sixth fit), never more than seven at
        a clock's end; an F23
        transfer flushes it. qstate raises on a field that does not fit its width."""
        s, text, _ = self._qvec("F13", "F13-c-out-shlcl16-pO-w0")
        head, lines, clocks = _parse_qvec(text)
        counts = [int(ln.split()[1]) for ln in lines if ln.startswith("S ")]
        # (the thirty-seventh fit: this run peaks at 7; no run of the corpus reaches 8 inside
        # a clock any more, the RTL keeps the eight entries)
        self.assertIn(max(counts), (7, 8))
        self.assertLessEqual(max(end[0] for _, _, end in clocks), 7)
        flush = rtl_vectors.QOPS.index("flush")
        _, text, _ = self._qvec("F23", "F23-push-br-n1-pO-w0")
        self.assertTrue(any(o[0] == flush for _, ops, _ in _parse_qvec(text)[2] for o in ops))


    def test_grp_disp_clock(self):
        """(WP61) grp_disp=hold: a group RMW form's d16 take sets gdisp_until = t + rmw's
        grp_free (the gdisp op, once per such form); the state counts it down to 0 and
        keeps it set (the arbiter reads t < gdisp_until as state)."""
        s, text, _ = self._qvec("F29", "F29-out-ec-gih-incd16-n0-pE-w0")
        head, lines, clocks = _parse_qvec(text)
        g = rtl_vectors.QOPS.index("gdisp")
        ops = [(k[0], o) for k, ops, _ in clocks for o in ops if o[0] == g]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0][1][3], self.cfg.c("rmw", "grp_free"))
        names = [n for n, _ in rtl_vectors.QFIELDS]
        gv, go = names.index("gd_valid"), names.index("gd_off")
        t0 = ops[0][0]
        ends = {k[0]: end for k, _, end in clocks}
        self.assertEqual((ends[t0][gv], ends[t0][go]), (1, self.cfg.c("rmw", "grp_free")))
        self.assertEqual((ends[t0 + 5][gv], ends[t0 + 5][go]), (1, 0))
        self.assertEqual(ends[t0 - 1][gv], 0)


@unittest.skipUnless(rtl_vectors.QBENCH.exists(), "bench not built: fpga/v35s/build_queue_tb.sh")
class QueueBench(unittest.TestCase):
    def test_sample_runs_exact(self):
        cfg = Config.fitted()
        for family, part in QSAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_queue_run(rec, cfg)
                self.assertEqual(r.error, "")
                self.assertTrue(r.ok, r.first)
                self.assertGreater(r.ops, r.clocks)

    def test_joint_runs_exact(self):
        """The RTL queue and bus unit together: the fetches the queue's, the cycles the model's."""
        cfg = Config.fitted()
        for family, part in QSAMPLE[:5]:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_queue_run(rec, cfg, joint=True)
                self.assertEqual(r.error, "")
                self.assertTrue(r.ok, f"{r.first} cycles {r.exact_cycles}/{r.cycles}")
                self.assertEqual(r.rtl_cycles, r.cycles)

    def _bench(self, lines):
        import subprocess
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.qvec"
            path.write_text("\n".join(lines) + "\n")
            return subprocess.run([str(rtl_vectors.QBENCH), str(path)], capture_output=True,
                                  text=True)

    def test_bench_catches_mutations(self):
        """A ModR/M take without its commit (the op's argument flipped) leaves the byte
        uncommitted in the RTL: the state after it differs; a wrong expected read fails."""
        s = normalize(_run("F2", None))
        text, _ = rtl_vectors.queue_vectors(s.chain, Config.fitted(), s.chain_base)
        lines = text.splitlines()
        take = rtl_vectors.QOPS.index("take")
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith(f"O {take} 1 "))          # a take with its ModR/M commit
        bad = lines[:]
        f = bad[i].split()
        f[2] = "0"
        bad[i] = " ".join(f)
        p = self._bench(bad)
        self.assertEqual(p.returncode, 1)
        self.assertRegex(p.stdout, r"FAIL clock \d+ op \d+ \(code 1\) unc model=")
        want = rtl_vectors.QOPS.index("want")
        j = next(k for k, ln in enumerate(lines) if ln.startswith(f"O {want} "))
        bad = lines[:]
        f = bad[j].split()
        f[6] = str(1 - int(f[6]))
        bad[j] = " ".join(f)
        p = self._bench(bad)
        self.assertEqual(p.returncode, 1)
        self.assertRegex(p.stdout, rf"FAIL clock \d+ op \d+ \(code {want}\) rd")
        p = self._bench(lines)
        self.assertEqual(p.returncode, 0, p.stdout[-500:])


# C3 ------------------------------------------------------------------------------------------

EU_SV = rtl_vectors.ROOT / "fpga" / "v35s" / "core" / "v35_eu.sv"
DEC_SV = rtl_vectors.ROOT / "fpga" / "v35s" / "core" / "v35_decoder.sv"

# the gate's families, with the runs that reach the EU's edges (rtl_vectors' C3 recorder):
# a port relatch (the inserted slot), the count-latch shift, abort_reg's early exec, the
# deferred take sync, a request behind a detached OUT, nop_hold, the abort's take sync
ESAMPLE = (("F1", "F1-out-m1-pE-w0"), ("F2", None), ("F3", None), ("F9", None), ("F11", None),
           ("F12", "F12-a-out-n0-none-pE-w0"), ("F12", "F12-b-none-n2-shli-pO-w1"),
           ("F12", "F12-a-out-n2-shl1-pO-w0"), ("F12", "F12-b-none-n2-addiaw-pE-w0"),
           ("F12", "F12-a-out-n0-movr-pO-w1"), ("F20", "F20-r-push-l0-none-outimm-pO-w0"),
           ("F20", "F20-n-push-d1-nop-outdw-pO-w0"), ("F20", "F20-r-none-n1-pfxnop-ld-pO-w0"))


def _sv_fields(text, name):
    body = text.split(f"}} {name};", 1)[0].rsplit("typedef struct packed {", 1)[1]
    return re.findall(r"^\s*(?:logic|v35_\w+)(?:\s*\[[^\]]*\])*\s+(\w+);", body, re.M)


class EUVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.fitted()

    def test_fields_and_ops_are_the_rtls(self):
        """EFIELDS is v35_st_t's declaration order ({d, e, r[2..0]}), QVIEW and BVIEW the
        views', the op codes the queue's and the arbiter's touches XOPS."""
        sv, dec = EU_SV.read_text(), DEC_SV.read_text()
        d = _sv_fields(dec, "v35_dec_t")
        e = _sv_fields(sv, "v35_eus_t")
        r = _sv_fields(sv, "v35_req_t")
        self.assertEqual(d, [n for n, _ in rtl_vectors.DFIELDS])
        self.assertEqual(e, [n for n, _ in rtl_vectors.EUFIELDS])
        self.assertEqual(r, [n for n, _ in rtl_vectors.RFIELDS])
        self.assertEqual(_sv_fields(sv, "v35_st_t"), ["d", "e", "r"])
        self.assertIn("v35_req_t [2:0]     r;", sv)
        self.assertEqual(_sv_fields(dec, "v35_qview_t"), list(rtl_vectors.QVIEW))
        self.assertEqual(_sv_fields(dec, "v35_bview_t"), [n for n, _ in rtl_vectors.BVIEW])
        self.assertIn(f"parameter int STATE_W = {rtl_vectors.ESTATE_W}", sv)
        self.assertIn(f"parameter int NQ = {rtl_vectors.NQ}", sv)
        self.assertIn(f"parameter int NXOP = {rtl_vectors.NXOP}", sv)
        codes = dict((n.lower(), int(v)) for n, v in
                     re.findall(r"localparam logic \[5:0\] V35_EQ_(\w+) = 6'd(\d+);", sv))
        self.assertTrue(codes)
        for n, v in codes.items():
            self.assertEqual(rtl_vectors.QOPS.index(n), v, n)
        x = dict((n.lower(), int(v)) for n, v in
                 re.findall(r"localparam logic \[2:0\] V35_XOP_(\w+) = 3'd(\d+);", sv))
        self.assertEqual(x, {n: i for i, n in enumerate(rtl_vectors.XOPS) if i})
        w = dict(rtl_vectors.QFIELDS)
        self.assertEqual(sum(w[k] for k in rtl_vectors.QVIEW), 52)
        self.assertEqual(sum(b for _, b in rtl_vectors.BVIEW), 18)

    def test_vectors_reach_the_edges(self):
        """The sample runs reach the EU's edges (a port relatch, the count latch, abort_reg,
        the deferred sync, a queued request, the arbiter's touches), every op of a phase fits
        the RTL's NQ, and the operand records are the instruction starts in order."""
        seen = set()
        for family, part in ESAMPLE[5:]:
            s = normalize(_run(family, part))
            text, cycles, erec = rtl_vectors.eu_vectors(s.chain, self.cfg, s.chain_base)
            self.assertEqual(text.splitlines()[0].split()[0], rtl_vectors.EFORMAT)
            for ck in erec.clocks:
                self.assertLessEqual(len(ck.tl), rtl_vectors.NQ)
                self.assertLessEqual(len(ck.p), rtl_vectors.NQ)
                for st in ck.states.values():
                    for k in ("e_ins", "e_shift_latched", "e_reg_early", "r1_valid", "e_exec_v"):
                        if st[k]:
                            seen.add(k)
                    if st["e_sync"] == 2:
                        seen.add("defer")
                seen.update(x for x, _ in ck.xops)
            eu = erec.m.eu
            self.assertEqual([o.offset - eu.origin for o in erec.opnds],
                             [off for _, off, _ in eu.trace])
        self.assertTrue({"e_ins", "e_shift_latched", "e_reg_early", "r1_valid", "e_exec_v",
                         "defer", "issue", "fetch_start", "free0", "sync_one"} <= seen, seen)

    def test_refresh_on_is_c5s(self):
        s = normalize(_run("F13", "F13-r-"))
        with self.assertRaises(rtl_vectors.NotModelled):
            rtl_vectors.eu_vectors(s.chain, self.cfg, s.chain_base)


@unittest.skipUnless(rtl_vectors.EBENCH.exists(), "bench not built: fpga/v35s/build_eu_tb.sh")
class EUBench(unittest.TestCase):
    def test_sample_runs_exact(self):
        cfg = Config.fitted()
        for family, part in ESAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_eu_run(rec, cfg)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, r.first)
                self.assertGreater(r.ops, r.clocks // 2)
                self.assertEqual(r.rtl_exact, r.model_exact)

    def test_joint3_runs_exact(self):
        """The RTL EU, queue and bus unit together (the arbiter scripted)."""
        cfg = Config.fitted()
        for family, part in ESAMPLE[:7]:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_eu_run(rec, cfg, joint=True)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, f"{r.first} cycles {r.exact_cycles}/{r.cycles}")
                self.assertTrue(r.rtl_model_exact)

    def _bench(self, lines):
        import subprocess
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.evec"
            path.write_text("\n".join(lines) + "\n")
            return subprocess.run([str(rtl_vectors.EBENCH), str(path)], capture_output=True,
                                  text=True)

    def test_bench_catches_mutations(self):
        """The decoder: the queue's available() read as 0 on a take (the RTL decoder takes
        nothing: need and the take's state differ). The EU: an instruction's shift count one
        more (its count loop one iteration longer: resume differs). The vectors as made pass."""
        s = normalize(_run("F12", "F12-b-none-n2-shli-pO-w1"))
        text, _, _ = rtl_vectors.eu_vectors(s.chain, Config.fitted(), s.chain_base)
        lines = text.splitlines()
        p = self._bench(lines)
        self.assertEqual(p.returncode, 0, p.stdout[-500:])
        avail, take = rtl_vectors.QOPS.index("avail"), rtl_vectors.QOPS.index("take")
        i = next(k for k, ln in enumerate(lines[:-1])
                 if ln.startswith(f"O {avail} ") and lines[k + 1].startswith(f"O {take} "))
        bad = lines[:]
        f = bad[i].split()
        f[6] = "0"
        bad[i] = " ".join(f)
        p = self._bench(bad)
        self.assertEqual(p.returncode, 1)
        self.assertRegex(p.stdout, r"FAIL clock \d+ (after T|T/L ops|T ops) ")
        j = next(k for k, ln in enumerate(lines) if ln.startswith("P ")
                 and int(ln.split()[7]) > 0)
        bad = lines[:]
        f = bad[j].split()
        f[7] = str(int(f[7]) + 1)
        bad[j] = " ".join(f)
        p = self._bench(bad)
        self.assertEqual(p.returncode, 1)
        self.assertRegex(p.stdout, r"FAIL clock \d+ \w+(?: \w)? e_(count|res|fmt)")


# C4 ------------------------------------------------------------------------------------------

ARB_SV = rtl_vectors.ROOT / "fpga" / "v35s" / "core" / "v35_arbiter.sv"
CORE_SV = rtl_vectors.ROOT / "fpga" / "v35s" / "core" / "v35_chain_core.sv"

# runs that reach the arbiter's edges (rtl_vectors' C4 recorder): free_hold's held fetch,
# grp_io_hold's, the I/O lead's lift, a request moved into the slot behind a detached OUT, the
# left-out write's slot, the aborted cycle and its take sync, free_idle's not_before, disp_io
CSAMPLE = (("F14", "F14-g-out-pop_bw-k2-pO-w0"), ("F14", "F14-g-out-shl_bw_cl-pO-w0"),
           ("F14", "F14-t-none-cmp_bw_aw-pE-w0"), ("F14", "F14-t-out-test_dir_aw-pO-w0"),
           ("F16", "F16-s-none-cl1-n1-shlcl-pO-w0"), ("F11", "F11-none-n0-addi-pE-w0"),
           ("F10", "F10-push-addawi-outdw-pE-w0"), ("F19", "F19-i-out-l0-stimmd16-k2-pE-w0"),
           ("F12", "F12-a-out-n1-imm-pE-w0"))


class ArbiterVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.fitted()

    def test_fields_and_codes_are_the_rtls(self):
        """ARFIELDS is v35_ast_t's declaration order (q[2..0] of v35_arq_t, then the history),
        the widths the parameters', the touches the EU's XOPS, the queue op codes the
        package's, and the core's view of the queue every QVIEW field."""
        sv, core = ARB_SV.read_text(), CORE_SV.read_text()
        self.assertEqual(_sv_fields(sv, "v35_arq_t"), [n for n, _ in rtl_vectors.ARQFIELDS])
        self.assertEqual(_sv_fields(sv, "v35_ast_t"), ["q", "run", "io_v", "io_age"])
        self.assertIn("v35_arq_t [2:0] q;", sv)
        self.assertEqual([n for n, _ in rtl_vectors.ARFIELDS][-3:], ["run", "io_v", "io_age"])
        self.assertIn(f"parameter int STATE_W = {rtl_vectors.ASTATE_W}", sv)
        self.assertIn(f"parameter int ASTATE_W = {rtl_vectors.ASTATE_W}", core)
        self.assertIn(f"parameter int NXQ = {rtl_vectors.NXQ}", sv)
        self.assertIn(f"parameter int NXQ = {rtl_vectors.NXQ}", core)
        self.assertIn(f"parameter int JSLOT = {rtl_vectors.JSLOT}", core)
        self.assertIn(f"parameter int STATE_W = {rtl_vectors.ESTATE_W}", core)
        self.assertIn(f"parameter int QSTATE_W = {rtl_vectors.QSTATE_W}", core)
        x = dict((n.lower(), int(v)) for n, v in
                 re.findall(r"localparam logic \[2:0\] V35_XOP_(\w+) = 3'd(\d+);", sv))
        self.assertEqual(x, {n: i for i, n in enumerate(rtl_vectors.XOPS) if i})
        used = set(re.findall(r"V35_QOP_(\w+)", sv))
        self.assertTrue(used <= {n.upper() for n in rtl_vectors.QOPS}, used)
        self.assertEqual(used, {"WANT", "ROOM", "TRIPLE", "ISSUE", "ABORT", "REDATE", "IO_HELD_CLR"})
        self.assertEqual(sorted(re.findall(r"^\s*v\.(\w+) = s\.\1;", core, re.M)),
                         sorted(rtl_vectors.QVIEW))

    def test_vectors_reach_the_edges(self):
        """The samples reach the arbiter's rules (its own fields, its touches, its queue ops),
        every clock's X ops fit NXQ, and every store the arbiter makes into a request is one the
        recorder classified (any other raises)."""
        seen = set()
        for family, part in CSAMPLE:
            s = normalize(_run(family, part))
            et, qt, bt, at, cycles, erec, arec = rtl_vectors.core_vectors(s.chain, self.cfg,
                                                                          s.chain_base)
            self.assertEqual(at.splitlines()[0].split()[0], rtl_vectors.AFORMAT)
            self.assertEqual(len(arec.clocks), len(erec.clocks))
            for ac, ck in zip(arec.clocks, erec.clocks):
                for k in ("q0_fh_now", "q0_gh_now", "q0_lift_now", "q0_rs_now", "run", "io_v"):
                    if ac.s_x[k]:
                        seen.add(k)
                if ac.ext:
                    seen.add("ext")
                seen.update(x for x, _ in ck.xops)
                seen.update("q:" + o.code for o in ck.xq)
                self.assertLessEqual(len(ck.xq), rtl_vectors.NXQ)
                if ck.states["l"]["r0_dw_moved"] or ck.states["l"]["r0_moved"]:
                    seen.add("moved")
            seen.update("st:" + k for k in arec.stores)
        want = {"q0_fh_now", "q0_gh_now", "q0_lift_now", "q0_rs_now", "run", "io_v", "ext",
                "issue", "nowrite", "fetch_start", "sync_one", "free0", "not_before", "moved",
                "q:want", "q:room", "q:triple", "q:issue", "q:abort", "q:redate", "q:io_held_clr",
                "st:count", "st:ready_since", "st:lift_t", "st:free_held", "st:grp_held",
                "st:eu_halted"}
        self.assertTrue(want <= seen, want - seen)

    def test_refresh_on_is_c5s(self):
        s = normalize(_run("F13", "F13-r-"))
        with self.assertRaises(rtl_vectors.NotModelled):
            rtl_vectors.core_vectors(s.chain, self.cfg, s.chain_base)

    def test_an_unclassified_store_raises(self):
        """The recorder's classification: a store of the arbiter's it does not know raises."""
        s = normalize(_run("F4", None))
        run = rtl_vectors.run_eu_model(s.chain, self.cfg, s.chain_base, arb=True)
        arec = run[3].arb
        with self.assertRaises(rtl_vectors.NotModelled):
            arec.store("xeu", {1}, 5)
        with self.assertRaises(rtl_vectors.NotModelled):
            arec.store("ready_since", 4, 5)
        with self.assertRaises(rtl_vectors.NotModelled):
            arec.store("setup", 3, 5)


@unittest.skipUnless(rtl_vectors.CBENCH.exists(), "bench not built: fpga/v35s/build_core_tb.sh")
class CoreBench(unittest.TestCase):
    def test_sample_runs_exact(self):
        cfg = Config.fitted()
        for family, part in CSAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_core_run(rec, cfg)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, f"{r.first} cycles {r.exact_cycles}/{r.cycles}")
                self.assertTrue(r.rtl_model_exact)
                self.assertEqual(r.rtl_exact, r.model_exact)
                self.assertLessEqual(r.iter_max, 16)

    def test_bench_catches_mutations(self):
        """Each of the arbiter's mutations (v35_arbiter.sv `mutate`) flips one decision: the
        fetch first or the data (arbiter=b2b), the hold's queue count (hold_q), the disp_io
        extension, a DW form's post clock given back (dw_count=bus); the bench fails each."""
        cfg = Config.fitted()
        for mut, (family, part) in ((1, ("F21", "F21-push-l0-ld-bw-pE-w0")),
                                    (2, ("F21", "F21-push-l0-ld-bw_ix_d8-pE-w0")),
                                    (3, ("F21", "F21-out-l0-ld-bw_ix_d16-pE-w0")),
                                    (4, ("F21", "F21-push-l0-ld-bw-pE-w0"))):
            rec = _run(family, part)
            with self.subTest(mutate=mut):
                r = rtl_vectors.check_core_run(rec, cfg)
                self.assertTrue(r.ok, r.first)
                r = rtl_vectors.check_core_run(rec, cfg, mutate=mut)
                self.assertEqual(r.error, "")
                self.assertFalse(r.ok)
                self.assertRegex(r.first, r"^FAIL clock \d+ ")


if __name__ == "__main__":
    unittest.main()
