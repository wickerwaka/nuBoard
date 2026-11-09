`timescale 1ns/1ps

// V35S core v2, front end (stage S2 of docs/v35s-core-v2.md): the bus-cycle kinds and widths
// and the fitted constants the front end reads ((Q1) the request rule's room function is gone:
// the queue counts its bytes, v35_queue.sv).
//
// The constants are the tracked fit's (validation/v35s/chains/fit.json, md5
// de193740eaf1dee0862d2220ae084909, fit 62), copied by hand for S2; S1's generated
// v35_consts.svh / v35_class_tbl.svh replace them (the names below are the fit's).
// The build-time macros (V35_Q2_TRI, V35_R1_*, V35_R2_*, V35_R3_*, V35_R4_*, A1_*) are in
// v35_macros.svh.
`include "v35_macros.svh"
package v35_front_pkg;

    // ------------------------------------------------------------ bus cycle kinds and widths
    // (the same encodings as the old core's v35_chain_params.svh, so v35_sfr.sv reads them)
    localparam logic [2:0] K_NONE = 3'd0;
    localparam logic [2:0] K_FETCH = 3'd1;
    localparam logic [2:0] K_READ = 3'd2;
    localparam logic [2:0] K_WRITE = 3'd3;
    localparam logic [2:0] K_IO_READ = 3'd4;
    localparam logic [2:0] K_IO_WRITE = 3'd5;
    localparam logic [2:0] K_REFRESH = 3'd6;
    localparam logic [1:0] BW_WORD = 2'd0;
    localparam logic [1:0] BW_LO = 2'd1;
    localparam logic [1:0] BW_HI = 2'd2;

    function automatic logic k_io(input logic [2:0] k);
        k_io = k == K_IO_READ || k == K_IO_WRITE;
    endfunction
    function automatic logic k_read(input logic [2:0] k);
        k_read = k == K_FETCH || k == K_READ || k == K_IO_READ;
    endfunction

    // ------------------------------------------------------------ (A1) the EU request port
    // the cycle types on the bus unit's EU request port (req_cyc: the pin-level cycle; the SFR
    // page is decoded from the address by the bus unit)
    localparam logic [1:0] RQ_MEMR = 2'd0;
    localparam logic [1:0] RQ_MEMW = 2'd1;
    localparam logic [1:0] RQ_IOR = 2'd2;
    localparam logic [1:0] RQ_IOW = 2'd3;

    // ------------------------------------------------------------ the datapath's request
    // (A1) the cycle a post asks for, as the datapath builds it (v35_eu mkreq): the sequencer's
    // bus interface (v35_ucode.sv, "the EU's bus interface") holds it with its own counts
    typedef struct packed {
        logic [2:0]  kind;
        logic        nowrite;   // grp_read=rmw_slot: the left-out write's slot (kind K_WRITE)
        logic [19:0] addr;
        logic [1:0]  width;
        logic [15:0] data;
        logic        alive;     // the address follows the running form's EA (posted before its
        logic [2:0]  aoff;      //   displacement was taken: pop_mem), + 2 * aoff
        logic        dlive;     // the datum is the running form's result (an RMW's, POP's)
        logic        dimm;      // ... its immediate, taken after the write issued (store_imm):
                                //     the bus takes it at B2
        logic        w16;       // the word's offset is FFFFh: an odd pair's second half wraps to
                                //     the segment's offset 0 (not a live address's: ea_lo's)
    } req_t;

    // ------------------------------------------------------------ fixed structure
    localparam int QUEUE_BYTES = 6;             // queue.QUEUE_BYTES
    localparam int BUS_BASE = 3;                // bus.BASE: B1 B2 B3
    localparam logic [19:0] SFR_PAGE = 20'hFFF00;   // eu.SFR_PAGE: an on-chip store
    localparam int WTC_MEM_LSB = 0;             // machine.waits_of: WTC field 0 (memory, fetch)
    localparam int WTC_IO_LSB = 14;             // ... field 7 (I/O, the SFR store)

    // ------------------------------------------------------------ fit integers (fit.json)
    localparam int FIT_HOLD_Q = 3;              // hold_q
    localparam int FIT_IO_RECOVER = 2;          // io_recover
    localparam int FIT_WLATCH = 4;              // wlatch
    localparam int FIT_MIN_GAP = 0;             // min_gap


endpackage
