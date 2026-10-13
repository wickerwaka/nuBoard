"""V35S execution unit: decode, semantics and timing steps.

The general and segment registers live in the internal RAM bank selected
by PSW.RB, exactly as on silicon (a data write to IDB:E00 + 20h*bank + n
changes the register). PC and PSW are flip-flops.

Every handler is a generator. It takes its instruction bytes from the
queue with `self.byte()`, does its memory and I/O through `self.read()` /
`self.write()`, and spends execution clocks with `self.step(name)`, where
`name` is a key of costs.COSTS. Timing is therefore a sequence of named
steps per instruction; fit.py compares the result with silicon.
"""

from __future__ import annotations

# Register slot offsets within a bank.
REG16 = (0x1E, 0x1C, 0x1A, 0x18, 0x16, 0x14, 0x12, 0x10)     # AW CW DW BW SP BP IX IY
SEG = (0x0E, 0x0C, 0x0A, 0x08)                               # DS1 PS SS DS0
AW, CW, DW, BW, SP, BP, IX, IY = range(8)
DS1, PS, SS, DS0 = range(4)

CY, P, AC, Z, S, BRK, IE, DIR, V = 0, 2, 4, 6, 7, 8, 9, 10, 11
BRKI = 1

PARITY = [bin(i).count("1") % 2 == 0 for i in range(256)]


class Trap(Exception):
    def __init__(self, vector):
        self.vector = vector


