"""Run chain-timing families on the socketed V35S and save the bus traces.

From the repo root:

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.chains acquire \\
        --socket-fitted --family F0 F0w F1

(`python -m validation.v35s.chains.acquire ...` takes the same arguments.)

Every selected chain is built (image.build_image), loaded and run once from
reset at fX/2 with X_HALF = 2 (8 ticks per CPU clock), and the socket lane's
full trace is kept. Results go to one file per (family, waits):

    <output-dir>/<family>-w<N>.json      (F0w, whose chains carry waits = -1: F0w.json)

Each file is rewritten after every run, atomically (a temporary file in the
same directory, then os.replace), so an interrupted sweep keeps every finished
run and the file on disk is never half written. Runs are keyed by chain id:
--resume skips ids already in the file; without it the selected chains are
run again and replace their old entries, and entries for chains not selected
are kept. A file written by the other backend is never mixed with this one.

Determinism check: after the sweep, every Nth chain of each file
(N = round(1 / --repeat-fraction), chain order as the family generates them)
is run again; its trace goes under "repeat_trace" and "repeat_identical" says
whether it equals the first exactly. "repeat_shift" is the constant number of
ticks the repeat is offset by when it matches apart from that offset and the
row addresses of refresh cycles (0 when no offset; null when it differs
otherwise): in simulation a repeat can land at another reset phase, which
moves every start and end by the same amount, and the refresh counter carries
over from run to run into the few refreshes the prelude makes before it turns
refresh off.
Only a repeat that differs beyond a constant offset counts as a mismatch.
--resume skips repeats already recorded.

--backend sim runs the model lane alone in Verilator (SimulationTransport
"direct") to test this plumbing only; the trace is still stored as
"socket_trace", with "backend": "sim", in a separate default directory.
--core chain (WP82) runs the chain-model core in that lane instead of the ucore
(fpga/v35s/build_sim.sh direct chain: build/fpga/v35s/verilator-direct-chain/), into
its own default directory (build/validation/v35s/chains-sim-chain), the file header
saying "core": "chain"; --diag passes +chain_diag (the lane's diagnostics on stderr).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "build/validation/v35s/chains"
SIM_OUTPUT = ROOT / "build/validation/v35s/chains-sim"
SIM_BINARY = ROOT / "build/fpga/v35s/verilator-direct/Vv35s_harness"
# (WP82) the model lane's cores under --backend sim: the binary and the default output directory
CHAIN_BINARY = ROOT / "build/fpga/v35s/verilator-direct-chain/Vv35s_harness"
CHAIN_OUTPUT = ROOT / "build/validation/v35s/chains-sim-chain"
# the V35S core v2 (docs/v35s-core-v2.md; fpga/v35s/build_sim.sh direct v35)
# ((S7b) V35_SIM_BINARY: another build of it, e.g. a work-in-progress one beside a running gate)
V35_BINARY = Path(os.environ.get("V35_SIM_BINARY")
                  or ROOT / "build/fpga/v35s/verilator-direct-v35/Vv35s_harness")
V35_OUTPUT = ROOT / "build/validation/v35s/chains-sim-v35"
SIM_CORES = {"ucore": (SIM_BINARY, SIM_OUTPUT), "chain": (CHAIN_BINARY, CHAIN_OUTPUT),
             "v35": (V35_BINARY, V35_OUTPUT)}
X_HALF = 2
TICKS_PER_CLOCK = 4 * X_HALF
DEFAULT_LIMIT = 2_000_000
FLAG_REFRESH = 1 << 2   # as runner.FLAG_REFRESH; kept here so the module imports without nuboard


def sim_transport(core: str = "ucore", diag: bool = False):
    """(WP82) a SimulationTransport on the model lane's binary for `core` (runner's for the
    ucore without diagnostics, else the same pipe protocol on the core's binary)."""
    import subprocess
    from ..runner import SimulationTransport
    if core == "ucore" and not diag:
        return SimulationTransport("direct")
    # (S7b) V35_PLUSARGS: more plusargs for the v35 core's runs (+v35_ticks=2: the two-tick
    # variant, ce_b on the CPU clock's middle tick; +v35_ceb=K)
    extra = os.environ.get("V35_PLUSARGS", "").split() if core == "v35" else []
    transport = SimulationTransport.__new__(SimulationTransport)
    transport.process = subprocess.Popen(
        [str(SIM_CORES[core][0])] + ([f"+{'v35' if core == 'v35' else 'chain'}_diag"]
                                     if diag else []) + extra, cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    return transport


def file_name(family: str, waits: int) -> str:
    return f"{family}.json" if waits < 0 else f"{family}-w{waits}.json"


def write_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=1)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


