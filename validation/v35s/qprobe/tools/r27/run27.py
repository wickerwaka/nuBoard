"""run27.py run.py-args...: the qprobe runner with round 27's READY runs. A chain whose name ends -yNNN / -zNNN / -xNNN gets
WTC = 0003h (block 0: two waits and READY; I/O stays at 0 waits) and the harness's READY hold set to NNN ticks for
that run (run_built's configure); every other chain runs exactly as run.py runs it. Socket and sim alike."""
import dataclasses, re, sys
sys.path[:0] = ["host/src", "."]
from validation.v35s.chains import acquire, image
from validation.v35s.qprobe import gen, run
from validation.v35s.runner import Harness

CUR = {"ticks": 0}
DBG = "-D" in sys.argv
if DBG: sys.argv.remove("-D")
_chains, _build, _conf = gen.chains, image.build_image, Harness.configure


def hold(cid):
    m = re.search(r"-[yzx](\d+)-p[EO]-w\d$", cid)
    return int(m.group(1)) if m else None


def prc(cid):
    """-yNNN: fX/2 (the frame's clock, 8 ticks); -zNNN: fX/4 (PRC 4Dh, 16 ticks); -xNNN: fX/8 (4Eh, 32 ticks)."""
    m = re.search(r"-([yzx])\d+-p[EO]-w\d$", cid)
    return {"y": 0x4C, "z": 0x4D, "x": 0x4E}[m.group(1)]


RFM_MAP = 0xF2          # refresh on, every 64 clocks, RFW = 0 (a chain named ...-rf)


def chains(*a, **k):
    out = []
    for c in _chains(*a, **k):
        if hold(c.id) is not None:
            c = dataclasses.replace(c, wtc=0x0003, prc=prc(c.id))
        elif re.search(r"-r[fg]-p[EO]-w\d$", c.id):
            c = dataclasses.replace(c, rfm=RFM_MAP if "-rf-" in c.id else 0xF3)   # -rg: every 128 clocks
        out.append(c)
    return out


def build_image(chain):
    CUR["ticks"] = hold(chain.id) or 0
    return _build(chain)


def configure(self, *a, **k):
    if "ready_ticks" in k:
        k["ready_ticks"] = CUR["ticks"]
        if DBG: print("configure", k, file=sys.stderr)
    return _conf(self, *a, **k)


gen.chains, image.build_image, Harness.configure = chains, build_image, configure
if __name__ == "__main__":
    sys.exit(run.main(sys.argv[1:]))
