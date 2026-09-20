"""Build, run, and compare bounded silicon/fx68k differential campaigns."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from nuboard.debug import CHANNEL, MAX_TRANSFER, DebugClient
from nuboard.device import NuBoard

from .corpus import DEFERRED, build_case, cases, defined_sr_mask, snapshot, toolchain
from .phase import compare, compare_state, draw_svg
from .runner import CORE_BUILD, CORE_REVISION, ROOT, Harness, SimulationTransport
from .scope import Scope

DEFAULT = ROOT / "build/validation/m68000/campaign"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def read_test(report_path, entry):
    if "artifact" not in entry:
        return entry
    path = report_path.parent / entry["artifact"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["artifact_sha256"]:
        raise ValueError(f"modified run artifact: {path}")
    return json.loads(raw)


def save_test(report_path, entry):
    if "artifact" in entry:
        return entry
    path = report_path.with_suffix("") / "cases" / f"{entry['name']}.json"
    write_json(path, entry)
    return {key: entry[key] for key in ("name", "stimulus_sha256", "passed")} | {
        "artifact": str(path.relative_to(report_path.parent)),
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build(args):
    selected = [case for case in cases(args.profile, args.seed)
                if not args.case or case.name in args.case]
    if not selected or args.case and set(args.case) - {case.name for case in selected}:
        raise ValueError("empty selection or unknown case")
    tools, environment = toolchain()
    manifest = {"schema": 1, "profile": args.profile, "seed": args.seed,
                "march": "68000", "fx68k_revision": CORE_REVISION,
                "assembler": subprocess.check_output([tools["as"], "--version"],
                                                      env=environment, text=True).splitlines()[0],
                "generator_sha256": hashlib.sha256(
                    (ROOT / "validation/m68000/corpus.py").read_bytes()).hexdigest(),
                "deferred": DEFERRED, "cases": []}
    for index, case in enumerate(selected):
        try:
            artifact = build_case(case, args.directory / "programs")
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"{case.name}: {exc.stderr.decode()}") from exc
        path = args.directory / "cases" / f"{case.name}.json"
        write_json(path, artifact)
        manifest["cases"].append({**asdict(case), "path": str(path.relative_to(args.directory)),
                                  "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                  "stimulus_sha256": artifact["sha256"]})
        if index % 100 == 0:
            print(f"built {index + 1}/{len(selected)}: {case.name}", flush=True)
    write_json(args.directory / "manifest.json", manifest)
    print(f"Built {len(selected)} cases: {args.directory / 'manifest.json'}")
    return 0


def load_manifest(directory, selected):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["schema"] != 1 or manifest["march"] != "68000":
        raise ValueError("unsupported corpus manifest")
    entries = [entry for entry in manifest["cases"] if not selected or entry["name"] in selected]
    if not entries or selected and set(selected) - {entry["name"] for entry in entries}:
        raise ValueError("empty selection or unknown case")
    artifacts = []
    for entry in entries:
        path = directory / entry["path"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["artifact_sha256"]:
            raise ValueError(f"modified corpus artifact: {path}")
        artifact = json.loads(data)
        if artifact["sha256"] != entry["stimulus_sha256"]:
            raise ValueError("stimulus identity mismatch")
        artifacts.append(artifact)
    return manifest, artifacts


def compare_runs(reference, candidate, artifact):
    sr_mask = defined_sr_mask(artifact["case"])
    state = compare_state(reference["state"], candidate["state"], sr_mask)
    state.update(sr_defined_mask=sr_mask, flags_policy_version=2)
    # Undefined flags copied into reporting RAM must not become bogus timing
    # failures. Preserve the raw bus values and expose the exact masks applied.
    data_masks = {0x5040: sr_mask}
    left_state, right_state = reference["state"], candidate["state"]
    if (left_state["vector"] == right_state["vector"] and
            left_state["ssp_at_collector"] == right_state["ssp_at_collector"]):
        frame = left_state["ssp_at_collector"]
        if left_state["vector"] == 3:
            data_masks[frame] = 0x001F
            data_masks[frame + 8] = sr_mask
        elif left_state["vector"]:
            data_masks[frame] = sr_mask
    timing = compare(reference, candidate, data_masks)
    vector = artifact["case"]["vector"]
    expected = {name: run["state"]["vector"] == vector
                for name, run in (("reference", reference), ("candidate", candidate))}
    passed = state["defined"] == "pass" and timing["verdict"] == "pass" and all(expected.values())
    return {"passed": passed, "state": state, "timing": timing,
            "expected_vector": vector, "expected_vector_matches": expected}


def simulator_provenance(target):
    spi = target == "spi-sim"
    variant = "spi" if spi else "direct"
    top = "nuboard_m68000" if spi else "m68000_harness"
    executable = ROOT / f"build/fpga/m68000/verilator-{variant}/V{top}"
    project = ROOT / "fpga/m68000"
    names = ["m68000_lane.sv", "m68000_scope.sv", "scope_encoder.sv", "m68000_harness.sv",
             "sim_spi_main.cpp" if spi else "sim_main.cpp"]
    if spi:
        names += ["nuboard_m68000.v", "nuboard_mailbox.v", "nuboard_debug_bridge.sv"]
    sources = [project / name for name in names]
    sources += [ROOT / "build/deps/fx68k/hdl/verilator" / name
                for name in ("fx68k.sv", "fx68kAlu.sv", "uaddrPla.sv")]
    if any(path.stat().st_mtime > executable.stat().st_mtime for path in sources):
        raise RuntimeError("stale simulator: rebuild with fpga/m68000/build_sim.sh")
    return {"executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sources}}


def run(args):
    if args.target == "board-pair" and not args.socket_fitted:
        raise ValueError("board-pair requires --socket-fitted")
    manifest, artifacts = load_manifest(args.directory, args.case)
    total_selected = len(artifacts)
    artifacts = artifacts[args.shard_index::args.shard_count]
    start_index = getattr(args, "start_index", 0)
    if not 0 <= start_index < len(artifacts):
        raise ValueError("start index outside selected shard")
    artifacts = artifacts[start_index:]
    if not artifacts:
        raise ValueError("empty shard")
    reference = None
    if args.reference:
        reference = json.loads(args.reference.read_text())
        if not reference["completed"]:
            raise ValueError("incomplete reference campaign")
    report = {"schema": 1, "target": args.target,
              "manifest": {key: value for key, value in manifest.items() if key != "cases"},
              "selected_cases": len(artifacts),
              "total_selected_cases": total_selected,
              "shard_index": args.shard_index, "shard_count": args.shard_count,
              "manifest_sha256": hashlib.sha256((args.directory / "manifest.json").read_bytes()).hexdigest(),
              "cpu_marking": "MC68000P12" if args.target == "board-pair" else None,
              "fx68k_revision": CORE_REVISION, "completed": False, "tests": [],
              "error": None, "cleanup_error": None, "mismatching_cases": 0}
    duration = getattr(args, "duration_seconds", None)
    report.update(start_index=start_index, duration_seconds=duration,
                  finished_cases=0, next_case_index=start_index,
                  debug_transfer_bytes=MAX_TRANSFER,
                  initialization="broadcast fill and sparse upload once per repetition")
    report["qualification"] = ("differential" if args.target == "board-pair" or args.reference
                               else "wrapper completion and expected exception only")
    report["started_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report["implementation_sha256"] = {
        name: hashlib.sha256((ROOT / "validation/m68000" / name).read_bytes()).hexdigest()
        for name in ("campaign.py", "corpus.py", "phase.py", "scope.py", "runner.py")}
    report["debug_client_sha256"] = hashlib.sha256(
        (ROOT / "host/src/nuboard/debug.py").read_bytes()).hexdigest()
    transport = None
    board = args.target.startswith("board")
    started = time.monotonic()
    try:
        subprocess.run([sys.executable, str(ROOT / "tools/fetch_m68000.py"), "--verify-only"],
                       check=True, capture_output=True)
        if not board:
            report["simulator"] = simulator_provenance(args.target)
        transport = NuBoard() if board else SimulationTransport(args.target == "spi-sim")
        if board:
            state = json.loads(transport.state())
            receipt = json.loads((ROOT / "build/fpga/m68000/receipt.json").read_text())
            report.update(board_state=state, build_receipt=receipt)
            if (state["vccb"] or not state["link"] or state["core_build"] != CORE_BUILD or
                    state["core_uuid"] != b"nuBoard-68000-v1".hex() or
                    state["sha256"] != receipt["bitstream_sha256"]):
                raise RuntimeError(f"requires receipt-matched build {CORE_BUILD} with VCCB off")
            exchange = lambda data: transport.fpga_exchange(CHANNEL, data)
        else:
            exchange = transport.exchange
        debug = DebugClient(exchange)
        harness = Harness(debug)
        scope = Scope(debug)
        if (debug.read16(8), debug.read16(10)) != (5, 8):
            raise RuntimeError("CPU clock/ACK settings differ from qualification")
        lanes = ("model", "socket") if args.target == "board-pair" else ("model",)
        if args.target == "board-pair":
            if state["selector_mv"] != 5000:
                raise RuntimeError("MC68000P12 requires exclusive 5 V")
            transport.vccb_enable()
            debug.write16(4, 1)
            time.sleep(0.01)
        for artifact in artifacts:
            # Finish an in-flight case, then stop before starting another one.
            # Normal finally cleanup still powers down and verifies the rails.
            if duration is not None and time.monotonic() - started >= duration:
                report["stop_reason"] = "time budget"
                break
            entry = {"name": artifact["case"]["name"], "stimulus_sha256": artifact["sha256"],
                     "runs": [], "comparisons": [], "passed": True}
            report["tests"].append(entry)
            for repeat in range(args.repeats):
                trial = {}
                # One broadcast initialization per repetition. Each lane has
                # private RAM; running/resetting one does not modify the other.
                harness.load({int(address): bytes.fromhex(data)
                              for address, data in artifact["segments"].items()}, artifact["extra_pages"])
                for lane in lanes:
                    scope.configure(lane)
                    result = harness.run(lane, limit=500_000)
                    capture = scope.download()
                    item = {"lane": lane, "repeat": repeat, "result": result,
                            "trace": result[f"{lane}_trace"], "capture": capture.report()}
                    entry["runs"].append(item)
                    if not result["passed"] or not result["trace_complete"] or not capture.complete:
                        raise RuntimeError(f"{entry['name']} {lane}: run/capture incomplete; stopping")
                    item["state"] = snapshot(harness, lane)
                    trial[lane] = item
                    entry["passed"] &= item["state"]["vector"] == artifact["case"]["vector"]
                if "socket" in trial:
                    comparison = compare_runs(trial["socket"], trial["model"], artifact)
                    entry["comparisons"].append(comparison)
                    entry["passed"] &= comparison["passed"]
                    if comparison["timing"]["verdict"] == "indeterminate":
                        raise RuntimeError(f"{entry['name']}: unresolved sampling boundary; stopping")
                if reference is not None:
                    matches = [row for row in reference["tests"] if row["name"] == entry["name"]
                               and row["stimulus_sha256"] == entry["stimulus_sha256"]]
                    if len(matches) != 1:
                        raise ValueError("missing or different reference stimulus")
                    reference_case = read_test(args.reference, matches[0])
                    reference_run = next(row for row in reference_case["runs"] if row["lane"] == "model")
                    comparison = compare_runs(reference_run, trial["model"], artifact)
                    comparison["kind"] = "simulation_vs_board_model"
                    entry["comparisons"].append(comparison)
                    entry["passed"] &= comparison["passed"]
                if repeat and any(item["state"] != entry["runs"][index]["state"]
                                  for index, item in enumerate(trial.values())):
                    raise RuntimeError(f"{entry['name']}: planned repetitions are nondeterministic")
                if repeat:
                    for index, item in enumerate(trial.values()):
                        repeated = compare(entry["runs"][index], item)
                        if repeated["verdict"] != "pass":
                            raise RuntimeError(f"{entry['name']}: repeated lane timing changed or unresolved")
            if not entry["passed"]:
                report["mismatching_cases"] += 1
                for index, comparison in enumerate(entry["comparisons"]):
                    path = args.output.parent / "waveforms" / f"{entry['name']}-{index}.svg"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    draw_svg(comparison["timing"], path, entry["name"])
                entry["reproduce"] = (f"python -m validation.m68000.campaign run --directory {args.directory} "
                                      f"--target {args.target} --case {entry['name']} --repeats 3 "
                                      "--socket-fitted --output reproduce.json")
            print(f"{entry['name']}: {'PASS' if entry['passed'] else 'DIFFERENCE'}", flush=True)
            # Persist after every case, before continuing a potentially long campaign.
            report["tests"][-1] = save_test(args.output, entry)
            report["finished_cases"] += 1
            report["next_case_index"] = start_index + report["finished_cases"]
            write_json(args.output, report)
            if report["mismatching_cases"] >= args.max_mismatches:
                report["stop_reason"] = "mismatch limit"
                break
        report["completed"] = len(report["tests"]) == len(artifacts)
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(report["error"], file=sys.stderr)
    finally:
        if transport is not None:
            try:
                if board:
                    transport.power_off()
                    time.sleep(0.02)
                    report["shutdown_state"] = json.loads(transport.state())
                    if any(report["shutdown_state"][key] for key in ("vccb", "rail_1v2", "rail_3v3")):
                        raise RuntimeError("rails remain enabled")
            except Exception as exc:
                report["cleanup_error"] = str(exc)
            finally:
                try:
                    transport.close()
                except Exception as exc:
                    report["cleanup_error"] = f"{report['cleanup_error'] or ''}; close: {exc}"
        report["completed"] &= report["error"] is None and report["cleanup_error"] is None
        report["tests"] = [save_test(args.output, entry) for entry in report["tests"]]
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["elapsed_seconds"] = time.monotonic() - started
        report["chunk_completed"] = (report.get("stop_reason") == "time budget" and
                                     report["error"] is None and report["cleanup_error"] is None)
        report["next_case_name"] = (artifacts[report["finished_cases"]]["case"]["name"]
                                    if report["finished_cases"] < len(artifacts) else None)
        write_json(args.output, report)
    successful_stop = report["completed"] or report["chunk_completed"]
    return 0 if successful_stop and all(row["passed"] for row in report["tests"]) else 1


def offline(args):
    """Re-evaluate saved evidence without accessing hardware or rerunning CPUs."""
    reference = json.loads(args.reference.read_text())
    candidate = json.loads(args.candidate.read_text())
    _, artifacts = load_manifest(args.directory, args.case)
    results = []
    for artifact in artifacts:
        name = artifact["case"]["name"]
        runs = []
        for path, report, lane in ((args.reference, reference, args.reference_lane),
                                   (args.candidate, candidate, args.candidate_lane)):
            matches = [entry for entry in report["tests"] if entry["name"] == name]
            if len(matches) != 1 or matches[0]["stimulus_sha256"] != artifact["sha256"]:
                raise ValueError(f"missing or incompatible stimulus: {name}")
            entry = read_test(path, matches[0])
            runs.append(next(run for run in entry["runs"] if run["lane"] == lane))
        comparison = compare_runs(*runs, artifact)
        results.append({"name": name, **comparison})
        if comparison["timing"]["verdict"] != "pass":
            svg = args.output.with_suffix("") / f"{name}.svg"
            svg.parent.mkdir(parents=True, exist_ok=True)
            draw_svg(comparison["timing"], svg, name)
    write_json(args.output, {"schema": 1, "comparisons": results})
    return 0 if all(item["passed"] for item in results) else 1


def merge(args):
    reports = [(path, json.loads(path.read_text())) for path in args.reports]
    first = reports[0][1]
    count = first["shard_count"]
    if (len(reports) != count or
            {report["shard_index"] for _, report in reports} != set(range(count))):
        raise ValueError("missing or duplicate shard")
    merged = {key: value for key, value in first.items() if key not in ("tests", "shard_index")}
    merged["tests"] = []
    for path, report in reports:
        if not report["completed"] or any(report[key] != first[key] for key in (
                "manifest_sha256", "target", "shard_count", "total_selected_cases")):
            raise ValueError("incomplete or incompatible shard")
        for entry in report["tests"]:
            read_test(path, entry)  # Verify persisted evidence, not only the index.
            entry = dict(entry)
            entry["artifact"] = os.path.relpath(path.parent / entry["artifact"], args.output.parent)
            merged["tests"].append(entry)
    names = {entry["name"] for entry in merged["tests"]}
    if len(names) != len(merged["tests"]) or len(names) != first["total_selected_cases"]:
        raise ValueError("duplicate or missing test cases across shards")
    merged["selected_cases"] = len(names)
    merged["mismatching_cases"] = sum(not entry["passed"] for entry in merged["tests"])
    merged["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_json(args.output, merged)
    return 0 if not merged["mismatching_cases"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    builder.add_argument("--seed", type=int, default=68000)
    builder.add_argument("--directory", type=Path, default=DEFAULT)
    builder.add_argument("--case", nargs="+")
    runner = commands.add_parser("run")
    runner.add_argument("--directory", type=Path, default=DEFAULT)
    runner.add_argument("--target", choices=("sim", "spi-sim", "board-model", "board-pair"), default="sim")
    runner.add_argument("--socket-fitted", action="store_true")
    runner.add_argument("--case", nargs="+")
    runner.add_argument("--repeats", type=int, choices=(1, 2, 3), default=1)
    runner.add_argument("--max-mismatches", type=int, default=20)
    runner.add_argument("--reference", type=Path)
    runner.add_argument("--output", type=Path, required=True)
    runner.add_argument("--shard-count", type=int, default=1)
    runner.add_argument("--shard-index", type=int, default=0)
    runner.add_argument("--start-index", type=int, default=0,
                        help="resume at this index within the selected shard")
    runner.add_argument("--duration-seconds", type=float,
                        help="wall-clock budget; finish the current case, then power off")
    comparer = commands.add_parser("compare")
    comparer.add_argument("--directory", type=Path, default=DEFAULT)
    comparer.add_argument("--reference", type=Path, required=True)
    comparer.add_argument("--candidate", type=Path, required=True)
    comparer.add_argument("--reference-lane", choices=("model", "socket"), default="socket")
    comparer.add_argument("--candidate-lane", choices=("model", "socket"), default="model")
    comparer.add_argument("--case", nargs="+")
    comparer.add_argument("--output", type=Path, required=True)
    merger = commands.add_parser("merge")
    merger.add_argument("--reports", nargs="+", type=Path, required=True)
    merger.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run" and args.max_mismatches < 1:
        parser.error("--max-mismatches must be positive")
    if args.command == "run" and not 0 <= args.shard_index < args.shard_count:
        parser.error("shard index must be within a positive shard count")
    if args.command == "run" and args.duration_seconds is not None:
        if not math.isfinite(args.duration_seconds) or args.duration_seconds <= 0:
            parser.error("--duration-seconds must be finite and positive")
    return {"build": build, "run": run, "compare": offline, "merge": merge}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
