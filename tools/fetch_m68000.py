#!/usr/bin/env python3
"""Fetch pinned, unmodified CPU and test dependencies into the build tree."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = {
    "fx68k": ("https://github.com/JTFPGA/fx68k.git",
              "1217ab8dc600de070c6adb71ea6fe69de8855362"),
    "Musashi": ("https://github.com/kstenerud/Musashi.git",
                "313ebf1bd9f4d0d93341eb5ce21fd8a119e9dbdd"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    for name, (url, revision) in DEPENDENCIES.items():
        path = ROOT / "build" / "deps" / name
        if not path.exists():
            if args.verify_only:
                raise SystemExit(f"Missing dependency: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "--no-checkout", url, str(path)], check=True)
            subprocess.run(["git", "-C", str(path), "checkout", "--detach", revision], check=True)
        actual = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain"], text=True
        ).strip()
        if actual != revision or dirty:
            raise SystemExit(f"Dependency {name} must be clean at {revision}; found {actual}")
        print(f"{name}: {actual}")


if __name__ == "__main__":
    main()
