"""(WP82) The chain-model core in the model lane: acquire's and replay's --core switch (offline),
and one F0 chain run end to end through the chain-lane binary (fpga/v35s/build_sim.sh direct
chain), its trace normalised and scored against silicon and the frozen model.

The end-to-end test uses build/fpga/v35s/verilator-direct-chain/Vv35s_harness when it exists
and is newer than the sources it is built from; otherwise it builds it when V35S_BUILD_CHAIN=1
is set, and is skipped (with the reason) when it cannot."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from validation.v35s.chains import acquire, replay
from validation.v35s.chains.families import generate

ROOT = acquire.ROOT
CHAIN_SOURCES = ["fpga/v35s/core/" + n for n in (
    "v35_decoder.sv", "v35_eu.sv", "v35_queue.sv", "v35_biu.sv", "v35_arbiter.sv",
    "v35_refresh.sv", "v35_chain_core.sv", "v35_sfr.sv", "v35s_chain_model.sv",
    "v35_chain_params.svh")] + ["fpga/v35s/v35s_harness.sv", "fpga/v35s/v35s_lane.sv",
                                "fpga/v35s/sim_main.cpp", "fpga/v35s/build_sim.sh"]
RUN_ID = "F0-ls-pE-w0"


def _binary_current() -> bool:
    b = acquire.CHAIN_BINARY
    if not b.exists():
        return False
    t = b.stat().st_mtime
    return all((ROOT / s).stat().st_mtime <= t for s in CHAIN_SOURCES)


def _chain_binary() -> str | None:
    """None when the binary is ready, else why the end-to-end test is skipped."""
    if _binary_current():
        return None
    if os.environ.get("V35S_BUILD_CHAIN") != "1":
        return ("the chain-lane binary is missing or older than its sources "
                "(fpga/v35s/build_sim.sh direct chain, or V35S_BUILD_CHAIN=1)")
    p = subprocess.run(["bash", str(ROOT / "fpga/v35s/build_sim.sh"), "direct", "chain"],
                       cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        return f"build_sim.sh direct chain failed: {p.stderr[-400:]}"
    return None


class TestCoreSwitch(unittest.TestCase):
    def test_cores(self):
        self.assertEqual(set(acquire.SIM_CORES), {"ucore", "chain", "v35"})
        self.assertEqual(acquire.SIM_CORES["ucore"], (acquire.SIM_BINARY, acquire.SIM_OUTPUT))
        binary, out = acquire.SIM_CORES["chain"]
        self.assertEqual(binary.parent.name, "verilator-direct-chain")
        self.assertNotEqual(out, acquire.SIM_OUTPUT)

    def test_acquire_parser(self):
        p = acquire.build_parser()
        a = p.parse_args(["--backend", "sim", "--core", "chain", "--family", "F0"])
        self.assertEqual((a.backend, a.core), ("sim", "chain"))
        self.assertEqual(p.parse_args(["--family", "F0"]).core, "ucore")
        with self.assertRaises(SystemExit):
            acquire.main(["--core", "chain", "--family", "F0", "--socket-fitted"])

    def test_replay_parser(self):
        a = replay.build_parser().parse_args(["--core", "chain", "--score", "--family", "F0"])
        self.assertEqual((a.core, a.score), ("chain", True))

    def test_run_file_keeps_cores_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F0-w0.json"
            path.write_text(json.dumps({"backend": "sim", "runs": []}))
            with self.assertRaises(SystemExit):
                acquire.RunFile(path, {"backend": "sim", "core": "chain"})
            acquire.RunFile(path, {"backend": "sim"})         # the ucore's: accepted
            path.write_text(json.dumps({"backend": "sim", "core": "chain", "runs": []}))
            acquire.RunFile(path, {"backend": "sim", "core": "chain"})
            with self.assertRaises(SystemExit):
                acquire.RunFile(path, {"backend": "sim"})

    def test_replay_header_names_the_core(self):
        chains = generate(["F0"], waits=(0,))[:2]

        def fake(chain):
            return {"chain": chain.to_json(), "code_hex": "", "chain_base": 0x10047,
                    "image_sha256": "x", "passed": True, "complete": True,
                    "socket_trace": []}
        with tempfile.TemporaryDirectory() as tmp:
            replay.replay(chains, output_dir=Path(tmp), identity={"binary": "b"}, runner=fake,
                          core="chain", log=lambda *a, **k: None)
            data = json.loads((Path(tmp) / "F0-w0.json").read_text())
            self.assertEqual(data["core"], "chain")


class TestChainLaneEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = _chain_binary()
        if why is not None:
            raise unittest.SkipTest(why)

    def test_one_f0_chain(self):
        chain = next(c for c in generate(["F0"]) if c.id == RUN_ID)
        transport, harness = replay._open_lane("chain")
        try:
            rec = replay.replay_one(chain, harness=harness)
        finally:
            transport.close()
        self.assertTrue(rec["passed"], rec["status"])
        self.assertTrue(rec["complete"])
        self.assertGreater(len(rec["socket_trace"]), 50)
        # the reset exit: the lane's first cycles are the reset refresh, then the reset fetch
        first = rec["socket_trace"][:2]
        self.assertTrue(first[0]["flags"] & acquire.FLAG_REFRESH)
        self.assertEqual(first[1]["address"], 0xFFFF0)
        # scored as a corpus entry: against silicon and the frozen model, the pre window too
        from validation.v35s.chains.normalize import load_runs, normalize
        n = normalize(rec, strict=False)
        self.assertIsNotNone(n.t_fill)
        self.assertTrue(n.pre)              # the POP PSW read found, the pre window built
        run = next(r for r in load_runs("F0", (0,)) if r["chain"]["id"] == RUN_ID)
        out = replay.score_lane_run((run, rec))
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["model_exact"])
        self.assertTrue(out["rtl_model"], out["model_first"])
        self.assertTrue(out["rtl_exact"], out["first"])


if __name__ == "__main__":
    unittest.main()
