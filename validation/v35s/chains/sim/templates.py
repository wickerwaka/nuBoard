"""Instruction decoding (lengths and classes from the bytes) and per-class templates.

`decode(code, k, regs)` reads one instruction (a segment prefix is its own
1-byte pseudo-instruction of class "prefix") from the chain bytes and returns
an `Op`: length, class (forms.CLASSES plus "halt") and its memory/I/O
operands, with addresses computed from the tracked registers (DS0 = SS = 0,
so offsets are linear). `steps(op, cfg)` returns the class template: a fixed
ORDER of micro-steps whose clock counts are config integers. A class whose
forms come with and without operand bytes (reg, out, in) runs `pre0` instead of
`pre` before the (empty) take of an operand-less form: the template order with
and without the operand byte, not a per-opcode rule.

Steps (tuples): ("clocks", k); ("take", n) operand bytes after the opcode
(("take", n, "lead"): ModR/M bytes taken by the decoder alongside the EU's
first clocks, no EU clock and no take sync of their own; ("take", n, "chain"):
an operand take followed by more operand bytes, no take sync);
("data", kind, addr, width_bytes, setup) where kind is read / write /
io_read / io_write: post a bus request, wait for read data or for a write's
issue; ("post", kind, addr, width_bytes, setup): post the request and go on
(imm_order=after_post), ("issued",): wait until it is on the bus, ("wait",):
wait for it as a data step does; ("post_io", kind, port, width, setup): an
OUT's I/O posted and left to the bus unit (io_release=post); ("take", n,
"port", request, detached): a port byte, whose take posts the I/O request.

I/O forms with io_release=post (fifth fit): OUT = pre clocks, the port take
(which posts the I/O and, with port_sync=none, has no take sync), exec
clocks, end; a form without a port byte posts pre0 clocks after its start.
IN = the same post, then the EU waits for the data and runs post clocks.
With io_post=start the request's setup is counted from the start (setup +
pre, or + pre0).
"""

from __future__ import annotations

from dataclasses import dataclass

PREFIXES = {0x26, 0x2E, 0x36, 0x3E}
# rm -> (base registers, class without / with displacement)
RM = [(("BW", "IX"), "base_index"), (("BW", "IY"), "base_index"), (("BP", "IX"), "base_index"),
      (("BP", "IY"), "base_index"), (("IX",), "base"), (("IY",), "base"), (("BP",), "base"),
      (("BW",), "base")]
DISP_CLASS = {"base": "base_disp", "base_index": "base_index_disp"}
GROUP_OPCODES = frozenset([0x80, 0x81, 0x82, 0x83, 0x8F, 0xC0, 0xC1, 0xC6, 0xC7, 0xD0, 0xD1, 0xD2,
                           0xD3, 0xF6, 0xF7, 0xFE, 0xFF])


@dataclass
class Op:
    offset: int                  # chain offset of the opcode (or prefix)
    length: int
    cls: str
    opcode: int
    width: int = 2               # operand bytes (memory / I/O)
    ea: int | None = None        # memory operand address
    mode_class: str | None = None
    port: int | None = None
    count: int = 0               # shift count
    stack: tuple = ()            # (read addr, write addr) on the stack, None where unused
    imm_bytes: int = 0           # trailing immediate bytes (after any ModR/M and displacement)
    modrm: bool = False          # the first operand byte is a ModR/M byte
    group: bool = False          # the ModR/M reg field is the opcode extension (group opcode)
    shift: bool = False          # a memory operand's operation is a shift (D0-D3, C0/C1 on memory)
    nowrite: bool = False        # a group memory form that reads and does not write (81 /7)
    # (WP19) format properties of the ModR/M forms (F14 series T)
    dbit: int | None = None      # the direction bit (bit 1 of the 00-3F ALU and 88-8B MOV
                                 # ModR/M opcodes; 1: the reg field is the destination)
    fixed_alu: bool = False      # an ALU operation that no ALU-op field names (TEST 84/85:
                                 # neither the opcode's bits 5:3 nor a group reg field)
    swap: bool = False           # both operands are written (XCH 86/87 with a memory operand)
    signed: bool = False         # (WP21) F6/F7 /5 MUL, /7 DIV: the signed operation
    sfr: int | None = None       # (WP23) an on-chip SFR store (eu.py sets it: a DS1-prefixed
                                 # address in the SFR page): the RFM value it writes
    cl_count: bool = False       # (WP57) the count is CL (D2/D3): the EU masks it by shift_count_mask
    disp: int = 0                # (WP27) displacement bytes after the ModR/M byte (mod 01: 1,
                                 # mod 10 and the direct mod 00 rm 110: 2)
    bus: bool = True             # (WP52) the memory operand has a bus cycle (False: LDEA, the
                                 # EA computed and written to a register)
    target: int | None = None    # (WP55) a control transfer that is taken: the code offset the
                                 # EU goes on at (None: not taken, or no transfer)
    cond: bool = False           # (WP55) a transfer with a condition field (the 70-7F row's low
                                 # nibble names the flag test: BE, BNE), a format property
    # (WP67, F24) the string forms: rep is the repeat prefix byte (F3 REP / REPE, F2 REPNE) the
    # form carries, None without one; ix / iy the element addresses' starting offsets (the
    # source DS0:IX, the destination DS1:IY, linear: the model's segments are 0), port DW;
    # n the elements the form runs (from the registers: CW with a prefix, else 1; the EU
    # sets the chain walk's count, sim/machine.py) and cond whether a REP compare's repeat
    # ended on its condition at the last element (the walk's; False: CW ran out)
    rep: int | None = None
    ix: int = 0
    iy: int = 0
    n: int = 0
    cond: bool = False


def _modrm(code: bytes, k: int, regs: dict):
    """(mod, reg, rm, ea, mode_class, bytes after the opcode incl. displacement)."""
    m = code[k]
    mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
    if mod == 3:
        return mod, reg, rm, None, None, 1
    if mod == 0 and rm == 6:
        return mod, reg, rm, int.from_bytes(code[k + 1:k + 3], "little"), "direct", 3
    names, mc = RM[rm]
    disp = 0
    if mod == 1:
        disp = int.from_bytes(code[k + 1:k + 2], "little", signed=True)
        mc = DISP_CLASS[mc]
    elif mod == 2:
        disp = int.from_bytes(code[k + 1:k + 3], "little")
        mc = DISP_CLASS[mc]
    ea = (sum(regs[r] for r in names) + disp) & 0xFFFF
    return mod, reg, rm, ea, mc, 1 + mod if mod < 3 else 1


