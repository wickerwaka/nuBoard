"""Form catalog (plan, "Form catalog"): limited, class-complete. Pure data.

Every form is a fixed byte string. reads / writes count memory data cycles
for an aligned operand (an odd word operand may split each into two); io
counts I/O cycles.
"""

from __future__ import annotations

from dataclasses import dataclass

CLASSES = ("reg", "imm", "prefix", "load", "load_alu", "store", "store_imm", "rmw",
           "rmw_imm", "push_mem", "pop_mem", "push", "pop", "out", "in", "shift_cl",
           "shift_imm", "mul", "div",
           "branch", "call", "lea",    # (WP49) F23 control flow, F25 EA without a bus cycle
           # (WP55) F23 by encoding format: a 1-byte / 2-byte displacement, the count, the return
           "branch_short", "branch_near", "dbnz", "ret",
           # (WP52) F25 the stack frame and the segment registers
           "xlat", "load_seg", "push_imm", "push_seg", "pop_seg", "push_r", "pop_r", "prepare",
           "dispose",
           # (WP66) F24 the string forms, one class per operation (block move, block compare,
           # store, load, compare with AW, port to memory, memory to port)
           "str_move", "str_cmp", "str_store", "str_load", "str_scan", "str_in", "str_out",
           # (WP74) F32 the 0F page: the bit ops on a register, a memory test, a memory
           # read-modify-write; the packed BCD strings (ADD4S / SUB4S, CMP4S); the digit
           # rotates on a register and in memory; the bit fields (EXT reads DS0:IX, INS writes
           # DS1:IY). (WP78) one class per cost the facts tell apart: CLR1 in memory (a clock
           # longer than SET1 / NOT1 between its read and write), ROL4 / ROR4 (ROR4 4 clocks
           # longer, in both forms)
           "bit1", "bit1_test", "bit1_rmw", "bit1_clr", "bcd4s", "bcd4s_cmp", "rol4", "ror4",
           "rol4_mem", "ror4_mem", "bf_ext", "bf_ins",
           # (WP74) F33 the register miscellany: INC / DEC on a register, the adjusts, the
           # conversions, the sign extensions, the flag forms, the immediate multiply. (WP78)
           # one class per cost: ADJ4A / ADJ4S (adjust) and ADJBA / ADJBS (adjust_b), CVTBD
           # (convert) and CVTDB (convert_d), CVTBW (extend) and CVTWL (extend_w), CLC STC CMC
           # CLD STD (flag), CLI (flag_di), STI (flag_ei)
           "incdec", "adjust", "adjust_b", "convert", "convert_d", "extend", "extend_w", "flag",
           "flag_di", "flag_ei", "mul_imm")
# Classes whose cycles are stack words (normalize.expected_accesses walks SP through them)
STACK_CLASSES = ("push", "pop", "call", "push_imm", "push_seg", "pop_seg", "push_r", "pop_r",
                 "prepare", "dispose", "ret")
MODE_CLASSES = ("base", "base_index", "disp", "base_disp", "base_index_disp", "direct")

# Register and EA knob values (plan, "Registers from the prelude").
DEFAULT_REGS = {"AW": 0x1234, "BW": 0x0800, "CW": 0x0000, "DW": 0x5678, "SP": 0x0F00,
                "BP": 0x0A00, "IX": 0x0100, "IY": 0x0180, "DS0": 0x0000, "DS1": 0x0000,
                "SS": 0x0000}
BW_ODD = 0x0801
D8 = 0x10
D16 = 0x0200
DIRECT = 0x0C00
IMM16 = 0x1234
IO_PORT = 0x40
SHL_IMM_COUNT = 4
SHL_CL_COUNTS = (0, 1, 2, 4, 8, 16, 31)


@dataclass(frozen=True)
class Mode:
    name: str          # filesystem-safe label, e.g. "bw_ix_d8"
    mod: int
    rm: int
    disp: bytes
    mode_class: str
    ea: int            # offset with the default registers
    uses_bw: bool      # [BW] or [BW+d8]: eligible for the odd-alignment knob


_RM = [  # (label, base regs, class without/with displacement)
    ("bw_ix", ("BW", "IX"), "base_index", "base_index_disp"),
    ("bw_iy", ("BW", "IY"), "base_index", "base_index_disp"),
    ("bp_ix", ("BP", "IX"), "base_index", "base_index_disp"),
    ("bp_iy", ("BP", "IY"), "base_index", "base_index_disp"),
    ("ix", ("IX",), "base", "base_disp"),
    ("iy", ("IY",), "base", "base_disp"),
    ("bp", ("BP",), "base", "base_disp"),
    ("bw", ("BW",), "base", "base_disp"),
]


def _modes() -> list[Mode]:
    modes = []
    for mod, disp, suffix in ((0, b"", ""), (1, bytes([D8]), "_d8"),
                              (2, D16.to_bytes(2, "little"), "_d16")):
        for rm, (label, regs, plain, displaced) in enumerate(_RM):
            if mod == 0 and rm == 6:
                modes.append(Mode("dir", 0, 6, DIRECT.to_bytes(2, "little"), "direct",
                                  DIRECT, False))
                continue
            ea = sum(DEFAULT_REGS[r] for r in regs) + int.from_bytes(disp or b"\0", "little")
            modes.append(Mode(label + suffix, mod, rm, disp, displaced if disp else plain,
                              ea & 0xFFFF, label == "bw" and mod in (0, 1)))
    return modes


MODES = _modes()
MODE = {m.name: m for m in MODES}


def modrm(mode: Mode, reg: int) -> bytes:
    """ModR/M byte plus displacement for a memory mode with the reg field."""
    return bytes([(mode.mod << 6) | ((reg & 7) << 3) | mode.rm]) + mode.disp


@dataclass(frozen=True)
class Form:
    name: str
    cls: str
    code: bytes
    reads: int = 0
    writes: int = 0
    io: int = 0
    width: int | None = None        # data operand width in bytes (memory / I/O)
    mode: str | None = None         # Mode.name for ModR/M memory forms
    mode_class: str | None = None
    ea: int | None = None           # data address with the default registers
    align_ok: bool = False          # odd-word variant via BW=0801h is meaningful
    needs: tuple = ()               # register presets required, as (name, value) pairs
    rfm: int | None = None          # (WP23) the RFM value an internal SFR write stores (no
                                    # external bus cycle: the SFR page is on chip)

    @property
    def length(self) -> int:
        return len(self.code)


IMM = IMM16.to_bytes(2, "little")
_forms: list[Form] = []


def _add(*args, **kw) -> Form:
    form = Form(*args, **kw)
    _forms.append(form)
    return form


def _mem(name, cls, opcode, reg, mode_name, tail=b"", width=2, **kw) -> Form:
    mode = MODE[mode_name]
    return _add(name, cls, bytes(opcode) + modrm(mode, reg) + tail, width=width,
                mode=mode.name, mode_class=mode.mode_class, ea=mode.ea,
                align_ok=mode.uses_bw and width == 2, **kw)


# Register-only, length series.
_add("nop", "reg", bytes([0x90]))
_add("xch_aw_dw", "reg", bytes([0x92]))
_add("mov_aw_dw", "reg", bytes([0x8B, 0xC2]))
_add("add_aw_dw", "reg", bytes([0x03, 0xC2]))
_add("mov_cl_imm", "imm", bytes([0xB1, SHL_IMM_COUNT]))
for _n in SHL_CL_COUNTS:
    _add(f"shl_cl{_n}", "shift_cl", bytes([0xB1, _n, 0xD3, 0xE0]))
_add("shl1", "shift_imm", bytes([0xD1, 0xE0]))
_add("mulu_dw", "mul", bytes([0xF7, 0xE2]))
_add("mov_aw_imm", "imm", bytes([0xB8]) + IMM)
_add("add_aw_imm", "imm", bytes([0x05]) + IMM)
_add(f"shl_imm{SHL_IMM_COUNT}", "shift_imm", bytes([0xC1, 0xE0, SHL_IMM_COUNT]))
_add("add_dw_imm", "imm", bytes([0x81, 0xC2]) + IMM)
_add("pfx_nop", "prefix", bytes([0x26, 0x90]))
_add("pfx_mov_aw_dw", "prefix", bytes([0x26, 0x8B, 0xC2]))
_add("pfx_mov_aw_imm", "prefix", bytes([0x26, 0xB8]) + IMM)
_add("pfx2_mov_aw_imm", "prefix", bytes([0x26, 0x2E, 0xB8]) + IMM)
_add("pfx3_mov_aw_imm", "prefix", bytes([0x26, 0x2E, 0x36, 0xB8]) + IMM)

