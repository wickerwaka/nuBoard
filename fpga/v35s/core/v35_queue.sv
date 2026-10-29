`timescale 1ns/1ps

// V35S prefetch queue (HDL plan, Phase C2), written from the frozen chain model
// (validation/v35s/chains/sim/frozen/queue.py, the Queue; machine.py, eu.py, decoder.py
// and arbiter.py for the clocks and the order it is read and written in) and the spec
// (docs/v35s-chain-rtl-spec.md, A2 "Queue", A3 "From the queue", "Writes the arbiter
// makes", A4 "The request rule and the queue's room", "The latched byte and the queue's
// write port", "The aborted fetch cycle", "The request re-evaluated on a fetch's issue",
// "Refresh: the beaten and lost fetch request").
//
// Storage. Six bytes (V35_QUEUE_BYTES) and, under word_latch=byte_d, the delivered word's
// second byte in a one-byte latch: `count` is len(queue.bytes), the stored bytes plus the
// latched one, which is the youngest (the tail). Inside a clock a word may be delivered
// into six stored bytes the decoder takes from on that clock, so the array holds eight;
// the storage check at the end of the clock (Queue.check) flags `error` above six stored.
// The IR is the decoder's (a seventh byte outside the queue); the decoder's state reaches
// the room function as a snapshot with each op (v35_qsnap: ir, need0, ir_hold, ea, imm16).
//
// Clocking. `ce` marks the END of a model clock: the registers hold the queue's state at
// the end of the last model clock (Machine._clock_row's moment), in the A2
// representations (flags for `== t`, offsets for the stamps ahead, an age for
// requested_at; v35_qstate_t). One model clock is a combinational chain: the clock's
// start (q_begin: the stamps move on a clock), phase C (the bus unit's delivery: arrive,
// or retry_after for any other cycle; data_ready=0), phase A (the aborted cycle's end),
// then NSLOT op stages in the order the other machines act (the EU's tick, the decoder's
// IR load, the arbiter, the post-issue pass: Machine.run's phases T, L, X, P), then phase
// E (q_end_clock: the storage check and the back-to-back decision).
//
// An op is one queue method another machine calls or one store it makes into the queue
// (the frozen model's sites, listed at V35_QOP_*): the decoder's take (with its ModR/M
// commit and the ModR/M's word-mate), commit and IR load; the EU's start, flush, the
// displacement's take clock, HALT, the flag re-evaluations (a retry, the count-latch
// shift's end, a re-raised dropped request), the retry and shift stamps, the I/O drop;
// the arbiter's wants_fetch, the fetch issue (request_reissue=no_mem), the aborted cycle
// (abort_fetch=retry), the refresh's drop and beaten request, the lost request's clocks,
// the re-dating, io_ir_hold, refresh_beat_t4's commit, nop_hold; the EU's grp_disp=hold
// clock (gdisp_until, which the arbiter reads as state); and the reads (room, asked,
// requesting, triple, stored, available) whose value goes back on `rd`.
//
// What the model has and this module keeps: the request rule (room_ir=arrival_idle with
// ea_ir_room and the IR hold, latch_midtake, latch_disp, modrm_mate=imm, room_ir_imm=none,
// request_eval=on_change, request_hold=lapse), the latched byte (word_latch=byte_d,
// latch_read=commit, modrm_port, latch_hold), the in-flight word's reservation, the fetch
// pointer (an odd target: one byte), the flush (discard, flush_hold=start), the aborted
// cycle and its retry (abort_fetch=retry, refresh_abort_retry=next), the back-to-back
// decision (b2b_at, refresh_io_run=pair_out's pair) and the next-clock commits (t4_at),
// count_latch's hold, nop_hold, io_ir_hold, the refresh's beaten and lost request. What
// the model does not read under the fit is not here (room_ir_ready, request_hold=hold,
// io_take=abort, the release-by-word table, the usable clocks, read_t, flush_t, the peak).
// `completed` (the delivered-fetch count the EU's take sync targets) is the `fetch_done`
// strobe; the sync's relative count is the EU's (C3).
// The queue's state and snapshot types, a package so that the arbiter and the core (C4) read
// the per-op states the module exports (state_c, state_op, state_e).
package v35_queue_pkg;
`include "v35_chain_params.svh"

    localparam int V35_Q_STORE = V35_QUEUE_BYTES + V35_QUEUE_WORD;   // bytes inside a clock

    // the decoder's (and the EU's) state an op reads
    typedef struct packed {
        logic imm16;        // room_ir_imm: the EU runs MOV r16,imm16 (class imm, 2 immediate bytes)
        logic ea;           // decoder.ea_end is set and t < ea_end (ea_ir_room)
        logic ir_hold;      // decoder.ir_hold (ir_load=disp_data)
        logic need0;        // decoder.need == 0 (not mid-take)
        logic ir;           // decoder.ir holds an opcode
    } v35_qsnap_t;

    // the queue's state, in the A2 representations (rtl_vectors.QFIELDS, in this order)
    typedef struct packed {
        logic [V35_W_Q_COUNT-1:0]   count;      // len(bytes): stored + the latched byte
        logic [8*V35_Q_STORE-1:0]         data;       // the bytes, head in the low byte
        logic [1:0]                 unc;        // len(uncommitted)
        logic                       latched;
        logic                       latch_full;
        logic                       flag;       // the request flag
        logic                       rq_valid;   // requested_at is set ...
        logic [V35_W_Q_AGE-1:0]     rq_age;     // ... t - requested_at
        logic                       inflight;
        logic [V35_W_ADDR-1:0]      fetch_addr;
        logic                       ab_valid;   // abort_end is set ...
        logic [V35_W_Q_AB_LEFT-1:0] ab_left;    // ... abort_end - t
        logic                       ab_this;    // abort_t == start_t
        logic                       ab_now;     // abort_t == t
        logic                       retry;
        logic                       retry_loop;
        logic                       abort_ref;
        logic                       rt_valid;   // retry_at is set ...
        logic [V35_W_Q_OFF-1:0]     rt_off;     // ... retry_at - t (signed)
        logic                       shift_held;
        logic                       sh_valid;   // shift_until is set ...
        logic [V35_W_Q_OFF-1:0]     sh_off;     // ... shift_until - t (signed)
        logic                       nop_held;   // nop_held set, no start since
        logic                       io_held;    // io_held set ...
        logic                       io_started; // ... and an instruction started since
        logic                       slot_fetch;
        logic                       slot_word;
        logic                       ar_pend;    // after_refresh >= t ...
        logic [V35_W_Q_AR_OFF-1:0]  ar_off;     // ... after_refresh - t
        logic                       ar_fetch;   // after_refresh == the last fetch's start
        logic                       beat_eval;
        logic                       refresh_beaten;
        logic                       dropped;
        logic                       drop_hold;
        logic                       lost_start; // lost_start is set
        logic                       lost_eval;  // lost_eval == t
        logic                       la_valid;   // lost_after is set ...
        logic [V35_W_Q_LA_OFF-1:0]  la_off;     // ... lost_after - t
        logic                       io_run_now; // io_run_at == t
        logic                       io_run_next;// io_run_at == t + 1
        logic                       t4_now;
        logic                       t4_next;
        logic                       b2b_now;    // b2b_at == t
        logic                       b2b_next;   // b2b_at == t + 1
        logic                       halted;
        logic                       discard;
        logic                       fh_valid;   // flush_held is set ...
        logic [V35_W_Q_FH_OFF-1:0]  fh_off;     // ... max(0, flush_held - t)
        logic                       gd_valid;   // gdisp_until is set (grp_disp=hold) ...
        logic [V35_W_Q_GD_OFF-1:0]  gd_off;     // ... max(0, gdisp_until - t)
        logic                       arrived_now;
        logic                       removed_now;
        logic                       ir_now;
        logic                       qport_now;
        logic                       disp_now;
        logic                       mate_now;
        logic                       take_now;
        logic                       take_prev;  // take_t == t - 1
        logic                       start_now;
        logic                       latch_in_now;
        logic [1:0]                 starts;     // saturating at 3 (triple: starts > 2)
    } v35_qstate_t;

    // ---- ops (rtl_vectors.QOPS) and the sites in the frozen model they stand for
    localparam logic [5:0] V35_QOP_NOP = 6'd0;
    localparam logic [5:0] V35_QOP_TAKE = 6'd1;         // decoder.take: a=ModR/M (commit_one), b=mate_t
    localparam logic [5:0] V35_QOP_COMMIT = 6'd2;       // decoder.commit (take_commit=at_end)
    localparam logic [5:0] V35_QOP_IRLOAD = 6'd3;       // decoder.load_ir: take, ir_t, commit
    localparam logic [5:0] V35_QOP_START = 6'd4;        // eu._start: start_t, starts; a: flush_held = t + val
    localparam logic [5:0] V35_QOP_FLUSH = 6'd5;        // eu._flush: queue.flush(val)
    localparam logic [5:0] V35_QOP_DISP = 6'd6;         // eu: disp_t (latch_disp)
    localparam logic [5:0] V35_QOP_HALT = 6'd7;         // eu halt step: queue.halted (halt_refresh)
    localparam logic [5:0] V35_QOP_EVAL = 6'd8;         // flag = room >= 2 (machine P: the IR load)
    localparam logic [5:0] V35_QOP_SHIFT_END = 6'd9;    // eu.tick: count_latch's shift_until reached
    localparam logic [5:0] V35_QOP_RETRY_END = 6'd10;   // eu: retry_at reached (abort_unit=loop, retry_first)
    localparam logic [5:0] V35_QOP_RETRY_SET = 6'd11;   // eu: retry_at = t + val (refresh_retry's += 1 too)
    localparam logic [5:0] V35_QOP_RERAISE = 6'd12;     // eu: dropped = False, flag = room >= 2 (refresh_reraise)
    localparam logic [5:0] V35_QOP_SHIFT_SET = 6'd13;   // eu: shift_until = t + val (count_latch)
    localparam logic [5:0] V35_QOP_SHIFT_HOLD = 6'd14;  // eu: shift_held (count_latch)
    localparam logic [5:0] V35_QOP_DROP_RETRY = 6'd15;  // eu._io_drop, machine io_take=unit: a=retry_loop, b=abort_t == t
    localparam logic [5:0] V35_QOP_WANT = 6'd16;        // wants_fetch (rd)
    localparam logic [5:0] V35_QOP_ASKED = 6'd17;       // asked (rd; take_sync=pending)
    localparam logic [5:0] V35_QOP_REQUESTING = 6'd18;  // requesting (rd; machine P io_ir_hold)
    localparam logic [5:0] V35_QOP_ROOM = 6'd19;        // room / counted / free (rd: room)
    localparam logic [5:0] V35_QOP_TRIPLE = 6'd20;      // triple (rd)
    localparam logic [5:0] V35_QOP_STORED = 6'd21;      // stored (rd)
    localparam logic [5:0] V35_QOP_AVAIL = 6'd22;       // available (rd; data_ready=0: every byte)
    localparam logic [5:0] V35_QOP_ISSUE = 6'd23;       // queue.issue: a=mem_waiting, b=slot_fetch (grp_read)
    localparam logic [5:0] V35_QOP_ABORT = 6'd24;       // queue.abort: a=retry_loop, b=abort_ref
    localparam logic [5:0] V35_QOP_DROP = 6'd25;        // arbiter refresh_drop: a=drop_hold
    localparam logic [5:0] V35_QOP_BEAT = 6'd26;        // arbiter _refresh: after_refresh = t + val; a: in HALT
    localparam logic [5:0] V35_QOP_LOST_EVAL = 6'd27;   // arbiter refresh_lost: evaluated on this start
    localparam logic [5:0] V35_QOP_LOST_HALT = 6'd28;   // ... at HALT's start: lost_after = t + val
    localparam logic [5:0] V35_QOP_LOST_AFTER = 6'd29;  // ... lost_after reached
    localparam logic [5:0] V35_QOP_REDATE = 6'd30;      // arbiter free_hold, grp_io_hold: requested_at = t
    localparam logic [5:0] V35_QOP_IO_HELD_CLR = 6'd31; // arbiter io_ir_hold's release
    localparam logic [5:0] V35_QOP_IO_HELD_SET = 6'd32; // machine P io_ir_hold: requested_at = io_held = t
    localparam logic [5:0] V35_QOP_T4 = 6'd33;          // arbiter refresh_beat_t4: t4_at = t + 1
    localparam logic [5:0] V35_QOP_NOP_HOLD = 6'd34;    // machine P nop_hold: nop_held = t
    localparam logic [5:0] V35_QOP_GDISP = 6'd35;       // eu grp_disp=hold: gdisp_until = t + val
