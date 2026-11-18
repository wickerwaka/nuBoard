"""off25.py FINAL.jsonl NAME=OFF.jsonl ...: per rule switched off alone: corpus runs and RTL miss rows (land21) it carries."""
import json, sys
S = "/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad"
miss = {json.loads(l)["run"] for l in open(S + "/v2/qprobe/land21/miss-v35_chk.jsonl") if not json.loads(l)["exact"]}
ld = lambda p: {json.loads(l)["run"]: json.loads(l)["exact"] for l in open(p)}
f = ld(sys.argv[1]); print("final", sum(f.values()), "rtl-miss exact", sum(f[r] for r in miss))
for a in sys.argv[2:]:
    n, p = a.split("=", 1); x = ld(p)
    lost = [r for r in f if f[r] and not x[r]]; gain = [r for r in f if x[r] and not f[r]]
    print(f"{n:12} carries {len(lost):4} corpus runs, {sum(r in miss for r in lost):4} RTL miss rows; off gains {len(gain)}")