class RunFile:
    """One output file: the runs of one (family, waits), keyed by chain id."""

    def __init__(self, path: Path, header: dict):
        self.path = path
        self.header = header
        self.runs: dict[str, dict] = {}
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("backend") != header["backend"]:
                raise SystemExit(f"{path} holds {data.get('backend')} runs, not "
                                 f"{header['backend']}: choose another --output-dir")
            if data.get("core", "ucore") != header.get("core", "ucore"):
                raise SystemExit(f"{path} holds the {data.get('core', 'ucore')} core's runs, "
                                 f"not the {header.get('core', 'ucore')}'s: choose another "
                                 f"--output-dir")
            for run in data.get("runs", []):
                self.runs[run["chain"]["id"]] = run

    def save(self, order: list[str]):
        """Write all runs: chains of this sweep in generator order, then any others."""
        ids = [i for i in order if i in self.runs]
        seen = set(ids)
        ids += [i for i in self.runs if i not in seen]
        write_atomic(self.path, {**self.header, "runs": [self.runs[i] for i in ids]})


def run_built(harness, built, backend: str, limit: int) -> dict:
    """Configure, load and run one image; return the run fields of the output."""
    harness.configure(x_half=X_HALF, ready_ticks=0)
    harness.load(built.image)
    lane = "model" if backend == "sim" else "socket"
    result = harness.run(lane, limit)
    lane_result = result[f"{lane}_result"]
    return {
        "status": result["status"],
        "passed": not result["timeout"] and lane_result == 1,
        "complete": result["trace_complete"],
        "timeout": result["timeout"],
        "overflow": result["overflow"],
        "socket_result": lane_result,
        "elapsed_ticks": result["elapsed_ticks"],
        "socket_trace": result[f"{lane}_trace"],
    }


def trace_shift(first: list[dict], again: list[dict]) -> int | None:
    """Ticks to add to `first` to get `again` if they differ only by one constant
    time offset (reset lands at another phase) and by the row address of refresh
    cycles (the refresh counter carries over from run to run, and the prelude
    runs a few refreshes before it turns refresh off); 0 if identical apart from
    those rows; None otherwise."""
    if len(first) != len(again):
        return None
    if not first:
        return 0
    shift = again[0]["start"] - first[0]["start"]

    def key(row, offset):
        row = {**row, "start": row["start"] + offset, "end": row["end"] + offset}
        if row["flags"] & FLAG_REFRESH:
            row.pop("address", None)
            row.pop("data", None)
        return row

    for a, b in zip(first, again):
        if key(a, shift) != key(b, 0):
            return None
    return shift


def group_chains(chains) -> dict[tuple[str, int], list]:
    groups: dict[tuple[str, int], list] = {}
    for chain in chains:
        groups.setdefault((chain.family, chain.waits), []).append(chain)
    return groups


