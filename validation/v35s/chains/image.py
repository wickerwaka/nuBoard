"""Chain images: prelude, parity pad, assembly, vectors and data fill.

The prelude follows the pattern of timing.py's _setup (own copy): it writes
the WTC, RFM and PRC SFRs through DS0=F000h, sets SS:SP and PSW (BRKI set so
OUT does not trap), loads segments and registers, AW last. Chain bytes are
emitted as DB lists only, then checked byte for byte at their offsets.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from ..asm import assemble
from . import blocks
from .forms import DEFAULT_REGS
from .types import CODE_BASE, CODE_SEGMENT, DATA_FILL, Built, Chain, Instr

SEGMENTS = ("DS0", "DS1", "SS")
REGS16 = ("BW", "CW", "DW", "SP", "BP", "IX", "IY")
VECTOR_TABLE = 0x400
PSW = 0x0002                       # bit 1 is BRKI on the V35


def _imm(value: int) -> str:
    return f"0{value & 0xFFFF:04X}h"


# (WP24, F18) the prelude's optional last instruction (Chain.prelude_marker): its bytes,
# checked at the prelude's end by build_image
PRELUDE_MARKERS = {"push": ("    PUSH AW", bytes([0x50])),
                   "out": ("    OUT 20h, AL", bytes([0xE6, 0x20]))}
PRELUDE_MARKER_PORT = 0x20
PRELUDE_MARKER_STACK = 0x0EFE          # PUSH AW at SP 0F00h


def prelude_source(regs: dict, wtc: int, rfm: int, prc: int, marker: str | None = None) -> str:
    regs = {**DEFAULT_REGS, **regs}
    lines = [
        "    MOV AW, 0F000h",
        "    MOV DS0, AW",
        f"    MOV word [0FFE8h], {_imm(wtc)}",
        f"    MOV byte [0FFE1h], 0{rfm & 0xFF:02X}h",
        f"    MOV byte [0FFEBh], 0{prc & 0xFF:02X}h",
        "    MOV AW, 0",
        "    MOV SS, AW",
        "    MOV SP, 0F00h",
        f"    PUSH {PSW:04X}h",
        "    POP PSW",
    ]
    for name in SEGMENTS:
        lines += [f"    MOV AW, {_imm(regs[name])}", f"    MOV {name}, AW"]
    for name in REGS16:
        lines.append(f"    MOV {name}, {_imm(regs[name])}")
    lines.append(f"    MOV AW, {_imm(regs['AW'])}")
    if marker is not None:
        lines.append(PRELUDE_MARKERS[marker][0])
    return "\n".join(lines) + "\n"


@lru_cache(maxsize=256)
def _prelude(regs_items: tuple, wtc: int, rfm: int, prc: int, marker: str | None) -> bytes:
    return assemble(prelude_source(dict(regs_items), wtc, rfm, prc, marker), org=0)


def prelude(regs: dict, wtc: int, rfm: int, prc: int, marker: str | None = None) -> bytes:
    return _prelude(tuple(sorted(regs.items())), wtc, rfm, prc, marker)


PRELUDE_TAIL_LOADS = len(REGS16) + 1     # MOV r16,imm16 x 7, then MOV AW,imm16 (3 bytes each)


def prelude_tail(chain, segs: bool = False) -> bytes:
    """(WP24) the prelude's last instructions the model runs with prelude_tail=regs
    (sim/config.py): the register loads (REGS16 then AW, each MOV r16,imm16 B8+r ii ii)
    and the prelude marker, the bytes directly before the chain's first byte; with segs
    (prelude_tail=segs) the three segment loads before them as well (MOV AW,imm16 ;
    MOV sreg,AW, 8E /r), everything after the prelude's POP PSW."""
    marker = getattr(chain, "prelude_marker", None)
    head = prelude(chain.regs, chain.wtc, chain.rfm, chain.prc, marker)
    n = 3 * PRELUDE_TAIL_LOADS + (len(PRELUDE_MARKERS[marker][1]) if marker else 0)
    n_seg = 5 * len(SEGMENTS) if segs else 0
    tail = head[-(n + n_seg):]
    for k in range(len(SEGMENTS) if segs else 0):
        if tail[5 * k] != 0xB8 or tail[5 * k + 3] != 0x8E:
            raise RuntimeError(f"{chain.id}: prelude segment load {k} is "
                               f"{tail[5 * k:5 * k + 5].hex()}")
    if segs and head[-(n + n_seg) - 1] != 0x9D:
        raise RuntimeError(f"{chain.id}: the segment loads do not follow POP PSW")
    for k in range(PRELUDE_TAIL_LOADS):
        if not 0xB8 <= tail[n_seg + 3 * k] <= 0xBF:
            raise RuntimeError(f"{chain.id}: prelude tail byte {3 * k} is "
                               f"{tail[n_seg + 3 * k]:02X}, not MOV r16,imm16")
    return tail


