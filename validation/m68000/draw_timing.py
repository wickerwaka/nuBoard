"""Render a measured paired waveform as SVG; no edges are synthesized."""

from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path

from .timing import decode_capture

WIDTH = 1500
HEIGHT = 1030
LEFT = 210
RIGHT = 1440
START_NS = -80
END_NS = 1800
MODEL_COLOR = "#1764ad"
SOCKET_COLOR = "#ba4c12"


def export_vcd(report):
    """Preserve the common timebase; SVG alignment is only a presentation choice."""
    samples = decode_capture(bytes.fromhex(report["runs"][0]["scope_hex"]))
    widths = {name: 1 for name in samples[0]["model"]}
    widths.update(address=24, data=16, fc=3)
    lines = [
        "$comment FPGA digital samples; 20 ns resolution, common two-register pipeline $end",
        "$timescale 1ns $end",
    ]
    identifiers = {}
    for lane, prefix in (("model", "m"), ("socket", "s")):
        lines.append(f"$scope module {lane} $end")
        for index, (name, width) in enumerate(widths.items()):
            identifier = f"{prefix}{index}"
            identifiers[lane, name] = identifier
            lines.append(f"$var wire {width} {identifier} {name} $end")
        lines.append("$upscope $end")
    lines.append("$enddefinitions $end")
    previous = {}
    for tick, sample in enumerate(samples):
        changes = []
        for lane in ("model", "socket"):
            for name, width in widths.items():
                value = sample[lane][name]
                identifier = identifiers[lane, name]
                if previous.get(identifier) != value:
                    changes.append(f"b{value:0{width}b} {identifier}")
                    previous[identifier] = value
        if changes:
            absolute_tick = tick + report.get("scope_start_tick", 0)
            lines.append(f"#{absolute_tick * report['sample_period_ns']}")
            lines.extend(changes)
    return "\n".join(lines) + "\n"


