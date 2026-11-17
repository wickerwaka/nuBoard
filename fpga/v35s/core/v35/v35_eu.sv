`timescale 1ns/1ps

// V35S core v2 (MX0): the datapath, re-plumbed to the microinstruction's fields
// (docs/v35s-mechanisms.md sections 3.3-3.6; README "MX0"). It keeps the register RAM's ports
// (v35_regram), the ALU and the functions (v35_fn_pkg), and adds nothing that times a form:
// every act is a field of the word the sequencer executes (`word`, `ex_b`).
//
// Two ticks (S7b):
//   tick A  the word's register selectors -> the RAM's read addresses (ra_next / rb_next,
//           latched by v35_regram at ce_b); the request port's level (req_v, its address and
//           width: registers); the stall inputs (opr_rdy, rq_busy, wr_hold: registers)
//   tick B  the RAM's data (this word's reads), the sources, the ALU (SIGMA and the flags),
//           the EA step, the moves, the write port (written at ce_a), the request's next state
// Everything a word does lands at ce_a when it executed (ex_b).
//
// The register file is the internal RAM (mechanisms 3.3): a register is a word of the bank
// PSW.RB; a byte register a half. Port A and port B read, the write port writes one register
// (a half) a word. The segment registers have flops beside their RAM words (the request's
// segment, PS for the queue), written together.
//
// The bus request (mechanisms 3.6): a word posts a request on the A1 port; the request stands
// (req_v) from the next clock until the bus unit acknowledges it (req_ack); it is outstanding
// until req_done. The address is the segment + the address register as the posting word
// leaves it; the write datum is OPRW as the posting word leaves it (rq_d, taken at the post). A read's datum is latched at
// req_done (an odd word's first half's byte at its own end); the F word takes it (opr_rdy).
// A memory write holds the routine's F and E until its end while RAMEN = 1 (PRC bit 6): with the
// internal RAM mapped, a store may land in the register RAM the next words read ((step D) kept:
// function-bearing, README "Step D"); an I/O write is posted and not waited for. (Step D) The
// reservation is gone; the bus unit latches a write's datum at its B2.
//
// Registered state (widths): psw 16, ds1 ps ss ds0 4x16, ta tb tc 3x16, sigma 16, scy 1,
// addr 16, ea_ss 1, oprw 16, pfx_v 1, pfx_s 2, mul (v35_mul_t 51), div (v35_div_t 75), dtrap 1;
// the request: rq_v 1, rq_cyc 2, rq_word 1, rq_pair 1, rq_addr 20, rq_off
// 16, rq_out 1, rq_rd 1, rq_wr 1, rq_io 1, opr_v 1, opr 16, plo 8, (F5b, qprobe round 6) rq_d 16; the ce_b copies.
module v35_eu
    import v35_front_pkg::*;
    import v35_pkg::*;
    import v35_fn_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    // the sequencer
    input  v35_uword_t word,
    // (MX5b) tick B: the next word and the values opc, modrm and fmt load at ce_a (the early read)
    input  v35_uword_t word_nx,
    input  wire [7:0]  op_nx,
    input  wire [7:0]  modrm_nx,
    input  v35_udec_t  fmt_nx,
    input  wire        ex_b,            // tick B / ce_a
    // the loader's registers
    input  v35_udec_t  fmt,
    input  wire [2:0]  op3,
    input  wire [7:0]  op,
    input  wire [7:0]  modrm,
    input  wire [7:0]  il,
    input  wire [7:0]  ih,
    input  wire [7:0]  dl,
    input  wire [7:0]  dh,
    input  wire [15:0] ip,              // (MX2) the instruction pointer (the loader's registers)
    input  wire [15:0] ins_ip,          // (F2b) the instruction's start: its first prefix's offset
    input  wire [7:0]  idb,             // (F2b) IDB (v35_sfr's register): SG_IDB's segment
    input  wire        p14,             // (F2b) the P14 pin as POLL reads it (v35_sfr's register)
    // the register RAM
    output wire [6:0]  ra_next,
    output wire [6:0]  rb_next,
    output wire [6:0]  ra_early,        // (MX5b) tick B: the next word's read addresses (read at ce_a)
    output wire [6:0]  rb_early,
    input  wire [15:0] ra_data,
    input  wire [15:0] rb_data,
    output wire        wa_en,
    output wire [6:0]  wa_addr,
    output wire [1:0]  wa_be,
    output wire [15:0] wa_data,
    // the bus unit's EU request port (A1)
    output wire        req_v,
    output wire [1:0]  req_cyc,
    output wire [19:0] req_addr,
    output wire        req_width,
    output wire [15:0] req_data,
    input  wire        req_ack,
    input  wire        req_done,
    input  wire [15:0] done_data,
    input  wire        eu_dlv,          // an EU cycle's datum is delivered now (a pair's first half too)
    input  wire        ramen,           // PRC.RAMEN
    // (MX5c) tick B: the next values of the stall inputs (the sequencer's registered stall
    // outcome): from the request registers' next state, the bus unit's next req_done, the
    // next RAMEN
    input  wire        req_done_nx,
    input  wire        ramen_nx,
    output wire        opr_rdy_nx,
    output wire        rq_busy_nx,
    output wire        wr_hold_nx,
    output wire        req_v_nx,        // (qprobe rule 4b) the request port's level's next value
    // (qprobe round 6, D) tick B: a memory request posted and not yet granted on the next clock
    // (the boundary's E_PEND)
    output wire        rqm_nx,
    // (qprobe rule 11) HALT's opcode released and HALT not yet run (the loader's ce_b register):
    // a request posted now is granted a clock later (the port's level held low a clock)
    input  wire        hp_b,
    // to the sequencer (registers; rb_lo tick B)
    output wire        opr_rdy,
    output wire        rq_busy,
    output wire        wr_hold,
    output wire        c_sgn,
    output wire        c_dtrap,
    output wire        c_xc,            // (MX2) the transfer's condition (registers)
    output wire        c_snz,           // (MX2) SIGMA is not zero
    output wire        c_f1,            // (MX3b) F1, the units' sign latch (the operands' signs differ)
    output wire        c_dn,            // (MX3b) the divide's dividend negative (DIVI's)
    output wire [7:0]  rb_lo,
    output wire [3:0]  sig_lo,          // (F2a) SIGMA's low four bits (a register: CN_SIG)
    // the queue's flush (tick A: registers)
    output wire [15:0] flush_off,
    output wire [19:0] ps_base,
    // (F1) the SFR page's FLAG (PSW bits 5 and 3, F1 and F0): read, and a store's bits at ce_a
    output wire [1:0]  psw_f,
    output wire        psw_brki,        // (F2b) PSW.BRKI (the loader's I/O-trap dispatch)
    output wire        psw_ie,          // (F3) PSW.IE and PSW.BRK (the interrupt take at the dispatch)
    output wire        psw_brk,
    input  wire [4:0]  tk_vec,          // (F3) the vector the dispatch took (v35_intc's register)
    input  wire        tk_bs,           // (F3b) ... a bank-switch take (ENCS 1), its level tk_l
    input  wire        tk_int,          // (F3b) ... the INT take (the vector from the bus)
    input  wire [2:0]  tk_l,
    input  wire        tk_ms,           // (F4b) ... a macro-service take; its channel, mode, DIR
    input  wire [2:0]  ms_ch,
    input  wire [2:0]  ms_mode,
    input  wire        ms_dir,
    input  wire        ms_hlt,          // (F4b) the take followed a HALT (v35_intc's register)
    output reg         ms_end,          // (F4b) the service's end (a ce_a strobe, MSDC's)
    // (F4c) a DMA take (v35_intc's register; the channel arrives on ms_ch) and its descriptor
    // (v35_dma's registers): the macro-service ops read it in place of the macro service's
    // (urom/dma.uasm); the TC update (MSDC: a ce_a strobe, TC reached 0), the last transfer in
    // flight (a register to the next take), the request's DMA cycle (`req_dk`: a transfer on
    // the pins, DMAAK's and TC's window)
    input  wire        tk_dm,
    input  wire        dm_in,
    input  wire        dm_out,
    input  wire        dm_w,
    input  wire [1:0]  dm_ps,
    input  wire [1:0]  dm_pd,
    output reg         dm_tend,
    output reg         dm_tlast,
    output reg         dm_last,
    output wire        req_dk,
    input  wire        ns_pin,          // (F3b) the N/S pin ((step C) sampled here, `ns`: MD at
                                        //   reset and on every interrupt entry)
    output wire        req_ia,          // (F3b) the request is an INT acknowledge (with RQ_IOR)
    input  wire        flag_we,
    input  wire [1:0]  flag_d,
    // (F1) the internal RAM's on-chip write (the bus unit's: the register RAM written at the
    // coming ce_b, registers): (step B) one to the current bank's DS0 / SS / DS1 slot is
    // decoded here, the segment's flop taking the slot's bytes at ce_a (a PS slot write reaches
    // the RAM only: README "F1")
    input  wire        oc_we,
    input  wire [6:0]  oc_wa,
    input  wire [1:0]  oc_be,
    input  wire [15:0] oc_wd
);
    // ------------------------------------------------------------ registered state
    // (F3b) N/S as last sampled: every fabric clock, no enable (the pin's sampler; (step C) moved
    // in from v35_top, its only reader the PSW's MD here)
    reg        ns = 1'b1;
    always @(posedge clock)
        ns <= ns_pin;
    reg [15:0] psw = 16'hF002;
    // (F1) the on-chip write's segment hit: the current bank's (PSW.RB) DS0 / SS / DS1 slot,
    // the flops' slot (0 DS1, 2 SS, 3 DS0)
    wire [2:0] psw_rb = psw[14:12];
    wire       oc_seg_we = oc_we && oc_wa[6:4] == psw_rb
                           && (oc_wa[3:0] == 4'd4 || oc_wa[3:0] == 4'd5 || oc_wa[3:0] == 4'd7);
    wire [1:0] oc_seg_s = oc_wa[3:0] == 4'd7 ? 2'd0 : oc_wa[3:0] == 4'd5 ? 2'd2 : 2'd3;
    reg        rq_ia = 1'b0;            // (F3b) the request posted is an INT acknowledge
    // (qprobe round 12, spec 7 A2) the write posted is not yet armed (BQ_MEMWD: its datum is
    // loaded by a later word, K: the first word after the post that loads OPRW). While it stands
    // the request is presented only while K is the current word (`k_cur`), with req_ia set:
    // the bus unit grants such a write only on a clock K executes (its ex) and no fetch asks for
    // the bus; K's load writes the request's datum (rq_d) and arms it. A write never reaches the
    // pins before its datum (`+v35_chk` below)
    reg        rq_un = 1'b0;
    reg        rq_dk = 1'b0;            // (F4c) the request posted is a DMA transfer's cycle
    initial begin
        dm_tend = 1'b0;
        dm_tlast = 1'b0;
        dm_last = 1'b0;
    end
    // (F4c) a DMA address's step (SAR by PS, DAR by PD): 01 +, 10 -, by the width
    function automatic logic [15:0] dstep(input logic [15:0] a, input logic [1:0] c,
                                          input logic wd);
        dstep = c == 2'b01 ? a + (wd ? 16'd2 : 16'd1)
              : c == 2'b10 ? a - (wd ? 16'd2 : 16'd1) : a;
    endfunction
    reg [15:0] ds1 = 16'd0, ps = 16'hFFFF, ss = 16'd0, ds0 = 16'd0;
    reg [15:0] ta = 16'd0, tb = 16'd0, tc = 16'd0, sigma = 16'd0, addr = 16'd0, oprw = 16'd0;
    reg        ms_eq = 1'b0;            // (F4b) MSEQ's match
    initial ms_end = 1'b0;
    reg        scy = 1'b0, ea_ss = 1'b0, pfx_v = 1'b0, dtrap = 1'b0;
    // (MX3c) the BCD string's state: the carry / borrow rides the shifter's step latch scy.
    // (F5b: silicon, f5x bcd4s, 220 cases) the flags after the string are the last byte step's:
    // CY the carry, Z every byte written zero (bor: the bytes ORed, BCDI clears it), S and P the
    // last byte's (bl), AC its low digit's adjust decision (bac), V the adjust's overflow (bs7:
    // the binary sum's bit 7 before the adjust)
    reg [7:0]  bor = 8'd0, bl = 8'd0;
    reg        bac = 1'b0, bs7 = 1'b0;
    reg [1:0]  pfx_s = 2'd0;
    // (F5b) the first prefix's start through BUSLOCK and a REP before a non-string opcode (the
    // words marked `pfx` on their E): a trap's ist pushes it (silicon, f5a_038: LOCK FPO2 pushes
    // the LOCK's offset; the loader's ins_ip keeps it through the segment prefixes only)
    reg [1:0]  pist = 2'd0;              // (F4q) its low two bits: all sist reads
    reg        pist_v = 1'b0;
    // (F4q) silicon's instruction start (validation/v35s/pfxtake.py, both sessions): the opcode's
    // offset less the count of its prefix bytes modulo 4 (a two-bit prefix count: 1-3 prefixes
    // give the first prefix's offset, 4 the opcode's own, 5 the fifth prefix's, ...). Every
    // reader of `ist` with prefixes (pist_v) re-enters the instruction there: the take at a REP
    // string's take point (NMI, the maskable interrupt, macro service and DMA: f4q_rep1-3,
    // f4q_mix, f4q_nmi, f4q_svc) and the FPO trap (f4q_fpo). Each reader runs before the routine
    // pops an operand (a string; an escape, whose ModR/M byte the dispatch has popped; the I/O
    // trap entered at the dispatch), so the opcode's offset is ip - 1 - hm (hm: the format has
    // a ModR/M byte; fmt_nx, the format loading at this ce_a, as the dispatch pops it) and the
    // count modulo 4 the low two bits of its distance from the first prefix (`pist`). A register
    // beside pist (ce_a): ip - 1 - (hm + k), formed as ip + ~(hm + k) (k the two-bit distance);
    // the select of SR_PC's ist source unchanged (sist where pist was)
    reg [15:0] sist = 16'd0;
    wire [1:0] sist_k = ip[1:0] - 2'd1 - {1'b0, fmt_nx.has_modrm} - pist;
    wire [2:0] sist_d = {1'b0, sist_k} + {2'b00, fmt_nx.has_modrm};
    always_ff @(posedge clock)
        if (ce_a)
            sist <= ip + {13'h1FFF, ~sist_d};
    v35_mul_t  mul = '0;
    v35_div_t  dv = '0;
    // (MX3b) F1: the multiply's / divide's sign latch, loaded by the unit's init word (MULI: the
    // operands' signs differ; DIVI: the dividend's and the divisor's signs differ, the quotient
    // negative); the signed routines' negation paths jump on it (the 8086 / V20 F1 flag)
    reg        f1 = 1'b0;
    reg        rq_v = 1'b0, rq_word = 1'b0, rq_pair = 1'b0, rq_out = 1'b0, rq_rd = 1'b0;
    reg        rq_wr = 1'b0, rq_io = 1'b0, opr_v = 1'b0;
    // (qprobe rule 7) the request's address is on the chip (the page IDB:E00-FFF, or FFFFFh:
    // the internal RAM and the SFRs, the bus unit's on-chip cycle): the RAMEN hold's (below)
    reg        rq_oc = 1'b0;
    // (qprobe rule 11) the request posted while HALT was released: the port's level held low
    // on the clock after the post (the grant a clock later)
    reg        rq_hd = 1'b0;
    reg [1:0]  rq_cyc = RQ_MEMR;
    reg [19:0] rq_addr = 20'd0;
    reg [15:0] rq_off = 16'd0, opr = 16'd0;
    reg [7:0]  plo = 8'h00;
    // (F5b, qprobe round 6) the request's datum: a write's datum is part of its request, taken
    // at the post like its address (`rq_d`: OPRW as the posting word leaves it, the posting
    // word's own load of OPRW included: a store's immediate moved into OPRW on its post word).
    // The words after the post may load OPRW for the next request at once: nothing the EU does
    // after the post reaches the cycle's datum, however long the bus unit holds the request
    // back (a fetch, a refresh, a DMA take, HLDRQ). Before: an I/O write's datum only (`iod`,
    // f5r io: an odd port's pair carried the next PUSH's datum); a memory write's datum was OPRW
    // live until the bus unit's B2 latch, overtaken when the next words loaded OPRW first (CALL
    // far's second push; across a boundary a store followed by PUSH PSW / a store / OUT DW with
    // the write's grant held back)
    reg [15:0] rq_d = 16'd0;

    wire [2:0] bank = psw[14:12];

    // ------------------------------------------------------------ the register selectors
    // {seg 1, lane 2 (0 word, 1 low, 2 high), slot 4}; slot: REG16[i] at 15 - i, the segment
    // s (0 DS1, 1 PS, 2 SS, 3 DS0) at 7 - s
    wire weff = word.wid == WD_WORD ? 1'b1 : (word.wid == WD_FMT ? fmt.w : 1'b0);
    // the multiply's and the divide's width is the format's (their words read AW whole)
    wire mdw = fmt.w;
    function automatic logic [6:0] num(input logic [2:0] r, input logic w);
        num = w ? {1'b0, 2'd0, 4'(4'd15 - {1'b0, r})}
                : {1'b0, r[2] ? 2'd2 : 2'd1, 4'(4'd15 - {2'd0, r[1:0]})};
    endfunction
    function automatic logic [6:0] fix(input logic [2:0] i, input logic w, input logic hi);
        fix = {1'b0, hi ? 2'd2 : (w ? 2'd0 : 2'd1), 4'(4'd15 - {1'b0, i})};
    endfunction
    function automatic logic [6:0] sg(input logic [1:0] s);
        sg = {1'b1, 2'd0, 4'(4'd7 - {2'd0, s})};
    endfunction
    // (MX5b) the register selector as a function of the values it reads (rsel: the current
    // word's; the early read: the next word's, in tick B)
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [6:0] rsel_g(input v35_rsel_e r, input v35_wid_e wd,
                                          input logic [7:0] md, input logic [7:0] o,
                                          input logic fd, input logic we);
        logic hi;
        hi = wd == WD_HIGH;
        case (r)
            RS_REG: rsel_g = num(md[5:3], we);
            RS_RM: rsel_g = num(md[2:0], we);
            RS_OPR: rsel_g = num(o[2:0], we);
            RS_DST: rsel_g = num(fd ? md[5:3] : md[2:0], we);
            RS_SRC: rsel_g = num(fd ? md[2:0] : md[5:3], we);
            RS_AW: rsel_g = fix(3'd0, we, hi);
            RS_CW: rsel_g = fix(3'd1, we, hi);
            RS_DW: rsel_g = fix(3'd2, we, hi);
            RS_BW: rsel_g = fix(3'd3, we, hi);
            RS_SP: rsel_g = fix(3'd4, we, hi);
            RS_BP: rsel_g = fix(3'd5, we, hi);
            RS_IX: rsel_g = fix(3'd6, we, hi);
            RS_IY: rsel_g = fix(3'd7, we, hi);
            RS_SREG: rsel_g = sg(md[4:3]);
            RS_SOPR: rsel_g = sg(o[4:3]);
            RS_PS: rsel_g = sg(2'd1);
            RS_SS: rsel_g = sg(2'd2);
            RS_DS0: rsel_g = sg(2'd3);
            RS_DS1: rsel_g = sg(2'd0);
            RS_BASE: rsel_g = fix((md[2:0] == 3'd2 || md[2:0] == 3'd3 || md[2:0] == 3'd6)
                                ? 3'd5 : md[2:0] == 3'd4 ? 3'd6 : md[2:0] == 3'd5 ? 3'd7
                                : 3'd3, 1'b1, 1'b0);
            RS_INDEX: rsel_g = fix(md[0] ? 3'd7 : 3'd6, 1'b1, 1'b0);
            // (F3b) the bank's save slots: words 1-3 (+02 vector PC, +04 PSW, +06 PC)
            RS_VPC: rsel_g = 7'd1;
            RS_PSWS: rsel_g = 7'd2;
            RS_PCS: rsel_g = 7'd3;
            default: rsel_g = 7'd0;
        endcase
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    function automatic logic [6:0] rsel(input v35_rsel_e r);
        rsel = rsel_g(r, word.wid, modrm, op, fmt.d, weff);
    endfunction

    // ------------------------------------------------------------ tick A: the read addresses
    wire [6:0] sa = rsel(word.ra);
    wire [6:0] sb = rsel(word.rb);
    assign ra_next = {bank, sa[3:0]};
    assign rb_next = {bank, sb[3:0]};
    // (MX5b) the early read: the next word's selectors on the values its fields will read at
    // ce_a. The bank is psw.RB as it stands: no write changes PSW's bits 14:12 (the ALU's flag
    // results and POP PSW's write keep them; `+v35_chk` checks the address against ra_next)
    wire       weff_n = word_nx.wid == WD_WORD ? 1'b1 : (word_nx.wid == WD_FMT ? fmt_nx.w : 1'b0);
    wire [6:0] sa_n = rsel_g(word_nx.ra, word_nx.wid, modrm_nx, op_nx, fmt_nx.d, weff_n);
    wire [6:0] sb_n = rsel_g(word_nx.rb, word_nx.wid, modrm_nx, op_nx, fmt_nx.d, weff_n);
    assign ra_early = {bank, sa_n[3:0]};
    assign rb_early = {bank, sb_n[3:0]};
    // ... registered at ce_a (the lanes of the early data, the address for the forward)
    reg  [1:0] la_e = 2'd0, lb_e = 2'd0;
    reg  [6:0] rae_q = 7'd0, rbe_q = 7'd0;
    // the write landing on ce_a (forwarded into the early read's data)
    reg  [1:0] fw_be = 2'd0;
    reg  [6:0] fw_a = 7'd0;
    reg [15:0] fw_d = 16'd0;
    always_ff @(posedge clock) begin
        if (ce_a) begin
            la_e <= sa_n[5:4];
            lb_e <= sb_n[5:4];
            rae_q <= ra_early;
            rbe_q <= rb_early;
            fw_be <= wa_en ? wa_be : 2'b00;
            fw_a <= wa_addr;
            fw_d <= wa_data;
        end
    end

    // (MX4) the string unit's step: the element's width (the format's), negated with PSW.DIR set,
    // registered at ce_a from the PSW and the format as they stand (both settle before a
    // string routine's first step: the format at the dispatch, DIR by an earlier instruction)
    reg [15:0] stepk = 16'd1;
    always_ff @(posedge clock) begin
        if (ce_a)
            stepk <= psw[V35_PSW_DIR] ? (fmt.w ? 16'hFFFE : 16'hFFFF) : (fmt.w ? 16'd2 : 16'd1);
    end

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg  [1:0] la_b = 2'd0, lb_b = 2'd0;
    reg        ack_b = 1'b0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            la_b <= sa[5:4];
            lb_b <= sb[5:4];
            ack_b <= req_ack;
        end
    end

    // ------------------------------------------------------------ tick B: the sources
    function automatic logic [15:0] lane(input logic [15:0] d, input logic [1:0] l);
        lane = l == 2'd1 ? {8'd0, d[7:0]} : l == 2'd2 ? {8'd0, d[15:8]} : d;
    endfunction
    wire [15:0] va = lane(ra_data, la_b);
    wire [15:0] vb = lane(rb_data, lb_b);
    assign rb_lo = vb[7:0];
    wire [15:0] imm = fmt.immw ? {ih, il} : (fmt.sx ? {{8{il[7]}}, il} : {8'd0, il});
    // the bus datum: latched, or arriving now (an odd word's first byte from its own end)
    wire [15:0] dnow = rq_pair ? {done_data[7:0], plo}
                     : !rq_word ? (rq_addr[0] ? {8'd0, done_data[15:8]} : {8'd0, done_data[7:0]})
                     : done_data;
    wire [15:0] oprv = opr_v ? opr : dnow;
    // (qprobe round 6, timing) the ports' values as arguments: src reads va / vb, srcq (the
    // request's address) the early read's data va_e / vb_e (below, captured at ce_b), each its
    // own mux
    function automatic logic [15:0] src_v(input v35_src_e s, input logic [15:0] pa,
                                          input logic [15:0] pb);
        case (s)
            SR_RA: src_v = pa;
            SR_RB: src_v = pb;
            SR_TA: src_v = ta;
            SR_TB: src_v = tb;
            SR_TC: src_v = tc;
            SR_SIG: src_v = sigma;
            SR_IMM: src_v = imm;
            SR_IMM8: src_v = {8'd0, il};
            SR_OPR: src_v = oprv;
            SR_PSW: src_v = psw;
            // (F2b) a trap routine's vector from the word (vk: the tgt field)
            SR_VEC: src_v = word.vk ? {6'd0, word.tgt[7:0], 2'b00}
                                  : {6'd0, fmt.len != 3'd0 ? il : {5'd0, op3}, 2'b00};
            SR_DISP: src_v = {dh, dl};
            SR_ADDR: src_v = addr;
            SR_ONE: src_v = 16'd1;
            SR_PC: src_v = word.ist ? (pist_v ? sist : ins_ip) : ip;     // (F2b) ist: the instruction's start; (F4q) sist
            default: src_v = 16'd0;
        endcase
    endfunction
    function automatic logic [15:0] src(input v35_src_e s);
        src = src_v(s, va, vb);
    endfunction
    // (MX5) the ALU's operands with the register RAM's data (read at ce_b, the latest source)
    // entering last: the word's choice among the other sources is formed beside the read
    // (`src` of the same field, the RAM ports' values not among them), the two RAM ports
    // select over it: the same value for every field, by construction
    wire [15:0] x_o = src(word.ax == SR_RA || word.ax == SR_RB ? SR_ZERO : word.ax);
    wire [15:0] y_o = src(word.ay == SR_RA || word.ay == SR_RB ? SR_ZERO : word.ay);
`ifndef SYNTHESIS
    // the checker's reference for x_b / y_b (the ce_b read's data entering last); simulation
    // only: synthesised, the reference's cone is not pruned (MX4's landing: +80 FF, -0.17 ns)
    wire [15:0] x_l = word.ax == SR_RA ? va : word.ax == SR_RB ? vb : x_o;
    wire [15:0] y_l = word.alu == AL_STEP ? stepk      // (MX4) the step's y (y_b's load)
                    : word.ay == SR_RA ? va : word.ay == SR_RB ? vb : y_o;
