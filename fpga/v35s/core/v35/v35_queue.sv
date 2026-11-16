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
//   fetch_req   (qprobe rules 1, 2) the request line, a level: the occupancy (the bytes fetched
//               and not released: this clock's window, the loader's `oadj`, less this clock's
//               releases `rls`) at most 4, or at most 5 on the clock after a fetch's last clock
//               (a word delivered now) unless the dispatch word executes now (`bnd`); low on a
//               flush and the four clocks after it (rule 5: the target's fetch starts five
//               clocks after the flush), and while suspended; (rule 11) low from the clock
//               HALT's opcode is released (the loader's `fstop`). Replaces (E1 M2) below: the line
//               reads this clock's releases, not the registered count.
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
//   fetch_addr  {PS, 0} + pfp with the 16-bit wrap (a flush on this clock: the new stream's);
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
    // (qprobe rules 1, 2) the occupancy's other parts (the loader's: the staging register and
    // the bytes popped less the bytes released, a register; this clock's releases, tick A) and
    // the dispatch word executing now (the sequencer's: the back-to-back threshold's)
    input  wire [3:0]  oadj,
    input  wire [2:0]  rls,
    input  wire        bnd,
    // (qprobe rule 11) prefetching stopped (the loader's, tick A: HALT released): nothing more is fetched
    input  wire        fstop,
    // (qprobe round 6, E) the line's give-way and the five-held continuation's exception: the
    // bus unit's stage (`pend`: a fetch wanted while an EU cycle held the bus; `eud`: an EU
    // cycle ended on the last clock), the sequencer's boundary released by its lead on a
    // back-to-back fetch's clock (`lpri`), the loader's request word executed on the last clock
    // (`rqx`); out: the line given way now (gwy), and the facts of the bus unit's stage: the
    // count after this clock's releases at most 4, with the word in flight at most 5 (c4_q,
    // cf_q: tick A), the stream not waiting for a flush's target on the next clock (pv_nx: tick B)
    input  wire        pend,
    input  wire        eud,
    input  wire        lpri,
    input  wire        rqx,
    output wire        gwy,
    output wire        c4_q,
    output wire        cf_q,
    output wire        pv_nx,
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
    wire [4:0] occ = {1'b0, avail_w} + {oadj[3], oadj} - {2'd0, rls};
    // (qprobe round 6, E) REQ_PRI: no five-held continuation when a request word executed on
    // the fetch's last clock (`rqx`); EU_EPRI / LEAD_EPRI: the fetch gives way for one clock to
    // a boundary executing now on the clock after an EU cycle that held it (`eud`, `pend`), or
    // released by its lead on this back-to-back clock (`lpri`)
    wire       b2b_c = dlv_v && !discard && !bnd && !rqx;
    wire       pv = !flush && flw == 3'd0;
    wire       room = pv && $signed(occ) <= (b2b_c ? 5'sd5 : 5'sd4);
    wire       gw = bnd && ((eud && pend) || lpri);
    assign fetch_req = room && !gw && !susp && !fstop;
    assign gwy = room && gw && !susp && !fstop;
    assign c4_q = pv && $signed(occ) <= 5'sd4;
    assign cf_q = pv && $signed(occ) + (odd ? 5'sd1 : 5'sd2) <= 5'sd5;
    // (MX5) the fetch address: the two sums formed from registers, the flush selecting last
    wire [19:0] fa_f = ps_base + {4'd0, flush_addr};
    wire [19:0] fa_n = ps_base + {4'd0, pfp};
    assign fetch_addr = flush ? fa_f : fa_n;
`ifndef SYNTHESIS
    // the direct arithmetic: the reference of `+v35_chk` and the qdbg trace's occ
    wire [4:0] occ_x = {1'b0, avail_w} + {oadj[3], oadj} - {2'd0, rls};
    wire       freq_x = !flush && flw == 3'd0 && !susp && !fstop && !(bnd && ((eud && pend) || lpri))
                        && $signed(occ_x) <= ((dlv_v && !discard && !bnd && !rqx) ? 5'sd5 : 5'sd4);
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
    // (E2) at most six bytes are held (the request line's room, E1 M1: `+v35_chk`)
    assign stored_nx = cnt_e[2:0];
    wire        unused_e3 = cnt_e[3];    // (E2) never set (the chk's overflow test reads it)
    assign odd_nx = go_r ? pfp_g[0] : odd;
    wire [2:0]  flw_nx = flush_r ? 3'd4 : flw != 3'd0 ? flw - 3'd1 : 3'd0;
    assign pv_nx = flw_nx == 3'd0;              // (qprobe round 6) the flush wait over on the next clock
    assign discard_nx = go_r ? 1'b0 : (flush_r && inflight && !dlv_v) ? 1'b1 : dlv_v ? 1'b0
                      : discard;
    always @(posedge clock) begin
        if (!reset_n) begin
            cnt <= 3'd0;
            flw <= 3'd0;
            pfp <= reset_ip;
            hip <= reset_ip;
            inflight <= 1'b0;
            discard <= 1'b0;
            odd <= 1'b0;
        end else if (ce_a) begin
            for (i = 0; i < QN; i = i + 1) begin
                q[i] <= seqb(4'(i) + {1'b0, reads});
                q_t[i] <= seqt(4'(i) + {1'b0, reads});
            end
            cnt <= stored_nx;
            // (qprobe rule 5) the flush wait: the line low four clocks after the flush's
            flw <= flw_nx;
            // (step D) the head's offset: a flush's target, else counted by the pops
            hip <= flush_r ? faddr_r : hip + {13'd0, reads};
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
            $fdisplay(qfd, "q %0d cnt %0d inf %0d dlv %0d rd %0d occ %0d req %0d susp %0d go %0d rqx %0d bnd %0d pend %0d eud %0d lpri %0d rls %0d",
                      qt, cnt, inflight, dlv_v, rd_r, $signed(occ), fetch_req, susp, go_r, rqx, bnd, pend, eud, lpri, rls);
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
                // (E1 M1, E2) with the six-byte room no seventh byte is ever held
                || cnt_e > 4'(QN)) begin
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
