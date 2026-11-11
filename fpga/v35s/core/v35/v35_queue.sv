`timescale 1ns/1ps
`include "v35_macros.svh"

// V35S core v2: the prefetch queue as a simple machine (docs/v35s-queue-strategy.md, Q1).
//
// Six storage bytes, a stored count, a released count, a prefetch pointer and a request line.
// The queue knows nothing of forms, classes, rows or the execution unit's steps: the EU reads
// the bytes it takes (`rd`: the storage is freed, the window moves on), releases them for the
// room (`rel`: a take step's bytes when it ends, a ModR/M byte and the opcode at once), tells
// whether its IR staging byte is occupied (`stg`), flushes the queue on a transfer and
// suspends prefetching; the bus unit samples the request line at its decision point (once a
// clock, at the end of tick A) and reports a fetch's start and its word's delivery.
//
//   fetch_req   the request line, a level: free >= 2 and not suspended, where
//               free = CAP - cnt - unrel - stg - 2 for a word in flight (a fetch, or the bus
//               unit's aborted cycle), from the counts after this clock's delivery, tick A's
//               reads and releases. CAP is 7 in variant B (the IR staging byte is the seventh:
//               room_ir; `stg` its occupancy as the loader reports it) and 6 in variant A (the
//               staging byte not counted)
//   q_low       the bytes counted (as the request line counts them, a word less than CAP in
//               B) <= HOLD_Q (the fit's hold_q = 3): the arbiter's priority hint
//   fetch_addr  {PS, 0} + pfp with the 16-bit wrap (a flush on this clock: the new stream's);
//               an odd pfp (an odd transfer target) fetches its word and drops the low byte
//   vb0..vb3,   the head window and the stored count, this clock's delivery bypassed (S1
//   avail       before the take)
//
// The read / release split (take_commit=at_end, release=byte): a byte read leaves the storage
// at once (`cnt`), but the room counts it (`unrel`) until it is released: a FIFO with a read
// pointer and a release pointer.
//
// Variant A (VARIANT_B = 0): a word write port: a delivered word is stored in one clock.
// Variant B (VARIANT_B = 1): a byte-wide write port shared with the EU, and a one-byte latch.
// The port's owner on a clock is fixed: the EU's (a clock that releases bytes: a take step's
// end, a ModR/M byte, the IR load; latch_read=commit) first, else the latched byte drains,
// else the delivered word's second byte is written. So on a delivery clock that releases the
// word's first byte goes in and its second waits in the latch (`lat`, `lat_byte`): not counted
// on its delivery clock, counted from the next one (word_latch=byte_d); a second byte that
// would be a seventh stored byte waits there too (the word issued on the staging byte's room).
// A latched byte drains at the end of the first clock without a release with storage free; the
// request line is not held while it waits (latch_hold: not built, the corpus prefers it so). The
// latched byte is in the window behind the stored ones. The fit's situational latch rules
// (latch_midtake, latch_disp, latch_start, modrm_port, arrive_partial) are not built.
//
// Registered state (widths): q 6x8, cnt 3, unrel 3, pfp 16, inflight 1, discard 1, odd 1 (25
// bits beyond the bytes); variant B lat 1, lat_byte 8 (34).
//
// Two ticks (S7b): tick A (from ce_a) computes the window, the counts after the delivery and
// tick A's reads and releases (the T pass's takes, the IR load) and the request line; tick B
// adds the P pass's reads (`rd_b`; its releases reach `rel` on the next clock: the line is
// sampled once a clock, at the end of tick A). The ce_a update reads tick A's inputs through the
// ce_b registers.
module v35_queue
    import v35_front_pkg::*;