def decode(code: bytes, k: int, regs: dict) -> Op:
    op = code[k] if k < len(code) else 0x90
    if op in PREFIXES:
        return Op(k, 1, "prefix", op)
    if op & 0xFE in STRING_OPS or op in REP_PREFIXES:
        sop = _string_op(code, k, regs)        # (WP67, F24) the string forms
        if sop is not None:
            return sop
    if op in (0x90, 0x92):
        return Op(k, 1, "reg", op)
    if op == 0xF4:
        return Op(k, 1, "halt", op)
    if op == 0x50:
        return Op(k, 1, "push", op, stack=(None, (regs["SP"] - 2) & 0xFFFF))
    if op in (0x58, 0x59):                  # POP AW, POP CW (F15)
        return Op(k, 1, "pop", op, stack=(regs["SP"], None))
    if 0xB0 <= op <= 0xB7:
        return Op(k, 2, "imm", op, imm_bytes=1)
    if 0xB8 <= op <= 0xBF or op in (0x05, 0xA9):  # (WP20) A9: TEST AW,imm16
        return Op(k, 3, "imm", op, imm_bytes=2)
    if op == 0xA8:                          # (WP20) TEST AL,imm8
        return Op(k, 2, "imm", op, imm_bytes=1)
    if op in (0xA1, 0xA3):
        return Op(k, 3, "load" if op == 0xA1 else "store", op,
                  ea=int.from_bytes(code[k + 1:k + 3], "little"), mode_class="direct")
    if op in (0xE4, 0xE5, 0xE6, 0xE7):
        return Op(k, 2, "in" if op < 0xE6 else "out", op, width=1 + (op & 1), port=code[k + 1])
    if op in (0xEC, 0xED, 0xEE, 0xEF):
        return Op(k, 1, "in" if op < 0xEE else "out", op, width=1 + (op & 1), port=regs["DW"])
    sp = regs["SP"]
    if op in (0x74, 0x75, 0xEB, 0xE2):
        # (WP55, F23) the short transfers, a 1-byte displacement from the next instruction:
        # BE (taken with Z), BNE (without Z), BR short (always) and DBNZ (CW counted down,
        # taken while it is not 0); the decision is the semantics' (execute sets Z and CW)
        disp = int.from_bytes(code[k + 1:k + 2], "little", signed=True)
        if op == 0xE2:
            taken = (regs["CW"] - 1) & 0xFFFF != 0
        elif op == 0xEB:
            taken = True
        else:
            if regs.get("Z") is None:
                raise ValueError(f"opcode {op:02X} at chain offset {k}: the flags are not known")
            taken = bool(regs["Z"]) == (op == 0x74)
        return Op(k, 2, "dbnz" if op == 0xE2 else "branch_short", op,
                  target=k + 2 + disp if taken else None, cond=0x70 <= op <= 0x7F)
    if op in (0xE9, 0xE8):
        # (WP55, F23) BR near / CALL near: a 2-byte displacement; CALL writes the return
        # address (the next instruction's) below SP
        disp = int.from_bytes(code[k + 1:k + 3], "little", signed=True)
        if op == 0xE9:
            return Op(k, 3, "branch_near", op, target=k + 3 + disp)
        return Op(k, 3, "call", op, target=k + 3 + disp, stack=(None, (sp - 2) & 0xFFFF))
    if op == 0xC3:
        # (WP55, F23) RET: the return address read at SP (the CALL that wrote it, execute)
        ret = regs.get(f"ret{sp:04X}")
        if ret is None:
            raise ValueError(f"RET at chain offset {k}: no return address at {sp:04X}")
        return Op(k, 1, "ret", op, target=ret, stack=(sp, None))
    if op in (0x68, 0x6A):                  # (WP52) PUSH imm16 / PUSH imm8 (sign-extended)
        n = 2 if op == 0x68 else 1
        return Op(k, 1 + n, "push_imm", op, imm_bytes=n, stack=(None, (sp - 2) & 0xFFFF))
    if op == 0x60:                          # (WP52) PUSH R: eight words from SP - 2 down
        return Op(k, 1, "push_r", op, stack=(None, (sp - 2) & 0xFFFF))
    if op == 0x61:                          # (WP52) POP R: eight words from SP up
        return Op(k, 1, "pop_r", op, stack=(sp, None))
    if op == 0xC8:                          # (WP52) PREPARE imm16,imm8: BP pushed (level 0)
        if code[k + 3] != 0:
            raise ValueError(f"PREPARE level {code[k + 3]} at chain offset {k} is not modelled")
        return Op(k, 4, "prepare", op, imm_bytes=3, stack=(None, (sp - 2) & 0xFFFF))
    if op == 0xC9:                          # (WP52) DISPOSE: SP := BP, BP popped
        return Op(k, 1, "dispose", op, stack=(regs["BP"], None))
    if op in (0x06, 0x0E, 0x16, 0x1E):      # (WP52) PUSH DS1 / PS / SS / DS0
        return Op(k, 1, "push_seg", op, stack=(None, (sp - 2) & 0xFFFF))
    if op in (0x07, 0x17, 0x1F):            # (WP52) POP DS1 / SS / DS0
        return Op(k, 1, "pop_seg", op, stack=(sp, None))
    if op == 0xD7:                          # (WP52) XLAT: the byte at BW + AL, no ModR/M
        return Op(k, 1, "xlat", op, width=1,
                  ea=(regs["BW"] + (regs["AW"] & 0xFF)) & 0xFFFF)
    mod, reg, rm, ea, mc, n = _modrm(code, k + 1, regs)
    mem = mod != 3
    # the w bit (bit 0) of the ALU, TEST, XCH and MOV ModR/M opcodes: 0 = byte operand
    width = 1 if (op < 0x40 or 0x84 <= op <= 0x8B) and not op & 1 else 2
    if op in (0xD0, 0xF6):              # (WP21) the byte groups' w bit
        width = 1
    # A group opcode: the operation is selected by the ModR/M reg field (a format
    # property of the encoding: 80-83, 8F, C0/C1, C6/C7, D0-D3, F6/F7, FE/FF).
    group = op in GROUP_OPCODES
    base = dict(offset=k, opcode=op, width=width, ea=ea, mode_class=mc, modrm=True, group=group,
                disp=n - 1 if mem else 0)
    if (op < 0x40 and not op & 4) or 0x88 <= op <= 0x8B:
        base["dbit"] = (op >> 1) & 1
    base["fixed_alu"] = op in (0x84, 0x85)
    base["swap"] = mem and op in (0x86, 0x87)
    length = 1 + n
    if op < 0x40 and op & 7 < 4:
        # the ALU ModR/M forms of the 00-3F block (operation in bits 5:3): a memory
        # destination (d = 0) is a read-modify-write, except CMP (bits 5:3 = 7), which
        # reads only; a register destination (d = 1) is a load + ALU
        cls = "reg" if not mem else (
            "rmw" if not op & 2 and (op >> 3) & 7 != 7 else "load_alu")
    elif op in (0x8B, 0x8A, 0x85, 0x89, 0x88, 0x87, 0x84, 0x86):
        cls = "reg" if not mem else {0x8B: "load", 0x8A: "load", 0x89: "store", 0x88: "store",
                                     0x87: "rmw", 0x86: "rmw"}.get(op, "load_alu")
    elif op in (0x81, 0x83):
        # (WP20) 83: the immediate is one byte, sign-extended
        nimm = 2 if op == 0x81 else 1
        length += nimm
        base["imm_bytes"] = nimm
        cls = "imm" if not mem else ("load_alu" if reg == 7 else "rmw_imm")
        base["nowrite"] = mem and reg == 7
    elif op == 0xC7:
        length += 2
        base["imm_bytes"] = 2
        cls = "store_imm"
    elif op == 0xC6:                    # (WP23) MOV r/m8,imm8: the byte store immediate (F17's
        length += 1                     # RFM write)
        base["imm_bytes"] = 1
        base["width"] = 1
        cls = "store_imm"
    elif op == 0xC1:
        length += 1
        return Op(length=length, cls="shift_imm", count=code[k + length - 1], imm_bytes=1,
                  **base)
    elif op in (0xD0, 0xD1):            # (WP21) D0: the byte form
        if not mem:
            return Op(length=length, cls="shift_imm", count=1, **base)
        cls = "rmw"
        base["count"] = 1
        base["shift"] = True
    elif op == 0xD3:
        if not mem:
            return Op(length=length, cls="shift_cl", count=regs["CW"] & 0xFF, cl_count=True, **base)
        cls = "rmw"                         # (WP19) SHL [BW],CL: a shift by CL on memory
        base["count"] = regs["CW"] & 0xFF   # (WP57) the full byte; the EU masks it by shift_count_mask
        base["cl_count"] = True
        base["shift"] = True
    elif op in (0xF6, 0xF7):            # (WP21) F6: the byte form (F16 uses /4 only)
        if reg == 0 and op == 0xF6:
            raise ValueError(f"opcode F6 /0 at chain offset {k} is not in the catalog")
        if reg == 0:                        # (WP19) TEST r/m16,imm16: reads, no write
            length += 2
            base["imm_bytes"] = 2
            base["fixed_alu"] = True        # AND, which its reg field (000) does not name
            cls = "load_alu" if mem else "imm"
            base["nowrite"] = mem
        else:
            cls = "mul" if reg in (4, 5) else "div" if reg in (6, 7) else "rmw"
            base["signed"] = reg in (5, 7)
    elif op == 0xFF:
        cls = "push_mem" if reg == 6 else "rmw"
        if reg == 6:
            base["stack"] = (None, (regs["SP"] - 2) & 0xFFFF)
    elif op == 0x8F:
        cls = "pop_mem"
        base["stack"] = (regs["SP"], None)
    elif op == 0x8E and not mem:
        cls = "reg"                     # (WP24) MOV sreg,r16: the prelude's segment loads
    elif op == 0x8E:
        cls = "load_seg"                # (WP52) MOV sreg,r/m16: a load into a segment register
    elif op == 0x8C:
        cls = "store" if mem else "reg"     # (WP52) MOV r/m16,sreg
    elif op == 0x8D:
        if not mem:
            raise ValueError(f"LDEA with a register operand at chain offset {k}")
        cls = "lea"                     # (WP52) LDEA r16,m: the EA, no bus cycle, to the reg
        base["bus"] = False
    else:
        raise ValueError(f"opcode {op:02X} at chain offset {k} is not in the catalog")
    return Op(length=length, cls=cls, **base)


