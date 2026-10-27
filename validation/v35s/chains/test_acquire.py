"""Offline tests of acquire.py: JSON layout, atomic rewrite, resume, filters, repeats."""

import json
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from validation.v35s.chains import acquire


@dataclass
class FakeChain:
    id: str
    family: str
    waits: int
    parity: str
    knobs: dict = field(default_factory=dict)

    def to_json(self):
        return {"id": self.id, "family": self.family, "waits": self.waits,
                "parity": self.parity, "knobs": self.knobs}


@dataclass
class FakeBuilt:
    chain: FakeChain
    image: dict
    code: bytes
    chain_base: int
    image_sha256: str


def fake_build(chain):
    code = chain.id.encode()
    return FakeBuilt(chain, {0x10000: code}, code, 0x10010, "sha-" + chain.id)


class FakeHarness:
    """Duck-typed Harness: the trace depends on the loaded image and the run count."""

    def __init__(self, flaky=(), fail=(), stop_after=None, shifty=()):
        self.loaded = None
        self.calls = []
        self.flaky, self.fail, self.stop_after = set(flaky), set(fail), stop_after
        self.shifty = set(shifty)

    def configure(self, x_half=2, ready_ticks=0):
        assert (x_half, ready_ticks) == (2, 0)

    def load(self, image):
        self.loaded = image[0x10000].decode()

    def run(self, mode="socket", limit=0):
        if self.stop_after is not None and len(self.calls) >= self.stop_after:
            raise KeyboardInterrupt
        name = self.loaded
        self.calls.append((name, mode))
        n = sum(1 for c in self.calls if c[0] == name)
        t0 = 4 * n if name in self.shifty else 0
        trace = [{"start": t0 + 8 * i, "end": t0 + 8 * i + 20, "address": i, "data": 0,
                  "flags": 1, "strobe": 8 if (name in self.flaky and n > 1) else 0}
                 for i in range(len(name))]
        ok = name not in self.fail
        lane = {"model": "model", "socket": "socket"}[mode]
        other = "socket" if lane == "model" else "model"
        return {"status": 0x12 if ok else 0x22, f"{lane}_result": 1 if ok else 2,
                f"{other}_result": 0, "timeout": False, "overflow": False,
                "trace_complete": True, "elapsed_ticks": 100 * len(name),
                f"{lane}_trace": trace, f"{other}_trace": []}


CATALOG = {
    "F0": lambda: [FakeChain(f"F0-{p}-w{w}-{k}", "F0", w, p)
                   for w in (0, 1, 2) for p in ("even", "odd") for k in range(5)],
    "F0w": lambda: [FakeChain(f"F0w-{p}-{k}", "F0w", -1, p) for p in ("even", "odd") for k in range(2)],
}


def go(harness, chains, tmp_path, **kw):
    opts = dict(backend="board", board_state={"link": True}, output_dir=tmp_path,
                resume=False, repeat_fraction=0.1, limit=1000, build=fake_build,
                log=lambda *a, **k: None)
    opts.update(kw)
    return acquire.sweep(harness, chains, **opts)



class AcquireTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_filters(self):
        sel = acquire.select_chains(["F0", "F0w"], waits=[0], parity=["odd"], catalog=CATALOG)
        assert [c.id for c in sel] == [f"F0-odd-w0-{k}" for k in range(5)] + ["F0w-odd-0", "F0w-odd-1"]
        assert len(acquire.select_chains(["F0"], ids=["-3", "w2-0"], catalog=CATALOG)) == 6 + 2
        with self.assertRaises(SystemExit):
            acquire.select_chains(["F9"], catalog=CATALOG)


    def test_files_layout_and_repeats(self):
        tmp_path = self.tmp_path
        chains = acquire.select_chains(["F0", "F0w"], catalog=CATALOG)
        harness = FakeHarness(flaky={"F0-even-w1-0"}, fail={"F0-odd-w2-4"}, shifty={"F0-odd-w1-0"})
        stats = go(harness, chains, tmp_path, repeat_fraction=0.2)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["F0-w0.json", "F0-w1.json",
                                                             "F0-w2.json", "F0w.json"]
        data = json.loads((tmp_path / "F0-w1.json").read_text())
        assert (data["backend"], data["x_half"], data["ticks_per_clock"], data["family"],
                data["waits"]) == ("board", 2, 8, "F0", 1)
        assert [r["chain"]["id"] for r in data["runs"]] == [c.id for c in chains if c.id.startswith("F0-") and "-w1-" in c.id]
        run = data["runs"][0]
        for key in ("chain", "code_hex", "chain_base", "image_sha256", "status", "passed", "complete",
                    "elapsed_ticks", "socket_trace", "repeat_trace", "repeat_identical", "repeat_shift"):
            assert key in run
        # every 5th chain per file repeated: indexes 0 and 5 of 10 in each F0 file, 0 of 4 in F0w
        repeated = {r["chain"]["id"]: (r["repeat_identical"], r["repeat_shift"])
                    for r in data["runs"] if r["repeat_trace"] is not None}
        assert repeated == {"F0-even-w1-0": (False, None), "F0-odd-w1-0": (False, 4)}
        w0 = json.loads((tmp_path / "F0-w0.json").read_text())
        assert {r["repeat_shift"] for r in w0["runs"] if r["repeat_trace"] is not None} == {0}
        assert json.loads((tmp_path / "F0w.json").read_text())["waits"] == -1
        assert stats["runs"] == 34 and stats["failures"] == 1 and stats["repeats"] == 7
        assert stats["repeat_mismatches"] == 1
        assert not list(tmp_path.glob("*.tmp"))


    def test_interrupt_and_resume(self):
        tmp_path = self.tmp_path
        chains = acquire.select_chains(["F0"], waits=[0], catalog=CATALOG)
        with self.assertRaises(KeyboardInterrupt):
            go(FakeHarness(stop_after=4), chains, tmp_path, repeat_fraction=0)
        data = json.loads((tmp_path / "F0-w0.json").read_text())
        assert [r["chain"]["id"] for r in data["runs"]] == [c.id for c in chains[:4]]
        harness = FakeHarness()
        stats = go(harness, chains, tmp_path, resume=True, repeat_fraction=0)
        assert [c[0] for c in harness.calls] == [c.id for c in chains[4:]]
        assert stats["skipped"] == 4 and stats["runs"] == 6
        data = json.loads((tmp_path / "F0-w0.json").read_text())
        assert [r["chain"]["id"] for r in data["runs"]] == [c.id for c in chains]
        # without --resume, a filtered re-run replaces only its own entries
        harness = FakeHarness(fail={chains[2].id})
        go(harness, [chains[2]], tmp_path, repeat_fraction=0)
        data = json.loads((tmp_path / "F0-w0.json").read_text())
        assert len(data["runs"]) == 10
        assert [r["passed"] for r in data["runs"]].count(False) == 1


    def test_backend_mixing_refused_and_sim_lane(self):
        tmp_path = self.tmp_path
        chains = acquire.select_chains(["F0w"], catalog=CATALOG)
        harness = FakeHarness()
        go(harness, chains, tmp_path, backend="sim", board_state=None, repeat_fraction=0)
        assert {mode for _, mode in harness.calls} == {"model"}
        data = json.loads((tmp_path / "F0w.json").read_text())
        assert data["backend"] == "sim" and data["runs"][0]["socket_trace"]
        with self.assertRaises(SystemExit):
            go(FakeHarness(), chains, tmp_path, repeat_fraction=0)


    def test_main_requires_socket_fitted(self):
        with self.assertRaises(SystemExit):
            acquire.main(["--family", "F0"])


    def test_trace_shift(self):
        row = lambda t, a, f=1: {"start": t, "end": t + 9, "address": a, "flags": f, "data": 0, "strobe": 0}
        a = [row(0, 0x100, 13), row(8, 5)]
        assert acquire.trace_shift(a, a) == 0
        assert acquire.trace_shift(a, [row(4, 0x2100, 13), row(12, 5)]) == 4
        assert acquire.trace_shift(a, [row(4, 0x100, 13), row(12, 6)]) is None
        assert acquire.trace_shift(a, [row(4, 0x100, 13), row(13, 5)]) is None
        assert acquire.trace_shift(a, a[:1]) is None


if __name__ == "__main__":
    unittest.main()
