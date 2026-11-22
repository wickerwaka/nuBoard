`timescale 1ns/1ps

// V35S core v2: the bus unit (docs/v35s-core-v2.md, "Modules and the state they own"; Appendix
// B §1 "Bus unit (BIU)"; (A1) docs/v35s-arbiter-strategy.md §2). One cycle at a time: B1, B2,
// waits, B3. A cycle granted on CPU clock s with w waits occupies s .. s+2+w (bus.py); its last
// clock is B3 and its datum is delivered on the next clock (data_ready=0), from the delivery
// registers written at the edge that ends the cycle. (WO30) A memory cycle or fetch takes the
// waits of the WTC field of its own address's block (A19-A17, the top two blocks one field: 6),
// an I/O cycle field 7's, an on-chip cycle none (3 clocks, never on the pins); READY lengthens
// only a cycle whose field is 3 (PMC1 bit 7). validation/v35s/wtc.py, the f4_wtc_* receipts.
//
// The pin timing and the read latch are v35_biu.sv's (lines 290-350), verbatim: a cycle granted
// on clock s shows B1 on the pins in the CPU state after s's `ce_a`; /MREQ (or /REFRQ) falls
// mid-B1, /IOSTB and a read's /MSTB mid-B2, a memory write's /MSTB mid-way through the state
// before B3, every strobe rises mid-B3, where read data is latched.
//
// (A1) The grant. The arbiter is gone: the bus unit grants its own cycles from two request
// ports, the EU's and the queue's, by one fixed priority evaluated once a clock on a free bus:
//   0. the odd word's second half (the bus unit's own pair: a memory word at an odd address
//      runs hi, then lo);
//   1. the EU's request (`req_v`);
//   2. the queue's fetch, when its line is up;
//   3. nothing.
// (qprobe rule 2) The back-to-back commitment (`b2b`: the line sampled at a fetch's last clock,
// winning over the EU) is gone: on the clock after a fetch's last clock the queue's line reads
// its own count against a threshold of 5 (the queue's), and an EU request standing wins.
// (step D) The rule-only terms are gone: the aborted fetch cycle (the triple clock's, and the
// committed b2b fetch whose line fell), the I/O issue's hold of a rising line (`ioh`), the I/O
// recovery window (a fitted integer), the EU's reservation with the queue's low hint
// (a fitted integer), and the phase facts only the sequencer's removed stalls read.
// The EU request port is the cycle type (memory read / write, I/O read / write), the address,
// the width (byte / word) and the datum (latched at B2: the write datum latch below); the bus
// unit answers `req_ack` (the request's first cycle issued now) and `req_done` (its last cycle
// ended on the last clock, the datum in `done_data`). Nothing on the port names an instruction:
// the bus unit knows no form, class, row, step or count. The grant is a handful of terms on
// registered facts (the cycle's position, the pair's half) and the two request lines.
// (MX5c) It is formed for each value of the queue's line and selected by the line last, and the
// pins' registers load per group from the line's select (README "MX5" round 3).
//
// Clocking: `ce_a` ends a CPU clock; the registers hold the state at the end of the last clock.
// Everything this module outputs is stage S0 (registers only) except the grant, which is S4 and
// is written at the edge. (The trace's and the function bench's views of the bus unit, the
// cycle running and the granted cycle's length, are read from its nets by v35_top's
// observation block: no port carries them.)
//
// Registered state (widths) and the model variables it replaces:
//   c_valid 1, c_kind 3, c_pos 3, c_len 3, c_addr 20, c_width 2, c_half 2, c_internal 1
//                                            bus.current (kind, t - start, length, ...)
//   p2_v 1                                   (A1) the odd word's second half is next
//   dlv_v 1, dlv_kind 3, d_p1 1, done_data 16
//                                            the cycle that ended on t-1 (bus.completed), its
//                                            read datum (latched mid-B3); d_p1: the pair's first
//   ((consol) the write datum latch wd_r / wd_w is gone: the EU's request datum is its own
//   register from the post to the cycle's end, `rq_d`, qprobe round 6)
module v35_bus
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,          // end of a CPU clock
    input  wire        ce_b,          // (S7b) the CPU clock's second tick (the pipeline registers)
    input  wire        ce_e,        // (S7b) the CPU clock's edge (the pins' B1 / B2)
    input  wire        ce_mid,      // the middle of a CPU clock (strobe edges)
    input  wire [15:0] wtc,
    // (F1) the on-chip decision (registers): IDB, PRC.RAMEN; (step B) the on-chip cycle's two
    // targets' read data (registers: the SFR page's, the register RAM's port C)
    input  wire [7:0]  idb,
    input  wire        ramen,
    input  wire [15:0] sfr_rd,
    input  wire [15:0] oc_rd,

    // (A1) the EU's request port (tick A)
    input  wire        req_v,       // a cycle is wanted (a level: stands until acknowledged)
    input  wire [1:0]  req_cyc,     // RQ_MEMR, RQ_MEMW, RQ_IOR, RQ_IOW
    input  wire [19:0] req_addr,    // the cycle's address (the pair's second half's after req_ack)
    input  wire        req_width,   // 1: a word (at an odd address, memory or (F5b) I/O: the bus unit's pair)
    input  wire [15:0] req_data,    // a write's datum, latched at B2 (lane-placed for a byte)
    // (F3b) the request (an RQ_IOR) is an INT acknowledge: the cycle runs as an I/O read with no
    // strobe on the pins and /INTAK low from mid-B1 to mid-B3 (silicon, f3_int: /INTAK low two
    // clocks, no /MREQ, /IOSTB or /MSTB); the read latch takes D7-D0 as for any read
    input  wire        req_ia,
    output reg         intak_n,
    // (F4c) the request is a DMA transfer's cycle: an ordinary memory cycle with `dk` high from
    // mid-B1 to mid-B3 (DMAAK's window: f4_dma, DMAAK low 4.5 clocks of a 5-clock cycle) and
    // `dkt` from mid-B2 for two clocks (TC's: low 2 clocks, inside DMAAK; (F4p) two clocks at
    // 0, 1 and 2 waits alike: validation/v35s/prio.py f4p_dma tc_w0 / tc_w1 / tc_w2)
    input  wire        req_dk,
    output reg         dk,
    output reg         dkt,
    // (F4d) bus hold: HLDRQ as v35_sfr registers it (PMC2 bit 7); /HLDAK (P26). The hold bit
    // (`hold`, a ce_a register) stops every grant but a pair's second half; /HLDAK falls at the
    // pins' edge a clock after the bus went idle under it and rises at the edge after HLDRQ
    // falls, the hold bit staying until then (f4_hold: /HLDAK 1.5 clocks after the cycle in
    // flight ends, 1.5 clocks before the next)
    input  wire        hrq,
    output reg         hlda_n,
    // (F4d) READY: PMC1 bit 7 and the pin's level (v35_sfr's second flop). A memory or I/O
    // cycle on the pins whose WTC field is 3 (2 waits) with PMC1 bit 7 holds its first wait
    // while READY (`rdy_lv`, v35_sfr's pin flop) is low (f4_rdy rd_on: 160 ticks of the
    // harness's hold after the column strobe add 5 clocks to a read or an I/O cycle, none to a
    // write, whose strobe falls after the first wait's samples)
    input  wire        rdy_en,
    input  wire        rdy_lv,
    output wire        req_ack,     // the request's first cycle issued now (S4)
    output wire        req_done,    // its last cycle ended on t-1 (S0; the datum in done_data)
    // the queue's fetch port (Q1): the request line, the address
    input  wire        fetch_req,
    input  wire [19:0] fetch_addr,

    // S4: the grant, as the queue reads it ((step B) the cycle granted, its kind, address and
    // width: this unit's own, the trace's view by name)
    output wire        g_fetch,         // a fetch issued now (the queue's fetch accepted)

    // S0
    output wire        eu_dlv,          // an EU cycle's datum is delivered now (either half of a pair)
    output wire        dlv_fetch,       // (step B) a fetch ended on t-1: its word is delivered
    output wire [15:0] done_data,       // the read datum of the cycle that ended on t-1 (on the
                                        //   pins mid-B3: (S7b) live through the delivery clock,
                                        //   then latched)
    output wire [15:0] done_nx,         // (F5t) tick B: done_data's next value (the datum register's D)
    output wire        done_ld,         // ... and its load (the register's enable)
    // (MX5c) the next values of S0 facts (tick B: the state the coming ce_a loads, the D nets
    // of the registers below), for the sequencer's registered stall outcome (through the
    // loader's q_stall_nx and the EU's opr_rdy_nx / rq_busy_nx)
    output wire        dlv_fetch_nx,    // (step B) dlv_fetch's
    output wire        eu_done_nx,      // req_done's
    // (consol, README "consol") The pace: the bus unit owns the front end's measured waits and
    // returns one registered hold to the sequencer (ph_nx, tick B: the word executing on the
    // next clock waits). It reads the next word's kind (wk_nx, the sequencer's: the dispatch
    // word, a FLUSH word, the bus-wait kind's bits) and whether the word executes now (ex, the
    // sequencer's registered stall outcome); the EU's request standing next and its memory
    // request posted and not granted next (eu_rq_nx, rqm_nx); the queue's count compares (lv_q
    // tick A, lv_nx tick B); the loader's instruction-stream facts (sf_nx). Round 6 exported
    // fb_nx, cb_nx, fl_nx, sl_nx and fy_nx from here, the loader b4_nx, ew_nx, ld_nx and le_nx,
    // the EU req_v_nx and rqm_nx into the sequencer, which formed the stall and the give-way
    // (lpri) there; the give-way, REQ_PRI's request word (rqx) and HALT's stop (fstop) were the
    // queue's and the loader's, the count's compares the loader's (c4_nx, c5_nx, cf_nx) and the
    // queue's (c4_q, cf_q)
    input  v35_wk_t    wk_nx,
    input  wire        ex,
    input  wire        eu_rq_nx,
    input  wire        rqm_nx,
    input  v35_lvq_t   lv_q,
    input  v35_lvn_t   lv_nx,
    input  v35_sf_t    sf_nx,
    output wire        ph_nx,

    // (F1, step B) the on-chip cycle (below): the SFR page's access port (a store's write: the
    // enable at ce_a, the address, width and lane-placed datum; (WO31) in the cycle's first
    // clock, a timer register's as its wait ends; the read: (step C) the same address and width,
    // a read cycle's strobe) and the internal RAM's write port (the register RAM's port C: written
    // at the coming ce_b; the EU's segment flops read it too)
    output wire        sfr_wr,
    // (work order 37; sfr_pend: allowed by the user 2026-11-20) an SFR store is captured and lands
    // at the coming ce_a (not a timer register's, which lands as its wait ends; not the internal
    // RAM's): registers only. v35_sfr's port-pin copies take its byte at the ce_b before (the CPU
    // clock's edge), as silicon's pins do
    output wire        sfr_pend,
    output reg  [19:0] sfr_a,
    output reg  [1:0]  sfr_w,
    output wire [15:0] sfr_d,
    output wire        sfr_rdgo,
    output reg         oc_we,
    output reg  [6:0]  oc_wa,
    output reg  [1:0]  oc_be,
    output reg  [15:0] oc_wd,

    // pins (as v35s_model.sv)
    output wire        a0,
    output wire        a19,
    output wire        a18_ube,
    output wire [8:0]  mux_address,
    output reg  [15:0] data_out,
    output reg         mreq_n,
    output reg         mstb_n,
    output reg         iostb_n,
    output wire        read_write,
    output reg         refrq_n,
    input  wire [15:0] data_in
);
    function automatic logic [2:0] rf_len(input logic [1:0] rfw);   // 3 + RFM.RFW
        case (rfw)
            2'd0: rf_len = 3'd3;
            2'd1: rf_len = 3'd4;
            default: rf_len = 3'd5;
        endcase
    endfunction

    // ------------------------------------------------ registered state (end of clock)
    reg         c_valid = 1'b0;
    reg  [2:0]  c_kind = K_NONE;
    reg  [2:0]  c_pos = 3'd0;
    reg  [2:0]  c_len = 3'd0;
    reg         c_internal = 1'b0;
    reg         c_ia = 1'b0;            // (F3b) the cycle is an INT acknowledge
    reg         g_ia_b = 1'b0;          // (F3b) ... granted now (the ce_b register)
    reg         c_dk = 1'b0;            // (F4c) the cycle is a DMA transfer's
    reg         g_dk_b = 1'b0;          // (F4c) ... granted now (the ce_b register)
    reg         c_rdy = 1'b0;           // (F4d) the cycle waits for READY (WTC field 3, PMC1 bit 7)
    reg         g_rdy_b = 1'b0;         // (F4d) ... granted now (the ce_b register)
    reg         c_tmw = 1'b0;           // (WO31) the cycle is a timer register's (it waits for the grid)
    reg         g_tmw_b = 1'b0;         // (WO31) ... granted now (the ce_b register)
    reg  [2:0]  gph = 3'd0;             // (WO31) the free-running divide-by-six (ce_a, from reset)
    reg         hold = 1'b0;            // (F4d) the bus held: no grant (a ce_a register)
    reg         hold_e = 1'b0;          // (F4d) the hold bit at the pins' last edge (the state
                                        //   boundary that enters the hold)
    reg         hk = 1'b0;              // (F4d) held and idle at the pins' last edge
    reg  [19:0] c_addr = 20'd0;
    reg  [1:0]  c_width = BW_WORD;
    reg  [1:0]  c_half = 2'd0;      // (A1) 0: a cycle of its own, 1: a pair's first, 2: its second
    reg         p2_v = 1'b0;        // (A1) the pair's second half is next
    reg         d_v = 1'b0;
    reg  [2:0]  d_kind = K_NONE;
    reg         d_p1 = 1'b0;

    // ------------------------------------------------ S0
    wire last_clock = c_valid && c_pos == c_len - 3'd1;
    wire busy = c_valid && !last_clock;     // a cycle started on an earlier clock runs on t
    wire [2:0] pos_now = c_pos + 3'd1;
    wire free = !busy;              // bus.free(t) (min_gap 0; (A1) disp_io=extend's gap clock not built)
    assign eu_dlv = d_v && d_kind != K_FETCH;
    assign req_done = eu_dlv && !d_p1;
    assign dlv_fetch = d_v && d_kind == K_FETCH;

    // ------------------------------------------------ S4: the grant (one priority)
    wire [2:0]  rq_kind = req_cyc == RQ_MEMR ? K_READ : req_cyc == RQ_MEMW ? K_WRITE
                        : req_cyc == RQ_IOR ? K_IO_READ : K_IO_WRITE;
    // the pair: (F5b) a word at an odd I/O port too (silicon: two byte cycles); (WO31) a word in
    // the SFR page at any address (silicon, f4_oc_v / f4_oc_s: every even offset is two byte
    // cycles, low address first, 3 clocks each: a byte-wide path). `rq_spg`: the request
    // register's address in IDB:F00-FFF (rq_sfr's compare's terms with bit 8; FFFFF is odd
    // already). Each half's lane is its own byte's address (an odd pair high then low, an even
    // pair low then high): the EU loads the second byte's address at the first half's grant
    wire        rq_spg = req_addr[19:12] == idb && req_addr[11:8] == 4'hF;
    wire        rq_two = req_width && (req_addr[0] || rq_spg);
    wire        g_second = free && p2_v;
    // (F4d) the grants but the pair's second half need the bus not held (one registered term)
    wire        free_h = free && !hold;
    // (MX5c) the grant expanded on the request line (Shannon's expansion on the bus unit's own
    // input): `gnt_f(fr)` is the priority below with fetch_req = fr, every other input as it
    // stands; the grant is `fetch_req ? gnt_f(1) : gnt_f(0)`, the line selecting last. The bus
    // unit reads nothing it did not read before (the same function; `+v35_chk` compares it with
    // the direct form every clock). README "MX5" round 3
    typedef struct packed {
        logic       start, fetch, ack, sfr, rdy;
        logic [2:0] kind, blen;
        logic [1:0] width, half;
    } v35_gnt_t;
    // lengths: bus.length(kind). (F4d) A field of 3 is 2 waits, and READY's with PMC1 bit 7
    // (f4_rdy rd_off: WTC FFFFh, 5-clock cycles as field 2's)
    // (WO30) The field per cycle, by its own address (silicon: f4_wtc_d / f / k / m / r / w, every
    // measured cycle): field n = A19-A17, the top two blocks one field (C0000h-FFFFFh: 6);
    // field 7 every I/O cycle (both halves of an odd port's word); an on-chip cycle (IDB page,
    // FFFFFh) no field at all (f4_wtc_x: 3 clocks under every WTC). One length and one READY fact
    // per source, each from the address the grant itself drives and the WTC register (an 8:1
    // select beside the grant, as rq_sfr's compare), joining the grant at the length's select by
    // the terms it had:
    //   the fetch:  fetch_addr[19:17] read directly (the queue's PS base + pfp, the address
    //               g_addr takes for a fetch: the field cannot disagree with the cycle's address
    //               on any clock). (WO30 v2) Not a register: fetch_addr also moves without a
    //               flush (MOV PS,r/m: the queue is not redirected, a fetch at the new PS is
    //               granted in the tick after the PS load; the secure bench A_nc_modrm), and the
    //               bus unit sees neither PS's load nor pfp's;
    //   the EU's:   the request register's own address (req_addr: posted at ce_a and grantable
    //               in the tick after, so read directly, not through a register of its own); a
    //               pair's second half reads it too, the EU having loaded the second byte's
    //               address at the first half's grant (lin2: the block of address + 1); a DMA
    //               cycle is an EU request;
    //   I/O:        field 7.
    // WTC and PMC1 are read as they stand (no register between: a store takes effect on the
    // grant after its cycle's delivery, as before)
    function automatic logic [2:0] wblk(input logic [2:0] a);      // the field of A19-A17
        wblk = (a[2] && a[1]) ? 3'd6 : a;
    endfunction
    function automatic logic [1:0] wfld(input logic [15:0] w, input logic [2:0] n);
        wfld = w[{n, 1'b0} +: 2];
    endfunction
    function automatic logic [2:0] wlen(input logic [1:0] f);     // 3 + the field's waits
        wlen = f == 2'd3 ? 3'(BUS_BASE) + 3'd2 : 3'(BUS_BASE) + {1'b0, f};
    endfunction
    wire [1:0] wf_fetch = wfld(wtc, wblk(fetch_addr[19:17]));
    wire [1:0] wf_req = wfld(wtc, wblk(req_addr[19:17]));
    wire [1:0] wf_io = wtc[WTC_IO_LSB +: 2];
    wire [2:0] bl_fetch = wlen(wf_fetch);
    wire [2:0] bl_req = wlen(wf_req);
    wire [2:0] bl_io = wlen(wf_io);
    wire       rdy_fetch = rdy_en && wf_fetch == 2'd3;
    wire       rdy_req = rdy_en && wf_req == 2'd3;
    wire       rdy_io = rdy_en && wf_io == 2'd3;
    // (MX5) a write's address is the request's (a write is never a fetch: g_kind K_WRITE implies
    // g_addr = req_addr), so the SFR page's compare reads the request register, not the grant
    // (F1) an on-chip memory cycle: the request's address in the page IDB:E00-FFF (E00-EFF the
    // internal RAM while RAMEN = 1, F00-FFF the SFRs) or FFFFF (IDB at any IDB): read or write,
    // no pins, (WO30) 3 clocks under every WTC (f4_wtc_x: no field lengthens an on-chip access;
    // it took field 7's waits before). From registers only (the request register, IDB, PRC): an 8-bit compare beside
    // the grant, joining it at the length's select as the old SFR compare did
    wire rq_sfr = (req_addr[19:12] == idb && req_addr[11:9] == 3'b111 && (req_addr[8] || ramen))
                  || req_addr == 20'hFFFFF;
    // (WO31) the timer unit's registers (TM0 MD0 TM1 MD1 TMC0 TMC1: offsets 80h-83h, 88h-8Bh,
    // 90h, 91h; silicon f4_oc_t / f4_oc_v: no other offset waits): a byte cycle there ends on
    // the free-running divide-by-six (the timer's count clock), the first grid point at least 4
    // clocks after its start. Granted 4 clocks (3 and the one wait every such cycle has), the
    // wait held on the grid (`tm_hold`, below) as READY's is: the length's select reads one more
    // per-source fact from the request register (an 8-bit compare beside rq_sfr's)
    wire rq_tmr = rq_spg && ((req_addr[7:4] == 4'h8 && !req_addr[2]) || req_addr[7:1] == 7'h48);
    wire [2:0] bl_sfr = rq_tmr ? 3'(BUS_BASE) + 3'd1 : 3'(BUS_BASE);
    // req_ia with req_v: on a memory write the write is not armed (its datum loaded by the EU's
    // current word, K); with req_v low (qprobe round 18, spec 13 A1 / Q69): a request announced
    // by its reserving word and not yet posted (`rsv`: its address not formed, it may not start)
    wire un_w = req_ia && req_v && req_cyc == RQ_MEMW;
    wire rsv = req_ia && !req_v;
    function automatic v35_gnt_t gnt_f(input logic fr);
        logic eu_win, eu;
        // (qprobe round 12, spec 7 A2 / Q33) req_ia on a memory write: its datum is loaded by
        // the EU's current word (K, not yet armed): granted only if that word executes now (ex),
        // and not against a chained fetch (a fetch asked for on the clock after a fetch's last,
        // dlv_fetch, decided on that fetch's next-to-last clock from the count, dc: registers):
        // the unarmed posted write does not compete with it. (qprobe round 18, spec 13 A1 / Q69)
        // Nor does a request that was only announced when the decision was taken (`dr`: a
        // read or a write of the C7 / 81 displacement cells, reserved on the word releasing
        // the displacement): it competes from its due clock, the decided fetch first
        // (qprobe round 21, spec 17 A1 / Q95) nor does a read requested inside the fetch chain
        // behind an EU cycle (`lcr`, registers): the chain runs while five or fewer are held
        eu_win = free_h && !g_second && req_v && !((un_w || dcu || dr) && fr && dlv_fetch && dc) && !(un_w && !ex)
                 && !(lcr && (fetch_req || lv_q.r5)) && !((lcw || aid) && fr);
        gnt_f.fetch = free_h && !g_second && !eu_win && fr;
        gnt_f.ack = eu_win;
        eu = g_second || gnt_f.ack;         // an EU cycle issued now (either half of a pair)
        gnt_f.start = eu || gnt_f.fetch;
        gnt_f.kind = gnt_f.fetch ? K_FETCH : g_second ? c_kind : rq_kind;
        // (WO31) a pair's halves by their own byte's address (req_addr: the second byte's on
        // the second half)
        gnt_f.width = !eu ? BW_WORD : (req_width && !g_second && !rq_two) ? BW_WORD
                    : (req_addr[0] ? BW_HI : BW_LO);
        gnt_f.half = g_second ? 2'd2 : (gnt_f.ack && rq_two) ? 2'd1 : 2'd0;
        gnt_f.sfr = (gnt_f.kind == K_WRITE || gnt_f.kind == K_READ) && rq_sfr;
        // (WO30) the source's length: the fetch's field, an I/O cycle's field 7, an on-chip
        // cycle 3 ((WO31) a timer register's 4, its wait held on the grid), an EU memory cycle
        // its request address's field
        gnt_f.blen = gnt_f.fetch ? bl_fetch : k_io(gnt_f.kind) ? bl_io
                   : gnt_f.sfr ? bl_sfr : bl_req;
        gnt_f.rdy = gnt_f.fetch ? rdy_fetch : k_io(gnt_f.kind) ? rdy_io : !gnt_f.sfr && rdy_req;
    endfunction
    v35_gnt_t gn1, gn0, gn;
    assign gn1 = gnt_f(1'b1);
    assign gn0 = gnt_f(1'b0);
    assign gn = fr ? gn1 : gn0;
    wire        g_start;            // a cycle starts now (a fetch or an EU cycle)
    wire [2:0]  g_kind;
    wire [19:0] g_addr;
    wire [1:0]  g_width;
    assign g_fetch = gn.fetch;
    assign req_ack = gn.ack;
    assign g_start = gn.start;
    assign g_kind = gn.kind;
    assign g_addr = gn.fetch ? fetch_addr : req_addr;
    assign g_width = gn.width;
    wire [1:0]  g_half = gn.half;

    wire g_sfr = gn.sfr;
    wire [2:0] grant_len = gn.blen;      // the length of the granted cycle
    // (qprobe round 15, spec 11 I7) the INT acknowledge is one cycle of six clocks with two
    // /INTAK pulses (silicon, Q55: low two clocks, high one, low two; the vector byte read at the
    // second pulse's end): its length set at the grant's register, the pulses below
    wire       g_ia = gn.ack && req_ia && req_cyc != RQ_MEMW;
    localparam logic [2:0] IA_LEN = 3'd6;

    // ------------------------------------------------ (S7b) the ce_b registers
    // the grant (S4), registered at the end of tick A: the end of the clock (the cycle's start,
    // the pins at ce_a) reads these, never tick A's logic
    reg         g_start_b = 1'b0, g_sfr_b = 1'b0, fetch_req_b = 1'b0;
    reg  [2:0]  g_kind_b = K_NONE, grant_len_b = 3'd0;
    reg  [19:0] g_addr_b = 20'd0;
    reg  [1:0]  g_width_b = BW_WORD, g_half_b = 2'd0;
    always @(posedge clock) begin
        if (!reset_n)
            g_start_b <= 1'b0;       // (the strobes at ce_mid read it before the first ce_b)
        else if (ce_b) begin
            g_start_b <= g_start;
            g_sfr_b <= g_sfr;
            g_ia_b <= g_ia;     // (F3b) the EU's cycle granted is an acknowledge (req_ia on a read)
            g_dk_b <= gn.ack && req_dk;     // (F4c) ... a DMA transfer's
            g_rdy_b <= gn.rdy;              // (F4d) the cycle granted waits for READY
            g_tmw_b <= gn.sfr && rq_tmr;    // (WO31) ... is a timer register's (waits for the grid)
            fetch_req_b <= fr;
            g_kind_b <= g_kind;
            grant_len_b <= g_ia ? IA_LEN : grant_len;
            g_addr_b <= g_addr;
            g_width_b <= g_width;
            g_half_b <= g_half;
        end
    end

    // ------------------------------------------------ the end of the clock (S6)
    // (F4d) READY's wait: the cycle's first wait (pos 2) repeats while READY is low at the
    // clock's middle (registers only: c_rdy, the position, v35_sfr's pin flop rdy_lv; work order 33)
    wire        rdy_hold = c_rdy && pos_now == 3'd2 && !rdy_lv;
    // (WO31) a timer register's byte cycle: its wait (pos 2) repeats until the clock before its
    // last is the grid's G_REL (the cycle then ends on the grid point: its last clock is the
    // next, the following cycle starts on the grid). Registers only (c_tmw, the position, gph).
    // G_REL (v35_front_pkg, shared with v35_timer): the grid's phase against reset (README "Work
    // order 31": read from the f4_oc_t / f4_oc_e receipts, one value for every window)
    wire        tm_hold = c_tmw && pos_now == 3'd2 && gph != G_REL;
    wire        pos_hold = rdy_hold || tm_hold;     // the cycle's first wait repeats
    // (MX5c) the next values the always block below loads (the delivery's)
    wire        d_v_nx = busy && pos_now == c_len - 3'd1;
    assign dlv_fetch_nx = d_v_nx && c_kind == K_FETCH;
    assign eu_done_nx = d_v_nx && c_kind != K_FETCH && !(c_half == 2'd1);
    // (qprobe rules 4, 5) the cycle registers' next values (the block below loads these) and
    // what they say of the next clock: a fetch started on an earlier clock runs then (fb_nx),
    // a cycle of any kind runs then, not on its last clock (cb_nx)
    wire        cv_nx = g_start_b || busy;
    wire [2:0]  ck_nx = g_start_b ? g_kind_b : c_kind;
    wire [2:0]  cp_nx = g_start_b ? 3'd0 : pos_hold ? c_pos : pos_now;
    wire [2:0]  cl_nx = g_start_b ? grant_len_b : c_len;
    wire        bz_nx = cv_nx && cp_nx != cl_nx - 3'd1;
    wire        fb_nx = bz_nx && ck_nx == K_FETCH;
    wire        fl_n = cp_nx + 3'd1 == cl_nx - 3'd1;        // the next clock is the cycle's last
    // (qprobe round 11, Q32 / A1) an odd word's two byte cycles are one EU cycle: on the first
    // half's last clock the cycle is not ending (its second half is due: c_half 1), and the
    // second half's first clock is a cycle running (p2_v: the second half is next and nothing
    // runs; it is granted on that clock, nothing between). Registers only (c_half, the grant's
    // ce_b register, p2_v)
    wire        ch1_nx = (g_start_b ? g_half_b : c_half) == 2'd1;
    wire        pr_nx = p2_v && !bz_nx;
    wire        bp_nx = bz_nx || pr_nx;
    wire        cb_nx = (bz_nx && (!fl_n || ch1_nx)) || pr_nx;

    // ------------------------------------------------ (qprobe round 6, B) the sequencing stage
    // The bus unit sequences a cycle in a stage ahead of its pins (the "slot",
    // validation/v35s/qprobe/model_m.py S_LAG / EU_SLOT / CHAIN_POP: the qprobe groups o6*, gb,
    // gd, gf, mm, ld-out8). From an idle bus the slot is the pin cycle itself; an EU cycle's slot
    // runs two clocks ahead of its pins (from the request's standing to two clocks before its
    // last pin clock), and so does the slot of a fetch wanted while an EU cycle held the bus
    // (`pend`) and of every fetch chained behind such a fetch back to back (`lg`: the running
    // fetch is "lagged"; `nl`: on a lagged fetch's next-to-last clock the stage has decided to
    // chain the next fetch, the queue's count with the word in flight at most 5), until the bus
    // goes idle; a chained fetch whose first clock carries a release is an ordinary fetch again
    // (the release restarts the request). The words that wait by the slot: the I/O request
    // words, OUT DW's first word, SHL r,CL's fourth word (rl=x without bi); the boundary, the
    // bus-idle words and the flush wait for the pin cycle. `sk`: the fetch gave way to a
    // boundary on this clock (rule E: EU_EPRI / LEAD_EPRI), the pending fetch keeps its slot.
    // Three registers (lg, nl, pend), their next values formed in tick A and registered at ce_b
    // (`*_b`, with sk_b), so the slot of the next clock (sl_nx) is formed in tick B like the
    // other stall facts.
    reg         lg = 1'b0, nl = 1'b0, pend = 1'b0;
    reg         lg_b = 1'b0, nl_b = 1'b0, pd_b = 1'b0, sk_b = 1'b0;
    reg         fe = 1'b0, fe_b = 1'b0;     // (qprobe round 13, Q42) the running fetch followed an EU cycle
    // (qprobe round 12, spec 7 A2 / Q33 fact 1) the chained fetch is decided on the running fetch's
    // next-to-last clock from the count then (the queue's cf: the count with the word in flight at
    // most 5): `dc`, the decision an unarmed write gives way to (any fetch, not only a lagged one)
    reg         dc = 1'b0, dc_b = 1'b0;
    // (qprobe round 17, spec 13 A2) the decision stands against a write armed after it: `dcu`,
    // the EU's posted write still unarmed on the running fetch's last clock (its K not executed
    // before that clock), so a K on the fetch's last clock (the write armed one clock before the
    // grant) does not take the decided chained fetch's clock (build check item 1)
    reg         dcu = 1'b0, dcu_b = 1'b0;
    // (qprobe round 18, spec 13 A1 / Q69, Q33 facts 1 and 2) the reserving request against the
    // decision: `dr`, the EU's request announced (rsv) on the decision's clock (it gives way to
    // the decided chained fetch at its due clock, as the unarmed write does); `rh`, the
    // announcement rose on the decision's clock (its reserving word executed on the clock
    // before: the decision's eve), which holds the decision: no chained fetch on the clock after
    // the running fetch's end, the bus idle, the EU's cycle on its due clock. `rs1`: rsv on the
    // last clock (a ce_a register). Registers only, beside dc
    reg         dr = 1'b0, dr_b = 1'b0, rh = 1'b0, rh_b = 1'b0, rs1 = 1'b0;
    wire        in_f = busy && c_kind == K_FETCH;           // a fetch started earlier runs now
    wire        f_last = in_f && pos_now == c_len - 3'd1;      // the running fetch's last clock
    wire        eu_r = busy && c_kind != K_FETCH;           // an EU cycle started earlier runs now
    wire        sec_last = pos_now == c_len - 3'd2;         // the running cycle's next-to-last clock
    wire        gave = gwy && free_h && !g_second && !req_v;    // the fetch that gave way now
    wire        lg_a = g_fetch ? (pend || (lg && nl && dlv_fetch && lv_q.nrl)) : lg;
    wire        nl_a = g_fetch ? 1'b0 : (lg && in_f && sec_last) ? lv_q.cf : nl;
    wire        pd_a = (eu_r || req_ack || g_second) ? (pend || lv_q.c4) : gave ? pend : 1'b0;
    always @(posedge clock) begin
        if (!reset_n) begin
            lg_b <= 1'b0;
            fe_b <= 1'b0;
            dc_b <= 1'b0;
            dcu_b <= 1'b0;
            dr_b <= 1'b0;
            rh_b <= 1'b0;
            nl_b <= 1'b0;
            pd_b <= 1'b0;
            sk_b <= 1'b0;
        end else if (ce_b) begin
            lg_b <= lg_a;
            fe_b <= g_fetch ? pend : fe;
            dc_b <= g_fetch ? 1'b0 : (in_f && sec_last) ? lv_q.cf : dc;
            dcu_b <= g_fetch ? 1'b0 : f_last ? un_w : dcu;
            dr_b <= g_fetch ? 1'b0 : (in_f && sec_last) ? rsv : dr;
            rh_b <= g_fetch ? 1'b0 : (in_f && sec_last) ? (rsv && !rs1) : rh;
            nl_b <= nl_a;
            pd_b <= pd_a;
            sk_b <= gave;
        end
    end
    always @(posedge clock) begin
        if (!reset_n) begin
            lg <= 1'b0;
            fe <= 1'b0;
            dc <= 1'b0;
            dcu <= 1'b0;
            dr <= 1'b0;
            rh <= 1'b0;
            rs1 <= 1'b0;
            nl <= 1'b0;
            pend <= 1'b0;
        end else if (ce_a) begin
            lg <= lg_b;
            fe <= fe_b;
            dc <= dc_b;
            dcu <= dcu_b;
            dr <= dr_b;
            rh <= rh_b;
            rs1 <= rsv;
            nl <= nl_b;
            pend <= pd_b;
        end
    end
    // (qprobe round 21, spec 17 A1 / Q95) the fetch chain behind an EU cycle: a read requested
    // from the chain's first pin clock on is not arbitrated against it. `lc`: the latest fetch
    // was granted with a fetch pending under an EU cycle (pend), or back to back behind such a
    // fetch (dlv_fetch at its grant); `ych`: a memory request word (Y / V: rlx with bi) executed
    // while lc stood (the chain's first grant clock included), cleared by the EU's grant and by
    // a new chain's first grant; `lcr`: on the clock after a chain fetch's last clock (lc,
    // dlv_fetch) the EU's request is that word's read: it does not compete with the fetch (the
    // grant's term with the line: the chain continues while five or fewer are held). A request
    // whose word executed before the chain's first pin clock keeps its place (behind it). Not
    // for writes (Q95: the stores keep spec 13 A1 / Q33). Registers only (wkm: the word's kind,
    // as wkr), the grant's term one AND
    reg         lc = 1'b0, lc_b = 1'b0, ych = 1'b0, ych_b = 1'b0, wkm = 1'b0;
    // (qprobe round 21, C_NOCH) `lw`: the last EU cycle granted was a memory write; `few`: the
    // fetch last granted was granted with a fetch pending under that write (fe with lw)
    reg         lw = 1'b0, lw_b = 1'b0, few = 1'b0, few_b = 1'b0;
    // (r26, work order 22 C5, Q130, model_m CH_EPRI's after_w with CH_K "W") `fx`: the fetch
    // last granted followed a memory write: granted with a fetch pending under it (few), or on
    // the clock the write's last cycle delivers (req_done with lw: the fetch starts on the clock
    // after the write's last pin clock, back to back behind it, with nothing pending under the
    // write: the count stood above four through it). Registers only
    reg         fx = 1'b0, fx_b = 1'b0;
    wire        lw_a = req_ack ? (req_cyc == RQ_MEMW) : lw;
    // (qprobe round 23, spec 18 A1) `lo`: the last EU cycle granted was an I/O write (lw's twin;
    // model_m EU_WPRI_K "O")
    reg         lo = 1'b0, lo_b = 1'b0;
    wire        lo_a = req_ack ? (req_cyc == RQ_IOW) : lo;
    wire        lc_a = g_fetch ? (pend || (lc && dlv_fetch)) : lc;
    wire        ych_a = (ex && wkm && lc_a) ? 1'b1 : (req_ack || (g_fetch && pend)) ? 1'b0 : ych;
    wire        lcr = lc && dlv_fetch && ych && req_cyc == RQ_MEMR;
    // (r25, work order 21 B6, Q123, model_m LCHW) the same for an armed write: a write whose
    // request word executed inside the chain (ych) does not stop the chain's next fetch while
    // five or fewer are held, counted before this clock's releases (`c5r`: the queue's c5 as the
    // last tick B left it for this clock); it starts when the chain ends. Registers only (the
    // grant's term with the line, as the unarmed write's)
    // A write posted unarmed (K later: un_w seen, `wur`) keeps Q33's rules (model_m LCHW "not
    // unarmed": the write's routine has a K word); wur is cleared by the EU's grant
    reg         c4r = 1'b0, c5r = 1'b0, wur = 1'b0, wur_b = 1'b0;
    wire        wur_a = req_ack ? 1'b0 : (un_w || wur);
    wire        lcw = lc && dlv_fetch && ych && req_cyc == RQ_MEMW && !un_w && !wur && c5r;
    // (r25, work order 21 B7, Q125, model_m ARB_IDLE) a request armed on the clock it is due does
    // not stop a fetch that starts from the idle bus with four or fewer held before this clock's
    // releases (`c4r`): the unarmed write whose datum word K executes now (un_w with ex), and the
    // read announced by its reserving word and posted on the last clock (rs1: the announcement
    // stood then; Q33's table holds for it as for the unarmed write, round 17). Not on the clock
    // after a fetch's last (dlv_fetch: the back-to-back case is Q33's, dc). Registers but ex
    wire        aid = !dlv_fetch && c4r && ((un_w && ex) || (rs1 && req_cyc == RQ_MEMR));
    always @(posedge clock) begin
        if (!reset_n) begin
            lc_b <= 1'b0;
            wur_b <= 1'b0;
            ych_b <= 1'b0;
            lw_b <= 1'b0;
            lo_b <= 1'b0;
            few_b <= 1'b0;
            fx_b <= 1'b0;
        end else if (ce_b) begin
            lc_b <= lc_a;
            wur_b <= wur_a;
            ych_b <= ych_a;
            lw_b <= lw_a;
            lo_b <= lo_a;
            few_b <= g_fetch ? (pend && lw) : few;
            fx_b <= g_fetch ? (lw && (pend || req_done)) : fx;
        end
    end
    always @(posedge clock) begin
        if (!reset_n) begin
            lc <= 1'b0;
            wur <= 1'b0;
            ych <= 1'b0;
            lw <= 1'b0;
            lo <= 1'b0;
            few <= 1'b0;
            fx <= 1'b0;
            wkm <= 1'b0;
        end else if (ce_a) begin
            lc <= lc_b;
            wur <= wur_b;
            ych <= ych_b;
            lw <= lw_b;
            lo <= lo_b;
            few <= few_b;
            fx <= fx_b;
            wkm <= wk_nx.rlx && wk_nx.bi;
        end
    end
    // the next clock's view (tick B): its position's clocks left after it (rm_nx, while a
    // cycle started earlier runs then), the cycle that ends now (the delivery then)
    // (consol) the queue's compares for the next clock, by this unit's own delivery then
    v35_lvc_t   lv;
    assign lv = dlv_fetch_nx ? lv_nx.a : lv_nx.n;
    wire [3:0]  rm_nx = {1'b0, cl_nx} - {1'b0, cp_nx} - 4'd2;
    wire        r2_nx = bz_nx && !rm_nx[3] && rm_nx >= 4'd2;
    wire        r1_nx = bz_nx && rm_nx == 4'd1;
    wire        euf_nx = bz_nx && ck_nx != K_FETCH;
    wire        aeu_nx = d_v_nx && c_kind != K_FETCH;
    wire        idle_nx = !bz_nx && !eu_rq_nx;
    wire        slot_nx = (fb_nx && lg_b) ? (r2_nx || (r1_nx ? lv.cf : nl_b))
                        : (!fb_nx && pd_b && lv.c4) ? ((euf_nx && !r2_nx) || (idle_nx && (aeu_nx || sk_b)))
                        : (!fb_nx && lg_b && nl_b && idle_nx && dlv_fetch_nx && lv.c5) ? 1'b1
                        : fb_nx;
    // (EU_SLOT) the EU cycle's own slot: from its request's standing to two clocks before its
    // last pin clock
    wire        sl_nx = slot_nx || eu_rq_nx || (euf_nx && r2_nx);
    // (qprobe round 10, LAG_FIRST) the slot's first clock when it runs ahead of the pins: a
    // lagged fetch's next-to-last pin clock with the chained fetch decided (cf), or the last but
    // one clock of the EU cycle a pending fetch waits behind; the A word (rl=x with alt, OUT
    // DW's first) does not wait on it
    wire        sf_first = (fb_nx && lg_b) ? (r1_nx && lv.cf) : (pd_b && lv.c4 && euf_nx && r1_nx);
    wire        sla_nx = (slot_nx && !sf_first) || eu_rq_nx || (euf_nx && r2_nx);
    // (qprobe round 6, C) a memory request word waits while a fetch has two clocks or more left
    wire        fy_nx = fb_nx && r2_nx;

    // ------------------------------------------------ (consol) the pace
    // Registers (ce_a; the kind also in reset, as the sequencer's word): the word's kind now
    // (`wk`, the word executing this clock), the first boundary of a stream (`aft`: a FLUSH
    // word executed and no dispatch since, rule 4c), a request word executed on the last clock
    // (`rqx`, REQ_PRI), and the boundary's facts as they stand now (the back-to-back fetch at a
    // count of 4, the EU's request standing, the lead's end: the give-way's; HALT released and
    // the word releasing a staged HALT: the line's stop)
    reg         wkd = 1'b0, wkf = 1'b0, wkr = 1'b0;    // (the kind's disp, flush, rlx)
    // (qprobe round 23, spec 18 A1) `wkp`: the word now has no kind at all (no wait, not the
    // dispatch word, not a FLUSH word); `ry1`: a memory request word Y (rlx with bi, not alt)
    // executed on the last clock; `pl1`: a word with no act executed on the last clock (wkp,
    // no byte released); `rqo`: a memory request word (Y / V: rlx with bi) executed and its
    // cycle not yet granted (model_m eu_due: the request outstanding from its word on)
    reg         wkp = 1'b0, ry1 = 1'b0, pl1 = 1'b0, rqo = 1'b0;
    // (r24, model_m CH_BNEXT, results Q42's second half) `wkbn`: the word now has no bus-wait kind
    // and is followed by a bus-idle word (the sequencer's free code flush with alt, no bi)
    reg         wkbn = 1'b0;
    reg         aft = 1'b0, rqx = 1'b0, b4r = 1'b0, rqvr = 1'b0, ler = 1'b0, hpr = 1'b0;
    reg         dst = 1'b0;                 // (qprobe round 13) the dispatch word waited on the last clock
    wire        xd = ex && wkd;                 // the dispatch word executes now (the boundary)
    wire        xf = ex && wkf;                // a FLUSH word executes now
    // tick A: the give-way (round 6, E: the boundary executing now takes this clock from the
    // fetch: on the clock the EU cycle that held a fetch back delivers, EU_EPRI; on its lead's
    // last clock over a back-to-back fetch, LEAD_EPRI); HALT's stop (rule 11: from the word
    // releasing the staged HALT to the halt word); the five-held continuation allowed (rule 2,
    // REQ_PRI: no dispatch word now, no request word on the last clock); the line as the grant
    // reads it (`fr`) and the fetch given way (`gwy`)
    // (qprobe round 13, Q42 / spec 9 A1, first half) carried one fetch further: the fetch chained
    // to the fetch that followed an EU cycle (`fe`: the fetch delivered now was granted with a
    // fetch pending under an EU cycle) gives way to a boundary that arrives fresh on its clock
    // (`dst`: the dispatch word did not wait on the clock before). Registers only. (r26, C5)
    // `fx` beside fe: also the fetch that started back to back behind a memory write with
    // nothing pending under it (Q130: MOV [d16],imm16 ; NOP, the NOP's boundary on t + 6)
    wire        gw = xd && ((pend && eu_dlv) || (b4r && !rqvr && ler) || ((fe || fx) && dlv_fetch && !dst));
    // (fix40) HALT's stop from the clock after the word that pops HALT's opcode (`hpr`), not on that
    // word's own clock: a fetch the line raises there still starts (Q14: nothing is fetched after
    // the pop). Silicon, periph f4_tm's socket trace: behind RETI five refetches at PSW + 19 .. 39
    // whatever the return address's parity, the fifth on the clock the core pops the sled's HALT
    // when the return address is even; the core's pop-clock term cancelled it, the release then
    // started it and the take out of HALT waited 3 clocks for it (f4_tb / f4_tm / f4_tout periods)
    wire        fstop = hpr;
    wire        unused_hc = sf_nx.hc;      // (fix40) the pop clock's term, no longer read here
    // (r24, work order 20 A3, Q112, model_m REQ_PRI=5) behind a memory request word Y executed on a
    // fetch's last clock (`ry1`, on that fetch's delivery) no back-to-back fetch starts at all,
    // four or fewer held too, unless the word now releases a byte (a queue read is a new fetch
    // request: the five-held continuation then as on any clock, not on the boundary's); X / S keep
    // REQ_PRI's five-held bar alone (their code is one)
    wire        rq1 = ry1 && dlv_fetch;
    wire        line = rq1 ? (!lv_q.nrl && (fetch_req || (lv_q.r5 && !xd)))
                           : (fetch_req || (lv_q.r5 && !xd && !rqx));
    // (qprobe round 18, spec 13 A1) the decision held by a reservation on its eve (`rh`): no
    // fetch on the clock after the running fetch's end (dlv_fetch)
    // (qprobe round 23, spec 18 A1 / Q101a; the user's ruling 2026-11-17: built as measured, the
    // register's identity unknown) behind an I/O write (`lo`), on the clock its delivery is seen
    // with a fetch pending under it (EU_EPRI's clock, c3 + 1), the fetch also gives way one
    // clock (keeping its slot, as EU_EPRI's) when (case 1) a memory request word Y executed on
    // the cycle's last clock (`ry1`) or a V word executes now, or (case 2) words with no act
    // executed on the last clock and now (`pl1`, `wkp`, no release) with no request
    // outstanding (none standing, none reserved). Registers only, beside gw; the two cases
    // separately switchable (A1_C1, A1_C2)
    localparam bit A1_C1 = 1'b1, A1_C2 = 1'b1;
    wire        a1p = ex && wkp && lv_q.nrl;        // a word with no act executes now
    wire        a1g = pend && eu_dlv && lo && ((A1_C1 && (ry1 || (ex && wkm && !wkr)))
                      || (A1_C2 && pl1 && a1p && !req_v && !rsv && !rqo));
    // (r24, model_m CH_BNEXT, results Q42's second half: the round-13 rule, not built until now)
    // the fetch chained to the fetch that followed a memory write (`few`, on that fetch's
    // delivery) is not started when the word executing now releases nothing and is followed by
    // a bus-idle word (`wkbn`: the word would have to wait the whole fetch); the bus is idle this
    // clock and the fetch is wanted again from the next (no give-way: the slot is not kept).
    // Registers but the release (lv_q.nrl, as a1p's)
`ifndef SYNTHESIS
    wire        bnx = dlv_fetch && few && ex && wkbn && lv_q.nrl;     // (timing repair 1: in fr's arms, bnx1)
