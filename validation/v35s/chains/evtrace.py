"""Event-trace diff of the V35S core v2 against the frozen chain model, one chain at a time.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains evtrace --id F0-ls-pE-w0 \\
        --rtl build/v35-F0-ls-pE-w0.trace [--run] [--window 8] [--model-out FILE]

The RTL side is fpga/v35s/core/v35/v35_trace.sv's file (`+v35_trace=FILE`; --run replays the
chain through build/fpga/v35s/verilator-direct-v35 with that plusarg first, into FILE). The
model side is the frozen Machine (validation/v35s/chains/sim/frozen) run on the same chain and
chain base, with thin hooks writing the same line format (docs/v35s-core-v2.md, Appendix A §5):

    <t> [X:<kind>:<addr>:<width>:<len>] [S:<class>:<pc>] [T:<n>] [L:<n>] [P:<kind>] [I] [B] [A]
        R:<room>:<flag> [W:<reason>]

X from bus.cycles (each cycle on its start clock), S from eu.trace (the instruction starts:
class, the opcode's linear address), T the bytes Decoder.take returned, L the IR loads
(Decoder.load_ir), P the requests EU._post made, I the EU's cycles (EU.issue), B the
back-to-back commitment made at the clock's end (queue.b2b_at == t + 1), A the aborted cycles
(Queue.abort), R the request rule's room and the flag at the clock's end (the clock_log row).
W, the RTL's wait reason, has no model counterpart and is shown, not compared.

Both traces are aligned at t_fill (normalize.normalize over their cycles: the end clock of the
last fetch before the first idle gap after the first LS's last byte); from there the lines are
compared clock by clock, and the first divergent clock is printed with --window clocks of both
around it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .acquire import ROOT, SIM_CORES
from .normalize import normalize
from .types import TICKS_PER_CLOCK

SFR_PAGE = 0xFFF00


# Model side --------------------------------------------------------------------------

def _chain_and_base(run_id: str):
    """The chain and its base: from the corpus run when there is one, else generated."""
    from .families import generate
    from .image import build_image
    from .normalize import load_runs
    family = run_id.split("-", 1)[0]
    try:
        rec = next((r for r in load_runs(family) if r["chain"]["id"] == run_id), None)
    except FileNotFoundError:
        rec = None
    if rec is not None:
        s = normalize(rec)
        return s.chain, s.chain_base
    chain = next((c for c in generate([family]) if c.id == run_id), None)
    if chain is None:
        raise SystemExit(f"unknown chain id {run_id}")
    return chain, build_image(chain).chain_base


def model_lines(chain, chain_base) -> tuple[dict, int]:
    """{clock: line} of the frozen model's run and its absolute t_fill clock."""
    from .sim.frozen.config import DEFAULT
    from .sim.frozen.machine import Machine, trace_rows
    m = Machine(chain, DEFAULT, chain_base)
    rows: list = []
    m.clock_log = rows
    takes: dict = {}
    loads: dict = {}
    posts: dict = {}
    issues: set = set()
    aborts: set = set()
    dec, eu, q = m.decoder, m.eu, m.queue

    take0 = dec.take

    def take(t, n, wide=False):
        k = take0(t, n, wide)
        takes[t] = takes.get(t, 0) + k
        return k
    dec.take = take
    load0 = dec.load_ir

    def load_ir(t):
        before = dec.ir
        load0(t)
        if dec.ir is not None and dec.ir != before:
            loads[t] = loads.get(t, 0) + 1
    dec.load_ir = load_ir
    post0 = eu._post

    def post(t, kind, *a, **kw):
        posts.setdefault(t, []).append(kind)
        return post0(t, kind, *a, **kw)
    eu._post = post
    issue0 = eu.issue

    def issue(t, bus):
        issues.add(t)
        return issue0(t, bus)
    eu.issue = issue
    abort0 = q.abort

    def abort(t):
        aborts.add(t)
        return abort0(t)
    q.abort = abort

    cycles = m.run()
    rec = {"chain": chain.to_json(), "chain_base": chain_base, "complete": True,
           "socket_trace": trace_rows(cycles)}
    n = normalize(rec, strict=False)
    starts = {c.start: c for c in cycles}
    st = {}
    for t, off, cls in eu.trace:
        st.setdefault(t, []).append((cls, chain_base + off))
    lines = {}
    for row in rows:
        t = row["t"]
        items = []
        c = starts.get(t)
        if c is not None:
            items.append(f"X:{c.kind}:{c.addr:05X}:{c.width}:{c.length}")
        for cls, pc in st.get(t, []):
            items.append(f"S:{_base_cls(cls)}:{pc:05X}")
        if takes.get(t):
            items.append(f"T:{takes[t]}")
        if loads.get(t):
            items.append(f"L:{loads[t]}")
        for kind in posts.get(t, []):
            items.append(f"P:{kind}")
        if t in issues:
            items.append("I")
        if row["b2b"]:
            items.append("B")
        if t in aborts:
            items.append("A")
        items.append(f"R:{row['room']}:{int(bool(row['flag']))}")
        lines[t] = " ".join(items)
    t_fill = None if n.t_fill is None else n.t0_tick // TICKS_PER_CLOCK + n.t_fill
    return lines, t_fill


def _base_cls(cls: str) -> str:
    from .sim.frozen.templates import base_class
    return base_class(cls)


# RTL side ----------------------------------------------------------------------------

