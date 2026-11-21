"""(work order 29) The V35S secure mode's translation table: bench-side tables and the secure benches.

The core v2 holds the table in two block RAMs in v35_queue, loaded through v35_top's load port
(`tt_we tt_a tt_d`; the harness's register C8h, runner.Harness.load_table). The core never
initialises it: the 1:1 table below is test stimulus only, loaded by the bench.

Entry k of a table is the opcode the encoded byte k decodes to (the book's "encrypted opcode ...
as an address, ... the correct V35 opcode as data"). A program is encoded through the inverse:
every opcode-position byte b is replaced by inv[b].

Tables by name (V35_TTAB, read by the replay's lanes and the program gates' _sim):
  identity   T(x) = x
  perm       T(x) = rotl8(x, 3) xor A7h (a bijection without a fixed point)
  none       nothing loaded
  FILE       256 bytes as hex text
"""
from __future__ import annotations

import os
from pathlib import Path

IDENTITY = bytes(range(256))


def _rotl8(x: int, n: int) -> int:
    return ((x << n) | (x >> (8 - n))) & 0xFF


PERM = bytes(_rotl8(x, 3) ^ 0xA7 for x in range(256))


def inverse(table: bytes) -> bytes:
    inv = bytearray(256)
    seen = set()
    for k, v in enumerate(table):
        if v in seen:
            raise ValueError("the table is not a bijection")
        seen.add(v)
        inv[v] = k
    return bytes(inv)


def table_named(name: str) -> bytes:
    if name == "identity":
        return IDENTITY
    if name == "perm":
        return PERM
    data = bytes.fromhex("".join(Path(name).read_text().split()))
    if len(data) != 256:
        raise ValueError(f"{name}: a table is 256 bytes")
    return data


def env_table(default: str | None = None) -> bytes | None:
    """The table V35_TTAB names (or `default`; None: none loaded)."""
    name = os.environ.get("V35_TTAB", default)
    return None if not name or name == "none" else table_named(name)


# ------------------------------------------------------------------ the encoder
# A length decoder of the V30 / V35 instruction set, written here from the book's opcode map
# (independent of the core's generated decode tables), for the bench programs' code regions:
# every byte of a region is classed as
#   pfx   a prefix (segment 26 2E 36 3E, REP F2 F3, REPC 65, REPNC 64, BUSLOCK F0)
#   op    an opcode: the first byte of an instruction, or the byte behind a prefix / REP
#   op2   the 0F page's second byte
#   modrm a ModR/M byte (the group opcodes' reg field included)
#   imm   an immediate, a displacement, an address, a port, a type byte (BRKS / BRKN / INT)
PREFIXES = {0x26, 0x2E, 0x36, 0x3E, 0xF2, 0xF3, 0x64, 0x65, 0xF0}


def _one_byte_form(op: int):
    """(has_modrm, immediate bytes, immediate bytes when the ModR/M reg field is 0 or 1)."""
    if op < 0x40 and op & 7 < 4:
        return True, 0, None
    if op < 0x40 and op & 7 == 4:
        return False, 1, None
    if op < 0x40 and op & 7 == 5:
        return False, 2, None
    if op < 0x40:
        return False, 0, None
    if op < 0x62:
        return False, 0, None
    table = {
        0x62: (True, 0), 0x63: (False, 1), 0x68: (False, 2), 0x69: (True, 2), 0x6A: (False, 1),
        0x6B: (True, 1), 0x80: (True, 1), 0x81: (True, 2), 0x82: (True, 1), 0x83: (True, 1),
        0x9A: (False, 4), 0xA0: (False, 2), 0xA1: (False, 2), 0xA2: (False, 2), 0xA3: (False, 2),
        0xA8: (False, 1), 0xA9: (False, 2), 0xC0: (True, 1), 0xC1: (True, 1), 0xC2: (False, 2),
        0xC4: (True, 0), 0xC5: (True, 0), 0xC6: (True, 1), 0xC7: (True, 2), 0xC8: (False, 3),
        0xCA: (False, 2), 0xCD: (False, 1), 0xD4: (False, 1), 0xD5: (False, 1),
        0xE0: (False, 1), 0xE1: (False, 1), 0xE2: (False, 1), 0xE3: (False, 1),
        0xE4: (False, 1), 0xE5: (False, 1), 0xE6: (False, 1), 0xE7: (False, 1),
        0xE8: (False, 2), 0xE9: (False, 2), 0xEA: (False, 4), 0xEB: (False, 1), 0xF1: (False, 1),
        0xFE: (True, 0), 0xFF: (True, 0),
    }
    if op in table:
        return (*table[op], None)
    if 0x70 <= op <= 0x7F:
        return False, 1, None
    if 0x84 <= op <= 0x8F:
        return True, 0, None
    if 0xB0 <= op <= 0xB7:
        return False, 1, None
    if 0xB8 <= op <= 0xBF:
        return False, 2, None
    if 0xD0 <= op <= 0xD3 or 0xD8 <= op <= 0xDF:
        return True, 0, None
    if op == 0xF6:
        return True, 0, 1
    if op == 0xF7:
        return True, 0, 2
    if op in (0x60, 0x61, 0x6C, 0x6D, 0x6E, 0x6F, 0xC3, 0xC9, 0xCB, 0xCC, 0xCE, 0xCF, 0xD6,
              0xD7, 0xEC, 0xED, 0xEE, 0xEF, 0xF4, 0xF5) or 0x90 <= op <= 0x9F \
            or 0xA4 <= op <= 0xAF or 0xF8 <= op <= 0xFD:
        return False, 0, None
    raise ValueError(f"opcode {op:02X} is not in the bench's length decoder")


