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
machine's state after every phase of every clock and the cycles; C5: the refresh controller
(v35_refresh.sv) and the refresh's rules in the arbiter and the EU, on refresh-on runs (--core
only); D1 and D2: the register file, the EA adder and the ALU (v35_eu_pkg) against the functional
reference (funcref.py: nuV30's semantics, checked against the frozen model's timing quantities,
silicon's data and SingleStepTests), in the benches and in the unit bench (v35_rf_tb). The
gates' full runs:
python -m validation.v35s.chains.rtl_vectors --family F0 F0w, --queue --family F0 F2 F9 F11,
--joint --family F0 F2 F9 F11, --eu / --joint3 --family F1 F2 F3 F9 F11 F12 F20, --core
--family F4 F5 F6 F7 F10 F14 F15 F16 F19 F21 F22 F26 F29, --core --family F8 F13 F17 F18,
--regfile and the corpus's --core over every family (35 lists: F0, F0w, F1 .. F33), funcref
--silicon, sst and sst --rtl. (WP75) The fortieth fit's seven mechanisms and (E3) the string
forms are in the RTL; (WP79) the 0F page and the register miscellany (F32, F33) too: no run is
outside it."""

from __future__ import annotations

import re
import unittest

from validation.v35s.chains import rtl_vectors
from validation.v35s.chains.normalize import load_runs, normalize
from validation.v35s.chains.rtlgen import fit_config

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
        cls.cfg = fit_config()

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
        cfg = fit_config()
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
        text, _ = rtl_vectors.vectors(s.chain, fit_config(), s.chain_base)
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
        cls.cfg = fit_config()

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
        cfg = fit_config()
        for family, part in QSAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_queue_run(rec, cfg)
                self.assertEqual(r.error, "")
                self.assertTrue(r.ok, r.first)
                self.assertGreater(r.ops, r.clocks)

    def test_joint_runs_exact(self):
        """The RTL queue and bus unit together: the fetches the queue's, the cycles the model's."""
        cfg = fit_config()
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
        text, _ = rtl_vectors.queue_vectors(s.chain, fit_config(), s.chain_base)
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
        cls.cfg = fit_config()

    def test_fields_and_ops_are_the_rtls(self):
        """EFIELDS is v35_st_t's declaration order ({d, e, f, r[2..0]}), QVIEW and BVIEW the
        views', the op codes the queue's and the arbiter's touches XOPS."""
        sv, dec = EU_SV.read_text(), DEC_SV.read_text()
        d = _sv_fields(dec, "v35_dec_t")
        e = _sv_fields(sv, "v35_eus_t")
        r = _sv_fields(sv, "v35_req_t")
        f = _sv_fields(sv, "v35_rf_t")
        self.assertEqual(f, [n for n, _ in rtl_vectors.FFIELDS])     # (D1) the register file
        self.assertEqual(_sv_fields(sv, "v35_fx_t"),                 # (D2) the context
                         [n for n, _ in rtl_vectors.XFIELDS])
        self.assertEqual(d, [n for n, _ in rtl_vectors.DFIELDS])
        self.assertEqual(e, [n for n, _ in rtl_vectors.EUFIELDS])
        self.assertEqual(r, [n for n, _ in rtl_vectors.RFIELDS])
        self.assertEqual(_sv_fields(sv, "v35_st_t"), ["d", "e", "f", "x", "r"])
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
                 re.findall(r"localparam logic \[3:0\] V35_XOP_(\w+) = 4'd(\d+);", sv))
        self.assertEqual(x, {n: i for i, n in enumerate(rtl_vectors.XOPS) if i})
        self.assertIn(f"localparam int V35_XOP_W = {rtl_vectors.XOP_W};", sv)
        tags = dict((n.lower(), int(v)) for n, v in re.findall(r"CT_(\w+) = 3'd(\d+)", sv))
        self.assertEqual(tags, {(t or "none"): i for i, t in enumerate(rtl_vectors.CLK_TAGS)})
        w = dict(rtl_vectors.QFIELDS)
        self.assertEqual(sum(w[k] for k in rtl_vectors.QVIEW), 52)
        self.assertEqual(sum(b for _, b in rtl_vectors.BVIEW), 20)   # (WP75) fsince 4 bits,
                                                                     # (WP77) run

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

    def test_refresh_on_is_the_cores(self):
        """The scripted-arbiter EU benches run refresh-off chains only (C5: --core)."""
        s = normalize(_run("F13", "F13-r-"))
        with self.assertRaises(rtl_vectors.NotModelled):
            rtl_vectors.eu_vectors(s.chain, self.cfg, s.chain_base)


