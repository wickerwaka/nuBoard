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
    // the write cycles posted and not yet off the pins (the arbiter's three positions, the bus
    // cycle running): an instruction's detached OUT runs after the next one's start
    output wire [3:0]  o_pend_w,
    // (+trace) the bus cycle's datum select and the EU's immediate
    output wire        o_drop,
    output wire        o_flush,         // a transfer's flush (T)
    output wire [1:0]  o_dsel,
    output wire [15:0] o_wd_imm
);
    // a read's delivery whose exec could not run (its operands not on the ports): lost
    assign o_drop = dut.eu.ex_mem && !dut.eu.xr.ok;
    assign o_dsel = dut.bus.c_dsel;
    assign o_flush = dut.t_flush;
    assign o_wd_imm = dut.eu.wd_imm;
    wire a0, a19, a18_ube, mreq_n, mstb_n, iostb_n, read_write, refrq_n;
    wire [8:0] mux_address;
    wire [15:0] data_out;
    v35_top dut (
        .clock, .x_rise(1'b1), .x_fall(1'b0), .reset_n, .ready(1'b1), .data_in,
        .input_levels(16'd0), .a0, .a19, .a18_ube, .mux_address, .data_out, .mreq_n, .mstb_n,
        .iostb_n, .read_write, .refrq_n
    );

    assign o_ce = dut.ce;
    assign o_ce_mid = dut.ce_mid;
    assign o_t_start = dut.t_start;
    assign o_p_start = dut.p_start;
    assign o_t_addr = dut.ir_addr_c;
    assign o_p_addr = dut.ir_addr_l;
    assign o_t_cls = dut.fmt_c.cls;
    assign o_p_cls = dut.fmt_l.cls;
    assign o_halted = dut.halted;
    assign o_c_valid = dut.bus.c_valid;
    assign o_c_kind = dut.bus.c_kind;
    assign o_c_addr = dut.bus.c_addr;
    assign o_c_width = dut.bus.c_width;
    assign o_c_pos = dut.bus.c_pos;
    assign o_c_len = dut.bus.c_len;
    assign o_c_internal = dut.bus.c_internal;
    assign o_data_out = data_out;
    assign o_div_trap = (dut.eu.dvp && dut.eu.ds_n.trap) || (dut.eu.dfin && dut.eu.dtrap);
    assign o_miss = dut.eu_miss;
    assign o_exec_pend = dut.eu.exec_pend;
    assign o_w2_v = dut.eu.w2_v;
    assign o_w2_a = dut.eu.w2_a;
    assign o_w2_be = dut.eu.w2_be;
    assign o_w2_d = dut.eu.w2_d;
    assign o_psw = dut.eu.psw;
    assign o_ds1 = dut.eu.ds1;
    assign o_ps = dut.eu.ps;
    assign o_ss = dut.eu.ss;
    assign o_ds0 = dut.eu.ds0;
    assign o_cw = dut.eu.cw;
    assign o_ix = dut.eu.ix;
    assign o_iy = dut.eu.iy;
    assign o_stale = {dut.eu.dcw, dut.eu.dix, dut.eu.diy};

    // a position's write cycles still to issue (an odd word: two)
    function automatic logic [3:0] pw(input logic v, input logic nwd, input logic [2:0] kind,
                                      input logic nowr, input logic iss, input logic h2,
                                      input logic [1:0] width, input logic a0);
        logic two;
        two = width == 2'd0 && a0 && kind == 3'd3;
        if (!v || nwd || nowr || !(kind == 3'd3 || kind == 3'd5))
            pw = 4'd0;
        else if (!iss)
            pw = two ? 4'd2 : 4'd1;
        else
            pw = (two && !h2) ? 4'd1 : 4'd0;
    endfunction
    assign o_pend_w = pw(dut.arbiter.r0.v, dut.arbiter.r0.nwd, dut.arbiter.r0.d.kind,
                         dut.arbiter.r0.d.nowrite, dut.arbiter.r0.iss, dut.arbiter.r0.h2,
                         dut.arbiter.r0.d.width, dut.arbiter.r0.d.addr[0])
                    + pw(dut.arbiter.r1.v, dut.arbiter.r1.nwd, dut.arbiter.r1.d.kind,
                         dut.arbiter.r1.d.nowrite, dut.arbiter.r1.iss, dut.arbiter.r1.h2,
                         dut.arbiter.r1.d.width, dut.arbiter.r1.d.addr[0])
                    + pw(dut.arbiter.r2.v, dut.arbiter.r2.nwd, dut.arbiter.r2.d.kind,
                         dut.arbiter.r2.d.nowrite, dut.arbiter.r2.iss, dut.arbiter.r2.h2,
                         dut.arbiter.r2.d.width, dut.arbiter.r2.d.addr[0])
                    + ((dut.bus.c_valid && !dut.bus.c_internal
                        && (dut.bus.c_kind == 3'd3 || dut.bus.c_kind == 3'd5)
                        && dut.bus.c_pos != dut.bus.c_len - 3'd1) ? 4'd1 : 4'd0);

    wire unused = &{1'b0, a0, a19, a18_ube, mreq_n, mstb_n, iostb_n, read_write, refrq_n,
                    mux_address};
endmodule
