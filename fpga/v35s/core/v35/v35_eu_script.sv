`timescale 1ns/1ps

// V35S core v2, stage S2 only: a SCRIPTED execution unit standing in for the microcode
// sequencer (v35_ucode.sv) and the datapath (v35_eu.sv) of S3. Throw-away: S3 replaces it.
//
// Given the loader's format word it runs the step list of each form the S2 families and the
// chain image's prelude use, as a small hand-written row table (template × row), taking bytes
// through the loader, posting requests to the arbiter and keeping the functional registers
// those forms need (the addresses of the stack and data cycles, the ports, the SFR stores).
// The rows fold the model's zero-time steps into the next timed one (docs/v35s-core-v2.md,
// "Microcode"): a row is one timed action (CLK clocks, TAKE bytes, DATA / WAIT / ISSUED for
// a request, SLOT, FLUSH, HALT) with side effects on entry (a wbsync gate, a lead take, a
// detached I/O post, fetch_hold) or at completion (a post on the take clock, a port take's
// post or relatch); `cont` marks a row whose completion lets the next one act on the same
// clock. The step lists are the frozen templates.steps under fit 62 (printed with
// validation/v35s/chains/sim/templates.py for each form; fit.json md5
// de193740eaf1dee0862d2220ae084909); the integers are fit.json's "cost" entries:
//
//   reg      pre0 4 (len 1), pre 0, exec 0, nx 1        [CLK 4] | [TAKE 1 sync]
//   imm      pre 3, exec 0, wb 0                        [CLK 3] [TAKE imm sync]
//            ModR/M form (81 /0): [CLK 3 after a lead take of the ModR/M] [TAKE 2 sync]
//   shift_cl pre 0, exec 7, loop 2, wb 2, hphase 2      [TAKE 1 sync] [CLK 7+2] [CLK 2·CL]
//            (per_shift_count 2; the LS's CL 31: 9 + 62 clocks)
//   out      pre 3, exec 2, setup 8, setup0 7, lead 2, relatch 3, wbsync 1, wbsync0 0
//            OUT imm8,AL: [CLK 3 after wbsync] [TAKE 1 port: io_write setup 8] [SLOT] [CLK 2]
//            OUT DW,AW:   [CLK 2, posting io_write setup 7 on entry]
//   push     setup 7, setup_free 3                      [DATA write SS:SP-2]
//   store    pre0 2, setup 0                            [CLK 2] [TAKE 2, post write] [WAIT]
//   prefix   exec 2                                     [CLK 2]
//   halt                                                [HALT]
//   prelude: branch_far pre 3, spre 2, exec 5, fgap 5; store_imm (ea direct 0) dadd 1, grp 3,
//            grp1 2, grp_free 1; push_imm pre 3, setup 7, setup_free 3; pop_psw setup 7,
//            setup_free 3, exec 4, phold 2, wb 2
//   unmodelled opcodes: [CLK 2] (trap_nop)
//
// The take sync (take_sync=pending): a take step that ends a form's operand bytes waits for
// the fetches in flight or asked for on its clock, as `owed` (0..2) counted down by the
// deliveries (completed < sync becomes owed > 0), lapsing when nothing is in flight and the
// room is gone; imm_landed defers the count a clock. unit_hold (the shift's exec clocks wait
// at a micro-boundary while a fetch is past its second clock) is a parity bit toggling from
// the exec's first clock, once per cycle (hold_done).
//
// Stage map: S2 (T, eu.tick) is pass "t" below and S5 (P, machine.py's retick on a detached
// I/O's issue clock) pass "p"; a pass is (A) the clocks wait and unit_hold, (B) the take sync,
// (C) one row, or the start gate and the new form's first row, (D) one row more when the
// first completed with `cont` (or ended the form and the next one starts). S6: the next state.
//
// Registered state (widths) and the model variables it replaces:
//   run 1, tmpl 4, k 3              eu.steps, eu.k (k >= len: run 0)
//   res 11                          eu.resume as a countdown (resume - t, the next clock's)
//   left 3, taken 3, oplen 3        eu.left, eu.taken, eu.op_len
//   sync_v 1, sync_def 1, owed 2    eu.sync (pending / defer) as fetches still owed
//   armed 1                         eu._port_take's inserted ("slot",), ("post_io", ...)
//   own_v 1                         eu.own
//   exec_v 1, ex_age 2, ex_par 1,   eu.exec_t (t - exec_t: saturating, and its parity),
//   hold_done 1                     eu.hold_done
//   abort_start 1                   queue.abort_t == eu.start_clock
//   done_m 1, wbu 2, wb_cur 2       eu.done_t is set; eu.wb_until - t; eu.wb
//   lu_inf 1, lu 3                  eu.latch_until - t (inf while a detached OUT waits)
//   halted 1                        eu.halted
//   fmt (fmt_t), ob 5×8             the running form's format and operand bytes
//   aw cw dw bw sp, ds0 ds1 ss ps, seg 3, pc 20     the functional registers (S2 subset)
module v35_eu_script
    import v35_front_pkg::*;
    import v35_stub_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,

    // the loader / queue (S1 values; the loader's IR before S2 and after S3)
    input  wire        ir_v_c,
    input  fmt_t       fmt_c,
    input  wire [19:0] ir_addr_c,
    input  wire        ir_v_l,
    input  fmt_t       fmt_l,
    input  wire [19:0] ir_addr_l,
    input  wire [7:0]  vb0, vb1, vb2, vb3,
    input  wire [3:0]  avail_c,
    input  wire        l_pop,
    input  wire        arrived_now,
    input  wire        lat_c,           // latched after S1 (imm_landed, port_landed)
    input  wire        lat_x,
    input  wire        inflight_c,
    input  wire        inflight_x,
    input  wire        completed_now,
    input  wire signed [4:0] room_c,
    input  wire signed [4:0] room_p0,
    input  wire [3:0]  stored_c,
    input  wire [3:0]  stored_l,
    input  wire        rq_old_c,
    input  wire        rq_old_p,
    input  wire        b2b_now,
    input  wire        asked_d,
    input  wire        asked_t,
    input  wire        asked_p,
    input  wire        retry,           // queue.retry before this clock's loop row
    input  wire        retry_loop,
    input  wire        latch_start_now,
    // the bus (S0)
    input  wire        bus_free,
    input  wire        busy,
    input  wire [2:0]  cur_kind,
    input  wire [2:0]  cur_left,
    input  wire        cur_on_start,
    input  wire        fetch_inflight,
    input  wire        fetch_past_b2,
    input  wire [3:0]  fetch_since,
    input  wire        abort_busy,
    input  wire        abort_last,
    input  wire        wl_busy,
    input  wire        wl_busy_x,
    input  wire [2:0]  grant_len,
    // the arbiter
    input  wire        slot_wait_c,
    input  wire        slot_wait_p,
    input  wire        slot_det_c,
    input  wire        slot_det_p,
    input  wire        own_issued,
    input  wire        own_done,
    input  wire        g_fetch,
    input  wire        g_abort,
    input  wire        retick,          // a detached I/O issued: the second pass runs
    input  wire        g_io,            // the issued cycle is an I/O cycle

    // S2 outputs
    output wire        t_start,
    output wire [1:0]  t_k,
    output wire        t_done,
    output wire        t_wide,
    output wire        t_flush,
    output wire [19:0] t_flush_addr,
    output wire        t_halt,
    output wire        t_fhold,
    output wire        ask_d,
    output wire        ask_t,
    output wire        rt_set,
    output wire signed [9:0] rt_n,
    output wire        imm16_c,
    output wire        imm16_t,
    output wire        nop_cand,
    output wire        abort_loop,
    output wire        halting,
    output wire        halted_o,
    output wire        wb_hold,
    output wire        latch_wait,
    output wire        relatch,
    output wire        relatch_late,
    output wire [1:0]  relatch_n,
    output wire        retire,
    // posts (S2, S5)
    output wire        post_t,
    output req_t       rq_t,
    output wire        post_p,
    output req_t       rq_p,
    // S5 outputs
    output wire        p_start,
    output wire        p_k,
    output wire        p_done,
    output wire        p_io_nx,
    output wire        ask_p,
    output wire        imm16_p,
    output wire        wl_fill_t,       // S2: a register form's last operand byte
    output wire        wl_fill_p,       // S5: the same in the second pass
    output wire        start_any,
    // the SFR store's datum (store_imm takes its immediate after the store issued)
    output wire [15:0] sfr_data,
    // the trace
    output wire [19:0] pc_o,
    output wire [6:0]  cls_o,
    output wire [3:0]  wait_o,
    output wire [10:0] res_o
);
    // ------------------------------------------------------------ the row table
    localparam logic [2:0] R_CLK = 3'd0, R_TAKE = 3'd1, R_DATA = 3'd2, R_WAIT = 3'd3,
                           R_ISSUED = 3'd4, R_SLOT = 3'd5, R_HALT = 3'd6, R_FLUSH = 3'd7;
    localparam logic [1:0] N_LIT = 2'd0, N_SEXEC = 2'd1, N_SLOOP = 2'd2, N_IMM = 2'd3;
    localparam logic [2:0] A_SP2 = 3'd0, A_SP = 3'd1, A_D16 = 3'd2, A_PORT = 3'd3, A_DW = 3'd4;

    localparam logic [3:0] TM_NOP = 4'd0, TM_TRAP = 4'd1, TM_REG2 = 4'd2, TM_IMM = 4'd3,
                           TM_IMMM = 4'd4, TM_SHL = 4'd5, TM_OUTI = 4'd6, TM_OUTDW = 4'd7,
                           TM_PUSH = 4'd8, TM_STORE = 4'd9, TM_PFX = 4'd10, TM_HALT = 4'd11,
                           TM_JMPF = 4'd12, TM_STI = 4'd13, TM_PUSHI = 4'd14, TM_POPPSW = 4'd15;

    localparam int SHL_EXEC = 7;        // shift_cl.exec
    localparam int SHL_LOOP = 2;        // shift_cl.loop (a nonzero count)
    localparam int FGAP_FAR = 5;        // branch_far.fgap

    typedef struct packed {
        logic [2:0] op;
        logic [6:0] n;
        logic [1:0] nsel;
        logic       wbsync;     // CLK: wait for the previous form's write-back first
        logic       lead;       // CLK: a lead take of one byte first
        logic       post_e;     // CLK: post the row's (detached I/O) request on entry
        logic       post_arm;   // CLK: ... only when the port take armed the slot rows
        logic       post_c;     // TAKE: post the row's request when the take ends (cont)
        logic       sync;       // TAKE: a take sync
        logic       port;       // TAKE: a port byte (io_write posted, or the slot armed)
        logic       wide;       // TAKE: two bytes a clock (disp16=word)
        logic       last;
        logic       tag_exec;   // CLK: the shift's exec clocks (unit_hold's exec_t)
        logic       tag_loop;   // CLK: the shift's count loop (abort_unit=loop)
        logic       ls_ok;      // the form's first model step is a clocks step (latch_start)
        logic       fhold;      // CLK: fetch_hold 2 on entry (POP PSW)
        logic [2:0] rkind;      // the row's request
        logic [2:0] asrc;
        logic [6:0] setup;
        logic       fn_v;
        logic [2:0] fn;
        logic [1:0] lead_io;
        logic       det;
        logic       grp;
    } row_t;

    function automatic row_t mk(input logic [2:0] op, input logic [6:0] n, input logic last);
        row_t r;
        r = '0;
        r.op = op;
        r.n = n;
        r.last = last;
        return r;
    endfunction

    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [3:0] tmpl_of(input fmt_t f);
        case (f.fn)
            FN_NONE:      tmpl_of = f.cls == CLS_REG ? TM_NOP : TM_TRAP;
            FN_MOV_RM, FN_MOV_SREG: tmpl_of = TM_REG2;
            FN_MOV_IMM:   tmpl_of = TM_IMM;
            FN_ADD_IMM:   tmpl_of = TM_IMMM;
            FN_SHL:       tmpl_of = TM_SHL;
            FN_OUT_IMM:   tmpl_of = TM_OUTI;
            FN_OUT_DW:    tmpl_of = TM_OUTDW;
            FN_PUSH_R:    tmpl_of = TM_PUSH;
            FN_STORE_AW:  tmpl_of = TM_STORE;
            FN_PREFIX:    tmpl_of = TM_PFX;
            FN_HALT:      tmpl_of = TM_HALT;
            FN_JMPF:      tmpl_of = TM_JMPF;
            FN_STORE_IMM: tmpl_of = TM_STI;
            FN_PUSH_IMM:  tmpl_of = TM_PUSHI;
            FN_POP_PSW:   tmpl_of = TM_POPPSW;
            default:      tmpl_of = TM_TRAP;
        endcase
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */

    // row k of template tm; `w` the form's word bit (store_imm's immediate bytes, setup)
    function automatic row_t row_of(input logic [3:0] tm, input logic [2:0] k, input logic w);
        row_t r;
        r = mk(R_HALT, 7'd0, 1'b1);
        case (tm)
            TM_NOP: begin r = mk(R_CLK, 7'd4, 1'b1); r.ls_ok = 1'b1; end   // reg.pre0
            TM_TRAP: r = mk(R_CLK, 7'd2, 1'b1);
            TM_REG2: begin r = mk(R_TAKE, 7'd1, 1'b1); r.sync = 1'b1; end
            TM_IMM: case (k)
                3'd0: begin r = mk(R_CLK, 7'd3, 1'b0); r.ls_ok = 1'b1; end    // imm.pre
                default: begin r = mk(R_TAKE, 7'd0, 1'b1); r.nsel = N_IMM; r.sync = 1'b1; end
            endcase
            TM_IMMM: case (k)
                3'd0: begin r = mk(R_CLK, 7'd3, 1'b0); r.lead = 1'b1; end      // lead, pre
                default: begin r = mk(R_TAKE, 7'd2, 1'b1); r.sync = 1'b1; end
            endcase
            TM_SHL: case (k)
                3'd0: begin r = mk(R_TAKE, 7'd1, 1'b0); r.sync = 1'b1; end
                3'd1: begin r = mk(R_CLK, 7'd0, 1'b0); r.nsel = N_SEXEC; r.tag_exec = 1'b1; end
                default: begin r = mk(R_CLK, 7'd0, 1'b1); r.nsel = N_SLOOP; r.tag_loop = 1'b1; end
            endcase
            TM_OUTI: case (k)
                3'd0: begin r = mk(R_CLK, 7'd3, 1'b0); r.wbsync = 1'b1; end    // wbsync, pre
                3'd1: begin r = mk(R_TAKE, 7'd1, 1'b0); r.port = 1'b1; end
                3'd2: r = mk(R_SLOT, 7'd0, 1'b0);
                default: begin r = mk(R_CLK, 7'd2, 1'b1); r.post_arm = 1'b1; end   // exec
            endcase
            TM_OUTDW: begin r = mk(R_CLK, 7'd2, 1'b1); r.post_e = 1'b1; end        // exec
            TM_PUSH: r = mk(R_DATA, 7'd0, 1'b1);
            TM_STORE: case (k)
                3'd0: begin r = mk(R_CLK, 7'd2, 1'b0); r.ls_ok = 1'b1; end    // store.pre0
                3'd1: begin r = mk(R_TAKE, 7'd2, 1'b0); r.post_c = 1'b1; end   // post_on_take
                default: r = mk(R_WAIT, 7'd0, 1'b1);
            endcase
            TM_PFX: r = mk(R_CLK, 7'd2, 1'b1);                                 // prefix.exec
            TM_HALT: r = mk(R_HALT, 7'd0, 1'b1);
            TM_JMPF: case (k)
                3'd0: begin r = mk(R_CLK, 7'd3, 1'b0); r.ls_ok = 1'b1; end    // pre
                3'd1: r = mk(R_TAKE, 7'd2, 1'b0);                              // offset, chain
                3'd2: r = mk(R_CLK, 7'd2, 1'b0);                               // spre
                3'd3: begin r = mk(R_TAKE, 7'd2, 1'b0); r.sync = 1'b1; end     // segment
                3'd4: r = mk(R_CLK, 7'd5, 1'b0);                               // exec
                default: r = mk(R_FLUSH, 7'd0, 1'b1);
            endcase
            TM_STI: case (k)
                3'd0: r = mk(R_TAKE, 7'd1, 1'b0);                              // ModR/M, chain
                3'd1: r = mk(R_CLK, 7'd2, 1'b0);                               // ea
                3'd2: begin r = mk(R_TAKE, 7'd2, 1'b0); r.wide = 1'b1; end     // d16, no sync
                3'd3: r = mk(R_CLK, 7'd1, 1'b0);                               // dadd
                3'd4: r = mk(R_ISSUED, 7'd0, 1'b0);                            // post, issued
                3'd5: r = mk(R_TAKE, w ? 7'd2 : 7'd1, 1'b0);                   // imm, chain
                default: r = mk(R_WAIT, 7'd0, 1'b1);
            endcase
            TM_PUSHI: case (k)
                3'd0: begin r = mk(R_CLK, 7'd3, 1'b0); r.ls_ok = 1'b1; end
                3'd1: begin r = mk(R_TAKE, 7'd0, 1'b0); r.nsel = N_IMM; r.sync = 1'b1; end
                default: r = mk(R_DATA, 7'd0, 1'b1);
            endcase
            TM_POPPSW: case (k)
                3'd0: r = mk(R_DATA, 7'd0, 1'b0);
                default: begin r = mk(R_CLK, 7'd4, 1'b1); r.fhold = 1'b1; end
            endcase
            default: ;
        endcase
        // the requests
        case (tm)
            TM_OUTI: begin r.rkind = K_IO_WRITE; r.asrc = A_PORT; r.setup = 7'd8;  // out.setup
                           r.lead_io = 2'd2; r.det = 1'b1; end
            TM_OUTDW: begin r.rkind = K_IO_WRITE; r.asrc = A_DW; r.setup = 7'd7;   // out.setup0
                            r.lead_io = 2'd2; r.det = 1'b1; end
            TM_PUSH, TM_PUSHI: begin r.rkind = K_WRITE; r.asrc = A_SP2; r.setup = 7'd7;
                                     r.fn_v = 1'b1; r.fn = 3'd3; end
            TM_STORE: begin r.rkind = K_WRITE; r.asrc = A_D16; r.setup = 7'd0; end
            TM_STI: begin r.rkind = K_WRITE; r.asrc = A_D16; r.setup = w ? 7'd3 : 7'd2;
                          r.fn_v = 1'b1; r.fn = 3'd1; r.grp = 1'b1; end
            TM_POPPSW: begin r.rkind = K_READ; r.asrc = A_SP; r.setup = 7'd7;
                             r.fn_v = 1'b1; r.fn = 3'd3; end
            default: ;
        endcase
        return r;
    endfunction

    // ------------------------------------------------------------ registered state
    reg        run = 1'b0;
    reg [3:0]  tmpl = TM_NOP;
    reg [2:0]  k = 3'd0;
    reg [10:0] res = 11'd0;
    reg [2:0]  left = 3'd0;
    reg [2:0]  taken = 3'd0;
    reg [2:0]  oplen = 3'd1;
    reg        sync_v = 1'b0;
    reg        sync_def = 1'b0;
    reg [1:0]  owed = 2'd0;
    reg        armed = 1'b0;
    reg        own_v = 1'b0;
    reg        exec_v = 1'b0;
    reg [1:0]  ex_age = 2'd0;
    reg        ex_par = 1'b0;
    reg        hold_done = 1'b0;
    reg        abort_start = 1'b0;
    reg        done_m = 1'b1;
    reg [1:0]  wbu = 2'd0;
    reg [1:0]  wb_cur = 2'd0;
    reg        lu_inf = 1'b0;
    reg [2:0]  lu = 3'd0;
    reg        halted = 1'b0;
    reg        refill = 1'b0;           // eu.refill: a flush's refill gates the next start
    fmt_t      fmt = '0;
    reg [39:0] ob = 40'd0;              // the operand bytes, ob[8j +: 8] the j-th
    // the functional registers (the S2 forms' subset)
    typedef struct packed {
        logic [15:0] aw, cw, dw, bw, sp;
        logic [15:0] ds0, ds1, ss, ps;
        logic [2:0]  seg;       // the segment prefix the next form carries (+4: valid)
    } fregs_t;
    localparam fregs_t FR_RESET = '{aw: 16'd0, cw: 16'd0, dw: 16'd0, bw: 16'd0, sp: 16'd0,
                                   ds0: 16'd0, ds1: 16'd0, ss: 16'd0, ps: 16'hFFFF, seg: 3'd0};
    fregs_t    fr = FR_RESET;
    reg [19:0] pc = 20'hFFFF0;

    // wait reasons (the trace's W)
    localparam logic [3:0] W_NONE = 4'd0, W_CLK = 4'd1, W_HOLD = 4'd2, W_SYNC = 4'd3,
                           W_BYTES = 4'd4, W_LATE = 4'd5, W_LATCH = 4'd6, W_DATA = 4'd7,
                           W_ISSUED = 4'd8, W_SLOT = 4'd9, W_WBSYNC = 4'd10, W_GATE = 4'd11,
                           W_IR = 4'd12, W_HALT = 4'd13, W_FLUSH = 4'd14, W_IOEXEC = 4'd15;

    // ------------------------------------------------------------ functional helpers
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [15:0] r16(input fregs_t g, input logic [2:0] n);
        case (n)
            3'd0: r16 = g.aw; 3'd1: r16 = g.cw; 3'd2: r16 = g.dw; 3'd3: r16 = g.bw;
            3'd4: r16 = g.sp; default: r16 = 16'd0;   // BP IX IY: not used by the S2 forms
        endcase
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    function automatic fregs_t w16(input fregs_t g, input logic [2:0] n, input logic [15:0] v);
        w16 = g;
        case (n)
            3'd0: w16.aw = v; 3'd1: w16.cw = v; 3'd2: w16.dw = v; 3'd3: w16.bw = v;
            3'd4: w16.sp = v; default: ;
        endcase
    endfunction
    // the functional effect of a form that ends (its operand bytes b)
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic fregs_t apply(input fregs_t g0, input fmt_t f, input logic [39:0] b);
        fregs_t g;
        logic [15:0] imm;
        g = g0;
        imm = b[23:8];
        case (f.fn)
            FN_MOV_RM: g = w16(g, b[5:3], r16(g, b[2:0]));
            FN_MOV_SREG: case (b[4:3])
                2'd0: g.ds1 = r16(g, b[2:0]); 2'd1: g.ps = r16(g, b[2:0]);
                2'd2: g.ss = r16(g, b[2:0]); default: g.ds0 = r16(g, b[2:0]);
            endcase
            FN_MOV_IMM: if (f.w)
                    g = w16(g, f.rg, b[15:0]);
                else
                    case (f.rg)
                        3'd0: g.aw[7:0] = b[7:0]; 3'd1: g.cw[7:0] = b[7:0];
                        3'd2: g.dw[7:0] = b[7:0]; 3'd3: g.bw[7:0] = b[7:0];
                        3'd4: g.aw[15:8] = b[7:0]; 3'd5: g.cw[15:8] = b[7:0];
                        3'd6: g.dw[15:8] = b[7:0]; default: g.bw[15:8] = b[7:0];
                    endcase
            FN_ADD_IMM: g = w16(g, b[2:0], r16(g, b[2:0]) + imm);
            FN_SHL: g = w16(g, b[2:0], r16(g, b[2:0]) << g.cw[4:0]);
            FN_PUSH_R, FN_PUSH_IMM: g.sp = g.sp - 16'd2;
            FN_POP_PSW: g.sp = g.sp + 16'd2;
            FN_JMPF: g.ps = b[31:16];
            default: ;
        endcase
        g.seg = f.fn == FN_PREFIX ? f.seg : 3'd0;
        return g;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    function automatic logic [19:0] lin(input logic [15:0] s, input logic [15:0] o);
        lin = {s, 4'd0} + {4'd0, o};
    endfunction

    // ------------------------------------------------------------ one pass (T or P)
    typedef struct packed {
        logic        run;
        logic [3:0]  tmpl;
        logic [2:0]  k;
        logic [10:0] res;       // resume - t on this clock
        logic [2:0]  left;
        logic [2:0]  taken;
        logic [2:0]  oplen;
        logic        sync_v;
        logic        sync_def;
        logic        armed;
        logic        own_v;
        logic        exec_v;
        logic        halted;
        logic        done_m;
        logic        started;   // a form started in this pass
        logic [39:0] ob;        // the operand bytes as they stand
        fmt_t        fmt;
    } ps_t;

    typedef struct packed {
        logic        is_p;
        logic [3:0]  avail;     // bytes the decoder may take now
        logic [7:0]  b0, b1;    // the head bytes now
        logic        ir_v;      // the IR holds an opcode (before this pass's start)
        logic        late;      // a fetch past its second clock (late_read)
        logic        lu_busy;   // t < latch_until
        logic [2:0]  lu_val;    // latch_until - t
        logic        wbu_busy;  // t < wb_until
        logic        slot_wait; // a request waits unissued in the slot
        logic        slot_det;  // ... a detached I/O write
        logic        cur_io_s;  // an I/O cycle that started on the form's start clock runs
        logic [2:0]  cur_left;
        logic        cur_io_now;    // an I/O cycle issued on this clock (P)
        logic        lat;       // latched before this pass's take (imm_landed, port_landed)
        logic        own_done;
        logic        own_issued;
        logic        retry_ok;  // q.retry and q.retry_loop
        logic        abort_st;
        logic        flush_ok;  // no fetch on the bus, fgap clocks past the last one's end
    } env_t;

    typedef struct packed {
        logic        complete;
        logic        cont;
        logic [3:0]  why;       // the wait reason when not complete
        logic [1:0]  tk;        // bytes taken
        logic        tk_done;   // the take step committed
        logic        wide;
        logic        ask;       // a take sync: owed from asked(t)
        logic        def;       // imm_landed: the sync deferred
        logic        post;      // the row's request posts
        logic        relatch;
        logic        wl_fill;
        logic        rt_set;
        logic signed [9:0] rt_n;
        logic        fhold;
        logic        flush;
        logic        halt;
        logic        io_nx;
        logic        set_exec;
        logic        retire;
        logic        landed;    // port_landed: the port byte taken with its word's other latched
        row_t        row;       // the row that acted (its request)
    } fx_t;

    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [10:0] row_res(input row_t r, input fmt_t f, input logic [7:0] cl);
        case (r.nsel)
            N_SEXEC: row_res = 11'(SHL_EXEC) + (cl != 8'd0 ? 11'(SHL_LOOP) : 11'd0);
            N_SLOOP: row_res = 11'(FIT_PER_SHIFT_COUNT) * {3'd0, cl};
            N_IMM: row_res = 11'(f.imm);
            N_LIT: row_res = 11'(r.n);
            default: row_res = 11'(r.n);
        endcase
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */

    // One row at the pass state s: its entry, or its continuation on a later clock.
    function automatic void do_row(inout ps_t s, input env_t e, output fx_t x,
                                   input logic [7:0] cl);
        row_t r;
        logic [10:0] n;
        logic [2:0] left0, cap, kk, need;
        r = row_of(s.tmpl, s.k, s.fmt.w);
        n = row_res(r, s.fmt, cl);
        x = '0;
        x.row = r;
        need = s.oplen - 3'd1 - s.taken;
        case (r.op)
            R_CLK: begin
                if (r.wbsync && e.wbu_busy) begin
                    x.why = W_WBSYNC;
                end else if (r.lead && e.avail == 4'd0) begin
                    x.why = W_BYTES;
                end else if ((r.post_e || (r.post_arm && s.armed)) && e.slot_wait) begin
                    x.why = W_SLOT;             // S2: nothing queues behind a waiting request
                end else if (n != 11'd0 && s.taken != 3'd0 && !s.fmt.mem && need == 3'd0
                             && s.fmt.ilock && e.cur_io_s) begin
                    // io_exec=after_io: a register form started on an I/O cycle's issue clock
                    // runs its clocks after its operand take only once the cycle has ended
                    x.why = W_IOEXEC;
                    s.res = 11'(e.cur_left);
                end else begin
                    if (r.lead) begin
                        x.tk = 2'd1;
                        x.tk_done = 1'b1;
                        s.ob[7:0] = e.b0;
                        if (s.fmt.modrm)
                            s.oplen = s.oplen + 3'(v35_modrm_disp(e.b0));
                        s.taken = s.taken + 3'd1;
                    end
                    x.post = r.post_e || (r.post_arm && s.armed);
                    x.fhold = r.fhold;
                    x.complete = 1'b1;
                    s.k = s.k + 3'd1;
                    if (r.last)
                        s.run = 1'b0;
                    if (n == 11'd0) begin
                        x.cont = 1'b1;
                    end else begin
                        s.res = n;
                        x.set_exec = r.tag_exec && !s.exec_v;
                        if (r.tag_exec)
                            s.exec_v = 1'b1;
                        // abort_unit=loop: a register shift started on an aborted cycle raises
                        // the dropped request as its last count iteration starts
                        if (r.tag_loop && e.retry_ok && e.abort_st) begin
                            x.rt_set = 1'b1;
                            x.rt_n = $signed({1'b0, 9'(n)}) - 10'sd2;
                        end
                    end
                end
            end
            R_TAKE: begin
                left0 = s.left != 3'd0 ? s.left : (r.nsel == N_IMM ? 3'(s.fmt.imm) : 3'(r.n));
                cap = r.wide ? 3'd2 : 3'd1;
                kk = left0 < cap ? left0 : cap;
                if ({1'b0, kk} > e.avail)
                    kk = 3'(e.avail);
                s.left = left0;
                if (e.lu_busy && s.fmt.imm != 2'd0 && s.taken >= s.oplen - 3'd1 - 3'(s.fmt.imm))
                    x.why = W_LATCH;            // imm_latch=wait: an OUT's I/O holds the latch
                // decoder.loads_after(t, 1): the IR would load on t too after this last byte
                else if (e.late && left0 == 3'd1 && !(e.ir_v && !s.started) && need == 3'd1
                         && v35_class_stub(s.fmt.cls).nx == 3'd0 && !s.halted
                         && e.avail > 4'd1)
                    x.why = W_LATE;             // late_read: the take and the IR load wait
                else if (kk == 3'd0)
                    x.why = W_BYTES;
                else begin
                    x.tk = 2'(kk);
                    x.wide = r.wide;
                    s.ob[8 * s.taken +: 8] = e.b0;
                    if (kk == 3'd2)
                        s.ob[8 * (s.taken + 3'd1) +: 8] = e.b1;
                    if (s.taken == 3'd0 && s.fmt.modrm)
                        s.oplen = s.oplen + 3'(v35_modrm_disp(e.b0));
                    s.taken = s.taken + kk;
                    s.left = left0 - kk;
                    need = s.oplen - 3'd1 - s.taken;
                    // wlatch_src=write_imm_read: the last immediate byte of a form without a
                    // memory operand; wlatch_imm=reg_last: the last operand byte of any
                    // register-only form: into the data latch on its take
                    x.wl_fill = need == 3'd0 && !s.fmt.mem
                                && (s.fmt.imm != 2'd0 || s.fmt.ilock_reg);
                    // io_take_nx: a register form's last operand byte taken on an I/O cycle's
                    // issue clock: its IR load a clock later
                    x.io_nx = e.is_p && e.cur_io_now && need == 3'd0 && s.fmt.cls == CLS_REG;
                    if (s.left != 3'd0) begin
                        x.why = W_BYTES;
                    end else begin
                        x.tk_done = 1'b1;
                        x.complete = 1'b1;
                        s.k = s.k + 3'd1;
                        if (r.last)
                            s.run = 1'b0;
                        s.res = 11'd1;          // the next row on the next clock
                        if (r.port) begin
                            x.relatch = 1'b1;
                            x.landed = arrived_now && e.lat && e.avail > 4'(kk);
                            if (e.slot_det)
                                s.armed = 1'b1; // ("slot",), ("post_io", ...) inserted
                            else
                                x.post = 1'b1;  // the I/O posted on the take clock
                        end else if (r.post_c) begin
                            x.post = 1'b1;      // post_on_take=nomodrm
                            s.own_v = 1'b1;
                            s.res = 11'd0;
                            x.cont = 1'b1;
                        end else if (r.sync) begin
                            x.def = s.fmt.imm != 2'd0 && !s.fmt.mem && arrived_now && e.lat
                                    && e.avail > 4'(kk);
                            x.ask = !x.def;
                            s.sync_v = 1'b1;
                            s.sync_def = x.def;
                        end
                    end
                end
            end
            R_DATA, R_WAIT, R_ISSUED: begin
                if (!s.own_v) begin
                    if (e.slot_wait) begin
                        x.why = W_SLOT;
                    end else begin
                        x.post = 1'b1;
                        s.own_v = 1'b1;
                        x.why = r.op == R_ISSUED ? W_ISSUED : W_DATA;
                    end
                end else if (r.op == R_ISSUED ? e.own_issued : e.own_done) begin
                    x.complete = 1'b1;
                    x.cont = 1'b1;
                    if (r.op != R_ISSUED) begin
                        s.own_v = 1'b0;
                        x.retire = 1'b1;
                    end
                    s.k = s.k + 3'd1;
                    if (r.last)
                        s.run = 1'b0;
                end else begin
                    x.why = r.op == R_ISSUED ? W_ISSUED : W_DATA;
                end
            end
            R_SLOT: begin
                if (!s.armed) begin
                    x.complete = 1'b1;
                    x.cont = 1'b1;
                    s.k = s.k + 3'd1;
                end else if (e.slot_wait) begin
                    x.why = W_SLOT;
                end else begin
                    x.complete = 1'b1;
                    s.k = s.k + 3'd1;
                    if (e.lu_busy && e.lu_val != 3'd0)
                        s.res = 11'(e.lu_val);  // resume = max(t, latch_until)
                    else
                        x.cont = 1'b1;
                end
            end
            R_FLUSH: begin
                if (!e.flush_ok) begin
                    x.why = W_FLUSH;
                end else begin
                    x.flush = 1'b1;
                    x.complete = 1'b1;
                    x.cont = 1'b1;
                    s.k = s.k + 3'd1;
                    s.run = 1'b0;
                end
            end
            default: begin              // R_HALT
                x.halt = 1'b1;
                x.why = W_HALT;
                s.halted = 1'b1;
                s.k = s.k + 3'd1;
                s.run = 1'b0;
            end
        endcase
    endfunction

    // the start gate (eu._start under the fit, for the stub's classes); `wl` the data latch
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic gate(input fmt_t f, input logic ir_v, input logic is_p,
                                  input logic slot_det, input logic rq_old, input logic infl,
                                  input logic [3:0] stored, input logic wl, input logic rfb);
        logic ok;
        ok = ir_v && !rfb;              // refill_start=full_io: a flush's refill first
        if (!is_p && fetch_inflight)
            ok = 1'b0;                  // start_sync: no start with a fetch on the bus
        if (f.modrm && b2b_now)
            ok = 1'b0;                  // start_sync=b2b_modrm
        if (f.ilock && slot_det)
            ok = 1'b0;                  // io_interlock=reg_pfx: an OUT's I/O waits in the slot
        if (f.ilock && busy && cur_kind == K_IO_WRITE)
            ok = 1'b0;                  // io_busy_start=issue: not after the OUT's issue clock
        if (f.cls == CLS_OUT && f.port && wl)
            ok = 1'b0;                  // wlatch, wlatch_cls=port
        if ((f.port || f.modrm) && rq_old && !infl && !is_p && bus_free
            && stored < 4'(FIT_IO_B2B_Q))
            ok = 1'b0;                  // io_older=io_modrm (the bus is never free in P)
        if (!f.modrm && b2b_now && stored < 4'(FIT_IO_B2B_Q))
            ok = 1'b0;                  // io_b2b=all
        return ok;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */

    // a form starts: the pass state for its first row
    function automatic void start_ps(inout ps_t s, input fmt_t f);
        s.run = 1'b1;
        s.tmpl = tmpl_of(f);
        s.k = 3'd0;
        s.res = 11'd0;
        s.left = 3'd0;
        s.taken = 3'd0;
        s.oplen = f.len;
        s.sync_v = 1'b0;
        s.sync_def = 1'b0;
        s.armed = 1'b0;
        s.own_v = 1'b0;
        s.exec_v = 1'b0;
        s.done_m = 1'b0;
        s.started = 1'b1;
        s.ob = '0;
        s.fmt = f;
    endfunction

    // ------------------------------------------------------------ S2: the T pass
    wire        lu_busy_c = lu_inf || lu != 3'd0;
    wire [1:0]  owed_c = owed - (completed_now && owed != 2'd0 ? 2'd1 : 2'd0);
    wire [7:0]  cl = fr.cw[7:0];
    wire [1:0]  hphase = v35_class_stub(fmt.cls).hphase;

    ps_t   s0, s1, s2, s3;
    fx_t   x1, x2;
    env_t  et;
    logic  t_hold, t_wait, t_sync_blk, t_sync_ok, t_gate1, t_gate2, t_try1, t_try2;
    logic  t_lapse, t_done_rec, t_ev1, t_ev2;
    logic [3:0] t_why;
    logic [1:0] owed_t;
    logic [10:0] hold_res;
    logic [1:0] wbu_t1, wbu_t2;

    always_comb begin
        s0 = '0;
        s0.run = run;
        s0.tmpl = tmpl;
        s0.k = k;
        s0.res = res;
        s0.left = left;
        s0.taken = taken;
        s0.oplen = oplen;
        s0.sync_v = sync_v;
        s0.sync_def = sync_def;
        s0.armed = armed;
        s0.own_v = own_v;
        s0.exec_v = exec_v;
        s0.halted = halted;
        s0.done_m = done_m;
        s0.ob = ob;
        s0.fmt = fmt;

        et = '0;
        et.avail = avail_c;
        et.b0 = vb0;
        et.b1 = vb1;
        et.ir_v = ir_v_c;
        et.late = fetch_past_b2;
        et.lu_busy = lu_busy_c;
        et.lu_val = lu;
        et.slot_wait = slot_wait_c;
        et.slot_det = slot_det_c;
        et.cur_io_s = cur_on_start && k_io(cur_kind);
        et.cur_left = cur_left;
        et.lat = lat_c;
        et.own_done = own_done;
        et.own_issued = own_issued;
        et.retry_ok = retry && retry_loop;
        et.abort_st = abort_start;
        et.flush_ok = !fetch_inflight && fetch_since > 4'(FGAP_FAR);

        // (A) the clocks wait; unit_hold: the exec clocks wait at a micro-boundary (every
        // second clock from hphase) while a fetch is past its second clock (or an aborted
        // cycle ends), to that cycle's end; once per cycle
        t_hold = !halted && exec_v && res != 11'd0 && ex_age >= hphase
                 && ex_par == hphase[0] && !hold_done && (fetch_past_b2 || abort_last);
        hold_res = res + (fetch_past_b2 ? 11'(cur_left) : 11'd1);
        t_wait = halted || res != 11'd0;

        // (B) the take sync: owed fetches not delivered, unless the request lapsed
        t_lapse = !inflight_c && !abort_busy && room_c < 5'sd2;
        owed_t = sync_def ? (inflight_c ? 2'd1 : 2'd0) + (asked_d ? 2'd1 : 2'd0) : owed_c;
        t_sync_blk = !t_wait && sync_v && owed_t != 2'd0 && !t_lapse;
        t_sync_ok = !t_wait && !t_sync_blk;

        // (C) the row, or the start gate and the new form's first row
        s1 = s0;
        if (!t_wait && sync_v)
            s1.sync_def = 1'b0;         // a deferred sync is counted now (met or not)
        if (t_sync_ok)
            s1.sync_v = 1'b0;
        t_done_rec = t_sync_ok && !run && !done_m;
        if (t_done_rec)
            s1.done_m = 1'b1;
        wbu_t1 = t_done_rec ? wb_cur : wbu;
        et.wbu_busy = wbu_t1 != 2'd0;
        t_gate1 = gate(fmt_c, ir_v_c, 1'b0, slot_det_c, rq_old_c, inflight_c, stored_c,
                       wl_busy, refill && (inflight_c || room_c >= 5'sd2));
        t_try1 = t_sync_ok && !run && !halted;
        if (t_try1 && t_gate1)
            start_ps(s1, fmt_c);
        t_ev1 = t_sync_ok && !halted && (run || (t_try1 && t_gate1));
        s2 = s1;
        x1 = '0;
        if (t_ev1)
            do_row(s2, et, x1, cl);

        // (D) a second row when the first one completed with `cont`
        et.avail = avail_c - 4'(x1.tk);
        et.b0 = x1.tk == 2'd0 ? vb0 : (x1.tk == 2'd1 ? vb1 : vb2);
        et.b1 = x1.tk == 2'd0 ? vb1 : (x1.tk == 2'd1 ? vb2 : vb3);
        s3 = s2;
        x2 = '0;
        t_try2 = t_ev1 && x1.complete && x1.cont && !s2.run && !s1.started;
        if (t_try2)
            s3.done_m = 1'b1;
        wbu_t2 = (t_done_rec || t_try2) ? wb_cur : wbu;
        et.wbu_busy = wbu_t2 != 2'd0;
        t_gate2 = gate(fmt_c, ir_v_c && !x1.flush, 1'b0, slot_det_c, rq_old_c, inflight_c,
                       stored_c, wl_busy, (refill || x1.flush) && (inflight_c || room_c >= 5'sd2
                                                                   || x1.flush));
        if (t_try2 && t_gate2)
            start_ps(s3, fmt_c);
        t_ev2 = t_ev1 && x1.complete && x1.cont && (s2.run || (t_try2 && t_gate2));
        if (t_ev2)
            do_row(s3, et, x2, cl);

        t_why = halted ? W_HALT : t_hold ? W_HOLD : t_wait ? W_CLK : t_sync_blk ? W_SYNC :
                ((t_try1 && !t_gate1) || (t_try2 && !t_gate2)) ? (ir_v_c ? W_GATE : W_IR) :
                t_ev2 ? x2.why : t_ev1 ? x1.why : W_NONE;
    end

    assign t_start = s1.started || s3.started;
    fx_t xt;
    always_comb begin
        xt = x1 | x2;
        xt.rt_n = x1.rt_set ? x1.rt_n : x2.rt_n;
        xt.row = (x2.post) ? x2.row : x1.row;
    end
    assign t_k = xt.tk;
    assign t_done = xt.tk_done;
    assign t_wide = xt.wide;
    assign t_flush = xt.flush;
    assign t_flush_addr = lin(ob[31:16], ob[15:0]);
    assign t_halt = xt.halt;
    assign t_fhold = xt.fhold;
    assign ask_d = !t_wait && sync_v && sync_def;
    assign ask_t = xt.ask;
    assign rt_set = xt.rt_set;
    assign rt_n = xt.rt_n;
    assign halting = xt.halt;
    assign halted_o = halted;
    assign abort_loop = t_start && s3.fmt.cls == CLS_SHIFT_CL && !s3.fmt.mem;
    // nop_hold: a register-only form without operand bytes started on this clock
    assign nop_cand = t_start && s3.fmt.len == 3'd1 && s3.fmt.ilock;
    // wb_fetch=hold: the form started on this clock waits at its wbsync step
    assign wb_hold = t_start && s3.k == 3'd0 && row_of(s3.tmpl, 3'd0, s3.fmt.w).wbsync
                     && wbu_t2 != 2'd0;
    // wlatch_hold: an I/O form waits at its start for the data latch (the checks before
    // eu._start's wlatch test passed)
    assign latch_wait = (t_try1 || t_try2) && ir_v_c && !fetch_inflight && !refill
                        && fmt_c.cls == CLS_OUT
                        && fmt_c.port && wl_busy;
    assign retire = xt.retire;
    // eu.cls / imm_bytes as the room's room_ir_imm reads them: the running (or last) form
    assign imm16_c = fmt.cls == CLS_IMM && fmt.imm == 2'd2;
    assign imm16_t = s3.fmt.cls == CLS_IMM && s3.fmt.imm == 2'd2;

    // ------------------------------------------------------------ S5: the P pass
    // machine.py's retick on a detached I/O's issue clock: the start gate again (the I/O
    // interlock satisfied), the started form's first row, a SLOT row's release
    ps_t   q0, q1, q2, q3;
    fx_t   y1, y2;
    env_t  ep;
    logic  p_gate1, p_gate2, p_try1, p_try2, p_ev1, p_ev2, p_wait, p_sync_ok, p_lapse;
    logic  p_done_rec;
    logic [1:0] wbu_p1, wbu_p2;

    always_comb begin
        q0 = s3;
        q0.started = 1'b0;
        ep = et;
        ep.is_p = 1'b1;
        ep.avail = avail_c - 4'(xt.tk) - (l_pop ? 4'd1 : 4'd0);
        ep.b0 = xt.tk == 2'd0 ? (l_pop ? vb1 : vb0) : (xt.tk == 2'd1 ? (l_pop ? vb2 : vb1)
                                                                  : (l_pop ? vb3 : vb2));
        ep.b1 = ep.b0;
        ep.ir_v = ir_v_l;
        ep.late = 1'b0;                 // the bus holds the I/O just issued
        ep.lu_busy = 1'b1;              // ... and it holds the latches to its end
        ep.lu_val = grant_len;
        ep.slot_wait = slot_wait_p;
        ep.slot_det = slot_det_p;
        ep.cur_io_s = g_io;             // the cycle issued now, on a P start's clock
        ep.cur_left = grant_len;
        ep.cur_io_now = g_io;
        ep.lat = lat_x;
        ep.own_done = 1'b0;
        ep.own_issued = own_issued;
        ep.flush_ok = 1'b0;

        p_wait = !retick || q0.halted || q0.res != 11'd0;
        p_lapse = !inflight_x && !abort_busy && room_p0 < 5'sd2;
        p_sync_ok = !p_wait && (!q0.sync_v || p_lapse);
        q1 = q0;
        if (p_sync_ok)
            q1.sync_v = 1'b0;
        p_done_rec = p_sync_ok && !q0.run && !q0.done_m;
        if (p_done_rec)
            q1.done_m = 1'b1;
        wbu_p1 = (t_done_rec || t_try2 || p_done_rec) ? wb_cur : wbu;
        ep.wbu_busy = wbu_p1 != 2'd0;
        p_gate1 = gate(fmt_l, ir_v_l, 1'b1, slot_det_p, rq_old_p, inflight_x, stored_l,
                       wl_busy_x, refill);
        p_try1 = p_sync_ok && !q0.run;
        if (p_try1 && p_gate1)
            start_ps(q1, fmt_l);
        p_ev1 = p_sync_ok && (q0.run || (p_try1 && p_gate1));
        q2 = q1;
        y1 = '0;
        if (p_ev1)
            do_row(q2, ep, y1, cl);
        q3 = q2;
        y2 = '0;
        p_try2 = p_ev1 && y1.complete && y1.cont && !q2.run && !q1.started;
        if (p_try2)
            q3.done_m = 1'b1;
        wbu_p2 = (t_done_rec || t_try2 || p_done_rec || p_try2) ? wb_cur : wbu;
        ep.wbu_busy = wbu_p2 != 2'd0;
        p_gate2 = gate(fmt_l, ir_v_l, 1'b1, slot_det_p, rq_old_p, inflight_x, stored_l,
                       wl_busy_x, refill);
        if (p_try2 && p_gate2)
            start_ps(q3, fmt_l);
        p_ev2 = p_ev1 && y1.complete && y1.cont && y1.tk == 2'd0
                && (q2.run || (p_try2 && p_gate2));
        if (p_ev2)
            do_row(q3, ep, y2, cl);
    end

    assign p_start = q1.started || q3.started;
    fx_t xp;
    always_comb begin
        xp = y1 | y2;
        xp.rt_n = y1.rt_set ? y1.rt_n : y2.rt_n;
        xp.row = y2.post ? y2.row : y1.row;
    end
    assign p_k = xp.tk != 2'd0;
    assign p_done = xp.tk_done;
    assign p_io_nx = xp.io_nx;
    assign ask_p = xp.ask;
    assign imm16_p = q3.fmt.cls == CLS_IMM && q3.fmt.imm == 2'd2;
    assign wl_fill_t = xt.wl_fill;
    assign wl_fill_p = xp.wl_fill;
    assign start_any = t_start || p_start;

    // ------------------------------------------------------------ the posts
    // the request a row posts, from the pass state after it (its operand bytes, the form)
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic req_t mkreq(input row_t r, input ps_t a, input fregs_t g);
        req_t q;
        logic [15:0] d16, sds;
        d16 = a.fmt.modrm ? a.ob[23:8] : a.ob[15:0];
        sds = g.seg == 3'd4 ? g.ds1 : g.seg == 3'd5 ? g.ps : g.seg == 3'd6 ? g.ss : g.ds0;
        q = '0;
        q.kind = r.rkind;
        case (r.asrc)
            A_SP2: q.addr = lin(g.ss, g.sp - 16'd2);
            A_SP: q.addr = lin(g.ss, g.sp);
            A_D16: q.addr = lin(sds, d16);
            A_PORT: q.addr = {12'd0, a.ob[7:0]};
            default: q.addr = {4'd0, g.dw};
        endcase
        case (a.tmpl)
            TM_PUSH: q.data = r16(g, a.fmt.rg);
            TM_PUSHI: q.data = a.fmt.imm == 2'd1 ? {{8{a.ob[7]}}, a.ob[7:0]} : a.ob[15:0];
            TM_OUTI, TM_OUTDW: q.data = {g.aw[7:0], g.aw[7:0]};
            default: q.data = g.aw;
        endcase
        q.width = a.fmt.w ? BW_WORD : (q.addr[0] ? BW_HI : BW_LO);
        q.setup = r.setup;
        q.fn_v = r.fn_v;
        q.fn = r.fn;
        q.lead = r.lead_io;
        q.port = r.asrc == A_PORT;
        q.detached = r.det;
        q.grp = r.grp;
        return q;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    assign post_t = xt.post;
    assign rq_t = mkreq(xt.row, s3, fr_t);
    assign post_p = xp.post && !xt.post;
    assign rq_p = mkreq(xp.row, q3, fr_p);
    // port_latch=relatch: the slot's waiting I/O (out.relatch 3), port_landed
    assign relatch = xt.relatch;
    assign relatch_late = xt.landed;
    assign relatch_n = 2'd3;

    // ------------------------------------------------------------ S6: the next state
    // latch_start: the byte latched behind a full queue went in on the clock a form whose
    // first step is a clocks step started (and is in it): its clocks begin a clock later
    wire ls_adj = latch_start_now && (t_start || p_start) && q3.res != 11'd0 && q3.k == 3'd1
                  && row_of(q3.tmpl, 3'd0, q3.fmt.w).ls_ok;
    wire [10:0] res_e = t_hold ? hold_res : (q3.res + (ls_adj ? 11'd1 : 11'd0));
    // the take sync's count: in flight + asked on the take clock (a held detached I/O's
    // request not counted; sync_io=issue: nor one asked under the I/O's issue clock)
    wire [1:0]  owed_tk = (inflight_c ? 2'd1 : 2'd0) + (asked_t && !slot_det_c ? 2'd1 : 2'd0);
    wire [1:0]  owed_pk = (inflight_x ? 2'd1 : 2'd0)
                          + (asked_p && !slot_det_p && !g_io ? 2'd1 : 2'd0);
    // the form that ends on this clock: its functional effect (T: the registered form; P:
    // the T pass's)
    wire end_t = t_done_rec || t_try2;
    wire end_p = p_done_rec || p_try2;
    wire end_any = end_t || end_p;
    fregs_t fr_t, fr_p;
    assign fr_t = end_t ? apply(fr, fmt, ob) : fr;           // after the T pass's end
    assign fr_p = end_p ? apply(fr_t, s3.fmt, s3.ob) : fr_t;  // after the P pass's
    // the late datum of a store_imm (its immediate as taken so far: ob 3, 4)
    assign sfr_data = fmt.w ? ob[39:24] : {ob[31:24], ob[31:24]};

    assign pc_o = pc;
    assign cls_o = fmt.cls;
    assign wait_o = t_why;
    assign res_o = res;

    always @(posedge clock) begin
        if (!reset_n) begin
            run <= 1'b0;
            tmpl <= TM_NOP;
            k <= 3'd0;
            res <= 11'd0;
            left <= 3'd0;
            taken <= 3'd0;
            oplen <= 3'd1;
            sync_v <= 1'b0;
            sync_def <= 1'b0;
            owed <= 2'd0;
            armed <= 1'b0;
            own_v <= 1'b0;
            exec_v <= 1'b0;
            ex_age <= 2'd0;
            ex_par <= 1'b0;
            hold_done <= 1'b0;
            abort_start <= 1'b0;
            done_m <= 1'b1;
            wbu <= 2'd0;
            wb_cur <= 2'd0;
            lu_inf <= 1'b0;
            lu <= 3'd0;
            halted <= 1'b0;
            refill <= 1'b0;
            fmt <= '0;
            ob <= 40'd0;
            fr <= FR_RESET;
            pc <= 20'hFFFF0;
        end else if (ce) begin
            run <= q3.run;
            tmpl <= q3.tmpl;
            k <= q3.k;
            res <= res_e == 11'd0 ? 11'd0 : res_e - 11'd1;
            left <= q3.left;
            taken <= q3.taken;
            oplen <= q3.oplen;
            sync_v <= q3.sync_v;
            sync_def <= q3.sync_def;
            if (xp.ask)
                owed <= owed_pk;
            else if (xt.ask)
                owed <= owed_tk;
            else if (ask_d)
                owed <= owed_t;
            else
                owed <= owed_c;
            armed <= q3.armed;
            own_v <= q3.own_v;
            exec_v <= q3.exec_v;
            if (xt.set_exec || xp.set_exec) begin
                ex_age <= 2'd1;
                ex_par <= 1'b1;
            end else begin
                if (ex_age != 2'd3)
                    ex_age <= ex_age + 2'd1;
                ex_par <= !ex_par;
            end
            if (t_hold)
                hold_done <= 1'b1;
            else if (g_fetch || g_abort)
                hold_done <= 1'b0;
            if (t_start || p_start)
                abort_start <= t_start && g_abort;
            done_m <= q3.done_m;
            fmt <= q3.fmt;
            ob <= q3.ob;
            halted <= q3.halted;
            if (xt.flush)
                refill <= 1'b1;
            else if (t_start || p_start)
                refill <= 1'b0;
            // eu.wb_until - t, from the clock a form's steps end (wb_from=end)
            if (end_any)
                wbu <= wb_cur == 2'd0 ? 2'd0 : wb_cur - 2'd1;
            else if (wbu != 2'd0)
                wbu <= wbu - 2'd1;
            if (t_start || p_start)
                wb_cur <= v35_class_stub(q3.fmt.cls).wb;
            // the latches an OUT's detached I/O holds (eu.latch_until): from its post to the
            // end of its cycle
            if (retick && g_io) begin
                lu_inf <= 1'b0;
                lu <= grant_len - 3'd1;         // latch_until = end + 1
            end else begin
                if ((post_t && rq_t.kind == K_IO_WRITE && rq_t.detached)
                    || (post_p && rq_p.kind == K_IO_WRITE && rq_p.detached))
                    lu_inf <= 1'b1;
                if (lu != 3'd0)
                    lu <= lu - 3'd1;
            end
            if (t_start)
                pc <= ir_addr_c;
            else if (p_start)
                pc <= ir_addr_l;
            fr <= fr_p;
        end
    end

    wire unused = &{1'b0, xt.why, xp.why, xt.def, xp.def, xt.complete, xp.complete, xt.cont,
                    xp.cont, xp.relatch, xp.flush, xp.halt, xp.fhold, xp.rt_set, xp.rt_n,
                    xp.retire, xp.wide, xp.set_exec, t_lapse, xt, xp};
endmodule
