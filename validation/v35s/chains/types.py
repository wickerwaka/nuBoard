"""Shared data types of the chain suite (the interface acquire.py codes against)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CODE_SEGMENT = 0x1000
CODE_BASE = CODE_SEGMENT << 4          # 0x10000
DATA_FILL = (0x0800, 0x0800)           # address, length of the 0x90 fill
# Memory waits only, I/O held at 0 waits. The F0w board run showed WTC bits
# 1:0 (field 0) govern block-0 memory (code and data; 2 gave 5-clock cycles)
# and bits 15:14 (field 7) govern I/O, independently; no other field affected
# either. Keeping I/O at 0 waits gives the OUT markers a constant 3-clock bus
# occupancy while memory waits vary.
WTC_FOR_WAITS = {0: 0x0000, 1: 0x0001, 2: 0x0002}
WTC_IO_SHIFT = 14                      # field 7: I/O waits
PRC_FX2 = 0x4C
RFM_OFF = 0xEC
RFM_ON = 0xFC
RFM_RFEN = 0x10                        # RFM bit 4: refresh enable (FCh on, ECh off)


def refresh_on(rfm: int) -> bool:
    return bool(rfm & RFM_RFEN)


def rfm_writes(chain) -> list:
    """(WP23, F17) (instr index, RFM value) of every internal RFM write in the chain, in
    chain order (forms.Form.rfm)."""
    from .forms import FORMS
    out = []
    for k, instr in enumerate(chain.instrs):
        form = FORMS.get(instr.form) if instr.role == "x" else None
        if form is not None and form.rfm is not None:
            out.append((k, form.rfm))
    return out


def refresh_any(chain) -> bool:
    """Refresh is on at some point of the chain: from the prelude (chain.rfm) or after an
    RFM write in the chain (F17)."""
    return refresh_on(chain.rfm) or any(refresh_on(v) for _, v in rfm_writes(chain))


def refresh_length(rfm: int) -> int:
    """A refresh cycle's clocks: 3 + RFM.RFW (bits 3-2), RFW 3 as 2 (F13 series R: F0h 3,
    F4h 4, F8h and FCh 5 at every WTC setting)."""
    return 3 + min((rfm >> 2) & 3, 2)


def refresh_rft(rfm: int) -> int:
    """RFM.RFT (bits 1-0), the refresh interval field: 16 << RFT clocks per the
    bus-timing probe (docs/v35s-bus-timing.md; F13 series R)."""
    return rfm & 0x03
TICKS_PER_CLOCK = 8


@dataclass
class Instr:
    offset: int            # byte offset from the first chain byte (the PAD or LS)
    code: bytes
    form: str              # catalog form name, or block name ("PAD","LS","M","D","END")
    role: str              # "pad" | "ls" | "marker" | "drain" | "x" | "end"
    marker_id: int | None = None   # 0,1,2,3 for markers
    index: int | None = None       # position of this X within the chain body (0-based)


@dataclass
class Chain:
    id: str                # unique, filesystem-safe, e.g. "F3-shl_cl16-k2-pE-w0"
    family: str            # "F0","F0w","F1",...,"F8"
    knobs: dict            # JSON-serialisable description of the varied knobs
    waits: int             # 0, 1 or 2 (memory waits; -1 for F0w where wtc is explicit)
    parity: str            # "even" | "odd": linear parity of the first byte after the first LS
    marker_kind: str       # "out" | "push" | "store"
    instrs: list[Instr]
    regs: dict             # register presets, NEC names
    wtc: int
    rfm: int = RFM_OFF
    prc: int = PRC_FX2
    # (WP24, F18) the prelude's last instruction, directly before the PAD / first LS: None
    # (the prelude ends with MOV AW,imm16), "push" (PUSH AW, the stack write at SP 0F00h - 2
    # = 0EFEh; SP is 0EFEh at the chain's start) or "out" (OUT 20h,AL). Part of the prelude
    # (image.prelude_source), not of the chain: clock 0 is still the fetch of the word
    # holding the chain's first byte, and normalize finds the marker's cycle in the trace
    # before or after clock 0 (Normalized.t_pre_marker)
    prelude_marker: str | None = None

    def to_json(self) -> dict:
        d = asdict(self)
        if d.get("prelude_marker") is None:
            d.pop("prelude_marker", None)     # every chain before F18: the JSON as before
        for instr in d["instrs"]:
            instr["code"] = instr["code"].hex()
        return d

    @classmethod
    def from_json(cls, d) -> "Chain":
        d = dict(d)
        d["instrs"] = [Instr(**{**i, "code": bytes.fromhex(i["code"])}) for i in d["instrs"]]
        d["knobs"] = dict(d["knobs"])
        d["regs"] = dict(d["regs"])
        return cls(**d)

    @property
    def code(self) -> bytes:
        return b"".join(i.code for i in self.instrs)


@dataclass
class Built:
    chain: Chain
    image: dict            # {linear_address: bytes}: code, reset vector, vectors, data fill
    code: bytes            # the whole code at CODE_BASE (prelude + chain)
    chain_base: int        # linear address of the first chain byte
    image_sha256: str
