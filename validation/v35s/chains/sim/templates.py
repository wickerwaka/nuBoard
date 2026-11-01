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
LOCK_PREFIX = 0xF0           # (WP88, F36) BUSLOCK: a prefix pseudo-instruction, no segment
# (WP88, F36) the accumulator's ALU forms with an imm16 (OR ADDC SUBC AND SUB XOR CMP AW,imm16;
# 05 ADD is F3's): the imm class
ACC_IMM16 = frozenset([0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D])


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
    count_byte: bool = False     # (WP99) a memory shift whose count is an operand byte (C0/C1 on
                                 # memory), a format property: the EU runs it per shift_mem_imm
    disp: int = 0                # (WP27) displacement bytes after the ModR/M byte (mod 01: 1,
                                 # mod 10 and the direct mod 00 rm 110: 2)
    bus: bool = True             # (WP52) the memory operand has a bus cycle (False: LDEA, the
                                 # EA computed and written to a register)
    sreg: str | None = None      # (WP76) a segment register is the operand moved, a format
                                 # property: "load" (MOV sreg,r/m, 8E: the segment register
                                 # the destination) or "store" (MOV r/m,sreg, 8C)
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
    # (WP78, F32) the 0F page: page is the opcode bytes after the first (the IR's) that come
    # before the ModR/M byte (1 for every 0F form, 0 elsewhere), a format property of the
    # encoding; bf a bit field's (offset, width field, crosses, cost) from the register file
    # (EXT / INS: the offset and width registers used whole, as silicon does; cost the
    # docs/v35s-eu-timing.md formula of (offset, width))
    page: int = 0
    bf: tuple | None = None
    # (WP81) the last immediate byte is the first (even) byte of its word, the next opcode its
    # second: the word half-taken (eu.py sets it from the chain base; a format property of the
    # operand's word alignment)
    half_word: bool = False
    # (WP88, F35) DBNZNE / DBNZE not taken because the Z test failed (not the count)
    zfail: bool = False
    # (WP91, F37) BRK's vector: the address of its offset word (4n; the segment word at + 2)
    vec: int | None = None


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


# (WP88, F35) the 70-7F row's conditions by the low nibble (bit 0 negates the even one's test):
# V, CY, Z, CY or Z, S, P, S xor V, (S xor V) or Z
_COND = {0: lambda f: f["V"], 2: lambda f: f["CY"], 4: lambda f: f["Z"],
         6: lambda f: f["CY"] or f["Z"], 8: lambda f: f["S"], 0xA: lambda f: f["P"],
         0xC: lambda f: f["S"] != f["V"], 0xE: lambda f: (f["S"] != f["V"]) or f["Z"]}
_COND_FLAGS = {0: ("V",), 2: ("CY",), 4: ("Z",), 6: ("CY", "Z"), 8: ("S",), 0xA: ("P",),
               0xC: ("S", "V"), 0xE: ("S", "V", "Z")}


def _flag(regs: dict, name: str, op: int, k: int) -> int:
    v = regs.get(name)
    if v is None:
        raise ValueError(f"opcode {op:02X} at chain offset {k}: the flags are not known")
    return v


def cond_taken(op: int, regs: dict, k: int = 0) -> bool:
    """(WP88, F35) whether the conditional short branch op (70-7F) is taken under the flags
    execute keeps (regs Z CY S V P; BE / BNE need Z alone, as since WP55)."""
    n = op & 0x0E
    f = {name: _flag(regs, name, op, k) for name in _COND_FLAGS[n]}
    return bool(_COND[n](f)) != bool(op & 1)


def _set_flags(regs: dict, a: int, b: int, sub: bool):
    """(WP88, F35) Z CY S V P of the 16-bit a - b (sub) or a + b, as execute keeps them."""
    r = (a - b if sub else a + b)
    v = r & 0xFFFF
    sa, sb, sr = a >> 15 & 1, b >> 15 & 1, v >> 15 & 1
    regs["Z"] = int(v == 0)
    regs["CY"] = int(r < 0 if sub else r > 0xFFFF)
    regs["S"] = sr
    regs["V"] = int((sa != sb and sr != sa) if sub else (sa == sb and sr != sa))
    regs["P"] = int(bin(v & 0xFF).count("1") % 2 == 0)


