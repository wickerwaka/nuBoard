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
module v35_top
    import v35_front_pkg::*;
    import v35_pkg::*;
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
    output wire [31:0] pins
);
    // ---------------------------------------------------------------- SFRs
    wire [7:0] prc, rfm, idb;
    wire [15:0] wtc;
    wire sfr_wr;                        // ((S7b) at ce_a itself: tick A sees the new value)
    reg [19:0] sfr_a = 20'd0;
    reg [1:0] sfr_w = 2'd0;
    wire [15:0] sfr_d;
    wire        sfr_wat;                // (MX5c) the store's write at the coming ce_a
    wire [7:0]  prc_at;                 // ... PRC after it (the registered stall's RAMEN)
    // (F1) the on-chip read (the cycle's offset, registered below) and FLAG
    wire [15:0] sfr_rd;
    reg  [7:0]  oc_off = 8'd0;
    reg         oc_word = 1'b0;
    reg         oc_rdgo = 1'b0;         // (F4b) an on-chip read cycle started at the last ce_a
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
    wire        ms_v, tk_ms, ms_dir, ms_end;
    wire [2:0]  ms_ch, ms_mode;
    reg         ms_hlt = 1'b0;
    wire        int_on;                 // (F3b) the INT request (the level, PMC1 bit 4)
    wire [14:0] pf_set;                 // (F4) the peripherals' IF requests
    // (F4c) DMA: the request and the take's descriptor (v35_dma's registers), the take, the
    // routine's TC update and last transfer (the EU's), the bus unit's DMA cycle windows
    wire        dm_v, dm_go, dm_ch, dm_in, dm_out, dm_w;
    wire [1:0]  dm_ps, dm_pd;
    wire        take_d, dm_smp, dm_tend, dm_tlast, dm_last, req_dk, b_dk, b_dkt, dm_rs;
    reg         tk_dm = 1'b0;           // the last take is a DMA transfer's
    // (F4d) bus hold and READY (v35_sfr's registers to the bus unit, /HLDAK back to the pins)
    wire        b_hrq, b_hlda_n, b_rdy_en, b_rdy_lv;
    v35_sfr sfr (.clock, .reset_n, .wr(sfr_wr), .addr(sfr_a), .width(sfr_w), .data(sfr_d),
                 .prc, .wtc, .rfm, .idb, .wr_at(sfr_wat), .prc_at,
                 .ce_rd(ce_b), .rd_off(oc_off), .rd_word(oc_word), .rd_data(sfr_rd),
                 .rd_go(oc_rdgo && !oc_ram), .psw_f,
                 .input_levels, .flag_we, .flag_d, .poll_p14,
                 .ic_b, .intm, .ic_we, .ic_wd, .ic_if, .ispr, .int_on, .ms_b, .ms_clr,
                 .ce_a, .pins_in, .intak_n, .pins, .pf_set,
                 .dm_take(take_d), .dm_tend, .dm_tlast, .dm_rs, .dm_smp, .dm_last, .dk(b_dk),
                 .dkt(b_dkt), .dm_v,
                 .dm_go, .dm_ch, .dm_in, .dm_out, .dm_w, .dm_ps, .dm_pd,
                 .hrq(b_hrq), .hlda_n(b_hlda_n), .rdy_en(b_rdy_en), .rdy_lv(b_rdy_lv));

    // ---------------------------------------------------------------- CPU clock
    reg [2:0] x_count = 3'd0;
    reg [1:0] pck = 2'd2;
    wire [2:0] x_last = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd3 : 3'd7;
    wire [2:0] x_mid = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd2 : 3'd4;
    wire state_start = reset_n && x_rise && x_count == 3'd0;
    wire state_mid = reset_n && x_rise && x_count == x_mid;
    always @(posedge clock) begin
        if (!reset_n) begin
            x_count <= 3'd0;
            pck <= 2'd2;
        end else if (x_rise) begin
            if (x_count == x_last)
                x_count <= 3'd0;
            else
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
    wire        b_in_wait, b_fetch_inflight, b_fetch_past_b2;
    wire        b_dlv_v, b_abort_busy, b_cpu_end_prev;
    wire [2:0]  b_dlv_kind;
    wire [15:0] b_done_data;
    wire [15:0] b_done_nx16;            // (F5t) its next value and load (the loader's tag register)
    wire        b_done_ld;
    // (MX5c) tick B: the next values of the facts the sequencer's stall reads (the D nets of
    // the modules' ce_a registers): the bus unit's, the queue's, the loader's, the datapath's
    wire        b_fir_nx, b_fpb_nx, b_iw_nx, b_b2b_nx, b_dv_nx, b_done_nx;
    wire [2:0]  b_dk_nx;
    wire [2:0]  q_st_nx;
    wire        q_lv_nx, q_od_nx, q_dc_nx;
    wire        l_qs_nx, l_sm_nx, l_sw_nx;
    wire        e_ordy_nx, e_rqb_nx, e_wrh_nx;
    // (A1) the grant (S4) and the EU request port
    wire        g_start, g_fetch, g_abort;
    wire [2:0]  g_kind;
    wire [19:0] g_addr;
    wire [1:0]  g_width;
    wire        req_v, req_width, req_resv, req_ack, req_done;
    wire [1:0]  req_cyc;
    wire [19:0] req_addr;
    wire [15:0] req_data;
    // queue (Q1: the simple machine)
    wire [7:0]  qv0, qv1;
    wire [2:0]  ld_rd, ld_rel;
    wire        ld_stg;
    wire [19:0] q_fetch_addr;
    wire [2:0]  q_avail, q_stored;
    wire [7:0]  q_h0, q_hl;             // (MX5b) the queue's registered head facts
    wire        q_hlv, q_hod;
    wire [QTAG_W-1:0] q_h0t, q_hlt;     // (MX5c) the byte tags the queue stores
    wire [2*QTAG_W-1:0] ld_dlv_tag;
    wire        q_fetch_req, q_low, b_b2b_now;
    wire        q_fetch_raise;
    wire        q_word;                 // (Q2)
    // (MX0) the loader: the word register, the popped bytes, the decode
    wire        q_stall, resv_e, s_modrm, dcall, e_rmodrm, s_wbs;
    wire        ec_reg, ec_call;                // (MX3c) the EAC word's mode facts
    wire [UADDR_W-1:0] ec_head;
    wire [UADDR_W-1:0] dent, dret;
    wire [7:0]  ld_opc, ld_modrm, ld_il, ld_ih, ld_dl, ld_dh;
    wire [2:0]  ld_op3, ld_len;
    wire        ld_load;
    v35_udec_t  fmt;
    v35_udecm_t dec2;
    // (MX0) the sequencer
    v35_uword_t word, word_nx;
    wire [7:0]  ld_opc_nx, ld_modrm_nx;   // (MX5b) tick B: the values loading at ce_a
    v35_udec_t  fmt_nx;
    wire [6:0]  ra_early, rb_early;
    wire        ex, ex_pop, ex_b, halted;
    wire        w_disp, w_dispm;               // (MX5) the word's derived bits (registers)
    wire        w_dispm_nx;                     // (MX5c) tick B: the next word's
    wire        w_erep, w_erep_nx;              // (F5d) e && ea == EA_REP (useq's registered fact; tick B: the next word's)
    wire        w_tki;                          // (F5e) seq == SQ_TKI (useq's registered fact)
    // (MX0) the datapath
    wire        opr_rdy, rq_busy, wr_hold, c_sgn, c_dtrap;
    wire        c_xc, c_snz, c_f1, c_dn, q_susp;    // (MX2) the transfer's conditions; prefetch suspended
    wire [15:0] ld_ip;                  // (MX2) the instruction pointer
    wire [15:0] ld_ins_ip;              // (F2b) the instruction's start (its first prefix's)
    wire        psw_brki, poll_p14;     // (F2b) PSW.BRKI; the P14 pin as POLL reads it
    wire        psw_ie, psw_brk;        // (F3) PSW.IE, PSW.BRK
    wire        ir_v, nmi_v, i_wake;    // (F3) the controller's offer, NMI, HALT's release
    wire [4:0]  ir_vec, tk_vec;
    wire        igo;
    wire        sgo;                    // (F5e) an interrupt taken at a string's take point
    wire        it_v, tk_bs, tk_int;    // (F3b) INT offered; the take's kind (bank switch, INT)
    wire [2:0]  tk_lv;                  // (F3b) the bank-switch take's level
    wire        req_ia;                 // (F3b) the EU's request is an INT acknowledge
    // (F3b) N/S as last sampled (a register: MD at reset and on every interrupt entry)
    reg         ns_r = 1'b1;
    always @(posedge clock)
        ns_r <= input_levels[0];
    wire [7:0]  rb_lo;
    wire [3:0]  sig_lo;                             // (F2a) SIGMA's low four bits (CN_SIG)
    wire [15:0] flush_off;
    wire [19:0] ps_base;
    wire [15:0] sfr_data;
    wire [6:0]  ra_next, rb_next, wa_addr;
    wire        wa_en;
    wire [1:0]  wa_be;
    wire [15:0] wa_data, ra_data, rb_data;
    // (F1) the on-chip data path
    wire [15:0] oc_rd, oc_data;
    wire [2:0]  psw_rb;
    reg         oc_ram = 1'b0;          // the cycle's target: the internal RAM (else the SFRs)
    reg         pend_v = 1'b0;          // an internal RAM write, landing at the coming ce_b
    reg  [6:0]  pend_a = 7'd0;
    reg  [1:0]  pend_be = 2'b00;
    reg  [15:0] pend_d = 16'd0;

    // (MX0f) Q2's start is the opcode's read from the queue: the E word's pop, not the routine's
    // entry word (the frozen model's start is that pop; the entry follows the post-E dispatch)
    wire        e_popped;
    wire        t_start = e_popped;
    wire        t_flush = ex_pop && word.flush;            // tick A: a FLUSH word executes
    wire        take_now;                              // tick A: an operand byte popped
    wire        ramen = prc[6];

    // (S7b) the slot's own ce_b registers: tick A's strobes that the nets between the modules
    // combine for tick B
    reg         g_start_b = 1'b0;
    reg  [2:0]  g_kind_b = K_NONE;
    reg  [19:0] g_addr_b = 20'd0;
    reg  [1:0]  g_width_b = BW_WORD;
    always @(posedge clock) begin
        if (ce_b) begin
            g_start_b <= g_start;
            g_kind_b <= g_kind;
            g_addr_b <= g_addr;
            g_width_b <= g_width;
        end
    end

    // ---------------------------------------------------------------- the bus unit
    wire c_a0, c_a19, c_a18_ube, c_mreq_n, c_mstb_n, c_iostb_n, c_read_write, c_refrq_n;
    wire [8:0] c_mux_address;
    wire [15:0] c_data_out;
    v35_bus bus (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b, .ce_e, .ce_mid, .wtc, .rfm,
        .idb, .ramen, .oc_data,
        .req_v, .req_cyc, .req_addr, .req_width, .req_data, .req_resv, .req_ack, .req_done,
        .req_ia, .intak_n, .req_dk, .dk(b_dk), .dkt(b_dkt),
        .hrq(b_hrq), .hlda_n(b_hlda_n), .rdy_en(b_rdy_en), .rdy_lv(b_rdy_lv),
        .fetch_req(q_fetch_req), .q_low, .q_word, .fetch_addr(q_fetch_addr),
        .t_start, .take_now, .l_pop(ld_load),
        .g_start, .g_kind, .g_addr, .g_width, .g_fetch, .g_abort,
        .b2b_now(b_b2b_now),
        .in_wait(b_in_wait),
        .fetch_inflight(b_fetch_inflight), .fetch_past_b2(b_fetch_past_b2),
        .cpu_end_prev(b_cpu_end_prev),
        .dlv_v(b_dlv_v), .dlv_kind(b_dlv_kind),
        .done_data(b_done_data), .done_nx(b_done_nx16), .done_ld(b_done_ld), .abort_busy(b_abort_busy),
        .fetch_inflight_nx(b_fir_nx), .fetch_past_b2_nx(b_fpb_nx), .in_wait_nx(b_iw_nx),
        .b2b_now_nx(b_b2b_nx), .dlv_v_nx(b_dv_nx), .dlv_kind_nx(b_dk_nx), .eu_done_nx(b_done_nx),
        .a0(c_a0), .a19(c_a19), .a18_ube(c_a18_ube), .mux_address(c_mux_address),
        .data_out(c_data_out), .mreq_n(c_mreq_n), .mstb_n(c_mstb_n), .iostb_n(c_iostb_n),
        .read_write(c_read_write), .refrq_n(c_refrq_n), .data_in
    );
    wire dlv_fetch = b_dlv_v && b_dlv_kind == K_FETCH;
    wire dlv_fetch_nx = b_dv_nx && b_dk_nx == K_FETCH;
    wire dlv_other = b_cpu_end_prev;

    // ---------------------------------------------------------------- the queue
    // (S6) the first fetch's address: FFFF0h (PS FFFFh, IP 0); the function bench
    // (fpga/v35s/v35_core2_tb.sv) sets a test's PS:IP here through `verilator public` hooks
    // (observability and preload only: the harness build keeps the constants). (Q1) The
    // queue's prefetch pointer is an offset in PS: in reset it loads tb_reset_ip (the loader's
    // offsets too), the observation block's address counter tb_reset_addr.
