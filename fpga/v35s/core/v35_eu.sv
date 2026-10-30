`timescale 1ns/1ps

// V35S execution unit and decoder (HDL plan, Phase C3), written from the frozen chain model
// (validation/v35s/chains/sim/frozen/eu.py, the EU; decoder.py, the Decoder, whose state and
// bookkeeping are v35_decoder.sv's; templates.py for the decode and the step lists;
// machine.py for the clock's phases and the post-issue pass) and the spec
// (docs/v35s-chain-rtl-spec.md, A2 "Decoder", "EU", "The request record", A3 "From the
// decoder", "From the EU", A4).
//
// Clocking. `ce` marks the END of a model clock: `r` holds the decoder's and the EU's state
// at the end of the last model clock (Machine._clock_row's moment) in the A2 representations
// (v35_st_t). One model clock is a combinational chain in Machine.run's order: the clock's
// start (eu_begin: the offsets move on a clock), phase C (an EU read's delivery,
// eu_complete; a delivered fetch counts against the take sync), phase T (eu_tick), phase L
// (dec_load_ir), phase X (the arbiter's touches on the EU: v35_eu_xop), phase P (the
// post-issue pass: mach_post, with the second tick and IR load), phase E's latch_start.
//
// The queue. Every queue method the EU and the decoder call, and every store they make into
// the queue, is one op of v35_queue.sv's chain (its V35_QOP_* codes, here V35_EQ_*), emitted
// in the model's order with the decoder's snapshot (v35_qsnap_t): `op_tl` for phases T and L,
// `op_p` for phase P. What the EU reads of the queue between its ops is the queue's state
// before the next op (`qv_tl[n]`, `qv_p[n]`: v35_qview_t, the fields of v35_qstate_t the EU
// reads) and an op's read (`rd_*`). The bench connects these to the RTL queue (the joint
// bench, the queue's chain T+L, the arbiter's X ops, P) or to the model's recording.
//
// The arbiter (C4) is not here: its decisions arrive as the touches it makes (`xop`: a data
// cycle issued from the slot, a left-out write's slot, the fetch on a start clock, the abort's
// take sync, a request's free_need and not_before), the cycle it started (`x_*`) and the
// requests' setup counts (`counts_*`, read by port_ready). The RTL decodes the format from the
// instruction's bytes (eu_decode, templates.decode) and selects the template (v35_tmpl_sel).
// The data latch is the bus unit's (C1): `bus_*.wl` reads it, `wl_fill_*` fills it.
//
// (D1) The register file is the EU's (v35_st_t's `f`, v35_rf_t), loaded with the chain's
// presets through `init_state`. At a start (_start) the EU decodes the instruction at pc from
// the code window (`code_win`, the twelve bytes at `code_addr`: the model decodes from the
// image, C3 decision 1), computes its operand record from the register file (v35_operands: the
// effective address of the 24 ModR/M memory modes, the direct and XLAT forms; the port, DW or
// the byte; the stack offsets from SP or BP; the shift count, CL or the byte; a transfer's
// decision and its target) and applies the instruction's start effects (v35_execute), so a
// second start in the clock reads them. `opr_*`/`rfx_*` (bench only) are each start's record
// and the register file before it.
// (D2) The function is nuV30's (validation/v35s/chains/funcref.py the reference): the register
// file holds the word, segment and PSW registers (the V35's layout) and the segment prefix
// ahead of the instruction; addresses are the segment's base + the offset (DS0, SS for the
// BP-based modes and the stack, a prefix's; the code PS's + code_org + pc). The instruction's
// function is split where the template consumes its data: the start (the register forms: the
// ALU, the shifter, the multiplier and divider, moves and exchanges; the stack pointer; the
// write datum the start knows, into the context `x`, v35_fx_t), each read's delivery (phase
// C: the bus word `c_data` into x.md and, on the request's last cycle, the read's effects:
// v35_deliver, RET's target into tgt) and each write's issue (phase X: `x_data`, v35_wdata).
// A form whose function is not built raises V35_EE_FUNC, a divide error V35_EE_DIV.
//
// (C5) With refresh on (`refresh_on`: the chain runs the refresh controller) the EU runs the
// refresh templates (refresh_hold_steps' tags) and refresh_eu=hold: the micro-boundary map
// (eu_boundary, v35_eu_pkg), the hold at the next boundary while a refresh it let through is on
// the bus (hold_end), refresh_reraise=unit, shift_exit0, refresh_sync=run's early fetch run (the
// arbiter's bus history, `early_t`/`early_p`), the clocks step's clk_tag/clk_start/clk_end/
// clk_seam, the HALT status's deferral (halt_defer), pop_refresh=stall in POP PSW's clocks, and
// the refresh's touches from the arbiter (V35_XOP_REFRESH, _SETUP, _BEAT, _HALT_DEFER: what
// EU.refresh_cost and refresh_post's give-back write). eu.sfr is the RFM store's value.
// Not built (dead under the fit or another phase's): since_start, since_t, io_pre, stalled,
// trace, origin, reg_latch_t (wlatch_ir=False), ro, seg_prefix (the register file's `pfx`),
// ls_shift (refresh_align=prelude), started (always True under
// prelude_tail=segs), refresh_beat (refresh_cost's argument: the arbiter's).
// The EU's state types (v35_eus_t, the request record v35_req_t, the bundle v35_st_t), a
// package so that the arbiter (C4) reads the state the module exports after phase L and at
// the end of the clock (state_l, state_e).
package v35_eu_pkg;
    import v35_decoder_pkg::*;

    // the take sync's modes
    localparam logic [1:0] SYNC_NONE = 2'd0, SYNC_COUNT = 2'd1, SYNC_DEFER = 2'd2;
    localparam logic [5:0] CLS_NONE = 6'd63;

    // ---- the EU's state (rtl_vectors.EUFIELDS, MSB first)
    typedef struct packed {
        logic [15:0] pc;
        logic [5:0]  cls;
        logic [7:0]  tmpl;
        logic        wbs;
        logic [8:0]  count;
        logic        ins;           // a port relatch inserted ("slot",) and the post ...
        logic [3:0]  ins_at;        // ... at this step
        logic [3:0]  k;
        logic [9:0]  res;           // resume - t (clipped at 0)
        logic [2:0]  left;
        logic        nw_v;
        logic [2:0]  nw;
        logic [2:0]  taken;
        logic [2:0]  op_len;
        logic [1:0]  imm_bytes;
        logic [1:0]  disp;
        logic        modrm;
        logic        mem;
        logic        unit;
        logic        fixed;
        logic        grp_form;
        logic        refill;        // refill_start: a flush's refill gates the next start
        logic [1:0]  route;
        logic [3:0]  floor_n;
        logic        df_v;
        logic [2:0]  df_off;
        logic [1:0]  wb;
        logic [1:0]  wbu;
        logic        done_v;
        logic [1:0]  done_age;
        logic [1:0]  sync;
        logic [1:0]  owed;
        logic [3:0]  start_age;     // t - start_clock (saturating at 15)
        logic        fs_now;
        logic        fs_this;
        logic        halted;
        logic        halt_now;
        logic [4:0]  sa_off;        // start_at - t (signed, clipped at -16: pop_refresh=stall)
        logic        exec_v;
        logic [1:0]  exec_age;
        logic        exec_par;
        logic        hd_fetch;
        logic        unit_early;
        logic        reg_early;
        logic        shift_latched;
        logic        lu_held;
        logic [2:0]  lu_off;
        logic        latch_wait_now;
        logic        port_now;
        logic [2:0]  port_held;
        logic [1:0]  own;           // 0 none, 1 the slot, 2 queued 0, 3 queued 1
        logic [19:0] ea;
        logic [15:0] port;
        logic [15:0] sr;
        logic [15:0] sw;
        logic [15:0] tgt;           // a taken transfer's target (a code offset)
        // (C5) the refresh's EU state
        logic [5:0]  prev_cls;      // refresh_beat_b2b: the class of the instruction before
        logic [7:0]  sfr;           // the SFR store's value (eu.sfr: the RFM write)
        logic        rmw;           // refresh_rmw_loop: a memory shift RMW (rmw_loop, rmw_top)
        logic        rmw_cl;        // refresh_grpcl: ... by CL (rmw_cl)
        logic [2:0]  clk_tag;       // the last clocks step's tag (CT_*)
        logic        cs_now;        // clk_start == t
        logic        clk_seam;      // the step began on the previous one's end clock
        logic [10:0] ce_off;        // clk_end - t (signed, clipped at -1: in the past)
        logic        res_past;      // resume < t (res is clipped at 0)
        logic        hv;            // refresh_eu=hold: hold_end is set ...
        logic [2:0]  h_off;         // ... hold_end - t (clipped at 0) ...
        logic        h_past;        // ... hold_end < t
        logic        hf_now;        // hold_from == t
        logic        hd_v;          // refresh_halt: halt_defer is set ...
        logic [2:0]  hd_off;        // ... halt_defer - t (clipped at 0) ...
        logic        hd_past;       // ... halt_defer < t
        logic        halt_prev;     // halt_t == t - 1
        logic        pr_cand;       // pop_refresh=stall: the last cycle is a refresh that
                                    // started before start_at, not yet counted ...
        logic        pr_now;        // ... it started on this clock ...
        logic [2:0]  pr_len;        // ... its length
    } v35_eus_t;

    // eu.clk_tag (refresh_eu=hold: the template's tags, a shift's own "loop" / "shift")
    localparam logic [2:0] CT_NONE = 3'd0, CT_EXEC = 3'd1, CT_LOOP = 3'd2, CT_TAIL = 3'd3,
                           CT_LOOP_ODD = 3'd4, CT_MEXIT = 3'd5, CT_SHIFT = 3'd6;

    // ---- a request record, the EU's fields (rtl_vectors.RFIELDS, MSB first); the arbiter's
    // own (count, ready_since, lift_t, free_held, grp_held, posted) are
    // v35_arbiter.sv's (C4)
    typedef struct packed {
        logic        valid;
        logic [2:0]  kind;          // V35_RK_*
        logic        w2;
        logic [1:0]  ncyc;
        logic [1:0]  issued;
        logic [19:0] addr;
        logic [6:0]  setup;
        logic        free_v;
        logic [4:0]  free;
        logic [1:0]  lead;
        logic        nowait;
        logic [5:0]  cls;
        logic        free_bus;
        logic        whole;
        logic [6:0]  through;
        logic [4:0]  free_orig;
        logic        imm1;
        logic        detached;
        logic        port;
        logic        moved;
        logic        dw_moved;
        logic        floor_hold;
        logic        gdisp;
        logic [3:0]  nb_off;        // not_before - t
        logic        da_v;          // done_at is set ...
        logic [2:0]  da_off;        // ... done_at - t (clipped) ...
        logic        da_past;       // ... done_at < t
        logic [1:0]  grpcl;         // (C5) refresh_grpcl: a memory shift's read: its CL clocks
        logic [2:0]  beat_ext;      // (C5) refresh_post=post_beat: the hold's clocks
    } v35_req_t;

    // ---- (D2) the register file (rtl_vectors.FFIELDS, MSB first): the word registers in
    // REG16 order (v35_rf_get's index: the ModR/M reg / rm field, B8+r), the segment registers
    // (v35_sreg_get's index is the sreg field: 0 DS1, 1 PS, 2 SS, 3 DS0), the PSW in the V35's
    // layout (15 MD, 14-12 RB, 11 V, 10 DIR, 9 IE, 8 BRK, 7 S, 6 Z, 5 F1, 4 AC, 3 F0, 2 P,
    // 1 BRKI, 0 CY; the ALU writes CY P AC Z S V only) and the segment prefix the next
    // instruction carries (bit 2: one is; 1-0 its sreg). Preset from the chain's registers
    // (the EU's presets, PS the code segment, the PSW after the prelude's POP PSW: F002h).
    typedef struct packed {
        logic [15:0] aw;
        logic [15:0] cw;
        logic [15:0] dw;
        logic [15:0] bw;
        logic [15:0] sp;
        logic [15:0] bp;
        logic [15:0] ix;
        logic [15:0] iy;
        logic [15:0] ps;
        logic [15:0] ss;
        logic [15:0] ds0;
        logic [15:0] ds1;
        logic [15:0] psw;
        logic [2:0]  pfx;
    } v35_rf_t;

    // ---- (D2) the running instruction's functional context (rtl_vectors.XFIELDS): set at its
    // start (v35_execute), the read data in at each delivery (v35_deliver), the write data out
    // at each issue (v35_wdata)
    typedef struct packed {
        logic [47:0] code;          // its bytes, the opcode in [47:40]
        logic [15:0] wd;            // the write datum: a store's, a push's, CALL's return
                                    // address, PREPARE's BP, XCH's register, an RMW's result
        logic [15:0] md;            // the read datum (an odd word's low byte first)
        logic [2:0]  rk;            // reads done (POP R's word)
        logic [2:0]  wk;            // memory writes issued (PUSH R's word)
    } v35_fx_t;

    typedef struct packed {
        v35_dec_t           d;
        v35_eus_t           e;
        v35_rf_t            f;      // (D1) the register file
        v35_fx_t            x;      // (D2) the instruction's functional context
        v35_req_t [2:0]     r;      // r[0] the slot, r[1] and r[2] queued behind it
    } v35_st_t;

    // ---- the arbiter's touches on the EU (rtl_vectors.XOPS): {code, val}
    localparam int V35_XOP_W = 12;
    localparam logic [3:0] V35_XOP_ISSUE = 4'd1;       // eu.issue: the slot's next cycle (val: its length)
    localparam logic [3:0] V35_XOP_NOWRITE = 4'd2;     // eu.issue_nowrite (val: the slot fetch's length, 0: none)
    localparam logic [3:0] V35_XOP_FETCH_START = 4'd3; // eu.fetch_start = t
    localparam logic [3:0] V35_XOP_SYNC_ONE = 4'd4;    // abort_latched: eu.sync = completed + 1
    localparam logic [3:0] V35_XOP_FREE0 = 4'd5;       // the slot's free_need = 0
    localparam logic [3:0] V35_XOP_NOT_BEFORE = 4'd6;  // the slot's not_before = t + val
    // (C5) the refresh's
    localparam logic [3:0] V35_XOP_REFRESH = 4'd7;     // a refresh cycle starts (eu.refresh_cost):
                                                       // val[2:0] its length, val[3] the EU's hold
    localparam logic [3:0] V35_XOP_SETUP = 4'd8;       // the slot's setup += val (signed)
    localparam logic [3:0] V35_XOP_BEAT = 4'd9;        // the slot's beat_ext = val
    localparam logic [3:0] V35_XOP_HALT_DEFER = 4'd10; // eu.halt_defer = t + val

    // ---- (C5) refresh_sync=run's early fetch run as the EU reads it (the bus unit's early,
    // early_n, which the arbiter keeps: v35_arbiter.sv)
    typedef struct packed {
        logic       cur;            // the cycle last started is bus.early
        logic       ep;             // bus.early ended on t - 1 (e.end == t - 1)
        logic [2:0] n;              // early_n (saturating at 7)
    } v35_early_t;

    // ---- a decoded step (v35_step's word, a count's clocks applied)
    typedef struct packed {
        logic [3:0] op;
        logic [9:0] n;
        logic [3:0] tag;
        logic [2:0] kind;
        logic [2:0] src;
        logic [2:0] src_i;
        logic [1:0] width;
        logic       has_free;
        logic [4:0] free;
        logic       grp;
        logic       whole;
        logic       detached;
    } v35_stp_t;

    // ------------------------------------------------ the step list (eu.steps)

    function automatic int eu_nsteps(input v35_eus_t e);
        if (e.cls == CLS_NONE)
            eu_nsteps = 0;                      // no instruction yet: eu.steps = []
        else
            eu_nsteps = int'(e.wbs) + v35_tmpl_len(int'(e.tmpl)) + (e.ins ? 2 : 0);
    endfunction

    // the template's j-th step (wbsync before it), the count applied
    function automatic v35_stp_t eu_base_step(input v35_eus_t e, input int j);
        logic [V35_STEP_W-1:0] w;
        v35_stp_t s;
        int n;
        s = '0;
        if (e.wbs && j == 0) begin
            s.op = 4'(V35_SOP_WBSYNC);
        end else begin
            w = v35_step(int'(e.tmpl), j - int'(e.wbs));
            s.op = w[V35_SF_OP +: V35_SF_OP_W];
            n = int'(w[V35_SF_N +: V35_SF_N_W])
                + int'(w[V35_SF_PER_COUNT +: V35_SF_PER_COUNT_W]) * int'(e.count);
            s.n = 10'(n);
            s.tag = w[V35_SF_TAG +: V35_SF_TAG_W];
            s.kind = w[V35_SF_KIND +: V35_SF_KIND_W];
            s.src = w[V35_SF_SRC +: V35_SF_SRC_W];
            s.src_i = w[V35_SF_SRC_I +: V35_SF_SRC_I_W];
            s.width = w[V35_SF_WIDTH +: V35_SF_WIDTH_W];
            s.has_free = w[V35_SF_HAS_FREE];
            s.free = w[V35_SF_FREE +: V35_SF_FREE_W];
            s.grp = w[V35_SF_GRP];
            s.whole = w[V35_SF_WHOLE];
            s.detached = w[V35_SF_DETACHED];
        end
        eu_base_step = s;
    endfunction

    // eu.steps[k]: _port_take's insertion of ("slot",) and the post at ins_at
    function automatic v35_stp_t eu_step(input v35_eus_t e, input int k);
        v35_stp_t s;
        int p;
        p = int'(e.ins_at);
        if (e.ins && k == p) begin
            s = '0;
            s.op = 4'(V35_SOP_SLOT);
        end else if (e.ins && k == p + 1) begin
            s = eu_base_step(e, p - 1);         // the port take's request
            s.op = 4'(s.detached ? V35_SOP_POST_IO : V35_SOP_POST);
            s.tag = 4'd0;
        end else if (e.ins && k > p + 1) begin
            s = eu_base_step(e, k - 2);
        end else begin
            s = eu_base_step(e, k);
        end
        eu_step = s;
    endfunction

    // ------------------------------------------------ (C5) the refresh's micro-boundary map

    // a step's model value step[1]: a port take's word carries its request's setup in n, its
    // bytes are the form's operand bytes (C3, 2)
    function automatic int eu_step_n(input v35_eus_t e, input v35_stp_t s);
        if (int'(s.op) == V35_SOP_TAKE && int'(s.tag) == V35_STAG_PORT)
            eu_step_n = int'(e.op_len) - 1;
        else
            eu_step_n = int'(s.n);
    endfunction

    // the step is the displacement's take, ("take", 2, "word") (refresh_disp)
    function automatic logic eu_disp_take(input v35_stp_t s);
        eu_disp_take = int'(s.op) == V35_SOP_TAKE && s.n == 10'd2 && int'(s.tag) == V35_STAG_WORD;
    endfunction

    // resume == clk_end, where t <= resume (every reader's case)
    function automatic logic eu_res_ce(input v35_eus_t e);
        eu_res_ce = !($signed(e.ce_off) < 0) && !e.res_past && $signed(e.ce_off) == $signed({1'b0, e.res});
    endfunction

    // inside a clocks step: t < resume and resume == clk_end
    function automatic logic eu_inside(input v35_eus_t e);
        eu_inside = e.res != '0 && $signed(e.ce_off) == $signed({1'b0, e.res});
    endfunction

    // EU.boundary: whether t is one of the EU's micro-boundaries (before: asked at the start of
    // t, ahead of the EU's step; else after it). qtake: queue.take_t >= t - 1; qlatch: a byte
    // latched behind a full queue (latched and len(bytes) > QUEUE_BYTES)
    function automatic logic eu_boundary(input v35_eus_t e, input logic qtake, input logic qlatch,
                                         input logic bef);
        v35_stp_t nxt, pst, st;
        logic inner, all0;
        int k, n, left;
        inner = eu_inside(e);
        k = int'(e.k);
        n = eu_nsteps(e);
        if (bef && !inner && k < n) begin
            nxt = eu_step(e, k);
            pst = k >= 1 ? eu_step(e, k - 1) : '0;
            // refresh_take0=none: an empty operand take is no step (a NOP's end)
            if (int'(nxt.op) == V35_SOP_TAKE && eu_step_n(e, nxt) == 0) begin
                all0 = 1'b1;
                for (int j = 0; j < 16; j++) begin
                    if (k + 1 + j < n) begin
                        st = eu_step(e, k + 1 + j);
                        if (!((int'(st.op) == V35_SOP_TAKE || int'(st.op) == V35_SOP_CLOCKS)
                              && eu_step_n(e, st) == 0))
                            all0 = 1'b0;
                    end
                end
                if (all0)
                    return 1'b1;
            end
            if (int'(nxt.op) == V35_SOP_WBSYNC)
                return 1'b0;                    // refresh_wbsync=seam
            if (int'(nxt.op) == V35_SOP_CLOCKS && int'(nxt.tag) == V35_STAG_TAIL
                    && int'(nxt.n) == FIT_REFRESH_TAIL_BOUND)
                return 1'b1;                    // shift_exit0: a 2-clock exit's first clock
            if (int'(nxt.op) == V35_SOP_CLOCKS && nxt.n != '0 && int'(nxt.tag) == V35_STAG_LOOP
                    && k >= 1 && int'(pst.op) == V35_SOP_CLOCKS && int'(pst.tag) == V35_STAG_EXEC)
                return 1'b1;                    // refresh_loop_hold=entry: the loop's first clock
            if (int'(nxt.op) == V35_SOP_CLOCKS && nxt.n != '0 && k >= 1 && e.res == '0
                    && !e.res_past && int'(pst.op) == V35_SOP_CLOCKS && e.ce_off == '0)
                return 1'b0;                    // a seamless clocks-to-clocks transition
            if (int'(nxt.op) == V35_SOP_CLOCKS && nxt.n != '0 && k >= 1 && e.res == '0
                    && !e.res_past && int'(pst.op) == V35_SOP_TAKE && k + 1 < n) begin
                st = eu_step(e, k + 1);
                if (int'(st.op) == V35_SOP_TAKE && eu_step_n(e, st) != 0 && qtake)
                    return 1'b0;                // refresh_take_seam=seam
            end
            // refresh_disp=free (_after_disp)
            if (int'(nxt.op) == V35_SOP_CLOCKS && nxt.n != '0 && k >= 1 && eu_disp_take(pst)
                    && e.res == '0 && !e.res_past && qtake)
                return 1'b0;
            if (int'(nxt.op) == V35_SOP_POST && k >= 2 && int'(pst.op) == V35_SOP_CLOCKS
                    && eu_disp_take(eu_step(e, k - 2)))
                return 1'b0;
            if (int'(nxt.op) == V35_SOP_TAKE && eu_step_n(e, nxt) != 0 && qlatch)
                return 1'b1;                    // refresh_take_latch=hold
            if (int'(nxt.op) == V35_SOP_TAKE && int'(nxt.tag) != V35_STAG_PORT)
                return 1'b0;                    // refresh_hold_take=port
            return 1'b1;
        end
        if (!inner)
            return 1'b1;
        left = int'(e.res);
        if (e.clk_tag == CT_TAIL && !bef && left == FIT_REFRESH_TAIL_BOUND)
            return 1'b1;                        // shift_exit0
        if (e.cs_now && !bef)
            return !e.clk_seam;
        case (e.clk_tag)
            CT_LOOP: return left % 2 == 0 && !e.cs_now;
            CT_LOOP_ODD: return left % 2 == 1 && !e.cs_now;
            CT_MEXIT: return left % 2 == 0 && !e.cs_now;        // refresh_mul_exit
            CT_EXEC: return left != 2 && left % 2 == 0;           // refresh_loop_hold: the eve
            CT_TAIL: return left == FIT_REFRESH_TAIL_BOUND;
            default: return 1'b0;
        endcase
    endfunction

    // EU.in_loop (refresh_reraise=unit, refresh_unit=muldiv): a count loop runs on t
    function automatic logic eu_in_loop(input v35_eus_t e);
        int c;
        c = int'(e.cls);
        if (e.cls == CLS_NONE || e.mem || !(c == V35_CLS_SHIFT_CL || c == V35_CLS_SHIFT_IMM
                                            || c == V35_CLS_MUL || c == V35_CLS_DIV))
            return 1'b0;
        if (eu_inside(e) && e.clk_tag == CT_TAIL)
            return 1'b0;                        // past its loop
        return int'(e.k) < eu_nsteps(e) || e.res != '0;
    endfunction

    // the memory shift's rmw_loop (refresh_rmw_span=all: the ALU, the shift's exec, the loop)
    // and rmw_top (the shift unit's clocks to go at its first)
    function automatic int eu_rmw_loop(input v35_eus_t e);
        if (!e.rmw)
            eu_rmw_loop = 0;
        else
            eu_rmw_loop = v35_cost(V35_CLS_RMW, V35_CN_ALU) + v35_cost(V35_CLS_SHIFT_IMM, V35_CN_EXEC)
                          + FIT_PER_SHIFT_COUNT * (int'(e.count) - 1);
    endfunction

    function automatic int eu_rmw_top(input v35_eus_t e);
        eu_rmw_top = eu_rmw_loop(e) - v35_cost(V35_CLS_RMW, V35_CN_ALU) - 1;
    endfunction

    // EU._rmw_bound (refresh_rmw_shape=shift): the write's setup d clocks before its issue
    function automatic logic eu_rmw_bound(input v35_eus_t e, input int d, input int setup);
        if (d == setup - 1 || d == FIT_REFRESH_TAIL_BOUND || d == 0)
            return 1'b1;
        return FIT_SHIFT_TAIL + 2 <= d && d <= eu_rmw_top(e) && (d - FIT_SHIFT_TAIL) % 2 == 0;
    endfunction
    // the instruction as decoded (templates.decode's Op, the format part)
    typedef struct packed {
        logic       ok;
        logic [5:0] cls;
        logic [2:0] length;
        logic [7:0] opcode;
        logic [1:0] imm_bytes;
        logic       modrm;
        logic       group;
        logic       shift;
        logic       nowrite;
        logic       dbit_v;
        logic       dbit;
        logic       fixed_alu;
        logic       swap;
        logic       signed_;
        logic       cond;
        logic [1:0] disp;
        logic       ea_v;           // op.ea is not None
        logic [2:0] mode;           // mode_class (V35_EAC_*)
        logic [1:0] width;
        logic       bus;            // the memory operand has a bus cycle (False: LDEA)
    } v35_op_t;

    // the operand record (rtl_vectors.OpRec, MSB first): (D1) the register file's and the EA
    // adder's (v35_operands) at the start, the format and template the start's
    typedef struct packed {
        logic [15:0] offset;
        logic [47:0] code;          // the instruction's bytes, the opcode in [47:40]
        logic [19:0] ea;
        logic [15:0] port;
        logic [15:0] sr;
        logic [15:0] sw;
        logic [8:0]  count;
        logic        taken;
        logic [15:0] target;
        logic [30:0] fmt;
        logic [7:0]  tmpl;
    } v35_opnd_t;

    // ------------------------------------------------ templates.decode (the format; D1: in the package, the
    // register file's unit bench decodes with it too)

    function automatic v35_op_t eu_decode(input logic [47:0] code);
        v35_op_t op;
        logic [7:0] o, m;
        logic [1:0] mod;
        logic [2:0] reg_, rm;
        logic mem;
        int n, mc;
        op = '0;
        o = code[47:40];
        m = code[39:32];
        op.ok = 1'b1;
        op.opcode = o;
        op.width = 2'd2;
        op.bus = 1'b1;
        op.length = 3'd1;
        if (o == 8'h26 || o == 8'h2E || o == 8'h36 || o == 8'h3E) begin
            op.cls = 6'(V35_CLS_PREFIX);
        end else if (o == 8'h90 || o == 8'h92) begin
            op.cls = 6'(V35_CLS_REG);
        end else if (o == 8'hF4) begin
            op.cls = 6'(V35_CLS_HALT);
        end else if (o == 8'h50) begin
            op.cls = 6'(V35_CLS_PUSH);
        end else if (o == 8'h58 || o == 8'h59) begin
            op.cls = 6'(V35_CLS_POP);
        end else if (o >= 8'hB0 && o <= 8'hB7) begin
            op.cls = 6'(V35_CLS_IMM); op.length = 3'd2; op.imm_bytes = 2'd1;
        end else if ((o >= 8'hB8 && o <= 8'hBF) || o == 8'h05 || o == 8'hA9) begin
            op.cls = 6'(V35_CLS_IMM); op.length = 3'd3; op.imm_bytes = 2'd2;
        end else if (o == 8'hA8) begin
            op.cls = 6'(V35_CLS_IMM); op.length = 3'd2; op.imm_bytes = 2'd1;
        end else if (o == 8'hA1 || o == 8'hA3) begin
            op.cls = 6'(o == 8'hA1 ? V35_CLS_LOAD : V35_CLS_STORE);
            op.length = 3'd3; op.ea_v = 1'b1; op.mode = 3'(V35_EAC_DIRECT);
        end else if (o >= 8'hE4 && o <= 8'hE7) begin
            op.cls = 6'(o < 8'hE6 ? V35_CLS_IN : V35_CLS_OUT);
            op.length = 3'd2; op.width = 2'd1 + {1'b0, o[0]};
        end else if (o >= 8'hEC && o <= 8'hEF) begin
            op.cls = 6'(o < 8'hEE ? V35_CLS_IN : V35_CLS_OUT);
            op.width = 2'd1 + {1'b0, o[0]};
        end else if (o[7:4] == 4'h7 || o == 8'hEB || o == 8'hE2) begin   // (D2) 70-7F
            op.cls = 6'(o == 8'hE2 ? V35_CLS_DBNZ : V35_CLS_BRANCH_SHORT);
            op.length = 3'd2; op.cond = o >= 8'h70 && o <= 8'h7F;
        end else if (o == 8'hE9) begin
            op.cls = 6'(V35_CLS_BRANCH_NEAR); op.length = 3'd3;
        end else if (o == 8'hE8) begin
            op.cls = 6'(V35_CLS_CALL); op.length = 3'd3;
        end else if (o == 8'hC3) begin
            op.cls = 6'(V35_CLS_RET);
        end else if (o == 8'h68 || o == 8'h6A) begin
            op.cls = 6'(V35_CLS_PUSH_IMM);
            op.imm_bytes = o == 8'h68 ? 2'd2 : 2'd1;
            op.length = 3'd1 + {1'b0, op.imm_bytes};
        end else if (o == 8'h60) begin
            op.cls = 6'(V35_CLS_PUSH_R);
        end else if (o == 8'h61) begin
            op.cls = 6'(V35_CLS_POP_R);
        end else if (o == 8'hC8) begin
            op.cls = 6'(V35_CLS_PREPARE); op.length = 3'd4; op.imm_bytes = 2'd3;
        end else if (o == 8'hC9) begin
            op.cls = 6'(V35_CLS_DISPOSE);
        end else if (o == 8'h06 || o == 8'h0E || o == 8'h16 || o == 8'h1E) begin
            op.cls = 6'(V35_CLS_PUSH_SEG);
        end else if (o == 8'h07 || o == 8'h17 || o == 8'h1F) begin
            op.cls = 6'(V35_CLS_POP_SEG);
        end else if (o == 8'hD7) begin
            op.cls = 6'(V35_CLS_XLAT); op.width = 2'd1; op.ea_v = 1'b1;
            op.mode = 3'(V35_EAC_NONE);
        end else begin
            // a ModR/M form (_modrm)
            mod = m[7:6];
            reg_ = m[5:3];
            rm = m[2:0];
            mem = mod != 2'd3;
            mc = V35_EAC_NONE;
            if (!mem) begin
                n = 1;
            end else if (mod == 2'd0 && rm == 3'd6) begin
                n = 3;
                mc = V35_EAC_DIRECT;
            end else begin
                mc = rm[2] ? V35_EAC_BASE : V35_EAC_BASE_INDEX;
                if (mod != 2'd0)
                    mc = rm[2] ? V35_EAC_BASE_DISP : V35_EAC_BASE_INDEX_DISP;
                n = 1 + int'(mod);
            end
            op.ea_v = mem;
            op.mode = 3'(mc);
            op.modrm = 1'b1;
            op.width = ((o < 8'h40 || (o >= 8'h84 && o <= 8'h8B)) && !o[0]) ? 2'd1 : 2'd2;
            if (o == 8'hD0 || o == 8'hF6)
                op.width = 2'd1;
            op.group = o inside {8'h80, 8'h81, 8'h82, 8'h83, 8'h8F, 8'hC0, 8'hC1, 8'hC6, 8'hC7,
                                 8'hD0, 8'hD1, 8'hD2, 8'hD3, 8'hF6, 8'hF7, 8'hFE, 8'hFF};
            op.disp = mem ? 2'(n - 1) : 2'd0;
            if ((o < 8'h40 && !o[2]) || (o >= 8'h88 && o <= 8'h8B)) begin
                op.dbit_v = 1'b1;
                op.dbit = o[1];
            end
            op.fixed_alu = o == 8'h84 || o == 8'h85;
            op.swap = mem && (o == 8'h86 || o == 8'h87);
            op.length = 3'(1 + n);
            if (o < 8'h40 && o[2:0] < 3'd4) begin
                op.cls = 6'(!mem ? V35_CLS_REG
                            : (!o[1] && o[5:3] != 3'd7) ? V35_CLS_RMW : V35_CLS_LOAD_ALU);
            end else if (o == 8'h8B || o == 8'h8A || o == 8'h85 || o == 8'h89 || o == 8'h88
                         || o == 8'h87 || o == 8'h84 || o == 8'h86) begin
                if (!mem)
                    op.cls = 6'(V35_CLS_REG);
                else if (o == 8'h8B || o == 8'h8A)
                    op.cls = 6'(V35_CLS_LOAD);
                else if (o == 8'h89 || o == 8'h88)
                    op.cls = 6'(V35_CLS_STORE);
                else if (o == 8'h87 || o == 8'h86)
                    op.cls = 6'(V35_CLS_RMW);
                else
                    op.cls = 6'(V35_CLS_LOAD_ALU);
            end else if (o == 8'h81 || o == 8'h83) begin
                op.imm_bytes = o == 8'h81 ? 2'd2 : 2'd1;
                op.length = op.length + {1'b0, op.imm_bytes};
                op.cls = 6'(!mem ? V35_CLS_IMM : reg_ == 3'd7 ? V35_CLS_LOAD_ALU
                                                               : V35_CLS_RMW_IMM);
                op.nowrite = mem && reg_ == 3'd7;
            end else if (o == 8'hC7) begin
                op.length = op.length + 3'd2;
                op.imm_bytes = 2'd2;
                op.cls = 6'(V35_CLS_STORE_IMM);
            end else if (o == 8'hC6) begin
                op.length = op.length + 3'd1;
                op.imm_bytes = 2'd1;
                op.width = 2'd1;
                op.cls = 6'(V35_CLS_STORE_IMM);
            end else if (o == 8'hC1) begin
                op.length = op.length + 3'd1;
                op.imm_bytes = 2'd1;
                op.cls = 6'(V35_CLS_SHIFT_IMM);
            end else if (o == 8'hD0 || o == 8'hD1) begin
                if (!mem) begin
                    op.cls = 6'(V35_CLS_SHIFT_IMM);
                end else begin
                    op.cls = 6'(V35_CLS_RMW);
                    op.shift = 1'b1;
                end
            end else if (o == 8'hD3) begin
                op.cls = 6'(!mem ? V35_CLS_SHIFT_CL : V35_CLS_RMW);
                op.shift = mem;
            end else if (o == 8'hF6 || o == 8'hF7) begin
                if (reg_ == 3'd0 && o == 8'hF6) begin
                    op.ok = 1'b0;
                end else if (reg_ == 3'd0) begin
                    op.length = op.length + 3'd2;
                    op.imm_bytes = 2'd2;
                    op.fixed_alu = 1'b1;
                    op.cls = 6'(mem ? V35_CLS_LOAD_ALU : V35_CLS_IMM);
                    op.nowrite = mem;
                end else begin
                    op.cls = 6'(reg_ == 3'd4 || reg_ == 3'd5 ? V35_CLS_MUL
                                : reg_ == 3'd6 || reg_ == 3'd7 ? V35_CLS_DIV : V35_CLS_RMW);
                    op.signed_ = reg_ == 3'd5 || reg_ == 3'd7;
                end
            end else if (o == 8'hFF) begin
                op.cls = 6'(reg_ == 3'd6 ? V35_CLS_PUSH_MEM : V35_CLS_RMW);
            end else if (o == 8'h8F) begin
                op.cls = 6'(V35_CLS_POP_MEM);
            end else if (o == 8'h8E) begin
                op.cls = 6'(!mem ? V35_CLS_REG : V35_CLS_LOAD_SEG);
            end else if (o == 8'h8C) begin
                op.cls = 6'(mem ? V35_CLS_STORE : V35_CLS_REG);
            end else if (o == 8'h8D) begin
                op.ok = mem;
                op.cls = 6'(V35_CLS_LEA);
                op.bus = 1'b0;
            end else begin
                op.ok = 1'b0;
            end
        end
        eu_decode = op;
    endfunction

    // ------------------------------------------------ (D1, D2) the register file, the EA adder
    // and the ALU: templates.decode's operands, then the instruction's function with nuV30's
    // semantics (validation/v35s/chains/funcref.py is the reference: instructions.json and
    // undefined_flags.md's laws), split at the points the template consumes data: the start
    // (v35_execute: the register forms, the stack pointer, the write data known there), each
    // read's delivery (v35_deliver: the datum into md, the read's effects on the request's last
    // cycle), each write's issue (v35_wdata). `mut` is the bench's mutation (0: none; 8: [BW+IX]
    // without IX, 9: a push's SP step 4, 10: MOV r8,imm8 into the other half; 11: ADD's AC
    // inverted, 12: a memory write's datum with bit 0 flipped, 13: the BP-based modes in DS0).

    localparam int V35_PSW_CY = 0, V35_PSW_P = 2, V35_PSW_AC = 4, V35_PSW_Z = 6,
                   V35_PSW_S = 7, V35_PSW_DIR = 10, V35_PSW_V = 11;

    // REG16[i]
    function automatic logic [15:0] v35_rf_get(input v35_rf_t f, input logic [2:0] i);
        case (i)
            3'd0: v35_rf_get = f.aw;
            3'd1: v35_rf_get = f.cw;
            3'd2: v35_rf_get = f.dw;
            3'd3: v35_rf_get = f.bw;
            3'd4: v35_rf_get = f.sp;
            3'd5: v35_rf_get = f.bp;
            3'd6: v35_rf_get = f.ix;
            default: v35_rf_get = f.iy;
        endcase
    endfunction

    function automatic v35_rf_t v35_rf_set(input v35_rf_t f0, input logic [2:0] i,
                                           input logic [15:0] v);
        v35_rf_t f;
        f = f0;
        case (i)
            3'd0: f.aw = v;
            3'd1: f.cw = v;
            3'd2: f.dw = v;
            3'd3: f.bw = v;
            3'd4: f.sp = v;
            3'd5: f.bp = v;
            3'd6: f.ix = v;
            default: f.iy = v;
        endcase
        v35_rf_set = f;
    endfunction

    // REG8[k]: the low (k < 4) or high byte of REG16[k & 3]
    function automatic logic [7:0] v35_rf_get8(input v35_rf_t f, input logic [2:0] k);
        logic [15:0] w;
        w = v35_rf_get(f, {1'b0, k[1:0]});
        v35_rf_get8 = k[2] ? w[15:8] : w[7:0];
    endfunction

    function automatic v35_rf_t v35_rf_set8(input v35_rf_t f, input logic [2:0] k,
                                            input logic [7:0] v);
        logic [15:0] w;
        w = v35_rf_get(f, {1'b0, k[1:0]});
        if (k[2])
            w[15:8] = v;
        else
            w[7:0] = v;
        v35_rf_set8 = v35_rf_set(f, {1'b0, k[1:0]}, w);
    endfunction

    // a register operand of width w (1: word): REG16[k] or REG8[k] in the low byte
    function automatic logic [15:0] v35_reg(input v35_rf_t f, input logic [2:0] k, input logic w);
        v35_reg = w ? v35_rf_get(f, k) : {8'd0, v35_rf_get8(f, k)};
    endfunction

    function automatic v35_rf_t v35_set_reg(input v35_rf_t f, input logic [2:0] k,
                                            input logic w, input logic [15:0] v);
        v35_set_reg = w ? v35_rf_set(f, k, v) : v35_rf_set8(f, k, v[7:0]);
    endfunction

    // the segment registers by the sreg field (0 DS1, 1 PS, 2 SS, 3 DS0)
    function automatic logic [15:0] v35_sreg_get(input v35_rf_t f, input logic [1:0] i);
        case (i)
            2'd0: v35_sreg_get = f.ds1;
            2'd1: v35_sreg_get = f.ps;
            2'd2: v35_sreg_get = f.ss;
            default: v35_sreg_get = f.ds0;
        endcase
    endfunction

    function automatic v35_rf_t v35_sreg_set(input v35_rf_t f0, input logic [1:0] i,
                                             input logic [15:0] v);
        v35_rf_t f;
        f = f0;
        case (i)
            2'd0: f.ds1 = v;
            2'd1: f.ps = v;
            2'd2: f.ss = v;
            default: f.ds0 = v;
        endcase
        v35_sreg_set = f;
    endfunction

    // the instruction's byte i (byte 0 the opcode)
    function automatic logic [7:0] v35_code_byte(input logic [47:0] code, input int i);
        v35_code_byte = code[47 - 8 * i -: 8];
    endfunction

    // the byte index of a ModR/M form's first byte after the displacement (its immediate)
    function automatic int v35_imm_at(input logic [47:0] code);
        logic [7:0] m;
        m = code[39:32];
        if (m[7:6] == 2'd1)
            v35_imm_at = 3;
        else if (m[7:6] == 2'd2 || (m[7:6] == 2'd0 && m[2:0] == 3'd6))
            v35_imm_at = 4;
        else
            v35_imm_at = 2;
    endfunction

    // a ModR/M form's immediate: the 81 / C7 / F7 /0 word, 83's byte sign-extended, the byte
    function automatic logic [15:0] v35_imm(input logic [47:0] code);
        logic [7:0] o, lo, hi;
        int k;
        o = code[47:40];
        k = v35_imm_at(code);
        lo = v35_code_byte(code, k);
        hi = v35_code_byte(code, k + 1);
        if (o == 8'h83)
            v35_imm = {{8{lo[7]}}, lo};
        else if (o[0])
            v35_imm = {hi, lo};
        else
            v35_imm = {8'd0, lo};
    endfunction

    // S Z P of a result of width w
    function automatic logic [15:0] v35_szp(input logic [15:0] psw0, input logic [15:0] r,
                                            input logic w);
        logic [15:0] psw;
        psw = psw0;
        psw[V35_PSW_S] = w ? r[15] : r[7];
        psw[V35_PSW_Z] = w ? r == 16'd0 : r[7:0] == 8'd0;
        psw[V35_PSW_P] = ~^r[7:0];
        v35_szp = psw;
    endfunction

    // the ALU: op the 00-3F block's / the 80-83 group's bits 5:3 (ADD OR ADC SBB AND SUB XOR
    // CMP), w the word form; the result (CMP's: the difference) and the PSW: CY V AC S Z P
    // written, the logic operations clearing CY V AC (undefined_flags.md: AC always 0)
    function automatic logic [15:0] v35_alu(input logic [2:0] op, input logic w,
                                            input logic [15:0] a0, input logic [15:0] b0,
                                            input logic [15:0] psw0, input logic [3:0] mut,
                                            output logic [15:0] psw);
        logic [16:0] r;
        logic [15:0] a, b, m, msb, res;
        logic cin, cy, v, ac;
        m = w ? 16'hFFFF : 16'h00FF;
        msb = w ? 16'h8000 : 16'h0080;
        a = a0 & m;
        b = b0 & m;
        cin = (op == 3'd2 || op == 3'd3) && psw0[V35_PSW_CY];
        cy = 1'b0;
        v = 1'b0;
        ac = 1'b0;
        case (op)
            3'd0, 3'd2: begin
                r = {1'b0, a} + {1'b0, b} + {16'd0, cin};
                v = |((a ^ r[15:0]) & (b ^ r[15:0]) & msb);
            end
            3'd3, 3'd5, 3'd7: begin
                r = {1'b0, a} - {1'b0, b} - {16'd0, cin};
                v = |((a ^ b) & (a ^ r[15:0]) & msb);
            end
            3'd1: r = {1'b0, a | b};
            3'd4: r = {1'b0, a & b};
            default: r = {1'b0, a ^ b};
        endcase
        if (op != 3'd1 && op != 3'd4 && op != 3'd6) begin
            cy = w ? r[16] : r[8];
            ac = a[4] ^ b[4] ^ r[4];
            if (mut == 4'd11 && op == 3'd0)
                ac = !ac;
        end
        res = r[15:0] & m;
        psw = v35_szp(psw0, res, w);
        psw[V35_PSW_CY] = cy;
        psw[V35_PSW_V] = v;
        psw[V35_PSW_AC] = ac;
        v35_alu = res;
    endfunction

    // the shift group (D0-D3, C0/C1; the reg field): ROL ROR ROLC RORC SHL SHR SHL (6, the
    // undocumented alias) SHRA by n, the full count (shift_count_mask=cl8). A count of 0
    // changes nothing; the rotates are periodic in the width (ROLC / RORC in the width + 1),
    // the shifts settle after width + 1. CY the last bit out; V from the final state (the
    // shift-V law: left ops MSB ^ CY, right ops the two top bits); the shifts write S Z P and
    // clear AC, the rotates leave them.
    function automatic logic [15:0] v35_shift(input logic [2:0] op, input logic w,
                                              input logic [15:0] a0, input logic [8:0] n,
                                              input logic [15:0] psw0, output logic [15:0] psw);
        logic [15:0] a, m, msb, msb1;
        logic cy, c;
        int k, nb;
        psw = psw0;
        if (n == 9'd0)
            return a0;
        nb = w ? 16 : 8;
        m = w ? 16'hFFFF : 16'h00FF;
        msb = w ? 16'h8000 : 16'h0080;
        msb1 = msb >> 1;
        a = a0 & m;
        cy = psw0[V35_PSW_CY];
        case (op)
            3'd0, 3'd1: k = int'(n) % nb;
            3'd2, 3'd3: k = int'(n) % (nb + 1);
            default: k = int'(n) > nb ? nb + 1 : int'(n);
        endcase
        for (int i = 0; i < 17; i++) begin
            if (i < k) begin
                case (op)
                    3'd0: a = ((a << 1) | {15'd0, |(a & msb)}) & m;
                    3'd1: a = (a >> 1) | (a[0] ? msb : 16'd0);
                    3'd2: begin
                        c = |(a & msb);
                        a = ((a << 1) | {15'd0, cy}) & m;
                        cy = c;
                    end
                    3'd3: begin
                        c = a[0];
                        a = (a >> 1) | (cy ? msb : 16'd0);
                        cy = c;
                    end
                    3'd5: begin
                        cy = a[0];
                        a = a >> 1;
                    end
                    3'd7: begin
                        cy = a[0];
                        a = (a >> 1) | (a & msb);
                    end
                    default: begin
                        cy = |(a & msb);
                        a = (a << 1) & m;
                    end
                endcase
            end
        end
        if (op == 3'd0)
            cy = a[0];
        else if (op == 3'd1)
            cy = |(a & msb);
        psw[V35_PSW_CY] = cy;
        if (op == 3'd0 || op == 3'd2 || op == 3'd4 || op == 3'd6)
            psw[V35_PSW_V] = |(a & msb) ^ cy;
        else
            psw[V35_PSW_V] = |(a & msb) ^ |(a & msb1);
        if (op[2]) begin
            psw = v35_szp(psw, a, w);
            psw[V35_PSW_AC] = 1'b0;
        end
        v35_shift = a;
    endfunction

    // MULU / MUL: the double-width product ([15:0] for a byte form). CY = V = the high half is
    // not the low half's extension; MULU leaves S Z AC P, MUL writes them as the flags of the
    // low half added to itself (undefined_flags.md)
    function automatic logic [31:0] v35_mul(input logic sgn, input logic w,
                                            input logic [15:0] a, input logic [15:0] b,
                                            input logic [15:0] psw0, output logic [15:0] psw);
        logic [31:0] p, sa, sb;
        logic [15:0] lo, f;
        logic ext;
        psw = psw0;
        if (w) begin
            sa = sgn ? {{16{a[15]}}, a} : {16'd0, a};
            sb = sgn ? {{16{b[15]}}, b} : {16'd0, b};
            p = sa * sb;
            lo = p[15:0];
            ext = sgn ? p[31:16] != {16{p[15]}} : p[31:16] != 16'd0;
        end else begin
            sa = sgn ? {{24{a[7]}}, a[7:0]} : {24'd0, a[7:0]};
            sb = sgn ? {{24{b[7]}}, b[7:0]} : {24'd0, b[7:0]};
            p = {16'd0, 16'(sa * sb)};
            lo = {8'd0, p[7:0]};
            ext = sgn ? p[15:8] != {8{p[7]}} : p[15:8] != 8'd0;
        end
        if (sgn) begin
            void'(v35_alu(3'd0, w, lo, lo, psw0, 4'd0, f));
            psw[V35_PSW_S] = f[V35_PSW_S];
            psw[V35_PSW_Z] = f[V35_PSW_Z];
            psw[V35_PSW_AC] = f[V35_PSW_AC];
            psw[V35_PSW_P] = f[V35_PSW_P];
        end
        psw[V35_PSW_CY] = ext;
        psw[V35_PSW_V] = ext;
        v35_mul = p;
    endfunction

    // DIVU / DIV of num (DW:AW; a byte form AW) by d: {remainder, quotient} ([15:8] / [7:0]
    // for a byte form). DIVU: the flags of the overflow pre-check SUB(num's high half, d), a
    // trap when it does not borrow (d = 0 included). DIV: the magnitudes' pre-check
    // SUB(|num|'s high half, |d|) traps with its flags; else the unsigned quotient's S Z P,
    // CY AC V clear, a quotient beyond 2^(n-1) - 1 trapping (symmetric); truncation toward 0,
    // the remainder the dividend's sign (undefined_flags.md, Campaign 3). trap: the divide
    // error (its sequence is a later item: the registers are left)
    function automatic logic [31:0] v35_div(input logic sgn, input logic w,
                                            input logic [31:0] num, input logic [15:0] d0,
                                            input logic [15:0] psw0, output logic [15:0] psw,
                                            output logic trap);
        logic [31:0] an, q, r;
        logic [15:0] ad, hi;
        logic nneg, dneg;
        psw = psw0;
        trap = 1'b0;
        if (w) begin
            nneg = sgn && num[31];
            dneg = sgn && d0[15];
            an = nneg ? 32'd0 - num : num;
            ad = dneg ? 16'd0 - d0 : d0;
            hi = an[31:16];
        end else begin
            nneg = sgn && num[15];
            dneg = sgn && d0[7];
            an = {16'd0, nneg ? 16'd0 - num[15:0] : num[15:0]};
            ad = {8'd0, dneg ? 8'd0 - d0[7:0] : d0[7:0]};
            hi = {8'd0, an[15:8]};
        end
        if (hi >= ad) begin                     // the pre-check (d = 0 included)
            void'(v35_alu(3'd5, w, hi, ad, psw0, 4'd0, psw));
            trap = 1'b1;
            return 32'd0;
        end
        q = an / {16'd0, ad};
        r = an % {16'd0, ad};
        if (!sgn) begin
            void'(v35_alu(3'd5, w, hi, ad, psw0, 4'd0, psw));
        end else begin
            psw = v35_szp(psw0, q[15:0], w);
            psw[V35_PSW_CY] = 1'b0;
            psw[V35_PSW_AC] = 1'b0;
            psw[V35_PSW_V] = 1'b0;
            if (w ? q > 32'h7FFF : q > 32'h7F) begin
                trap = 1'b1;
                return 32'd0;
            end
            if (nneg != dneg)
                q = 32'd0 - q;
            if (nneg)
                r = 32'd0 - r;
        end
        v35_div = w ? {r[15:0], q[15:0]} : {16'd0, r[7:0], q[7:0]};
    endfunction

    // Bcond's 16 conditions (the 70-7F row's low nibble)
    function automatic logic v35_cond(input logic [15:0] psw, input logic [3:0] cc);
        logic t, cy, z, s, v, p;
        cy = psw[V35_PSW_CY];
        z = psw[V35_PSW_Z];
        s = psw[V35_PSW_S];
        v = psw[V35_PSW_V];
        p = psw[V35_PSW_P];
        case (cc[3:1])
            3'd0: t = v;
            3'd1: t = cy;
            3'd2: t = z;
            3'd3: t = cy || z;
            3'd4: t = s;
            3'd5: t = p;
            3'd6: t = s ^ v;
            default: t = (s ^ v) || z;
        endcase
        v35_cond = t ^ cc[0];
    endfunction

    // the memory operand's offset (templates.RM, the direct forms, XLAT's BW + AL) and its
    // segment register's value: DS0, SS for the BP-based modes, a prefix's when one is ahead
    function automatic logic [15:0] v35_ea_off(input v35_rf_t f, input logic [47:0] code,
                                               input logic [3:0] mut, output logic [15:0] seg);
        logic [7:0] o, b1, b2, b3;
        logic [1:0] mod;
        logic [2:0] rm;
        logic [15:0] base, disp;
        logic bp;
        o = code[47:40];
        b1 = code[39:32];
        b2 = code[31:24];
        b3 = code[23:16];
        bp = 1'b0;
        if (o >= 8'hA0 && o <= 8'hA3) begin
            v35_ea_off = {b2, b1};              // direct, no ModR/M
        end else if (o == 8'hD7) begin
            v35_ea_off = f.bw + {8'd0, f.aw[7:0]};   // XLAT: BW + AL
        end else begin
            mod = b1[7:6];
            rm = b1[2:0];
            if (mod == 2'd0 && rm == 3'd6) begin
                v35_ea_off = {b3, b2};          // direct
            end else begin
                case (rm)                       // templates.RM
                    3'd0: base = f.bw + (mut == 4'd8 ? 16'd0 : f.ix);
                    3'd1: base = f.bw + f.iy;
                    3'd2: base = f.bp + f.ix;
                    3'd3: base = f.bp + f.iy;
                    3'd4: base = f.ix;
                    3'd5: base = f.iy;
                    3'd6: base = f.bp;
                    default: base = f.bw;
                endcase
                bp = rm == 3'd2 || rm == 3'd3 || rm == 3'd6;
                disp = mod == 2'd1 ? {{8{b2[7]}}, b2} : mod == 2'd2 ? {b3, b2} : 16'd0;
                v35_ea_off = base + disp;
            end
        end
        seg = f.pfx[2] ? v35_sreg_get(f, f.pfx[1:0]) : (bp && mut != 4'd13) ? f.ss : f.ds0;
    endfunction

    // the forms whose function the RTL builds: those the decoder knows whose template fits
    // their semantics. Not built (V35_EE_FUNC): F6/F7 /1 (TEST's alias: the decoder gives it
    // the RMW template), FF /2-/5 and /7 (transfers), the register forms of F6/F7 /2 /3 and
    // FF /0 /1 /6, 8F and C6/C7 (the decoder gives them a memory template with no address),
    // 8F /1-7, MOV PS,r/m (8E /1: the code segment changes under the queue) and PREPARE with
    // a level (frozen templates.decode raises)
    function automatic logic v35_func_ok(input logic [47:0] code);
        logic [7:0] o;
        logic [1:0] mod;
        logic [2:0] reg_;
        o = code[47:40];
        mod = code[39:38];
        reg_ = code[37:35];
        v35_func_ok = 1'b1;
        if ((o == 8'hF6 || o == 8'hF7) && (reg_ == 3'd1 || (mod == 2'd3 && (reg_ == 3'd2
                                                                              || reg_ == 3'd3))))
            v35_func_ok = 1'b0;
        if (o == 8'hFF && (reg_ inside {3'd2, 3'd3, 3'd4, 3'd5, 3'd7} || mod == 2'd3))
            v35_func_ok = 1'b0;
        if (o == 8'h8F && (mod == 2'd3 || reg_ != 3'd0))
            v35_func_ok = 1'b0;
        if ((o == 8'hC6 || o == 8'hC7) && mod == 2'd3)
            v35_func_ok = 1'b0;
        if (o == 8'h8E && reg_[1:0] == 2'd1)
            v35_func_ok = 1'b0;
        if (o == 8'hC8 && code[23:16] != 8'd0)
            v35_func_ok = 1'b0;
    endfunction

    // templates.decode's operands from the register file before the instruction: the memory
    // operand's linear address (its segment's base + the offset: the SFR store's, DS1-prefixed,
    // in the SFR page as any other), the port, the stack offsets (SS's base is added by the
    // request: eu_addr), the shift count, a transfer's decision and target (RET's target is the
    // stack read's: 0 here, the EU's tgt set at the delivery). The format and the template are
    // the start's. bad: a form whose function the RTL does not build (v35_func_ok)
    function automatic v35_opnd_t v35_operands(input v35_rf_t f, input logic [47:0] code,
                                               input logic [15:0] pc, input v35_op_t op,
                                               input logic [3:0] mut, output logic bad);
        v35_opnd_t r;
        logic [7:0] o, b1, b2;
        logic [15:0] off, seg, tgt;
        logic tk;
        int c;
        r = '0;
        o = code[47:40];
        b1 = code[39:32];
        b2 = code[31:24];
        c = int'(op.cls);
        r.offset = pc;
        r.code = code;
        if (op.ea_v) begin
            off = v35_ea_off(f, code, mut, seg);
            r.ea = {seg, 4'd0} + {4'd0, off};
        end
        // the port: the byte, or DW
        if (o >= 8'hE4 && o <= 8'hE7)
            r.port = {8'd0, b1};
        else if (o >= 8'hEC && o <= 8'hEF)
            r.port = f.dw;
        // the stack: (read, write)
        if (c == V35_CLS_PUSH || c == V35_CLS_PUSH_IMM || c == V35_CLS_PUSH_R
                || c == V35_CLS_PREPARE || c == V35_CLS_PUSH_SEG || c == V35_CLS_CALL
                || c == V35_CLS_PUSH_MEM)
            r.sw = f.sp - 16'd2;
        if (c == V35_CLS_POP || c == V35_CLS_POP_R || c == V35_CLS_POP_SEG || c == V35_CLS_RET
                || c == V35_CLS_POP_MEM)
            r.sr = f.sp;
        if (c == V35_CLS_DISPOSE)
            r.sr = f.bp;
        // the shift count: C1's byte, D0/D1's 1, D3's CL (shift_count_mask=cl8: the byte)
        if (o == 8'hC1)
            r.count = {1'b0, v35_code_byte(code, int'(op.length) - 1)};
        else if (o == 8'hD0 || o == 8'hD1)
            r.count = 9'd1;
        else if (o == 8'hD3)
            r.count = {1'b0, f.cw[7:0]};
        // (WP55, F23; D2) a transfer: taken (Bcond from the PSW), and its target
        tk = 1'b0;
        tgt = 16'd0;
        if (o[7:4] == 4'h7 || o == 8'hEB || o == 8'hE2) begin
            tgt = pc + 16'd2 + {{8{b1[7]}}, b1};
            if (o == 8'hE2)
                tk = f.cw != 16'd1;             // DBNZ: CW - 1 != 0
            else if (o == 8'hEB)
                tk = 1'b1;
            else
                tk = v35_cond(f.psw, o[3:0]);
        end else if (o == 8'hE9 || o == 8'hE8) begin
            tgt = pc + 16'd3 + {b2, b1};
            tk = 1'b1;
        end else if (o == 8'hC3) begin
            tk = 1'b1;                          // RET: the target is the stack read's
        end
        r.taken = tk;
        r.target = tk ? tgt : 16'd0;
        bad = !v35_func_ok(code);
        v35_operands = r;
    endfunction

    // the instruction's function at its start: the register forms (the ALU, the shifter, the
    // multiplier and divider, the moves and exchanges, the segment moves), the stack pointer's
    // and CW's steps, LDEA's offset, the segment prefix; the context for its data (the write
    // datum the start knows). ret: the return address CALL pushes (code_org + the next
    // instruction's offset); trap: a register divide's error
    function automatic v35_rf_t v35_execute(input v35_rf_t f0, input logic [47:0] code,
                                            input v35_op_t op, input v35_opnd_t r,
                                            input logic [15:0] code_org, input logic [3:0] mut,
                                            output v35_fx_t x, output logic trap);
        v35_rf_t f;
        logic [7:0] o, b1, b2;
        logic [1:0] mod;
        logic [2:0] reg_, rm;
        logic [15:0] a, b, res, psw, seg, imm;
        logic [31:0] p;
        logic w, mem;
        int c;
        f = f0;
        x = '0;
        x.code = code;
        trap = 1'b0;
        o = code[47:40];
        b1 = code[39:32];
        b2 = code[31:24];
        mod = b1[7:6];
        reg_ = b1[5:3];
        rm = b1[2:0];
        w = o[0];
        mem = op.ea_v;
        c = int'(op.cls);
        imm = v35_imm(code);
        if (o >= 8'hB0 && o <= 8'hB7) begin
            f = v35_rf_set8(f, mut == 4'd10 ? o[2:0] ^ 3'd4 : o[2:0], b1);
        end else if (o >= 8'hB8 && o <= 8'hBF) begin
            f = v35_rf_set(f, o[2:0], {b2, b1});
        end else if (o >= 8'h91 && o <= 8'h97) begin
            a = v35_rf_get(f, o[2:0]);          // XCH AW,r16
            f = v35_rf_set(f, o[2:0], f.aw);
            f.aw = a;
        end else if (o == 8'h05) begin
            f.aw = v35_alu(3'd0, 1'b1, f.aw, {b2, b1}, f.psw, mut, psw);
            f.psw = psw;
        end else if (o == 8'hA8 || o == 8'hA9) begin
            void'(v35_alu(3'd4, w, f.aw, w ? {b2, b1} : {8'd0, b1}, f.psw, mut, psw));
            f.psw = psw;
        end else if (o == 8'hA2 || o == 8'hA3) begin
            x.wd = v35_reg(f, 3'd0, w);         // MOV [disp16],acc
        end else if (o >= 8'h50 && o <= 8'h57) begin
            x.wd = o == 8'h54 ? f.sp - 16'd2 : v35_rf_get(f, o[2:0]);
        end else if (o == 8'h06 || o == 8'h0E || o == 8'h16 || o == 8'h1E) begin
            x.wd = v35_sreg_get(f, o[4:3]);
        end else if (o == 8'h68 || o == 8'h6A) begin
            x.wd = o == 8'h68 ? {b2, b1} : {{8{b1[7]}}, b1};
        end else if (o == 8'hE8) begin
            x.wd = code_org + r.offset + 16'd3; // CALL: the return address (its IP)
        end else if (o == 8'hC8) begin
            x.wd = f.bp;                        // PREPARE: BP pushed
        end else if (op.modrm) begin
            a = v35_reg(f, reg_, w);            // the reg field's operand
            b = v35_reg(f, rm, w);              // the rm field's register operand
            if (o < 8'h40 && o[2:0] < 3'd4) begin
                if (!mem) begin
                    if (o[1]) begin
                        res = v35_alu(o[5:3], w, a, b, f.psw, mut, psw);
                        if (o[5:3] != 3'd7)
                            f = v35_set_reg(f, reg_, w, res);
                    end else begin
                        res = v35_alu(o[5:3], w, b, a, f.psw, mut, psw);
                        if (o[5:3] != 3'd7)
                            f = v35_set_reg(f, rm, w, res);
                    end
                    f.psw = psw;
                end
            end else if (o == 8'h84 || o == 8'h85) begin
                if (!mem) begin
                    void'(v35_alu(3'd4, w, b, a, f.psw, mut, psw));
                    f.psw = psw;
                end
            end else if (o == 8'h86 || o == 8'h87) begin
                if (!mem) begin
                    f = v35_set_reg(f, reg_, w, b);
                    f = v35_set_reg(f, rm, w, a);
                end else begin
                    x.wd = a;                   // XCH r/m,reg: the register's value written
                end
            end else if (o >= 8'h88 && o <= 8'h8B) begin
                if (!mem && o[1])
                    f = v35_set_reg(f, reg_, w, b);
                else if (!mem)
                    f = v35_set_reg(f, rm, w, a);
                else if (!o[1])
                    x.wd = a;                   // MOV r/m,reg
            end else if (o == 8'h8C) begin
                if (!mem)
                    f = v35_rf_set(f, rm, v35_sreg_get(f, reg_[1:0]));
                else
                    x.wd = v35_sreg_get(f, reg_[1:0]);
            end else if (o == 8'h8D) begin
                f = v35_rf_set(f, reg_, v35_ea_off(f, code, mut, seg));   // LDEA: the offset
            end else if (o == 8'h8E) begin
                if (!mem)
                    f = v35_sreg_set(f, reg_[1:0], v35_rf_get(f, rm));
            end else if (o >= 8'h80 && o <= 8'h83) begin
                if (!mem) begin
                    res = v35_alu(reg_, w, b, imm, f.psw, mut, psw);
                    if (reg_ != 3'd7)
                        f = v35_set_reg(f, rm, w, res);
                    f.psw = psw;
                end
            end else if (o == 8'hC6 || o == 8'hC7) begin
                x.wd = imm;                     // MOV r/m,imm
            end else if (o == 8'hC0 || o == 8'hC1 || (o >= 8'hD0 && o <= 8'hD3)) begin
                if (!mem) begin
                    res = v35_shift(reg_, w, b, r.count, f.psw, psw);
                    f = v35_set_reg(f, rm, w, res);
                    f.psw = psw;
                end
            end else if (o == 8'hF6 || o == 8'hF7) begin
                if (!mem) begin
                    if (reg_ == 3'd0) begin
                        void'(v35_alu(3'd4, w, b, imm, f.psw, mut, psw));
                        f.psw = psw;
                    end else if (reg_ == 3'd4 || reg_ == 3'd5) begin
                        p = v35_mul(reg_[0], w, f.aw, b, f.psw, psw);
                        f.psw = psw;
                        f.aw = p[15:0];
                        if (w)
                            f.dw = p[31:16];
                    end else if (reg_ == 3'd6 || reg_ == 3'd7) begin
                        p = v35_div(reg_[0], w, w ? {f.dw, f.aw} : {16'd0, f.aw}, b, f.psw, psw,
                                    trap);
                        f.psw = psw;
                        if (!trap) begin
                            f.aw = p[15:0];
                            if (w)
                                f.dw = p[31:16];
                        end
                    end
                end
            end
        end
        // the stack pointer and CW
        if (c == V35_CLS_PUSH || c == V35_CLS_PUSH_MEM || c == V35_CLS_PUSH_IMM
                || c == V35_CLS_PUSH_SEG || c == V35_CLS_PREPARE || c == V35_CLS_CALL)
            f.sp = f.sp - (mut == 4'd9 ? 16'd4 : 16'd2);
        if (c == V35_CLS_PREPARE) begin         // BP := SP after BP's push, SP -= imm16
            f.bp = f.sp;
            f.sp = f.sp - {b2, b1};
        end
        if (c == V35_CLS_POP || c == V35_CLS_POP_MEM || c == V35_CLS_POP_SEG || c == V35_CLS_RET)
            f.sp = f.sp + 16'd2;
        if (c == V35_CLS_PUSH_R)
            f.sp = f.sp - 16'd16;               // eight words
        if (c == V35_CLS_POP_R)
            f.sp = f.sp + 16'd16;
        if (c == V35_CLS_DISPOSE)               // SP := BP, BP popped (the delivery's)
            f.sp = f.bp + 16'd2;
        if (c == V35_CLS_DBNZ)
            f.cw = f.cw - 16'd1;
        f.pfx = c == V35_CLS_PREFIX ? {1'b1, o[4:3]} : 3'd0;   // 26 DS1, 2E PS, 36 SS, 3E DS0
        v35_execute = f;
    endfunction

    // a delivered read cycle of the instruction's own request (the bus word; the byte lane
    // by the request's address and the cycle's half: an odd word's first cycle carries its low
    // byte on D15-8, the second its high byte on D7-0) into md; on the request's last cycle,
    // the read's effects: the register a load, POP, IN or XLAT writes, the ALU's result and
    // flags of a load-ALU, CMP / TEST, an RMW (its write datum), the multiplier and divider,
    // a segment load, POP R's register (by the read's index), DISPOSE's BP, RET's target.
    // count: the shift count; tgt_v / tgt: RET's target (a code offset, the stack's IP less
    // code_org); trap: a memory divide's error
    function automatic v35_rf_t v35_deliver(input v35_rf_t f0, input v35_fx_t x0,
                                            input logic w2, input logic odd, input logic io,
                                            input logic last, input logic [15:0] data,
                                            input logic [8:0] count, input logic [15:0] code_org,
                                            input logic [3:0] mut, output v35_fx_t x,
                                            output logic tgt_v, output logic [15:0] tgt,
                                            output logic trap);
        v35_rf_t f;
        logic [7:0] o, m;
        logic [2:0] reg_;
        logic [15:0] md, a, res, psw, imm;
        logic [31:0] p;
        logic w;
        f = f0;
        x = x0;
        tgt_v = 1'b0;
        tgt = 16'd0;
        trap = 1'b0;
        if (w2 && odd && !io) begin
            if (!last)
                x.md[7:0] = data[15:8];         // the first half: the low byte, odd
            else
                x.md[15:8] = data[7:0];
        end else if (w2) begin
            x.md = data;
        end else begin
            x.md = {8'd0, odd ? data[15:8] : data[7:0]};
        end
        if (!last)
            return f;
        md = x.md;
        o = x.code[47:40];
        m = x.code[39:32];
        reg_ = m[5:3];
        w = o[0];
        imm = v35_imm(x.code);
        a = v35_reg(f, reg_, w);
        if (o < 8'h40 && o[2:0] < 3'd4) begin   // the ALU's memory forms
            if (o[1]) begin
                res = v35_alu(o[5:3], w, a, md, f.psw, mut, psw);
                if (o[5:3] != 3'd7)
                    f = v35_set_reg(f, reg_, w, res);
            end else begin
                res = v35_alu(o[5:3], w, md, a, f.psw, mut, psw);
                x.wd = res;
            end
            f.psw = psw;
        end else if (o == 8'h84 || o == 8'h85) begin
            void'(v35_alu(3'd4, w, md, a, f.psw, mut, psw));
            f.psw = psw;
        end else if (o == 8'h86 || o == 8'h87 || o == 8'h8A || o == 8'h8B) begin
            f = v35_set_reg(f, reg_, w, md);
        end else if (o == 8'h8E) begin
            f = v35_sreg_set(f, reg_[1:0], md);
        end else if (o == 8'h8F) begin
            x.wd = md;                          // POP r/m: the stack's word written
        end else if (o >= 8'h80 && o <= 8'h83) begin
            res = v35_alu(reg_, w, md, imm, f.psw, mut, psw);
            x.wd = res;
            f.psw = psw;
        end else if (o == 8'hC0 || o == 8'hC1 || (o >= 8'hD0 && o <= 8'hD3)) begin
            x.wd = v35_shift(reg_, w, md, count, f.psw, psw);
            f.psw = psw;
        end else if (o == 8'hF6 || o == 8'hF7) begin
            case (reg_)
                3'd0, 3'd1: begin
                    void'(v35_alu(3'd4, w, md, imm, f.psw, mut, psw));
                    f.psw = psw;
                end
                3'd2: x.wd = ~md;
                3'd3: begin
                    x.wd = v35_alu(3'd5, w, 16'd0, md, f.psw, mut, psw);
                    f.psw = psw;
                end
                3'd4, 3'd5: begin
                    p = v35_mul(reg_[0], w, f.aw, md, f.psw, psw);
                    f.psw = psw;
                    f.aw = p[15:0];
                    if (w)
                        f.dw = p[31:16];
                end
                default: begin
                    p = v35_div(reg_[0], w, w ? {f.dw, f.aw} : {16'd0, f.aw}, md, f.psw, psw,
                                trap);
                    f.psw = psw;
                    if (!trap) begin
                        f.aw = p[15:0];
                        if (w)
                            f.dw = p[31:16];
                    end
                end
            endcase
        end else if (o == 8'hFE || o == 8'hFF) begin
            if (reg_ == 3'd0 || reg_ == 3'd1) begin   // INC / DEC: CY kept
                x.wd = v35_alu(reg_[0] ? 3'd5 : 3'd0, w, md, 16'd1, f.psw, mut, psw);
                psw[V35_PSW_CY] = f.psw[V35_PSW_CY];
                f.psw = psw;
            end else begin
                x.wd = md;                      // PUSH r/m: the operand's word pushed
            end
        end else if (o == 8'hA0 || o == 8'hA1 || o == 8'hE4 || o == 8'hE5 || o == 8'hEC
                     || o == 8'hED) begin
            f = v35_set_reg(f, 3'd0, w, md);    // MOV acc,[disp16]; IN
        end else if (o >= 8'h58 && o <= 8'h5F) begin
            f = v35_rf_set(f, o[2:0], md);
        end else if (o == 8'h07 || o == 8'h17 || o == 8'h1F) begin
            f = v35_sreg_set(f, o[4:3], md);
        end else if (o == 8'h61) begin          // POP R: IY IX BP (SP's discarded) BW DW CW AW
            if (x.rk != 3'd3)
                f = v35_rf_set(f, 3'd7 - x.rk, md);
        end else if (o == 8'hC9) begin
            f.bp = md;                          // DISPOSE
        end else if (o == 8'hC3) begin
            tgt_v = 1'b1;                       // RET
            tgt = md - code_org;
        end else if (o == 8'hD7) begin
            f = v35_rf_set8(f, 3'd0, md[7:0]);  // XLAT
        end
        x.rk = x.rk + 3'd1;
        v35_deliver = f;
    endfunction

    // the datum of an EU cycle issued (kind V35_RK_*, a word request, its address odd, the
    // first cycle of an odd word): an OUT's AW / AL at its issue (the model's: the ALU passes
    // the waiting OUT's data at its issue, io_interlock), PUSH R's register by the write's
    // index, else the context's write datum; on the cycle's lanes (an odd byte on D15-8, the
    // other lane 0; an odd word's first cycle its low byte on D15-8, the second its high byte
    // on D7-0). A read drives none (0)
    function automatic logic [15:0] v35_wdata(input v35_rf_t f, input v35_fx_t x,
                                              input logic [2:0] kind, input logic w2,
                                              input logic odd, input logic first,
                                              input logic [3:0] mut);
        logic [15:0] d;
        logic io;
        io = int'(kind) == V35_RK_IO_WRITE;
        if (!io && int'(kind) != V35_RK_WRITE)
            return 16'd0;
        if (io) begin
            d = f.aw;
        end else if (x.code[47:40] == 8'h60) begin
            case (x.wk)                         // PUSH R: AW CW DW BW SP (before) BP IX IY
                3'd4: d = f.sp + 16'd16;
                default: d = v35_rf_get(f, x.wk);
            endcase
        end else begin
            d = x.wd;
        end
        if (!io && mut == 4'd12)
            d = d ^ 16'h0001;
        if (w2 && odd && !io)
            v35_wdata = first ? {d[7:0], 8'd0} : {8'd0, d[15:8]};
        else if (w2)
            v35_wdata = d;
        else
            v35_wdata = odd ? {d[7:0], 8'd0} : {8'd0, d[7:0]};
    endfunction
endpackage

module v35_eu
    import v35_decoder_pkg::*;
    import v35_eu_pkg::*;
#(
    parameter int NQ = 16,                  // queue ops per phase (T and L; P)
    parameter int NXOP = 6,                 // the arbiter's touches per clock
    parameter int STATE_W = 879             // $bits(v35_st_t), checked below
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,                  // end of a model clock
    input  wire [STATE_W-1:0] init_state,   // the state at the end of the model's clock -1
    input  wire [15:0] code_org,            // (D2) the IP of the code's offset 0 (the code's
                                            // linear base is PS's + it: a target's, code_addr)
    input  wire        refresh_on,          // (C5) the chain runs the refresh controller

    // phase C
    input  wire        c_eu,                // an EU cycle was delivered (eu.complete) ...
    input  wire        c_read,              // ... a read
    input  wire [15:0] c_data,              // ... (D2) the word the bus delivered
    input  wire        fetch_done,          // queue.completed counted one (C or A)

    // the bus unit before the choice (T) and after it (P)
    input  wire [17:0] bus_t,
    input  wire [17:0] bus_p,
    // (C5) the early fetch run before the choice (T) and after it (P) (v35_early_t)
    input  wire [4:0]  early_t,
    input  wire [4:0]  early_p,

    // (D1) the code: the twelve bytes from code_addr (the code base + pc at the end of the
    // last clock, the byte there in [95:88]): the bytes of the clock's first and second start
    output wire [19:0]  code_addr,
    input  wire [95:0]  code_win,

    // the queue: its state before each op of a phase (and after the last), and each op's read
    input  wire [NQ:0][51:0] qv_tl,
    input  wire [NQ-1:0][7:0] rd_tl,
    input  wire [NQ:0][51:0] qv_p,
    input  wire [NQ-1:0][7:0] rd_p,

    // phase X: the arbiter's cycle and touches, the requests' setup counts at T and at P
    input  wire        x_valid,
    input  wire [2:0]  x_kind,
    input  wire        x_eu,                // the cycle is the EU's
    input  wire [NXOP-1:0][V35_XOP_W-1:0] xop,   // {code (V35_XOP_*), val}
    input  wire [2:0][6:0] counts_t,
    input  wire [2:0][6:0] counts_p,

    // phase E: queue.latch_in_t == t after its end_clock
    input  wire        q_latch_in,

    // the ops
    output logic [NQ-1:0][32:0] op_tl,
    output logic [4:0]  n_tl,               // ops in T and L ...
    output logic [4:0]  n_t,                // ... of which T's
    output logic [NQ-1:0][32:0] op_p,
    output logic [4:0]  n_p,
    output logic [1:0]  n_start,            // instructions started this clock
    // the data latch fills (the bus unit's wlatch_fill): T, X (the left-out write's slot), P
    output logic        wl_fill_t,
    output logic        wl_fill_x,
    output logic        wl_fill_p,
    // the data cycle the slot issued in X (its kind V35_K_*, address, width V35_BW_*)
    output logic        x_cyc,
    output logic [2:0]  x_cyc_kind,
    output logic [19:0] x_cyc_addr,
    output logic [1:0]  x_cyc_width,
    // the queue's inputs from the decoder and the EU: phase C's snapshot (retry_after), E's
    output logic [4:0]  qsnap_c,
    output logic [4:0]  qsnap_e,
    output logic        e_io,               // the EU runs an IN or OUT whose I/O is to come
    output logic        e_out,
    output reg          error,              // sticky: a case the RTL does not cover
    output logic [7:0]  err_code,           // this clock's (0: none)
    // for the arbiter (C4): the state after phase L and at the end of the clock (v35_st_t,
    // v35_eu_pkg), and the requests posted this clock in T/L (positions after L) and in P
    // (positions at the end): their setup counts start at 0
    output wire [STATE_W-1:0] state_l,
    output wire [STATE_W-1:0] state_e,
    output wire [2:0]   fresh_l,
    output wire [2:0]   fresh_p,
    // (D1) the register file's AW after the starts before phase X: an EU cycle's datum
    output wire [15:0]  x_data              // (D2) the datum of the EU cycle issued in X
`ifdef V35S_STATE_DUMP
    ,
    input  wire [3:0]   mutate,             // the bench's mutation tests (v35_operands)
    // (D1) the operand record of the clock's first and second start, and the register file
    // after each one's execute
    output wire [196:0] opr_a,
    output wire [196:0] opr_b,
    output wire [210:0] rfx_a,
    output wire [210:0] rfx_b,
    output wire [STATE_W-1:0] state_c,
    output wire [STATE_W-1:0] state_t,
    output wire [STATE_W-1:0] state_x,
    output wire [STATE_W-1:0] state_p,
    output wire [STATE_W-1:0] state_dump
