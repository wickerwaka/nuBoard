`timescale 1ns/1ps

// The Verilator bench top for the chain-model core (HDL plan, C4): v35_chain_core with its state
// bundles (V35S_STATE_DUMP), driven and read by v35_core_tb.cpp from the frozen model's vectors
// (validation/v35s/chains/rtl_vectors.py --core: the EU's, the queue's, the bus unit's and the
// arbiter's of the same run). The bench serves the core's memory from the chain's image and
// Phase D's operand records and write data from the vectors; every timing decision is the core's.
// Build: fpga/v35s/build_core_tb.sh (binary in build/fpga/v35s/core-tb/).
module v35_core_tb #(
    parameter int NQ = 16,
    parameter int NXOP = 4,
    parameter int NXQ = 8,
    parameter int JSLOT = 40,
    parameter int STATE_W = 516,
    parameter int QSTATE_W = 180,
    parameter int ASTATE_W = 69
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        run,                 // end the model clock once it has settled
    input  wire        ce_mid,              // the middle of the CPU clock (strobes, read latch)

    // the start (Machine.__init__): the EU's state at the end of clock -1, the queue's preload
    input  wire [STATE_W-1:0] init_state,
    input  wire [19:0] code_base,
    input  wire [3:0]  init_count,
    input  wire [63:0] init_data,
    input  wire [19:0] init_fetch_addr,
    // the SFR block
    input  wire [15:0] wtc,
    input  wire [7:0]  rfm,

    // Phase D: the operand records of the clock's starts, the EU's write data
    input  wire [212:0] opnd_a,
    input  wire [212:0] opnd_b,
    input  wire [15:0] eu_data,

    // memory
    output wire [19:0] fetch_addr,          // a fetch starting this clock: its address ...
    input  wire [15:0] fetch_data,          // ... and the word there
    input  wire [15:0] data_in,             // the bus's data (latched mid-B3)

    output wire        settled,             // the model clock's chain has settled
    output wire [1:0]  n_start,             // instructions started this clock
    output wire        done,                // the cycle that ended on the previous clock ...
    output wire [2:0]  done_kind,
    output wire [19:0] done_addr,
    output wire        error,               // sticky: a machine's error or a core check
    output wire [7:0]  err_code,            // this clock's, {core, arbiter, EU} (0: none)

    // pins (v35_biu.sv)
    output wire        a0,
    output wire        a19,
    output wire        a18_ube,
    output wire [8:0]  mux_address,
    output wire [15:0] data_out,
    output wire        mreq_n,
    output wire        mstb_n,
    output wire        iostb_n,
    output wire        read_write,
    output wire        refrq_n
`ifdef V35S_STATE_DUMP
    ,
    input  wire [3:0]  mutate,              // the arbiter's mutation tests
    // B3: every machine's state after every phase (the EU's, the queue's after each op stage,
    // the arbiter's after X and at the end), the registered ones, the clock's ops and cycle
    output wire [STATE_W-1:0] eu_c,
    output wire [STATE_W-1:0] eu_t,
    output wire [STATE_W-1:0] eu_l,
    output wire [STATE_W-1:0] eu_x,
    output wire [STATE_W-1:0] eu_p,
    output wire [STATE_W-1:0] eu_e,
    output wire [STATE_W-1:0] eu_dump,
    output wire [QSTATE_W-1:0] q_c,
    output wire [JSLOT-1:0][QSTATE_W-1:0] q_ops,
    output wire [QSTATE_W-1:0] q_e,
    output wire [QSTATE_W-1:0] q_dump,
    output wire [ASTATE_W-1:0] a_x,
    output wire [ASTATE_W-1:0] a_e,
    output wire [ASTATE_W-1:0] a_dump,
    output wire [63:0] biu_dump,
    output wire [JSLOT-1:0][32:0] slots,    // the clock's queue ops, in chain order
    output wire [JSLOT-1:0][7:0] slot_rd,
    output wire [4:0]  n_tl,
    output wire [4:0]  n_t,
    output wire [3:0]  n_x,
    output wire [4:0]  n_p,
    output wire [NXOP-1:0][10:0] xops,
    output wire        x_cyc,
    output wire [2:0]  x_cyc_kind,
    output wire [19:0] x_cyc_addr,
    output wire [1:0]  x_cyc_width,
    output wire        req_start,
    output wire        req_ext,
    output wire        b_busy,
    output wire        b_free,
    output wire        b_finf,
    output wire        b_busy_x,
    output wire        b_free_x,
    output wire        b_wl_x
`endif
);
    v35_chain_core #(.NQ(NQ), .NXOP(NXOP), .NXQ(NXQ), .JSLOT(JSLOT), .STATE_W(STATE_W),
                     .QSTATE_W(QSTATE_W), .ASTATE_W(ASTATE_W)) core (.*);
endmodule