`endif
    // (timing repair 1) the line as the grant reads it, Shannon's expansion on the queue's three
    // late facts: the request line, the five-held continuation (lv_q.r5) and the release (nrl);
    // each arm a function of registers (kept), the late facts selecting last. The same function
    // as `line && !gw && !a1g && !fstop && !(rh && dlv_fetch) && !bnx` (`+v35_chk` every clock)
    wire        g_c = !gw && !fstop && !(rh && dlv_fetch);
    wire        a1g1 = pend && eu_dlv && lo && ((A1_C1 && (ry1 || (ex && wkm && !wkr)))
                       || (A1_C2 && pl1 && ex && wkp && !req_v && !rsv && !rqo));
    wire        a1g0 = pend && eu_dlv && lo && A1_C1 && (ry1 || (ex && wkm && !wkr));
    wire        bnx1 = dlv_fetch && few && ex && wkbn;
    (* syn_keep = "true" *) wire f1_1 = !rq1 && g_c && !a1g1 && !bnx1;            // nrl 1: fetch_req's arm
    (* syn_keep = "true" *) wire f2_1 = !rq1 && !xd && !rqx && g_c && !a1g1 && !bnx1;     // ... r5's
    (* syn_keep = "true" *) wire f1_0 = g_c && !a1g0;                             // nrl 0
    (* syn_keep = "true" *) wire f2_0 = !xd && (rq1 || !rqx) && g_c && !a1g0;
    wire        fr = lv_q.nrl ? ((fetch_req && f1_1) || (lv_q.r5 && f2_1))
                              : ((fetch_req && f1_0) || (lv_q.r5 && f2_0));
`ifndef SYNTHESIS
    wire        fr_x = line && !gw && !a1g && !fstop && !(rh && dlv_fetch) && !bnx;