# (WP67, F24) the string forms by their even opcode (bit 0: the word form): the class, and one
# element's bus cycles in order, (kind, operand) with operand ix (the source, DS0:IX), iy (the
# destination, DS1:IY) or port (DW). CMPBK reads the destination first (F24 silicon). A REP
# prefix (F3, F2) before one of them is part of the form (one instruction of two bytes), not a
# pseudo-instruction as a segment prefix is.
STRING_OPS = {0xA4: "str_move", 0xA6: "str_cmp", 0xAA: "str_store", 0xAC: "str_load",
              0xAE: "str_scan", 0x6C: "str_in", 0x6E: "str_out"}
STRING_STEPS = {"str_move": (("read", "ix"), ("write", "iy")),
                "str_cmp": (("read", "iy"), ("read", "ix")),
                "str_store": (("write", "iy"),),
                "str_load": (("read", "ix"),),
                "str_scan": (("read", "iy"),),
                "str_in": (("io_read", "port"), ("write", "iy")),
                "str_out": (("read", "ix"), ("io_write", "port"))}
STRING_CLASSES = tuple(STRING_STEPS)
STRING_COMPARES = ("str_cmp", "str_scan")     # REPE / REPNE: the repeat tests the result
REP_PREFIXES = (0xF2, 0xF3)


def _string_op(code: bytes, k: int, regs: dict):
    """(WP67, F24) the string form at k (with its REP prefix), or None."""
    op = code[k] if k < len(code) else 0x90
    rep = None
    if op in REP_PREFIXES and k + 1 < len(code) and code[k + 1] & 0xFE in STRING_OPS:
        rep, op = op, code[k + 1]
    cls = STRING_OPS.get(op & 0xFE)
    if cls is None:
        return None
    port = regs["DW"] if cls in ("str_in", "str_out") else None
    return Op(k, 2 if rep is not None else 1, cls, op, width=1 + (op & 1), port=port,
              rep=rep, ix=regs["IX"], iy=regs["IY"],
              n=regs["CW"] if rep is not None else 1)


REG16 = ("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY")
REG8 = (("AW", 0), ("CW", 0), ("DW", 0), ("BW", 0), ("AW", 8), ("CW", 8), ("DW", 8), ("BW", 8))
FILL_WORD = 0x9090           # every data word reads the 0x90 fill (types.DATA_FILL)


def _set8(regs: dict, k: int, value: int):
    name, shift = REG8[k]
    regs[name] = (regs[name] & ~(0xFF << shift) & 0xFFFF) | ((value & 0xFF) << shift)


def written(op: Op, code: bytes) -> tuple:
    """The general registers op writes (16-bit names; a byte register counts as its word).
    A format property: the destination of the encoding (B0-BF, 91-97, a ModR/M form's reg
    field for 8B/8A/03/3B... with a register destination, its rm field for a register
    operand of a group form), not a per-opcode timing rule."""
    o = op.opcode
    if op.cls == "prefix" or o in (0x90, 0xF4) or op.cls in ("out", "push", "store",
                                                              "store_imm", "push_mem"):
        return ()
    if 0xB0 <= o <= 0xB7:
        return (REG8[o - 0xB0][0],)
    if 0xB8 <= o <= 0xBF:
        return (REG16[o - 0xB8],)
    if 0x91 <= o <= 0x97:
        return ("AW", REG16[o - 0x90])
    if o in (0x05, 0xA1) or op.cls == "in":
        return ("AW",)
    if op.cls == "pop":
        return (REG16[o - 0x58],)
    if not op.modrm:
        return ()
    m = code[op.offset + 1]
    mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
    if o in (0x8B, 0x8A) or (o < 0x40 and o & 7 < 4 and o & 2 and (o >> 3) & 7 != 7):
        return (REG16[reg] if o & 1 else REG8[reg][0],)
    if o == 0x87:
        return (REG16[reg],) + ((REG16[rm],) if mod == 3 else ())
    if o in (0x3B, 0x85, 0x39, 0x38, 0x84, 0x3A, 0xA8, 0xA9):
        return ()                           # CMP / TEST: flags only
    if o < 0x40 and o & 7 < 4:              # d = 0: the rm operand (memory: none)
        return (REG16[rm],) if mod == 3 else ()
    if o == 0x86:
        return (REG8[reg][0],)
    if o == 0xF7 and reg in (4, 5, 6, 7):
        return ("AW", "DW")                 # MULU / DIVU: DW:AW
    if mod == 3 and o in (0x81, 0x83, 0xD1, 0xD3, 0xC1) and not (o in (0x81, 0x83)
                                                                  and reg == 7):
        return (REG16[rm],)
    return ()


