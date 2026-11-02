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
    import v35_stub_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,
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
    input  wire [3:0]  why
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
            CLS_REG: cname = "reg";
            CLS_IMM: cname = "imm";
            CLS_SHIFT_CL: cname = "shift_cl";
            CLS_OUT: cname = "out";
            CLS_PUSH: cname = "push";
            CLS_STORE: cname = "store";
            CLS_PREFIX: cname = "prefix";
            CLS_HALT: cname = "halt";
            CLS_BRANCH_FAR: cname = "branch_far";
            CLS_STORE_IMM: cname = "store_imm";
            CLS_PUSH_IMM: cname = "push_imm";
            CLS_POP_PSW: cname = "pop_psw";
            default: cname = "trap_nop";
        endcase
    endfunction
    function automatic string why_name(input logic [3:0] w);
        case (w)
            4'd1: why_name = "clk";
            4'd2: why_name = "hold";
            4'd3: why_name = "sync";
            4'd4: why_name = "bytes";
            4'd5: why_name = "late_read";
            4'd6: why_name = "imm_latch";
            4'd7: why_name = "data";
            4'd8: why_name = "issued";
            4'd9: why_name = "slot";
            4'd10: why_name = "wbsync";
            4'd11: why_name = "gate";
            4'd12: why_name = "ir";
            4'd13: why_name = "halt";
            4'd14: why_name = "flush";
            4'd15: why_name = "io_exec";
            default: why_name = "-";
        endcase
    endfunction

    always @(posedge clock) begin
        if (!reset_n) begin
            t <= 32'd0;
            running <= 1'b0;
        end else if (ce) begin
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
                line = {line, $sformatf(" R:%0d:%0d W:%s", room, flag, why_name(why))};
                $fdisplay(fd, "%s", line);
                $fflush(fd);
            end
            running <= 1'b1;
            t <= t + 32'd1;
        end
    end
`else
    wire unused = &{1'b0, clock, reset_n, ce, g_start, g_kind, g_addr, g_width, g_len, start_t,
                    start_p, scls_t, scls_p, pc_t, pc_p, takes, loads, post, post_kind, issue,
                    b2b, abort, room, flag, why};
`endif
endmodule
