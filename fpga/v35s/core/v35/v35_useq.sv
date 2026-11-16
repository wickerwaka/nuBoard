`timescale 1ns/1ps

// V35S core v2 (MX0): the microsequencer (docs/v35s-mechanisms.md sections 3.1, 4; README
// "MX0"). One microinstruction a CPU clock from a registered ROM word: the ROM (three 32-bit
// banks, v35_urom_b?.hex, assembled by validation/v35s/chains/uasm.py) is read at ce_a with the
// next microaddress computed in tick B, so the word a clock executes is a register from its
// first tick on. The microaddress is a register.
//
// The five stalls, each from registered state at tick A (a stalled word performs none of its
// acts and is read again); (MX5c) the outcome itself is a register (`st_r`, loaded at ce_a with
// the stalls of the next state, README "MX5" round 3):
//   q     the word pops a byte and there is none: an operand byte and the queue is empty, or
//         E's opcode and the staging register is empty
//   f     F: the requested datum has not arrived (the datapath's opr_rdy: req_done or the
//         datum latched)
//   slot  the word posts a request while the EU's one request is still outstanding
//   hold  E while a memory write is outstanding with RAMEN = 1 ((step D) kept: function-bearing,
//         a store into the register RAM read by the next words, README "Step D")
//   halt  halted
// (step D) Nothing else: the rule-only stalls (the bus wait, the unit hold, the write-back
// waits, the take sync, the dispatch law, SUSP's and the decide's fetch wait, the refill wait)
// are removed with the facts only they read (README "Step D").
// (qprobe) Two measured stalls (README "qprobe"; validation/v35s/qprobe/model.py):
//   bnd   (rule 4) the dispatch word (the model's E, the instruction boundary) waits (a) while
//         a fetch cycle started on an earlier clock runs, except on its last clock; (b) on the
//         clock a back-to-back fetch starts (the loader's b4: a fetch delivered now, the count
//         at most 4, no EU request standing: the fetch wins); (c, d) the loader's ew: the count
//         below 3 for the first boundary after a flush or a ModR/M opcode
//   b     (rule 5) a word marked `bi` waits while a fetch cycle started on an earlier clock runs,
//         its last clock included
// (qprobe round 5) and their refinements:
//   bnd   (rule 7) also while any bus cycle started on an earlier clock runs (the EU's own: a
//         memory read or write, an I/O cycle), not on its last clock (the bus unit's cb_nx /
//         fl_nx); (rule 12) while the clocks since the opcode register's release are fewer
//         than its decode's lead (the loader's ld_nx)
// (qprobe round 6: validation/v35s/qprobe/model_m.py, README "qprobe round 6") rule 9 (a `bi`
// word from a fetch's third clock) and rule 10 (G, a `bi` word that posts) are withdrawn:
//   bnd   also while a memory request is posted and not yet granted (E_PEND: the EU's rqm_nx);
//         the count short now includes any boundary's two bytes (EMIN, the loader's ew_nx);
//         (b) does not hold the boundary whose lead ends now (LEAD_EPRI: le_nx), the fetch
//         gives way a clock instead (`lpri` to the queue)
//   b     by the word's kind: `bi` (B, F) the pin cycle of a fetch started earlier, its last
//         clock included (fb); rl=x (X, S, A) the bus unit's slot (sl_nx); rl=x with bi (Y,
//         a memory request word) a fetch with two clocks or more left (fy_nx)
// Their facts enter as next values (the bus unit's fb_nx / fl_nx, the loader's b4_nx / ew_nx,
// the EU's req_v_nx) and as their ce_a-registered copies (`qf`: the facts as they stand).
//
// The next microaddress (tick B): the same word (stalled), the next, a jump (on a registered
// condition), a call (one return register: the V20 ROM's FARJMP subroutines nest one level,
// V20UC.TXT 0000-04FF has no FARJMP from inside a FARJMP target), a return, a loop on the
// counter, or a dispatch from the decode registered at the end of tick A: DISP (the word after
// E) on the opcode the E word popped (v35_udec1 of the loader's opcode register), DISPM on the
// byte this word pops (v35_udec2 of the opcode register and the word register's byte). No
// queue byte reaches the address except through those registers.
// (MX1) The dispatch of a ModR/M memory cell is a call: the target is the EA head of the
// registered ModR/M byte's mode (the loader's dent), the return register loads the routine's
// entry (dret); the head pops the displacement and returns (ea.uasm). One level still: no
// memory routine calls (the heads' return frees the register).
//
// The loop counter (9 bits) is loaded by a word from port B's low byte (CL), the immediate,
// the operand's bit count, the trap's remaining byte count or (F2a) SIGMA's low four bits, and
// stepped by LOOP.
//
// Depth (by construction, the levelizer's run is the overseer's): tick A: the stall terms
// (a handful of registered bits, the word's fields) and the decode lookups (the opcode register
// and the word register's byte into the generated case tables: ROM-like LUT logic) into the
// ce_b registers; tick B: the next-address mux (eight sources by the word's seq field and the
// registered ex) into the ROM's read address. The ROM output is a register.
//
// Registered state (widths): upc 10, the ROM word 86 (96), retr 10, cnt 9, halted 1; the ce_b
// copies ex_b 1, d1_b 10, d2_b 10, (MX1) dc_b 1, dr_b 10.
module v35_useq
    import v35_pkg::*;
#(
    parameter string UROM_DIR = "fpga/v35s/core/v35/"
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    // the loader (tick A: registers)
    input  wire        q_stall,         // the word's pop finds no byte (the loader's)
    input  wire [UADDR_W-1:0] dent,     // the DISP word's target (the loader's)
    input  wire        dcall,           // (MX1) ... an EA head, called (the return register <- dret)
    input  wire [UADDR_W-1:0] dret,     // ... the routine's entry (the head's return)
    input  v35_udecm_t dec2,            // v35_udec2(the opcode register, the word register's byte)
    input  wire        ec_reg,          // (MX3c) the EAC word's popped byte: register mode
    input  wire        ec_call,         // ... a memory mode with an EA head (called)
    input  wire [UADDR_W-1:0] ec_head,  // ... the head
    input  wire [2:0]  len,             // the instruction's bytes still to pop (the trap's LEN)
    input  wire [7:0]  il,              // the first immediate byte
    input  wire        fmt_w,           // the running form's width
    // the datapath (tick A: registers; rb_lo: tick B)
    input  wire        opr_rdy,         // F's datum is here
    input  wire        rq_busy,         // the request slot is taken
    input  wire        wr_hold,         // an outstanding write holds E (RAMEN)
    input  wire        c_sgn,           // SIGMA's sign
    input  wire        c_dtrap,         // the divide error
    input  wire        c_xc,            // (MX2) the transfer's condition (the datapath's, by the format)
    input  wire        c_snz,           // (MX2) SIGMA is not zero
    input  wire        c_f1,            // (MX3b) F1, the units' sign latch
    input  wire        c_dn,            // (MX3b) the divide's dividend negative
    input  wire [7:0]  rb_lo,           // port B's low byte (tick B)
    input  wire [3:0]  sig_lo,          // (F2a) SIGMA's low four bits (a register)
    input  wire        wake,            // (F3) HALT's release (v35_intc's register: NMI or an unmasked IF)
    input  wire        igo,             // (F3) an interrupt is taken at this dispatch (v35_intc: an
                                        //   AND-OR of registers): the DISP word goes to UROM_INT, not dent
    input  wire        sgo,             // (F5e) an interrupt is taken at a string's take point (a TKI
                                        //   word; v35_intc: an AND-OR of registers): the word's target
    // (MX5c) tick B: the next values of the stall's inputs (the D nets of their ce_a registers,
    // as they stand after the coming ce_a): the loader's, the datapath's, the bus unit's
    input  wire        q_stall_nx,
    input  wire        opr_rdy_nx,
    input  wire        rq_busy_nx,
    input  wire        wr_hold_nx,
    // (qprobe rules 4, 5) tick B: the next values of the boundary's and the B word's facts: a
    // fetch cycle started on an earlier clock runs (fb_nx), it is its last clock (fl_nx) (the bus
    // unit's); a back-to-back fetch at a count of at most 4 (b4_nx), the count short for this
    // boundary (ew_nx) (the loader's); the EU's request standing (req_v_nx)
    input  wire        fb_nx,
    input  wire        fl_nx,
    input  wire        b4_nx,
    input  wire        ew_nx,
    input  wire        req_v_nx,
    // (qprobe rules 7, 12) tick B: a cycle of any kind started earlier runs on the next clock
    // (cb_nx, the bus unit's); the boundary short of its lead (ld_nx, the loader's)
    input  wire        cb_nx,
    input  wire        ld_nx,
    // (qprobe round 6) tick B: the bus unit's slot taken on the next clock (sl_nx: rl=x words),
    // a fetch with two clocks or more left then (fy_nx: rl=x bi words, the memory request
    // words); the boundary's lead ending then (le_nx, the loader's: LEAD_EPRI); a memory request
    // posted and not granted then (rqm_nx, the EU's: E_PEND)
    input  wire        sl_nx,
    input  wire        fy_nx,
    input  wire        le_nx,
    input  wire        rqm_nx,
    // (qprobe round 6, E) tick A: the boundary executes on its lead's last clock over a
    // back-to-back fetch (the queue's line gives way one clock: LEAD_EPRI)
    output wire        lpri,
    // (qprobe round 6) the word is the dispatch (the derived bit, a register; tick B: the next
    // word's): the loader's release on the dispatch word
    output wire        w_disp,
    output wire        w_disp_nx,
    // the word and its execution
    output v35_uword_t word,            // the current microinstruction (a register)
    output v35_uword_t word_nx,         // (MX5b) tick B: the next word (the banks' read data)
    output wire        w_dispm,         // (MX5) the word's derived bits (registers): seq == SQ_DISPM
    output wire        w_dispm_nx,      // (MX5c) tick B: the next word's seq == SQ_DISPM
    output wire        w_erep,          // (F5d) the word's derived bit (a register): e && ea == EA_REP
    output wire        w_erep_nx,       // ... tick B: the next word's
    output wire        ex,              // the word executes this clock (tick A)
    output reg         ex_b,            // ... registered at ce_b (tick B, ce_a)
    // (step B) the take points and acts the interrupt / service unit (v35_intc) reads, named for
    // what they are (each an AND of the registered outcome and the word's fields or derived
    // bits): tick A
    output wire        x_disp,          // the dispatch word executes: an instruction boundary
    output wire        x_tki,           // a TKI word executes: a string's take point
    output wire        x_end,           // an E word executes (the instruction's last word) ...
    output wire        x_nb,            // ... marking its end no boundary (a prefix, EI, DI, a
                                        //   segment register's load: `nb`)
    output wire        x_nbi,           // ... dropping the interrupt arms (POP PSW, RETI, FINT:
                                        //   seg=NBI)
    output wire        x_flush,         // a FLUSH word executes (the queue's and the loader's flush)
    // tick B (ex_b)
    output wire        w_stop,          // the word is STOP's halt word (halt, cnt=stop; a level)
    output wire        x_stop,          // ... and it executes
    output wire        x_ivec,          // the take's IVEC word executes (the controller's acknowledge)
    output wire        x_fint,          // FINT executes
    output wire        q_susp,          // (MX2) prefetching suspended (the queue's susp: SUSP)
    output reg         halted
);
    localparam int ROM_N = 1 << UADDR_W;

    // ------------------------------------------------------------ the ROM
    reg [31:0] rom0 [0:ROM_N-1];
    reg [31:0] rom1 [0:ROM_N-1];
    reg [31:0] rom2 [0:ROM_N-1];
    integer i;
    initial begin
        for (i = 0; i < ROM_N; i = i + 1) begin
            rom0[i] = 32'd0;
            rom1[i] = 32'd0;
            rom2[i] = 32'd0;
        end
        $readmemh({UROM_DIR, "v35_urom_b0.hex"}, rom0, 0, UROM_WORDS - 1);
        $readmemh({UROM_DIR, "v35_urom_b1.hex"}, rom1, 0, UROM_WORDS - 1);
        $readmemh({UROM_DIR, "v35_urom_b2.hex"}, rom2, 0, UROM_WORDS - 1);
    end

    reg [UADDR_W-1:0] upc = UROM_RESET;
    // (MX5) the ROM is read a tick earlier: the banks at ce_b (`r0`..`r2`, the RAM's read data)
    // with the next address decided in tick A (`upc_a`), the word a plain register (`q0`..`q2`)
    // loaded from the read data at ce_a. The word a clock executes is the one the old ce_a read
    // gave: the address is the same function of the same values (README "MX5")
    reg [31:0] r0 = 32'd0, r1 = 32'd0, r2 = 32'd0;
    reg [31:0] q0 = 32'd0, q1 = 32'd0, q2 = 32'd0;
    wire [95:0] qw = {q2, q1, q0};
    assign word = v35_uword_t'(qw[UWORD_BITS-1:0]);
    // (MX5) the word's derived bits (the field compares the stall terms and the take points
    // read), decoded from the next word's read data in tick B and registered with the word
    // at ce_a: `pd` is always the function `pre(word)` of the word it sits beside
    typedef struct packed {
        logic post;         // bus != BQ_NONE
        logic disp;         // seq == SQ_DISP
        logic dispm;        // seq == SQ_DISPM
        logic erep;         // (F5d) e && ea == EA_REP: the E pop re-enters the REP page
        logic tki;          // (F5e) seq == SQ_TKI: a string's take point
    } v35_upre_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_upre_t pre(input v35_uword_t w);
        pre.post = w.bus != BQ_NONE;
        pre.disp = w.seq == SQ_DISP;
        pre.dispm = w.seq == SQ_DISPM;
        pre.erep = w.e && w.ea == EA_REP;
        pre.tki = w.seq == SQ_TKI;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    wire [95:0] rw = {r2, r1, r0};
    assign word_nx = v35_uword_t'(rw[UWORD_BITS-1:0]);
    v35_upre_t pd = '0;
    assign w_dispm = pd.dispm;
    assign w_disp = pd.disp;
    assign w_erep = pd.erep;

    reg [UADDR_W-1:0] retr = '0;
    reg [8:0]  cnt = 9'd0;
    initial halted = 1'b0;

    // ------------------------------------------------------------ tick A: the stalls
    // (MX5c) The stall outcome is a register. Every stall term reads ce_a registers only (the
    // word, its derived bits, the loader's staging slot and byte counts, the datapath's request
    // registers and RAMEN), never tick A's logic. `stall_f(i)` is the five stalls below on the facts `i`;
    // the outcome (ex, why) is `st_r`, a ce_a register loaded with stall_f of the facts' next
    // values (`si_nx`: tick B's word_nx and its derived bits, the other modules' *_nx outputs:
    // the D nets of their registers), in reset with stall_f of the facts as they stand. So st_r
    // is stall_f(si_now) on every clock (`+v35_chk`), and tick A starts from a registered stall
    // outcome. README "MX5" round 3
    typedef struct packed {
        logic       halted, f, e, post;
        logic       q_stall, opr_rdy, rq_busy, wr_hold;
        logic       disp, bi;           // (qprobe) the word is the dispatch; is a B word
        logic       fb, fl, b4, ew, rqv;    // (qprobe) the bus unit's, the loader's, the EU's facts
        logic       rlx;                // (qprobe rule 9) rl=X
        logic       cb, ld;             // (qprobe rules 7, 12) the bus unit's, the loader's
        logic       sl, fy, le, pm;     // (qprobe round 6) the slot, the late wait, the lead's end, E_PEND
    } v35_sin_t;
    typedef struct packed {
        logic       ex;
        logic [4:0] why;    // the stall's reason (the trace's W): 0 none, 1 q, 2 f, 3 slot, 4 hold,
                            //   5 halt, (qprobe) 6 the boundary's, 7 a B word's
    } v35_stl_t;
    function automatic v35_stl_t stall_f(input v35_sin_t f);
        logic st_q, st_f, st_slt, st_hld, st_bnd, st_bi;
        st_q   = f.q_stall;                 // the queue: a pop finds no byte
        st_f   = f.f && !f.opr_rdy;         // the bus cycle: F's datum not here
        st_slt = f.post && f.rq_busy;       // the one request slot taken
        st_hld = f.e && f.wr_hold;          // a memory write outstanding with RAMEN = 1 ((qprobe rule 7) into the on-chip page)
        // (qprobe rule 4) the boundary: (a) a fetch running, not on its last clock; (b) a
        // back-to-back fetch starting now (no EU request to win the bus) unless the boundary's
        // lead ends now (round 6, LEAD_EPRI: the boundary executes, the fetch gives way a
        // clock); (c, d) the count short (round 6: EMIN, any boundary two bytes); (rule 7) any
        // cycle running, not on its last clock; (rule 12) the lead; (round 6, D: E_PEND) a
        // memory request posted and not yet granted
        st_bnd = f.disp && ((f.cb && !f.fl) || (f.b4 && !f.rqv && !f.le) || f.ew || f.ld || f.pm);
        // (round 6, A, B, C) the bus waits by the word's kind (the ROM's bi and rl=x):
        //   bi            B, F: a fetch's pin cycle started earlier runs (its last clock included)
        //   rl=x          X, S, A: the bus unit's slot is taken (sl)
        //   rl=x and bi   Y: a fetch started earlier runs with two clocks or more left (fy)
        st_bi  = (f.bi && !f.rlx && f.fb) || (f.rlx && !f.bi && f.sl) || (f.rlx && f.bi && f.fy);
        stall_f.ex = !f.halted && !st_q && !st_f && !st_slt && !st_hld && !st_bnd && !st_bi;
        stall_f.why = f.halted ? 5'd5 : st_q ? 5'd1 : st_f ? 5'd2 : st_slt ? 5'd3
                    : st_hld ? 5'd4 : st_bnd ? 5'd6 : st_bi ? 5'd7 : 5'd0;
    endfunction
    // (qprobe) the facts of rules 4 and 5 as they stand: ce_a registers of their next values
    // (in reset none: no cycle runs, nothing is delivered)
    typedef struct packed {
        logic       fb, fl, b4, ew, rqv;
        logic       cb, ld, sl, fy, le, pm;
    } v35_qf_t;
    v35_qf_t   qf = '0;
    reg        sp = 1'b0;
    v35_sin_t  si_now;
    always_comb begin
        si_now.halted = halted;
        si_now.f = word.f;
        si_now.e = word.e;
        si_now.post = pd.post;
        si_now.q_stall = q_stall;
        si_now.opr_rdy = opr_rdy;
        si_now.rq_busy = rq_busy;
        si_now.wr_hold = wr_hold;
        si_now.disp = pd.disp;
        si_now.bi = word.bi;
        si_now.fb = qf.fb;
        si_now.fl = qf.fl;
        si_now.b4 = qf.b4;
        si_now.ew = qf.ew;
        si_now.rqv = qf.rqv;
        si_now.rlx = word.rl == RL_X;
        si_now.cb = qf.cb;
        si_now.ld = qf.ld;
        si_now.sl = qf.sl;
        si_now.fy = qf.fy;
        si_now.le = qf.le;
        si_now.pm = qf.pm;
    end
    v35_stl_t  st_r = '0;
    assign ex = st_r.ex;
    // (step B) the take points and acts (v35_top's glue before: the same terms)
    assign x_disp = ex && pd.disp;
    assign lpri = x_disp && qf.b4 && !qf.rqv && qf.le;     // (qprobe round 6, E: LEAD_EPRI)
    assign x_tki = ex && pd.tki;
    assign x_end = ex && word.e;
    assign x_nb = ex && word.e && word.nb;
    assign x_nbi = ex && word.e && word.seg == SG_NBI;
    assign x_flush = ex && word.flush;
    assign w_stop = word.halt && word.cnt == CN_STOP;
    assign x_stop = ex_b && w_stop;
    assign x_ivec = ex_b && word.alu == AL_IVEC;
    assign x_fint = ex_b && word.alu == AL_FINT;
    // (MX2) SUSP suspends prefetching (the queue's request line held low from the clock the word
    // is reached until the FLUSH: `sp` once it has executed)
    assign q_susp = (sp && !word.flush) || word.susp;     // (the FLUSH word issues the target's fetch)
    // (MX2) the suspension stands from the SUSP word's execution to the FLUSH (or an E)
    wire       sp_n = (ex && (word.flush || word.e)) ? 1'b0 : (ex && word.susp) ? 1'b1 : sp;

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg [UADDR_W-1:0] d1_b = '0, d2_b = '0, dr_b = '0;
    reg        dc_b = 1'b0;
    reg        ig_b = 1'b0;                 // (F3) igo, for tick B's DISP target
    reg        sg_b = 1'b0;                 // (F5e) sgo, for tick B's TKI target
    reg        ecr_b = 1'b0, ecc_b = 1'b0;      // (MX3c) the EAC word's mode facts
    reg [UADDR_W-1:0] ech_b = '0;
    reg        sp_b = 1'b0;
    reg [2:0]  len_b = 3'd0;
    reg [7:0]  il_b = 8'd0;
    reg        w_b = 1'b0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            ex_b <= ex;
            d1_b <= dent;
            ig_b <= igo;
            sg_b <= sgo;
            dc_b <= dcall;
            ecr_b <= ec_reg;
            ecc_b <= ec_call;
            ech_b <= ec_head;
            sp_b <= sp_n;
            dr_b <= dret;
            d2_b <= dec2.entry;
            len_b <= len;
            il_b <= il;
            w_b <= fmt_w;
        end
    end

    // (MX5c) the stall's facts as they stand after the coming ce_a (tick B: the next word and
    // its derived bits, the ce_b registers the counters load, the other modules' next values)
    // and the registered outcome
    v35_upre_t pd_nx;
    assign pd_nx = pre(word_nx);
    assign w_dispm_nx = pd_nx.dispm;
    assign w_disp_nx = pd_nx.disp;
    assign w_erep_nx = pd_nx.erep;
    v35_sin_t  si_nx;
    always_comb begin
        si_nx.halted = (halted || (ex_b && word.halt)) && !wake;     // (F3) the release
        si_nx.f = word_nx.f;
        si_nx.e = word_nx.e;
        si_nx.post = pd_nx.post;
        si_nx.q_stall = q_stall_nx;
        si_nx.opr_rdy = opr_rdy_nx;
        si_nx.rq_busy = rq_busy_nx;
        si_nx.wr_hold = wr_hold_nx;
        si_nx.disp = pd_nx.disp;
        si_nx.bi = word_nx.bi;
        si_nx.fb = fb_nx;
        si_nx.fl = fl_nx;
        si_nx.b4 = b4_nx;
        si_nx.ew = ew_nx;
        si_nx.rqv = req_v_nx;
        si_nx.rlx = word_nx.rl == RL_X;
        si_nx.cb = cb_nx;
        si_nx.ld = ld_nx;
        si_nx.sl = sl_nx;
        si_nx.fy = fy_nx;
        si_nx.le = le_nx;
        si_nx.pm = rqm_nx;
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            st_r <= stall_f(si_now);
            qf <= '0;
        end else if (ce_a) begin
            st_r <= stall_f(si_nx);
            qf.fb <= fb_nx;
            qf.fl <= fl_nx;
            qf.b4 <= b4_nx;
            qf.ew <= ew_nx;
            qf.rqv <= req_v_nx;
            qf.cb <= cb_nx;
            qf.ld <= ld_nx;
            qf.sl <= sl_nx;
            qf.fy <= fy_nx;
            qf.le <= le_nx;
            qf.pm <= rqm_nx;
        end
    end

    // ------------------------------------------------------------ tick B: the next address
    logic cond_v;
    always_comb begin
        case (word.cond)
            CD_CNTZ: cond_v = cnt == 9'd0;
            CD_SGN: cond_v = c_sgn;
            CD_DTRAP: cond_v = c_dtrap;
            CD_WORD: cond_v = w_b;
            CD_XC: cond_v = c_xc;
            CD_SNZ: cond_v = c_snz;
            CD_SGD: cond_v = c_f1;
            CD_DN: cond_v = c_dn;
            default: cond_v = 1'b0;
        endcase
    end
    wire [UADDR_W-1:0] inc = upc + 1'b1;
    logic [UADDR_W-1:0] upc_n;
    always_comb begin
        if (!ex_b)
            upc_n = upc;
        else begin
            case (word.seq)
                SQ_JMP: upc_n = word.tgt;
                SQ_JC: upc_n = cond_v ? word.tgt : inc;
                SQ_JNC: upc_n = cond_v ? inc : word.tgt;
                SQ_CALL: upc_n = word.tgt;
                SQ_RET: upc_n = retr;
                SQ_LOOP: upc_n = cnt != 9'd1 ? word.tgt : inc;
                SQ_DISPM: upc_n = d2_b;
                SQ_DISP: upc_n = ig_b ? UROM_INT : d1_b;     // (F3) the interrupt take
                SQ_TKI: upc_n = sg_b ? word.tgt : inc;          // (F5e) a string's take point
                // (MX3c) EAC: the register path, the EA head (called), or the next word
                SQ_EAC: upc_n = ecr_b ? word.tgt : ecc_b ? ech_b : inc;
                default: upc_n = inc;
            endcase
        end
    end
    logic [8:0] cnt_n;
    always_comb begin
        cnt_n = cnt;
        if (ex_b) begin
            case (word.cnt)
                CN_RB: cnt_n = {1'b0, rb_lo};
                CN_IL: cnt_n = {1'b0, il_b};
                CN_BITS: cnt_n = w_b ? 9'd16 : 9'd8;
                CN_LEN: cnt_n = {6'd0, len_b};
                // (MX3c) (CL + 1) / 2: CL shifted right by one, its low bit the carry-in
                CN_CLH: cnt_n = {2'd0, rb_lo[7:1]} + {8'd0, rb_lo[0]};
                // (F2a) SIGMA's low four bits (the bit fields' per-bit loops)
                CN_SIG: cnt_n = {5'd0, sig_lo};
                default: cnt_n = word.seq == SQ_LOOP ? cnt - 9'd1 : cnt;
            endcase
        end
    end

    // ------------------------------------------------------------ (MX5) tick A: the ROM's address
    // The next address as tick B's upc_n computes it, on the tick-A sources of its ce_b registers
    // (ex for ex_b, dent for d1_b, dec2.entry for d2_b, the EAC facts for ecr_b / ecc_b / ech_b,
    // fmt_w for w_b; the word, upc, retr, cnt and the datapath's conditions are ce_a registers):
    // each ce_b register holds its source's tick-A value (`+v35_chk`), so upc_a at ce_b is upc_n
    // at ce_a. The candidate (`nx_a`) is formed from the word and registers; ex selects last.
    logic cond_a;
    always_comb begin
        case (word.cond)
            CD_CNTZ: cond_a = cnt == 9'd0;
            CD_SGN: cond_a = c_sgn;
            CD_DTRAP: cond_a = c_dtrap;
            CD_WORD: cond_a = fmt_w;
            CD_XC: cond_a = c_xc;
            CD_SNZ: cond_a = c_snz;
            CD_SGD: cond_a = c_f1;
            CD_DN: cond_a = c_dn;
            default: cond_a = 1'b0;
        endcase
    end
`ifndef SYNTHESIS
    // (qprobe round 6, timing) the reference: raddr below is `!reset_n ? UROM_RESET : upc_a`
    logic [UADDR_W-1:0] nx_a;
    always_comb begin
        case (word.seq)
            SQ_JMP: nx_a = word.tgt;
            SQ_JC: nx_a = cond_a ? word.tgt : inc;
            SQ_JNC: nx_a = cond_a ? inc : word.tgt;
            SQ_CALL: nx_a = word.tgt;
            SQ_RET: nx_a = retr;
            SQ_LOOP: nx_a = cnt != 9'd1 ? word.tgt : inc;
            SQ_DISPM: nx_a = dec2.entry;
            SQ_DISP: nx_a = igo ? UROM_INT : dent;      // (F3) the interrupt take
            SQ_TKI: nx_a = sgo ? word.tgt : inc;        // (F5e) a string's take point
            SQ_EAC: nx_a = ec_reg ? word.tgt : ec_call ? ec_head : inc;
            default: nx_a = inc;
        endcase
    end
    wire [UADDR_W-1:0] upc_a = ex ? nx_a : upc;