def execute(op: Op, code: bytes, regs: dict):
    """Register side effects the timing depends on: CL (shift count), DW (port), SP, and
    the values that reach them (AW, the other word registers); memory reads return the
    data fill."""
    o, k = op.opcode, op.offset
    imm16 = lambda at: int.from_bytes(code[at:at + 2], "little")
    if 0xB0 <= o <= 0xB7:
        _set8(regs, o - 0xB0, code[k + 1])
    elif 0xB8 <= o <= 0xBF:
        regs[REG16[o - 0xB8]] = imm16(k + 1)
    elif 0x91 <= o <= 0x97:
        r = REG16[o - 0x90]
        regs["AW"], regs[r] = regs[r], regs["AW"]
    elif o == 0x05:
        regs["AW"] = (regs["AW"] + imm16(k + 1)) & 0xFFFF
    elif o == 0xA1:
        regs["AW"] = FILL_WORD
    elif op.modrm and op.cls not in ("prefix",):
        m = code[k + 1]
        mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
        src = regs[REG16[rm]] if mod == 3 else FILL_WORD
        if o == 0x8B:
            regs[REG16[reg]] = src
        elif o == 0x03:
            regs[REG16[reg]] = (regs[REG16[reg]] + src) & 0xFFFF
        elif o in (0x23, 0x33):               # (WP20) AND / XOR AW,[BW]
            v = regs[REG16[reg]]
            regs[REG16[reg]] = (v & src) if o == 0x23 else (v ^ src)
        elif o == 0x87 and mod == 3:
            regs[REG16[reg]], regs[REG16[rm]] = regs[REG16[rm]], regs[REG16[reg]]
        elif o == 0x87:
            regs[REG16[reg]] = FILL_WORD
        elif o == 0x81 and mod == 3 and reg == 0:
            regs[REG16[rm]] = (regs[REG16[rm]] + imm16(k + 2)) & 0xFFFF
        elif o in (0xD1, 0xD3, 0xC1) and mod == 3 and reg == 4:
            n = 1 if o == 0xD1 else (regs["CW"] & 0xFF if o == 0xD3 else code[k + 2])   # (WP57) silicon: the full count
            regs[REG16[rm]] = (regs[REG16[rm]] << n) & 0xFFFF
        elif o == 0xF7 and reg == 4:
            p = regs["AW"] * src
            regs["AW"], regs["DW"] = p & 0xFFFF, (p >> 16) & 0xFFFF
        elif o == 0xF7 and reg == 6 and src:
            q, r = divmod((regs["DW"] << 16) | regs["AW"], src)
            regs["AW"], regs["DW"] = q & 0xFFFF, r & 0xFFFF
        elif o == 0x86:
            _set8(regs, reg, FILL_WORD & 0xFF if mod != 3 else 0)
        elif o == 0x8D:
            regs[REG16[reg]] = op.ea            # (WP52) LDEA: the offset itself
        elif o in (0x3B, 0x39) and mod == 3:
            regs["Z"] = int(regs[REG16[reg]] == regs[REG16[rm]])   # (WP55) CMP r16,r16: Z
    if o == 0xD7:
        _set8(regs, 0, FILL_WORD & 0xFF)        # (WP52) XLAT: AL from the data fill
    if op.cls in ("push", "push_mem", "push_imm", "push_seg", "prepare"):
        regs["SP"] = (regs["SP"] - 2) & 0xFFFF
    if op.cls == "prepare":
        # (WP52) PREPARE imm16,0: BP := SP after BP's push, then SP -= imm16
        regs["BP"] = regs["SP"]
        regs["SP"] = (regs["SP"] - imm16(k + 1)) & 0xFFFF
    if op.cls in ("pop", "pop_mem", "pop_seg"):
        regs["SP"] = (regs["SP"] + 2) & 0xFFFF
    if op.cls == "push_r":
        regs["SP"] = (regs["SP"] - 16) & 0xFFFF     # (WP52) eight words
    if op.cls == "pop_r":
        # (WP52) eight words; the registers keep their values (as POP AW's: a stack read
        # after the matching push returns what it pushed; SP's slot is discarded)
        regs["SP"] = (regs["SP"] + 16) & 0xFFFF
    if op.cls == "dispose":
        # (WP52) SP := BP, then BP popped (the data fill, as every other memory read)
        regs["SP"] = (regs["BP"] + 2) & 0xFFFF
        regs["BP"] = FILL_WORD
    if op.cls == "dbnz":
        regs["CW"] = (regs["CW"] - 1) & 0xFFFF      # (WP55) DBNZ
    if op.cls == "call":
        # (WP55) CALL: the return address (its code offset; the trace's data word is not
        # compared) at SP - 2, read back by the RET that pops it
        regs["SP"] = (regs["SP"] - 2) & 0xFFFF
        regs[f"ret{regs['SP']:04X}"] = k + op.length
    if op.cls == "ret":
        regs["SP"] = (regs["SP"] + 2) & 0xFFFF      # (WP55) RET
    if op.cls in STRING_CLASSES:
        # (WP67, F24) IX / IY stepped upward (DIR clear) by the elements run, CW counted down
        used = {place for _, place in STRING_STEPS[op.cls]}
        step = op.n * op.width
        if "ix" in used:
            regs["IX"] = (regs["IX"] + step) & 0xFFFF
        if "iy" in used:
            regs["IY"] = (regs["IY"] + step) & 0xFFFF
        if op.rep is not None:
            regs["CW"] = (regs["CW"] - op.n) & 0xFFFF


def io_ports(code: bytes, regs: dict, start: int = 0) -> dict:
    """{chain offset: port} of every IN/OUT in code from `start`, walking it with decode /
    execute from the register presets (the DW forms address the DW they find)."""
    regs = dict(regs)
    out, k = {}, start
    while k < len(code):
        op = decode(code, k, regs)
        if op.cls in ("in", "out"):
            out[k] = op.port
        if op.cls == "halt":
            break
        execute(op, code, regs)
        k = op.target if op.target is not None else k + op.length   # (WP55) taken transfers
    return out


def _head(op: Op, cfg, pre: int, ea=None) -> list[tuple]:
    """Pre clocks, operand takes and EA clocks of a memory form (mem_order, config.py).

    pre_take: the pre clocks, every operand byte in one take step, the EA clocks.
    lead: a ModR/M byte is taken by the decoder at the start (as for the imm
    class), alongside the pre clocks; the remaining operand bytes (displacement,
    immediate) follow them, then the EA clocks.
    lead_ea: as lead, with the EA clocks before the remaining operand bytes.
    A form without a ModR/M byte (A1/A3 direct) has no lead take: pre, then its
    address bytes, then the EA clocks (a format property, like pre0).
    split: pre clocks, the ModR/M byte as an operand take of its own, the EA
    clocks, then the remaining operand bytes (displacement, immediate). The take
    sync follows the last operand take only: a ModR/M byte followed by more
    operand bytes is a chained take (("take", 1, "chain"): the next step starts
    on the next clock with no sync). A form without a ModR/M byte (A1/A3) runs
    pre0 clocks (the class's pre when it has none) and then its address bytes:
    a format property, like the operand-less pre0 of reg/out/in.
    ea=None: the template places the EA clocks itself (pop_mem).
    With imm_order other than with_addr the immediate bytes are not part of the
    head (the template takes them itself).
    """
    rest = op.length - 1 - (op.imm_bytes if cfg.imm_order != "with_addr" else 0)
    tail = [ea] if ea is not None else []
    if cfg.mem_order == "split" and op.ea is not None:
        if not op.modrm:
            # no ModR/M byte (A1/A3): pre0 clocks, then the address bytes
            pre0 = cfg.c(op.cls, "pre0") if "pre0" in cfg.cost.get(op.cls, {}) else pre
            return [("clocks", pre0), ("take", rest)] + tail
        more = rest - 1
        # the ModR/M take is chained (no take sync) when operand bytes follow it
        modrm = ("take", 1, "chain") if more else ("take", 1)
        disp = ("take", more)
        if cfg.disp16 == "word" and op.disp == 2 and more == 2:
            disp = ("take", 2, "word")      # (WP27) the two displacement bytes on one clock
        dadd = cfg.c(op.cls, "dadd") if op.disp and more == op.disp else 0
        if dadd and not (more and op.imm_bytes and cfg.imm_head == "disp_ea"):
            # (WP27) the class's dadd EU clocks after a displacement's take (its add)
            return [("clocks", pre), modrm] + tail + [disp, ("clocks", dadd)]
        if more and op.imm_bytes and cfg.imm_head == "disp_ea":
            # a form with an immediate: its displacement before the EA clocks
            return [("clocks", pre), modrm, disp] + tail
        return [("clocks", pre), modrm] + tail + [disp]
    if cfg.mem_order in ("lead", "lead_ea") and op.modrm and op.ea is not None:
        if cfg.mem_order == "lead_ea":
            return [("take", 1, "lead"), ("clocks", pre)] + tail + [("take", rest - 1)]
        return [("take", 1, "lead"), ("clocks", pre), ("take", rest - 1)] + tail
    return [("clocks", pre), ("take", rest)] + tail