`endif
);

    // ---- the queue's op codes (v35_queue.sv V35_QOP_*, rtl_vectors.QOPS)
    localparam logic [5:0] V35_EQ_TAKE = 6'd1;
    localparam logic [5:0] V35_EQ_COMMIT = 6'd2;
    localparam logic [5:0] V35_EQ_IRLOAD = 6'd3;
    localparam logic [5:0] V35_EQ_START = 6'd4;
    localparam logic [5:0] V35_EQ_FLUSH = 6'd5;
    localparam logic [5:0] V35_EQ_DISP = 6'd6;
    localparam logic [5:0] V35_EQ_HALT = 6'd7;
    localparam logic [5:0] V35_EQ_EVAL = 6'd8;
    localparam logic [5:0] V35_EQ_SHIFT_END = 6'd9;
    localparam logic [5:0] V35_EQ_RETRY_END = 6'd10;
    localparam logic [5:0] V35_EQ_RETRY_SET = 6'd11;
    localparam logic [5:0] V35_EQ_RERAISE = 6'd12;
    localparam logic [5:0] V35_EQ_SHIFT_SET = 6'd13;
    localparam logic [5:0] V35_EQ_SHIFT_HOLD = 6'd14;
    localparam logic [5:0] V35_EQ_DROP_RETRY = 6'd15;
    localparam logic [5:0] V35_EQ_WANT = 6'd16;
    localparam logic [5:0] V35_EQ_ASKED = 6'd17;
    localparam logic [5:0] V35_EQ_REQUESTING = 6'd18;
    localparam logic [5:0] V35_EQ_ROOM = 6'd19;
    localparam logic [5:0] V35_EQ_STORED = 6'd21;
    localparam logic [5:0] V35_EQ_AVAIL = 6'd22;
    localparam logic [5:0] V35_EQ_IO_HELD_SET = 6'd32;
    localparam logic [5:0] V35_EQ_NOP_HOLD = 6'd34;
    localparam logic [5:0] V35_EQ_GDISP = 6'd35;

    // ---- error codes (err_code)
    localparam logic [7:0] V35_EE_OPS = 8'd1;          // more than NQ queue ops in a phase
    localparam logic [7:0] V35_EE_LOOP = 8'd2;         // the tick's step loop did not settle
    localparam logic [7:0] V35_EE_DECODE = 8'd3;       // an opcode outside the catalog
    localparam logic [7:0] V35_EE_TMPL = 8'd4;         // no template for the format
    localparam logic [7:0] V35_EE_FMT = 8'd5;          // (C3; D1: the record is the RTL's) unused
    localparam logic [7:0] V35_EE_PC = 8'd6;           // the operand record is not at pc
    localparam logic [7:0] V35_EE_STEP = 8'd7;         // a step C3 does not build (flush, decide)
    localparam logic [7:0] V35_EE_SLOT = 8'd8;         // a request slot error
    localparam logic [7:0] V35_EE_XOP = 8'd9;          // an arbiter touch on an empty slot
    localparam logic [7:0] V35_EE_RF = 8'd10;          // (D1) unused (D2: the PSW and the stack
                                                       // read give BE / BNE and RET)
    localparam logic [7:0] V35_EE_FUNC = 8'd11;        // (D2) a form whose function is not built
    localparam logic [7:0] V35_EE_DIV = 8'd12;         // (D2) a divide error (its trap: later)


    if (FIT_RERAISE_OFF != 0) begin : g_reraise
        $error("v35_eu: refresh_reraise's tail rule is built for reraise_off = 0");
    end
    if ($bits(v35_st_t) != STATE_W) begin : g_state_width
        $error("v35_eu: the state is %0d bits, STATE_W %0d", $bits(v35_st_t), STATE_W);
    end
    if ($bits(v35_qview_t) != 52 || $bits(v35_bview_t) != 18 || V35_TMPL_W != 8
            || V35_FMT_W != 31 || V35_STEP_W != 38 || $bits(v35_opnd_t) != 197
            || $bits(v35_rf_t) != 211) begin : g_port_widths
        $error("v35_eu: the port widths no longer match the include");
    end

    // the clock's context: the ops, the phase, what happened this clock
    typedef struct packed {
        logic [NQ-1:0][32:0] ops_tl;
        logic [NQ-1:0][32:0] ops_p;
        logic [4:0]  n_tl;
        logic [4:0]  n_p;
        logic        p;             // in phase P
        logic [1:0]  starts;
        logic        wl_t;          // the EU filled the data latch in T ...
        logic        wl_x;          // ... in X (the slot) ...
        logic        wl_p;          // ... in P
        logic        retick;
        logic        held_abort;    // unit_hold held on the aborted cycle's end this clock
        logic [2:0]  fresh;         // requests posted this clock (their setup count is 0)
        logic [2:0]  fresh_p;       // ... of them, posted in phase P (C4: the arbiter's)
        logic        x_cyc;
        logic [2:0]  x_kind;
        logic [19:0] x_addr;
        logic [1:0]  x_width;
        logic [7:0]  err;
        v35_opnd_t [1:0] opr;       // (D1) the starts' operand records ...
        v35_rf_t [1:0] rfx;         // ... and the register file before each one's execute
        logic [15:0] x_data;        // (D2) the datum of the cycle issued in X
    } v35_ctx_t;

    logic [15:0] pc_r;                      // (D1) pc at the end of the last model clock

    // ------------------------------------------------ helpers

    function automatic logic is_cls(input logic [5:0] cls, input int c);
        is_cls = int'(cls) == c;
    endfunction

    function automatic logic [9:0] cost(input logic [5:0] cls, input int name);
        cost = 10'(v35_cost(int'(cls), name));
    endfunction

    function automatic logic has(input logic [5:0] cls, input int name);
        has = v35_cost_has(int'(cls), name);
    endfunction

    function automatic logic is_io(input logic [2:0] rk);
        is_io = int'(rk) == V35_RK_IO_READ || int'(rk) == V35_RK_IO_WRITE;
    endfunction

    function automatic logic bus_io(input v35_bview_t b);
        bus_io = b.kind == V35_K_IO_READ || b.kind == V35_K_IO_WRITE;
    endfunction

    function automatic void fail(inout v35_ctx_t c, input logic [7:0] code);
        if (c.err == 8'd0)
            c.err = code;
    endfunction

    function automatic logic imm16(input v35_st_t s);
        imm16 = is_cls(s.e.cls, V35_CLS_IMM) && s.e.imm_bytes == 2'd2;
    endfunction

    // the queue's state now (before the phase's next op)
    function automatic v35_qview_t qv(input v35_ctx_t c);
        if (c.p)
            qv = v35_qview_t'(qv_p[c.n_p]);
        else
            qv = v35_qview_t'(qv_tl[c.n_tl]);
    endfunction

    // one queue op; returns its read
    function automatic logic [7:0] q_op(inout v35_ctx_t c, input v35_st_t s,
                                        input logic [5:0] code, input logic a, input logic b,
                                        input logic [19:0] val);
        logic [32:0] w;
        w = {code, a, b, val, dec_snap(s.d, imm16(s))};
        q_op = 8'd0;
        if (!c.p) begin
            if (int'(c.n_tl) >= NQ) begin
                fail(c, V35_EE_OPS);
            end else begin
                c.ops_tl[c.n_tl] = w;
                q_op = rd_tl[c.n_tl];
                c.n_tl = c.n_tl + 5'd1;
            end
        end else begin
            if (int'(c.n_p) >= NQ) begin
                fail(c, V35_EE_OPS);
            end else begin
                c.ops_p[c.n_p] = w;
                q_op = rd_p[c.n_p];
                c.n_p = c.n_p + 5'd1;
            end
        end
    endfunction

    function automatic logic [19:0] off20(input int v);   // a signed offset in the op's val
        off20 = 20'(v);
    endfunction

    // a request step's address (symbolic sources, rtlgen.ADDR_SRC): (D2) the stack's in SS
    function automatic logic [19:0] eu_addr(input v35_eus_t e, input v35_rf_t f,
                                            input v35_stp_t s);
        case (int'(s.src))
            V35_SRC_EA: eu_addr = e.ea;
            V35_SRC_STACK_READ: eu_addr = {f.ss, 4'd0} + {4'd0, e.sr + 16'(2 * int'(s.src_i))};
            V35_SRC_STACK_WRITE: eu_addr = {f.ss, 4'd0} + {4'd0, e.sw - 16'(2 * int'(s.src_i))};
            V35_SRC_PORT: eu_addr = {4'd0, e.port};
            default: eu_addr = 20'd0;
        endcase
    endfunction

    // templates.ea_class, has_count, and the format word (rtlgen.FMT_FIELDS)
    function automatic logic [30:0] eu_fmt(input v35_op_t op, input logic [8:0] count,
                                           input logic taken, input logic refresh);
        logic [30:0] f;
        int mc;
        logic cnt;
        mc = int'(op.mode);
        if (mc == V35_EAC_BASE_INDEX_DISP && op.disp == 2'd2)
            mc = V35_EAC_BASE_INDEX_DISP16;         // ea_disp16=own
        if (mc == V35_EAC_DIRECT && op.modrm)
            mc = V35_EAC_BASE_DISP;                 // ea_direct=base_disp
        if (!op.ea_v)
            mc = V35_EAC_NONE;
        cnt = is_cls(op.cls, V35_CLS_SHIFT_IMM) || is_cls(op.cls, V35_CLS_SHIFT_CL) || op.shift;
        f = '0;
        f[V35_FF_CLS +: V35_FF_CLS_W] = op.cls;
        f[V35_FF_LENGTH +: V35_FF_LENGTH_W] = op.length;
        f[V35_FF_IMM_BYTES +: V35_FF_IMM_BYTES_W] = op.imm_bytes;
        f[V35_FF_HAS_EA] = op.ea_v;
        f[V35_FF_MODRM] = op.modrm;
        f[V35_FF_DISP +: V35_FF_DISP_W] = op.disp;
        f[V35_FF_WIDTH +: V35_FF_WIDTH_W] = op.width;
        f[V35_FF_EA_CLASS +: V35_FF_EA_CLASS_W] = 3'(mc);
        f[V35_FF_SIGNED] = op.signed_;
        f[V35_FF_GROUP] = op.group;
        f[V35_FF_FIXED_ALU] = op.fixed_alu;
        f[V35_FF_SHIFT] = op.shift;
        f[V35_FF_CL] = op.opcode == 8'hD2 || op.opcode == 8'hD3;
        f[V35_FF_NOWRITE] = op.nowrite;
        f[V35_FF_SWAP] = op.swap;
        f[V35_FF_COND] = op.cond;
        f[V35_FF_TAKEN] = taken;
        f[V35_FF_COUNT_ZERO] = cnt && count == 9'd0;
        f[V35_FF_REFRESH] = refresh;                // refresh_eu=hold: refresh_hold_steps
        eu_fmt = f;
    endfunction

    // ------------------------------------------------ EU methods

    // _interlocked: cls is one of the register-only classes of the mode (INTERLOCK; lea_form,
    // branch_reg, reg_div)
    function automatic logic eu_interlocked(input logic [5:0] cls, input logic pfx);
        int c;
        c = int'(cls);
        eu_interlocked = c == V35_CLS_REG || c == V35_CLS_IMM || c == V35_CLS_SHIFT_IMM
                         || c == V35_CLS_SHIFT_CL || c == V35_CLS_MUL
                         || (pfx && c == V35_CLS_PREFIX) || c == V35_CLS_LEA
                         || c == V35_CLS_BRANCH_SHORT || c == V35_CLS_BRANCH_NEAR
                         || c == V35_CLS_DBNZ || c == V35_CLS_CALL || c == V35_CLS_RET
                         || c == V35_CLS_DIV;
    endfunction

    // a request still to issue: an I/O one not a port form's (dw_port)
    function automatic logic dw_req(input v35_req_t r);
        dw_req = r.valid && r.ncyc != 2'd0 && r.issued == 2'd0 && is_io(r.kind) && !r.port;
    endfunction

    // the clock's start: the offsets and ages move on a clock
    function automatic v35_st_t eu_begin(input v35_st_t r, input v35_bview_t b,
                                         input logic fdone);
        v35_st_t s;
        s = r;
        s.d = dec_begin(r.d);
        s.e.res_past = r.e.res == '0;           // resume < t
        if (s.e.res != '0) s.e.res = s.e.res - 1'b1;
        // (C5) the refresh's stamps
        if ($signed(r.e.ce_off) >= 0) s.e.ce_off = r.e.ce_off - 1'b1;   // clipped at -1
        s.e.cs_now = 1'b0;
        s.e.hf_now = 1'b0;
        if (r.e.hv) begin
            if (r.e.h_off == '0) s.e.h_past = 1'b1;
            else s.e.h_off = r.e.h_off - 1'b1;
        end
        if (r.e.hd_v) begin
            if (r.e.hd_off == '0) s.e.hd_past = 1'b1;
            else s.e.hd_off = r.e.hd_off - 1'b1;
        end
        s.e.halt_prev = r.e.halt_now;
        s.e.pr_now = 1'b0;
        if (s.e.df_off != '0) s.e.df_off = s.e.df_off - 1'b1;
        if (s.e.wbu != '0) s.e.wbu = s.e.wbu - 1'b1;
        if (s.e.done_v && s.e.done_age != 2'd3) s.e.done_age = s.e.done_age + 1'b1;
        if (s.e.start_age != 4'd15) s.e.start_age = s.e.start_age + 1'b1;
        s.e.fs_now = 1'b0;
        s.e.halt_now = 1'b0;
        if ($signed(s.e.sa_off) > -16) s.e.sa_off = s.e.sa_off - 1'b1;
        if (s.e.exec_v) begin
            if (s.e.exec_age != 2'd3) s.e.exec_age = s.e.exec_age + 1'b1;
            s.e.exec_par = !s.e.exec_par;
        end
        if (b.kind != V35_K_FETCH)
            s.e.hd_fetch = 1'b0;                // the fetch that held it has left the bus
        if (!s.e.lu_held && s.e.lu_off != '0) s.e.lu_off = s.e.lu_off - 1'b1;
        s.e.latch_wait_now = 1'b0;
        s.e.port_now = 1'b0;
        s.e.port_held = 3'd0;
        for (int i = 0; i < 3; i++) begin
            if (s.r[i].nb_off != '0) s.r[i].nb_off = s.r[i].nb_off - 1'b1;
            if (s.r[i].da_v) begin
                if (s.r[i].da_off == '0)
                    s.r[i].da_past = 1'b1;
                else
                    s.r[i].da_off = s.r[i].da_off - 1'b1;
            end
        end
        // queue.completed counted a fetch: the take sync owes one fewer
        if (fdone && s.e.sync == SYNC_COUNT && s.e.owed != 2'd0)
            s.e.owed = s.e.owed - 2'd1;
        eu_begin = s;
    endfunction

    // complete: a read cycle of the current request ended at t-1 (data_ready=0); (D2) its
    // datum into the instruction's context and, on the request's last cycle, the read's
    // effects (v35_deliver; RET's target into tgt)
    function automatic void eu_complete(inout v35_st_t s, inout v35_ctx_t c);
        int i;
        logic tv, tr;
        logic [15:0] tg;
        v35_fx_t x;
        i = s.e.own != 2'd0 ? int'(s.e.own) - 1 : 0;
        if (s.r[i].valid && s.r[i].issued != 2'd0) begin
            s.f = v35_deliver(s.f, s.x, s.r[i].w2, s.r[i].addr[0], is_io(s.r[i].kind),
                              s.r[i].ncyc == 2'd0, c_data, s.e.count, code_org, mut, x, tv, tg,
                              tr);
            s.x = x;
            if (tv)
                s.e.tgt = tg;
            if (tr)
                fail(c, V35_EE_DIV);
        end
        if (s.r[i].valid && s.r[i].ncyc == 2'd0 && s.r[i].issued != 2'd0) begin
            s.r[i].da_v = 1'b1;
            s.r[i].da_off = 3'd0;
            s.r[i].da_past = 1'b0;
        end
    endfunction

    // _retire
    function automatic void eu_retire(inout v35_st_t s);
        if (s.e.own == 2'd1)
            s.r[0] = '0;                        // the slot was the instruction's own
        s.e.own = 2'd0;
    endfunction

    // _promote: the detached request in the slot has been issued; the next one moves in
    function automatic void eu_promote(inout v35_st_t s, inout v35_ctx_t c);
        s.r[0] = s.r[1];
        s.r[1] = s.r[2];
        s.r[2] = '0;
        if (s.r[0].valid) begin
            if (!is_io(s.r[0].kind))
                s.r[0].moved = 1'b1;            // slot_fetch
            else if (!s.r[0].port)
                s.r[0].dw_moved = 1'b1;         // dw_slot=behind
        end
        if (s.e.own != 2'd0)
            s.e.own = s.e.own - 2'd1;           // own is never the issued detached request
        s.e.port_held = s.e.port_held >> 1;
        c.fresh = c.fresh >> 1;
        c.fresh_p = c.fresh_p >> 1;
    endfunction

    // _post: the request record of a data step
    function automatic v35_req_t eu_post(input v35_st_t s, input v35_stp_t st);
        v35_req_t r;
        logic io;
        int setup, fr;
        r = '0;
        io = is_io(st.kind);
        setup = int'(st.n);
        r.valid = 1'b1;
        r.kind = st.kind;
        r.addr = eu_addr(s.e, s.f, st);
        r.w2 = st.width == 2'd2;
        r.ncyc = (int'(st.kind) == V35_RK_NOWRITE) ? 2'd1
                 : (r.w2 && r.addr[0] && !io) ? 2'd2 : 2'd1;   // odd_split=atomic
        r.setup = 7'(setup);
        if (st.has_free) begin
            r.free_v = 1'b1;
            r.free = st.free;
        end else if (has(s.e.cls, V35_CN_SETUP_FREE)) begin
            r.free_v = 1'b1;
            r.free = 5'(cost(s.e.cls, V35_CN_SETUP_FREE));
        end
        r.lead = io ? 2'(cost(s.e.cls, V35_CN_LEAD)) : 2'd0;
        r.nowait = io;                          // io_count=nowait
        r.cls = s.e.cls;
        r.free_bus = st.grp;                    // grp_free_bus
        r.whole = st.whole;
        fr = int'(r.free);
        r.free_orig = (r.free_v && r.free != '0) ? 5'(fr < setup ? fr : setup) : 5'd0;
        r.imm1 = (int'(st.kind) == V35_RK_READ || int'(st.kind) == V35_RK_WRITE)
                 && s.e.imm_bytes == 2'd1 && s.e.mem && s.e.floor_n != '0;
        if ((int'(st.kind) == V35_RK_WRITE || int'(st.kind) == V35_RK_NOWRITE)
                && is_cls(s.e.cls, V35_CLS_RMW) && !st.grp)   // rmw_alu=through
            r.through = 7'(setup - int'(s.e.route) - 1 > 0 ? setup - int'(s.e.route) - 1 : 0);
        eu_post = r;
    endfunction

    // _submit: post a request into the slot, or behind a detached one waiting there; returns
    // the position + 1 (the `own` encoding), 0 when the slot and its queue are full
    function automatic logic [1:0] eu_submit(inout v35_st_t s, inout v35_ctx_t c,
                                             input v35_stp_t st, input logic detached);
        v35_req_t r;
        v35_qview_t q;
        int nb;
        r = eu_post(s, st);
        if (s.e.rmw_cl && int'(st.kind) == V35_RK_READ && refresh_on)
            r.grpcl = 2'(cost(6'(V35_CLS_RMW), V35_CN_GRPCL));   // refresh_grpcl=step
        if (s.e.df_v && !is_io(st.kind)) begin  // disp_floor
            if (s.e.df_off > 3'(r.nb_off)) r.nb_off = {1'b0, s.e.df_off};
            s.e.df_v = 1'b0;
            s.e.df_off = '0;
        end
        if (s.e.floor_n != '0 && !is_io(st.kind)) begin   // imm_count=start
            nb = int'(s.e.floor_n) - int'(s.e.start_age);
            if (nb > int'(r.nb_off)) r.nb_off = 4'(nb);
            s.e.floor_n = '0;
        end
        q = qv(c);
        if ((s.e.unit || s.e.fixed) && q.ab_this && !s.e.unit_early && r.setup != '0
                && st.grp && r.free_v && 7'(r.free) < r.setup) begin   // abort_unit, abort_fixed
            r.setup = r.setup - 1'b1;
            s.e.unit_early = 1'b1;
        end
        r.detached = detached;
        if (r.free_bus && s.e.mem && s.e.disp == 2'd2 && is_cls(s.e.cls, V35_CLS_RMW)
                && s.e.imm_bytes == '0
                && (int'(st.kind) == V35_RK_READ || int'(st.kind) == V35_RK_NOWRITE))
            r.gdisp = 1'b1;                     // grp_disp=hold
        if (detached && int'(st.kind) == V35_RK_IO_WRITE)
            s.e.lu_held = 1'b1;                 // latch_until = inf
        eu_submit = 2'd0;
        if (!s.r[0].valid) begin
            s.r[0] = r;
            c.fresh[0] = 1'b1;
            c.fresh_p[0] = c.p;
            eu_submit = 2'd1;
        end else if (s.r[0].detached || s.r[1].valid) begin
            if (!s.r[1].valid) begin
                s.r[1] = r;
                c.fresh[1] = 1'b1;
                c.fresh_p[1] = c.p;
                eu_submit = 2'd2;
            end else if (!s.r[2].valid) begin
                s.r[2] = r;
                c.fresh[2] = 1'b1;
                c.fresh_p[2] = c.p;
                eu_submit = 2'd3;
            end else begin
                fail(c, V35_EE_SLOT);
            end
        end
    endfunction

    // _floor (disp_floor=posted): the next data request no earlier than t + at
    function automatic void eu_floor(inout v35_st_t s, input logic [2:0] at);
        s.e.df_v = 1'b1;
        s.e.df_off = at;
        if (s.r[0].valid && s.r[0].ncyc != '0 && s.r[0].issued == '0 && !s.r[0].detached
                && !is_io(s.r[0].kind)) begin
            if ({1'b0, at} > s.r[0].nb_off) s.r[0].nb_off = {1'b0, at};
            s.r[0].floor_hold = 1'b1;
            s.e.df_v = 1'b0;
            s.e.df_off = '0;
        end
    endfunction

    // _data_next (post_on_take=nomodrm)
    function automatic logic eu_data_next(input v35_st_t s);
        v35_stp_t st;
        int n;
        eu_data_next = 1'b0;
        if (!s.e.modrm) begin
            n = eu_nsteps(s.e);
            for (int j = 0; j < 16; j++) begin
                if (int'(s.e.k) + j < n) begin
                    st = eu_step(s.e, int'(s.e.k) + j);
                    if (!(int'(st.op) == V35_SOP_CLOCKS && st.n == '0)) begin
                        eu_data_next = int'(st.op) == V35_SOP_DATA;
                        break;
                    end
                end
            end
        end
    endfunction

    // (C5) the early fetch run as the phase reads it (T: before the choice, P: after it)
    function automatic v35_early_t ev_now(input v35_ctx_t c);
        ev_now = v35_early_t'(c.p ? early_p : early_t);
    endfunction

    // EU._early (refresh_sync=run): t is one of the last two clocks of a fetch of the run (the
    // cycle on the bus is bus.early)
    function automatic logic eu_early(input v35_ctx_t c, input v35_bview_t b);
        eu_early = ev_now(c).cur && b.kind != V35_K_NONE && int'(b.pos) + 2 >= int'(b.len);
    endfunction

    // _late_fetch: a fetch past its second clock
    function automatic logic eu_late_fetch(input v35_bview_t b);
        eu_late_fetch = b.kind == V35_K_FETCH && b.pos >= 3'd2;
    endfunction

    // ------------------------------------------------ decoder methods with the queue port

    // Decoder.take (bytes_per_clock=1; wide: disp16=word, two bytes on a clock)
    function automatic logic [2:0] dec_take(inout v35_st_t s, inout v35_ctx_t c,
                                            input logic [2:0] n, input logic wide);
        logic [7:0] avail;
        logic [2:0] k;
        logic mate, one;
        avail = q_op(c, s, V35_EQ_AVAIL, 1'b0, 1'b0, 20'd0);
        k = n;
        if (!wide && k > 3'd1) k = 3'd1;
        if (wide && k > 3'd2) k = 3'd2;
        if ({5'd0, k} > avail) k = avail[2:0];
        for (int i = 0; i < 2; i++) begin
            if (i < int'(k)) begin
                s.d = dec_take_byte(s.d, k, mate, one);
                void'(q_op(c, s, V35_EQ_TAKE, one, mate, 20'd0));
            end
        end
        s.d = dec_take_end(s.d, k);
        dec_take = k;
    endfunction

    function automatic void dec_commit(inout v35_st_t s, inout v35_ctx_t c);
        void'(q_op(c, s, V35_EQ_COMMIT, 1'b0, 1'b0, 20'd0));
    endfunction

    function automatic logic dec_loads_after(inout v35_st_t s, inout v35_ctx_t c,
                                             input logic [2:0] n);
        logic [7:0] avail;
        dec_loads_after = 1'b0;
        if (dec_loads_after_cond(s.d, n)) begin
            avail = q_op(c, s, V35_EQ_AVAIL, 1'b0, 1'b0, 20'd0);
            dec_loads_after = avail > {5'd0, n};
        end
    endfunction

    function automatic void dec_load_ir(inout v35_st_t s, inout v35_ctx_t c);
        logic [7:0] avail;
        if (dec_load_cond(s.d)) begin
            avail = q_op(c, s, V35_EQ_AVAIL, 1'b0, 1'b0, 20'd0);
            if (avail != 8'd0 && !s.d.ir_hold) begin
                void'(q_op(c, s, V35_EQ_IRLOAD, 1'b0, 1'b0, 20'd0));
                s.d = dec_load(s.d);
            end
        end
    endfunction

    // _late_read: the take is the last operand byte with the IR loading on t too
    function automatic logic eu_late_read(inout v35_st_t s, inout v35_ctx_t c,
                                          input v35_bview_t b);
        eu_late_read = 1'b0;
        if (eu_late_fetch(b) && s.e.left == 3'd1)
            eu_late_read = dec_loads_after(s, c, 3'd1);
    endfunction

    // ------------------------------------------------ _start

    // (D1) the instruction's bytes at pc: the code window's (code_addr: pc at the end of the
    // last clock; a start in the clock moves pc by its length, at most 6, and a flush, which
    // moves it anywhere, empties the IR, so no start follows it in the clock). ok: pc is in it
    function automatic logic [47:0] eu_code(input v35_st_t s, output logic ok);
        logic [15:0] off;
        off = s.e.pc - pc_r;
        ok = off <= 16'd6;
        eu_code = ok ? code_win[95 - 8 * int'(off[2:0]) -: 48] : 48'h909090909090;
    endfunction

    function automatic logic eu_start(inout v35_st_t s, inout v35_ctx_t c,
                                      input v35_bview_t b);
        v35_opnd_t opr;
        v35_op_t op;
        v35_qview_t q;
        v35_st_t s2;
        logic regonly, ilk, portf, dw0, dw1, dw2, cok, bad;
        logic [7:0] st, room;
        logic [30:0] fmt;
        logic [47:0] code;
        int tm, wbu, fl;
        eu_start = 1'b0;
        code = eu_code(s, cok);
        if (s.e.pr_cand && !s.e.pr_now) begin
            // pop_refresh=stall: a refresh started inside POP PSW's clocks after its read
            // stalls them by its length less 2
            if ($signed(s.e.sa_off) == -16)
                fail(c, V35_EE_SLOT);           // start_at too far behind to count from
            s.e.sa_off = s.e.sa_off + 5'(s.e.pr_len) - 5'd2;
            s.e.pr_cand = 1'b0;
        end
        if ($signed(s.e.sa_off) > 0)
            return 1'b0;                        // prelude_anchor=pop: POP PSW still runs
        if (s.e.refill) begin                   // refill_start=full_io
            q = qv(c);
            if (q.inflight)
                return 1'b0;
            st = q_op(c, s, V35_EQ_WANT, 1'b0, 1'b0, 20'd0);
            if (st[0])
                return 1'b0;
            q = qv(c);
            op = eu_decode(code);
            if (s.d.ir_v && !cok)
                fail(c, V35_EE_PC);             // the instruction is not in the code window
            if (q.arrived_now && b.flen3 && s.d.ir_v
                    && (is_cls(op.cls, V35_CLS_IN) || is_cls(op.cls, V35_CLS_OUT)))
                return 1'b0;                    // an IN / OUT not on a 3-clock fetch's delivery
            s.e.refill = 1'b0;
        end
        if (b.finf && !eu_early(c, b))
            return 1'b0;                        // start_sync=b2b_modrm
        q = qv(c);
        if (ev_now(c).ep && q.b2b_now)
            return 1'b0;                        // refresh_sync=run: the run's next fetch
        if (!s.d.ir_v)
            return 1'b0;
        op = eu_decode(code);
        if (!op.ok) begin
            fail(c, V35_EE_DECODE);
            return 1'b0;
        end
        if (!cok)
            fail(c, V35_EE_PC);                 // the instruction is not in the code window
        if (op.dbit_v && !op.dbit && is_cls(op.cls, V35_CLS_LOAD_ALU) && op.ea_v)
            op.nowrite = 1'b1;                  // dest_route=slot: CMP r/m,reg
        if (op.nowrite)                         // grp_read: the group's RMW class
            op.cls = 6'(op.imm_bytes != '0 ? V35_CLS_RMW_IMM : V35_CLS_RMW);
        q = qv(c);
        if (op.modrm && q.b2b_now)
            return 1'b0;                        // a ModR/M form waits out the b2b fetch
        if (op.modrm && b.finf && eu_early(c, b))
            return 1'b0;                        // refresh_run_modrm=wait
        regonly = !op.ea_v || !op.bus;          // lea_form=reg
        ilk = eu_interlocked(op.cls, 1'b1);     // io_interlock=reg_pfx
        if (ilk && regonly && s.r[0].valid && s.r[0].detached && s.r[0].ncyc != '0
                && int'(s.r[0].kind) == V35_RK_IO_WRITE)
            return 1'b0;
        if (ilk && regonly && b.kind == V35_K_IO_WRITE && b.pos != 3'd0)
            return 1'b0;                        // io_busy_start=issue
        portf = (is_cls(op.cls, V35_CLS_OUT) || is_cls(op.cls, V35_CLS_IN)) && op.length > 3'd1;
        if (portf) begin                        // dw_port=hold
            dw0 = dw_req(s.r[0]);
            dw1 = dw_req(s.r[1]);
            dw2 = dw_req(s.r[2]);
            if ((dw0 || dw1 || dw2) && (dw1 || dw2 || bus_io(b)))
                return 1'b0;
            if (b.wl || (c.p ? c.wl_p : c.wl_t)) begin   // wlatch_cls=port
                s.e.latch_wait_now = 1'b1;
                return 1'b0;
            end
        end
        if ((portf || op.modrm) && q.rq_valid && q.rq_age != '0 && !q.inflight && b.free) begin
            st = q_op(c, s, V35_EQ_STORED, 1'b0, 1'b0, 20'd0);   // io_older=io_modrm
            if (st < 8'(FIT_IO_B2B_Q))
                return 1'b0;
        end
        q = qv(c);
        if (op.ea_v && op.modrm && op.imm_bytes != '0 && b.free && !q.inflight && b.fprev) begin
            st = q_op(c, s, V35_EQ_STORED, 1'b0, 1'b0, 20'd0);   // imm_start=wait
            if (st <= 8'(FIT_IO_B2B_Q)) begin
                s2 = s;
                s2.d.ir_v = 1'b0;               // the IR it empties counted as room
                room = q_op(c, s2, V35_EQ_ROOM, 1'b0, 1'b0, 20'd0);
                if ($signed(room) >= 8'sd2)
                    return 1'b0;
            end
        end
        q = qv(c);
        if (!op.modrm && q.b2b_now) begin       // io_b2b=all
            st = q_op(c, s, V35_EQ_STORED, 1'b0, 1'b0, 20'd0);
            if (st < 8'(FIT_IO_B2B_Q))
                return 1'b0;
        end
        // the start: (D1) the operand record from the register file (templates.decode)
        opr = v35_operands(s.f, code, s.e.pc, op, mut, bad);
        if (bad)
            fail(c, V35_EE_FUNC);
        wbu = int'(s.e.wb) - (s.e.done_v ? int'(s.e.done_age) : 0);   // wb_from=end
        s.e.wbu = 2'(wbu > 0 ? wbu : 0);
        s.e.done_v = 1'b0;
        s.e.done_age = '0;
        s.e.wb = 2'((op.ea_v && has(op.cls, V35_CN_MWB)) ? cost(op.cls, V35_CN_MWB)
                                                          : cost(op.cls, V35_CN_WB));
        s.e.route = (op.ea_v && op.swap) ? 2'(cost(op.cls, V35_CN_DCLK)) : 2'd0;   // dest_route=slot
        s.e.prev_cls = s.e.cls;                 // refresh_beat_b2b
        s.e.cls = op.cls;
        s.e.grp_form = op.group;
        // the SFR store's value: DS1's MOV byte [0FFE1h],imm8, its last byte (eu.sfr)
        s.e.sfr = ((is_cls(op.cls, V35_CLS_STORE) || is_cls(op.cls, V35_CLS_STORE_IMM)) && op.ea_v
                   && opr.ea >= V35_SFR_PAGE) ? opr.code[47 - 8 * (int'(op.length) - 1) -: 8] : 8'd0;
        s.e.rmw = op.ea_v && op.shift && is_cls(op.cls, V35_CLS_RMW);   // refresh_rmw_loop
        s.e.rmw_cl = s.e.rmw && (op.opcode == 8'hD2 || op.opcode == 8'hD3);   // shift_cl_mem=count
        s.e.unit = op.ea_v && (op.shift || is_cls(op.cls, V35_CLS_MUL)
                               || is_cls(op.cls, V35_CLS_DIV) || is_cls(op.cls, V35_CLS_PUSH_MEM));
        s.e.unit_early = 1'b0;
        s.e.exec_v = 1'b0;
        s.e.exec_age = '0;
        s.e.exec_par = 1'b0;
        s.e.reg_early = 1'b0;
        s.e.shift_latched = 1'b0;
        s.e.modrm = op.modrm;
        s.e.mem = op.ea_v && op.bus;
        s.e.op_len = op.length;
        s.e.imm_bytes = op.imm_bytes;
        s.e.taken = '0;
        s.e.disp = op.disp;
        s.e.df_v = 1'b0;
        s.e.df_off = '0;
        fl = 0;
        if (op.ea_v && op.imm_bytes != '0 && has(op.cls, V35_CN_ISTART))
            fl = int'(cost(op.cls, V35_CN_ISTART)) + int'(op.imm_bytes);   // imm_count=start
        s.e.fixed = op.fixed_alu && op.ea_v;    // abort_fixed
        if (fl != 0 && op.group && op.fixed_alu)
            fl = fl + int'(cost(6'(V35_CLS_LOAD_ALU), V35_CN_FGRP));   // fixed_floor
        s.e.floor_n = 4'(fl);
        s.e.start_age = '0;
        s.e.fs_this = s.e.fs_now;
        s.d = dec_start(s.d, op.length, 2'(cost(op.cls, V35_CN_NX)), op.modrm,
                        op.imm_bytes != '0 && !op.ea_v);
        s.d.ir_hold = op.ea_v && op.modrm && op.disp != '0 && op.bus;   // ir_load=disp_data
        void'(q_op(c, s, V35_EQ_START, opr.taken, 1'b0,
                   opr.taken ? 20'(cost(op.cls, V35_CN_HOLD)) : 20'd0));   // flush_hold=start
        s.e.wbs = v35_wbsync(int'(op.cls), op.length == 3'd1);
        fmt = eu_fmt(op, opr.count, opr.taken, refresh_on);
        tm = v35_tmpl_sel(fmt);
        if (tm < 0) begin
            fail(c, V35_EE_TMPL);
            tm = 0;
        end
        opr.fmt = fmt;
        opr.tmpl = 8'(tm);
        s.e.tmpl = 8'(tm);
        s.e.count = opr.count;
        s.e.ins = 1'b0;
        s.e.ins_at = '0;
        s.e.k = '0;
        s.e.ea = opr.ea;
        s.e.port = opr.port;
        s.e.sr = opr.sr;
        s.e.sw = opr.sw;
        s.e.tgt = opr.target;
        s.e.pc = s.e.pc + {13'd0, op.length};
        // (D2) the instruction's function at its start (its data's: v35_deliver, v35_wdata)
        if (c.starts < 2'd2) begin
            c.opr[c.starts[0]] = opr;
            c.rfx[c.starts[0]] = s.f;
        end
        s.f = v35_execute(s.f, code, op, opr, code_org, mut, s.x, bad);
        if (bad)
            fail(c, V35_EE_DIV);
        c.starts = c.starts + 2'd1;
        return 1'b1;
    endfunction

    // _flush: the queue and the IR emptied, the fetch pointer at the target, the EU's next
    // instruction the target's
    function automatic void eu_flush(inout v35_st_t s, inout v35_ctx_t c);
        logic [19:0] a;
        a = {s.f.ps, 4'd0} + {4'd0, code_org + s.e.tgt};
        void'(q_op(c, s, V35_EQ_FLUSH, 1'b0, 1'b0, a));
        s.d.ir_v = 1'b0;
        s.d.ir_addr = 20'd0;
        s.d.taddr = a;
        s.d.mate_next = 1'b0;
        s.e.pc = s.e.tgt;
        s.e.refill = 1'b1;
    endfunction

    // _unit_hold: a register shift, multiply or divide in its exec clocks waits at a
    // micro-boundary while a fetch, or an aborted cycle, is past its second clock
    function automatic logic eu_unit_hold(inout v35_st_t s, inout v35_ctx_t c,
                                          input v35_bview_t b);
        v35_qview_t q;
        int hp, left;
        logic fetch;
        eu_unit_hold = 1'b0;
        hp = int'(cost(s.e.cls, V35_CN_HPHASE));
        if (int'(s.e.exec_age) < hp || (s.e.exec_par ^ hp[0]))
            return 1'b0;
        q = qv(c);
        fetch = b.kind == V35_K_FETCH && b.pos >= 3'd2;
        if (fetch) begin
            if (s.e.hd_fetch)
                return 1'b0;                    // this cycle held it already
            left = int'(b.len) - 1 - int'(b.pos);
            s.e.hd_fetch = 1'b1;
        end else if (q.ab_valid && q.ab_left == '0) begin
            if (c.held_abort)
                return 1'b0;
            left = 0;
            c.held_abort = 1'b1;
            s.e.hd_fetch = 1'b0;
        end else begin
            return 1'b0;
        end
        if (eu_res_ce(s.e))                     // the clocks step's end moves with it
            s.e.ce_off = s.e.ce_off + 11'(left + 1);
        s.e.res = s.e.res + 10'(left + 1);      // end + 1 - t
        s.e.res_past = 1'b0;
        return 1'b1;
    endfunction

    // _io_drop (io_take=unit)
    function automatic logic eu_io_drop(inout v35_st_t s, inout v35_ctx_t c,
                                        input v35_bview_t b);
        v35_qview_t q;
        logic loop;
        eu_io_drop = 1'b0;
        if (s.d.need != '0 || s.e.taken == '0)
            return 1'b0;
        if (s.e.mem && !(s.e.unit && (is_cls(s.e.cls, V35_CLS_MUL) || is_cls(s.e.cls, V35_CLS_DIV))))
            return 1'b0;
        q = qv(c);
        if (!(s.e.start_age == '0 && bus_io(b) && b.pos == 3'd0 && q.arrived_now && q.latched
              && eu_interlocked(s.e.cls, 1'b0)))
            return 1'b0;
        loop = is_cls(s.e.cls, V35_CLS_SHIFT_CL) || is_cls(s.e.cls, V35_CLS_SHIFT_IMM)
               || is_cls(s.e.cls, V35_CLS_MUL) || is_cls(s.e.cls, V35_CLS_DIV);
        void'(q_op(c, s, V35_EQ_DROP_RETRY, loop, 1'b1, 20'd0));   // abort_unit=loop
        return 1'b1;
    endfunction

    // the ready test of _port_take's port_ready=issue (count >= setup: the arbiter's count)
    function automatic logic eu_ready(input v35_st_t s, input v35_ctx_t c, input int i);
        logic [6:0] n;
        n = c.fresh[i] ? 7'd0 : (c.p ? counts_p[i] : counts_t[i]);
        eu_ready = n >= s.r[i].setup;
    endfunction

    // _port_take: a port byte taken (port_latch=relatch, port_landed, port_ready=issue)
    function automatic void eu_port_take(inout v35_st_t s, inout v35_ctx_t c,
                                         input v35_stp_t st, input v35_bview_t b);
        v35_qview_t q;
        logic [2:0] held;
        logic late;
        logic [1:0] idx;
        int nb;
        q = qv(c);
        late = q.arrived_now && q.latched;
        held = 3'd0;
        for (int i = 0; i < 3; i++) begin
            if (s.r[i].valid && eu_ready(s, c, i) && s.r[i].nb_off == '0
                    && b.kind == V35_K_NONE) begin
                // it issues on this clock
            end else if (s.r[i].valid && s.r[i].detached && s.r[i].ncyc != '0
                         && s.r[i].issued == '0) begin
                nb = int'(late) + int'(cost(s.r[i].cls, V35_CN_RELATCH));
                if (nb > int'(s.r[i].nb_off)) s.r[i].nb_off = 4'(nb);
                held[i] = 1'b1;
            end
        end
        s.e.port_now = 1'b1;
        s.e.port_held = held;
        if (s.r[0].valid && s.r[0].detached && s.r[0].ncyc != '0) begin
            s.e.ins = 1'b1;                     // the slot, then the relatched post
            s.e.ins_at = s.e.k;
            return;
        end
        idx = eu_submit(s, c, st, st.detached);
        if (idx != 2'd0)
            s.r[int'(idx) - 1].port = 1'b1;
        if (!st.detached)
            s.e.own = idx;
    endfunction

    // ------------------------------------------------ tick

    function automatic void eu_tick(inout v35_st_t s, inout v35_ctx_t c, input v35_bview_t b);
        v35_qview_t q;
        v35_stp_t st, pst;
        logic [7:0] a, room;
        logic [2:0] n, bytes;
        logic last, wide, io_drop, asked, held, lapse, early;
        int ns, nb;
        q = qv(c);
        if (q.sh_valid && $signed(q.sh_off) <= 0)
            void'(q_op(c, s, V35_EQ_SHIFT_END, 1'b0, 1'b0, 20'd0));   // count_latch's end
        q = qv(c);
        if (q.rt_valid && $signed(q.rt_off) <= 0)
            void'(q_op(c, s, V35_EQ_RETRY_END, 1'b0, 1'b0, 20'd0));   // abort_unit=loop's exit
        // refresh_eu=hold: the EU does not pass a micro-boundary while a refresh it let
        // through is on the bus; what would happen on t moves one clock on
        if (s.e.hv) begin
            if (s.e.h_past) begin
                s.e.hv = 1'b0;                  // hold_end = None
                s.e.h_off = '0;
                s.e.h_past = 1'b0;
            end else if (!s.e.hf_now) begin
                q = qv(c);
                if (eu_boundary(s.e, q.take_now || q.take_prev,
                                q.latched && int'(q.count) > V35_QUEUE_BYTES, 1'b1)) begin
                    if (eu_inside(s.e)) begin
                        s.e.ce_off = s.e.ce_off + 11'd1;   // clk_end = resume = resume + 1
                        s.e.res = s.e.res + 10'd1;
                        q = qv(c);
                        if (q.rt_valid && $signed(q.rt_off) > 0
                                && int'(s.e.k) == eu_nsteps(s.e))   // refresh_retry=end
                            void'(q_op(c, s, V35_EQ_RETRY_SET, 1'b0, 1'b0,
                                       off20(int'($signed(q.rt_off)) + 1)));
                    end else begin
                        if (int'(s.e.k) >= eu_nsteps(s.e) && !s.e.done_v && s.e.res == '0) begin
                            s.e.done_v = 1'b1;  // refresh_wb=free_wait: the steps ended on t
                            s.e.done_age = '0;
                        end
                        s.e.res = 10'd1;
                        s.e.res_past = 1'b0;
                    end
                    return;                     // (stalled: dead)
                end
            end
        end
        // refresh_reraise=unit: the count loop raises the request a refresh took from it as its
        // last iteration starts (a multiply: mtail before its end)
        q = qv(c);
        if (q.dropped && q.drop_hold && eu_inside(s.e)) begin
            nb = FIT_RERAISE_OFF;
            if (s.e.clk_tag == CT_LOOP_ODD || s.e.clk_tag == CT_MEXIT)
                nb = -int'(cost(s.e.cls, V35_CN_MTAIL));
            if (((s.e.clk_tag == CT_LOOP || s.e.clk_tag == CT_LOOP_ODD || s.e.clk_tag == CT_MEXIT)
                 && nb < 0 && int'(s.e.res) == -nb
                 && (s.e.clk_tag != CT_LOOP_ODD || int'(s.e.k) == eu_nsteps(s.e)))
                    || (s.e.clk_tag == CT_TAIL && nb >= 0))   // t - clk_start >= 0
                void'(q_op(c, s, V35_EQ_RERAISE, 1'b0, 1'b0, 20'd0));
        end
        if (s.e.exec_v && s.e.res != '0 && eu_unit_hold(s, c, b))
            return;
        // shift_exit0=exit: the refresh template's split moves no hold point (unit_hold's exec
        // clocks counted through a seam between its split steps as inside them)
        if (refresh_on && s.e.exec_v && s.e.res == '0 && !s.e.res_past && s.e.ce_off == '0
                && int'(s.e.k) < eu_nsteps(s.e)) begin
            st = eu_step(s.e, int'(s.e.k));
            if (int'(st.op) == V35_SOP_CLOCKS && (int'(st.tag) == V35_STAG_LOOP
                    || int'(st.tag) == V35_STAG_TAIL || int'(st.tag) == V35_STAG_MEXIT)
                    && eu_unit_hold(s, c, b))
                return;
        end
        for (int it = 0; it < 24; it++) begin
            if (s.e.halted)
                return;
            if (s.e.res != '0)
                return;
            ns = eu_nsteps(s.e);
            if (int'(s.e.k) >= ns && !s.e.done_v) begin
                s.e.done_v = 1'b1;              // the running instruction's steps are done
                s.e.done_age = '0;
            end
            if (int'(s.e.k) >= ns && !eu_start(s, c, b))
                return;
            if (s.e.sync == SYNC_DEFER) begin   // imm_landed
                q = qv(c);
                a = q_op(c, s, V35_EQ_ASKED, 1'b0, 1'b0, 20'd0);
                s.e.sync = SYNC_COUNT;
                s.e.owed = 2'(int'(q.inflight) + int'(a[0]));
            end
            if (s.e.sync == SYNC_COUNT && s.e.owed != '0) begin
                q = qv(c);
                lapse = 1'b0;
                // refresh_sync=run: met 2 clocks early, only on the beaten fetch and the one
                // after it (refresh_sync_run=two), not for a class reg form
                // (refresh_sync_reg=delivery)
                early = s.e.owed == 2'd1 && eu_early(c, b) && !(ev_now(c).n > 3'd2)
                        && !is_cls(s.e.cls, V35_CLS_REG);
                if (!early && !q.inflight && !q.ab_valid) begin
                    room = q_op(c, s, V35_EQ_ROOM, 1'b0, 1'b0, 20'd0);
                    lapse = $signed(room) < 8'sd2 || q.dropped;   // wlatch_ir=False
                end
                if (early) begin
                    // met early
                end else if (lapse) begin
                    // the request the sync counted has lapsed
                end else if (q.ab_valid && q.ab_left == '0 && q.ab_this && !s.e.mem
                             && (is_cls(s.e.cls, V35_CLS_SHIFT_IMM) || is_cls(s.e.cls, V35_CLS_MUL)
                                 || is_cls(s.e.cls, V35_CLS_DIV))
                             && s.e.owed == 2'd1) begin
                    s.e.reg_early = 1'b1;       // abort_reg
                end else begin
                    return;
                end
            end
            s.e.sync = SYNC_NONE;
            s.e.owed = '0;
            st = eu_step(s.e, int'(s.e.k));
            case (int'(st.op))
                V35_SOP_CLOCKS: begin
                    if (st.n != '0 && s.e.taken != '0 && !s.e.mem && s.d.need == '0
                            && eu_interlocked(s.e.cls, 1'b1) && bus_io(b)
                            && {1'b0, b.pos} == s.e.start_age) begin
                        s.e.res = 10'(int'(b.len) - int'(b.pos));   // io_exec=after_io
                        s.e.res_past = 1'b0;
                        return;
                    end
                    s.e.k = s.e.k + 1'b1;
                    if (st.n != '0 && !s.e.exec_v && !s.e.mem && s.e.taken != '0
                            && s.d.need == '0
                            && (is_cls(s.e.cls, V35_CLS_SHIFT_IMM) || is_cls(s.e.cls, V35_CLS_SHIFT_CL)
                                || is_cls(s.e.cls, V35_CLS_MUL) || is_cls(s.e.cls, V35_CLS_DIV))) begin
                        s.e.exec_v = 1'b1;      // unit_hold: the exec's first clock
                        s.e.exec_age = '0;
                        s.e.exec_par = 1'b0;
                    end
                    if (st.n != '0) begin
                        if (refresh_on) begin
                            // refresh_eu=hold: a clocks step following another clocks step on
                            // its end clock starts without a micro-boundary (refresh_clk_start=
                            // after_wait: also straight after a take; refresh_start_seam=start:
                            // not on the start clock)
                            q = qv(c);
                            pst = int'(s.e.k) >= 2 ? eu_step(s.e, int'(s.e.k) - 2) : '0;
                            s.e.clk_seam = (int'(s.e.k) >= 2 && int'(pst.op) == V35_SOP_CLOCKS
                                            && s.e.ce_off == '0)
                                           || (int'(s.e.k) >= 2 && int'(pst.op) == V35_SOP_TAKE
                                               && (q.take_now || q.take_prev)
                                               && s.e.start_age != '0);
                            s.e.cs_now = 1'b1;
                        end
                        s.e.res = st.n;
                        s.e.res_past = 1'b0;
                        if (int'(st.tag) == V35_STAG_EA && s.e.mem && s.e.disp != '0)
                            s.d.ea_off = 2'(st.n);  // ea_ir_room
                        last = int'(s.e.k) == eu_nsteps(s.e);
                        q = qv(c);
                        if ((is_cls(s.e.cls, V35_CLS_SHIFT_CL) || is_cls(s.e.cls, V35_CLS_SHIFT_IMM))
                                && !s.e.mem && last && q.retry && q.retry_loop && q.ab_this)
                            void'(q_op(c, s, V35_EQ_RETRY_SET, 1'b0, 1'b0,
                                       off20(int'(s.e.res) - FIT_PER_SHIFT_COUNT)));
                        q = qv(c);
                        if ((is_cls(s.e.cls, V35_CLS_MUL) || is_cls(s.e.cls, V35_CLS_DIV))
                                && !s.e.mem && last && q.retry && q.retry_loop && q.ab_this)
                            void'(q_op(c, s, V35_EQ_RETRY_SET, 1'b0, 1'b0,
                                       off20(int'(s.e.res) - int'(cost(s.e.cls, V35_CN_MTAIL)))));
                        q = qv(c);
                        if (q.rt_valid && $signed(q.rt_off) <= 0)   // retry_first
                            void'(q_op(c, s, V35_EQ_RETRY_END, 1'b0, 1'b0, 20'd0));
                        q = qv(c);
                        if (q.shift_held && last)   // count_latch: its last clock
                            void'(q_op(c, s, V35_EQ_SHIFT_SET, 1'b0, 1'b0,
                                       off20(int'(s.e.res) - 1)));
                        q = qv(c);
                        if (int'(st.tag) == V35_STAG_MEXEC && !s.e.unit_early && q.retry
                                && q.retry_loop && q.ab_this)   // io_take=unit
                            void'(q_op(c, s, V35_EQ_RETRY_SET, 1'b0, 1'b0,
                                       off20(int'(s.e.res) - int'(cost(s.e.cls, V35_CN_MTAIL)))));
                        if (int'(st.tag) == V35_STAG_MEXEC && s.e.unit_early) begin   // abort_unit=loop
                            q = qv(c);
                            if (q.retry && q.retry_loop)
                                void'(q_op(c, s, V35_EQ_RETRY_SET, 1'b0, 1'b0,
                                           off20(int'(s.e.res) - int'(cost(s.e.cls, V35_CN_MTAIL)))));
                            s.e.res = s.e.res + 1'b1;
                        end
                        if (refresh_on) begin
                            // refresh_eu: the template's tags (a shift's own: its last clocks
                            // step the count loop)
                            if (int'(st.tag) == V35_STAG_EXEC) s.e.clk_tag = CT_EXEC;
                            else if (int'(st.tag) == V35_STAG_LOOP) s.e.clk_tag = CT_LOOP;
                            else if (int'(st.tag) == V35_STAG_TAIL) s.e.clk_tag = CT_TAIL;
                            else if (int'(st.tag) == V35_STAG_LOOP_ODD) s.e.clk_tag = CT_LOOP_ODD;
                            else if (int'(st.tag) == V35_STAG_MEXIT) s.e.clk_tag = CT_MEXIT;
                            else if (!(is_cls(s.e.cls, V35_CLS_SHIFT_CL)
                                       || is_cls(s.e.cls, V35_CLS_SHIFT_IMM)))
                                s.e.clk_tag = CT_NONE;
                            else
                                s.e.clk_tag = last ? CT_LOOP : CT_SHIFT;
                            s.e.ce_off = 11'(s.e.res);
                            q = qv(c);
                            if (s.e.clk_tag == CT_TAIL && q.dropped && q.drop_hold
                                    && int'(st.n) < FIT_SHIFT_TAIL)   // shift_exit0=exit
                                void'(q_op(c, s, V35_EQ_RERAISE, 1'b0, 1'b0, 20'd0));
                        end
                    end
                end
                V35_SOP_NOWAIT: begin           // fixed_lookup=decoder_nowait
                    if (!s.e.nw_v) begin
                        s.e.nw_v = 1'b1;
                        s.e.nw = 3'(st.n);
                        if (s.e.start_age == 4'd1 && s.e.fs_this)
                            s.e.nw = s.e.nw + 1'b1;     // lookup_start
                    end
                    if (s.e.nw != '0 && !b.in_wait)
                        s.e.nw = s.e.nw - 1'b1;
                    if (s.e.nw != '0) begin
                        s.e.res = 10'd1;
                        s.e.res_past = 1'b0;
                        return;
                    end
                    s.e.nw_v = 1'b0;
                    s.e.k = s.e.k + 1'b1;
                end
                V35_SOP_TAKE: begin
                    // a port take's word carries its request's setup in n: its bytes are the
                    // form's operand bytes (E4..E7: one)
                    bytes = int'(st.tag) == V35_STAG_PORT ? s.e.op_len - 3'd1 : 3'(st.n);
                    if (bytes == '0) begin
                        s.e.k = s.e.k + 1'b1;
                    end else begin
                        if (s.e.left == '0)
                            s.e.left = bytes;
                        if (eu_late_read(s, c, b))
                            return;             // late_read
                        if (s.e.mem && s.e.disp != '0 && s.e.taken == 3'd1 && eu_late_fetch(b))
                            return;             // late_disp=all
                        wide = int'(st.tag) == V35_STAG_WORD || int'(st.tag) == V35_STAG_CHAIN_WORD;
                        n = dec_take(s, c, s.e.left, wide);
                        q = qv(c);
                        if (n == '0 && q.dropped)
                            void'(q_op(c, s, V35_EQ_RERAISE, 1'b0, 1'b0, 20'd0));
                        s.e.taken = s.e.taken + n;
                        s.e.left = s.e.left - n;
                        if (n != '0 && s.d.need == '0 && is_cls(s.e.cls, V35_CLS_REG) && bus_io(b)
                                && b.pos == 3'd0)
                            s.d.ra_off = s.d.ra_off + 2'd1;   // io_take_nx
                        if (n != '0 && s.e.mem && s.e.disp != '0
                                && s.e.taken == s.e.op_len - 3'd1 - {1'b0, s.e.imm_bytes}) begin
                            void'(q_op(c, s, V35_EQ_DISP, 1'b0, 1'b0, 20'd0));   // latch_disp
                            q = qv(c);
                            if (q.arrived_now)
                                s.d.ir_hold = 1'b0;     // ir_load: on a word's delivery clock
                            if (cost(s.e.cls, V35_CN_DFLOOR) != '0)
                                eu_floor(s, 3'(cost(s.e.cls, V35_CN_DFLOOR)));
                        end
                        if (n != '0 && s.e.taken >= s.e.op_len - 3'd1
                                && ((s.e.imm_bytes != '0 && !s.e.mem)
                                    || (!s.e.mem && eu_interlocked(s.e.cls, 1'b0)))) begin
                            if (c.p) c.wl_p = 1'b1;     // wlatch_imm=reg_last: the data latch
                            else c.wl_t = 1'b1;
                        end
                        if (s.e.left != '0)
                            return;             // stalled or more to take
                        dec_commit(s, c);
                        q = qv(c);
                        if (is_cls(s.e.cls, V35_CLS_SHIFT_IMM) && s.e.imm_bytes != '0
                                && q.arrived_now && q.latched) begin   // count_latch
                            room = q_op(c, s, V35_EQ_ROOM, 1'b0, 1'b0, 20'd0);
                            if (int'($signed(room)) - ((s.d.need == '0) ? int'(q.latched) : 0) < 2) begin
                                s.e.shift_latched = 1'b1;
                                void'(q_op(c, s, V35_EQ_SHIFT_HOLD, 1'b0, 1'b0, 20'd0));
                            end
                        end
                        io_drop = eu_io_drop(s, c, b);
                        s.e.k = s.e.k + 1'b1;
                        if (int'(st.tag) == V35_STAG_PORT) begin
                            eu_port_take(s, c, st, b);
                            s.e.res = 10'd1;    // port_sync=none
                            s.e.res_past = 1'b0;
                            return;
                        end
                        if (int'(st.tag) == V35_STAG_LEAD) begin
                            // alongside the next step's clocks
                        end else if (int'(st.tag) == V35_STAG_CHAIN
                                     || int'(st.tag) == V35_STAG_CHAIN_WORD) begin
                            s.e.res = 10'd1;    // more operand bytes follow: no sync
                            s.e.res_past = 1'b0;
                            return;
                        end else if (eu_data_next(s)) begin
                            // post_on_take=nomodrm: post the request on the take clock
                        end else begin          // take_sync=pending
                            held = s.r[0].valid && s.r[0].detached && s.r[0].ncyc != '0;
                            asked = 1'b0;
                            if (!io_drop) begin
                                a = q_op(c, s, V35_EQ_ASKED, 1'b0, 1'b0, 20'd0);
                                asked = a[0];
                            end
                            if (asked && bus_io(b) && b.pos == 3'd0)
                                asked = 1'b0;   // sync_io=issue
                            q = qv(c);
                            s.e.sync = SYNC_COUNT;
                            s.e.owed = 2'(int'(q.inflight) + int'(asked && !held));
                            if (s.e.grp_form && s.e.mem && s.e.disp == 2'd2
                                    && is_cls(s.e.cls, V35_CLS_RMW) && s.e.imm_bytes == '0
                                    && s.e.taken == s.e.op_len - 3'd1) begin   // grp_disp=hold
                                s.e.owed = {1'b0, q.inflight};
                                void'(q_op(c, s, V35_EQ_GDISP, 1'b0, 1'b0,
                                           20'(cost(s.e.cls, V35_CN_GRP_FREE))));
                            end
                            if (s.e.imm_bytes != '0 && s.e.mem && s.e.disp != '0) begin
                                s.e.sync = SYNC_NONE;   // sync_req=disp
                                s.e.owed = '0;
                            end
                            q = qv(c);
                            if (s.e.imm_bytes != '0 && !s.e.mem && q.arrived_now && q.latched) begin
                                s.e.sync = SYNC_DEFER;  // imm_landed
                                s.e.owed = '0;
                            end
                            if (s.e.shift_latched) begin   // count_latch
                                s.e.sync = SYNC_COUNT;
                                s.e.owed = {1'b0, q.inflight};
                                s.e.res = q.arrived_now ? 10'd2 : 10'd1;
                                s.e.res_past = 1'b0;
                                return;
                            end
                            s.e.res = 10'd1;
                            s.e.res_past = 1'b0;
                            return;
                        end
                    end
                end
                V35_SOP_DATA: begin
                    if (s.e.own == '0) begin
                        s.e.own = eu_submit(s, c, st, 1'b0);
                        if (s.e.own == '0)
                            return;             // the slot and its queue are full
                    end
                    nb = int'(s.e.own) - 1;
                    if (!s.r[nb].da_v || (s.r[nb].da_off != '0))
                        return;
                    eu_retire(s);
                    s.e.k = s.e.k + 1'b1;
                end
                V35_SOP_POST: begin             // post and go on
                    if (s.e.own == '0) begin
                        s.e.own = eu_submit(s, c, st, 1'b0);
                        if (s.e.own == '0)
                            return;
                        pst = s.e.k != '0 ? eu_step(s.e, int'(s.e.k) - 1) : '0;
                        if (is_io(st.kind) && s.e.k != '0 && int'(pst.op) == V35_SOP_SLOT)
                            s.r[int'(s.e.own) - 1].port = 1'b1;   // a port form relatching
                    end
                    s.e.k = s.e.k + 1'b1;
                end
                V35_SOP_POST_IO: begin          // io_release=post
                    nb = int'(eu_submit(s, c, st, 1'b1));
                    if (nb == 0)
                        return;
                    pst = s.e.k != '0 ? eu_step(s.e, int'(s.e.k) - 1) : '0;
                    if (s.e.k != '0 && int'(pst.op) == V35_SOP_SLOT)
                        s.r[nb - 1].port = 1'b1;
                    s.e.k = s.e.k + 1'b1;
                end
                V35_SOP_SLOT: begin             // the I/O ahead has released the latch
                    if (s.r[0].valid && s.r[0].ncyc != '0)
                        return;
                    if (s.e.lu_held)
                        fail(c, V35_EE_SLOT);
                    s.e.k = s.e.k + 1'b1;
                    s.e.res = {7'd0, s.e.lu_off};
                    s.e.res_past = 1'b0;
                end
                V35_SOP_ISSUED: begin
                    if (s.e.own != '0 && s.r[int'(s.e.own) - 1].issued == '0)
                        return;
                    s.e.k = s.e.k + 1'b1;
                end
                V35_SOP_WAIT: begin
                    if (s.e.own != '0) begin
                        nb = int'(s.e.own) - 1;
                        if (!s.r[nb].da_v || s.r[nb].da_off != '0)
                            return;
                        eu_retire(s);
                    end
                    s.e.k = s.e.k + 1'b1;
                end
                V35_SOP_WBSYNC: begin           // the previous write-back (wb_from=end)
                    if (s.e.wbu != '0) begin
                        s.e.res = {8'd0, s.e.wbu};
                        s.e.res_past = 1'b0;
                        return;
                    end
                    s.e.k = s.e.k + 1'b1;
                end
                V35_SOP_HALT: begin
                    s.e.halt_now = 1'b1;
                    s.e.halted = 1'b1;
                    if (refresh_on)             // halt_refresh=run_drop: queue.halted
                        void'(q_op(c, s, V35_EQ_HALT, 1'b0, 1'b0, 20'd0));
                    s.d.stopped = 1'b1;
                    return;
                end
                V35_SOP_FLUSH, V35_SOP_DECIDE: begin   // a transfer (flush_inflight=wait, untaken=wait)
                    nb = int'(cost(s.e.cls, int'(st.op) == V35_SOP_FLUSH ? V35_CN_FGAP : V35_CN_NFGAP));
                    if (b.finf || int'(b.fsince) <= nb)
                        return;                 // fgap clocks after the last fetch's end
                    if (int'(st.op) == V35_SOP_FLUSH)
                        eu_flush(s, c);
                    s.e.k = s.e.k + 1'b1;
                end
                default: begin
                    fail(c, V35_EE_STEP);
                    return;
                end
            endcase
        end
        fail(c, V35_EE_LOOP);
    endfunction

    // ------------------------------------------------ phase X: the arbiter's touches

    // the slot's next cycle (eu.issue's pop): kind, address, width
    function automatic void eu_cycle(input v35_req_t r, output logic [2:0] kind,
                                     output logic [19:0] addr, output logic [1:0] width);
        case (int'(r.kind))
            V35_RK_READ: kind = V35_K_READ;
            V35_RK_WRITE: kind = V35_K_WRITE;
            V35_RK_IO_READ: kind = V35_K_IO_READ;
            V35_RK_IO_WRITE: kind = V35_K_IO_WRITE;
            default: kind = V35_K_NONE;
        endcase
        addr = r.addr;
        if (r.w2 && r.addr[0] && !is_io(r.kind)) begin   // odd_split=atomic
            if (r.ncyc == 2'd2) begin
                width = V35_BW_HI;
            end else begin
                addr = r.addr + 20'd1;
                width = V35_BW_LO;
            end
        end else if (r.w2) begin
            width = V35_BW_WORD;
        end else begin
            width = r.addr[0] ? V35_BW_HI : V35_BW_LO;
        end
    endfunction

    function automatic void eu_issue(inout v35_st_t s, inout v35_ctx_t c,
                                     input logic [2:0] len);
        logic [2:0] kind;
        logic [19:0] addr;
        logic [1:0] width;
        if (!s.r[0].valid || s.r[0].ncyc == '0) begin
            fail(c, V35_EE_XOP);
            return;
        end
        eu_cycle(s.r[0], kind, addr, width);
        if (!c.x_cyc) begin
            c.x_cyc = 1'b1;
            c.x_kind = kind;
            c.x_addr = addr;
            c.x_width = width;
            c.x_data = v35_wdata(s.f, s.x, s.r[0].kind, s.r[0].w2, s.r[0].addr[0],
                                 s.r[0].ncyc == 2'd2, mut);
        end
        s.r[0].ncyc = s.r[0].ncyc - 1'b1;
        s.r[0].issued = s.r[0].issued + 1'b1;
        if (s.r[0].ncyc == '0 && int'(s.r[0].kind) == V35_RK_WRITE)
            s.x.wk = s.x.wk + 3'd1;             // (D2) PUSH R's next word
        if (s.r[0].ncyc == '0 && s.r[0].detached) begin
            if (int'(s.r[0].kind) == V35_RK_IO_WRITE) begin
                s.e.lu_held = 1'b0;             // the latches free once the cycle ends
                s.e.lu_off = len;
            end
            c.retick = 1'b1;
            eu_promote(s, c);
            return;
        end
        if (s.r[0].ncyc == '0 && int'(s.r[0].kind) != V35_RK_READ
                && int'(s.r[0].kind) != V35_RK_IO_READ) begin   // write_wait=mem_end
            s.r[0].da_v = 1'b1;
            s.r[0].da_past = 1'b0;
            s.r[0].da_off = is_io(s.r[0].kind) ? 3'd0 : len;
        end
    endfunction

    // issue_nowrite (grp_read=rmw_slot_any, slot_latch, slot_idle=eu): len, the fetch's
    function automatic void eu_issue_nowrite(inout v35_st_t s, inout v35_ctx_t c,
                                             input logic [2:0] len);
        if (!s.r[0].valid || s.r[0].ncyc == '0) begin
            fail(c, V35_EE_XOP);
            return;
        end
        s.r[0].ncyc = s.r[0].ncyc - 1'b1;
        c.wl_x = 1'b1;
        s.r[0].da_v = 1'b1;
        s.r[0].da_past = 1'b0;
        s.r[0].da_off = len != '0 ? len : 3'(cost(s.e.cls, V35_CN_SIDLE));
    endfunction

    function automatic void eu_xop(inout v35_st_t s, inout v35_ctx_t c,
                                   input logic [V35_XOP_W-1:0] w);
        logic [3:0] code;
        logic [7:0] val;
        {code, val} = w;
        case (code)
            V35_XOP_ISSUE: eu_issue(s, c, val[2:0]);
            V35_XOP_NOWRITE: eu_issue_nowrite(s, c, val[2:0]);
            V35_XOP_FETCH_START: begin
                s.e.fs_now = 1'b1;
                s.e.fs_this = 1'b1;             // the arbiter's test: start_clock == t
            end
            V35_XOP_SYNC_ONE: begin             // abort_latched
                s.e.sync = SYNC_COUNT;
                s.e.owed = 2'd1;
            end
            V35_XOP_FREE0: begin
                if (!s.r[0].valid) fail(c, V35_EE_XOP);
                s.r[0].free_v = 1'b1;
                s.r[0].free = '0;
            end
            V35_XOP_NOT_BEFORE: begin
                if (!s.r[0].valid) fail(c, V35_EE_XOP);
                s.r[0].nb_off = val[3:0];
            end
            V35_XOP_REFRESH: begin              // eu.refresh_cost: the EU's hold
                if (val[3]) begin               // hold_from = t, hold_end = t + length - 1
                    s.e.hv = 1'b1;
                    s.e.h_off = val[2:0] - 3'd1;
                    s.e.h_past = 1'b0;
                    s.e.hf_now = 1'b1;
                end
                // pop_refresh=stall: a refresh started before start_at (POP PSW's clocks)
                s.e.pr_cand = $signed(s.e.sa_off) > 0;
                s.e.pr_now = 1'b1;
                s.e.pr_len = val[2:0];
            end
            V35_XOP_SETUP: begin                // refresh_cost / refresh_post's give-back
                if (!s.r[0].valid) fail(c, V35_EE_XOP);
                s.r[0].setup = s.r[0].setup + 7'($signed(val));
            end
            V35_XOP_BEAT: begin
                if (!s.r[0].valid) fail(c, V35_EE_XOP);
                s.r[0].beat_ext = val[2:0];
            end
            V35_XOP_HALT_DEFER: begin           // refresh_halt=status
                s.e.hd_v = 1'b1;
                s.e.hd_off = val[2:0];
                s.e.hd_past = 1'b0;
            end
            default: ;
        endcase
    endfunction

    // ------------------------------------------------ phase P: Machine.run's post-issue pass

    function automatic void mach_post(inout v35_st_t s, inout v35_ctx_t c);
        v35_qview_t q;
        v35_bview_t b;
        logic raised, xio, xfetch;
        logic [7:0] a;
        int nb;
        b = v35_bview_t'(bus_p);
        xio = x_kind == V35_K_IO_READ || x_kind == V35_K_IO_WRITE;
        xfetch = x_kind == V35_K_FETCH;
        if (x_valid && x_eu && s.d.ir_hold) begin   // ir_load: the data cycle issued
            s.d.ir_hold = 1'b0;
            dec_load_ir(s, c);
            q = qv(c);
            if (q.ir_now)
                void'(q_op(c, s, V35_EQ_EVAL, 1'b0, 1'b0, 20'd0));   // the IR load: a change
        end
        if (x_valid && x_eu && (c.retick || (s.r[0].valid && s.r[0].da_v && !s.r[0].da_past
                                             && s.r[0].da_off == '0))) begin
            c.retick = 1'b0;
            q = qv(c);
            raised = q.flag;
            eu_tick(s, c, b);                   // released on the issue clock
            dec_load_ir(s, c);
            q = qv(c);
            if (xio && !raised && q.ir_now && !q.take_now && !q.inflight) begin   // io_ir_hold
                a = q_op(c, s, V35_EQ_REQUESTING, 1'b0, 1'b0, 20'd0);
                if (a[0])
                    void'(q_op(c, s, V35_EQ_IO_HELD_SET, 1'b0, 1'b0, 20'd0));
            end
        end
        q = qv(c);
        if (x_valid && xio && q.flag && q.arrived_now && q.latched && s.e.unit
                && (is_cls(s.e.cls, V35_CLS_MUL) || is_cls(s.e.cls, V35_CLS_DIV))
                && !q.inflight && !q.retry)     // io_take=unit
            void'(q_op(c, s, V35_EQ_DROP_RETRY, 1'b1, s.e.start_age == '0, 20'd0));
        if (x_valid && xfetch && s.e.port_now && s.e.port_held != '0) begin   // port_issue
            for (int i = 0; i < 3; i++) begin
                if (s.e.port_held[i] && s.r[i].ncyc != '0 && s.r[i].issued == '0) begin
                    nb = 1 + int'(cost(s.r[i].cls, V35_CN_RELATCH));
                    if (nb > int'(s.r[i].nb_off)) s.r[i].nb_off = 4'(nb);
                end
            end
        end
        q = qv(c);
        if (x_valid && xfetch && s.e.start_age == '0 && q.flag && q.ir_now && !q.take_now
                && s.e.op_len == 3'd1 && eu_interlocked(s.e.cls, 1'b1))   // nop_hold=any
            void'(q_op(c, s, V35_EQ_NOP_HOLD, 1'b0, 1'b0, 20'd0));
    endfunction

    // ------------------------------------------------ the clock's chain
    v35_st_t r;
    v35_st_t s_c, s_t, s_l, s_x, s_p, s_e;
    logic [3:0] mut;                        // the bench's mutation (v35_operands, v35_execute)
`ifdef V35S_STATE_DUMP
    assign mut = mutate;
