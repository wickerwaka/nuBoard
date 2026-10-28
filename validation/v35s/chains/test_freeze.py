"""The frozen chain model (freeze.py; docs/v35s-hdl-plan.md, Phase A1): the checked-in
sim/frozen/ is what the generator makes of fit.json and sim/, it runs only the fit's
structure, and it runs a sample of the corpus exactly as sim/ does (the whole corpus:
python -m validation.v35s.chains.freeze --verify)."""

from __future__ import annotations

import unittest

from validation.v35s.chains import freeze
from validation.v35s.chains.sim.config import Config

SAMPLE = ("F0", "F3", "F5", "F6", "F8")


class FrozenPackage(unittest.TestCase):
    def test_checked_in_is_a_fresh_generation(self):
        res = freeze.generate()
        on_disk = sorted(p.name for p in freeze.FROZEN.glob("*.py"))
        self.assertEqual(on_disk, sorted(res.files),
                         "regenerate: python -m validation.v35s.chains.freeze")
        for name, text in sorted(res.files.items()):
            self.assertEqual((freeze.FROZEN / name).read_text(), text,
                             f"sim/frozen/{name} drifted from fit.json and sim/: regenerate with "
                             "python -m validation.v35s.chains.freeze")

    def test_header_names_the_fit(self):
        import hashlib

        sha = hashlib.sha256(freeze.FIT.read_bytes()).hexdigest()
        for p in sorted(freeze.FROZEN.glob("*.py")):
            self.assertIn(f"(sha256 {sha}); do not edit.", p.read_text().split('"""')[0], p.name)

    def test_rejects_another_structure(self):
        from validation.v35s.chains.sim.frozen.machine import Machine
        from validation.v35s.chains.sim.machine import Machine as SimMachine
        from validation.v35s.chains.families import generate

        chain = next(iter(generate(["F0"])))
        fitted = Config.fitted()
        Machine(chain, fitted)                         # the fit runs
        Machine(chain, fitted.replace(**{"imm.pre": fitted.c("imm", "pre") + 1}))  # integers too
        Machine(chain)                                 # the default is the fit
        other = {"hold_q": fitted.hold_q + 1,           # an integer field of the structure
                 "arbiter": "data_wins" if fitted.arbiter != "data_wins" else "fifo",
                 "refresh_drop": not fitted.refresh_drop}
        for field, value in other.items():
            with self.subTest(field=field):
                cfg = fitted.replace(**{field: value})
                SimMachine(chain, cfg)                 # sim/ takes it
                with self.assertRaisesRegex(ValueError, field):
                    Machine(chain, cfg)

    def test_sample_runs_identically(self):
        """One run of each SAMPLE family: events and per-clock state rows (clock log, so no
        fast-forward), and the events again with the fast-forward on in both."""
        from validation.v35s.chains.normalize import load_runs, normalize
        from validation.v35s.chains.sim import machine as m0
        from validation.v35s.chains.sim.frozen import machine as m1

        cfg = Config.fitted()
        for fam in SAMPLE:
            try:
                runs = load_runs(fam)
            except FileNotFoundError:
                self.skipTest(f"no {fam} corpus entries")
            rec = runs[len(runs) // 2]
            with self.subTest(run=rec["chain"]["id"]):
                s = normalize(rec)
                anchor = m0.refresh_anchor(s)
                a, b = freeze._one(m0, s, cfg, anchor), freeze._one(m1, s, cfg, anchor)
                self.assertEqual(a[0], "ok", a[1])
                self.assertTrue(a[2], "no clock rows")
                self.assertIsNone(freeze._diff(a, b))
                fast = [m.simulate_normalized(s.chain, cfg, s.chain_base, refresh=anchor)
                        for m in (m0, m1)]
                self.assertEqual(fast[0].events, fast[1].events)
                self.assertEqual(fast[0].events, a[1].events)


if __name__ == "__main__":
    unittest.main()