def _imm_read(op: Op, cfg, c) -> list[tuple]:
    """The read and the immediate take of a memory form with an immediate (imm_order):
    after_post: the read is posted (issuable after the class's rsetup clocks), the
    immediate is taken while it waits (a chained take: the EU waits on its own
    request, not on the take sync), then the EU waits for the read data;
    after_issue: as after_post, the immediate taken once the read is on the bus;
    after_data: the read, then the immediate."""
    if cfg.imm_order == "after_post":
        return [("post", "read", op.ea, op.width, c("rsetup")), ("take", op.imm_bytes, "chain"),
                ("wait",), ("clocks", cfg.read_use_latency)]
    if cfg.imm_order == "after_issue":
        return [("post", "read", op.ea, op.width, c("rsetup")), ("issued",),
                ("take", op.imm_bytes, "chain"), ("wait",), ("clocks", cfg.read_use_latency)]
    return [("data", "read", op.ea, op.width, c("rsetup")), ("clocks", cfg.read_use_latency),
            ("take", op.imm_bytes)]


def _ea_setup(seq: list[tuple], cfg) -> list[tuple]:
    """ea_post=setup: EA clocks directly before a data step become that request's
    setup clocks (the request is posted when the EA starts, so it holds fetches
    under hold_fetch while the address is formed)."""
    if cfg.ea_post != "setup":
        return seq
    out = []
    for k, step in enumerate(seq):
        nxt = next((s for s in seq[k + 1:] if not (s[0] == "take" and s[1] == 0)), None)
        if (step[0] == "clocks" and step[1] and len(step) > 2 and step[2] == "ea"
                and nxt is not None and nxt[0] == "data"):
            j = seq.index(nxt, k + 1)
            seq[j] = nxt[:4] + (nxt[4] + step[1],)
            continue
        out.append(step)
    return out


def _group(seq: list[tuple], op: Op, cfg) -> list[tuple]:
    """A memory form of a group opcode runs the class's grp clocks right before its
    first data request (post or data step): as EU clocks (grp_mode=clocks), or as
    extra setup clocks of that request, the last grp_free of which (default all)
    must be fetch-free (grp_mode=setup; a sixth step element overrides the class's
    setup_free for that request)."""
    # (WP19) grp_ops: the forms that take the group setup besides the group opcodes
    fixed = cfg.grp_ops == "fixed" and op.fixed_alu
    gcls = op.cls
    n = cfg.c(gcls, "grp")
    if cfg.imm8_grp == "own" and op.imm_bytes == 1 and op.group:
        n = cfg.c(gcls, "grp1")         # (WP20) a one-byte immediate (83 /x): its own setup
    cl = 0
    if cfg.shift_cl_mem == "count" and op.shift and op.opcode in (0xD2, 0xD3):
        # (WP19) a memory shift whose count is in CL (D2/D3, opcode bit 1): grpcl more
        # clocks before its read, and the whole group setup fetch-free
        cl = cfg.c(gcls, "grpcl")
        n += cl
    grp = op.group or fixed or (
        cfg.grp_ops == "nodir" and op.dbit is None and 0x84 <= op.opcode <= 0x87)
    if not (grp and op.ea is not None and n):
        return seq
    k = next((i for i, s in enumerate(seq) if s[0] in ("data", "post")), None)
    if op.cls == "pop_mem" and cfg.pop_mem_order != "modrm_first":
        # (WP20) the stack read needs nothing from the ModR/M byte: the group setup goes
        # on the memory write, the request posted after the reg field is decoded
        k = max((i for i, s in enumerate(seq) if s[0] in ("data", "post")), default=None)
    if k is None:
        return seq
    looked = False
    if (cfg.fixed_lookup in ("decoder", "decoder_nowait") and fixed
            and (not op.group or cfg.fixed_lookup_grp == "group")
            and any(s[0] == "take" and len(s) > 2 and s[2] == "chain" for s in seq[:k])):
        # (WP20) TEST 84/85 with a displacement: the fixed operation's lookup holds the
        # decoder between the ModR/M byte and the displacement bytes (fdisp EU clocks);
        # (WP43) fixed_lookup_grp=group: so does the group form TEST r/m,imm16 (F7 /0)
        j = next(i for i, s in enumerate(seq) if s[0] == "take" and len(s) > 2
                 and s[2] == "chain")
        fd = cfg.c("load_alu", "fdisp")
        # decoder_nowait: the lookup's clocks do not count while a memory cycle waits
        step = ("nowait", fd) if cfg.fixed_lookup == "decoder_nowait" else ("clocks", fd)
        seq = seq[:j + 1] + [step] + seq[j + 1:]
        k += 1
        n = max(n - fd, 0)              # the lookup clocks are part of the group setup
        looked = True
    if cfg.grp_mode == "setup":
        # setup clocks of the request that must be fetch-free (as PUSH/OUT setup_free)
        st = seq[k]
        free = (n if cl else cfg.c(gcls, "grp_free")) if "grp_free" in cfg.cost.get(gcls, {}) else n
        free = min(free, n)
        if cfg.grp_fixed == "test" and op.group and op.fixed_alu and cfg.grp_ops == "fixed":
            # (WP20) as TEST 84/85 (load_alu grp/grp_free) and fgrp more clocks: the group
            # decode after the fixed operation's lookup
            n = cfg.c("load_alu", "grp") + cfg.c("load_alu", "fgrp")
            free = cfg.c("load_alu", "grp_free") + cfg.c("load_alu", "fgrp_free")
            if looked:
                # (WP43) fixed_lookup_grp=group: the lookup ran in the decoder; the read
                # keeps only its group's decode, the group's own setup (rmw_imm grp/grp_free)
                n = cfg.c(gcls, "grp")
                free = min(cfg.c(gcls, "grp_free"), n)
        if cfg.grp_fixed == "both" and op.group and op.fixed_alu and cfg.grp_ops == "fixed":
            # (WP20) a group form whose operation no ALU-op field names (F6/F7 /0, TEST):
            # the group's setup and then the fixed operation's lookup, TEST 84/85's
            n += cfg.c("load_alu", "fgrp")
            free += cfg.c("load_alu", "fgrp_free")
        # the seventh element marks the free clocks as the grp's (grp_free_bus, arbiter.py)
        return seq[:k] + [st[:4] + (st[4] + n, free, True)] + seq[k + 1:]
    return seq[:k] + [("clocks", n)] + seq[k:]