def sweep(harness, chains, *, backend: str, board_state, output_dir: Path, resume: bool,
          repeat_fraction: float, limit: int, build=None, log=print, core: str = "ucore") -> dict:
    """Run the chains, writing each (family, waits) file after every run."""
    if build is None:
        from .image import build_image as build
    files: dict[tuple[str, int], RunFile] = {}
    groups = group_chains(chains)
    for (family, waits), members in groups.items():
        header = {"backend": backend, "board_state": board_state, "x_half": X_HALF,
                  "ticks_per_clock": TICKS_PER_CLOCK, "family": family, "waits": waits}
        if core != "ucore":
            header["core"] = core
        files[(family, waits)] = RunFile(output_dir / file_name(family, waits), header)
    order = {key: [c.id for c in members] for key, members in groups.items()}

    stats = {"runs": 0, "failures": 0, "incomplete": 0, "skipped": 0,
             "repeats": 0, "repeat_mismatches": 0, "seconds": 0.0}
    started = time.monotonic()

    def progress(tag, chain_id, record, trace):
        stats["seconds"] = time.monotonic() - started
        done = stats["runs"] + stats["repeats"]
        log(f"{tag:<6} {chain_id:<48} cycles={len(trace):<5} "
            f"{'pass' if record['passed'] else 'FAIL'}"
            f"{'' if record['complete'] else ' INCOMPLETE'}"
            f" {stats['seconds'] / done:.2f} s/run", flush=True)

    for key, members in groups.items():
        out = files[key]
        for chain in members:
            if resume and chain.id in out.runs:
                stats["skipped"] += 1
                continue
            built = build(chain)
            record = {"chain": chain.to_json(), "code_hex": built.code.hex(),
                      "chain_base": built.chain_base, "image_sha256": built.image_sha256}
            record.update(run_built(harness, built, backend, limit))
            record.update(repeat_trace=None, repeat_identical=None, repeat_shift=None)
            out.runs[chain.id] = record
            out.save(order[key])
            stats["runs"] += 1
            stats["failures"] += not record["passed"]
            stats["incomplete"] += not record["complete"]
            progress("run", chain.id, record, record["socket_trace"])

    if repeat_fraction > 0:
        every = max(1, round(1 / repeat_fraction))
        for key, members in groups.items():
            out = files[key]
            for chain in members[::every]:
                first = out.runs.get(chain.id)
                if first is None or first.get("repeat_trace") is not None:
                    continue
                built = build(chain)
                if built.image_sha256 != first["image_sha256"]:
                    log(f"repeat {chain.id}: image changed since the first run "
                        f"({first['image_sha256'][:12]} -> {built.image_sha256[:12]}); skipped",
                    flush=True)
                    continue
                again = run_built(harness, built, backend, limit)
                first["repeat_trace"] = again["socket_trace"]
                first["repeat_identical"] = again["socket_trace"] == first["socket_trace"]
                first["repeat_shift"] = trace_shift(first["socket_trace"], again["socket_trace"])
                out.save(order[key])
                stats["repeats"] += 1
                stats["repeat_mismatches"] += first["repeat_shift"] is None
                progress("repeat", chain.id, again, again["socket_trace"])
                if first["repeat_shift"] is None:
                    log(f"       {chain.id}: repeat trace DIFFERS from the first", flush=True)
                elif first["repeat_shift"]:
                    log(f"       {chain.id}: repeat trace equal but shifted by "
                        f"{first['repeat_shift']} ticks", flush=True)

    stats["seconds"] = time.monotonic() - started
    done = stats["runs"] + stats["repeats"]
    log(f"\n{stats['runs']} runs, {stats['failures']} failed, {stats['incomplete']} incomplete, "
        f"{stats['skipped']} skipped (resume); {stats['repeats']} repeats, "
        f"{stats['repeat_mismatches']} differ; "
        f"{(stats['seconds'] / done if done else 0):.2f} s/run mean", flush=True)
    for out in files.values():
        log(f"  {out.path}")
    return stats


