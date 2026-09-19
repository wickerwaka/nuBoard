#!/usr/bin/env python3
"""Download the pinned MOVEQ single-step vectors and their upstream decoder."""

from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REVISION = "64b253116a3de04aaac4346c43680960dc9b67e5"


def main():
    destination = ROOT / "build/deps/m68000-vectors"
    for name in ("LICENSE", "README.md", "decode.py", "v1/MOVE.q.json.bin"):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/SingleStepTests/m68000/{REVISION}/{name}"
        with urlopen(url, timeout=30) as response:
            path.write_bytes(response.read())
    subprocess.run([sys.executable, "decode.py"], cwd=destination, check=True)
    print(f"SingleStepTests/m68000: {REVISION}")


if __name__ == "__main__":
    main()