`endif
    wire        gwy = line && (gw || a1g) && !fstop;
    // tick B: the stream's first boundary after this clock, and the hold
    wire        aft_n = xf ? 1'b1 : xd ? 1'b0 : aft;
    // (rules 4c, 4d, EMIN; rule 11) the boundary waits for the stream: the count below 3 for the
    // first boundary of a stream or a ModR/M opcode's, below 2 for any; not for bytes that will
    // not come (HALT released)
    // (qprobe round 22, spec 18 A3, Q104) the stream facts' free code ld and le both (`sml`): the
    // staged instruction (CALL / JMP near and far through memory: the FF group's m3 is 0, Q44)
    // waits for three bytes behind it, counting the bytes a fetch delivers on its last clock; with
    // one byte or more arriving and the count below 2 already a wait (lt2), that is the three-byte
    // term dropped on a fetch's last clock (fb_nx && fl_n: the next clock is a fetch's last)
    wire        sml = sf_nx.ld && sf_nx.le;
    wire        sld = sf_nx.ld && !sf_nx.le;
    wire        sle = sf_nx.le && !sf_nx.ld;
    wire        ews = ((lv.lt3 && (aft_n || sf_nx.m3 || (sml && !(fb_nx && fl_n)))) || lv.lt2) && !sf_nx.hp;
    // (rules 4, 7, 12; round 6 D, E) the boundary: a cycle started earlier running, not on its
    // last clock; a back-to-back fetch starting (no EU request to win the bus) unless the lead
    // ends then (LEAD_EPRI: the give-way instead); the stream short; the lead short; a memory
    // request posted and not granted (E_PEND)
    // (r26, work order 22 C5, Q130, model_m CH_EPRI) nor when the fetch delivered then followed a
    // memory write (`fx` as the next clock will have it: fx_b; no fetch is granted on a fetch's
    // last pin clock) and the boundary arrives fresh (`wkd`: the dispatch word is not the word
    // now, so it did not wait on this clock): the boundary executes and the chained fetch gives
    // way (gw). Registers only
    wire        chx_nx = fx_b && !wkd;
    wire        bnd_w = cb_nx || (lv.b4 && !eu_rq_nx && !sle && !chx_nx) || ews || sld || rqm_nx;
    // (round 6, A, B, C) the bus waits by the word's kind: B (bi) a fetch's pin cycle started
    // earlier (its last clock included), S (rl=x) the slot, Y (both) a fetch with two clocks or
    // more left
    // (qprobe round 10, Q26 / A1) B: a pin cycle of any kind started earlier (its last clock
    // included; an odd word's pair as one cycle, bp_nx): the EU's own cycle as well as a fetch
    // (bz_nx, the cycle registers' next values:
    // registered state only, never this clock's request). (Q31 / B4) C (bi with alt, the commit
    // word): B's wait, and also on the clock a back-to-back fetch starts (the delivery with the
    // count at most 5, no EU request standing: the slot's continuation, slot_nx's c5 term).
    // (Q29 / A4) V (rl=x and bi with alt, the late request word): a fetch running then, not on
    // its last clock (the fetch's last clock is the earliest; Y's is its last two), and no
    // REQ_PRI (`rqx` is Y's and the X / S words'). (LAG_FIRST) A (rl=x alone with alt): the
    // slot but its first clock ahead of the pins (sla_nx)
    wire        b2s_nx = dlv_fetch_nx && lv.c5 && !eu_rq_nx;
    // (r24, work order 20 A4, Q111, model_m B_I4=4) a bus-idle word that releases a byte (P, P2 or
    // N: v35_useq's code dispatch with bi, `kbp`, and the commit word's alt-alone code) waits on
    // the clock a fetch starts back to back with four or fewer held before its own release (lv.b4,
    // no EU request standing): that fetch is needed, not the five-held continuation the release
    // would complete
    wire        b4w_nx = lv.b4 && !eu_rq_nx;
    // (r25, work order 21 B6, Q123 (3)) the store's G word (a bus-idle word that releases the
    // next opcode: kbp's code) waits with a write that gives way to the chain's next fetch on
    // that clock (lcw as the next clock will have it: the chain fetch delivered then, the count
    // then at most 5 before its releases, the armed write posted and standing)
    wire        lcw_nx = lc_b && ych_b && dlv_fetch_nx && lv.c5 && req_v && req_cyc == RQ_MEMW && !req_ia && !wur_b;
    wire        kbp = wk_nx.disp && wk_nx.bi;
    // (qprobe round 21, spec 10 A1 / Q42's second half, model_m C_NOCH=3) the commit word that
    // releases a byte (`P C`, the kind's alt-alone code: v35_useq) waits as C, except on the
    // clock the fetch chained behind the fetch that followed a write starts (`few`: the fetch
    // delivered then was granted with a fetch pending under an EU write cycle): it passes
    wire        cr_k = wk_nx.alt && !wk_nx.bi && !wk_nx.rlx && !wk_nx.flush;   // ((r24) flush with alt alone: wkbn's code)
    // (qprobe round 23, spec 18 A2 / Q101b, model_m CH3=2) against the second and later fetches of
    // the chain behind an EU cycle (`c3_nx`: a lagged fetch, lg, not the chain's first, fe) the
    // commit word C (bi with alt; and the alt-alone code) waits by the slot one clock earlier:
    // while three clocks or more are left after the next, on the second-last clock if the
    // chained fetch is decided (cf) and on the last if it was (nl); so it passes from the
    // fetch's third-last clock. On the clock such a fetch starts with no wait state (its first
    // clock is its third-last: `c3n_nx`, the fetch ending now lagged) the back-to-back term is
    // dropped. Not the strict word (flush with alt, v35_useq), not the slot words S / A / X.
    // EXCEPTION to "every delay needs a machine explanation" (the user's ruling 2026-11-17):
    // the third-last clock is a measured constant with no mechanism read (S_LAG is two); it is
    // to be backed out if the top's seed-1 slack at 17 ns falls under +2.0 ns
    wire        c3_nx = fb_nx && lg_b && !fe_b;
    wire        c3s_nx = !rm_nx[3] && (rm_nx >= 4'd3 || (rm_nx == 4'd1 && lv.cf) || (rm_nx == 4'd0 && nl_b));
    wire        cbw_nx = c3_nx ? c3s_nx : bp_nx;
    // (WO30) the waits are the fetch's that starts next (back to back: at fetch_addr as it stands
    // in tick B, its field read directly)
    wire        c3n_nx = lg_b && wf_fetch == 2'd0;
    wire        kst = wk_nx.flush && wk_nx.alt && wk_nx.bi;     // the strict word ((r24) flush with alt and no bi: wkbn's code)
    assign ph_nx = (wk_nx.disp && !wk_nx.bi && bnd_w) || (wk_nx.bi && !wk_nx.rlx && !wk_nx.alt && (bp_nx || (kbp && (b4w_nx || lcw_nx))))
                   || (kst && (bp_nx || b2s_nx))
                   || (wk_nx.bi && wk_nx.alt && !wk_nx.rlx && !kst && (cbw_nx || (b2s_nx && !c3n_nx)))
                   || (cr_k && (cbw_nx || b4w_nx || (b2s_nx && !few_b && !c3n_nx)))
                   || (wk_nx.rlx && !wk_nx.bi && (wk_nx.alt ? sla_nx : sl_nx))
                   || (wk_nx.rlx && wk_nx.bi && (wk_nx.alt ? (fb_nx && !fl_n) : fy_nx));
    always @(posedge clock) begin
        if (!reset_n || ce_a) begin
            wkd <= wk_nx.disp && !wk_nx.bi;     // ((r24) dispatch with bi: kbp's code, a B word)
            wkf <= wk_nx.flush && !wk_nx.alt;     // (round 23: flush with alt is the strict word)
            wkr <= wk_nx.rlx && !wk_nx.alt;
            wkp <= !(wk_nx.disp || wk_nx.rlx || wk_nx.bi) && (wk_nx.flush == wk_nx.alt);     // ((r24) wkbn's code is a word with no act)
            wkbn <= wk_nx.flush && wk_nx.alt && !wk_nx.bi && !wk_nx.rlx && !wk_nx.disp;
        end
        if (!reset_n) begin
            aft <= 1'b0;
            rqx <= 1'b0;
            ry1 <= 1'b0;
            pl1 <= 1'b0;
            rqo <= 1'b0;
            dst <= 1'b0;
            b4r <= 1'b0;
            c4r <= 1'b0;
            c5r <= 1'b0;
            rqvr <= 1'b0;
            ler <= 1'b0;
            hpr <= 1'b0;
        end else if (ce_a) begin
            aft <= aft_n;
            rqx <= ex && wkr;
            ry1 <= ex && wkm && wkr;
            pl1 <= a1p;
            rqo <= (ex && wkm) ? 1'b1 : req_ack ? 1'b0 : rqo;
            dst <= wkd && !ex;
            b4r <= lv.b4;
            c4r <= lv.c4;       // (r25 B7)
            c5r <= lv.c5;       // (r25 B6)
            rqvr <= eu_rq_nx;
            ler <= sle;
            hpr <= sf_nx.hp;
        end
    end
    always @(posedge clock) begin
        if (!reset_n) begin
            c_valid <= 1'b0;
            c_kind <= K_NONE;
            c_pos <= 3'd0;
            c_len <= 3'd0;
            c_internal <= 1'b0;
            c_ia <= 1'b0;
            c_dk <= 1'b0;
            c_rdy <= 1'b0;
            c_tmw <= 1'b0;
            gph <= 3'd0;
            hold <= 1'b0;
            d_v <= 1'b0;
            // (S7b) the reset complete: the cycle's fields, the delivery's
            c_addr <= 20'd0;
            c_width <= BW_WORD;
            c_half <= 2'd0;
            p2_v <= 1'b0;
            d_kind <= K_NONE;
            d_p1 <= 1'b0;
        end else if (ce_a) begin
            // the delivery registers: the cycle whose last clock is this one
            d_v <= d_v_nx;
            d_kind <= c_kind;
            d_p1 <= c_half == 2'd1;
            if (g_start_b) begin
                c_valid <= 1'b1;
                c_kind <= g_kind_b;
                c_pos <= 3'd0;
                c_len <= grant_len_b;
                c_internal <= g_sfr_b;
                c_ia <= g_ia_b;
                c_dk <= g_dk_b;
                c_rdy <= g_rdy_b;
                c_tmw <= g_tmw_b;
                c_addr <= g_addr_b;
                c_width <= g_width_b;
                c_half <= g_half_b;
                p2_v <= g_half_b == 2'd1;
            end else begin
                if (busy)
                    c_pos <= pos_hold ? c_pos : pos_now;
                else
                    c_valid <= 1'b0;
            end
            // (F4d) the hold bit: HLDRQ, or /HLDAK still low (the bus is taken back a clock
            // after /HLDAK rises)
            hold <= hrq || !hlda_n;
            // (WO31) the divide-by-six runs from reset, every CPU clock
            gph <= gph == 3'd5 ? 3'd0 : gph + 3'd1;
        end
    end

    // ------------------------------------------------ (consol) the write datum
    // (step D's write datum latch, wd_r / wd_w, captured at B2, is gone) The EU's request datum
    // and width are its registers from the post (`rq_d`: OPRW as the posting word leaves it,
    // qprobe round 6) to the cycle's end: the EU posts nothing new before req_done (its one
    // request slot), so the pair's second half and an on-chip store (its datum written at the
    // cycle's end) read the request port itself. `+v35_chk` keeps the B2 capture as the
    // reference and compares it wherever the latch was read
`ifndef SYNTHESIS
    reg  [15:0] wd_r = 16'd0;
    reg         wd_w = 1'b0;
    wire        wd_cap = busy && pos_now == 3'd1 && c_half != 2'd2
                         && (c_kind == K_WRITE || c_kind == K_IO_WRITE);
    always @(posedge clock) begin
        if (ce_a && wd_cap) begin
            wd_r <= req_data;
            wd_w <= req_width;
        end
    end
