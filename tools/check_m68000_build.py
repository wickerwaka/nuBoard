#!/usr/bin/env python3
"""Fail the build on negative constrained slack or a wrong assigned package pin."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "fpga/m68000"
OUTPUT = ROOT / "build/fpga/m68000/outflow"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_clock_relationships(report):
    """Require every active clock and reject negative or relaxed timing paths."""
    periods = {"clk_50mhz": 20.0, "spi_sck": 100.0, "spi_commit": 100.0}
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
        if (launch and capture and constraint and launch[1] == capture[1] and
                launch[1] in periods and float(constraint[1]) > periods[launch[1]] + 0.001):
            raise ValueError("A same-domain path has a relaxed clock constraint")
    return slacks


def source_manifest():
    namespace = {"efx": "http://www.efinixinc.com/enf_proj"}
    project_xml = ET.parse(PROJECT / "m68000.xml")
    sources = [PROJECT / node.attrib["name"]
               for node in project_xml.findall(".//efx:design_file", namespace)]
    sources += [PROJECT / f"m68000.{suffix}" for suffix in ("xml", "isf", "sdc")]
    sources += [ROOT / "build/deps/fx68k/hdl" / name
                for name in ("microrom.mem", "nanorom.mem")]
    return {str(path.resolve().relative_to(ROOT)): digest(path) for path in sources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    if os.environ.get("PSRAM_PHY"):
        raise SystemExit("Capture uses BRAM; PSRAM_PHY is unsupported")
    manifest_path = OUTPUT.parent / "build-input.json"
    if args.snapshot:
        # Efinity rewrites the project without a final newline. Normalize that
        # formatting before snapshotting, so a tool-only whitespace change
        # cannot look like a source edit halfway through the build.
        project_path = PROJECT / "m68000.xml"
        project_path.write_bytes(project_path.read_bytes().rstrip(b"\n"))
    manifest = {"capture_storage": "bram", "source_sha256": source_manifest()}
    if args.snapshot:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return
    if not manifest_path.exists() or json.loads(manifest_path.read_text()) != manifest:
        raise SystemExit("Build input changed or snapshot missing; rebuild before qualification")
    for name in ("m68000.hex.bin", "m68000.timing.rpt", "m68000.pinout.rpt",
                 "m68000.pt.rpt", "m68000.pt_timing.rpt", "m68000.place.rpt"):
        if (OUTPUT / name).stat().st_mtime_ns <= manifest_path.stat().st_mtime_ns:
            raise SystemExit(f"Stale build artifact: {name}")
    log = (OUTPUT / "m68000.log").read_text()
    if re.search(r"WARNING[^\n]*(\[SDC[^\n]*m68000\.sdc|cannot be used with reference pin)", log):
        raise SystemExit("A project timing constraint was ignored; inspect m68000.log")
    slacks = check_clock_relationships((OUTPUT / "m68000.timing.rpt").read_text())

    assigned = {}
    for line in (OUTPUT / "m68000.pinout.rpt").read_text().splitlines():
        columns = [column.strip() for column in line.split("|")]
        if len(columns) > 3:
            assigned[columns[1]] = columns[2]
    expected = re.findall(r'assign_pkg_pin\("([^"]+)", "([^"]+)"\)',
                          (PROJECT / "m68000.isf").read_text())
    for signal, pin in expected:
        if signal not in assigned.get(pin, ""):
            raise SystemExit(f"Pin gate failed: expected {signal} at {pin}, found {assigned.get(pin)}")

    bitstream = OUTPUT / "m68000.hex.bin"
    if b"Width: 4" not in bitstream.read_bytes():
        raise SystemExit("Not a passive-x4 bitstream")
    resources = (OUTPUT / "m68000.place.rpt").read_text()
    ram = re.search(r"Memory Blocks:\s*(\d+)\s*/\s*(\d+)", resources)
    if not ram or int(ram[1]) > int(ram[2]):
        raise SystemExit("Invalid block RAM utilization")
    receipt = {
        "bitstream_sha256": digest(bitstream),
        "bitstream_bytes": bitstream.stat().st_size,
        "timing_report_sha256": digest(OUTPUT / "m68000.timing.rpt"),
        "peripheral_timing_report_sha256": digest(OUTPUT / "m68000.pt_timing.rpt"),
        "constrained_slacks_ns": slacks,
        "checked_package_assignments": len(expected),
        "source_sha256": manifest["source_sha256"],
        "capture_storage": "bram",
        "scope_abi": 4,
        "capture_capacity_records": 32768,
        "memory_blocks_used": int(ram[1]),
        "memory_blocks_available": int(ram[2]),
        "socket_electrical_timing_qualified": False,
    }
    destination = OUTPUT.parent / "receipt.json"
    destination.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Timing/pin gates passed; {destination}")


if __name__ == "__main__":
    main()