# the 0F page's forms the benches use: second byte -> (has_modrm, immediate bytes)
PAGE_0F = {**{b: (True, 0) for b in range(0x10, 0x18)}, **{b: (True, 1) for b in range(0x18, 0x1C)},
           **{b: (True, 1) for b in range(0x1C, 0x20)}, 0x20: (False, 0), 0x22: (False, 0),
           0x26: (False, 0), 0x28: (True, 0), 0x2A: (True, 0), 0x91: (False, 0), 0x92: (False, 0),
           0x9E: (False, 0)}


def _modrm_len(m: int) -> int:
    mod, rm = m >> 6, m & 7
    return 2 if (mod == 0 and rm == 6) or mod == 2 else 1 if mod == 1 else 0


def classify(code: bytes, start: int, end: int) -> dict[int, str]:
    """Class of every byte offset in code[start:end], decoded linearly from start."""
    out = {}
    k = start
    while k < end:
        while code[k] in PREFIXES:
            out[k] = "pfx"
            k += 1
        op = code[k]
        out[k] = "op"
        k += 1
        if op == 0x0F:
            b = code[k]
            out[k] = "op2"
            k += 1
            if b not in PAGE_0F:
                raise ValueError(f"0F {b:02X} is not in the bench's length decoder")
            has_modrm, imm = PAGE_0F[b]
            grp = None
        else:
            has_modrm, imm, grp = _one_byte_form(op)
        if has_modrm:
            m = code[k]
            out[k] = "modrm"
            k += 1
            n = _modrm_len(m)
            if grp is not None and (m >> 3) & 7 < 2:
                n += grp
            imm += n
        for _ in range(imm):
            out[k] = "imm"
            k += 1
    if k != end:
        raise ValueError(f"the region {start:#x}..{end:#x} does not end on an instruction")
    return out


def assemble_labels(source: str, org: int):
    """asm.assemble with the label table (the same two passes over the same parser)."""
    from .asm import _assembler, _expand
    a = _assembler()
    lines = a._parse_lines(_expand(source))
    labels = {}
    for pass_ in (1, 2):
        out = bytearray()
        pc = org
        for _ln, kind, payload in lines:
            if kind == "label":
                labels[payload] = pc
            elif kind == "org":
                pc = payload
            elif kind == "db":
                vals = [a._val(v, labels, pass_) & 0xFF for v in payload]
                out += bytes(vals)
                pc += len(vals)
            elif kind == "dw":
                for v in payload:
                    x = a._val(v, labels, pass_) & 0xFFFF
                    out += bytes((x & 0xFF, x >> 8))
                    pc += 2
            else:
                c = a._encode(payload, pc, labels, pass_)
                out += c
                pc += len(c)
    return bytes(out), labels


