"""an23.py round [v=1] : per unmasked run of a round-23 DMA family, against its masked twin (same
transfer, DIC0 masked): tw = first clock of the terminal DMA write (from M0), A = the vector read
(0050h) and A - tw, the instruction pushed (index in the train from the first one behind the
store / of the body), the first event that differs from the twin (clock - tw, kind, shift), and
for load trains the control's read clocks - tw around the take (Tprev, Tlast = the last read made
in the run, Tnext)."""
import json, sys, collections
from pathlib import Path
from validation.v35s.qprobe import read
kw = dict(x.split("=") for x in sys.argv[1:] if "=" in x)
for rnd in [x for x in sys.argv[1:] if "=" not in x]:
    for path in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QP{rnd}-w*.json")):
        runs = {r["chain"]["id"]: r for r in json.loads(path.read_text())["runs"]}
        rows = []
        for cid, r in sorted(runs.items()):
            if "-u-" not in cid:
                continue
            m = runs[cid.replace("-u-", "-m-")]
            eu, em = read.events(r), read.events(m)
            dw = [t for t, k, wh in eu if k == "W" and 0xD000 <= wh < 0xE000]
            dwm = [t for t, k, wh in em if k == "W" and 0xD000 <= wh < 0xE000]
            if not dw:
                rows.append((cid, "no DMA write")); continue
            tw = dw[-1]
            A = next((t for t, k, wh in eu if k == "R" and wh in (0x50, 0x54) and t > tw), None)
            recs = r["socket_trace"]
            pcw = [x for x in recs if not x["flags"] & 1 and x["address"] == 0xEFA and not x["flags"] & 2]
            pc = pcw[-1]["data"] if pcw else None
            ins = [i for i in r["chain"]["instrs"] if i["form"] == "x"]
            base = r["chain_base"] - 0x10000
            idx = next((n for n, i in enumerate(ins) if base + i["offset"] == pc), None)
            name = ins[idx]["code"] if idx is not None else "?"
            # first differing event
            i = next((i for i, (x, y) in enumerate(zip(eu, em)) if x != y), None)
            dif = ""
            if i is not None:
                x, y = eu[i], em[i]
                dif = f"{y[0]-tw}{y[1]}" + (f"{x[0]-y[0]:+d}" if x[1:] == y[1:] else f"->{x[0]-tw}{x[1]}{x[2]&0xfff:x}")
            rd_m = [t - tw for t, k, wh in em if k == "R" and wh == 0x800 and t > tw - 12]
            rd_u = [t - tw for t, k, wh in eu if k == "R" and wh == 0x800 and tw - 12 < t < (A or 999)]
            rows.append((cid[4:], f"tw={tw}{'' if dw == dwm else '!m' + str(dwm[-1] if dwm else None)} A-tw={A - tw if A else None} push#{idx}({name}) diff@{dif}"
                         + (f" ctl={rd_m[:len(rd_u)+2]} run={rd_u}" if rd_m else "")
                         + (" f:" + " ".join(f"{t-tw}{k}{'' if k!='F' else wh}" for t, k, wh in eu if tw - 6 <= t <= (A or tw + 60)) if kw.get("v") else "")))
        for row in rows:
            print(*row)