@unittest.skipUnless(rtl_vectors.EBENCH.exists(), "bench not built: fpga/v35s/build_eu_tb.sh")
class EUBench(unittest.TestCase):
    def test_sample_runs_exact(self):
        cfg = fit_config()
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
        cfg = fit_config()
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
        more in the model's record (D1: the RTL computes the count from CL or the byte, so the
        start's record differs in its count). The vectors as made pass."""
        s = normalize(_run("F12", "F12-b-none-n2-shli-pO-w1"))
        text, _, _ = rtl_vectors.eu_vectors(s.chain, fit_config(), s.chain_base)
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
        self.assertRegex(p.stdout, r"FAIL clock \d+ start \d+ record count ")


# C4 ------------------------------------------------------------------------------------------

ARB_SV = rtl_vectors.ROOT / "fpga" / "v35s" / "core" / "v35_arbiter.sv"
REF_SV = rtl_vectors.ROOT / "fpga" / "v35s" / "core" / "v35_refresh.sv"
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
        cls.cfg = fit_config()

    def test_fields_and_codes_are_the_rtls(self):
        """ARFIELDS is v35_ast_t's declaration order (q[2..0] of v35_arq_t, then the history),
        the widths the parameters', the touches the EU's XOPS, the queue op codes the
        package's, and the core's view of the queue every QVIEW field."""
        sv, core = ARB_SV.read_text(), CORE_SV.read_text()
        self.assertEqual(_sv_fields(sv, "v35_arq_t"), [n for n, _ in rtl_vectors.ARQFIELDS])
        hist = [n for n, _ in rtl_vectors.ARFIELDS[3 * len(rtl_vectors.ARQFIELDS):]]
        self.assertEqual(_sv_fields(sv, "v35_ast_t"), ["q"] + hist)
        self.assertIn("v35_arq_t [2:0] q;", sv)
        self.assertEqual(hist[:3], ["run", "io_v", "io_age"])
        self.assertIn(f"parameter int STATE_W = {rtl_vectors.ASTATE_W}", sv)
        self.assertIn(f"parameter int ASTATE_W = {rtl_vectors.ASTATE_W}", core)
        self.assertIn(f"parameter int NXQ = {rtl_vectors.NXQ}", sv)
        self.assertIn(f"parameter int NXQ = {rtl_vectors.NXQ}", core)
        self.assertIn(f"parameter int JSLOT = {rtl_vectors.JSLOT}", core)
        self.assertIn(f"parameter int STATE_W = {rtl_vectors.ESTATE_W}", core)
        self.assertIn(f"parameter int QSTATE_W = {rtl_vectors.QSTATE_W}", core)
        used = set(re.findall(r"V35_QOP_(\w+)", sv))
        self.assertTrue(used <= {n.upper() for n in rtl_vectors.QOPS}, used)
        self.assertEqual(used, {"WANT", "ROOM", "TRIPLE", "ISSUE", "ABORT", "REDATE", "IO_HELD_CLR",
                                "LOST_EVAL", "LOST_HALT", "LOST_AFTER", "DROP", "BEAT", "T4"})
        self.assertIn(f"parameter int NXOP = {rtl_vectors.NXOP}", sv)
        self.assertIn(f"parameter int NXOP = {rtl_vectors.NXOP}", core)
        # (C5) the refresh controller's state and widths
        rsv = REF_SV.read_text()
        self.assertEqual(_sv_fields(rsv, "v35_rst_t"), [n for n, _ in rtl_vectors.RFFIELDS])
        self.assertIn(f"parameter int STATE_W = {rtl_vectors.RSTATE_W}", rsv)
        self.assertIn(f"parameter int RSTATE_W = {rtl_vectors.RSTATE_W}", core)
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

    def test_refresh_on_is_modelled(self):
        """(C5) a refresh-on run is recorded for the core bench: the controller's state on every
        clock, its counter at clock 0 POP_COUNTER's (the vector header)"""
        from validation.v35s.chains.sim.frozen.refresh import POP_COUNTER
        s = normalize(_run("F13", "F13-r-"))
        et, qt, bt, at, cycles, erec, arec = rtl_vectors.core_vectors(s.chain, self.cfg,
                                                                      s.chain_base)
        head = at.splitlines()[0].split()
        self.assertEqual(head[0], "V35ARB-2")
        self.assertEqual(head[4:], ["1", str(POP_COUNTER[(s.chain.rfm, s.chain.wtc)])])
        self.assertEqual(len(arec.ref.clocks), len(arec.clocks))
        self.assertEqual(sum(1 for x in at.splitlines() if x.startswith("R ")),
                         1 + 2 * len(arec.clocks))

    def test_an_unclassified_store_raises(self):
        """The recorder's classification: a store of the arbiter's it does not know raises."""
        s = normalize(_run("F4", None))
        run = rtl_vectors.run_eu_model(s.chain, self.cfg, s.chain_base, arb=True)
        arec = run[3].arb
        with self.assertRaises(rtl_vectors.NotModelled):
            arec.store("xeu", {1}, 5)
        with self.assertRaises(rtl_vectors.NotModelled):
            arec.store("beat_ext", 2, 5)
        with self.assertRaises(rtl_vectors.NotModelled):
            arec.store("ready_since", 4, 5)
        with self.assertRaises(rtl_vectors.NotModelled):
            arec.store("setup", 3, 5)


