#!/usr/bin/env python3
"""Download pinned SingleStepTests/v20 (v1_native) opcode files for the V35S chain RTL's
functional check (HDL plan D2: validation/v35s/chains/sst.py).

The files go to build/deps/sst-v20/ (never into the tree) with a manifest of their sha256.
By default the files of every opcode the RTL decodes (sst.RTL_FILES) and (S6) the core v2's
whole-core bench's further files (sst.S6_FILES); --files names others.

    python3 tools/fetch_sst_v20.py [--files 00 81.0 ...] [--verify-only]
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REVISION = "6b3748f97533d606249382cad8d94b1c165ef93d"
DEST = ROOT / "build" / "deps" / "sst-v20"
BASE = f"https://raw.githubusercontent.com/SingleStepTests/v20/{REVISION}"


def _fetch(name: str) -> Path:
    path = DEST / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(f"{BASE}/{name}", timeout=120) as response:
            data = response.read()
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.rename(path)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--files", nargs="+", help="opcode file stems (00, 81.0, ...)")
    parser.add_argument("--verify-only", action="store_true",
                        help="check the manifest's hashes without downloading")
    args = parser.parse_args(argv)
    if args.files is None:
        sys.path.insert(0, str(ROOT))
        from validation.v35s.chains.sst import RTL_FILES, S6_FILES
        args.files = list(RTL_FILES) + list(S6_FILES)
    if any(not re.fullmatch(r"[0-9A-F]{2,4}(\.[0-7])?", f) for f in args.files):
        parser.error("file stems are upper-case hex opcodes, optionally .N")
    manifest_path = DEST / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        "schema": 1, "revision": REVISION, "files": {}}
    if manifest.get("revision") != REVISION:
        raise SystemExit(f"{DEST} holds revision {manifest.get('revision')}, not {REVISION}")
    names = ["README.md", "v1_native/metadata.json"] + [
        f"v1_native/{f}.json.gz" for f in args.files]
    bad = 0
    for name in names:
        if args.verify_only:
            path = DEST / name
            if not path.exists():
                print(f"missing {name}")
                bad += 1
                continue
        else:
            path = _fetch(name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        known = manifest["files"].get(name)
        if known is not None and known != digest:
            print(f"hash mismatch {name}")
            bad += 1
        manifest["files"][name] = digest
    if not args.verify_only:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"SingleStepTests/v20 {REVISION}: {len(names)} files, {bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
