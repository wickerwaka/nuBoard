"""Timing parameters of the V35S model, in CPU clocks unless stated.

Every value here is fitted to silicon (validation/v35s/fit.py) or comes
straight from a measurement in docs/v35s-eu-timing.md. Execution steps are
named after the instruction class that spends them; the bus unit adds its
own cycles, so a step is what the EU spends beyond waiting for the bus.
"""

import json
import os

COSTS = {
    # Bus unit and queue.
    "queue_words": 3,                   # prefetch queue word slots, a fetch in flight included
    "word_load": 2,                     # EU clocks to move the head queue word into its word register
    "fetch_data_delay": 0,              # clocks from the end of B3 until the EU can take the bytes
    # Microcode routines (opcode, 0F xx as 0x0Fxx, "r"/"m" for register or
    # memory ModR/M forms) whose word loads hide one clock: at the end, the
    # load of the next opcode's word overlaps the routine's last clock; in the
    # middle, an operand word's load starts a clock before the byte is read.
    # Derived from the A6 odd-minus-even costs (validation/v35s/fit_hide.py).
    "end_hide": {'23m', '2Bm', '2m', '39m', '3Bm', '3m', '62m', '69r', '83m', '8Am', '8Bm', 'D2r',
                 'D3r', 'F12r', 'F13r', 'F28r', 'F2Ar', 0x27, 0x2F, 0x37, 0x3F, 0x40, 0x48,
                 0x61, 0x99, 0xA4, 0xA5, 0xA6, 0xA7, 0xAC, 0xAD, 0xCE, 0xE4, 0xE5, 0xE6, 0xE7,
                 0xEC, 0xED, 0xEF, 0xF5, 0xF8, 0xF9, 0xFC, 0xFD},
    "mid_hide": {'83m', '83r', 0x85, 0xD5},
    "io_recovery": 1,                   # idle clocks after an I/O cycle before the next cycle
    "write_posted": 1,                  # 1: the EU hands a write to the bus unit and continues
    "write_post_clocks": 1,             # EU clocks spent handing over a posted write
    "eu_after_read": 0,
    "eu_after_write": 0,
    "reset_first_fetch_states": 25,     # fX/8 states after /RESET rises
    "reset_first_refresh_states": 15,
    "refresh_tick_offset": 3,           # /REFRQ falls this many eighths of a state into B1
    "internal_access": 3,
    "ramen_write": 3,

    # Decode.
    "prefix": 2,
    "prefix_buslock": 1,
    "ea": 0,

    # ALU and moves (register forms are the measured totals).
    "alu_rr": 1, "alu_rm": 5, "alu_mr": 3, "cmp_mr": 7,
    "alu_acc_imm1": 4, "alu_acc_imm2": 4,
    "alu_r_imm1": 4, "alu_r_imm2": 3, "alu_m_imm": 5, "cmp_m_imm": 9,
    "test_rr": 4, "test_mr": 7, "test_r_imm": 8, "test_m_imm": 5,
    "xch_rr": 1, "xch_mr": 5, "xch_aw": 3,
    "mov_rr": 3, "mov_load": 4, "mov_store": 1, "mov_store_imm": 2,
    "mov_r8_imm": 4, "mov_r16_imm": 7,
    "ldea": 2, "load_far": 4,
    "incdec_r16": 2, "incdec_rm": 4, "incdec_m": 6,
    "unary_r": 4, "unary_m": 6,

    # Multiply and divide (see docs/v35s-eu-timing.md).
    "mulu8": 24, "mulu16": 32, "mul8": 35, "mul16": 42, "mul_imm": 38,
    "mulu8_m": 26, "mulu16_m": 34, "mul8_m": 37, "mul16_m": 44,
    "mul_negate": 8,
    "divu8": 34, "divu16": 40, "div8": 53, "div16": 61,
    "divu8_m": 33, "divu16_m": 41, "div8_m": 52, "div16_m": 60,
    "div_negate_dividend": 7, "div_negate_quotient": 2,

    # Shifts: 10 for a count of 0, 12 + 2n otherwise.
    "shift_r": 10, "shift_m": 7, "shift_m_cl": 11,
    "shift_per_bit": 2, "shift_nonzero": 2,

    # Stack.
    "push_r": 3, "pop_r": 7, "push_seg": 5, "pop_seg": 8, "push_imm": 8,
    "push_rm": 9, "pop_rm": 7, "push_psw": 4, "pop_psw": 9,
    "push_all": 18, "pop_all": 18, "prepare": 24, "prepare_level": 14, "dispose": 7,

    # Control transfer (EU part; the refill is the bus unit's).
    "bcond": 10, "branch_taken": 9, "bcwz": 8, "dbnz": 11, "dbnz_cond": 8,
    "br_short": 15, "br_near": 15, "br_far": 12, "br_indirect": 17, "br_far_indirect": 10,
    "call_near": 20, "call_far": 24, "call_indirect": 20, "call_far_indirect": 14,
    "ret": 18, "ret_far": 14, "reti": 28, "brkv": 6, "chkind": 18,
    "trap_entry": 25, "trap_exit": 12,

    # Strings.
    "string_single": 6, "movbk": 10, "stm": 2, "ldm": 4, "cmpbk": 13, "cmpm": 8,
    "inm": 6, "outm": 6, "rep_start": 10, "rep_iteration": 4, "rep_end": 2,

    # I/O.
    "in_imm": 11, "in_dw": 8, "out_imm": 6, "out_imm_post": 1, "out_dw": 2,

    # Misc.
    "flag_op": 2, "sahf": 3, "lahf": 3, "cvtbw": 2, "cvtwl": 9,
    "nop": 3, "halt": 2, "trans": 7,
    "adj4": 10, "adjb": 17, "cvtbd": 20, "cvtdb": 19,

    # 0F page.
    "test1_r_cl": 5, "test1_r_imm": 5, "clr1_r_cl": 6, "clr1_r_imm": 5,
    "set1_r_cl": 5, "set1_r_imm": 5, "not1_r_cl": 5, "not1_r_imm": 5,
    "test1_m_cl": 8, "test1_m_imm": 4, "clr1_m_cl": 8, "clr1_m_imm": 3,
    "set1_m_cl": 7, "set1_m_imm": 2, "not1_m_cl": 7, "not1_m_imm": 2,
    "bcd4s_start": 15, "bcd4s_digit_pair": 23,
    "rol4_r": 16, "ror4_r": 20, "rol4_m": 13, "ror4_m": 17,
    "ext_base": 107, "ext_full": 43, "ext_cross": 61,
    "ins_base": 94, "ins_boundary": 86, "ins_cross": 128,
    "bitfield_cl_adjust": -1,
    "stop": 2, "fint": 2,
}