#(
    parameter bit VARIANT_B = 1'b1
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    // the bus unit
    output wire        fetch_req,
    output wire        fetch_raise,     // (MX1f experiment) the request the room raises, before the latch's hold
    output wire [19:0] fetch_addr,
    output wire        q_low,
    output wire        q_word,          // (Q2) the line is up with room for exactly one word ((R3) or a byte short, see q_short)
                                        //   ((R3) or a byte short by a byte the abort test counts)
    input  wire        fetch_go,        // a fetch issued now (S4)
    input  wire        dlv_v,           // a fetch ended on t-1: its word arrives now (S0)
    input  wire [15:0] dlv_data,
    input  wire        abort_go,        // the bus unit's aborted cycle runs (S0): a word in flight
    // the execution unit
    output wire [7:0]  vb0, vb1, vb2, vb3,
    output wire [2:0]  avail,
    output wire [2:0]  stored,          // (MX0b) the bytes stored (not this clock's delivery,
                                        //   not the latch): the word register loads from these
    // (MX5b) the queue's own registered facts (the loader's head-byte decode reads them before
    // the head select): the first stored byte, the latched byte, the latch's bit (variant B),
    // the in-flight word's parity. Registers of the queue's state, nothing of an instruction
    output wire [7:0]  h_q0,
    output wire [7:0]  h_lat,
    output wire        h_latv,
    output wire        h_odd,
    input  wire [2:0]  rd,              // bytes read in tick A (the T pass's takes, the IR load)
    input  wire [2:0]  rd_b,            // ... in tick B (the P pass's take and IR load)
    input  wire [2:0]  rel,             // bytes released (tick A; the P pass's a clock later)
    input  wire        stg,             // the EU's IR staging byte is occupied (tick A)
    input  wire        flush,           // clear the queue, the stream from flush_addr (tick A)
    input  wire [15:0] flush_addr,      // (in reset: the first fetch's offset)
    input  wire        susp,            // suspend prefetch: the request line held low (tick A)
    input  wire [19:0] ps_base          // {PS, 0} (after this clock's far transfer)
);
    localparam int CAP = VARIANT_B ? QUEUE_BYTES + 1 : QUEUE_BYTES;

    // ------------------------------------------------------------ registered state
    reg [7:0]  q [0:5];
    reg [2:0]  cnt = 3'd0;
    reg [2:0]  unrel = 3'd0;
    reg [15:0] pfp = 16'd0;
    reg        inflight = 1'b0;
    reg        discard = 1'b0;
    reg        odd = 1'b0;
    reg        lat = 1'b0;              // (variant B) the latched byte
    reg [7:0]  lat_byte = 8'h00;
    wire       lat_v = VARIANT_B && lat;

    integer i;
    initial for (i = 0; i < 6; i = i + 1) q[i] = 8'h00;

    // ------------------------------------------------------------ S1: the delivery
    wire       arrive = dlv_v && !discard;
    wire [7:0] a0 = odd ? dlv_data[15:8] : dlv_data[7:0];
    wire [7:0] a1 = dlv_data[15:8];
    // the window: the stored bytes, the latched one (B), then the delivered ones
    wire [2:0] n_arr = !arrive ? 3'd0 : (odd ? 3'd1 : 3'd2);
    wire [3:0] cnt_s = {1'b0, cnt} + (lat_v ? 4'd1 : 4'd0);
    wire [3:0] avail_w = cnt_s + {1'b0, n_arr};
    assign avail = avail_w > 4'd7 ? 3'd7 : avail_w[2:0];
    assign stored = cnt;
    assign h_q0 = q[0];
    assign h_lat = lat_byte;
    assign h_latv = lat_v;
    assign h_odd = odd;

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
    assign vb0 = seqb(4'd0);
    assign vb1 = seqb(4'd1);
    assign vb2 = seqb(4'd2);
    assign vb3 = seqb(4'd3);

    // ------------------------------------------------------------ tick A: the request line
    wire       infl_a = (inflight && !dlv_v) || abort_go;
    // (MX5) The room's facts with the loader's tick-A inputs (rd, rel, stg, flush) entering last.
    // The occupancy the request line tests is
    //     occ = cnt_a + unrel_a + stg - unc_a + 2 infl_a
    //         = (avail_w - rd) + (unrel + rd - rel) + stg - unc_a + 2 infl_a
    //         = E - (rel - stg + unc_a),     E = avail_w + unrel + 2 infl_a
    // (no flush; with a flush cnt_a = unrel_a = unc_a = 0 and occ = stg + 2 infl_a). E is formed
    // from registers alone, early in tick A; each threshold occ <= c is E <= c + rel - stg +
    // unc_a, read from E's thermometer (`lev`) by rel (an 8-way select) and then by stg and
    // unc_a (a 3-way select): two levels of select for the three adders in series. The identity
    // holds while no read takes more bytes than are available (avail_w >= rd) and no release
    // more than are read (unrel + rd >= rel), the queue's invariants (`+v35_chk` compares every
    // output with the old arithmetic, kept for the check and the qdbg trace). The tests on cnt_a
    // (not zero, the storage full, the physical room) are exact per rd: one value per rd,
    // selected by rd. The laws (fetch_req, fetch_raise, q_word, q_short, q_low, lat_hold, susp)
    // are the same expressions on the same facts. README "MX5"
    localparam int CL = CAP - QUEUE_BYTES;          // q_low's offset (B 1, A 0)
    wire [4:0] i2 = infl_a ? 5'd2 : 5'd0;
    // E = eq_r + n_arr + 2 infl_a: `eq_r` (cnt + the latch + unrel, the queue's own registers)
    // is a register beside them (loaded at ce_a with their next values: eq_r is always their
    // sum, `+v35_chk`), so E's thermometer is eq_r's compares selected by this clock's arrival
    // and flight (a2, the bus unit's registers): no adder before the compares
    reg  [4:0] eq_r = 5'd0;
    wire [2:0] a2 = n_arr + (infl_a ? 3'd2 : 3'd0);
    wire       sg = VARIANT_B && stg;
    logic [16:0] lev;                               // lev[i]: E <= i - 2
    always_comb
        for (int t = 0; t < 17; t = t + 1) begin
            lev[t] = 1'b0;
            for (int k = 0; k < 5; k = k + 1)
                if ({29'd0, a2} == 32'(k))
                    lev[t] = t - 2 - k >= 0 && {27'd0, eq_r} <= 32'(t - 2 - k);
        end
    // the per-rd tests on cnt_a = avail_w - rd (4 bits, exactly as the old arithmetic)
    logic [7:0] nz_r, ge_r, ph_r;
    always_comb
        for (int j = 0; j < 8; j = j + 1) begin
            nz_r[j] = avail_w - 4'(j) != 4'd0;
            ge_r[j] = {1'b0, 4'(avail_w - 4'(j))} >= 5'(QUEUE_BYTES);
            ph_r[j] = {1'b0, 4'(avail_w - 4'(j))} + i2 <= 5'(QUEUE_BYTES + (VARIANT_B ? 1 : 0) - 2);
        end
    // (variant B) the port: a clock that releases bytes is the EU's. The delivered word's second
    // byte waits uncounted on such a delivery clock
    wire       port_a = rel != 3'd0;
    wire       c_nz = !flush && nz_r[rd];           // cnt_a != 0
    wire       c_ge = !flush && ge_r[rd];           // cnt_a >= QUEUE_BYTES
    wire       unc_a = VARIANT_B && arrive && n_arr == 3'd2 && port_a && c_nz;
    // occ <= c (c >= -1): no flush, E's thermometer by rel then by unc_a - stg; a flush,
    // stg + 2 infl_a <= c (registers and stg)
    function automatic logic le_occ(input int c);
        logic m0, m1, m2;
        m0 = lev[c + 1 + int'(rel)];                // unc_a - stg = -1
        m1 = lev[c + 2 + int'(rel)];                // 0
        m2 = lev[c + 3 + int'(rel)];                // +1
        le_occ = flush ? 32'({4'd0, sg} + i2) <= 32'(c) && c >= 0
               : (unc_a && !sg) ? m2 : (!unc_a && sg) ? m0 : m1;
    endfunction
    wire       le_req = le_occ(CAP - 2);
    wire       le_ful = le_occ(CAP - 1);
    wire       le_low = le_occ(CL + FIT_HOLD_Q);
    wire       le_lo0 = le_occ(CL - 1);
    // the word must find its bytes a place: the six storage bytes and (B) the latch, the bytes
    // stored, latched and in flight counted whatever the room counts
    wire       phys_ok = flush ? i2 <= 5'(QUEUE_BYTES + (VARIANT_B ? 1 : 0) - 2) : ph_r[rd];
    // (MX1e) V35_MX1E_LHOLD: the latch's hold on the request line (the frozen model's
    // latch_hold, queue.py latch_blocks, measured on F3-push-nop-k4-pE-w0 -3: room 3, the line
    // held): a byte delivered on an earlier clock still latched, and on this clock the queue's
    // port is the EU's (a release) or the storage is full, so the byte cannot go in: no fetch is
    // requested until it can (the word would find its second byte's place still taken)
    wire       lat_hold = `V35_MX1E_LHOLD && lat_v && !arrive && (port_a || c_ge);
    assign fetch_req = le_req && phys_ok && !susp && !lat_hold;
    assign fetch_raise = le_req && phys_ok && !susp;
    // (Q2) q_word: the line up with room for exactly a word (the triple clock's abort test).
    // (R3) Or the line a byte short of a word by one byte the abort test counts as room: a byte
    // read and not yet released (xfer_abort=word: a transfer's displacement byte, released a
    // clock late by the loader) or a byte latched on an earlier clock (abort_latched)
    wire [3:0] unrel_a = flush ? 4'd0 : {1'b0, unrel} + {1'b0, rd} - {1'b0, rel};
    wire       q_short = le_ful && !le_req && !susp
                         && ((`V35_R3_XRW && unrel_a == 4'd1 && phys_ok)
                             || (`V35_R3_ALAT && lat_v && !arrive));
    assign q_word = (fetch_req && le_req && !le_occ(CAP - 3)) || q_short;
    // q_low: occ - (CAP - QUEUE_BYTES) <= FIT_HOLD_Q (5 bits): CL <= occ <= CL + FIT_HOLD_Q
    assign q_low = le_low && !le_lo0;
    // (MX5) the fetch address: the two sums formed from registers, the flush selecting last
    wire [19:0] fa_f = ps_base + {4'd0, flush_addr};
    wire [19:0] fa_n = ps_base + {4'd0, pfp};
    assign fetch_addr = flush ? fa_f : fa_n;
`ifndef SYNTHESIS
    // the old arithmetic: the reference of `+v35_chk` and the qdbg trace's occ
    wire [4:0] e_s = {1'b0, avail_w} + {2'd0, unrel} + i2;
    wire [3:0] cnt_x = flush ? 4'd0 : avail_w - {1'b0, rd};
    wire       unc_x = VARIANT_B && arrive && n_arr == 3'd2 && port_a && cnt_x != 4'd0;
    wire [4:0] occ = {1'b0, cnt_x} + {1'b0, unrel_a} + ((VARIANT_B && stg) ? 5'd1 : 5'd0)
                     - (unc_x ? 5'd1 : 5'd0) + i2;
    wire       phys_x = {1'b0, cnt_x} + i2 <= 5'(QUEUE_BYTES + (VARIANT_B ? 1 : 0) - 2);
    wire       lhold_x = `V35_MX1E_LHOLD && lat_v && !arrive
                         && (port_a || {1'b0, cnt_x} >= 5'(QUEUE_BYTES));
    wire       freq_x = occ <= 5'(CAP - 2) && phys_x && !susp && !lhold_x;
    wire       frai_x = occ <= 5'(CAP - 2) && phys_x && !susp;
    wire       qsh_x = occ == 5'(CAP - 1) && !susp
                       && ((`V35_R3_XRW && unrel_a == 4'd1 && phys_x)
                           || (`V35_R3_ALAT && lat_v && !arrive));
    wire       qword_x = (freq_x && occ == 5'(CAP - 2)) || qsh_x;
    wire       qlow_x = occ - 5'(CAP - QUEUE_BYTES) <= 5'(FIT_HOLD_Q);
    wire [15:0] pfp_x = flush ? flush_addr : pfp;
    wire [19:0] faddr_x = ps_base + {4'd0, pfp_x};
`endif

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg  [2:0]  rd_r = 3'd0, rel_r = 3'd0;
    reg         flush_r = 1'b0, go_r = 1'b0;
    reg  [15:0] faddr_r = 16'd0;
    always @(posedge clock) begin
        if (ce_b) begin
            rd_r <= rd;
            rel_r <= rel;
            flush_r <= flush;
            go_r <= fetch_go;
            faddr_r <= flush_addr;
        end
    end

    // ------------------------------------------------------------ next state (ce_a)
    wire [2:0]  reads = rd_r + rd_b;
    wire [3:0]  cnt_e = flush_r ? 4'd0 : avail_w - {1'b0, reads};
    wire [3:0]  unrel_e = flush_r ? 4'd0 : {1'b0, unrel} + {1'b0, reads} - {1'b0, rel_r};
    wire [15:0] pfp_g = flush_r ? faddr_r : pfp;
    // (variant B) the latch at the clock's end: the window's last byte (a latched byte, or this
    // delivery's second byte) waits when the clock released bytes, or when it would be a
    // seventh stored byte
    wire        lat_e = VARIANT_B && !flush_r && cnt_e != 4'd0
                        && ((rel_r != 3'd0 && (lat_v || (arrive && n_arr == 3'd2)))
                            || cnt_e > 4'(QUEUE_BYTES));
    always @(posedge clock) begin
        if (!reset_n) begin
            cnt <= 3'd0;
            unrel <= 3'd0;
            eq_r <= 5'd0;
            pfp <= flush_addr;
            inflight <= 1'b0;
            discard <= 1'b0;
            odd <= 1'b0;
            lat <= 1'b0;
        end else if (ce_a) begin
            for (i = 0; i < 6; i = i + 1)
                q[i] <= seqb(4'(i) + {1'b0, reads});
            cnt <= 3'(cnt_e - (lat_e ? 4'd1 : 4'd0));
            unrel <= unrel_e[2:0];
            lat <= lat_e;
            // (MX5) the room's registered sum: the three registers' new values added
            eq_r <= {2'd0, 3'(cnt_e - (lat_e ? 4'd1 : 4'd0))} + ((VARIANT_B && lat_e) ? 5'd1 : 5'd0)
                    + {2'd0, unrel_e[2:0]};
            if (lat_e)
                lat_byte <= seqb(cnt_e - 4'd1 + {1'b0, reads});
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

    wire unused = &{1'b0, unrel_e[3]};

`ifndef SYNTHESIS
    // +v35_diag: more than six bytes stored, or more released than read
    reg diag = 1'b0;
    reg ovf = 1'b0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (reset_n && ce_a && !ovf && (cnt_e - (lat_e ? 4'd1 : 4'd0) > 4'(QUEUE_BYTES)
                                        || unrel_e[3])) begin
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
            $fdisplay(qfd, "q %0d cnt %0d unrel %0d lat %0d inf %0d dlv %0d rd %0d/%0d rel %0d stg %0d occ %0d req %0d susp %0d go %0d",
                      qt, cnt, unrel, lat, inflight, dlv_v, rd_r, rd_b, rel_r, stg, occ,
                      fetch_req, susp, go_r);
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
            if (rd_r !== rd || rel_r !== rel || flush_r !== flush || go_r !== fetch_go
                || faddr_r !== flush_addr
                // (MX5) the room's facts against the old arithmetic
                || fetch_req !== freq_x || fetch_raise !== frai_x || q_word !== qword_x
                || q_low !== qlow_x || fetch_addr !== faddr_x || lat_hold !== lhold_x
                || eq_r !== {2'd0, cnt} + (lat_v ? 5'd1 : 5'd0) + {2'd0, unrel}
                || e_s !== eq_r + {2'd0, a2}) begin
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
