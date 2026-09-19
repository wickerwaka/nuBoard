"""Draw the captured operand read/write cycles, excluding reset-vector cycles."""

from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path

from .draw_timing import export_vcd
from .timing import decode_capture

COLORS = {"model": "#1764ad", "socket": "#ba4c12"}
LABELS = {"model": "fx68k (FPGA)", "socket": "MC68000P12 (physical CPU)"}
CONTROL_SIGNALS = ("clock", "as_n", "uds_n", "lds_n", "dtack_n", "read")


def validate(report):
    if (report["backend"] != "board" or report.get("program") != "memory"
            or not report["completed"] or report["sample_period_ns"] != 20):
        raise ValueError("a completed physical memory-move capture is required")
    runs = report["runs"]
    reference = runs[0]
    samples = decode_capture(bytes.fromhex(reference["scope_hex"]))
    for run in runs:
        if not run["result"]["passed"] or not run["result"]["trace_complete"]:
            raise ValueError("functional bus comparison did not pass completely")
        if (run["result"]["clock_divider"], run["result"]["wait_ticks"]) != (5, 8):
            raise ValueError("capture does not use the documented clock/wait settings")
        observed = decode_capture(bytes.fromhex(run["scope_hex"]))
        for lane in ("model", "socket"):
            if run["ram_after"][lane] != "a55aa55a":
                raise ValueError("read/write RAM result differs")
            operands = run["operand_intervals"][lane]
            if operands != reference["operand_intervals"][lane]:
                raise ValueError("operand timing did not repeat identically")
            if [(row["address"], row["read"], row["data"], row["fc"]) for row in operands] != [
                (0x200, 1, 0xA55A, 5), (0x202, 0, 0xA55A, 5),
            ]:
                raise ValueError("capture is not the intended ordinary data read/write")
            for operand in operands:
                for tick in range(operand["start_tick"] - 4, operand["end_tick"] + 4):
                    for signal in (*CONTROL_SIGNALS, "address", "data", "fc"):
                        if observed[tick][lane][signal] != samples[tick][lane][signal]:
                            raise ValueError(f"non-repeating {lane} {signal} at sample {tick}")
    return samples