`endif

    // ------------------------------------------------ pins (v35_biu.sv:290-350)
    // (S7b) The pins keep the model's timing while the core's clock sits half a CPU clock later
    // (v35_top: ce_a at the CPU clock's middle, ce_b at its edge). At the edge (ce_e) B1 / B2
    // take the grant tick A has just decided (g_*) and the running cycle's registers as they
    // stood (written at the last ce_a); at the middle (ce_mid, with ce_a) the strobes and the
    // read latch follow the cycle as this clock leaves it (n_*: the registers' next state).
    // The write datum is driven at mid-B2 (Divergence 31): (A1) the EU's req_data as it stands
    // there (the EU presents its late result by then), which the write datum latch captures; the
    // pair's second half drives the latched copy. The bus unit places the pair's bytes (first
    // half: the low byte on the high lane).
    // the cycle as this clock leaves it (the pins' view from the middle on)
    wire        n_valid = g_start_b || busy;
    wire [2:0]  n_kind = g_start_b ? g_kind_b : c_kind;
    wire [19:0] n_addr = g_start_b ? g_addr_b : c_addr;     // (the function bench's view)
    wire [1:0]  n_width = g_start_b ? g_width_b : c_width;
    wire [2:0]  n_pos = g_start_b ? 3'd0 : pos_now;
    wire [2:0]  n_len = g_start_b ? grant_len_b : c_len;
    wire        n_internal = g_start_b ? g_sfr_b : c_internal;
    wire        n_write = n_kind == K_WRITE || n_kind == K_IO_WRITE;
    wire        pins = n_valid && !n_internal;
    wire        n_ia = g_start_b ? g_ia_b : c_ia;   // (F3b) the cycle on the pins is an acknowledge
    wire        n_dk = g_start_b ? g_dk_b : c_dk;   // (F4c) ... a DMA transfer's
    // (MX5c) the registers the pins' edge writes (ce_e) carry no inferred enable: each loads its
    // group's select every fabric clock, the hold folded into the selected values (below)
    (* syn_extract_enable = "false" *) reg        read_write_r = 1'b1;
    (* syn_extract_enable = "false" *) reg  [8:0] mux_address_r = 9'd0;
    (* syn_extract_enable = "false" *) reg        a0_r = 1'b0, a19_r = 1'b0, a18_ube_r = 1'b0;
    (* syn_extract_enable = "false" *) reg  [8:0] refresh_row = 9'd0;
    // B2's write datum, decided at the edge, driven at the middle
    (* syn_extract_enable = "false" *) reg        dp_v = 1'b0;
    (* syn_extract_enable = "false" *) reg  [1:0] dp_half = 2'd0;
    assign read_write = read_write_r;
    assign mux_address = mux_address_r;
    assign a0 = a0_r;
    assign a19 = a19_r;
    assign a18_ube = a18_ube_r;
    // (MX5c) the pins' edge as a function of the grant: `pin_f(g)` is the B1 / B2 update with the
    // grant g (the e_* view: the cycle granted now, else the running one), the registers' hold
    // values included, so a pin register's only enable is ce_e. Each pin group loads
    // `fetch_req ? pin_f(gn1) : pin_f(gn0)` through its own kept select (syn_keep): the grant's
    // last stage duplicated per group (the request line enters each group's data select, not
    // one grant net with every pin register's enable on it). The same values the update below
    // computed from g_*; README "MX5" round 3
    typedef struct packed {
        logic       rw;
        logic [8:0] ma;
        logic       a0, a19, a18;
        logic [8:0] rr;
        logic       dpv;
        logic [1:0] dph;
    } v35_pin_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_pin_t pin_f(input v35_gnt_t g);
        logic        ev, ein, ew;
        logic [2:0]  ek, ep;
        logic [19:0] ea;
        logic [1:0]  ewd;
        ev = g.start || busy;
        ek = g.start ? g.kind : c_kind;
        ep = g.start ? 3'd0 : pos_now;
        ea = g.start ? (g.fetch ? fetch_addr : req_addr) : c_addr;
        ewd = g.start ? g.width : c_width;
        ein = g.start ? g.sfr : c_internal;
        ew = ek == K_WRITE || ek == K_IO_WRITE;
        pin_f.rw = read_write_r;
        pin_f.ma = mux_address_r;
        pin_f.a0 = a0_r;
        pin_f.a19 = a19_r;
        pin_f.a18 = a18_ube_r;
        pin_f.rr = refresh_row;
        pin_f.dpv = 1'b0;
        pin_f.dph = dp_half;
        if (!ev || ein) begin
            pin_f.rw = 1'b1;
        end else if (ep == 3'd0) begin
            // B1: the row (A17..A9), A19, A18 and A0
            pin_f.rw = !ew;
            if (ek == K_REFRESH) begin
                pin_f.ma = refresh_row;
                pin_f.rr = refresh_row + 1'b1;
                pin_f.a0 = 1'b0;
                pin_f.a19 = 1'b0;
                pin_f.a18 = 1'b0;
            end else begin
                pin_f.ma = ea[17:9];
                pin_f.a0 = ea[0];
                pin_f.a19 = ea[19];
                pin_f.a18 = ea[18];
            end
        end else if (ep == 3'd1 && ek != K_REFRESH) begin
            // B2: the column (A9, A8..A1), /UBE; the write datum at mid-B2
            pin_f.ma = {ea[9], ea[8:1]};
            pin_f.a18 = ewd == BW_LO;
            pin_f.dpv = ew;
            pin_f.dph = c_half;
        end
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // the registers as they stand (the selected values off the edge)
    v35_pin_t pn1, pn0, ph;
    assign ph = {read_write_r, mux_address_r, a0_r, a19_r, a18_ube_r, refresh_row, dp_v, dp_half};
    assign pn1 = ce_e ? pin_f(gn1) : ph;
    assign pn0 = ce_e ? pin_f(gn0) : ph;
    (* syn_keep = "true" *) wire       pk_rw = fr ? pn1.rw : pn0.rw;
    (* syn_keep = "true" *) wire [8:0] pk_ma = fr ? pn1.ma : pn0.ma;
    (* syn_keep = "true" *) wire [2:0] pk_ah = fr ? {pn1.a0, pn1.a19, pn1.a18}
                                                         : {pn0.a0, pn0.a19, pn0.a18};
    (* syn_keep = "true" *) wire [8:0] pk_rr = fr ? pn1.rr : pn0.rr;
    (* syn_keep = "true" *) wire [2:0] pk_dp = fr ? {pn1.dpv, pn1.dph} : {pn0.dpv, pn0.dph};

    initial begin
        data_out = 16'd0;
        mreq_n = 1'b1;
        mstb_n = 1'b1;
        iostb_n = 1'b1;
        refrq_n = 1'b1;
        intak_n = 1'b1;
        dk = 1'b0;
        dkt = 1'b0;
        hlda_n = 1'b1;
    end

    always @(posedge clock) begin
        if (!reset_n) begin
            read_write_r <= 1'b1;
            refresh_row <= 9'd0;
            a0_r <= 1'b0;               // (S7b) the address and data pins too
            a19_r <= 1'b0;
            a18_ube_r <= 1'b0;
            mux_address_r <= 9'd0;
            dp_v <= 1'b0;
            dp_half <= 2'd0;
        end else begin
            read_write_r <= pk_rw;
            mux_address_r <= pk_ma;
            {a0_r, a19_r, a18_ube_r} <= pk_ah;
            refresh_row <= pk_rr;
            {dp_v, dp_half} <= pk_dp;
        end
    end

    always @(posedge clock) begin
        if (!reset_n) begin
            mreq_n <= 1'b1;
            mstb_n <= 1'b1;
            iostb_n <= 1'b1;
            refrq_n <= 1'b1;
            intak_n <= 1'b1;
            dk <= 1'b0;
            dkt <= 1'b0;
            hk <= 1'b0;
            hold_e <= 1'b0;
            hlda_n <= 1'b1;
            data_out <= 16'd0;
        end else begin
            // (F4d) /HLDAK at the pins' edge: low from the second edge with the bus held and idle
            // (no cycle in flight, no pair's second half to come), high at the first edge after
            // HLDRQ falls (registers only)
            if (ce_e) begin
                hold_e <= hold;
                hk <= hold_e && hold && hrq && !busy && !p2_v;
                hlda_n <= !(hk && hold && hrq && !busy && !p2_v);
            end
            // (F4c) a DMA transfer's cycle: DMAAK's and TC's windows
            if (ce_mid) begin
                dk <= pins && n_dk && n_pos != n_len - 3'd1;
                dkt <= pins && n_dk && (n_pos == 3'd1 || n_pos == 3'd2);
            end
            // (F3b) the acknowledge: /INTAK in place of the strobes, mid-B1 to mid-B3
            if (ce_mid && pins && n_ia)
                intak_n <= n_pos == 3'd2 || n_pos == n_len - 3'd1;
            if (ce_a && dp_v)
                data_out <= dp_half == 2'd0 ? req_data
                          : dp_half == 2'd1 ? {req_data[7:0], 8'd0} : {8'd0, req_data[15:8]};
            if (ce_mid && pins && !n_ia) begin
                if (n_pos == 3'd0) begin
                    if (n_kind == K_REFRESH)
                        refrq_n <= 1'b0;
                    else
                        mreq_n <= 1'b0;
                end else if (n_pos == n_len - 3'd1) begin
                    mreq_n <= 1'b1;
                    mstb_n <= 1'b1;
                    iostb_n <= 1'b1;
                    refrq_n <= 1'b1;
                end else if (n_kind != K_REFRESH) begin
                    if (k_io(n_kind))
                        iostb_n <= 1'b0;
                    else if (!n_write || n_pos == n_len - 3'd2)
                        mstb_n <= 1'b0;
                end
            end
        end
    end

    // ------------------------------------------------ (F1) the on-chip cycles
    // (step B: moved in from v35_top; the decision is the grant's own `g_sfr_b`, made once on the
    // request's address: IDB:E00-EFF with RAMEN = 1, IDB:F00-FFF, FFFFF; v35_top made it again
    // on its own ce_b copy of the grant: the same value at every ce_a, IDB and PRC being written
    // at ce_a only) An on-chip memory cycle is captured at its start: its offset (the SFR read's
    // and the register RAM's port C address: both read at every ce_b, this unit latching the
    // datum at the cycle's last clock) and its target.
    // (WO31) A store lands in its cycle's first clock (silicon, f4_oc_e: P1's pin half a clock
    // after the cycle's start; a WTC byte store governs the fetch that starts on the clock its
    // cycle ends): at the ce_a one clock after the capture (`oc_first`), the SFR page at that
    // ce_a, the internal RAM at the next ce_b (the register RAM's ce_a belongs to the EU's write
    // port), and a write to the current bank's DS0 / SS / DS1 slot updates the segment's flop at
    // the ce_a after (the EU's decode). A timer register's store lands as its wait ends (the
    // clock before its last: the timer unit takes it on its own clock, the grid; f4_oc_e: TOUT
    // at the start falls 1.5 clocks before the stretched cycle's end whatever its wait). The
    // datum is the request's own register (`rq_d`, from the post to the cycle's end: an on-chip
    // store is armed at its post), as at the old landing (`+v35_chk` below)
    wire        g_top = g_addr_b == 20'hFFFFF;
    wire        g_ocmem = g_start_b && g_sfr_b;
    reg         sfr_open = 1'b0;        // a store captured, not yet landed
    reg         oc_first = 1'b0;        // (WO31) the on-chip cycle's first clock (a ce_a register)
    reg         oc_ram = 1'b0;          // the cycle's target: the internal RAM (else the SFRs)
    reg         oc_rdgo = 1'b0;         // (F4b) an on-chip read cycle started at the last ce_a
    // (WO31) the datum's lanes: a byte cycle of an odd pair carries its low byte on the high lane
    // (the first, odd address) and its high byte on the low lane (the second), as this unit
    // places them on the pins; an even pair's (the SFR page's words) carry each byte on its own
    // lane, the datum unswapped. From the grant's registers at the capture
    reg         oc_sw = 1'b0;
    // (step C) one capture: the read's offset and word bit were registers beside sfr_a / sfr_w,
    // loaded at the same ce_a from the same grant fields (oc_off = FFFFF ? FFh : the address's
    // low byte, which is FFh there too: always sfr_a[7:0]; oc_word = sfr_w == WORD). The SFR
    // page and the register RAM's port C read sfr_a / sfr_w. sfr_w starts at BW_LO so that the
    // word bit reads 0 before the first capture as oc_word did; sfr_w's own readers (the lane
    // swap, the write's byte enables, the SFR store) act only on a captured cycle.
    // (WO31) An SFR-page word's two byte cycles (an even pair) carry the word bit (sfr_w =
    // BW_WORD), each at its own byte's address: v35_sfr writes and reads each byte at its own
    // cycle and the 16-bit registers (TM0 MD0 TM1 MD1) whole at the high byte's, the request's
    // datum holding both bytes through the pair (the EU's rq_d); an odd pair's halves stay byte
    // cycles (BW_HI / BW_LO, as before)
    initial begin
        sfr_a = 20'd0;
        sfr_w = BW_LO;
        oc_we = 1'b0;               // an internal RAM write, landing at the coming ce_b
        oc_wa = 7'd0;
        oc_be = 2'b00;
        oc_wd = 16'd0;
    end
    wire        oc_land = sfr_open && (c_tmw ? (pos_now == 3'd2 && !tm_hold) : oc_first);
    assign sfr_wr = ce_a && oc_land && !oc_ram;
    assign sfr_pend = sfr_open && oc_first && !c_tmw && !oc_ram;
    assign sfr_rdgo = oc_rdgo && !oc_ram;
    assign sfr_d = oc_sw ? {req_data[7:0], req_data[15:8]} : req_data;
    wire        g_even2 = (g_half_b == 2'd1 && !g_addr_b[0]) || (g_half_b == 2'd2 && g_addr_b[0]);
    always @(posedge clock) begin
        if (!reset_n) begin
            sfr_open <= 1'b0;
            oc_first <= 1'b0;
            oc_we <= 1'b0;
        end else if (ce_a) begin
            oc_we <= 1'b0;
            oc_rdgo <= 1'b0;
            oc_first <= g_ocmem;
            // a store lands before its cycle ends; the next cycle's capture (a pair's second
            // half) comes at the end
            if (oc_land) begin
                sfr_open <= 1'b0;
                if (oc_ram) begin
                    oc_we <= 1'b1;
                    oc_wa <= sfr_a[7:1];
                    oc_be <= sfr_w == BW_WORD ? 2'b11 : sfr_w == BW_HI ? 2'b10 : 2'b01;
                    oc_wd <= sfr_d;
                end
            end
            if (g_ocmem) begin
                sfr_open <= g_kind_b == K_WRITE;
                oc_rdgo <= g_kind_b == K_READ;
                sfr_a <= g_addr_b;
                sfr_w <= g_even2 ? BW_WORD : g_width_b;
                oc_sw <= (g_half_b == 2'd1 && g_addr_b[0]) || (g_half_b == 2'd2 && !g_addr_b[0]);
                oc_ram <= !g_addr_b[8] && !g_top;
            end
        end
    end
    // the on-chip read's datum: the register RAM's port C or the SFR page, by the cycle's target
    wire [15:0] oc_data = oc_ram ? oc_rd : sfr_rd;

    // read data: on the pins by mid-B3, delivered on the same CPU clock (the pins' B3 is the
    // core's delivery clock). (S7b) The datum register is written at mid-B3 (ce_mid, with ce_a):
    // the delivery clock's tick A starts from it.
    reg  [15:0] done_r = 16'hffff;
    // (F1) an on-chip read's datum at the same point, from the on-chip read register
    wire        b3_read = n_valid && n_pos == n_len - 3'd1 && k_read(n_kind);
    assign done_nx = n_internal ? oc_data : data_in;
    assign done_ld = ce_mid && b3_read;
    always @(posedge clock) begin
        if (done_ld)
            done_r <= done_nx;
    end
    assign done_data = done_r;

    // (S7b) chk begin (generated: the ce_b registers against their sources at ce_a)
`ifndef SYNTHESIS
    // (MX5c) the direct form (the grant as written before the expansion, the pins' edge from it):
    // the reference `+v35_chk` compares the expanded grant and pin_f(gn) with
    wire        x_eu_win = free_h && !g_second && req_v && !((un_w || dcu || dr) && fr && dlv_fetch && dc) && !(un_w && !ex)
                           && !(lcr && (fetch_req || lv_q.r5)) && !((lcw || aid) && fr);     // (qprobe round 12, A2; round 21, spec 17 A1; r25 B6 / B7)
    v35_gnt_t   gnt_x;
    logic       x_eu;
    always_comb begin
        gnt_x.fetch = free_h && !g_second && !x_eu_win && fr;
        gnt_x.ack = x_eu_win;
        x_eu = g_second || gnt_x.ack;
        gnt_x.start = x_eu || gnt_x.fetch;
        gnt_x.kind = gnt_x.fetch ? K_FETCH : g_second ? c_kind : rq_kind;
        gnt_x.width = !x_eu ? BW_WORD : (req_width && !g_second && !rq_two) ? BW_WORD
                    : (req_addr[0] ? BW_HI : BW_LO);
        gnt_x.half = g_second ? 2'd2 : (gnt_x.ack && rq_two) ? 2'd1 : 2'd0;
        gnt_x.sfr = (gnt_x.kind == K_WRITE || gnt_x.kind == K_READ) && rq_sfr;
        gnt_x.blen = gnt_x.fetch ? bl_fetch : k_io(gnt_x.kind) ? bl_io
                   : gnt_x.sfr ? bl_sfr : bl_req;
        gnt_x.rdy = gnt_x.fetch ? rdy_fetch : k_io(gnt_x.kind) ? rdy_io : !gnt_x.sfr && rdy_req;
    end
    // the pins' update from the selected per-group values (what the registers load at ce_e)
    v35_pin_t   pn_x;
    assign pn_x = {pk_rw, pk_ma, pk_ah, pk_rr, pk_dp};
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    // (MX5c) every fabric clock: the expanded grant against the direct form, the pins' selected
    // values against the update from it
    always @(posedge clock) begin
        if (chk_on && reset_n && (gn !== gnt_x || pn_x !== (ce_e ? pin_f(gn) : ph) || fr !== fr_x)) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: bus: the expanded grant differs from the direct form at %0t",
                         $time);
        end
    end
    // (consol) the request datum where the B2 latch was read: the pair's second half's drive
    // and an on-chip store's write
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a && dp_v && dp_half == 2'd2 && req_data[15:8] !== wd_r[15:8]) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: bus: the request datum differs from its B2 capture at %0t", $time);
        end
    end
    // (WO31) an on-chip store's datum: the request's at its landing (the cycle's first clock, or
    // a timer register's wait's end) is the request's at the cycle's delivery (where it landed
    // before: the datum stands from the post to the cycle's end) and the B2 capture's; no single-cycle word
    // reaches the SFR page (its words are pairs)
    reg  [15:0] ld_d = 16'd0;
    reg         ld_w = 1'b0, ld_v = 1'b0;
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (ld_v && eu_dlv) begin
                ld_v <= 1'b0;
                if (req_data !== ld_d || req_width !== ld_w || ld_d !== wd_r || ld_w !== wd_w) begin
                    chk_n = chk_n + 1;
                    if (chk_n <= 20)
                        $display("v35 chk: bus: an on-chip store's datum changed between its landing and its delivery at %0t", $time);
                end
            end
            if (oc_land) begin
                ld_d <= req_data;
                ld_w <= req_width;
                ld_v <= 1'b1;
                if ((ld_v && !eu_dlv) || (!oc_ram && sfr_w == BW_WORD && sfr_a[0] == 1'b0 && sfr_a != 20'hFFFFF
                             && req_addr != sfr_a + 20'd1)) begin
                    chk_n = chk_n + 1;
                    if (chk_n <= 20)
                        $display("v35 chk: bus: an on-chip store landed out of order or an SFR word in one cycle at %0t", $time);
                end
            end
        end
    end
    // (WO30) the granted cycle's length and READY fact against the direct reading of its own
    // address (g_addr: the fetch's, the request's, the pair's second byte's): the per-source
    // select is the cycle's own field
    wire [2:0]  x_blen = gn.sfr ? bl_sfr : k_io(gn.kind) ? bl_io : wlen(wfld(wtc, wblk(g_addr[19:17])));
    wire        x_rdy = !gn.sfr && rdy_en && (k_io(gn.kind) ? wf_io : wfld(wtc, wblk(g_addr[19:17]))) == 2'd3;
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_b && gn.start && (gn.blen !== x_blen || gn.rdy !== x_rdy)) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: bus: the granted cycle's waits differ from its address's field at %0t (fetch %0d addr %h len %0d/%0d)",
                         $time, gn.fetch, g_addr, gn.blen, x_blen);
        end
    end
    // (step D) the pins' B2 (dp_v at ce_a, not the pair's second half) is a latch capture
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a && dp_v && dp_half != 2'd2 && !wd_cap) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: bus: a write's B2 without the datum latch's capture at %0t", $time);
        end
    end
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (g_start_b !== g_start) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_start changed in tick B: %h -> %h at %0t",
                             g_start_b, g_start, $time);
            end
            if (g_sfr_b !== g_sfr) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_sfr changed in tick B: %h -> %h at %0t",
                             g_sfr_b, g_sfr, $time);
            end
            if (fetch_req_b !== fr) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.fetch_req changed in tick B: %h -> %h at %0t",
                             fetch_req_b, fr, $time);
            end
            if (g_kind_b !== g_kind) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_kind changed in tick B: %h -> %h at %0t",
                             g_kind_b, g_kind, $time);
            end
            if (grant_len_b !== (g_ia ? IA_LEN : grant_len)) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.grant_len changed in tick B: %h -> %h at %0t",
                             grant_len_b, grant_len, $time);
            end
            if (g_addr_b !== g_addr) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_addr changed in tick B: %h -> %h at %0t",
                             g_addr_b, g_addr, $time);
            end
            if (g_width_b !== g_width) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_width changed in tick B: %h -> %h at %0t",
                             g_width_b, g_width, $time);
            end
            if (g_half_b !== g_half) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_half changed in tick B: %h -> %h at %0t",
                             g_half_b, g_half, $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: bus: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
    // (S7b) chk end