def decode(code: bytes, k: int, regs: dict) -> Op:
    op = code[k] if k < len(code) else 0x90
    if op in PREFIXES:
        return Op(k, 1, "prefix", op)
    if op & 0xFE in STRING_OPS or op in REP_PREFIXES:
        sop = _string_op(code, k, regs)        # (WP67, F24) the string forms
        if sop is not None:
            return sop
    if op == LOCK_PREFIX:
        # (WP88, F36) BUSLOCK (F0): a prefix pseudo-instruction as a segment prefix is (F36:
        # BUSLOCK MOV AW,DW costs what DS1: MOV AW,DW does, cell for cell); it names no segment
        return Op(k, 1, "prefix", op)
    if 0x90 <= op <= 0x97:
        # NOP, XCH AW,r16 (WP88, F36: 91-97 cost what XCH AW,DW does in every cell)
        return Op(k, 1, "reg", op)
    if op == 0xF4:
        return Op(k, 1, "halt", op)
    if 0x50 <= op <= 0x57 or op == 0x9C:
        # PUSH r16 (WP88, F36: 51-57 cost what PUSH AW does in every cell); PUSH PSW (9C: its
        # write on PUSH r16's clock)
        return Op(k, 1, "push", op, stack=(None, (regs["SP"] - 2) & 0xFFFF))
    if 0x58 <= op <= 0x5F:                  # POP r16 (F15 POP AW / CW; WP88, F36 the rest)
        return Op(k, 1, "pop", op, stack=(regs["SP"], None))
    if op == 0x9D:                          # (WP88, F36) POP PSW: its own class
        return Op(k, 1, "pop_psw", op, stack=(regs["SP"], None))
    if 0xB0 <= op <= 0xB7:
        return Op(k, 2, "imm", op, imm_bytes=1)
    if 0xB8 <= op <= 0xBF or op in (0x05, 0xA9) or op in ACC_IMM16:  # (WP20) A9: TEST AW,imm16
        return Op(k, 3, "imm", op, imm_bytes=2)
    if op == 0xA8:                          # (WP20) TEST AL,imm8
        return Op(k, 2, "imm", op, imm_bytes=1)
    if op < 0x40 and op & 7 == 4:
        # (WP98, F38) op AL,imm8 (04 0C 14 1C 24 2C 34 3C, the operation in bits 5:3): the imm
        # class as TEST AL,imm8 (A8) is decoded (F38: each costs exactly A8's cost in every cell)
        return Op(k, 2, "imm", op, imm_bytes=1)
    if op in (0xA0, 0xA1, 0xA2, 0xA3):
        # MOV AW,[d16] / MOV [d16],AW; (WP88, F36) the byte forms A0 / A2 (bit 0 the width)
        return Op(k, 3, "load" if op < 0xA2 else "store", op, width=1 + (op & 1),
                  ea=int.from_bytes(code[k + 1:k + 3], "little"), mode_class="direct")
    if op in (0xE4, 0xE5, 0xE6, 0xE7):
        return Op(k, 2, "in" if op < 0xE6 else "out", op, width=1 + (op & 1), port=code[k + 1])
    if op in (0xEC, 0xED, 0xEE, 0xEF):
        return Op(k, 1, "in" if op < 0xEE else "out", op, width=1 + (op & 1), port=regs["DW"])
    sp = regs["SP"]
    if op in (0xEB, 0xE0, 0xE1, 0xE2, 0xE3) or 0x70 <= op <= 0x7F:
        # (WP55, F23) the short transfers, a 1-byte displacement from the next instruction:
        # BE (taken with Z), BNE (without Z), BR short (always) and DBNZ (CW counted down,
        # taken while it is not 0); the decision is the semantics' (execute sets Z and CW).
        # (WP88, F35) every condition of the 70-7F row (cond_taken: the flags execute keeps),
        # DBNZNE / DBNZE (E0 / E1: CW counted down, taken while it is not 0 and Z is clear /
        # set: the loop format, DBNZ's class) and BCWZ (E3: taken when CW is 0, CW unchanged:
        # its own class, the loop format's structure)
        disp = int.from_bytes(code[k + 1:k + 2], "little", signed=True)
        cls = "branch_short"
        zfail = False
        if op in (0xE0, 0xE1, 0xE2):
            taken = (regs["CW"] - 1) & 0xFFFF != 0
            cls = "dbnz"
            if op != 0xE2:
                # DBNZNE / DBNZE: the Z test decides first (F35: not taken on Z 3 clocks
                # shorter than not taken on the count, taken a clock longer than DBNZ)
                zfail = _flag(regs, "Z", op, k) != (op == 0xE1)
                taken = taken and not zfail
                cls = "dbnz_z"
        elif op == 0xE3:
            taken, cls = regs["CW"] == 0, "bcwz"
        elif op == 0xEB:
            taken = True
        else:
            taken = cond_taken(op, regs, k)
        return Op(k, 2, cls, op, target=k + 2 + disp if taken else None,
                  cond=0x70 <= op <= 0x7F, zfail=zfail)
    if op in (0xEA, 0x9A):
        # (WP88, F35) BR far / CALL far (EA / 9A offset16 segment16): the target an absolute
        # offset in the code segment (the segment is the chain's own, PS = 1000h); CALL far
        # writes PS, then the return offset, below SP
        target = int.from_bytes(code[k + 1:k + 3], "little") - regs.get("code_at", 0)
        if op == 0xEA:
            return Op(k, 5, "branch_far", op, target=target)
        return Op(k, 5, "call_far", op, target=target, stack=(None, (sp - 2) & 0xFFFF))
    if op in (0xC2, 0xCA, 0xCB):
        # (WP88, F35) RET imm16 (C2), RET far (CB: the offset, then the segment) and RET far
        # imm16 (CA): the return address read at SP (the CALL that wrote it, execute), SP
        # raised past it and by the immediate
        ret = regs.get(f"ret{sp:04X}")
        if ret is None:
            raise ValueError(f"RET at chain offset {k}: no return address at {sp:04X}")
        cls = {0xC2: "ret_imm", 0xCA: "ret_far_imm", 0xCB: "ret_far"}[op]
        n = 0 if op == 0xCB else 2
        return Op(k, 1 + n, cls, op, target=ret, imm_bytes=n, stack=(sp, None))
    if op in (0xC4, 0xC5):
        # (WP88, F36) LES / LDS (MOV DS1,r16,m32 / MOV DS0,r16,m32): the pointer's offset word,
        # then its segment word (load_ptr; the segment registers are not modelled)
        mod, reg, rm, ea, mc, n = _modrm(code, k + 1, regs)
        if mod == 3:
            raise ValueError(f"opcode {op:02X} with a register operand at chain offset {k}")
        return Op(k, 1 + n, "load_ptr", op, ea=ea, mode_class=mc, modrm=True, disp=n - 1)
    if op in (0xCC, 0xCD):
        # (WP91, F37) BRK 3 (CC) / BRK imm8 (CD n): the vector's offset word at 4n read, PSW
        # pushed, the segment word at 4n + 2 read, PS and the return offset pushed (three words
        # below SP); the target the vector's offset (a code offset in PS, the chain's own: the
        # lead stored it, execute's memory image)
        n = 3 if op == 0xCC else code[k + 1]
        length = 1 if op == 0xCC else 2
        # (the type byte is an operand byte as a transfer's displacement is, not imm_bytes)
        return Op(k, length, "brk", op, target=_far_target(regs, 4 * n, k), vec=4 * n,
                  stack=(None, (sp - 2) & 0xFFFF))
    if op == 0xCF:
        # (WP91, F37) RETI: the return offset, PS and PSW popped at SP, SP + 2, SP + 4 (the BRK
        # that pushed them, execute)
        ret = regs.get(f"ret{sp:04X}")
        if ret is None:
            raise ValueError(f"RETI at chain offset {k}: no return address at {sp:04X}")
        return Op(k, 1, "reti", op, target=ret, stack=(sp, None))
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
    if op == 0x0F:
        return _page0f(code, k, regs)       # (WP78, F32) the 0F page
    if op in ONE_BYTE or 0x40 <= op <= 0x4F:
        # (WP78, F33) the one-byte register forms: INC / DEC r16, the adjusts, CVTBW / CVTWL,
        # the flag forms; each class its own costs (ONE_BYTE)
        return Op(k, 1, "incdec" if 0x40 <= op <= 0x4F else ONE_BYTE[op], op)
    if op in (0xD4, 0xD5):
        # (WP78, F33) CVTBD / CVTDB (D4 0A / D5 0A): the second byte a constant operand the form
        # takes as an immediate byte
        return Op(k, 2, "convert" if op == 0xD4 else "convert_d", op, imm_bytes=1)
    mod, reg, rm, ea, mc, n = _modrm(code, k + 1, regs)
    mem = mod != 3
    # the w bit (bit 0) of the ALU, TEST, XCH and MOV ModR/M opcodes: 0 = byte operand
    width = 1 if (op < 0x40 or 0x84 <= op <= 0x8B) and not op & 1 else 2
    if op in (0xD0, 0xF6, 0xFE, 0x80, 0x82, 0xD2, 0xC0):   # (WP21) the byte groups' w bit;
        width = 1                           # (WP78) FE; (WP88, F36) 80 / 82, D2; (WP98, F38) C0
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
    elif op in (0x84, 0x85) and not mem:
        # (WP88, F36) TEST r8,r8 / r16,r16: its own class (TEST DL,AL costs 3 clocks more than
        # the other two-byte register forms, MOV r8,imm8's cost: the fixed operation's lookup)
        cls = "test_reg"
    elif op in (0x8B, 0x8A, 0x85, 0x89, 0x88, 0x87, 0x84, 0x86):
        cls = "reg" if not mem else {0x8B: "load", 0x8A: "load", 0x89: "store", 0x88: "store",
                                     0x87: "rmw", 0x86: "rmw"}.get(op, "load_alu")
    elif op in (0x80, 0x81, 0x82, 0x83):
        # (WP20) 83: the immediate is one byte, sign-extended; (WP88, F36) 80 and its alias 82,
        # the byte group: a one-byte immediate (F36: ADD / CMP byte [BW],imm8 in 80 / 82 cost
        # what the word form 83 does)
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
    elif op in (0xC0, 0xC1):            # (WP98, F38) C0: the byte form (bit 0 the width)
        length += 1
        if not mem:
            return Op(length=length, cls="shift_imm", count=code[k + length - 1], imm_bytes=1,
                      **base)
        # (WP98, F38) a memory operand: a shift on memory, the rmw class as D1 / D3's memory
        # forms are decoded (count, shift; no imm_bytes: the rmw template's head takes every
        # operand byte, the count byte last), the count from the immediate byte (F38: C0 27 04
        # costs exactly C1 27 04's cost in every cell)
        cls = "rmw"
        base["count"] = code[k + length - 1]
        base["shift"] = True
        base["count_byte"] = True       # (WP99) the count an operand byte (shift_mem_imm)
    elif op in (0xD0, 0xD1):            # (WP21) D0: the byte form
        if not mem:
            return Op(length=length, cls="shift_imm", count=1, **base)
        cls = "rmw"
        base["count"] = 1
        base["shift"] = True
    elif op in (0xD2, 0xD3):            # (WP88, F36) D2: the byte form
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
    elif op == 0xFE:                    # (WP78, F33) INC / DEC r/m8 (FE /0, /1)
        if reg not in (0, 1):
            raise ValueError(f"opcode FE /{reg} at chain offset {k} is not in the catalog")
        cls = "rmw" if mem else "incdec"    # a register operand: INC / DEC r8, its own class
    elif op in (0x69, 0x6B):
        # (WP78, F33) MUL r16,r/m16,imm16 / imm8 (sign-extended): the multiply with an
        # immediate after the ModR/M operand
        nimm = 2 if op == 0x69 else 1
        length += nimm
        base["imm_bytes"] = nimm
        base["signed"] = True
        cls = "mul_imm"
    elif op == 0xFF and not mem and reg in (2, 4):
        # (WP88, F35) CALL r16 (FF /2) / BR r16 (FF /4): the target an absolute offset in the
        # code segment, the register's value; CALL writes the return offset below SP
        target = regs[REG16[rm]] - regs.get("code_at", 0)
        # the ModR/M byte names the register: an operand byte as a displacement is, not a
        # memory form's ModR/M (the rules that name a ModR/M form do not see it: start_sync
        # b2b_modrm, io_older io_modrm, the ModR/M latch). F35 ind: with it a ModR/M form,
        # the third refill fetch after M0's I/O 3 clocks late at pE and one too many at pO
        base = {**base, "modrm": False}
        if reg == 2:
            return Op(length=length, cls="call_reg", target=target,
                      **{**base, "stack": (None, (regs["SP"] - 2) & 0xFFFF)})
        return Op(length=length, cls="br_reg", target=target, **base)
    elif op == 0xFF and mem and reg in (2, 3, 4, 5):
        # (WP91, F37) CALL near [m] (FF /2), CALL far [m] (/3), BR near [m] (/4), BR far [m] (/5):
        # the pointer at the EA (its offset; a far pointer's segment at EA + 2) is the word the
        # chain's lead stored there (execute's memory image); a memory form's ModR/M (the head,
        # displacement and EA as the load's). CALL writes PS (far) and the return offset below SP
        cls = {2: "call_mem", 3: "call_far_mem", 4: "br_mem", 5: "branch_far_mem"}[reg]
        target = (_far_target(regs, ea, k) if reg in (3, 5)
                  else _mem_word(regs, ea, k) - regs.get("code_at", 0))
        if reg in (2, 3):
            base["stack"] = (None, (regs["SP"] - 2) & 0xFFFF)
        return Op(length=length, cls=cls, target=target, **base)
    elif op == 0xFF:
        cls = "push_mem" if reg == 6 else "rmw"
        if reg == 6:
            base["stack"] = (None, (regs["SP"] - 2) & 0xFFFF)
    elif op == 0x8F:
        cls = "pop_mem"
        base["stack"] = (regs["SP"], None)
    elif op == 0x8E and not mem:
        cls = "reg"                     # (WP24) MOV sreg,r16: the prelude's segment loads
        base["sreg"] = "load"
    elif op == 0x8E:
        cls = "load_seg"                # (WP52) MOV sreg,r/m16: a load into a segment register
        base["sreg"] = "load"
    elif op == 0x8C:
        cls = "store" if mem else "reg"     # (WP52) MOV r/m16,sreg
        base["sreg"] = "store"
    elif op == 0x8D:
        if not mem:
            raise ValueError(f"LDEA with a register operand at chain offset {k}")
        cls = "lea"                     # (WP52) LDEA r16,m: the EA, no bus cycle, to the reg
        base["bus"] = False
    else:
        raise ValueError(f"opcode {op:02X} at chain offset {k} is not in the catalog")
    return Op(length=length, cls=cls, **base)


