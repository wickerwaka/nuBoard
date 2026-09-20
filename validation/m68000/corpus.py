"""Native, reset-executable differential cases; no internal CPU state injection.

The wrappers save registers and SR before writing reporting markers. Exceptions
have individual entry stubs, so a wrong vector is a result, not a host timeout.
The collector's TRAP #15 is outside the timed region and is never confused with
a TRAP #15 under test. Undefined SR bits remain in the raw snapshot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess

from .runner import ROOT

CODE = 0x10000
RESULT = 0x5000
BEGIN = 0x6000
END = 0x6002
DEFERRED = ["external interrupts", "bus arbitration", "injected bus errors",
            "VPA peripheral cycles", "supervisor STOP and RESET",
            "arbitrary imported prefetch state", "exhaustive opcode/register combinations"]


@dataclass(frozen=True)
class Case:
    name: str
    family: str
    body: str
    setup: str = ""
    vector: int = 0
    sr_mask: int = 0xFFFF
    operand: int = 0x7FFFFFFF
    ccr: int = 0x10


def defined_sr_mask(case):
    """Operand-sensitive CCR policy, independent of legacy manifest masks.

    M68000PRM DIVS/DIVU: N/Z undefined on overflow; V remains defined.
    CHK preserves X and specifies N on a trap; Z/V/C are undefined.
    Raw snapshots are never changed by this reporting policy.
    """
    if case["vector"] == 5:
        return 0xFFF1
    if case["vector"] == 6:
        return 0xFFF8
    if case["vector"] == 3:
        return 0xFFFF
    if case["family"] in ("divs", "divu") and not case["setup"]:
        dividend = case["operand"]
        if case["family"] == "divs":
            if dividend & 0x80000000:
                dividend -= 1 << 32
            quotient = (abs(dividend) // 2) * (-1 if dividend < 0 else 1)
            overflow = not -32768 <= quotient <= 32767
        else:
            overflow = dividend // 2 > 65535
        return 0xFFF3 if overflow else 0xFFFF
    return case["sr_mask"]


def cases(profile="smoke", seed=68000):
    """Enumerate a finite coverage matrix with stable case names and ordering."""
    result = []

    def add(name, body, setup="", vector=0, mask=0xFFFF, family=None):
        result.append(Case(name, family or name.split(".")[0], body, setup, vector, mask))

    add("nop", "nop")
    add("moveq", "moveq #-128,%d0")
    eas = {"indirect": "(%a0)", "postincrement": "(%a0)+",
           "predecrement": "-(%a0)", "displacement": "16(%a0)",
           "indexed": "8(%a0,%d1.w)", "absolute_w": "0x2040.w",
           "absolute_l": "0x2040.l"}
    selected_eas = eas if profile == "full" else {"indirect": "(%a0)"}
    sizes = ("b", "w", "l") if profile == "full" else ("w",)
    for size in sizes:
        for operation in ("add", "sub", "and", "or", "cmp", "eor"):
            add(f"{operation}.{size}.register", f"{operation}.{size} %d1,%d0")
            add(f"{operation}i.{size}", f"{operation}i.{size} #1,%d0")
            for mode, ea in selected_eas.items():
                if operation != "eor":
                    add(f"{operation}.{size}.{mode}.read", f"{operation}.{size} {ea},%d0")
                if operation != "cmp":
                    add(f"{operation}.{size}.{mode}.write", f"{operation}.{size} %d0,{ea}")
        for mode, ea in selected_eas.items():
            add(f"move.{size}.{mode}.read", f"move.{size} {ea},%d0")
            add(f"move.{size}.{mode}.write", f"move.{size} %d0,{ea}")
            add(f"move.{size}.{mode}.memory", f"move.{size} {ea},(%a1)")
        for operation in ("clr", "neg", "negx", "not", "tst"):
            add(f"{operation}.{size}.register", f"{operation}.{size} %d0")
            for mode, ea in selected_eas.items():
                add(f"{operation}.{size}.{mode}", f"{operation}.{size} {ea}")
        for operation in ("addq", "subq"):
            add(f"{operation}.{size}", f"{operation}.{size} #1,%d0")
        for operation in ("addx", "subx"):
            add(f"{operation}.{size}", f"{operation}.{size} %d1,%d0")
            add(f"{operation}.{size}.memory", f"{operation}.{size} -(%a0),-(%a1)")
        add(f"cmpm.{size}", f"cmpm.{size} (%a0)+,(%a1)+")
        for operation in ("asl", "asr", "lsl", "lsr", "rol", "ror", "roxl", "roxr"):
            add(f"{operation}.{size}", f"{operation}.{size} %d1,%d0")
    for operation in ("bchg", "bclr", "bset", "btst"):
        add(operation, f"{operation} %d1,%d0")
        add(f"{operation}.memory", f"{operation} #7,(%a0)")
    for operation in ("adda", "suba", "cmpa", "movea"):
        for size in ("w", "l"):
            add(f"{operation}.{size}", f"{operation}.{size} %d0,%a0")
    for operation in ("muls", "mulu", "divs", "divu"):
        add(operation, f"{operation}.w %d1,%d0", mask=0xFFF1 if operation.startswith("div") else 0xFFFF)
    for operation in ("abcd", "sbcd"):
        add(operation, f"{operation} %d1,%d0", mask=0xFFF5)
        add(f"{operation}.memory", f"{operation} -(%a0),-(%a1)", mask=0xFFF5)
    add("nbcd", "nbcd %d0", mask=0xFFF5)
    add("tas", "tas (%a0)")
    add("swap", "swap %d0")
    add("ext.w", "ext.w %d0")
    add("ext.l", "ext.l %d0")
    add("exg", "exg %d0,%a0")
    add("lea", "lea 8(%a0,%d1.w),%a2")
    add("pea", "pea 16(%a0)")
    add("link", "link %a6,#-16\n unlk %a6")
    add("movem.store", "movem.l %d0-%d7/%a0-%a6,-(%sp)")
    add("movem.load", "movem.w (%a0)+,%d0-%d7/%a1-%a6")
    for size in ("w", "l"):
        add(f"movep.{size}.store", f"movep.{size} %d0,0(%a0)")
        add(f"movep.{size}.load", f"movep.{size} 0(%a0),%d0")
    for condition in ("t", "f", "hi", "ls", "cc", "cs", "ne", "eq",
                      "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le"):
        add(f"s{condition}", f"s{condition} %d0", family="scc")
        add(f"db{condition}", f"db{condition} %d1,1f\n moveq #5,%d0\n1: nop", family="dbcc")
        if condition not in ("t", "f"):
            add(f"b{condition}", f"b{condition} 1f\n moveq #5,%d0\n1: nop", family="bcc")
    add("bsr_rts", "bsr 1f\n bra 2f\n1: addq.l #1,%d0\n rts\n2: nop")
    add("jmp", "jmp 1f\n illegal\n1: nop")
    add("jsr_rts", "jsr 1f\n bra 2f\n1: addq.l #1,%d0\n rts\n2: nop")
    add("rtr", "pea 1f\n move.w #0x15,-(%sp)\n rtr\n1: nop")
    add("rte", "pea 1f\n move.w #0x2700,-(%sp)\n rte\n1: nop")
    add("move_usp", "move %a0,%usp\n move %usp,%a2")
    add("move_sr", "move.w %sr,%d0")
    for op in ("ori", "andi", "eori"):
        add(f"{op}_ccr", f"{op} #0x15,%ccr")
        add(f"{op}_sr", f"{op} #0x2715,%sr")
    add("user_move", "move.l (%a0),%d0", "andi.w #0xdfff,%sr")
    for name, body, vector in (
        ("illegal", "illegal", 4), ("line_a", ".word 0xa000", 10),
        ("line_f", ".word 0xf000", 11), ("divide_zero", "divu.w #0,%d0", 5),
        ("chk", "chk.w #1,%d0", 6), ("trapv", "ori #2,%ccr\n trapv", 7),
        ("trace", "ori.w #0x8000,%sr\n nop\n nop", 9),
        ("address_read", "move.w 1(%a0),%d0", 3),
        ("address_write", "move.w %d0,1(%a0)", 3),
        ("address_fetch", "jmp 0x10001", 3),
    ):
        add(f"exception.{name}", body, vector=vector,
            mask=0xFFE0 if vector in (3, 5, 6) else 0xFFFF, family="exception")
    for number in range(16):
        add(f"trap.{number}", f"trap #{number}", vector=32 + number)
    add("exception.privilege", "move.w #0x2700,%sr",
        "andi.w #0xdfff,%sr", vector=8, family="exception")
    add("reads.sequence", "\n".join(f"move.w (%a0)+,%d{i}" for i in range(8)))
    add("writes.sequence", "\n".join(f"move.w %d{i},(%a0)+" for i in range(8)))

    # Focused bus/addressing cases supplement the regular operand matrix.
    # Keep these names independent of random operands so they are easy to replay.
    for size in ("b", "w", "l"):
        add(f"move.{size}.pc_relative", f"move.{size} literal(%pc),%d0")
        add(f"move.{size}.pc_indexed", f"move.{size} literal-2(%pc,%d1.w),%d0")
        add(f"move.{size}.odd_byte_lane", f"move.b 1(%a0),%d0\n move.b %d0,3(%a1)")
    for count in (0, 1, 7, 8, 15, 16, 31, 32, 63):
        for operation in ("lsl", "asr", "roxl"):
            add(f"{operation}.count_{count}", f"{operation}.l %d1,%d0",
                f"moveq #{count},%d1")
    for operation in ("asl", "asr", "lsl", "lsr", "rol", "ror", "roxl", "roxr"):
        add(f"{operation}.memory", f"{operation}.w (%a0)")
    add("stack.byte_increment", "move.b (%sp)+,%d0\n move.b %d0,-(%sp)")
    add("movem.self_base", "movem.l %d0-%d7/%a0-%a7,-(%a0)")
    add("memory.page_boundary", "move.l 0x2ffe,%d0\n move.l %d0,0x2ffe")
    add("abcd.chain", "abcd %d1,%d0\n abcd %d2,%d0", mask=0xFFF5)
    add("sbcd.chain", "sbcd %d1,%d0\n sbcd %d2,%d0", mask=0xFFF5)
    add("divs.negative", "divs.w %d1,%d0", "move.l #-32768,%d0\n moveq #-3,%d1")
    add("divu.nonoverflow", "divu.w %d1,%d0", "move.l #65535,%d0\n moveq #7,%d1")

    if profile == "smoke":
        return result
    rng = random.Random(seed)
    expanded = []
    for case in result:
        # Exceptions have directed triggering operands; randomization must not
        # silently turn an expected fault into a normal instruction.
        if case.vector:
            expanded.append(case)
            continue
        operands = [0, 1, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF]
        operands += [rng.getrandbits(32) for _ in range(16)]
        for index, operand in enumerate(operands):
            values = asdict(case)
            values.update(name=f"{case.name}.{index:02d}", operand=operand, ccr=index % 32)
            expanded.append(Case(**values))
    return expanded


def assembly(case):
    normal_trap = case.vector != 47
    body = case.body
    if "literal" in body:
        # Brief indexed PC addressing has an eight-bit displacement. Keep its
        # operand next to the instruction, not beyond the exception stubs.
        body += f"\n bra 1f\n .balign 2\nliteral:\n .long 0x{case.operand:08x}\n1:"
    lines = [".text", ".global _start", "_start:",
             " move.l #0x4ff0,%a0", " move %a0,%usp"]
    for index in range(8):
        value = case.operand if index == 0 else (2 if index == 1 else index * 0x11111111)
        lines.append(f" move.l #0x{value:08x},%d{index}")
    for index in range(7):
        lines.append(f" move.l #0x{0x2040 + index * 8:x},%a{index}")
    lines += [f" move.w #0x1111,0x{BEGIN:x}",
              f" move.w #0x{0x2700 | case.ccr:x},%sr", case.setup,
              "body:", body, "normal_exit:",
              f" move.w %sr,0x{RESULT + 64:x}",
              f" movem.l %d0-%d7/%a0-%a7,0x{RESULT:x}",
              f" move.w #0,0x{RESULT + 66:x}",
              f" move.w #0x2222,0x{END:x}", " trap #15", " bra normal_exit"]
    for vector in range(2, 48):
        lines.append(f"vector_{vector}:")
        if vector != 47 or not normal_trap:
            lines += [f" move.w %sr,0x{RESULT + 64:x}",
                      f" movem.l %d0-%d7/%a0-%a7,0x{RESULT:x}",
                      f" move.w #{vector},0x{RESULT + 66:x}",
                      f" move.w #0x2222,0x{END:x}"]
        lines += [" jmp finish"]
    lines += ["finish:", " move %usp,%a0", f" move.l %a0,0x{RESULT + 68:x}",
              f" move.l %sp,0x{RESULT + 72:x}",
              # Preserve the raw frame before the completion write resets CPU.
              " move.l (%sp),%d0", f" move.l %d0,0x{RESULT + 76:x}",
              " move.l 4(%sp),%d0", f" move.l %d0,0x{RESULT + 80:x}",
              " move.l 8(%sp),%d0", f" move.l %d0,0x{RESULT + 84:x}",
              " move.w 12(%sp),%d0", f" move.w %d0,0x{RESULT + 88:x}",
              " move.l #1,0x100004", " bra ."]
    return "\n".join(lines) + "\n"


def toolchain():
    local = ROOT / "build/deps/binutils/usr"
    environment = os.environ.copy()
    if local.exists():
        environment["LD_LIBRARY_PATH"] = str(local / "lib/x86_64-linux-gnu")
    paths = {name: shutil.which(f"m68k-linux-gnu-{name}") or
             str(local / f"bin/m68k-linux-gnu-{name}") for name in ("as", "ld", "nm", "objcopy")}
    return paths, environment


def build_case(case, directory):
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{case.name}.s"
    obj = source.with_suffix(".o")
    elf = source.with_suffix(".elf")
    binary = source.with_suffix(".bin")
    source.write_text(assembly(case))
    tools, environment = toolchain()
    commands = [
        [tools["as"], "-march=68000", "-o", str(obj), str(source)],
        [tools["ld"], "-Ttext", hex(CODE), "-o", str(elf), str(obj)],
        [tools["objcopy"], "-O", "binary", str(elf), str(binary)],
    ]
    for command in commands:
        subprocess.run(command, env=environment, check=True, capture_output=True)
    symbols = {}
    for line in subprocess.check_output([tools["nm"], str(elf)], env=environment, text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    vectors = bytearray(256 * 4)
    struct.pack_into(">II", vectors, 0, 0x3FF0, CODE)
    for vector in range(2, 48):
        struct.pack_into(">I", vectors, vector * 4, symbols[f"vector_{vector}"])
    segments = {0: bytes(vectors), CODE: binary.read_bytes(),
                0x2000: bytes(range(256)), RESULT: bytes([0xCC]) * 96}
    digest = hashlib.sha256(b"".join(struct.pack(">I", address) + data
                                    for address, data in sorted(segments.items()))).hexdigest()
    return {"case": asdict(case), "symbols": symbols, "sha256": digest,
            "segments": {str(address): data.hex() for address, data in segments.items()},
            "extra_pages": [3, 4, 5, 6], "assembly": source.read_text()}


def snapshot(harness, lane):
    raw = harness.read_memory(lane, RESULT, 90)
    values = struct.unpack_from(">16I", raw)
    registers = dict(zip([f"d{i}" for i in range(8)] + [f"a{i}" for i in range(8)], values))
    sr, vector, usp, ssp = struct.unpack_from(">HHII", raw, 64)
    frame_length = 14 if vector == 3 else 6
    return {"registers": registers, "sr": sr, "vector": vector, "usp": usp,
            "ssp_at_collector": ssp, "frame": raw[76:76 + frame_length].hex(),
            "data": harness.read_memory(lane, 0x2000, 256).hex(),
            "stack": harness.read_memory(lane, 0x3F00, 256).hex(),
            "user_stack": harness.read_memory(lane, 0x4F00, 256).hex()}
