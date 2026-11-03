`timescale 1ns/1ps

// V35S core v2: the EA unit (docs/v35s-core-v2.md, "Function path": `v35_ea_off` becomes
// v35_ea.sv; stage S4). It forms a memory operand's address for the running form: the mode
// from the format word (v35_pkg::v35_fmt_t: the ModR/M md / rm, the direct d16 form without a
// ModR/M byte, the base+index+d16 mode, XLAT's BW + AL), the base read on the register RAM's
// port B and the index on port A (named a clock ahead by v35_eu; latched into `ea_bi` on the
// clock both are on the ports), the displacement from the operand bytes the loader took, the
// 16-bit add, and the segment (a prefix's; SS for a BP mode; else DS0). The physical address is
// {seg, 4'b0} + off. The EA table's clocks stay the class table's (v35_consts.svh); this unit
// has no timing of its own.
//
// Stage map: S2 (T) the address of the form after T's takes (`f_t`, `b_t`: the arbiter reads it
// in S4 for a request posted before its displacement was taken); S6 the latch (`f_now`: the
// form after S5).
//
// Registered state (widths) and the model variables it replaces:
//   ea_bi 16, ea_done 1     the base + index (XLAT: BW + AL) of v35_ea_off, latched once read
//                           (templates.decode's op.ea, which the model computes at the start)
//   (S5b) ea_mr 5           the mode (md, rm) the latch was taken for: a form started before its
//                           ModR/M byte arrived latched the decode ahead's registers; its ModR/M
//                           take re-decodes another mode, the latch is not that one's
module v35_ea
    import v35_pkg::*;
    import v35_fn_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,          // (S7b) the CPU clock's second tick (the pipeline registers)

    // the form after T (the address) ...
    input  v35_fmt_t   f_t,
    input  wire        t_new,           // (S6) ... started in T (the latch is the last form's)
    input  wire [47:0] b_t,             // its operand bytes (ob[8j +: 8] the j-th)
    input  wire [16:0] base_t,          // {on the ports, value}: the mode's base register
    input  wire [16:0] index_t,         // ... its index register
    input  wire [2:0]  sego,            // the segment prefix (seg code: 1 + DS1 PS SS DS0)
    input  wire [15:0] ds1, ps, ss, ds0,
    // ... and after S5 (the latch)
    input  v35_fmt_t   f_now,
    input  wire [47:0] b_now,           // (S6) its operand bytes
    input  wire        new_form,        // a form started on this clock
    input  wire        aim_ea,          // the ports held the EA's registers on this clock
    input  wire [16:0] base_n,
    input  wire [16:0] index_n,
    input  wire [15:0] xl_bw,           // XLAT: BW, AL
    input  wire [7:0]  xl_al,

    output wire [7:0]  regs_n,          // v35_ea_regs: the registers f_now's mode reads
    output wire        done_n,          // ea_bi holds f_now's base + index after this clock
    output wire [15:0] off,             // the offset (f_t)
    output wire        bp,              // ... a BP mode (the default segment SS)
    output wire [15:0] seg,
    output wire [19:0] phys,
    output wire        ok_t,            // (S5a) off is known: base + index latched or on the ports
    output wire [15:0] off_n,           // (S6) the offset of the form after S5 (f_now: LDEA's exec)
    output wire        ok_n             // (S6) ... known
);
    reg [15:0] ea_bi = 16'd0;
    reg        ea_done = 1'b0;
    reg [4:0]  ea_mr = 5'd0;            // (S5b) the mode (md, rm) ea_bi was latched for

    /* verilator lint_off UNUSEDSIGNAL */
    // the displacement (after the ModR/M byte; the direct form's d16 its first bytes)
    function automatic logic [15:0] dispv(input v35_fmt_t f, input logic [47:0] b);
        int k;
        k = (f.page != 2'd0 ? 1 : 0) + (f.has_modrm ? 1 : 0);
        dispv = {b[8 * (k + 1) +: 8], b[8 * k +: 8]};
    endfunction
    function automatic logic [15:0] segv(input logic [1:0] s);
        case (s)
            2'd0: segv = ds1;
            2'd1: segv = ps;
            2'd2: segv = ss;
            default: segv = ds0;
        endcase
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */

    // the base + index: latched, or on the ports now ((S5b) the latch only for the mode it was
    // latched for: a start decoded before its ModR/M byte arrived latches the decode ahead's
    // registers, and the ModR/M take's re-decode names others)
    // ((S6) not for a form started in T: the latch is then the last form's)
    wire        lat_ok_t = ea_done && !t_new && ea_mr == {f_t.md, f_t.rm};
    wire [15:0] bi_t = lat_ok_t ? ea_bi : base_t[15:0] + index_t[15:0];
    assign ok_t = lat_ok_t || (base_t[16] && index_t[16]);
    logic       bp_w;
    logic [15:0] off_w;
    always_comb begin
        bp_w = 1'b0;
        if (f_t.has_modrm)
            off_w = v35_ea_off(f_t.md, f_t.rm, bi_t, 16'd0, dispv(f_t, b_t), bp_w);
        else if (f_t.xop == V35_XOP_XLAT)
            off_w = ea_bi;
        else
            off_w = dispv(f_t, b_t);        // the direct form (A0-A3)
    end
    assign off = off_w;
    assign bp = bp_w;
    assign seg = (sego != 3'd0 && sego <= 3'd4) ? segv(2'(sego - 3'd1)) : (bp_w ? ss : ds0);
    assign phys = {seg, 4'd0} + {4'd0, off_w};

    // (S6) the offset of the form after S5 (the P pass): the exec of a form that starts in P, or
    // whose last operand byte the P pass takes, reads its own bytes and registers (LDEA: `off`
    // is the T form's, the form before when LDEA starts in P on a detached I/O's issue: an
    // OUT's port byte read as a direct offset, AL = 20h after F25's OUT 20h,AL; LDEA AW,[BW])
    wire        lat_ok_n = ea_done && !new_form && ea_mr == {f_now.md, f_now.rm};
    wire [15:0] bi_n = lat_ok_n ? ea_bi : base_n[15:0] + index_n[15:0];
    assign ok_n = lat_ok_n || (base_n[16] && index_n[16]);
    logic       bp_n;
    logic [15:0] off_nw;
    always_comb begin
        bp_n = 1'b0;
        if (f_now.has_modrm)
            off_nw = v35_ea_off(f_now.md, f_now.rm, bi_n, 16'd0, dispv(f_now, b_now), bp_n);
        else
            off_nw = dispv(f_now, b_now);
    end
    assign off_n = off_nw;

    // the latch (S6): once the ports held both registers for the form's mode
    assign regs_n = v35_ea_regs(f_now.md, f_now.rm);
    wire mr_ok = ea_mr == {f_now.md, f_now.rm};
    wire lat = aim_ea && (new_form || !ea_done || !mr_ok) && base_n[16] && index_n[16];
    assign done_n = lat || (ea_done && !new_form && mr_ok);
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            ea_bi <= 16'd0;
            ea_done <= 1'b0;
            ea_mr <= 5'd0;              // ((S6) the reset complete)
        end else if (ce_a) begin
            if (lat) begin
                ea_bi <= base_n[15:0] + index_n[15:0];
                ea_mr <= {f_now.md, f_now.rm};
            end
            ea_done <= done_n;
            if (f_now.xop == V35_XOP_XLAT)
                ea_bi <= xl_bw + {8'd0, xl_al};
        end
    end

    wire unused = &{1'b0, ce_b, f_now, bp_n};
endmodule
