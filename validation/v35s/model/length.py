"""Instruction lengths for the decode stage (V30 set plus the V35's 0F forms)."""

from __future__ import annotations

PREFIXES = {0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3, 0x64, 0x65}

# One-byte opcodes: (ModR/M, immediate bytes).
_TABLE = {}
for base in range(0x00, 0x40, 8):
    for k in range(4):
        _TABLE[base + k] = (True, 0)
    _TABLE[base + 4] = (False, 1)
    _TABLE[base + 5] = (False, 2)
_TABLE.update({0x62: (True, 0), 0x68: (False, 2), 0x69: (True, 2), 0x6A: (False, 1),
               0x6B: (True, 1), 0x80: (True, 1), 0x81: (True, 2), 0x82: (True, 1),
               0x83: (True, 1), 0x9A: (False, 4), 0xA0: (False, 2), 0xA1: (False, 2),
               0xA2: (False, 2), 0xA3: (False, 2), 0xA8: (False, 1), 0xA9: (False, 2),
               0xC0: (True, 1), 0xC1: (True, 1), 0xC2: (False, 2), 0xC4: (True, 0),
               0xC5: (True, 0), 0xC6: (True, 1), 0xC7: (True, 2), 0xC8: (False, 3),
               0xCA: (False, 2), 0xCD: (False, 1), 0xD4: (False, 1), 0xD5: (False, 1),
               0xE8: (False, 2), 0xE9: (False, 2), 0xEA: (False, 4), 0xEB: (False, 1),
               0xFE: (True, 0), 0xFF: (True, 0), 0xF6: (True, 0), 0xF7: (True, 0)})
for op in range(0x84, 0x90):
    _TABLE[op] = (True, 0)
for op in list(range(0x70, 0x80)) + list(range(0xE0, 0xE8)) + list(range(0xB0, 0xB8)):
    _TABLE[op] = (False, 1)
for op in range(0xB8, 0xC0):
    _TABLE[op] = (False, 2)
for op in list(range(0xD0, 0xD4)) + list(range(0xD8, 0xE0)):
    _TABLE[op] = (True, 0)

# 0F page: (ModR/M, immediate bytes).
_TABLE_0F = {0x20: (False, 0), 0x22: (False, 0), 0x26: (False, 0), 0x28: (True, 0),
             0x2A: (True, 0), 0x2D: (True, 0), 0x31: (True, 0), 0x33: (True, 0),
             0x39: (True, 1), 0x3B: (True, 1), 0x91: (False, 0), 0x92: (False, 0),
             0x94: (True, 0), 0x95: (True, 0), 0x9C: (True, 2), 0x9E: (False, 0),
             0xFF: (False, 1)}
for op in range(0x10, 0x20):
    _TABLE_0F[op] = (True, 1 if op >= 0x18 else 0)


def _modrm_length(modrm: int) -> int:
    mod, rm = modrm >> 6, modrm & 7
    if mod == 0:
        return 3 if rm == 6 else 1
    return {1: 2, 2: 3, 3: 1}[mod]


def length(read, address: int) -> int:
    """Length of the instruction at a linear address; read(linear) gives a byte."""
    n = 0
    op = read(address)
    while op in PREFIXES and n < 15:
        n += 1
        op = read(address + n)
    n += 1
    if op == 0x0F:
        op = 0x0F00 | read(address + n)
        n += 1
        modrm, imm = _TABLE_0F.get(op & 0xFF, (True, 0))
    else:
        modrm, imm = _TABLE.get(op, (False, 0))
    if modrm:
        byte = read(address + n)
        n += _modrm_length(byte)
        if op in (0xF6, 0xF7) and not (byte >> 3) & 6:
            imm = 1 if op == 0xF6 else 2
    return n + imm
