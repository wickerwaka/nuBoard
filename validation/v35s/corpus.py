"""The silicon corpus: frozen socket-lane results that offline checks run against.

    python -m validation.v35s.corpus add NAME FILE [--note TEXT]
    python -m validation.v35s.corpus list

`add` copies a probe's result file (timing.json, prefetch.json, a
characterize receipt, ...) into build/validation/v35s/corpus/NAME.json and
records it in manifest.json with its hash, the harness bitstream that took
it and the date. The Python cycle model and the RTL replay read the corpus
through `load` and `cases`, never the probes' working output files, so a
later probe run cannot silently change what they are checked against.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
from pathlib import Path

from .runner import ROOT

CORPUS = ROOT / "build/validation/v35s/corpus"
MANIFEST = CORPUS / "manifest.json"
RECEIPT = ROOT / "build/fpga/v35s/receipt.json"


def manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"entries": {}}


def add(name: str, source: Path, note: str = "") -> dict:
    CORPUS.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    target = CORPUS / f"{name}.json"
    shutil.copyfile(source, target)
    receipt = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else {}
    entry = {
        "file": target.name,
        "source": str(source.relative_to(ROOT) if source.is_relative_to(ROOT) else source),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bitstream_sha256": receipt.get("bitstream_sha256"),
        "added": datetime.date.today().isoformat(),
        "note": note,
    }
    book = manifest()
    book["entries"][name] = entry
    MANIFEST.write_text(json.dumps(book, indent=1) + "\n")
    return entry


def load(name: str) -> dict:
    entry = manifest()["entries"][name]
    data = (CORPUS / entry["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"corpus entry {name} does not match its manifest hash")
    return json.loads(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    put = sub.add_parser("add")
    put.add_argument("name")
    put.add_argument("file", type=Path)
    put.add_argument("--note", default="")
    sub.add_parser("list")
    args = parser.parse_args()
    if args.command == "add":
        entry = add(args.name, args.file.resolve(), args.note)
        print(f"{args.name}: {entry['sha256'][:12]} from {entry['source']}")
    else:
        for name, entry in manifest()["entries"].items():
            print(f"{name:<24} {entry['added']} {entry['sha256'][:12]} "
                  f"bitstream {str(entry['bitstream_sha256'])[:12]}  {entry['note']}")


if __name__ == "__main__":
    main()