`ifndef SYNTHESIS
    // diagnostics (+v35_diag): a bus start on a busy bus on stderr (`error`: a start on a bus
    // that was not free, sticky; reported once)
    reg diag = 1'b0;
    reg error = 1'b0, err_seen = 1'b0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (!reset_n) begin
            error <= 1'b0;
            err_seen <= 1'b0;
        end else if (ce_a) begin
            if (g_start_b && !free)
                error <= 1'b1;
            if (error && !err_seen) begin
                err_seen <= 1'b1;
                if (diag)
                    $display("v35: a bus start on a busy bus");
            end
        end
    end
    // (A1) +v35_gdbg=FILE: the grant's inputs and its choice per clock (bring-up, classifier)
    integer gdbg = 0, gdbg_t = 0;
    string gdbg_n;
    initial if ($value$plusargs("v35_gdbg=%s", gdbg_n)) gdbg = $fopen(gdbg_n, "w");
    always @(posedge clock) begin
        if (gdbg != 0 && reset_n && ce_a) begin
            $fdisplay(gdbg, "g %0d free%0d rv%0d fr%0d g%0d",
                      gdbg_t, free, req_v, fetch_req,
                      g_second ? 5 : g_fetch ? 3 : req_ack ? 2 : 0);
            gdbg_t <= gdbg_t + 1;
        end
    end
`endif

    wire unused = &{1'b0, ce_b, n_addr, n_width, fetch_req_b};   // (fetch_req_b: the chk's)
endmodule
