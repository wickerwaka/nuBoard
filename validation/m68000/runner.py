from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard

ROOT = Path(__file__).resolve().parents[2]
CORE_REVISION = "1217ab8dc600de070c6adb71ea6fe69de8855362"
CORE_BUILD = 14
MUSASHI_REVISION = "313ebf1bd9f4d0d93341eb5ce21fd8a119e9dbdd"
MODES = {"model": 1, "socket": 2, "both": 3}


class SimulationTransport:
    def __init__(self, spi=False, dual=False):
        variant = "dual" if dual else "spi" if spi else "direct"
        top = "m68000_dual_sim" if dual else "nuboard_m68000" if spi else "m68000_harness"
        self.process = subprocess.Popen(
            [str(ROOT / f"build/fpga/m68000/verilator-{variant}/V{top}")],
            cwd=ROOT / "build/deps/fx68k/hdl",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def exchange(self, data: bytes) -> bytes:
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        self.process.stdin.flush()
        header = self.process.stdout.read(4)
        if len(header) != 4:
            raise RuntimeError("Verilator process exited without a response")
        length = struct.unpack("<I", header)[0]
        if length > 4096:
            raise RuntimeError("invalid simulator framing")
        result = self.process.stdout.read(length)
        if len(result) != length:
            raise RuntimeError("truncated simulator response")
        return result

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.process.stdout.close()


@dataclass
class Transaction:
    start: int
    address: int
    data: int
    flags: int
    end: int

    @property
    def functional(self):
        lane_mask = (0xFF00 if self.flags & 2 else 0) | (0x00FF if self.flags & 1 else 0)
        return self.address, self.data & lane_mask, self.flags


def compare_traces(reference, candidate):
    differences = []
    timing = []
    if len(reference) != len(candidate):
        differences.append({"kind": "length", "reference": len(reference), "candidate": len(candidate)})
    for index, (left, right) in enumerate(zip(reference, candidate)):
        if left.functional != right.functional:
            differences.append({"index": index, "reference": asdict(left), "candidate": asdict(right)})
        # Reset exit latency may differ; subsequent relative timing is explicit.
        if ((left.start - reference[0].start, left.end - left.start) !=
                (right.start - candidate[0].start, right.end - right.start)):
            timing.append(index)
    return {"functional_match": not differences, "differences": differences,
            "timing_match": not timing and len(reference) == len(candidate),
            "timing_difference_indices": timing}


class Harness:
    def __init__(self, debug: DebugClient):
        self.debug = debug
        if struct.unpack("<HH", debug.read(0, 4)) != (0x6830, 1):
            raise RuntimeError("unexpected 68000 harness identity or ABI")

    def load(self, segments: dict[int, bytes], extra_pages=()):
        self.image = (segments, extra_pages)
        pages = set(extra_pages)
        for address, data in segments.items():
            if address < 0 or address + len(data) > 0x1000000:
                raise ValueError("program segment outside the 68000 address space")
            if not data:
                continue
            pages.update(range(address >> 12, ((address + len(data) - 1) >> 12) + 1))
        ordered = sorted(pages)
        if any(not 0 <= page < 4096 for page in ordered):
            raise ValueError("page outside the 68000 address space")
        if len(ordered) > 16:
            raise ValueError("image exceeds the sixteen independently mapped 4 KiB pages")
        images = {page: bytearray(4096) for page in ordered}
        for address, data in segments.items():
            for offset, value in enumerate(data):
                target = address + offset
                images[target >> 12][target & 4095] = value
        mapping = [(0x8000 | ordered[slot]) if slot < len(ordered) else 0
                   for slot in range(16)]
        self.debug.write(0x40, struct.pack("<16H", *mapping))
        # The host-write port initializes both independent lane memories.
        # Clear every mapped byte, including stack/results and segment holes,
        # before uploading only the nonzero span of each page.
        if ordered:
            self.debug.fill(0x10000, len(ordered) * 4096)
        for slot, page in enumerate(ordered):
            # Debug words are little endian; the CPU memory is big endian.
            words = images[page]
            encoded = bytearray(len(words))
            encoded[0::2] = words[1::2]
            encoded[1::2] = words[0::2]
            nonzero = [index for index, value in enumerate(encoded) if value]
            if nonzero:
                first = nonzero[0] & ~1
                end = (nonzero[-1] + 2) & ~1
                self.debug.write(0x10000 + slot * 4096 + first, encoded[first:end])
        self.pages = ordered

    def trace(self, lane: str):
        count = self.debug.read16(0x14 if lane == "model" else 0x16)
        if count > 2048:
            raise RuntimeError("invalid trace count")
        if not count:
            return []
        raw = self.debug.read(0x30000 if lane == "model" else 0x40000, count * 16)
        return [Transaction(*record) for record in struct.iter_unpack("<IIHHI", raw)]

    def read_memory(self, lane: str, address: int, length: int):
        """Read CPU byte order, including unaligned byte-sized observations."""
        result = bytearray()
        while length:
            page, offset = divmod(address, 4096)
            slot = self.pages.index(page)
            count = min(length, 4096 - offset)
            first = offset & ~1
            last = (offset + count + 1) & ~1
            base = 0x10000 if lane == "model" else 0x20000
            raw = self.debug.read(base + slot * 4096 + first, last - first)
            ordered = bytearray(len(raw))
            ordered[0::2] = raw[1::2]
            ordered[1::2] = raw[0::2]
            result.extend(ordered[offset - first:offset - first + count])
            address += count
            length -= count
        return bytes(result)

    def run(self, mode="model", limit=50_000_000, capture_start=0):
        self.debug.write(0x2A, struct.pack("<I", capture_start))
        self.debug.write(0x0C, struct.pack("<I", limit))
        self.debug.write16(4, (MODES[mode] << 8) | 2)
        status = self.debug.wait16(6, 2, 2, limit + 100_000)
        model = self.trace("model") if MODES[mode] & 1 else []
        socket = self.trace("socket") if MODES[mode] & 2 else []
        # These registers are contiguous and stable after completion. Read
        # them in one exchange, without crossing into unrelated scope/control.
        registers = self.debug.read(0x08, 0x22)

        def register(address, format):
            return struct.unpack_from(format, registers, address - 0x08)[0]

        result = {
            "status": status,
            "model_result": (status >> 2) & 3,
            "socket_result": (status >> 4) & 3,
            "timeout": bool(status & 128),
            "overflow": bool(status & 64),
            "clock_divider": register(0x08, "<H"),
            "wait_ticks": register(0x0A, "<H"),
            "elapsed_ticks": register(0x10, "<I"),
            "socket_pins_after_run": register(0x18, "<H"),
            "capture_start": capture_start,
            "model_total": register(0x1A, "<I"),
            "socket_total": register(0x1E, "<I"),
            "model_signature": register(0x22, "<I"),
            "socket_signature": register(0x26, "<I"),
            "model_trace": [asdict(t) for t in model],
            "socket_trace": [asdict(t) for t in socket],
        }
        result["passed"] = not status & 192 and all(
            result[f"{lane}_result"] == 1
            for lane, bit in (("model", 1), ("socket", 2)) if MODES[mode] & bit
        )
        if mode == "both":
            result["comparison"] = compare_traces(socket, model)
            result["passed"] &= result["comparison"]["functional_match"]
            result["passed"] &= result["model_total"] == result["socket_total"]
        result["trace_complete"] = all(
            result[f"{lane}_total"] <= len(result[f"{lane}_trace"])
            for lane, bit in (("model", 1), ("socket", 2)) if MODES[mode] & bit
        )
        return result

    def run_complete(self, mode="model"):
        """Replay deterministic images to capture every transaction for comparison.

        Single-lane suite runs retain a bounded diagnostic window. Differential
        runs cannot pass by comparing only that prefix: every window is read.
        """
        result = self.run(mode)
        if mode != "both" or not result["passed"]:
            return result
        segments, extra_pages = self.image
        for start in range(2048, result["model_total"], 2048):
            self.load(segments, extra_pages)
            window = self.run(mode, capture_start=start)
            for lane in ("model", "socket"):
                for field in ("total", "signature"):
                    if window[f"{lane}_{field}"] != result[f"{lane}_{field}"]:
                        result["passed"] = False
                        result["replay_error"] = f"{lane} {field} changed at window {start}"
                        return result
                result[f"{lane}_trace"].extend(window[f"{lane}_trace"])
            result["passed"] &= window["passed"]
            if not result["passed"]:
                result["failed_window"] = window
                return result
        reference = [Transaction(**row) for row in result["socket_trace"]]
        candidate = [Transaction(**row) for row in result["model_trace"]]
        result["comparison"] = compare_traces(reference, candidate)
        result["trace_complete"] = True
        result["passed"] &= result["comparison"]["functional_match"]
        return result


def musashi_image(binary: bytes):
    vectors = bytearray(struct.pack(">I", 0xDEADBEEF) * 256)
    struct.pack_into(">II", vectors, 0, 0x3F0, 0x10000)
    return {0: bytes(vectors), 0x10000: binary}


def main():
    parser = argparse.ArgumentParser(description="Run identical 68000 programs in simulation or on nuBoard")
    parser.add_argument("--backend", choices=("sim", "spi-sim", "board"), default="sim")
    parser.add_argument("--mode", choices=MODES, default="model")
    parser.add_argument("--socket-fitted", action="store_true",
                        help="confirm the MC68000P12 daughterboard is installed; permits DUT power")
    parser.add_argument("--suite", type=Path, default=ROOT / "build/validation/m68000/programs")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--vectors", type=Path,
                        help="decoded SingleStepTests/m68000 MOVE.q JSON instead of Musashi")
    parser.add_argument("--limit", type=int, default=100,
                        help="maximum single-step cases (default: 100)")
    parser.add_argument("--output", type=Path, default=ROOT / "build/validation/m68000/results.json")
    args = parser.parse_args()
    if args.backend != "board" and args.mode != "model":
        parser.error("the socket is only available with --backend board")
    if args.mode != "model" and not args.socket_fitted:
        parser.error("socket modes require --socket-fitted and the installed MC68000P12")
    if args.vectors and (args.only or args.limit <= 0):
        parser.error("--vectors requires a positive --limit and cannot be combined with --only")

    subprocess.run([sys.executable, str(ROOT / "tools/fetch_m68000.py"), "--verify-only"],
                   check=True)
    program_manifest = None
    if not args.vectors and args.suite == ROOT / "build/validation/m68000/programs":
        program_manifest = json.loads((args.suite / "manifest.json").read_text())
        if program_manifest["march"] != "68000":
            raise RuntimeError("test programs were not built for the 68000 ISA")
        for path in args.suite.glob("*.bin"):
            if hashlib.sha256(path.read_bytes()).hexdigest() != program_manifest["binaries"].get(path.name):
                raise RuntimeError(f"test program differs from build manifest: {path.name}")

    transport = None
    reports = []
    board_state = None
    completed = False
    failure = None
    cleanup_error = None
    vector_digest = None
    try:
        transport = NuBoard() if args.backend == "board" else SimulationTransport(args.backend == "spi-sim")
        if args.backend == "board":
            state = json.loads(transport.state())
            board_state = state
            if not state["link"]:
                raise RuntimeError("configure the m68000 harness bitstream first")
            if state["core_uuid"] != b"nuBoard-68000-v1".hex():
                raise RuntimeError("configured core is not the 68000 harness")
            if state["core_build"] != CORE_BUILD:
                raise RuntimeError(f"optimized debug access requires build {CORE_BUILD}")
            if state["vccb"]:
                raise RuntimeError("start from a freshly configured harness with VCCB off")
            exchange = lambda data: transport.fpga_exchange(CHANNEL, data)
        else:
            exchange = transport.exchange
        harness = Harness(DebugClient(exchange))
        if args.mode != "model":
            if state["selector_mv"] != 5000:
                raise RuntimeError("MC68000P12 requires the exclusive 5 V selector")
            transport.vccb_enable()
            harness.debug.write16(4, 1)
            time.sleep(0.01)  # Continuous clock and reset while DUT power settles.
        if args.vectors:
            vector_bytes = args.vectors.read_bytes()
            vector_digest = hashlib.sha256(vector_bytes).hexdigest()
            files = json.loads(vector_bytes)[:args.limit]
        else:
            files = sorted(args.suite.glob("*.bin"))
        if args.only:
            unknown = set(args.only) - {path.stem for path in files}
            if unknown:
                raise ValueError(f"unknown test names: {', '.join(sorted(unknown))}")
            files = [path for path in files if path.stem in args.only]
        if not files:
            raise RuntimeError("no test binaries selected")
        for path in files:
            if args.vectors:
                from .singlestep import UnsupportedVector, check_result, make_image
                name = path["name"]
                binary = json.dumps(path, sort_keys=True).encode()
                try:
                    segments, pages = make_image(path)
                except UnsupportedVector as exc:
                    reports.append({"name": name, "passed": None, "skipped": str(exc)})
                    print(f"{name}: SKIP {exc}", flush=True)
                    continue
            else:
                name = path.stem
                binary = path.read_bytes()
                segments, pages = musashi_image(binary), (0x300, 0x30F)
            harness.load(segments, pages)
            result = harness.run_complete(args.mode)
            if args.vectors and result["passed"]:
                result["architectural_checks"] = {}
                for lane, bit in (("model", 1), ("socket", 2)):
                    if MODES[args.mode] & bit:
                        check = check_result(harness, lane, path)
                        result["architectural_checks"][lane] = check
                        result["passed"] &= check["passed"]
            result.update(name=name, stimulus_sha256=hashlib.sha256(binary).hexdigest())
            reports.append(result)
            print(f"{name}: {'PASS' if result['passed'] else 'FAIL'} "
                  f"status=0x{result['status']:04x} "
                  f"transactions={len(result['model_trace'])}/{len(result['socket_trace'])}", flush=True)
            if args.mode == "both" and not result["passed"]:
                break  # Stop physical differential work on the first failure.
        completed = len(reports) == len(files)
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if transport is not None:
            try:
                if args.backend == "board":
                    transport.power_off()
            except Exception as exc:
                cleanup_error = f"power-off failed: {exc}"
            finally:
                try:
                    transport.close()
                except Exception as exc:
                    cleanup_error = f"{cleanup_error or ''}; transport close failed: {exc}"
        if cleanup_error:
            print(cleanup_error, file=sys.stderr)
        completed = completed and failure is None and cleanup_error is None
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "backend": args.backend, "mode": args.mode,
            "completed": completed, "board_state_before_run": board_state,
            "error": failure, "cleanup_error": cleanup_error,
            "cpu_marking": "MC68000P12" if args.mode != "model" else None,
            "fx68k_revision": CORE_REVISION, "musashi_revision": MUSASHI_REVISION,
            "suite": "SingleStepTests MOVE.q" if args.vectors else "Musashi mc68000",
            "vector_file_sha256": vector_digest,
            "program_manifest": program_manifest,
            "tests": reports,
        }, indent=2) + "\n")
    executed = [item for item in reports if "skipped" not in item]
    return 0 if completed and executed and all(item["passed"] for item in executed) else 1


if __name__ == "__main__":
    sys.exit(main())
