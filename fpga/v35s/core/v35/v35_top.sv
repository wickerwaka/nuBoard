`timescale 1ns/1ps

// V35S core v2: the slot module (docs/v35s-core-v2.md, "Architecture"), stage S3: the front
// end (bus unit, prefetch queue, loader, (A1) the grant in the bus unit) and the execution unit
// ((MX0) the microsequencer v35_useq on a registered ROM word, the datapath v35_eu, the register
// RAM v35_regram).
// Ports are v35s_model.sv's (25-43); the harness instantiates it as `model` under
// V35S_CORE_V35 (fpga/v35s/v35s_harness.sv, fpga/v35s/build_sim.sh direct v35).
//
// From v35s_chain_model.sv (the chain-model core's slot wrapper), as it does them: the CPU
// clock (one CPU clock per CLKOUT = X1/2, 4 or 8 by PRC.PCK, X1/8 at reset, a PCK change at the
// next state boundary: 89-108), the reset exit (the measured A3 figures: the reset refresh's
// B1 in state 15, the first fetch's in state 25; the core held in reset until the state before
// it: 110-151), the SFR block (v35_sfr.sv) written by the core's on-chip SFR stores at their
// cycle's end (274-291), the pins forced idle (bar the reset refresh) until the core runs
// (293-316). Nothing is scripted: the core fetches the reset vector and runs the image's
// prelude itself.
//
// (Step B of docs/v35s-core-v2-interfaces.md) This module holds the CPU clock's divider, the
// reset exit, the two ticks, the pins' idle forcing, the instances and their wiring, the trace
// and the simulation's observation, nothing else: the on-chip cycle is the bus unit's
// (v35_bus), the interrupt / macro-service / DMA / single-step take and STOP are the interrupt
// controller's (v35_intc in ../v35_sfr.sv), the decodes the instances' connections made here
// are their owners' outputs (the sequencer's take points, the loader's memory form, the bus
// unit's delivered fetch).
//
// The refresh controller (v35_refresh.sv, reused as is) is instantiated, its request ignored
// (no refresh-on family is in the gates; the prelude's refreshes before its RFM store are not
// run, so the pre-window differs from silicon there).
//
// (MX0) The CPU clock's two ticks (S7b; the enables `ce_a` / `ce_b` below):
//   tick A  every module's registers; the queue's delivery and window; the microinstruction (a
//           register) decides its stalls, its pops (the loader: the queue's reads and the
//           staging load, the request line), its RAM read addresses; the decode lookups from
//           the opcode / ModR/M / staging registers; the bus unit's grant on the request
//           register and the queue's line
//   tick B  the RAM's data, the sources, the ALU, the EA step, the write port, the request's
//           next state, the next microaddress (the ROM read at ce_a)
// Quartus 17.1 reads one import in a module header, so the imports sit in $unit scope
// verilator lint_off IMPORTSTAR
import v35_front_pkg::*;
import v35_pkg::*;
// verilator lint_on IMPORTSTAR
module v35_top
#(
    parameter int RESET_REFRESH_STATE = 15,     // A3: first refresh 118-128 X1 (/REFRQ mid-B1)
    parameter int RESET_FETCH_STATE = 25        // A3: first fetch 198-208 X1 (/MREQ mid-B1)
) (
    input  wire        clock,
    input  wire        x_rise,
    input  wire        x_fall,
    input  wire        reset_n,
    input  wire        ready,
    input  wire [15:0] data_in,
    input  wire [15:0] input_levels,
    output reg         a0,
    output reg         a19,
    output reg         a18_ube,
    output reg  [8:0]  mux_address,
    output reg  [15:0] data_out,
    output reg         mreq_n,
    output reg         mstb_n,
    output reg         iostb_n,
    output reg         read_write,
    output reg         refrq_n,
    output wire        intak_n,         // (F3b) the INT acknowledge (P13 as /INTAK: PMC1 bit 3)
    // (F4) the port pins the board drives ({P2, P1, P0}: an input-mode bit reads its pin) and
    // the output pin vector in the harness's order (v35s_harness.sv "Pin vector")
    input  wire [23:0] pins_in,
    output wire [31:0] pins,
    // (work order 29) the secure mode's translation table's load port (v35_queue): one fabric
    // clock of tt_we writes tt_d at tt_a. Load it while the core is held in reset; the core
    // never initialises it
    input  wire        tt_we,
    input  wire [7:0]  tt_a,
    input  wire [7:0]  tt_d
);
    // ---------------------------------------------------------------- SFRs
    wire [7:0] prc, rfm, idb;
    wire [15:0] wtc;
    // (F1) the SFR page's access port (the bus unit's on-chip cycle)
    wire sfr_wr;                        // ((S7b) at ce_a itself: tick A sees the new value)
    wire sfr_pend;                      // (work order 37) a store captured, landing at the coming ce_a
    wire [19:0] sfr_a;
    wire [1:0] sfr_w;
    wire [15:0] sfr_d;
    // (F1) the on-chip read (the SFR page reads the cycle's offset and width from its access
    // port: (step C) the bus unit's sfr_a / sfr_w, its oc_off / oc_word before) and FLAG
    wire [15:0] sfr_rd;
    wire        sfr_rdgo;               // (F4b) an SFR read cycle started at the last ce_a
    wire [1:0]  psw_f;
    wire        flag_we;
    wire [1:0]  flag_d;
    // (F3) the interrupt controller's links: the IC registers' bytes, INTM, the IC stores, and
    // the IF bits and ISPR it owns
    wire [8*15-1:0] ic_b;
    wire [7:0]  intm, ispr;
    wire [14:0] ic_we, ic_wd, ic_if;
    // (F4b) macro service: the sources' control registers, the end's MS clear, the request, the
    // take's kind and channel / mode / direction, the end (the EU's strobe)
    wire [8*15-1:0] ms_b;
    wire [14:0] ms_clr;
    wire        tk_ms, ms_dir, ms_end;
    wire [2:0]  ms_ch, ms_mode;         // (step B) ms_ch: a DMA take's channel too (v35_intc)
    wire        ms_hlt;
    wire        int_on;                 // (F3b) the INT request (the level, PMC1 bit 4)
    wire [14:0] pf_set;                 // (F4) the peripherals' IF requests
    // (F4c) DMA: the request and the take's descriptor (v35_dma's registers), the take, the
    // routine's TC update and last transfer (the EU's), the bus unit's DMA cycle windows
    wire        dm_v, dm_go, dm_ch, dm_in, dm_out, dm_w;
    wire [1:0]  dm_ps, dm_pd;
    wire        take_d, dm_smp, dm_tend, dm_tlast, dm_last, req_dk, b_dk, b_dkt, dm_rs;
    wire        tk_dm;                  // the last take is a DMA transfer's (v35_intc)
    // (F4d) bus hold and READY (v35_sfr's registers to the bus unit, /HLDAK back to the pins)
    wire        b_hrq, b_hlda_n, b_rdy_en, b_rdy_lv;
    v35_sfr sfr (.clock, .reset_n, .wr(sfr_wr), .wr_pend(sfr_pend), .addr(sfr_a), .width(sfr_w), .data(sfr_d),
                 .prc, .wtc, .rfm, .idb,
                 .ce_rd(ce_b), .rd_data(sfr_rd),
                 .rd_go(sfr_rdgo), .psw_f,
                 .input_levels, .flag_we, .flag_d, .poll_p14,
                 .ic_b, .intm, .ic_we, .ic_wd, .ic_if, .ispr, .int_on, .ms_b, .ms_clr,
                 .ce_a, .pins_in, .intak_n, .pins, .pf_set,
                 .dm_take(take_d), .dm_tend, .dm_tlast, .dm_rs, .dm_smp, .dm_last, .dk(b_dk),
                 .dkt(b_dkt), .dm_v,
                 .dm_go, .dm_ch, .dm_in, .dm_out, .dm_w, .dm_ps, .dm_pd,
                 .hrq(b_hrq), .hlda_n(b_hlda_n), .rdy_en(b_rdy_en), .rdy_lv(b_rdy_lv));

    // ---------------------------------------------------------------- CPU clock
    // (work order 36) the divider is a free-running X1/8 count from reset: `x_count` counts every
    // X1 rise and wraps at 8 whatever the PCK; a CPU clock is the count's low PCK-dependent bits
    // (`x_last`, the mask: 1 at fX/2, 3 at fX/4, 7 at fX/8): its edge where they are 0, its middle
    // where they equal `x_mid`. A PRC store never reloads or re-phases the count, and the new
    // PCK is taken only at the count's wrap (x_count 0, a state start at every PCK): the first
    // wrap after the store lands. Silicon (build/overseer/wo34s/RESULTS.md section 2, 59 of 59
    // changes a session, x_half 2, 3 and 4): the new period starts on a CLKOUT rise that is
    // always the X1/8 boundary counted from reset, with a whole first phase; from fX/4 the change
    // waits up to 1 CPU clock, from fX/2 up to 3; the CPU clock stays on the reset grid. (Its
    // bus upset on a change from fX/2 to fX/4 is a chip malfunction, not built.) At the target
    // (an X1 rise every fabric tick) fX/2 is still two ticks a CPU clock
    reg [2:0] x_count = 3'd0;
    reg [1:0] pck = 2'd2;
    wire [2:0] x_last = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd3 : 3'd7;
    wire [2:0] x_mid = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd2 : 3'd4;
    wire state_start = reset_n && x_rise && (x_count & x_last) == 3'd0;
    wire state_mid = reset_n && x_rise && (x_count & x_last) == x_mid;
    always @(posedge clock) begin
        if (!reset_n) begin
            x_count <= 3'd0;
            pck <= 2'd2;
        end else if (x_rise) begin
            x_count <= x_count + 1'b1;
            if (x_count == 3'd0)
                pck <= prc[1:0];
        end
    end

    // ---------------------------------------------------------------- the reset exit
    reg [5:0] state_n = 6'd0;
    reg started = 1'b0;
    always @(posedge clock) begin
        if (!reset_n) begin
            state_n <= 6'd0;
            started <= 1'b0;
        end else if (state_start) begin
            started <= 1'b1;
            if (started && state_n != 6'd63)
                state_n <= state_n + 1'b1;
        end
    end
    wire [5:0] state_now = started ? state_n : 6'd0;
    reg core_run = 1'b0;
    always @(posedge clock) begin
        if (!reset_n)
            core_run <= 1'b0;
        else if (state_start && started && state_n + 6'd1 == 6'(RESET_FETCH_STATE - 1))
            core_run <= 1'b1;
    end
    wire core_reset_n = reset_n && core_run;
    localparam int RX_LEN = 5;      // RFM FCh: RFW 2 waits, 5 states
    reg rx_refrq_n = 1'b1;
    always @(posedge clock) begin
        if (!reset_n)
            rx_refrq_n <= 1'b1;
        else if (state_mid && !core_run) begin
            if (state_now == 6'(RESET_REFRESH_STATE))
                rx_refrq_n <= 1'b0;
            else if (state_now == 6'(RESET_REFRESH_STATE + RX_LEN - 1))
                rx_refrq_n <= 1'b1;
        end
    end
    localparam int INIT_COUNTER = (8 + (RESET_FETCH_STATE - 1) - (RESET_REFRESH_STATE - 1)) % 128;

    // (S7b) the two enables of a CPU clock. The pins' timing is the model's (v35_biu's): a cycle
    // granted on a clock shows B1 from the CPU clock's edge after it, the strobes move at the
    // clock's middle, and a read's datum is on the pins at mid-B3, where the V35 samples it.
    // The core's clock is placed half a CPU clock later than that convention so that its first
    // tick starts from the sampled datum:
    //   ce_a  the CPU clock's middle (ce_mid): every architectural register, and the bus
    //         unit's datum register (the read latch). Tick A runs from here: S1 (arrival, from
    //         the registered datum) through S4 (the grant).
    //   ce_b  the CPU clock's edge: the pipeline registers that hold tick A's results; the
    //         pins' edge (B1's address, B2's column) takes the grant there. Tick B runs from
    //         here: S5, S6, ending at the next ce_a.
    // A clock's S5 / S6 results reach the pins half a CPU clock after the edge that ends the
    // model's clock: the write datum is driven at mid-B2 (README, Divergence 31); nothing else
    // on the pins depends on them. No input reaches logic without first landing in a register.
    // Simulation only: +v35_ceb=K puts ce_b K fabric ticks after ce_a (K = 1..3 in the harness's
    // eight-tick clock; the default is the edge, the target's second tick); the pins' edge
    // stays at the CPU clock's edge. The core's registers update on ce_a and ce_b only, so the
    // default runs exactly as at the target, two ticks a CPU clock, while the harness's pins
    // and its recording at 30 ns ticks are unchanged (+v35_ticks=2 names that variant).
    // ce_a waits for a ce_b since the core left reset (the ce_b registers then hold tick A's
    // results of the state the ce_a ends: the first clock after the reset exit included).
    wire ce_mid = state_mid;
    wire ce_e = state_start && core_run;            // the pins' edge
    reg  [2:0] ceb_age = 3'd7;          // fabric ticks since the CPU clock's middle (sat 7)
    reg        b_seen = 1'b0;
    wire       ce_b;
    always @(posedge clock) begin
        if (!reset_n)
            ceb_age <= 3'd7;
        else if (state_mid)
            ceb_age <= 3'd1;
        else if (ceb_age != 3'd7)
            ceb_age <= ceb_age + 3'd1;
        if (!core_reset_n)
            b_seen <= 1'b0;
        else if (ce_b)
            b_seen <= 1'b1;
    end
    wire ce_a = state_mid && core_run && b_seen;
`ifndef SYNTHESIS
    reg  [2:0] ceb_k = 3'd0;
    integer    ceb_arg = 0;
    initial begin
        if ($value$plusargs("v35_ceb=%d", ceb_arg) && ceb_arg >= 0 && ceb_arg <= 3
            && !$test$plusargs("v35_ticks=2"))
            ceb_k = 3'(ceb_arg);
    end
    assign ce_b = core_run && !state_mid && (ceb_k == 3'd0 ? state_start : ceb_age == ceb_k);
`else
    assign ce_b = core_run && state_start;
`endif
    wire ce = ce_a;                     // (the function bench's hook: o_ce)

    // ---------------------------------------------------------------- the nets between stages
    // bus (S0)
    wire        b_eu_dlv;               // (step D) an EU cycle's datum delivered now (either half)
    wire        dlv_fetch, dlv_fetch_nx;    // (step B) a fetched word delivered (the bus unit's)
    wire [15:0] b_done_data;
    wire [15:0] b_done_nx16;            // (F5t) its next value and load (the loader's tag register)
    wire        b_done_ld;
    // (MX5c) tick B: the next values of the facts the sequencer's stall reads (the D nets of
    // the modules' ce_a registers): the bus unit's, the queue's, the loader's, the datapath's
    wire        b_done_nx;
    wire [2:0]  q_st_nx;
    wire        q_od_nx, q_dc_nx;
    wire        l_qs_nx;
    wire        e_ordy_nx, e_rqb_nx;
    // (consol) the pace (the bus unit's): the next word's kind (the sequencer's), the hold back;
    // the EU's request standing and memory request standing next; the queue's count compares;
    // the loader's stream facts; the loader's releases (to the queue), HALT's request delay (to
    // the EU); the sequencer's dispatch bit (the loader's)
    v35_wk_t    s_wk_nx;
    wire        b_ph_nx, e_rqv_nx, e_rqm_nx;
    v35_lvq_t   q_lv;
    v35_lvn_t   q_lv_nx;
    v35_sf_t    l_sf_nx;
    wire        l_hp_b, s_wdisp, s_wdisp_nx;
    wire [2:0]  l_rls;
    // (A1) the grant (S4) and the EU request port
    wire        g_fetch;
    wire        req_v, req_width, req_ack, req_done;
    wire [1:0]  req_cyc;
    wire [19:0] req_addr;
    wire [15:0] req_data;
    // queue (Q1: the simple machine)
    wire [7:0]  qv0, qv1;
    wire [1:0]  ld_pop;                 // (step C) the pop: 0 to 2 bytes off the queue's head
    wire [19:0] q_fetch_addr;
    wire [2:0]  q_avail, q_stored;
    wire [15:0] q_ip;                   // (step D) the queue's head byte's offset in PS
    wire [7:0]  q_h0;                   // (MX5b) the queue's registered head facts
    wire        q_hod;
    wire [QTAG_W-1:0] q_h0t;            // (MX5c) the byte tag the queue stores
    wire [2*QTAG_W-1:0] ld_dlv_tag;
    wire        q_fetch_req;
    // (MX0) the loader: the word register, the popped bytes, the decode
    wire        q_stall, dcall;
    wire        ec_reg, ec_call;                // (MX3c) the EAC word's mode facts
    wire [UADDR_W-1:0] ec_head;
    wire [UADDR_W-1:0] dent, dret;
    wire [7:0]  ld_opc, ld_modrm, ld_il, ld_ih, ld_dl, ld_dh;
    wire [2:0]  ld_op3, ld_len;
    v35_udec_t  fmt;
    v35_udecm_t dec2;
    // (MX0) the sequencer
    v35_uword_t word, word_nx;
    wire [7:0]  ld_opc_nx, ld_modrm_nx;   // (MX5b) tick B: the values loading at ce_a
    v35_udec_t  fmt_nx;
    wire [6:0]  ra_early, rb_early;
    wire        ex, ex_b, halted;
    wire        w_dispm;                        // (MX5) the word's derived bits (registers)
    wire        w_dispm_nx;                     // (MX5c) tick B: the next word's
    wire        w_erep, w_erep_nx;              // (F5d) e && ea == EA_REP (useq's registered fact; tick B: the next word's)
    // (step B) the sequencer's take points and acts (v35_useq): the dispatch, a string's take
    // point, an E word (no boundary; the arms dropped), a FLUSH; STOP's halt word (and executing),
    // the take's IVEC word, FINT
    wire        x_disp, x_tki, x_end, x_nb, x_nbi, x_flush, w_stop, x_stop, x_ivec, x_fint;
    // (MX0) the datapath
    wire        opr_rdy, rq_busy, c_sgn, c_dtrap;
    wire        c_xc, c_snz, c_f1, c_dn, q_susp;    // (MX2) the transfer's conditions; prefetch suspended
    wire [15:0] ld_ip;                  // (MX2) the instruction pointer
    wire [15:0] ld_ins_ip;              // (F2b) the instruction's start (its first prefix's)
    wire        psw_md;                 // (work order 29) PSW.MD
    wire [15:0] q_tq;                   // (work order 29) the queue's table reading of its head bytes
    wire        psw_brki, poll_p14;     // (F2b) PSW.BRKI; the P14 pin as POLL reads it
    wire        psw_ie, psw_brk;        // (F3) PSW.IE, PSW.BRK
    wire [4:0]  tk_vec;
    wire        igo;                    // (F3) an interrupt taken at the dispatch (v35_intc)
    wire        sgo;                    // (F5e) an interrupt taken at a string's take point
    wire        tk_bs, tk_int;          // (F3b) the take's kind (bank switch, INT)
    wire [2:0]  tk_lv;                  // (F3b) the bank-switch take's level
    wire        req_ia;                 // (F3b) the EU's request is an INT acknowledge
    wire [7:0]  rb_lo;
    wire [3:0]  sig_lo;                             // (F2a) SIGMA's low four bits (CN_SIG)
    wire [15:0] flush_off;
    wire [19:0] ps_base;
    wire [6:0]  ra_next, rb_next, wa_addr;
    wire        wa_en;
    wire [1:0]  wa_be;
    wire [15:0] wa_data, ra_data, rb_data;
    // (F1) the on-chip data path: the register RAM's port C read, the internal RAM's write (the
    // bus unit's registers: landing at the coming ce_b)
    wire [15:0] oc_rd;
    wire        oc_we;
    wire [6:0]  oc_wa;
    wire [1:0]  oc_be;
    wire [15:0] oc_wd;

    wire        ramen = prc[6];

    // ---------------------------------------------------------------- the bus unit
    wire c_a0, c_a19, c_a18_ube, c_mreq_n, c_mstb_n, c_iostb_n, c_read_write, c_refrq_n;
    wire [8:0] c_mux_address;
    wire [15:0] c_data_out;
    v35_bus bus (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b, .ce_e, .ce_mid, .wtc,
        .idb, .ramen, .sfr_rd, .oc_rd,
        .req_v, .req_cyc, .req_addr, .req_width, .req_data, .req_ack, .req_done,
        .req_ia, .intak_n, .req_dk, .dk(b_dk), .dkt(b_dkt),
        .hrq(b_hrq), .hlda_n(b_hlda_n), .rdy_en(b_rdy_en), .rdy_lv(b_rdy_lv),
        .fetch_req(q_fetch_req), .fetch_addr(q_fetch_addr),
        .g_fetch,
        .eu_dlv(b_eu_dlv),
        .dlv_fetch,
        .done_data(b_done_data), .done_nx(b_done_nx16), .done_ld(b_done_ld),
        .dlv_fetch_nx, .eu_done_nx(b_done_nx),
        .wk_nx(s_wk_nx), .ex, .eu_rq_nx(e_rqv_nx), .rqm_nx(e_rqm_nx), .lv_q(q_lv), .lv_nx(q_lv_nx),
        .sf_nx(l_sf_nx), .ph_nx(b_ph_nx),
        .sfr_wr, .sfr_pend, .sfr_a, .sfr_w, .sfr_d, .sfr_rdgo,
        .oc_we, .oc_wa, .oc_be, .oc_wd,
        .a0(c_a0), .a19(c_a19), .a18_ube(c_a18_ube), .mux_address(c_mux_address),
        .data_out(c_data_out), .mreq_n(c_mreq_n), .mstb_n(c_mstb_n), .iostb_n(c_iostb_n),
        .read_write(c_read_write), .refrq_n(c_refrq_n), .data_in
    );

    // ---------------------------------------------------------------- the queue
    // (S6) the first fetch's address: FFFF0h (PS FFFFh, IP 0); the function bench
    // (fpga/v35s/v35_core2_tb.sv) sets a test's PS:IP here through `verilator public` hooks
    // (observability and preload only: the harness build keeps the constants). (Q1) The
    // queue's prefetch pointer and (step D) its head offset are offsets in PS: in reset they
    // load tb_reset_ip, the observation block's address counter tb_reset_addr.
`ifndef SYNTHESIS
    reg [19:0] tb_reset_addr = 20'hFFFF0;
    reg [15:0] tb_reset_ip = 16'h0000;
`else
    wire [15:0] tb_reset_ip = 16'h0000;
`endif
    // (MX2) the suspend: the V20 ROM's SUSP before a transfer's FLUSH (the sequencer's q_susp: the
    // request line held low from the SUSP word to the FLUSH)
    v35_queue queue (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .fetch_req(q_fetch_req), .fetch_addr(q_fetch_addr),
        .fetch_go(g_fetch), .dlv_v(dlv_fetch), .dlv_data(b_done_data), .dlv_tag(ld_dlv_tag),
        .vb0(qv0), .vb1(qv1), .avail(q_avail), .hip(q_ip), .stored(q_stored), .h_q0(q_h0), .h_odd(q_hod), .h_q0t(q_h0t), .pop_n(ld_pop),
        .flush(x_flush), .flush_addr(flush_off), .reset_ip(tb_reset_ip), .susp(q_susp), .ps_base,
        .stored_nx(q_st_nx), .odd_nx(q_od_nx), .discard_nx(q_dc_nx),
        .rls(l_rls), .lv_q(q_lv), .lv_nx(q_lv_nx),
        .dlv_nx(b_done_nx16), .tt_we, .tt_a, .tt_d, .tq(q_tq)
    );

    // ---------------------------------------------------------------- the loader
    v35_loader loader (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .qv0, .qv1, .q_avail, .q_stored, .h_q0(q_h0), .h_odd(q_hod), .h_dlv(b_done_data), .h_dlv_nx(b_done_nx16), .h_dlv_ld(b_done_ld), .h_q0t(q_h0t), .dlv_tag(ld_dlv_tag), .pop_n(ld_pop),
        .q_ip, .flush_w(word.flush),
        .ex, .pop(word.pop), .e_pop(word.e),
        .dispm(w_dispm), .e_rep(w_erep), .e_pfx(word.pfx), .e_rep_nx(w_erep_nx), .q_stall, .opc(ld_opc), .modrm(ld_modrm), .il(ld_il), .ih(ld_ih),
        .dl(ld_dl), .dh(ld_dh), .fmt, .opc_nx(ld_opc_nx), .modrm_nx(ld_modrm_nx), .fmt_nx, .op3(ld_op3), .dec2, .len(ld_len),
        .dent, .dcall, .dret,
        .ec_reg, .ec_call, .ec_head,
        .pop_nx(word_nx.pop), .e_pop_nx(word_nx.e), .q_stored_nx(q_st_nx),
        .q_odd_nx(q_od_nx), .q_discard_nx(q_dc_nx), .q_dlv_nx(dlv_fetch_nx),
        .flush_w_nx(word_nx.flush), .dispm_nx(w_dispm_nx),
        .q_stall_nx(l_qs_nx),
        .ro(word.ro), .rl(word.rl), .ro_nx(word_nx.ro), .w_disp(s_wdisp), .w_disp_nx(s_wdisp_nx), .rls(l_rls),
        .sf_nx(l_sf_nx), .w_halt(word.halt), .hp_b(l_hp_b),
        .ip(ld_ip), .brki(psw_brki), .ins_ip(ld_ins_ip), .tq(q_tq), .psw_md
    );

    // ---------------------------------------------------------------- the microsequencer
    wire h_wake;                        // HALT's release ((F4d) STOP's: v35_intc)
    v35_useq useq (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .q_stall, .dent, .dcall, .dret, .dec2, .ec_reg, .ec_call, .ec_head, .len(ld_len), .il(ld_il), .fmt_w(fmt.w),
        .opr_rdy, .rq_busy, .c_sgn, .c_dtrap, .c_xc, .c_snz, .c_f1, .c_dn, .rb_lo, .sig_lo,
        .q_stall_nx(l_qs_nx), .opr_rdy_nx(e_ordy_nx), .rq_busy_nx(e_rqb_nx),
        .wk_nx(s_wk_nx), .ph_nx(b_ph_nx), .w_disp(s_wdisp), .w_disp_nx(s_wdisp_nx),
        .wake(h_wake), .igo, .sgo,
        .word, .word_nx, .w_dispm, .w_dispm_nx, .w_erep, .w_erep_nx, .ex, .ex_b, .q_susp, .halted,
        .x_disp, .x_tki, .x_end, .x_nb, .x_nbi, .x_flush, .w_stop, .x_stop, .x_ivec, .x_fint
    );

    // ---------------------------------------------------------------- the datapath
    v35_eu eu (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .word, .word_nx(word_nx), .op_nx(ld_opc_nx), .modrm_nx(ld_modrm_nx), .fmt_nx,
        .ra_early, .rb_early, .ex_b,
        .fmt, .op3(ld_op3), .op(ld_opc), .modrm(ld_modrm), .il(ld_il), .ih(ld_ih), .dl(ld_dl),
        .dh(ld_dh), .ip(ld_ip), .ins_ip(ld_ins_ip), .idb, .p14(poll_p14), .psw_brki, .psw_md,
        .psw_ie, .psw_brk, .tk_vec, .tk_bs, .tk_int, .tk_l(tk_lv), .ns_pin(input_levels[0]), .req_ia,
        .tk_ms, .ms_ch, .ms_mode, .ms_dir, .ms_hlt, .ms_end,
        .tk_dm, .dm_in, .dm_out, .dm_w, .dm_ps, .dm_pd, .dm_tend, .dm_tlast, .dm_last, .req_dk,
        .ra_next, .rb_next, .ra_data, .rb_data, .wa_en, .wa_addr, .wa_be, .wa_data,
        .req_v, .req_cyc, .req_addr, .req_width, .req_data, .req_ack, .req_done,
        .done_data(b_done_data), .eu_dlv(b_eu_dlv),
        .req_done_nx(b_done_nx), .opr_rdy_nx(e_ordy_nx),
        .rq_busy_nx(e_rqb_nx), .req_v_nx(e_rqv_nx), .rqm_nx(e_rqm_nx), .hp_b(l_hp_b),
        .opr_rdy, .rq_busy, .c_sgn, .c_dtrap, .c_xc, .c_snz, .c_f1, .c_dn, .rb_lo, .sig_lo,
        .flush_off, .ps_base,
        .psw_f, .flag_we, .flag_d,
        .oc_we, .oc_wa, .oc_be, .oc_wd
    );

    // ---------------------------------------------------------------- (F3) the interrupt controller
    // (step B) with the take (NMI, the maskable offer, a macro service, DMA, the single step; the
    // prefix and arming holds) and STOP: the sequencer's take points in, the take and HALT's
    // release out, the take's parameters to the EU, the DMA take to v35_dma
    v35_intc intc (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b, .input_levels, .intm, .ic_b,
        .wr(sfr_wr), .ic_we, .ic_wd,
        .x_disp, .x_tki, .x_end, .x_nb, .x_nbi, .halted, .w_stop, .x_stop,
        .iack(x_ivec), .fint(x_fint),
        .int_on, .ie(psw_ie), .brk(psw_brk), .pf_set, .ms_b, .ms_end, .dm_go, .dm_v, .dm_ch,
        .igo, .sgo, .wake(h_wake), .take_d, .dm_rs, .dm_smp, .tk_dm, .ms_hlt,
        .tk_ms, .ms_ch, .ms_mode, .ms_dir, .ms_clr, .tk_bs, .tk_lv, .tk_int,
        .ic_if, .ispr, .tk_vec
    );

    // ---------------------------------------------------------------- the register RAM
    v35_regram regram (
        .clock, .ce_a, .ce_b, .ra_next, .ra_early, .rb_early, .wa_en, .wa_addr, .wa_be, .wa_data, .ra_data, .rb_next, .rb_data,
        .oc_ra(sfr_a[7:1]), .oc_rd, .oc_we, .oc_wa, .oc_be, .oc_wd
    );
    // ---------------------------------------------------------------- refresh (not served)
    wire rf_pending, rf_load;
    wire [7:0] rf_value;
    wire [23:0] rf_state_r, rf_state_e;
    v35_refresh #(.STATE_W(24)) refresh (
        .clock, .reset_n(core_reset_n), .ce(ce_a), .en(1'b1), .rfm, .init_counter(7'(INIT_COUNTER)),
        .start(1'b0), .wr(1'b0), .wr_value(8'd0),
        .pending(rf_pending), .rfm_load(rf_load), .rfm_value(rf_value),
        .state_r(rf_state_r), .state_e(rf_state_e)
    );

    // ---------------------------------------------------------------- pins
    always @* begin
        a0 = c_a0;
        a19 = c_a19;
        a18_ube = c_a18_ube;
        mux_address = c_mux_address;
        data_out = c_data_out;
        mreq_n = c_mreq_n;
        mstb_n = c_mstb_n;
        iostb_n = c_iostb_n;
        read_write = c_read_write;
        refrq_n = c_refrq_n;
        if (!core_run) begin
            a0 = 1'b0;
            a19 = 1'b0;
            a18_ube = 1'b0;
            mux_address = 9'd0;
            mreq_n = 1'b1;
            mstb_n = 1'b1;
            iostb_n = 1'b1;
            read_write = 1'b1;
            refrq_n = rx_refrq_n;
        end
    end

`ifndef SYNTHESIS
    // (consol) `+v35_chk`: the queue's count (`ob`, its own register: the bytes fetched and not
    // released, this clock's delivery not counted) against round 6's parts, the queue's stored
    // bytes and the loader's bytes taken out and not released (`oadj_ref`, the loader's
    // simulation reference), at every ce_a
    /* verilator lint_off BLKSEQ */
    reg chk_ob = 1'b0;
    integer chk_obn = 0;
    initial chk_ob = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_ob && core_reset_n && ce_a
            && queue.ob !== $signed({2'b00, queue.cnt}) + $signed({loader.oadj_ref[3], loader.oadj_ref})) begin
            chk_obn = chk_obn + 1;
            if (chk_obn <= 20)
                $display("v35 chk: top: the queue's count differs from the window and the loader's part at %0t", $time);
        end
    end
    // (work order 29) `+v35_chk`: at every staging load (ce_a), the byte loaded into the staging
    // register against the book's rule: the head byte itself in normal mode (MD 1), the
    // translation table's entry for it in secure mode (MD 0), the table read here from the
    // queue's memory directly. MD is the EU's ce_a register: as it stood when the loader's twin
    // flops took the byte (tick A of this clock)
    integer chk_ttn = 0;
    wire [7:0] chk_raw = (loader.opop_b || loader.mpop_b) ? loader.sb1_b : loader.sb0_b;
    always @(posedge clock) begin
        if (chk_ob && core_reset_n && ce_a && loader.sload_b && !loader.flush_b
            && loader.s_nb !== (eu.psw[15] ? chk_raw : queue.tt0[chk_raw])) begin
            chk_ttn = chk_ttn + 1;
            if (chk_ttn <= 20)
                $display("v35 chk: top: the staged opcode %02x is not the table's reading of %02x (MD %0d) at %0t",
                         loader.s_nb, chk_raw, eu.psw[15], $time);
        end
    end
    final if (chk_ob && chk_ttn != 0)
        $display("v35 chk: top: %0d staging loads off the translation rule", chk_ttn);
    // (WO31) `+v35_chk`: the on-chip store's hold of E is gone, so every on-chip store must land
    // before the instruction after it reads anything: at the ce_a ending the clock the dispatch
    // executes (the next routine's first word reads the register RAM from this ce_a on: the
    // early read, then its ce_b read; the segment flops from this ce_a), no store captured or
    // granted to an on-chip target may still be waiting to land (the internal RAM's write lands
    // at the ce_b after the landing ce_a, the SFR page's at it)
    integer chk_oln = 0;
    always @(posedge clock) begin
        if (chk_ob && core_reset_n && ce_a && x_disp
            && (bus.sfr_open || (bus.g_ocmem && bus.g_kind_b == K_WRITE))) begin
            chk_oln = chk_oln + 1;
            if (chk_oln <= 20)
                $display("v35 chk: top: the dispatch executes before an on-chip store landed at %0t", $time);
        end
    end
    final if (chk_ob && chk_oln != 0)
        $display("v35 chk: top: %0d dispatches before an on-chip store landed", chk_oln);
    /* verilator lint_on BLKSEQ */

    // ---------------------------------------------------------------- observation (simulation)
    // The trace's and the function bench's views (fpga/v35s/v35_core2_tb.sv reads dut.start,
    // dut.start_trap, dut.ir_addr_c), read from the modules' own nets: no module port carries
    // them. `start`: a routine's entry word executes (the sequencer's); `start_trap`: and its
    // instruction has no routine (the opcode, or the ModR/M / 0F head's second-level cell);
    // `ir_addr_c`: the linear address of the opcode the E word popped, counted as the loader
    // pops (the next queue byte's address `o_pc`, the staged opcode's `o_sa`, a flush's target
    // {PS, 0} + SIGMA registered at ce_b)
    // (qprobe round 12) a REP prefix is its own routine (rep_p) whose E word pops the string
    // opcode: the instruction's start is the prefix's (its routine's entry, at the prefix's
    // address), not the string routine's entry after it (`rp_e`: rep_p's E executed, the next
    // start not counted), as before the prefix had its routine
    reg         rp_e = 1'b0;
    always @(posedge clock) begin
        if (!reset_n)
            rp_e <= 1'b0;
        else if (ce_a) begin
            if (useq.ex && word.e && useq.upc == UROM_REPP)
                rp_e <= 1'b1;
            else if (useq.start)
                rp_e <= 1'b0;
        end
    end
    wire        start = useq.start && !rp_e;
    wire        t_flush = x_flush;      // (the function bench's o_flush)
    wire        start_trap = loader.df.trap || (word.seq == SQ_DISPM && dec2.trap);
    reg  [19:0] o_pc = 20'hFFFF0, o_sa = 20'd0, ir_addr_c = 20'd0, o_flin = 20'd0;
    wire [19:0] o_pc_pop = o_pc + ((loader.opop_b || loader.mpop_b) ? 20'd1 : 20'd0);
    always @(posedge clock) begin
        if (ce_b)
            o_flin <= ps_base + {4'd0, flush_off};
        if (!core_reset_n) begin
            o_pc <= tb_reset_addr;
            o_sa <= tb_reset_addr;
        end else if (ce_a) begin
            if (loader.flush_b)
                o_pc <= o_flin;
            else begin
                o_pc <= o_pc_pop + (loader.sload_b ? 20'd1 : 20'd0);
                if (loader.sload_b)
                    o_sa <= o_pc_pop;
            end
            if (loader.epop_b && !loader.erep_b)
                ir_addr_c <= o_sa;
        end
    end
    // (the function bench's hooks, read from outside: the divide error's strobe too)
    wire        unused_obs = &{1'b0, start, start_trap, ir_addr_c, eu.trap_o, t_flush};
`ifdef V35S_CORE_V35
    // the bus unit's: a fetch's last clock (the trace's B with the line), an EU cycle issued
    // (either half of a pair: I), the granted cycle's length (X's)
    wire        fetch_last = bus.busy && bus.c_kind == K_FETCH && bus.c_len - bus.pos_now == 3'd1;
    wire        g_eu = bus.g_second || req_ack;
    wire        q_infl_c = bus.busy && bus.c_kind == K_FETCH;      // a fetch in flight
    // ---------------------------------------------------------------- the trace hook
    v35_trace trace (
        .clock, .reset_n(core_reset_n), .ce_a,
        .g_start(bus.g_start), .g_kind(bus.g_kind), .g_addr(bus.g_addr), .g_width(bus.g_width),
        .g_len(bus.grant_len),
        .start, .epop(loader.epop), .start_trap, .entry(useq.upc), .pc(ir_addr_c),
        .take(loader.opop || loader.mpop), .load(loader.sload),
        .post(ex && word.bus != BQ_NONE && word.bus != BQ_RSV), .post_kind(word.bus == BQ_MEMR ? K_READ
                                           : (word.bus == BQ_MEMW || word.bus == BQ_MEMWD) ? K_WRITE
                                           : (word.bus == BQ_IOR || word.bus == BQ_INTA) ? K_IO_READ
                                           : K_IO_WRITE),
        .issue(g_eu), .b2b(fetch_last && q_fetch_req), .abort(1'b0),     // (step D: no aborted cycle)
        .room(5'sd6 - 5'({2'd0, q_avail} - {3'd0, ld_pop}) - (q_infl_c ? 5'sd2 : 5'sd0)),
        .flag(q_fetch_req), .why(useq.st_r.why), .upc(useq.upc)
    );
`endif
`endif

    wire unused = &{1'b0, ready, ce, x_fall, prc[7], prc[5:2],
                    rf_pending, rf_load, rf_value, rf_state_r, rf_state_e};
endmodule
