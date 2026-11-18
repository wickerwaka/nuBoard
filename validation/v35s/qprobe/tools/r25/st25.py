"""st25.py RUN_ID CLOCK... [K=V]: which `stall = True` lines of model_m.simulate execute at the given run clocks (corpus run)."""
import sys, linecache
sys.path[:0] = ["host/src", ".", "build/qp"]
import cw24
M = cw24.M
argv = sys.argv[1:]
rid = argv[0]; clocks = {int(a) for a in argv[1:] if "=" not in a}; o = M.options([a for a in argv if "=" in a])
r = cw24.get(rid); d = cw24.OFF.get(cw24.cm.group_of(r["chain"]), 0)
hits = []
def tr(frame, ev, arg):
    if frame.f_code.co_name != "simulate": return None
    def loc(frame, ev, arg):
        if ev == "line":
            t = frame.f_locals.get("t")
            if t is not None and t + d in clocks:
                s = linecache.getline(frame.f_code.co_filename, frame.f_lineno)
                if "stall = True" in s or "lead_pri = True" in s: hits.append((t + d, frame.f_lineno))
        return loc
    return loc
sys.settrace(tr); cw24.both(r, o); sys.settrace(None)
for h in hits: print(h, linecache.getline(M.__file__, h[1] - 1).strip()[:150])
