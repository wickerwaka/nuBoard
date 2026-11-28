"""(Work order 54) The save state's structural checks (build/overseer/ss-design/DESIGN-SS.md 5.1):

1. every state element of the core (ss_inventory.py: Verilator's elaboration of v35_top with and
   without SYNTHESIS, every target of a non-blocking assignment in a clocked block) has a row in
   the class file fpga/v35s/core/v35/v35_ss_class.tsv with its width and a class; a register added
   to the core fails here until it is classed (SAVED, DERIVED, IDLE, HISTORY, CONST, SIMONLY);
2. the inventory's two methods (the elaboration, a textual scan) agree;
3. the state map fpga/v35s/core/v35/v35_ss_map.tsv covers every SAVED element whole (every bit of
   every instance, once; two rows on the same bits of one word name two copies of one value), and
   names no element that is not SAVED; its rows fit their words and do not overlap otherwise;
   index 000h (the format word) holds no field.
Skipped without Verilator."""

from __future__ import annotations

import re
import shutil
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V35 = ROOT / "fpga" / "v35s" / "core" / "v35"
CLASS_FILE = V35 / "v35_ss_class.tsv"
MAP_FILE = V35 / "v35_ss_map.tsv"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ss_inventory  # noqa: E402


def read_map(path: Path = MAP_FILE) -> list:
    """(index, lsb, width, element, element lsb) rows."""
    rows = []
    for ln in path.read_text().splitlines():
        if not ln.strip() or ln.startswith("#") or ln.startswith("index"):
            continue
        i, l, w, e, el = ln.split("\t")
        rows.append((int(i, 16), int(l), int(w), e, int(el)))
    return rows


def read_classes(path: Path = CLASS_FILE) -> dict:
    out = {}
    for ln in path.read_text().splitlines():
        f = ln.split("\t")
        if len(f) < 4 or ln.startswith("#") or f[:2] == ["module", "name"]:
            continue
        out[(f[0], f[1])] = f[3]
    return out


@unittest.skipUnless(shutil.which("verilator"), "verilator not on PATH")
class SaveStateInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = ss_inventory.build(str(ROOT))

    def test_every_register_is_classified(self):
        problems, _saved = ss_inventory.check(self.inv, str(CLASS_FILE))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_both_methods_agree(self):
        self.assertEqual(ss_inventory.crosscheck(self.inv), [])

    def test_the_map_covers_the_saved_state(self):
        classes = read_classes()
        els = self.inv.elements                              # instance path.name -> row
        rows = read_map()
        covered = defaultdict(list)                          # path -> [(element bit, count)]
        problems = []
        for i, l, w, e, el in rows:
            m = re.fullmatch(r"([\w.]+?)(?:\[(\d+)\])?", e)
            path, k = m.group(1), int(m.group(2) or 0)
            r = els.get(path)
            if r is None:
                problems.append(f"{i:03X}: {e} is no state element of the core")
                continue
            if classes.get((r["module"], r["name"])) != "SAVED":
                problems.append(f"{i:03X}: {e} is not SAVED "
                                f"({classes.get((r['module'], r['name']))})")
            if el + w > r["width"] or k >= r["depth"]:
                problems.append(f"{i:03X}: {e}[{el + w - 1}:{el}] outside its {r['width']} x "
                                f"{r['depth']} bits")
            covered[path] += [k * r["width"] + b for b in range(el, el + w)]
        for path, r in els.items():
            if classes.get((r["module"], r["name"])) != "SAVED":
                continue
            bits = covered.get(path, [])
            if sorted(bits) != list(range(r["width"] * r["depth"])):
                missing = r["width"] * r["depth"] - len(set(bits))
                problems.append(f"{path}: SAVED, the map covers {len(set(bits))} of "
                                f"{r['width'] * r['depth']} bits ({missing} missing, "
                                f"{len(bits) - len(set(bits))} twice)")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_map_rows_fit(self):
        problems = []
        words = defaultdict(list)
        for i, l, w, e, el in read_map():
            if not (0 < i < 0x400) or l < 0 or w < 1 or l + w > 16:
                problems.append(f"{i:03X}: {e} at [{l + w - 1}:{l}] outside the map's words")
            words[i].append((l, w, e))
        for i, fs in words.items():
            for a in range(len(fs)):
                for b in range(a + 1, len(fs)):
                    (la, wa, ea), (lb, wb, eb) = fs[a], fs[b]
                    if la < lb + wb and lb < la + wa and (la, wa) != (lb, wb):
                        problems.append(f"{i:03X}: {ea} and {eb} overlap")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