def read_rtl(path: Path) -> dict:
    """{clock: (line without W, W)} of the trace file's last run."""
    runs, cur = [], None
    for raw in Path(path).read_text().splitlines():
        if raw.startswith("#"):
            cur = {}
            runs.append(cur)
            continue
        if not raw.strip():
            continue
        if cur is None:
            cur = {}
            runs.append(cur)
        head, _, rest = raw.partition(" ")
        items = rest.split()
        w = next((i for i in items if i.startswith("W:")), "")
        items = [_upper_addr(i) for i in items]
        cur[int(head)] = (" ".join(i for i in items if not i.startswith("W:")), w)
    if not runs:
        raise SystemExit(f"{path}: no trace lines")
    return runs[-1]


def _upper_addr(item: str) -> str:
    """$sformatf's %X writes lower-case hex: the address fields as the model writes them."""
    f = item.split(":")
    if f[0] == "X" and len(f) == 5:
        f[2] = f[2].upper()
    elif f[0] == "S" and len(f) == 3:
        f[1] = _base_cls(f[1])          # (S5a) the model side names the base class
        f[2] = f[2].upper()
    return ":".join(f)


def rtl_t_fill(lines: dict, chain, chain_base) -> int | None:
    """The RTL run's absolute t_fill clock (normalize over its X items, the on-chip SFR
    stores left out as trace_rows leaves them out)."""
    from .normalize import FLAG_IO, FLAG_NUBE, FLAG_READ
    rows = []
    for t in sorted(lines):
        for item in lines[t][0].split():
            if not item.startswith("X:"):
                continue
            _, kind, addr, width, length = item.split(":")
            addr, length = int(addr, 16), int(length)
            if kind == "write" and addr >= SFR_PAGE:
                continue
            flags = 0 if kind in ("write", "io_write") else FLAG_READ
            if kind.startswith("io"):
                flags |= FLAG_IO
            if width == "lo":
                flags |= FLAG_NUBE
            start = t * TICKS_PER_CLOCK
            rows.append({"start": start, "end": start + (length - 1) * TICKS_PER_CLOCK,
                         "address": addr, "flags": flags, "data": 0, "strobe": 0})
    rec = {"chain": chain.to_json(), "chain_base": chain_base, "complete": True,
           "socket_trace": rows}
    n = normalize(rec, strict=False)
    return None if n.t_fill is None else n.t0_tick // TICKS_PER_CLOCK + n.t_fill


def run_rtl(chain, path: Path):
    """Replay the chain through the v35 lane with +v35_trace=path."""
    import subprocess
    from nuboard.debug import DebugClient
    from ..runner import Harness, SimulationTransport
    from .replay import replay_one
    binary = SIM_CORES["v35"][0]
    if not binary.exists():
        raise SystemExit(f"{binary} is missing: fpga/v35s/build_sim.sh direct v35")
    transport = SimulationTransport.__new__(SimulationTransport)
    import os
    # (S5a) V35_PLUSARGS: more plusargs for the run (e.g. +v35_dbg=FILE, the sequencer's state)
    extra = os.environ.get("V35_PLUSARGS", "").split()
    transport.process = subprocess.Popen([str(binary), f"+v35_trace={path}", *extra], cwd=ROOT,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        rec = replay_one(chain, harness=Harness(DebugClient(transport.exchange)))
    finally:
        transport.close()
    return rec


# Diff --------------------------------------------------------------------------------

def diff(model: dict, m_fill: int, rtl: dict, r_fill: int, window: int = 8) -> str:
    off = r_fill - m_fill
    out = [f"aligned at t_fill: model clock {m_fill}, RTL clock {r_fill} (offset {off})"]
    first = None
    for t in sorted(k for k in model if k >= m_fill):
        a = model[t]
        b = rtl.get(t + off, ("<none>", ""))[0]
        if a != b:
            first = t
            break
    if first is None:
        out.append(f"no divergence over {len([k for k in model if k >= m_fill])} model clocks")
        return "\n".join(out)
    out.append(f"first divergence at model clock {first} (t_fill{first - m_fill:+d}), RTL clock "
               f"{first + off}")
    for t in range(first - window, first + window + 1):
        mark = ">" if t == first else " "
        r = rtl.get(t + off, ("<none>", ""))
        out.append(f"{mark} {t - m_fill:+4d}  model: {model.get(t, '<none>')}")
        out.append(f"{mark} {t - m_fill:+4d}  rtl:   {r[0]}  {r[1]}")
    return "\n".join(out)


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="python -m validation.v35s.chains evtrace",
                                         description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", required=True, help="the chain id (e.g. F0-ls-pE-w0)")
    parser.add_argument("--rtl", type=Path, required=True, help="the RTL trace file")
    parser.add_argument("--run", action="store_true",
                        help="replay the chain through the v35 lane first, tracing into --rtl")
    parser.add_argument("--window", type=int, default=8, help="clocks shown around the first "
                        "divergence (default 8)")
    parser.add_argument("--model-out", type=Path, help="write the model's lines here")
    return parser


def main(argv=None, args=None) -> int:
    if args is None:
        args = build_parser().parse_args(argv)
    chain, base = _chain_and_base(args.id)
    if args.run:
        rec = run_rtl(chain, args.rtl.resolve())
        if not rec.get("passed"):
            print(f"{args.id}: the RTL run did not pass (status {rec.get('status')})")
    model, m_fill = model_lines(chain, base)
    if args.model_out:
        args.model_out.write_text("".join(f"{t} {model[t]}\n" for t in sorted(model)))
    rtl = read_rtl(args.rtl)
    r_fill = rtl_t_fill(rtl, chain, base)
    if m_fill is None or r_fill is None:
        print(f"{args.id}: no t_fill (model {m_fill}, RTL {r_fill})")
        return 2
    print(f"{args.id}")
    print(diff(model, m_fill, rtl, r_fill, args.window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