`else
    assign mut = 4'd0;
`endif
    v35_ctx_t cx;
    logic [2:0] fr_l;

    always_comb begin
        v35_st_t s;
        v35_ctx_t c;
        v35_stp_t st0;
        c = '0;
        s = eu_begin(r, v35_bview_t'(bus_t), fetch_done);
        if (c_eu && c_read)
            eu_complete(s, c);
        s_c = s;
        qsnap_c = dec_snap(s.d, imm16(s));
        eu_tick(s, c, v35_bview_t'(bus_t));
        s_t = s;
        n_t = c.n_tl;
        dec_load_ir(s, c);
        s_l = s;
        fr_l = c.fresh;
        if (x_valid)
            s.e.pr_cand = 1'b0;                 // another cycle is the last
        for (int i = 0; i < NXOP; i++)
            eu_xop(s, c, xop[i]);
        s_x = s;
        c.p = 1'b1;
        mach_post(s, c);
        s_p = s;
        // phase E's latch_start: the byte latched behind a full queue went in on the start
        st0 = eu_step(s.e, 0);
        if (q_latch_in && s.e.start_age == '0 && s.e.k == 4'd1
                && int'(st0.op) == V35_SOP_CLOCKS && st0.n != '0 && s.e.res != '0)
            s.e.res = s.e.res + 1'b1;
        s_e = s;
        qsnap_e = dec_snap(s.d, imm16(s));
        e_io = !s.e.halted && (is_cls(s.e.cls, V35_CLS_OUT) || is_cls(s.e.cls, V35_CLS_IN))
               && !(s.r[0].valid && s.r[0].ncyc != '0 && s.r[0].issued != '0)
               && !(s.r[0].valid && s.r[0].ncyc == '0);
        e_out = is_cls(s.e.cls, V35_CLS_OUT);
        cx = c;
    end

    assign op_tl = cx.ops_tl;
    assign n_tl = cx.n_tl;
    assign op_p = cx.ops_p;
    assign n_p = cx.n_p;
    assign n_start = cx.starts;
    assign wl_fill_t = cx.wl_t;
    assign wl_fill_x = cx.wl_x;
    assign wl_fill_p = cx.wl_p;
    assign x_cyc = cx.x_cyc;
    assign x_cyc_kind = cx.x_kind;
    assign x_cyc_addr = cx.x_addr;
    assign x_cyc_width = cx.x_width;
    assign err_code = cx.err;
    assign pc_r = r.e.pc;
    assign code_addr = {r.f.ps, 4'd0} + {4'd0, code_org + pc_r};
    assign x_data = cx.x_data;

    always @(posedge clock) begin
        if (!reset_n) begin
            r <= v35_st_t'(init_state);
            error <= 1'b0;
        end else if (ce) begin
            r <= s_e;
            if (cx.err != 8'd0)
                error <= 1'b1;
        end
    end

    assign state_l = s_l;
    assign state_e = s_e;
    assign fresh_l = fr_l;
    assign fresh_p = cx.fresh_p;
`ifdef V35S_STATE_DUMP
    assign state_c = s_c;
    assign state_t = s_t;
    assign state_x = s_x;
    assign state_p = s_p;
    assign state_dump = r;
    assign opr_a = cx.opr[0];
    assign opr_b = cx.opr[1];
    assign rfx_a = cx.rfx[0];
    assign rfx_b = cx.rfx[1];
`endif
endmodule
