#!/usr/bin/env python3
"""Download explicitly selected, pinned single-step files with provenance."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REVISION = "64b253116a3de04aaac4346c43680960dc9b67e5"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instructions", nargs="+", default=["MOVE.q"],
                        help="upstream file stems, for example MOVE.q ADD.w SUB.w")
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9]+", name) for name in args.instructions):
        parser.error("instruction names must be simple upstream file stems")
    destination = ROOT / "build/deps/m68000-vectors"
    hashes = {}
    for name in ["LICENSE", "README.md", "decode.py", *[
            f"v1/{instruction}.json.bin" for instruction in args.instructions]]:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/SingleStepTests/m68000/{REVISION}/{name}"
        with urlopen(url, timeout=30) as response:
            path.write_bytes(response.read())
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    subprocess.run([sys.executable, "decode.py"], cwd=destination, check=True)
    (destination / "manifest.json").write_text(json.dumps(
        {"schema": 1, "revision": REVISION, "files": hashes}, indent=2) + "\n")
    print(f"SingleStepTests/m68000: {REVISION}")


if __name__ == "__main__":
    main()
