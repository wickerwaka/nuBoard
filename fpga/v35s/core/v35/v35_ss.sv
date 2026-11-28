`timescale 1ns/1ps

// V35S core v2, work order 54: save state (build/overseer/ss-design/DESIGN-SS.md; the core README
// "Work order 54"). The freeze (part 1) and the state port's read side (part 2).
//
// A save-state request (ss_req, the host's level) is the interrupt controller's top-priority take
// (v35_intc `pk`); the sequencer runs the park routine (urom/zz_ss.uasm) and its park word
// (v35_useq x_park). `frz` loads at the ce_a that ends the park word: from there v35_top's clock
// block gives no ce_a, ce_b, ce_e or ce_mid and stops the X1 count, so every clocked register of
// the core (the peripherals included) stands at one instant, between a ce_a and the next ce_b,
// with the word behind the park word standing. `ss_parked` is `frz`. ss_req low (registered:
// `rq_q`) clears it: the first enable after the resume is the ce_b that was due.
//
// (part 2) The state port: the map is v35_ss_map.tsv (version 1: index 000h reads 5301h). The
// port's address, datum and strobes are registered here (`ss_a` and the read pipe, one fabric
// clock behind the port: stage 1); each module that holds saved state registers its select from
// ss_a (stage 2) and its word (`ss_q`, stage 3; 0 unless one of its indexes is selected); the
// register RAM's words come through its port C (read at stage 2 while frozen, here registered at
// stage 3); this module ORs them into `ss_dout` (stage 4). `ss_valid` is ss_rd (while parked)
// four fabric clocks later; a word a clock may be read. The words read are those of the core as
// frozen (with ss_rd outside the park nothing is valid). ss_din / ss_we are taken but not yet used
// (the write path is a later work order).
// Registered state: frz 1, rq_q 1; the port's pipe (ss_a 10, rv 4, the RAM select 1, the own word
// 16 and its select, ss_dout 16): no core logic reads it.
module v35_ss (
    input  wire        clock,
    input  wire        reset_n,         // the core's reset (v35_top core_reset_n)
    input  wire        ce_a,
    input  wire        ss_req,          // the host's request (hold to ss_parked; low resumes)
    input  wire        x_park,          // the park word executes (v35_useq; tick A)
    output reg         frz,             // the freeze (v35_top's enables, v35_intc's request hold, regram)
    output wire        ss_parked,
    // (part 2) the state port
    input  wire [9:0]  ss_addr,
    input  wire [15:0] ss_din,
    input  wire        ss_we,
    input  wire        ss_rd,
    output reg  [15:0] ss_dout,
    output wire        ss_valid,
    output reg  [9:0]  ss_a,            // the index, registered (to the modules' selects)
    // the clock block's registers (v35_top: the X1 count and the PCK in force; word 003h)
    input  wire [2:0]  x_count,
    input  wire [1:0]  pck,
    // the modules' words (stage 3 registers) and the register RAM's port C (stage 2)
    input  wire [15:0] q_eu,
    input  wire [15:0] q_bus,
    input  wire [15:0] q_intc,
    input  wire [15:0] q_sfr,
    input  wire [15:0] oc_rd
);
    localparam logic [15:0] FORMAT = 16'h5301;          // magic 53h, version 01h
    reg        rq_q = 1'b0;             // ss_req as last sampled (the fabric clock)
    initial frz = 1'b0;
    always @(posedge clock) begin
        rq_q <= ss_req;
        if (!reset_n)
            frz <= 1'b0;
        else if (frz)
            frz <= rq_q;                // the resume: the request dropped
        else if (ce_a && x_park)
            frz <= 1'b1;                // the park word's ce_a
    end
    assign ss_parked = frz;

    // ---- the read side
    initial ss_a = 10'd0;
    initial ss_dout = 16'd0;
    reg  [3:0]  rv = 4'd0;              // ss_rd's pipe (stage 1 .. 4)
    reg         rm = 1'b0;              // the RAM's range selected (stage 2)
    reg         o_v = 1'b0;             // this module's words selected (stage 2)
    reg  [1:0]  o_i = 2'd0;
    reg  [15:0] o_q = 16'd0, m_q = 16'd0;   // this module's word, the RAM's (stage 3)
    logic [15:0] ss_wd;
    always_comb begin
        ss_wd = 16'd0;
        case (o_i)
            2'd0: ss_wd = FORMAT;
            2'd3: begin ss_wd[2:0] = x_count; ss_wd[4:3] = pck; end
            default: ;
        endcase
    end
    always @(posedge clock) begin
        ss_a <= ss_addr;
        rv <= {rv[2:0], ss_rd && frz};
        o_v <= ss_a[9:2] == 8'd0;
        o_i <= ss_a[1:0];
        rm <= ss_a[9:7] == 3'd1;
        o_q <= o_v ? ss_wd : 16'd0;
        m_q <= rm ? oc_rd : 16'd0;
        ss_dout <= o_q | m_q | q_eu | q_bus | q_intc | q_sfr;
    end
    assign ss_valid = rv[3];
    wire unused = &{1'b0, ss_din, ss_we};
endmodule