def encode(code: bytes, classes: dict[int, str], table: bytes, which=("pfx", "op")) -> bytes:
    """The image through T^-1: every byte whose class is in `which` replaced by inv[byte]."""
    inv = inverse(table)
    out = bytearray(code)
    for k, c in classes.items():
        if c in which:
            out[k] = inv[out[k]]
    return bytes(out)


# ------------------------------------------------------------------ the bench program
ROOT = Path(__file__).resolve().parents[2]
RES = 0x2000            # the results (DS0 0: 2000h..20FFh)
DATA = 0x3000           # preloaded data (3000h..31FFh); DS1 = 0010h reads 3100h.. through 26h
SP0 = 0x7F00
V_BRKS, V_BRKN, V_INT = 0x20, 0x21, 0x22     # (the IVT page below the code at 100h)

MAIN = f"""\
main:
    MOV SP, {SP0:04X}h
    XOR AW, AW
    MOV SS, AW
    MOV DS0, AW
    MOV AW, 0010h
    MOV DS1, AW
"""
# (bench B only) the secure body entered as BRKS's handler (the vector is in the IVT)
MAIN_BRKS = f"    DB 0F1h, {V_BRKS:02X}h\n"
# the body: every prefix kind, the byte behind each, REP / REPNE / REPC / REPNC with a string
# opcode and with a segment prefix on either side, BUSLOCK, the 0F page (with a ModR/M, an
# immediate, a displacement and a prefix), group opcodes, immediates and displacements, BRKN
# and its RETI, INT n and its RETI, the FPO trap (D8: vector 7) and its RETI, PSW read back
BODY = f"""\
body:
    MOV AW, 1234h
    MOV [2000h], AW
    ADD AW, 5A5Ah
    MOV [2002h], AW
    DB 26h
    MOV AL, [3000h]
    MOV [2004h], AL
    DB 2Eh
    MOV AL, [3001h]
    MOV [2005h], AL
    DB 36h
    MOV AL, [3002h]
    MOV [2006h], AL
    DB 3Eh
    MOV AL, [3003h]
    MOV [2007h], AL
    DB 26h, 2Eh
    MOV AW, [3004h]
    MOV [2008h], AW
    MOV byte [2010h], 0C3h
    ADD byte [2010h], 33h
    MOV word [2012h], 7FFEh
    INC word [2012h]
    MOV byte [2014h], 5Ah
    NOT byte [2014h]
    MOV CW, AW
    XOR CW, 0F0Fh
    MOV [2016h], CW
    MOV BW, 2000h
    MOV [BW+20h], AW
    MOV DW, [BW+1020h]
    MOV [BW+22h], DW
    MOV IX, 3010h
    MOV IY, 2030h
    MOV CW, 8
    DB 0FCh
    DB 0F3h, 0A4h
    MOV IX, 3020h
    MOV IY, 2040h
    MOV CW, 4
    DB 0F3h, 26h, 0A4h
    MOV IX, 3028h
    MOV IY, 2044h
    MOV CW, 4
    DB 26h, 0F3h, 0A5h
    MOV IX, 3030h
    MOV IY, 3038h
    MOV CW, 6
    DB 0F2h, 0A6h
    MOV [2050h], CW
    MOV IX, 3040h
    MOV IY, 3044h
    MOV CW, 6
    DB 65h, 0A6h
    MOV [2052h], CW
    MOV IX, 3048h
    MOV IY, 304Ch
    MOV CW, 6
    DB 64h, 0A6h
    MOV [2054h], CW
    MOV AL, 77h
    DB 0F0h
    XCH AL, [2056h]
    MOV [2057h], AL
    MOV byte [2060h], 00h
    DB 0Fh, 1Ch, 06h, 60h, 20h, 03h
    MOV CL, 6
    DB 0Fh, 16h, 06h, 60h, 20h
    DB 26h
    DB 0Fh, 1Ch, 06h, 61h, 30h, 05h
    DB 26h
    MOV AL, [3061h]
    MOV [2061h], AL
    DB 63h, {V_BRKN:02X}h
    INC byte [2070h]
    DB 0CDh, {V_INT:02X}h
    INC byte [2071h]
    DB 0D8h, 0C0h
    INC byte [2072h]
    PUSH PSW
    POP AW
    AND AW, 7FFFh
    MOV [2080h], AW
    MOV [2082h], SP
    MOV DW, 0FF00h
    OUT DW, AL
    HALT
done:
    BR done
"""
H_BRKN = """\
h_brkn:
    MOV byte [2070h], 0A0h
    RETI
"""
H_INT = """\
h_int:
    MOV byte [2071h], 0B0h
    RETI
"""
H_FPO = """\
h_fpo:
    MOV BP, SP
    ADD word [BP], 2
    MOV byte [2072h], 0C0h
    RETI
"""
REGIONS = ("main", "body", "h_brkn", "h_int", "h_fpo")
# each bench's regions' modes (S: runs in secure mode, encoded; N: normal mode, plain)
MODES = {
    # A: N/S low from reset: everything secure but BRKN's handler (BRKN sets MD 1)
    "A": {"reset": "S", "main": "S", "body": "S", "h_brkn": "N", "h_int": "S", "h_fpo": "S"},
    # B: N/S high; BRKS enters the body; every handler runs normal (BRKN: MD 1; INT and the
    # trap: MD <- N/S = 1) and its RETI restores MD 0
    "B": {"reset": "N", "main": "N", "body": "S", "h_brkn": "N", "h_int": "N", "h_fpo": "N"},
}