def render(report, report_hash):
    if report["backend"] != "board" or not report["completed"]:
        raise ValueError("a completed physical capture is required")
    runs = report["runs"]
    if not all(run["result"]["passed"] for run in runs):
        raise ValueError("cannot illustrate a failed functional capture as a timing-only mismatch")
    first = runs[0]
    intervals = first["read_intervals"]
    model_reads = intervals["model"][:2]
    socket_reads = intervals["socket"][:2]
    widths = [model_reads[0]["as_low_ns"], socket_reads[0]["as_low_ns"]]
    periods = [
        (reads[1]["start_tick"] - reads[0]["start_tick"]) * report["sample_period_ns"]
        for reads in (model_reads, socket_reads)
    ]
    if (report["sample_period_ns"] != 20 or widths != [500, 700]
            or periods != [800, 1000] or first["result"]["clock_divider"] != 5):
        raise ValueError("capture does not reproduce the documented 5 MHz reset-read mismatch")
    for run in runs[1:]:
        for lane in ("model", "socket"):
            if run["read_intervals"][lane][:2] != intervals[lane][:2]:
                raise ValueError("the first two reads did not repeat identically")
    samples = decode_capture(bytes.fromhex(first["scope_hex"]))
    for lane in ("model", "socket"):
        for read in intervals[lane][:2]:
            for tick in range(read["start_tick"] - 1, read["end_tick"] + 1):
                row = samples[tick][lane]
                if not row["as_n"] == row["uds_n"] == row["lds_n"]:
                    raise ValueError("AS/UDS/LDS do not share the illustrated edges")
    # UDS/LDS/DTACK/clock must also reproduce, not only the summarized AS widths.
    for run in runs[1:]:
        other = decode_capture(bytes.fromhex(run["scope_hex"]))
        for lane in ("model", "socket"):
            start = intervals[lane][0]["start_tick"] - 4
            end = intervals[lane][1]["end_tick"] + 4
            for tick in range(start, end):
                for name in ("clock", "as_n", "uds_n", "lds_n", "read", "dtack_n"):
                    if samples[tick][lane][name] != other[tick][lane][name]:
                        raise ValueError(f"non-repeating {lane} {name} at sample {tick}")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b43}'
        '.mono{font-family:DejaVu Sans Mono,monospace}</style>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#f6f8fc"/>',
    ]

    def text(x, y, value, size=17, color="#172b43", anchor="start", weight="normal"):
        parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" '
            f'font-weight="{weight}" style="fill:{color}">{escape(str(value))}</text>'
        )

    def x(ns):
        return LEFT + (ns - START_NS) * (RIGHT - LEFT) / (END_NS - START_NS)

    def line(x1, y1, x2, y2, color, width=1, dash=""):
        parts.append(
            f'<line x1="{x1:.2f}" y1="{y1}" x2="{x2:.2f}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}"/>'
        )

    def digital(lane, name, origin, y, color):
        start = origin + START_NS // 20
        end = origin + END_NS // 20
        previous = samples[start][lane][name]
        level = y - 10 if previous else y + 10
        path = [f"M {x(START_NS):.2f} {level}"]
        for tick in range(start + 1, end + 1):
            value = samples[tick][lane][name]
            if value != previous:
                edge_x = x((tick - origin) * 20)
                path.append(f"H {edge_x:.2f}")
                path.append(f"V {y - 10 if value else y + 10}")
                previous = value
        path.append(f"H {x(END_NS):.2f}")
        parts.append(f'<path d="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="2.5"/>')

    def bus(lane, origin, y, color, data=False):
        line(LEFT, y, RIGHT, y, "#a8b3c4", 1, "4 4")
        for interval in intervals[lane]:
            beginning = interval["dtack_tick"] if data else interval["start_tick"]
            start_ns = (beginning - origin) * 20
            end_ns = (interval["end_tick"] - origin) * 20
            if start_ns >= END_NS or end_ns <= START_NS:
                continue
            left = x(max(start_ns, START_NS))
            right = x(min(end_ns, END_NS))
            points = [(left, y), (left + 5, y - 12), (right - 5, y - 12),
                      (right, y), (right - 5, y + 12), (left + 5, y + 12)]
            encoded = " ".join(f"{px:.2f},{py}" for px, py in points)
            parts.append(f'<polygon points="{encoded}" fill="white" stroke="{color}" stroke-width="1.5"/>')
            value = interval["data"] if data else interval["address"]
            label = f"${value:04X}" if data else f"${value:06X}"
            text((left + right) / 2, y + 6, label, 16, color, "middle")

    text(42, 48, "One extra 5 MHz clock per reset-vector read", 29, weight="bold")
    text(42, 79, "Actual FPGA-sampled signals · fx68k versus socketed MC68000P12 · 20 ns resolution", 18)
    text(42, 106, f"{len(runs)} / {len(runs)} repeated runs match · identical program and memory · wait_ticks = 8", 17)
    text(42, 133, "Each panel is aligned to its own first AS falling edge; this removes reset-exit phase offset.", 16)

    for lane, title, color, top in (
        ("model", "fx68k (on the FPGA)", MODEL_COLOR, 184),
        ("socket", "MC68000P12 (physical CPU)", SOCKET_COLOR, 566),
    ):
        first_read, second_read = intervals[lane][:2]
        origin = first_read["start_tick"]
        width = first_read["as_low_ns"]
        period = (second_read["start_tick"] - origin) * 20
        parts.append(f'<rect x="28" y="{top - 28}" width="1444" height="361" rx="12" fill="white"/>')
        text(48, top, title, 22, color, weight="bold")
        text(1440, top, f"AS low: {width} ns    |    next read: +{period} ns", 19, color, "end", "bold")
        for ns in range(0, END_NS + 1, 200):
            line(x(ns), top + 35, x(ns), top + 321, "#dfe6f0", 1)
            text(x(ns), top + 26, str(ns), 13, "#607289", "middle")
        text(LEFT - 20, top + 26, "ns", 13, "#607289", "end")
        # Highlight the extra time for which the physical CPU keeps AS low.
        if lane == "socket":
            model_end = intervals["model"][0]["as_low_ns"]
            parts.append(f'<rect x="{x(model_end):.2f}" y="{top + 74}" '
                         f'width="{x(width) - x(model_end):.2f}" height="25" fill="#ffe0bd"/>')
        rows = [
            ("clock", "CLK  (5 MHz)"),
            ("as_n", "AS_N"),
            ("uds_n", "UDS_N"),
            ("lds_n", "LDS_N"),
            ("dtack_n", "DTACK_N *"),
            ("read", "R/W  (1 = read)"),
        ]
        for row, (name, label) in enumerate(rows):
            y = top + 50 + row * 36
            text(LEFT - 20, y + 6, label, 16, color, "end")
            digital(lane, name, origin, y, color)
        for row, label, is_data in ((6, "A[23:0]", False), (7, "D[15:0]", True)):
            y = top + 50 + row * 36
            text(LEFT - 20, y + 6, label, 16, color, "end")
            bus(lane, origin, y, color, is_data)
        text((x(0) + x(width)) / 2, top + 87, f"{width} ns", 14, color, "middle", "bold")

    text(42, 944, "Difference: AS / UDS / LDS stay asserted 200 ns longer; the next read starts 200 ns later.", 18, weight="bold")
    text(42, 971, "* DTACK is measured at the FPGA responder output, not at the CPU pin. Data is shown only after ACK.", 15)
    text(42, 995, "Digital capture after level translation; not an analog timing signoff or proof of an fx68k defect.", 15)
    text(42, 1018, f"Raw capture SHA-256: {report_hash}", 11, "#607289")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--vcd", type=Path, help="also export the unaligned common-timebase capture")
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
