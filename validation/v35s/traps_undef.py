"""Item 4's reader: what each undefined-opcode case did on a backend (traps.run_undef receipts).

    PYTHONPATH=host/src:. python3 -m validation.v35s.traps_undef summary --series 0f [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.traps_undef gate [--series S ...]

Per case: pass A (the NOP sled) and pass B (the INC AW sled): a trap (vector, pushed PC offset
from the opcode), a landing in the zone, the registers changed against the setup, the PSW, the
sled bytes pass B executed (8 - AW: the bytes the opcode consumed beyond its own), and the bus
cycles between the opcode and the continuation that are not code fetches.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import traps as T

NAMES = ("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY", "DS0", "DS1", "SS", "PSW")


def load(series, backend):
    return json.loads(T.receipt_path(f"undef_{series}", backend).read_text())["cases"]


def _slots(rec):
    s = bytes.fromhex(rec["regions"][f"{T.SLOTS:05X}"])
    return [{r: T._w(s, 32 * k + 2 * i) for i, r in enumerate(NAMES)} for k in range(2)]


def _log(rec):
    hdr = bytes.fromhex(rec["regions"][f"{T.LOG:05X}"])
    log = bytes.fromhex(rec["regions"][f"{T.LOG + 0x100:05X}"])
    n = T._w(hdr, 0)
    land = T._w(hdr, 0x14)
    ents = [{"vector": log[32 * k], "test": T._w(log, 32 * k + 2), "pc": T._w(log, 32 * k + 4)}
            for k in range(min(n, 8))]
    return n, land, ents


def summary_line(name, rec, raw, regs):
    regs = dict(T.UREGS, **(regs or {}))
    exp = dict(regs, SP=T.SP0, DS0=T.UDS0, DS1=T.UDS1, SS=0, PSW=0xF000 | T.UPSW)
    n, land, ents = _log(rec)
    sl = _slots(rec)
    at = rec["test_at"]
    out = [f"{name:10s} {' '.join(f'{b:02X}' for b in raw):14s} {'PASS' if rec['passed'] else 'FAIL'}"]
    for k in range(2):
        e = [x for x in ents if x["test"] == k]
        tr = " ".join(f"v{x['vector']}@{x['pc'] - at[k]:+d}" for x in e)
        s = sl[k]
        ex = dict(exp, AW=exp["AW"] if k == 0 else 0)
        ch = " ".join(f"{r}={s[r]:04X}" for r in NAMES if s[r] != ex[r] and not (k == 1 and r == "AW"))
        extra = f" sled={s['AW']}" if k == 1 else ""
        out.append(f"{'AB'[k]}:{tr or '-'}{extra} {ch}")
    if land:
        out.append(f"landed {land}")
    # bus cycles that are not fetches: memory writes beyond the slots / log, I/O, data reads
    from .runner import FLAG_IO, FLAG_READ, FLAG_STROBE
    odd = []
    for a, d, f in rec["trace"]:
        if not f & FLAG_STROBE:
            continue
        if f & FLAG_IO:
            odd.append(f"io{'r' if f & FLAG_READ else 'w'}:{a:04X}={d:04X}")
        elif not f & FLAG_READ and not (0x7E00 <= a < 0x7F00 or 0x8000 <= a < 0x9800):
            odd.append(f"w:{a:05X}={d:04X}")
        elif f & FLAG_READ and (0xA000 <= a < 0xC000 or 0x2000 <= a < 0x3000):
            odd.append(f"r:{a:05X}")
    io_ok = [o for o in odd if not o.startswith("iow:FF00")]
    if io_ok:
        out.append("bus " + " ".join(io_ok[:8]) + (f" (+{len(io_ok) - 8})" if len(io_ok) > 8 else ""))
    return " | ".join(out)


def summary(series, backend="socket"):
    recs = load(series, backend)
    cases = {c[1]: c for c in T.undef_cases()}
    for name, rec in recs.items():
        _, _, raw, regs, note = cases[name]
        print(summary_line(name, rec, raw, regs) + f"   ({note})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("summary", "gate"))
    p.add_argument("--series", nargs="*", default=["op", "modrm", "rep", "0f"])
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    a = p.parse_args()
    if a.action == "summary":
        for s in a.series:
            summary(s, a.ref)
        return 0
    return gate(a.series, a.ref, a.cand)


# The cases whose silicon behaviour the core builds (README "F2b"): the gate's set. The others
# are measured only: silicon runs an internal sequence for them (registers changed, stray bus
# cycles, a runaway) or a form F2b leaves open (FE /2-/6: FF's operation with a byte-wide stack
# write; D6: a read-modify-write of its ModR/M operand; REP before a segment prefix).
_NOP0F = ("23 80 82 88 90 98 A4 A5 AC AD B4 B5 BC BD C8 D0 E8 F0 "      # two bytes
          "30 32 35 36 37 38 3A 3D 3E 3F "                              # three
          "CA CC D2 D4 EA EC F2 F4").split()                            # four
BUILT = ({f"u0f{b}" for b in _NOP0F}
         | {f"u{op}{k}{r}" for op in ("8F", "C6", "C7") for k in "rm" for r in range(1, 8)}
         | {"uFEr3", "uFEr5", "uFEr7", "uFEm7", "uFFr7", "uFFm7", "u8Dreg", "uC4reg", "uC5reg",
            "uFFr3", "uFFr5", "u62reg"}
         | {c[1] for c in T.undef_cases() if c[0] == "rep" and c[1] not in ("rF3_26A4", "rF3_0F")
            and "IDIV" not in c[1]})
# the IDIV cases: the quotient and remainder equal (REP ignored, no negation), but silicon's IDIV
# leaves AC set (PSW F012) where the RTL's clears it: an IDIV flag difference outside F2b, reported
# rF3_0F: REP before TEST1 AL,0 runs TEST1 once as built, but silicon's TEST1 keeps AC (the RTL
# clears it, as the V20 suite's reference does): a TEST1 flag difference outside F2b, reported


def gate(series, ref="socket", cand="sim", skip=()):
    """Every built case (BUILT): the write and I/O sequence and the result regions equal."""
    bad = 0
    total = 0
    for s in series:
        ra, rb = load(s, ref), load(s, cand)
        for name, a in ra.items():
            if name in skip or name not in BUILT:
                continue
            total += 1
            b = rb.get(name)
            ok = b is not None and a["writes"] == b["writes"] and a["regions"] == b["regions"] \
                and a["passed"] == b["passed"]
            if not ok:
                bad += 1
                why = "missing" if b is None else ("writes" if a["writes"] != b["writes"] else
                                                  "regions" if a["regions"] != b["regions"] else
                                                  "passed")
                print(f"{s}/{name}: DIFFER ({why})")
    print(f"undef gate: {total - bad} / {total} equal")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