CODE_SEG = 0x1000            # (WP91) PS: the chain's code segment (types.CODE_SEGMENT)


def _mem_word(regs: dict, addr: int, k: int) -> int:
    """(WP91, F37) the word at addr as the chain stored it (execute's memory image of MOV
    [m],r16 / MOV [m],imm16); a word no instruction of the chain wrote is not modelled (the
    image's 90h fill or the zeroed vector table would send the transfer out of the chain)."""
    w = regs.get(f"mem{addr & 0xFFFF:04X}")
    if w is None:
        raise ValueError(f"transfer at chain offset {k}: no stored word at {addr & 0xFFFF:04X}")
    return w


def _far_target(regs: dict, addr: int, k: int) -> int:
    """(WP91, F37) a far pointer's (or a vector's) target as a chain offset: its segment word
    (at addr + 2) must be PS, its offset word (at addr) is a code offset in PS."""
    seg = _mem_word(regs, addr + 2, k)
    if seg != CODE_SEG:
        raise ValueError(f"far transfer at chain offset {k}: segment {seg:04X} is not PS")
    return _mem_word(regs, addr, k) - regs.get("code_at", 0)


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
# (WP76, F33) REPNC (64) and REPC (65) are REPNE / REPE with the carry in place of Z: the same
# form, the compare's exit the walk's (normalize.string_elements, StringRun.cond: the carry for
# 64 / 65, Z for F2 / F3); the template never reads which flag
REP_PREFIXES = (0xF2, 0xF3, 0x64, 0x65)


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


# (WP78, F33) the one-byte register forms other than INC / DEC r16 (40-4F), by class: each class
# its own costs (F33: CLC, STC, CMC, CLD, STD and CVTBW cost what INC r16 does; CLI, STI, CVTWL,
# the decimal and the ASCII adjusts their own)
ONE_BYTE = {0xF8: "flag", 0xF9: "flag", 0xF5: "flag", 0xFC: "flag", 0xFD: "flag",
            0xFA: "flag_di", 0xFB: "flag_ei", 0x98: "extend", 0x99: "extend_w",
            0x27: "adjust", 0x2F: "adjust", 0x37: "adjust_b", 0x3F: "adjust_b",
            # (WP88, F36) LAHF / SAHF (MOV AH,PSW / MOV PSW,AH): CLC's cost, alone and in a pair
            0x9F: "flag", 0x9E: "flag"}