def select_chains(families, waits=None, parity=None, ids=None, catalog=None):
    """Chains of the named families that pass the --waits/--parity/--id filters."""
    if catalog is None:
        from .families import FAMILIES as catalog
    unknown = [f for f in families if f not in catalog]
    if unknown:
        raise SystemExit(f"unknown families {unknown}; known: {', '.join(catalog)}")
    chains = []
    for family in families:
        for chain in catalog[family]():
            if waits is not None and chain.waits >= 0 and chain.waits not in waits:
                continue
            if parity is not None and chain.parity not in parity:
                continue
            if ids and not any(s in chain.id for s in ids):
                continue
            chains.append(chain)
    return chains


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m validation.v35s.chains acquire", description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--socket-fitted", action="store_true",
                        help="confirm the uPD70337 daughterboard is installed; permits DUT power")
    parser.add_argument("--backend", choices=("board", "sim"), default="board",
                        help="sim: model lane in Verilator, to test the plumbing only")
    parser.add_argument("--core", choices=tuple(SIM_CORES), default="ucore",
                        help="(WP82) with --backend sim: the model lane's core (chain: the "
                             "chain-model RTL, build_sim.sh direct chain)")
    parser.add_argument("--diag", action="store_true",
                        help="(WP82) with --core chain: the lane's diagnostics on stderr")
    parser.add_argument("--family", nargs="+", required=True, help="families, e.g. F0 F0w F1")
    parser.add_argument("--waits", nargs="+", type=int, choices=(0, 1, 2),
                        help="keep chains at these waits (F0w chains are always kept)")
    parser.add_argument("--parity", nargs="+", choices=("even", "odd"))
    parser.add_argument("--id", nargs="+", dest="ids", help="keep chain ids containing any of these")
    parser.add_argument("--output-dir", type=Path,
                        help=f"default {DEFAULT_OUTPUT} (sim: {SIM_OUTPUT})")
    parser.add_argument("--resume", action="store_true",
                        help="skip chain ids already in the output files")
    parser.add_argument("--repeat-fraction", type=float, default=0.1,
                        help="re-run every round(1/F)th chain to check determinism (0: none)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="tick limit per run")
    return parser


def main(argv=None, args=None) -> int:
    """Entry point; __main__ may pass already-parsed `args` from its subparser."""
    if args is None:
        args = build_parser().parse_args(argv)
    if not 0 <= args.repeat_fraction <= 1:
        raise SystemExit("--repeat-fraction must be between 0 and 1")
    if args.backend == "board" and not args.socket_fitted:
        raise SystemExit("board runs power the socket: pass --socket-fitted")
    if args.core != "ucore" and args.backend != "sim":
        raise SystemExit("--core selects the model lane's core: it needs --backend sim")
    binary, sim_output = SIM_CORES[args.core]
    output_dir = args.output_dir or (sim_output if args.backend == "sim" else DEFAULT_OUTPUT)

    chains = select_chains(args.family, args.waits, args.parity, args.ids)
    if not chains:
        raise SystemExit("no chains match the filters")
    print(f"{len(chains)} chains from {' '.join(args.family)} -> {output_dir}", flush=True)

    from nuboard.debug import DebugClient
    from ..runner import Harness, open_board

    common = dict(backend=args.backend, output_dir=output_dir, resume=args.resume,
                  repeat_fraction=args.repeat_fraction, limit=args.limit)
    if args.backend == "sim":
        if not binary.exists():
            print(f"error: the Verilator model is not built ({binary} is missing)",
                  file=sys.stderr)
            return 2
        transport = sim_transport(args.core, args.diag)
        try:
            stats = sweep(Harness(DebugClient(transport.exchange)), chains,
                          board_state=None, core=args.core, **common)
        finally:
            transport.close()
    else:
        transport, harness, state = open_board(True)
        try:
            transport.vccb_enable()
            harness.arm()
            time.sleep(0.05)
            stats = sweep(harness, chains, board_state=state, **common)
        finally:
            try:
                harness.arm(False)
                transport.power_off()
            finally:
                transport.close()
    return 1 if stats["failures"] or stats["incomplete"] or stats["repeat_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