# (C5) refresh-on runs reaching the refresh's edges (a search over F8/F13/F17/F18): a beaten
# fetch, a lost request raised again (refresh_lost=start and a count loop's re-raise), the RFM
# store taking effect rfm_delay clocks after its issue, a refresh in a count loop (MULU's
# loop_odd and its exit), beside a posted I/O's lead, in HALT (the deferred status), in a memory
# shift's write setup and by CL's read (refresh_grpcl), refresh_post's beat_ext, the lost request
# in HALT (lost_after), refresh_beat_t4, and pop_refresh=stall in the prelude's POP PSW
# (E3) F24 runs with a string form: an unprefixed MOVBK, a REP MOVBK, REPE CMPBK ending on its
# condition, REPNE CMPM running CW out (the overrun read), REP INM and OUTM, REP STM with CW = 0
F24_STRING = "F24-out-s-movbk-b-k1-pE-w0"
SSAMPLE = (("F24", F24_STRING), ("F24", "F24-out-r-rep-movbk-w-n2-pE-w0"),
           ("F24", "F24-out-t-repe-cmpbk-w-n4-pat-pE-w0"),
           ("F24", "F24-out-r-repne-cmpm-w-n4-pO-w0"), ("F24", "F24-out-r-rep-inm-w-n2-pE-w1"),
           ("F24", "F24-out-r-rep-outm-b-n1-pO-w0"), ("F24", "F24-out-r-rep-stm-w-n0-pE-w0"),
           ("F24", "F24-out-a-rep-movbk-w-n2-ix-pO-w0"), ("F30", "F30-out-str-inm-w-n1-l0-pE-w0"))
# (WP75) the fortieth fit's mechanisms, each on its deciding run: (mutation, family, run,
# what the bench sees first): imm_latch=wait, lea_io=recover, lea_room=ir, prepare_sync=run,
# burst_count=dw, cond_gap=own (the EU's), xfer_abort=word (the arbiter's); the string
# template's element address step, overrun read and compare exit (E3)
MSAMPLE = ((14, "F25", "F25-out-push_imm8-pO-w0"), (15, "F25", "F25-out-ldea-bw-pE-w0"),
           (16, "F25", "F25-push-ldea-bw-pO-w0"), (17, "F25", "F25-push-prepare-pE-w0"),
           (18, "F25", "F25-push-pushr-pO-w0"), (19, "F23", "F23-out-be-n0-pE-w2"),
           (20, "F23", "F23-push-br-n0-pO-w0"), (21, "F24", "F24-out-r-rep-movbk-w-n2-pE-w0"),
           (22, "F24", "F24-out-r-repne-cmpm-w-n4-pO-w0"),
           (23, "F24", "F24-out-t-repe-cmpbk-w-n4-pat-pE-w0"))
# (WP77) the forty-first fit's nine mechanisms, each turned off by its mutation, on its deciding
# run (docs/v35s-chains.md "The forty-first fit"): xfer_odd=idle (24, the start's queue op),
# str_exit=wb (25), str_split=floor (26), str_io_setup=run (27), str_start=skip (28),
# str_fetch=hold (29: no fetch_release op), sreg_io=hold (30), sreg_store=own (31: the
# request's sreg), lea_disp=split (32)
M41SAMPLE = ((24, "F30", "F30-out-br-short-n0-pad1-pE-w0"),
             (25, "F31", "F31-out-alf-stm-n1-nop-pE-w0"),
             (26, "F30", "F30-out-odd-stm-iy-n1-end-pE-w0"),
             (27, "F30", "F30-out-str-inm-w-n1-l0-pE-w1"),
             (28, "F30", "F30-out-str-stm-w-n1-sep-pO-w0"),
             (29, "F30", "F30-out-str-stm-w-n0-sep-pO-w0"),
             (30, "F30", "F30-out-seg-8e-ds1-aw-n0-pE-w0"),
             (31, "F30", "F30-out-seg-8c-bw-ds1-n0-pO-w0"),
             (32, "F30", "F30-push-lea-bw_d16-k1-pE-w1"))
# (WP77) F33's REPC / REPNC runs with the STC / CLC byte a NOP (the model does not decode them;
# test_sim.ProbeShapes): the exit the carry's, the RTL's from its own data
REPC_SAMPLE = ("F33-out-repc-cmpbk-w-n4-clc-pE-w0", "F33-out-repnc-cmpbk-w-n4-clc-pE-w0",
               "F33-out-repnc-cmpm-w-n4-stc-pE-w0", "F33-out-repc-cmpm-w-n4-clc-pat-pE-w0")
RSAMPLE = (("F8", "F8-push-st_bw-k4-pE-w1"), ("F17", "F17-p-n1-mulu-pE-w1"),
           ("F18", "F18-b-n1-shlmcl-pE-w1"), ("F13", "F13-r-rfm-f2-pE-w0"),
           ("F13", "F13-r-rfm-f2-pE-w2"))


class RefreshVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = fit_config()

    def test_vectors_reach_the_edges(self):
        """The refresh samples reach every refresh rule the gate needs, and every store the frozen
        code makes into the controller, the EU and the requests under refresh is classified (the
        recorders raise on any other)."""
        seen = set()
        for family, part in RSAMPLE:
            s = normalize(_run(family, part))
            et, qt, bt, at, cycles, erec, arec = rtl_vectors.core_vectors(s.chain, self.cfg,
                                                                          s.chain_base)
            rrec = arec.ref
            self.assertIsNotNone(rrec)
            if rrec.applies:
                seen.add("rfm_apply")
                # the store's issue and its effect rfm_delay (3) clocks later
                ref = erec.m.refresh
                self.assertTrue(all(at_ - t0 == self.cfg.rfm_delay for t0, at_, _ in ref.writes))
            prev = None
            for ac, ck, (rt, sr, se) in zip(arec.clocks, erec.clocks, rrec.clocks):
                self.assertEqual(rt, ck.t)
                self.assertLessEqual(len(ck.xops), rtl_vectors.NXOP)
                self.assertLessEqual(len(ck.xq), rtl_vectors.NXQ)
                ops = {o.code for o in ck.tl + ck.xq + ck.p}
                seen |= {"q:" + c for c in ops & {"beat", "drop", "lost_eval", "lost_halt",
                                                  "lost_after", "t4", "reraise", "halt"}}
                xs = dict(ck.xops)
                seen |= {"x:" + x for x in xs if x in ("refresh", "setup", "beat", "halt_defer")}
                l = ck.states["l"]
                if "refresh" in xs:
                    tag = rtl_vectors.CLK_TAGS[l["e_clk_tag"]]
                    if tag in ("loop", "loop_odd", "mexit") and l["e_res"]:
                        seen.add("in_" + tag)
                    if l["e_rmw"]:
                        seen.add("rmw")
                    if l["r0_grpcl"]:
                        seen.add("grpcl")
                    if l["r0_valid"] and l["r0_kind"] in (3, 4) and l["r0_lead"]:
                        seen.add("io_lead")
                    if l["e_halted"]:
                        seen.add("halted")
                if sr["pending"]:
                    seen.add("pending")
                if ac.s_x["early_on"]:
                    seen.add("early")
                if prev is not None and prev["e_pr_cand"] and not ck.states["t"]["e_pr_cand"]:
                    seen.add("pop_refresh")
                prev = ck.states["e"]
        want = {"rfm_apply", "q:beat", "q:drop", "q:lost_eval", "q:lost_halt", "q:lost_after",
                "q:t4", "q:reraise", "q:halt", "x:refresh", "x:setup", "x:beat", "x:halt_defer",
                "in_loop", "in_loop_odd", "in_mexit", "rmw", "grpcl", "io_lead", "halted",
                "pending", "early", "pop_refresh"}
        self.assertTrue(want <= seen, want - seen)

    def test_string_forms_are_modelled(self):
        """(E3) a run with a string form is an ordinary run in every mode: the vectors hold its
        steps (the compare's fetch hold a queue op, the element count in the start's record,
        the walk's), and the frozen model's flat step index is the RTL's k."""
        from validation.v35s.chains.normalize import string_elements
        for family, part in SSAMPLE:
            s = normalize(_run(family, part))
            with self.subTest(run=s.run_id):
                rtl_vectors.vectors(s.chain, self.cfg, s.chain_base)
                rtl_vectors.queue_vectors(s.chain, self.cfg, s.chain_base)
                et, qt, bt, at, cycles, erec, arec = rtl_vectors.core_vectors(
                    s.chain, self.cfg, s.chain_base)
                strs = [o.string for o in erec.opnds if o.string[0]]
                self.assertTrue(strs)
                for (_, n, cond), (_, sr) in zip(strs, sorted(
                        string_elements(s.chain).items())):
                    self.assertEqual((n, cond), (len(sr.elements), int(sr.cond)))
                ops = [o for ck in erec.clocks for o in ck.tl + ck.p]
                # (E3) a compare's fetch hold (chold clocks); (WP77) str_fetch=hold: a REP
                # form's hold from its first element (forever), its release xfetch clocks after
                # the stream (str_held) and, with CW = 0, the aborted start's request (str_raise)
                hold = any(o.code == "str_held" and not o.a and o.val < 4 for o in ops)
                forever = any(o.code == "str_held" and o.a for o in ops)
                raise_ = any(o.code == "str_raise" for o in ops)
                rep = "-rep" in part or "-str-" in part
                self.assertEqual(hold, "cmp" in part)
                self.assertEqual(forever, rep and "-n0-" not in part)
                self.assertEqual(raise_, rep and "-n0-" in part)
                self.assertGreater(max(ck.states["e"]["e_k"] for ck in erec.clocks), 3)
        r = rtl_vectors.check_queue_run(_run("F24", F24_STRING), self.cfg)
        self.assertEqual(r.not_modelled, "")

    def test_an_unclassified_refresh_store_raises(self):
        """A store into the controller from a method that does not make it raises."""
        s = normalize(_run("F13", "F13-r-"))
        run = rtl_vectors.run_eu_model(s.chain, self.cfg, s.chain_base, arb=True)
        ref = run[0].refresh
        with self.assertRaises(rtl_vectors.NotModelled):
            ref.pending = 3
        with self.assertRaises(rtl_vectors.NotModelled):
            ref.on = False


