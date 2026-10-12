"""NEC-syntax assembly for V35S test programs.

The assembler is nuV30's sw/v30asm.py from the pinned checkout fetched by
tools/fetch_v35s.py. Its instruction database covers the V30 set. The
V35-only instructions are not in it, so they are expanded here to their
data-book encodings before assembly.
"""

from __future__ import annotations

import importlib.util
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NUV30 = ROOT / "build" / "deps" / "nuV30"

# V35 additions (1991 V-Series data book, V35 instruction set). Operand-free
# forms only; operand forms are written with DB in the source.
V35_EXTENSIONS = {
    "TSKSW_AW": "0x0F, 0x94, 0xF8",
    "RETRBI": "0x0F, 0x91",
    "FINT": "0x0F, 0x92",
    "STOP": "0x0F, 0x9E",
    "BRKS": "0xF1",
    "BRKN": "0x63",
}


@lru_cache(maxsize=1)
def _module():
    path = NUV30 / "sw" / "v30asm.py"
    if not path.exists():
        raise RuntimeError("run tools/fetch_v35s.py to fetch the nuV30 assembler")
    spec = importlib.util.spec_from_file_location("v30asm", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _assembler():
    return _module().Assembler()


def _expand(source: str) -> str:
    lines = []
    for line in source.splitlines():
        code = line.split(";", 1)[0].strip()
        key = code.upper().replace(" ", "_")
        if key in V35_EXTENSIONS:
            indent = re.match(r"\s*", line).group(0)
            lines.append(f"{indent}DB {V35_EXTENSIONS[key]}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def assemble(source: str, org: int = 0) -> bytes:
    return _assembler().assemble(_expand(source), org=org)
