"""Chain building blocks as bytes (plan, "Experimental design / Blocks")."""

from __future__ import annotations

# MOV CL,31; SHL AW,CL: ~70+ clocks with no bus cycle of its own. 4 bytes, so
# it does not change parity. LS24 is the CL=24 control variant.
LS = bytes([0xB1, 0x1F, 0xD3, 0xE0])
LS24 = bytes([0xB1, 0x18, 0xD3, 0xE0])
PAD = bytes([0x90])
# MOV DW,0FF00h; OUT DW,AL; HALT; then 16 NOPs so prefetch past HALT reads real bytes.
END = bytes([0xBA, 0x00, 0xFF, 0xEF, 0xF4]) + bytes([0x90]) * 16

MARKER_KINDS = ("out", "push", "store")
MARKER_PORT_BASE = 0x20


def marker(kind: str, i: int) -> bytes:
    """Marker i: OUT (20h+i),AL; PUSH AW; or MOV [0C00h],AW."""
    if kind == "out":
        return bytes([0xE6, MARKER_PORT_BASE + i])
    if kind == "push":
        return bytes([0x50])
    if kind == "store":
        return bytes([0xA3, 0x00, 0x0C])
    raise ValueError(f"unknown marker kind {kind!r}")


DRAIN_IMM = (0x1234, 0x5678)


def drainer(i: int) -> bytes:
    """i-th drainer: B8 34 12 (MOV AW,1234h) / BA 78 56 (MOV DW,5678h) alternating."""
    value = DRAIN_IMM[i % 2]
    return bytes([0xB8 if i % 2 == 0 else 0xBA]) + value.to_bytes(2, "little")


def drainer4(i: int) -> bytes:
    """i-th 4-byte drainer D4: ADD DW,imm16 (81 C2 ii ii)."""
    return bytes([0x81, 0xC2]) + DRAIN_IMM[i % 2].to_bytes(2, "little")