`endif

    // ------------------------------------------------------------ the end of the clock (ce_a)
    // (MX5) the banks read at ce_b (in reset: the reset word, every clock); the word register
    // loads their data at ce_a, the derived bits with it
    // (qprobe round 6, timing) the same address, `!reset_n ? UROM_RESET : upc_a`, with the late
    // candidates (the second level's entry, the EAC head, the dispatch's interrupt take, the
    // string's take point, the condition) selected last by facts of registers alone (reset,
    // ex, the word's seq), the rest formed beside them (`ra_e`); `+v35_chk` compares the two
    logic [UADDR_W-1:0] ra_e;
    always_comb begin
        if (!reset_n)
            ra_e = UROM_RESET;
        else if (!ex)
            ra_e = upc;
        else begin
            case (word.seq)
                SQ_JMP, SQ_CALL: ra_e = word.tgt;
                SQ_RET: ra_e = retr;
                SQ_LOOP: ra_e = cnt != 9'd1 ? word.tgt : inc;
                default: ra_e = inc;
            endcase
        end
    end
    wire               r_go = reset_n && ex;
    wire               s_dm = r_go && word.seq == SQ_DISPM;
    wire               s_ds = r_go && word.seq == SQ_DISP;
    wire               s_ec = r_go && word.seq == SQ_EAC;
    wire               s_tk = r_go && word.seq == SQ_TKI;
    wire               s_jc = r_go && word.seq == SQ_JC;
    wire               s_jn = r_go && word.seq == SQ_JNC;
    wire [UADDR_W-1:0] raddr = s_dm ? dec2.entry
                             : s_ec ? (ec_reg ? word.tgt : ec_call ? ec_head : inc)
                             : s_ds ? (igo ? UROM_INT : dent)
                             : s_tk ? (sgo ? word.tgt : inc)
                             : s_jc ? (cond_a ? word.tgt : inc)
                             : s_jn ? (cond_a ? inc : word.tgt)
                             : ra_e;
    always_ff @(posedge clock) begin
        if (!reset_n || ce_b) begin
            r0 <= rom0[raddr];
            r1 <= rom1[raddr];
            r2 <= rom2[raddr];
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n || ce_a) begin
            q0 <= r0;
            q1 <= r1;
            q2 <= r2;
            pd <= pd_nx;
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            upc <= UROM_RESET;
            retr <= '0;
            cnt <= 9'd0;
            sp <= 1'b0;
            halted <= 1'b0;
        end else if (ce_a) begin
            upc <= upc_n;
            cnt <= cnt_n;
            sp <= sp_b;
            if (ex_b && (word.seq == SQ_CALL || (word.seq == SQ_EAC && !ecr_b && ecc_b)))
                retr <= inc;
            else if (ex_b && word.seq == SQ_DISP && dc_b)
                retr <= dr_b;      // (MX1) the dispatch's call of an EA head
            halted <= (halted || (ex_b && word.halt)) && !wake;     // (F3) the release
        end
    end

    // (st_r.why: the stall's reason, the trace's W: v35_top's observation block)
    // ((step D) the word is 92 bits: the banks' top four bits unread)
    // ((qprobe) the word is 96 bits: the banks' every bit read)
    wire unused = &{1'b0, dec2, st_r.why};

`ifndef SYNTHESIS
    // the instruction start (the trace's S, the function bench's o_t_start; v35_top's observation
    // block reads it, no port carries it): a routine's entry word executes (`at_entry`: the word
    // is a routine's entry, not yet executed; an entry word is never the dispatch word, and an
    // entry word that is an E word executes with ex)
    reg        at_entry = 1'b0;
    always_ff @(posedge clock) begin
        if (!reset_n)
            at_entry <= 1'b0;
        else if (ce_a && ex_b)
            at_entry <= word.seq == SQ_DISP;
    end
    wire       start = at_entry && ex;
    // (S7b) chk: the ce_b registers against their sources at ce_a
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    // (MX5) the address read at ce_b against tick B's, and the derived bits against the word
    reg [UADDR_W-1:0] upc_ab = '0;
    always @(posedge clock) if (ce_b) upc_ab <= upc_a;
    // (qprobe round 6, timing) the ROM's address as formed against upc_a
    reg [UADDR_W-1:0] ra_ab = '0, ra_rb = '0;
    always @(posedge clock) if (ce_b) begin
        ra_ab <= raddr;
        ra_rb <= !reset_n ? UROM_RESET : upc_a;
    end
    // (MX5c) the registered stall outcome against the stalls of the facts as they stand, every
    // clock
    always @(posedge clock) begin
        if (chk_on && reset_n && st_r !== stall_f(si_now)) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: useq: the registered stall outcome differs at %0t", $time);
        end
    end
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (upc_ab !== upc_n || pd !== pre(word) || ra_ab !== ra_rb) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: the ROM's address or the derived bits differ at %0t", $time);
            end
            if (ex_b !== ex || d1_b !== dent || ig_b !== igo || sg_b !== sgo || d2_b !== dec2.entry || len_b !== len
                || dc_b !== dcall || dr_b !== dret || ecr_b !== ec_reg || ecc_b !== ec_call
                || ech_b !== ec_head || sp_b !== sp_n
                || il_b !== il || w_b !== fmt_w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: a tick A source changed in tick B at %0t", $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: useq: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
endmodule