def refresh_hold_steps(op: Op, cfg, seq: list[tuple]) -> list[tuple]:
    """(WP17) refresh_eu=hold, for a chain with refresh on (eu.py): the template with the
    EU's micro-boundary structure marked. A shift's count loop is tagged "loop" (its
    iterations are boundaries), its exec clocks before it "exec" (refresh_exec), and
    the last shift_tail of those exec clocks run after the loop as its exit ("tail",
    the split F13 series S shows); a register MULU's exec clocks are a count loop too
    (refresh_mul=loop). The clock totals are unchanged."""
    if op.cls in ("shift_cl", "shift_imm") and len(seq) >= 2 and seq[-1][0] == seq[-2][0] == "clocks":
        ex, loop = seq[-2][1], seq[-1][1]
        if loop:
            tail = min(cfg.shift_tail, ex)
            if (cfg.shift_exit0 == "exit" and op.cls == "shift_imm" and not op.imm_bytes
                    and "exec0" in cfg.cost.get("shift_imm", {})):
                # (WP36) shift_exit0: the exec0 form (no count byte) runs the count-byte form's
                # exec head; the clock it lacks is its exit's
                head = max(0, min(cfg.c("shift_imm", "exec") - cfg.shift_tail, ex))
                tail = ex - head
            return seq[:-2] + [("clocks", ex - tail, "exec"), ("clocks", loop, "loop"),
                               ("clocks", tail, "tail")]
        return seq
    if (op.cls in (("mul", "div") if cfg.refresh_unit != "mul" else ("mul",)) and op.ea is None
            and cfg.refresh_mul in ("loop", "loop_odd") and seq and seq[-1][0] == "clocks"):
        n = seq[-1][1]
        T = cfg.c(op.cls, "rexit")
        if cfg.refresh_mul_exit == "exit" and cfg.refresh_mul == "loop_odd" and 0 < T < n:
            # (WP36) refresh_mul_exit: the class's last rexit exec clocks run as the loop's exit
            return seq[:-1] + [("clocks", n - T, "loop_odd"),
                               ("clocks", T, "mexit")]
        return seq[:-1] + [("clocks", n, "loop" if cfg.refresh_mul == "loop"
                            else "loop_odd")]
    return seq


def _dest_route(op: Op, cfg) -> int:
    """(WP19) dest_route: the class's dclk clocks a form spends routing its result to an
    operand its direction bit does not name, after the read (a read-only form) or before
    the write (a read-modify-write), else 0 (config.py)."""
    if cfg.dest_route == "none" or op.ea is None:
        return 0
    writes = op.cls in ("rmw", "rmw_imm") and not op.nowrite
    if cfg.dest_route == "slot":
        hit = op.swap                    # the d = 0 read-only form runs the slot (eu.py)
    elif cfg.dest_route in ("d0ro_swap", "d0ro_latch"):
        hit = (op.dbit == 0 and not writes) or op.swap
    else:   # mismatch: bit 1 of the 00-3F / 84-8B ModR/M opcodes against the memory write
        bit = (op.opcode >> 1) & 1 if (op.opcode < 0x40 and not op.opcode & 4) or (
            0x84 <= op.opcode <= 0x8B) else None
        hit = bit is not None and (bit == 0) != writes
    return cfg.c(op.cls, "dclk") if hit else 0


def ea_class(op: Op, cfg) -> str:
    """(WP27) the EA table entry a memory form runs: its mode class, except base+index with a
    two-byte displacement under ea_disp16=own (base_index_disp16) and a ModR/M direct
    address under ea_direct=base_disp (base_disp)."""
    if cfg.ea_disp16 == "own" and op.mode_class == "base_index_disp" and op.disp == 2:
        return "base_index_disp16"
    if cfg.ea_direct == "base_disp" and op.mode_class == "direct" and op.modrm:
        return "base_disp"
    return op.mode_class


def grp_class(op: Op, cfg) -> str:
    """The cost class op runs under: grp_read other than own runs a non-writing group
    memory form (81 /7) under its group's read-modify-write class."""
    if op.nowrite and cfg.grp_read != "own":
        return "rmw_imm" if op.imm_bytes else "rmw"
    return op.cls


def steps(op: Op, cfg) -> list[tuple]:
    """The class template of op. Order is structural; integers come from cfg."""
    return _ea_setup(_group(_steps(op, cfg), op, cfg), cfg)


