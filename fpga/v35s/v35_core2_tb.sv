`timescale 1ns/1ps

// The core v2's whole-core function bench (docs/v35s-core-v2.md, "Verification", function;
// stage S6). v35_top, the real slot module, runs one instruction at a time from a preloaded
// state: the register RAM, PS, the segment registers, CW / IX / IY and the PSW (the EU's flops)
// and the first fetch's address are written by the C++ driver (v35_core2_tb.cpp) through
// `verilator public` hooks (v35_core2_tb.vlt) after a reset, the prelude and the reset exit
// skipped; the memory is the driver's, served on the bus unit's current cycle (data_in), the
// writes read off the pins. This module only wires the core and reads its nets for the driver
// (hierarchical references, no behaviour of its own). Build: fpga/v35s/build_core2_tb.sh.
module v35_core2_tb
    import v35_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire [15:0] data_in,

    // the CPU clock's enables (the registered update at ce; the strobes at ce_mid)
    output wire        o_ce,
    output wire        o_ce_mid,
    // the starts: T and P, the IR's address, the class of the started form
    output wire        o_t_start,
    output wire        o_p_start,
    output wire [19:0] o_t_addr,
    output wire [19:0] o_p_addr,
    output wire [6:0]  o_t_cls,
    output wire [6:0]  o_p_cls,
    output wire        o_halted,
    // the bus unit's current cycle (the driver serves reads on it and records writes)
    output wire        o_c_valid,
    output wire [2:0]  o_c_kind,
    output wire [19:0] o_c_addr,
    output wire [1:0]  o_c_width,
    output wire [2:0]  o_c_pos,
    output wire [2:0]  o_c_len,
    output wire        o_c_internal,
    output wire [15:0] o_data_out,
    // the datapath: the divide error (the trap condition), a lost register write, the pending
    // second write, the EU's flops
    output wire        o_div_trap,
    output wire        o_miss,
    output wire        o_exec_pend,
    output wire        o_w2_v,
    output wire [6:0]  o_w2_a,
    output wire [1:0]  o_w2_be,
    output wire [15:0] o_w2_d,
    output wire [15:0] o_psw,
    output wire [15:0] o_ds1,
    output wire [15:0] o_ps,
    output wire [15:0] o_ss,
    output wire [15:0] o_ds0,
    output wire [15:0] o_cw,
    output wire [15:0] o_ix,
    output wire [15:0] o_iy,
    output wire [2:0]  o_stale,
    // the write cycles posted and not yet off the pins ((A1) the EU bus interface's two entries, the bus
    // cycle running): an instruction's detached OUT runs after the next one's start
    output wire [3:0]  o_pend_w,
    // (+trace) the bus cycle's datum select and the EU's immediate
    output wire        o_drop,
    output wire        o_flush,         // a transfer's flush (T)
    output wire [1:0]  o_dsel,
    output wire [15:0] o_wd_imm
);
    // (MX0) no lost exec, no datum select, no immediate register in the datapath's sense
    assign o_drop = 1'b0;
    assign o_dsel = 2'd0;
    assign o_flush = dut.t_flush;
    assign o_wd_imm = 16'd0;
    wire a0, a19, a18_ube, mreq_n, mstb_n, iostb_n, read_write, refrq_n;
    wire [8:0] mux_address;
    wire [15:0] data_out;
    // (sstfix) the input pins at the board's rest levels (validation/v35s/runner.py REST_LEVELS
    // 0x1E1F, register 8E: N/S high, NMI and /INTP0-2 high, RxD and /CTS high; INT, DMARQ and
    // HLDRQ low): (F3b) every interrupt entry, BRK / RETI's bank switch among them, loads MD from
    // N/S, so a bench with N/S low left PSW bit 15 clear after CC / CD / CF where the board's
    // socket (N/S high) sets it
    localparam logic [15:0] REST_LEVELS = 16'h1E1F;
    v35_top dut (
        .clock, .x_rise(1'b1), .x_fall(1'b0), .reset_n, .ready(1'b1), .data_in,
        .input_levels(REST_LEVELS), .a0, .a19, .a18_ube, .mux_address, .data_out, .mreq_n, .mstb_n,
        .iostb_n, .read_write, .refrq_n, .pins_in(24'd0), .pins()
    );

    assign o_ce = dut.ce;
    assign o_ce_mid = dut.ce_mid;
    assign o_t_start = dut.start;       // (MX0) a routine's entry word executes (MX0f: t_start is Q2's E pop)
    assign o_p_start = 1'b0;
    assign o_t_addr = dut.ir_addr_c;    // the started instruction's opcode address
    assign o_p_addr = 20'd0;
    assign o_t_cls = dut.start_trap ? 7'd0 : 7'd1;   // 0: a trap routine (not compared)
    assign o_p_cls = 7'd0;
    assign o_halted = dut.useq.halted;
    assign o_c_valid = dut.bus.n_valid;   // ((S7b) the cycle the pins show from mid-clock on)
    assign o_c_kind = dut.bus.n_kind;
    assign o_c_addr = dut.bus.n_addr;
    assign o_c_width = dut.bus.n_width;
    assign o_c_pos = dut.bus.n_pos;
    assign o_c_len = dut.bus.n_len;
    assign o_c_internal = dut.bus.n_internal;
    assign o_data_out = data_out;
    assign o_div_trap = dut.eu.trap_o;
    assign o_miss = 1'b0;
    assign o_exec_pend = 1'b0;
    assign o_w2_v = 1'b0;
    assign o_w2_a = 7'd0;
    assign o_w2_be = 2'd0;
    assign o_w2_d = 16'd0;
    assign o_psw = dut.eu.psw;
    assign o_ds1 = dut.eu.ds1;
    assign o_ps = dut.eu.ps;
    assign o_ss = dut.eu.ss;
    assign o_ds0 = dut.eu.ds0;
    // (MX0) CW / IX / IY are RAM words only: the driver reads them from the RAM (o_stale all set)
    assign o_cw = 16'd0;
    assign o_ix = 16'd0;
    assign o_iy = 16'd0;
    assign o_stale = 3'b111;

    // the write cycles posted and not yet off the pins: the EU's request standing (an odd word:
    // two), the bus cycle running, (sstfix) a pair's second half still to come (p2_v: the EU's
    // request was acknowledged at the first half's grant, the second half is the bus unit's own;
    // an odd-port word OUT whose first half runs across the next start was cut off at one write)
    wire eu_w = dut.eu.rq_v && (dut.eu.rq_cyc == 2'd1 || dut.eu.rq_cyc == 2'd3);
    wire p2_w = dut.bus.p2_v && (dut.bus.c_kind == 3'd3 || dut.bus.c_kind == 3'd5);
    assign o_pend_w = (eu_w ? (dut.eu.rq_pair ? 4'd2 : 4'd1) : 4'd0)
                    + ((dut.bus.c_valid && !dut.bus.c_internal
                        && (dut.bus.c_kind == 3'd3 || dut.bus.c_kind == 3'd5)
                        && dut.bus.c_pos != dut.bus.c_len - 3'd1) ? 4'd1 : 4'd0)
                    + (p2_w ? 4'd1 : 4'd0);

    wire unused = &{1'b0, a0, a19, a18_ube, mreq_n, mstb_n, iostb_n, read_write, refrq_n,
                    mux_address};
endmodule
