"""Bounded qualification of the imported register-only adapter in Verilator.

This compares against upstream functional expectations, not a silicon oracle.
Native campaign programs provide the separate physical/timing comparison.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from nuboard.debug import DebugClient

from .campaign import simulator_provenance, write_json
from .runner import ROOT, Harness, SimulationTransport
from .singlestep import REVISION, UnsupportedVector, check_result, make_image

INSTRUCTIONS = ("MOVE.q", "ADD.w", "SUB.w", "AND.w", "OR.w", "CMP.w")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "build/deps/m68000-vectors")
    parser.add_argument("--instructions", nargs="+", choices=INSTRUCTIONS, default=list(INSTRUCTIONS))
    parser.add_argument("--limit", type=int, default=100, help="eligible cases per instruction file")
    parser.add_argument("--max-mismatches", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.max_mismatches < 1:
        parser.error("limits must be positive")
    source_manifest = json.loads((args.directory / "manifest.json").read_text())
    if source_manifest["revision"] != REVISION:
        raise ValueError("unexpected upstream revision")
    required = ["LICENSE", "README.md", "decode.py"]
    required += [f"v1/{name}.json.bin" for name in args.instructions]
    for name in required:
        if hashlib.sha256((args.directory / name).read_bytes()).hexdigest() != source_manifest["files"].get(name):
            raise ValueError(f"unverified source file: {name}")
    report = {"schema": 1, "completed": False, "source_manifest": source_manifest,
              "reference": "MAME-generated SingleStepTests; not physical CPU",
              "prefetch_checked": False, "suite_bus_timing_checked": False,
              "files": [], "error": None, "mismatches": 0}
    transport = None
    try:
        report["simulator"] = simulator_provenance("sim")
        transport = SimulationTransport()
        harness = Harness(DebugClient(transport.exchange))
        harness.debug.write16(0x36, 0)
        for name in args.instructions:
            raw = (args.directory / f"v1/{name}.json").read_bytes()
            entry = {"instruction": name, "decoded_sha256": hashlib.sha256(raw).hexdigest(),
                     "tests": [], "skips_by_reason": {}}
            report["files"].append(entry)
            skips = Counter()
            for test in json.loads(raw):
                try:
                    segments, pages = make_image(test)
                except UnsupportedVector as exc:
                    skips[str(exc)] += 1
                    entry["skips_by_reason"] = dict(skips)
                    continue
                harness.load(segments, pages)
                run = harness.run("model")
                if not run["passed"]:
                    entry["failed_run"] = run
                    raise RuntimeError(f"{name}: CPU run incomplete")
                result = check_result(harness, "model", test)
                result.update(name=test["name"], stimulus_sha256=hashlib.sha256(
                    json.dumps(test, sort_keys=True).encode()).hexdigest())
                entry["tests"].append(result)
                report["mismatches"] += not result["passed"]
                if report["mismatches"] >= args.max_mismatches:
                    raise RuntimeError("upstream mismatch limit reached")
                if len(entry["tests"]) >= args.limit:
                    break
            entry["quota_met"] = len(entry["tests"]) == args.limit
            print(f"{name}: {len(entry['tests'])} eligible; {sum(skips.values())} skipped", flush=True)
            write_json(args.output, report)
        report["completed"] = all(entry["quota_met"] for entry in report["files"])
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if transport is not None:
            transport.close()
        write_json(args.output, report)
    return 0 if report["completed"] and report["mismatches"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