def _steps(op: Op, cfg) -> list[tuple]:
    c = lambda name: cfg.c(op.cls, name)
    rest = op.length - 1
    ea = ("clocks", cfg.ea.get(ea_class(op, cfg), 0) if op.ea is not None else 0, "ea")
    cls = op.cls
    if cls in ("reg", "prefix"):
        # a form without operand bytes runs pre0 clocks where an operand form runs pre
        pre = c("pre") if rest else c("pre0") if "pre0" in cfg.cost.get(cls, {}) else c("pre")
        return [("clocks", pre), ("take", rest), ("clocks", c("exec"))]
    if cls == "halt":
        return [("halt",)]
    if cls == "imm":
        # ModR/M forms take the ModR/M byte at once; the immediate follows the pre clocks
        lead = rest - op.imm_bytes
        head = [("take", lead, "lead")] if lead else []
        return head + [("clocks", c("pre")), ("take", op.imm_bytes), ("clocks", c("exec"))]
    if cls == "shift_imm":
        # (WP16) a form without a count byte (D1: count 1) runs exec0 where the count-byte
        # form (C1) runs exec, as pre0 for the operand-less forms (a format property)
        ex = c("exec0") if not op.imm_bytes and "exec0" in cfg.cost.get(cls, {}) else c("exec")
        if op.imm_bytes and cfg.shift_count == "late":
            # (WP16) the count byte is taken cpre clocks after the ModR/M byte
            return [("clocks", c("pre")), ("take", rest - op.imm_bytes, "chain"),
                    ("clocks", c("cpre")), ("take", op.imm_bytes), ("clocks", ex),
                    ("clocks", cfg.per_shift_count * op.count)]
        return [("clocks", c("pre")), ("take", rest), ("clocks", ex),
                ("clocks", cfg.per_shift_count * op.count)]
    if cls == "shift_cl":
        # the count is data (CL): a zero count skips the shift loop's loop clocks
        loop = c("loop") if op.count else 0
        return [("clocks", c("pre")), ("take", rest), ("clocks", c("exec") + loop),
                ("clocks", cfg.per_shift_count * op.count)]
    if cls in ("mul", "div"):
        if op.ea is None:
            return [("clocks", c("pre")), ("take", rest), ("clocks", c("exec"))]
        # (WP19) a memory operand form may have its own mexec (a format property, as exec0)
        mex = c("mexec") if "mexec" in cfg.cost.get(cls, {}) else c("exec")
        if op.signed and "smexec" in cfg.cost.get(cls, {}):
            mex = c("smexec")           # (WP21) the signed operation (F7 /5, /7): its own
        elif op.width == 1 and "bmexec" in cfg.cost.get(cls, {}):
            mex = c("bmexec")           # (WP21) the byte operation (F6): its own
        return _head(op, cfg, c("pre"), ea) + [("data", "read", op.ea, op.width, 0),
                                                ("clocks", mex, "mexec")]
    if cls in ("load", "load_alu") and op.imm_bytes and cfg.imm_order != "with_addr":
        return _head(op, cfg, c("pre"), ea) + _imm_read(op, cfg, c) + [("clocks", c("exec"))]
    if cls == "store_imm" and cfg.imm_order != "with_addr":
        if cfg.imm_order in ("after_post", "after_issue"):
            mid = [("issued",)] if cfg.imm_order == "after_issue" else []
            return _head(op, cfg, c("pre"), ea) + [
                ("post", "write", op.ea, op.width, c("setup"))] + mid + [
                ("take", op.imm_bytes, "chain"), ("wait",), ("clocks", c("post"))]
        return _head(op, cfg, c("pre"), ea) + [
            ("data", "write", op.ea, op.width, c("setup")), ("take", op.imm_bytes),
            ("clocks", c("post"))]
    if cls == "rmw_imm" and cfg.imm_order != "with_addr":
        alu, setup = c("alu"), c("setup")
        if cfg.rmw_imm_issue == "rmw" and cfg.rmw_write_issue == "immediate":
            alu, setup = 0, max(alu, setup)     # posted at the start of the ALU step
        if op.nowrite:
            # grp_read: a form that does not write (81 /7) keeps the write's bus slot
            write = [("data", "nowrite", op.ea, op.width, setup)]
        else:
            write = [("data", "write", op.ea, op.width, setup)]
        return (_head(op, cfg, c("pre"), ea) + _imm_read(op, cfg, c)
                + [("clocks", alu)] + write + [("clocks", c("post"))])
    if cls == "lea":
        # (WP52) LDEA: the memory form's head (the EA table's clocks), no bus cycle, then the
        # exec clocks that write the offset to the register
        return _head(op, cfg, c("pre"), ea) + [("clocks", c("exec"))]
    if cls == "xlat":
        # (WP52) XLAT: no operand byte; pre clocks, the byte read at BW + AL posted with its
        # setup clocks (the last setup_free of them fetch-free, as a stack read's), exec clocks
        return [("clocks", c("pre")), ("data", "read", op.ea, 1, c("setup")),
                ("clocks", c("exec"))]
    if cls in ("load", "load_alu", "load_seg"):
        return _head(op, cfg, c("pre"), ea) + [("data", "read", op.ea, op.width, 0),
                                                ("clocks", cfg.read_use_latency),
                                                ("clocks", c("exec") + _dest_route(op, cfg))]
    if cls in ("store", "store_imm"):
        return _head(op, cfg, c("pre"), ea) + [("data", "write", op.ea, op.width, c("setup")),
                                                ("clocks", c("post"))]
    if cls in ("rmw", "rmw_imm"):
        read = _head(op, cfg, c("pre"), ea) + [("data", "read", op.ea, op.width, 0),
                                                ("clocks", cfg.read_use_latency)]
        alu = c("alu") + _dest_route(op, cfg)
        if op.shift and cfg.rmw_shift == "shift":
            # the operation is the shift unit's: the ALU step does the first count, the
            # shift unit adds its exec clocks and per_shift_count per further count
            alu += cfg.c("shift_imm", "exec") + cfg.per_shift_count * (op.count - 1)
        wk = "nowrite" if op.nowrite else "write"   # (WP19) dest_route=slot: CMP r/m,reg
        if cfg.rmw_write_issue == "immediate":
            # posted at the start of the ALU step, issuable after max(alu, setup) clocks
            return read + [("data", wk, op.ea, op.width, max(alu, c("setup"))),
                           ("clocks", c("post"))]
        return read + [("clocks", alu), ("data", wk, op.ea, op.width, c("setup")),
                       ("clocks", c("post"))]
    if cls == "push_mem" and cfg.push_mem_write == "at_data":
        # (WP20) the stack write posted as the operand's data arrives, its setup covering
        # the exec clocks (it holds fetches from then on, as POP r/m's memory write)
        return _head(op, cfg, c("pre"), ea) + [("data", "read", op.ea, 2, 0),
                ("data", "write", op.stack[1], 2, c("exec") + c("setup")),
                ("clocks", c("post"))]
    if cls == "push_mem":
        return _head(op, cfg, c("pre"), ea) + [("data", "read", op.ea, 2, 0),
                ("clocks", c("exec")), ("data", "write", op.stack[1], 2, c("setup")),
                ("clocks", c("post"))]
    if cls == "pop_mem" and cfg.pop_mem_order != "modrm_first":
        # (WP20) the stack read posted at the start (POP AW's), then the ModR/M byte and
        # any displacement, the EA clocks and the memory write
        if cfg.pop_mem_order == "stack_first":
            return ([("data", "read", op.stack[0], 2, c("rsetup"), c("rfree")),
                     ("clocks", c("exec"))] + _head(op, cfg, c("pre"), ea)
                    + [("data", "write", op.ea, 2, c("setup")), ("clocks", c("post"))])
        if cfg.pop_mem_order == "stack_post":
            # the memory write posted as the stack read's data arrives, its setup covering
            # the EA (it holds fetches from then on); a displacement is taken while it waits
            pre = c("pre")
            word = cfg.disp16 == "word" and rest == 3
            if cfg.disp_take == "end" and (rest == 2 or word):
                pre += 1            # (WP22) disp_take=end: a one-byte displacement is taken
                                    # where a two-byte one's last byte would be; (WP27)
                                    # disp16=word: a two-byte one's bytes both on that clock
            ea_n = ea[1]
            if ea_class(op, cfg) == "base_index_disp16":
                # (WP27) ea_disp16=own: the clocks base+index+d16 takes beyond the d8 form run
                # before the displacement leaves the queue, as in the split head
                extra = ea_n - cfg.ea.get("base_index_disp", 0)
                pre, ea_n = pre + extra, ea_n - extra
            disp = [("clocks", pre), ("take", rest - 1, "chain_word" if word else "chain")
                    ] if rest > 1 else []
            return ([("take", 1, "lead"),
                     ("data", "read", op.stack[0], 2, c("rsetup"), c("rfree"), False,
                      cfg.pop_read_hold == "queue"),
                     ("post", "write", op.ea, 2, c("setup") + ea_n)] + disp
                    + [("wait",), ("clocks", c("post"))])
        # stack_lead: the ModR/M byte taken by the decoder at the start, the displacement
        # after the read
        disp = [("take", rest - 1)] if rest > 1 else []
        return ([("take", 1, "lead"), ("data", "read", op.stack[0], 2, c("rsetup"), c("rfree")),
                 ("clocks", c("exec"))] + disp + [("clocks", c("pre")), ea,
                ("data", "write", op.ea, 2, c("setup")), ("clocks", c("post"))])
    if cls == "pop_mem":
        return _head(op, cfg, c("pre")) + [("data", "read", op.stack[0], 2, 0),
                ("clocks", c("exec")), ea, ("data", "write", op.ea, 2, c("setup")),
                ("clocks", c("post"))]
    if cls in ("push", "push_seg"):
        return [("data", "write", op.stack[1], 2, c("setup")), ("clocks", c("post"))]
    if cls in ("pop", "pop_seg", "dispose"):
        # (WP52) DISPOSE: its one stack read at BP (SP := BP first), pre clocks before it
        pre = [("clocks", c("pre"))] if c("pre") else []
        return pre + [("data", "read", op.stack[0], 2, c("setup")), ("clocks", c("exec"))]
    if cls == "push_imm":
        # (WP52) PUSH imm16 / imm8: the immediate taken, then the stack write
        return [("clocks", c("pre")), ("take", op.imm_bytes),
                ("data", "write", op.stack[1], 2, c("setup")), ("clocks", c("post"))]
    if cls == "prepare":
        # (WP52) PREPARE imm16,0: prepare_order puts BP's stack write before the three
        # operand bytes' take (write_first) or after it (take_first); exec clocks after both
        write = [("data", "write", op.stack[1], 2, c("setup"))]
        take = [("clocks", c("pre")), ("take", op.imm_bytes)]
        body = write + take if cfg.prepare_order == "write_first" else take + write
        return body + [("clocks", c("exec"))]
    if cls in ("push_r", "pop_r"):
        # (WP52) PUSH R / POP R: eight stack words, AW CW DW BW SP BP IX IY written from
        # SP - 2 down / read from SP up (SP's word read and discarded). burst_wait=data: each
        # word a data step (the EU waits as for any write / read); issue: each word posted and
        # the EU goes on once it is issued, gap clocks before the next is posted (a cadence
        # that does not stretch with the waits); the last word waits as a data step
        write = cls == "push_r"
        kind = "write" if write else "read"
        out = [("clocks", c("pre"))] if c("pre") else []
        for i in range(8):
            addr = (op.stack[1] - 2 * i if write else op.stack[0] + 2 * i) & 0xFFFF
            setup = c("setup") if i == 0 else c("wsetup")
            if cfg.burst_wait == "issue" and i < 7:
                out += [("post", kind, addr, 2, setup), ("sent",)]
            else:
                out += [("data", kind, addr, 2, setup)]
            if i < 7 and c("gap"):
                out.append(("clocks", c("gap")))
        return out + [("clocks", c("post" if write else "exec"))]
    if cls in ("branch_short", "branch_near", "dbnz"):
        # (WP55, F23) pre clocks, the displacement's take, a form with a condition field its
        # cond clocks (the flag test); taken: exec clocks, the flush (eu.py: the queue
        # discarded, fetching from the target on), post clocks; not taken: nexec clocks, a
        # register form
        head = [("clocks", c("pre")), ("take", rest)]
        if op.cond and c("cond"):
            head.append(("clocks", c("cond")))
        if op.target is None:
            decide = [("decide",)] if cfg.untaken == "wait" else []
            return head + decide + [("clocks", c("nexec"))]
        return head + [("clocks", c("exec")), ("flush", op.target), ("clocks", c("post"))]
    if cls == "call":
        # (WP55, F23) CALL: pre clocks, the displacement's take, then (call_order) the return
        # address's stack write and the exec clocks with the flush, post clocks
        write = [("data", "write", op.stack[1], 2, c("setup"))]
        flush = [("clocks", c("exec")), ("flush", op.target)]
        body = write + flush if cfg.call_order == "write_first" else flush + write
        return [("clocks", c("pre")), ("take", rest)] + body + [("clocks", c("post"))]
    if cls == "ret":
        # (WP55, F23) RET: pre clocks, the stack read of the return address, exec clocks,
        # the flush, post clocks
        return [("clocks", c("pre")), ("data", "read", op.stack[0], 2, c("setup")),
                ("clocks", c("exec")), ("flush", op.target), ("clocks", c("post"))]
    if cls in STRING_CLASSES:
        return _string_steps(op, cfg)
    if cls in ("out", "in"):
        kind = "io_write" if cls == "out" else "io_read"
        pre = c("pre") if rest else c("pre0")  # no port byte (DW forms): pre0 (default 0)
        if cfg.io_release == "post":
            # the request is posted when the port is latched: on the port byte's take, or
            # pre0 clocks after the start (DW); an OUT then runs exec clocks and ends (its
            # I/O left in the bus unit's slot), an IN waits for its data
            out = cls == "out"
            # a form without a port byte (DW) may have its own setup0 (format property)
            setup = c("setup0") if not rest and "setup0" in cfg.cost.get(cls, {}) else c("setup")
            req = (kind, op.port, op.width, setup)
            if rest:
                head = [("clocks", pre), ("take", rest, "port", req, out)]
            else:
                head = [("clocks", pre), ("post_io", *req) if out else ("post", *req)]
            tail = [("clocks", c("exec"))] if out else [("wait",), ("clocks", c("post"))]
            return head + tail
        return [("clocks", pre), ("take", rest), ("clocks", c("exec")),
                ("data", kind, op.port, op.width, c("setup")), ("clocks", c("post"))]
    raise ValueError(cls)


