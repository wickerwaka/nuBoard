`timescale 1ns/1ps

// V35S core v2: the prefetch queue as a simple machine (docs/v35s-queue-strategy.md, Q1;
// (step D) docs/v35s-core-v2-interfaces.md 3.2: a self-contained FIFO).
//
// Six storage bytes, a stored count, a prefetch pointer, the head byte's address and a request
// line. The queue knows nothing of forms, classes, rows
// or the execution unit's steps: the decoder pops the bytes it takes (`pop_n`: the storage is
// freed, the window moves on), flushes the queue on a transfer (the new stream's offset) and
// suspends prefetching; the bus unit samples the request line at its decision point (once a
// clock, at the end of tick A) and reports a fetch's start and its word's delivery.
//
//   fetch_req   (qprobe rules 1, 2; consol) the request line, a level: the occupancy (the
//               queue's own count `ob` of the bytes fetched and not released, this clock's
//               delivery added, this clock's releases `rls` taken) at most 4; low on a flush and
//               the four clocks after it (rule 5: the target's fetch starts five clocks after the
//               flush), and while suspended. The five-held continuation (at most 5 on the clock
//               after a fetch's last clock: lv_q.r5), the give-way and HALT's stop (rule 11) are
//               the bus unit's (the pace). Replaces (E1 M2) below: the line reads this clock's
//               releases, not the registered count.
//   (was)       the request line, a level: room for a word and not suspended. (E1) The room is
//               the queue's own count as it stands at the start of the clock: the bytes it holds
//               (this clock's delivery included, this clock's pops not) plus 2 for a word in
//               flight, at most QUEUE_BYTES - 2 (the six storage bytes: a word issued now always
//               has its two places in the storage). Two mechanisms, each one definition:
//               (E1 M1) the queue is six bytes: nothing beyond the storage counts as room
//               (the V30's measured geometry, biu_model.md exp 1: depth never above 6, no
//               fetch started at 5); (E1 M2) the line is formed from the registered count, so
//               a pop's room reaches the bus unit's decision on the next clock (a pipeline
//               stage between the queue's read side and the bus unit's request input)
//   fetch_addr  {PS, 0} + pfp with the 16-bit wrap (on a flush's clock the old stream's: qprobe round 16);
//               an odd pfp (an odd transfer target) fetches its word and drops the low byte
//   vb0, vb1,   the head window and the stored count, this clock's delivery bypassed (S1
//   avail       before the pop)
//   hip         (step D) the head byte's offset in PS: the next byte the decoder pops (the
//               instruction pointer's source), counted by the pops, loaded by a flush
//
// (E2) The latch is gone: with the six-byte room (E1 M1) a seventh byte is never held, so the
// latch (`lat`, `lat_byte`, `lat_t`: the window's seventh byte) never loaded; it is removed with
// the loader's head-select candidates that read it (h_lat / h_latv / h_latt) and the latch's
// next value (latv_nx). `+v35_chk` checks that no more than six bytes are ever held.
// (Step D) The rule-only room terms are gone: the read / release split (`unrel`: bytes read and
// still counted until the loader released them), the staging slot's count (`stg`), the
// delivered word's second byte uncounted on a releasing clock (`unc_a`) and latched there, the
// latch's hold of the request line (`lat_hold`), the aborted cycle's word in flight, the fitted
// low hint (`q_low`) and the triple clock's room test (`q_word`).
//
// Registered state (widths): q 6x8, cnt 3, pfp 16, hip 16, inflight 1, discard 1, odd 1; the
// tags q_t 6x6.
//
// Two ticks (S7b): tick A (from ce_a) computes the window, the counts after the delivery and
// tick A's pops (the operand pops, the IR load) and the request line. The ce_a update reads
// tick A's inputs through the ce_b registers.
//
// The ports by kind. The FIFO's own: the fetch port (fetch_req / fetch_addr out; fetch_go
// accepted, dlv_v the word valid, dlv_data the word in), the read port (vb0 / vb1, avail and
// hip: the head bytes, how many are valid, the head's address), the pop (`pop_n`, 0 to 2 bytes
// a clock), the control (flush with the new offset, susp). The fetch in flight is held here as
// FIFO state: `inflight` (a word owed, the room counts it), `odd` (its parity, the byte the
// queue drops) and `discard` (a flushed word still owed); the bus unit holds the cycle.
// Untouched (step E): the tags (dlv_tag in, h_q0t out), the head facts the loader's head select
// reads (stored, h_q0, h_odd: MX5b), the next values (stored_nx, odd_nx, discard_nx: the
// sequencer's registered stall through the loader's q_stall_nx).
module v35_queue
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    // the bus unit
    output wire        fetch_req,
    output wire [19:0] fetch_addr,
    input  wire        fetch_go,        // a fetch issued now (S4)
    input  wire        dlv_v,           // a fetch's word is delivered now (S0)
    input  wire [15:0] dlv_data,
    // (MX5c) the delivered word's byte tags (high byte's, low byte's): bits stored beside each
    // byte and kept with it through the storage and the latch, opaque to the queue (the loader
    // forms and reads them)
    input  wire [2*QTAG_W-1:0] dlv_tag,
    // the decoder
    output wire [7:0]  vb0, vb1,
    output wire [2:0]  avail,
    output reg  [15:0] hip,             // (step D) the head byte's offset in PS
    output wire [2:0]  stored,          // (MX0b) the bytes stored (not this clock's delivery):
                                        //   the word register loads from these
    // (MX5b) the queue's own registered facts (the loader's head-byte decode reads them before
    // the head select): the first stored byte, the in-flight word's parity. Registers of the
    // queue's state, nothing of an instruction
    output wire [7:0]  h_q0,
    output wire        h_odd,
    output wire [QTAG_W-1:0] h_q0t,     // (MX5c) the first stored byte's tag
    // (MX5c) the next values of its registers the stall's byte counts read (tick B: what the
    // coming ce_a loads): the stored count, the in-flight word's parity, the discard of a
    // flushed word in flight
    output wire [2:0]  stored_nx,
    output wire        odd_nx,
    output wire        discard_nx,
    input  wire [1:0]  pop_n,           // (step C) the pop: bytes leaving the head this clock, 0
                                        //   to 2 (tick A: an operand pop, the IR load)
    input  wire        flush,           // clear the queue, the stream from flush_addr (tick A)
    input  wire [15:0] flush_addr,      // the new stream's offset (the EU's flush target)
    input  wire [15:0] reset_ip,        // (step D) in reset: the first fetch's offset
    input  wire        susp,            // suspend prefetch: the request line held low (tick A)
    // (qprobe rules 1, 3; consol) the releases: the bytes this clock's word releases from the
    // occupancy (the loader's count of the word's ro / rl and the ModR/M byte's, tick A). The
    // queue owns the occupancy (`ob`, below) and every compare on it
    input  wire [2:0]  rls,
    // (consol) the count's compares for the bus unit's pace (v35_front_pkg): this clock's after
    // its releases (tick A: lv_q) and the next clock's before them (tick B: lv_nx, for either
    // delivery). The line (fetch_req) is the threshold of 4; the five-held continuation (lv_q.r5),
    // the give-way and HALT's stop are the bus unit's (round 6 the queue read the boundary, the
    // request word, the give-way and HALT's stop here)
    output v35_lvq_t   lv_q,
    output v35_lvn_t   lv_nx,
    input  wire [19:0] ps_base          // {PS, 0} (after this clock's far transfer)
);
    // ((E1 M1) the six-byte room, CAP = QUEUE_BYTES, is replaced by the occupancy's thresholds)
    // (qprobe rule 1) the storage: seven bytes (the model's six and one). The occupancy (the bytes fetched and not
    // released) is never above 7 (a fetch starts at most at 5); the bytes stored are that less
    // the staging register's opcode and the bytes popped and not released, plus at most the one
    // opcode released and not popped (between N and E, the staging register then full): with
    // operand bytes owed the staging register is empty and all seven can be the queue's
    localparam int QN = QUEUE_BYTES + 1;
    // (step C) the pop as the read count the arithmetic below was written for
    wire [2:0]  rd = {1'b0, pop_n};

    // ------------------------------------------------------------ registered state
    reg [7:0]  q [0:QN-1];
    reg [2:0]  cnt = 3'd0;
    reg [15:0] pfp = 16'd0;
    initial hip = 16'd0;
    reg        inflight = 1'b0;
    reg        discard = 1'b0;
    reg        odd = 1'b0;
    // (MX5c) the bytes' tags: each written with its byte, from the same window position
    reg [QTAG_W-1:0] q_t [0:QN-1];

    integer i;
    initial for (i = 0; i < QN; i = i + 1) q[i] = 8'h00;
    initial for (i = 0; i < QN; i = i + 1) q_t[i] = '0;

    // ------------------------------------------------------------ S1: the delivery
    wire       arrive = dlv_v && !discard;
    wire [7:0] a0 = odd ? dlv_data[15:8] : dlv_data[7:0];
    wire [7:0] a1 = dlv_data[15:8];
    // the window: the stored bytes, then the delivered ones
    wire [2:0] n_arr = !arrive ? 3'd0 : (odd ? 3'd1 : 3'd2);
    wire [3:0] cnt_s = {1'b0, cnt};
    wire [3:0] avail_w = cnt_s + {1'b0, n_arr};
    assign avail = avail_w > 4'd7 ? 3'd7 : avail_w[2:0];
    assign stored = cnt;
    assign h_q0 = q[0];
    assign h_odd = odd;
    assign h_q0t = q_t[0];
    wire [QTAG_W-1:0] a0t = odd ? dlv_tag[QTAG_W +: QTAG_W] : dlv_tag[0 +: QTAG_W];
    wire [QTAG_W-1:0] a1t = dlv_tag[QTAG_W +: QTAG_W];

    function automatic logic [7:0] seqb(input logic [3:0] k);
        if (k < {1'b0, cnt})
            seqb = q[k[2:0]];
        else if (k == cnt_s)
            seqb = a0;
        else
            seqb = a1;
    endfunction
    // (MX5c) the tag of the window's byte k (seqb's choice)
    function automatic logic [QTAG_W-1:0] seqt(input logic [3:0] k);
        if (k < {1'b0, cnt})
            seqt = q_t[k[2:0]];
        else if (k == cnt_s)
            seqt = a0t;
        else
            seqt = a1t;
    endfunction
    assign vb0 = seqb(4'd0);
    assign vb1 = seqb(4'd1);

    // ------------------------------------------------------------ tick A: the request line
    // (E1 M2) The occupancy at the start of the clock: the window (this clock's delivery in)
    // plus 2 for a word in flight (a fetch issued on an earlier clock whose word is not
    // delivered now); this clock's pops are not read (their room is seen on the next clock).
    // The line is up while that is at most CAP - 2 (a flush empties the queue: only a word in
    // flight counts). Registers only: the decoder's pop is no longer on the request line
    // (qprobe rules 1, 2) the occupancy after this clock's releases against the threshold: 4,
    // or 5 on the clock after a fetch's last clock when no dispatch word executes (a fetch in
    // flight holds the bus: the line is read on a free bus only); none during the flush wait
    reg  [2:0] flw = 3'd0;              // (qprobe rule 5) the clocks of the flush wait left
    // (consol) The occupancy is the queue's own register: `ob`, the bytes fetched and not
    // released, this clock's delivery not yet counted (two's complement). Each clock it gains the
    // delivered bytes and loses the releases; a flush empties it. (Round 6 formed it from the
    // window and the loader's `oadj`: the bytes taken out of the queue and not released, which
    // the loader counted from the pops; the pops move bytes between the two and cancel. The
    // loader's dispatch-time reset of its part, a correction for releases off the pops, never
    // acted: `+v35_chk` compares ob with the window and the loader's reference every clock.)
    reg  signed [4:0] ob = 5'sd0;
    wire signed [4:0] n_ab = {2'b00, n_arr};
`ifndef SYNTHESIS
    wire signed [4:0] occ = ob + n_ab - $signed({2'b00, rls});      // (the reference's and qdbg's)
`endif
    // (qprobe rules 1, 2) the line: the count after this clock's releases at most 4; at most 5
    // on the clock after a fetch's last clock (lv_q.r5) when the bus unit allows the
    // continuation (no dispatch word executes now and no request word executed on the last
    // clock: REQ_PRI); none during the flush wait or while suspended
    // (qprobe round 16, spec 12 C1; the model's FLUSH_B2B / FLUSH_GAP) the flush's own clock: the
    // back-to-back fetch the five-held continuation would start there (a word delivered now, five
    // or fewer held after this clock's releases) is still made, from the old stream's offset; its
    // word is discarded (`fdb`: a flushed stream's back-to-back fetch in flight, the line low
    // while it runs) and the target's fetch waits three clocks after its delivery (flw reloaded
    // with 2 there). Every other line stays low on the flush clock and in the flush wait
    reg        fdb = 1'b0;
    wire       pv = !flush && flw == 3'd0 && !fdb;
    wire       pvf = flush && flw == 3'd0 && !fdb;
    // (timing repair 1) the compares on the count without its sum: `occ <= T` is
    // `rls >= ob + n_ab - T`, and ob, odd and discard are ce_a registers, so the right-hand side
    // is formed in tick B from their next values (ob_nx, odd_nx) and registered beside them at
    // ce_a, once for no delivery (`*n`) and once for a delivered word (`*a`, ob + its bytes);
    // the delivery (arrive: dlv_v and not discard) selects. A bound is kept as {<= 0, > 7, its
    // low three bits} (`v35_qk_t`); `+v35_chk` compares each compare with the direct
    // arithmetic every clock
    typedef struct packed {
        logic       z, b;
        logic [2:0] v;
    } v35_qk_t;
    function automatic v35_qk_t qk_f(input logic signed [5:0] k);
        qk_f.z = k <= 6'sd0;
        qk_f.b = k > 6'sd7;
        qk_f.v = k[2:0];
    endfunction
    function automatic logic qge(input logic [2:0] r, input v35_qk_t k);
        qge = k.z || (!k.b && r >= k.v);
    endfunction
    v35_qk_t   k4n, k4a, k5a, kfn, kfa;
    wire       le4 = arrive ? qge(rls, k4a) : qge(rls, k4n);
    assign fetch_req = pv && le4 && !susp;
    assign lv_q.r5 = (pv || pvf) && qge(rls, k5a) && arrive && !susp;
    assign lv_q.c4 = pv && le4;
    assign lv_q.cf = pv && (arrive ? qge(rls, kfa) : qge(rls, kfn));
    assign lv_q.nrl = rls == 3'd0;
    // (MX5) the fetch address from pfp. (qprobe round 16) No fetch of the new stream is granted on
    // the flush's clock (the line is low there but for the old stream's continuation, which
    // fetches at pfp), so the flush's offset no longer selects here (its sum fa_f is gone)
    wire [19:0] fa_n = ps_base + {4'd0, pfp};
    assign fetch_addr = fa_n;
`ifndef SYNTHESIS
    // the direct arithmetic: the reference of `+v35_chk`
    wire       freq_x = !flush && flw == 3'd0 && !fdb && !susp && $signed(ob + n_ab - $signed({2'b00, rls})) <= 5'sd4;
    wire [15:0] pfp_x = pfp;
    wire [19:0] faddr_x = ps_base + {4'd0, pfp_x};
`endif

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg  [2:0]  rd_r = 3'd0;
    reg         flush_r = 1'b0, go_r = 1'b0;
    reg  [15:0] faddr_r = 16'd0;
    always @(posedge clock) begin
        if (ce_b) begin
            rd_r <= rd;
            flush_r <= flush;
            rls_r <= rls;
            go_r <= fetch_go;
            faddr_r <= flush_addr;
        end
    end

    // ------------------------------------------------------------ next state (ce_a)
    wire [2:0]  reads = rd_r;
    wire [3:0]  cnt_e = flush_r ? 4'd0 : avail_w - {1'b0, reads};
    wire [15:0] pfp_g = flush_r ? faddr_r : pfp;
    // (E2) at most six bytes are held (the request line's room, E1 M1: `+v35_chk`)
    assign stored_nx = cnt_e[2:0];
    wire        unused_e3 = cnt_e[3];    // (E2) never set (the chk's overflow test reads it)
    assign odd_nx = go_r ? pfp_g[0] : odd;
    wire        fdb_nx = (go_r && flush_r) ? 1'b1 : dlv_v ? 1'b0 : fdb;
    wire [2:0]  flw_nx = flush_r ? 3'd4 : (fdb && dlv_v) ? 3'd2 : flw != 3'd0 ? flw - 3'd1 : 3'd0;
    wire       pv_nx = flw_nx == 3'd0 && !fdb_nx;          // (qprobe round 6) the flush wait over on the next clock
    // (consol) the count on the next clock before its releases (`ob` as the coming ce_a loads
    // it, with the next clock's delivery for lv_nx.a) and its compares (the loader's c4_nx,
    // c5_nx, cf_nx, b4_nx and ew_nx's counts before)
    reg  [2:0]  rls_r = 3'd0;
    wire signed [4:0] ob_nx = flush_r ? 5'sd0 : ob + n_ab - $signed({2'b00, rls_r});
    wire signed [4:0] ar_nx = odd_nx ? 5'sd1 : 5'sd2;      // a delivered word's bytes then
    function automatic v35_lvc_t lvc_f(input logic signed [4:0] o, input logic dl);
        lvc_f.c4 = pv_nx && o <= 5'sd4;
        lvc_f.c5 = pv_nx && o <= 5'sd5;
        lvc_f.cf = pv_nx && o + ar_nx <= 5'sd5;
        lvc_f.b4 = dl && o <= 5'sd4;
        lvc_f.lt3 = o < 5'sd3;
        lvc_f.lt2 = o < 5'sd2;
    endfunction
    assign lv_nx.n = lvc_f(ob_nx, 1'b0);
    // (timing repair 1) the bounds as the coming ce_a leaves ob and odd (in reset: ob 0, odd 0)
    function automatic logic [24:0] qkb_f(input logic signed [4:0] o, input logic signed [4:0] ar);
        logic signed [5:0] sn, sa, a6;
        sn = {o[4], o};
        a6 = {ar[4], ar};
        sa = sn + a6;
        qkb_f = {qk_f(sn - 6'sd4),             // k4n
                 qk_f(sa - 6'sd4),             // k4a
                 qk_f(sa - 6'sd5),             // k5a
                 qk_f(sn + a6 - 6'sd5),        // kfn
                 qk_f(sa + a6 - 6'sd5)};       // kfa
    endfunction
    wire [24:0] qkb_nx = qkb_f(ob_nx, ar_nx);
    localparam logic [24:0] QKB_RST = qkb_f(5'sd0, 5'sd2);
    initial {k4n, k4a, k5a, kfn, kfa} = QKB_RST;
    assign lv_nx.a = discard_nx ? lvc_f(ob_nx, 1'b0) : lvc_f(ob_nx + ar_nx, 1'b1);
    assign discard_nx = go_r ? flush_r : (flush_r && inflight && !dlv_v) ? 1'b1 : dlv_v ? 1'b0
                      : discard;
    always @(posedge clock) begin
        if (!reset_n) begin
            cnt <= 3'd0;
            ob <= 5'sd0;
            {k4n, k4a, k5a, kfn, kfa} <= QKB_RST;
            flw <= 3'd0;
            pfp <= reset_ip;
            hip <= reset_ip;
            inflight <= 1'b0;
            discard <= 1'b0;
            fdb <= 1'b0;
            odd <= 1'b0;
        end else if (ce_a) begin
            for (i = 0; i < QN; i = i + 1) begin
                q[i] <= seqb(4'(i) + {1'b0, reads});
                q_t[i] <= seqt(4'(i) + {1'b0, reads});
            end
            cnt <= stored_nx;
            ob <= ob_nx;
            {k4n, k4a, k5a, kfn, kfa} <= qkb_nx;
            // (qprobe rule 5) the flush wait: the line low four clocks after the flush's
            flw <= flw_nx;
            fdb <= fdb_nx;
            // (step D) the head's offset: a flush's target, else counted by the pops
            hip <= flush_r ? faddr_r : hip + {13'd0, reads};
            if (go_r) begin
                inflight <= 1'b1;
                odd <= pfp_g[0];
                // (qprobe round 16) the old stream's continuation granted on the flush's clock:
                // its word discarded, the stream from the flush's offset
                pfp <= flush_r ? faddr_r : (pfp_g | 16'd1) + 16'd1;
                discard <= flush_r;
            end else begin
                if (dlv_v)
                    inflight <= 1'b0;
                if (flush_r)
                    pfp <= faddr_r;
                if (dlv_v)
                    discard <= 1'b0;
                if (flush_r && inflight && !dlv_v)
                    discard <= 1'b1;
            end
        end
    end

`ifndef SYNTHESIS
    // +v35_diag: more than seven bytes held
    reg diag = 1'b0;
    reg ovf = 1'b0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (reset_n && ce_a && !ovf && cnt_e > 4'(QN)) begin   // (qprobe) more than seven held
            ovf <= 1'b1;
            if (diag)
                $display("v35: queue overflow");
        end
    end
    // +v35_qdbg=FILE: the queue's state each clock (bring-up)
    integer qfd = 0;
    string qfn;
    integer qt = 0;
    initial if ($value$plusargs("v35_qdbg=%s", qfn)) qfd = $fopen(qfn, "w");
    always @(posedge clock) begin
        if (qfd != 0 && reset_n && ce_a) begin
            $fdisplay(qfd, "q %0d cnt %0d inf %0d dlv %0d rd %0d occ %0d req %0d susp %0d go %0d rls %0d",
                      qt, cnt, inflight, dlv_v, rd_r, $signed(occ), fetch_req, susp, go_r, rls);
            qt <= qt + 1;
        end
    end
    // (S7b) chk: the ce_b registers against their sources at ce_a
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (rd_r !== rd || flush_r !== flush || go_r !== fetch_go || faddr_r !== flush_addr || rls_r !== rls
                // (MX5) the request line against the direct arithmetic
                || fetch_req !== freq_x || fetch_addr !== faddr_x
                // (E1 M1, E2) with the six-byte room no seventh byte is ever held
                || cnt_e > 4'(QN)) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue: a tick A input changed in tick B at %0t", $time);
            end
        end
    end
    // (timing repair 1) the registered bounds against the direct arithmetic, every clock
    integer tqk_n = 0;
    wire signed [4:0] occ_x = occ;
    always @(posedge clock) begin
        if (chk_on && reset_n
            && (fetch_req !== (pv && occ_x <= 5'sd4 && !susp)
                || lv_q.r5 !== ((pv || pvf) && occ_x <= 5'sd5 && dlv_v && !discard && !susp)
                || lv_q.c4 !== (pv && occ_x <= 5'sd4)
                || lv_q.cf !== (pv && occ_x + (odd ? 5'sd1 : 5'sd2) <= 5'sd5))) begin
            tqk_n = tqk_n + 1;
            if (tqk_n <= 20)
                $display("v35 chk: queue: the registered bounds off the count at %0t", $time);
        end
    end
    final if (chk_on && tqk_n != 0)
        $display("v35 chk: queue: %0d clocks with the bounds off the count", tqk_n);
    final if (chk_on && chk_n != 0)
        $display("v35 chk: queue: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
endmodule
