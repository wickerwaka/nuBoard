"""Compare the V35S timing sweep with V30 silicon and the V35 data book.

    python -m validation.v35s.timing_report [timing.json] [v35_book_clocks.json]

Reads the output of validation.v35s.timing and a transcription of the V35
data book's clock table (pdf pp 550-553), evaluated at EA = 3, W = 0, and
prints one row per form plus summary counts. Book values for control
transfers exclude the queue refill the probe includes, so those rows are
listed but not scored.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from .runner import ROOT

ALIASES = {
    "INC mem": "INC mem (word)", "DEC mem": "DEC mem (word)",
    "CMPBK/CMPBKB/CMPBKW": "CMPBK", "MOVBK/MOVBKB/MOVBKW": "MOVBK",
    "LDM/LDMB/LDMW": "LDM", "STM/STMB/STMW": "STM",
    "TRANS no operand / TRANS src-table / TRANSB no operand": "TRANS",
    "XCH AW,reg16 / XCH reg16,AW": "XCH AW,reg16",
    "XCH mem,reg / XCH reg,mem": "XCH mem,reg",
    "TEST mem,reg or TEST reg,mem": "TEST mem,reg",
    "EXT reg1, reg2": "EXT reg8,reg8", "INS reg1, reg2": "INS reg8,reg8",
    "LDEA reg16,mem16": "LDEA", "DIVU reg16": "DIVU reg16",
    "PREPARE imm16,imm8": "PREPARE imm16,imm8",
    "BRK 3": "BRK 3", "BRKV (no operand)": "BRKV",
    "CHKIND reg16,mem32": "CHKIND reg16,mem32",
}

FLOW = ("short-label", "near-label", "far-label", "memptr16", "regptr16", "near-proc",
        "far-proc", "RET", "RETI", "BRK 3", "BRKV (V=1", "CHKIND DW,[BW] (trap)")


def book_key(form: str, book: dict) -> str | None:
    if form in book:
        return form
    if form in ALIASES:
        return ALIASES[form]
    base = form.replace(" (no operand)", "")
    if base in book:
        return base
    if re.match(r"B(C|Z|NZ|NC) short-label", form):
        return "BC/BZ/BNZ/BNC short-label (Bcond)"
    if form.startswith(("DBNZ", "BCWZ")):
        return form.split()[0] if form.split()[0] in book else form.replace(" short-label", "") + " short-label"
    for key in book:
        if key.startswith(form.split()[0] + " ") and form.split()[-1] in key:
            return key
    return None


def width(name: str) -> str:
    byte = re.search(r"\b(AL|BL|CL|DL|AH|BH|CH|DH)\b|byte|B\b|MOVBKB|CMPBKB|LDMB|STMB|0x12\b|0x40, AL",
                     name)
    return "byte" if byte and "CL]" not in name.split("[")[0] else "word"


def book_value(entry: dict, name: str):
    """Returns (value or (min, max), expression) at EA=3, W=0."""
    count = re.search(r"CL=(\d)|CW=000(\d)|, (\d)$|, (\d) \[|PREPARE 8, (\d)", name)
    n = next((g for g in count.groups() if g), None) if count else None
    if "values_by_imm8" in entry and n is not None:
        return entry["values_by_imm8"].get(n), entry.get("expr")
    if "values_by_n" in entry:
        if "4S" in name and n is not None:
            return entry["values_by_n"].get(str(int(n) // 2)), entry.get("expr")
        if n is not None:
            return entry["values_by_n"].get(n), entry.get("expr")
    side = entry.get(width(name))
    if side and side.get("value") is not None:
        return side["value"], side.get("expr")
    if entry.get("value") is not None:
        return entry["value"], entry.get("expr")
    if entry.get("value_min") is not None:
        return (entry["value_min"], entry["value_max"]), entry.get("expr")
    if entry.get("values_printed"):
        low, high = min(entry["values_printed"]), max(entry["values_printed"])
        return (high if "taken)" in name and "not" not in name else low), entry.get("expr")
    return None, entry.get("expr")


def classify(silicon, book):
    if silicon is None or book is None:
        return "-"
    if isinstance(book, tuple):
        return "in range" if book[0] <= silicon <= book[1] else "outside range"
    delta = silicon - book
    if abs(delta) <= 0.5:
        return "match"
    if abs(delta) <= 1.5:
        return "±1"
    return f"{delta:+g}"


def main():
    timing = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build/validation/v35s/timing.json"
    clocks = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "build/validation/v35s/v35_book_clocks.json"
    rows = json.loads(timing.read_text())["summary"]
    book = json.loads(clocks.read_text())["forms"]
    tally, v30_tally = Counter(), Counter()
    print(f"{'case':<50} {'V30':>4} {'V35S':>6} {'book':>8}  verdict")
    for row in rows:
        key = book_key(row["form"], book)
        value, _ = book_value(book[key], row["name"]) if key else (None, None)
        flow = any(token in row["form"] or token in row["name"] for token in FLOW)
        verdict = "flow (refill included)" if flow else classify(row["socket"], value)
        if not flow and row["socket"] is not None and row["v30"] is not None:
            v30_tally["same as V30" if abs(row["socket"] - row["v30"]) <= 0.5 else
                      "differs from V30"] += 1
        if not flow:
            tally[verdict if verdict in ("match", "±1", "in range", "-") else "off by more"] += 1
        shown = "-" if value is None else (f"{value[0]}-{value[1]}" if isinstance(value, tuple)
                                           else f"{value}")
        socket = "-" if row["socket"] is None else f"{row['socket']:g}"
        print(f"{row['name'][:50]:<50} {row['v30'] if row['v30'] is not None else '-':>4} "
              f"{socket:>6} {shown:>8}  {verdict}")
    print("\nAgainst the data book (non-flow):", dict(tally))
    print("Against V30 silicon (non-flow):", dict(v30_tally))


if __name__ == "__main__":
    main()
