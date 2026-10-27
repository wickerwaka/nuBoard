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
    disp: int = 0                # (WP27) displacement bytes after the ModR/M byte (mod 01: 1,
                                 # mod 10 and the direct mod 00 rm 110: 2)


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
            return Op(length=length, cls="shift_cl", count=regs["CW"] & 0x1F, **base)
        cls = "rmw"                         # (WP19) SHL [BW],CL: a shift by CL on memory
        base["count"] = regs["CW"] & 0x1F
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
    else:
        raise ValueError(f"opcode {op:02X} at chain offset {k} is not in the catalog")
    return Op(length=length, cls=cls, **base)


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
            n = 1 if o == 0xD1 else (regs["CW"] & 0x1F if o == 0xD3 else code[k + 2])
            regs[REG16[rm]] = (regs[REG16[rm]] << n) & 0xFFFF
        elif o == 0xF7 and reg == 4:
            p = regs["AW"] * src
            regs["AW"], regs["DW"] = p & 0xFFFF, (p >> 16) & 0xFFFF
        elif o == 0xF7 and reg == 6 and src:
            q, r = divmod((regs["DW"] << 16) | regs["AW"], src)
            regs["AW"], regs["DW"] = q & 0xFFFF, r & 0xFFFF
        elif o == 0x86:
            _set8(regs, reg, FILL_WORD & 0xFF if mod != 3 else 0)
    if op.cls in ("push", "push_mem"):
        regs["SP"] = (regs["SP"] - 2) & 0xFFFF
    if op.cls in ("pop", "pop_mem"):
        regs["SP"] = (regs["SP"] + 2) & 0xFFFF


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
        k += op.length
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
    if cls in ("load", "load_alu"):
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
    if cls == "push":
        return [("data", "write", op.stack[1], 2, c("setup")), ("clocks", c("post"))]
    if cls == "pop":
        return [("data", "read", op.stack[0], 2, c("setup")), ("clocks", c("exec"))]
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
