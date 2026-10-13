"""Does an opcode stop the clock? CLKOUT after the last bus cycle.

    python -m validation.v35s.stop_probe --socket-fitted [OPCODE_HEX ...]

Each opcode runs after the characterize prelude (CLKOUT on P07, fX/2, zero
waits, refresh on) with the scope armed. HALT and STOP (0F 9E) are the
references: in HALT CLKOUT and refresh continue; STOP stops the oscillator,
so CLKOUT stops too. For each opcode the report gives the last bus cycle,
the last CLKOUT edge, and the CLKOUT edges counted after the last bus cycle.

Results: build/validation/v35s/stop_probe.json.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .asm import assemble
from .characterize import program
from .runner import FLAG_REFRESH, ROOT, Transaction, open_board, reset_image
from .scope import Scope, edges

REFERENCES = {"HALT": "F4", "STOP": "0F 9E"}
DEFAULT = ["0F 21", "0F 24", "0F 30", "0F 93", "0F 96", "0F FF", "0F 80"]
LIMIT = 200_000


def body(opcode: str) -> str:
    raw = ", ".join(f"0x{b}" for b in opcode.split())
    return ("    MOV CW, 4\nw:\n    NOP\n    DBNZ w\n"
            f"    DB {raw}, 0xC0, 0x90, 0x90, 0x90, 0x90\n"
            "    MOV DW, 0FF00h\n    OUT DW, AW\n    HALT\n")


def run_one(harness, opcode: str):
    source = program(prc=0x4C, wtc=0x0000, rfm=0xFC).split("    XOR AW, AW")[0] + body(opcode)
    harness.configure(x_half=2)
    harness.load(reset_image(assemble(source, org=0x100)))
    scope = Scope(harness.debug)
    scope.configure("socket")
    result = harness.run("socket", LIMIT)
    capture = scope.download()
    trace = [Transaction(**row) for row in result["socket_trace"]]
    memory = [t for t in trace if not t.flags & FLAG_REFRESH]
    refresh = [t for t in trace if t.flags & FLAG_REFRESH]
    last_bus = memory[-1].start if memory else 0
    clock = [e.tick for e in edges(capture, ["clkout"])]
    return {
        "opcode": opcode, "status": result["status"], "passed": result["passed"],
        "elapsed_ticks": result["elapsed_ticks"], "capture_complete": capture.complete,
        "last_bus": memory[-1].describe() if memory else None,
        "last_bus_tick": last_bus,
        "refresh_after_last_bus": sum(1 for t in refresh if t.start > last_bus),
        "clkout_edges_after_last_bus": sum(1 for t in clock if t > last_bus),
        "last_clkout_tick": clock[-1] if clock else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--socket-fitted", action="store_true", required=True)
    parser.add_argument("opcodes", nargs="*")
    parser.add_argument("--output", type=Path, default=ROOT / "build/validation/v35s/stop_probe.json")
    args = parser.parse_args()
    opcodes = list(REFERENCES.values()) + (args.opcodes or DEFAULT)
    transport, harness, state = open_board(True)
    report = {"board_state": state, "runs": []}
    try:
        transport.vccb_enable()
        harness.arm()
        time.sleep(0.05)
        for opcode in opcodes:
            row = run_one(harness, opcode)
            report["runs"].append(row)
            print(f"{opcode:<6} passed={row['passed']} last bus {row['last_bus_tick']} "
                  f"refresh after {row['refresh_after_last_bus']} clkout edges after "
                  f"{row['clkout_edges_after_last_bus']} last clkout {row['last_clkout_tick']} "
                  f"complete={row['capture_complete']}", flush=True)
    finally:
        try:
            harness.arm(False)
            transport.power_off()
        finally:
            transport.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