# Loads: MOV AW,r/m16 in all 24 memory modes; short direct; byte load.
for _m in MODES:
    _mem(f"ld_{_m.name}", "load", [0x8B], 0, _m.name, reads=1)
_add("ld_acc_dir", "load", bytes([0xA1]) + DIRECT.to_bytes(2, "little"), reads=1, width=2,
     mode_class="direct", ea=DIRECT)
_mem("ldb_bw", "load", [0x8A], 0, "bw", width=1, reads=1)

# Load + ALU.
_mem("add_aw_m", "load_alu", [0x03], 0, "bw", reads=1)
_mem("cmp_aw_m", "load_alu", [0x3B], 0, "bw", reads=1)
_mem("test_m_aw", "load_alu", [0x85], 0, "bw", reads=1)
_mem("cmp_m_imm", "load_alu", [0x81], 7, "bw", IMM, reads=1)
# MULU [BW] is listed with load+ALU but its EU class is mul.
_mem("mulu_m", "mul", [0xF7], 4, "bw", reads=1)

# Stores.
_mem("st_bw", "store", [0x89], 0, "bw", writes=1)
_mem("stb_bw", "store", [0x88], 0, "bw", width=1, writes=1)
_add("st_acc_dir", "store", bytes([0xA3]) + DIRECT.to_bytes(2, "little"), writes=1, width=2,
     mode_class="direct", ea=DIRECT)
_mem("st_imm_bw", "store_imm", [0xC7], 0, "bw", IMM, writes=1)
_mem("st_imm_bw_d16", "store_imm", [0xC7], 0, "bw_d16", IMM, writes=1)

# Read-modify-write, same address.
_mem("add_m_aw", "rmw", [0x01], 0, "bw", reads=1, writes=1)
_mem("inc_m", "rmw", [0xFF], 0, "bw", reads=1, writes=1)
_mem("not_m", "rmw", [0xF7], 2, "bw", reads=1, writes=1)
_mem("shl_m1", "rmw", [0xD1], 4, "bw", reads=1, writes=1)
_mem("add_m_imm", "rmw_imm", [0x81], 0, "bw", IMM, reads=1, writes=1)
_mem("add_m_imm_d16", "rmw_imm", [0x81], 0, "bw_d16", IMM, reads=1, writes=1)
_mem("xch_m_aw", "rmw", [0x87], 0, "bw", reads=1, writes=1)

# Read A then write B; stack only.
_mem("push_m", "push_mem", [0xFF], 6, "bw", reads=1, writes=1)
_mem("pop_m", "pop_mem", [0x8F], 0, "bw", reads=1, writes=1)
_add("push_aw", "push", bytes([0x50]), writes=1, width=2, ea=DEFAULT_REGS["SP"] - 2)
_add("pop_aw", "pop", bytes([0x58]), reads=1, width=2, ea=DEFAULT_REGS["SP"])

# I/O (ports 40h; the DW forms need DW=0040h).
_add("out_imm_al", "out", bytes([0xE6, IO_PORT]), io=1, width=1)
_add("out_imm_aw", "out", bytes([0xE7, IO_PORT]), io=1, width=2)
_add("in_al_imm", "in", bytes([0xE4, IO_PORT]), io=1, width=1)
_add("in_aw_imm", "in", bytes([0xE5, IO_PORT]), io=1, width=2)
_add("out_dw_al", "out", bytes([0xEF]), io=1, width=1, needs=(("DW", IO_PORT),))
_add("in_al_dw", "in", bytes([0xEC]), io=1, width=1, needs=(("DW", IO_PORT),))

FORMS: dict[str, Form] = {}
for _f in _forms:
    if _f.name in FORMS:
        raise RuntimeError(f"duplicate form {_f.name}")
    if _f.cls not in CLASSES:
        raise RuntimeError(f"{_f.name}: unknown class {_f.cls}")
    FORMS[_f.name] = _f

REGISTER_ONLY = [f.name for f in _forms if f.reads == f.writes == f.io == 0]
LOADS_BY_MODE = [f"ld_{m.name}" for m in MODES]
LOAD_ALU = ["add_aw_m", "cmp_aw_m", "test_m_aw", "cmp_m_imm", "mulu_m"]
STORES = ["st_bw", "stb_bw", "st_acc_dir", "st_imm_bw", "st_imm_bw_d16"]
RMW = ["add_m_aw", "inc_m", "not_m", "shl_m1", "add_m_imm", "add_m_imm_d16", "xch_m_aw"]
PUSH_POP_MEM = ["push_m", "pop_m"]
STACK = ["push_aw", "pop_aw"]
IO = ["out_imm_al", "out_imm_aw", "in_al_imm", "in_aw_imm", "out_dw_al", "in_al_dw"]

# A bare segment prefix (ES:) for the F9 release series. Added after the lists
# above so the F3 register-only sweep does not pick it up.
FORMS["pfx_es"] = Form("pfx_es", "prefix", bytes([0x26]))

# F10 (OUT DW interlock series): the instructions before an IN/OUT DW form, varying
# which register they write (the port register DW or another) and how (immediate,
# register, read-modify-write, memory load). Added after the lists above so no
# earlier family picks them up. MOV DW,imm16 and ADD DW,imm16 keep DW = IO_PORT so the
# DW forms still address port 40h; MOV DW,AW and MOV DW,[0C00h] change the port (to
# AW, 0 after the long shift, and to the data fill 9090h): the normaliser tracks DW
# through the chain (normalize.expected_accesses).
for _f in (Form("mov_dw_imm", "imm", bytes([0xBA]) + IO_PORT.to_bytes(2, "little")),
           Form("mov_dw_aw", "reg", bytes([0x8B, 0xD0])),
           Form("mov_cw_aw", "reg", bytes([0x8B, 0xC8])),
           # a port in the END's page (FF04h: not the harness's FF00h/FF02h/FF10h)
           Form("mov_dw_ff04", "imm", bytes([0xBA, 0x04, 0xFF])),
           Form("add_dw_imm0", "imm", bytes([0x81, 0xC2, 0x00, 0x00])),
           Form("ld_dw_dir", "load", bytes([0x8B, 0x16]) + DIRECT.to_bytes(2, "little"),
                reads=1, width=2, mode="dir", mode_class="direct", ea=DIRECT)):
    FORMS[_f.name] = _f


# F12 (the F7 companion and the 4-byte register form): ADD AW,imm16 in the group format
# of ADD DW,imm16 (81 /0 with a register operand: opcode, ModR/M, imm16), so the two
# 4-byte forms differ only in the register the ModR/M byte names. Added after the lists
# above so no earlier family picks it up.
FORMS["add_aw_imm81"] = Form("add_aw_imm81", "imm", bytes([0x81, 0xC0]) + IMM)


def form(name: str) -> Form:
    return FORMS[name]


# F13 (the refresh machine's EU side): MOV CL,n ; SHL AW,CL at every count 0..31, the same
# bytes as the shl_cl forms above (B1 nn D3 E0). Added after the lists above so the F3
# register-only sweep does not pick up the new counts.
for _n in range(32):
    if f"shl_cl{_n}" not in FORMS:
        FORMS[f"shl_cl{_n}"] = Form(f"shl_cl{_n}", "shift_cl", bytes([0xB1, _n, 0xD3, 0xE0]))