@unittest.skipUnless(rtl_vectors.CBENCH.exists(), "bench not built: fpga/v35s/build_core_tb.sh")
class CoreBench(unittest.TestCase):
    def test_sample_runs_exact(self):
        cfg = fit_config()
        for family, part in CSAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_core_run(rec, cfg)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, f"{r.first} cycles {r.exact_cycles}/{r.cycles}")
                self.assertTrue(r.rtl_model_exact)
                self.assertEqual(r.rtl_exact, r.model_exact)
                self.assertLessEqual(r.iter_max, 16)

    def test_refresh_runs_exact(self):
        """(C5) the refresh samples run exact in the core, the controller checked every clock."""
        cfg = fit_config()
        for family, part in RSAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_core_run(rec, cfg)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, f"{r.first} cycles {r.exact_cycles}/{r.cycles}")
                self.assertTrue(r.rtl_model_exact)
                self.assertEqual(r.rtl_exact, r.model_exact)

    def test_bench_catches_refresh_mutations(self):
        """(C5) the refresh's mutations (v35_arbiter.sv `mutate` 5..7): a refresh started in a
        posted I/O's lead (refresh_lead=closed off), the beaten fetch not going next
        (refresh_after=fetch_next off), dw_view=eu's clock 2 earlier not taken; the bench fails
        each."""
        cfg = fit_config()
        for mut, (family, part) in ((5, ("F13", "F13-s-shlcl7-pO-w0")),
                                    (6, ("F8", "F8-push-st_bw-k4-pE-w1")),
                                    (7, ("F17", "F17-s-n2-out-pE-w0"))):
            rec = _run(family, part)
            with self.subTest(mutate=mut):
                self.assertTrue(rtl_vectors.check_core_run(rec, cfg).ok)
                r = rtl_vectors.check_core_run(rec, cfg, mutate=mut)
                self.assertEqual(r.error, "")
                self.assertFalse(r.ok)
                self.assertRegex(r.first, r"^FAIL clock \d+ ")

    def test_bench_catches_mutations(self):
        """Each of the arbiter's mutations (v35_arbiter.sv `mutate`) flips one decision: the
        fetch first or the data (arbiter=b2b), the hold's queue count (hold_q), the disp_io
        extension, a DW form's post clock given back (dw_count=bus); the bench fails each."""
        cfg = fit_config()
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

    def test_string_runs_exact(self):
        """(E3) the string samples run exact in the core: the element loop, the addresses from
        IX / IY by the element, the compare's exit from the data, the elements checked against
        the walk's at the next start."""
        cfg = fit_config()
        for family, part in SSAMPLE:
            rec = _run(family, part)
            with self.subTest(run=rec["chain"]["id"]):
                r = rtl_vectors.check_core_run(rec, cfg)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, f"{r.first} cycles {r.exact_cycles}/{r.cycles}")
                self.assertTrue(r.rtl_model_exact)
                self.assertEqual(r.rtl_exact, r.model_exact)

    def test_bench_catches_fit40_and_string_mutations(self):
        """(WP75) each of the fortieth fit's seven mechanisms turned off (mutations 14 .. 20) and
        each string template mutation (21: an element's address step 0, 22: no overrun read,
        23: the compare's condition ignored) fails its deciding run, which runs exact without."""
        cfg = fit_config()
        for mut, family, part in MSAMPLE:
            rec = _run(family, part)
            with self.subTest(mutate=mut):
                self.assertTrue(rtl_vectors.check_core_run(rec, cfg).ok)
                r = rtl_vectors.check_core_run(rec, cfg, mutate=mut)
                self.assertEqual(r.error, "")
                self.assertFalse(r.ok)
                self.assertRegex(r.first, r"^FAIL clock \d+ ")

    def test_bench_catches_fit41_mutations(self):
        """(WP77) each of the forty-first fit's nine mechanisms turned off (mutations 24 .. 32)
        fails its deciding run, which runs exact (and silicon-exact) without."""
        cfg = fit_config()
        for mut, family, part in M41SAMPLE:
            rec = _run(family, part)
            with self.subTest(mutate=mut, run=part):
                r = rtl_vectors.check_core_run(rec, cfg)
                self.assertTrue(r.ok, r.first)
                self.assertTrue(r.rtl_exact)
                r = rtl_vectors.check_core_run(rec, cfg, mutate=mut)
                self.assertEqual(r.error, "")
                self.assertFalse(r.ok)
                self.assertRegex(r.first, r"^FAIL clock \d+ ")

    def test_repc_repnc(self):
        """(WP77) REPC (65) and REPNC (64) decode as REP prefixes and the RTL ends the compare
        on the carry: F33's REPC / REPNC runs (STC / CLC as a NOP) run exact against the frozen
        model, whose element counts are the walk's (the carry's), checked at the next start."""
        import dataclasses
        cfg = fit_config()
        nop = bytes([0x90])
        caught = 0
        for cid in REPC_SAMPLE:
            rec = _run("F33", cid)
            s = normalize(rec)
            ch = dataclasses.replace(s.chain, instrs=[
                dataclasses.replace(i, code=nop, form="nop") if i.form in ("stc", "clc") else i
                for i in s.chain.instrs])
            with self.subTest(run=cid):
                r = rtl_vectors.check_core_run(rec, cfg, chain=ch)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, r.first)
                caught += not rtl_vectors.check_core_run(rec, cfg, mutate=23, chain=ch).ok
        self.assertEqual(caught, 3)     # the exit's condition ignored: all but REPNC CMPBK,
                                        # which runs CW out

    def test_page_and_miscellany_runs_exact(self):
        """(WP79) F32 / F33 forms of every new template shape run exact against the frozen model
        through the core: a register bit op (CL index), a memory bit op (page_grp=group), a digit
        rotate on memory, a BCD string of 4 byte pairs (the compact loop) behind the DS1 prefix,
        the bit fields (EXT crossing, INS crossing at k = 2: the stepped offset register and IY),
        a one-byte form with nx0 (ADJBA), CVTDB, MUL imm memory; silicon-exact where the model
        is."""
        cfg = fit_config()
        for family, part in PSAMPLE:
            rec = _run(family, part)
            with self.subTest(run=part):
                r = rtl_vectors.check_core_run(rec, cfg)
                self.assertEqual((r.error, r.not_modelled), ("", ""))
                self.assertTrue(r.ok, r.first)
                self.assertEqual(r.rtl_exact, r.model_exact)

    def test_bench_catches_page_and_miscellany_mutations(self):
        """(WP79) each new mechanism or function broken (v35_eu.sv `mutate` 33 .. 38: a BCD
        pair's address step 0, bf_count=dw off, a bit op's index off by one, a BCD pair's carry
        dropped, a bit field's offset step without its + 1, the 0F page's second byte not
        skipped at the ModR/M latch) fails its run, which runs exact without."""
        cfg = fit_config()
        for mut, family, part in PMUT:
            rec = _run(family, part)
            with self.subTest(mutate=mut, run=part):
                self.assertTrue(rtl_vectors.check_core_run(rec, cfg).ok)
                r = rtl_vectors.check_core_run(rec, cfg, mutate=mut)
                self.assertEqual(r.error, "")
                self.assertFalse(r.ok)
                self.assertRegex(r.first, r"^FAIL clock \d+ ")

    def test_bench_catches_register_file_mutations(self):
        """(D1, D2) the register file's and the ALU's mutations (v35_eu.sv `mutate` 8..12):
        [BW+IX] computed without IX (an EA mode: the record), a push's SP step of 4 (the next
        start's register file, or the record's stack offset), MOV r8,imm8 written to the other
        half of its word (CL into CH: the shift's count, so its template, or the next start's
        register file), ADD's AC inverted (the
        next start's PSW), a memory write's datum with bit 0 flipped (the cycle's datum); the
        bench fails each. (13, the BP-based modes in DS0, is the unit bench's: the corpus runs
        with SS = DS0 = 0.)"""
        cfg = fit_config()
        for mut, (family, part), what in (
                (8, ("F21", "F21-out-l0-ld-bw_ix_d16-pE-w0"), r"(after \w+ e_ea|start \d+ record ea)"),
                (9, ("F21", "F21-push-l0-ld-bw-pE-w0"),
                 r"(start \d+ registers sp|start \d+ record s[rw]|after \w+ e_s[rw])"),
                (10, ("F16", "F16-s-none-cl1-n1-shlcl-pO-w0"),
                 r"(start \d+ registers cw|start \d+ record count|after \w+ e_(tmpl|count))"),
                (11, ("F14", "F14-t-push-add_bw_aw-pE-w0"), r"start \d+ registers psw"),
                (12, ("F14", "F14-t-push-add_bw_aw-pE-w0"), r"data cycle datum")):
            rec = _run(family, part)
            with self.subTest(mutate=mut):
                self.assertTrue(rtl_vectors.check_core_run(rec, cfg).ok)
                r = rtl_vectors.check_core_run(rec, cfg, mutate=mut)
                self.assertEqual(r.error, "")
                self.assertFalse(r.ok)
                self.assertRegex(r.first, rf"^FAIL clock \d+ {what} ")