`endif
    // (MX5b) the ALU's operands a tick earlier: the early read's data (tick A) with the ce_a
    // write forwarded byte by byte, the lane, the same choice; captured at ce_b (`x_b`, `y_b`).
    // Every other source is a ce_a register (stable through the clock) and the early read's
    // data is the ce_b read's (the same address, no write between ce_a and ce_b), so x_b is the
    // old x through tick B (`+v35_chk` compares them every clock)
    function automatic logic [15:0] fwd(input logic [15:0] d, input logic [6:0] a);
        fwd = {(fw_be[1] && fw_a == a) ? fw_d[15:8] : d[15:8],
               (fw_be[0] && fw_a == a) ? fw_d[7:0] : d[7:0]};
    endfunction
    wire [15:0] va_e = lane(fwd(ra_data, rae_q), la_e);
    wire [15:0] vb_e = lane(fwd(rb_data, rbe_q), lb_e);
    reg  [15:0] x_b = 16'd0, y_b = 16'd0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            x_b <= word.ax == SR_RA ? va_e : word.ax == SR_RB ? vb_e : x_o;
            // (MX4) AL_STEP's y: the string unit's step (stepk, a register), so the step shares
            // AL_ADD's adder in tick B
            y_b <= word.alu == AL_STEP ? stepk
                 : word.ay == SR_RA ? va_e : word.ay == SR_RB ? vb_e : y_o;
        end
    end
    wire [15:0] x = x_b;
    wire [15:0] y = y_b;
    // (qprobe round 6, timing) the two ports' early data as registers (captured at ce_b with
    // x_b / y_b, the same argument: the early read is the ce_b read's data through tick B) for
    // the request's address alone: the RAM's clock-to-out is not on the path through the
    // segment add to the on-chip compare (rq_oc_nx -> wr_hold_nx -> the registered stall).
    // `+v35_chk` compares the address formed on them with the one formed on va / vb at every
    // post (the only clock the address is read)
    // (consol) and the address itself: the choice below formed in tick A on the early read
    // (va_e / vb_e, as x_b / y_b) and on the other sources (ce_a registers, the bus unit's datum
    // register among them: OPR, an address read from memory), registered at ce_b (`aq_b`): the
    // r6t repair captured the ports' data alone (va_q / vb_q), which left the read datum's lane
    // (`dnow`, from the request's address) and the source mux on the tick-B path to the
    // segment add, the on-chip compare and the registered stall
    function automatic logic [15:0] srcq(input v35_src_e s);
        srcq = src_v(s, va_e, vb_e);
    endfunction
    reg  [15:0] aq_b = 16'd0;
    always_ff @(posedge clock) begin
        if (ce_b)
            aq_b <= word.ea == EA_DISP ? {dh, dl}
                  : word.d1 == MD_ADDR ? srcq(word.s1) : word.d2 == MD_ADDR ? srcq(word.s2) : addr;
    end
    wire [15:0] s1v = src(word.s1);
    wire [15:0] s2v = src(word.s2);
    // (qprobe round 6) OPRW as this word leaves it: the request's datum at a write's post
    logic [15:0] oprw_nx;
    always_comb begin
        oprw_nx = oprw;
        if (ex_b && word.d1 == MD_OPRW)
            oprw_nx = s1v;
        if (ex_b && word.d2 == MD_OPRW)
            oprw_nx = s2v;
    end
    wire [15:0] wsv = src(word.ws);

    // ------------------------------------------------------------ tick B: the ALU
    logic [15:0] r, pn, tc_n, tb_n, bfm;
    logic        scy_n, dtrap_n, tc_w, tb_w, bac_n, bs7_n;
    logic [7:0]  bor_n, bl_n;
    logic [4:0]  bfs;
    logic [9:0]  b10;
    logic [16:0] st;
    logic [31:0] q32;
    v35_mul_t    mul_n;
    v35_div_t    dv_n;
    always_comb begin
        r = sigma;
        pn = psw;
        scy_n = scy;
        bor_n = bor;
        bl_n = bl;
        bac_n = bac;
        bs7_n = bs7;
        b10 = 10'd0;
        dtrap_n = dtrap;
        tc_n = tc;
        tc_w = 1'b0;
        tb_n = tb;
        tb_w = 1'b0;
        // (F2a) the bit field's mask: the width field's w + 1 low bits (tmpa's low four bits)
        bfm = 16'((17'd2 << ta[3:0]) - 17'd1);
        bfs = 5'd0;
        mul_n = mul;
        dv_n = dv;
        st = 17'd0;
        q32 = 32'd0;
        case (word.alu)
            AL_PASS: r = x;
            AL_GRP: r = v35_alu(op3, weff, x, y, psw, pn);
            AL_AND: r = v35_alu(3'd4, weff, x, y, psw, pn);
            AL_INC: begin
                r = v35_alu(3'd0, weff, x, 16'd1, psw, pn);
                pn[V35_PSW_CY] = psw[V35_PSW_CY];
            end
            AL_DEC: begin
                r = v35_alu(3'd5, weff, x, 16'd1, psw, pn);
                pn[V35_PSW_CY] = psw[V35_PSW_CY];
            end
            AL_NOT: r = ~x;
            AL_NEG: r = v35_alu(3'd5, weff, 16'd0, x, psw, pn);
            AL_INC2: r = x + 16'd2;
            AL_DEC2: r = x - 16'd2;
            AL_SEXT: r = {{8{x[7]}}, x[7:0]};
            AL_SIGNW: r = {16{x[15]}};
            AL_SHI: begin
                r = weff ? x : {8'd0, x[7:0]};
                scy_n = psw[V35_PSW_CY];
            end
            AL_SH1: begin
                st = v35_shift1(op3, weff, x, scy);
                r = st[15:0];
                scy_n = st[16];
            end
            AL_SHF: begin
                r = x;
                pn = v35_shift_fl(op3, weff, x, scy, psw);
            end
            AL_MULI: mul_n = v35_mul_init(op3[0], mdw, x, y);
            AL_MULS: mul_n = v35_mul_step(mul);
            AL_MULF: begin
                q32 = v35_mul_fin(mul, mdw, psw, pn);
                r = q32[15:0];
                tc_n = q32[31:16];
                tc_w = 1'b1;
            end
            AL_DIVI: begin
                dv_n = v35_div_init(op3[0], mdw, mdw ? {tc, x} : {16'd0, x}, y);
                dtrap_n = dv_n.trap;
            end
            AL_DIVS: dv_n = v35_div_step(dv);
            AL_DIVF: begin
                q32 = v35_div_fin(dv, psw, pn, dtrap_n);
                r = q32[15:0];
                tc_n = q32[31:16];
                tc_w = 1'b1;
            end
            AL_FLAG: begin
                case (op3)
                    3'd0: pn[V35_PSW_CY] = 1'b0;
                    3'd1: pn[V35_PSW_CY] = 1'b1;
                    3'd2: pn[V35_PSW_CY] = !psw[V35_PSW_CY];
                    3'd3: pn[V35_PSW_IE] = 1'b0;
                    3'd4: pn[V35_PSW_IE] = 1'b1;
                    3'd5: pn[V35_PSW_DIR] = 1'b0;
                    default: pn[V35_PSW_DIR] = 1'b1;
                endcase
            end
            AL_PSWL: pn = {psw[15:8], x[15:8]};
            AL_ADD, AL_STEP: r = x + y;      // (MX4) AL_STEP: y the registered step (y_b's load)
            AL_ADJ: begin
                q32 = v35_adjust(op3[1:0], x, psw);
                r = q32[15:0];
                pn = q32[31:16];
            end
            AL_CVBI: dv_n = v35_div_init(1'b0, 1'b0, {24'd0, x[7:0]}, y);
            AL_CVBF: begin
                r = dv.trap ? {{8{1'b1}}, x[7:0]} : {dv.q[7:0], dv.r[7:0]};
                pn = v35_szp(psw, {8'd0, r[7:0]}, 1'b0);
                pn[V35_PSW_CY] = 1'b0;     // AC kept (F5: silicon)
                pn[V35_PSW_V] = 1'b0;
            end
            // (F5) CVTDB multiplies AH by its immediate (silicon, f5x; the V20 suite's 10)
            AL_CVDI: mul_n = v35_mul_init(1'b0, 1'b0, {8'd0, x[15:8]}, {8'd0, y[7:0]});
            AL_CVDF: begin
                q32 = v35_mul_fin(mul, 1'b0, psw, pn);
                r = {8'd0, 8'(v35_alu(3'd0, 1'b0, {8'd0, q32[7:0]}, {8'd0, x[7:0]}, psw, pn))};
            end
            // (MX3c) the 0F page
            AL_BIT: r = v35_bit1({5'd0, op3[1:0], 1'b0}, x,
                                 weff ? 16'(16'd1 << y[3:0]) : 16'(16'd1 << y[2:0]), weff, psw, pn);
            AL_BCDI: begin
                scy_n = 1'b0;
                bor_n = 8'd0;
                bl_n = 8'd0;
                bac_n = 1'b0;
                bs7_n = 1'b0;
            end
            AL_BCDS: begin
                b10 = v35_bcd8(op3 != 3'd0, x[7:0], y[7:0], scy);
                r = {8'd0, b10[7:0]};
                scy_n = b10[9];
                bor_n = bor | b10[7:0];
                bl_n = b10[7:0];
                bac_n = b10[8];
                bs7_n = v35_bcd8_s7(op3 != 3'd0, x[7:0], y[7:0], scy);
            end
            AL_BCDF: begin
                pn[V35_PSW_CY] = scy;
                pn[V35_PSW_Z] = bor == 8'd0;
                pn[V35_PSW_V] = op3 != 3'd0 ? bs7 && !bl[7] : !bs7 && bl[7];
                pn[V35_PSW_S] = bl[7];
                pn[V35_PSW_AC] = bac;
                pn[V35_PSW_P] = ~^bl;
            end
            AL_R4: begin
                q32 = {16'd0, v35_rot4(op3[0], x[7:0], y[7:0])};
                r = {8'd0, q32[7:0]};
                tc_n = {8'd0, q32[15:8]};
                tc_w = 1'b1;
            end
            // (F2a) the bit fields: the pair {tmpc, tmpb} rotated by one (SIGMA kept), the
            // field merged into or masked out of tmpb, the crossing test with the flags, the
            // offset's step
            AL_BFR: begin
                tb_n = {tc[0], tb[15:1]};
                tc_n = {tb[0], tc[15:1]};
                tb_w = 1'b1;
                tc_w = 1'b1;
            end
            AL_BFL: begin
                tb_n = {tb[14:0], tc[15]};
                tc_n = {tc[14:0], tb[15]};
                tb_w = 1'b1;
                tc_w = 1'b1;
            end
            AL_BFI: begin
                tb_n = (tb & ~bfm) | (x & bfm);
                tb_w = 1'b1;
            end
            AL_BFM: begin
                tb_n = tb & bfm;
                tb_w = 1'b1;
            end
            AL_BFK: begin
                q32[15:0] = v35_alu(3'd5, 1'b0, 16'd15, x, psw, pn);
                r = 16'd15 - x;
            end
            AL_BFU: begin
                bfs = {1'b0, x[3:0]} + {1'b0, y[3:0]} + 5'd1;
                r = {bfs[4], 11'd0, bfs[3:0]};
            end
            AL_CITF: begin
                pn[V35_PSW_IE] = 1'b0;
                pn[8] = 1'b0;               // BRK (the single-step flag)
                pn[15] = ns;                // (F3b) MD <- N/S on every interrupt (the data book)
            end
            // (F3b) BRKN / BRKS: CITF with MD set / cleared (f3_brkn, f3_brks: BRKS's handler
            // runs with MD 0, the NMI taken in it with MD 1 again: N/S high)
            AL_CITN, AL_CITS: begin
                pn[V35_PSW_IE] = 1'b0;
                pn[8] = 1'b0;
                pn[15] = word.alu == AL_CITN;
            end
            // (F3b) the bank switch's PSW: RB <- x[2:0], IE and BRK cleared, MD <- N/S, the rest
            // kept (f3_bins brkcs_aw: FECF -> BCCF; f3_bsw intp0_bank3: F246 -> B046)
            AL_BSW: pn = {ns, x[2:0], psw[11:10], 2'b00, psw[7:0]};
            AL_RBR: pn = {psw[15], x[2:0], psw[11:0]};          // (F3b) TSKSW / MOVSPB
            AL_RBP: pn = {psw[15], x[14:12], psw[11:0]};        // (F3b) MOVSPA (x: the PSW save)
            AL_VEC4: r = {6'd0, x[7:0], 2'b00};                 // (F3b) the INT vector's address
            // (F2b) the I/O trap's PSW: IE and BRK cleared, BRKI set (f2_iot: the handler's PSW)
            AL_CITB: begin
                pn[V35_PSW_IE] = 1'b0;
                pn[8] = 1'b0;
                pn[1] = 1'b1;
                pn[15] = ns;                // (F3b) MD <- N/S
            end
            AL_LTS: r = {$signed(x) < $signed(y), 15'd0};      // (F2b) CHKIND's compares
            AL_SFRA: r = 16'h0F00 | {8'd0, x[7:0]};             // (F2b) BTCLR's SFR offset (F00h + x)
            AL_BTM: r = 16'(16'd1 << x[10:8]);                  // (F2b) BTCLR's bit (DH)
            AL_BTC: r = x & ~y;                                 // (F2b) BTCLR's clear
            AL_P14: r = {p14, 15'd0};                           // (F2b) POLL's test
            // (F3) 4 x the vector taken; (F3b) a bank-switch take: {1, the level}; INT: 0
            // (F4b) a macro-service take: FFFFh (negative: bank.uasm's bsw_q tells it from a
            // bank switch's 800xh)
            // (F4c) a DMA take: FFFEh (bsw_q sends it to urom/dma.uasm)
            AL_IVEC: r = tk_dm ? 16'hFFFE : tk_ms ? 16'hFFFF : tk_int ? 16'd0
                       : tk_bs ? {13'h1000, tk_l}
                       : {9'd0, tk_vec, 2'b00};
            // (F4b) macro service (urom/ms.uasm)
            AL_MSCA: r = {10'b0000_1110_00, ms_ch, 3'd0};
            // (F4c) with a DMA take: SFRH SARH's segment (x & FF00h, the block's {SARH, DARH}
            // word), MSEQ DARH's ({x[7:0], 00h}), MSMD the kind {I/O to memory, 0, memory to
            // I/O}, MSDR {W, 0}, MSDC TC - 1 (16 bits), DMS the address step (y 0 SAR by PS,
            // 1 DAR by PD)
            AL_SFRH: r = tk_dm ? x & 16'hFF00 : 16'h0F00 | {8'd0, x[15:8]};
            AL_MSMD: r = tk_dm ? {dm_in, 14'd0, dm_out} : {15'd0, ms_mode == 3'b001};
            AL_MSDR: r = {tk_dm ? dm_w : ms_dir, 15'd0};
            AL_MSEQ: r = tk_dm ? {x[7:0], 8'h00} : x;
            AL_MSDC: r = tk_dm ? x - 16'd1 : ({8'd0, x[7:0]} - 16'd1) & 16'h00FF;
            AL_DMS: r = y[0] ? dstep(x, dm_pd, dm_w) : dstep(x, dm_ps, dm_w);
            AL_MSPC: r = x - {15'd0, ms_hlt};
            default: ;
        endcase
    end

    // ------------------------------------------------------------ tick B: the EA step, the moves
    wire [15:0] ea_off;
    wire        ea_bp;
    v35_ea ea (.step(word.ea), .modrm, .base(va), .index(vb), .disp({dh, dl}), .off(ea_off),
               .bp(ea_bp));
    wire [15:0] addr_n = word.ea != EA_NONE ? ea_off
                       : word.d1 == MD_ADDR ? s1v : word.d2 == MD_ADDR ? s2v : addr;
    wire        ea_ss_n = word.ea != EA_NONE ? ea_bp : ea_ss;
    // (MX1) the request's address: the address register as a posting word leaves it, but never
    // through the EA's add (the assembler rejects a word with ea=BI that posts: the add's
    // 3-input sum ends in the address register, the request reads it a word later; README
    // "MX1", depth); the direct form's displacement (ea=DISP) is a register
    // (qprobe round 6, timing; consol) the address registered at ce_b (aq_b, above): the same value
    wire [15:0] addr_q = aq_b;
    wire        ea_ss_q = word.ea == EA_NONE && ea_ss;

    // ------------------------------------------------------------ tick B: the write port
    wire [6:0]  sw = rsel(word.wr);
    wire        w_ram = ex_b && word.wr != RS_NONE && word.wr != RS_PSW && word.wr != RS_PSWA;
    assign wa_en = w_ram;
    assign wa_addr = {bank, sw[3:0]};
    assign wa_be = sw[5:4] == 2'd0 ? 2'b11 : sw[5:4] == 2'd2 ? 2'b10 : 2'b01;
    assign wa_data = sw[5:4] == 2'd0 ? wsv : {wsv[7:0], wsv[7:0]};

    // ------------------------------------------------------------ tick B: the request
    wire        post = ex_b && word.bus != BQ_NONE;
    wire        b_io = word.bus == BQ_IOR || word.bus == BQ_IOW || word.bus == BQ_INTA;
    wire        b_rd = word.bus == BQ_MEMR || word.bus == BQ_IOR || word.bus == BQ_INTA;
    wire        b_mw = word.bus == BQ_MEMW || word.bus == BQ_MEMWD;
    // (A2) the current word loads OPRW (K for an unarmed write), and the next word's (tick B)
    wire        k_cur = word.d1 == MD_OPRW || word.d2 == MD_OPRW;
    wire        k_nx = word_nx.d1 == MD_OPRW || word_nx.d2 == MD_OPRW;
    wire [15:0] segv = word.seg == SG_ZERO ? 16'd0 : word.seg == SG_IDB ? {idb, 8'h00}
                     : word.seg == SG_TA ? ta
                     : word.seg == SG_SS ? ss : word.seg == SG_DS1 ? ds1
                     : pfx_v ? (pfx_s == 2'd0 ? ds1 : pfx_s == 2'd1 ? ps : pfx_s == 2'd2 ? ss
                                : ds0)
                     : (ea_ss_q && word.seg != SG_DSP) ? ss : ds0;
    wire [19:0] lin = {segv, 4'd0} + {4'd0, addr_q};
    wire [15:0] off2 = rq_off + 16'd1;
    // (F5d) a memory word's second half is the first's linear address + 1 (the offset is not
    // wrapped in the segment: silicon, f5i's words at offset FFFFh write their high byte at
    // 16 x seg + 10000h, the megabyte wrapping, not at 16 x seg + 0000h)
    wire [19:0] lin2 = rq_addr + 20'd1;

    // ------------------------------------------------------------ the port
    assign req_v = rq_v && !rq_hd && !(rq_un && !k_cur);
    assign req_cyc = rq_cyc;
    assign req_ia = rq_ia || rq_un;      // (A2) on a write: the datum is loaded by the current word
    assign req_dk = rq_dk;
    assign req_addr = rq_addr;
    assign req_width = rq_word;
    assign req_data = rq_word ? rq_d : {rq_d[7:0], rq_d[7:0]};
    // (MX2) F after a memory write (the last request a write): the RAMEN hold (mechanisms 3.3:
    // the EU holds until the write cycle ends, the write may land in the register RAM) placed on
    // that word, not only on E; a read's F waits for its datum. (Step D) Kept: without it a
    // store into a register bank is read stale by the next words (banks f3_bins: RETRBI's read
    // of the PSW save the MOV before it stored, README "Step D")
    // (qprobe rule 7 fix) F's wait on a memory write is the write's own (`wr_run`: until the
    // clock after its end, any memory write, RAMEN or not, on the chip or off it), as a read's F
    // waits for its datum: F is the routine's wait for its request's cycle. Not the RAMEN hold,
    // which rule 7 narrowed to the on-chip store and to E. (Found as CALL far's runaway: with F
    // free on an external write the second push's PC load overtook the first push's datum, then
    // OPRW live until B2; the datum is now the request's own, `rq_d`, so that is no longer what
    // F protects: F35 / F40's far call / return timing is what it keeps)
    wire        wr_run = rq_out && rq_wr && !rq_io && !req_done;
    assign opr_rdy = rq_wr ? !wr_run : (opr_v || (req_done && rq_out && rq_rd));
    // (MX1) the slot frees on the cycle's end (req_done): a post on that clock stands from the
    // next, the book check's machine (uasm.length: a post waits for the last request's end)
    assign rq_busy = rq_v || (rq_out && !req_done);
    // (qprobe rule 7) the hold is the on-chip store's only: an external write is waited for
    // by the boundary alone (the sequencer's: the dispatch until the cycle's last clock), not
    // here; a store into the on-chip page (the register banks are the internal RAM) still
    // holds E and an F word until the clock after its end (its datum lands a clock later)
    wire        oc_hit = (lin[19:12] == idb && lin[11:9] == 3'b111) || lin == 20'hFFFFF;
    assign wr_hold = rq_out && rq_wr && !rq_io && ramen && rq_oc && !req_done;
    // (MX5c) the same three on the request registers' next values (the ce_a block below)
    wire        rq_v_nx = post ? 1'b1 : ack_b ? 1'b0 : rq_v;
    // (qprobe round 16, timing) the port level's next value reads the unarmed state without the
    // on-chip compare: the segment add and the compare (oc_hit, on the post's linear address)
    // were on the path into the sequencer's execute register (ex, through b_ph_nx). A MEMWD
    // write is posted on the word before K (k_nx), where the term is 0 either way: the same
    // value on every clock (`+v35_chk`: a MEMWD post with the next word not K is reported)
    wire        rq_unv_nx = post ? (word.bus == BQ_MEMWD) : (ex_b && k_cur) ? 1'b0 : rq_un;
    assign req_v_nx = rq_v_nx && !(post && hp_b) && !(rq_unv_nx && !k_nx);
    wire        rq_oc_nx = post ? (oc_hit && !b_io) : rq_oc;
    wire        rq_out_nx = post ? 1'b1 : (req_done && rq_out) ? 1'b0 : rq_out;
    wire        rq_rd_nx = post ? b_rd : rq_rd;
    wire        rq_wr_nx = post ? (b_mw || word.bus == BQ_IOW) : rq_wr;
    wire        rq_io_nx = post ? b_io : rq_io;
    assign rqm_nx = rq_v_nx && !rq_io_nx;
    wire        opr_v_nx = (ex_b && word.f) ? 1'b0 : (req_done && rq_out && rq_rd) ? 1'b1 : opr_v;
    assign wr_hold_nx = rq_out_nx && rq_wr_nx && !rq_io_nx && ramen_nx && rq_oc_nx && !req_done_nx;
    wire        wr_run_nx = rq_out_nx && rq_wr_nx && !rq_io_nx && !req_done_nx;
    assign opr_rdy_nx = rq_wr_nx ? !wr_run_nx
                      : (opr_v_nx || (req_done_nx && rq_out_nx && rq_rd_nx));
    assign rq_busy_nx = rq_v_nx || (rq_out_nx && !req_done_nx);
    assign c_sgn = sigma[15];
    assign sig_lo = sigma[3:0];
    assign c_dtrap = dtrap;
    // (MX2) the flush's target: SIGMA (the V20 ROM's SIGMA -> PC on its FLUSH word), in PS
    assign flush_off = sigma;
    // (MX2) the transfer's condition by the format's xc: the PSW's sixteen (the encoding's low
    // nibble: V, CY, Z, CY or Z, S, P, S xor V, (S xor V) or Z, each and its negation), the
    // loop forms' counter test on SIGMA (CW - 1 not zero, or CW zero for BCWZ)
    logic xcv;
    always_comb begin
        case (fmt.xc[3:1])
            3'd0: xcv = psw[V35_PSW_V];
            3'd1: xcv = psw[V35_PSW_CY];
            3'd2: xcv = psw[V35_PSW_Z];
            3'd3: xcv = psw[V35_PSW_CY] || psw[V35_PSW_Z];
            3'd4: xcv = psw[V35_PSW_S];
            3'd5: xcv = psw[V35_PSW_P];
            3'd6: xcv = psw[V35_PSW_S] ^ psw[V35_PSW_V];
            default: xcv = (psw[V35_PSW_S] ^ psw[V35_PSW_V]) || psw[V35_PSW_Z];
        endcase
    end
    wire       sz = sigma == 16'd0;
    assign c_xc = !fmt.xc[4] ? (xcv ^ fmt.xc[0]) : (sz ^ !fmt.xc[0]);
    assign c_snz = !sz;
    assign c_f1 = f1;
    assign c_dn = dv.nneg;
    assign ps_base = {ps, 4'd0};

    // ------------------------------------------------------------ the end of the clock (ce_a)
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            psw <= {ns, 15'h7002};      // (F3b) MD from N/S at reset (the data book)
            ds1 <= 16'd0;
            ps <= 16'hFFFF;
            ss <= 16'd0;
            ds0 <= 16'd0;
            pfx_v <= 1'b0;
            pfx_s <= 2'd0;
            pist_v <= 1'b0;
            rq_v <= 1'b0;
            rq_un <= 1'b0;
            rq_out <= 1'b0;
            rq_rd <= 1'b0;
            rq_oc <= 1'b0;
            rq_hd <= 1'b0;
            rq_wr <= 1'b0;
            rq_io <= 1'b0;
            opr_v <= 1'b0;
            dtrap <= 1'b0;
            f1 <= 1'b0;
            ms_end <= 1'b0;
            ms_eq <= 1'b0;
            dm_tend <= 1'b0;
            dm_tlast <= 1'b0;
            dm_last <= 1'b0;
            scy <= 1'b0;
            bor <= 8'd0;
            bl <= 8'd0;
            bac <= 1'b0;
            bs7 <= 1'b0;
            ea_ss <= 1'b0;
        end else if (ce_a) begin
            // (F4b) macro service: the character search's match (MSEQ), the end (MSDC: the count
            // reaches 0, or the match)
            if (ex_b && word.alu == AL_MSEQ)
                ms_eq <= !tk_dm && ms_mode == 3'b100 && x[7:0] == y[7:0];
            ms_end <= ex_b && word.alu == AL_MSDC && !tk_dm
                      && ({8'd0, x[7:0]} == 16'd1 || ms_eq);
            // (F4c) DMA: the TC update and its end; the last transfer (to the next MSDC)
            dm_tend <= ex_b && word.alu == AL_MSDC && tk_dm;
            dm_tlast <= x == 16'd1;
            if (ex_b && word.alu == AL_MSDC && tk_dm)
                dm_last <= x == 16'd1;
            // (F1) an on-chip write to a segment's slot (before the word's own writes: a
            // register write on the same clock is later in the program and wins)
            if (oc_seg_we) begin    // (step B: v35_top's decode before, the same terms)
                case (oc_seg_s)
                    2'd0: ds1 <= seg_merge(ds1);
                    2'd2: ss <= seg_merge(ss);
                    2'd3: ds0 <= seg_merge(ds0);
                    default: ;
                endcase
            end
            if (ex_b) begin
                sigma <= r;
                if (word.wf)
                    psw <= pn;
                scy <= scy_n;
                bor <= bor_n;
                bl <= bl_n;
                bac <= bac_n;
                bs7 <= bs7_n;
                dtrap <= dtrap_n;
                mul <= mul_n;
                dv <= dv_n;
                if (word.alu == AL_MULI)
                    f1 <= mul_n.neg;
                else if (word.alu == AL_DIVI)
                    f1 <= dv_n.nneg ^ dv_n.dneg;
                if (tc_w)
                    tc <= tc_n;
                if (tb_w)
                    tb <= tb_n;
                case (word.d1)
                    MD_TA: ta <= s1v;
                    MD_TB: tb <= s1v;
                    MD_TC: tc <= s1v;
                    MD_OPRW: oprw <= s1v;
                    default: ;
                endcase
                case (word.d2)
                    MD_TA: ta <= s2v;
                    MD_TB: tb <= s2v;
                    MD_TC: tc <= s2v;
                    MD_OPRW: oprw <= s2v;
                    default: ;
                endcase
                addr <= addr_n;
                ea_ss <= ea_ss_n;
                // the write port's segment flops and the PSW
                if (word.wr == RS_PSW)
                    psw <= {psw[15:12], wsv[11:0]};
                else if (word.wr == RS_PSWA)
                    psw <= wsv;
                else if (w_ram && sw[6]) begin
                    case (sw[3:0])
                        4'd7: ds1 <= wsv;
                        4'd6: ps <= wsv;
                        4'd5: ss <= wsv;
                        default: ds0 <= wsv;
                    endcase
                end
                // the segment prefix: set by a prefix, cleared by the next instruction's E.
                // (F5b) `pfx` on another prefix's E word (BUSLOCK, a REP before a non-string
                // opcode) keeps it: silicon's segment override reaches the opcode through them
                // (f5a_000: PS: REP SUBC [430Ah] at PS:430Ah)
                // (F5d) an E word with ea=REP (a REP-page prefix cell: REP seg / REP BUSLOCK, the
                // string after it repeated, f5r repsegstr) keeps both too; with `pfx` its segment
                // is the cell's byte's (the ModR/M register: 26 2E 36 3E, bits 4:3 = DS1 PS SS
                // DS0, pfx_s's order)
                if (word.e) begin
                    pist_v <= word.pfx || word.ea == EA_REP;
                    // (F5e) REP BUSLOCK (rep_lk: ea=REP without pfx) loads it too: the REP's
                    // offset (f5_repint ri_replock: an interrupt inside the string pushed a
                    // stale start)
                    if ((word.pfx || word.ea == EA_REP) && !pist_v)
                        pist <= ins_ip[1:0];
                end
                if (word.pfx) begin
                    if (word.ea == EA_REP) begin
                        pfx_v <= 1'b1;
                        pfx_s <= modrm[4:3];
                    end else if (fmt.seg[2]) begin
                        pfx_v <= 1'b1;
                        pfx_s <= fmt.seg[1:0];
                    end
                end else if (word.e && !fmt.seg[2] && word.ea != EA_REP)
                    pfx_v <= 1'b0;
            end
            // the request
            rq_oc <= rq_oc_nx;
            rq_hd <= post && hp_b;
            if (post) begin
                rq_v <= 1'b1;
                rq_cyc <= word.bus == BQ_MEMR ? RQ_MEMR : b_mw ? RQ_MEMW
                        : (word.bus == BQ_IOR || word.bus == BQ_INTA) ? RQ_IOR : RQ_IOW;
                rq_word <= weff;
                // (F5b) a word at an odd I/O port is the pair too (silicon, f5r io / strio: the
                // port on the high lane, then port + 1 on the low)
                rq_pair <= weff && (b_io ? addr_q[0] : lin[0]);
                rq_addr <= b_io ? {4'd0, addr_q} : lin;
                rq_off <= addr_q;
                rq_out <= 1'b1;
                rq_rd <= b_rd;
                rq_ia <= word.bus == BQ_INTA;
                // (F4c) a DMA transfer's cycle: the routine's cycles at tmpa's segment, the
                // write, or the read of a memory-to-I/O transfer (the memory-to-memory read is
                // not one: no DMAAK, no TC)
                rq_dk <= tk_dm && word.seg == SG_TA && (b_mw || dm_out);
                rq_wr <= b_mw || word.bus == BQ_IOW;
                rq_io <= b_io;
                if (word.bus == BQ_IOW || b_mw)
                    rq_d <= oprw_nx;
                rq_un <= word.bus == BQ_MEMWD && !oc_hit;     // (an on-chip store: armed, its E held: RAMEN)
            end else begin
                // (A2) K: the deferred datum loaded, the write armed
                if (rq_un && ex_b && k_cur) begin
                    rq_d <= oprw_nx;
                    rq_un <= 1'b0;
                end
                if (ack_b) begin
                    rq_v <= 1'b0;
                    if (rq_pair)
                        rq_addr <= rq_io ? {4'd0, off2} : lin2;
                end
                if (req_done && rq_out)
                    rq_out <= 1'b0;
                else if (eu_dlv && rq_out && rq_pair)
                    plo <= done_data[15:8];
            end
            // (MX1) a read's datum latched at its end, also when the clock posts the next
            // request (the slot is free on the end's clock: rq_busy)
            if (req_done && rq_out && rq_rd) begin
                opr <= dnow;
                opr_v <= 1'b1;
            end
            if (ex_b && word.f)
                opr_v <= 1'b0;
            // (F1) a FLAG store: PSW bits 5 and 3 (after the word's PSW write: the store's
            // cycle ended on this clock)
            if (flag_we) begin
                psw[5] <= flag_d[1];
                psw[3] <= flag_d[0];
            end
        end
    end
    function automatic logic [15:0] seg_merge(input logic [15:0] old);
        seg_merge = {oc_be[1] ? oc_wd[15:8] : old[15:8],
                     oc_be[0] ? oc_wd[7:0] : old[7:0]};
    endfunction
    assign psw_f = {psw[5], psw[3]};
    assign psw_brki = psw[1];
    assign psw_ie = psw[V35_PSW_IE];
    assign psw_brk = psw[8];

    wire unused = &{1'b0, sa[6], sb[6], word_nx, fmt_nx, sa_n[6], sb_n[6], dh, fmt, mul_n.acc[16], q32[31:16], word, op};

`ifndef SYNTHESIS
    // the divide error raised (a strobe at the word's end): the function bench's o_div_trap
    // (fpga/v35s/v35_core2_tb.sv reads eu.trap_o; no port carries it)
    reg        trap_o = 1'b0;
    always_ff @(posedge clock) begin
        if (!reset_n)
            trap_o <= 1'b0;
        else if (ce_a)
            trap_o <= ex_b && word.seq == SQ_TRAP;     // (qprobe round 12) the word's TRAP
    end
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (x_b !== x_l || y_b !== y_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: eu: the early operands differ at %0t", $time);
            end
            // (qprobe round 6, timing) the request's address on the early data against va / vb
            if (post && addr_q !== (word.ea == EA_DISP ? {dh, dl}
                                    : word.d1 == MD_ADDR ? s1v : word.d2 == MD_ADDR ? s2v : addr)) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: eu: the request's address on the early data differs at %0t", $time);
            end
            if (la_b !== sa[5:4] || lb_b !== sb[5:4] || ack_b !== req_ack) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: eu: a tick A source changed in tick B at %0t", $time);
            end
        end
    end
    // (qprobe round 12, A2) an unarmed write is granted only on the clock its datum is loaded
    // (K executes): never on the pins before its datum; (qprobe round 16) a MEMWD post is on the
    // word before K (req_v_nx's unarmed term above reads it so)
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a && post && word.bus == BQ_MEMWD && !k_nx) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: eu: a MEMWD post not followed by K at %0t", $time);
        end
        if (chk_on && reset_n && ce_a && ack_b && rq_un && !(ex_b && k_cur)) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: eu: an unarmed write granted before its datum at %0t", $time);
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: eu: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
endmodule
