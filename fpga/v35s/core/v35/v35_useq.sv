`timescale 1ns/1ps
`include "v35_macros.svh"

// V35S core v2 (MX0): the microsequencer (docs/v35s-mechanisms.md sections 3.1, 4; README
// "MX0"). One microinstruction a CPU clock from a registered ROM word: the ROM (three 32-bit
// banks, v35_urom_b?.hex, assembled by validation/v35s/chains/uasm.py) is read at ce_a with the
// next microaddress computed in tick B, so the word a clock executes is a register from its
// first tick on. The microaddress is a register.
//
// The five stalls, each from registered state at tick A (a stalled word performs none of its
// acts and is read again):
//   q     the word pops a byte and there is none: an operand byte and the queue is empty, or
//         E's opcode and the staging register is empty
//   f     F: the requested datum has not arrived (the datapath's opr_rdy: req_done or the
//         datum latched)
//   slot  the word posts a request while the EU's one request is still outstanding
//   hold  E while a memory write is outstanding with RAMEN = 1
//   halt  halted
//   fetch (MX0c) the dispatch while the bus unit runs a fetch (and a ModR/M form's on a
//         back-to-back fetch's issue clock): V35_MX0C_DISPATCH
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
// the operand's bit count or the trap's remaining byte count, and stepped by LOOP.
//
// Depth (by construction, the levelizer's run is the overseer's): tick A: the stall terms
// (a handful of registered bits, the word's fields) and the decode lookups (the opcode register
// and the word register's byte into the generated case tables: ROM-like LUT logic) into the
// ce_b registers; tick B: the next-address mux (eight sources by the word's seq field and the
// registered ex) into the ROM's read address. The ROM output is a register.
//
// Registered state (widths): upc 10, the ROM word 86 (96), retr 10, cnt 9, halted 1, at_entry
// 1; the ce_b copies ex_b 1, d1_b 10, d2_b 10, (MX1) dc_b 1, dr_b 10.
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
    input  v35_udec_t  dec1,            // v35_udec1(the opcode register)
    input  wire [UADDR_W-1:0] dent,     // the DISP word's target (the loader's)
    input  wire        dcall,           // (MX1) ... an EA head, called (the return register <- dret)
    input  wire [UADDR_W-1:0] dret,     // ... the routine's entry (the head's return)
    input  wire        dtrap,           // ... the instruction has no routine
    input  v35_udecm_t dec2,            // v35_udec2(the opcode register, the word register's byte)
    input  wire [2:0]  len,             // the instruction's bytes still to pop (the trap's LEN)
    input  wire [7:0]  il,              // the first immediate byte
    input  wire        fmt_w,           // the running form's width
    // the datapath (tick A: registers; rb_lo: tick B)
    input  wire        opr_rdy,         // F's datum is here
    input  wire        rq_busy,         // the request slot is taken
    input  wire        wr_hold,         // an outstanding write holds E
    input  wire        c_sgn,           // SIGMA's sign
    input  wire        c_dtrap,         // the divide error
    input  wire        c_xc,            // (MX2) the transfer's condition (the datapath's, by the format)
    input  wire        c_snz,           // (MX2) SIGMA is not zero
    input  wire        c_f1,            // (MX3b) F1, the units' sign latch
    input  wire        c_dn,            // (MX3b) the divide's dividend negative
    // (MX0c) the bus unit's registered facts the dispatch reads: a fetch cycle granted on an
    // earlier clock runs on this one (its clocks after the issue through its last), and a
    // back-to-back fetch issues on this clock
    input  wire        fetch_run,
    input  wire        bus_wait,        // (MX1g) a memory cycle is in a wait state (bus.in_wait)
    input  wire        fetch_dph,       // (MX3b) a fetch is past its second clock (bus.fetch_past_b2)
    input  wire        f_abort,         // (MX3b) the bus unit grants an aborted fetch cycle now (bus.g_abort)
    input  wire        b2b_now,
    input  wire        s_modrm,         // the staged opcode has a ModR/M byte (the loader's decode)
    input  wire        s_wbs,           // (MX1f) the staged opcode's routine reads the accumulator first
    input  wire [7:0]  rb_lo,           // port B's low byte (tick B)
    // (MX1c) the take sync's facts (tick A): the E word pops a register-mode ModR/M, the
    // running instruction is a memory form, the queue's request line, a fetch in flight (granted
    // on an earlier clock), a fetch granted now, a fetched word delivered now
    input  wire        e_rmodrm,
    input  wire        rmem,
    input  wire        q_req,
    input  wire        resv,            // the EU's reservation (a request it asks the bus to hold)
    input  wire        f_grant,
    input  wire        f_dlv,
    // the word and its execution
    output v35_uword_t word,            // the current microinstruction (a register)
    output wire        ex,              // the word executes this clock (tick A)
    output wire        ex_pop,          // ... but for the dispatch's fetch stall (the pops' view)
    output reg         ex_b,            // ... registered at ce_b (tick B, ce_a)
    output wire        start,           // a routine's entry word executes (an instruction starts)
    output wire        start_trap,      // ... and it is a trap (no routine)
    output wire [4:0]  why,             // the stall's reason (the trace): 0 none, 1 q, 2 f, 3 slot, 4 hold, 5 halt
                                        //   6 fetch, 7 sync, (MX2) 8 susp, 9 refill
    output wire        q_susp,          // (MX2) prefetching suspended (the queue's susp)
    output reg         halted,
    output wire [UADDR_W-1:0] upc_o
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
    reg [31:0] q0 = 32'd0, q1 = 32'd0, q2 = 32'd0;
    wire [95:0] qw = {q2, q1, q0};
    assign word = v35_uword_t'(qw[UWORD_BITS-1:0]);
    assign upc_o = upc;

    reg [UADDR_W-1:0] retr = '0;
    reg [8:0]  cnt = 9'd0;
    reg        at_entry = 1'b0;     // the current word is a routine's entry, not yet executed
    initial halted = 1'b0;

    // ------------------------------------------------------------ tick A: the stalls
    wire st_q   = q_stall;
    wire st_f   = word.f && !opr_rdy;
    wire st_slt = word.bus != BQ_NONE && rq_busy;
    wire st_hld = word.e && wr_hold;
    // (MX1f) V35_MX1F_WB: the write-back wait (the frozen model's wbsync: the port form of OUT
    // waits for the previous instruction's write-back, wb_until = its done_t + wb). An E word
    // flagged `wb` (a routine whose result's write-back runs on past its last act: the shifts,
    // the multiply and divide, the converts and adjusts) holds the register file's write port
    // through its own clock and the next (the result's write, then the flags'). 1: the E word
    // that pops an opcode whose routine reads the accumulator first (the decode's wbs: OUT
    // imm8,acc) waits for both clocks (`wbn`: the clocks this E word has stood), the model's
    // placement (done_t = the E clock; OUT's three clocks before its port take start at
    // wb_until); 2: the routine's entry word of such an opcode waits instead, the write-back
    // counted as the two clocks after the post-E word (`wbp`), the coordinator's fallback
    // (its placement two clocks after the model's)
    reg  [1:0] wbn = 2'd0, wbp = 2'd0;
    // (MX1g) V35_MX1G_BW: the bus wait. A word that moves into the bus unit's registers (the
    // address register, 1 and 2; the write datum, 1) waits while a memory cycle is in a wait
    // state: the move crosses the internal bus the running cycle holds for its datum until
    // READY (the frozen model's io_count=nowait: an I/O or DW-form request's setup counts no
    // memory wait-state clock)
    wire mv_biu = (word.d1 == MD_ADDR || word.d2 == MD_ADDR)
                  || (`V35_MX1G_BW == 1 && (word.d1 == MD_OPRW || word.d2 == MD_OPRW));
    wire st_bw = `V35_MX1G_BW != 0 && bus_wait && mv_biu;
    // (MX3b) V35_MX3B_UH: the unit hold. A multiply or divide step (MULS, DIVS) waits while a
    // fetch is past its second clock (its datum phase, B3 and the wait states): the step's move
    // crosses the internal bus between the units that the fetch holds for its datum (provisional:
    // MX1g's BW reading with B3 included; the frozen model's _unit_hold, mechanisms Correction 26)
    wire st_uh = `V35_MX3B_UH != 0 && fetch_dph && (word.alu == AL_MULS || word.alu == AL_DIVS);
    // (MX3) `wpn`: the clock of the post-E write has been stood (set on the first clock the E word
    // meets no other stall; cleared when it executes)
    reg        wpn = 1'b0;
    wire st_oth;
    wire st_wp = `V35_MX3_WBR != 0 && word.e && word.wp && !word.wb && s_wbs && !wpn;
    // (MX3) V35_MX3_WBR: the same law for a register form whose result is written by its post-E
    // word (`wp`, the assembler's): that write holds the write port on the clock after E, and the
    // E word that pops a wbs opcode (OUT imm8,acc) stands that one clock (`wbn` 1); the frozen
    // model's wlatch (an I/O port form's start no earlier than the register form's last operand
    // take + 4: MOV / ADD reg,reg before OUT imm8, README "MX3")
    wire st_wbw = (`V35_MX1F_WB == 1 && word.e && word.wb && s_wbs && wbn != 2'd2)
                  || st_wp
                  || (`V35_MX1F_WB == 2 && at_entry && dec1.wbs && (wbp == 2'd2 || wbp == 2'd1));
    // (MX1c) the take sync (V35_MX1C_TSYNC): a word that pops no byte waits, after an operand
    // byte's pop (a register form's ModR/M on its E word, an immediate byte of a register form;
    // not a displacement, a port number or a memory form's byte), until the fetched words in
    // flight or requested on the pop's clock have been delivered (`tw`: the deliveries still
    // owed, two at most: the fetch on the bus and the one the request line asks for). A request
    // that lapses (no fetch in flight, none granted, the line down) ends the wait. The machine
    // explanation (the overseer's hypothesis): the operand byte's path from the queue and the
    // word's write into the queue share the queue's port, the routine's next act waiting for the
    // words the pop's room asked for
    reg  [1:0] tw = 2'd0;
    // (the delivery's own clock frees the word: the last owed word delivered now)
    wire st_tsy = `V35_MX1C_TSYNC && tw != 2'd0 && !(tw == 2'd1 && f_dlv)
                  && word.pop == PP_NONE && word.seq != SQ_DISP
                  && (`V35_MX1E_TSE || !word.e)
                  // (MX2) in a memory form the sync gates the EA's add (the model's ea clocks
                  // start on the delivery), not the book's EA clock before it
                  && (!(`V35_MX2_TSM && rmem) || word.ea != EA_NONE);
    // (MX0c) the dispatch (the word after E: the staged opcode's decode into its routine's
    // entry) waits while the bus unit runs a fetch cycle (V35_MX0C_DISPATCH >= 1), and a form
    // with a ModR/M byte also on the clock a back-to-back fetch issues (2). The dispatch and
    // the fetch exclude each other: one shared step (the decode's read and the queue's write)
    // (3: the same law on the E word, the staged opcode's pop into the opcode register: the
    // frozen model's start is that pop, its staging load (the IR load) stays free)
    wire st_fch = `V35_MX0C_DISPATCH >= 3
                  ? word.e && (fetch_run || (s_modrm && b2b_now))
                  : word.seq == SQ_DISP
                    && ((`V35_MX0C_DISPATCH >= 1 && fetch_run)
                        || (`V35_MX0C_DISPATCH == 2 && dec1.has_modrm && b2b_now));
    // (MX2) SUSP (the V20 ROM's SUSP before its FLUSH): the word suspends prefetching (the
    // queue's request line held low from the clock the word is reached until the FLUSH: `sp`
    // once it has executed) and waits while a fetch cycle runs (granted on an earlier clock,
    // through its last clock: the bus unit's fetch_inflight). The machine reading: the routine
    // reads the instruction pointer and replaces the stream; the bus unit's prefetch is stopped
    // and the cycle it runs completes first (the V20's PC is the prefetch pointer less the
    // queue's count; a doomed fetch is not started)
    reg        sp = 1'b0;
    wire st_sus = (word.susp && fetch_run)
                  // (MX2) the decide's wait (`fw`): while a fetch cycle runs or its word is
                  // delivered (the queue's port the fetch's: the take sync's reading), the frozen
                  // model's untaken=wait (a short transfer not taken waits for no fetch in flight
                  // and a clock after its last); no suspension
                  || (word.fw && (fetch_run || f_dlv));
    // (MX3b) V35_MX3B_US: the unit's suspension of a dropped request. A fetch request the bus unit
    // dropped with an aborted cycle (`drop`, from that grant to the next fetch's) is not raised
    // again while the multiply / divide unit runs: prefetching suspended (the queue's susp) from
    // the clock the word that loads the unit (MULI, DIVI, CVBI, CVDI) is reached to the clock the
    // word that takes its result (MULF, DIVF, CVBF, CVDF) or an E is. Provisional: the frozen
    // model's abort_unit=loop (the request an aborted cycle dropped at a multiply's start raised
    // mtail before its end); F3-push-mulu_dw-k2-pE-w0: the fetch +119 against silicon's +147. A
    // request not dropped still goes (F16-l-out-mulu_aw-pE-w0: the fetch at the load's clock +87)
    reg        un = 1'b0;
    wire       u_init = word.alu == AL_MULI || word.alu == AL_DIVI || word.alu == AL_CVBI
                        || word.alu == AL_CVDI;
    wire       u_fin = word.alu == AL_MULF || word.alu == AL_DIVF || word.alu == AL_CVBF
                       || word.alu == AL_CVDF || word.e;
    wire       un_n = (ex && u_fin) ? 1'b0 : (ex && u_init) ? 1'b1 : un;
    reg        drop = 1'b0;
    wire       drop_n = f_abort ? 1'b1 : f_grant ? 1'b0 : drop;
    wire       u_sus = `V35_MX3B_US != 0 && drop && ((un && !u_fin) || u_init);
    assign q_susp = (sp && !word.flush) || word.susp      // (the FLUSH word issues the target's fetch)
                    || u_sus;
    // (MX2) the refill: after a FLUSH, the E word that pops the target's opcode waits while the
    // refill's fetch run lasts (`rf` from the FLUSH to that E): a fetch granted on an earlier
    // clock in flight, or the request line up at the end of the last clock (`rqp`, a register:
    // the run's next fetch is granted on this clock). The machine reading (README "MX2"): the
    // queue's port is the refill's writes' while the run lasts, as the take sync's
    reg        rf = 1'b0, rqp = 1'b0;
    wire st_rfl = word.e && rf && (fetch_run || rqp);
    // the stalls a popping word can meet (the loader's pops read this: a DISP word never pops;
    // with the stall on the E word (3) it is the E word's too)
    assign st_oth = !halted && !st_q && !st_f && !st_slt && !st_hld && !st_tsy && !st_bw
                    && !st_uh && !st_sus && !st_rfl && !st_fch;
    wire wpn_n = (word.e && word.wp && !ex) ? (wpn || st_oth) : 1'b0;
    wire base = !halted && !st_q && !st_f && !st_slt && !st_hld && !st_tsy && !st_wbw && !st_bw
                && !st_uh && !st_sus && !st_rfl;
    assign ex_pop = base && !(`V35_MX0C_DISPATCH >= 3 && st_fch);
    assign ex = base && !st_fch;
    assign why = halted ? 5'd5 : st_q ? 5'd1 : st_f ? 5'd2 : st_slt ? 5'd3 : (st_hld || st_wbw) ? 5'd4 : st_bw ? 5'd3
               : st_uh ? 5'd10 : st_sus ? 5'd8 : st_rfl ? 5'd9 : st_fch ? 5'd6 : st_tsy ? 5'd7 : 5'd0;
    // the arming pop (tick A) and the deliveries owed from it
    wire arm = ex_pop && ((word.e && e_rmodrm)
                          || (!word.e && !rmem && (word.pop == PP_IL || word.pop == PP_IH)));
    // (a request the EU's own reservation holds back is not counted: the model's take sync
    // counts no request a posted request holds, and a form that posts after its take does not
    // sync: the routine's request goes first)
    wire       ask = (q_req && !resv) || f_grant;
    wire [1:0] owe = {1'b0, fetch_run} + {1'b0, ask} - {1'b0, f_dlv && fetch_run};
    wire [1:0] wbn_n = (word.e && word.wb && !ex) ? (wbn == 2'd2 ? 2'd2 : wbn + 2'd1) : 2'd0;
    // (MX2) the suspension stands from the SUSP word's execution to the FLUSH (or an E); the
    // refill from the FLUSH to the E
    wire       sp_n = (ex && (word.flush || word.e)) ? 1'b0 : (ex && word.susp) ? 1'b1 : sp;
    wire       rf_n = (ex && word.e) ? 1'b0 : (ex && word.flush) ? 1'b1 : rf;
    wire [1:0] wbp_n = (ex && word.e && word.wb) ? 2'd3 : (wbp != 2'd0 ? wbp - 2'd1 : 2'd0);
    wire [1:0] tw_n = (ex && word.flush) ? 2'd0      // (MX2) the flush: the words asked are dropped
                    : arm ? owe
                    : (tw != 2'd0 && f_dlv) ? tw - 2'd1
                    : (tw != 2'd0 && !fetch_run && !ask) ? 2'd0 : tw;
    assign start = at_entry && ex_pop;     // (an entry word is never the dispatch word; with
                                           //  3 an entry word that is an E word: ex_pop is ex)
    // the instruction is a trap: its opcode has no routine, or (the ModR/M / 0F head) its
    // second-level cell has none
    assign start_trap = dtrap || (word.seq == SQ_DISPM && dec2.trap);

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg [UADDR_W-1:0] d1_b = '0, d2_b = '0, dr_b = '0;
    reg        dc_b = 1'b0;
    reg  [1:0] tw_b = 2'd0;
    reg  [1:0] wbn_b = 2'd0, wbp_b = 2'd0;
    reg        wpn_b = 1'b0;
    reg        sp_b = 1'b0, rf_b = 1'b0, rq_b = 1'b0, un_b = 1'b0, drop_b = 1'b0;
    reg [2:0]  len_b = 3'd0;
    reg [7:0]  il_b = 8'd0;
    reg        w_b = 1'b0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            ex_b <= ex;
            d1_b <= dent;
            dc_b <= dcall;
            tw_b <= tw_n;
            wbn_b <= wbn_n;
            wpn_b <= wpn_n;
            wbp_b <= wbp_n;
            sp_b <= sp_n;
            un_b <= un_n;
            drop_b <= drop_n;
            rf_b <= rf_n;
            rq_b <= q_req;
            dr_b <= dret;
            d2_b <= dec2.entry;
            len_b <= len;
            il_b <= il;
            w_b <= fmt_w;
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
                SQ_DISP: upc_n = d1_b;
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
                default: cnt_n = word.seq == SQ_LOOP ? cnt - 9'd1 : cnt;
            endcase
        end
    end

    // ------------------------------------------------------------ the end of the clock (ce_a)
    wire [UADDR_W-1:0] raddr = !reset_n ? UROM_RESET : upc_n;
    always_ff @(posedge clock) begin
        if (!reset_n || ce_a) begin
            q0 <= rom0[raddr];
            q1 <= rom1[raddr];
            q2 <= rom2[raddr];
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            upc <= UROM_RESET;
            retr <= '0;
            cnt <= 9'd0;
            tw <= 2'd0;
            wbn <= 2'd0;
            wbp <= 2'd0;
            wpn <= 1'b0;
            sp <= 1'b0;
            un <= 1'b0;
            drop <= 1'b0;
            rf <= 1'b0;
            rqp <= 1'b0;
            halted <= 1'b0;
            at_entry <= 1'b0;
        end else if (ce_a) begin
            upc <= upc_n;
            cnt <= cnt_n;
            tw <= tw_b;
            wbn <= wbn_b;
            wpn <= wpn_b;
            wbp <= wbp_b;
            sp <= sp_b;
            un <= un_b;
            drop <= drop_b;
            rf <= rf_b;
            rqp <= rq_b;
            if (ex_b && word.seq == SQ_CALL)
                retr <= inc;
            else if (ex_b && word.seq == SQ_DISP && dc_b)
                retr <= dr_b;      // (MX1) the dispatch's call of an EA head
            if (ex_b && word.halt)
                halted <= 1'b1;
            if (ex_b)
                at_entry <= word.seq == SQ_DISP;
        end
    end

    wire unused = &{1'b0, dec1, dec2, qw[95:UWORD_BITS]};

`ifndef SYNTHESIS
    // (S7b) chk: the ce_b registers against their sources at ce_a
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (ex_b !== ex || d1_b !== dent || d2_b !== dec2.entry || len_b !== len
                || dc_b !== dcall || dr_b !== dret || tw_b !== tw_n || wbn_b !== wbn_n || wpn_b !== wpn_n || wbp_b !== wbp_n
                || sp_b !== sp_n || un_b !== un_n || drop_b !== drop_n || rf_b !== rf_n || rq_b !== q_req
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
