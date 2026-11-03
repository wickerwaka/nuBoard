`timescale 1ns/1ps

// V35S core v2: the per-clock event trace (simulation only; docs/v35s-core-v2.md,
// "Verification", and Appendix A §5). With +v35_trace=FILE, one line per CPU clock:
//
//   <t> [X:<kind>:<addr>:<width>:<len>] [S:<class>:<pc>] [T:<n>] [L:<n>] [P:<kind>] [I] [B]
//       [A] R:<room>:<flag> W:<reason>
//
// X a cycle start (normalize.Event's kinds, the address in hex, word/lo/hi, the length in
// clocks; an on-chip SFR store is listed too, as the model's bus.cycles list it), S an
// instruction start (the class and the opcode's address), T the operand bytes the EU took,
// L the IR loads, P a request posted, I the EU's request issued, B the bus unit committed to
// a back-to-back fetch at this clock's end, A an aborted fetch cycle, R the request rule's
// room and the request flag at the clock's end, W the EU's wait reason (RTL only).
// validation/v35s/chains/evtrace.py writes the model's side in the same format and diffs the
// two from t_fill. `t` counts CPU clocks from the core's reset exit; each reset exit starts a
// run with a "# reset" line.
module v35_trace
    import v35_front_pkg::*;
    import v35_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        g_start,
    input  wire [2:0]  g_kind,
    input  wire [19:0] g_addr,
    input  wire [1:0]  g_width,
    input  wire [2:0]  g_len,
    input  wire        start_t,
    input  wire        start_p,
    input  wire [6:0]  scls_t,          // the T start's class
    input  wire [6:0]  scls_p,          // the P start's class
    input  wire [19:0] pc_t,
    input  wire [19:0] pc_p,
    input  wire [2:0]  takes,
    input  wire [1:0]  loads,
    input  wire        post,
    input  wire [2:0]  post_kind,
    input  wire        issue,
    input  wire        b2b,
    input  wire        abort,
    input  wire signed [4:0] room,
    input  wire        flag,
    input  wire [4:0]  why,
    input  wire [3:0]  hold,            // (S4) the arbiter's fetch hold (W:<reason>/<hold>)
    input  wire        dec_miss,        // the start waited for its decode (W: dec)
    input  wire        wlost            // a register write was lost (W: lost)
);
`ifndef SYNTHESIS
    integer fd = 0;
    reg [31:0] t = 32'd0;
    reg running = 1'b0;
    string fname;

    initial begin
        if ($value$plusargs("v35_trace=%s", fname))
            fd = $fopen(fname, "w");
    end

    function automatic string kname(input logic [2:0] k);
        case (k)
            K_FETCH: kname = "fetch";
            K_READ: kname = "read";
            K_WRITE: kname = "write";
            K_IO_READ: kname = "io_read";
            K_IO_WRITE: kname = "io_write";
            K_REFRESH: kname = "refresh";
            default: kname = "none";
        endcase
    endfunction
    function automatic string wname(input logic [1:0] w);
        case (w)
            BW_LO: wname = "lo";
            BW_HI: wname = "hi";
            default: wname = "word";
        endcase
    endfunction
    function automatic string cname(input logic [6:0] c);
        case (c)
            V35_CLS_TRAP_NOP: cname = "trap_nop";
            V35_CLS_ADJUST: cname = "adjust";
            V35_CLS_ADJUST_B: cname = "adjust_b";
            V35_CLS_BCD4S: cname = "bcd4s";
            V35_CLS_BCD4S_CMP: cname = "bcd4s_cmp";
            V35_CLS_BCWZ: cname = "bcwz";
            V35_CLS_BF_EXT: cname = "bf_ext";
            V35_CLS_BF_INS: cname = "bf_ins";
            V35_CLS_BIT1: cname = "bit1";
            V35_CLS_BIT1_CLR: cname = "bit1_clr";
            V35_CLS_BIT1_RMW: cname = "bit1_rmw";
            V35_CLS_BIT1_TEST: cname = "bit1_test";
            V35_CLS_BR_MEM: cname = "br_mem";
            V35_CLS_BR_REG: cname = "br_reg";
            V35_CLS_BRANCH_FAR: cname = "branch_far";
            V35_CLS_BRANCH_FAR_MEM: cname = "branch_far_mem";
            V35_CLS_BRANCH_NEAR: cname = "branch_near";
            V35_CLS_BRANCH_SHORT: cname = "branch_short";
            V35_CLS_BRK: cname = "brk";
            V35_CLS_CALL: cname = "call";
            V35_CLS_CALL_FAR: cname = "call_far";
            V35_CLS_CALL_FAR_MEM: cname = "call_far_mem";
            V35_CLS_CALL_MEM: cname = "call_mem";
            V35_CLS_CALL_REG: cname = "call_reg";
            V35_CLS_CONVERT: cname = "convert";
            V35_CLS_CONVERT_D: cname = "convert_d";
            V35_CLS_DBNZ: cname = "dbnz";
            V35_CLS_DBNZ_Z: cname = "dbnz_z";
            V35_CLS_DISPOSE: cname = "dispose";
            V35_CLS_DIV: cname = "div";
            V35_CLS_EXTEND: cname = "extend";
            V35_CLS_EXTEND_W: cname = "extend_w";
            V35_CLS_FLAG: cname = "flag";
            V35_CLS_FLAG_DI: cname = "flag_di";
            V35_CLS_FLAG_EI: cname = "flag_ei";
            V35_CLS_HALT: cname = "halt";
            V35_CLS_IMM: cname = "imm";
            V35_CLS_IN: cname = "in";
            V35_CLS_INCDEC: cname = "incdec";
            V35_CLS_LEA: cname = "lea";
            V35_CLS_LOAD: cname = "load";
            V35_CLS_LOAD_ALU: cname = "load_alu";
            V35_CLS_LOAD_PTR: cname = "load_ptr";
            V35_CLS_LOAD_SEG: cname = "load_seg";
            V35_CLS_MUL: cname = "mul";
            V35_CLS_MUL_IMM: cname = "mul_imm";
            V35_CLS_OUT: cname = "out";
            V35_CLS_POP: cname = "pop";
            V35_CLS_POP_MEM: cname = "pop_mem";
            V35_CLS_POP_PSW: cname = "pop_psw";
            V35_CLS_POP_R: cname = "pop_r";
            V35_CLS_POP_SEG: cname = "pop_seg";
            V35_CLS_PREFIX: cname = "prefix";
            V35_CLS_PREPARE: cname = "prepare";
            V35_CLS_PUSH: cname = "push";
            V35_CLS_PUSH_IMM: cname = "push_imm";
            V35_CLS_PUSH_MEM: cname = "push_mem";
            V35_CLS_PUSH_R: cname = "push_r";
            V35_CLS_PUSH_SEG: cname = "push_seg";
            V35_CLS_REG: cname = "reg";
            V35_CLS_RET: cname = "ret";
            V35_CLS_RET_FAR: cname = "ret_far";
            V35_CLS_RET_FAR_IMM: cname = "ret_far_imm";
            V35_CLS_RET_IMM: cname = "ret_imm";
            V35_CLS_RETI: cname = "reti";
            V35_CLS_RMW: cname = "rmw";
            V35_CLS_RMW_IMM: cname = "rmw_imm";
            V35_CLS_ROL4: cname = "rol4";
            V35_CLS_ROL4_MEM: cname = "rol4_mem";
            V35_CLS_ROR4: cname = "ror4";
            V35_CLS_ROR4_MEM: cname = "ror4_mem";
            V35_CLS_SHIFT_CL: cname = "shift_cl";
            V35_CLS_SHIFT_IMM: cname = "shift_imm";
            V35_CLS_STORE: cname = "store";
            V35_CLS_STORE_IMM: cname = "store_imm";
            V35_CLS_STR_CMP: cname = "str_cmp";
            V35_CLS_STR_IN: cname = "str_in";
            V35_CLS_STR_LOAD: cname = "str_load";
            V35_CLS_STR_MOVE: cname = "str_move";
            V35_CLS_STR_OUT: cname = "str_out";
            V35_CLS_STR_SCAN: cname = "str_scan";
            V35_CLS_STR_STORE: cname = "str_store";
            V35_CLS_TEST_REG: cname = "test_reg";
            V35_CLS_XLAT: cname = "xlat";
            default: cname = "trap_nop";
        endcase
    endfunction
    function automatic string why_name(input logic [4:0] w);
        case (w)
            5'd1: why_name = "clk";
            5'd2: why_name = "hold";
            5'd3: why_name = "sync";
            5'd4: why_name = "bytes";
            5'd5: why_name = "late_read";
            5'd6: why_name = "imm_latch";
            5'd7: why_name = "data";
            5'd8: why_name = "issued";
            5'd9: why_name = "slot";
            5'd10: why_name = "wbsync";
            5'd11: why_name = "gate";
            5'd12: why_name = "ir";
            5'd13: why_name = "halt";
            5'd14: why_name = "flush";
            5'd15: why_name = "io_exec";
            5'd16: why_name = "late_disp";      // (S4) sync_req=disp's _late_fetch
            5'd17: why_name = "post";           // (S4) no request position (_submit)
            default: why_name = "-";
        endcase
    endfunction
    // (S4) the arbiter's fetch holds (v35_arbiter why_o)
    function automatic string hold_name(input logic [3:0] h);
        case (h)
            4'd1: hold_name = "/free_hold";
            4'd2: hold_name = "/grp_io_hold";
            4'd3: hold_name = "/slot_fetch";
            4'd4: hold_name = "/grp_disp";
            4'd5: hold_name = "/ea_b2b";
            4'd6: hold_name = "/sreg";
            4'd7: hold_name = "/hold_fetch";
            4'd8: hold_name = "/wb_fetch";
            4'd9: hold_name = "/io_hold";
            4'd10: hold_name = "/lead";
            default: hold_name = "";
        endcase
    endfunction

    always @(posedge clock) begin
        if (!reset_n) begin
            t <= 32'd0;
            running <= 1'b0;
        end else if (ce_a) begin
            if (fd != 0) begin
                string line;
                if (!running)
                    $fdisplay(fd, "# reset");
                line = $sformatf("%0d", t);
                if (g_start)
                    line = {line, $sformatf(" X:%s:%05X:%s:%0d", kname(g_kind), g_addr,
                                            wname(g_width), g_len)};
                if (start_t)
                    line = {line, $sformatf(" S:%s:%05X", cname(scls_t), pc_t)};
                if (start_p)
                    line = {line, $sformatf(" S:%s:%05X", cname(scls_p), pc_p)};
                if (takes != 3'd0)
                    line = {line, $sformatf(" T:%0d", takes)};
                if (loads != 2'd0)
                    line = {line, $sformatf(" L:%0d", loads)};
                if (post)
                    line = {line, $sformatf(" P:%s", kname(post_kind))};
                if (issue)
                    line = {line, " I"};
                if (b2b)
                    line = {line, " B"};
                if (abort)
                    line = {line, " A"};
                line = {line, $sformatf(" R:%0d:%0d W:%s", room, flag,
                                        wlost ? "lost" : dec_miss ? "dec"
                                                                 : why_name(why)),
                        hold_name(hold)};
                $fdisplay(fd, "%s", line);
                $fflush(fd);
            end
            running <= 1'b1;
            t <= t + 32'd1;
        end
    end
`else
    wire unused = &{1'b0, clock, reset_n, ce_a, g_start, g_kind, g_addr, g_width, g_len, start_t,
                    start_p, scls_t, scls_p, pc_t, pc_p, takes, loads, post, post_kind, issue,
                    b2b, abort, room, flag, why, hold, dec_miss, wlost};
`endif
endmodule