class EU:
    def __init__(self, machine):
        self.m = machine
        self.iram = machine.iram
        self.costs = machine.costs
        self.psw = 0xF002
        self.pc = 0
        self.set_seg(PS, 0xFFFF)
        for s in (DS1, SS, DS0):
            self.set_seg(s, 0)
        self.seg_override = None
        self.rep = None
        self.halted = False

    # -- registers --------------------------------------------------------

    @property
    def bank(self):
        return (self.psw >> 12) & 7

    def _slot(self, offset):
        return self.bank * 32 + offset

    def r16(self, n):
        o = self._slot(REG16[n])
        return self.iram[o] | (self.iram[o + 1] << 8)

    def w16(self, n, v):
        o = self._slot(REG16[n])
        self.iram[o] = v & 0xFF
        self.iram[o + 1] = (v >> 8) & 0xFF

    def r8(self, n):
        return self.iram[self._slot(REG16[n & 3]) + (n >> 2)]

    def w8(self, n, v):
        self.iram[self._slot(REG16[n & 3]) + (n >> 2)] = v & 0xFF

    def seg(self, n):
        o = self._slot(SEG[n])
        return self.iram[o] | (self.iram[o + 1] << 8)

    def set_seg(self, n, v):
        o = self._slot(SEG[n])
        self.iram[o] = v & 0xFF
        self.iram[o + 1] = (v >> 8) & 0xFF

    def flag(self, bit):
        return (self.psw >> bit) & 1

    def set_flag(self, bit, value):
        self.psw = (self.psw & ~(1 << bit)) | ((1 if value else 0) << bit)

    # -- timing and bus primitives -----------------------------------------

    def step(self, name, extra=0):
        n = self.costs.get(name, 0) + extra
        if n:
            yield ("clocks", n)

    def clocks(self, n):
        if n > 0:
            yield ("clocks", n)

    def byte(self, operand=True):
        """Take the next instruction byte. Operand bytes (immediates and
        displacements) keep their queue space until the instruction ends;
        decode bytes (opcode, prefixes, ModR/M) free it at once."""
        value = yield ("byte", operand)
        self.pc = (self.pc + 1) & 0xFFFF
        return value

    def word(self):
        low = yield from self.byte()
        high = yield from self.byte()
        return low | (high << 8)

    def linear(self, segment, offset):
        return ((segment << 4) + (offset & 0xFFFF)) & 0xFFFFF

    def _internal(self, linear):
        """'ram', 'sfr' or None for a data access at this linear address."""
        m = self.m
        if linear == 0xFFFFF:
            return "sfr"
        if (linear >> 12) != m.sfr[0xFF]:
            return None
        low = linear & 0xFFF
        if low >= 0xF00:
            return "sfr"
        if low >= 0xE00 and m.sfr[0xEB] & 0x40:
            return "ram"
        return None

    def _read_byte_internal(self, kind, linear):
        if kind == "ram":
            return self.iram[linear & 0xFF]
        if linear == 0xFFFFF:
            return self.m.sfr[0xFF]
        return self.m.sfr[linear & 0xFF]

    def _write_byte_internal(self, kind, linear, value):
        if kind == "ram":
            self.iram[linear & 0xFF] = value & 0xFF
        else:
            self.m.sfr[linear & 0xFF] = value & 0xFF
            if (linear & 0xFF) == 0xEA:           # FLAG: F0 bit 3, F1 bit 5
                self.set_flag(3, value & 0x08)
                self.set_flag(5, value & 0x20)

    def read(self, segment, offset, width, space="mem"):
        """Data read of 1 or 2 bytes; an odd word is two cycles, odd byte first."""
        if space == "io":
            value = yield ("read", "io", offset & 0xFFFF, width)
            return value
        if width == 1:
            linear = self.linear(segment, offset)
            kind = self._internal(linear)
            if kind:
                yield from self.step("internal_access")
                return self._read_byte_internal(kind, linear)
            value = yield ("read", "mem", linear, 1)
            return value
        linear = self.linear(segment, offset)
        if linear & 1:
            low = yield from self.read(segment, offset, 1)
            high = yield from self.read(segment, offset + 1, 1)
            return low | (high << 8)
        kind = self._internal(linear)
        if kind:
            yield from self.step("internal_access")
            return (self._read_byte_internal(kind, linear)
                    | (self._read_byte_internal(kind, linear + 1) << 8))
        value = yield ("read", "mem", linear, 2)
        return value

    def write(self, segment, offset, width, value, space="mem"):
        if space == "io":
            yield ("write", "io", offset & 0xFFFF, width, value)
            return
        linear = self.linear(segment, offset)
        if width == 2 and linear & 1:
            yield from self.write(segment, offset, 1, value & 0xFF)
            yield from self.write(segment, offset + 1, 1, value >> 8)
            return
        kind = self._internal(linear)
        if kind:
            yield from self.step("internal_access")
            self._write_byte_internal(kind, linear, value)
            if width == 2:
                self._write_byte_internal(kind, linear + 1, value >> 8)
        else:
            yield ("write", "mem", linear, width, value)
        if self.m.sfr[0xEB] & 0x40:
            yield from self.step("ramen_write")

    def push(self, value):
        sp = (self.r16(SP) - 2) & 0xFFFF
        self.w16(SP, sp)
        yield from self.write(self.seg(SS), sp, 2, value)

    def pop(self):
        sp = self.r16(SP)
        value = yield from self.read(self.seg(SS), sp, 2)
        self.w16(SP, sp + 2)
        return value

    def jump(self, pc, ps=None):
        if ps is not None:
            self.set_seg(PS, ps)
        self.pc = pc & 0xFFFF
        yield ("flush", self.linear(self.seg(PS), self.pc))

    # -- ModR/M ------------------------------------------------------------

    def modrm(self):
        """Decode a ModR/M byte. Returns (mod, reg, rm, segment, offset)."""
        value = yield from self.byte(operand=False)
        mod, reg, rm = value >> 6, (value >> 3) & 7, value & 7
        if mod == 3:
            return mod, reg, rm, None, None
        disp = 0
        if mod == 1:
            disp = yield from self.byte()
            disp = disp - 0x100 if disp & 0x80 else disp
        elif mod == 2 or (mod == 0 and rm == 6):
            disp = yield from self.word()
        base = {0: self.r16(BW) + self.r16(IX), 1: self.r16(BW) + self.r16(IY),
                2: self.r16(BP) + self.r16(IX), 3: self.r16(BP) + self.r16(IY),
                4: self.r16(IX), 5: self.r16(IY), 6: self.r16(BP), 7: self.r16(BW)}[rm]
        if mod == 0 and rm == 6:
            base = 0
        segment = DS0
        if rm in (2, 3) or (rm == 6 and mod != 0):
            segment = SS
        if self.seg_override is not None:
            segment = self.seg_override
        extra = (1 if mod in (1, 2) or (mod == 0 and rm == 6) else 0) + \
                (1 if mod == 2 and rm < 4 else 0)
        yield from self.step("ea", extra)
        return mod, reg, rm, self.seg(segment), (base + disp) & 0xFFFF

    def rm_read(self, decoded, width):
        mod, _, rm, segment, offset = decoded
        if mod == 3:
            return self.r16(rm) if width == 2 else self.r8(rm)
        value = yield from self.read(segment, offset, width)
        return value

    def rm_write(self, decoded, width, value):
        mod, _, rm, segment, offset = decoded
        if mod == 3:
            (self.w16 if width == 2 else self.w8)(rm, value)
            return
        yield from self.write(segment, offset, width, value)

    def reg_read(self, n, width):
        return self.r16(n) if width == 2 else self.r8(n)

    def reg_write(self, n, width, value):
        (self.w16 if width == 2 else self.w8)(n, value)

    # -- flags -------------------------------------------------------------

    def szp(self, value, width):
        mask = 0xFFFF if width == 2 else 0xFF
        value &= mask
        self.set_flag(Z, value == 0)
        self.set_flag(S, value & (0x8000 if width == 2 else 0x80))
        self.set_flag(P, PARITY[value & 0xFF])

    def alu(self, op, a, b, width):
        """ADD OR ADDC SUBC AND SUB XOR CMP (op 0-7). Returns the result."""
        mask = 0xFFFF if width == 2 else 0xFF
        sign = 0x8000 if width == 2 else 0x80
        if op in (0, 2):
            carry = self.flag(CY) if op == 2 else 0
            r = a + b + carry
            self.set_flag(CY, r > mask)
            self.set_flag(AC, ((a & 0xF) + (b & 0xF) + carry) > 0xF)
            self.set_flag(V, (~(a ^ b) & (a ^ r)) & sign)
        elif op in (3, 5, 7):
            borrow = self.flag(CY) if op == 3 else 0
            r = a - b - borrow
            self.set_flag(CY, r < 0)
            self.set_flag(AC, ((a & 0xF) - (b & 0xF) - borrow) < 0)
            self.set_flag(V, ((a ^ b) & (a ^ r)) & sign)
        else:
            r = {1: a | b, 4: a & b, 6: a ^ b}[op]
            self.set_flag(CY, 0)
            self.set_flag(V, 0)
            self.set_flag(AC, 0)
        r &= mask
        self.szp(r, width)
        return r

    # -- main loop ---------------------------------------------------------

    def run(self):
        yield ("flush", self.linear(self.seg(PS), self.pc))
        while True:
            yield from self.instruction()

    def instruction(self):
        self.seg_override = None
        self.rep = None
        start_pc = self.pc
        try:
            while True:
                op = yield from self.byte(operand=False)
                yield ("boundary",)
                if self.m.log is not None:
                    self.m.log.append((self.m.clock, (self.pc - 1) & 0xFFFF, op))
                if op in (0x26, 0x2E, 0x36, 0x3E):
                    self.seg_override = (op >> 3) & 3
                    yield from self.step("prefix")
                    continue
                if op in (0xF2, 0xF3, 0x64, 0x65):
                    self.rep = op
                    yield from self.step("prefix")
                    continue
                if op == 0xF0:
                    yield from self.step("prefix_buslock")
                    continue
                break
            yield from self.execute(op)
        except Trap as trap:
            yield from self.interrupt(trap.vector, start_pc)

    def interrupt(self, vector, return_pc=None):
        yield from self.step("trap_entry")
        psw = self.psw
        yield from self.push(psw)
        self.set_flag(IE, 0)
        self.set_flag(BRK, 0)
        yield from self.push(self.seg(PS))
        yield from self.push(self.pc if return_pc is None else return_pc)
        pc = yield from self.read(0, vector * 4, 2)
        ps = yield from self.read(0, vector * 4 + 2, 2)
        yield from self.step("trap_exit")
        yield from self.jump(pc, ps)

    # -- dispatch ----------------------------------------------------------

    def execute(self, op):
        if op < 0x40 and (op & 7) < 6:
            yield from self.op_alu(op)
        elif op < 0x40 and (op & 7) == 6:
            yield from self.op_seg_stack(op)
        elif op < 0x40 and (op & 7) == 7:
            if op == 0x0F:
                yield from self.op_0f()
            elif op in (0x07, 0x17, 0x1F):
                yield from self.op_seg_stack(op)
            else:
                yield from self.op_adjust(op)
        elif op < 0x50:
            yield from self.op_incdec_reg(op)
        elif op < 0x60:
            yield from self.op_pushpop_reg(op)
        else:
            handler = DISPATCH.get(op)
            if handler is None:
                raise Trap(6)
            yield from handler(self, op)

    # -- ALU ---------------------------------------------------------------

    def op_alu(self, op):
        kind = op >> 3
        form = op & 7
        width = 2 if op & 1 else 1
        if form in (4, 5):
            imm = (yield from self.word()) if width == 2 else (yield from self.byte())
            a = self.reg_read(AW, width)
            yield from self.step(f"alu_acc_imm{width}")
            r = self.alu(kind, a, imm, width)
            if kind != 7:
                self.reg_write(AW, width, r)
            return
        decoded = yield from self.modrm()
        mod, reg, rm, _, _ = decoded
        to_reg = form & 2
        if mod == 3:
            a = self.reg_read(reg if to_reg else rm, width)
            b = self.reg_read(rm if to_reg else reg, width)
            yield from self.step("alu_rr")
            r = self.alu(kind, a, b, width)
            if kind != 7:
                self.reg_write(reg if to_reg else rm, width, r)
            return
        m = yield from self.rm_read(decoded, width)
        g = self.reg_read(reg, width)
        if to_reg:
            yield from self.step("alu_rm")
            r = self.alu(kind, g, m, width)
            if kind != 7:
                self.reg_write(reg, width, r)
        else:
            yield from self.step("alu_mr" if kind != 7 else "cmp_mr")
            r = self.alu(kind, m, g, width)
            if kind != 7:
                yield from self.rm_write(decoded, width, r)

    def op_group1(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        mod, kind, rm, _, _ = decoded
        if op == 0x81:
            imm = yield from self.word()
        else:
            imm = yield from self.byte()
            if op == 0x83 and imm & 0x80:
                imm |= 0xFF00
        if mod == 3:
            a = self.reg_read(rm, width)
            yield from self.step(f"alu_r_imm{2 if op == 0x81 else 1}" if width == 2 else "alu_r_imm1")
            r = self.alu(kind, a, imm, width)
            if kind != 7:
                self.reg_write(rm, width, r)
            return
        a = yield from self.rm_read(decoded, width)
        yield from self.step("alu_m_imm" if kind != 7 else "cmp_m_imm")
        r = self.alu(kind, a, imm, width)
        if kind != 7:
            yield from self.rm_write(decoded, width, r)

    def op_test_rm(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        a = yield from self.rm_read(decoded, width)
        yield from self.step("test_rr" if decoded[0] == 3 else "test_mr")
        self.alu(4, a, self.reg_read(decoded[1], width), width)

    def op_test_acc(self, op):
        width = 2 if op & 1 else 1
        imm = (yield from self.word()) if width == 2 else (yield from self.byte())
        yield from self.step(f"alu_acc_imm{width}")
        self.alu(4, self.reg_read(AW, width), imm, width)

    def op_xch_rm(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        a = yield from self.rm_read(decoded, width)
        b = self.reg_read(decoded[1], width)
        yield from self.step("xch_rr" if decoded[0] == 3 else "xch_mr")
        if decoded[0] == 3:
            self.reg_write(decoded[2], width, b)
        else:
            yield from self.rm_write(decoded, width, b)
        self.reg_write(decoded[1], width, a)

    def op_xch_aw(self, op):
        n = op & 7
        a, b = self.r16(AW), self.r16(n)
        yield from self.step("xch_aw")
        self.w16(AW, b)
        self.w16(n, a)

    # -- moves -------------------------------------------------------------

    def op_mov_rm(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        mod, reg, rm, _, _ = decoded
        if mod == 3:
            yield from self.step("mov_rr")
            if op & 2:
                self.reg_write(reg, width, self.reg_read(rm, width))
            else:
                self.reg_write(rm, width, self.reg_read(reg, width))
            return
        if op & 2:
            value = yield from self.rm_read(decoded, width)
            yield from self.step("mov_load")
            self.reg_write(reg, width, value)
        else:
            yield from self.step("mov_store")
            yield from self.rm_write(decoded, width, self.reg_read(reg, width))

    def op_mov_seg(self, op):
        decoded = yield from self.modrm()
        mod, reg, rm, _, _ = decoded
        reg &= 3
        if op == 0x8C:
            if mod == 3:
                yield from self.step("mov_rr")
                self.w16(rm, self.seg(reg))
            else:
                yield from self.step("mov_store")
                yield from self.rm_write(decoded, 2, self.seg(reg))
        else:
            value = yield from self.rm_read(decoded, 2)
            yield from self.step("mov_rr" if mod == 3 else "mov_load")
            self.set_seg(reg, value)

    def op_lea(self, op):
        decoded = yield from self.modrm()
        yield from self.step("ldea")
        self.w16(decoded[1], decoded[4] if decoded[4] is not None else 0)

    def op_load_far(self, op):
        decoded = yield from self.modrm()
        mod, reg, _, segment, offset = decoded
        low = yield from self.read(segment, offset, 2)
        high = yield from self.read(segment, offset + 2, 2)
        yield from self.step("load_far")
        self.w16(reg, low)
        self.set_seg(DS1 if op == 0xC4 else DS0, high)

    def op_mov_acc_mem(self, op):
        width = 2 if op & 1 else 1
        offset = yield from self.word()
        segment = self.seg(self.seg_override if self.seg_override is not None else DS0)
        yield from self.step("ea", 1)
        if op < 0xA2:
            value = yield from self.read(segment, offset, width)
            yield from self.step("mov_load")
            self.reg_write(AW, width, value)
        else:
            yield from self.step("mov_store")
            yield from self.write(segment, offset, width, self.reg_read(AW, width))

    def op_mov_reg_imm(self, op):
        if op < 0xB8:
            imm = yield from self.byte()
            yield from self.step("mov_r8_imm")
            self.w8(op & 7, imm)
        else:
            imm = yield from self.word()
            yield from self.step("mov_r16_imm")
            self.w16(op & 7, imm)

    def op_mov_rm_imm(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        imm = (yield from self.word()) if width == 2 else (yield from self.byte())
        if decoded[0] == 3:
            yield from self.step("mov_r16_imm" if width == 2 else "mov_r8_imm")
            self.reg_write(decoded[2], width, imm)
        else:
            yield from self.step("mov_store_imm")
            yield from self.rm_write(decoded, width, imm)

    # -- inc / dec / unary -------------------------------------------------

    def _incdec(self, value, dec, width):
        carry = self.flag(CY)
        r = self.alu(5 if dec else 0, value, 1, width)
        self.set_flag(CY, carry)
        return r

    def op_incdec_reg(self, op):
        yield from self.step("incdec_r16")
        self.w16(op & 7, self._incdec(self.r16(op & 7), op & 8, 2))

    def op_group_fe(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        mod, kind, rm, segment, offset = decoded
        if kind < 2:
            value = yield from self.rm_read(decoded, width)
            yield from self.step("incdec_rm" if mod == 3 else "incdec_m")
            yield from self.rm_write(decoded, width, self._incdec(value, kind, width))
            return
        if width == 1:
            raise Trap(6)
        if kind == 2:                        # CALL near indirect
            target = yield from self.rm_read(decoded, 2)
            yield from self.step("call_indirect")
            yield from self.push(self.pc)
            yield from self.jump(target)
        elif kind == 3:                      # CALL far indirect
            pc = yield from self.read(segment, offset, 2)
            ps = yield from self.read(segment, offset + 2, 2)
            yield from self.step("call_far_indirect")
            yield from self.push(self.seg(PS))
            yield from self.push(self.pc)
            yield from self.jump(pc, ps)
        elif kind == 4:                      # BR near indirect
            target = yield from self.rm_read(decoded, 2)
            yield from self.step("br_indirect")
            yield from self.jump(target)
        elif kind == 5:                      # BR far indirect
            pc = yield from self.read(segment, offset, 2)
            ps = yield from self.read(segment, offset + 2, 2)
            yield from self.step("br_far_indirect")
            yield from self.jump(pc, ps)
        elif kind == 6:                      # PUSH rm
            value = yield from self.rm_read(decoded, 2)
            yield from self.step("push_rm")
            yield from self.push(value)
        else:
            raise Trap(6)

    def op_group_f6(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        mod, kind, rm, _, _ = decoded
        if kind in (0, 1):
            imm = (yield from self.word()) if width == 2 else (yield from self.byte())
            value = yield from self.rm_read(decoded, width)
            yield from self.step("test_r_imm" if mod == 3 else "test_m_imm")
            self.alu(4, value, imm, width)
            return
        value = yield from self.rm_read(decoded, width)
        mask = 0xFFFF if width == 2 else 0xFF
        if kind == 2:
            yield from self.step("unary_r" if mod == 3 else "unary_m")
            yield from self.rm_write(decoded, width, ~value & mask)
        elif kind == 3:
            yield from self.step("unary_r" if mod == 3 else "unary_m")
            r = self.alu(5, 0, value, width)
            self.set_flag(CY, value != 0)
            yield from self.rm_write(decoded, width, r)
        elif kind in (4, 5):
            yield from self.multiply(value, width, signed=kind == 5, memory=mod != 3)
        else:
            yield from self.divide(value, width, signed=kind == 7, memory=mod != 3)

    def multiply(self, value, width, signed, memory):
        bits = 8 * width
        a = self.reg_read(AW, width)
        if signed:
            sa = a - (1 << bits) if a >> (bits - 1) else a
            sb = value - (1 << bits) if value >> (bits - 1) else value
            product = sa * sb
            r = product & ((1 << (2 * bits)) - 1)
            low_half = r & ((1 << bits) - 1)
            high_half = r >> bits
            extra = 0
            if (a >> (bits - 1)) != (value >> (bits - 1)):
                extra = self.costs["mul_negate"] + (low_half == 0) + (low_half == 0 and high_half == 0)
            yield from self.step(f"mul{bits}" + ("_m" if memory else ""), extra)
            fits = -(1 << (bits - 1)) <= product < (1 << (bits - 1))
        else:
            r = a * value
            yield from self.step(f"mulu{bits}" + ("_m" if memory else ""))
            fits = r < (1 << bits)
        if width == 1:
            self.w16(AW, r & 0xFFFF)
        else:
            self.w16(AW, r & 0xFFFF)
            self.w16(DW, (r >> 16) & 0xFFFF)
        self.set_flag(CY, not fits)
        self.set_flag(V, not fits)

    def divide(self, value, width, signed, memory):
        bits = 8 * width
        if width == 1:
            dividend = self.r16(AW)
        else:
            dividend = (self.r16(DW) << 16) | self.r16(AW)
        extra = 0
        if value == 0:
            yield from self.step(f"div{bits}" + ("_m" if memory else ""))
            raise Trap(0)
        if signed:
            sd = dividend - (1 << (2 * bits)) if dividend >> (2 * bits - 1) else dividend
            sv = value - (1 << bits) if value >> (bits - 1) else value
            q = abs(sd) // abs(sv)
            if (sd < 0) != (sv < 0):
                q = -q
            rem = abs(sd) % abs(sv)
            if sd < 0:
                rem = -rem
                extra += self.costs["div_negate_dividend"]
            if (sd < 0) != (sv < 0):
                extra += self.costs["div_negate_quotient"]
            yield from self.step(f"div{bits}" + ("_m" if memory else ""), extra)
            if not -(1 << (bits - 1)) < q < (1 << (bits - 1)):
                raise Trap(0)
        else:
            q, rem = divmod(dividend, value)
            yield from self.step(f"divu{bits}" + ("_m" if memory else ""))
            if q >= (1 << bits):
                raise Trap(0)
        mask = (1 << bits) - 1
        if width == 1:
            self.w16(AW, ((rem & mask) << 8) | (q & mask))
        else:
            self.w16(AW, q & mask)
            self.w16(DW, rem & mask)

    # -- shifts ------------------------------------------------------------

    def op_shift(self, op):
        width = 2 if op & 1 else 1
        decoded = yield from self.modrm()
        mod, kind, rm, _, _ = decoded
        if op in (0xC0, 0xC1):
            count = yield from self.byte()
        elif op in (0xD0, 0xD1):
            count = 1
        else:
            count = self.r8(1)
        value = yield from self.rm_read(decoded, width)
        name = "shift_r" if mod == 3 else "shift_m"
        if op in (0xD2, 0xD3) and mod != 3:
            name = "shift_m_cl"
        yield from self.step(name, (self.costs["shift_per_bit"] * count + self.costs["shift_nonzero"])
                             if count else 0)
        r = self.shift(kind, value, count, width)
        yield from self.rm_write(decoded, width, r)

    def shift(self, kind, value, count, width):
        bits = 8 * width
        mask = (1 << bits) - 1
        sign = 1 << (bits - 1)
        if count == 0:
            return value
        cf = self.flag(CY)
        r = value
        for _ in range(count):
            if kind == 0:                                  # ROL
                cf = (r >> (bits - 1)) & 1
                r = ((r << 1) | cf) & mask
            elif kind == 1:                                # ROR
                cf = r & 1
                r = (r >> 1) | (cf << (bits - 1))
            elif kind == 2:                                # ROLC
                new = (r >> (bits - 1)) & 1
                r = ((r << 1) | cf) & mask
                cf = new
            elif kind == 3:                                # RORC
                new = r & 1
                r = (r >> 1) | (cf << (bits - 1))
                cf = new
            elif kind in (4, 6):                           # SHL
                cf = (r >> (bits - 1)) & 1
                r = (r << 1) & mask
            elif kind == 5:                                # SHR
                cf = r & 1
                r >>= 1
            else:                                          # SHRA
                cf = r & 1
                r = (r >> 1) | (r & sign)
        self.set_flag(CY, cf)
        if kind >= 4:
            self.szp(r, width)
        if kind in (0, 2, 4, 6):
            self.set_flag(V, bool(r & sign) != bool(cf))
        elif kind in (1, 3):
            self.set_flag(V, bool(r & sign) != bool(r & (sign >> 1)))
        elif kind == 5:
            self.set_flag(V, bool(value & sign) if count == 1 else 0)
        else:
            self.set_flag(V, 0)
        return r

    # -- stack -------------------------------------------------------------

    def op_pushpop_reg(self, op):
        n = op & 7
        if op < 0x58:
            value = self.r16(n)
            if n == SP:
                value = (value - 2) & 0xFFFF
            yield from self.step("push_r")
            yield from self.push(value)
        else:
            value = yield from self.pop()
            yield from self.step("pop_r")
            self.w16(n, value)

    def op_seg_stack(self, op):
        seg = (op >> 3) & 3
        if op & 1:
            value = yield from self.pop()
            yield from self.step("pop_seg")
            self.set_seg(seg, value)
        else:
            yield from self.step("push_seg")
            yield from self.push(self.seg(seg))

    def op_push_imm(self, op):
        if op == 0x68:
            value = yield from self.word()
        else:
            value = yield from self.byte()
            if value & 0x80:
                value |= 0xFF00
        yield from self.step("push_imm")
        yield from self.push(value)

    def op_pop_rm(self, op):
        decoded = yield from self.modrm()
        value = yield from self.pop()
        yield from self.step("pop_rm")
        yield from self.rm_write(decoded, 2, value)

    def op_pushf(self, op):
        yield from self.step("push_psw")
        yield from self.push(self.psw)

    def op_popf(self, op):
        value = yield from self.pop()
        yield from self.step("pop_psw")
        self.psw = (self.psw & 0xF000) | (value & 0x0FFF)

    def op_push_r(self, op):
        sp = self.r16(SP)
        yield from self.step("push_all")
        for n in (AW, CW, DW, BW, SP, BP, IX, IY):
            yield from self.push(sp if n == SP else self.r16(n))

    def op_pop_r(self, op):
        yield from self.step("pop_all")
        for n in (IY, IX, BP, SP, BW, DW, CW, AW):
            value = yield from self.pop()
            if n != SP:
                self.w16(n, value)

    def op_prepare(self, op):
        size = yield from self.word()
        level = (yield from self.byte()) & 0x1F
        yield from self.step("prepare")
        yield from self.push(self.r16(BP))
        frame = self.r16(SP)
        if level:
            for _ in range(level - 1):
                bp = (self.r16(BP) - 2) & 0xFFFF
                self.w16(BP, bp)
                value = yield from self.read(self.seg(SS), bp, 2)
                yield from self.step("prepare_level")
                yield from self.push(value)
            yield from self.push(frame)
        self.w16(BP, frame)
        self.w16(SP, (self.r16(SP) - size) & 0xFFFF)

    def op_dispose(self, op):
        self.w16(SP, self.r16(BP))
        value = yield from self.pop()
        yield from self.step("dispose")
        self.w16(BP, value)

    # -- control transfer ---------------------------------------------------

    def op_bcond(self, op):
        disp = yield from self.byte()
        disp = disp - 0x100 if disp & 0x80 else disp
        cond = self.condition(op & 0xF)
        yield from self.step("bcond")
        if cond:
            yield from self.step("branch_taken")
            yield from self.jump(self.pc + disp)

    def condition(self, n):
        f = self.flag
        result = {
            0: f(V), 1: not f(V), 2: f(CY), 3: not f(CY), 4: f(Z), 5: not f(Z),
            6: f(CY) or f(Z), 7: not (f(CY) or f(Z)), 8: f(S), 9: not f(S),
            10: f(P), 11: not f(P), 12: f(S) != f(V), 13: f(S) == f(V),
            14: f(Z) or f(S) != f(V), 15: not f(Z) and f(S) == f(V)}[n]
        return bool(result)

    def op_loop(self, op):
        disp = yield from self.byte()
        disp = disp - 0x100 if disp & 0x80 else disp
        if op == 0xE3:
            taken = self.r16(CW) == 0
            yield from self.step("bcwz")
        else:
            cw = (self.r16(CW) - 1) & 0xFFFF
            self.w16(CW, cw)
            taken = cw != 0
            if op == 0xE1:
                taken = taken and self.flag(Z)
            elif op == 0xE0:
                taken = taken and not self.flag(Z)
            yield from self.step("dbnz" if op == 0xE2 else "dbnz_cond")
        if taken:
            yield from self.step("branch_taken")
            yield from self.jump(self.pc + disp)

    def op_br_short(self, op):
        disp = yield from self.byte()
        disp = disp - 0x100 if disp & 0x80 else disp
        yield from self.step("br_short")
        yield from self.jump(self.pc + disp)

    def op_br_near(self, op):
        disp = yield from self.word()
        yield from self.step("br_near")
        yield from self.jump(self.pc + disp)

    def op_br_far(self, op):
        pc = yield from self.word()
        ps = yield from self.word()
        yield from self.step("br_far")
        yield from self.jump(pc, ps)

    def op_call_near(self, op):
        disp = yield from self.word()
        yield from self.step("call_near")
        yield from self.push(self.pc)
        yield from self.jump(self.pc + disp)

    def op_call_far(self, op):
        pc = yield from self.word()
        ps = yield from self.word()
        yield from self.step("call_far")
        yield from self.push(self.seg(PS))
        yield from self.push(self.pc)
        yield from self.jump(pc, ps)

    def op_ret(self, op):
        adjust = (yield from self.word()) if op in (0xC2, 0xCA) else 0
        pc = yield from self.pop()
        if op in (0xCA, 0xCB):
            ps = yield from self.pop()
            yield from self.step("ret_far")
            self.w16(SP, self.r16(SP) + adjust)
            yield from self.jump(pc, ps)
        else:
            yield from self.step("ret")
            self.w16(SP, self.r16(SP) + adjust)
            yield from self.jump(pc)

    def op_reti(self, op):
        pc = yield from self.pop()
        ps = yield from self.pop()
        psw = yield from self.pop()
        yield from self.step("reti")
        self.psw = psw
        yield from self.jump(pc, ps)

    def op_brk(self, op):
        if op == 0xCC:
            vector = 3
        elif op == 0xCE:
            yield from self.step("brkv")
            if not self.flag(V):
                return
            vector = 4
        else:
            vector = yield from self.byte()
        yield from self.interrupt(vector)

    def op_brkn(self, op):
        vector = yield from self.byte()
        yield from self.interrupt(vector)
        self.psw |= 0x8000

    def op_chkind(self, op):
        decoded = yield from self.modrm()
        _, reg, _, segment, offset = decoded
        low = yield from self.read(segment, offset, 2)
        high = yield from self.read(segment, offset + 2, 2)
        yield from self.step("chkind")
        value = self.r16(reg)
        signed = lambda x: x - 0x10000 if x & 0x8000 else x
        if not signed(low) <= signed(value) <= signed(high):
            raise Trap(5)

    # -- strings -----------------------------------------------------------

    def _string_step(self, op, width):
        dirn = -width if self.flag(DIR) else width
        src_seg = self.seg(self.seg_override if self.seg_override is not None else DS0)
        if op in (0xA4, 0xA5):
            value = yield from self.read(src_seg, self.r16(IX), width)
            yield from self.step("movbk")
            yield from self.write(self.seg(DS1), self.r16(IY), width, value)
            self.w16(IX, self.r16(IX) + dirn)
            self.w16(IY, self.r16(IY) + dirn)
        elif op in (0xAA, 0xAB):
            yield from self.step("stm")
            yield from self.write(self.seg(DS1), self.r16(IY), width, self.reg_read(AW, width))
            self.w16(IY, self.r16(IY) + dirn)
        elif op in (0xAC, 0xAD):
            value = yield from self.read(src_seg, self.r16(IX), width)
            yield from self.step("ldm")
            self.reg_write(AW, width, value)
            self.w16(IX, self.r16(IX) + dirn)
        elif op in (0xA6, 0xA7):
            a = yield from self.read(src_seg, self.r16(IX), width)
            b = yield from self.read(self.seg(DS1), self.r16(IY), width)
            yield from self.step("cmpbk")
            self.alu(7, a, b, width)
            self.w16(IX, self.r16(IX) + dirn)
            self.w16(IY, self.r16(IY) + dirn)
        elif op in (0xAE, 0xAF):
            b = yield from self.read(self.seg(DS1), self.r16(IY), width)
            yield from self.step("cmpm")
            self.alu(7, self.reg_read(AW, width), b, width)
            self.w16(IY, self.r16(IY) + dirn)
        elif op in (0x6C, 0x6D):
            value = yield from self.read(0, self.r16(DW), width, space="io")
            yield from self.step("inm")
            yield from self.write(self.seg(DS1), self.r16(IY), width, value)
            self.w16(IY, self.r16(IY) + dirn)
        elif op in (0x6E, 0x6F):
            value = yield from self.read(src_seg, self.r16(IX), width)
            yield from self.step("outm")
            yield from self.write(0, self.r16(DW), width, value, space="io")
            self.w16(IX, self.r16(IX) + dirn)

    def op_string(self, op):
        width = 2 if op & 1 else 1
        if op in (0x6C, 0x6D, 0x6E, 0x6F) and not self.flag(BRKI):
            raise Trap(19)
        if self.rep is None:
            yield from self.step("string_single")
            yield from self._string_step(op, width)
            return
        yield from self.step("rep_start")
        while self.r16(CW):
            yield from self._string_step(op, width)
            self.w16(CW, self.r16(CW) - 1)
            yield from self.step("rep_iteration")
            if op in (0xA6, 0xA7, 0xAE, 0xAF):
                if self.rep in (0xF3,) and not self.flag(Z):
                    break
                if self.rep in (0xF2,) and self.flag(Z):
                    break
            if op in (0xA6, 0xA7, 0xAE, 0xAF) and self.rep == 0x65 and not self.flag(CY):
                break
            if op in (0xA6, 0xA7, 0xAE, 0xAF) and self.rep == 0x64 and self.flag(CY):
                break
        yield from self.step("rep_end")

    # -- I/O ---------------------------------------------------------------

    def _io_check(self):
        if not self.flag(BRKI):
            raise Trap(19)

    def op_in(self, op):
        width = 2 if op & 1 else 1
        if op in (0xE4, 0xE5):
            port = yield from self.byte()
            yield from self.step("in_imm")
        else:
            port = self.r16(DW)
            yield from self.step("in_dw")
        self._io_check()
        value = yield from self.read(0, port, width, space="io")
        self.reg_write(AW, width, value)

    def op_out(self, op):
        width = 2 if op & 1 else 1
        if op in (0xE6, 0xE7):
            yield from self.step("out_imm")
            port = yield from self.byte()
            yield from self.step("out_imm_post")
        else:
            port = self.r16(DW)
            yield from self.step("out_dw")
        self._io_check()
        yield from self.write(0, port, width, self.reg_read(AW, width), space="io")

    # -- flags and misc ----------------------------------------------------

    def op_flagop(self, op):
        yield from self.step("flag_op")
        if op == 0xF5:
            self.set_flag(CY, not self.flag(CY))
        elif op in (0xF8, 0xF9):
            self.set_flag(CY, op & 1)
        elif op in (0xFA, 0xFB):
            self.set_flag(IE, op & 1)
        elif op in (0xFC, 0xFD):
            self.set_flag(DIR, op & 1)

    def op_sahf(self, op):
        yield from self.step("sahf")
        self.psw = (self.psw & 0xFF00) | self.r8(4)

    def op_lahf(self, op):
        yield from self.step("lahf")
        self.w8(4, self.psw & 0xFF)

    def op_cbw(self, op):
        if op == 0x98:
            yield from self.step("cvtbw")
            al = self.r8(0)
            self.w16(AW, al | (0xFF00 if al & 0x80 else 0))
        else:
            yield from self.step("cvtwl")
            self.w16(DW, 0xFFFF if self.r16(AW) & 0x8000 else 0)

    def op_nop(self, op):
        yield from self.step("nop")

    def op_halt(self, op):
        yield from self.step("halt")
        yield ("halt",)

    def op_trans(self, op):
        segment = self.seg(self.seg_override if self.seg_override is not None else DS0)
        value = yield from self.read(segment, self.r16(BW) + self.r8(0), 1)
        yield from self.step("trans")
        self.w8(0, value)

    def op_adjust(self, op):
        al, ah = self.r8(0), self.r8(4)
        if op == 0x27 or op == 0x2F:                     # ADJ4A / ADJ4S
            yield from self.step("adj4")
            old_al, old_cy = al, self.flag(CY)
            sub = op == 0x2F
            if (al & 0xF) > 9 or self.flag(AC):
                al = (al - 6) if sub else (al + 6)
                self.set_flag(AC, 1)
            else:
                self.set_flag(AC, 0)
            if old_al > 0x99 or old_cy:
                al = (al - 0x60) if sub else (al + 0x60)
                self.set_flag(CY, 1)
            else:
                self.set_flag(CY, 0)
            self.w8(0, al)
            self.szp(al, 1)
        else:                                            # ADJBA / ADJBS
            yield from self.step("adjb")
            sub = op == 0x3F
            if (al & 0xF) > 9 or self.flag(AC):
                al = (al - 6) if sub else (al + 6)
                ah = (ah - 1) if sub else (ah + 1)
                self.set_flag(AC, 1)
                self.set_flag(CY, 1)
            else:
                self.set_flag(AC, 0)
                self.set_flag(CY, 0)
            self.w8(0, al & 0x0F)
            self.w8(4, ah)

    def op_aam(self, op):
        base = yield from self.byte()
        al = self.r8(0)
        if op == 0xD4:
            yield from self.step("cvtbd")
            if base == 0:
                raise Trap(0)
            self.w8(4, al // base)
            self.w8(0, al % base)
            self.szp(al % base, 1)
        else:
            yield from self.step("cvtdb")
            value = (al + self.r8(4) * base) & 0xFF
            self.w16(AW, value)
            self.szp(value, 1)

    # -- 0F page ---------------------------------------------------------

    def op_0f(self):
        second = yield from self.byte(operand=False)
        if 0x10 <= second <= 0x1F:
            yield from self.op_bit(second)
        elif second in (0x20, 0x22, 0x26):
            yield from self.op_bcd_string(second)
        elif second in (0x28, 0x2A):
            yield from self.op_rol4(second)
        elif second in (0x31, 0x33, 0x39, 0x3B):
            yield from self.op_bitfield(second)
        elif second == 0x9E:
            yield from self.step("stop")
            yield ("halt",)
        elif second == 0x92:
            yield from self.step("fint")
        else:
            raise Trap(6)

    def op_bit(self, second):
        width = 2 if second & 1 else 1
        decoded = yield from self.modrm()
        if second & 8:
            bit = yield from self.byte()
        else:
            bit = self.r8(1)
        bit &= 15 if width == 2 else 7
        value = yield from self.rm_read(decoded, width)
        kind = (second >> 1) & 3                 # 0 TEST1, 1 CLR1, 2 SET1, 3 NOT1
        memory = decoded[0] != 3
        name = ("test1", "clr1", "set1", "not1")[kind] + ("_m" if memory else "_r") + \
               ("_imm" if second & 8 else "_cl")
        yield from self.step(name)
        if kind == 0:
            self.set_flag(Z, not (value >> bit) & 1)
            self.set_flag(CY, 0)
            self.set_flag(V, 0)
            return
        if kind == 1:
            value &= ~(1 << bit)
        elif kind == 2:
            value |= 1 << bit
        else:
            value ^= 1 << bit
        yield from self.rm_write(decoded, width, value)

    def op_bcd_string(self, second):
        count = (self.r8(1) + 1) // 2
        src_seg = self.seg(self.seg_override if self.seg_override is not None else DS0)
        carry = 0
        zero = True
        yield from self.step("bcd4s_start")
        for i in range(count):
            a = yield from self.read(self.seg(DS1), self.r16(IY) + i, 1)
            b = yield from self.read(src_seg, self.r16(IX) + i, 1)
            if second == 0x20:
                lo = (a & 0xF) + (b & 0xF) + carry
                c1 = lo > 9
                lo = (lo - 10 if c1 else lo) & 0xF
                hi = (a >> 4) + (b >> 4) + c1
                carry = hi > 9
                hi = (hi - 10 if carry else hi) & 0xF
            else:
                lo = (a & 0xF) - (b & 0xF) - carry
                c1 = lo < 0
                lo = (lo + 10 if c1 else lo) & 0xF
                hi = (a >> 4) - (b >> 4) - c1
                carry = hi < 0
                hi = (hi + 10 if carry else hi) & 0xF
            r = (hi << 4) | lo
            zero = zero and r == 0
            yield from self.step("bcd4s_digit_pair")
            if second != 0x26:
                yield from self.write(self.seg(DS1), self.r16(IY) + i, 1, r)
        self.set_flag(CY, carry)
        self.set_flag(Z, zero)

    def op_rol4(self, second):
        decoded = yield from self.modrm()
        value = yield from self.rm_read(decoded, 1)
        al = self.r8(0)
        memory = decoded[0] != 3
        if second == 0x28:
            yield from self.step("rol4" + ("_m" if memory else "_r"))
            r = ((value << 4) | (al & 0xF)) & 0xFF
            self.w8(0, (al & 0xF0) | (value >> 4))
        else:
            yield from self.step("ror4" + ("_m" if memory else "_r"))
            r = ((al & 0xF) << 4) | (value >> 4)
            self.w8(0, (al & 0xF0) | (value & 0xF))
        yield from self.rm_write(decoded, 1, r)

    def op_bitfield(self, second):
        decoded = yield from self.modrm()
        mod, reg, rm, _, _ = decoded
        if second in (0x39, 0x3B):
            width = (yield from self.byte()) & 0xF
            offset_reg = rm
        else:
            width = self.r8(reg) & 0xF
            offset_reg = rm
        offset = self.r8(offset_reg) & 0xF
        cross = offset + width >= 16
        boundary = offset + width == 15
        if second in (0x33, 0x3B):                       # EXT
            if cross:
                n = self.costs["ext_cross"] + 2 * offset - (1 if width == 15 else 0)
            elif boundary and offset == 0:
                n = self.costs["ext_full"]
            else:
                n = self.costs["ext_base"] - 2 * offset - 4 * width
            if second == 0x33:
                n += self.costs["bitfield_cl_adjust"]
            segment, ix = self.seg(DS0), self.r16(IX)
            low = yield from self.read(segment, ix, 2)
            high = 0
            if cross:
                high = yield from self.read(segment, ix + 2, 2)
            yield from self.clocks(n)
            bits = ((high << 16) | low) >> offset
            self.w16(AW, bits & ((1 << (width + 1)) - 1))
            new = offset + width + 1
            if new >= 16:
                self.w16(IX, ix + 2)
            self.w8(offset_reg, new & 0xF)
        else:                                            # INS
            if cross:
                n = self.costs["ins_cross"] + 4 * (offset + width - 16)
            elif boundary:
                n = self.costs["ins_boundary"] - (2 if offset == 0 else 0)
            else:
                n = self.costs["ins_base"] - (2 if offset == 0 else 0)
            if second == 0x31:
                n += self.costs["bitfield_cl_adjust"]
            segment, iy = self.seg(DS1), self.r16(IY)
            field = self.r16(AW) & ((1 << (width + 1)) - 1)
            combined = yield from self.read(segment, iy, 2)
            mask = ((1 << (width + 1)) - 1) << offset
            if cross:
                combined |= (yield from self.read(segment, iy + 2, 2)) << 16
            combined = (combined & ~mask) | (field << offset)
            yield from self.clocks(n)
            yield from self.write(segment, iy, 2, combined & 0xFFFF)
            if cross:
                yield from self.write(segment, iy + 2, 2, combined >> 16)
            new = offset + width + 1
            if new >= 16:
                self.w16(IY, iy + 2)
            self.w8(offset_reg, new & 0xF)

    # -- far pointers / misc remaining ------------------------------------

    def op_xlat_placeholder(self, op):
        raise Trap(6)

    def op_salc_undefined(self, op):
        raise Trap(6)

    def op_fpo(self, op):
        yield from self.modrm()
        raise Trap(7)

    def op_fpo2(self, op):
        yield from self.byte()
        raise Trap(7)


DISPATCH = {}
for _op in (0x80, 0x81, 0x82, 0x83):
    DISPATCH[_op] = EU.op_group1
for _op in (0x84, 0x85):
    DISPATCH[_op] = EU.op_test_rm
for _op in (0x86, 0x87):
    DISPATCH[_op] = EU.op_xch_rm
for _op in range(0x88, 0x8C):
    DISPATCH[_op] = EU.op_mov_rm
DISPATCH[0x8C] = DISPATCH[0x8E] = EU.op_mov_seg
DISPATCH[0x8D] = EU.op_lea
DISPATCH[0x8F] = EU.op_pop_rm
DISPATCH[0x90] = EU.op_nop
for _op in range(0x91, 0x98):
    DISPATCH[_op] = EU.op_xch_aw
DISPATCH[0x98] = DISPATCH[0x99] = EU.op_cbw
DISPATCH[0x9A] = EU.op_call_far
DISPATCH[0x9B] = EU.op_nop          # POLL: P14 reads low unless an input; treated as NOP for now
DISPATCH[0x9C] = EU.op_pushf
DISPATCH[0x9D] = EU.op_popf
DISPATCH[0x9E] = EU.op_sahf
DISPATCH[0x9F] = EU.op_lahf
for _op in range(0xA0, 0xA4):
    DISPATCH[_op] = EU.op_mov_acc_mem
for _op in (0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF, 0x6C, 0x6D, 0x6E, 0x6F):
    DISPATCH[_op] = EU.op_string
DISPATCH[0xA8] = DISPATCH[0xA9] = EU.op_test_acc
for _op in range(0xB0, 0xC0):
    DISPATCH[_op] = EU.op_mov_reg_imm
for _op in (0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3):
    DISPATCH[_op] = EU.op_shift
for _op in (0xC2, 0xC3, 0xCA, 0xCB):
    DISPATCH[_op] = EU.op_ret
DISPATCH[0xC4] = DISPATCH[0xC5] = EU.op_load_far
DISPATCH[0xC6] = DISPATCH[0xC7] = EU.op_mov_rm_imm
DISPATCH[0xC8] = EU.op_prepare
DISPATCH[0xC9] = EU.op_dispose
for _op in (0xCC, 0xCD, 0xCE):
    DISPATCH[_op] = EU.op_brk
DISPATCH[0xCF] = EU.op_reti
DISPATCH[0xD4] = DISPATCH[0xD5] = EU.op_aam
DISPATCH[0xD7] = EU.op_trans
for _op in range(0xD8, 0xE0):
    DISPATCH[_op] = EU.op_fpo
DISPATCH[0x66] = DISPATCH[0x67] = EU.op_fpo
for _op in range(0xE0, 0xE3):
    DISPATCH[_op] = EU.op_loop
DISPATCH[0xE3] = EU.op_loop
DISPATCH[0xE4] = DISPATCH[0xE5] = DISPATCH[0xEC] = DISPATCH[0xED] = EU.op_in
DISPATCH[0xE6] = DISPATCH[0xE7] = DISPATCH[0xEE] = DISPATCH[0xEF] = EU.op_out
DISPATCH[0xE8] = EU.op_call_near
DISPATCH[0xE9] = EU.op_br_near
DISPATCH[0xEA] = EU.op_br_far
DISPATCH[0xEB] = EU.op_br_short
DISPATCH[0xF4] = EU.op_halt
for _op in (0xF5, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD):
    DISPATCH[_op] = EU.op_flagop
DISPATCH[0xF6] = DISPATCH[0xF7] = EU.op_group_f6
DISPATCH[0xFE] = DISPATCH[0xFF] = EU.op_group_fe
for _op in range(0x70, 0x80):
    DISPATCH[_op] = EU.op_bcond
DISPATCH[0x60] = EU.op_push_r
DISPATCH[0x61] = EU.op_pop_r
DISPATCH[0x62] = EU.op_chkind
DISPATCH[0x63] = EU.op_brkn
DISPATCH[0x68] = DISPATCH[0x6A] = EU.op_push_imm


def _imul(self, op):
    decoded = yield from self.modrm()
    value = yield from self.rm_read(decoded, 2)
    if op == 0x69:
        imm = yield from self.word()
    else:
        imm = yield from self.byte()
        if imm & 0x80:
            imm |= 0xFF00
    sa = value - 0x10000 if value & 0x8000 else value
    sb = imm - 0x10000 if imm & 0x8000 else imm
    product = sa * sb
    r = product & 0xFFFFFFFF
    extra = 0
    if (value >> 15) != (imm >> 15):
        extra = self.costs["mul_negate"] + ((r & 0xFFFF) == 0) + (r == 0)
    yield from self.step("mul_imm", extra)
    self.w16(decoded[1], r & 0xFFFF)
    fits = -0x8000 <= product < 0x8000
    self.set_flag(CY, not fits)
    self.set_flag(V, not fits)


DISPATCH[0x69] = DISPATCH[0x6B] = _imul
