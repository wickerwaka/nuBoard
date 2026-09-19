#!/usr/bin/env python3
"""Rebuild Musashi's sources for 68000, never its default -march=68040."""

import os
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "build/deps/Musashi/test"
    output = ROOT / "build/validation/m68000/programs"
    output.mkdir(parents=True, exist_ok=True)
    local = ROOT / "build/deps/binutils/usr"
    assembler = shutil.which("m68k-linux-gnu-as") or str(local / "bin/m68k-linux-gnu-as")
    linker = shutil.which("m68k-linux-gnu-ld") or str(local / "bin/m68k-linux-gnu-ld")
    environment = os.environ.copy()
    if local.exists():
        environment["LD_LIBRARY_PATH"] = str(local / "lib/x86_64-linux-gnu")
    subprocess.run(["python3", str(ROOT / "tools/fetch_m68000.py"), "--verify-only"], check=True)
    hashes = {}
    for path in sorted((source / "mc68000").glob("*.s")):
        obj = output / (path.stem + ".o")
        binary = output / (path.stem + ".bin")
        subprocess.run([assembler, "-march=68000", "-I", str(source),
                        "-o", str(obj), str(path)], check=True, env=environment)
        subprocess.run([linker, "-Ttext", "0x10000", "--oformat", "binary",
                        "-o", str(binary), str(obj)], check=True, env=environment)
        hashes[binary.name] = hashlib.sha256(binary.read_bytes()).hexdigest()
    manifest = {"march": "68000", "binaries": hashes,
                "assembler": subprocess.check_output([assembler, "--version"],
                                                       env=environment, text=True).splitlines()[0]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {len(list(output.glob('*.bin')))} 68000 programs in {output}")


if __name__ == "__main__":
    main()
