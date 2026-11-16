"""Run the qprobe programs on the socket or in simulation (the core v2).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.qprobe.run \\
        --socket-fitted --round r1
    PYTHONPATH=host/src:. python3 -m validation.v35s.qprobe.run --backend sim --round r1

The board path is chains.acquire's (open_board, vccb_enable, arm, sweep, arm(False), power_off):
the same safety sequence, only the chain list is this package's. Every chain is run twice
(--repeat-fraction 1). Output: build/validation/v35s/qprobe/{socket,sim}/<family>-w<N>.json.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ..chains import acquire
from . import gen

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "build/validation/v35s/qprobe"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket-fitted", action="store_true")
    ap.add_argument("--backend", choices=("board", "sim"), default="board")
    ap.add_argument("--round", nargs="+", default=["r1"])
    ap.add_argument("--waits", nargs="+", type=int, default=list(gen.WAITS))
    ap.add_argument("--parity", nargs="+", default=list(gen.PARITIES))
    ap.add_argument("--id", nargs="+", dest="ids")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--repeat-fraction", type=float, default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    chains = gen.chains(args.round, args.waits, args.parity, args.ids)
    if args.list:
        from ..chains.image import build_image
        for c in chains:
            b = build_image(c)
            print(f"{c.id:<28} base={b.chain_base:05X} "
                  + " ".join(i.code.hex() for i in c.instrs[:-1]))
        print(len(chains), "chains")
        return 0
    if args.backend == "board" and not args.socket_fitted:
        raise SystemExit("board runs power the socket: pass --socket-fitted")
    out = args.output_dir or OUT / ("sim" if args.backend == "sim" else "socket")
    rep = args.repeat_fraction
    if rep is None:
        rep = 1.0 if args.backend == "board" else 0.0
    common = dict(backend=args.backend, output_dir=out, resume=args.resume,
                  repeat_fraction=rep, limit=acquire.DEFAULT_LIMIT)
    from nuboard.debug import DebugClient
    from ..runner import Harness, open_board
    if args.backend == "sim":
        binary = acquire.SIM_CORES["v35"][0]
        if not binary.exists():
            raise SystemExit(f"{binary} missing")
        transport = acquire.sim_transport("v35", False)
        try:
            stats = acquire.sweep(Harness(DebugClient(transport.exchange)), chains,
                                  board_state=None, core="v35", log=lambda *a, **k: None,
                                  **common)
        finally:
            transport.close()
    else:
        transport, harness, state = open_board(True)
        try:
            transport.vccb_enable()
            harness.arm()
            time.sleep(0.05)
            stats = acquire.sweep(harness, chains, board_state=state, **common)
        finally:
            try:
                harness.arm(False)
                transport.power_off()
            finally:
                transport.close()
    print({k: v for k, v in stats.items()})
    return 1 if stats["failures"] or stats["incomplete"] or stats["repeat_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
