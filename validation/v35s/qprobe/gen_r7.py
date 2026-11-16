"""Round 7: small follow-ups of round 5's reading (one question each)."""

from .gen import INC, M1, NOP, RI, RR, SLOW, q, train

M1W = bytes([0xEF])


def round7():
    v = []
    # the END's OUT DW,AW is one clock later than the model's: is it the changed DW value
    # (fw-dw wrote the value DW already held), the word form after MOV DW,imm16, or the port?
    v.append(("fx-dw22", [q([0xBA, 0x22, 0x00], "mov_dw")]))           # M1 goes to port 22h
    v.append(("fx-dw20w", ([q([0xBA, 0x20, 0x00], "mov_dw")], M1W)))
    v.append(("fx-dw120", [q([0xBA, 0x20, 0x01], "mov_dw")]))          # M1 goes to port 120h
    v.append(("fx-dw22w", ([q([0xBA, 0x22, 0x00], "mov_dw")], M1W)))
    # ... or the HALT behind it, or port FF00h itself: the program ends inside the body
    ff = q([0xBA, 0x00, 0xFF], "mov_dw")
    v.append(("fy-h", [ff, q([0xEE], "out"), q([0xF4], "halt")]))
    v.append(("fy-nh", [ff, q([0xEE], "out"), q(NOP, "nop"), q([0xF4], "halt")]))
    v.append(("fy-wh", [ff, q([0xEF], "outw"), q([0xF4], "halt")]))
    return v


ROUNDS = {"r7": round7}
