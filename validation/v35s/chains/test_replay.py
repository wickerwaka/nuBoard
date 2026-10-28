"""Offline tests of replay.py and score --rtl: identity header, resume, the three-way table
and summary, the state-row comparison. No board, no Verilator."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from validation.v35s.chains import replay, score
from validation.v35s.chains.families import generate
from validation.v35s.chains.image import build_image
from validation.v35s.chains.score import Score, ThreeWay


IDENTITY = {"binary": "build/fpga/v35s/verilator-direct/Vv35s_harness",
            "binary_mtime": 1760289220.396, "binary_mtime_iso": "2026-10-12T10:13:40-07:00",
            "fpga_commit": "d39b108b" * 5, "fpga_tree": "e3f4cbff" * 5,
            "fpga_dirty": False, "sources_newer": []}


def chain_of(cid, waits=0, parity="even", family="F0"):
    return SimpleNamespace(id=cid, family=family, waits=waits, parity=parity)


def fake_record(chain, tag="a"):
    return {"chain": chain.to_json(), "code_hex": "", "chain_base": 0x10047,
            "image_sha256": "sha-" + chain.id, "status": 2, "passed": True, "complete": True,
            "timeout": False, "overflow": False, "socket_result": 1, "elapsed_ticks": 1,
            "socket_trace": [{"tag": tag}], "repeat_trace": None, "repeat_identical": None,
            "repeat_shift": None, "replay_seconds": 0.01}


class TestReplayDriver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.chains = generate(["F0"], waits=(0, 1))

    def tearDown(self):
        self.tmp.cleanup()

    def test_header_identity_and_record_key(self):
        stats = replay.replay(self.chains, output_dir=self.dir, identity=IDENTITY,
                              runner=fake_record, log=lambda *a, **k: None)
        self.assertEqual(stats["runs"], len(self.chains))
        data = json.loads((self.dir / "F0-w0.json").read_text())
        self.assertEqual(data["backend"], "sim")
        self.assertEqual(data["rtl"], IDENTITY)
        for key in ("binary", "binary_mtime", "fpga_commit", "fpga_tree", "fpga_dirty"):
            self.assertIn(key, data["rtl"])
        key = replay.rtl_key(IDENTITY)
        self.assertTrue(key.startswith("1760289220.396:e3f4cbffe3f4"))
        self.assertTrue(all(r["rtl_key"] == key for r in data["runs"]))
        self.assertEqual([r["chain"]["id"] for r in data["runs"]],
                         [c.id for c in self.chains if c.waits == 0])
        self.assertTrue((self.dir / "F0-w1.json").exists())

    def test_resume_skips_same_build_only(self):
        quiet = lambda *a, **k: None
        replay.replay(self.chains, output_dir=self.dir, identity=IDENTITY, runner=fake_record,
                      log=quiet)
        stats = replay.replay(self.chains, output_dir=self.dir, identity=IDENTITY,
                              runner=fake_record, resume=True, log=quiet)
        self.assertEqual((stats["runs"], stats["skipped"]), (0, len(self.chains)))
        newer = {**IDENTITY, "binary_mtime": IDENTITY["binary_mtime"] + 60}
        stats = replay.replay(self.chains, output_dir=self.dir, identity=newer,
                              runner=lambda c: fake_record(c, "b"), resume=True, log=quiet)
        self.assertEqual(stats["runs"], len(self.chains))
        data = json.loads((self.dir / "F0-w0.json").read_text())
        self.assertEqual(data["rtl"]["binary_mtime"], newer["binary_mtime"])
        self.assertTrue(all(r["socket_trace"] == [{"tag": "b"}] for r in data["runs"]))

    def test_rtl_identity_fields(self):
        binary = self.dir / "Vfake"
        binary.write_bytes(b"")
        os.utime(binary, (1.0, 1.0))           # older than every source: a stale build
        ident = replay.rtl_identity(binary)
        self.assertEqual(ident["binary_mtime"], 1.0)
        self.assertTrue(ident["sources_newer"])
        self.assertIn("fpga/v35s/core/v35s_model.sv", ident["sources_newer"])
        self.assertIn("fpga_tree", ident)
        self.assertIsNone(replay.rtl_identity(self.dir / "missing")["binary_mtime"])

    def test_load_rtl_runs(self):
        replay.replay(self.chains, output_dir=self.dir, identity=IDENTITY, runner=fake_record,
                      log=lambda *a, **k: None)
        runs, headers = replay.load_rtl_runs("F0", (0, 2), self.dir)
        self.assertEqual(set(runs), {c.id for c in self.chains if c.waits == 0})
        self.assertEqual(len(headers), 1)


def sc(exact, run_id="x"):
    return Score(run_id, exact, 5, 5, 5 if exact else 1, None if exact else (1, None, None))


def tw(cid, model, rtl, rm, waits=0, parity="even", family="F0", status="ok", checks=()):
    """model / rtl / rm: True exact, False miss, None absent."""
    s = SimpleNamespace(chain=chain_of(cid, waits, parity, family), run_id=cid)
    m = object() if model is not None else None
    r = object() if rtl is not None else None
    return ThreeWay(s, m, None if model is None else sc(model), r,
                    None if rtl is None else sc(rtl), None if rm is None else sc(rm),
                    status, list(checks))


class TestThreeWayTables(unittest.TestCase):
    def results(self):
        return [tw("F0-ls-pE-w0", True, True, True),
                tw("F0-ls-pO-w0", True, False, False, parity="odd",
                   checks=["fastest fetch cadence 6 != fetch length {3}"]),
                tw("F0-ls-pE-w1", False, False, True, waits=1),
                tw("F0-ls-pO-w1", True, None, None, waits=1, parity="odd", status="no RTL")]

    def test_marks_and_table(self):
        res = self.results()
        self.assertEqual([score.marks(t) for t in res], ["===", "=xx", "xx=", "=?-"])
        text = score.table3(res)
        self.assertIn("pE-w0", text)
        row = next(line for line in text.splitlines() if line.startswith("ls "))
        self.assertEqual(row.split()[1:], ["===", "xx=", "=xx", "=?-"])

    def test_summary_counts_and_gate(self):
        text = score.summary3(self.results())
        self.assertIn("model-exact 3/4  RTL-exact 1/4  RTL=model 2/4  no RTL 1", text)
        self.assertIn("gate RTL-exact >= model-exact: no (1 vs 3)", text)
        self.assertIn("soft: fastest fetch cadence # != fetch length {#}", text)

    def test_missing_rtl_is_never_exact(self):
        t = tw("F0-ls-pE-w0", True, None, None, status="no RTL")
        self.assertFalse(t.rtl_exact)
        self.assertFalse(t.has_rtl)
        self.assertIn("RTL-exact 0/1", score.summary3([t]))
        self.assertIn("gate RTL-exact >= model-exact: no", score.summary3([t]))

    def test_gate_yes(self):
        text = score.summary3([tw("F0-ls-pE-w0", False, True, False),
                               tw("F0-ls-pO-w0", True, True, True, parity="odd")])
        self.assertIn("gate RTL-exact >= model-exact: yes (2 vs 1)", text)

    def test_unmodelled_family(self):
        res = [tw("F23-push-pE-w0", None, True, None, family="F23"),
               tw("F23-push-pO-w0", None, False, None, family="F23", parity="odd")]
        self.assertEqual([score.marks(t) for t in res], ["-=-", "-x-"])
        text = score.summary3(res, modelled=False)
        self.assertIn("model-exact n/a  RTL-exact 1/2  RTL=model n/a", text)
        self.assertIn("gate (model n/a, RTL-exact alone, every run): no (1/2)", text)
        self.assertIn("yes (1/1)", score.summary3(res[:1], modelled=False))

    def test_check_category(self):
        self.assertEqual(score.check_category(
            "F0-ls-pE-w0: no fetch of the first chain word 10046"),
            "no fetch of the first chain word #")
        self.assertEqual(score.check_category(
            "data/stack/I/O cycles differ from the expected accesses: expected [], observed []"),
            "data/stack/I/O cycles differ from the expected accesses")


class TestThreeWayRecords(unittest.TestCase):
    """three_way on model run records standing in for silicon and RTL (no Verilator)."""

    @classmethod
    def setUpClass(cls):
        from validation.v35s.chains.sim.config import Config
        from validation.v35s.chains.sim.machine import run_record
        cls.cfg = Config.fitted()
        cls.chains = generate(["F0"], waits=(0,))[:3]
        cls.silicon = []
        for chain in cls.chains:
            built = build_image(chain)
            rec = run_record(chain, cls.cfg, built.chain_base)
            rec["image_sha256"] = built.image_sha256
            cls.silicon.append(rec)

    def rtl(self, k, **change):
        return {**json.loads(json.dumps(self.silicon[k])), "rtl_key": "K", **change}

    def test_three_way(self):
        rtl = {self.chains[0].id: self.rtl(0),
               self.chains[1].id: self.rtl(1, image_sha256="other"),
               # the third has no replay
               }
        res = score.three_way(self.silicon, self.cfg, rtl, current_key="K")
        self.assertEqual([t.rtl_status for t in res], ["ok", "image differs", "no RTL"])
        self.assertTrue(res[0].model_exact and res[0].rtl_exact and res[0].rtl_model_exact)
        self.assertFalse(res[1].rtl_exact or res[2].rtl_exact)
        self.assertEqual([score.marks(t) for t in res], ["===", "=?-", "=?-"])
        self.assertIn("no RTL 2", score.summary3(res))
        self.assertIn("first silicon/RTL divergence", score.side_by_side3(res[0]))

    def test_rtl_normalise_error_scores_a_miss(self):
        bad = self.rtl(0, socket_trace=[r for r in self.silicon[0]["socket_trace"]
                                        if r["address"] != self.silicon[0]["chain_base"] & ~1])
        res = score.three_way(self.silicon[:1], self.cfg, {self.chains[0].id: bad})
        self.assertTrue(res[0].rtl_status.startswith("error: no fetch of the first chain word"))
        self.assertEqual(score.marks(res[0]), "=!-")
        self.assertIn("RTL error", score.side_by_side3(res[0]))
        self.assertIn("error: no fetch of the first chain word #", score.summary3(res))

    def test_rtl_shifted_and_stale(self):
        late = self.rtl(0, rtl_key="old")
        last = late["socket_trace"][-1]         # the END write, a clock later
        last["start"] += 8
        last["end"] += 8
        res = score.three_way(self.silicon[:1], self.cfg, {self.chains[0].id: late},
                              current_key="K")
        self.assertTrue(res[0].stale)
        self.assertFalse(res[0].rtl_exact)
        self.assertEqual(score.marks(res[0]), "=xx")
        self.assertIn("warning: 1 RTL runs", score.summary3(res))

    def test_unmodelled_skips_the_model(self):
        res = score.three_way(self.silicon[:1], self.cfg, {self.chains[0].id: self.rtl(0)},
                              model=False)
        self.assertIsNone(res[0].model)
        self.assertEqual(score.marks(res[0]), "-=-")


class TestStateRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = replay.model_state_rows("F0-ls-pE-w0")

    def test_full_log(self):
        ts = [r["t"] for r in self.rows]
        self.assertEqual(ts, list(range(ts[0], ts[0] + len(ts))))    # no clock skipped
        for k in replay.STATE_REQUIRED + replay.STATE_OPTIONAL:
            self.assertIn(k, self.rows[0])

    def test_self_and_round_trip(self):
        self.assertIsNone(replay.compare_state_rows(self.rows, self.rows))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dump.jsonl"
            replay.write_state(path, self.rows, "F0-ls-pE-w0")
            self.assertIsNone(replay.compare_state_rows(self.rows, replay.read_state(path)))
            # an absolute clock count re-based by the header's t0
            lines = path.read_text().splitlines()
            head = {**json.loads(lines[0]), "t0": 1000}
            body = [{**json.loads(x), "t": json.loads(x)["t"] + 1000} for x in lines[1:]]
            path.write_text("\n".join(json.dumps(x) for x in [head] + body) + "\n")
            self.assertIsNone(replay.compare_state_rows(self.rows, replay.read_state(path)))

    def test_perturbed_row(self):
        dump = json.loads(json.dumps(self.rows))
        k = len(dump) // 2
        dump[k]["need"] += 1
        diff = replay.compare_state_rows(self.rows, dump)
        self.assertEqual((diff.t, diff.key), (self.rows[k]["t"], "need"))
        self.assertEqual(diff.rtl, self.rows[k]["need"] + 1)
        dump[k - 1]["room"] += 1
        self.assertEqual(replay.compare_state_rows(self.rows, dump).t, self.rows[k - 1]["t"])

    def test_required_optional_missing_extra(self):
        dump = [{k: v for k, v in r.items() if k not in replay.STATE_OPTIONAL}
                for r in json.loads(json.dumps(self.rows))]
        self.assertIsNone(replay.compare_state_rows(self.rows, dump))
        del dump[3]["flag"]
        diff = replay.compare_state_rows(self.rows, dump)
        self.assertEqual((diff.t, diff.key, diff.rtl), (self.rows[3]["t"], "flag", "<missing>"))
        dump = json.loads(json.dumps(self.rows))
        del dump[5]
        self.assertEqual(replay.compare_state_rows(self.rows, dump).key, "t")
        dump = json.loads(json.dumps(self.rows)) + [{**self.rows[-1], "t": 99999}]
        diff = replay.compare_state_rows(self.rows, dump)
        self.assertEqual((diff.t, diff.key), (99999, "t"))


if __name__ == "__main__":
    unittest.main()