# F14 (WP19: the TEST/XCH format ladder, the group memory forms, the OUT after a register
# form). The memory forms at [BW] vary one format property at a time against ADD [BW],AW
# (01 07): the direction bit (39 vs 3B), read-only against read-modify-write with a
# register operand (39 vs 01), the group read-only form (F7 /0 TEST [BW],imm16 against
# 85 TEST [BW],AW), XCH's register (87 0F: XCH CW,[BW]; 87 07 is the only XCH AW,[BW]),
# the byte forms (w bit 0), the direct address (mod 00 rm 110). Group memory forms: NEG
# (F7 /3), DIVU (F7 /6: DW:AW = 5678h:0000h after the fence's shift, divided by the 9090h
# fill, quotient 990Ch < 10000h, so no divide trap and a fixed datum), SHL [BW],CL (D3 /4,
# CL = 31 from the fence), MULU AW (F7 E0, the register control of MULU [BW]); SHL AW,8
# (C1 E0 08) next to SHL AW,4. Added after the lists above so no earlier family picks
# them up.
_DIR = DIRECT.to_bytes(2, "little")
for _f in (Form("cmp_m_aw", "load_alu", bytes([0x39, 0x07]), reads=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("test_m_imm", "load_alu", bytes([0xF7, 0x07]) + IMM, reads=1, width=2,
                mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("xch_cw_m", "rmw", bytes([0x87, 0x0F]), reads=1, writes=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("neg_m", "rmw", bytes([0xF7, 0x1F]), reads=1, writes=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("test_m_al", "load_alu", bytes([0x84, 0x07]), reads=1, width=1, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"]),
           Form("xch_m_al", "rmw", bytes([0x86, 0x07]), reads=1, writes=1, width=1, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"]),
           Form("add_m_al", "rmw", bytes([0x00, 0x07]), reads=1, writes=1, width=1, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"]),
           Form("cmp_m_al", "load_alu", bytes([0x38, 0x07]), reads=1, width=1, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"]),
           Form("test_dir_aw", "load_alu", bytes([0x85, 0x06]) + _DIR, reads=1, width=2,
                mode="dir", mode_class="direct", ea=DIRECT),
           Form("xch_dir_aw", "rmw", bytes([0x87, 0x06]) + _DIR, reads=1, writes=1, width=2,
                mode="dir", mode_class="direct", ea=DIRECT),
           Form("divu_m", "div", bytes([0xF7, 0x37]), reads=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("shl_m_cl", "rmw", bytes([0xD3, 0x27]), reads=1, writes=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("mulu_aw", "mul", bytes([0xF7, 0xE0])),
           Form("shl_imm8", "shift_imm", bytes([0xC1, 0xE0, 0x08]))):
    if _f.name in FORMS:
        raise RuntimeError(f"duplicate form {_f.name}")
    FORMS[_f.name] = _f


# F15 (WP20: the AND control and the TEST ladder, POP [BW], the k = 2 second instance, the
# OUT-frame remainder). A: the ALU forms of the 00-3F block at [BW] whose operation is
# named by the opcode's bits 5:3 (AND 21/23, OR 09, XOR 33, SUB 29), the group immediate
# forms AND [BW],imm16 (81 /4) and the sign-extended imm8 forms (83 /0, 83 /4), direct
# AND and CMP, and the register-form TEST immediates (A8, A9) as controls. P: POP [BW] in
# other address modes (direct, [BW+10h], [IX] with IX = 0900h so the write stays in the
# data page) and POP CW (59) next to POP AW. O: SHL AW,16 (C1 E0 10) next to SHL AW,4/8.
# Added after the lists above so no earlier family picks them up.
F15_IMM8 = 0x05
F15_IX = 0x0900
_I8 = bytes([F15_IMM8])
for _f in (Form("and_m_aw", "rmw", bytes([0x21, 0x07]), reads=1, writes=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("and_aw_m", "load_alu", bytes([0x23, 0x07]), reads=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("and_m_imm", "rmw_imm", bytes([0x81, 0x27]) + IMM, reads=1, writes=1, width=2,
                mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("or_m_aw", "rmw", bytes([0x09, 0x07]), reads=1, writes=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("xor_aw_m", "load_alu", bytes([0x33, 0x07]), reads=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("sub_m_aw", "rmw", bytes([0x29, 0x07]), reads=1, writes=1, width=2, mode="bw",
                mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("and_dir_aw", "rmw", bytes([0x21, 0x06]) + _DIR, reads=1, writes=1, width=2,
                mode="dir", mode_class="direct", ea=DIRECT),
           Form("cmp_dir_aw", "load_alu", bytes([0x39, 0x06]) + _DIR, reads=1, width=2,
                mode="dir", mode_class="direct", ea=DIRECT),
           Form("test_al_imm", "imm", bytes([0xA8, IMM16 & 0xFF])),
           Form("test_aw_imm", "imm", bytes([0xA9]) + IMM),
           Form("add_m_imm8", "rmw_imm", bytes([0x83, 0x07]) + _I8, reads=1, writes=1, width=2,
                mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("and_m_imm8", "rmw_imm", bytes([0x83, 0x27]) + _I8, reads=1, writes=1, width=2,
                mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("pop_m_dir", "pop_mem", bytes([0x8F, 0x06]) + _DIR, reads=1, writes=1, width=2,
                mode="dir", mode_class="direct", ea=DIRECT),
           Form("pop_m_d8", "pop_mem", bytes([0x8F, 0x47, D8]), reads=1, writes=1, width=2,
                mode="bw_d8", mode_class="base_disp", ea=DEFAULT_REGS["BW"] + D8),
           Form("pop_m_ix", "pop_mem", bytes([0x8F, 0x04]), reads=1, writes=1, width=2,
                mode="ix", mode_class="base", ea=F15_IX, needs=(("IX", F15_IX),)),
           Form("pop_cw", "pop", bytes([0x59]), reads=1, width=2, ea=DEFAULT_REGS["SP"]),
           Form("shl_imm16", "shift_imm", bytes([0xC1, 0xE0, 0x10]))):
    if _f.name in FORMS:
        raise RuntimeError(f"duplicate form {_f.name}")
    FORMS[_f.name] = _f


# F16 (WP21: the reg-field ladder, POP's held fetch, the long register forms after the OUT
# marker, the marker-less shift's count byte). R: every reg value of the D1 shift group on
# [BW] (/0 ROL, /1 ROR, /2 RCL, /3 RCR, /4 SHL, /5 SHR, /7 SAR; /6 is undefined), of the
# F7 group (/0 TEST imm16, /2 NOT, /3 NEG, /4 MULU, /5 MUL, /6 DIVU, /7 DIV) and of FF (/0
# INC, /1 DEC, /6 PUSH), and the byte group's D0 /4 SHL and F6 /4 MULU as width controls.
# MUL [BW] (F7 /5): AW = 0 after the fence, so the product is 0. DIV [BW] (F7 /7) needs
# DW = 0100h: with the fence's DW = 5678h the signed quotient 5678h:0000h / 9090h is out
# of range (a divide trap); 0100h:0000h / 9090h (-28528) = -588 rem 2752, and the second
# instance 0AC0h:FDB4h / 9090h = -6324 (after INC [BW], / 9091h: -588 then -7675), no trap. L: SHL AW,CL
# (D3 E0) with CL set by MOV CL,n (B1 nn) before M0, SHL AW,n (C1 E0 nn) for n = 1, 2;
# DIVU DW cannot run here (DW:AW / DW >= 10000h whenever AW >= 0: always a divide trap),
# so the register divide is DIVU IX (F7 F6) with IX = 9090h: the datum of DIVU [BW].
F16_DIV_DW = 0x0100
F16_DIVU_IX = 0x9090
_BW = dict(width=2, mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True)
_BWB = dict(width=1, mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"])
_f16 = [Form(f"{n}_m1", "rmw", bytes([0xD1, 0x07 | (r << 3)]), reads=1, writes=1, **_BW)
        for n, r in (("rol", 0), ("ror", 1), ("rcl", 2), ("rcr", 3), ("shr", 5), ("sar", 7))]
_f16 += [Form("mul_m", "mul", bytes([0xF7, 0x2F]), reads=1, **_BW),
         Form("div_m", "div", bytes([0xF7, 0x3F]), reads=1, needs=(("DW", F16_DIV_DW),), **_BW),
         Form("dec_m", "rmw", bytes([0xFF, 0x0F]), reads=1, writes=1, **_BW),
         Form("shlb_m1", "rmw", bytes([0xD0, 0x27]), reads=1, writes=1, **_BWB),
         Form("mulub_m", "mul", bytes([0xF6, 0x27]), reads=1, **_BWB),
         Form("shl_aw_cl", "shift_cl", bytes([0xD3, 0xE0])),
         Form("divu_ix", "div", bytes([0xF7, 0xF6]), needs=(("IX", F16_DIVU_IX),))]
_f16 += [Form(f"shl_imm{n}", "shift_imm", bytes([0xC1, 0xE0, n])) for n in (1, 2)]
_f16 += [Form(f"mov_cl{n}", "imm", bytes([0xB1, n])) for n in (1, 2, 8, 16)]
for _f in _f16:
    if _f.name in FORMS:
        raise RuntimeError(f"duplicate form {_f.name}")
    FORMS[_f.name] = _f


# F17 (WP23: the refresh fill phase made observable). RFMON = DS1: MOV byte [0FFE1h],imm8
# (26 C6 06 E1 FF ii) with DS1 = F000h: the store reaches RFM (FFFE1h, the SFR page at
# FFF00h-FFFFFh under the reset IDB FFh) on chip, with no external bus cycle (the prelude's
# own SFR writes leave none in any trace). DS1's prefix is 26h (the assembler's SREG
# DS1 = 0; 3Eh is DS0, which is 0 in every chain, so a 3E form would write linear 0FFE1h
# off chip). imm FCh turns refresh on (RFEN, RFW 3, RFT 0), ECh leaves it off (the
# store's own cost), FDh is RFT 1 (32-clock interval). A store-class form, 6 bytes:
# prefix + C6 06 lo hi imm8. The assembler drops a "DS1:" written before the mnemonic
# (it parses it as a label), so the bytes are given here and checked by test_chains.
F17_DS1 = 0xF000
RFM_ADDR = 0xFFE1
RFM_LINEAR = (F17_DS1 << 4) + RFM_ADDR          # 0FFFE1h
for _v in (0xFC, 0xEC, 0xFD):
    _f = Form(f"rfm_{_v:02x}", "store_imm", bytes([0x26, 0xC6, 0x06]) + RFM_ADDR.to_bytes(2, "little")
              + bytes([_v]), width=1, mode="dir", mode_class="direct", ea=RFM_ADDR,
              needs=(("DS1", F17_DS1),), rfm=_v)
    if _f.name in FORMS:
        raise RuntimeError(f"duplicate form {_f.name}")
    FORMS[_f.name] = _f


# F19 (WP25: the immediate memory forms and the DW I/O forms). I: MOV byte [BW],imm8 (C6 /0,
# one immediate byte), MOV [BW+10h],imm16 (C7 /0 with a one-byte displacement) and CMP
# [BW],imm8 (83 /7, sign-extended: reads, no write) next to the F5 forms C7 07, C7 87 d16,
# 81 /7 and 81 /0. D: the byte and word DW forms not yet in the catalog: OUT DW,AL (EE) and
# IN AW,DW (ED). The catalog's "out_dw_al" is EF, OUT DW,AW (a word I/O cycle on the
# trace, as the END's), so F19 labels the four DW forms by opcode width: EE "outb",
# EF "outw", EC "inb", ED "inw". All need DW = IO_PORT.
F19_IMM8 = 0x34
for _f in (Form("st_imm8_bw", "store_imm", bytes([0xC6, 0x07, F19_IMM8]), writes=1, width=1,
                mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"]),
           Form("st_imm_bw_d8", "store_imm", bytes([0xC7, 0x47, D8]) + IMM, writes=1, width=2,
                mode="bw_d8", mode_class="base_disp", ea=DEFAULT_REGS["BW"] + D8,
                align_ok=True),
           Form("cmp_m_imm8", "load_alu", bytes([0x83, 0x3F, F15_IMM8]), reads=1, width=2,
                mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"], align_ok=True),
           Form("out_dw_b", "out", bytes([0xEE]), io=1, width=1, needs=(("DW", IO_PORT),)),
           Form("in_aw_dw", "in", bytes([0xED]), io=1, width=2, needs=(("DW", IO_PORT),))):
    if _f.name in FORMS:
        raise RuntimeError(f"duplicate form {_f.name}")
    FORMS[_f.name] = _f


# F21 (WP27: the effective-address path). Five consumers of a ModR/M memory operand, each
# over the base, base+index and direct modes with no displacement, a one-byte and a
# two-byte displacement: MOV AW,r/m (8B /0), MOV r/m,AW (89 /0), MOV r/m,imm16 (C7 /0,
# 1234h), ADD r/m,AW (01 /0) and POP r/m (8F /0). The modes: [BW] (base), [BW+10h],
# [BW+200h], [BW+IX] (base+index), [BW+IX+10h], [BW+IX+200h] and [0C00h] (mod 00 rm 110);
# with the presets every address is in the data page (0800h-0D80h, off the stack). A form
# already in the catalog with the same bytes keeps its name (ld_*, st_bw, st_imm_bw*,
# add_m_aw, pop_m, pop_m_d8, pop_m_dir); the rest are named <consumer>_<mode>. Added after
# the lists above so no earlier family picks them up.
F21_MODES = ("bw", "bw_d8", "bw_d16", "bw_ix", "bw_ix_d8", "bw_ix_d16", "dir")
F21_CONTROL_MODES = ("ix_d8", "ix_d16", "bp_iy_d8", "bp_iy_d16")      # loads only
F21_CONSUMERS = {"ld": ("load", [0x8B], 0, b"", dict(reads=1)),
                 "st": ("store", [0x89], 0, b"", dict(writes=1)),
                 "sti": ("store_imm", [0xC7], 0, IMM, dict(writes=1)),
                 "add": ("rmw", [0x01], 0, b"", dict(reads=1, writes=1)),
                 "pop": ("pop_mem", [0x8F], 0, b"", dict(reads=1, writes=1))}
F21_PREFIX = {"ld": "ld", "st": "st", "sti": "st_imm", "add": "add_m_aw", "pop": "pop_m"}
F21_FORM: dict[tuple[str, str], str] = {}


def _f21_form(cons: str, mode_name: str) -> str:
    cls, opcode, reg, tail, counts = F21_CONSUMERS[cons]
    mode = MODE[mode_name]
    code = bytes(opcode) + modrm(mode, reg) + tail
    same = [f.name for f in FORMS.values() if f.code == code]
    if same:
        return same[0]
    name = f"{F21_PREFIX[cons]}_{mode_name}"
    if name in FORMS:
        raise RuntimeError(f"duplicate form {name}")
    FORMS[name] = Form(name, cls, code, width=2, mode=mode.name, mode_class=mode.mode_class,
                       ea=mode.ea, **counts)
    return name


for _c in F21_CONSUMERS:
    for _m in F21_MODES:
        F21_FORM[(_c, _m)] = _f21_form(_c, _m)
for _m in F21_CONTROL_MODES:
    F21_FORM[("ld", _m)] = _f21_form("ld", _m)


# F22 (the immediate forms' post against the fetch run). The immediate memory forms whose
# data request is posted beside a fetch run's delivery clock: the immediate RMW ADD
# r/m,imm16 (81 /0) at [BW+200h], [BW+10h], [BW] and [0C00h], ADD [BW+200h],imm8 (83 /0,
# sign-extended 05h), the left-out write CMP [BW+200h],imm16 (81 /7) and TEST
# [BW+200h],imm16 (F7 /0), against the immediate store MOV r/m,imm16 (C7 /0) in the same
# four modes. A form already in the catalog with the same bytes keeps its name
# (add_m_imm_d16, add_m_imm, st_imm_bw_d16, st_imm_bw_d8, st_imm_bw, st_imm_dir); the rest
# are named <form>_<mode>. Every address is in the data page (0800h, 0810h, 0A00h, 0C00h).
# Added after the lists above so no earlier family picks them up.
F22_FORMS = {"add_d16": ("rmw_imm", [0x81], 0, "bw_d16", IMM, dict(reads=1, writes=1)),
             "add_d8": ("rmw_imm", [0x81], 0, "bw_d8", IMM, dict(reads=1, writes=1)),
             "add_bw": ("rmw_imm", [0x81], 0, "bw", IMM, dict(reads=1, writes=1)),
             "add_dir": ("rmw_imm", [0x81], 0, "dir", IMM, dict(reads=1, writes=1)),
             "add8_d16": ("rmw_imm", [0x83], 0, "bw_d16", _I8, dict(reads=1, writes=1)),
             "cmp_d16": ("load_alu", [0x81], 7, "bw_d16", IMM, dict(reads=1)),
             "test_d16": ("load_alu", [0xF7], 0, "bw_d16", IMM, dict(reads=1)),
             "sti_d16": ("store_imm", [0xC7], 0, "bw_d16", IMM, dict(writes=1)),
             "sti_d8": ("store_imm", [0xC7], 0, "bw_d8", IMM, dict(writes=1)),
             "sti_bw": ("store_imm", [0xC7], 0, "bw", IMM, dict(writes=1)),
             "sti_dir": ("store_imm", [0xC7], 0, "dir", IMM, dict(writes=1))}
F22_NAMES = {"add_d16": "add_m_imm_d16", "add_d8": "add_m_imm_d8", "add_bw": "add_m_imm",
             "add_dir": "add_m_imm_dir", "add8_d16": "add_m_imm8_d16",
             "cmp_d16": "cmp_m_imm_d16", "test_d16": "test_m_imm_d16",
             "sti_d16": "st_imm_bw_d16", "sti_d8": "st_imm_bw_d8", "sti_bw": "st_imm_bw",
             "sti_dir": "st_imm_dir"}
F22_FORM: dict[str, str] = {}
for _label, (_cls, _op, _reg, _mn, _tail, _counts) in F22_FORMS.items():
    _mode = MODE[_mn]
    _code = bytes(_op) + modrm(_mode, _reg) + _tail
    _same = [f.name for f in FORMS.values() if f.code == _code]
    _name = _same[0] if _same else F22_NAMES[_label]
    if _name != F22_NAMES[_label]:
        raise RuntimeError(f"F22 {_label}: catalog has {_name}, expected {F22_NAMES[_label]}")
    if not _same:
        FORMS[_name] = Form(_name, _cls, _code, width=2, mode=_mode.name,
                            mode_class=_mode.mode_class, ea=_mode.ea,
                            align_ok=_mode.uses_bw, **_counts)
    F22_FORM[_label] = _name


# F23 and F25 (WP49): control flow inside the chain, EA without a bus cycle and the stack
# frame. Generator-only: the simulator does not decode these forms yet (UNMODELLED_FORMS;
# families.UNMODELLED). Added after the lists above so no earlier family picks them up. The
# fence before M0 leaves AW = 0 (SHL AW,31) and CW = 001Fh (MOV CL,31), so every value
# below that depends on AW or CW is the in-frame one, not the prelude's.
def _register(forms) -> tuple:
    for f in forms:
        if f.name in FORMS:
            raise RuntimeError(f"duplicate form {f.name}")
        if f.cls not in CLASSES:
            raise RuntimeError(f"{f.name}: unknown class {f.cls}")
        FORMS[f.name] = f
    return tuple(f.name for f in forms)


_SP = DEFAULT_REGS["SP"]
_STACK_W = dict(writes=1, width=2, ea=_SP - 2)     # nominal: the frame's SP moves it
_STACK_R = dict(reads=1, width=2, ea=_SP)

# F23 control flow. CMP AW,AW (3B C0: Z = 1) makes the flags known. Short branches carry the
# displacement in their second byte: BE +n (74 n, taken with Z = 1), BNE +n (75 n, not
# taken), BR short +n (EB n); BR near +n (E9 n 00); DBNZ +n (E2 n: CW -= 1, taken while
# CW != 0) after MOV CW,1 / MOV CW,2 (B9 01 00 / B9 02 00: CW must be set in the frame, the
# fence's MOV CL,31 overwrites a preset); CALL +n (E8 n 00: the return address to the stack,
# a flush) and RET (C3: the return address from the stack).
F23_BE_N = range(8)
F23_BR_N = range(8)
F23_BR_NEAR_N = (0, 1, 2, 3)
F23_BNE_N = (0, 2)
F23_DBNZ_N = (0, 2)
F23_FORMS = _register(
    [Form("cmp_aw_aw", "reg", bytes([0x3B, 0xC0]))]
    + [Form(f"be_n{n}", "branch_short", bytes([0x74, n])) for n in F23_BE_N]
    + [Form(f"bne_n{n}", "branch_short", bytes([0x75, n])) for n in F23_BNE_N]
    + [Form(f"br_n{n}", "branch_short", bytes([0xEB, n])) for n in F23_BR_N]
    + [Form(f"br_near_n{n}", "branch_near", bytes([0xE9, n, 0x00])) for n in F23_BR_NEAR_N]
    + [Form(f"dbnz_n{n}", "dbnz", bytes([0xE2, n])) for n in F23_DBNZ_N]
    + [Form("mov_cw_imm1", "imm", bytes([0xB9, 0x01, 0x00])),
       Form("mov_cw_imm2", "imm", bytes([0xB9, 0x02, 0x00])),
       Form("call_n0", "call", bytes([0xE8, 0x00, 0x00]), **_STACK_W),
       Form("call_n2", "call", bytes([0xE8, 0x02, 0x00]), **_STACK_W),
       Form("ret", "ret", bytes([0xC3]), **_STACK_R)])

# F25 EA alone: LDEA AW,r/m (8D /0) in all 24 memory modes; no memory cycle (reads = writes =
# 0), the mode's EA computed and written to AW.
F25_LDEA = {m.name: f"ldea_{m.name}" for m in MODES}
F25_LDEA_FORMS = _register(
    [Form(F25_LDEA[m.name], "lea", bytes([0x8D]) + modrm(m, 0), mode=m.name,
          mode_class=m.mode_class, ea=m.ea) for m in MODES])

# F25 the stack frame and the segment registers. XLAT (D7): a byte read at BW + AL = 0800h
# (AL = 0 after the fence). PUSH imm16 (68 34 12), PUSH imm8 (6A 12, sign-extended).
# PUSH R (60: AW CW DW BW SP BP IX IY, eight stack writes) and POP R (61: eight stack reads,
# the SP word discarded). PREPARE 0,0 (C8 00 00 00: PUSH BP ; BP := SP) and DISPOSE (C9:
# SP := BP ; POP BP). Segment pushes and pops: PUSH DS1 (06), POP DS1 (07), PUSH DS0 (1E),
# POP DS0 (1F), PUSH PS (0E). MOV DS1,AW (8E C0: DS1 := 0), MOV AW,DS1 (8C C0), MOV DS1,[BW]
# (8E 07: DS1 := 9090h, nothing after it uses DS1) and MOV [BW],DS0 (8C 1F).
F25_XLAT_EA = DEFAULT_REGS["BW"]
_BW_MEM = dict(width=2, mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"])
F25_STACK_FORMS = _register([
    Form("xlat", "xlat", bytes([0xD7]), reads=1, width=1, ea=F25_XLAT_EA),
    Form("push_imm16", "push_imm", bytes([0x68]) + IMM, **_STACK_W),
    Form("push_imm8", "push_imm", bytes([0x6A, 0x12]), **_STACK_W),
    Form("push_r", "push_r", bytes([0x60]), writes=8, width=2, ea=_SP - 2),
    Form("pop_r", "pop_r", bytes([0x61]), reads=8, width=2, ea=_SP),
    Form("prepare_00", "prepare", bytes([0xC8, 0x00, 0x00, 0x00]), **_STACK_W),
    Form("dispose", "dispose", bytes([0xC9]), **_STACK_R),
    Form("push_ds1", "push_seg", bytes([0x06]), **_STACK_W),
    Form("pop_ds1", "pop_seg", bytes([0x07]), **_STACK_R),
    Form("push_ds0", "push_seg", bytes([0x1E]), **_STACK_W),
    Form("pop_ds0", "pop_seg", bytes([0x1F]), **_STACK_R),
    Form("push_ps", "push_seg", bytes([0x0E]), **_STACK_W),
    Form("mov_ds1_aw", "reg", bytes([0x8E, 0xC0])),
    Form("mov_aw_ds1", "reg", bytes([0x8C, 0xC0])),
    Form("mov_ds1_m", "load_seg", bytes([0x8E, 0x07]), reads=1, **_BW_MEM),
    Form("mov_m_ds0", "store", bytes([0x8C, 0x1F]), writes=1, **_BW_MEM)])

# Forms the simulator does not decode yet (test_sim skips them); (WP55) none since F23's;
# (WP74) the F32 and F33 forms joined it, (WP78) and left it: none.
UNMODELLED_FORMS = frozenset()

# F26 and F27 (WP56: the probes of the ten rules pinned by one or two cells). Every other
# form the two families use is in the catalog above. TEST [BW+200h],AW (85 87 00 02: TEST
# 85's lookup with a two-byte displacement, the control of TEST [0C00h],AW for lookup_start);
# the C0/C1 count mask: SHL AW,n (C1 E0 nn) at n = 31, 32, 33, 255 (the model takes the count
# byte unmasked: 255 is 510 clocks of count loop; masked to 5 bits it is 31) and MOV CL,n ;
# SHL AW,CL (B1 nn D3 E0) at n = 32, 255 (CL masked to 5 bits: 0 and 31; the CL path's
# control). Added after the lists above so no earlier family picks them up.
F26_SHL_IMM_N = (31, 32, 33, 255)
F26_SHL_CL_N = (32, 255)
F26_FORMS = _register(
    [Form("test_m_aw_bw_d16", "load_alu", bytes([0x85, 0x87]) + D16.to_bytes(2, "little"),
          reads=1, width=2, mode="bw_d16", mode_class="base_disp",
          ea=DEFAULT_REGS["BW"] + D16)]
    + [Form(f"shl_imm{n}", "shift_imm", bytes([0xC1, 0xE0, n])) for n in F26_SHL_IMM_N]
    + [Form(f"shl_cl{n}", "shift_cl", bytes([0xB1, n, 0xD3, 0xE0])) for n in F26_SHL_CL_N])


# F28 and F29 (WP59: the open states of the thirty-sixth fit). Every other form the two
# families use is in the catalog above. The group memory forms of F26's gih ladder at
# [BW+200h] (mod 10 rm 111, d16 0200h, EA 0A00h in the data page): INC (FF /0), NOT (F7 /2),
# SHL ,1 (D1 /4), NEG (F7 /3), DEC (FF /1), each a read and a write of the word at 0A00h.
# Added after the lists above so no earlier family picks them up.
F29_GIH_D16 = (("inc_m_bw_d16", 0xFF, 0), ("not_m_bw_d16", 0xF7, 2),
               ("shl_m1_bw_d16", 0xD1, 4), ("neg_m_bw_d16", 0xF7, 3),
               ("dec_m_bw_d16", 0xFF, 1))
F29_FORMS = _register(
    [Form(name, "rmw", bytes([op]) + modrm(MODE["bw_d16"], reg), reads=1, writes=1, width=2,
          mode="bw_d16", mode_class="base_disp", ea=MODE["bw_d16"].ea)
     for name, op, reg in F29_GIH_D16])


# F24 (WP66: the string and block forms, sustained data demand through the arbiter).
# (WP67) modelled: the simulator decodes them (sim/templates.py, _string_steps).
# NEC mnemonics and bytes: MOVBK (A4 byte, A5 word: [DS1:IY] := [DS0:IX]), CMPBK (A6/A7:
# compare [DS0:IX] with [DS1:IY], reading [DS1:IY] first), STM (AA/AB: [DS1:IY] := AL/AW), LDM (AC/AD: AL/AW :=
# [DS0:IX]), CMPM (AE/AF: compare AL/AW with [DS1:IY]), INM (6C/6D: [DS1:IY] := port DW), OUTM
# (6E/6F: port DW := [DS0:IX]); each element steps IX and/or IY by the width, upward (PSW
# 0002h: DIR clear). The prefixes: REP (F3; REPE/REPZ on CMPBK and CMPM) and REPNE/REPNZ (F2)
# repeat while CW != 0, decrementing CW per element, the compares also stopping on Z = 0
# (REPE) or Z = 1 (REPNE) after the element; REPC (65) and REPNC (64) are not used. Silicon
# (F24, acquired 2026-10-28, all 912 runs): CMPBK reads the destination [DS1:IY] before the
# source [DS0:IX] in every element, with and without a prefix; a REP compare (REPE / REPNE
# CMPBK and CMPM) reads one more element at the next IX / IY after the element that ends the
# repeat, whether CW reached 0 or the condition failed (none at CW = 0; the other REP forms
# and the unprefixed compares run exactly their elements). A prefixed
# form is one catalog form (prefix + opcode) as the pfx_* forms are. reads / writes / io
# count one element's cycles (an odd word splits each in two). The data ranges are set by the
# family's register presets (F24_IX / F24_IY: source at 0A40h, destination at 0C40h, both in
# the data page and clear of every EA the other forms use, the store marker's 0C00h and the
# stack); DS0 = DS1 = 0 (the prelude's), so the offsets are linear addresses. INM / OUTM use
# DW = IO_PORT (40h), as the DW I/O forms do.
@dataclass(frozen=True)
class StringOp:
    op: str                 # movbk cmpbk stm ldm cmpm inm outm
    width: int              # 1 byte, 2 word
    rep: str | None         # None (one element), "rep" (F3), "repe" (F3 on a compare), "repne" (F2)
    steps: tuple            # one element's cycles in order: (kind, "ix" | "iy" | "port")


F24_OPS = {  # op: (byte opcode, class, one element's cycles in bus order)
    "movbk": (0xA4, "str_move", (("data_read", "ix"), ("data_write", "iy"))),
    "cmpbk": (0xA6, "str_cmp", (("data_read", "iy"), ("data_read", "ix"))),   # IY first (F24)
    "stm": (0xAA, "str_store", (("data_write", "iy"),)),
    "ldm": (0xAC, "str_load", (("data_read", "ix"),)),
    "cmpm": (0xAE, "str_scan", (("data_read", "iy"),)),
    "inm": (0x6C, "str_in", (("io_read", "port"), ("data_write", "iy"))),
    "outm": (0x6E, "str_out", (("data_read", "ix"), ("io_write", "port"))),
}
F24_COMPARES = ("cmpbk", "cmpm")
F24_REP_PREFIX = {"rep": 0xF3, "repe": 0xF3, "repne": 0xF2}
F24_WIDTH_TAG = {1: "b", 2: "w"}
F24_IX = 0x0A40                 # source DS0:IX (0A40h-0A5Fh at most: 16 words)
F24_IY = 0x0C40                 # destination DS1:IY (0C40h-0C5Fh at most)
F24_PATTERN = 0x0C42            # the word the T series' pattern store zeroes (IY + 2)
F24_MOV_CW_N = (0, 3, 4, 8, 16) # MOV CW,n (B9 nn nn) beside F23's mov_cw_imm1 / mov_cw_imm2
STRING_FORMS: dict[str, StringOp] = {}


def f24_form_name(op: str, width: int, rep: str | None = None) -> str:
    return (f"{rep}_" if rep else "") + f"{op}_{F24_WIDTH_TAG[width]}"


def _f24_forms() -> list:
    forms = []
    for op, (opcode, cls, steps) in F24_OPS.items():
        reads = sum(1 for kind, _ in steps if kind == "data_read")
        writes = sum(1 for kind, _ in steps if kind == "data_write")
        io = sum(1 for kind, _ in steps if kind.startswith("io"))
        needs = (("DW", IO_PORT),) if io else ()
        reps = (None, "repe", "repne") if op in F24_COMPARES else (None, "rep")
        for width in (1, 2):
            for rep in reps:
                name = f24_form_name(op, width, rep)
                code = (bytes([F24_REP_PREFIX[rep]]) if rep else b"") + bytes([opcode | (width - 1)])
                forms.append(Form(name, cls, code, reads=reads, writes=writes, io=io,
                                  width=width, needs=needs))
                STRING_FORMS[name] = StringOp(op, width, rep, steps)
    return forms


F24_STRING_FORMS = _register(_f24_forms())
# MOV CW,n for the repeat counts, and the T series' pattern store before the first LS:
# MOV word [0C42h],0 (C7 06 42 0C 00 00), so the destination word at IY + 2 reads 0000h
F24_MOV_CW = {1: "mov_cw_imm1", 2: "mov_cw_imm2"}
F24_MOV_CW.update(zip(F24_MOV_CW_N, _register(
    [Form(f"mov_cw_imm{n}", "imm", bytes([0xB9]) + n.to_bytes(2, "little"))
     for n in F24_MOV_CW_N])))
F24_PATTERN_STORE = _register(
    [Form("st_imm0_dir_c42", "store_imm", bytes([0xC7, 0x06]) + F24_PATTERN.to_bytes(2, "little")
          + bytes(2), writes=1, width=2, mode="dir", mode_class="direct", ea=F24_PATTERN)])[0]
# (WP67) the simulator decodes the string forms (sim/templates.py, _string_steps): none left


# F30 (WP73: the facts-only shapes of the thirty-ninth and fortieth fits). Every other form the
# family uses is in the catalog above. The segment register forms by sreg field (NEC: 0 DS1,
# 1 PS, 2 SS, 3 DS0; 8E with PS is illegal and not used): MOV sreg,AW (8E C0 / D0 / D8: AW = 0
# after the fence, so the sreg keeps its prelude value 0), MOV sreg,[IX] (8E 04 / 14 / 1C: the
# word at IX = 0100h, in the zeroed vector table, so SS and DS0 load 0 and the stack and data
# addresses do not move; the mode class of [BW], base), MOV AW,sreg (8C C0 / C8 / D0 / D8) and
# MOV [BW],sreg (8C 07 / 0F / 17 / 1F, a word store at 0800h); PUSH SS (16) and POP SS (17).
F30_SREG = {"ds1": 0, "ps": 1, "ss": 2, "ds0": 3}
F30_SEG_FORMS = _register(
    [Form(f"mov_{s}_aw", "reg", bytes([0x8E, 0xC0 | (r << 3)]))
     for s, r in F30_SREG.items() if s not in ("ps", "ds1")]
    + [Form(f"mov_{s}_ix", "load_seg", bytes([0x8E]) + modrm(MODE["ix"], r), reads=1, width=2,
            mode="ix", mode_class=MODE["ix"].mode_class, ea=MODE["ix"].ea)
       for s, r in F30_SREG.items() if s != "ps"]
    + [Form(f"mov_aw_{s}", "reg", bytes([0x8C, 0xC0 | (r << 3)]))
       for s, r in F30_SREG.items() if s != "ds1"]
    + [Form(f"mov_m_{s}", "store", bytes([0x8C]) + modrm(MODE["bw"], r), writes=1, **_BW_MEM)
       for s, r in F30_SREG.items() if s != "ds0"]
    + [Form("push_ss", "push_seg", bytes([0x16]), **_STACK_W),
       Form("pop_ss", "pop_seg", bytes([0x17]), **_STACK_R)])


# F32 and F33 (WP74; HDL plan Phase E items 4 and 5): the 0F page and the register miscellany.
# Generator-only until WP78 (UNMODELLED_FORMS, families.UNMODELLED): their runs were read as
# facts; (WP78) the simulator decodes them (sim/templates.py: decode, _page0f, ONE_BYTE). Every byte
# string follows the V35 data book's encodings (the V20 manual's for the 0F page, which the
# V35's eu-timing probes ran: 0F 10-1F, 20 / 22 / 26, 28 / 2A, 31 / 33 / 39 / 3B; the V35's own
# 0F 25 MOVSPA and 0F 2D BRKCS sit between them and are not used). The fence leaves AW = 0,
# CW = 001Fh (CL = 31) and the other registers at their presets.
#
# F32 the bit ops (TEST1 0F 10/11, CLR1 12/13, SET1 14/15, NOT1 16/17 with the bit index in CL,
# +8 with an imm3 / imm4 byte after the operand): on AL / AW (ModR/M C0) and at [BW] (07, the
# byte or word at 0800h), byte and word; CL = 31 is masked to bit 7 / bit 15, so the
# immediate forms name the same bit (07h / 0Fh). TEST1 at [BW] reads, CLR1 / SET1 / NOT1 read
# and write. SET1 [m],CL word in four more modes ([BW+10h], [BW+200h], [BW+IX] = 0900h with
# the default IX, [0C00h]) for the mode sweep.
F32_BIT_OPS = {"test1": 0x10, "clr1": 0x12, "set1": 0x14, "not1": 0x16}
F32_BIT_IMM = {1: 0x07, 2: 0x0F}
F32_WTAG = {1: "b", 2: "w"}
F32_SET1_MODES = ("bw_d8", "bw_d16", "bw_ix", "dir")
F32_BIT: dict[str, tuple] = {}      # name: (op, operand "r" | "m", width, index "cl" | "imm")


def _f32_bit_forms() -> list:
    forms = []
    for op, base in F32_BIT_OPS.items():
        for width in (1, 2):
            for src in ("cl", "imm"):
                second = base | (width - 1) | (8 if src == "imm" else 0)
                tail = bytes([F32_BIT_IMM[width]]) if src == "imm" else b""
                for operand in ("r", "m"):
                    name = f"{op}_{operand}{F32_WTAG[width]}_{src}"
                    F32_BIT[name] = (op, operand, width, src)
                    if operand == "r":
                        forms.append(Form(name, "bit1", bytes([0x0F, second, 0xC0]) + tail))
                        continue
                    counts = dict(reads=1) if op == "test1" else dict(reads=1, writes=1)
                    forms.append(Form(name, {"test1": "bit1_test", "clr1": "bit1_clr"}.get(
                                          op, "bit1_rmw"),
                                      bytes([0x0F, second]) + modrm(MODE["bw"], 0) + tail,
                                      width=width, mode="bw", mode_class="base",
                                      ea=DEFAULT_REGS["BW"], **counts))
    for m in F32_SET1_MODES:
        mode = MODE[m]
        name = f"set1_mw_cl_{m}"
        F32_BIT[name] = ("set1", "m", 2, "cl")
        forms.append(Form(name, "bit1_rmw", bytes([0x0F, 0x15]) + modrm(mode, 0), reads=1,
                          writes=1, width=2, mode=m, mode_class=mode.mode_class, ea=mode.ea))
    return forms


F32_BIT_FORMS = _register(_f32_bit_forms())

# F32 the packed BCD strings: ADD4S (0F 20) and SUB4S (0F 22) add / subtract the string at
# DS0:IX into the one at DS1:IY, CMP4S (0F 26) compares them; CL digits, (CL + 1) / 2 bytes,
# set in the frame by MOV CL,n (n = 2, 4, 8, 16). IX = F24_IX (0A40h) and IY = F24_IY (0C40h)
# as presets, the bytes in the 90h fill (packed BCD 90). reads / writes count one byte pair
# (the source byte, the destination byte, the result byte back; CMP4S writes nothing); the
# normaliser walks the count (normalize._StringState.bcd). Silicon (V35 data check,
# docs/v35s-eu-timing.md): the source byte before the destination byte.
F32_BCD = {"add4s": 0x20, "sub4s": 0x22, "cmp4s": 0x26}
F32_BCD_N = (2, 4, 8, 16)
F32_MOV_CL = {2: "mov_cl2", 4: "mov_cl_imm", 8: "mov_cl8", 16: "mov_cl16"}   # B1 nn
_F24_PRESETS = (("IX", 0x0A40), ("IY", 0x0C40))       # F24_IX / F24_IY (defined above)
F32_BCD_FORMS = _register(
    [Form(name, "bcd4s_cmp" if name == "cmp4s" else "bcd4s", bytes([0x0F, second]),
          reads=2, writes=0 if name == "cmp4s" else 1, width=1, needs=_F24_PRESETS)
     for name, second in F32_BCD.items()])

# F32 the digit rotates: ROL4 (0F 28) and ROR4 (0F 2A) on DL (ModR/M C2: DL = 78h from DW's
# preset) and on the byte at [BW] (07: a byte read and a byte write at 0800h).
F32_ROT4_FORMS = _register(
    [Form(f"{op}_dl", op, bytes([0x0F, second, 0xC2]))
     for op, second in (("rol4", 0x28), ("ror4", 0x2A))]
    + [Form(f"{op}_m", f"{op}_mem", bytes([0x0F, second]) + modrm(MODE["bw"], 0), reads=1,
            writes=1, width=1, mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"])
       for op, second in (("rol4", 0x28), ("ror4", 0x2A))])

# F32 the bit fields. EXT (0F 33 reg form, 0F 3B imm4) loads AW from the field at DS0:IX, INS
# (0F 31, 0F 39) stores AW's low bits into the field at DS1:IY; the bit offset is the 8-bit
# register in ModR/M bits 2:0, the width - 1 the register in bits 5:3 (reg form) or the imm4
# byte (the data book: the low 4 bits of each); after the transfer the offset register holds
# (offset + width + 1) & 15 and IX / IY steps by 2 when the sum passes 15. Silicon (WP74, the
# first F32 acquisition, w0 / w1): an offset register with bits above bit 3 set (DL = 78h from
# DW 5678h) is not reduced to its low 4 bits (the field crosses into the next word, INS writes
# FFFFh there, the second instance crosses again), so every bit-field chain presets DW = 0608h:
# the offsets BL = 0 (BW 0800h) and DL = 8, the widths DH = 6 (7 bits) and BH = 8 (9 bits), all
# within 0-15. The cases (offset, width field): reg form (0, 6) and (8, 6) within one word (the
# second instance of (8, 6) at offset 15 crosses), (8, 8) crossing, (8, 0) with the offset in BH
# and the width in BL (the operand order's control: swapped, (0, 8) then (9, 8) crosses);
# imm (0, 7) within, (8, 7) ending at the word boundary (one word, f-ext), (8, 11) crossing.
# IX = 0A40h and IY = 0C40h as presets. reads / writes count the aligned single-word case;
# the normaliser walks the offset, the crossing and the IX / IY step
# (normalize._StringState.bitfield): EXT reads the word at IX (and IX + 2 when the field
# crosses), INS reads and writes back the word at IY (then IY + 2 when it crosses).
F32_BITFIELD: dict[str, tuple] = {}     # name: (op "ext" | "ins", offset reg, width reg | None, imm)
F32_BITFIELD_DW = 0x0608
_R8 = {"al": 0, "cl": 1, "dl": 2, "bl": 3, "ah": 4, "ch": 5, "dh": 6, "bh": 7}


def _f32_bitfield_forms() -> list:
    forms = []
    for op, reg_op, imm_op in (("ext", 0x33, 0x3B), ("ins", 0x31, 0x39)):
        presets = ((_F24_PRESETS[0] if op == "ext" else _F24_PRESETS[1]), ("DW", F32_BITFIELD_DW))
        counts = (dict(reads=1, width=2, ea=0x0A40) if op == "ext"
                  else dict(reads=1, writes=1, width=2, ea=0x0C40))
        cls = f"bf_{op}"
        for off, wid in (("bl", "dh"), ("dl", "dh"), ("dl", "bh"), ("bh", "bl")):
            name = f"{op}_{off}_{wid}"
            F32_BITFIELD[name] = (op, _R8[off], _R8[wid], None)
            forms.append(Form(name, cls, bytes([0x0F, reg_op, 0xC0 | (_R8[wid] << 3) | _R8[off]]),
                              needs=presets, **counts))
        for off, imm in (("bl", 7), ("dl", 7), ("dl", 11)):
            name = f"{op}_{off}_i{imm}"
            F32_BITFIELD[name] = (op, _R8[off], None, imm)
            forms.append(Form(name, cls, bytes([0x0F, imm_op, 0xC0 | _R8[off], imm]),
                              needs=presets, **counts))
    return forms


F32_BITFIELD_FORMS = _register(_f32_bitfield_forms())

# F32 four 0F forms behind the DS1 segment prefix (26h; DS1 = 0, so every address stays):
# TEST1 [BW],CL word, SET1 [BW],7 byte, ROL4 [BW] and ADD4S (the prefix names ADD4S's source
# segment).
F32_PFX = {"pfx_test1_mw_cl": "test1_mw_cl", "pfx_set1_mb_imm": "set1_mb_imm",
           "pfx_rol4_m": "rol4_m", "pfx_add4s": "add4s"}


def _f32_pfx_forms() -> list:
    out = []
    for name, base in F32_PFX.items():
        f = FORMS[base]
        out.append(Form(name, f.cls, bytes([0x26]) + f.code, reads=f.reads, writes=f.writes,
                        width=f.width, mode=f.mode, mode_class=f.mode_class, ea=f.ea,
                        needs=f.needs))
        if base in F32_BIT:
            F32_BIT[name] = F32_BIT[base]
    return out


F32_PFX_FORMS = _register(_f32_pfx_forms())
F32_BCD.update({"pfx_add4s": F32_BCD["add4s"]})
F32_FORMS = F32_BIT_FORMS + F32_BCD_FORMS + F32_ROT4_FORMS + F32_BITFIELD_FORMS + F32_PFX_FORMS

# F33 the register miscellany. INC r16 (40+r) and DEC r16 (48+r) for every register; INC / DEC
# r8 (FE /0, FE /1) on AL (C0 / C8) and DH (C6 / CE); INC / DEC byte [BW] (FE 07 / FE 0F; the
# word forms are F16's inc_m / dec_m); the adjusts ADJ4A (27), ADJ4S (2F), ADJBA (37), ADJBS
# (3F); CVTBD (D4 0A), CVTDB (D5 0A); CVTBW (98, CBW) and CVTWL (99, CWD); MUL CW (F7 E9,
# signed), DIV CW (F7 F9) and DIVU CW (F7 F1) beside F16's mul_m / div_m and F14's divu_m; the
# immediate multiply MUL AW,r/m,imm16 (69 /0: 69 C1 34 12 with CW, 69 07 34 12 at [BW]) and
# MUL AW,r/m,imm8 (6B C1 05, 6B 07 05); the flag forms CLR1 CY / SET1 CY / NOT1 CY (F8 / F9 /
# F5: CLC STC CMC), DI / EI (FA / FB: CLI STI, no interrupt source is enabled), CLR1 DIR /
# SET1 DIR (FC / FD: CLD STD, nothing after them steps IX / IY). The leads: MOV DW,0 (BA 00
# 00, the dividend's high word), MOV AW,8080h (B8 80 80, CBW / CWD on a negative operand).
_R16 = ("aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy")
F33_FLAGS = {"clc": 0xF8, "stc": 0xF9, "cmc": 0xF5, "cli": 0xFA, "sti": 0xFB, "cld": 0xFC,
             "std": 0xFD}
F33_FLAG_CLASS = {"cli": "flag_di", "sti": "flag_ei"}      # (WP78) their own costs
F33_REG_FORMS = _register(
    [Form(f"inc_{r}", "incdec", bytes([0x40 + i])) for i, r in enumerate(_R16)]
    + [Form(f"dec_{r}", "incdec", bytes([0x48 + i])) for i, r in enumerate(_R16)]
    + [Form(f"{op}_{r}", "incdec", bytes([0xFE, 0xC0 | (sub << 3) | _R8[r]]))
       for r in ("al", "dh") for op, sub in (("inc", 0), ("dec", 1))]
    + [Form(f"{op}b_m", "rmw", bytes([0xFE]) + modrm(MODE["bw"], sub), reads=1, writes=1,
            width=1, mode="bw", mode_class="base", ea=DEFAULT_REGS["BW"])
       for op, sub in (("inc", 0), ("dec", 1))]
    + [Form(n, cls, bytes([op])) for n, cls, op in (("adj4a", "adjust", 0x27),
                                                     ("adj4s", "adjust", 0x2F),
                                                     ("adjba", "adjust_b", 0x37),
                                                     ("adjbs", "adjust_b", 0x3F))]
    + [Form("cvtbd", "convert", bytes([0xD4, 0x0A])), Form("cvtdb", "convert_d", bytes([0xD5, 0x0A])),
       Form("cvtbw", "extend", bytes([0x98])), Form("cvtwl", "extend_w", bytes([0x99]))]
    + [Form("mul_cw", "mul", bytes([0xF7, 0xE9])), Form("div_cw", "div", bytes([0xF7, 0xF9])),
       Form("divu_cw", "div", bytes([0xF7, 0xF1]))]
    + [Form("mul_aw_cw_imm16", "mul_imm", bytes([0x69, 0xC1]) + IMM),
       Form("mul_aw_m_imm16", "mul_imm", bytes([0x69, 0x07]) + IMM, reads=1, **_BW_MEM),
       Form("mul_aw_cw_imm8", "mul_imm", bytes([0x6B, 0xC1, F15_IMM8])),
       Form("mul_aw_m_imm8", "mul_imm", bytes([0x6B, 0x07, F15_IMM8]), reads=1, **_BW_MEM)]
    + [Form(n, F33_FLAG_CLASS.get(n, "flag"), bytes([op])) for n, op in F33_FLAGS.items()]
    + [Form("mov_dw_imm0", "imm", bytes([0xBA, 0x00, 0x00])),
       Form("mov_aw_8080", "imm", bytes([0xB8, 0x80, 0x80]))])

# F33 REPC (65) and REPNC (64) before CMPM / CMPBK word: repeat while CW != 0, decrementing CW
# per element, REPC stopping after an element that leaves CY = 0, REPNC after one that leaves
# CY = 1 (the data book: the comparison's carry). CMPM is AW - [DS1:IY], CMPBK [DS0:IX] -
# [DS1:IY] (read IY first, as F24's CMPBK). On the fill: CMPM 0 - 9090h borrows (CY = 1: REPC
# runs CW out, REPNC stops after element 1); CMPBK fill - fill does not (CY = 0: REPC stops
# after element 1, REPNC runs out). The patterns: F24's MOV word [0C42h],0 (the destination
# word at IY + 2: CMPM's element 2 is 0 - 0, CY = 0, REPC stops there) and MOV word
# [0A42h],0 (the source word at IX + 2: CMPBK's element 2 is 0 - 9090h, CY = 1, REPNC stops
# there), both before the first LS. Kept out of STRING_FORMS (the simulator's string table,
# F24's 32 forms); the normaliser walks them as string forms (UNMODELLED_STRING_FORMS, a name
# kept from WP74: the simulator decodes them as REP compares since WP76).
F33_REP_PREFIX = {"repc": 0x65, "repnc": 0x64}
UNMODELLED_STRING_FORMS: dict[str, StringOp] = {}


def _f33_rep_forms() -> list:
    forms = []
    for rep, prefix in F33_REP_PREFIX.items():
        for op in ("cmpm", "cmpbk"):
            opcode, cls, steps = F24_OPS[op]
            name = f24_form_name(op, 2, rep)
            reads = sum(1 for kind, _ in steps if kind == "data_read")
            forms.append(Form(name, cls, bytes([prefix, opcode | 1]), reads=reads, width=2,
                              needs=_F24_PRESETS))
            UNMODELLED_STRING_FORMS[name] = StringOp(op, 2, rep, steps)
    return forms


F33_REP_FORMS = _register(_f33_rep_forms())
F33_PATTERN_SRC = 0x0A42            # the source word at IX + 2
F33_PATTERN_STORE = _register(
    [Form("st_imm0_dir_a42", "store_imm", bytes([0xC7, 0x06]) + F33_PATTERN_SRC.to_bytes(2, "little")
          + bytes(2), writes=1, width=2, mode="dir", mode_class="direct", ea=F33_PATTERN_SRC)])[0]
F33_FORMS = F33_REG_FORMS + F33_REP_FORMS + (F33_PATTERN_STORE,)

# (WP74) the F32 and F33 forms were generator-only until (WP78) the simulator decoded them
# (sim/templates.py: the 0F page, the one-byte forms, FE, 69 / 6B, D4 / D5): none left

# F34 (WP80: probes for the forty-second fit's miss shapes). Every other form the family uses is
# in the catalog above, byte for byte. CMP AW,DW (3B C2) leaves Z = 0 (AW = 0 or 1234h against
# DW = 5678h), so BE +0 after it is the second not-taken conditional form beside CMP AW,AW ;
# BNE +0; the decoder takes it as CMP AW,AW (the reg class, CMP r16,r16 setting Z from the two
# registers; the RTL's format key is cmp_aw_aw's).
F34_FORMS = _register([Form("cmp_aw_dw", "reg", bytes([0x3B, 0xC2]))])