# (WP78, F32) the 0F page's second byte: the bit ops (10-1F: bits 2:1 the operation, TEST1 /
# CLR1 / SET1 / NOT1, bit 0 the width, bit 3 an imm index after the operand where clear the
# index is CL), the packed BCD strings (20 ADD4S, 22 SUB4S, 26 CMP4S), the digit rotates (28
# ROL4, 2A ROR4), the bit fields (31 / 39 INS, 33 / 3B EXT: bit 3 the imm4 width)
BIT1_MEM = ("bit1_test", "bit1_clr", "bit1_rmw", "bit1_rmw")     # by bits 2:1 of the second byte
BCD_OPS = {0x20: "bcd4s", 0x22: "bcd4s", 0x26: "bcd4s_cmp"}
ROT4_OPS = {0x28: "rol4", 0x2A: "ror4"}
BF_OPS = {0x31: "bf_ins", 0x39: "bf_ins", 0x33: "bf_ext", 0x3B: "bf_ext"}
BCD_CLASSES = ("bcd4s", "bcd4s_cmp")
BF_CLASSES = ("bf_ext", "bf_ins")
# (WP94) bf_imm_hold: ("fetch_hold", BF_TAKE_HOLD) arms a hold that starts with the next operand
# take (that clock included) and lasts until a ("fetch_hold", 0) lifts it; requests raised
# (and back-to-back fetches committed) before that take still run (eu.py, queue.py)
BF_TAKE_HOLD = -1
# (WP78) the classes of the 0F page and F33 whose structure (the queue's, the bus unit's and the
# EU's rules that name a class: the I/O interlock, the register forms' and the unit forms'
# rules, the read-modify-write's) is an existing class's: the costs are their own (Config.c
# with the class itself), every structural rule sees the base class (eu.py)
BASE_CLASS = {"bit1": "reg", "rol4": "reg", "ror4": "reg", "incdec": "reg", "adjust": "reg",
              "adjust_b": "reg", "extend": "reg", "extend_w": "reg", "flag": "reg",
              "flag_di": "reg", "flag_ei": "reg", "convert": "imm", "convert_d": "imm",
              "bit1_test": "load_alu", "bit1_rmw": "rmw", "bit1_clr": "rmw",
              "rol4_mem": "rmw", "ror4_mem": "rmw", "mul_imm": "mul",
              # (WP88, F35, F36) the transfers F35 completes and the forms of F36 that cost
              # differently from their class (_wp88_steps): BCWZ and DBNZNE / DBNZE the loop
              # format's (dbnz); RET imm16 and the far returns RET's; CALL r16 and CALL far
              # CALL near's; BR r16 and BR far BR near's; LES / LDS the load's; POP PSW POP
              # r16's; TEST r,r the register forms' (_wp78_steps)
              "bcwz": "dbnz", "dbnz_z": "dbnz", "ret_imm": "ret", "ret_far": "ret",
              "ret_far_imm": "ret", "call_reg": "call", "call_far": "call",
              "br_reg": "branch_near", "branch_far": "branch_near", "load_ptr": "load",
              "pop_psw": "pop", "test_reg": "reg",
              # (WP91, F37) the memory-indirect transfers, BRK and RETI (_wp91_steps): CALL
              # near / far [m] and BRK CALL near's, BR near / far [m] BR near's, RETI RET's
              "call_mem": "call", "call_far_mem": "call", "br_mem": "branch_near",
              "branch_far_mem": "branch_near", "brk": "call", "reti": "ret"}
WP88_CLASSES = ("bcwz", "dbnz_z", "ret_imm", "ret_far", "ret_far_imm", "call_reg", "call_far",
                "br_reg", "branch_far", "load_ptr", "pop_psw")
WP91_CLASSES = ("call_mem", "br_mem", "call_far_mem", "branch_far_mem", "brk", "reti")


def base_class(cls: str) -> str:
    """(WP78) the existing class whose structure cls shares (BASE_CLASS), else cls."""
    return BASE_CLASS.get(cls, cls)


def bf_cost(op: str, offset: int, width: int) -> int:
    """(WP78, F32) the bit field's EU cost as docs/v35s-eu-timing.md gives it, a function of the
    offset o and the width field w (w + 1 bits) alone (swept over all 256 pairs there; F32's
    seven cases equal it plus a class constant): EXT 107 - 2o - 4w within one word or ending at
    the boundary (43 at o = 0, w = 15), 61 + 2o crossing (-1 at w = 15); INS 94 within (92 at
    o = 0), 86 at the boundary (84 at o = 0), 128 + 4(o + w - 16) crossing. The registers are
    used whole (WP74: silicon does not reduce them to 4 bits); outside 0-15 the formula is
    extrapolated (no corpus run goes there)."""
    o, w = offset, width
    if op == "bf_ext":
        if o + w >= 16:
            return 61 + 2 * o - (1 if w == 15 else 0)
        return 43 if (o, w) == (0, 15) else 107 - 2 * o - 4 * w
    if o + w >= 16:
        return 128 + 4 * (o + w - 16)
    if o + w == 15:
        return 84 if o == 0 else 86
    return 92 if o == 0 else 94


