#!/usr/bin/env python3
"""Fetch the pinned, unmodified nuV30 checkout used by the V35S harness.

nuV30 supplies the V20-microcode core that fpga/v35s/core/ is derived from,
the NEC-syntax assembler sw/v30asm.py, and its instruction database.
"""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = {
    "nuV30": ("https://github.com/wickerwaka/nuV30.git",
              "ddda5dfe792672680952e95de5625dfc372fa593"),
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
