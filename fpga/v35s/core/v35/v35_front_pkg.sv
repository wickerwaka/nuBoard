`timescale 1ns/1ps

// V35S core v2, front end (stage S2 of docs/v35s-core-v2.md): the bus-cycle kinds and widths
// and the fitted constants the front end reads ((Q1) the request rule's room function is gone:
// the queue counts its bytes, v35_queue.sv).
//
// The constants are the tracked fit's (validation/v35s/chains/fit.json, md5
// de193740eaf1dee0862d2220ae084909, fit 62), copied by hand for S2; S1's generated
// v35_consts.svh / v35_class_tbl.svh replace them (the names below are the fit's).
// (Q2) V35_Q2_TRI: the triple clock's aborted fetch and its retry window (1: built;
// 0: the Q1 core)
`ifndef V35_Q2_TRI
`define V35_Q2_TRI 1'b1
`endif
// (R1) the EU / microcode rules R1 recovers, one macro each (1: built; 0: the 541d91e core)
//   V35_R1_REFILL  refill_start=full_io: after a flush no start while a fetch is on the bus or
//                  the request line stands (the sequencer's Q1_REFILL)
`ifndef V35_R1_REFILL
`define V35_R1_REFILL 1'b1
`endif
//   V35_R1_PGRUN   page_run=field: a 0F memory form's waiting read does not hold the bus unit's
//                  back-to-back sample, once per form (the arbiter's pr_used)
`ifndef V35_R1_PGRUN
`define V35_R1_PGRUN 1'b1
`endif
//   V35_R1_NEED    hold_count=ahead: the arbiter's hold_fetch=le_q subtracts the loader's operand
//                  bytes still to take (need_t) from the bytes counted
`ifndef V35_R1_NEED
`define V35_R1_NEED 1'b1
`endif
//   V35_R1_IRH     ea_ir_room (ir_load=disp_data): the loader's staging byte is occupied while the
//                  IR load is held for the form's data cycle and no operand byte is left
`ifndef V35_R1_IRH
`define V35_R1_IRH 1'b1
`endif
//   V35_R1_NOMEM   request_reissue=no_mem: the arbiter's view of the line stays down
//                  after a fetch issued beside a waiting memory request until the queue changes
`ifndef V35_R1_NOMEM
`define V35_R1_NOMEM 1'b1
`endif
//   V35_R1_FHDATE  free_hold=delivery: the held fetch dates from the clock its hold ends, so it
//                  goes before a request that became issuable then (the arbiter's fetch_first)
`ifndef V35_R1_FHDATE
`define V35_R1_FHDATE 1'b1
`endif
// (R2) the bus unit's / arbiter's sampling of the request line R2 recovers, one macro each
// (1: built; 0: the 0a696bc core)
//   V35_R2_SLOT    slot_room=word: the left-out write's slot chosen on a word's delivery clock
//                  runs a fetch (the bus unit chose the slot's cycle before the word was written:
//                  the delivered word is room)
`ifndef V35_R2_SLOT
`define V35_R2_SLOT 1'b1
`endif
//   V35_R2_GDLUP   grp_disp=hold's take clock: a fetch goes on the displacement's take clock only
//                  when the line stood before the take (the arbiter's `lup`), not on the room
//                  the take itself frees (room for two words after a two-byte take)
`ifndef V35_R2_GDLUP
`define V35_R2_GDLUP 1'b1
`endif
//   V35_R2_DWLUP   dw_lift=moved: a DW-form I/O request moved into the slot takes the bus unit's
//                  sample from before the move-in (`lup`, the line up on a bus without a fetch
//                  in flight) as its post's sample, not the line on the move-in clock
`ifndef V35_R2_DWLUP
`define V35_R2_DWLUP 1'b1
`endif
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

    // ------------------------------------------------------------ the EU's request record
    // (as posted: arbiter.Request's fields as eu._post / _submit set them; S4)
    typedef struct packed {
        logic [2:0]  kind;
        logic        nowrite;   // grp_read=rmw_slot: the left-out write's slot (kind K_WRITE)
        logic [19:0] addr;
        logic [1:0]  width;
        logic [15:0] data;
        logic [6:0]  setup;
        logic        fn_v;      // free_need is set (None: every setup clock fetch-free)
        logic [6:0]  fn;        // free_need ((S5a) 7 bits: BRK's rfree 8, a shift's setup - sthru)
        logic [1:0]  lead;
        logic        port;      // an I/O form with a port byte
        logic        detached;  // io_release=post
        logic        grp;       // grp_free_bus (free_bus)
        logic [6:0]  through;   // rmw_alu=through: setup clocks that count through a fetch
        logic        imm1;      // imm1_first: a one-byte-immediate memory form's first request
        logic        gdisp;     // grp_disp=hold: a group RMW form's read after its d16
        logic        sreg;      // sreg_store=own: MOV r/m,sreg's write
        logic        whole;     // pop_read_hold=queue: the hold compares the whole queue
        logic        restart;   // call_far_post=take: free_run restarts the free clocks
        logic [3:0]  nb;        // not_before - t at the post (disp_floor, imm_count=start)
        logic [1:0]  rl;        // the posting class's relatch (port_latch=relatch)
        logic        alive;     // the address follows the running form's EA (posted before its
        logic [2:0]  aoff;      //   displacement was taken: pop_mem), + 2 * aoff
        logic        dlive;     // the datum is the running form's result (an RMW's, POP's)
        logic        dimm;      // ... its immediate, taken after the write issued (store_imm):
                                //     the bus takes it at B2
        // (S5a)
        logic        nwt;       // io_count=nowait: the setup counts every clock but a wait
                                // state (an I/O request; str_count / burst_count = dw)
        logic        dwl;       // dwlike: a string's / PUSH R's request counted as a DW-form
                                // I/O request's (dw_count)
        logic        memc;      // str_in_io=free: an unprefixed INM's I/O read counted as a
                                // memory request's (the sequencer's)
        logic        fhd;       // floor_hold: the floor (str_single_start=write) holds fetches
        logic        strc;      // a string form's (str_io_latch=write: its I/O write latched)
        logic        mfr;       // mul_imm_count=sync: MUL imm memory's read, counted by mul_free
        logic [3:0]  c0;        // ... its count at the post (the clean clocks since mul_from;
                                //     (S5b) page_mem=fixed: the fetch-free clocks back to the
                                //     start, pf_cnt)
        // (S5b) the 0F page's read (page_mem=fixed, bf_read=fixed: Request.pfree is set)
        logic        pfv;       // pfree: every setup clock fetch-free since a fetch not
                                //     committed back to back after the post (page_free)
        logic        prw;       // run_wait (page_run): a committed fetch's wait clocks not counted
        logic [1:0]  pth;       // pthru (page_cl=thru): the last setup clocks that count through
                                //     a fetch requested after the post (the CL clocks)
        logic [2:0]  ftl;       // ftail: a bit field's read issues once ftl clocks passed since
                                //     the last fetch's end
        // (S6)
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