# D1, D2 --------------------------------------------------------------------------------------

# (WP79) F32 / F33 runs of each new template shape, and each WP79 mutation's run
PSAMPLE = (("F32", "F32-out-set1_rb_cl-k1-pE-w0"), ("F32", "F32-out-set1_mb_cl-k1-pE-w0"),
           ("F32", "F32-out-rol4_m-k1-pE-w0"), ("F32", "F32-out-pfx_add4s-n4-k1-pE-w0"),
           ("F32", "F32-out-ext_dl_bh-k1-pE-w0"), ("F32", "F32-out-ins_dl_dh-k2-pE-w0"),
           ("F33", "F33-out-adjba-k1-pE-w0"), ("F33", "F33-out-cvtdb-k1-pE-w0"),
           ("F33", "F33-out-mul_aw_m_imm8-k1-pE-w0"))
PMUT = ((33, "F32", "F32-out-add4s-n4-k1-pE-w0"), (34, "F32", "F32-out-ext_bl_dh-k1-pO-w0"),
        (35, "F32", "F32-out-set1_rb_cl-k1-pE-w0"), (36, "F32", "F32-out-add4s-n4-k1-pE-w0"),
        (37, "F32", "F32-out-ins_dl_dh-k2-pE-w0"), (38, "F32", "F32-out-set1_mb_cl-k1-pE-w0"))

