"""Offline clock-phase comparison of ABI-4 records.

No per-transfer time warping: each stream is aligned once at its opening
marker. A signal changing between the two observations preceding a clock
edge is unresolved at this resolution, not silently rounded into agreement.
"""

from __future__ import annotations

from html import escape

from .corpus import BEGIN, END
from .scope import Capture
from .timing import decode_word

POLICY = {"version": 2, "sample_period_ns": 20,
          "sample_before_edge_ticks": 1, "guard_before_edge_ticks": 2,
          "alignment": "first clock edge following opening marker completion",
          "guard": "CPU outputs; synchronous responder ACK checked at sampling phase"}


def from_report(report):
    return Capture(**{name: report[name] for name in (
        "lane", "reason", "first_tick", "last_tick", "missed_tick",
        "accepted", "committed", "buffer_used")}, raw=bytes.fromhex(report["records_hex"]))


def marker_interval(trace):
    boundaries = []
    for address, data in ((BEGIN, 0x1111), (END, 0x2222)):
        selected = [row for row in trace if row["address"] == address
                    and row["data"] == data and row["flags"] & 7 == 3]
        if len(selected) != 1:
            raise ValueError(f"expected one marker at {address:#x}, found {len(selected)}")
        boundaries.append(selected[0]["end"])
    if boundaries[1] <= boundaries[0]:
        raise ValueError("reversed marker interval")
    return boundaries


def meaningful(row):
    # The bus is undefined between transfers. DTACK release latency after AS
    # is not a CPU output timing failure, but its next active phase is checked.
    result = {key: row[key] for key in ("as_n", "uds_n", "lds_n", "reset_n", "halt_n")}
    if not row["as_n"]:
        result.update({key: row[key] for key in ("read", "address", "fc", "dtack_n", "berr_n")})
        selected = not row["uds_n"] or not row["lds_n"]
        if selected and (not row["read"] or not row["dtack_n"]):
            mask = (0xFF00 if not row["uds_n"] else 0) | (0xFF if not row["lds_n"] else 0)
            result["data"] = row["data"] & mask
    return result


def phases(capture, trace):
    if not capture.complete:
        raise ValueError("incomplete capture cannot qualify timing")
    begin, end = marker_interval(trace)
    if begin - 2 < capture.first_tick or end > capture.last_tick:
        raise ValueError("markers outside capture")
    # Scope capacity bounds ordinary workloads, but delta records can encode
    # long idle gaps. Expand only the marked region and impose a finite limit.
    if end - begin > 500_000:
        raise ValueError("native timing region exceeds ten milliseconds")
    samples = [(tick, decode_word(word)) for tick, word in capture.window(begin - 2, end + 1)]
    result = []
    for index in range(2, len(samples)):
        tick, current = samples[index]
        if current["clock"] == samples[index - 1][1]["clock"]:
            continue
        before = meaningful(samples[index - 1][1])
        guard = meaningful(samples[index - 2][1])
        # DTACK/BERR are known synchronous responder outputs, not asynchronous
        # CPU outputs. Their sampled value is checked, and any changed CPU wait
        # decision is visible in subsequent phases. A newly valid read-data
        # field is not itself a data transition: compare actual bus values.
        unstable = [key for key in set(before) & set(guard)
                    if key not in ("dtack_n", "berr_n", "data") and before[key] != guard[key]]
        if "data" in before:
            mask = (0xFF00 if not samples[index - 1][1]["uds_n"] else 0)
            mask |= 0xFF if not samples[index - 1][1]["lds_n"] else 0
            if (samples[index - 1][1]["data"] ^ samples[index - 2][1]["data"]) & mask:
                unstable.append("data")
        result.append({"tick": tick, "edge": current["clock"], "signals": before,
                       "unstable": sorted(unstable)})
    if len(result) < 2:
        raise ValueError("no measurable clock region")
    for previous, current in zip(result, result[1:]):
        if current["tick"] - previous["tick"] != 5:
            raise ValueError("capture clock is not the qualified 5 MHz clock")
    return result


def compare(reference, candidate, data_masks=None):
    data_masks = {} if data_masks is None else data_masks
    left = phases(from_report(reference["capture"]), reference["trace"])
    right = phases(from_report(candidate["capture"]), candidate["trace"])
    differences = []
    unresolved = []
    if len(left) != len(right):
        differences.append({"kind": "half_cycle_count", "reference": len(left), "candidate": len(right)})
    for index, (a, b) in enumerate(zip(left, right)):
        if a["unstable"] or b["unstable"]:
            unresolved.append({"phase": index, "reference": a["unstable"], "candidate": b["unstable"]})
        keys = set(a["signals"]) | set(b["signals"])
        changed = {key: [a["signals"].get(key), b["signals"].get(key)]
                   for key in sorted(keys) if a["signals"].get(key) != b["signals"].get(key)
                   and key not in a["unstable"] and key not in b["unstable"]}
        if "data" in changed and a["signals"].get("address") == b["signals"].get("address"):
            mask = data_masks.get(a["signals"].get("address"), 0xFFFF)
            values = changed["data"]
            if all(value is not None for value in values) and not (values[0] ^ values[1]) & mask:
                del changed["data"]
        if a["edge"] != b["edge"]:
            changed["clock_edge"] = [a["edge"], b["edge"]]
        if changed:
            differences.append({"kind": "phase", "phase": index, "signals": changed})
    verdict = "fail" if differences else "indeterminate" if unresolved else "pass"
    return {"verdict": verdict, "policy": POLICY, "data_defined_masks": data_masks,
            "reference_half_cycles": len(left),
            "candidate_half_cycles": len(right), "differences": differences,
            "unresolved": unresolved, "reference_phases": left, "candidate_phases": right}