endpackage

module v35_queue
    import v35_queue_pkg::*;
#(
    parameter int NSLOT = 16,               // op stages per clock
    parameter int STATE_W = 180             // $bits(v35_qstate_t), checked below
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,                  // end of a model clock

    // the state at the model's clock 0 (prelude_tail=segs: three words preloaded)
    input  wire [3:0]  init_count,          // V35_W_Q_COUNT (checked below)
    input  wire [63:0] init_data,
    input  wire [19:0] init_fetch_addr,

    // phase C: the cycle whose last clock was the previous one (the bus unit's done)
    input  wire        c_done,
    input  wire        c_fetch,             // ... a fetch: its word to the queue
    input  wire        c_refresh,           // ... a refresh (retry_after's kind)
    input  wire        c_odd,               // the fetch's address is odd: one byte
    input  wire [15:0] c_data,
    input  wire [4:0]  c_snap,              // the decoder's state then (retry_after's room)

    // the clock's ops, in order (V35_QOP_*; v35_qop: code, a, b, val, snap)
    input  wire [NSLOT-1:0][32:0] op,

    // phase E
    input  wire        e_fetch_end,         // bus.current is a fetch whose last clock is this
    input  wire        e_io,                // the EU runs an IN or OUT whose I/O is to come
    input  wire        e_out,               // ... an OUT (refresh_io_run=pair_out)
    input  wire [4:0]  e_snap,              // the decoder's state at the end of the clock

    output wire [NSLOT-1:0][7:0] rd,        // each op's read (or the byte it took)
    output wire        fetch_issue,         // a fetch issued this clock (an issue op)
    output logic [19:0] fetch_issue_addr,    // ... at this address (the bus unit's request)
    output wire        fetch_done,          // `completed` counts one this clock (C or A)
    output reg         error,               // the storage check (QueueOverflow), sticky
    // the state (v35_qstate_t, v35_queue_pkg, MSB first) after phases C and A, after each
    // op stage and at the end of the clock (combinational): the EU's and the arbiter's views
    // of the queue between their ops (C4: the core's ports; B3's bundle as well)
    output wire [STATE_W-1:0] state_c,
    output wire [NSLOT-1:0][STATE_W-1:0] state_op,
    output wire [STATE_W-1:0] state_e
