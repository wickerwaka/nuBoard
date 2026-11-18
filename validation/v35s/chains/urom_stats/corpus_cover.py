"""Which corpus runs exercise the iterative instructions: per keyword, the number of runs whose
chain id / case name carries it, the file groups, and for chains the distinct `form` strings of
the instructions (to see how far operands vary). Read-only."""
import json, glob, re, collections, os
keys = ["mulu", "mul", "divu", "div", "ins", "ext", "add4s", "sub4s", "cmp4s", "rol4", "ror4",
        "shl", "shr", "sar", "rcl", "rcr", "cvtbd", "cvtdb", "adj4a", "adj4s", "adjba", "pushr", "popr", "prepare", "rep"]
cnt = collections.Counter(); files = collections.defaultdict(set); ex = collections.defaultdict(set); forms = collections.defaultdict(set)
for f in sorted(glob.glob("build/validation/v35s/corpus/*.json")):
    try: d = json.load(open(f))
    except Exception: continue
    runs = d.get("runs") if isinstance(d, dict) else None
    if not isinstance(runs, list): continue
    for r in runs:
        if not isinstance(r, dict): continue
        c = r.get("chain") or r.get("case") or {}
        n = (c.get("id") or c.get("name") or "").lower()
        fm = [str(i.get("form")) + ":" + str(i.get("code")) for i in c.get("instrs", []) if isinstance(i, dict)] or [str(c.get("form", "")) + ":" + str(c.get("target", ""))]
        toks = re.split(r"[^a-z0-9]+", n + " " + " ".join(x.split(":")[0].lower() for x in fm))
        for k in keys:
            if any(t.startswith(k) and (len(t) == len(k) or not t[len(k)].isalpha() or t[len(k):] in ("i",)) for t in toks):
                cnt[k] += 1; files[k].add(os.path.basename(f).split("-w")[0].replace(".json", "")); 
                if len(ex[k]) < 3: ex[k].add(n)
                for x in fm:
                    if k in x.lower(): forms[k].add(x)
for k in keys:
    print(f"{k:8} {cnt[k]:5} runs, {len(files[k]):3} file groups, {len(forms[k]):4} distinct form:code; e.g. {sorted(ex[k])}")
    print("          groups:", " ".join(sorted(files[k]))[:200])