`ifndef SYNTHESIS
    reg [19:0] tb_reset_addr = 20'hFFFF0;
    reg [15:0] tb_reset_ip = 16'h0000;
`else
    wire [15:0] tb_reset_ip = 16'h0000;
`endif
    wire [15:0] q_flush_addr = core_reset_n ? flush_off : tb_reset_ip;
    // (Q1) the variant: B (a byte port and a latch) unless V35_QUEUE_A (a word write port)
`ifdef V35_QUEUE_A
    localparam bit Q1_VARIANT_B = 1'b0;
`else
    localparam bit Q1_VARIANT_B = 1'b1;
`endif
    // (MX2) the suspend: the V20 ROM's SUSP before a transfer's FLUSH (the sequencer's q_susp: the
    // request line held low from the SUSP word to the FLUSH)
    v35_queue #(.VARIANT_B(Q1_VARIANT_B)) queue (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .fetch_req(q_fetch_req), .fetch_raise(q_fetch_raise), .fetch_addr(q_fetch_addr), .q_low, .q_word,
        .fetch_go(g_fetch), .dlv_v(dlv_fetch), .dlv_data(b_done_data), .dlv_tag(ld_dlv_tag), .abort_go(b_abort_busy),
        .vb0(qv0), .vb1(qv1), .avail(q_avail), .stored(q_stored), .h_q0(q_h0), .h_lat(q_hl), .h_latv(q_hlv), .h_odd(q_hod), .h_q0t(q_h0t), .h_latt(q_hlt), .rd(ld_rd), .rd_b(3'd0),
        .rel(ld_rel), .stg(ld_stg),
        .flush(t_flush), .flush_addr(q_flush_addr), .susp(q_susp), .ps_base,
        .stored_nx(q_st_nx), .latv_nx(q_lv_nx), .odd_nx(q_od_nx), .discard_nx(q_dc_nx)
    );

    // ---------------------------------------------------------------- the loader
    v35_loader loader (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .qv0, .qv1, .q_avail, .q_stored, .q_arrive(dlv_fetch), .h_q0(q_h0), .h_lat(q_hl), .h_latv(q_hlv), .h_odd(q_hod), .h_dlv(b_done_data), .h_dlv_nx(b_done_nx16), .h_dlv_ld(b_done_ld), .h_q0t(q_h0t), .h_latt(q_hlt), .dlv_tag(ld_dlv_tag), .rd(ld_rd), .rel(ld_rel), .stg(ld_stg),
        .reset_ip(tb_reset_ip), .flush(t_flush), .flush_w(word.flush),
        .flush_off,
        .ex(ex_pop), .pop(word.pop), .e_pop(word.e), .disp(ex && w_disp),
        .dispm(w_dispm), .e_rep(w_erep), .e_pfx(word.pfx), .e_rep_nx(w_erep_nx), .q_stall, .opc(ld_opc), .modrm(ld_modrm), .il(ld_il), .ih(ld_ih),
        .dl(ld_dl), .dh(ld_dh), .fmt, .opc_nx(ld_opc_nx), .modrm_nx(ld_modrm_nx), .fmt_nx, .op3(ld_op3), .dec2, .len(ld_len),
        .l_load(ld_load), .o_pop(take_now), .o_epop(e_popped), .dent, .dcall, .dret,
        .resv_e, .s_modrm, .e_rmodrm, .s_wbs, .ec_reg, .ec_call, .ec_head,
        .pop_nx(word_nx.pop), .e_pop_nx(word_nx.e), .q_stored_nx(q_st_nx), .q_latv_nx(q_lv_nx),
        .q_odd_nx(q_od_nx), .q_discard_nx(q_dc_nx), .q_dlv_nx(dlv_fetch_nx),
        .flush_w_nx(word_nx.flush), .dispm_nx(w_dispm_nx),
        .q_stall_nx(l_qs_nx), .s_modrm_nx(l_sm_nx), .s_wbs_nx(l_sw_nx), .ip(ld_ip), .brki(psw_brki), .ins_ip(ld_ins_ip)
    );

    // ---------------------------------------------------------------- the microsequencer
    wire h_wake;                        // HALT's release ((F4d) STOP's: below)
    v35_useq useq (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .q_stall, .dent, .dcall, .dret, .dec2, .ec_reg, .ec_call, .ec_head, .len(ld_len), .il(ld_il), .fmt_w(fmt.w),
        .opr_rdy, .rq_busy, .wr_hold, .c_sgn, .c_dtrap, .c_xc, .c_snz, .c_f1, .c_dn, .rb_lo, .sig_lo,
        .fetch_run(b_fetch_inflight), .bus_wait(b_in_wait), .fetch_dph(b_fetch_past_b2), .b2b_now(b_b2b_now), .s_modrm, .s_wbs,
        .e_rmodrm, .rmem((fmt.has_modrm || fmt.pg) && ld_modrm[7:6] != 2'd3), .q_req(q_fetch_raise), .resv(req_resv),
        .f_grant(g_fetch), .f_dlv(dlv_fetch),
        .q_stall_nx(l_qs_nx), .opr_rdy_nx(e_ordy_nx), .rq_busy_nx(e_rqb_nx), .wr_hold_nx(e_wrh_nx),
        .s_wbs_nx(l_sw_nx), .s_modrm_nx(l_sm_nx),
        .rmem_nx((fmt_nx.has_modrm || fmt_nx.pg) && ld_modrm_nx[7:6] != 2'd3),
        .fetch_run_nx(b_fir_nx), .bus_wait_nx(b_iw_nx), .fetch_dph_nx(b_fpb_nx),
        .b2b_now_nx(b_b2b_nx), .f_dlv_nx(dlv_fetch_nx), .wake(h_wake), .igo, .sgo,
        .f_abort(g_abort), .word, .word_nx, .w_disp, .w_dispm, .w_dispm_nx, .w_erep, .w_erep_nx, .w_tki, .ex, .ex_pop, .ex_b, .q_susp, .halted
    );

    // ---------------------------------------------------------------- the datapath
    v35_eu eu (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .word, .word_nx(word_nx), .op_nx(ld_opc_nx), .modrm_nx(ld_modrm_nx), .fmt_nx,
        .ra_early, .rb_early, .ex, .ex_b, .resv_e, .tk_go(ex && w_disp && igo),
        .fmt, .op3(ld_op3), .op(ld_opc), .modrm(ld_modrm), .il(ld_il), .ih(ld_ih), .dl(ld_dl),
        .dh(ld_dh), .ip(ld_ip), .ins_ip(ld_ins_ip), .idb, .p14(poll_p14), .psw_brki,
        .psw_ie, .psw_brk, .tk_vec, .tk_bs, .tk_int, .tk_l(tk_lv), .ns(ns_r), .req_ia,
        .tk_ms, .ms_ch(tk_dm ? {2'b00, dm_ch} : ms_ch), .ms_mode, .ms_dir, .ms_hlt, .ms_end,
        .tk_dm, .dm_in, .dm_out, .dm_w, .dm_ps, .dm_pd, .dm_tend, .dm_tlast, .dm_last, .req_dk,
        .ra_next, .rb_next, .ra_data, .rb_data, .wa_en, .wa_addr, .wa_be, .wa_data,
        .req_v, .req_cyc, .req_addr, .req_width, .req_data, .req_resv, .req_ack, .req_done,
        .done_data(b_done_data), .cpu_end_prev(b_cpu_end_prev), .ramen,
        .req_done_nx(b_done_nx), .ramen_nx(prc_at[6]), .opr_rdy_nx(e_ordy_nx),
        .rq_busy_nx(e_rqb_nx), .wr_hold_nx(e_wrh_nx),
        .opr_rdy, .rq_busy, .wr_hold, .c_sgn, .c_dtrap, .c_xc, .c_snz, .c_f1, .c_dn, .rb_lo, .sig_lo,
        .flush_off, .ps_base, .sfr_data,
        .psw_f, .psw_rb, .flag_we, .flag_d,
        .oc_seg_we(pend_v && pend_a[6:4] == psw_rb
                   && (pend_a[3:0] == 4'd4 || pend_a[3:0] == 4'd5 || pend_a[3:0] == 4'd7)),
        .oc_seg_s(pend_a[3:0] == 4'd7 ? 2'd0 : pend_a[3:0] == 4'd5 ? 2'd2 : 2'd3),
        .oc_seg_be(pend_be), .oc_seg_d(pend_d)
    );

    // ---------------------------------------------------------------- (F3) the interrupt take
    // At a dispatch (the word after E: an instruction's start) the sequencer enters the
    // interrupt routine (urom/trap.uasm intr) instead of the instruction it popped when, the last
    // instruction's E word not marking the start as no boundary (`nb`: a prefix, EI, DI, a
    // segment register's load; f3_step), NMI is pending, or the controller offers a request and
    // IE is 1 now and was 1 at the last start (`ie_arm`: EI's, POP PSW's and RETI's following
    // instruction runs; f3_order), or PSW.BRK is 1 now and was at the last start (`brk_arm`: the
    // single step after each instruction that ran with BRK set; f3_step). NMI first, then the
    // offer, then the step (f3_step2 step_intp). Every term is a register; `igo` overrides the
    // sequencer's ROM address last (UROM_INT in place of the DISP word's target: the loader's
    // decoded entry is not behind it)
    reg  ie_arm = 1'b0, brk_arm = 1'b0, nb_r = 1'b0;
    wire g_n = nmi_v;
    wire g_i = (ir_v || it_v) && psw_ie && ie_arm;     // (F3b) it_v: INT (the controller chooses)
    wire g_s = psw_brk && brk_arm;
    // (F4b) a macro-service request: taken at a start whatever IE (f4_ms ms_p0, IE 0); in HALT
    // the stall ends on it (the sequencer's `wake` OR ms_v) and the routine returns to the HALT
    // (f4_ms ms_halt: no release). (F4p) The controller resolves it with the vectored requests
    // (v35_intc: ms_v and ir_v never stand together); NMI goes before it (validation/v35s/
    // prio.py f4p_hb b_nmi_ms: both held by a DMA burst, NMI's frame pushed, then the macro
    // service at the handler's first instruction)
    wire g_m = ms_v;
    // (F4c) a DMA request: taken at the start after the one that saw it (f4_dma step_w /
    // burst_w, the instruction after the TDMA store runs first; a store clearing EDMA lets one
    // more transfer through: f4_dm3 tdma_io); in single step and single transfer a take lets
    // one instruction run before the next, in burst and demand release not (back to back). In
    // HALT the stall ends on the request and the take needs no arm (f4_dma halt_io: transfers
    // in HALT, no release). (F4p) The arms are v35_dma's (`dm_go`, sampled at `dm_smp`: a start
    // or a string's take point that is not a DMA take); DMA goes first, before NMI, a macro
    // service and the maskable interrupt (validation/v35s/prio.py f4p_hb, f4p_hr: each
    // pair held by a DMA burst), so a burst holds every other request to its end
    // (F4c) a DMA transfer or a macro service taken out of HALT resumes at the HALT: its start is
    // no boundary for NMI or an interrupt (`rs_hlt` makes the routine's E word set nb_r), so the
    // HALT runs, is released by the pending request and the request is taken after it with the
    // HALT's next offset pushed (f4_dma halt: the DIC1 handler returns after the HALT)
    reg  rs_hlt = 1'b0;
    wire g_d = dm_go || (ms_hlt && dm_v);
    assign igo = !nb_r && (g_n || g_m || g_d || g_i || g_s);
    // (F5e) a REP string's take point (a TKI word: urom/str.uasm, at an element's end when the
    // string goes on; silicon, intr.py f5_si_*): NMI or the maskable offer (IE 1 and armed: IE
    // as it stood at the string's own start) is taken there, whatever the start's `nb` (a
    // prefix before the REP: f5_repint); the single step is not (one trap per string, after
    // its last element: f5_si_long; NMI inside a stepped string: f5_si_nstep); (F5e) a macro
    // service and DMA waited for the next start: (F5f) no longer, below. The word's target is
    // the string's entry into urom/trap.uasm intr: the take strobes below latch the source as at
    // a dispatch; the PC pushed is `ist` (the first
    // prefix's offset), so RETI re-enters the whole prefixed string with CW as it stands.
    // (F5f) a macro service and a DMA request are taken there too, in the dispatch's order
    // ((F4p) DMA, NMI, macro service, the maskable offer: prio.py f4p_hr; validation/v35s/dma.py f5_sdma, f5_sms,
    // f5_sms_inv, f5_sasync: silicon serves both between a long string's elements): their
    // routines resume at tmpc, the string's first prefix, so the string goes on with CW as it
    // stands. A single-step DMA take there disarms the request as at a dispatch (one element
    // between transfers: f5_sdma st_movw), a burst does not (the transfers back to back after
    // the first element: bu_movw)
    assign sgo = g_n || g_m || g_d || g_i;
    wire tki_x = ex && w_tki;
    wire dsp_x = ex && w_disp;
    assign take_d = (dsp_x && igo && g_d) || (tki_x && g_d);
    wire take_n = (dsp_x && igo && !g_d && g_n) || (tki_x && !g_d && g_n);
    wire take_m = (dsp_x && igo && !g_d && !g_n && g_m) || (tki_x && !g_d && !g_n && g_m);
    assign dm_rs = dsp_x && !take_d;          // (F4c) the CPU resumes: DIC's IF set here
    assign dm_smp = (dsp_x || tki_x) && !take_d;
    wire take_i = (dsp_x && igo && !g_n && !g_m && !g_d && g_i)
                  || (tki_x && !g_n && !g_m && !g_d && g_i);
    wire take_s = dsp_x && igo && !g_n && !g_m && !g_d && !g_i;
    always @(posedge clock) begin
        if (!core_reset_n) begin
            ie_arm <= 1'b0;
            brk_arm <= 1'b0;
            nb_r <= 1'b0;
            ms_hlt <= 1'b0;
            tk_dm <= 1'b0;
            rs_hlt <= 1'b0;
        end else if (ce_a) begin
            if (dsp_x) begin
                ie_arm <= psw_ie;
                brk_arm <= psw_brk;
            end
            if (take_d)
                tk_dm <= 1'b1;
            else if (take_n || take_m || take_i || take_s)
                tk_dm <= 1'b0;
            if (ex_pop && word.e)
                nb_r <= word.nb || rs_hlt;
            // (F5c) POP PSW, RETI, FINT (seg=NBI on the E word): the interrupt arms dropped, so
            // the next start takes neither the maskable interrupt nor the single step (NMI,
            // macro service and DMA are not held); the dispatch reloads them from the PSW
            if (ex_pop && word.e && word.seg == SG_NBI) begin
                ie_arm <= 1'b0;
                brk_arm <= 1'b0;
            end
            if (take_d || take_m)
                rs_hlt <= ms_hlt;
            else if (ex_pop && word.e)
                rs_hlt <= 1'b0;
            // (F4b) the stall of a HALT seen since the last start that was not a macro service's
            if (halted)
                ms_hlt <= 1'b1;
            else if (dsp_x && !take_m && !take_d)
                ms_hlt <= 1'b0;
        end
    end
    // (F4d) STOP (urom/xfer_stop.uasm: a halt word with cnt=stop). While it stands (`stp`, set
    // when that word executes) the halted stall's release is the settling count's end alone: NMI
    // pending (the controller's nmi_v) counts 2^19 CPU clocks (`st_c`), then `st_rel` releases it
    // (f4_stop: the first cycle 2^19 + 38 clocks after NMI's edge; IE 1 or 0); the controller's
    // wake (an unmasked IF, INT), a macro service and DMA do not (f4_stop stop_intp); the INTP
    // samplers hold (v35_intc `frz`). The release pops the instruction after STOP, whose
    // dispatch takes NMI. The count is its own 19-bit counter (not the time base's: its taps
    // keep running, as measured in HALT; the time base in STOP is not measured)
    reg         stp = 1'b0;
    reg  [18:0] st_c = 19'd0;
    reg         st_rel = 1'b0;
    wire        stp_w = word.halt && word.cnt == CN_STOP;      // the word is STOP's halt
    always @(posedge clock) begin
        if (!core_reset_n) begin
            stp <= 1'b0;
            st_c <= 19'd0;
            st_rel <= 1'b0;
        end else if (ce_a) begin
            if (stp && st_rel)
                stp <= 1'b0;
            else if (ex_b && stp_w)
                stp <= 1'b1;
            if (!stp) begin
                st_c <= 19'd0;
                st_rel <= 1'b0;
            end else if (nmi_v && !st_rel) begin
                st_c <= st_c + 19'd1;
                st_rel <= &st_c;
            end
        end
    end
    assign h_wake = (stp || stp_w) ? st_rel : (i_wake || ms_v || dm_v);
    v35_intc intc (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b, .input_levels, .frz(stp), .intm, .ic_b,
        .wr(sfr_wr), .ic_we, .ic_wd, .take_n, .take_i, .take_s,
        .iack(ex_b && word.alu == AL_IVEC), .fint(ex_b && word.alu == AL_FINT),
        .ic_if, .ispr, .ir_v, .ir_vec, .nmi_v, .wake(i_wake), .tk_vec,
        .int_on, .ie(psw_ie), .it_v, .tk_bs, .tk_lv, .tk_int, .pf_set,
        .ms_b, .take_m, .take_d, .ms_end, .ms_v, .tk_ms, .ms_ch, .ms_mode, .ms_dir, .ms_clr
    );

    // ---------------------------------------------------------------- the register RAM
    v35_regram regram (
        .clock, .ce_a, .ce_b, .ra_next, .ra_early, .rb_early, .wa_en, .wa_addr, .wa_be, .wa_data, .ra_data, .rb_next, .rb_data,
        .oc_ra(oc_off[7:1]), .oc_rd, .oc_we(pend_v), .oc_wa(pend_a), .oc_be(pend_be), .oc_wd(pend_d)
    );
    assign oc_data = oc_ram ? oc_rd : sfr_rd;
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

    // ---------------------------------------------------------------- the on-chip cycles
    // (F1) an on-chip memory cycle (the bus unit's decision, made again here on the granted
    // address: IDB:E00-EFF with RAMEN = 1, IDB:F00-FFF, FFFFF) is captured at its start: its
    // offset (the SFR read's and the register RAM's port C address: both read at every ce_b,
    // the bus unit latching the datum at the cycle's last clock) and its target. A store is
    // written at its cycle's end with the EU's datum then (a store_imm takes its immediate
    // after the store issued): the SFR page at that ce_a (as the SFR store always was); the
    // internal RAM at the next ce_b (the register RAM's ce_a belongs to the EU's write port),
    // and a write to the current bank's DS0 / SS / DS1 slot updates the segment's flop at the
    // ce_a after
    wire g_top = g_addr_b == 20'hFFFFF;
    wire g_oc = (g_addr_b[19:12] == idb && g_addr_b[11:9] == 3'b111 && (g_addr_b[8] || ramen))
                || g_top;
    wire g_ocmem = g_start_b && (g_kind_b == K_WRITE || g_kind_b == K_READ) && g_oc;
    reg sfr_open = 1'b0;
    assign sfr_wr = ce_a && sfr_open && dlv_other && !oc_ram;
    assign sfr_wat = sfr_open && dlv_other && !oc_ram;
    // the datum by lane: an odd word's halves (a byte cycle of a word request) carry its low
    // byte on the high lane (the first, odd address) and its high byte on the low lane (the
    // second), as the bus unit places them on the pins
    assign sfr_d = (sfr_w != BW_WORD && req_width) ? {sfr_data[7:0], sfr_data[15:8]} : sfr_data;
    always @(posedge clock) begin
        if (!core_reset_n) begin
            sfr_open <= 1'b0;
            pend_v <= 1'b0;
        end else if (ce_a) begin
            pend_v <= 1'b0;
            oc_rdgo <= 1'b0;
            // a cycle's end and the next cycle's start can share the clock (an odd word's
            // halves): the end reads the captured cycle, the start captures the new one
            if (sfr_open && dlv_other) begin
                sfr_open <= 1'b0;
                if (oc_ram) begin
                    pend_v <= 1'b1;
                    pend_a <= sfr_a[7:1];
                    pend_be <= sfr_w == BW_WORD ? 2'b11 : sfr_w == BW_HI ? 2'b10 : 2'b01;
                    pend_d <= sfr_d;
                end
            end
            if (g_ocmem) begin
                sfr_open <= g_kind_b == K_WRITE;
                oc_rdgo <= g_kind_b == K_READ;
                sfr_a <= g_addr_b;
                sfr_w <= g_width_b;
                oc_off <= g_top ? '1 : g_addr_b[7:0];
                oc_word <= g_width_b == BW_WORD;
                oc_ram <= !g_addr_b[8] && !g_top;
            end
        end
    end

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
    // ---------------------------------------------------------------- observation (simulation)
    // The trace's and the function bench's views (fpga/v35s/v35_core2_tb.sv reads dut.start,
    // dut.start_trap, dut.ir_addr_c), read from the modules' own nets: no module port carries
    // them. `start`: a routine's entry word executes (the sequencer's); `start_trap`: and its
    // instruction has no routine (the opcode, or the ModR/M / 0F head's second-level cell);
    // `ir_addr_c`: the linear address of the opcode the E word popped, counted as the loader
    // pops (the next queue byte's address `o_pc`, the staged opcode's `o_sa`, a flush's target
    // {PS, 0} + SIGMA registered at ce_b)
    wire        start = useq.start;
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
    wire        unused_obs = &{1'b0, start, start_trap, ir_addr_c, eu.trap_o};
`ifdef V35S_CORE_V35
    // the bus unit's: a fetch's last clock (the trace's B with the line), an EU cycle issued
    // (either half of a pair: I), the granted cycle's length (X's)
    wire        fetch_last = bus.busy && bus.c_kind == K_FETCH && bus.c_len - bus.pos_now == 3'd1;
    wire        g_eu = bus.g_second || req_ack;
    wire        q_infl_c = b_fetch_inflight || b_abort_busy;
    // ---------------------------------------------------------------- the trace hook
    v35_trace trace (
        .clock, .reset_n(core_reset_n), .ce_a,
        .g_start, .g_kind, .g_addr, .g_width, .g_len(bus.grant_len),
        .start, .epop(e_popped), .start_trap, .entry(useq.upc), .pc(ir_addr_c),
        .take(take_now), .load(ld_load),
        .post(ex_pop && word.bus != BQ_NONE), .post_kind(word.bus == BQ_MEMR ? K_READ
                                           : word.bus == BQ_MEMW ? K_WRITE
                                           : (word.bus == BQ_IOR || word.bus == BQ_INTA) ? K_IO_READ
                                           : K_IO_WRITE),
        .issue(g_eu), .b2b(fetch_last && q_fetch_req), .abort(g_abort),
        .room(5'sd6 - 5'({2'd0, q_avail} - {2'd0, ld_rd}) - (q_infl_c ? 5'sd2 : 5'sd0)),
        .flag(q_fetch_req), .why(useq.st_r.why), .upc(useq.upc)
    );
`endif
`endif

    wire unused = &{1'b0, ready, ce, x_fall, prc[7], prc[5:2],
                    rf_pending, rf_load, rf_value, rf_state_r, rf_state_e,
                    prc_at[7], prc_at[5:0], ir_vec};
endmodule