def render(report, digest):
    samples = validate(report)
    first = report["runs"][0]
    core_build = report["board_state_before_run"]["core_build"]
    direct_ack = core_build in (5, 6)
    ack_label = "DTACK_N *" if direct_ack else "ACK_INT_N *"
    ack_summary = "ACK" if direct_ack else "int.ACK"
    longest = max(row["as_low_ns"] for lane in ("model", "socket")
                  for row in first["operand_intervals"][lane])
    end_ns = max(1000, ((longest + 80 + 199) // 200) * 200)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1060" viewBox="0 0 1600 1060">',
        '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b43}</style>',
        '<rect width="1600" height="1060" fill="#f6f8fc"/>',
    ]

    def text(x, y, value, size=16, color="#172b43", anchor="start", bold=False):
        parts.append(
            f'<text x="{x:.2f}" y="{y}" font-size="{size}" text-anchor="{anchor}" '
            f'font-weight="{"bold" if bold else "normal"}" style="fill:{color}">'
            f'{escape(str(value))}</text>'
        )

    def line(x1, y1, x2, y2, color, width=1):
        parts.append(f'<line x1="{x1:.2f}" y1="{y1}" x2="{x2:.2f}" y2="{y2}" '
                     f'stroke="{color}" stroke-width="{width}"/>')

    text(40, 44, "Ordinary MOVE.W operand cycles — after reset", 29, bold=True)
    text(40, 75, f"{len(report['runs'])}/{len(report['runs'])} identical paired captures · 5 MHz · wait_ticks = 8 · FC = 5 (supervisor data)", 18)
    text(40, 103, "Every panel aligns its own operand AS falling edge to zero; the scale is identical across all four panels.", 17)

    for operation, top, heading in (
        (0, 156, "1 · MOVE.W $0200.W,D0 — memory READ"),
        (1, 564, "2 · MOVE.W D0,$0202.W — memory WRITE"),
    ):
        text(40, top - 14, heading, 20, bold=True)
        for lane, left in (("model", 30), ("socket", 815)):
            color = COLORS[lane]
            operand = first["operand_intervals"][lane][operation]
            origin = operand["start_tick"]
            start_tick = origin - 4
            end_tick = operand["end_tick"] + 4
            plot_left = left + 146
            plot_right = left + 733

            def x(ns):
                return plot_left + (ns + 80) * (plot_right - plot_left) / (end_ns + 80)

            parts.append(f'<rect x="{left}" y="{top}" width="755" height="368" rx="12" fill="white"/>')
            text(left + 18, top + 28, LABELS[lane], 21, color, bold=True)
            text(left + 18, top + 55,
                 f"AS: {operand['as_low_ns']} ns   UDS/LDS: {operand['uds_n_low_ns']}/{operand['lds_n_low_ns']} ns   AS→{ack_summary}: {operand['as_to_dtack_ns']} ns",
                 16, color)
            for ns in range(0, end_ns + 1, 200):
                line(x(ns), top + 90, x(ns), top + 353, "#dfe6f0")
                text(x(ns), top + 80, ns, 13, "#607289", "middle")
            text(plot_left - 15, top + 80, "ns", 13, "#607289", "end")

            for row, (signal, label) in enumerate(zip(CONTROL_SIGNALS,
                    ("CLK", "AS_N", "UDS_N", "LDS_N", ack_label, "R/W"))):
                y = top + 105 + row * 33
                text(plot_left - 15, y + 5, label, 15, color, "end")
                before = samples[start_tick][lane][signal]
                path = [f"M {x(-80):.2f} {y - 9 if before else y + 9}"]
                for tick in range(start_tick + 1, end_tick + 1):
                    value = samples[tick][lane][signal]
                    if value != before:
                        path.append(f"H {x((tick - origin) * 20):.2f}")
                        path.append(f"V {y - 9 if value else y + 9}")
                        before = value
                path.append(f"H {x((end_tick - origin) * 20):.2f}")
                parts.append(f'<path d="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="2.3"/>')

            for row, name, is_data in ((6, "A[23:0]", False), (7, "D[15:0]", True)):
                y = top + 105 + row * 33
                text(plot_left - 15, y + 5, name, 15, color, "end")
                key = "data" if is_data else "address"
                # Draw every sampled word transition, including stale values
                # before valid data arrives. Do not infer validity solely
                # from ACK; builds before 5 also have a socket-only ACK gate.
                beginning = origin
                value = samples[origin][lane][key]
                boundaries = []
                for tick in range(origin + 1, operand["end_tick"]):
                    if samples[tick][lane][key] != value:
                        boundaries.append((beginning, tick, value))
                        beginning = tick
                        value = samples[tick][lane][key]
                boundaries.append((beginning, operand["end_tick"], value))
                for beginning, ending, value in boundaries:
                    x1 = x((beginning - origin) * 20)
                    x2 = x((ending - origin) * 20)
                    points = [(x1, y), (x1 + 5, y - 11), (x2 - 5, y - 11),
                              (x2, y), (x2 - 5, y + 11), (x1 + 5, y + 11)]
                    encoded = " ".join(f"{px:.2f},{py}" for px, py in points)
                    parts.append(f'<polygon points="{encoded}" fill="white" stroke="{color}" stroke-width="1.5"/>')
                    digits = 4 if is_data else 6
                    size = 12 if x2 - x1 < 85 else 15
                    text((x1 + x2) / 2, y + 5, f"${value:0{digits}X}", size, color, "middle")

    read_model, write_model = first["operand_intervals"]["model"]
    read_socket, write_socket = first["operand_intervals"]["socket"]
    read_delta = read_socket["as_low_ns"] - read_model["as_low_ns"]
    write_delta = write_socket["as_low_ns"] - write_model["as_low_ns"]
    text(40, 967, f"Physical minus fx68k AS duration: read {read_delta:+d} ns; write {write_delta:+d} ns. Both transfer $A55A correctly.", 19, bold=True)
    if direct_ack:
        ack_note = f"20 ns samples. * DTACK directly feeds the socket output in build {core_build}; physical pin/buffer propagation is not measured."
    else:
        ack_note = "20 ns samples. * Internal ACK precedes the socket read-turnaround gate: this is NOT the CPU-facing DTACK signal."
    text(40, 994, ack_note, 15)
    text(40, 1018, "Data shows sampled words, including stale values before $A55A arrives. Each waveform ends 80 ns after its transfer.", 15)
    text(40, 1043, f"Raw capture SHA-256: {digest}", 11, "#607289")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--vcd", type=Path)
    args = parser.parse_args()
    raw = args.capture.read_bytes()
    report = json.loads(raw)
    diagram = render(report, hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(diagram)
    if args.vcd:
        args.vcd.parent.mkdir(parents=True, exist_ok=True)
        args.vcd.write_text(export_vcd(report))


if __name__ == "__main__":
    main()
