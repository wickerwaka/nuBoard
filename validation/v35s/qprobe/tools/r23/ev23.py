"""ev23.py round idsub... : a run's bus events (clock kind where) from clock lo (default 90) on."""
import json, sys
from pathlib import Path
from validation.v35s.qprobe import read
rnd = sys.argv[1]
lo = int(next((a[3:] for a in sys.argv if a.startswith("lo=")), 90)); hi = int(next((a[3:] for a in sys.argv if a.startswith("hi=")), 400))
subs = [a for a in sys.argv[2:] if "=" not in a]
for path in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QP{rnd}-w*.json")):
    for r in json.loads(path.read_text())["runs"]:
        if any(s in r["chain"]["id"] for s in subs):
            ev = read.events(r)
            print(r["chain"]["id"][4:], r["status"], r["passed"], r.get("repeat_identical"),
                  " ".join(f"{t}{k}{wh & 0xfffff:x}" if k != "F" else f"{t}F{wh}" for t, k, wh in ev if lo <= t <= hi))
