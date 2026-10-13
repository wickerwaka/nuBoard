"""Timing parameters of the V35S model, in CPU clocks unless stated.

Every value here is fitted to silicon (validation/v35s/fit.py) or comes
straight from a measurement in docs/v35s-eu-timing.md. Execution steps are
named after the instruction class that spends them; the bus unit adds its
own cycles, so a step is what the EU spends beyond waiting for the bus.
"""

COSTS = {
    # Bus unit and queue.
    "queue_bytes": 8,
    "fetch_threshold": 2,
    "fetch_data_delay": 0,              # clocks from the end of B3 until the EU can take the bytes
    "release_delay": 0,                 # clocks until a byte the EU took frees queue space
    "free_latency": 1,                  # clocks from a queue word emptying until it can be refilled
    "release_at_boundary": 0,           # 1: an instruction's bytes are freed when the next opcode is taken
    "release_words": 2,                 # 1: space is freed a word at a time
    "io_recovery": 1,                   # idle clocks after an I/O cycle before the next cycle
    "write_posted": 1,                  # 1: the EU hands a write to the bus unit and continues
    "write_post_clocks": 0,             # EU clocks spent handing over a posted write
    "eu_after_read": 0,
    "eu_after_write": 0,
    "reset_first_fetch_states": 25,     # fX/8 states after /RESET rises
    "reset_first_refresh_states": 15,
    "refresh_tick_offset": 3,           # /REFRQ falls this many eighths of a state into B1
    "internal_access": 3,
    "ramen_write": 3,

    # Decode.
    "prefix": 2,
    "prefix_buslock": 3,
    "ea": 0,

    # ALU and moves (register forms are the measured totals).
    "alu_rr": 3, "alu_rm": 3, "alu_mr": 3, "cmp_mr": 2,
    "alu_acc_imm1": 6, "alu_acc_imm2": 7,
    "alu_r_imm1": 6, "alu_r_imm2": 7, "alu_m_imm": 4, "cmp_m_imm": 4,
    "test_rr": 6, "test_mr": 3, "test_r_imm": 8, "test_m_imm": 5,
    "xch_rr": 3, "xch_mr": 5, "xch_aw": 4,
    "mov_rr": 3, "mov_load": 3, "mov_store": 1, "mov_store_imm": 2,
    "mov_r8_imm": 6, "mov_r16_imm": 7,
    "ldea": 6, "load_far": 4,
    "incdec_r16": 2, "incdec_rm": 6, "incdec_m": 5,
    "unary_r": 6, "unary_m": 5,

    # Multiply and divide (see docs/v35s-eu-timing.md).
    "mulu8": 26, "mulu16": 34, "mul8": 37, "mul16": 44, "mul_imm": 41,
    "mulu8_m": 25, "mulu16_m": 33, "mul8_m": 36, "mul16_m": 43,
    "mul_negate": 8,
    "divu8": 34, "divu16": 42, "div8": 53, "div16": 61,
    "divu8_m": 33, "divu16_m": 41, "div8_m": 52, "div16_m": 60,
    "div_negate_dividend": 7, "div_negate_quotient": 2,

    # Shifts: 10 for a count of 0, 12 + 2n otherwise.
    "shift_r": 10, "shift_m": 12, "shift_m_cl": 13,
    "shift_per_bit": 2, "shift_nonzero": 2,

    # Stack.
    "push_r": 5, "pop_r": 7, "push_seg": 6, "pop_seg": 8, "push_imm": 8,
    "push_rm": 6, "pop_rm": 6, "push_psw": 5, "pop_psw": 9,
    "push_all": 10, "pop_all": 10, "prepare": 20, "prepare_level": 10, "dispose": 4,

    # Control transfer (EU part; the refill is the bus unit's).
    "bcond": 8, "branch_taken": 4, "bcwz": 8, "dbnz": 11, "dbnz_cond": 8,
    "br_short": 8, "br_near": 10, "br_far": 12, "br_indirect": 10, "br_far_indirect": 10,
    "call_near": 12, "call_far": 16, "call_indirect": 12, "call_far_indirect": 14,
    "ret": 12, "ret_far": 14, "reti": 20, "brkv": 6, "chkind": 10,
    "trap_entry": 20, "trap_exit": 4,

    # Strings.
    "string_single": 4, "movbk": 10, "stm": 4, "ldm": 4, "cmpbk": 10, "cmpm": 8,
    "inm": 6, "outm": 6, "rep_start": 10, "rep_iteration": 4, "rep_end": 2,

    # I/O.
    "in_imm": 8, "in_dw": 5, "out_imm": 5, "out_imm_post": 0, "out_dw": 2,

    # Misc.
    "flag_op": 2, "sahf": 3, "lahf": 3, "cvtbw": 3, "cvtwl": 9,
    "nop": 4, "halt": 2, "trans": 4,
    "adj4": 10, "adjb": 17, "cvtbd": 22, "cvtdb": 21,

    # 0F page.
    "test1_r_cl": 8, "test1_r_imm": 9, "clr1_r_cl": 8, "clr1_r_imm": 9,
    "set1_r_cl": 8, "set1_r_imm": 9, "not1_r_cl": 8, "not1_r_imm": 9,
    "test1_m_cl": 9, "test1_m_imm": 7, "clr1_m_cl": 9, "clr1_m_imm": 7,
    "set1_m_cl": 8, "set1_m_imm": 6, "not1_m_cl": 8, "not1_m_imm": 6,
    "bcd4s_start": 10, "bcd4s_digit_pair": 20,
    "rol4_r": 18, "ror4_r": 22, "rol4_m": 15, "ror4_m": 19,
    "ext_base": 107, "ext_full": 43, "ext_cross": 61,
    "ins_base": 94, "ins_boundary": 86, "ins_cross": 128,
    "bitfield_cl_adjust": -1,
    "stop": 2, "fint": 2,
}