def _page0f(code: bytes, k: int, regs: dict) -> Op:
    """(WP78, F32) a 0F-page form at k: the IR holds 0F, the second opcode byte is the first
    operand byte (page = 1), then the ModR/M byte where the form has one."""
    s = code[k + 1]
    if s in BCD_OPS:
        # the packed BCD strings: (CL + 1) / 2 byte pairs from the register file (the EU takes
        # the walk's count, as a REP form's: machine.py), source DS0:IX, destination DS1:IY
        cl = regs["CW"] & 0xFF
        return Op(k, 2, BCD_OPS[s], 0x0F, width=1, ix=regs["IX"], iy=regs["IY"],
                  n=(cl + 1) // 2, page=1)
    if not (0x10 <= s <= 0x1F or s in ROT4_OPS or s in BF_OPS):
        raise ValueError(f"opcode 0F {s:02X} at chain offset {k} is not in the catalog")
    mod, reg, rm, ea, mc, n = _modrm(code, k + 2, regs)
    mem = mod != 3
    base = dict(offset=k, opcode=0x0F, modrm=True, page=1, ea=ea, mode_class=mc,
                disp=n - 1 if mem else 0)
    length = 2 + n
    if 0x10 <= s <= 0x1F:
        imm = 1 if s & 8 else 0
        cls = BIT1_MEM[(s >> 1) & 3] if mem else "bit1"
        return Op(length=length + imm, cls=cls, width=1 + (s & 1), imm_bytes=imm,
                  cl_count=not imm, **base)
    if s in ROT4_OPS:
        return Op(length=length, cls=ROT4_OPS[s] + ("_mem" if mem else ""), width=1, **base)
    if mem:
        raise ValueError(f"0F {s:02X} with a memory operand at chain offset {k}")
    cls = BF_OPS[s]
    imm = 1 if s & 8 else 0
    offset = (regs[REG8[rm][0]] >> REG8[rm][1]) & 0xFF
    width = code[k + 3] if imm else (regs[REG8[reg][0]] >> REG8[reg][1]) & 0xFF
    cross = offset + width >= 16
    return Op(length=length + imm, cls=cls, width=2, imm_bytes=imm, ix=regs["IX"],
              iy=regs["IY"], bf=(offset, width, cross, bf_cost(cls, offset, width)),
              **{**base, "ea": None, "mode_class": None})


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
    if o < 0x40 and o & 7 == 4:             # (WP98) op AL,imm8 (CMP: flags only)
        return () if o == 0x3C else ("AW",)
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
    if mod == 3 and o == 0xC0:              # (WP98) SHL r8,imm8
        return (REG8[rm][0],)
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
    elif o < 0x40 and o & 7 == 4:
        # (WP98) op AL,imm8: AL's value (the flags are not kept, as for the AW,imm16 forms)
        al, imm, f = regs["AW"] & 0xFF, code[k + 1], (o >> 3) & 7
        cy = regs.get("CY") or 0
        r = (al + imm, al | imm, al + imm + cy, al - imm - cy, al & imm, al - imm, al ^ imm,
             al)[f]
        _set8(regs, 0, r & 0xFF)
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
            _set_flags(regs, regs[REG16[rm]], imm16(k + 2), False)   # (WP88) F35's ADD DW,imm16
            regs[REG16[rm]] = (regs[REG16[rm]] + imm16(k + 2)) & 0xFFFF
        elif o in (0xD1, 0xD3, 0xC1) and mod == 3 and reg == 4:
            n = 1 if o == 0xD1 else (regs["CW"] & 0xFF if o == 0xD3 else code[k + 2])   # (WP57) silicon: the full count
            regs[REG16[rm]] = (regs[REG16[rm]] << n) & 0xFFFF
        elif o == 0xC0 and mod == 3 and reg == 4:   # (WP98) SHL r8,imm8
            name, sh = REG8[rm]
            _set8(regs, rm, ((regs[name] >> sh) << code[k + 2]) & 0xFF)
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
            # (WP88, F35) and CY S V P, every condition of the 70-7F row
            a, b = regs[REG16[reg]], regs[REG16[rm]]
            _set_flags(regs, a if o == 0x3B else b, b if o == 0x3B else a, True)
    if o == 0xD7:
        _set8(regs, 0, FILL_WORD & 0xFF)        # (WP52) XLAT: AL from the data fill
    _execute_wp78(op, code, regs)
    if op.cls in ("push", "push_mem", "push_imm", "push_seg", "prepare"):
        regs["SP"] = (regs["SP"] - 2) & 0xFFFF
    _execute_wp88(op, code, regs)
    _execute_wp91(op, code, regs)
    if op.cls == "prepare":
        # (WP52) PREPARE imm16,0: BP := SP after BP's push, then SP -= imm16
        regs["BP"] = regs["SP"]
        regs["SP"] = (regs["SP"] - imm16(k + 1)) & 0xFFFF
    if op.cls in ("pop", "pop_mem", "pop_seg", "pop_psw"):
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
    if op.cls in ("dbnz", "dbnz_z"):
        regs["CW"] = (regs["CW"] - 1) & 0xFFFF      # (WP55) DBNZ; (WP88) DBNZNE / DBNZE
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


def _execute_wp88(op: Op, code: bytes, regs: dict):
    """(WP88, F35) the register effects of the transfers F35 completes: CALL r16 keeps the
    return offset below SP as CALL near does; CALL far writes PS, then the return offset (two
    words); RET imm16 and the far returns raise SP past what they read and by the immediate.
    (DBNZNE / DBNZE count CW down with DBNZ in execute; BCWZ leaves CW.)"""
    k, cls = op.offset, op.cls
    if cls == "call_reg":
        regs["SP"] = (regs["SP"] - 2) & 0xFFFF
        regs[f"ret{regs['SP']:04X}"] = k + op.length
    elif cls == "call_far":
        regs["SP"] = (regs["SP"] - 4) & 0xFFFF
        regs[f"ret{regs['SP']:04X}"] = k + op.length
    elif cls in ("ret_imm", "ret_far", "ret_far_imm"):
        n = 2 if cls == "ret_imm" else 4
        imm = int.from_bytes(code[k + 1:k + 3], "little") if op.imm_bytes else 0
        regs["SP"] = (regs["SP"] + n + imm) & 0xFFFF


def _execute_wp91(op: Op, code: bytes, regs: dict):
    """(WP91, F37) a memory image of the words the chain stores, and the stack walk of the F37
    transfers. MOV [m],AW (A3), MOV [m],r16 (89) and MOV [m],imm16 (C7) keep the word they
    write as regs["mem<addr>"] (a word store only: the transfers read words; the timing never
    reads it except as a pointer or vector, templates._mem_word), as CALL keeps "ret<SP>".
    CALL near [m] lowers SP by 2 and CALL far [m] by 4 and keep the return offset at the new SP
    (as CALL r16 / CALL far); BRK lowers SP by 6 (PSW, PS, then the return offset, at SP - 6);
    RETI raises it by 6."""
    o, k, cls = op.opcode, op.offset, op.cls
    if cls == "store" and op.ea is not None and op.width == 2 and op.sfr is None:
        if o == 0xA3:
            regs[f"mem{op.ea:04X}"] = regs["AW"]
        elif o == 0x89 and op.modrm:
            regs[f"mem{op.ea:04X}"] = regs[REG16[(code[k + 1] >> 3) & 7]]
    elif cls == "store_imm" and o == 0xC7 and op.ea is not None and op.sfr is None:
        regs[f"mem{op.ea:04X}"] = int.from_bytes(code[k + op.length - 2:k + op.length], "little")
    elif cls in ("call_mem", "call_far_mem", "brk"):
        regs["SP"] = (regs["SP"] - {"call_mem": 2, "call_far_mem": 4, "brk": 6}[cls]) & 0xFFFF
        regs[f"ret{regs['SP']:04X}"] = k + op.length
    elif cls == "reti":
        regs["SP"] = (regs["SP"] + 6) & 0xFFFF


def _execute_wp78(op: Op, code: bytes, regs: dict):
    """(WP78, F32, F33) the register effects of the 0F page and the register miscellany that a
    later form's addresses, counts or ports can read: INC / DEC r16 and r8, CVTBW / CVTWL,
    CVTBD / CVTDB, the signed register multiply and divide and the immediate multiply (DW:AW,
    AW), the bit field's offset register and IX / IY (the walk's rule, normalize.py: offset
    (o + w + 1) & 15, the pointer + 2 when o + w + 1 passes 15), EXT's AW. The adjusts and the
    flag forms change nothing the timing reads; the bit ops and the rotates write AL / AW / DL
    or memory, whose values no address, count or port depends on."""
    o, k, cls = op.opcode, op.offset, op.cls
    if cls == "incdec":
        d = -1 if (o & 8 if o != 0xFE else (code[k + 1] >> 3) & 1) else 1
        if o == 0xFE:
            i = code[k + 1] & 7
            name, sh = REG8[i]
            _set8(regs, i, ((regs[name] >> sh) + d) & 0xFF)
        else:
            r = REG16[o & 7]
            regs[r] = (regs[r] + d) & 0xFFFF
    elif cls == "extend":
        al = regs["AW"] & 0xFF
        regs["AW"] = al | (0xFF00 if al & 0x80 else 0)
    elif cls == "extend_w":
        regs["DW"] = 0xFFFF if regs["AW"] & 0x8000 else 0
    elif cls == "convert":
        al = regs["AW"] & 0xFF
        regs["AW"] = ((al // 10) << 8) | (al % 10)
    elif cls == "convert_d":
        regs["AW"] = ((regs["AW"] >> 8) * 10 + (regs["AW"] & 0xFF)) & 0xFF
    elif cls in BF_CLASSES:
        offset, width, _, _ = op.bf
        rm = code[k + 2] & 7
        new = (offset & 15) + (width & 15) + 1
        _set8(regs, rm, new & 15)
        if new >= 16:
            p = "IX" if cls == "bf_ext" else "IY"
            regs[p] = (regs[p] + 2) & 0xFFFF
        if cls == "bf_ext":
            regs["AW"] = 0                  # the field (its value is not tracked)
    elif op.signed and op.modrm and cls in ("mul", "div", "mul_imm"):
        m = code[k + 1]
        mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
        if mod != 3:
            return                          # the memory forms as before (no effect modelled)
        sx = lambda v: v - 0x10000 if v & 0x8000 else v
        src = sx(regs[REG16[rm]])
        if cls == "mul_imm":
            imm = (int.from_bytes(code[k + 2:k + 4], "little", signed=True) if o == 0x69
                   else int.from_bytes(code[k + 2:k + 3], "little", signed=True))
            regs[REG16[reg]] = (src * imm) & 0xFFFF
        elif cls == "mul":
            p = sx(regs["AW"]) * src
            regs["AW"], regs["DW"] = p & 0xFFFF, (p >> 16) & 0xFFFF
        elif src:
            n = (regs["DW"] << 16) | regs["AW"]
            n = n - (1 << 32) if n & 0x80000000 else n
            q = abs(n) // abs(src) * (1 if (n < 0) == (src < 0) else -1)
            regs["AW"], regs["DW"] = q & 0xFFFF, (n - q * src) & 0xFFFF


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
    if op.page:
        # (WP78) a 0F-page form: its second opcode byte is taken first, chained to the head
        # (the ModR/M byte and what follows it)
        sub = Op(**{**op.__dict__, "length": op.length - op.page, "page": 0})
        return [("take", op.page, "chain")] + _head(sub, cfg, pre, ea)
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
    if cfg.page_grp == "group" and op.page and op.ea is not None and cfg.page_mem == "group":
        # (WP78) page_grp=group: a 0F memory form (its operation named by the second opcode
        # byte, as a group form's by the reg field) takes its class's group setup, and with
        # the bit index in CL its cl clocks as part of it (as grpcl for SHL r/m,CL)
        grp = True
        if op.cl_count:
            cl = cfg.c(gcls, "cl")
            n += cl
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
    if cls in WP88_CLASSES:
        return _wp88_steps(op, cfg, c, ea)
    if cls in WP91_CLASSES:
        return _wp91_steps(op, cfg, c, ea)
    if cls in BASE_CLASS or cls in BCD_CLASSES or cls in BF_CLASSES:
        return _wp78_steps(op, cfg, c, ea)
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
            # (WP78, F33) the signed register form (F7 /5 MUL, /7 DIV) runs the class's sexec
            # where it has one (a format property, as smexec for the memory form)
            ex = c("sexec") if op.signed and "sexec" in cfg.cost.get(cls, {}) else c("exec")
            return [("clocks", c("pre")), ("take", rest), ("clocks", ex)]
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
        shift = op.shift and cfg.rmw_shift == "shift"
        if shift:
            # (WP99) shift_mem_imm=rmw_imm: the memory shift by imm8 (its count byte this
            # class's immediate): the ALU step adds the shift unit's clocks (shift_imm.exec,
            # per_shift_count per count beyond the first) and the class's sexec
            alu += (cfg.c("shift_imm", "exec") + cfg.per_shift_count * (op.count - 1)
                    + c("sexec"))
        if cfg.rmw_imm_issue == "rmw" and cfg.rmw_write_issue == "immediate":
            alu, setup = 0, max(alu, setup)     # posted at the start of the ALU step
        if op.nowrite:
            # grp_read: a form that does not write (81 /7) keeps the write's bus slot
            write = [("data", "nowrite", op.ea, op.width, setup)]
        elif shift and not alu:
            # (WP99) the write posted at the start of the ALU step: its first sthru setup clocks
            # count through a fetch in flight, the rest (the shift's) only with none
            # (F38-out-shb-shl_m_imm4-pO-w0: R91, fetch 94-96, W112 = the fetch's end + 16;
            # pE-w0, no fetch: R90, W110 = the read's end + 18)
            write = [("data", "write", op.ea, op.width, setup, max(0, setup - c("sthru")))]
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
        # (WP72) cond_gap=own: a taken form with a condition field flushes cfgap clocks after
        # the last fetch's end (its flag test keeps the flush's quiet window open), not fgap
        flush = (("flush", op.target, "cfgap") if cfg.cond_gap == "own" and op.cond
                 else ("flush", op.target))
        return head + [("clocks", c("exec")), flush, ("clocks", c("post"))]
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


def _wp88_steps(op: Op, cfg, c, ea) -> list[tuple]:
    """(WP88, F35, F36) the templates of the classes F35 and F36 add, each its base class's
    (BASE_CLASS) with its own integers.

    bcwz (BCWZ) and dbnz_z (DBNZNE / DBNZE, base dbnz): the short transfer's template (pre, the
    displacement's take; taken: exec, the flush, post; not taken: the decide step, then nexec,
    or for dbnz_z not taken on its Z test zexec). The head of the others: a register form's
    ModR/M byte taken on the start, then its pre clocks; a far form's pre clocks, its offset
    word (chained: no take sync), spre clocks, its segment word. br_reg (BR r16) and
    branch_far (BR far, base branch_near): the head, exec, the flush, post. call_reg (CALL
    r16) and call_far (CALL far, base call): the head, wpre clocks, then in call_order the
    stack writes (call_far: PS with setup, then the return offset with wsetup, all fetch-free)
    and the exec clocks with the flush, post. ret_imm (RET imm16), ret_far (RET far),
    ret_far_imm (RET far imm16) (base ret): pre, the stack read of the return offset (setup;
    with an immediate posted, the immediate taken once the read is on the bus), the far forms
    the segment's read (wsetup), exec, the flush, post. load_ptr (LES / LDS, base load): the
    load's head and its read, the segment word's read (wsetup), exec. pop_psw (POP PSW, base
    pop): POP r16's template with its own integers. Both hold fetch requests phold clocks from
    the last read's data. (test_reg, TEST r,r, runs the register forms' template,
    _wp78_steps.)"""
    cls, rest = op.cls, op.length - 1
    if cls in ("bcwz", "dbnz_z"):
        head = [("clocks", c("pre")), ("take", rest)]
        if op.target is None:
            decide = [("decide",)] if cfg.untaken == "wait" else []
            # dbnz_z: not taken on the Z test, zexec clocks; on the count, nexec
            return head + decide + [("clocks", c("zexec" if op.zfail else "nexec"))]
        return head + [("clocks", c("exec")), ("flush", op.target), ("clocks", c("post"))]
    # a far form: pre clocks, the offset word, spre clocks, the segment word; a register form:
    # the ModR/M byte, then the pre clocks
    head = ([("clocks", c("pre")), ("take", 2, "chain")]
            + ([("clocks", c("spre"))] if c("spre") else []) + [("take", 2)] if rest == 4
            else [("take", rest), ("clocks", c("pre"))])
    if cls in ("br_reg", "branch_far"):
        return head + [("clocks", c("exec")), ("flush", op.target), ("clocks", c("post"))]
    if cls in ("call_reg", "call_far"):
        sp = op.stack[1]
        # wpre: EU clocks between the operand take and the first write's post
        write = ([("clocks", c("wpre"))] if c("wpre") else []) + [
            ("data", "write", sp, 2, c("setup"))]
        if cls == "call_far":
            write.append(("data", "write", (sp - 2) & 0xFFFF, 2, c("wsetup"), c("wsetup")))
        flush = [("clocks", c("exec")), ("flush", op.target)]
        body = write + flush if cfg.call_order == "write_first" else flush + write
        return head + body + [("clocks", c("post"))]
    if cls in ("ret_imm", "ret_far", "ret_far_imm"):
        sp = op.stack[0]
        seq = [("clocks", c("pre"))]
        if op.imm_bytes:
            # the stack read posted, the immediate taken once it is on the bus (chained: no take
            # sync), as a memory form's immediate under imm_order=after_issue
            # (WP88) ret_imm_hold=word: an immediate whose last byte is the even half of its
            # word (the next opcode the odd half) raises no fetch request for mhold clocks from
            # its take
            hold = ([("fetch_hold", c("mhold"))] if cfg.ret_imm_hold == "word" and op.half_word
                    else [])
            seq += [("post", "read", sp, 2, c("setup")), ("issued",),
                    ("take", op.imm_bytes, "chain")] + hold + [("wait",)]
        else:
            seq.append(("data", "read", sp, 2, c("setup")))
        if cls != "ret_imm":
            seq.append(("data", "read", (sp + 2) & 0xFFFF, 2, c("wsetup"), c("wsetup")))
        return seq + [("clocks", c("exec")), ("flush", op.target), ("clocks", c("post"))]
    # phold: no fetch request for phold clocks from the last read's data (LES / LDS: the
    # segment word; POP PSW: the PSW), the register file's load
    hold = [("fetch_hold", c("phold"))] if c("phold") else []
    if cls == "load_ptr":
        return _head(op, cfg, c("pre"), ea) + [("data", "read", op.ea, 2, 0),
                                                ("data", "read", (op.ea + 2) & 0xFFFF, 2,
                                                 c("wsetup"), c("wsetup"))] + hold + [
                                                ("clocks", cfg.read_use_latency),
                                                ("clocks", c("exec"))]
    if cls == "pop_psw":
        return [("data", "read", op.stack[0], 2, c("setup"))] + hold + [("clocks", c("exec"))]
    raise ValueError(cls)


def _wp91_steps(op: Op, cfg, c, ea) -> list[tuple]:
    """(WP91, F37) the memory-indirect transfers, BRK and RETI, each its base class's
    (BASE_CLASS) structure with its own integers, the cycles in silicon's order
    (normalize.VECTORED_ACCESSES).

    call_mem (CALL near [m]), br_mem (BR near [m]), call_far_mem (CALL far [m]) and
    branch_far_mem (BR far [m]): a memory form's head (_head: pre, the ModR/M byte, the EA, any
    displacement, as the load's; xfer_mem_head=lead: the ModR/M byte taken on the start), the
    pointer's offset word read at the EA (a group form's: its grp / grp_free group setup,
    _group; xfer_mem_disp=grp: a d16 taken as grp_disp's, eu.py), the far forms its segment
    word at EA + 2 (rwsetup, every clock fetch-free: LES / LDS's second read); BR: exec, the
    flush, post (BR near's); CALL: in call_order the stack writes (call_mem the return offset
    with setup; call_far_mem PS with setup, then the return offset with wsetup, all fetch-free:
    CALL far's) and the exec clocks with the flush, post (CALL near's).
    brk (BRK 3 / BRK imm8, base call): pre, the type byte's take (BRK imm8, chained), then
    twice: the vector word's read posted (the offset at 4n with rsetup, its last rfree clocks
    fetch-free; the segment at 4n + 2 with vsetup, all fetch-free), rexec EU clocks from its
    issue, the read's data, a push (PSW, then PS) with setup; then the return offset's push
    (wsetup, fetch-free), exec, the flush, post.
    The push after a read is the later of rexec clocks after the read's issue and its data
    (silicon: 6 / 6 / 7 clocks issue to issue at 0 / 1 / 2 waits).
    reti (RETI, base ret): pre, the return offset's read at SP (setup), PS's at SP + 2 and PSW's
    at SP + 4 (wsetup each, fetch-free: RET far's cadence), exec, the flush, post."""
    cls, rest = op.cls, op.length - 1
    tail = [("clocks", c("exec")), ("flush", op.target), ("clocks", c("post"))]
    if cls == "reti":
        sp = op.stack[0]
        return [("clocks", c("pre")), ("data", "read", sp, 2, c("setup"))] + [
            ("data", "read", (sp + 2 * j) & 0xFFFF, 2, c("wsetup"), c("wsetup"))
            for j in (1, 2)] + tail
    if cls == "brk":
        sp = op.stack[1]
        # BRK imm8's type byte: a chained take (no take sync; with a sync 48 of F37's 72 brk
        # runs, every BRK imm8 cell with a fetch after its start a clock or more late)
        seq = [("clocks", c("pre"))] + ([("take", rest, "chain")] if rest else [])
        for j, (setup, free) in enumerate(((c("rsetup"), c("rfree")),
                                           (c("vsetup"), c("vsetup")))):
            seq += [("post", "read", (op.vec + 2 * j) & 0xFFFF, 2, setup, free), ("issued",),
                    ("clocks", c("rexec")), ("wait",),
                    ("data", "write", (sp - 2 * j) & 0xFFFF, 2, c("setup"))]
        return seq + [("data", "write", (sp - 4) & 0xFFFF, 2, c("wsetup"), c("wsetup"))] + tail
    seq = _head(op, cfg, c("pre"), ea)
    if cfg.xfer_mem_head == "lead" and len(seq) > 1 and seq[1][:2] == ("take", 1):
        # xfer_mem_head=lead: the ModR/M byte taken by the decoder on the start (as
        # mem_order=lead's), then the pre clocks, the EA and any displacement as split's
        seq = [("take", 1, "lead"), seq[0]] + seq[2:]
    # the pointer's read: a group form's (FF /2-/5), its grp / grp_free group setup (_group)
    seq = seq + [("data", "read", op.ea, 2, 0)]
    if cls in ("call_far_mem", "branch_far_mem"):
        seq.append(("data", "read", (op.ea + 2) & 0xFFFF, 2, c("rwsetup"), c("rwsetup")))
    if cls in ("br_mem", "branch_far_mem"):
        return seq + tail
    sp = op.stack[1]
    write = [("data", "write", sp, 2, c("setup"))]
    if cls == "call_far_mem":
        write.append(("data", "write", (sp - 2) & 0xFFFF, 2, c("wsetup"), c("wsetup")))
    flush = [("clocks", c("exec")), ("flush", op.target)]
    body = write + flush if cfg.call_order == "write_first" else flush + write
    return seq + body + [("clocks", c("post"))]


def _wp78_steps(op: Op, cfg, c, ea) -> list[tuple]:
    """(WP78, F32, F33) the templates of the 0F page and the register miscellany, by class.

    The register forms (BASE_CLASS reg): pre clocks (pre0 for a form without operand bytes:
    INC / DEC r16, the adjusts, the extends, the flag forms), the operand take (a 0F form's
    second opcode byte, ModR/M byte and any immediate), exec clocks; bit1, the bit ops on a
    register, cl more exec clocks when the bit index is CL (the index from the register file;
    the imm form takes one more byte instead). convert / convert_d (CVTBD / CVTDB, base imm):
    the imm class's template, the constant second byte an immediate. bit1_test (TEST1 r/m,
    base load_alu) and bit1_rmw / bit1_clr / rol4_mem / ror4_mem (base rmw): the load_alu and
    rmw templates with the class's own integers, the CL index's cl clocks before the read.
    mul_imm (MUL r16,r/m,imm, base mul): register: pre, the take, exec; memory: the memory
    head, the read posted and the immediate taken once it is on the bus (as imm_order
    after_issue), mexec clocks. The BCD strings (bcd4s ADD4S / SUB4S, bcd4s_cmp CMP4S): pre,
    the second opcode byte's take, then per byte pair a byte read at IX + i (setup first, later
    pairs loop), a byte read at IY + i (mid) and, bcd4s only, the result written back at IY + i
    (wmid), each a data step the EU waits on; exec clocks after the last. The bit fields
    (bf_ext EXT, bf_ins INS): pre, the take, the word read at IX (EXT) / IY (INS) with setup;
    EXT: crossing into the next word, the next word's read (xsetup), then the cost formula's
    clocks less span (xspan crossing); INS: within one word the formula's clocks less span,
    then the write back (wsetup) and post; crossing, the first word written back (xwsetup), the
    next word read (xrsetup), the formula's clocks less xspan, its write back (wsetup), post.
    """
    cls, rest = op.cls, op.length - 1
    base = BASE_CLASS.get(cls)
    if op.page and cfg.page_take == "own" and op.ea is None and (base == "reg"
                                                                 or cls in BF_CLASSES):
        # (WP81) page_take=own: a 0F register form's second opcode byte is taken (and leaves
        # the queue) on its start clock as a take of its own, chained to the rest, as the
        # memory forms' head takes it (_head); the template's own take is the rest
        sub = Op(**{**op.__dict__, "length": op.length - op.page, "page": 0})
        return [("take", op.page, "chain")] + _wp78_steps(sub, cfg, c, ea)
    if base == "reg":
        pre = c("pre") if rest else (c("pre0") if "pre0" in cfg.cost.get(cls, {}) else c("pre"))
        return [("clocks", pre), ("take", rest),
                ("clocks", c("exec") + (c("cl") if op.cl_count else 0))]
    if base == "imm":
        return [("clocks", c("pre")), ("take", op.imm_bytes), ("clocks", c("exec"))]
    fixed = cfg.page_mem == "fixed" and op.page and op.ea is not None
    cl = ([("clocks", c("cl"))] if op.cl_count and c("cl")
          and not (cfg.page_grp == "group" and op.ea is not None) and not fixed else [])
    if fixed and base in ("load_alu", "rmw"):
        # (WP81) page_mem=fixed: the read's setup is the class's fsetup (and with the index in
        # CL its cl) clocks, all fetch-free, counted back from its post to the end of the last
        # fetch the form did not let through (eu.py, arbiter.py); no group setup (_group)
        fs = c("fsetup") + (c("cl") if op.cl_count else 0)
        seq = _wp78_mem(op, cfg, c, ea, base, [])
        k = next(i for i, st in enumerate(seq) if st[0] in ("data", "post") and st[1] == "read")
        seq[k] = seq[k][:4] + (fs, fs)
        return seq
    if base in ("load_alu", "rmw"):
        return _wp78_mem(op, cfg, c, ea, base, cl)
    if base == "mul":
        if op.ea is None:
            return [("clocks", c("pre")), ("take", rest), ("clocks", c("exec"))]
        hold = ([("fetch_hold", c("mhold"))] if cfg.mul_imm_hold == "word" and op.half_word
                else [])
        if cfg.mul_imm_read == "imm":
            # (WP81) mul_imm_read=imm: the read is posted before the immediate's take but
            # issues only rsetup clocks and a clock per immediate byte after its post, the
            # immediate taken while it waits (imm_order=after_post's order); (WP81)
            # mul_imm_hold=word: with the immediate's word half-taken (the next opcode its
            # second byte), no fetch request for mhold clocks from the post
            return (_head(op, cfg, c("pre"), ea)
                    + [("post", "read", op.ea, op.width, c("rsetup") + op.imm_bytes)] + hold
                    + [("take", op.imm_bytes, "chain"), ("wait",), ("clocks", c("mexec"))])
        return _head(op, cfg, c("pre"), ea) + _imm_read(op, cfg, c) + hold + [("clocks", c("mexec"))]
    if cls in BCD_CLASSES:
        seq = [("clocks", c("pre")), ("take", rest)]
        for i in range(op.n):
            seq += [("data", "read", (op.ix + i) & 0xFFFF, 1, c("first") if i == 0 else c("loop")),
                    ("data", "read", (op.iy + i) & 0xFFFF, 1, c("mid"))]
            if cls == "bcd4s":
                seq.append(("data", "write", (op.iy + i) & 0xFFFF, 1, c("wmid")))
        return seq + [("clocks", c("exec"))]
    offset, width, cross, cost = op.bf
    first = op.ix if cls == "bf_ext" else op.iy
    # (WP81) bf_read=fixed: the first word's read is issued fsetup clocks (and one more per
    # immediate byte: the imm4 width) after the last fetch's end, every one fetch-free (eu.py)
    st = c("fsetup") + op.imm_bytes if cfg.bf_read == "fixed" else c("setup")
    # (WP94) bf_imm_hold=word: the width byte the even half of its word (the next opcode the
    # odd half): no fetch request from the width byte's take to hrel clocks before the end
    hold = cfg.bf_imm_hold == "word" and op.imm_bytes and op.half_word
    if op.imm_bytes:
        # the imm4 width form: the word's read is posted after the ModR/M byte and the width
        # byte taken while it waits (as a memory form's immediate under imm_order=after_post)
        seq = [("clocks", c("pre")), ("take", rest - op.imm_bytes),
               ("post", "read", first, 2, st)]
        seq += ([("fetch_hold", BF_TAKE_HOLD)] if hold else []) + [
            ("take", op.imm_bytes, "chain"), ("wait",)]
    else:
        seq = [("clocks", c("pre")), ("take", rest), ("data", "read", first, 2, st)]
    if cls == "bf_ext":
        if cross:
            seq.append(("data", "read", (op.ix + 2) & 0xFFFF, 2, c("xsetup")))
        tail = max(0, cost - c("xspan" if cross else "span"))
    else:
        if cross:
            seq += [("data", "write", op.iy, 2, c("xwsetup")),
                    ("data", "read", (op.iy + 2) & 0xFFFF, 2, c("xrsetup")),
                    ("clocks", max(0, cost - c("xspan"))),
                    ("data", "write", (op.iy + 2) & 0xFFFF, 2, c("wsetup"))]
        else:
            seq += [("clocks", max(0, cost - c("span"))),
                    ("data", "write", op.iy, 2, c("wsetup"))]
        tail = c("post")
    if hold:
        # (WP94) the hold ends hrel clocks before the form's last clock (at the tail's start
        # when the tail is shorter): a fetch_hold of 0 clocks lifts it
        r = min(c("hrel"), tail)
        return seq + [("clocks", tail - r), ("fetch_hold", 0), ("clocks", r)]
    return seq + [("clocks", tail)]


def _wp78_mem(op: Op, cfg, c, ea, base, cl) -> list[tuple]:
    """(WP78) the 0F memory forms on the load_alu (TEST1) and rmw shapes, the CL index's cl
    clocks (cl: the step, or none) before the read."""
    head = _head(op, cfg, c("pre"), ea) + cl
    if base == "load_alu":
        if op.imm_bytes and cfg.imm_order != "with_addr":
            return head + _imm_read(op, cfg, c) + [("clocks", c("exec"))]
        return head + [("data", "read", op.ea, op.width, 0), ("clocks", cfg.read_use_latency),
                       ("clocks", c("exec"))]
    if op.imm_bytes and cfg.imm_order != "with_addr":
        read = head + _imm_read(op, cfg, c)
    else:
        read = head + [("data", "read", op.ea, op.width, 0),
                       ("clocks", cfg.read_use_latency)]
    if cfg.rmw_write_issue == "immediate":
        return read + [("data", "write", op.ea, op.width, max(c("alu"), c("setup"))),
                       ("clocks", c("post"))]
    return read + [("clocks", c("alu")), ("data", "write", op.ea, op.width, c("setup")),
                   ("clocks", c("post"))]


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
        # (WP95) str_single_wb=wb: the exec's last uwb clocks are a write-back (eu.py)
        ex = c("exec") - (c("uwb") if cfg.str_single_wb == "wb" else 0)
        return ([("clocks", c("pre"))] + element(0, c("setup"), last=cfg.str_last == "all")
                + [("clocks", ex)])
    seq = [("take", 1) if cfg.str_take == "sync" else ("take", 1, "chain")]
    if cfg.str_take == "quiet":
        seq.append(("quiet",))
    seq.append(("nowait" if cfg.str_setup == "nowait" else "clocks", c("rpre")))
    if not op.n:
        if cfg.str_fetch == "hold":     # (WP76) the aborted start's request, zfetch clocks in
            seq.append(("fetch_release", c("zfetch"), "raise"))
        return seq + [("clocks", c("zexit"))]
    if cfg.str_fetch == "hold":
        seq.append(("fetch_release", None))     # (WP76) str_fetch=hold: none from here
    for i in range(op.n):
        seq += element(i, c("first") if i == 0 else loop(i),
                       last=i == op.n - 1 and not op.cond)
    if cfg.str_overrun == "read" and op.cls in STRING_COMPARES:
        seq += element(op.n, loop(op.n), kinds=("read",))
    if cfg.str_fetch == "hold":
        # (WP76) str_fetch=hold: fetch requests again xfetch clocks after the last cycle
        seq.append(("fetch_release", c("xfetch")))
    if cfg.str_split == "floor" and (len(cyc) > 1 or cyc[0][0] != "read"):
        # (WP76) str_split=floor: when the stream's last cycle was split (an odd word), the exit
        # starts no earlier than xsplit clocks after its second half's issue; not after an
        # element whose one cycle is a read (LDM, CMPM: the EU waits for the data)
        seq.append(("split_floor", c("xsplit")))
    exit_ = c("cexit" if op.cond else "rexit")
    if cfg.str_exit == "wb":
        exit_ -= c("xwb")       # (WP76) str_exit=wb: the exit's last xwb clocks are a write-back
    return seq + [("clocks", exit_)]
