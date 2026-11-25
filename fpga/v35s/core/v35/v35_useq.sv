`timescale 1ns/1ps

// V35S core v2 (MX0): the microsequencer (docs/v35s-mechanisms.md sections 3.1, 4; README
// "MX0"). One microinstruction a CPU clock from a registered ROM word: the ROM ((work order 27)
// the 40-bit word L40, v35_l40_rom.hex, and its tables v35_l40_x.hex / v35_l40_y.hex, assembled
// by validation/v35s/chains/uasm.py; before, three 32-bit banks v35_urom_b?.hex, now the
// simulation's reference) is read at ce_a with the
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
//   (hold: E while an on-chip store was outstanding with RAMEN = 1; (WO31) gone: the store
//         lands in its cycle's first clock, before the next instruction's words read it)
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
// (consol, README "consol") These waits are the bus unit's now, the pace's owner: the sequencer
// presents the next word's kind (`wk_nx`: the dispatch word, a FLUSH word, rl == RL_X, bi) and
// reads one registered hold back (`ph_nx`, the D of `ph`): the stall `pace`. Round 6 read eleven
// facts here (the bus unit's fb_nx / fl_nx / cb_nx / sl_nx / fy_nx, the loader's b4_nx / ew_nx /
// ld_nx / le_nx, the EU's req_v_nx / rqm_nx) and formed the give-way (`lpri`) for the queue.
//
// The next microaddress (tick B): the same word (stalled), the next, a jump (on a registered
// condition), a call (one return register: the V20 ROM's FARJMP subroutines nest one level,
// V20UC.TXT 0000-04FF has no FARJMP from inside a FARJMP target), a return, a loop on the
// counter, or a dispatch from the decode registered at the end of tick A: DISP (the word after
// E) on the opcode the E word popped (v35_udec1 of the loader's opcode register); (qprobe round
// 17) DISPM (the second level on the byte a word pops) withdrawn: no routine used it. No
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
// copies ex_b 1, d1_b 10, (MX1) dc_b 1, dr_b 10 ((qprobe round 17) d2_b removed with DISPM).
// Quartus 17.1 reads one import in a module header, so the imports sit in $unit scope
// verilator lint_off IMPORTSTAR
import v35_front_pkg::*;
import v35_pkg::*;
// verilator lint_on IMPORTSTAR
module v35_useq
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
    input  v35_udecm_t dec2,            // v35_udec2(the opcode register, the word register's byte): (qprobe round 17) unread (DISPM withdrawn)
    input  wire        ec_reg,          // (MX3c) the EAC word's popped byte: register mode
    input  wire        ec_call,         // ... a memory mode with an EA head (called)
    input  wire [UADDR_W-1:0] ec_head,  // ... the head
    input  wire [2:0]  len,             // the instruction's bytes still to pop (the trap's LEN)
    input  wire [7:0]  il,              // the first immediate byte
    input  wire        fmt_w,           // the running form's width
    // the datapath (tick A: registers; rb_lo: tick B)
    input  wire        opr_rdy,         // F's datum is here
    input  wire        rq_busy,         // the request slot is taken
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
    input  wire        ramen,           // (WO46) PRC bit 6 (v35_sfr's register): the internal RAM
                                        //   enabled; RAMEN 0 marks the early end (below)
    // (MX5c) tick B: the next values of the stall's inputs (the D nets of their ce_a registers,
    // as they stand after the coming ce_a): the loader's, the datapath's, the bus unit's
    input  wire        q_stall_nx,
    input  wire        opr_rdy_nx,
    input  wire        rq_busy_nx,
    // (consol) the pace: the next word's kind (tick B, to the bus unit) and the bus unit's hold
    // for the next clock (tick B, ph_nx: the D of the registered fact)
    output v35_wk_t    wk_nx,
    input  wire        ph_nx,
    // (qprobe round 6) the word is the dispatch (the derived bit, a register; tick B: the next
    // word's): the loader's release on the dispatch word
    output wire        w_disp,
    output wire        w_disp_nx,
    // the word and its execution
    output v35_uword_t word,            // the current microinstruction (a register)
    output v35_uword_t word_nx,         // (MX5b) tick B: the next word (the ROM's read data; (work
                                        //   order 27) its early fields, and KW / POST as d1 / bus codes)
    output wire        w_dispm,         // (MX5) the word's derived bits (registers): seq == SQ_DISPM
    output wire        w_dispm_nx,      // (MX5c) tick B: the next word's seq == SQ_DISPM
    output wire        w_erep,          // (F5d) the word's derived bit (a register): e && ea == EA_REP
    output wire        w_erep_nx,       // ... tick B: the next word's
    output wire        ex,              // the word executes this clock (tick A)
    output wire        w_fa,            // (WO47) the word is an access wait (`fa`; a register beside
                                        //   the word): an F word that takes no datum (the EU's opr_v)
    output reg         ex_b,            // ... registered at ce_b (tick B, ce_a)
    // (step B) the take points and acts the interrupt / service unit (v35_intc) reads, named for
    // what they are (each an AND of the registered outcome and the word's fields or derived
    // bits): tick A
    output wire        x_disp,          // the dispatch word executes: an instruction boundary
    output wire        x_tki,           // a TKI word executes: a string's take point
    output wire        x_end,           // (WO38) the instruction's look (below): the word releasing
                                        //   the next opcode, held open to the dispatch ...
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
    // (work order 27) the ROM is the 40-bit word L40 (docs/v35s-urom-w40-layout.md; uasm.py's
    // L40 section, v35_l40.svh): one ROM of 2,048 x 40 (v35_l40_rom.hex), read at ce_b with the
    // address formed in tick A as before. Its early fields (SEQ, K, POP, WID, RA / RB, B) are at
    // fixed positions in every word and are read raw in tick B; the late fields are two codes
    // into the tables X (256 x {alu ax ay wf cnt}) and Y (512 x {d1 s1 d2 s2 wr ws ea bus seg
    // pfx susp halt ist}: {POST half, index}), block RAMs read at `!reset_n || ce_a` (the word
    // register's own enable) at the address the word's form gives (`xa`, `ya`, formed from the
    // ROM's read data in tick B). The word a clock executes is the early fields' flops (`qe`)
    // and the tables' read data (`xq`, `yq`): `word` is the same v35_uword_t as before, field
    // for field. (work order 26 and before: three 32-bit banks of the 96-bit word, read the same
    // way; in simulation they remain the reference, `+v35_chk` below.) The address stays
    // UADDR_W bits wide (the loader's dent / dret / ec_head ports); its top bit is 0
    /* verilator lint_off UNUSEDPARAM */
    `include "v35_l40.svh"
    /* verilator lint_on UNUSEDPARAM */
    localparam int ROM_WORDS = L40_WORDS;
    reg [L40_BITS-1:0]  rom  [0:ROM_WORDS-1];
    reg [L40_XBITS-1:0] xtab [0:255];
    reg [L40_YBITS-1:0] ytab [0:511];
    initial begin
        $readmemh({UROM_DIR, "v35_l40_rom.hex"}, rom);
        $readmemh({UROM_DIR, "v35_l40_x.hex"}, xtab);
        $readmemh({UROM_DIR, "v35_l40_y.hex"}, ytab);
    end

    reg [UADDR_W-1:0] upc = UROM_RESET;
    // (MX5) the ROM is read a tick earlier: at ce_b (`rd`, the RAM's read data) with the next
    // address decided in tick A (`upc_a`), the word a plain register loaded from the read data
    // at ce_a. The word a clock executes is the one the old ce_a read gave: the address is the
    // same function of the same values (README "MX5")
    reg [L40_BITS-1:0] rd = '0;                         // the ROM's read data (ce_b)
    wire [4:0]  s5  = rd[L40_SEQ_LSB +: L40_SEQ_W];     // SEQ
    wire [8:0]  kk  = rd[L40_K_LSB +: L40_K_W];         // {e f nb bi vk ro rl[1:0] flush}
    wire [2:0]  rpp = rd[L40_POP_LSB +: L40_POP_W];
    wire [1:0]  rwd = rd[L40_WID_LSB +: L40_WID_W];
    wire [4:0]  rra = rd[L40_RA_LSB +: L40_RA_W];
    wire [4:0]  rrb = rd[L40_RB_LSB +: L40_RB_W];
    wire [10:0] rbb = rd[L40_B_LSB +: L40_B_W];
    wire        esc = rra >= L40_ESC;                   // no register: {RA[1:0], RB} is payload P
    wire        tf  = s5[4] || s5[3];                   // B is the target (or the vector number)
    wire [6:0]  p7  = {rra[1:0], rrb};
    // the early one-bit facts (layout 2.6): the word posts a request; KW, the word loads OPRW
    // (read for the arming word of an unarmed write: form N's B[0])
    wire        e_post = tf ? (esc && rra[1:0] == 2'd3) : rbb[10];
    wire        e_kw = esc && !tf && s5 != L40_SQ_HOLD && rbb[0];
    // SEQ -> seq, cond, tgt (TKI: the take entry, generated; SEQ >= 8: B)
    logic [3:0] e_seq;
    always_comb begin
        if (s5[4])
            e_seq = s5[3] ? SQ_JNC : SQ_JC;
        else begin
            case (s5)
                L40_SQ_RET: e_seq = SQ_RET;
                L40_SQ_TKI0, L40_SQ_TKI1: e_seq = SQ_TKI;
                L40_SQ_DISP, L40_SQ_DISP + 5'd1: e_seq = SQ_DISP;
                L40_SQ_JMP: e_seq = SQ_JMP;
                L40_SQ_CALL: e_seq = SQ_CALL;
                L40_SQ_LOOP: e_seq = SQ_LOOP;
                L40_SQ_EAC: e_seq = SQ_EAC;
                L40_SQ_TRAP: e_seq = SQ_TRAP;
                default: e_seq = SQ_NEXT;               // NEXT, EREP, VEC (B the vector)
            endcase
        end
    end
    wire [UADDR_W-1:0] e_tgt = s5 == L40_SQ_TKI0 ? L40_TKI0 : s5 == L40_SQ_TKI1 ? L40_TKI1
                             : tf ? {{(UADDR_W - L40_B_W){1'b0}}, rbb} : '0;
    // the next word as tick B has it (`word_nx`): the early fields raw from the ROM's read data
    // (RA / RB too: a word that names no register reads selector 28..31, which v35_eu's rsel_g
    // reads as RS_NONE's address 0: no gate in front of the early read); of the late fields only
    // the one-bit facts tick B reads, each as its field's code: d1 = OPRW for KW (the EU's k_nx),
    // bus = MEMR for POST (the EU's post flop); every other late field 0
    // (WO46, README "WO46") the early end. With the internal RAM disabled (RAMEN 0) the end of a
    // data-access routine (the next opcode's pop E and the dispatch) rides on its last two words:
    // a word marked for it is the routine's E word (the next opcode popped and released), and the
    // word executed after it is the dispatch word whatever its own acts (a store's datum and
    // post, a read-modify-write's Z, a compare's word with no act); the routine's own E word and
    // dispatch behind them are then not reached. Two free codes of the K field mark it (uasm `ee`):
    //   vk alone (no bi, rl not x) on a word whose SEQ is NEXT, JMP, CALL, RET (the layout's forms of
    //     NEXT) or LOOP (vk is otherwise SR_VEC's
    //     on a vector word, SEQ VEC or TRAP; (WO47) on a posting word the mode post p1's): a plain
    //     word; on a LOOP word only on the loop's exit (the counter at 1: the loop body loads no
    //     counter, uasm), an E word being followed by its dispatch word alone
    //   nb with bi on a word that is not E (nb is otherwise an E word's, or the CH_BNEXT mark of a
    //     word with no bus-wait kind): a bus-idle word, which keeps its wait (E with bi: G N)
    // The forced word is an ordinary E word to every reader (`e`, `ro`; nb cleared). With RAMEN 1
    // no term below is 1 and the word runs as it reads (vk alone and nb with bi have no other
    // meaning: wk_bn below excludes bi)
    reg [8:0]  cnt = 9'd0;                  // the loop counter (declared here: the early end reads it)
    wire        ee_v = kk[4] && !kk[5] && kk[2:1] != 2'd3 && !e_post        // (WO47) vk on a post: p1
                       && !kk[0]                                         // (WO48) vk with flush: er
                       && (s5 == L40_SQ_NEXT || s5 == L40_SQ_JMP || s5 == L40_SQ_CALL || s5 == L40_SQ_RET
                           || (s5 == L40_SQ_LOOP && cnt == 9'd1));
    wire        ee_b = kk[6] && kk[5] && !kk[8];
    // ((WO47, round 4) work order 46's mode branch, a JC on DN with vk entering REP STM's and REP
    // MOVBK's RAMEN 0 bodies, is withdrawn with those bodies: the two routines run one body in both
    // modes, user ruling 2026-11-24)
    // (WO48, README "WO48") the early end with the release a word ahead (`er`): the vk bit with the flush
    // bit on a plain word (no F, no bus wait, no post; never a FLUSH word in either mode). With RAMEN 0 the
    // word releases the next opcode (ro), the word executed after it is the E word (no release of its own:
    // e2) and the word after that the dispatch (ee_q / ed_q as the early end's); with RAMEN 1 a word with no
    // act. uasm checks the code on the packed image and the word after it (_finish)
    wire        er_c = kk[4] && kk[0] && !kk[7] && !kk[5] && kk[2:1] != 2'd3 && !e_post;
    wire        er_nx = er_c && !ramen;
    reg         er_q = 1'b0;                // the word now is an `er` word (RAMEN 0)
    reg         e2_q = 1'b0;                // the word now is the E word behind it
    wire        e2_nx = (er_q && ex) || (e2_q && !ex);     // the word read now follows it (or is it still, stalled)
    wire        ee_nx = ((ee_v || ee_b) && !ramen) || e2_nx;
    // (WO47, README "WO47") three more free codes of the K field, each read with RAMEN:
    //   `fa`, the access wait: f with the flush bit (a FLUSH word never waits, uasm). With RAMEN 1 an
    //     F word (it waits for its request's cycle as F does) that takes nothing: `w_fa` tells the EU
    //     to leave the datum-valid flag for the F word behind it that takes the datum; with RAMEN 0
    //     a plain word. Never a FLUSH word
    //   `p1`, a posting word with vk: it posts with RAMEN 1 only
    //   `p0`, a posting word with the flush bit (not f): it posts with RAMEN 0 only (never a FLUSH)
    // A masked post is a word with no post to every reader: the early POST bit (the EU's post
    // flop, the slot stall), the late bus field (pm_q below). With RAMEN 1 the access wait is the
    // F word it replaced and a p0 word a word with no act; uasm checks on the packed image that
    // each decode selects exactly the words marked with it
    wire        fa_c = kk[7] && kk[0];
    wire        e_pm = e_post && ((kk[4] && !ramen) || (kk[0] && !kk[7] && ramen));
    wire        e_post_m = e_post && !e_pm;
    reg         pm_q = 1'b0;                // the word now is a mode post masked in this mode
    reg         fa_q = 1'b0;                // the word now carries the access wait's code
    always_ff @(posedge clock)
        if (!reset_n || ce_a) begin
            pm_q <= e_pm;
            fa_q <= fa_c;
        end
    assign w_fa = fa_q;
    reg         ee_q = 1'b0;                // the word now is an early-end word (RAMEN 0)
    reg         ed_q = 1'b0;                // the word now is its dispatch word
    wire        ed_nx = (ee_q && ex) || (ed_q && !ex);     // the word read now follows it (or is it still, stalled): the dispatch
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            ee_q <= 1'b0;
            ed_q <= 1'b0;
            er_q <= 1'b0;
            e2_q <= 1'b0;
        end else if (ce_a) begin
            ee_q <= ee_nx;
            ed_q <= ed_nx;
            er_q <= er_nx;
            e2_q <= e2_nx;
        end
    end
    v35_uword_t wnx;
    always_comb begin
        wnx = '0;
        {wnx.e, wnx.f, wnx.nb, wnx.bi, wnx.vk, wnx.ro} = kk[8:3];
        if (ee_nx) begin
            wnx.e = 1'b1;
            wnx.ro = !e2_nx;                // (WO48) behind an `er` word the release is done
            wnx.nb = 1'b0;
        end
        if (er_nx)
            wnx.ro = 1'b1;                  // (WO48) `er`: the next opcode released a word ahead
        wnx.rl = v35_rl_e'(kk[2:1]);
        wnx.flush = kk[0] && !kk[7] && !e_post && !er_c;    // (WO47) not fa's, not p0's; (WO48) not er's
        if (fa_c && !ramen)
            wnx.f = 1'b0;                   // (WO47) the access wait with RAMEN 0: a plain word
        wnx.pop = v35_pop_e'(rpp);
        wnx.wid = v35_wid_e'(rwd);
        wnx.ra = v35_rsel_e'(rra);
        wnx.rb = v35_rsel_e'(rrb);
        wnx.seq = ed_nx ? SQ_DISP : v35_seq_e'(e_seq);
        wnx.cond = v35_cond_e'(s5[4] ? s5[2:0] : 3'd0);
        wnx.tgt = e_tgt;
        wnx.d1 = e_kw ? MD_OPRW : MD_NONE;
        wnx.bus = e_post_m ? BQ_MEMR : BQ_NONE;
    end
    assign word_nx = wnx;
    // the tables' addresses by the word's form (layout 2.4; uasm l40_table_addr): N (no register,
    // no target) X {P, B[1]}, Y {B[10], B[9:2]}; NT (target) one page code in P; R (a register,
    // no target) X B[9:2], or Y {B[10], B[9:2]}, or both pages; RT none. Address 0 of each table
    // is the empty payload
    logic [7:0] xa;
    logic [8:0] ya;
    always_comb begin
        xa = 8'd0;
        ya = 9'd0;
        if (esc) begin
            if (tf) begin
                if (p7 < 7'd48)
                    xa = {1'b1, p7};                        // X NT (L40_XPAGE_NT = 128)
                else
                    ya = {p7[6] && p7[5], 1'b1, p7};      // 48..95: Y NT, 96..127: Y NT1 (posts)
            end else begin
                xa = {p7, rbb[1]};
                ya = {rbb[10], rbb[9:2]};
            end
        end else if (!tf) begin
            if (rbb[0]) begin
                xa = 8'(L40_XPAGE_R) | {4'd0, rbb[4:1]};
                ya = {rbb[10], 8'(L40_YPAGE_R) | {3'd0, rbb[9:5]}};
            end else if (rbb[1])
                ya = {rbb[10], rbb[9:2]};
            else
                xa = rbb[9:2];
        end
    end
    // the registered word: the early fields' flops (`qe`, RA / RB 0 when the word names no
    // register, as the 96-bit word has them) and the tables' read data (`xq`, `yq`), all loaded
    // at `!reset_n || ce_a` as the 96-bit word register was
    v35_uword_t qe = '0;
    reg [L40_XBITS-1:0] xq = '0;
    reg [L40_YBITS-1:0] yq = '0;
    // (the w40 trial's repair 3) one-bit flops beside the word for the late facts that head
    // paths into the bus grant and the interrupt controller, from the table address in tick B
    // (the svh's functions: the entries the assembler placed): SUSP (q_susp, sp_n), IVEC /
    // FINT (x_ivec, x_fint). (KW for k_cur and POST for the EU's post are the EU's flops of
    // word_nx; `pd.post` here)
    reg        su_q = 1'b0, iv_q = 1'b0, fi_q = 1'b0;
    always_comb begin
        word = qe;
        {word.alu, word.ax, word.ay, word.wf, word.cnt} = xq;
        {word.d1, word.s1, word.d2, word.s2, word.wr, word.ws, word.ea, word.bus, word.seg,
         word.pfx, word.susp, word.halt, word.ist} = yq;
        if (pm_q)
            word.bus = BQ_NONE;             // (WO47) the mode post masked in this mode
    end
    // (MX5) the word's derived bits (the field compares the stall terms and the take points
    // read), decoded from the next word's read data in tick B and registered with the word
    // at ce_a: `pd` is always the function `pre(word)` of the word it sits beside
    typedef struct packed {
        logic post;         // bus != BQ_NONE, BQ_RSV
        logic disp;         // seq == SQ_DISP
        logic dispm;        // seq == SQ_DISPM
        logic erep;         // (F5d) e && ea == EA_REP: the E pop re-enters the REP page
        logic tki;          // (F5e) seq == SQ_TKI: a string's take point
    } v35_upre_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_upre_t pre(input v35_uword_t w);
        pre.post = w.bus != BQ_NONE && w.bus != BQ_RSV;   // (round 18) RSV posts nothing
        pre.disp = w.seq == SQ_DISP;
        pre.dispm = w.seq == SQ_DISPM;
        pre.erep = w.e && w.ea == EA_REP;
        pre.tki = w.seq == SQ_TKI;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    v35_upre_t pd = '0;
    assign w_dispm = pd.dispm;
    assign w_disp = pd.disp;
    assign w_erep = pd.erep;

    reg [UADDR_W-1:0] retr = '0;
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
        logic       halted, f, post;
        logic       q_stall, opr_rdy, rq_busy;
        logic       disp;               // (qprobe) the word is the dispatch (the boundary)
        logic       ph;                 // (consol) the bus unit's pace holds the word
    } v35_sin_t;
    typedef struct packed {
        logic       ex;
        logic [4:0] why;    // the stall's reason (the trace's W): 0 none, 1 q, 2 f, 3 slot, 4 hold,
                            //   5 halt, (qprobe) 6 the boundary's, 7 a B word's
    } v35_stl_t;
    function automatic v35_stl_t stall_f(input v35_sin_t f);
        logic st_q, st_f, st_slt, st_pc;
        st_q   = f.q_stall;                 // the queue: a pop finds no byte
        st_f   = f.f && !f.opr_rdy;         // the bus cycle: F's datum not here
        st_slt = f.post && f.rq_busy;       // the one request slot taken
        // ((WO31) the on-chip store's hold of E, 4, is gone: the store lands in its cycle's first
        // clock)
        // (consol) the pace: the measured front-end waits (the boundary's, the bus-wait kinds'),
        // the bus unit's (ph_nx)
        st_pc  = f.ph;
        stall_f.ex = !f.halted && !st_q && !st_f && !st_slt && !st_pc;
        // (the boundary's, 6, or a bus-wait kind's, 7: the dispatch word has no bus-wait kind)
        stall_f.why = f.halted ? 5'd5 : st_q ? 5'd1 : st_f ? 5'd2 : st_slt ? 5'd3
                    : (st_pc && f.disp) ? 5'd6 : st_pc ? 5'd7 : 5'd0;
    endfunction
    // (qprobe) the facts of rules 4 and 5 as they stand: ce_a registers of their next values
    // (in reset none: no cycle runs, nothing is delivered)
    reg        ph = 1'b0;               // (consol) the pace's hold as it stands
    reg        sp = 1'b0;
    v35_sin_t  si_now;
    always_comb begin
        si_now.halted = halted;
        si_now.f = word.f;
        si_now.post = pd.post;
        si_now.q_stall = q_stall;
        si_now.opr_rdy = opr_rdy;
        si_now.rq_busy = rq_busy;
        si_now.disp = pd.disp;
        si_now.ph = ph;
    end
    v35_stl_t  st_r = '0;
    assign ex = st_r.ex;
    // (step B) the take points and acts (v35_top's glue before: the same terms)
    assign x_disp = ex && pd.disp;
    assign x_tki = ex && pd.tki;
    // (WO38) `x_end` is the instruction's look: the clock the controller samples the request
    // line and NMI (validation/v35s/passage.py third and fourth probes, RESULTS3 Q2 / RESULTS4:
    // one fixed clock of the instruction's own routine, the end of its execution). It is the
    // word that releases the next opcode (`ro`: the E word unless the routine releases it
    // earlier, NOP / XCH AW,r / CVTBW / CMPM / the bit ops' register forms; uasm.py gives every
    // path one `ro` before or on its E). When the release is the E word and the dispatch word
    // behind it is held, the look stays open through the held clocks (`lk_o`) while nothing of
    // the routine's own is on the bus: no request of the EU's outstanding (`rq_busy`: a
    // store's, PUSH's, an on-chip store's write, with its wait states and the timer grid's)
    // and the held word posts nothing (OUT's I/O write is posted on its dispatch word). So a
    // routine whose last act is its E word (INC, MULU, DIVU, a shift, a read, BR) is looked at
    // up to its dispatch, a store one clock in front of its write's end however long the wait,
    // NOP / XCH two clocks and CVTBW one in front of the E word. No opcode is named: the marks
    // are the ROM's `ro` and `e` fields and the bus unit's request slot
    // (WO39) A dispatch that follows no E word (`redisp`: the DMA routine's end, the
    // interrupted opcode dispatched again from the queue kept) is looked at on the word in
    // front of it (the service's last word: `pd_nx.disp` with this word not an E word); every
    // other dispatch word follows its E word
    reg        lk_o = 1'b0;
    // (x_end is assigned below pd_nx, the next word's derived bits)
    assign x_nb = ex && word.e && word.nb;
    assign x_nbi = ex && word.e && word.seg == SG_NBI;
    assign x_flush = ex && word.flush;
    assign w_stop = word.halt && word.cnt == CN_STOP;
    assign x_stop = ex_b && w_stop;
    assign x_ivec = ex_b && iv_q;       // (work order 27) word.alu == AL_IVEC, a flop
    assign x_fint = ex_b && fi_q;       // ... AL_FINT
    // (MX2) SUSP suspends prefetching (the queue's request line held low from the clock the word
    // is reached until the FLUSH: `sp` once it has executed)
    // (consol) and halted: no prefetch while the sequencer is halted (the loader's fstop read
    // the halted state before; the queue's line is low for either)
    assign q_susp = (sp && !word.flush) || su_q || halted;     // (the FLUSH word issues the target's fetch; su_q: word.susp, a flop)
    // (MX2) the suspension stands from the SUSP word's execution to the FLUSH (or an E)
    wire       sp_n = (ex && (word.flush || word.e)) ? 1'b0 : (ex && su_q) ? 1'b1 : sp;

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg [UADDR_W-1:0] d1_b = '0, dr_b = '0;
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
            len_b <= len;
            il_b <= il;
            w_b <= fmt_w;
        end
    end

    // (MX5c) the stall's facts as they stand after the coming ce_a (tick B: the next word and
    // its derived bits, the ce_b registers the counters load, the other modules' next values)
    // and the registered outcome
    // (work order 27) from the raw word (layout 2.6): `pre(word_nx)` of the 96-bit word
    // (`+v35_chk`)
    v35_upre_t pd_nx;
    always_comb begin
        // (WO47, round 4) the slot's stall reads a p1 word as posting in both modes: with RAMEN 0 it
        // posts nothing but is still the request's place and waits for the slot there; the cycle is
        // posted by the p0 word behind it. A p0 word with RAMEN 1 neither posts nor waits
        pd_nx.post = e_post && !(kk[0] && !kk[7] && ramen);
        pd_nx.disp = s5[4:1] == L40_SQ_DISP[4:1] || ed_nx;
        pd_nx.dispm = 1'b0;                 // (qprobe round 17) DISPM withdrawn
        pd_nx.erep = kk[8] && s5[0];        // an E word's SEQ is NEXT, EREP or JMP (uasm)
        pd_nx.tki = s5[4:1] == L40_SQ_TKI0[4:1];
    end
    assign w_dispm_nx = pd_nx.dispm;
    assign w_disp_nx = pd_nx.disp;
    assign x_end = (ex && word.ro) || (lk_o && pd.disp && !ex && !rq_busy && !pd.post)
                   || (ex && !word.e && pd_nx.disp);       // (WO39) the redisp's look (above)
    assign w_erep_nx = pd_nx.erep;
    // (consol) the next word's kind for the bus unit's pace
    // (r24, work order 20 A4, Q111) a bus-idle word that releases a byte (bi, no vk, not FLUSH, rl 1 /
    // 2 or ro) presents the kind's free code dispatch with bi (the dispatch word never has bi): the
    // bus unit's wait against a back-to-back fetch at four or fewer held (`kbp`)
    wire        wk_bp = word_nx.bi && !word_nx.vk && !word_nx.flush && word_nx.rl != RL_X
                        && (word_nx.rl != RL_0 || word_nx.ro);
    assign wk_nx.disp = pd_nx.disp || wk_bp;
    // (qprobe round 23, spec 18 A2) the strict word (bi vk rl == RL_2) presents C's code with
    // the flush bit: the kind's free code flush with alt (a FLUSH word never carries vk), so
    // the bus unit tells it from the commit word C, which passes on the third-last clock of the
    // chain's second fetch and the strict word does not
    wire        wk_st = word_nx.bi && word_nx.vk && word_nx.rl == RL_2;
    // (r24, model_m CH_BNEXT, Q42's second half) nb on a word that is not an E word: a word with
    // no bus-wait kind followed by a bus-idle word (the assembler's mark, uasm _mark_bnext). It
    // presents the kind's free code flush with alt and no bi (the strict word has bi; a FLUSH
    // word never carries vk), so the bus unit can keep the fetch chained behind a write's fetch
    // from starting on the clock this word executes
    wire        wk_bn = word_nx.nb && !word_nx.e && !word_nx.bi;     // (WO46) nb with bi: the early end's mark
    // (WO48, README "WO48") a word that releases operand bytes (rl 1 / 2) and is not a bus-idle word presents
    // the kind's free code rl=x with flush (no bi; alt keeps wk_bn's mark): the bus unit's release-word wait
    // (it waits while the EU's memory write has a clock left after the next). No word has rl=x with a FLUSH
    // (uasm checks it on the image), and no FLUSH word releases without bi (likewise)
    wire        wk_rl = (word_nx.rl == RL_1 || word_nx.rl == RL_2) && !word_nx.bi;
    assign wk_nx.flush = word_nx.flush || wk_st || wk_bn || wk_rl;
    assign wk_nx.rlx = word_nx.rl == RL_X || wk_rl;
    // (qprobe round 21, spec 10 A1 / Q42's second half, C_NOCH) the commit word that releases a
    // byte (bi with vk and rl == RL_1: `P C`) presents the kind's free code, alt alone (bi
    // low): the bus unit's C wait without the fetch chained behind a write's fetch. alt is the
    // vk bit on a bus-wait word only (bi or rl == RL_X: an SR_VEC word's vk is not a kind), so
    // alt alone has this one meaning; the strict word (bi vk rl == RL_2) keeps C's code, marked by
    // the flush bit (below)
    wire        wk_cr = word_nx.bi && word_nx.vk && word_nx.rl == RL_1;
    assign wk_nx.bi = word_nx.bi && !wk_cr;
    assign wk_nx.alt = (word_nx.vk && (word_nx.bi || word_nx.rl == RL_X)) || wk_bn;     // (qprobe round 10) the wait's second kind (C, V); (r24) wk_bn's code
    v35_sin_t  si_nx;
    always_comb begin
        si_nx.halted = (halted || (ex_b && word.halt)) && !wake;     // (F3) the release
        si_nx.f = word_nx.f;
        si_nx.post = pd_nx.post;
        si_nx.q_stall = q_stall_nx;
        si_nx.opr_rdy = opr_rdy_nx;
        si_nx.rq_busy = rq_busy_nx;
        si_nx.disp = pd_nx.disp;
        si_nx.ph = ph_nx;
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            st_r <= stall_f(si_now);
            ph <= 1'b0;
        end else if (ce_a) begin
            st_r <= stall_f(si_nx);
            ph <= ph_nx;
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
    // (ex for ex_b, dent for d1_b, the EAC facts for ecr_b / ecc_b / ech_b,
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
    wire               s_ds = r_go && word.seq == SQ_DISP;
    wire               s_ec = r_go && word.seq == SQ_EAC;
    wire               s_tk = r_go && word.seq == SQ_TKI;
    wire               s_jc = r_go && word.seq == SQ_JC;
    wire               s_jn = r_go && word.seq == SQ_JNC;
    // (timing repair 1) the late one-bit facts (the take point's sgo, the dispatch's igo, the
    // EAC word's ec_reg, the condition) are exclusive by the word's seq, so they are merged into
    // one bit (`lt`) that selects last between the two addresses formed beside it without them
    // (`a1` with the fact 1, `a0` with it 0): the same select as before (`+v35_chk` compares
    // raddr with upc_a), each fact one LUT from the ROM's address instead of the select chain.
    // ((work order 26) the high part's copy of `lt` and of the last stage, `lt_h` / `rah`, went
    // with the high part)
    wire [UADDR_W-1:0] ec0 = ec_call ? ec_head : inc;
    (* syn_keep = "true" *) wire [UADDR_W-1:0] a1 = s_ec ? word.tgt : s_ds ? UROM_INT
                                                   : (s_tk || s_jc) ? word.tgt : s_jn ? inc : ra_e;
    (* syn_keep = "true" *) wire [UADDR_W-1:0] a0 = s_ec ? ec0 : s_ds ? dent
                                                   : (s_tk || s_jc) ? inc : s_jn ? word.tgt : ra_e;
    (* syn_keep = "true" *) wire lt_l = s_tk ? sgo : s_ds ? igo : s_ec ? ec_reg : cond_a;
    (* syn_keep = "true" *) wire [UADDR_W-1:0] raddr = lt_l ? a1 : a0;
    always_ff @(posedge clock) begin
        if (!reset_n || ce_b)
            rd <= rom[raddr[10:0]];
    end
    always_ff @(posedge clock) begin
        if (!reset_n || ce_a) begin
            qe <= wnx;
            if (esc) begin
                qe.ra <= RS_NONE;
                qe.rb <= RS_NONE;
            end
            xq <= xtab[xa];
            yq <= ytab[ya];
            su_q <= v35_l40_ysusp(ya);
            iv_q <= v35_l40_xivec(xa);
            fi_q <= v35_l40_xfint(xa);
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
            lk_o <= 1'b0;
        end else if (ce_a) begin
            upc <= upc_n;
            cnt <= cnt_n;
            sp <= sp_b;
            if (ex_b && (word.seq == SQ_CALL || (word.seq == SQ_EAC && !ecr_b && ecc_b)))
                retr <= inc;
            else if (ex_b && word.seq == SQ_DISP && dc_b)
                retr <= dr_b;      // (MX1) the dispatch's call of an EA head
            halted <= (halted || (ex_b && word.halt)) && !wake;     // (F3) the release
            // (WO38) the look held open from an E word that releases the next opcode (not a
            // no-boundary E: nb) to its dispatch word's execution
            if (ex_b && word.e)
                lk_o <= word.ro && !word.nb;
            else if (ex_b && pd.disp)
                lk_o <= 1'b0;
        end
    end

    // (st_r.why: the stall's reason, the trace's W: v35_top's observation block)
    // ((step D) the word is 92 bits: the banks' top four bits unread)
    // ((qprobe) the word is 96 bits: the banks' every bit read)
    // ((work order 26) the address's top bit: 0, the ROM is one part of 2,048 words)
    wire unused = &{1'b0, dec2, st_r.why, raddr[UADDR_W-1:11]};

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
    // (timing repair 1) the address against its reference, every clock; ((work order 26) the
    // high part's copy is gone) and the address inside the one part
    always @(posedge clock) begin
        if (chk_on && (raddr !== (!reset_n ? UROM_RESET : upc_a) || raddr[UADDR_W-1:11] != '0)) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: useq: the ROM's address differs from its reference or leaves the ROM at %0t", $time);
        end
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
    // (WO47, round 4) the derived bits of the word now: a p1 word masked with RAMEN 0 (pm_q with vk)
    // still reads as posting for the slot (pd_nx.post)
    v35_upre_t pre_w;
    always_comb begin
        pre_w = pre(word);
        if (pm_q && word.vk)
            pre_w.post = 1'b1;
    end
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            // (qprobe round 17) the DISPM source is withdrawn (no routine had one; uasm rejects it)
            if (ex && word.seq == SQ_DISPM) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: a DISPM word executed at %0t (the source is withdrawn)", $time);
            end
            if (upc_ab !== upc_n || pd !== pre_w || ra_ab !== ra_rb) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: the ROM's address or the derived bits differ at %0t", $time);
            end
            if (ex_b !== ex || d1_b !== dent || ig_b !== igo || sg_b !== sgo || len_b !== len
                || dc_b !== dcall || dr_b !== dret || ecr_b !== ec_reg || ecc_b !== ec_call
                || ech_b !== ec_head || sp_b !== sp_n
                || il_b !== il || w_b !== fmt_w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: a tick A source changed in tick B at %0t", $time);
            end
        end
    end
    // (work order 27) the reference: the 96-bit ROM (v35_urom_b0..b2.hex, the same layout,
    // the same addresses), read at the same address with the same enables as the 40-bit ROM
    // and its tables. Every clock the word the core uses (the early fields' flops and the
    // tables' read data) is compared with the 96-bit word, whole; the early facts of tick B
    // (the raw fields word_nx carries, the derived bits pd_nx, KW) with the 96-bit read data's;
    // and the one-bit flops beside the word with the fields they stand for
    // the page bases the address select builds in (X NT and Y NT / NT1 at 128 + P, X R at 16 +,
    // Y R at 32 +) against the generated constants
    if (L40_XPAGE_NT != 128 || L40_YPAGE_NT != 128 + 48 || L40_YPAGE_NT1 != 128 + 96
        || L40_XPAGE_R != 16 || L40_YPAGE_R != 32) begin : g_pages
        $error("v35_useq: the L40 page bases differ from the address select's");
    end
    reg [31:0] rom0 [0:ROM_WORDS-1];
    reg [31:0] rom1 [0:ROM_WORDS-1];
    reg [31:0] rom2 [0:ROM_WORDS-1];
    integer i;
    initial begin
        for (i = 0; i < ROM_WORDS; i = i + 1) begin
            rom0[i] = 32'd0;
            rom1[i] = 32'd0;
            rom2[i] = 32'd0;
        end
        $readmemh({UROM_DIR, "v35_urom_b0.hex"}, rom0, 0, ROM_WORDS - 1);
        $readmemh({UROM_DIR, "v35_urom_b1.hex"}, rom1, 0, ROM_WORDS - 1);
        $readmemh({UROM_DIR, "v35_urom_b2.hex"}, rom2, 0, ROM_WORDS - 1);
    end
    reg [31:0] r0 = 32'd0, r1 = 32'd0, r2 = 32'd0;     // the reference's read data (ce_b)
    reg [31:0] q0 = 32'd0, q1 = 32'd0, q2 = 32'd0;     // ... its word register (ce_a)
    always @(posedge clock) begin
        if (!reset_n || ce_b) begin
            r0 <= rom0[raddr[10:0]];
            r1 <= rom1[raddr[10:0]];
            r2 <= rom2[raddr[10:0]];
        end
        if (!reset_n || ce_a) begin
            q0 <= r0;
            q1 <= r1;
            q2 <= r2;
        end
    end
    wire [95:0] rw_ref = {r2, r1, r0};
    wire [95:0] qw_ref = {q2, q1, q0};
    reg         ramen_c = 1'b1;             // RAMEN as the word register has it (the checker's)
    always @(posedge clock)
        if (!reset_n || ce_a)
            ramen_c <= ramen;
    v35_uword_t nx_raw, w_raw, nx_ref, w_ref;
    v35_upre_t  pd_ref;
    assign nx_raw = v35_uword_t'(rw_ref[UWORD_BITS-1:0]);
    assign w_raw = v35_uword_t'(qw_ref[UWORD_BITS-1:0]);
    // (WO46) the reference with the early end's forcing (RAMEN 0): the E word's e / ro / nb, its
    // dispatch word's seq
    always_comb begin
        nx_ref = nx_raw;
        w_ref = w_raw;
        if (ee_nx) begin
            nx_ref.e = 1'b1;
            nx_ref.ro = !e2_nx;
            nx_ref.nb = 1'b0;
        end
        if (er_nx)
            nx_ref.ro = 1'b1;
        if (ed_nx)
            nx_ref.seq = SQ_DISP;
        if (ee_q) begin
            w_ref.e = 1'b1;
            w_ref.ro = !e2_q;
            w_ref.nb = 1'b0;
        end
        if (er_q)
            w_ref.ro = 1'b1;
        if (ed_q)
            w_ref.seq = SQ_DISP;
        // (WO47) the access wait and the mode posts, decoded from the reference's own fields
        // (the next word with RAMEN, the word now with RAMEN as it was loaded: ramen_c)
        nx_ref = ref_mode(nx_ref, ramen);
        w_ref = ref_mode(w_ref, ramen_c);
        // (WO47, round 4) the derived POST bit the slot reads: a p1 word's in both modes
        pd_ref = pre(nx_ref);
        if (pre(nx_raw).post && nx_raw.vk && !ramen)
            pd_ref.post = 1'b1;
    end
    function automatic v35_uword_t ref_mode(input v35_uword_t w, input logic rm);
        ref_mode = w;
        if (w.f && w.flush) begin               // fa: never a FLUSH; F with RAMEN 1 only
            ref_mode.flush = 1'b0;
            if (!rm)
                ref_mode.f = 1'b0;
        end else if (pre(w).post && w.vk) begin // p1: posts with RAMEN 1 only
            if (!rm)
                ref_mode.bus = BQ_NONE;
        end else if (pre(w).post && w.flush) begin  // p0: posts with RAMEN 0 only, never a FLUSH
            ref_mode.flush = 1'b0;
            if (rm)
                ref_mode.bus = BQ_NONE;
        end else if (w.vk && w.flush && !w.bi && w.rl != RL_X)     // (WO48) er: never a FLUSH
            ref_mode.flush = 1'b0;
    endfunction
    wire       kw_ref = nx_ref.d1 == MD_OPRW || nx_ref.d2 == MD_OPRW;
    always @(posedge clock) begin
        if (chk_on) begin
            // the word, whole
            if (word !== w_ref) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: the L40 word differs from the 96-bit ROM's at upc %0d at %0t",
                             upc, $time);
            end
            // the early facts of tick B
            if (pd_nx !== pd_ref || (e_kw && !kw_ref)
                || {wnx.e, wnx.f, wnx.nb, wnx.bi, wnx.vk, wnx.ro, wnx.rl, wnx.flush, wnx.pop, wnx.wid,
                    wnx.seq, wnx.cond, wnx.tgt}
                   !== {nx_ref.e, nx_ref.f, nx_ref.nb, nx_ref.bi, nx_ref.vk, nx_ref.ro, nx_ref.rl,
                        nx_ref.flush, nx_ref.pop, nx_ref.wid, nx_ref.seq, nx_ref.cond, nx_ref.tgt}
                || (esc ? (nx_ref.ra != RS_NONE || nx_ref.rb != RS_NONE)
                        : (wnx.ra !== nx_ref.ra || wnx.rb !== nx_ref.rb))) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: an early field or fact of the L40 read differs from the 96-bit ROM's at %0t",
                             $time);
            end
            // the one-bit flops beside the word
            if (su_q !== word.susp || iv_q !== (word.alu == AL_IVEC) || fi_q !== (word.alu == AL_FINT)) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: a flop beside the word differs from its field at %0t", $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: useq: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
endmodule
