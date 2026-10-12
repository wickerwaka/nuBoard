#!/usr/bin/env python3
"""Run the HyperRAM test on every image built by `make -C fpga hyperram-sweep`.

For each build/fpga/template-hr<MHz>-p<phase>/ image this configures the
FPGA, reads the ID registers and runs every test pattern over the whole
device. It prints a frequency x capture-phase grid and writes the full
results to logs/hyperram-sweep-<timestamp>.csv.

Run it with the host virtual environment:

    build/host-venv/bin/python tools/hyperram-sweep.py [--bursts N]
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "host" / "src"))

from nuboard import hyperram  # noqa: E402
from nuboard.device import NuBoard  # noqa: E402

RUNS = [
    ("prbs", 0x00000001),
    ("prbs", 0x9e3779b9),
    ("address", 0x00000000),
    ("walking", 0x00000000),
    ("toggle", 0x000000ff),
]


def images() -> list[tuple[int, int, Path]]:
    found = []
    for path in (repo_root / "build" / "fpga").glob("template-hr*-p*"):
        match = re.fullmatch(r"template-hr(\d+)-p(\d+)", path.name)
        image = path / "outflow" / "template.hex.bin"
        if match and image.exists():
            found.append((int(match[1]), int(match[2]), path))
    return sorted(found)


def worst_slack(build: Path) -> float | None:
    summary = build / "timing-summary.txt"
    if summary.exists():
        match = re.search(r"worst_slack_ns=(-?[\d.]+)", summary.read_text())
        if match:
            return float(match[1])
    return None


def run_image(board: NuBoard, mhz: int, phase: int, build: Path,
              bursts: int | None) -> dict:
    row = {"mhz": mhz, "phase": phase, "slack_ns": worst_slack(build)}
    # The firmware accepts a new image only once the FPGA has finished its
    # power-down sequence (3.3 V off, 5 ms, then 1.2 V off).
    board.power_off()
    deadline = time.monotonic() + 2.0
    while json.loads(board.state()).get("phase") != 0:
        if time.monotonic() > deadline:
            raise RuntimeError("FPGA did not power down")
        time.sleep(0.005)
    board.configure(build / "outflow" / "template.hex.bin")
    ident = hyperram.wait_ready(board)
    row.update(id0=f"0x{ident.id0:04x}", id1=f"0x{ident.id1:04x}",
               status=hyperram.STATUS_NAMES.get(ident.status, ident.status))
    if ident.status != 0:
        row["result"] = "not ready"
        return row
    if (ident.mhz, ident.phase) != (mhz, phase):
        raise RuntimeError(f"{build.name} reports {ident.mhz} MHz "
                           f"{ident.phase} degrees")
    row["burst_words"] = ident.burst_words
    errors = missing = words = 0
    bits = 0
    first = None
    for name, seed in RUNS:
        result = hyperram.test(board, hyperram.PATTERNS[name], seed, 0, bursts)
        words += result.words
        errors += result.errors
        missing += result.missing
        bits |= result.error_bits
        if result.status != 0:
            row["result"] = hyperram.STATUS_NAMES.get(result.status)
            break
        if result.errors and first is None:
            first = (f"{name}@0x{result.first_error_address:06x} "
                     f"exp 0x{result.first_error_expected:04x} "
                     f"got 0x{result.first_error_actual:04x}")
        row["write_mb_per_s"] = result.write_mb_per_s
        row["read_mb_per_s"] = result.read_mb_per_s
    row.update(words=words, errors=errors, missing=missing,
               error_bits=f"0x{bits:04x}", first_error=first or "")
    row.setdefault("result", "pass" if errors == 0 and missing == 0 else "fail")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bursts", type=lambda text: int(text, 0),
                        default=None,
                        help="bursts per pattern (default: whole device)")
    args = parser.parse_args()

    builds = images()
    if not builds:
        print("no sweep images; run: make -C fpga -j2 hyperram-sweep",
              file=sys.stderr)
        return 1

    rows = []
    with NuBoard() as board:
        for mhz, phase, build in builds:
            try:
                row = run_image(board, mhz, phase, build, args.bursts)
            except Exception as exc:  # keep sweeping; record the failure
                row = {"mhz": mhz, "phase": phase, "result": "error",
                       "first_error": str(exc)}
            rows.append(row)
            print(f"{mhz:4d} MHz {phase:3d} deg: {row['result']:9s} "
                  f"errors={row.get('errors', '-')} "
                  f"missing={row.get('missing', '-')} "
                  f"bits={row.get('error_bits', '-')} "
                  f"write={row.get('write_mb_per_s')}MB/s "
                  f"slack={row.get('slack_ns')} {row.get('first_error', '')}",
                  flush=True)

    phases = sorted({row["phase"] for row in rows})
    print("\nMHz  " + "".join(f"{p:>6}" for p in phases))
    for mhz in sorted({row["mhz"] for row in rows}):
        cells = []
        for phase in phases:
            row = next((r for r in rows
                        if r["mhz"] == mhz and r["phase"] == phase), None)
            mark = "-" if row is None else {
                "pass": "ok", "fail": "FAIL"}.get(row["result"], "ERR")
            if row and row.get("slack_ns") is not None and row["slack_ns"] < 0:
                mark += "*"
            cells.append(f"{mark:>6}")
        print(f"{mhz:<5}" + "".join(cells))
    print("* fabric timing not met in that build")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = repo_root / "logs" / f"hyperram-sweep-{stamp}.csv"
    log.parent.mkdir(exist_ok=True)
    fields = ["mhz", "phase", "result", "words", "errors", "missing",
              "error_bits", "first_error", "id0", "id1", "status",
              "burst_words", "write_mb_per_s", "read_mb_per_s", "slack_ns"]
    with log.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"results: {log.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