# The queue models (docs/v35s-core-model.md). "iwr": the EU moves the head
# queue word into a word register, freeing its slot. "consume": a word slot
# frees when all its bytes have been consumed, and operand bytes are consumed
# at their micro-step (operand_at clocks after the opcode).
COSTS["queue_model"] = "iwr"
COSTS["fetch_request"] = ""                  # "": fetch whenever a slot is free; "take" / "opcode":
                                             # only on a request the EU issues as it takes a queue byte / an opcode;
                                             # "ask": as it asks for an opcode, before the byte arrives
COSTS["fetch_grant"] = "free"                # a request grants every free slot ("free") or one fetch ("one")
COSTS["fetch_request_delay"] = 0             # clocks from the EU's request to the bus unit seeing it
COSTS["operand_at"] = [3, 6, 9, 12, 15]       # k-th operand byte, byte reads
COSTS["operand_word_at"] = [4, 7, 10, 13, 16]  # k-th operand byte, word reads

# "two_word": as "iwr", but the register holds the current word and the
# next, so a slot frees when the current word's last byte is consumed;
# queue_words counts both register words.
# Per-model fitted values: the active profile overrides COSTS.
PROFILES = {
    "iwr": {},
    "two_word": {"queue_model": "two_word", "queue_words": 4},
    "consume": {
        "queue_model": "consume",
        "queue_words": 3,
        "word_load": 2,
        "operand_at": [4, 7, 10, 13, 16],
        "operand_word_at": [4, 7, 10, 13, 16],
        # Fitted for this model by fit_hide.py and fit_steps.py.
        "end_hide": {'69r', 'C1r', 'D2r', 'D3r', 'F10m', 'F10r', 'F11m', 'F11r', 'F12m', 'F12r', 'F13m', 'F13r', 'F14m', 'F14r', 'F15m', 'F15r', 'F16m', 'F16r', 'F17m', 'F17r', 'F28m', 'F28r', 'F2Am', 'F2Ar', 'F31r', 'F33r', 0x27, 0x2F, 0x37, 0x3F, 0x40, 0x48, 0x5B, 0x61, 0x99, 0x9D, 0xA0, 0xA1, 0xA4, 0xA5, 0xA6, 0xA7, 0xAC, 0xAD, 0xC9, 0xCE, 0xD7, 0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEF, 0xF5, 0xF8, 0xF9, 0xFC, 0xFD},
        "mid_hide": {'6Br', '83m', '83r', 'F18r', 'F19r', 'F1Ar', 'F1Cr', 'F1Dr', 'F1Er', 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D, 0x5, 0x68, 0x85, 0xA3, 0xA9, 0xB8, 0xBB, 0xD, 0xD5},
        "alu_acc_imm1": 0,
        "alu_acc_imm2": 0,
        "alu_m_imm": 2,
        "alu_r_imm1": 0,
        "alu_r_imm2": 0,
        "bcond": 9,
        "br_near": 11,
        "br_short": 11,
        "branch_taken": 6,
        "brkv": 5,
        "call_far": 18,
        "call_indirect": 23,
        "call_near": 15,
        "chkind": 19,
        "clr1_r_imm": 3,
        "cmp_m_imm": 6,
        "cvtbd": 16,
        "cvtdb": 15,
        "in_imm": 7,
        "mov_load": 5,
        "mov_r8_imm": 0,
        "mul_imm": 35,
        "not1_r_imm": 3,
        "pop_all": 26,
        "prepare": 20,
        "prepare_level": 10,
        "push_all": 26,
        "reti": 36,
        "set1_r_imm": 3,
        "test1_r_imm": 3,
    },
}
COSTS.update(PROFILES[os.environ.get("V35S_PROFILE", "iwr")])
# V35S_COSTS='{"key": value}' overrides single values, for sweeps.
COSTS.update(json.loads(os.environ.get("V35S_COSTS", "{}")))