def data_bytes() -> bytes:
    d = bytearray((_rotl8((k * 37 + 11) & 0xFF, k % 8) ^ (k >> 3)) & 0xFF for k in range(0x200))
    # the CMPBK runs: 4 equal bytes, then a mismatch (REPNE stops at once, REPC / REPNC by CY)
    for a, b in ((0x30, 0x38), (0x40, 0x44), (0x48, 0x4C)):
        for j in range(4):
            d[a + j] = d[b + j] = 0x50 + j
        d[a + 4], d[b + 4] = 0x10, 0x90
    return bytes(d)


def bench_program(bench: str):
    """(code at 100h, labels, {offset: (class, region)}, the IVT page)."""
    src = MAIN + (MAIN_BRKS if bench == "B" else "") + BODY + H_BRKN + H_INT + H_FPO
    code, labels = assemble_labels(src, 0x100)
    bounds = [labels[r] - 0x100 for r in REGIONS] + [len(code)]
    regions = {r: (bounds[i], bounds[i + 1]) for i, r in enumerate(REGIONS)}
    classes = {}
    for r, (a, b) in regions.items():
        classes.update({k: (c, r) for k, c in classify(code, a, b).items()})
    ivt = bytearray(0x100)
    for vec, lab in ((V_BRKS, "body"), (V_BRKN, "h_brkn"), (V_INT, "h_int"), (7, "h_fpo")):
        ivt[4 * vec:4 * vec + 4] = labels[lab].to_bytes(2, "little") + b"\x00\x00"
    return code, labels, classes, bytes(ivt)


RESET = bytes([0xEA, 0x00, 0x01, 0x00, 0x00])
RESET_KINDS = {0: "op", 1: "imm", 2: "imm", 3: "imm", 4: "imm"}
# the position kinds the reading built translates (the user's ruling 3: prefixes and the opcode
# behind a prefix / REP translated; the 0F page's second byte, ModR/M, operands not)
ENCODED = frozenset({"op", "pfx", "pfx behind prefix", "op behind segment", "op behind REP",
                     "op behind BUSLOCK"})
KINDS = ("op", "pfx", "pfx behind prefix", "op behind segment", "op behind REP",
         "op behind BUSLOCK", "op2", "modrm", "imm")


def kinds(bench: str) -> dict[int, str]:
    """Each S-region byte's position kind (offset in the code at 100h)."""
    code, labels, classes, _ = bench_program(bench)
    modes = MODES[bench]
    out, prev = {}, None
    for k in sorted(classes):
        c, r = classes[k]
        if modes[r] != "S":
            prev = None
            continue
        key = c
        if c == "op" and prev == "pfx":
            key = ("op behind REP" if code[k - 1] in (0xF2, 0xF3, 0x64, 0x65)
                   else "op behind BUSLOCK" if code[k - 1] == 0xF0 else "op behind segment")
        if c == "pfx" and prev == "pfx":
            key = "pfx behind prefix"
        out[k] = key
        prev = c
    return out


def position_census(bench: str) -> dict:
    out = {}
    for v in kinds(bench).values():
        out[v] = out.get(v, 0) + 1
    return {k: out.get(k, 0) for k in KINDS}