# (WP75) the lists of the whole corpus: F0, F0w, F1 .. F31 (F30 and F31 the probe families);
# (WP79) and F32, F33: 35 lists, 28,142 runs
ALL_FAMILIES = ("F0", "F0w") + tuple(f"F{i}" for i in range(1, 34))


class FunctionalReference(unittest.TestCase):
    """(D2) funcref.py: nuV30's semantics against the frozen model's timing quantities, silicon's
    data and the ALU's laws."""

    def test_agrees_with_the_frozen_execute_over_the_corpus(self):
        """Every instruction start of the whole corpus (every family, the prelude's tail first,
        the string forms included): the quantities the timing depends on (the memory operand's
        address, the port, the stack offsets, the shift count, a transfer's decision and target,
        a string form's start registers, element count and exit) are the frozen model's; and
        every data cycle's datum (a write's, a read's delivered word, on the cycle's lanes) is
        silicon's."""
        from validation.v35s.chains import funcref
        tot = funcref.agree_corpus(ALL_FAMILIES, silicon=True)
        self.assertGreater(tot["runs"], 28000)
        self.assertGreater(tot["starts"], 700000)
        self.assertEqual((tot["bad"], tot["nm"], tot["trap"]), (0, 0, 0), tot["first"])
        self.assertGreater(tot["scyc"], 90000)
        self.assertEqual(tot["seq"], tot["scyc"], tot["first"])
        self.assertEqual(tot["sbad"], 0, tot["first"])

    def test_model_starts_are_the_references(self):
        """The model's starts (the recorder's records) are the reference's, in order, with
        its register file before each (the P lines), and the EU's cycles are its cycles."""
        from validation.v35s.chains import funcref
        cfg = fit_config()
        for family, part in (("F23", None), ("F25", "pushr_popr-pO"), ("F25", "prepare_dispose"),
                             ("F25", "push_ds0_pop_ds0")):
            s = normalize(_run(family, part))
            _, cycles, erec = rtl_vectors.eu_vectors(s.chain, cfg, s.chain_base)
            run = funcref.chain_run(s.chain, s.chain_base)
            self.assertEqual([o.offset for o in erec.opnds], [st.pc for st in run.starts])
            self.assertEqual([o.rf for o in erec.opnds],
                             [rtl_vectors.rf_of(st.regs) for st in run.starts])
            eu = [c for c in cycles if c.owner is erec.m.eu]
            self.assertEqual([(c.kind, c.addr, c.width, c.data) for c in eu],
                             [(c.kind, c.addr, c.width, c.data) for c in run.cycles])

    def test_alu_laws(self):
        """A few of nuV30's results by hand: ADD's carries and overflow, SUB's borrow, the
        logic forms clearing CY V AC, INC keeping CY, ROLC through the carry, SHL's V, SHR by
        more than the width, MULU leaving S Z AC P, MUL's S Z AC P of the low half's self-add,
        DIVU's pre-check flags and trap, DIV's symmetric range trap."""
        from validation.v35s.chains import funcref as fr
        r, f = fr.alu(0, 0x7FFF, 1, 2, 0xF002)
        self.assertEqual((r, f & fr.ARITH), (0x8000, (1 << fr.V) | (1 << fr.S) | (1 << fr.AC)
                                              | (1 << fr.P)))
        r, f = fr.alu(5, 0, 1, 1, 0)
        self.assertEqual(r, 0xFF)
        self.assertTrue(f & (1 << fr.CY) and f & (1 << fr.S) and f & (1 << fr.AC))
        _, f = fr.alu(4, 0xFF, 0x0F, 1, 0xFFFF)
        self.assertEqual(f & ((1 << fr.CY) | (1 << fr.V) | (1 << fr.AC)), 0)
        _, f = fr.incdec(False, 0xFFFF, 2, 1 << fr.CY)
        self.assertTrue(f & (1 << fr.CY) and f & (1 << fr.Z))
        r, f = fr.shift(2, 0x80, 1, 1, 0)                       # ROLC 80h: CY 1, AL 0
        self.assertEqual((r, f & 1), (0x00, 1))
        r, f = fr.shift(4, 0x4000, 1, 2, 0)                     # SHL: V = MSB ^ CY
        self.assertTrue(f & (1 << fr.V))
        r, f = fr.shift(5, 0xFFFF, 17, 2, 0)
        self.assertEqual((r, f & 1), (0, 0))
        p, f = fr.mul(False, 0xFF, 0xFF, 1, 0x00D5)
        self.assertEqual((p, f & 0x00D4, f & 0x0801), (0xFE01, 0x00D4, 0x0801))
        p, f = fr.mul(True, 0x80, 0x7F, 1, 0)                   # C080h: lo 80h: Z 1, S 0
        self.assertEqual(p, 0xC080)
        self.assertTrue(f & (1 << fr.Z) and not f & (1 << fr.S))
        q, rem, f, trap = fr.div(False, 0x0100, 0x01, 1, 0)    # AH 1 >= 1: the trap
        self.assertTrue(trap)
        q, rem, f, trap = fr.div(False, 0x1234, 0x56, 1, 0)
        self.assertEqual((q, rem, trap), (0x1234 // 0x56, 0x1234 % 0x56, False))
        self.assertTrue(f & (1 << fr.CY))                       # SUB(12h, 56h) borrows
        self.assertTrue(fr.div(True, 0x3C15, 0x88, 1, 0)[3])   # quotient -128 traps
        for cc in range(16):
            self.assertNotEqual(fr.cond(cc, 0), fr.cond(cc ^ 1, 0))


@unittest.skipUnless((rtl_vectors.ROOT / "build" / "deps" / "sst-v20" / "v1_native" / "00.json.gz")
                     .exists(), "SingleStepTests not fetched: tools/fetch_sst_v20.py")
class SingleStepTests(unittest.TestCase):
    """(D2) the V20 suite: the reference (and, built, the unit bench) on a sample of files."""
    FILES = ("01", "2B", "81.3", "C1.2", "D3.7", "F7.6", "F7.7", "F6.5", "8F", "61", "C3", "7C",
             # (WP79) the 0F page and the register miscellany
             "0F15", "0F1A", "0F20", "0F22", "0F26", "0F33", "0F39", "27", "3F", "D4", "D5", "6B")

    def test_reference_passes(self):
        from validation.v35s.chains import sst
        res = sst.check_funcref(self.FILES, show=0)
        for stem, counts in res.items():
            self.assertEqual(counts.get("fail", 0), 0, (stem, counts))
            self.assertGreater(counts.get("pass", 0), 1900, (stem, counts))

    @unittest.skipUnless(rtl_vectors.RFBENCH.exists(), "bench not built: fpga/v35s/build_rf_tb.sh")
    def test_rtl_passes(self):
        res = rtl_vectors.check_sst(self.FILES, show=0)
        for stem, counts in res.items():
            self.assertFalse([k for k in counts if k.startswith("rtl fail")], (stem, counts))
            self.assertGreater(counts.get("pass", 0), 1900, (stem, counts))


@unittest.skipUnless(rtl_vectors.RFBENCH.exists(), "bench not built: fpga/v35s/build_rf_tb.sh")
class RegfileBench(unittest.TestCase):
    def test_every_form_against_the_reference(self):
        """eu_decode, v35_operands, v35_execute, v35_deliver and v35_wdata against the
        functional reference on every instruction start of the corpus's chains, every encoding
        on random register files and memory, the 24 ModR/M memory modes on the
        address-computing forms and random operands on every ALU form."""
        bad, counts, out = rtl_vectors.check_regfile(ALL_FAMILIES)
        self.assertEqual(bad, 0, out[-1500:])
        self.assertGreater(counts["walk"], 1000)
        self.assertGreater(counts["modes"], 24 * 8)
        self.assertGreater(counts["alu"], 3000)

    def test_mutations_are_caught(self):
        """The unit bench fails each register-file and ALU mutation: an EA mode (8), a push's SP
        step (9), MOV r8,imm8's byte (10), ADD's AC (11), a write's datum (12), the BP-based
        modes' segment (13: random segments)."""
        for mut, field in ((8, "ea"), (9, "sp"), (10, ""), (11, "psw"), (12, "write datum"),
                           (13, "ea")):
            with self.subTest(mutate=mut):
                bad, _, out = rtl_vectors.check_regfile(("F21",), mutate=mut)
                self.assertGreater(bad, 0)
                self.assertRegex(out, rf"FAIL vector \d+ code \w+ {field}")


if __name__ == "__main__":
    unittest.main()
