`timescale 1ns/1ps

// V35S core v2: the per-clock event trace (simulation only; docs/v35s-core-v2.md,
// "Verification", and Appendix A §5). With +v35_trace=FILE, one line per CPU clock:
//
//   <t> [X:<kind>:<addr>:<width>:<len>] [S:<routine>:<pc>] [T:<n>] [L:<n>] [P:<kind>] [I] [B]
//       [A] [U] R:<room>:<flag> W:<reason> [M:<upc>]
//
// X a cycle start (normalize.Event's kinds, the address in hex, word/lo/hi, the length in
// clocks; an on-chip SFR store is listed too), S an instruction start ((MX0) the routine's
// entry address as `u<n>`, `trap` for a trap routine, and the opcode's address), T the operand
// bytes popped, L the word register's loads, P a request posted, I the EU's request issued, B
// the bus unit committed to a back-to-back fetch at this clock's end, A an aborted fetch cycle,
// R the free bytes (approximate) and the request line, W the sequencer's stall (q f slot hold
// halt), M the microaddress executing (RTL only).
// validation/v35s/chains/evtrace.py writes the model's side in the same format and diffs the
// two from t_fill (--keys X narrows the diff to the cycles). `t` counts CPU clocks from the
// core's reset exit; each reset exit starts a run with a "# reset" line.
module v35_trace
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        g_start,
    input  wire [2:0]  g_kind,
    input  wire [19:0] g_addr,
    input  wire [1:0]  g_width,
    input  wire [2:0]  g_len,
    input  wire        start,
    input  wire        epop,            // (MX1b) the E word pops the next opcode (the model's start)
    input  wire        start_trap,
    input  wire [v35_pkg::UADDR_W-1:0] entry,
    input  wire [19:0] pc,
    input  wire        take,
    input  wire        load,
    input  wire        post,
    input  wire [2:0]  post_kind,
    input  wire        issue,
    input  wire        b2b,
    input  wire        abort,
    input  wire signed [4:0] room,
    input  wire        flag,
    input  wire [4:0]  why,
    input  wire [v35_pkg::UADDR_W-1:0] upc
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
    function automatic string why_name(input logic [4:0] w);
        case (w)
            5'd1: why_name = "q";
            5'd2: why_name = "f";
            5'd3: why_name = "slot";
            5'd4: why_name = "hold";
            5'd5: why_name = "halt";
            5'd6: why_name = "fetch";
            5'd7: why_name = "sync";
            default: why_name = "-";
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
                if (epop)
                    line = {line, " E"};
                if (start)
                    line = {line, start_trap ? $sformatf(" S:trap:%05X", pc)
                                             : $sformatf(" S:u%0d:%05X", entry, pc)};
                if (take)
                    line = {line, " T:1"};
                if (load)
                    line = {line, " L:1"};
                if (post)
                    line = {line, $sformatf(" P:%s", kname(post_kind))};
                if (issue)
                    line = {line, " I"};
                if (b2b)
                    line = {line, " B"};
                if (abort)
                    line = {line, " A"};
                line = {line, $sformatf(" R:%0d:%0d W:%s M:%0d", room, flag, why_name(why), upc)};
                $fdisplay(fd, "%s", line);
                $fflush(fd);
            end
            running <= 1'b1;
            t <= t + 32'd1;
        end
    end
`else
    wire unused = &{1'b0, clock, reset_n, ce_a, g_start, g_kind, g_addr, g_width, g_len, start, epop,
                    start_trap, entry, pc, take, load, post, post_kind, issue, b2b, abort, room,
                    flag, why, upc};
`endif
endmodule