def bench_image(bench: str, table: bytes | None, which=ENCODED):
    """The bench's image: table None the plain program, else its S regions (and the reset
    vector's far jump when it runs secure) with the position kinds in `which` through T^-1."""
    code, labels, classes, ivt = bench_program(bench)
    reset = RESET
    if table is not None:
        code = encode(code, kinds(bench), table, tuple(which))
        if MODES[bench]["reset"] == "S":
            reset = encode(RESET, RESET_KINDS, table, tuple(which))
    segments = {0x0000: ivt, 0x100: code, DATA: data_bytes(), 0xFFFF0: reset}
    pages = sorted({0, RES >> 12, DATA >> 12, (SP0 - 2) >> 12, 0xFF})
    return segments, pages, code


# ------------------------------------------------------------------ running and comparing
def run_bench(segments, pages, table: bytes | None, ns_low: bool, limit=2_000_000,
              plusargs=("+v35_chk",)):
    """One run on a fresh simulation lane (model lane only): its trace, results and chk."""
    import subprocess
    from nuboard.debug import DebugClient
    from .chains.acquire import SIM_CORES
    from .runner import REST_LEVELS, Harness, SimulationTransport
    transport = SimulationTransport.__new__(SimulationTransport)
    transport.process = subprocess.Popen([str(SIM_CORES["v35"][0]), *plusargs], cwd=ROOT,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
    try:
        harness = Harness(DebugClient(transport.exchange), strict=False)
        harness.configure(x_half=2, input_levels=REST_LEVELS & ~1 if ns_low else REST_LEVELS)
        if table is not None:
            harness.load_table(table)
        harness.load(segments, pages)
        result = harness.run_complete("model", limit)
        res = harness.read_memory("model", RES, 0x100)
        stack = harness.read_memory("model", SP0 - 0x40, 0x40)
    finally:
        transport.close()
    err = transport.process.stderr.read().decode(errors="replace")
    transport.process.stderr.close()
    chk = [ln for ln in err.splitlines() if "v35 chk" in ln]
    return {"passed": result["passed"], "status": result["status"],
            "timeout": result["timeout"], "trace": result["model_trace"],
            "results": res.hex(), "stack": stack.hex(), "chk": chk}


def compare(ref: dict, run: dict, code_len: int) -> dict:
    """The run against the reference: every bus cycle at the same clock (relative to the
    first), the same kind, address and data, except the code fetches' data (the encoded bytes)
    and a PSW image's MD bit on the stack (a push or its pop differing in bit 15 alone); refresh rows by time.
    And the results page byte for byte."""
    from .runner import FLAG_READ, FLAG_REFRESH, FLAG_STROBE
    a, b = ref["trace"], run["trace"]
    diffs, masked_md, fetch = [], 0, 0
    if len(a) != len(b):
        diffs.append(f"length {len(a)} / {len(b)}")
    t0a, t0b = (a[0]["start"] if a else 0), (b[0]["start"] if b else 0)
    for i, (x, y) in enumerate(zip(a, b)):
        if (x["start"] - t0a, x["end"] - x["start"], x["flags"], x["strobe"]) != \
                (y["start"] - t0b, y["end"] - y["start"], y["flags"], y["strobe"]):
            diffs.append(f"row {i}: timing/kind {x} / {y}")
            continue
        if x["flags"] & FLAG_REFRESH:
            continue
        if x["address"] != y["address"]:
            diffs.append(f"row {i}: address {x['address']:05X} / {y['address']:05X}")
            continue
        if x["data"] == y["data"]:
            continue
        read = x["flags"] & FLAG_READ and x["flags"] & FLAG_STROBE
        if read and (0x100 <= x["address"] < 0x100 + code_len + 8
                     or 0xFFFF0 <= x["address"]):
            fetch += 1
            continue
        if SP0 - 0x40 <= x["address"] < SP0 and x["data"] ^ y["data"] == 0x8000:
            masked_md += 1
            continue
        diffs.append(f"row {i}: data {x['address']:05X} {x['data']:04X} / {y['data']:04X}")
    if ref["results"] != run["results"]:
        ra, rb = bytes.fromhex(ref["results"]), bytes.fromhex(run["results"])
        diffs.append("results: " + " ".join(f"{RES + k:04X}:{ra[k]:02X}/{rb[k]:02X}"
                                            for k in range(len(ra)) if ra[k] != rb[k])[:400])
    return {"equal": not diffs, "rows": len(a), "fetch_rows_differing": fetch,
            "md_masked": masked_md, "diffs": diffs[:12]}


# ------------------------------------------------------------------ the benches
# (name, bench, table, N/S low, the kinds encoded (None: plain), the reference, the expectation)
# The plain program in normal mode (A_ref: no table, N/S high) is A's reference; B's is the plain
# program with the 1:1 table and N/S high (BRKS enters secure mode, the identity translation).
# Negative controls: the permutation image with one position kind treated the other way; each
# is predicted to DIFFER (registered here before the first run).
NEG = {
    "nc_op2": ENCODED | {"op2"},                        # the 0F second byte also encoded
    "nc_modrm": ENCODED | {"modrm"},                    # ModR/M bytes also encoded
    "nc_imm": ENCODED | {"imm"},                        # operands also encoded
    "nc_pfx": ENCODED - {"pfx", "pfx behind prefix"},   # prefixes left plain
    "nc_seg_op": ENCODED - {"op behind segment"},       # the byte behind a segment prefix plain
    "nc_rep_op": ENCODED - {"op behind REP"},           # the byte behind REP plain
    "nc_lock_op": ENCODED - {"op behind BUSLOCK"},      # the byte behind BUSLOCK plain
}


def benches():
    from_ = []
    from_.append(("A_ref", "A", None, False, None, None, "reference"))
    from_.append(("A_unloaded_normal", "A", None, False, None, "A_ref", "equal"))
    from_.append(("A_perm_normal_plain", "A", PERM, False, None, "A_ref", "equal"))
    from_.append(("A_identity_secure", "A", IDENTITY, True, None, "A_ref", "equal"))
    from_.append(("A_perm_secure", "A", PERM, True, ENCODED, "A_ref", "equal"))
    for name, which in NEG.items():
        from_.append((f"A_{name}", "A", PERM, True, which, "A_ref", "differ"))
    from_.append(("B_ref_identity", "B", IDENTITY, False, None, None, "reference"))
    from_.append(("B_perm", "B", PERM, False, ENCODED, "B_ref_identity", "equal"))
    from_.append(("B_nc_op2", "B", PERM, False, ENCODED | {"op2"}, "B_ref_identity", "differ"))
    return from_


def main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="the secure mode's benches (simulation only)")
    ap.add_argument("command", choices=("bench", "census"))
    ap.add_argument("--out", type=Path, default=ROOT / "build/validation/v35s/secure.json")
    args = ap.parse_args(argv)
    if args.command == "census":
        for b in "AB":
            print(b, position_census(b))
        return 0
    runs, report, ok = {}, [], True
    for name, bench, table, ns_low, which, ref, expect in benches():
        segments, pages, code = bench_image(bench, table if which is not None else None,
                                            which or ENCODED)
        run = run_bench(segments, pages, table, ns_low)
        runs[name] = (run, len(code))
        row = {"name": name, "bench": bench, "ns_low": ns_low,
               "table": None if table is None else "identity" if table == IDENTITY else "perm",
               "encoded": None if which is None else sorted(which), "expect": expect,
               "passed": run["passed"], "timeout": run["timeout"], "chk": run["chk"][:4],
               "rows": len(run["trace"])}
        if ref is not None:
            cmp_ = compare(runs[ref][0], run, len(code))
            row.update(cmp_)
            got = "equal" if cmp_["equal"] and run["passed"] else "differ"
        else:
            got = "reference" if run["passed"] else "FAILED"
        row["got"] = got
        good = got == expect and not run["chk"]
        ok &= good
        report.append(row)
        print(f"{name:22s} expect {expect:9s} got {got:9s} {'OK' if good else 'UNEXPECTED'}"
              f" rows {row['rows']} fetch-diff {row.get('fetch_rows_differing', '-')}"
              f" md-masked {row.get('md_masked', '-')} chk {len(run['chk'])}"
              + (f"  first: {row['diffs'][0][:120]}" if row.get("diffs") else ""), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"census": {b: position_census(b) for b in "AB"},
                                    "runs": report,
                                    "results": {n: r[0]["results"] for n, r in runs.items()}},
                                   indent=1) + "\n")
    print("secure benches:", "all as predicted" if ok else "NOT as predicted")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
