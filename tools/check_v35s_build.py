#!/usr/bin/env python3
"""Qualify the V35S image: timing, package pins, passive-x4 and the sources.

fpga/v35s/build.sh compiles a private copy of the project in
build/fpga/v35s/project, so the checked sources are exactly the files in
that copy. The receipt goes to build/fpga/v35s/receipt.json.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/fpga/v35s"
OUTPUT = BUILD / "outflow"
PROJECT = BUILD / "project"
PERIODS = {"clk_sys": 30.0, "spi_sck": 100.0}
# fpga/v35s/core/model.sdc relaxes exactly these paths in model builds.
MULTICYCLE_FROM = ("harness/model/core/", "harness/model/core_")
MULTICYCLE_TO = "harness/model/"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_clock_relationships(report, periods=PERIODS):
    """Require exactly the expected clocks and no negative or relaxed paths."""
    relationships = report.split("Setup (Max) Clock Relationship", 1)[1]
    relationships = relationships.split("NOTE:", 1)[0]
    rows = re.findall(
        r"^\s+(\S+)\s+(\S+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+\([RF]-[RF]\)",
        relationships, re.MULTILINE,
    )
    slacks = [float(row[3]) for row in rows]
    clocks = {clock for row in rows for clock in row[:2]}
    if clocks != set(periods) or not slacks or min(slacks) < 0:
        raise ValueError(f"Timing gate failed: clocks={clocks}, slacks={slacks}")
    for path in report.split("++++ Path"):
        launch = re.search(r"Launch Clock\s*:\s*(\S+)", path)
        capture = re.search(r"Capture Clock\s*:\s*(\S+)", path)
        constraint = re.search(r"^Constraint\s*:\s*([\d.]+)", path, re.MULTILINE)
        begin = re.search(r"Path Begin\s*:\s*(\S+)", path)
        end = re.search(r"Path End\s*:\s*(\S+)", path)
        declared = (begin and end and begin[1].startswith(MULTICYCLE_FROM) and
                    end[1].startswith(MULTICYCLE_TO))
        if (launch and capture and constraint and launch[1] == capture[1] and
                launch[1] in periods and float(constraint[1]) > periods[launch[1]] + 0.001
                and not declared):
            raise ValueError("A same-domain path has a relaxed clock constraint")
    return slacks


def check_pins(pinout, isf):
    assigned = {}
    for line in pinout.splitlines():
        columns = [column.strip() for column in line.split("|")]
        if len(columns) > 3:
            assigned[columns[1]] = columns[2]
    expected = re.findall(r'assign_pkg_pin\("([^"]+)", "([^"]+)"\)', isf)
    for signal, pin in expected:
        if signal not in assigned.get(pin, ""):
            raise ValueError(f"Pin gate failed: expected {signal} at {pin}, found {assigned.get(pin)}")
    return len(expected)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    bitstream = OUTPUT / "v35s.hex.bin"
    for name in ("v35s.hex.bin", "v35s.timing.rpt", "v35s.pinout.rpt", "v35s.place.rpt"):
        # v35s_build.vh is written before compiling; Efinity rewrites the .xml.
        if (OUTPUT / name).stat().st_mtime_ns < (PROJECT / "v35s_build.vh").stat().st_mtime_ns:
            raise SystemExit(f"Stale build artifact: {name}")
    # The model's multicycle wildcards also match combinational cells, which
    # Efinity reports as invalid start/end points and skips; any other SDC
    # warning means a constraint was ignored.
    log = "\n".join(line for line in (OUTPUT / "v35s.log").read_text().splitlines()
                    if not re.search(r"set_multicycle_path: '[^']*' is not a valid "
                                     r"(startpoint|endpoint)", line))
    if re.search(r"WARNING[^\n]*(\[SDC[^\n]*v35s\.sdc|cannot be used with reference pin)", log):
        raise SystemExit("A project timing constraint was ignored; inspect v35s.log")
    try:
        slacks = check_clock_relationships((OUTPUT / "v35s.timing.rpt").read_text())
        pins = check_pins((OUTPUT / "v35s.pinout.rpt").read_text(),
                          (PROJECT / "v35s.isf").read_text())
    except ValueError as error:
        raise SystemExit(str(error))
    if b"Width: 4" not in bitstream.read_bytes():
        raise SystemExit("Not a passive-x4 bitstream")
    resources = (OUTPUT / "v35s.place.rpt").read_text()
    ram = re.search(r"Memory Blocks:\s*(\d+)\s*/\s*(\d+)", resources)
    if not ram or int(ram[1]) > int(ram[2]):
        raise SystemExit("Invalid block RAM utilization")
    model = "`define V35S_MODEL_PRESENT 1" in (PROJECT / "v35s_build.vh").read_text()
    sources = sorted(p for p in PROJECT.rglob("*")
                     if p.is_file() and p.suffix in (".v", ".sv", ".svh", ".vh", ".hex",
                                                      ".isf", ".sdc", ".xml"))
    receipt = {
        "bitstream_sha256": digest(bitstream),
        "bitstream_bytes": bitstream.stat().st_size,
        "model_present": model,
        "timing_report_sha256": digest(OUTPUT / "v35s.timing.rpt"),
        "constrained_slacks_ns": slacks,
        "checked_package_assignments": pins,
        "memory_blocks_used": int(ram[1]),
        "memory_blocks_available": int(ram[2]),
        "source_sha256": {str(p.relative_to(PROJECT)): digest(p) for p in sources},
        "scope_abi": 4,
        "capture_capacity_records": 32768,
    }
    destination = BUILD / "receipt.json"
    destination.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Timing/pin gates passed (model={model}); {destination}")


if __name__ == "__main__":
    main()
