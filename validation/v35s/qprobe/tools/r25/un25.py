"""un25.py MODEL.jsonl [PATTERN]: RTL miss rows (land17) by the model's state: exact / miss / not parsed; the misses by class
for the run ids matching PATTERN (regex)."""
import json, sys, re, collections
S = "/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad"
miss = {json.loads(l)["run"] for l in open(S + "/v2/qprobe/land17/miss-v35_chk.jsonl") if not json.loads(l)["exact"]}
m = {}
for l in open(sys.argv[1]):
    d = json.loads(l); m[d["run"]] = d
pat = re.compile(sys.argv[2] if len(sys.argv) > 2 else ".")
c = collections.Counter(); cl = collections.Counter(); ex = {}
for r, d in m.items():
    if not pat.search(r): continue
    st = "exact" if d["exact"] else ("miss" if d["status"] == "ok" else "nomodel")
    c[(r in miss and "rtlmiss" or "rtlexact", st)] += 1
    if st == "miss":
        k = (re.sub(r"-p[EO]-w\d", "", r)[:44], d["first"]["class"]); cl[k] += 1; ex.setdefault(k, []).append(r[-5:])
print(sorted(c.items()))
if "-q" not in sys.argv:
    for k, v in sorted(cl.items()): print("  ", v, *k, " ".join(ex[k]))
