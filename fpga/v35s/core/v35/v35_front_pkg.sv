`timescale 1ns/1ps

// V35S core v2, front end (stage S2 of docs/v35s-core-v2.md): the bus-cycle kinds and widths,
// the fitted constants the front end reads, and the request rule's room as one function the
// queue evaluates at each stage that reads it.
//
// The constants are the tracked fit's (validation/v35s/chains/fit.json, md5
// de193740eaf1dee0862d2220ae084909, fit 62), copied by hand for S2; S1's generated
// v35_consts.svh / v35_class_tbl.svh replace them (the names below are the fit's).
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

    // ------------------------------------------------------------ the request rule's room
    // queue.room(t) under the fit (room_ir=arrival_idle, word_latch=byte_d, latch_midtake,
    // latch_disp, room_ir_imm=none, modrm_mate=imm, release=byte, take_commit=at_end):
    //   used  = len(bytes) + uncommitted + 2·inflight − (the latched byte, when it is
    //           uncounted: on its delivery clock while the decoder holds the write port, and
    //           neither mid-take nor on a displacement's take clock)
    //   size  = 6, +1 with the IR as a seventh slot (a delivery clock, or no operand bytes
    //           outstanding unless a two-byte-immediate register form runs), `used` counting
    //           the IR byte then; ir_hold takes the slot away (its `used += ir` branch)
    //   used += 1 on a delivery clock that took the ModR/M's word-mate (modrm_mate=imm)
    // (S4) ir_hold takes the slot away once the operand bytes are all taken, or (ea_ir_room)
    // while the form runs its EA clocks; room_ir_pre=modrm: the running TEST r,r / INC-DEC r8
    // with no operand byte taken (fresh) counts the IR as the seventh slot and, on a delivery
    // clock (pre_modrm=arrival), its ModR/M byte as gone; a slot fetch's word (grp_read) is
    // counted on its delivery clock whatever holds the port
    // Signed: −4 .. 7.
    function automatic logic signed [4:0] room_f(
        input logic [3:0] cnt,          // len(bytes): stored + latched
        input logic [2:0] unc,          // taken, not committed
        input logic       inflight,     // a word in flight (or an aborted cycle)
        input logic       lat,          // the latched byte is present
        input logic       arrived_now,  // a word was delivered on this clock
        input logic       port_busy,    // the decoder holds the write port on this clock
        input logic [2:0] nd,           // operand bytes outstanding (decoder.need)
        input logic       disp_now,     // a displacement's take on this clock (latch_disp)
        input logic       ir_v,         // the IR holds an opcode
        input logic       imm16,        // a two-byte-immediate register form runs (room_ir_imm)
        input logic       ir_hold,      // ir_load=disp_data: the IR is no seventh slot
        input logic       mate_now,     // the ModR/M's word-mate taken on a delivery clock
        input logic       ea_act,       // ea_ir_room: t < ea_end
        input logic       fresh,        // room_ir_pre=modrm: decoder.fresh (_pre_room)
        input logic       slot_word,    // the delivered word is a slot fetch's
        input logic [2:0] xk,           // (S5a) the running form: {a displaced LDEA (lea_slot),
                                        // a memory-indirect transfer (xfer_mem_room), a far
                                        // transfer (far_room)}
        input logic       lea_ir,       // (S5a) lea_room=ir: LDEA's EA clocks after its last
                                        // operand byte: the IR's opcode not counted
        input logic       flr           // (S5b) page_ir_room=end: a full-latch bit op runs: an
                                        // empty IR is no seventh slot
    );
        logic signed [5:0] used, size;
        logic lat_now, need_nz, far1, xarr;
        need_nz = nd != 3'd0;
        // far_room=take: a far form's segment word's last byte still to take: no seventh slot
        // on the arrival clock; xfer_mem_room=arrival: a memory-indirect transfer with two or
        // more operand bytes to take: the arrival clock's seventh slot whatever holds the IR
        far1 = xk[0] && nd == 3'd1;
        xarr = arrived_now && xk[1] && nd >= 3'd2;
        used = 6'(cnt) + 6'(unc) + (inflight ? 6'sd2 : 6'sd0);
        // _latched_now (byte_d): the byte counts as a queue byte after its delivery clock,
        // and on it unless the decoder holds the port
        lat_now = lat && arrived_now && port_busy && !slot_word;
        if (lat_now && !need_nz && !disp_now)
            used = used - 6'sd1;
        size = 6'sd6;
        if ((arrived_now && !far1) || ((!need_nz || fresh) && !imm16)) begin
            // (lea_slot=ea: a displaced LDEA's EA clocks before its displacement's take)
            if (((ir_hold && (!need_nz || ea_act)) || (xk[2] && need_nz && ea_act)) && !xarr)
                used = used + (ir_v ? 6'sd1 : 6'sd0);
            else if (flr && !ir_v)
                ;                       // (S5b) page_ir_room=end
            else begin
                size = size + 6'sd1;
                used = used + (ir_v ? 6'sd1 : 6'sd0);
            end
        end
        if (lea_ir && ir_v && size > 6'sd6)
            used = used - 6'sd1;
        if (fresh && arrived_now)
            used = used - 6'sd1;
        if (arrived_now && mate_now)
            used = used + 6'sd1;
        room_f = 5'(size - used);
    endfunction

endpackage