def _string_steps(op: Op, cfg) -> list[tuple]:
    """(WP67, F24) a string form: each element's bus cycles in order (STRING_STEPS), each a
    data step (the EU posts the request and waits: a read for its data, a write until it is
    issued, write_wait), the element's first cycle with its own setup and every later one
    with mid. The addresses step by the width from IX / IY (an odd word splits per
    odd_split); an I/O cycle runs at the I/O waits.

    Without a prefix: pre clocks, the one element (setup), exec clocks.
    REP: the string opcode's take after the prefix (str_take: with the take sync; chained, none;
    quiet: chained, then a wait until no fetch is on the bus or wanted, the refill done), rpre
    clocks (str_setup=nowait: counted only on clocks no memory cycle is in a wait state); with no element (CW = 0) zexit clocks and the end; else the elements,
    the first with first, element 1 (the second) with loop1 when the class has one, the rest
    with loop; the last cycle of the element that runs CW out last more clocks; then, with
    str_overrun=read, a REP compare issues the next element's reads (at the next IX / IY, as
    a loop element: the read the loop posts before the element's termination test takes
    effect, nothing compared with it; silicon's in every REP compare that ran an element);
    then the exit: rexit clocks when CW ran out, cexit when a compare's condition ended it.
    str_hold=hold: after each compared element a compare raises no fetch request for its
    class's chold clocks (the result's clocks; F24: a single CMPM's or CMPBK's next fetch is 2
    to 3 clocks after its read where LDM's follows the read at once)."""
    c = lambda name: cfg.c(op.cls, name)
    w, cyc = op.width, STRING_STEPS[op.cls]
    has = cfg.cost.get(op.cls, {})

    def element(i: int, setup: int, last: bool = False, kinds=None) -> list[tuple]:
        out = []
        for j, (kind, place) in enumerate(cyc):
            if kinds is not None and kind not in kinds:
                continue
            addr = {"ix": (op.ix + i * w) & 0xFFFF, "iy": (op.iy + i * w) & 0xFFFF,
                    "port": op.port}[place]
            st = setup if not out else c("mid")
            if last and j == len(cyc) - 1:
                st += c("last")
            out.append(("data", kind, addr, w, st))
        if (out and kinds is None and cfg.str_hold == "hold" and op.cls in STRING_COMPARES
                and c("chold")):
            out.append(("fetch_hold", c("chold")))
        return out

    def loop(i: int) -> int:
        return c("loop1") if i == 1 and "loop1" in has else c("loop")

    if op.rep is None:
        return [("clocks", c("pre"))] + element(0, c("setup")) + [("clocks", c("exec"))]
    seq = [("take", 1) if cfg.str_take == "sync" else ("take", 1, "chain")]
    if cfg.str_take == "quiet":
        seq.append(("quiet",))
    seq.append(("nowait" if cfg.str_setup == "nowait" else "clocks", c("rpre")))
    if not op.n:
        return seq + [("clocks", c("zexit"))]
    for i in range(op.n):
        seq += element(i, c("first") if i == 0 else loop(i),
                       last=i == op.n - 1 and not op.cond)
    if cfg.str_overrun == "read" and op.cls in STRING_COMPARES:
        seq += element(op.n, loop(op.n), kinds=("read",))
    return seq + [("clocks", c("cexit" if op.cond else "rexit"))]
