`timescale 1ns/1ps

// (MX0b, MX1d) The byte path: every pop takes the queue's window directly (its stored bytes,
// the latch, this clock's delivery bypassed); the queue's `pop_n` is the pops. README "MX0b"
// and "MX1d" have the word-register laws measured and not built.
//
// V35S core v2 (MX0): the loader, shrunk to the opcode's staging register, the pop port and the
// decode (docs/v35s-mechanisms.md sections 3.1, 3.2, 4; README "MX0").
//
// The pop port. A microinstruction that pops an operand byte (the ModR/M byte, an immediate, a
// displacement, a port number: one a word) takes the queue's head byte into its register at
// the word's end; with no byte in the queue the word stalls (the sequencer's stall q). The E
// word pops the next opcode from the staging register `s` (the queue's seventh slot, variant
// B's staging byte) into the opcode register; with the staging register empty it stalls.
//
// The staging register is loaded from the queue's head when it is empty and the running
// instruction has no byte left to pop (`need` = 0): the byte after the instruction's last is
// the next opcode. `need` is the instruction's bytes still to pop, from its format: loaded at
// the E pop from the popped opcode's decode (v35_udec1 of the staging register: its ModR/M
// byte and its immediate or displacement bytes), extended at the ModR/M byte's pop by its
// displacement and the group's immediate (v35_umodrm) and at the 0F page's second byte's pop
// (v35_upage), counted down by each pop. ((step D) The queue's room no longer counts the
// staging slot or a byte popped and not released: the loader's room outputs `rel` / `stg` and
// the release a clock late (`hold`, `hold2`) are gone.)
//
// (MX1) The dispatch's target for a ModR/M memory cell (the decode's ea bit) is the EA head of
// the registered ModR/M byte's mode, called with the routine's entry as the return (dcall,
// dret): mod 01 one displacement pop, mod 10 and the direct form two, the book's heads (eab)
// with the book's EA clock as an OPEN word, mod 00 too (ea.uasm). The choice reads the mode's
// bits and the cell's two decode bits only.
//
// The decode's inputs are registers and the popped byte: v35_udec1 of the opcode register
// (registered into `fmt` at the dispatch, DISP), v35_udec2 of the opcode register and the byte
// a DISPM word pops (the group's reg field: `op3`). No byte is read that the routine does not
// pop.
//
// Two ticks: tick A decides the pops and the load (`pop_n` on the queue's port)
// from registers and the sequencer's tick-A word; the ce_a update reads tick A's decisions and
// the queue's head bytes through the ce_b registers. (MX5c) The outcomes on the queue's port
// and the bus unit's strobes are registers selected by the registered stall outcome and the
// head byte's z1; the head byte enters through its tag (stored by the queue beside the byte)
// or, for the delivered word, through its decode in tick A (README "MX5" round 3).
//
// Registered state (widths): s_v 1, s_b 8, need 3, op 8, opc 8 (the running instruction's
// opcode: the word after E still runs the last one's acts while `op` holds the next), modrm 8,
// il ih dl dh 4x8, fmt (v35_udec_t), op3 3; mp 8 (the ModR/M byte the E word popped: `modrm`,
// the running instruction's, loads from it at the dispatch, as fmt and opc do); s_ip 16 (the
// staged opcode's offset; (step D) the next queue byte's is the queue's `hip`); the ce_b
// copies. (The linear addresses of the next queue byte, the staged opcode and the popped
// opcode, the trace's and the function bench's, are v35_top's observation block's.)
module v35_loader
    import v35_front_pkg::*;
    import v35_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    // the queue's port (Q1, unchanged)
    input  wire [7:0]  qv0,
    input  wire [7:0]  qv1,
    input  wire [2:0]  q_avail,
    input  wire [2:0]  q_stored,        // (MX0b) the queue's stored bytes (the load's source)
    // (MX5b) the queue's own registered facts for the head byte's decode: its first stored byte,
    // the latched byte and the latch's bit, the in-flight word's parity; with the delivered word
    // (the bus unit's datum register) they are the head byte's candidates, q_stored and the
    // latch's bit its select
    input  wire [7:0]  h_q0,
    input  wire        h_odd,
    input  wire [15:0] h_dlv,
    input  wire [15:0] h_dlv_nx,        // (F5t) tick B: h_dlv's next value and its load (the bus
    input  wire        h_dlv_ld,        //   unit's datum register's D and enable)
    // (MX5c) the byte tags (`bt_f`, below): the queue's stored ones of its first stored byte and
    // its latched byte; the delivered word's, formed here on the delivery clock and stored by the
    // queue beside the bytes (high byte's, low byte's)
    input  wire [QTAG_W-1:0] h_q0t,
    output wire [2*QTAG_W-1:0] dlv_tag,
    output wire [1:0]  pop_n,           // (step C) the pop: the bytes leaving the queue's head
                                        //   (tick A): an operand pop, the staging load (0 to 2)
    input  wire [15:0] q_ip,            // (step D) the queue's head byte's offset in PS (hip)
    input  wire        flush_w,         // (MX5) the word's FLUSH (a register; (consol) the loader
                                        //   forms `flush` = ex && flush_w itself, as the sequencer
                                        //   did for it: the flush input gone)
    // the sequencer (tick A)
    input  wire        ex,
    input  v35_pop_e   pop,
    input  wire        e_pop,           // the word is an E word
    input  wire        dispm,           // the word is a DISPM word
    input  wire        e_rep,           // (F5d) the E word re-enters the REP page (ea=REP; a register)
    input  wire        e_pfx,           // (F4q) the E word is a prefix's (pfx: a register)
    input  wire        e_rep_nx,        // ... the next word's (tick B)
    output wire        q_stall,         // the word's pop finds no byte (stall q)
    // the registers
    output reg  [7:0]  opc,             // the running instruction's opcode (loaded with fmt)
    output reg  [7:0]  modrm,
    output reg  [7:0]  il,
    output reg  [7:0]  ih,
    output reg  [7:0]  dl,
    output reg  [7:0]  dh,
    output v35_udec_t  fmt,             // the running instruction's format (registered)
    // (MX5b) tick B: the values opc, modrm and fmt load at the coming ce_a (the datapath's early
    // register read forms the next word's read address from them)
    output wire [7:0]  opc_nx,
    output wire [7:0]  modrm_nx,
    output v35_udec_t  fmt_nx,
    output reg  [2:0]  op3,
    output v35_udecm_t dec2,            // tick A: v35_udec2(op, the byte this word pops) (its entry: d2ent)
    output wire [2:0]  len,             // tick A: the bytes still to pop after this clock (LEN)
    output wire [UADDR_W-1:0] dent,     // tick A: the DISP word's target
    output wire        dcall,           // tick A: (MX1) ... an EA head, called: the return is dret
    output wire [UADDR_W-1:0] dret,     // tick A: ... the routine's entry (the head's return)
    // (MX3c) the EAC word (a 0F form's ModR/M byte popped by a routine word): the byte's mode
    // (tick A, from the byte popped): register mode (the routine's register path), and for a
    // memory mode the EA head to call (the routine's ea=book / bare by the second level's eab)
    output wire        ec_reg,
    output wire        ec_call,
    output wire [UADDR_W-1:0] ec_head,
    // (MX5c) tick B: the next values of the stall's loader facts (the sequencer's registered
    // stall outcome), from the next word's pop fields, the queue's and the bus unit's next state
    input  v35_pop_e   pop_nx,
    input  wire        e_pop_nx,
    input  wire [2:0]  q_stored_nx,
    input  wire        q_odd_nx,
    input  wire        q_discard_nx,
    input  wire        q_dlv_nx,        // a fetched word is delivered on the next clock
    input  wire        flush_w_nx,      // the next word's FLUSH, its DISPM
    input  wire        dispm_nx,
    output wire        q_stall_nx,
    // (qprobe rules 1, 3) the releases from the queue's occupancy (the bytes fetched and not yet
    // released: the queue's count): the word's (`ro` the next opcode, `rl` operand bytes: the
    // sequencer's word, tick A; ro_nx the next word's, tick B: the staging wait) and the ModR/M
    // byte's on the first word after the dispatch (`mra`), counted into `rls`
    input  wire        ro,
    input  v35_rl_e    rl,
    input  wire        ro_nx,
    // (qprobe round 6) the word is the dispatch (the sequencer's registered derived bit; tick B:
    // the next word's): a release on the dispatch word (a store's N, the model's boundary word)
    // releases the opcode the E word popped, never waits for the staging register; (consol)
    // the dispatch executing (`disp`, the format's load) is ex && w_disp, formed here (the
    // disp input gone)
    input  wire        w_disp,
    input  wire        w_disp_nx,
    // (consol) this clock's releases (tick A) to the queue, which owns the count
    output wire [2:0]  rls,
    // (consol) tick B: the instruction stream's facts for the next clock's boundary, to the bus
    // unit's pace (v35_front_pkg v35_sf_t): the lead (rule 12: short of it, ld; ending, le), a
    // ModR/M opcode (three bytes behind it, rules 4c / 4d), HALT released and not yet run, and
    // the next word releasing a staged HALT (rule 11's line stop on that word's clock). Round 6
    // exported the count's compares from here (b4_nx, ew_nx, c4_nx, c5_nx, cf_nx: the queue's
    // now), the lead's two facts, the request word (rqx) and HALT's stop (fstop: the bus unit's)
    output v35_sf_t    sf_nx,
    // (qprobe rule 11) HALT: the word is a halt word (the sequencer's word); HALT released and
    // not yet run (`hp`; sf_nx, the bus unit's line stop), and a ce_b register of it for the EU
    // (a request posted then is granted a clock later)
    input  wire        w_halt,
    output reg         hp_b,
    input  wire        brki,            // (F2b) PSW.BRKI (the EU's register): the I/O trap's dispatch
    output reg  [15:0] ins_ip,          // (F2b) the instruction's start: the offset of the opcode the
                                        //   E word popped, kept through a segment prefix (its first
                                        //   prefix's offset: the I/O and FPO traps push it)
    output wire [15:0] ip               // (MX2) the instruction pointer (registers): the offset of
                                        //   the byte after the last the routine popped
);
    // (consol) the word executing a FLUSH, the dispatch executing (ex: the sequencer's registered
    // stall outcome; the word's bits registers)
    wire       flush = ex && flush_w;
    wire       disp = ex && w_disp;
    reg        s_v = 1'b0;
    reg [7:0]  s_b = 8'h00;
    reg [7:0]  op = 8'h00;              // the opcode the E word popped (the decode's input)
    // (MX2) the offset in PS of the staged opcode: the instruction pointer a transfer reads
    // (SR_PC) while the slot holds it ((step D) else the queue's head offset, q_ip)
    reg [15:0] s_ip = 16'd0;
    reg [2:0]  need = 3'd0;
    reg [7:0]  mp = 8'h00;              // the ModR/M byte the E word popped (the next instruction's)
    initial begin
        ins_ip = 16'd0;
        opc = 8'h00;
        modrm = 8'h00;
        il = 8'h00;
        ih = 8'h00;
        dl = 8'h00;
        dh = 8'h00;
        fmt = '0;
        op3 = 3'd0;
    end

    // ------------------------------------------------------------ tick A
    wire       wants_op = pop != PP_NONE;
    // (MX0b) the byte source the pops take from: the queue's window (`avail`), (MX1d) a
    // delivered word's bytes usable on its delivery clock (the frozen model's
    // queue.arrive(addr, t, t): usable <= t)
    // (MX5c) the bytes the pops can take (sn below) as a function of the window's count: the
    // same expression for this clock and the next
    function automatic logic [1:0] sn_f(input logic [2:0] av);
        sn_f = av >= 3'd2 ? 2'd2 : 2'(av);
    endfunction
    wire [7:0] sb0 = qv0;
    wire [7:0] sb1 = qv1;
    wire [1:0] sn = sn_f(q_avail);
    // the E word pops the staging register's opcode and, when the opcode has one, its ModR/M
    // byte from the queue's head (the opcode's decode from the staging register)
    // (MX5) the staging register's decode is a register beside it (`ds`: v35_udec1 of the byte
    // loaded into s_b, decoded in tick B from the ce_b registers and loaded with s_b at ce_a;
    // in reset with s_b, which a reset does not change): ds is v35_udec1(s_b) whenever s_v
    // (`+v35_chk`), and nothing reads it without s_v (the E pop stalls on an empty slot)
    v35_udec_t ds = '0;
    // (MX2) the E word pops the opcode's second byte with it: a ModR/M byte, or (the decode's e2)
    // a short transfer's displacement (into IL; the frozen model's take on the start clock)
    // (F5d) an E word with ea=REP pops the staged opcode alone (the REP page's second byte: its
    // ModR/M byte, displacement or 0F second byte stay in the queue for the cell's routine;
    // rep_nx refetches from the opcode); e_rep is the sequencer's registered word fact
    // (qprobe round 12, spec 7 A3) a REP prefix (the decode's rp) pops alone: its routine (rep_p)
    // pops the string opcode with its own E word (ea=REP)
    wire       ds2 = (ds.has_modrm || ds.e2 || (ds.pg && !ds.rp)) && !e_rep;   // (MX3c) the 0F page's second byte
    assign q_stall = (wants_op && sn == 2'd0)
                     || (e_pop && (!s_v || (ds2 && sn == 2'd0)))
                     || (ro && !s_v && !w_disp);    // (qprobe) N releases the staged opcode: none yet
    // the lookups the function reads (registers and the queue's head byte: early in tick A)
    wire       o1 = wants_op && !flush_w;
    wire       m1 = e_pop && ds2;
    wire [2:0] t1 = (o1 ? 3'd1 : 3'd0) - need;
    function automatic logic z1_f(input logic [2:0] us, input logic [2:0] uo, input logic [2:0] ug);
        z1_f = flush_w
               || ((m1 && ds.e2) ? ds.len - 3'd1 == t1
                 : (m1 && ds.pg) ? ug == t1
                 : m1 ? us == t1 - ds.len
                 : e_pop ? ds.len == t1
                 : (o1 && pop == PP_MODRM) ? uo == t1
                 : (o1 && dispm && !dec1.has_modrm) ? ug == t1 : t1 == 3'd0);
    endfunction
    // (MX5b) the head byte's lookups formed per candidate source before the head select: `hd_f`
    // of each candidate (the queue's first stored byte, its latch, the delivered word's two
    // bytes), selected by the registered facts that select the byte itself (the queue's
    // seqb(0)). The selected lookups are
    // hd_f(sb0) on every clock (`+v35_chk`); no lookup sits behind the select (README "MX5")
    typedef struct packed {
        logic [2:0] umr_s, umr_o, upg;
        logic       ecr, ecc;
        logic [UADDR_W-1:0] ech;
        logic       z;              // z1's compare for this byte (below)
    } v35_hd_t;
    // (MX5c) the head byte's facts of the byte alone are its tag (`bt_f`): the ModR/M byte's
    // displacement bytes (v35_umdsp), its reg field being 0 or 1 (mb[5:4] == 0), the 0F page's
    // second byte's added bytes (v35_upage) and the direct form (mod 00 rm 110). The tag is
    // formed on the delivered word (h_dlv, the bus unit's datum register) on its delivery clock
    // and stored by the queue beside each byte, through its storage (opaque bits
    // to the queue: dlv_tag, h_q0t; (E2) the latch's h_latt is gone). The opcode's share of v35_umodrm (the form's
    // immediate bytes, v35_umimm of the opcode and r01) is a register beside s_b (`ims`) and
    // beside op (`imo`), loaded with them (as ds and d1r are). So umodrm(s_b, b) is
    // dsp(tag) + ims[r01(tag)] and no decode table sits between a stored candidate and z; the
    // delivered word's two bytes are decoded in tick A, the only content-dependent decode left
    // there. `+v35_chk` compares the head facts with the tables' and each stored tag with its
    // byte's. README "MX5" round 3
    typedef struct packed {
        logic [1:0] dsp;
        logic       r01;
        logic [1:0] upg;
        logic       edir;
    } v35_btag_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_btag_t bt_f(input logic [7:0] b);
        logic [2:0] d, g;
        d = v35_umdsp(b);
        g = v35_upage(b);
        bt_f.dsp = d[1:0];
        bt_f.r01 = b[5:4] == 2'd0;
        bt_f.upg = g[1:0];
        bt_f.edir = b[7:6] == 2'd0 && b[2:0] == 3'd6;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // the opcode's share: {v35_umimm(o, 1), v35_umimm(o, 0)}
    function automatic logic [5:0] im_f(input logic [7:0] o);
        im_f = {v35_umimm(o, 1'b1), v35_umimm(o, 1'b0)};
    endfunction
    reg [5:0]  ims = 6'd0, imo = 6'd0;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_hd_t hd_f(input logic [7:0] b, input v35_btag_t t, input logic eab);
        hd_f.umr_s = {1'b0, t.dsp} + (t.r01 ? ims[5:3] : ims[2:0]);
        hd_f.umr_o = {1'b0, t.dsp} + (t.r01 ? imo[5:3] : imo[2:0]);
        hd_f.upg = {1'b0, t.upg};
        hd_f.ecr = b[7:6] == 2'd3;
        hd_f.ecc = !hd_f.ecr && (b[7:6] != 2'd0 || t.edir || eab);
        hd_f.ech = b[7:6] == 2'd1 ? (eab ? UROM_EAB8 : UROM_EA8)
                 : (b[7:6] == 2'd2 && eab) ? UROM_EAB16
                 : (b[7:6] == 2'd2 || t.edir) ? UROM_EAD
                 : UROM_EAB0;
        hd_f.z = z1_f(hd_f.umr_s, hd_f.umr_o, hd_f.upg);
    endfunction
`ifndef SYNTHESIS
    // the reference (`+v35_chk`): the facts from the tables on the byte itself
    function automatic v35_hd_t hd_ref(input logic [7:0] b, input logic eab);
        logic edir;
        hd_ref.umr_s = v35_umodrm(s_b, b);
        hd_ref.umr_o = v35_umodrm(op, b);
        hd_ref.upg = v35_upage(b);
        edir = b[7:6] == 2'd0 && b[2:0] == 3'd6;
        hd_ref.ecr = b[7:6] == 2'd3;
        hd_ref.ecc = !hd_ref.ecr && (b[7:6] != 2'd0 || edir || eab);
        hd_ref.ech = b[7:6] == 2'd1 ? (eab ? UROM_EAB8 : UROM_EA8)
                   : (b[7:6] == 2'd2 && eab) ? UROM_EAB16
                   : (b[7:6] == 2'd2 || edir) ? UROM_EAD
                   : UROM_EAB0;
        hd_ref.z = z1_f(hd_ref.umr_s, hd_ref.umr_o, hd_ref.upg);
    endfunction
`endif
    /* verilator lint_on UNUSEDSIGNAL */
    // (F5t) the delivered word's tags are a register beside the bus unit's datum register,
    // loaded with the same enable from the same next value (tick B: the pins' sampled datum or
    // the on-chip read register), so no decode table sits between the delivered word and z1:
    // tg_lo / tg_hi are bt_f(h_dlv) on every clock (`+v35_chk`; the datum register starts at
    // FFFFh, bt_f(FFh) = 6'b000010). The datum register's twin: its enable is the CPU clock's
    // middle at a read's B3 (ce_mid, the edge ce_a shares), written as the datum register's
    // own block is. README "F5t"
    v35_btag_t tg_lo = v35_btag_t'(6'b000010), tg_hi = v35_btag_t'(6'b000010);
    // (qprobe round 6, timing) the second level's numbered-opcode entries of the two bytes
    // (d2ent above), the datum register's start FFFFh's
    reg [7*UADDR_W-1:0] fe_lo = d2fe_all('1), fe_hi = d2fe_all('1);
    always @(posedge clock) begin
        if (h_dlv_ld) begin
            tg_lo <= bt_f(h_dlv_nx[7:0]);
            tg_hi <= bt_f(h_dlv_nx[15:8]);
            fe_lo <= d2fe_all(h_dlv_nx[7:0]);
            fe_hi <= d2fe_all(h_dlv_nx[15:8]);
        end
    end
    assign dlv_tag = {tg_hi, tg_lo};
    // the head byte's source: 0 the queue's first stored byte, 2 / 3 the delivered word's low /
    // high byte (seqb(0): stored bytes first, then the arrival at its parity). (E2) The queue's
    // latch and its candidate (1) are gone: a seventh byte is never held
    wire [2:0] hs = q_stored != 3'd0 ? 3'd0 : h_odd ? 3'd3 : 3'd2;
    v35_hd_t hd0, hd2, hd3, hh;
    assign hh = hs == 3'd0 ? hd0 : hs == 3'd2 ? hd2 : hd3;
    wire [2:0] umr_s = hh.umr_s;
    wire [2:0] umr_o = hh.umr_o;
    wire [2:0] upg_s = hh.upg;
    // (MX5) tick A's pops, the staging load and the room facts, as a function of the
    // sequencer's late bit `ex` (and the FLUSH it gates): `ta(x, fl)` is the code below with
    // ex = x and flush = fl, every other input a register or a register's lookup; the outputs
    // are `ex ? ta(1, flush_w) : ta(0, 0)` (Shannon's expansion on ex: the same function, the
    // late bit selecting last; flush is ex && the word's FLUSH, `+v35_chk`). README "MX5"
    typedef struct packed {
        logic       opop, epop, mpop, sload;
        logic [1:0] np;
        logic [2:0] need_n, rd;
    } v35_lta_t;
    // (MX5c) the function's register inputs (and the head byte's lookups, read by need_n only)
    // as a struct: `ln` the facts as they stand, `lx` their next values (tick B), for the
    // registered outcomes below
    typedef struct packed {
        logic       wants_op, e_pop, dispm, d1hm, ds2;
        v35_pop_e   pop;
        v35_udec_t  ds;
        logic [2:0] need, umr_s, umr_o, upg_s;
        logic       s_v;
        logic [1:0] sn;
    } v35_lin_t;
    // (MX5) z: the bytes still owed after this clock are none (need_n == 0), passed in so that
    // the queue head's decode (the one late input of the function's ex = 1 case) selects between
    // two outcomes formed early; the callers pass the true value (`z1`, `+v35_chk`)
    function automatic v35_lta_t ta(input logic x, input logic fl, input logic z,
                                    input v35_lin_t L);
        logic [2:0] add;
        logic       s_left;
        ta.opop = x && L.wants_op && !fl;
        ta.epop = x && L.e_pop;
        ta.mpop = ta.epop && L.ds2;               // ... and its second byte
        add = (ta.mpop && L.ds.e2) ? L.ds.len - 3'd1
            : (ta.mpop && L.ds.pg) ? L.upg_s        // (MX3c) the second byte's ModR/M and immediate
            : ta.mpop ? L.ds.len + L.umr_s
            : ta.epop ? L.ds.len
            : (ta.opop && L.pop == PP_MODRM) ? L.umr_o
            : (ta.opop && L.dispm && !L.d1hm) ? L.upg_s : 3'd0;
        ta.need_n = fl ? 3'd0 : L.need + add - (ta.opop ? 3'd1 : 3'd0);
        s_left = L.s_v && !ta.epop;
        // (MX2, MX3) the staging load on the E word's ModR/M pop's clock
        ta.sload = !fl && !s_left && z
                   && L.sn > ((ta.opop || ta.mpop) ? 2'd1 : 2'd0);
        // the bytes popped this clock (an operand or the E word's ModR/M byte, the staging load)
        ta.np = ((ta.opop || ta.mpop) ? 2'd1 : 2'd0) + (ta.sload ? 2'd1 : 2'd0);
        // the queue's port: the bytes leaving its storage
        ta.rd = {1'b0, ta.np};
    endfunction
    v35_lta_t lt0, lt1, ltx;
    // (MX5) z for ex = 1: need + add - opop == 0 (3 bits) is add == opop - need, each case's add
    // compared with that early target (the head byte's lookups compared, not summed)
    wire       z1 = hh.z;
    v35_lin_t  ln;
    always_comb begin
        ln.wants_op = wants_op;
        ln.e_pop = e_pop;
        ln.dispm = dispm;
        ln.d1hm = dec1.has_modrm;
        ln.ds2 = ds2;
        ln.pop = pop;
        ln.ds = ds;
        ln.need = need;
        ln.umr_s = umr_s;
        ln.umr_o = umr_o;
        ln.upg_s = upg_s;
        ln.s_v = s_v;
        ln.sn = sn;
    end
    assign lt0 = ta(1'b0, 1'b0, need == 3'd0, ln);
    assign lt1 = z1 ? ta(1'b1, flush_w, 1'b1, ln) : ta(1'b1, flush_w, 1'b0, ln);
    assign ltx = ex ? lt1 : lt0;
    // (MX5c) the outcomes the queue's port and the pops read, from registers: each of ta(1, flush_w, 1), ta(1, flush_w, 0) and ta(0, 0, need == 0)
    // reads registered state only (the head byte's lookups enter need_n, none of these), so
    // each is a ce_a register loaded with ta of the facts' next values (`lx`, tick B), in reset
    // with ta of the facts as they stand. Tick A selects them by the registered stall outcome
    // (ex) and z1 (the head byte's compare, the one content-dependent input):
    // `ex ? (z1 ? lr1 : lr0) : lrx` is ltx's on every clock (`+v35_chk`)
    typedef struct packed {
        logic [2:0] rd;
        logic       opop, mpop, epop;
    } v35_lrg_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_lrg_t lrg_f(input v35_lta_t t);
        lrg_f.rd = t.rd;
        lrg_f.opop = t.opop;
        lrg_f.mpop = t.mpop;
        lrg_f.epop = t.epop;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    v35_lrg_t  lr1 = '0, lr0 = '0, lrx = '0;
    v35_lrg_t  lrs, lrv;
    // (MX5c) z1 for these selects: z1_f's cases and targets read registered state only (the
    // word's pop fields and FLUSH, the staged opcode's decode, need, the opcode shares), so they
    // are a register (`zc`, loaded with zc_f of the next values, in reset of the values as they
    // stand); the head byte enters only through its tag (dsp, r01, upg): z1 is
    //   k || dsp == (r01 ? a1 : a0) || upg == g   (a1, a0, g: 3 when nothing matches)
    // `zt_f` is that compare for one candidate. The stored candidates' tags are registers (the
    // queue's); the delivered word's two bytes are decoded here, each compared, the head select
    // last. z1f is hh.z on every clock (`+v35_chk`)
    typedef struct packed {
        logic       k;
        logic [1:0] a1, a0;         // the dsp value that matches for r01 = 1 / 0 (3: none)
        logic [1:0] g;              // the upg value that matches (3 with t1 = 3; gv: any)
        logic       gv;
    } v35_zc_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_zc_t zc_f(input v35_lin_t l, input logic fw, input logic [5:0] s6,
                                     input logic [5:0] o6);
        logic       zo1, zm1, ce2, cpg, cus, cep, cuo, cug, cu;
        logic [2:0] zt1, ts, i1, i0, za1, za0;
        zo1 = l.wants_op && !fw;
        zm1 = l.e_pop && l.ds2;
        zt1 = (zo1 ? 3'd1 : 3'd0) - l.need;
        ce2 = zm1 && l.ds.e2;
        cpg = zm1 && !l.ds.e2 && l.ds.pg;
        cus = zm1 && !l.ds.e2 && !l.ds.pg;
        cep = !zm1 && l.e_pop;
        cuo = !zm1 && !l.e_pop && zo1 && l.pop == PP_MODRM;
        cug = !zm1 && !l.e_pop && !(zo1 && l.pop == PP_MODRM) && zo1 && l.dispm && !l.d1hm;
        zc_f.k = fw || (ce2 && l.ds.len - 3'd1 == zt1) || (cep && l.ds.len == zt1)
                 || (!zm1 && !l.e_pop && !(zo1 && l.pop == PP_MODRM)
                     && !(zo1 && l.dispm && !l.d1hm) && zt1 == 3'd0);
        cu = !fw && (cus || cuo);
        ts = cus ? zt1 - l.ds.len : zt1;
        i1 = cus ? s6[5:3] : o6[5:3];
        i0 = cus ? s6[2:0] : o6[2:0];
        za1 = ts - i1;
        za0 = ts - i0;
        zc_f.a1 = (cu && za1 <= 3'd2) ? za1[1:0] : 2'd3;
        zc_f.a0 = (cu && za0 <= 3'd2) ? za0[1:0] : 2'd3;
        zc_f.gv = !fw && (cpg || cug) && zt1 <= 3'd3;
        zc_f.g = zt1[1:0];
    endfunction
    function automatic logic zt_f(input v35_zc_t c, input v35_btag_t t);
        zt_f = c.k || (t.dsp == (t.r01 ? c.a1 : c.a0)) || (c.gv && t.upg == c.g);
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    v35_zc_t   zc = '0;
    // the head byte's candidates (hs, above): the stored ones' compares from their tags, each of
    // the delivered word's bytes decoded and compared, the head select last
    wire       z_st = zt_f(zc, v35_btag_t'(h_q0t));
    wire       z_lo = zt_f(zc, tg_lo);
    wire       z_hi = zt_f(zc, tg_hi);
    (* syn_keep = "true" *) wire z1f = hs == 3'd3 ? z_hi : hs == 3'd2 ? z_lo : z_st;
    // (ex, a register, selects first: the head byte's z1 last)
    (* syn_keep = "true" *) v35_lrg_t lrq1;
    (* syn_keep = "true" *) v35_lrg_t lrq0;
    assign lrq1 = ex ? lr1 : lrx;
    assign lrq0 = ex ? lr0 : lrx;
    assign lrs = z1f ? lrq1 : lrq0;
    assign lrv = lrs;
    wire       opop = lrv.opop;
    wire       epop = lrv.epop;
    wire       mpop = lrv.mpop;
    // (ltx: the function's outcomes the registered ones are checked against, `+v35_chk`; df.trap:
    // the trace's and the function bench's start_trap, v35_top's observation block)
    wire unused = &{1'b0, rls_b, ds, dm, q_avail, ltx, df.trap, lrv.rd[2]};
    wire [2:0] need_n = ltx.need_n;
    wire       sload = ltx.sload;
    assign pop_n = lrv.rd[1:0];         // (rd[2]: 0, at most two bytes a clock)
    assign len = need_n;
    // (MX2) the instruction pointer: the staged opcode's offset, else the next queue byte's (a
    // routine reads it after its last pop: the bytes owed are none)
    assign ip = s_v ? s_ip : q_ip;
    // (MX5b) the opcode register's decode is a register beside it, loaded with op's next value
    // at ce_a (in reset from op): dec1 is v35_udec1(op) on every clock (`+v35_chk`)
    v35_udec_t d1r = '0;
    v35_udec_t dec1;
    assign dec1 = d1r;
    // (the second level's lookup stays behind the head select: replicated per candidate it maps
    // into 72 more RAM blocks; its reader is the DISPM target, README "MX5" round 2)
    // (qprobe round 6, timing) the entry (the DISPM word's target, on the ROM's address in tick
    // A) split over the ticks: for an opcode the assembler numbers 0 (v35_udec2_fx: all but the
    // few whose second byte is a whole opcode, 0F's page and the REP pages) the entry is a
    // function of the byte's class (its mode being 3, its reg field: uasm.udec2_by_class), so
    // the opcode's sixteen entries are registers beside it (`d2row`, loaded at ce_a with op's
    // next value, in reset from op, as df) and the byte's class selects among them; the
    // numbered opcodes read their own lookup (v35_udec2_fe, a constant opcode each). Each is
    // formed per candidate head byte (the queue's first stored byte, the delivered word's low /
    // high byte) and selected by the registered facts that select the byte itself (hs: sb0 is
    // that choice, the queue's seqb(0)). d2ent is v35_udec2(op, sb0).entry on every clock
    // (`+v35_chk`)
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [UADDR_W-1:0] d2row_f(input logic [7:0] o, input logic [3:0] k);
        v35_udecm_t t;
        t = v35_udec2(o, {k[3] ? 2'b11 : 2'b00, k[2:0], 3'b000});
        d2row_f = t.entry;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // (one vector: flops, never inferred as a RAM block: the select is in tick A)
    reg [16*UADDR_W-1:0] d2row = '0;
    reg [2:0]  d2f = 3'd0;
    integer    d2i;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [UADDR_W-1:0] d2r_f(input logic [7:0] b);
        d2r_f = d2row[{b[7:6] == 2'b11, b[5:3]}*UADDR_W +: UADDR_W];
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // the numbered opcodes' entries of a byte, all seven (v35_udec2_fe), and their choice by d2f
    function automatic logic [7*UADDR_W-1:0] d2fe_all(input logic [7:0] b);
        for (int k = 0; k < 7; k = k + 1)
            d2fe_all[k*UADDR_W +: UADDR_W] = v35_udec2_fe(3'(k + 1), b);
    endfunction
    function automatic logic [UADDR_W-1:0] d2fe_sel(input logic [7*UADDR_W-1:0] e);
        d2fe_sel = '0;
        for (int k = 0; k < 7; k = k + 1)
            if (d2f == 3'(k + 1))
                d2fe_sel = e[k*UADDR_W +: UADDR_W];
    endfunction
    function automatic logic [UADDR_W-1:0] d2e_f(input logic [7:0] b);
        d2e_f = d2f != 3'd0 ? v35_udec2_fe(d2f, b) : d2r_f(b);
    endfunction
    wire [UADDR_W-1:0] d2e0 = d2e_f(h_q0);
    // the delivered word's two bytes: their numbered-opcode entries are registers beside the
    // bus unit's datum register (`fe_lo` / `fe_hi`, loaded with its enable from its next value,
    // as the tags tg_lo / tg_hi below): d2fe_all(h_dlv) on every clock (`+v35_chk`)
    wire [UADDR_W-1:0] d2e2 = d2f != 3'd0 ? d2fe_sel(fe_lo) : d2r_f(h_dlv[7:0]);
    wire [UADDR_W-1:0] d2e3 = d2f != 3'd0 ? d2fe_sel(fe_hi) : d2r_f(h_dlv[15:8]);
    wire [UADDR_W-1:0] d2ent = hs == 3'd0 ? d2e0 : hs == 3'd2 ? d2e2 : d2e3;
    v35_udecm_t dec2r;
    assign dec2r = v35_udec2(op, sb0);
    always_comb begin
        dec2 = dec2r;
        dec2.entry = d2ent;
    end
    // the dispatch's (DISP) entry: the second level on the registered ModR/M byte for an
    // opcode with one, else the first
    v35_udecm_t dm;
    assign dm = v35_udec2(op, mp);
    // (MX1) a memory cell (dm.ea) dispatches to the EA head of the registered ModR/M byte's
    // mode and returns to the routine's entry (its add): mod 01 one displacement pop, mod 10 and
    // the direct form (mod 00 rm 110) two; with the book's heads (dm.eab) each head ends with
    // the book's EA clock its pops and the add do not fill (OPEN), mod 00 included. A mode
    // without a head (mod 00, ea=bare) enters the routine directly. The mode's bits only: no
    // opcode reaches the choice (the cell's two bits are the decode table's)
    wire       d2l = dec1.has_modrm || dec1.pg;    // (MX3c) the dispatch reads the second level
    // (MX5) the dispatch's facts are a function of op and mp alone (`dsp_f`), held in a register
    // beside them (`df`: loaded at ce_a from the values op and mp load, in reset from op and mp):
    // df is dsp_f(op, mp) on every clock (`+v35_chk`), so the next address reads a register
    typedef struct packed {
        logic [UADDR_W-1:0] ent, ret;
        logic               call, trap, eab, io;
    } v35_dsp_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_dsp_t dsp_f(input logic [7:0] o, input logic [7:0] m);
        v35_udec_t  d1;
        v35_udecm_t d2;
        logic       mdir, mea, l2;
        logic [UADDR_W-1:0] hd;
        d1 = v35_udec1(o);
        d2 = v35_udec2(o, m);
        mdir = m[7:6] == 2'd0 && m[2:0] == 3'd6;
        mea = d1.has_modrm && d2.ea;
        l2 = d1.has_modrm || d1.pg;
        // (qprobe round 6) ea=q: the measured heads, one per mode (mod 00 too)
        // (qprobe round 10, Q18) base + index + d16 (mod 10, rm 0-3): its own head, one word more
        hd = d2.eaq ? (m[7:6] == 2'd1 ? UROM_EAQ8 : (m[7:6] == 2'd2 && !m[2]) ? UROM_EAQ16X
                       : (m[7:6] == 2'd2 || mdir) ? UROM_EAQ16 : UROM_EAQ0)
           : m[7:6] == 2'd1 ? (d2.eab ? UROM_EAB8 : UROM_EA8)
           : (m[7:6] == 2'd2 && d2.eab) ? UROM_EAB16
           : (m[7:6] == 2'd2 || mdir) ? UROM_EAD
           : UROM_EAB0;
        dsp_f.call = mea && (m[7:6] != 2'd0 || mdir || d2.eab || d2.eaq);
        dsp_f.ret = d2.entry;
        dsp_f.ent = !l2 ? d1.entry : dsp_f.call ? hd : d2.entry;
        dsp_f.trap = l2 ? d2.trap : d1.trap;
        dsp_f.eab = d2.eab;             // (the EAC word's head choice: dm.eab)
        dsp_f.io = l2 ? d2.io : d1.io;     // (F2b) an I/O form (no ModR/M: never a call)
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    v35_dsp_t df = '0;
    assign dcall = df.call;
    assign hd0 = hd_f(h_q0, v35_btag_t'(h_q0t), df.eab);
    assign hd2 = hd_f(h_dlv[7:0], tg_lo, df.eab);
    assign hd3 = hd_f(h_dlv[15:8], tg_hi, df.eab);
    assign dret = df.ret;
    // (F2b) the I/O trap: an I/O form (the decode's io: IN, OUT, INM, OUTM, the REP I/O strings)
    // with PSW.BRKI 0 dispatches to the trap's routine instead of its own: BRKI as the PSW
    // register stands while the dispatch word runs (after the previous instruction's E word's
    // writes: POP PSW's BRKI acts at once, f2_iot); a 2:1 select on two register bits
    assign dent = (df.io && !brki) ? UROM_IOT : df.ent;
    // (MX3c) the EAC word: the mode of the byte it pops (sb0) picks the register path or the EA
    // head of that mode, as `head` above does for the registered ModR/M (the mode's bits and the
    // routine's eab only)
    assign ec_reg = hh.ecr;
    assign ec_call = hh.ecc;
    assign ec_head = hh.ech;

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg        e2_b = 1'b0;
    reg        mpop_b = 1'b0, opop_b = 1'b0, epop_b = 1'b0, sload_b = 1'b0, flush_b = 1'b0, disp_b = 1'b0;
    reg        dispm_b = 1'b0;
    reg        erep_b = 1'b0;           // (F5d) the E pop re-enters the REP page
    reg        rpop_b = 1'b0;           // (qprobe round 12) the E pop is a REP prefix's own (mp <- the prefix)
    reg        epfx_b = 1'b0;           // (F4q) the E pop is a prefix's own (its word has pfx)
    v35_pop_e  pop_b = PP_NONE;
    reg [7:0]  sb0_b = 8'h00, sb1_b = 8'h00;
    reg [2:0]  need_b = 3'd0;
    v35_udec_t dec1_b = '0;
    reg [2:0]  op3m_b = 3'd0;
    reg        dmw_b = 1'b0;
    reg  [2:0] rls_b = 3'd0;            // (qprobe) this clock's releases
    reg        ex_lb = 1'b0;            // (qprobe) the word executes
    reg        ro_b = 1'b0;             // (qprobe rule 12) the next opcode released now
    reg        hrel_b = 1'b0, hw_b = 1'b0;     // (qprobe rule 11) HALT released now; the halt word
    initial hp_b = 1'b0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            rls_b <= rls;
            ex_lb <= ex;
            ro_b <= ex && ro;
            hrel_b <= hrel;
            hw_b <= ex && w_halt;
            hp_b <= hp || hrel;
            opop_b <= opop;
            mpop_b <= mpop;
            e2_b <= ds.e2;
            epop_b <= epop;
            erep_b <= epop && e_rep;
            rpop_b <= epop && !e_rep && ds.rp;     // (qprobe round 12) a REP prefix's own pop
            epfx_b <= epop && e_pfx;
            sload_b <= sload;
            flush_b <= flush;
            disp_b <= disp;
            dispm_b <= ex && dispm;
            pop_b <= pop;
            sb0_b <= sb0;
            sb1_b <= sb1;
            need_b <= need_n;
            dec1_b <= dec1;
            op3m_b <= dispm ? dec2.op3 : d2l ? dm.op3 : dec1.op3;
            dmw_b <= dm.w;
        end
    end

    // ------------------------------------------------------------ (qprobe) the releases
    // The model's count (validation/v35s/qprobe/model.py) is the bytes fetched and not released.
    // (consol) The queue owns it (v35_queue `ob`); the loader counts the releases (`rls`: the
    // word's ro and rl, and the ModR/M byte's below) and the stream facts the boundary reads
    // (sf_nx). Round 6 kept the bytes taken out of the queue and not released here (`oadj`, with
    // its dispatch-time reset to the staging register and the E word's second byte): that
    // register is now the simulation's reference (`oadj_ref`, below), against which the queue's
    // count is compared every clock.
    //   mra  (rule 3) the ModR/M (or page) byte the E word popped is released on the first word
    //        executed after the dispatch (the routine's first word, or its EA head's)
    reg        mpm = 1'b0;              // the last E word popped a ModR/M or page byte (not a displacement)
    reg        mra = 1'b0;
    //   lc   (rule 12) the clocks since the last release of a next opcode (`ro`), at most 3: the
    //        dispatch into the opcode register's instruction waits while lc is below the
    //        decode's lead (the staged opcode released at t, its boundary at t + lead at the
    //        earliest: MOV sreg,r16 2, OUT / IN imm8 3)
    //   hp   (rule 11) HALT's opcode released and the halt word not yet run (cleared there, or
    //        at a flush: an interrupt taken at HALT's dispatch). From the release (`hrel`: a
    //        word releasing the staged opcode HALT: the staged opcode's decode `hlt`) the request line
    //        is low (the bus unit's, from sf_nx: hp, and hc for the releasing word's own
    //        clock), and a request the EU posts is granted a clock later (the EU's, from hp_b)
    reg  [2:0] lc = 3'd4;           // (qprobe round 6) to 4: a lead of 3 ending is seen once
    reg        hp = 1'b0;
    wire       hrel = ex && ro && s_v && ds.hlt;
    // (rl=X: a request word, no byte released)
    assign rls = !ex ? 3'd0 : {2'd0, ro} + ((rl == RL_X) ? 3'd0 : {1'd0, rl}) + {2'd0, mra};
    wire       mpm_nx = epop_b ? (mpop_b && !e2_b) : mpm;
    wire       mra_nx = flush_b ? 1'b0 : disp_b ? mpm : ex_lb ? 1'b0 : mra;
    wire [2:0] lc_nx = ro_b ? 3'd1 : lc == 3'd4 ? 3'd4 : lc + 3'd1;
    wire       hp_nx = hrel_b ? 1'b1 : (flush_b || hw_b) ? 1'b0 : hp;
    // ------------------------------------------------------------ the end of the clock (ce_a)
    wire [7:0] s_nb = (opop_b || mpop_b) ? sb1_b : sb0_b;     // the staging load's byte
    // (MX5c) the next values the sequencer's registered stall reads (tick B; the block below
    // loads s_v, ds and d1r with exactly these): q_stall and the opcode register's decode bits
    // as they stand after the coming ce_a
    wire       s_v_nx = flush_b ? 1'b0 : sload_b ? 1'b1 : epop_b ? 1'b0 : s_v;
    v35_udec_t ds_nx;
    assign ds_nx = (!flush_b && sload_b) ? v35_udec1(s_nb) : ds;
    wire       arrive_nx = q_dlv_nx && !q_discard_nx;
    wire [3:0] av_w_nx = {1'b0, q_stored_nx}
                         + (!arrive_nx ? 4'd0 : q_odd_nx ? 4'd1 : 4'd2);
    wire [2:0] av_nx = av_w_nx > 4'd7 ? 3'd7 : av_w_nx[2:0];
    wire [1:0] sn_nx = sn_f(av_nx);
    // (consol) the stream facts for the next clock's boundary (the bus unit's pace)
    assign sf_nx.ld = lc_nx < {1'b0, d1_nx.lead};                      // (qprobe rule 12)
    assign sf_nx.le = d1_nx.lead != 2'd0 && lc_nx == {1'b0, d1_nx.lead};    // (round 6, E)
    assign sf_nx.m3 = d1_nx.m3;     // (rules 4c, 4d; qprobe round 8, Q20: the decode's m3, not FE / F7)
    assign sf_nx.hp = hp_nx;                                            // (rule 11)
    assign sf_nx.hc = ro_nx && s_v_nx && ds_nx.hlt;     // (rule 11: hrel on the next clock, but ex)
    wire       ds2_nx = (ds_nx.has_modrm || ds_nx.e2 || (ds_nx.pg && !ds_nx.rp)) && !e_rep_nx;
    assign q_stall_nx = (pop_nx != PP_NONE && sn_nx == 2'd0)
                        || (e_pop_nx && (!s_v_nx || (ds2_nx && sn_nx == 2'd0)))
                        || (ro_nx && !s_v_nx && !w_disp_nx);
    // (MX5) the values op and mp load at ce_a (the dispatch facts' register reads them)
    // (F5d) an E word with ea=REP (a REP-page prefix cell's: REP seg / REP BUSLOCK) pops the
    // staged opcode into the ModR/M register and keeps the opcode register (the REP byte): the
    // dispatch reads the REP page's cell of the popped opcode (silicon, f5r repsegstr: REP
    // then segment prefixes and BUSLOCK, then a string opcode, repeats the string)
    wire [7:0] op_nx = (epop_b && !erep_b) ? s_b : op;
    // (qprobe round 12) a REP prefix's pop loads the ModR/M register with the prefix's byte too:
    // the dispatch reads the REP page at it (rep_p's cell)
    wire [7:0] mp_nx = (mpop_b && !e2_b) ? sb0_b : (erep_b || rpop_b) ? s_b : mp;   // (exclusive: ds2 is 0 on erep and on a prefix's pop)
    // (MX5b) opc, modrm and fmt load exactly these at ce_a (the block below assigns them)
    assign opc_nx = disp_b ? op : opc;
    assign modrm_nx = disp_b ? mp : (opop_b && pop_b == PP_MODRM) ? sb0_b : modrm;
    always_comb begin
        fmt_nx = fmt;
        if (disp_b) begin
            fmt_nx = dec1_b;
            if (dec1_b.pg)
                fmt_nx.w = dmw_b;   // (MX3c) the 0F form's width (the second level's)
        end
    end
    v35_udec_t d1_nx;
    assign d1_nx = v35_udec1(op_nx);
    // the function's facts after the coming ce_a (the block below loads these)
    v35_lin_t  lx;
    always_comb begin
        lx = '0;                        // (the head byte's lookups: not read by lrg_f's fields)
        lx.wants_op = pop_nx != PP_NONE;
        lx.e_pop = e_pop_nx;
        lx.dispm = dispm_nx;
        lx.d1hm = d1_nx.has_modrm;
        lx.ds2 = ds2_nx;
        lx.pop = pop_nx;
        lx.ds = ds_nx;
        lx.need = need_b;
        lx.s_v = s_v_nx;
        lx.sn = sn_nx;
    end
    wire [5:0] ims_nx = (!flush_b && sload_b) ? im_f(s_nb) : ims;
    wire [5:0] imo_nx = im_f(op_nx);
    always_ff @(posedge clock) begin
        if (!reset_n)
            zc <= zc_f(ln, flush_w, ims, imo);
        else if (ce_a)
            zc <= zc_f(lx, flush_w_nx, ims_nx, imo_nx);
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            lr1 <= lrg_f(ta(1'b1, flush_w, 1'b1, ln));
            lr0 <= lrg_f(ta(1'b1, flush_w, 1'b0, ln));
            lrx <= lrg_f(ta(1'b0, 1'b0, need == 3'd0, ln));
        end else if (ce_a) begin
            lr1 <= lrg_f(ta(1'b1, flush_w_nx, 1'b1, lx));
            lr0 <= lrg_f(ta(1'b1, flush_w_nx, 1'b0, lx));
            lrx <= lrg_f(ta(1'b0, 1'b0, need_b == 3'd0, lx));
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            df <= dsp_f(op, mp);
            d1r <= v35_udec1(op);
            imo <= im_f(op);
        end else if (ce_a) begin
            df <= dsp_f(op_nx, mp_nx);
            d1r <= d1_nx;
            imo <= imo_nx;
        end
    end
    // (qprobe round 6, timing) the opcode's sixteen second-level entries (d2ent, above)
    always_ff @(posedge clock) begin
        if (!reset_n || ce_a) begin
            for (d2i = 0; d2i < 16; d2i = d2i + 1)
                d2row[d2i*UADDR_W +: UADDR_W] <= d2row_f(!reset_n ? op : op_nx, d2i[3:0]);
            d2f <= v35_udec2_fx(!reset_n ? op : op_nx);
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            mpm <= 1'b0;
            mra <= 1'b0;
            lc <= 3'd4;
            hp <= 1'b0;
        end else if (ce_a) begin
            mpm <= mpm_nx;
            mra <= mra_nx;
            lc <= lc_nx;
            hp <= hp_nx;
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            ds <= v35_udec1(s_b);
            ims <= im_f(s_b);
            s_v <= 1'b0;
            need <= 3'd0;
        end else if (ce_a) begin
            fmt <= fmt_nx;
            opc <= opc_nx;
            modrm <= modrm_nx;
            need <= need_b;
            if (flush_b) begin
                s_v <= 1'b0;
            end else begin
                if (sload_b) begin
                    s_v <= 1'b1;
                    s_b <= s_nb;
                    ds <= ds_nx;
                    ims <= ims_nx;
                    s_ip <= q_ip + ((opop_b || mpop_b) ? 16'd1 : 16'd0);
                end else if (epop_b)
                    s_v <= 1'b0;
            end
            if (epop_b && !erep_b) begin
                op <= s_b;
                // (F4q) kept through a segment prefix's own E word only: a take's routine entered
                // in place of a prefix (intr, msv, the DMA's) pops with the prefix's format
                // still loaded; its E word (the handler's first opcode, or the prefix again)
                // starts an instruction (pfxtake.py f4q_l nmi_ms: the macro service at NMI's
                // handler's first instruction resumed at the interrupted prefix: the handler lost)
                if (!fmt.seg[2] || !epfx_b)
                    ins_ip <= s_ip;
            end
            if (mpop_b && !e2_b)
                mp <= sb0_b;
            else if (erep_b || rpop_b)
                mp <= s_b;              // (F5d) the REP page's second byte (op_nx, mp_nx above)
            if (mpop_b && e2_b)
                il <= sb0_b;            // (MX2) the short transfer's displacement
            if (opop_b) begin
                case (pop_b)
                    PP_MODRM: ;                 // (modrm_nx)
                    PP_IL, PP_PORT: il <= sb0_b;
                    PP_IH: ih <= sb0_b;
                    PP_DL: dl <= sb0_b;
                    PP_DH: dh <= sb0_b;
                    default: ;
                endcase
            end
            if (disp_b) begin
                // (MX5b) fmt, opc and modrm: their next values (above)
                op3 <= op3m_b;
            end
            if (dispm_b)
                op3 <= op3m_b;
        end
    end

`ifndef SYNTHESIS
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if ((s_v && ds !== v35_udec1(s_b)) || df !== dsp_f(op, mp) || hh !== hd_ref(sb0, df.eab) || d1r !== v35_udec1(op)
                || imo !== im_f(op) || (s_v && ims !== im_f(s_b))
                || (q_stored != 3'd0 && h_q0t !== bt_f(h_q0))
                || (ex ? z1 : need == 3'd0) !== (need_n == 3'd0)
                || opop_b !== opop || mpop_b !== mpop || e2_b !== ds.e2 || epop_b !== epop || sload_b !== sload || flush_b !== flush
                || disp_b !== disp || dispm_b !== (ex && dispm) || pop_b !== pop
                || sb0_b !== sb0 || sb1_b !== sb1
                || need_b !== need_n
                || dec1_b !== dec1 || dmw_b !== dm.w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader: a tick A source changed in tick B at %0t", $time);
            end
        end
    end
    // (MX5c) every clock: the registered outcomes against the function's
    always @(posedge clock) begin
        if (chk_on && reset_n && (lrs !== lrg_f(ltx) || z1f !== z1 || d2ent !== dec2r.entry
                                  || fe_lo !== d2fe_all(h_dlv[7:0]) || fe_hi !== d2fe_all(h_dlv[15:8])
                                  || tg_lo !== bt_f(h_dlv[7:0]) || tg_hi !== bt_f(h_dlv[15:8])
                                  || zc !== zc_f(ln, flush_w, ims, imo))) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: loader: the registered outcomes differ at %0t", $time);
        end
    end
    // (qprobe) a dispatch where the releases did not match the pops (the count set back), the
    // stored adjustment against its parts ((consol) the removed register `d`, the bytes popped
    // into the registers less the releases, kept here as the reference), and the release
    // count's ce_b copy
    reg  [2:0] d_ref = 3'd0;
    reg  [3:0] oadj_ref = 4'd0;         // (consol) round 6's oadj (the queue's count's reference)
    reg        mpp = 1'b0;              // the last E word popped a second byte
    wire [2:0] pops_rb = {2'd0, opop_b} + {2'd0, mpop_b} + {2'd0, epop_b};
    wire [3:0] np_b = {3'd0, opop_b || mpop_b} + {3'd0, sload_b};
    wire [3:0] oadj_run = oadj_ref + np_b - {1'b0, rls_b};
    always @(posedge clock) begin
        if (!reset_n) begin
            d_ref <= 3'd0;
            oadj_ref <= 4'd0;
            mpp <= 1'b0;
        end else if (ce_a) begin
            d_ref <= flush_b ? 3'd0 : disp_b ? {2'd0, mpp} : d_ref + pops_rb - rls_b;
            oadj_ref <= flush_b ? 4'd0 : disp_b ? {3'd0, s_v_nx} + {3'd0, mpp} : oadj_run;
            mpp <= epop_b ? mpop_b : mpp;
        end
    end
    integer rsync_n = 0;
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (disp_b && !flush_b && oadj_run != {3'd0, s_v_nx} + {3'd0, mpp}) begin
                rsync_n = rsync_n + 1;
                if (rsync_n <= 20)
                    $display("v35 chk: loader: releases against pops off by %0d at a dispatch at %0t",
                             $signed(oadj_run) - $signed({3'd0, s_v_nx} + {3'd0, mpp}), $time);
            end
            if (rls_b !== rls || ex_lb !== ex || oadj_ref !== {3'd0, s_v} + {d_ref[2], d_ref}
                || ro_b !== (ex && ro) || hrel_b !== hrel || hw_b !== (ex && w_halt)) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader: the occupancy's sources changed in tick B at %0t", $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: loader: %0d changes in tick B", chk_n);
    final if (chk_on && rsync_n != 0)
        $display("v35 chk: loader: %0d dispatches with the releases off the pops", rsync_n);
    // +v35_ldbg=FILE: the loader's room facts each clock (bring-up; clock as the queue's qdbg)
    integer lfd = 0;
    string lfn;
    integer lt = 0;
    initial if ($value$plusargs("v35_ldbg=%s", lfn)) lfd = $fopen(lfn, "w");
    always @(posedge clock) begin
        if (lfd != 0 && reset_n && ce_a) begin
            $fdisplay(lfd, "l %0d s_v %0d need %0d need_n %0d epop %0d opop %0d mpop %0d sload %0d np %0d rd %0d win %0d",
                      lt, s_v, need, need_n, epop, opop, mpop, sload, ltx.np, pop_n, q_avail);
            lt <= lt + 1;
        end
    end
    /* verilator lint_on BLKSEQ */
`endif
endmodule
