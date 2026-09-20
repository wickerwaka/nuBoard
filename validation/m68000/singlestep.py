"""Reset-executable adapter for a qualified register-only single-step subset.

This is intentionally a qualified subset, not a claim of general single-step
support. Trace exceptions perturb SR.T and prefetch; neither suite bus timing
nor final prefetch contents is claimed as checked by this adapter.
"""

import struct

REVISION = "64b253116a3de04aaac4346c43680960dc9b67e5"
BOOT = 0xF00000
HANDLER = BOOT + 0x100
REGISTERS = BOOT + 0x200
RESULT = BOOT + 0x1000
REGISTER_NAMES = [f"d{i}" for i in range(8)] + [f"a{i}" for i in range(7)]


class UnsupportedVector(ValueError):
    pass


def register_instruction(opcode):
    """Only two-byte, non-faulting, non-SR-writing operations qualify here.

    Do not extend this by mnemonic alone: ADD/SUB files also contain address
    register and memory forms, which need separate wrapper qualification.
    """
    if opcode & 0xF100 == 0x7000:
        return True  # MOVEQ
    group = opcode >> 12
    opmode = (opcode >> 6) & 7
    register_ea = opcode & 0x38 == 0
    return register_ea and group in (0x8, 0x9, 0xB, 0xC, 0xD) and opmode <= 2


def words(*values):
    return struct.pack(">" + "H" * len(values), *values)


def long(value):
    return struct.pack(">I", value & 0xFFFFFFFF)


def make_image(test):
    initial = test["initial"]
    pc = initial["pc"] - 4
    prefetch = initial["prefetch"]
    if not register_instruction(prefetch[0]):
        raise UnsupportedVector("only MOVEQ and register-source ADD/SUB/AND/OR/CMP qualify")
    if initial["ssp"] & 1 or pc & 1:
        raise UnsupportedVector("odd stack/PC is not supported")
    memory = dict(initial["ram"])
    if any(not 0 <= value <= 255 for value in memory.values()):
        raise UnsupportedVector("expected byte RAM from the pinned upstream decoder")
    ssp = initial["ssp"]
    frame = (ssp - 6) & 0xFFFFFF
    occupied = set(memory) | set(dict(test["final"]["ram"]))
    occupied.update(range(pc, pc + 8))
    reserved = set(range(0, 40)) | set(range(BOOT, RESULT + 4096))
    if occupied & reserved or set(range(frame, frame + 6)) & (occupied | reserved):
        raise UnsupportedVector("fixture overlaps bootstrap, vectors, results, or trace frame")
    if frame + 6 > 0x1000000:
        raise UnsupportedVector("stack frame wraps the physical address space")

    segments = {address: bytes([value]) for address, value in memory.items()
                if not pc <= address < pc + 4}
    segments[pc] = words(*prefetch)
    segments[0] = long(ssp - 6) + long(BOOT)
    segments[36] = long(HANDLER)
    segments[frame] = words(initial["sr"] | 0x8000) + long(pc)
    segments[REGISTERS] = b"".join(long(initial[name]) for name in REGISTER_NAMES)

    # MOVEA.L #USP,A0; MOVE A0,USP; MOVEM.L registers,D0-D7/A0-A6; RTE.
    # RTE establishes the original stack bank/SR and executes one traced op.
    segments[BOOT] = (
        words(0x207C) + long(initial["usp"]) + words(0x4E60, 0x4CF9, 0x7FFF)
        + long(REGISTERS) + words(0x4E73)
    )
    # Save registers before using any scratch registers, followed by the trace
    # frame's SR/PC and both stack pointers. Finally signal the normal MMIO pass.
    segments[HANDLER] = (
        words(0x48F9, 0x7FFF) + long(RESULT)
        + words(0x23CF) + long(RESULT + 60)
        + words(0x4E68, 0x23C8) + long(RESULT + 64)
        + words(0x33D7) + long(RESULT + 68)
        + words(0x23EF, 2) + long(RESULT + 70)
        + words(0x23FC) + long(1) + long(0x100004)
        + words(0x4E72, 0x2700)
    )
    return segments, (RESULT >> 12,)


def check_result(harness, lane, test):
    raw = harness.read_memory(lane, RESULT, 74)
    actual = dict(zip(REGISTER_NAMES, struct.unpack_from(">15I", raw)))
    actual["ssp"] = (struct.unpack_from(">I", raw, 60)[0] + 6) & 0xFFFFFFFF
    actual["usp"] = struct.unpack_from(">I", raw, 64)[0]
    actual["sr"] = ((struct.unpack_from(">H", raw, 68)[0] & ~0x8000)
                    | (test["initial"]["sr"] & 0x8000))
    actual["pc"] = (struct.unpack_from(">I", raw, 70)[0] + 4) & 0xFFFFFFFF
    expected = test["final"]
    differences = {name: {"expected": expected[name], "actual": value}
                   for name, value in actual.items() if value != expected[name]}
    memory_differences = []
    for address, value in expected["ram"]:
        observed = harness.read_memory(lane, address, 1)[0]
        if observed != value:
            memory_differences.append({"address": address, "expected": value, "actual": observed})
    return {"passed": not differences and not memory_differences,
            "registers": actual, "register_differences": differences,
            "memory_differences": memory_differences,
            "prefetch_checked": False, "suite_bus_timing_checked": False}