def compare_state(reference, candidate, sr_mask):
    defined = []
    chip = []
    for key in reference:
        if reference[key] == candidate[key]:
            continue
        entry = {"field": key, "reference": reference[key], "candidate": candidate[key]}
        if key == "sr":
            if (reference[key] ^ candidate[key]) & sr_mask:
                defined.append(entry)
            if (reference[key] ^ candidate[key]) & (~sr_mask & 0xFFFF):
                chip.append(entry)
        elif key in ("frame", "stack", "user_stack"):
            def normalized(state):
                data = bytearray.fromhex(state[key])
                frame_address = state["ssp_at_collector"]
                base = {"frame": frame_address, "stack": 0x3F00, "user_stack": 0x4F00}[key]
                offset = frame_address - base

                def mask_word(position, mask):
                    if 0 <= position and position + 2 <= len(data):
                        value = int.from_bytes(data[position:position + 2], "big") & mask
                        data[position:position + 2] = value.to_bytes(2, "big")

                # Original 68000 group-0 frame: SSW, address, IR, SR, PC.
                # The upper eleven SSW bits are not architecturally specified.
                if state["vector"] == 3:
                    mask_word(offset, 0x001F)
                    mask_word(offset + 8, sr_mask)
                else:
                    mask_word(offset, sr_mask)
                return data

            if normalized(reference) != normalized(candidate):
                defined.append(entry)
            else:
                chip.append(entry)
        else:
            defined.append(entry)
    return {"defined": "fail" if defined else "pass",
            "chip_compatibility": "fail" if chip or defined else "pass",
            "defined_differences": defined, "chip_differences": chip}


def draw_svg(comparison, path, title):
    """Compact actual waveforms surrounding the first differing clock phase."""
    changed = [entry["phase"] for entry in comparison["differences"] if "phase" in entry]
    center = changed[0] if changed else max(0, min(
        len(comparison["reference_phases"]), len(comparison["candidate_phases"])) - 8)
    start = max(0, center - 4)
    stop = start + 20
    signals = ("clock", "as_n", "uds_n", "lds_n", "read", "dtack_n", "berr_n")
    width = 1120
    rows = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="730" viewBox="0 0 {width} 730">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<text x="20" y="26" font-family="monospace">{escape(title)}</text>',
            '<text x="20" y="48" font-family="monospace">Clock-phase observations; raw 20 ns records retained in JSON</text>']
    for offset in range(21):
        x = 180 + offset * 44
        rows += [f'<path d="M{x} 75 V710" stroke="#ddd"/>',
                 f'<text x="{x}" y="70" font-size="10">{start + offset}</text>']
    for signal_index, signal in enumerate(signals):
        for lane_index, (key, color, label) in enumerate((
                ("reference_phases", "#147d64", "CPU"), ("candidate_phases", "#ba3b38", "fx68k"))):
            y = 95 + signal_index * 70 + lane_index * 28
            rows.append(f'<text x="12" y="{y}" font-family="monospace" font-size="12">{signal} {label}</text>')
            points = []
            for index, phase in enumerate(comparison[key][start:stop]):
                value = phase["edge"] if signal == "clock" else phase["signals"].get(signal)
                if value is None:
                    continue
                level = y - 15 if value else y
                x = 180 + index * 44
                points.extend((f"{x},{level}", f"{x + 44},{level}"))
            rows.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"/>')
    for row_index, (key, label) in enumerate((
            ("reference_phases", "CPU"), ("candidate_phases", "fx68k"))):
        for field_index, field in enumerate(("address", "data")):
            y = 610 + row_index * 48 + field_index * 20
            rows.append(f'<text x="12" y="{y}" font-family="monospace" font-size="12">{label} {field}</text>')
            for index, phase in enumerate(comparison[key][start:stop]):
                value = phase["signals"].get(field)
                text = "-" if value is None else f"{value:04x}"
                rows.append(f'<text x="{180 + index * 44}" y="{y}" font-family="monospace" font-size="9">{text}</text>')
    rows.append("</svg>")
    path.write_text("\n".join(rows) + "\n")
