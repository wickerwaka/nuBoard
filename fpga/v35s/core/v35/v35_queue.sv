`timescale 1ns/1ps

// V35S core v2: the prefetch queue as a simple machine (docs/v35s-queue-strategy.md, Q1;
// (step D) docs/v35s-core-v2-interfaces.md 3.2: a self-contained FIFO).
//
// Six storage bytes and a one-byte latch (a seventh byte), a stored count, a prefetch pointer,
// the head byte's address and a request line. The queue knows nothing of forms, classes, rows
// or the execution unit's steps: the decoder pops the bytes it takes (`pop_n`: the storage is
// freed, the window moves on), flushes the queue on a transfer (the new stream's offset) and
// suspends prefetching; the bus unit samples the request line at its decision point (once a
// clock, at the end of tick A) and reports a fetch's start and its word's delivery.
//
//   fetch_req   the request line, a level: room for a word and not suspended. (E1) The room is
//               the queue's own count as it stands at the start of the clock: the bytes it holds
//               (this clock's delivery included, this clock's pops not) plus 2 for a word in
//               flight, at most QUEUE_BYTES - 2 (the six storage bytes: a word issued now always
//               has its two places in the storage). Two mechanisms, each one definition:
//               (E1 M1) the queue is six bytes: nothing beyond the storage counts as room
//               (the V30's measured geometry, biu_model.md exp 1: depth never above 6, no
//               fetch started at 5); (E1 M2) the line is formed from the registered count, so
//               a pop's room reaches the bus unit's decision on the next clock (a pipeline
//               stage between the queue's read side and the bus unit's request input)
//   fetch_addr  {PS, 0} + pfp with the 16-bit wrap (a flush on this clock: the new stream's);
//               an odd pfp (an odd transfer target) fetches its word and drops the low byte
//   vb0, vb1,   the head window and the stored count, this clock's delivery bypassed (S1
//   avail       before the pop)
//   hip         (step D) the head byte's offset in PS: the next byte the decoder pops (the
//               instruction pointer's source), counted by the pops, loaded by a flush
//
// The latch: the window's seventh byte waits in the latch register (`lat`, `lat_byte`) and is
// in the window behind the stored ones; it moves into the storage when there is a place.
// (E1) With the six-byte room (M1) a seventh byte is never held, so the latch never loads
// (`+v35_chk` checks it every clock); it is left in place, unreachable, for the overseer to
// remove with the loader's head select (h_lat / h_latv) when the tags are reworked.
// (Step D) The rule-only room terms are gone: the read / release split (`unrel`: bytes read and
// still counted until the loader released them), the staging slot's count (`stg`), the
// delivered word's second byte uncounted on a releasing clock (`unc_a`) and latched there, the
// latch's hold of the request line (`lat_hold`), the aborted cycle's word in flight, the fitted
// low hint (`q_low`) and the triple clock's room test (`q_word`).
//
// Registered state (widths): q 6x8, cnt 3, pfp 16, hip 16, inflight 1, discard 1, odd 1, lat 1,
// lat_byte 8; the tags q_t 6x6, lat_t 6.
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
// Untouched (step E): the tags (dlv_tag in, h_q0t / h_latt out), the head facts the loader's
// head select reads (stored, h_q0, h_lat, h_latv, h_odd: MX5b), the next values (stored_nx,
// latv_nx, odd_nx, discard_nx: the sequencer's registered stall through the loader's
// q_stall_nx).
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
    output wire [2:0]  stored,          // (MX0b) the bytes stored (not this clock's delivery,
                                        //   not the latch): the word register loads from these
    // (MX5b) the queue's own registered facts (the loader's head-byte decode reads them before
    // the head select): the first stored byte, the latched byte, the latch's bit,
    // the in-flight word's parity. Registers of the queue's state, nothing of an instruction
    output wire [7:0]  h_q0,
    output wire [7:0]  h_lat,
    output wire        h_latv,
    output wire        h_odd,
    output wire [QTAG_W-1:0] h_q0t,     // (MX5c) the first stored byte's tag, the latched byte's
    output wire [QTAG_W-1:0] h_latt,
    // (MX5c) the next values of its registers the stall's byte counts read (tick B: what the
    // coming ce_a loads): the stored count, the latch's bit, the in-flight word's parity, the
    // discard of a flushed word in flight
    output wire [2:0]  stored_nx,
    output wire        latv_nx,
    output wire        odd_nx,
    output wire        discard_nx,
    input  wire [1:0]  pop_n,           // (step C) the pop: bytes leaving the head this clock, 0
                                        //   to 2 (tick A: an operand pop, the IR load)
    input  wire        flush,           // clear the queue, the stream from flush_addr (tick A)
    input  wire [15:0] flush_addr,      // the new stream's offset (the EU's flush target)
    input  wire [15:0] reset_ip,        // (step D) in reset: the first fetch's offset
    input  wire        susp,            // suspend prefetch: the request line held low (tick A)
    input  wire [19:0] ps_base          // {PS, 0} (after this clock's far transfer)
);
    // (E1 M1) the queue's capacity: its six storage bytes (was QUEUE_BYTES + 1, the latch
    // counted as a seventh place)
    localparam int CAP = QUEUE_BYTES;
    // (step C) the pop as the read count the arithmetic below was written for
    wire [2:0]  rd = {1'b0, pop_n};

    // ------------------------------------------------------------ registered state
    reg [7:0]  q [0:5];
    reg [2:0]  cnt = 3'd0;
    reg [15:0] pfp = 16'd0;
    initial hip = 16'd0;
    reg        inflight = 1'b0;
    reg        discard = 1'b0;
    reg        odd = 1'b0;
    reg        lat = 1'b0;              // the latched byte
    reg [7:0]  lat_byte = 8'h00;
    // (MX5c) the bytes' tags: each written with its byte, from the same window position
    reg [QTAG_W-1:0] q_t [0:5];
    reg [QTAG_W-1:0] lat_t = '0;
    wire       lat_v = lat;

    integer i;
    initial for (i = 0; i < 6; i = i + 1) q[i] = 8'h00;
    initial for (i = 0; i < 6; i = i + 1) q_t[i] = '0;

    // ------------------------------------------------------------ S1: the delivery
    wire       arrive = dlv_v && !discard;
    wire [7:0] a0 = odd ? dlv_data[15:8] : dlv_data[7:0];
    wire [7:0] a1 = dlv_data[15:8];
    // the window: the stored bytes, the latched one, then the delivered ones
    wire [2:0] n_arr = !arrive ? 3'd0 : (odd ? 3'd1 : 3'd2);
    wire [3:0] cnt_s = {1'b0, cnt} + (lat_v ? 4'd1 : 4'd0);
    wire [3:0] avail_w = cnt_s + {1'b0, n_arr};
    assign avail = avail_w > 4'd7 ? 3'd7 : avail_w[2:0];
    assign stored = cnt;
    assign h_q0 = q[0];
    assign h_lat = lat_byte;
    assign h_latv = lat_v;
    assign h_odd = odd;
    assign h_q0t = q_t[0];
    assign h_latt = lat_t;
    wire [QTAG_W-1:0] a0t = odd ? dlv_tag[QTAG_W +: QTAG_W] : dlv_tag[0 +: QTAG_W];
    wire [QTAG_W-1:0] a1t = dlv_tag[QTAG_W +: QTAG_W];

    function automatic logic [7:0] seqb(input logic [3:0] k);
        if (k < {1'b0, cnt})
            seqb = q[k[2:0]];
        else if (lat_v && k == {1'b0, cnt})
            seqb = lat_byte;
        else if (k == cnt_s)
            seqb = a0;
        else
            seqb = a1;
    endfunction
    // (MX5c) the tag of the window's byte k (seqb's choice)
    function automatic logic [QTAG_W-1:0] seqt(input logic [3:0] k);
        if (k < {1'b0, cnt})
            seqt = q_t[k[2:0]];
        else if (lat_v && k == {1'b0, cnt})
            seqt = lat_t;
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
    wire       infl_a = inflight && !dlv_v;
    wire [4:0] i2 = infl_a ? 5'd2 : 5'd0;
    wire       room = flush ? i2 <= 5'(CAP - 2) : {1'b0, avail_w} + i2 <= 5'(CAP - 2);
    assign fetch_req = room && !susp;
    // (MX5) the fetch address: the two sums formed from registers, the flush selecting last
    wire [19:0] fa_f = ps_base + {4'd0, flush_addr};
    wire [19:0] fa_n = ps_base + {4'd0, pfp};
    assign fetch_addr = flush ? fa_f : fa_n;
`ifndef SYNTHESIS
    // the direct arithmetic: the reference of `+v35_chk` and the qdbg trace's occ
    wire [3:0] cnt_x = flush ? 4'd0 : avail_w;
    wire [4:0] occ = {1'b0, cnt_x} + i2;
    wire       freq_x = occ <= 5'(CAP - 2) && !susp;
    wire [15:0] pfp_x = flush ? flush_addr : pfp;
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
            go_r <= fetch_go;
            faddr_r <= flush_addr;
        end
    end

    // ------------------------------------------------------------ next state (ce_a)
    wire [2:0]  reads = rd_r;
    wire [3:0]  cnt_e = flush_r ? 4'd0 : avail_w - {1'b0, reads};
    wire [15:0] pfp_g = flush_r ? faddr_r : pfp;
    // the latch at the clock's end: the window's seventh byte waits there
    wire        lat_e = !flush_r && cnt_e > 4'(QUEUE_BYTES);
    assign stored_nx = 3'(cnt_e - (lat_e ? 4'd1 : 4'd0));
    assign latv_nx = lat_e;
    assign odd_nx = go_r ? pfp_g[0] : odd;
    assign discard_nx = go_r ? 1'b0 : (flush_r && inflight && !dlv_v) ? 1'b1 : dlv_v ? 1'b0
                      : discard;
    always @(posedge clock) begin
        if (!reset_n) begin
            cnt <= 3'd0;
            pfp <= reset_ip;
            hip <= reset_ip;
            inflight <= 1'b0;
            discard <= 1'b0;
            odd <= 1'b0;
            lat <= 1'b0;
        end else if (ce_a) begin
            for (i = 0; i < 6; i = i + 1) begin
                q[i] <= seqb(4'(i) + {1'b0, reads});
                q_t[i] <= seqt(4'(i) + {1'b0, reads});
            end
            cnt <= stored_nx;
            lat <= lat_e;
            // (step D) the head's offset: a flush's target, else counted by the pops
            hip <= flush_r ? faddr_r : hip + {13'd0, reads};
            if (lat_e) begin
                lat_byte <= seqb(cnt_e - 4'd1 + {1'b0, reads});
                lat_t <= seqt(cnt_e - 4'd1 + {1'b0, reads});
            end
            if (go_r) begin
                inflight <= 1'b1;
                odd <= pfp_g[0];
                pfp <= (pfp_g | 16'd1) + 16'd1;
                discard <= 1'b0;
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
        if (reset_n && ce_a && !ovf && cnt_e > 4'(CAP)) begin   // (E1) more than six held
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
            $fdisplay(qfd, "q %0d cnt %0d lat %0d inf %0d dlv %0d rd %0d occ %0d req %0d susp %0d go %0d",
                      qt, cnt, lat, inflight, dlv_v, rd_r, occ, fetch_req, susp, go_r);
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
            if (rd_r !== rd || flush_r !== flush || go_r !== fetch_go || faddr_r !== flush_addr
                // (MX5) the request line against the direct arithmetic
                || fetch_req !== freq_x || fetch_addr !== faddr_x
                // (E1 M1) with the six-byte room the latch (a seventh byte) never loads
                || lat_e) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue: a tick A input changed in tick B at %0t", $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: queue: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
endmodule
