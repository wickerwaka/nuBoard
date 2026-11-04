"""(WP82) The model lane's cores: acquire's and replay's --core switch (offline). The chain-model
core's end-to-end test went with that core (S7); the core v2's lane (--core v35) is gated by the
replay of the corpus (replay --core v35 --score)."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from validation.v35s.chains import acquire, replay
from validation.v35s.chains.families import generate


class TestCoreSwitch(unittest.TestCase):
    def test_cores(self):
        self.assertEqual(set(acquire.SIM_CORES), {"ucore", "v35"})
        self.assertEqual(acquire.SIM_CORES["ucore"], (acquire.SIM_BINARY, acquire.SIM_OUTPUT))
        binary, out = acquire.SIM_CORES["v35"]
        if "V35_SIM_BINARY" not in os.environ:
            self.assertEqual(binary.parent.name, "verilator-direct-v35")
        self.assertNotEqual(out, acquire.SIM_OUTPUT)

    def test_acquire_parser(self):
        p = acquire.build_parser()
        a = p.parse_args(["--backend", "sim", "--core", "v35", "--family", "F0"])
        self.assertEqual((a.backend, a.core), ("sim", "v35"))
        self.assertEqual(p.parse_args(["--family", "F0"]).core, "ucore")
        with self.assertRaises(SystemExit):
            acquire.main(["--core", "v35", "--family", "F0", "--socket-fitted"])
        with self.assertRaises(SystemExit):     # (S7) the chain core is retired
            p.parse_args(["--backend", "sim", "--core", "chain", "--family", "F0"])

    def test_replay_parser(self):
        a = replay.build_parser().parse_args(["--core", "v35", "--score", "--family", "F0"])
        self.assertEqual((a.core, a.score), ("v35", True))

    def test_run_file_keeps_cores_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F0-w0.json"
            path.write_text(json.dumps({"backend": "sim", "runs": []}))
            with self.assertRaises(SystemExit):
                acquire.RunFile(path, {"backend": "sim", "core": "v35"})
            acquire.RunFile(path, {"backend": "sim"})         # the ucore's: accepted
            path.write_text(json.dumps({"backend": "sim", "core": "v35", "runs": []}))
            acquire.RunFile(path, {"backend": "sim", "core": "v35"})
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
                          core="v35", log=lambda *a, **k: None)
            data = json.loads((Path(tmp) / "F0-w0.json").read_text())
            self.assertEqual(data["core"], "v35")


if __name__ == "__main__":
    unittest.main()