`ifdef V35S_STATE_DUMP
    ,
    // B3 state bundle: the state as registered at the last ce
    output wire [STATE_W-1:0] state_dump
`endif
);

    localparam int STORE = V35_Q_STORE;     // bytes inside a clock



    if ($bits(v35_qstate_t) != STATE_W) begin : g_state_width
        $error("v35_queue: the state is %0d bits, STATE_W %0d", $bits(v35_qstate_t), STATE_W);
    end
    if (V35_W_Q_COUNT != 4 || V35_W_ADDR != 20 || STORE != 8) begin : g_port_widths
        $error("v35_queue: the port widths no longer match the include");
    end

    // ------------------------------------------------ the queue's functions (queue.py)

    // _port_busy: the decoder holds the write port (latch_read=commit; modrm_port: a
    // ModR/M's commit_one is no port use for a byte latched on an earlier clock)
    function automatic logic q_port_busy(input v35_qstate_t s);
        q_port_busy = s.arrived_now ? s.removed_now : (s.qport_now || s.ir_now);
    endfunction

    // room: the request rule's room (room_ir=arrival_idle, ea_ir_room, latch_midtake,
    // latch_disp, modrm_mate=imm, room_ir_imm=none; room_ir_ready=False: no ready test)
    function automatic logic signed [V35_W_ROOM:0] q_room(input v35_qstate_t s,
                                                          input v35_qsnap_t d);
        logic latched_now;
        int used, size;
        // _latched_now (byte_d): only on the delivery clock, with the port held, and not a
        // slot fetch's word
        latched_now = s.latched && s.arrived_now && s.removed_now && !s.slot_word;
        used = int'(s.count) + int'(s.unc) + (s.inflight ? V35_QUEUE_WORD : 0);
        if (!(latched_now && !d.need0) && !(latched_now && s.disp_now))
            used -= int'(latched_now);
        size = V35_QUEUE_BYTES;
        if (s.arrived_now || (d.need0 && !d.imm16)) begin
            if (d.ir_hold && (d.need0 || d.ea))
                used += int'(d.ir);         // ir_load: the IR is no seventh slot
            else begin
                size += 1;                  // the IR's slot
                used += int'(d.ir);
            end
        end
        if (s.arrived_now && s.mate_now)
            used += 1;                      // modrm_mate: the ModR/M's word is not free yet
        q_room = (V35_W_ROOM + 1)'(size - used);
    endfunction

    function automatic logic q_word(input v35_qstate_t s, input v35_qsnap_t d);
        q_word = int'(q_room(s, d)) >= V35_QUEUE_WORD;
    endfunction

    // _evaluates (request_eval=on_change): a queue change on t, the first clock, the lost
    // request's start, a beaten request in HALT
    function automatic logic q_evaluates(input v35_qstate_t s, input logic first);
        q_evaluates = s.lost_eval || (s.refresh_beaten && s.halted)
                      || s.removed_now || s.arrived_now || first;
    endfunction

    // requesting (its value; the op stores it in the flag)
    function automatic logic q_requesting(input v35_qstate_t s, input v35_qsnap_t d,
                                          input logic first);
        if (s.io_run_now || s.t4_now)
            q_requesting = 1'b1;            // refresh_io_run, refresh_beat_t4: committed
        else if (s.dropped && s.drop_hold)
            q_requesting = 1'b0;            // refresh_reraise=unit: lost until the EU raises it
        else if (!q_evaluates(s, first))
            q_requesting = s.flag && q_word(s, d);
        else
            q_requesting = q_word(s, d);
    endfunction

    // latch_hold: a byte delivered before t still latched, and it cannot go in on t
    function automatic logic q_latch_blocks(input v35_qstate_t s);
        q_latch_blocks = s.latched && !s.arrived_now
                         && (q_port_busy(s) || int'(s.count) > V35_QUEUE_BYTES);
    endfunction

    // triple (abort_fetch): a start, an operand take and an IR load on t, past the first LS
    function automatic logic q_triple(input v35_qstate_t s);
        q_triple = s.start_now && s.take_now && s.ir_now && s.starts == 2'd3;
    endfunction

    // pop the head byte (Queue.take): taken through the latch when it was the last
    function automatic v35_qstate_t q_pop(input v35_qstate_t s);
        q_pop = s;
        q_pop.data = s.data >> 8;
        q_pop.count = s.count - 1'b1;
        if (q_pop.count == '0)
            q_pop.latched = 1'b0;           // latched = min(latched, len(bytes))
        q_pop.unc = s.unc + 1'b1;
    endfunction

    // Queue.commit: the take's bytes leave the occupancy; the port is held
    function automatic v35_qstate_t q_commit(input v35_qstate_t s);
        q_commit = s;
        if (s.unc != '0) begin
            q_commit.removed_now = 1'b1;
            q_commit.qport_now = 1'b1;
        end
        q_commit.unc = '0;
    endfunction

    // an unset stamp's offset is 0 (the representation's don't-care, made canonical so the
    // state compares as a whole)
    function automatic v35_qstate_t q_canon(input v35_qstate_t s);
        q_canon = s;
        if (!s.rq_valid) q_canon.rq_age = '0;
        if (!s.ab_valid) q_canon.ab_left = '0;
        if (!s.rt_valid) q_canon.rt_off = '0;
        if (!s.sh_valid) q_canon.sh_off = '0;
        if (!s.ar_pend) q_canon.ar_off = '0;
        if (!s.la_valid) q_canon.la_off = '0;
        if (!s.fh_valid) q_canon.fh_off = '0;
        if (!s.gd_valid) q_canon.gd_off = '0;
    endfunction

    // ------------------------------------------------ the clock's start: stamps move on
    function automatic v35_qstate_t q_begin(input v35_qstate_t r, output logic abort_due);
        v35_qstate_t s;
        s = r;
        if (s.rq_valid && s.rq_age != '1)
            s.rq_age = s.rq_age + 1'b1;
        abort_due = r.ab_valid && r.ab_left == '0;  // abort_end == t - 1
        if (r.ab_valid && r.ab_left != '0)
            s.ab_left = r.ab_left - 1'b1;
        s.ab_now = 1'b0;
        if (s.rt_valid)
            s.rt_off = r.rt_off - 1'b1;
        if (s.sh_valid)
            s.sh_off = r.sh_off - 1'b1;
        if (r.ar_pend) begin
            if (r.ar_off == '0)
                s.ar_pend = 1'b0;           // past
            else
                s.ar_off = r.ar_off - 1'b1;
        end
        s.lost_eval = 1'b0;
        if (r.la_valid && r.la_off != '0)
            s.la_off = r.la_off - 1'b1;
        s.io_run_now = r.io_run_next;
        s.io_run_next = 1'b0;
        s.t4_now = r.t4_next;
        s.t4_next = 1'b0;
        s.b2b_now = r.b2b_next;
        s.b2b_next = 1'b0;
        if (r.fh_valid && r.fh_off != '0)
            s.fh_off = r.fh_off - 1'b1;
        if (r.gd_valid && r.gd_off != '0)
            s.gd_off = r.gd_off - 1'b1;         // grp_disp=hold: t < gdisp_until while > 0
        s.take_prev = r.take_now;
        s.arrived_now = 1'b0;
        s.removed_now = 1'b0;
        s.ir_now = 1'b0;
        s.qport_now = 1'b0;
        s.disp_now = 1'b0;
        s.mate_now = 1'b0;
        s.take_now = 1'b0;
        s.start_now = 1'b0;
        s.latch_in_now = 1'b0;
        q_begin = s;
    endfunction

    // ------------------------------------------------ phase C and A
    // arrive (data_ready=0): the word's bytes are usable at once; the second byte (an odd
    // address's only byte) waits in the latch (word_latch=byte_d); a flush's discard
    function automatic v35_qstate_t q_arrive(input v35_qstate_t s, input logic odd,
                                             input logic [15:0] data);
        q_arrive = s;
        q_arrive.inflight = 1'b0;
        q_arrive.slot_word = s.slot_fetch;
        q_arrive.slot_fetch = 1'b0;
        if (s.discard) begin
            q_arrive.discard = 1'b0;        // fetched before a flush: dropped, no change
        end else begin
            q_arrive.arrived_now = 1'b1;
            q_arrive.latched = 1'b1;
            q_arrive.data[8 * int'(s.count) +: 8] = data[7:0];
            if (odd) begin
                q_arrive.count = s.count + 1'b1;
            end else begin
                q_arrive.data[8 * (int'(s.count) + 1) +: 8] = data[15:8];
                q_arrive.count = s.count + V35_W_Q_COUNT'(V35_QUEUE_WORD);
            end
        end
    endfunction

    // retry_after (abort_fetch=retry): a cycle other than a fetch ended; a request aborted
    // under a refresh waits for the next cycle after it (refresh_abort_retry=next)
    function automatic v35_qstate_t q_retry_after(input v35_qstate_t s, input logic refresh,
                                                  input v35_qsnap_t d);
        q_retry_after = s;
        q_retry_after.abort_ref = 1'b0;
        if (!(s.abort_ref && refresh) && s.retry && !s.retry_loop) begin
            q_retry_after.retry = 1'b0;
            q_retry_after.flag = q_word(s, d);
        end
    endfunction

    // ------------------------------------------------ one op
    function automatic v35_qstate_t q_op(input v35_qstate_t s, input logic [32:0] w,
                                         input logic first, output logic [7:0] rd_o,
                                         output logic issued, output logic err);
        logic [5:0] code;
        logic a, b, raised, want;
        logic [19:0] val;
        v35_qsnap_t d;
        v35_qstate_t n;
        {code, a, b, val, d} = w;
        n = s;
        rd_o = 8'd0;
        issued = 1'b0;
        err = 1'b0;
        case (code)
            V35_QOP_TAKE: begin
                err = s.count == '0;
                rd_o = s.data[7:0];
                n = q_pop(s);
                n.take_now = 1'b1;
                n.take_prev = 1'b0;         // take_t moved to t (take_t >= t-1: either)
                if (b)
                    n.mate_now = 1'b1;
                if (a) begin                // modrm_commit=byte: the ModR/M latch
                    n.unc = n.unc - 1'b1;
                    n.removed_now = 1'b1;
                end
            end
            V35_QOP_COMMIT: n = q_commit(s);
            V35_QOP_IRLOAD: begin
                err = s.count == '0;
                rd_o = s.data[7:0];
                n = q_pop(s);
                n.ir_now = 1'b1;
                n = q_commit(n);
            end
            V35_QOP_START: begin
                n.start_now = 1'b1;
                if (s.starts != 2'd3)
                    n.starts = s.starts + 1'b1;
                n.nop_held = 1'b0;          // _nop_held: start_t > nop_held
                n.io_started = s.io_held;   // io_ir_hold: started since
                n.ab_this = s.ab_now;       // abort_t == start_t
                if (a) begin                // flush_hold=start
                    n.fh_valid = 1'b1;
                    n.fh_off = V35_W_Q_FH_OFF'(val);
                end
            end
            V35_QOP_FLUSH: begin
                n.count = '0;
                n.data = '0;
                n.unc = '0;
                n.latched = 1'b0;
                n.latch_full = 1'b0;
                n.discard = s.inflight && !s.ab_valid;
                n.fetch_addr = val;
                n.flag = 1'b0;
                n.rq_valid = 1'b0;
                n.removed_now = 1'b1;
                n.fh_valid = 1'b0;
            end
            V35_QOP_DISP: n.disp_now = 1'b1;
            V35_QOP_HALT: n.halted = 1'b1;
            V35_QOP_EVAL: n.flag = q_word(s, d);
            V35_QOP_SHIFT_END: begin
                n.sh_valid = 1'b0;
                n.shift_held = 1'b0;
                n.flag = q_word(s, d);
            end
            V35_QOP_RETRY_END: begin
                n.rt_valid = 1'b0;
                if (s.retry) begin
                    n.retry = 1'b0;
                    n.flag = q_word(s, d);
                end
            end
            V35_QOP_RETRY_SET: begin
                n.rt_valid = 1'b1;
                n.rt_off = V35_W_Q_OFF'(val);
            end
            V35_QOP_RERAISE: begin
                n.dropped = 1'b0;
                n.flag = q_word(s, d);
            end
            V35_QOP_SHIFT_SET: begin
                n.sh_valid = 1'b1;
                n.sh_off = V35_W_Q_OFF'(val);
            end
            V35_QOP_SHIFT_HOLD: n.shift_held = 1'b1;
            V35_QOP_DROP_RETRY: begin
                n.flag = 1'b0;
                n.rq_valid = 1'b0;
                n.retry = 1'b1;
                n.retry_loop = a;
                n.ab_this = 1'b1;           // abort_t = the instruction's start clock
                n.ab_now = b;
            end
            V35_QOP_WANT: begin             // wants_fetch
                raised = q_requesting(s, d, first);
                n.flag = raised;
                if (s.fh_valid && s.fh_off == '0 && d.need0)
                    raised = 1'b0;          // flush_hold: a taken transfer runs
                if (s.nop_held)
                    raised = 1'b0;
                want = raised && !s.inflight && !q_latch_blocks(s) && !s.shift_held;
                if (want && !s.rq_valid) begin
                    n.rq_valid = 1'b1;
                    n.rq_age = '0;
                end
                if (!want && !s.inflight)
                    n.rq_valid = 1'b0;
                rd_o = {7'd0, want};
            end
            V35_QOP_ASKED: begin
                if (s.inflight) begin
                    rd_o = {7'd0, q_word(s, d)};
                end else begin
                    raised = q_requesting(s, d, first);
                    n.flag = raised;
                    rd_o = {7'd0, raised};
                end
            end
            V35_QOP_REQUESTING: begin
                raised = q_requesting(s, d, first);
                n.flag = raised;
                rd_o = {7'd0, raised};
            end
            V35_QOP_ROOM: rd_o = 8'(q_room(s, d));
            V35_QOP_TRIPLE: rd_o = {7'd0, q_triple(s)};
            V35_QOP_STORED: rd_o = 8'(s.count - V35_W_Q_COUNT'(s.latched));
            V35_QOP_AVAIL: rd_o = 8'(s.count);
            V35_QOP_ISSUE: begin            // request_reissue=no_mem, refresh_reissue=keep
                issued = 1'b1;
                n.inflight = 1'b1;
                n.dropped = 1'b0;
                n.lost_start = 1'b0;
                n.flag = 1'b0;
                if (!a && (q_evaluates(s, first)
                           || (s.ar_pend && s.ar_off == '0 && s.beat_eval)))
                    n.flag = q_word(n, d);  // the word in flight reserved
                n.rq_valid = 1'b0;
                n.fetch_addr = (s.fetch_addr | 20'd1) + 20'd1;
                n.ar_fetch = s.ar_pend && s.ar_off == '0;
                if (b)
                    n.slot_fetch = 1'b1;
            end
            V35_QOP_ABORT: begin            // an aborted cycle of BASE clocks
                n.inflight = 1'b1;
                n.flag = 1'b0;
                n.rq_valid = 1'b0;
                n.ab_valid = 1'b1;
                n.ab_left = V35_W_Q_AB_LEFT'(V35_BUS_BASE - 1);
                n.ab_now = 1'b1;
                n.ab_this = s.start_now;
                n.retry = 1'b1;
                n.retry_loop = a;
                n.abort_ref = b;
            end
            V35_QOP_DROP: begin             // refresh_drop
                n.flag = 1'b0;
                n.rq_valid = 1'b0;
                n.dropped = 1'b1;
                n.drop_hold = a;
                if (!a)
                    n.lost_start = 1'b1;    // refresh_lost=start
            end
            V35_QOP_BEAT: begin             // refresh_after=fetch_next, halt_refresh
                n.beat_eval = q_evaluates(s, first);
                n.ar_fetch = 1'b0;
                n.ar_pend = !a;
                n.ar_off = V35_W_Q_AR_OFF'(val);
                n.refresh_beaten = !a;
            end
            V35_QOP_LOST_EVAL: begin
                n.lost_start = 1'b0;
                n.lost_eval = 1'b1;
            end
            V35_QOP_LOST_HALT: begin
                n.lost_start = 1'b0;
                n.la_valid = 1'b1;
                n.la_off = V35_W_Q_LA_OFF'(val);
            end
            V35_QOP_LOST_AFTER: begin
                n.la_valid = 1'b0;
                n.lost_eval = 1'b1;
                n.ar_pend = 1'b1;
                n.ar_off = '0;
                n.ar_fetch = 1'b0;
            end
            V35_QOP_REDATE: begin
                n.rq_valid = 1'b1;
                n.rq_age = '0;
            end
            V35_QOP_IO_HELD_CLR: begin
                n.io_held = 1'b0;
                n.io_started = 1'b0;
            end
            V35_QOP_IO_HELD_SET: begin
                n.rq_valid = 1'b1;
                n.rq_age = '0;
                n.io_held = 1'b1;
                n.io_started = 1'b0;
            end
            V35_QOP_T4: n.t4_next = 1'b1;
            V35_QOP_NOP_HOLD: n.nop_held = 1'b1;
            V35_QOP_GDISP: begin            // grp_disp=hold (the arbiter reads t < gdisp_until)
                n.gd_valid = 1'b1;
                n.gd_off = V35_W_Q_GD_OFF'(val);
            end
            default: ;
        endcase
        q_op = q_canon(n);
    endfunction

    // ------------------------------------------------ phase E: end_clock
    function automatic v35_qstate_t q_end_clock(input v35_qstate_t s, input logic fetch_end,
                                                input logic io, input logic out,
                                                input v35_qsnap_t d, input logic first,
                                                output logic err);
        v35_qstate_t n;
        logic raised;
        int room, taking;
        n = s;
        // check: the latched byte enters the queue when the port is free and it fits
        if (s.latched && int'(s.count) <= V35_QUEUE_BYTES && !q_port_busy(s)) begin
            if (s.latch_full)
                n.latch_in_now = 1'b1;      // latch_start
            n.latched = 1'b0;
        end
        if (n.latched && int'(n.count) > V35_QUEUE_BYTES)
            n.latch_full = 1'b1;
        else if (!n.latched)
            n.latch_full = 1'b0;
        err = int'(n.count) - int'(n.latched) > V35_QUEUE_BYTES;
        // the back-to-back decision on a fetch's last clock (_raised: no side effects)
        raised = !n.nop_held && (q_evaluates(n, first) ? q_word(n, d) : n.flag && q_word(n, d));
        room = int'(q_room(n, d));
        taking = int'(!d.ir || !d.need0);   // _taking
        if (fetch_end && raised)
            n.b2b_next = 1'b1;
        else if (fetch_end && n.ar_fetch && io && !n.latched && out && room + taking >= 1) begin
            n.b2b_next = 1'b1;              // refresh_io_run=pair_out
            n.io_run_next = 1'b1;
        end
        q_end_clock = q_canon(n);
    endfunction

    // ------------------------------------------------ the clock's chain
    v35_qstate_t r;                         // the end of the last model clock
    reg first = 1'b1;                       // the model's clock 0 (_evaluates: t == 0)
    v35_qstate_t s_begin, s_c, s_e;
    logic abort_due;
    logic [NSLOT-1:0] issued, op_err;
    logic [NSLOT-1:0][19:0] issue_at;
    logic e_err, c_err;

    // abort_done's clock in its own process: fetch_done reaches the EU (its take sync) before
    // the EU's snapshot reaches phase C here (C4's core, no circular process)
    always_comb abort_due = r.ab_valid && r.ab_left == '0;

    always_comb begin
        logic due;
        s_begin = q_begin(r, due);
        s_c = s_begin;
        c_err = 1'b0;
        if (c_done && c_fetch) begin
            c_err = s_begin.latched && !s_begin.discard;   // a word into a full latch
            s_c = q_arrive(s_begin, c_odd, c_data);
        end else if (c_done) begin
            s_c = q_retry_after(s_begin, c_refresh, v35_qsnap_t'(c_snap));
        end
        if (abort_due) begin                // abort_done: the aborted cycle ends
            s_c.inflight = 1'b0;
            s_c.ab_valid = 1'b0;
        end
        s_c = q_canon(s_c);
    end

    for (genvar i = 0; i < NSLOT; i++) begin : g_op
        v35_qstate_t s_in, s_out;
        logic [7:0] rd_i;
        logic issued_i, err_i;
        if (i == 0) begin : g_first
            assign s_in = s_c;
        end else begin : g_next
            assign s_in = g_op[i - 1].s_out;
        end
        always_comb s_out = q_op(s_in, op[i], first, rd_i, issued_i, err_i);
        assign rd[i] = rd_i;
        assign issued[i] = issued_i;
        assign op_err[i] = err_i;
        assign issue_at[i] = issued_i ? s_in.fetch_addr : 20'd0;
    end

    always_comb s_e = q_end_clock(g_op[NSLOT - 1].s_out, e_fetch_end, e_io, e_out,
                                  v35_qsnap_t'(e_snap), first, e_err);

    // the fetch address of the clock's issue: the pointer before the issue op (one a clock)
    always_comb begin
        fetch_issue_addr = 20'd0;
        for (int i = 0; i < NSLOT; i++)
            fetch_issue_addr = fetch_issue_addr | issue_at[i];
    end
    assign fetch_issue = |issued;
    assign fetch_done = (c_done && c_fetch) || abort_due;

    always @(posedge clock) begin
        if (!reset_n) begin
            r <= '0;
            r.count <= init_count;
            r.data <= init_data;
            r.fetch_addr <= init_fetch_addr;
            r.drop_hold <= 1'b1;            // refresh_reraise=unit's start value
            first <= 1'b1;
            error <= 1'b0;
        end else if (ce) begin
            r <= s_e;
            first <= 1'b0;
            if (c_err || |op_err || e_err)
                error <= 1'b1;
        end
    end

    assign state_c = s_c;
    for (genvar i = 0; i < NSLOT; i++) begin : g_state
        assign state_op[i] = g_op[i].s_out;
    end
    assign state_e = s_e;
`ifdef V35S_STATE_DUMP
    assign state_dump = r;
`endif
endmodule