def needs_pad(regs: dict, wtc: int, rfm: int, prc: int, parity: str,
              marker: str | None = None) -> bool:
    """True when a NOP before the first LS is needed for the requested parity.

    CODE_BASE is even, so linear parity is code-offset parity; LS is 4 bytes.
    """
    after_ls = len(prelude(regs, wtc, rfm, prc, marker)) + len(blocks.LS)
    return (after_ls & 1) != (parity == "odd")


def assign_offsets(instrs: list[Instr]) -> list[Instr]:
    offset = 0
    for instr in instrs:
        instr.offset = offset
        offset += len(instr.code)
    return instrs


def _db_source(instrs: list[Instr]) -> str:
    lines = []
    for instr in instrs:
        lines.append("    DB " + ", ".join(f"0x{b:02X}" for b in instr.code)
                     + f"    ; {instr.form}")
    return "\n".join(lines) + "\n"


def _first_after_ls(chain: Chain) -> int:
    for instr in chain.instrs:
        if instr.role == "ls":
            return instr.offset + len(instr.code)
    raise ValueError(f"{chain.id}: no LS")


def image_sha256(image: dict) -> str:
    h = hashlib.sha256()
    for address in sorted(image):
        data = image[address]
        h.update(address.to_bytes(4, "little") + len(data).to_bytes(4, "little") + data)
    return h.hexdigest()


def reset_vector(origin: int, segment: int) -> bytes:
    offset = origin - (segment << 4)
    return bytes([0xEA, offset & 0xFF, offset >> 8, segment & 0xFF, segment >> 8])


def build_image(chain: Chain) -> Built:
    marker = getattr(chain, "prelude_marker", None)
    head = prelude(chain.regs, chain.wtc, chain.rfm, chain.prc, marker)
    if marker is not None:
        # (WP24, F18) the marker is the prelude's last instruction, its bytes directly
        # before the chain's first byte (the PAD or the first LS), the AW load before it
        tail = PRELUDE_MARKERS[marker][1]
        bare = prelude(chain.regs, chain.wtc, chain.rfm, chain.prc)
        if head[-len(tail):] != tail or head[:-len(tail)] != bare:
            raise RuntimeError(f"{chain.id}: prelude marker {marker}: prelude ends "
                               f"{head[-4:].hex()}, not the bare prelude + {tail.hex()}")
        if bare[-3] != 0xB8:
            raise RuntimeError(f"{chain.id}: the instruction before the prelude marker is "
                               f"not MOV AW,imm16 ({bare[-3:].hex()})")
    body = assemble(_db_source(chain.instrs), org=len(head))
    code = head + body
    chain_base = CODE_BASE + len(head)
    expected = 0
    for instr in chain.instrs:
        if instr.offset != expected:
            raise RuntimeError(f"{chain.id}: {instr.form} at offset {instr.offset}, "
                               f"expected {expected}")
        expected += len(instr.code)
        start = chain_base - CODE_BASE + instr.offset
        got = code[start:start + len(instr.code)]
        if got != instr.code:
            raise RuntimeError(f"{chain.id}: {instr.form} at +{instr.offset}: "
                               f"image {got.hex()} != catalog {instr.code.hex()}")
    if len(code) != len(head) + expected:
        raise RuntimeError(f"{chain.id}: code length {len(code)} != {len(head) + expected}")
    after = chain_base + _first_after_ls(chain)
    if (after & 1) != (chain.parity == "odd"):
        raise RuntimeError(f"{chain.id}: first byte after LS at {after:05X}, "
                           f"not {chain.parity}")
    if CODE_BASE + len(code) > CODE_BASE + 0x1000:
        raise RuntimeError(f"{chain.id}: code runs past the fetch window")
    fill_at, fill_len = DATA_FILL
    image = {CODE_BASE: code, 0xFFFF0: reset_vector(CODE_BASE, CODE_SEGMENT),
             0x00000: bytes(VECTOR_TABLE), fill_at: b"\x90" * fill_len}
    return Built(chain, image, code, chain_base, image_sha256(image))
