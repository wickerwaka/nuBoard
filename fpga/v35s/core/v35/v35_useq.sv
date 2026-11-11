`timescale 1ns/1ps
`include "v35_macros.svh"

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
    input  wire        ec_reg,          // (MX3c) the EAC word's popped byte: register mode
    input  wire        ec_call,         // ... a memory mode with an EA head (called)
    input  wire [UADDR_W-1:0] ec_head,  // ... the head
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
    // (MX5c) tick B: the next values of the stall's inputs (the D nets of their ce_a registers,
    // as they stand after the coming ce_a): the loader's, the datapath's, the bus unit's
    input  wire        q_stall_nx,
    input  wire        opr_rdy_nx,
    input  wire        rq_busy_nx,
    input  wire        wr_hold_nx,
    input  wire        s_wbs_nx,
    input  wire        s_modrm_nx,
    input  wire        d1_wbs_nx,
    input  wire        d1_hm_nx,
    input  wire        rmem_nx,
    input  wire        fetch_run_nx,
    input  wire        bus_wait_nx,
    input  wire        fetch_dph_nx,
    input  wire        b2b_now_nx,
    input  wire        f_dlv_nx,
    // the word and its execution
    output v35_uword_t word,            // the current microinstruction (a register)
    output v35_uword_t word_nx,         // (MX5b) tick B: the next word (the banks' read data)
    output wire        w_disp,          // (MX5) the word's derived bits (registers): seq == SQ_DISP
    output wire        w_dispm,         // ... seq == SQ_DISPM
    output wire        w_popany,        // ... pop != PP_NONE
    output wire        w_dispm_nx,      // (MX5c) tick B: the next word's seq == SQ_DISPM
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
    // (MX5) the ROM is read a tick earlier: the banks at ce_b (`r0`..`r2`, the RAM's read data)
    // with the next address decided in tick A (`upc_a`), the word a plain register (`q0`..`q2`)
    // loaded from the read data at ce_a. The word a clock executes is the one the old ce_a read
    // gave: the address is the same function of the same values (README "MX5")
    reg [31:0] r0 = 32'd0, r1 = 32'd0, r2 = 32'd0;
    reg [31:0] q0 = 32'd0, q1 = 32'd0, q2 = 32'd0;
    wire [95:0] qw = {q2, q1, q0};
    assign word = v35_uword_t'(qw[UWORD_BITS-1:0]);
    // (MX5) the word's derived bits (the field compares the stall terms, the pops and the take
    // sync read), decoded from the next word's read data in tick B and registered with the word
    // at ce_a: `pd` is always the function `pre(word)` of the word it sits beside
    typedef struct packed {
        logic post;         // bus != BQ_NONE
        logic mvbiu;        // a move into the bus unit's address register (or OPRW, BW 1)
        logic unit;         // a multiply or divide step (MULS, DIVS)
        logic uinit;        // the unit's load (MULI DIVI CVBI CVDI)
        logic ufin;         // the unit's result taken (MULF DIVF CVBF CVDF) or E
        logic tsy;          // the take sync's word facts but the memory form's: no pop, not DISP, (TSE or not E)
        logic ea;           // ea != EA_NONE
        logic disp;         // seq == SQ_DISP
        logic dispm;        // seq == SQ_DISPM
        logic popany;       // pop != PP_NONE
        logic pmodrm;       // pop == PP_MODRM
        logic pilih;        // pop == PP_IL or PP_IH
    } v35_upre_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_upre_t pre(input v35_uword_t w);
        pre.post = w.bus != BQ_NONE;
        pre.mvbiu = (w.d1 == MD_ADDR || w.d2 == MD_ADDR)
                    || (`V35_MX1G_BW == 1 && (w.d1 == MD_OPRW || w.d2 == MD_OPRW));
        pre.unit = w.alu == AL_MULS || w.alu == AL_DIVS;
        pre.uinit = w.alu == AL_MULI || w.alu == AL_DIVI || w.alu == AL_CVBI || w.alu == AL_CVDI;
        pre.ufin = w.alu == AL_MULF || w.alu == AL_DIVF || w.alu == AL_CVBF || w.alu == AL_CVDF
                   || w.e;
        pre.tsy = w.pop == PP_NONE && w.seq != SQ_DISP && (`V35_MX1E_TSE || !w.e);
        pre.ea = w.ea != EA_NONE;
        pre.disp = w.seq == SQ_DISP;
        pre.dispm = w.seq == SQ_DISPM;
        pre.popany = w.pop != PP_NONE;
        pre.pmodrm = w.pop == PP_MODRM;
        pre.pilih = w.pop == PP_IL || w.pop == PP_IH;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    wire [95:0] rw = {r2, r1, r0};
    assign word_nx = v35_uword_t'(rw[UWORD_BITS-1:0]);
    v35_upre_t pd = '0;
    assign w_disp = pd.disp;
    assign w_dispm = pd.dispm;
    assign w_popany = pd.popany;
    assign upc_o = upc;

    reg [UADDR_W-1:0] retr = '0;
    reg [8:0]  cnt = 9'd0;
    reg        at_entry = 1'b0;     // the current word is a routine's entry, not yet executed
    initial halted = 1'b0;

    // ------------------------------------------------------------ tick A: the stalls
    // (MX5c) The stall outcome is a register. Every stall term reads ce_a registers only (the
    // word, its derived bits, the sequencer's counters, the loader's staging slot and byte
    // counts, the datapath's request registers and RAMEN, the bus unit's cycle registers), never
    // tick A's logic. `stall_f(i)` is the five stalls below on the facts `i`; the outcome
    // (ex, ex_pop, st_oth, why) is `st_r`, a ce_a register loaded with stall_f of the facts' next
    // values (`si_nx`: tick B's word_nx and its derived bits, the ce_b registers the counters
    // load from, the other modules' *_nx outputs: the D nets of their registers), in reset with
    // stall_f of the facts as they stand. So st_r is stall_f(si_now) on every clock
    // (`+v35_chk`), and tick A starts from a registered stall outcome. README "MX5" round 3
    typedef struct packed {
        logic       halted, f, e, wp, wb, susp, fw;
        logic       post, mvbiu, unit, tsy, ea, disp, at_entry;
        logic [1:0] wbn, wbp, tw;
        logic       wpn, rf, rqp;
        logic       q_stall, opr_rdy, rq_busy, wr_hold, s_wbs, s_modrm, d1_wbs, d1_hm, rmem;
        logic       fetch_run, bus_wait, fetch_dph, b2b_now, f_dlv;
    } v35_sin_t;
    typedef struct packed {
        logic       ex, exp, oth;
        logic [4:0] why;
    } v35_stl_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_stl_t stall_f(input v35_sin_t f);
        logic st_q, st_f, st_slt, st_hld, st_bw, st_uh, st_wp, st_wbw, st_tsy, st_fch, st_sus;
        logic st_rfl, base;
        st_q   = f.q_stall;
        st_f   = f.f && !f.opr_rdy;
        st_slt = f.post && f.rq_busy;
        st_hld = f.e && f.wr_hold;
        // (MX1g) V35_MX1G_BW: the bus wait. A word that moves into the bus unit's registers (the
        // address register, 1 and 2; the write datum, 1) waits while a memory cycle is in a wait
        // state: the move crosses the internal bus the running cycle holds for its datum until
        // READY (the frozen model's io_count=nowait: an I/O or DW-form request's setup counts no
        // memory wait-state clock)
        st_bw = `V35_MX1G_BW != 0 && f.bus_wait && f.mvbiu;
        // (MX3b) V35_MX3B_UH: the unit hold. A multiply or divide step (MULS, DIVS) waits while a
        // fetch is past its second clock (its datum phase, B3 and the wait states): the step's
        // move crosses the internal bus between the units that the fetch holds for its datum
        // (provisional: MX1g's BW reading with B3 included; the frozen model's _unit_hold,
        // mechanisms Correction 26)
        st_uh = `V35_MX3B_UH != 0 && f.fetch_dph && f.unit;
        // (MX3) V35_MX3_WBR: the same law for a register form whose result is written by its
        // post-E word (`wp`, the assembler's): that write holds the write port on the clock
        // after E, and the E word that pops a wbs opcode (OUT imm8,acc) stands that one clock
        // (`wpn`: the clock of the post-E write has been stood); the frozen model's wlatch (an
        // I/O port form's start no earlier than the register form's last operand take + 4: MOV /
        // ADD reg,reg before OUT imm8, README "MX3")
        st_wp = `V35_MX3_WBR != 0 && f.e && f.wp && !f.wb && f.s_wbs && !f.wpn;
        // (MX1f) V35_MX1F_WB: the write-back wait (the frozen model's wbsync: the port form of
        // OUT waits for the previous instruction's write-back, wb_until = its done_t + wb). An E
        // word flagged `wb` (a routine whose result's write-back runs on past its last act: the
        // shifts, the multiply and divide, the converts and adjusts) holds the register file's
        // write port through its own clock and the next (the result's write, then the flags').
        // 1: the E word that pops an opcode whose routine reads the accumulator first (the
        // decode's wbs: OUT imm8,acc) waits for both clocks (`wbn`: the clocks this E word has
        // stood), the model's placement (done_t = the E clock; OUT's three clocks before its
        // port take start at wb_until); 2: the routine's entry word of such an opcode waits
        // instead, the write-back counted as the two clocks after the post-E word (`wbp`), the
        // coordinator's fallback (its placement two clocks after the model's)
        st_wbw = (`V35_MX1F_WB == 1 && f.e && f.wb && f.s_wbs && f.wbn != 2'd2)
                 || st_wp
                 || (`V35_MX1F_WB == 2 && f.at_entry && f.d1_wbs && (f.wbp == 2'd2 || f.wbp == 2'd1));
        // (MX1c) the take sync (V35_MX1C_TSYNC): a word that pops no byte waits, after an
        // operand byte's pop (a register form's ModR/M on its E word, an immediate byte of a
        // register form; not a displacement, a port number or a memory form's byte), until the
        // fetched words in flight or requested on the pop's clock have been delivered (`tw`: the
        // deliveries still owed, two at most: the fetch on the bus and the one the request line
        // asks for). A request that lapses (no fetch in flight, none granted, the line down) ends
        // the wait. The machine explanation (the overseer's hypothesis): the operand byte's path
        // from the queue and the word's write into the queue share the queue's port, the
        // routine's next act waiting for the words the pop's room asked for. (The delivery's own
        // clock frees the word: the last owed word delivered now.) (MX2) In a memory form the
        // sync gates the EA's add (the model's ea clocks start on the delivery), not the book's
        // EA clock before it
        st_tsy = `V35_MX1C_TSYNC && f.tw != 2'd0 && !(f.tw == 2'd1 && f.f_dlv)
                 && f.tsy && (!(`V35_MX2_TSM && f.rmem) || f.ea);
        // (MX0c) the dispatch (the word after E: the staged opcode's decode into its routine's
        // entry) waits while the bus unit runs a fetch cycle (V35_MX0C_DISPATCH >= 1), and a
        // form with a ModR/M byte also on the clock a back-to-back fetch issues (2). The
        // dispatch and the fetch exclude each other: one shared step (the decode's read and the
        // queue's write) (3: the same law on the E word, the staged opcode's pop into the opcode
        // register: the frozen model's start is that pop, its staging load (the IR load) stays
        // free)
        st_fch = `V35_MX0C_DISPATCH >= 3
                 ? f.e && (f.fetch_run || (f.s_modrm && f.b2b_now))
                 : f.disp
                   && ((`V35_MX0C_DISPATCH >= 1 && f.fetch_run)
                       || (`V35_MX0C_DISPATCH == 2 && f.d1_hm && f.b2b_now));
        // (MX2) SUSP: the word waits while a fetch cycle runs (granted on an earlier clock,
        // through its last clock: the bus unit's fetch_inflight); the decide's wait (`fw`): while
        // a fetch cycle runs or its word is delivered (the queue's port the fetch's: the take
        // sync's reading), the frozen model's untaken=wait
        st_sus = (f.susp && f.fetch_run) || (f.fw && (f.fetch_run || f.f_dlv));
        // (MX2) the refill: after a FLUSH, the E word that pops the target's opcode waits while
        // the refill's fetch run lasts (`rf` from the FLUSH to that E): a fetch granted on an
        // earlier clock in flight, or the request line up at the end of the last clock (`rqp`)
        st_rfl = f.e && f.rf && (f.fetch_run || f.rqp);
        // the stalls a popping word can meet (the loader's pops read this: a DISP word never
        // pops; with the stall on the E word (3) it is the E word's too)
        stall_f.oth = !f.halted && !st_q && !st_f && !st_slt && !st_hld && !st_tsy && !st_bw
                      && !st_uh && !st_sus && !st_rfl && !st_fch;
        base = !f.halted && !st_q && !st_f && !st_slt && !st_hld && !st_tsy && !st_wbw && !st_bw
               && !st_uh && !st_sus && !st_rfl;
        stall_f.exp = base && !(`V35_MX0C_DISPATCH >= 3 && st_fch);
        stall_f.ex = base && !st_fch;
        stall_f.why = f.halted ? 5'd5 : st_q ? 5'd1 : st_f ? 5'd2 : st_slt ? 5'd3
                    : (st_hld || st_wbw) ? 5'd4 : st_bw ? 5'd3
                    : st_uh ? 5'd10 : st_sus ? 5'd8 : st_rfl ? 5'd9 : st_fch ? 5'd6
                    : st_tsy ? 5'd7 : 5'd0;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    reg  [1:0] wbn = 2'd0, wbp = 2'd0;
    reg        wpn = 1'b0;
    reg  [1:0] tw = 2'd0;
    reg        sp = 1'b0;
    reg        rf = 1'b0, rqp = 1'b0;
    v35_sin_t  si_now;
    always_comb begin
        si_now.halted = halted;
        si_now.f = word.f;
        si_now.e = word.e;
        si_now.wp = word.wp;
        si_now.wb = word.wb;
        si_now.susp = word.susp;
        si_now.fw = word.fw;
        si_now.post = pd.post;
        si_now.mvbiu = pd.mvbiu;
        si_now.unit = pd.unit;
        si_now.tsy = pd.tsy;
        si_now.ea = pd.ea;
        si_now.disp = pd.disp;
        si_now.at_entry = at_entry;
        si_now.wbn = wbn;
        si_now.wbp = wbp;
        si_now.tw = tw;
        si_now.wpn = wpn;
        si_now.rf = rf;
        si_now.rqp = rqp;
        si_now.q_stall = q_stall;
        si_now.opr_rdy = opr_rdy;
        si_now.rq_busy = rq_busy;
        si_now.wr_hold = wr_hold;
        si_now.s_wbs = s_wbs;
        si_now.s_modrm = s_modrm;
        si_now.d1_wbs = dec1.wbs;
        si_now.d1_hm = dec1.has_modrm;
        si_now.rmem = rmem;
        si_now.fetch_run = fetch_run;
        si_now.bus_wait = bus_wait;
        si_now.fetch_dph = fetch_dph;
        si_now.b2b_now = b2b_now;
        si_now.f_dlv = f_dlv;
    end
    v35_stl_t  st_r = '0;
    wire       st_oth = st_r.oth;
    assign ex_pop = st_r.exp;
    assign ex = st_r.ex;
    assign why = st_r.why;
    // (MX3b) V35_MX3B_US: the unit's suspension of a dropped request. A fetch request the bus
    // unit dropped with an aborted cycle (`drop`, from that grant to the next fetch's) is not
    // raised again while the multiply / divide unit runs: prefetching suspended (the queue's
    // susp) from the clock the word that loads the unit (MULI, DIVI, CVBI, CVDI) is reached to
    // the clock the word that takes its result (MULF, DIVF, CVBF, CVDF) or an E is. Provisional:
    // the frozen model's abort_unit=loop (the request an aborted cycle dropped at a multiply's
    // start raised mtail before its end); F3-push-mulu_dw-k2-pE-w0: the fetch +119 against
    // silicon's +147. A request not dropped still goes (F16-l-out-mulu_aw-pE-w0: the fetch at
    // the load's clock +87)
    reg        un = 1'b0;
    wire       u_init = pd.uinit;
    wire       u_fin = pd.ufin;
    wire       un_n = (ex && u_fin) ? 1'b0 : (ex && u_init) ? 1'b1 : un;
    reg        drop = 1'b0;
    wire       drop_n = f_abort ? 1'b1 : f_grant ? 1'b0 : drop;
    wire       u_sus = `V35_MX3B_US != 0 && drop && ((un && !u_fin) || u_init);
    // (MX2) SUSP suspends prefetching (the queue's request line held low from the clock the word
    // is reached until the FLUSH: `sp` once it has executed)
    assign q_susp = (sp && !word.flush) || word.susp      // (the FLUSH word issues the target's fetch)
                    || u_sus;
    wire wpn_n = (word.e && word.wp && !ex) ? (wpn || st_oth) : 1'b0;
    // the arming pop (tick A) and the deliveries owed from it
    // (MX3c) a 0F form's ModR/M byte, popped by its routine's EAC word, arms it as the E word's
    // ModR/M pop does (the frozen model's take sync after the page's operand take)
    wire arm = ex_pop && ((word.e && e_rmodrm)
                          || (!word.e && !rmem && pd.pilih)
                          || (!word.e && pd.pmodrm));
    // (a request the EU's own reservation holds back is not counted: the model's take sync
    // counts no request a posted request holds, and a form that posts after its take does not
    // sync: the routine's request goes first)
    wire       ask = (q_req && !resv) || f_grant;
    wire [1:0] wbn_n = (word.e && word.wb && !ex) ? (wbn == 2'd2 ? 2'd2 : wbn + 2'd1) : 2'd0;
    // (MX2) the suspension stands from the SUSP word's execution to the FLUSH (or an E); the
    // refill from the FLUSH to the E
    wire       sp_n = (ex && (word.flush || word.e)) ? 1'b0 : (ex && word.susp) ? 1'b1 : sp;
    wire       rf_n = (ex && word.e) ? 1'b0 : (ex && word.flush) ? 1'b1 : rf;
    wire [1:0] wbp_n = (ex && word.e && word.wb) ? 2'd3 : (wbp != 2'd0 ? wbp - 2'd1 : 2'd0);
    // (MX5) the same choice with the request facts (`ask`: the queue's line and the grant, the
    // last to arrive) selecting last: tw_f(a) is the choice with ask = a
    function automatic logic [1:0] tw_f(input logic a);
        logic [1:0] ow;
        ow = {1'b0, fetch_run} + {1'b0, a} - {1'b0, f_dlv && fetch_run};
        tw_f = (ex && word.flush) ? 2'd0      // (MX2) the flush: the words asked are dropped
             : arm ? ow
             : (tw != 2'd0 && f_dlv) ? tw - 2'd1
             : (tw != 2'd0 && !fetch_run && !a) ? 2'd0 : tw;
    endfunction
    wire [1:0] tw_n = ask ? tw_f(1'b1) : tw_f(1'b0);
    assign start = at_entry && ex_pop;     // (an entry word is never the dispatch word; with
                                           //  3 an entry word that is an E word: ex_pop is ex)
    // the instruction is a trap: its opcode has no routine, or (the ModR/M / 0F head) its
    // second-level cell has none
    assign start_trap = dtrap || (word.seq == SQ_DISPM && dec2.trap);

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg [UADDR_W-1:0] d1_b = '0, d2_b = '0, dr_b = '0;
    reg        dc_b = 1'b0;
    reg        ecr_b = 1'b0, ecc_b = 1'b0;      // (MX3c) the EAC word's mode facts
    reg [UADDR_W-1:0] ech_b = '0;
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
            ecr_b <= ec_reg;
            ecc_b <= ec_call;
            ech_b <= ec_head;
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

    // (MX5c) the stall's facts as they stand after the coming ce_a (tick B: the next word and
    // its derived bits, the ce_b registers the counters load, the other modules' next values)
    // and the registered outcome
    v35_upre_t pd_nx;
    assign pd_nx = pre(word_nx);
    assign w_dispm_nx = pd_nx.dispm;
    v35_sin_t  si_nx;
    always_comb begin
        si_nx.halted = halted || (ex_b && word.halt);
        si_nx.f = word_nx.f;
        si_nx.e = word_nx.e;
        si_nx.wp = word_nx.wp;
        si_nx.wb = word_nx.wb;
        si_nx.susp = word_nx.susp;
        si_nx.fw = word_nx.fw;
        si_nx.post = pd_nx.post;
        si_nx.mvbiu = pd_nx.mvbiu;
        si_nx.unit = pd_nx.unit;
        si_nx.tsy = pd_nx.tsy;
        si_nx.ea = pd_nx.ea;
        si_nx.disp = pd_nx.disp;
        si_nx.at_entry = ex_b ? word.seq == SQ_DISP : at_entry;
        si_nx.wbn = wbn_b;
        si_nx.wbp = wbp_b;
        si_nx.tw = tw_b;
        si_nx.wpn = wpn_b;
        si_nx.rf = rf_b;
        si_nx.rqp = rq_b;
        si_nx.q_stall = q_stall_nx;
        si_nx.opr_rdy = opr_rdy_nx;
        si_nx.rq_busy = rq_busy_nx;
        si_nx.wr_hold = wr_hold_nx;
        si_nx.s_wbs = s_wbs_nx;
        si_nx.s_modrm = s_modrm_nx;
        si_nx.d1_wbs = d1_wbs_nx;
        si_nx.d1_hm = d1_hm_nx;
        si_nx.rmem = rmem_nx;
        si_nx.fetch_run = fetch_run_nx;
        si_nx.bus_wait = bus_wait_nx;
        si_nx.fetch_dph = fetch_dph_nx;
        si_nx.b2b_now = b2b_now_nx;
        si_nx.f_dlv = f_dlv_nx;
    end
    always_ff @(posedge clock) begin
        if (!reset_n)
            st_r <= stall_f(si_now);
        else if (ce_a)
            st_r <= stall_f(si_nx);
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
            SQ_DISP: nx_a = dent;
            SQ_EAC: nx_a = ec_reg ? word.tgt : ec_call ? ec_head : inc;
            default: nx_a = inc;
        endcase
    end
    wire [UADDR_W-1:0] upc_a = ex ? nx_a : upc;

    // ------------------------------------------------------------ the end of the clock (ce_a)
    // (MX5) the banks read at ce_b (in reset: the reset word, every clock); the word register
    // loads their data at ce_a, the derived bits with it
    wire [UADDR_W-1:0] raddr = !reset_n ? UROM_RESET : upc_a;
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
            if (ex_b && (word.seq == SQ_CALL || (word.seq == SQ_EAC && !ecr_b && ecc_b)))
                retr <= inc;
            else if (ex_b && word.seq == SQ_DISP && dc_b)
                retr <= dr_b;      // (MX1) the dispatch's call of an EA head
            if (ex_b && word.halt)
                halted <= 1'b1;
            if (ex_b)
                at_entry <= word.seq == SQ_DISP;
        end
    end

    wire unused = &{1'b0, dec1, dec2, qw[95:UWORD_BITS], rw[95:UWORD_BITS]};

`ifndef SYNTHESIS
    // (S7b) chk: the ce_b registers against their sources at ce_a
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    // (MX5) the address read at ce_b against tick B's, and the derived bits against the word
    reg [UADDR_W-1:0] upc_ab = '0;
    always @(posedge clock) if (ce_b) upc_ab <= upc_a;
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
            if (upc_ab !== upc_n || pd !== pre(word)) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: the ROM's address or the derived bits differ at %0t", $time);
            end
            if (ex_b !== ex || d1_b !== dent || d2_b !== dec2.entry || len_b !== len
                || dc_b !== dcall || dr_b !== dret || ecr_b !== ec_reg || ecc_b !== ec_call
                || ech_b !== ec_head || tw_b !== tw_n || wbn_b !== wbn_n || wpn_b !== wpn_n || wbp_b !== wbp_n
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
