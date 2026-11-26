`timescale 1ns/1ps

// V35S special function registers: the SFR page IDB:F00-FFF (and IDB at FFFFF) as data, from
// the F1 measurements on the socket (validation/v35s/onchip.py; receipts
// validation/v35s/receipts/f1-f1_sfr_*-socket*.json; README "F1").
//
// Written by the core's on-chip store (`wr`: (WO31) in the internal cycle's first clock, a
// timer register's as its wait ends; no pins; the address, width and datum as issued). (WO31)
// Every store is one byte at its own offset (an odd address the high lane): a word in the page
// is two byte cycles, low address first (silicon, f4_oc_v), each carrying the word bit (width
// BW_WORD at the byte's own address) and the request's whole datum; the 16-bit registers (TM0,
// MD0, TM1, MD1) take the word whole at its high byte's cycle, a lone byte store ignored.
// Read by the on-chip read: `rd_off` (the cycle's offset: (step C) the access port's address,
// the bus unit's register, captured at the cycle's start) -> `rd_data` registered at `ce_rd`,
// {the byte at offset | 1, the byte at offset & ~1}; the 16-bit registers (TM0, MD0, TM1, MD1)
// by word whole.
//
// What each offset is (measured; README "F1" has the table):
//   storage   the bits the four patterns (00 FF 55 AA) and the every-value sweep wrote, with the
//             bits that read fixed 1 (the priority fields PR2-0 of SRIC / STIC / TMIC1/2 / DIC1 /
//             TBIC / EXIC1/2) and the measured reset values. Storage only (their function is a
//             later stage's): PMT, INTM, EMS0-2, EXIC0-2, SRMS / STMS / SCM / SCC / BRG / SEIC /
//             SRIC / STIC 0 and 1, TM0 / MD0 / TM1 / MD1, TMC0/1, TMMS0-2, TMIC0-2, DMAC0/1,
//             DMAM0/1, DIC0/1, TBIC, the port latches P0-P2, PM0-2, PMC0-2, TxB0/1. Built with
//             function: PRC, WTC, RFM (as before), IDB, FLAG (the EU's PSW bits 5 and 3).
//   SCM0/1    bit 3 reads written bit 3 and bit 0 (the every-value sweep)
//   16-bit    TM0 MD0 TM1 MD1: a byte write is ignored; a byte read of the low offset reads the
//             low byte; of the high offset the bus residue
//   pins      P0, P2, PT read 00h (the harness holds them low), P1 the NMI / INTP / INT levels
//             and READY high (input mode: the latch is not read back)
//   (F4b)     SCM / SCC / BRG stay storage, read by the serial channels (v35_serial, below);
//             RxB0/1 and SCE0/1 are the channels' (RxB kept through reset, as silicon's); the
//             MS registers are read by the controller at a macro-service take
//   constant  STBC 00h (writes ignored: STOP / HALT are F4's), ISPR 00h, FF0/FF1 00h, FF4 02h,
//             FF7 C7h, FF8 4Eh,
//             FF9 00h (FF7-FF9 change on silicon: hidden live registers, not built), and every
//             undocumented offset with address bit 2 set F7h (but FF5, FF6, FFD, FFE: residue)
//   residue   the write-only SFRs and the undocumented offsets with bit 2 clear: silicon returns
//             the internal bus's last byte (the code stream's). Not built: the low lane reads
//             00h, the high lane the low lane's byte (a word read of an 8-bit SFR is two byte
//             reads on silicon: P1 by word reads 8F8Fh)
module v35_sfr (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        wr,              // an SFR store's cycle ends ...
    input  wire        wr_pend,         // (work order 37) a store captured, landing at the coming ce_a
    input  wire [19:0] addr,            // ... its address (IDB:Fxx or FFFFF), width (V35_BW_*), datum
    input  wire [1:0]  width,
    input  wire [15:0] data,
    output reg  [7:0]  prc,
    output reg  [15:0] wtc,
    output reg  [7:0]  rfm,
    output reg  [7:0]  idb,
    // (F1) the on-chip read (the offset and width: the access port's addr / width, below)
    input  wire        ce_rd,
    output reg  [15:0] rd_data,
    input  wire        rd_go,           // (F4b) an SFR read cycle of rd_off (a ce_a strobe)
    input  wire [1:0]  psw_f,           // the EU's PSW {F1 (bit 5), F0 (bit 3)}
    input  wire [15:0] input_levels,
    output wire        flag_we,         // a FLAG store at this write: PSW bits 5 and 3 <- flag_d
    output wire [1:0]  flag_d,
    output reg         poll_p14,        // (F2b) the P14 pin as POLL reads it: the INT level while
                                        //   PM1 bit 4 makes P14 an input, else low (registered)
    output reg         int_on,          // (F3b) the INT request: the INT level while PMC1 bit 4
                                        //   selects P14's INT function (registered)
    // (F3) the interrupt controller (v35_intc, below): the IC registers' stored bytes and INTM
    // (MK, MS / INT, ENCS, PR; the edges), the stores that write an IC register (its IF bit), and
    // the IF bits and ISPR the controller owns, read back here
    output wire [8*15-1:0] ic_b,        // the 15 IC registers' bytes (v35_intc's order), storage
    output wire [7:0]  intm,
    output wire [8*15-1:0] ms_b,        // (F4b) the macro-service registers (v35_intc's order)
    input  wire [14:0] ms_clr,          // (F4b) a macro service's end: the IC register's MS cleared
    output wire [14:0] ic_we,           // a store writes IC register i now (with `wr`) ...
    output wire [14:0] ic_wd,           // ... its bit 7 (IF)
    input  wire [14:0] ic_if,
    input  wire [7:0]  ispr,
    // (F4) the peripherals: the CPU clock (the timers', the time base's), the port pins the board
    // drives ({P2, P1, P0}), /INTAK (P13's level while PMC1 bit 3 selects it), the output pin
    // vector (the harness's order), the IF bits the peripherals raise (v35_intc's order)
    input  wire        ce_a,
    input  wire [23:0] pins_in,
    input  wire        intak_n,
    output reg  [31:0] pins,
    output wire [14:0] pf_set,
    output wire [14:0] pf_pre,          // (WO50, P8) the timers' count-outs as they are made (pf_set's TMIC bits a clock ahead)
    // (F4c) DMA (v35_dma, below): the take and the routine's TC update (v35_intc / the EU), the
    // request and the take's descriptor (registers), the bus unit's DMA cycle on the pins (`dk`:
    // DMAAK's window, `dkt`: TC's, inside it)
    input  wire        dm_take,
    input  wire        dm_tend,
    input  wire        dm_tlast,
    input  wire        dm_rs,           // a start that is not a DMA take (DIC's IF is set there)
    input  wire        dm_smp,          // (F4p) a start or a string's take point that is not a DMA take
    input  wire        dm_last,         // the transfer in flight is the last (the EU's register)
    input  wire        dk,
    input  wire        dkt,
    output wire        dm_v,
    output wire        dm_go,
    output wire        dm_ch,
    output wire        dm_in,
    output wire        dm_out,
    output wire        dm_w,
    output wire [1:0]  dm_ps,
    output wire [1:0]  dm_pd,
    // (F4d) bus hold and READY (v35_bus): HLDRQ's level while PMC2 bit 7 selects P27's function
    // (a register), /HLDAK (the bus unit's register: P26 by PMC2 bit 6), PMC1 bit 7 (P17 as
    // READY) and READY's level (the pin's second flop)
    output reg         hrq,
    input  wire        hlda_n,
    output wire        rdy_en,
    output wire        rdy_lv
);
    localparam logic [7:0] PRC_RESET = 8'h4E;
    localparam logic [15:0] WTC_RESET = 16'hFFFF;
    localparam logic [7:0] RFM_RESET = 8'hFC;
    localparam logic [7:0] IDB_RESET = 8'hFF;
    localparam logic [1:0] BW_WORD = 2'd0, BW_HI = 2'd2;   // as v35/v35_front_pkg.sv (BW_LO 1)
    // (F1) the on-chip read's offset and word bit: (step C) the access port's address and width
    // (the bus unit's registers, captured at the cycle's start; its oc_off / oc_word before,
    // the same values at every clock)
    wire [7:0] rd_off = addr[7:0];
    wire       rd_word = width == BW_WORD;

    // ---- the offsets (measured) -------------------------------------------------------------
    localparam logic [2:0] K_ST = 3'd0, K_C = 3'd1, K_PIN = 3'd2, K_RES = 3'd3, K_W16 = 3'd4,
                           K_FLAG = 3'd5, K_IDB = 3'd6, K_ISPR = 3'd7;
    function automatic logic [2:0] kind(input logic [7:0] o);
        case (o)
            8'h3B, 8'h40, 8'h44, 8'h45, 8'h46, 8'h4C, 8'h4D, 8'h4E, 8'h65, 8'h66, 8'h68, 8'h69,
            8'h6A, 8'h6C, 8'h6D, 8'h6E, 8'h75, 8'h76, 8'h78, 8'h79, 8'h7A, 8'h7C, 8'h7D, 8'h7E,
            8'h90, 8'h91, 8'h94, 8'h95, 8'h96, 8'h9C, 8'h9D, 8'h9E, 8'hA0, 8'hA1, 8'hA2, 8'hA3,
            8'hAC, 8'hAD, 8'hE1, 8'hE8, 8'hE9, 8'hEB, 8'hEC: kind = K_ST;
            8'h80, 8'h81, 8'h82, 8'h83, 8'h88, 8'h89, 8'h8A, 8'h8B: kind = K_W16;
            8'h00, 8'h08, 8'h10, 8'h38: kind = K_PIN;
            8'hEA: kind = K_FLAG;
            8'hFF: kind = K_IDB;
            8'h01, 8'h02, 8'h09, 8'h0A, 8'h11, 8'h12, 8'h62, 8'h72, 8'hF5, 8'hF6, 8'hFD,
            8'hFE: kind = K_RES;
            8'h60, 8'h70, 8'h6B, 8'h7B, 8'hE0, 8'hF0, 8'hF1, 8'hF4, 8'hF7, 8'hF8,
            8'hF9: kind = K_C;
            8'hFC: kind = K_ISPR;       // (F3) the controller's ISPR
            default: kind = o[2] ? K_C : K_RES;
        endcase
    endfunction
    // the written bits (storage); the latches with no read-back (ports, PM, PMC, TxB) keep
    // what is written, all bits
    function automatic logic [7:0] wmask(input logic [7:0] o);
        case (o)
            8'h3B, 8'h69, 8'h79: wmask = 8'h0F;
            8'h40: wmask = 8'h55;
            8'h44, 8'h45, 8'h46, 8'h65, 8'h66, 8'h75, 8'h76, 8'h94, 8'h95, 8'h96,
            8'h4C, 8'h9C: wmask = 8'hF7;
            8'h4D, 8'h4E, 8'h6D, 8'h6E, 8'h7D, 8'h7E, 8'h9D, 8'h9E: wmask = 8'hF0;
            8'h6C, 8'h7C, 8'hAC: wmask = 8'hD7;
            8'hAD: wmask = 8'hD0;
            8'hEC: wmask = 8'hC0;
            8'h68, 8'h78: wmask = 8'hFD;
            8'h90: wmask = 8'hFD;
            8'h91: wmask = 8'hC0;
            8'hA0, 8'hA2: wmask = 8'h33;
            8'hA1, 8'hA3: wmask = 8'hFC;
            8'hEB: wmask = 8'h4F;
            8'h6A, 8'h7A, 8'hE1, 8'hE8, 8'hE9, 8'hFF: wmask = 8'hFF;
            8'h80, 8'h81, 8'h82, 8'h83, 8'h88, 8'h89, 8'h8A, 8'h8B: wmask = 8'hFF;
            8'h00, 8'h01, 8'h02, 8'h08, 8'h09, 8'h0A, 8'h10, 8'h11, 8'h12, 8'h62, 8'h72:
                wmask = 8'hFF;
            default: wmask = 8'h00;
        endcase
    endfunction
    // bits that read 1 whatever is written (the fixed priority fields)
    function automatic logic [7:0] ones(input logic [7:0] o);
        case (o)
            8'h4D, 8'h4E, 8'h6D, 8'h6E, 8'h7D, 8'h7E, 8'h9D, 8'h9E, 8'hAD, 8'hEC: ones = 8'h07;
            default: ones = 8'h00;
        endcase
    endfunction
    function automatic logic [7:0] rst(input logic [7:0] o);
        case (o)
            8'h44, 8'h45, 8'h46, 8'h65, 8'h66, 8'h75, 8'h76, 8'h95, 8'h96: rst = 8'h44;
            8'h94: rst = 8'hC4;
            8'h4C, 8'h4D, 8'h4E, 8'h6C, 8'h6D, 8'h6E, 8'h7C, 8'h7D, 8'h7E, 8'h9C, 8'h9D,
            8'h9E, 8'hAC, 8'hAD, 8'hEC: rst = 8'h47;
            8'h80, 8'h81, 8'h82, 8'h83, 8'h88, 8'h89, 8'h8A, 8'h8B: rst = 8'hFF;
            8'h01, 8'h09, 8'h11: rst = 8'hFF;
            8'hE1: rst = RFM_RESET;
            8'hE8: rst = WTC_RESET[7:0];
            8'hE9: rst = WTC_RESET[15:8];
            8'hEB: rst = PRC_RESET;
            8'hFF: rst = IDB_RESET;
            default: rst = 8'h00;
        endcase
    endfunction
    function automatic logic [7:0] cval(input logic [7:0] o);
        case (o)
            8'h6B, 8'h7B: cval = 8'h80;
            8'hF4: cval = 8'h02;
            8'hF7: cval = 8'hC7;
            8'hF8: cval = 8'h4E;
            8'h60, 8'h70, 8'hE0, 8'hFC, 8'hF0, 8'hF1, 8'hF9: cval = 8'h00;
            default: cval = 8'hF7;
        endcase
    endfunction

    // (F3) the IC registers in the controller's order: EXIC0-2, SEIC0 SRIC0 STIC0, SEIC1 SRIC1
    // STIC1, TMIC0-2, DIC0-1, TBIC
    localparam logic [8*15-1:0] IC_OFF = {8'hEC, 8'hAD, 8'hAC, 8'h9E, 8'h9D, 8'h9C, 8'h7E, 8'h7D,
                                          8'h7C, 8'h6E, 8'h6D, 8'h6C, 8'h4E, 8'h4D, 8'h4C};
    function automatic logic [3:0] ic_idx(input logic [7:0] o);
        ic_idx = 4'd15;
        for (int k = 0; k < 15; k++)
            if (IC_OFF[8*k +: 8] == o)
                ic_idx = 4'(k);
    endfunction

    genvar gi;
    // ---- the storage: one byte per offset; the bits no write reaches are constants ----------
    // PRC, WTC, RFM and IDB are their own registers (the function bench sets PRC and WTC
    // through them: fpga/v35s/v35_core2_tb.cpp); their bytes in `st` are not read
    reg [7:0] st [0:255];
    reg       sbf = 1'b0;               // (F4d) STBC bit 0 (below: the store's write)
    integer i;
    initial begin
        for (i = 0; i < 256; i = i + 1)
            st[i] = rst(8'(i));
        prc = PRC_RESET;
        wtc = WTC_RESET;
        rfm = RFM_RESET;
        idb = IDB_RESET;
    end

    wire in_page = addr[19:12] == idb && addr[11:8] == 4'hF;
    wire top = addr == 20'hFFFFF;
    wire [7:0] w_off = top ? 8'hFF : addr[7:0];
    // a byte store at an offset (byte stores to a 16-bit register's half are ignored)
    function automatic logic byte_ok(input logic [7:0] o, input logic is_word);
        byte_ok = wmask(o) != 8'h00 && (is_word || kind(o) != K_W16);
    endfunction
    // (WO31) the store is one byte at its offset; `w_word`: it is a byte of a word (the bus
    // unit's even pair); its byte on the lane of its address (a byte store has it on both)
    wire        w_word = width == BW_WORD && !top;
    wire [7:0]  w_lo = (width == BW_HI || (width == BW_WORD && addr[0])) ? data[15:8] : data[7:0];
    // (timing repair 1) the store's decode registered at ce_b (ce_rd): the address, width and
    // IDB are ce_a registers, so at ce_b they hold the values the coming ce_a's store reads; every
    // store reader below is enabled by `wr` (ce_a) and reads these (`+v35_chk`: against the direct
    // decode at every store)
    reg         ip_b = 1'b0, tp_b = 1'b0, ww_b = 1'b0;
    reg  [7:0]  wo_b = 8'h00;
    always @(posedge clock) begin
        if (ce_rd) begin
            ip_b <= in_page;
            tp_b <= top;
            wo_b <= w_off;
            ww_b <= w_word;
        end
    end
`ifndef SYNTHESIS
    /* verilator lint_off BLKSEQ */
    integer trw_n = 0;
    always @(posedge clock) begin
        if ($test$plusargs("v35_chk") && reset_n && wr
            && (ip_b !== in_page || tp_b !== top || wo_b !== w_off || ww_b !== w_word)) begin
            trw_n = trw_n + 1;
            if (trw_n <= 20)
                $display("v35 chk: sfr: the store's registered decode off the address at %0t", $time);
        end
    end
    final if ($test$plusargs("v35_chk") && trw_n != 0)
        $display("v35 chk: sfr: %0d stores with the registered decode off", trw_n);
    /* verilator lint_on BLKSEQ */
`endif
    always @(posedge clock) begin
        if (!reset_n) begin
            for (i = 0; i < 256; i = i + 1)
                st[i] <= rst(8'(i));
            prc <= PRC_RESET;
            wtc <= WTC_RESET;
            rfm <= RFM_RESET;
            idb <= IDB_RESET;
        end else if (wr && (tp_b || ip_b)) begin
            // (WO31) one byte at its own offset (a word's high byte comes in its own cycle)
            if (byte_ok(wo_b, ww_b))
                st[wo_b] <= w_lo & wmask(wo_b);
            if (wo_b == 8'hEB)
                prc <= w_lo & 8'h4F;
            if (wo_b == 8'hE1)
                rfm <= w_lo;
            if (wo_b == 8'hE8)
                wtc[7:0] <= w_lo;
            if (wo_b == 8'hE9)
                wtc[15:8] <= w_lo;
            if (wo_b == 8'hFF)
                idb <= w_lo;
        end
        // (F4d) STBC's SBF (bit 0): set by a store with bit 0 = 1, never cleared by a store or by
        // reset; 0 at power-on (f4_stop: 00h stores leave it, FFh sets it, the second run after a
        // reset reads 01h; a STOP does not set it). No other STBC bit reads back
        if (reset_n && wr && ip_b && wo_b == 8'hE0 && w_lo[0])
            sbf <= 1'b1;
        // (F4b) a macro service's end: the source's MS bit (f4_ms: TMIC0 27h -> 07h)
        if (reset_n)
            for (i = 0; i < 15; i = i + 1)
                if (ms_clr[i])
                    st[IC_OFF[8*i +: 8]][5] <= 1'b0;
    end
    // (F4b) the macro-service control registers by source (EMS0-2, SRMS0 STMS0, SRMS1 STMS1,
    // TMMS0-2)
    localparam logic [8*15-1:0] MS_OFF = {8'h00, 8'h00, 8'h00, 8'h96, 8'h95, 8'h94, 8'h76,
                                          8'h75, 8'h00, 8'h66, 8'h65, 8'h00, 8'h46, 8'h45, 8'h44};
    generate
        for (gi = 0; gi < 15; gi++) begin : g_ms
            localparam logic [7:0] MO = MS_OFF[8*gi +: 8];
            assign ms_b[8*gi +: 8] = MO == 8'h00 ? 8'h00 : st[MO];
        end
    endgenerate
    // (F3) the IC registers' bytes and the stores that write them (the IF bit is the controller's)
    generate
        for (gi = 0; gi < 15; gi++) begin : g_ic
            localparam logic [7:0] O = IC_OFF[8*gi +: 8];
            assign ic_b[8*gi +: 8] = st[O];
            assign ic_we[gi] = wr && ip_b && !tp_b && wo_b == O;
            assign ic_wd[gi] = w_lo[7];
        end
    endgenerate
    assign intm = st[8'h40];

    // FLAG: the store's byte (bits 5 and 3) into the PSW
    assign flag_we = wr && ip_b && !tp_b && wo_b == 8'hEA;
    assign flag_d = {w_lo[5], w_lo[3]};

    // ---- (F4) the peripherals ----------------------------------------------------------------
    // the store as the peripherals see it: a byte at w_off (w_lo), with a word the next (data hi)
    wire        p_we = wr && ip_b && !tp_b;
    wire [15:0] tm0, md0, tm1, md1;
    wire [7:0]  tmc0, tmc1;
    wire        tout;
    wire [2:0]  tf;
    wire        tbf;
    v35_timer timer (.clock, .reset_n, .ce_a, .we(p_we), .w_off(wo_b), .w_word(ww_b), .w_lo(data[7:0]),
                     .w_hi(data[15:8]), .tm0, .md0, .tm1, .md1, .tmc0, .tmc1, .tout, .tf, .tfp);
    v35_tbc tbc (.clock, .reset_n, .ce_a, .tb(prc[3:2]), .tbf);
    // (F4b) the serial channels (channel 0 with the I/O interface mode): SCM / SCC / BRG in the
    // storage; the stores of SCM and TxB, RxB's reads; RxD0/1, /CTS0/1 the input levels 9-12
    wire [7:0] rxb0, rxb1, sce0, sce1;
    wire       txd0, txd1, sck0, rsck0, rsck_oe0, rsck1, rsck_oe1, sck1;
    wire       sr0, st0, se0, sr1, st1, se1;
    v35_serial #(.IO_MODE(1'b1)) ser0 (
        .clock, .reset_n, .ce_a, .s_scm(p_we && wo_b == 8'h68), .v_scm(w_lo),
        .s_txb(p_we && wo_b == 8'h62), .v_txb(w_lo),
        .s_bg(p_we && (wo_b == 8'h69 || wo_b == 8'h6A)),
        .scm(st[8'h68]), .scc(st[8'h69]),
        .brg(st[8'h6A]), .rd_rxb(rd_go && rd_off[7:1] == 7'h30), .rxd_in(input_levels[9]),
        .cts_in(input_levels[11]), .rxb(rxb0), .sce(sce0), .txd(txd0), .sck(sck0), .rsck(rsck0),
        .rsck_oe(rsck_oe0), .sr(sr0), .st(st0), .se(se0));
    v35_serial #(.IO_MODE(1'b0)) ser1 (
        .clock, .reset_n, .ce_a, .s_scm(p_we && wo_b == 8'h78), .v_scm(w_lo),
        .s_txb(p_we && wo_b == 8'h72), .v_txb(w_lo),
        .s_bg(p_we && (wo_b == 8'h79 || wo_b == 8'h7A)),
        .scm(st[8'h78]), .scc(st[8'h79]),
        .brg(st[8'h7A]), .rd_rxb(rd_go && rd_off[7:1] == 7'h38), .rxd_in(input_levels[10]),
        .cts_in(input_levels[12]), .rxb(rxb1), .sce(sce1), .txd(txd1), .sck(sck1), .rsck(rsck1),
        .rsck_oe(rsck_oe1), .sr(sr1), .st(st1), .se(se1));
    // (F4c) DMA: DMAM's mode, W and EDMA live in v35_dma (read back from it); DMAC in the storage
    wire [7:0] dmam0, dmam1;
    wire [1:0] dic;
    // (WO38) DIC's IF is set in the last transfer, at its cycle's start (the bus unit's DMA
    // window `dk` rising in the transfer the EU marked the last, `dm_last`): passage.py
    // RESULTS4 section 4.1, f5_pd_dl0 / dl7 / d_*: the request behaves as an NMI edge half a
    // clock before the last transfer's write strobe starts, not at the service's end. v35_dma's
    // `rs` (the CPU resuming, which set it before) sets the IF from the TC update's pending
    // flag; this start is the earlier of the two (the TC update is the routine's first act)
    reg        dl_q = 1'b0;
    always_ff @(posedge clock) begin
        if (!reset_n)
            dl_q <= 1'b0;
        else if (ce_a)
            dl_q <= dk && dm_last;
    end
    wire       dl_go = dk && dm_last && !dl_q;
    v35_dma dma (.clock, .reset_n, .ce_a, .we(p_we), .w_off(wo_b), .w_lo,
                 .dmac0(st[8'hA0]), .dmac1(st[8'hA2]), .dmarq(input_levels[7:6]),
                 .take(dm_take), .tend(dm_tend), .tlast(dm_tlast), .rs(dm_rs || dl_go), .smp(dm_smp), .dmam0, .dmam1,
                 .dm_v, .dm_go, .tk_ch(dm_ch), .tk_in(dm_in), .tk_out(dm_out), .tk_w(dm_w),
                 .tk_ps(dm_ps), .tk_pd(dm_pd), .dic);
    // the IF bits raised: SEIC0 SRIC0 STIC0 (3-5), SEIC1 SRIC1 STIC1 (6-8), TMIC0-2 (9-11), (F4c)
    // DIC0-1 (12-13), TBIC (14)
    assign pf_set = {tbf, dic, tf, st1, sr1, se1, st0, sr0, se0, 3'd0};
    // (WO50, P8) the timers' count-outs in the clock they are made (v35_timer's `tfp`: the terms its `tf`
    // strobe is loaded from), in pf_set's TMIC0-2 places; the other sources have none
    wire [2:0]  tfp;
    assign pf_pre = {1'b0, 2'b00, tfp, 9'd0};

    // the ports (f4_port): a bit in input mode (PM 1) reads its pin, in output mode its latch;
    // P10-P13 are inputs (PM1 bits 3:0 fixed 1), P13 the /INTAK output's level while PMC1 bit 3
    // selects it. The pins the board drives are registered here (two flops, the levels being
    // asynchronous to the core)
    reg [23:0] pin_s = 24'd0, pin_r = 24'd0;
    always_ff @(posedge clock) begin
        pin_s <= pins_in;
        pin_r <= pin_s;
    end
    wire [7:0] p0l = st[8'h00], p1l = st[8'h08], p2l = st[8'h10];
    wire [7:0] pm0 = st[8'h01], pm1 = st[8'h09] | 8'h0F, pm2 = st[8'h11];
    wire [7:0] pmc1 = st[8'h0A];
    wire [7:0] p1pin = {pin_r[15:12], pmc1[3] ? intak_n : pin_r[11], pin_r[10:8]};
    wire [7:0] p0 = (pm0 & pin_r[7:0]) | (~pm0 & p0l);
    wire [7:0] p1 = (pm1 & p1pin) | (~pm1 & p1l);
    wire [7:0] p2 = (pm2 & pin_r[23:16]) | (~pm2 & p2l);
    // the output pins: a port bit in output mode drives its latch; P13 /INTAK and P15 TOUT by
    // PMC1. A pin the CPU does not drive keeps the level it last carried (the board's bus
    // keepers: f4_tout, P13 stays high after PMC1 bit 3 is cleared). (F4b) TxD0/1; SCK0 on P16 by
    // PMC1 bit 6; RSCK0 on /CTS0's pin while channel 0's I/O mode drives it (f4_sio).
    // (work order 34) CLKOUT on P07 while PMC0 bit 7 is 1 (the data book's PMC0: PMC07 selects
    // the function, PM07 and the latch are not read for it). `ck` is the CPU clock's level: 1
    // from the CPU clock's edge (ce_rd: ce_b, the divider's state start, where B1's address and
    // the write's R/W move), 0 from its middle (ce_a, where /MREQ, the strobes and /REFRQ move,
    // and where READY is sampled). Silicon (validation/v35s/clkout.py; the rdy_s* / rdy_ms*
    // scope receipts at fX/8, /4, /2): CLKOUT falls 1 scope tick before /MREQ, the strobes and
    // /REFRQ fall, rises 1 tick before a write's R/W falls, 50 % duty at each PCK; the core
    // moves the pin on the same fabric tick as those pins (that tick is silicon's output delay
    // difference, under a 30 ns tick). The pin's register loads `ck`'s next value, so the pin
    // and `ck` are one register's copy: no gate on a clock net, no derived clock
    reg        ck = 1'b0;
    wire       ck_d = ce_rd || (ck && !ce_a);
    always_ff @(posedge clock)
        ck <= ck_d;
    // (work order 36) the port pins take an SFR store at the CPU clock's edge. Silicon
    // (build/overseer/wo34s/RESULTS.md section 1; clk_en8 / clk_en2, both sessions, fX/8 and
    // fX/2): a P0 latch store, a PMC0 select and a PMC0 deselect all show on P07 one scope tick
    // after a CLKOUT rise, never at the clock's middle, 2.5 clocks before the next fetch's /MREQ
    // fall. So the bytes the output pins are made of (the latches P0-P2, PM0-2, PMC0-2) are
    // copied at ce_rd (the CPU clock's edge, where CLKOUT rises) and the pins register reads the
    // copies, the pin moving the tick after CLKOUT's rise (the pins register is one tick behind
    // the copy, as silicon's pin is one tick behind its CLKOUT rise). (work order 37) The edge
    // is the one before the store's landing ce_a: while the bus unit holds a store captured and
    // landing at the coming ce_a (`wr_pend`, its registers only), the copy of the store's offset
    // takes the store's byte (w_lo; each store is one byte, these offsets' write masks are FFh)
    // instead of the page's; at the later edges the page holds it. Work order 36 took the edge
    // after the landing, 1 clock late against the next fetch. This is the pins' update rule for
    // every port bit, not for P07 alone; the
    // port reads (p0 / p1 / p2 below), the input functions (INT, POLL, HLDRQ, READY, /INTAK's
    // read) and the peripherals read the page itself, as before. What it gives at P07 (as
    // silicon): a select with the latch 1 makes no edge before the regular fall, with the
    // latch 0 (or the pin released) the first high phase starts one tick after CLKOUT's rise;
    // a deselect with the latch 1 makes no runt, with the latch 0 a one-tick high runt; a
    // deselect with PM07 = 1 releases the pin while it is high
    reg  [7:0] op0l, opm0, opmc0, op1l, opm1, opmc1, op2l, opm2, opmc2;
    // (trial T2) TOUT's pin copy at the CPU clock's edge, as every other port bit's
    reg        otout = 1'b1;
    always_ff @(posedge clock)
        if (ce_rd) otout <= tout;
    initial begin
        op0l = rst(8'h00); opm0 = rst(8'h01); opmc0 = rst(8'h02);
        op1l = rst(8'h08); opm1 = rst(8'h09); opmc1 = rst(8'h0A);
        op2l = rst(8'h10); opm2 = rst(8'h11); opmc2 = rst(8'h12);
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            op0l <= rst(8'h00); opm0 <= rst(8'h01); opmc0 <= rst(8'h02);
            op1l <= rst(8'h08); opm1 <= rst(8'h09); opmc1 <= rst(8'h0A);
            op2l <= rst(8'h10); opm2 <= rst(8'h11); opmc2 <= rst(8'h12);
        end else if (ce_rd) begin
            op0l <= st[8'h00]; opm0 <= st[8'h01]; opmc0 <= st[8'h02];
            op1l <= st[8'h08]; opm1 <= st[8'h09]; opmc1 <= st[8'h0A];
            op2l <= st[8'h10]; opm2 <= st[8'h11]; opmc2 <= st[8'h12];
            if (wr_pend && in_page && !top)
                case (w_off)
                    8'h00: op0l <= w_lo;
                    8'h01: opm0 <= w_lo;
                    8'h02: opmc0 <= w_lo;
                    8'h08: op1l <= w_lo;
                    8'h09: opm1 <= w_lo;
                    8'h0A: opmc1 <= w_lo;
                    8'h10: op2l <= w_lo;
                    8'h11: opm2 <= w_lo;
                    8'h12: opmc2 <= w_lo;
                    default: ;
                endcase
        end
    end
    wire [7:0] opm1f = opm1 | 8'h0F;      // the output side's PM1 (bits 3:0 fixed 1, as pm1's)
    // (F4c) PMC2 bits 1, 2, 4, 5: DMAAK0, TC0, DMAAK1, TC1 (f4_dma: DMAAK low through the
    // transfer's cycle in the I/O modes only, TC low inside the last transfer's cycle, every mode)
    wire [7:0] pmc2 = st[8'h12];
    wire       dk_io = dk && (dm_in || dm_out);
    wire       tc_l = dkt && dm_last;
    // (F4d) PMC2 bit 6: /HLDAK (the bus unit's register); bit 7: HLDRQ's input (hrq)
    wire [7:0] p2f = {1'b0, hlda_n, !(tc_l && dm_ch), !(dk_io && dm_ch), 1'b0, !(tc_l && !dm_ch),
                      !(dk_io && !dm_ch), 1'b0};
    wire [7:0] p2v = (opmc2 & p2f) | (~opmc2 & ~opm2 & op2l);
    wire [7:0] p2d = opmc2 | ~opm2;
    wire [31:0] pv = {5'd0, rsck0, txd1, txd0, 1'b0, p2v[6:4], 1'b0,
                      p2v[2:1], 1'b0, ~opm1f[7] & op1l[7], opmc1[6] ? sck0 : op1l[6],
                      opmc1[5] ? otout : op1l[5], ~opm1f[4] & op1l[4], intak_n, 3'd0,
                      opmc0[7] ? ck_d : ~opm0[7] & op0l[7], ~opm0[6:0] & op0l[6:0]};
    wire [31:0] pd = {5'h1F, rsck_oe0, 2'b11, 1'b1, p2d[6:4], 1'b1, p2d[2:1], 1'b1, ~opm1f[7],
                      opmc1[6] || !opm1f[6], opmc1[5] || !opm1f[5], ~opm1f[4], opmc1[3], 3'b111,
                      opmc0[7] || !opm0[7], ~opm0[6:0]};
    initial pins = 32'h0300_0000;
    always_ff @(posedge clock)
        pins <= (pd & pv) | (~pd & pins);
    // (F4d) bus hold's request: HLDRQ (P27) while PMC2 bit 7 selects it (f4_hold h_port: with
    // PMC2 0 HLDRQ is ignored); READY (P17) and PMC1 bit 7 (f4_rdy rd_off: with bit 7 0 no
    // extension)
    // HLDRQ passes two CPU-clock flops (sampled at ce_a: f4_hold, /HLDAK's edges two clocks after
    // the level's on silicon against a direct sample)
    reg  h1 = 1'b0;
    initial hrq = 1'b0;
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            h1 <= 1'b0;
            hrq <= 1'b0;
        end else if (ce_a) begin
            h1 <= pin_r[23] && pmc2[7];
            hrq <= h1;
        end
    end
    assign rdy_en = pmc1[7];
    assign rdy_lv = pin_r[15];

    // ---- the read ---------------------------------------------------------------------------
    function automatic logic [7:0] rbyte(input logic [7:0] o);
        case (kind(o))
            K_ST: rbyte = o == 8'hEB ? prc : o == 8'hE1 ? rfm : o == 8'hE8 ? wtc[7:0]
                        : o == 8'hE9 ? wtc[15:8] : (st[o] & wmask(o)) | ones(o);
            K_ISPR: rbyte = ispr;
            K_W16: rbyte = o[3] ? (o[1] ? (o[0] ? md1[15:8] : md1[7:0])
                                        : (o[0] ? tm1[15:8] : tm1[7:0]))
                                 : (o[1] ? (o[0] ? md0[15:8] : md0[7:0])
                                         : (o[0] ? tm0[15:8] : tm0[7:0]));
            K_PIN: rbyte = o == 8'h00 ? p0 : o == 8'h08 ? p1 : o == 8'h10 ? p2 : 8'h00;
            K_FLAG: rbyte = {2'b00, psw_f[1], 1'b0, psw_f[0], 3'b000};
            K_IDB: rbyte = idb;
            K_C: rbyte = cval(o);
            default: rbyte = 8'h00;
        endcase
        // (F4) TMC0 / TMC1: the timer's (TS0 / MS0 end a one-shot count)
        if (o == 8'h90)
            rbyte = tmc0 & 8'hFD;
        if (o == 8'h91)
            rbyte = tmc1 & 8'hC0;
        // (F4b) RxB0/1, SCE0/1: the serial channels'
        if (o == 8'h60)
            rbyte = rxb0;
        if (o == 8'h70)
            rbyte = rxb1;
        if (o == 8'h6B)
            rbyte = sce0;
        if (o == 8'h7B)
            rbyte = sce1;
        // (F4c) DMAM0/1: the DMA unit's (TDMA reads 0, EDMA cleared at TC 0)
        if (o == 8'hA1)
            rbyte = dmam0;
        if (o == 8'hA3)
            rbyte = dmam1;
        // (F4d) STBC: SBF
        if (o == 8'hE0)
            rbyte = {7'd0, sbf};
        // (F3) an IC register's IF bit: the controller's
        if (kind(o) == K_ST && ic_idx(o) != 4'd15)
            rbyte[7] = ic_if[ic_idx(o)];
        // SCM0/1: bit 3 reads written bit 3 and bit 0 (the every-value sweep)
        if (o == 8'h68 || o == 8'h78)
            rbyte[3] = st[o][3] && st[o][0];
    endfunction
    wire [7:0] r_lo_off = {rd_off[7:1], 1'b0};
    wire [7:0] r_hi_off = {rd_off[7:1], 1'b1};
    wire [7:0] r_lo = rbyte(r_lo_off);
    wire [7:0] r_hi = (kind(r_hi_off) == K_RES || (kind(r_hi_off) == K_W16 && !rd_word)) ? r_lo
                    : rbyte(r_hi_off);
    initial rd_data = 16'h0000;
    always @(posedge clock) begin
        if (ce_rd)
            rd_data <= {r_hi, r_lo};
    end


    initial poll_p14 = 1'b0;
    always_ff @(posedge clock)
        poll_p14 <= input_levels[5] && st[8'h09][4];
    initial int_on = 1'b0;
    always_ff @(posedge clock)
        int_on <= input_levels[5] && st[8'h0A][4];
    wire unused = &{1'b0, input_levels[15:13], input_levels[8], input_levels[4:0], rsck1,
                    rsck_oe1, sck1};
endmodule

// ============================================================================================
// (F3) The interrupt controller (docs/v35s-differences.md section 5; README "F3"), measured on
// the socket (validation/v35s/intr.py: f3_vec, f3_order, f3_prio, f3_trap, f3_step; receipts
// validation/v35s/receipts/f3-*). Beside v35_sfr: the IC registers' MK, MS / INT, ENCS and PR
// are its storage; the IF bits and ISPR are this module's registers (read back through
// v35_sfr's page).
//
//   requests  INTP0-2 by their edges (INTM ES0-2: 0 falling, 1 rising; f3_vec), NMI by its edge
//             (ESNMI); every IC register's IF by a store (f3_vec: a store of IF 1 requests the
//             interrupt; a store of IF 0 clears a pending one)
//   priority  six groups in the default order TU, D, P, SER0, SER1, TB, each at the level of its
//             first register's PR (TMIC0, DIC0, EXIC0, SEIC0, SEIC1; TB 7), members in their
//             fixed order (f3_prio); a request is offered while its level is above (numerically
//             below) the highest level in service (ISPR's lowest set bit). MK 1 masks a source,
//             MS 1 makes it a macro-service request: (F4p) resolved with the vectored ones
//             in one pass (a group's first requesting member of either kind; the winner is
//             `ms_v` when it is in macro service, else the offer `ir_v`; with IE 0 a group
//             whose first member is vectored drops out: validation/v35s/prio.py)
//   the take  (step B: moved in from v35_top, below) the sequencer's dispatch or a string's take
//             point takes the offer, NMI, a macro service, DMA or the single step (`igo` /
//             `sgo`, the take strobes); STOP's settling count and HALT's release; `iack` (the entry's
//             IVEC word) clears the taken source's IF and sets its level in ISPR (NMI: clears
//             its request); (WO43) on the entry's second IVEC word (the acknowledge, `ak_l`), and
//             it restarts the scan there (a macro service: its one IVEC word clears its IF);
//             FINT clears ISPR's highest-priority bit (f3_prio)
//   HALT      `wake`: NMI or any IF with MK 0 (and MS 0) ((WO33) at its level's offer slot, through
//             the offer's passage: below); f3_vec: a masked request does not
//             release HALT
// The resolution is a pipeline of registers (the groups' keys, two minimum stages, the offer),
// two CPU clocks from an IF / MK / PR / ISPR change to the offer: the latency the sequencer's
// boundary sees after a store (silicon's is longer: f3_lat; the gate's programs place an
// absorber after each release). Every output of the resolution is a ce_a register; the take's
// (igo, sgo, take_d, dm_rs, dm_smp, wake, ms_ch) are AND-ORs of registers and the
// sequencer's take points, as they were in v35_top.
/* verilator lint_off DECLFILENAME */
module v35_intc (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    input  wire [15:0] input_levels,    // NMI 1, INTP0-2 2-4
    input  wire [7:0]  intm,
    input  wire [8*15-1:0] ic_b,
    input  wire        wr,              // the SFR store's write enable (with ic_we)
    input  wire [14:0] ic_we,
    input  wire [14:0] ic_wd,
    // (step B) the sequencer's take points and acts (v35_useq; tick A unless noted)
    input  wire        x_disp,          // the dispatch word executes: an instruction boundary
    input  wire        x_tki,           // a TKI word executes: a string's take point
    input  wire        x_end,           // (WO38) the instruction's look (v35_useq: the word releasing
                                        //   the next opcode, held open to the dispatch)
    input  wire        x_nb,            // an E word executes marking its end no boundary (nb: a
                                        //   prefix, EI, DI, ...)
    input  wire        x_nbi,           // ... dropping the arms (seg=NBI: POP PSW, RETI, FINT)
    input  wire        halted,          // a halt word stands ((WO50) HALT's / STOP's loop: the word's halt bit)
    input  wire        w_stop,          // (F4d) the word is STOP's halt word (a level)
    input  wire        x_stop,          // ... and it executes (tick B)
    input  wire        iack,            // an IVEC word executes (ce_a strobe; (WO43) the entry's second: the acknowledge)
    input  wire        fint,            // FINT executes (ce_a strobe)
    input  wire        int_on,          // (F3b) the INT request (v35_sfr's register)
    input  wire        ie,              // (F4p) PSW.IE (the EU's register): a group whose first
                                        // requesting member is vectored competes only with IE 1
    input  wire        ie_r,            // (WO40) PSW.IE as the EU's register holds it (`ie` is the
                                        // datum's IE in the clock a PSW load reads it): the scan's
                                        // restart by IE's rise (`ie_q`, `ie_up`)
    input  wire        brk,             // (F3) PSW.BRK (the EU's register): the single step
    input  wire [14:0] pf_set,          // (F4) the peripherals' requests (ce_a strobes: IF <- 1)
    input  wire [14:0] pf_pre,          // (WO50, P8) the strobes a clock ahead (the timer's count-outs)
    // (F4b) macro service: the sources' macro-service control registers (v35_sfr's storage, in
    // this module's order; 0 where a source has none), the service's end (the EU's MSDC strobe)
    input  wire [8*15-1:0] ms_b,
    input  wire        ms_end,
    // (F4c) DMA (v35_dma's registers): the armed request, any request, the requesting channel
    input  wire        dm_go,
    input  wire        dm_v,
    input  wire        dm_ch,
    // (step B) the take (below): to the sequencer, the dispatch's and the string take point's
    // take and HALT's release; to the EU, the take at the dispatch and its parameters; to
    // v35_dma, the DMA take and the starts it samples at
    output wire        igo,
    output wire        sgo,
    output wire        wake,            // HALT's release ((F4d) STOP's: the settling count's end)
    output wire        take_d,          // a DMA take (a ce_a strobe)
    output wire        dm_rs,           // a start that is not a DMA take
    output wire        dm_smp,          // a start or a string's take point that is not a DMA take
    output reg         tk_dm,           // the last take is a DMA transfer's
    output reg         ms_hlt,          // the stall of a HALT seen since the last start that was
                                        //   not a macro service's or a DMA take's
    output reg         tk_ms,           // the last take is a macro service ...
    output wire [2:0]  ms_ch,           // ... its channel (a DMA take's: the DMA channel), mode
    output reg  [2:0]  ms_mode,         //   (MSM), direction
    output reg         ms_dir,
    output wire [14:0] ms_clr,          // the source's MS bit cleared at the end (v35_sfr's storage)
    output reg         tk_bs,           // (F3b) the last take is a bank switch (ENCS 1) ...
    output reg  [2:0]  tk_lv,           // ... at this level (the new bank)
    output reg         tk_int,          // (F3b) the last take is INT
    output reg  [14:0] ic_if,
    output reg  [7:0]  ispr,
    output reg  [4:0]  tk_vec           // the vector of the last take (IVEC's)
);
    reg         ms_v;                   // a macro-service request is pending
    reg  [2:0]  mc_ch;                  // the macro service's channel (the take's)
    // (WO35) the request flip-flop `ir_h` (R) for the maskable sources, INT and the scan's slots,
    // first come; `ir_int` names INT as the one that set it; `ir_v` R seen at the EU's sample, the
    // fixed delay behind R passed (the line, below)
    reg         ir_h;                   // (qprobe round 14-16) a maskable request is raised (held): R
    reg         ir_int = 1'b0;          // (WO35) ... by INT (else by a slot: its source in ir_i ...)
    wire        ir_v;                   // a maskable request is offered (R through the line)
    reg  [4:0]  ir_vec;
    reg         nmi_v;                  // NMI is pending
    reg         i_wake;                 // HALT's release: NMI, an unmasked IF ((WO33) at its slot), INT
    // (F4d) STOP stands (`stp`, below): the INTP0-2 samplers hold their last levels (no edge is
    // seen while stopped: f4_stop stop_intp, an INTP0 pulse in STOP leaves its IF 0); NMI's
    // keeps sampling (it releases STOP)
    reg         stp = 1'b0;
    wire        frz = stp;
    wire        take_n, take_i, take_s, take_m;

    // the sources: (group rank, member) -> IC index and vector
    //   rank 0 TU: 9 10 11 (28 29 30); 1 D: 12 13 (20 21); 2 P: 0 1 2 (24 25 26);
    //   3 SER0: 3 4 5 (12 13 14); 4 SER1: 6 7 8 (16 17 18); 5 TB: 14 (31)
    function automatic logic [4:0] vec_of(input logic [3:0] i);
        case (i)
            4'd0: vec_of = 5'd24; 4'd1: vec_of = 5'd25; 4'd2: vec_of = 5'd26;
            4'd3: vec_of = 5'd12; 4'd4: vec_of = 5'd13; 4'd5: vec_of = 5'd14;
            4'd6: vec_of = 5'd16; 4'd7: vec_of = 5'd17; 4'd8: vec_of = 5'd18;
            4'd9: vec_of = 5'd28; 4'd10: vec_of = 5'd29; 4'd11: vec_of = 5'd30;
            4'd12: vec_of = 5'd20; 4'd13: vec_of = 5'd21;
            default: vec_of = 5'd31;
        endcase
    endfunction
    wire [14:0] mk, ms;
    genvar gi;
    generate
        for (gi = 0; gi < 15; gi++) begin : g_src
            assign mk[gi] = ic_b[8*gi + 6];
            assign ms[gi] = ic_b[8*gi + 5];
        end
    endgenerate
    // (WO50, P8) the scan sees a request in the clock its strobe raises the flag (`pf_set`), not a register
    // later, and the timer's count-out as it is being made (`pf_pre`, a clock ahead of its strobe): f5_la_a's
    // take window against the count-out (29.5 .. 44.5 half clocks), periph f4_tout's first period
    wire [14:0] rq = (ic_if | pf_set | pf_pre) & ~mk & ~ms;
    // (F4b) the sources with a macro-service register: EXIC0-2, SRIC0 STIC0, SRIC1 STIC1, TMIC0-2
    // (not the serial errors, DMA, TB: the data book's table 6)
    localparam logic [14:0] MS_CAP = 15'b000_1111_1011_0111;
    wire [14:0] rq_m = ic_if & ~mk & ms & MS_CAP;
    // (F4p) one resolution for both kinds (validation/v35s/prio.py f4p_ms, f4p_x6): each group's
    // first requesting member in its fixed order, vectored or macro service; the groups by
    // {level, default order} against ISPR (a macro service at a level equal to or below the
    // highest in service waits for FINT, IE 0 too: is_eq / is_hi); with IE 0 a group whose first
    // requesting member is vectored drops out and holds its own later members' macro services
    // (end_ms_di, y_tu_vm_di) while another group's macro service goes on (x_vm, y_svm_di)
    wire [14:0] rq_a = rq | rq_m;
    reg  [3:0]  ms_i = 4'd0;            // the macro service's source (the resolution's winner)
    assign ms_clr = ms_end ? 15'(15'd1 << tk_i) : 15'd0;
    function automatic logic [2:0] pr_of(input logic [3:0] i);
        pr_of = ic_b[8*i +: 3];
    endfunction

    // ---- the edges (sampled at the CPU clock) and the request registers --------------------
    reg  [3:0] lv = 4'hF;               // NMI, INTP0-2 as last sampled
    wire [3:0] lvn = input_levels[4:1];
    wire [3:0] es = {intm[6], intm[4], intm[2], intm[0]};
    // (qprobe round 14, spec 10 I1) INTP0-2 are sampled every second clock, NMI every clock.
    // (WO32) The divided clock is the level scan's: its counter's low bit (`sc[0]`, below; the
    // scan's round is eight of its periods), which EI and a store to a request control register
    // restart, so the two-clock lattice of the latest edge a read of the IF sees follows the
    // distance from the last such store, not reset (validation/v35s/phase.py f5_ph_e / e1: the
    // lattice moves with the sled's parity, never with the absolute parity). It was a toggle
    // from reset (`ph`), which no program restarts
    reg  [3:0] sc = 4'd0;               // the scan's counter (the scan below)
    // (WO33) the scan's divided clock: a toggle restarted with the scan (sc[0] while no offer
    // slot stands; a slot holds the counter for two clocks, the toggle runs on, so the sampler
    // keeps its two-clock lattice from the restart)
    reg        dv = 1'b0;
    // (WO35) NMI's edge catch has half a clock (f5_pb_w_n: a pulse of 16 ticks is caught, 12 is
    // not): the pin is also sampled at ce_b (`nmi_h`), and an edge between the last ce_a sample
    // and it, or between it and this ce_a's, is NMI's edge at this ce_a (a level that stands
    // gives its edge at the same ce_a as before)
    reg        nmi_h = 1'b1;
    wire       nmi_e = es[0] ? ((nmi_h && !lv[0]) || (lvn[0] && !nmi_h))
                             : ((!nmi_h && lv[0]) || (!lvn[0] && nmi_h));
    // (WO50, item 9: the INTP sampler half a clock later) INTP0-2 are sampled at ce_b, the middle of the CPU
    // clock behind the divided clock's point (`lvh`), not at its start: silicon's sampling instant is 8 to 12
    // ticks of 32 behind the clock boundary (build/overseer introws section 2; f5_lc_pa / pb, f5_ld_pa .. pd,
    // f5_la_p, f5_ph_e / e1). The edge is formed at the end of that clock (the divided clock's other phase,
    // `!dv`), and the flag's count behind it (`idl`) is INTP_DLY - 1 because the edge is now formed a clock
    // later after the sample: the flag lands where it did, the way from the pin to the flag half a clock
    // shorter (DESIGN-INT2 section 4). NMI's sampler is untouched
    reg  [2:0] lvh = 3'b111;
    always_ff @(posedge clock) if (ce_b) lvh <= lvn[3:1];
    wire [3:0] edge_c = {((es[3:1] & lvh & ~lv[3:1]) | (~es[3:1] & ~lvh & lv[3:1]))
                         & {3{!frz && !dv}}, nmi_e};
    always_ff @(posedge clock) begin
        if (!reset_n)
            nmi_h <= lvn[0];
        else if (ce_b)
            nmi_h <= lvn[0];
    end
    reg        nmi_p = 1'b0;
    // (qprobe rounds 12-13, spec 8 A3 / spec 9 C3-C4) NMI's edge reaches its request (nmi_p)
    // NMI_DLY clocks after it is sampled (`nd`, a down-count loaded by the edge). (qprobe round
    // 16) the round-12 free-running grid is gone: it is the level scan below, which every
    // maskable source goes through. (WO35) NMI_DLY is ACK and RESP (below)
    // INTP0-2's edge reaches its IF bit INTP_DLY clocks after it is sampled (`idl`, one
    // down-count a pin): the pin path's latency measured on the socket (QPr14ninc: the
    // instruction a pin edge is taken in front of moves at the edge 72.5 clocks from M0 on
    // silicon, 83.5 without the delay), the request then going through the level scan as a
    // software request does. A measured latency, not a read mechanism (as NMI_DLY).
    // (WO32) Not re-derived: with the sampler on `dv` the program's read of the IF (phase.py
    // f5_ph_e / e1) wants 5 (the only value with silicon's lattice parity within the half-clock
    // pin phase), the pin's takes wanted 11 (qprobe r14n / r12j / r26i schedule families).
    // (WO33) 5: with the scan's slot and the offer's passage (below) the timer's cut-off is
    // silicon's, and 5 gives silicon's pin cut-off for the take too (lattice.py f5_la_h7 / h0:
    // the latest edge taken 80.4 / 82.4 clocks after mark 1 on the RTL's pin, silicon 80.9 /
    // 82.9 on its, the RTL's pin half a clock early) as for the flag read (f5_la_p, f5_ph_e):
    // one delay, the pin's (RESULTS section 3: the pin is 3 to 5 clocks behind a count-out)
    // (WO35) the line (validation/v35s/passage.py, RESULTS2 sections 6 and 7): the request
    // flip-flop R (`ir_h`) is seen at the EU's sample a fixed delay after it is set, counted by
    // `rq_c` (loaded at the set, R held: a counter and a shift of R are alike on every pin):
    //   RESP  8 clocks from R's set to the boundary's sample: the ACCEPTED MEASURED CONSTANT
    //         (the user's ruling of 2026-11-20). Three independent readings give it: INT's
    //         rising edge to the boundary 10 clocks less its two samples' way in (f5_pa_i_*,
    //         f5_pb_w_i: a two-clock pulse is taken 18 clocks after it fell), IE's load to the
    //         boundary with INT standing (f5_pa_e_pop: POP PSW ; INC ; INC), and EI's own eight
    //         idle words behind its IE rise (f5_pa_q_ei*, lattice.py k*). No mechanism is known:
    //         not the scan, not the pin's level, not a commit point (f5_pb_*)
    //   ACK   the controller's stage between a slot's claim of R and the line, 5 clocks: a slot
    //         with IE to the boundary is 14 clocks (f5_pa_q_*: IE rising in the slot's first
    //         clock; lattice.py: the vector read 30 clocks behind the slot): its own clock, ACK
    //         and RESP; NMI's edge to the boundary the same 14 (f5_pa_n_*: the catch, ACK, RESP),
    //         INT's 10 (RESP and the two samples: f5_pa_i_*). A measured stage, named so; a slot
    //         standing 2 clocks after an INT edge still claims R (f5_pb_v0 / v7)
    // The count loaded is the delay less two clocks: the set's own clock (R's register is loaded
    // at its end) and the sample word's (the sample is registered into `ie_e` on that word and the
    // dispatch reads it on the next); a slot's set adds ACK (`ACK_N`, below)
    localparam logic [3:0] RESP = 4'd8;
    localparam logic [3:0] ACK = 4'd5;
    // (WO35) NMI's request (`nmi_p`, then `nmi_v`) runs the controller's ACK and the line's RESP
    // from the edge's catch: the count less the catch's clock, the sample word's and nmi_p's
    // register (10: the round-12 figure, now derived)
    localparam logic [3:0] NMI_DLY = ACK + RESP - 4'd3;
    localparam logic [3:0] INTP_DLY = 4'd5;
    reg  [3:0] nd = 4'd0;
    reg  [3:0] idl [0:2];
    initial for (int k = 0; k < 3; k++) idl[k] = 4'd0;
    wire [2:0] ip_set = {idl[2] == 4'd1, idl[1] == 4'd1, idl[0] == 4'd1};
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            nd <= 4'd0;
            for (int k = 0; k < 3; k++) idl[k] <= 4'd0;
        end else if (ce_a) begin
            nd <= edge_c[0] ? NMI_DLY : (nd != 4'd0 ? nd - 4'd1 : 4'd0);
            for (int k = 0; k < 3; k++)
                idl[k] <= edge_c[k + 1] ? INTP_DLY - 4'd1 : (idl[k] != 4'd0 ? idl[k] - 4'd1 : 4'd0);     // (WO50, item 9) - 1: the edge formed a clock later (lvh)
        end
    end
    reg  [2:0] tk_k = 3'd0;             // the last take: {NMI, the offer, the step}
    reg  [3:0] tk_i = 4'd0;
    reg  [2:0] tk_l = 3'd0;
    reg  [3:0] ir_i = 4'd0;
    reg  [2:0] ir_l = 3'd0;
    reg        ir_bs = 1'b0;            // (F3b) the offer's member has ENCS 1
    // (WO41) FINT's clear is written back on the clock after FINT's first word (the read and its
    // priority encode on that word, the write a register behind it): the scan sees ISPR cleared
    // one clock after the word (passage.py f5_pi_*, passage8 RESULTS rule 2: X = R - 12 with FINT's
    // first word on R - 11 in silicon's pi frames)
    reg         fint_q = 1'b0;
    always_ff @(posedge clock)
        if (!reset_n)
            fint_q <= 1'b0;
        else if (ce_a)
            fint_q <= fint;
    // (WO43) the acknowledge (passage11 RESULTS, the rule): the entry asks for its vector on its
    // first IVEC word (the decision: SIGMA names the kind and the vector, nothing else changes)
    // and acknowledges on its second, the entry's word on the boundary + 10 (V0 - 6): the taken
    // source's IF cleared, its level set in ISPR, NMI's request cleared and the scan restarted
    // there (silicon's level 0 two scan clocks behind it, V0 - 8 in T units; the flag's clear
    // 10 to 12 clocks behind the old IVEC acknowledge, f5_po_*). `ak_1`: the take's first IVEC
    // has executed (cleared by the next take), so the strobe on `iack` with it set is the
    // acknowledge. A macro service has one IVEC word and keeps its IF's clear there; a DMA take,
    // INT and the single step acknowledge nothing here
    reg         ak_1 = 1'b0;
    wire        ak_l = iack && ak_1;
    // (WO43) the taken source's IF is written back a register behind the acknowledge word (the
    // source read and decoded on the word, its flag's write the clock after it, as FINT's clear:
    // `fint_q`): silicon's flag clear is 10 to 12 clocks behind the cores' old acknowledge, the
    // restart 9 (passage11 section 4: f5_po_* lost up to -6.5, kept from -5.5)
    reg         ak_q = 1'b0;
    always_ff @(posedge clock)
        if (!reset_n)
            ak_q <= 1'b0;
        else if (ce_a)
            ak_q <= ak_l && tk_k[1];
    function automatic logic [7:0] fint_f(input logic [7:0] p);
        fint_f = p;
        for (int b = 7; b >= 0; b--)
            if (p[b])
                fint_f = p & ~(8'd1 << b);
    endfunction
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            lv <= lvn;
            ic_if <= 15'd0;
            ispr <= 8'd0;
            nmi_p <= 1'b0;
            tk_k <= 3'd0;
            tk_i <= 4'd0;
            tk_l <= 3'd0;
            tk_vec <= 5'd0;
            tk_int <= 1'b0;
            tk_bs <= 1'b0;
            tk_lv <= 3'd0;
            tk_ms <= 1'b0;
            mc_ch <= 3'd0;
            ms_mode <= 3'd0;
            ms_dir <= 1'b0;
            ak_1 <= 1'b0;
        end else if (ce_a) begin
            lv <= (frz || dv) ? {lv[3:1], lvn[0]} : {lvh, lvn[0]};
            if (take_n || take_i || take_s || take_m || take_d)
                ak_1 <= 1'b0;
            else if (iack)
                ak_1 <= 1'b1;
            tk_ms <= tk_ms;
            if (take_m) begin
                tk_k <= 3'd0;
                tk_int <= 1'b0;
                tk_bs <= 1'b0;
                tk_ms <= 1'b1;
                tk_i <= ms_i;
                mc_ch <= ms_b[8 * ms_i +: 3];
                ms_dir <= ms_b[8 * ms_i + 4];
                ms_mode <= ms_b[8 * ms_i + 5 +: 3];
            end
            if (take_d) begin
                tk_k <= 3'd0;
                tk_int <= 1'b0;
                tk_bs <= 1'b0;
                tk_ms <= 1'b0;
            end
            if (take_n || take_i || take_s) begin
                tk_ms <= 1'b0;
                // (F3b) INT's take (R set by INT: ir_int) is not the offer's take
                tk_k <= {take_n, take_i && !take_n && !ir_int, take_s && !take_n && !take_i};
                tk_int <= take_i && !take_n && ir_int;
                tk_bs <= take_i && !take_n && !ir_int && ir_bs;
                tk_lv <= ir_l;
                tk_i <= ir_i;
                tk_l <= ir_l;
                tk_vec <= take_n ? 5'd2 : take_i ? ir_vec : 5'd1;
            end
            for (int k = 0; k < 15; k++) begin
                if (wr && ic_we[k])
                    ic_if[k] <= ic_wd[k];
                else if ((ak_q || (iack && tk_ms)) && tk_i == 4'(k))
                    ic_if[k] <= 1'b0;   // (F4b) a macro-service take: IF cleared, ISPR kept; (WO43) a vectored take's a register behind the acknowledge
                if (ms_end && tk_i == 4'(k))
                    ic_if[k] <= 1'b1;   // (F4b) the service's end: the vectored request
                if (k < 3 && ip_set[k % 3])
                    ic_if[k] <= 1'b1;   // (qprobe round 16) INTP0-2: the pin's edge (sampled every second clock) after the pin path's latency
                if (pf_set[k])
                    ic_if[k] <= 1'b1;
            end
            if (ak_l && tk_k[1])
                ispr <= ispr | (8'd1 << tk_l);
            else if (fint_q)
                ispr <= fint_f(ispr);
            if (nd == 4'd1)
                nmi_p <= 1'b1;          // (qprobe round 12-13) NMI's edge after the pin's delay
            else if (ak_l && tk_k[2])
                nmi_p <= 1'b0;
        end
    end

    // ---- the resolution pipeline: S1 (ce_b) the groups' keys {level, rank} and members; S2
    // (ce_a) three minima of pairs; S3 (ce_b) the first two pairs' minimum; S4 (ce_a) the offer
    typedef struct packed {
        logic       v;
        logic [2:0] lvl;
        logic [2:0] rank;
        logic [3:0] idx;
        logic       bs;                 // (F3b) the member's ENCS (f3_bsw: the member's own bit)
        logic       ms;                 // (F4p) the member is in macro service
    } key_t;
    function automatic key_t kmin(input key_t a, input key_t b);
        kmin = (a.v && (!b.v || {a.lvl, a.rank} <= {b.lvl, b.rank})) ? a : b;
    endfunction
    function automatic key_t gkey(input logic [2:0] rank, input logic [3:0] i0, input int n,
                                  input logic [3:0] lead, input logic fixed7);
        gkey = '0;
        gkey.rank = rank;
        gkey.lvl = fixed7 ? 3'd7 : pr_of(lead);
        for (int m = n - 1; m >= 0; m--)
            if (rq_a[i0 + 4'(m)]) begin
                gkey.v = 1'b1;
                gkey.ms = rq_m[i0 + 4'(m)];
                gkey.idx = i0 + 4'(m);
                // (F3b) the member's ENCS; TB has no bank switching (f3_bsw tb_encs: vector 31
                // with ENCS written 1, TBIC's bit 4 reads 0)
                gkey.bs = !fixed7 && ic_b[8 * (i0 + 4'(m)) + 4];
            end
        gkey.v = gkey.v && (gkey.ms || ie);
    endfunction
    key_t k1 [0:5];
    key_t k2 [0:2];
    key_t k3 [0:1];
    reg   [3:0] isp_l = 4'd8;            // the highest level in service (8: none)
    function automatic logic [3:0] isp_f(input logic [7:0] p);
        isp_f = 4'd8;
        for (int b = 7; b >= 0; b--)
            if (p[b])
                isp_f = 4'(b);
    endfunction
    integer j;
    initial begin
        for (j = 0; j < 6; j++) k1[j] = '0;
        for (j = 0; j < 3; j++) k2[j] = '0;
        for (j = 0; j < 2; j++) k3[j] = '0;
        ir_h = 1'b0;
        ir_vec = 5'd0;
        ms_v = 1'b0;
        tk_ms = 1'b0;
        mc_ch = 3'd0;
        ms_mode = 3'd0;
        ms_dir = 1'b0;
        tk_bs = 1'b0;
        tk_lv = 3'd0;
        tk_int = 1'b0;
        nmi_v = 1'b0;
        i_wake = 1'b0;
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            for (j = 0; j < 6; j++) k1[j] <= '0;
            for (j = 0; j < 2; j++) k3[j] <= '0;
            isp_l <= 4'd8;
        end else if (ce_b) begin
            k1[0] <= gkey(3'd0, 4'd9, 3, 4'd9, 1'b0);      // TU
            k1[1] <= gkey(3'd1, 4'd12, 2, 4'd12, 1'b0);    // D
            k1[2] <= gkey(3'd2, 4'd0, 3, 4'd0, 1'b0);      // P
            k1[3] <= gkey(3'd3, 4'd3, 3, 4'd3, 1'b0);      // SER0
            k1[4] <= gkey(3'd4, 4'd6, 3, 4'd6, 1'b0);      // SER1
            k1[5] <= gkey(3'd5, 4'd14, 1, 4'd14, 1'b1);    // TB (level 7)
            k3[0] <= kmin(k2[0], k2[1]);
            k3[1] <= k2[2];
            isp_l <= isp_f(ispr);
        end
    end
    key_t kw;
    assign kw = kmin(k3[0], k3[1]);
    // (qprobe round 14, spec 10 I1) the scan's counter (`sc`, declared with the samplers above)
    // and EI's restart of it: IE rising after an E word that marks no boundary (nb: EI's, and
    // not a PSW load's, nbi: POP PSW, RETI). (WO32, Q78) A store to a request control register
    // restarts it too (`ic_st`: the IF write's own strobe; f5_ph_a / b / c: the period of the
    // takes after EI counts from the store; Q78 r18s: the vector read a fixed 50 clocks after
    // the store's write cycle as the store moves through 24 clocks)
    // (WO33, validation/v35s/lattice.py series a b c e: RESULTS section 1) any rise of IE restarts
    // the scan, whatever raised it (EI, POP PSW, RETI: `ie_up`), and so does a store to a request
    // control register (`ic_st`, any IE); nothing else does. A rise of IE in an offer slot (`sl`,
    // below) does not restart it: in the slot's first clock the slot's request is raised instead,
    // in its second nothing happens (k1 .. k9: the two phases of the 18-clock period)
    reg        ie_q = 1'b0;
    // (WO35) the offer slot: a level holding a request (lq) gets two clocks in front of its own
    // two (the round 16 + 2 a level holding one; lattice.py), the slot's first clock the level's
    // first (`sl_1`: the restart + 2 L when no lower level holds one, RESULTS section 9 B);
    // `sl` 1 the slot's second clock, 2 the level's first clock behind the slot (the counter
    // held through both)
    reg  [1:0] sl = 2'd0;
    wire       sl_1;
    // (WO35) the line: RESP, ACK (with the NMI delay, above)
    wire       [3:0] ACK_N;
    reg  [3:0] rq_c = 4'd0;
    assign ir_v = ir_h && rq_c == 4'd0;
    // (WO35) HALT's release with IE 0 at a slot (lattice.py w1 .. w9, WO33): decided in the
    // slot's second clock if the HALT stands then, it runs the controller's line as an offer
    // would (`hw_c`, one count: ACK and RESP as R's from a slot) and releases one stage before
    // the offer would reach the sample
    reg  [3:0] hw_c = 4'd0;
    // (WO50, the HALT loop) the loop alternates two halt words, B (the release test, HALT's own first word) and
    // A (the take test): `hb` is high on A's clock (the halt word that stood last clock was B), so B is
    // `halted && !hb`
    reg        hb = 1'b0;
    // (WO35) INT's two samples: R is set by INT seen high on two consecutive clocks (f5_pb_w_i:
    // a pulse two clocks wide is taken, one clock wide is not), the samples taken at ce_b from
    // v35_sfr's pin register (the pin as it stood at the clock's start: an edge half a clock
    // later is caught a clock later, f5_pa_i_wr against i_wr_h), R set at the ce_a behind them
    reg        int_q = 1'b0, int_q2 = 1'b0;
    wire       int_2 = int_q && int_q2;
    // (WO40) the rise that restarts the scan is IE's in the PSW register (`ie_r`); the slot's
    // claim (`sl_raise`) reads IE from the datum at the PSW word's read (`ie`): passage.py
    // f5_pe_* (the claim on silicon's clock) with periph f4_tb and f5_pa_q_reti7 (the restart a
    // clock behind it)
    wire       ie_up = ie_r && !ie_q;
    wire       ic_st = wr && (|ic_we);
    // (WO39) a rise in a slot's first clock never restarts the scan: that slot claims R whatever
    // better level is pending (passage.py f5_pe_*: WO38's `sl_ie` was not silicon's rule)
    // (WO40) where the rise falls is decided at the datum's rise (`d_up`, `ie`), the restart made
    // at the register's (`ie_up`): a POP PSW / RETI rise outside a slot's first two clocks leaves
    // `rs_k`, and the register's write a clock later restarts the scan whatever the scan then
    // stands at (no claim in that clock); EI's rise is the register's own (both in one clock)
    reg        ie_dq = 1'b0;
    reg        rs_k = 1'b0;
    wire       d_up = ie && !ie_dq;
    // (WO50, P5) EI's restart of the scan is a register behind IE's rise (`rs_e`), as POP PSW's and RETI's
    // are behind their datum's (`rs_k`): f5_lc_pb (DI ; EI) has its sampler threshold at silicon's sled
    // parity with it. And INT's claim sees EI's rise through the same register (`eu_q`, in r_set_i): with
    // the restart a clock later INTP0's naming is a clock later, and INT must not claim R ahead of it
    // (banks f3_int: PR 0 before INT)
    reg        rs_e = 1'b0;
    reg        eu_q = 1'b0;
    wire       rs_ie = (ie_up && !d_up && rs_k) || rs_e;
    // (WO43) and the acknowledge of a controller request or NMI (passage11: not BRK's entry, not
    // INT's; NMI's with nothing in service too)
    wire       rs_ak = ak_l && (tk_k[1] || tk_k[2]);
    wire       rs_sc = ic_st || rs_ie || rs_ak;
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            ie_dq <= 1'b0;
            rs_k <= 1'b0;
            rs_e <= 1'b0;
            eu_q <= 1'b0;
            ie_q <= 1'b0;
            int_q <= 1'b0;
            int_q2 <= 1'b0;
        end else begin
            if (ce_a) begin
                ie_q <= ie_r;
                ie_dq <= ie;
                rs_k <= d_up && !ie_r && !sl_1 && sl != 2'd1;
                rs_e <= ie_up && d_up && !sl_1 && sl != 2'd1;
                eu_q <= ie_up && d_up;
            end
            if (ce_b) begin
                int_q <= int_on;
                int_q2 <= int_q;
            end
        end
    end
    // (WO33, RESULTS sections 2 and 7 B) the levels holding a request the scan can offer: lq[L],
    // some group has an unmasked vectored request (rq) and its level is L, L above the highest
    // level in service (ISPR clear at L and below); IE plays no part (the slot stands with IE 0
    // too); macro service stays out (not measured: it is taken as before, ms_v). And the slot's
    // request (`sel`): the first group in the default order whose level is the scan's, its first
    // requesting member; both registered on ce_b from registers. (WO38) The exact form: any
    // level's slot raises its own request while R is clear, first come (passage.py RESULTS3
    // section 1.3, f5_pc_h70 / h07 / h73: a level found at its slot holds R and its vector
    // although a better level's flag stands or arrives after; WO33's reduced form, the slot
    // raising only at the highest level holding a request, gave the take to the better level a
    // round later)
    reg  [7:0]  lq = 8'd0;
    wire [7:0]  lq_n;
    reg         sel_v = 1'b0;
    reg  [3:0]  sel_i = 4'd0;
    reg         sel_bs = 1'b0;
    function automatic logic [7:0] lv_bit(input logic [2:0] l, input logic any);
        lv_bit = any ? 8'(8'd1 << l) : 8'd0;
    endfunction
    wire [5:0]  g_any = {rq[14], |rq[8:6], |rq[5:3], |rq[2:0], |rq[13:12], |rq[11:9]};
    wire [2:0]  g_lvl [0:5];
    assign g_lvl[0] = pr_of(4'd9);
    assign g_lvl[1] = pr_of(4'd12);
    assign g_lvl[2] = pr_of(4'd0);
    assign g_lvl[3] = pr_of(4'd3);
    assign g_lvl[4] = pr_of(4'd6);
    assign g_lvl[5] = 3'd7;
    wire [7:0]  isp_ok;                 // level L is above the highest in service
    genvar li;
    generate
        for (li = 0; li < 8; li++) begin : g_ispok
            assign isp_ok[li] = ~|ispr[li:0];
        end
    endgenerate
    // a group's first requesting vectored member (the fixed order within the group)
    function automatic logic [3:0] first_of(input logic [3:0] i0, input int n);
        first_of = i0;
        for (int m = n - 1; m >= 0; m--)
            if (rq[i0 + 4'(m)])
                first_of = i0 + 4'(m);
    endfunction
    wire [3:0]  g_first [0:5];
    assign g_first[0] = first_of(4'd9, 3);
    assign g_first[1] = first_of(4'd12, 2);
    assign g_first[2] = first_of(4'd0, 3);
    assign g_first[3] = first_of(4'd3, 3);
    assign g_first[4] = first_of(4'd6, 3);
    assign g_first[5] = 4'd14;
    assign lq_n = (lv_bit(g_lvl[0], g_any[0]) | lv_bit(g_lvl[1], g_any[1]) | lv_bit(g_lvl[2], g_any[2])
                   | lv_bit(g_lvl[3], g_any[3]) | lv_bit(g_lvl[4], g_any[4]) | lv_bit(g_lvl[5], g_any[5]))
                  & isp_ok;
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            lq <= 8'd0;
            sel_v <= 1'b0;
            sel_i <= 4'd0;
            sel_bs <= 1'b0;
        end else if (ce_b) begin
            lq <= lq_n;
            sel_v <= 1'b0;
            sel_i <= 4'd0;
            sel_bs <= 1'b0;
            for (int g = 5; g >= 0; g--)
                if (g_any[g] && g_lvl[g] == sc[3:1]) begin
                    sel_v <= isp_ok[sc[3:1]];
                    sel_i <= g_first[g];
                    sel_bs <= g != 5 && ic_b[8 * g_first[g] + 4];
                end
        end
    end
    // (WO35) the slot's first clock: the scan at a level's first clock (sc[0] 0) with a request
    // at that level (lq), no slot standing. The raise: in it, IE 1 as it stands (a rise in this
    // clock included); (WO38) at any level (the exact form, above); otherwise the slot passes
    // (as with IE 0)
    assign sl_1 = sl == 2'd0 && !sc[0] && lq[sc[3:1]];
    // (WO39) A rise of IE in a slot's first clock (EI, POP PSW, RETI) raises that slot's request
    // at once, whatever better level also holds one (passage.py f5_pe_*: the worse level's vector
    // at the first boundary in all eleven two-level programs and in a handler's RETI, f5_pe_h4),
    // as a slot does with IE standing: first come
    wire  sl_raise = sl_1 && ie && sel_v;
    // (WO35, RESULTS2 section 3: f5_pb_f*) the round with a level in service: the counter wraps
    // after the highest-priority level in service (P: isp_l), 2 (P + 1) clocks; FINT clears it
    // and the count runs on upward from where it stands
    // (WO40) WO39's switch FINT_RUN (no wrap on FINT's own clock) is gone: the count wraps by the
    // rule above on every clock (passage.py f5_pe_h4 / f5_pf_*: build/overseer/wo40/rtl.md); (WO41)
    // FINT's clear reaches ISPR a register behind FINT's first word (`fint_q`), and the round in
    // progress runs on to level 7 (passage8 RESULTS rule 2)
    wire  sc_wrap = !isp_l[3] && sc == {isp_l[2:0], 1'b1};
    // (WO35) R's set: a slot's raise, or INT seen high twice with IE 1, only while R is clear;
    // the slot first when both come in one clock (f5_pb_v0 / v7: a slot standing 2 clocks after
    // INT's edge wins). With both standing when IE rises, level 0 first (f3_int: PR 0 goes
    // before INT; the order is not measured otherwise): INT waits out the rise's clock while a
    // level-0 request stands, and the level-0 slot (the restart's first clock) claims R
    // (WO50, P5) INT sees EI's rise as the scan does, a register behind it (`eu_q`)
    wire  r_set_i = int_2 && ie && !(ie_up && d_up) && !(((ie_up && !d_up) || eu_q) && lq[0]);
    wire  sl_set = sl_raise && !rs_sc;    // (WO40) a restart in the slot's clock: no claim
    assign ACK_N = sl_set ? ACK : 4'd0;
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            for (j = 0; j < 3; j++) k2[j] <= '0;
            ir_h <= 1'b0;
            ir_int <= 1'b0;
            rq_c <= 4'd0;
            hw_c <= 4'd0;
            hb <= 1'b0;
            nmi_v <= 1'b0;
            i_wake <= 1'b0;
            ms_v <= 1'b0;
            ms_i <= 4'd0;
            sc <= 4'd0;
            sl <= 2'd0;
            dv <= 1'b0;
        end else if (ce_a) begin
            k2[0] <= kmin(k1[0], k1[1]);
            k2[1] <= kmin(k1[2], k1[3]);
            k2[2] <= kmin(k1[4], k1[5]);
            // (qprobe round 14-16, spec 10 I1 / I3) the level scan (`sc`: level sc[3:1], two
            // clocks a level, 16 a round; (WO33) a rise of IE and a request control store restart
            // it at level 0, `rs_sc`; (WO35) 2 (P + 1) with level P in service). (WO35) A level
            // holding a request (lq) gets its slot at its first clock (`sl_1`), the counter held
            // for the slot's second clock (`sl` 1) and the level's first (`sl` 2): the round is
            // 16 + 2 clocks a level holding a request
            if (rs_sc) begin
                sc <= 4'd0;
                sl <= 2'd0;
                dv <= 1'b0;
            end else begin
                dv <= !dv;
                case (sl)
                    2'd0: if (sl_1) sl <= 2'd1; else sc <= sc_wrap ? 4'd0 : sc + 4'd1;
                    2'd1: sl <= 2'd2;
                    default: begin
                        sl <= 2'd0;
                        sc <= sc + 4'd1;
                    end
                endcase
            end
            // (WO35) R (`ir_h`): set first come (above), held when INT drops (f5_pb_w_i, g_i);
            // cleared by IE 0 (DI, a PSW load: f5_pb_d_*, k_i, z_i: no take ever pushes IE 0, a
            // caught request is gone after the next EI) and by the take; a slot's request also by
            // its IF, its mask or the level against ISPR (as before; not measured). The slot's
            // raise loads its request (`sel`); the line's count (`rq_c`) loads at the set
            // (WO38) a slot's R is dropped by any store to a request control register (`ic_st`;
            // RESULTS3 section 1.3, f5_pc_m_mk / m_if / m_id / m_pr: the mask, the flag cleared,
            // the register rewritten as it stands, another level: no take; the request, still
            // standing, is found again from the scan's restart the store makes and runs its
            // whole count), and no slot sets R on the store's clock. INT's R is not (not
            // measured: INT is not a controller request)
            if (ir_h) begin
                ir_h <= ie && !take_i && (ir_int || (!ic_st && rq[ir_i] && {1'b0, ir_l} < isp_l));
                if (rq_c != 4'd0)
                    rq_c <= rq_c - 4'd1;
            end else begin
                ir_h <= sl_set || r_set_i;
                ir_int <= !sl_set;
                rq_c <= ACK_N + RESP - 4'd2;
                ir_vec <= vec_of(sel_i);
                ir_i <= sel_i;
                ir_l <= sc[3:1];
                ir_bs <= sel_bs;
            end
            // (WO35) HALT's release with IE 0: decided in a slot's second clock with the HALT
            // standing (any level), through the controller's line; the first slot's count runs
            // out undisturbed (a later slot's second clock does not reload it: with two levels
            // holding requests their slots come 10 clocks apart, less than the count, and a
            // reload would hold the HALT for ever: lattice.py w2 / w4 / w9)
            // (WO50, the HALT loop) the count starts where the loop's release test B stands in the slot's
            // second clock or the level's first clock behind it (B is tested every second clock, so one of the
            // two finds it), and it is ACK + RESP - 4: the old stall's ACK + RESP - 2 less the loop's two words
            // (the count starts at B's clock, two words later than the halted stall's start, and the E still
            // follows the count's start by the same line: f5_la_w1 .. w9)
            hb <= halted && !hb;
            if ((sl == 2'd1 || sl == 2'd2) && halted && !hb && !ie && hw_c == 4'd0)
                hw_c <= ACK + RESP - 4'd4;
            else if (hw_c != 4'd0)
                hw_c <= hw_c - 4'd1;
            ms_v <= kw.v && kw.ms && {1'b0, kw.lvl} < isp_l;
            ms_i <= kw.idx;
            nmi_v <= nmi_p && !(ak_l && tk_k[2]);
            // (F3b) INT releases HALT with IE 0 (f3_int); (WO35) with IE 1 R releases it through
            // the line one stage before the offer reaches the sample (WO33's place: the E word
            // after HALT executes in the clock the offer arrives and the dispatch takes it as a
            // running boundary's would); with IE 0 a slot's release (`hw_c`) one stage before
            // an offer would arrive, the request left pending, the round going on. (WO50, the HALT
            // loop) R's term at rq_c 2, a clock ahead of the line's end: the loop's B reads the wake
            // registered (wake, then the sequencer's tick-B copy), the stall read it a clock later
            i_wake <= nmi_p || ir_v || (int_on && !ie) || (ir_h && rq_c == 4'd2) || hw_c == 4'd1;
        end
    end

    // ---- (step B) the take and STOP, moved in from v35_top (the same registers, ticks, terms) --
    // (F3) At a dispatch (the word after E: an instruction's start) the sequencer enters the
    // interrupt routine (urom/trap.uasm intr) instead of the instruction it popped when, the last
    // instruction's E word not marking the start as no boundary (`nb`: a prefix, EI, DI, a
    // segment register's load; f3_step), NMI is pending, or the controller offers a request and
    // IE is 1 ((WO35) `ie_arm`, IE at the last start, is gone for the maskable offer: R is cleared
    // by IE 0 and needs the line's 8 clocks behind IE's rise; `mi_arm` keeps only the NBI rule:
    // the start behind POP PSW, RETI and FINT takes no maskable request (f5_step2; f5_pa_e_reti:
    // RETI's refetch outlasts the line, one X runs all the same), or PSW.BRK is 1 now and was at the last start (`brk_arm`: the
    // single step after each instruction that ran with BRK set; f3_step). NMI first, then the
    // offer, then the step (f3_step2 step_intp). Every term is a register; `igo` overrides the
    // sequencer's ROM address last (UROM_INT in place of the DISP word's target: the loader's
    // decoded entry is not behind it)
    reg  brk_arm = 1'b0, nb_r = 1'b0, mi_arm = 1'b0;
    wire g_n = nmi_v;
    // (qprobe round 13, spec 9 C3) NMI at a dispatch is the request as the E word that took the
    // next opcode saw it (`ne`, loaded when an E word executes): the opcode taken then runs.
    // (WO38) "the E word" here and below is the instruction's look (`x_end`, v35_useq: the word
    // releasing the next opcode, held open over a dispatch held by the front end)
    reg  ne = 1'b0;
    wire g_nd = ne;
    // (qprobe round 14-16, spec 10 I2 / I3, spec 11 I7) the maskable offer and INT at a dispatch
    // are the requests as the E word that took the next opcode saw them (`ie_e`, as NMI's `ne`;
    // also loaded in the HALT stall, whose release dispatches without an E word); a maskable
    // request or INT raised before NMI is taken first (`mf`: first come at the request latch;
    // `mf_e` as the E word saw it), NMI then at the handler's first instruction. The string's
    // take point (sgo, x_tki) reads the offer as it stands
    reg  ie_e = 1'b0, mf = 1'b0, mf_e = 1'b0;
    // (WO35) the sample (`ie_e`, R through the line) ANDed with IE at the dispatch: a request DI or
    // POP PSW overtakes is never taken (f5_pb_d_*)
    // (WO38) and R still standing at the dispatch: a request withdrawn after the look (R
    // dropped by the mask, its flag, a request control store, ISPR) is not taken (RESULTS3
    // section 1.3: silicon never takes it; from the look on it starts the entry and drops it
    // where the vector is asked for, 10 clocks with no cycle: not built, the core takes nothing)
    // (WO40) IE at the dispatch and the take point from the register (`ie_r`): the datum's bypass
    // (`ie`) differs from it only in the clock a D word loads the PSW from a read (POP PSW's,
    // RETI's), never a DISP or TKI word's clock (an E word stands between), so the take is the same
    // and the bus datum leaves the take's enables (the tick-B path into tk_k / tk_i)
    wire g_i = ie_e && ie_r && mi_arm && ir_h;
    wire g_it = ir_v && ie_r && mi_arm;
    wire g_nd_f = g_nd && !(g_i && mf_e);
    wire g_s = brk && brk_arm;
    // (F4b) a macro-service request: taken at a start whatever IE (f4_ms ms_p0, IE 0); in HALT
    // the stall ends on it (`wake` OR ms_v) and the routine returns to the HALT (f4_ms ms_halt:
    // no release). (F4p) The resolution above takes it with the vectored requests (ms_v and
    // ir_v never stand together); NMI goes before it (validation/v35s/prio.py f4p_hb b_nmi_ms:
    // both held by a DMA burst, NMI's frame pushed, then the macro service at the handler's
    // first instruction)
    wire g_m = ms_v;
    // (F4c) a DMA request: taken at the start after the one that saw it (f4_dma step_w /
    // burst_w, the instruction after the TDMA store runs first; a store clearing EDMA lets one
    // more transfer through: f4_dm3 tdma_io); in single step and single transfer a take lets
    // one instruction run before the next, in burst and demand release not (back to back). In
    // HALT the stall ends on the request and the take needs no arm (f4_dma halt_io: transfers
    // in HALT, no release). (F4p) The arms are v35_dma's (`dm_go`, sampled at `dm_smp`: a start
    // or a string's take point that is not a DMA take); DMA goes first, before NMI, a macro
    // service and the maskable interrupt (validation/v35s/prio.py f4p_hb, f4p_hr: each
    // pair held by a DMA burst), so a burst holds every other request to its end
    // (F4c) a DMA transfer or a macro service taken out of HALT resumes at the HALT: its start is
    // no boundary for NMI or an interrupt (`rs_hlt` makes the routine's E word set nb_r), so the
    // HALT runs, is released by the pending request and the request is taken after it with the
    // HALT's next offset pushed (f4_dma halt: the DIC1 handler returns after the HALT)
    reg  rs_hlt = 1'b0;
    wire g_d = dm_go || (ms_hlt && dm_v);
    assign igo = !nb_r && (g_nd || g_m || g_d || g_i || g_s);
    // (F5e) a REP string's take point (a TKI word: urom/str.uasm, at an element's end when the
    // string goes on; silicon, intr.py f5_si_*): NMI or the maskable offer (IE 1 and armed: IE
    // as it stood at the string's own start) is taken there, whatever the start's `nb` (a
    // prefix before the REP: f5_repint); the single step is not (one trap per string, after
    // its last element: f5_si_long; NMI inside a stepped string: f5_si_nstep); (F5e) a macro
    // service and DMA waited for the next start: (F5f) no longer, below. The word's target is
    // the string's entry into urom/trap.uasm intr: the take strobes below latch the source as at
    // a dispatch; the PC pushed is `ist` (the first prefix's offset), so RETI re-enters the
    // whole prefixed string with CW as it stands.
    // (F5f) a macro service and a DMA request are taken there too, in the dispatch's order
    // ((F4p) DMA, NMI, macro service, the maskable offer: prio.py f4p_hr; validation/v35s/dma.py
    // f5_sdma, f5_sms, f5_sms_inv, f5_sasync: silicon serves both between a long string's
    // elements): their routines resume at tmpc, the string's first prefix, so the string goes
    // on with CW as it stands. A single-step DMA take there disarms the request as at a
    // dispatch (one element between transfers: f5_sdma st_movw), a burst does not (the
    // transfers back to back after the first element: bu_movw)
    // (WO50, the HALT loop) in HALT the loop's take test A reads `sgo`: NMI's and the maskable offer's, the
    // offer from rq_c 1 (a clock ahead of the line's end, `g_ih`), so that with IE 1 A sees the offer before
    // B sees the release ("the release becomes a take": the take's dispatch with no E, no fetch).
    // OPEN (DESIGN-INT 2.4): the loop's A / B phase against the offer is not settled: the first take is 4
    // clocks early or late in most f5_la_a / b / e / g frames (silicon's phase differs with and without a
    // fetch pending at HALT's pop; the selecting signal is not found: rows H1)
    // (WO50, item 8) The take test in HALT is the dispatch's own term (`igo`) seen ahead through the same
    // registers, so that A's yes is always the yes of `halt redisp` three clocks later: `halt redisp` with no
    // take would wait for a fetch the stopped prefetcher never makes (the core stands there for ever:
    // build/overseer/int-design2 DESIGN-INT2 5.1). igo is !nb_r && (g_nd || g_m || g_d || g_i || g_s); in HALT
    // no instruction runs, so nb_r, ie_r, mi_arm and the request's hold (`ir_h`) stand still from A to the
    // dispatch, NMI's `ne` follows `nmi_v` a clock behind, and g_i's ie_e follows the line's end (ir_v, rq_c
    // 0) a clock behind: A reads !nb_r with NMI's nmi_v and the offer at rq_c <= 1, so each of its terms
    // implies the matching term of igo at the dispatch. (The other choice, `halt redisp` falling back to B
    // when nothing is taken, needs a new sequencer target for a halt word's dispatch.)
    wire g_ih = ir_h && rq_c <= 4'd1 && ie_r && mi_arm;
    assign sgo = halted ? (!nb_r && (g_n || g_ih)) : (g_n || g_it || g_m || g_d);
    assign take_d = (x_disp && igo && g_d) || (x_tki && g_d);
    assign take_n = (x_disp && igo && !g_d && g_nd_f) || (x_tki && !g_d && g_n);
    assign take_m = (x_disp && igo && !g_d && !g_nd_f && g_m) || (x_tki && !g_d && !g_n && g_m);
    assign dm_rs = x_disp && !take_d;           // (F4c) the CPU resumes: DIC's IF set here
    assign dm_smp = (x_disp || x_tki) && !take_d;
    assign take_i = (x_disp && igo && !g_nd_f && !g_m && !g_d && g_i)
                    || (x_tki && !g_n && !g_m && !g_d && g_it);
    assign take_s = x_disp && igo && !g_nd_f && !g_m && !g_d && !g_i;
    // (F4c) the parameters from one place: a DMA take's channel in place of the macro service's
    assign ms_ch = tk_dm ? {2'b00, dm_ch} : mc_ch;
    initial begin
        tk_dm = 1'b0;
        ms_hlt = 1'b0;
    end
    always @(posedge clock) begin
        if (!reset_n) begin
            brk_arm <= 1'b0;
            mi_arm <= 1'b0;
            nb_r <= 1'b0;
            ne <= 1'b0;
            ie_e <= 1'b0;
            mf <= 1'b0;
            mf_e <= 1'b0;
            ms_hlt <= 1'b0;
            tk_dm <= 1'b0;
            rs_hlt <= 1'b0;
        end else if (ce_a) begin
            if (x_disp) begin
                brk_arm <= brk;
                mi_arm <= 1'b1;
            end
            if (take_d)
                tk_dm <= 1'b1;
            else if (take_n || take_m || take_i || take_s)
                tk_dm <= 1'b0;
            // (WO38) the look (x_end) may come before the E word (an early `ro`) or stand open
            // over the held dispatch: an E word marking no boundary sets it whenever it executes;
            // (WO50) and on every clock of HALT's loop, so the release E's NBI reaches the controller
            if (x_end || x_nb || halted)
                nb_r <= x_nb || rs_hlt;
            // (qprobe round 13) NMI as the E word sees it; cleared by its take
            if (take_n)
                ne <= 1'b0;
            else if (x_end || halted)     // (WO50) as nb_r: in HALT's loop too
                ne <= nmi_v;
            // (qprobe round 14-16) the maskable offer / INT and its order against NMI, as the E
            // word (or the HALT stall) sees them; cleared by their take
            mf <= ir_v && (mf || !nmi_v);
            if (take_i) begin
                ie_e <= 1'b0;
                mf_e <= 1'b0;
            end else if (x_end || halted) begin
                ie_e <= ir_v;
                mf_e <= mf;
            end
            // (F5c) POP PSW, RETI, FINT (seg=NBI on the E word): the interrupt arms dropped, so
            // the next start takes neither the maskable interrupt nor the single step (NMI,
            // macro service and DMA are not held); the dispatch reloads them from the PSW
            if (x_nbi) begin
                brk_arm <= 1'b0;
                mi_arm <= 1'b0;
            end
            if (take_d || take_m)
                rs_hlt <= ms_hlt;
            else if (x_disp)
                rs_hlt <= 1'b0;     // (WO38) to the routine's dispatch (its look may repeat)
            // (F4b) the stall of a HALT seen since the last start that was not a macro service's
            if (halted)
                ms_hlt <= 1'b1;
            else if (x_disp && !take_m && !take_d)
                ms_hlt <= 1'b0;
        end
    end
    // (F4d) STOP (urom/xfer_stop.uasm: a halt word with cnt=stop). While it stands (`stp`, set
    // when that word executes) the halted stall's release is the settling count's end alone: NMI
    // pending (nmi_v) counts 2^19 CPU clocks (`st_c`), then `st_rel` releases it (f4_stop: the
    // first cycle 2^19 + 38 clocks after NMI's edge; IE 1 or 0); the controller's wake (an
    // unmasked IF, INT), a macro service and DMA do not (f4_stop stop_intp); the INTP samplers
    // hold (`frz`). The release pops the instruction after STOP, whose dispatch takes NMI. The
    // count is its own 19-bit counter (not the time base's: its taps keep running, as measured
    // in HALT; the time base in STOP is not measured)
    reg  [18:0] st_c = 19'd0;
    reg         st_rel = 1'b0;
    always @(posedge clock) begin
        if (!reset_n) begin
            stp <= 1'b0;
            st_c <= 19'd0;
            st_rel <= 1'b0;
        end else if (ce_a) begin
            if (stp && st_rel)
                stp <= 1'b0;
            else if (x_stop)
                stp <= 1'b1;
            if (!stp) begin
                st_c <= 19'd0;
                st_rel <= 1'b0;
            end else if (nmi_v && !st_rel) begin
                st_c <= st_c + 19'd1;
                st_rel <= &st_c;
            end
        end
    end
    assign wake = (stp || w_stop) ? st_rel : (i_wake || ms_v || dm_v);
`ifndef SYNTHESIS
    // (WO33) +v35_idbg=FILE: the scan's state on every CPU clock with an event (t counts ce_a
    // from the reset exit, as v35_trace's): a restart, the raise, the offer, the release, a take
    integer idbg_fd = 0;
    string  idbg_fn;
    reg [31:0] idbg_t = 32'd0;
    reg        idbg_run = 1'b0;
    initial if ($value$plusargs("v35_idbg=%s", idbg_fn)) idbg_fd = $fopen(idbg_fn, "w");
    always @(posedge clock) begin
        if (!reset_n) begin
            idbg_t <= 32'd0;
            idbg_run <= 1'b0;
        end else if (ce_a) begin
            if (idbg_fd != 0 && (!idbg_run || rs_sc || ir_h || sl_1 || i_wake || iack
                                 || (x_disp && igo) || (ie != ie_q) || (ie_r != ie_q)))
                $fdisplay(idbg_fd, "%0d sc=%0d sl=%0d%0d lq=%02x ie=%0d rs=%0d%0d h=%0d d=%0d v=%0d w=%0d hl=%0d tk=%0d ia=%0d xe=%0d kw=%0d:%0d:%0d",
                          idbg_t, sc, sl, sl_1, lq, ie, rs_ie, ic_st, ir_h, rq_c, ir_v, i_wake, halted,
                          x_disp && igo, iack, x_end, kw.v, kw.lvl, kw.idx);
            idbg_run <= 1'b1;
            idbg_t <= idbg_t + 32'd1;
        end
    end
`endif
endmodule
/* verilator lint_on DECLFILENAME */

// ============================================================================================
// (F4) The timer unit (docs/v35s-differences.md section 8; README "F4"), measured on the
// socket (validation/v35s/periph.py: f4_tm, f4_tout; receipts validation/v35s/receipts/f4-*).
// Beside v35_sfr, which decodes the stores and reads the registers through its registered read.
// Every register counts at ce_a (the CPU clock, SCLK).
//
//   interval  TMC0 MOD0 0: TM0 counts down at SCLK/6 (TCLK0 0) or /128; at 0 it reloads from MD0
//             and raises TMIC0: the period is (MD0 + 1) x the prescale (TOUT: 600 clocks for
//             MD0 99 at /6). TM1 the same (TMC1; /6 or /128), raising TMIC1 and TMIC2 both
//   start     a TMC0 store with TS0 1 (also when TS0 was already 1) loads TM0 from MD0 (f4_tout
//             tout_rs: TM0 20 at the start is not counted; tout_flip: a rewrite while running
//             moves the next count-out); TMC1 with TS1 likewise
//   one-shot  MOD0 1: TM0 (TS0; SCLK/12 or /128 by TCLK0) and MD0 (MS0; /12 or /128 by MCLK)
//             count down from their own values; each at 0 raises TMIC0 / TMIC1 and clears its
//             start bit (TMC0 reads 01h after both: f4_tm tm0_os)
//   stopped   the count holds (tm_hold)
//   TOUT      a flop q (1 at reset and at each start from TS0 0) toggled at TM0's count-outs;
//             the pin is q ^ ALV while ENT0 is 1, else ~ALV (f4_tout: every store's level)
// The count-out is a registered strobe (`tf`, one ce_a); v35_intc sets the IF from it.
//
// (WO32) The count clocks are one chain from reset (validation/v35s/phase.py f5_ph_g / g1 / g2 /
// g3, RESULTS sections 5, 6), not prescalers restarted at the store:
//   /6    the count edge of the bus unit's grid: a copy of its divide-by-six (`gph`, the same
//         reset and enable as v35_bus's, so no wire joins them), the edge K6 = 4 clocks after
//         the clock at which a timer register's wait ends (gph == G_REL): 2.5 clocks after the
//         grid point on silicon's pins (a timer register's cycle ends on the grid point), the
//         RTL's pin half a clock earlier (its pin phase, README "Work order 31")
//   /12   every second /6 edge from reset (`h12` halves the grid count: {h12, gph} is the
//         clock count mod 12): silicon's one-shot count-out at n = 8.5 mod 12
//   /128  a seven-bit count of the clock from reset (`t128`) whose carry (`k128`) is held until
//         the next /12 edge (silicon's count-outs 132, 132, 120 clocks apart, all on /12 edges)
//   Each phase is stated against the grid's point (G_REL + K mod 6, 12, 128), so the chain
//   moves with the grid's constant.
//   A start (or the MD0 one-shot's MS0) is taken on the first edge of its clock after the
//   store, which does not count (`s0`, `sm`, `s1`): TM0's first count is the second edge (f4_tout:
//   the first count-out 604 clocks after the start's TOUT level at /6; f5_ph_g: 76 or 82
//   clocks to the one-shot's count-out at /12 by the grid point the start lands on)
/* verilator lint_off DECLFILENAME */
module v35_timer (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        we,              // an SFR store at this ce_a (v35_sfr's decode) ...
    input  wire [7:0]  w_off,           // ... its offset, width, bytes
    input  wire        w_word,          // ((WO31) a byte of a word: the pair's)
    input  wire [7:0]  w_lo,            // ((WO31) the datum's lanes: the byte at an even offset is
    input  wire [7:0]  w_hi,            //   w_lo, at an odd offset w_hi; a word's both at its high byte)
    output reg  [15:0] tm0,
    output reg  [15:0] md0,
    output reg  [15:0] tm1,
    output reg  [15:0] md1,
    output reg  [7:0]  tmc0,
    output reg  [7:0]  tmc1,
    output wire        tout,
    output reg  [2:0]  tf,              // TMIC0-2's request (a ce_a strobe)
    output wire [2:0]  tfp              // (WO50, P8) the count-out being made in this clock (tf's terms)
);
    localparam logic [7:0] O_TM0 = 8'h80, O_MD0 = 8'h82, O_TM1 = 8'h88, O_MD1 = 8'h8A,
                           O_TMC0 = 8'h90, O_TMC1 = 8'h91;
    wire os = tmc0[0];                  // one-shot (MOD0)
    // ---- (WO32) the count clocks: one chain from reset, phased against the grid's point
    // K: each clock's edge in clocks after the ce_a at which a timer register's wait ends
    // (gph == G_REL), modulo the chain's period; with silicon's grid against reset (G_REL = 3)
    // the counters' phases are silicon's n (clock boundaries after the release: n = t + 25 for
    // the t-th ce_a, the FFFF0h fetch at n = 25 on both): /6 at n = 2 mod 6, /12 at n = 8 mod 12,
    // the /128 carry at n = 73 mod 128 (the pins a half clock before silicon's 2.5, 8.5; the
    // carry anywhere in n = 72 .. 75 gives silicon's count-outs, 76.5 / 80.5 / 84.5 mod 128:
    // RESULTS section 5's 4-clock window). With another G_REL the chain moves with the grid
    localparam int K6 = 4;              // /6: 2 clocks after the grid point (the wait's last clock is the next)
    localparam int K12 = K6;            // /12: the /6 edge at n = 8 mod 12, not 2
    localparam int K128 = 45;           // the /128 carry
    localparam int P12 = (int'(v35_front_pkg::G_REL) + K12) % 12;
    localparam logic [2:0] P6 = 3'(P12 % 6);
    localparam logic       H12 = 1'(P12 / 6);
    localparam logic [6:0] P128 = 7'((int'(v35_front_pkg::G_REL) + K128) % 128);
    reg  [2:0] gph = 3'd0;              // the grid's divide-by-six (v35_bus's copy)
    reg        h12 = 1'b0;              // ... halved: {h12, gph} counts the clock mod 12
    reg  [6:0] t128 = 7'd0;             // the clock mod 128
    reg        k128 = 1'b0;             // its carry, held to the next /12 edge
    wire       e6 = gph == P6;
    wire       e12 = e6 && h12 == H12;
    wire       e128 = e12 && k128;
    // each count's clock: TM0 /6, /12 (one-shot) or /128 (TCLK0); MD0 /12 or /128 (MCLK); TM1 /6
    // or /128 (TCLK1)
    wire       c0 = tmc0[6] ? e128 : os ? e12 : e6;
    wire       cm = tmc0[4] ? e128 : e12;
    wire       c1 = tmc1[6] ? e128 : e6;
    reg        s0 = 1'b0, sm = 1'b0, s1 = 1'b0;    // a start not yet taken by its clock's edge
    wire       co0 = tmc0[7] && c0 && !s0 && (os ? tm0 == 16'd1 || tm0 == 16'd0 : tm0 == 16'd0);
    wire       com = os && tmc0[5] && cm && !sm && (md0 == 16'd1 || md0 == 16'd0);
    wire       co1 = tmc1[7] && c1 && !s1 && tm1 == 16'd0;
    assign tfp = {co1, co1 || com, co0};
    reg        q = 1'b1;
    assign tout = tmc0[3] ? q ^ tmc0[2] : !tmc0[2];
    // a store's byte at its offset ((WO31) a word is two byte stores, low offset first)
    wire        s_tmc0 = we && (w_off == O_TMC0);
    wire        s_tmc1 = we && (w_off == O_TMC1);
    wire [7:0]  v_tmc1 = w_hi;
    initial begin
        tm0 = 16'hFFFF; md0 = 16'hFFFF; tm1 = 16'hFFFF; md1 = 16'hFFFF;
        tmc0 = 8'd0; tmc1 = 8'd0; tf = 3'd0;
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            gph <= 3'd0; h12 <= 1'b0; t128 <= 7'd0; k128 <= 1'b0;
        end else if (ce_a) begin
            gph <= gph == 3'd5 ? 3'd0 : gph + 3'd1;
            if (gph == 3'd5)
                h12 <= !h12;
            t128 <= t128 + 7'd1;
            if (t128 == P128)
                k128 <= 1'b1;
            else if (e12)
                k128 <= 1'b0;
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            tm0 <= 16'hFFFF; md0 <= 16'hFFFF; tm1 <= 16'hFFFF; md1 <= 16'hFFFF;
            tmc0 <= 8'd0; tmc1 <= 8'd0; tf <= 3'd0; q <= 1'b1;
            s0 <= 1'b0; sm <= 1'b0; s1 <= 1'b0;
        end else if (ce_a) begin
            tf <= 3'd0;
            // ---- the counts
            if (tmc0[7] && c0) begin
                s0 <= 1'b0;
                if (!s0) begin
                    if (os ? tm0 == 16'd1 || tm0 == 16'd0 : tm0 == 16'd0) begin
                        tf[0] <= 1'b1;
                        q <= !q;
                        if (os) begin
                            tmc0[7] <= 1'b0;
                            tm0 <= 16'd0;
                        end else
                            tm0 <= md0;
                    end else
                        tm0 <= tm0 - 16'd1;
                end
            end
            if (os && tmc0[5] && cm) begin
                sm <= 1'b0;
                if (!sm) begin
                    if (md0 == 16'd1 || md0 == 16'd0) begin
                        tf[1] <= 1'b1;
                        tmc0[5] <= 1'b0;
                        md0 <= 16'd0;
                    end else
                        md0 <= md0 - 16'd1;
                end
            end
            if (tmc1[7] && c1) begin
                s1 <= 1'b0;
                if (!s1) begin
                    if (tm1 == 16'd0) begin
                        tf[2:1] <= 2'b11;
                        tm1 <= md1;
                    end else
                        tm1 <= tm1 - 16'd1;
                end
            end
            // ---- the stores (after the counts: a store wins); (WO31) a 16-bit register whole at
            // its word's high byte (the second byte cycle), a lone byte ignored
            if (we && w_word && w_off == (O_TM0 | 8'd1))
                tm0 <= {w_hi, w_lo};
            if (we && w_word && w_off == (O_MD0 | 8'd1))
                md0 <= {w_hi, w_lo};
            if (we && w_word && w_off == (O_TM1 | 8'd1))
                tm1 <= {w_hi, w_lo};
            if (we && w_word && w_off == (O_MD1 | 8'd1))
                md1 <= {w_hi, w_lo};
            if (s_tmc0) begin
                tmc0 <= w_lo & 8'hFD;
                if (w_lo[7]) begin
                    s0 <= 1'b1;
                    if (!w_lo[0])
                        tm0 <= md0;
                    if (!tmc0[7])
                        q <= 1'b1;
                end
                if (w_lo[5])
                    sm <= 1'b1;
            end
            if (s_tmc1) begin
                tmc1 <= v_tmc1 & 8'hC0;
                if (v_tmc1[7]) begin
                    s1 <= 1'b1;
                    tm1 <= md1;
                end
            end
        end
    end
endmodule

// (F4) The time base counter: 20 bits at the CPU clock from reset; PRC TB1-0 picks the tap
// (2^10, 2^13, 2^16, 2^20 clocks; f4_tb, f4_tbl) whose carry raises TBIC (a ce_a strobe).
module v35_tbc (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire [1:0]  tb,
    output reg         tbf
);
    reg [19:0] c = 20'd0;
    initial tbf = 1'b0;
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            c <= 20'd0;
            tbf <= 1'b0;
        end else if (ce_a) begin
            c <= c + 20'd1;
            case (tb)
                2'd0: tbf <= &c[9:0];
                2'd1: tbf <= &c[12:0];
                2'd2: tbf <= &c[15:0];
                default: tbf <= &c;
            endcase
        end
    end
endmodule
/* verilator lint_on DECLFILENAME */

// ============================================================================================
// (F4b) A serial channel (docs/v35s-differences.md section 8; README "F4 (part B)"), measured on
// the socket (validation/v35s/serial.py: f4_stx, f4_srx, f4_sio; receipts
// validation/v35s/receipts/f4-f4_s*). Beside v35_sfr, which keeps SCM / SCC / BRG in its storage
// (read back there) and decodes the stores; this module holds TxB's and RxB's state and SCE.
// Every register updates at ce_a (the CPU clock).
//
//   baud      a bit is BRG x 2^(n+1) clocks, n = SCC (f4_stx: SCC 0 x 32 = 64, 3 x 5 = 80, 1 x 13
//             = 52, 0 x 40 = 80 on channel 1; f4_srx: 3 x 6 = 96); `per`, a register
//   transmit  a TxB store fills the buffer; it moves to the shift register when the shifter is
//             idle, TxRDY (SCM bit 7) is 1 and (asynchronous mode) /CTS is low, raising STIC (the
//             `st` strobe); a TxRDY store 0 -> 1 with the buffer empty raises it too (f4_stx: IF at
//             the enable). The asynchronous frame: start, 7 / 8 data bits LSB first, the parity
//             bit (SCM PRTY 01: 0, 10 odd, 11 even), 1 / 2 stop bits; frames back to back. A
//             character in flight ends whatever TxRDY or /CTS do (tx_dis, tx_cts); /CTS is
//             looked at only at the move
//   I/O mode  channel 0, SCM MD 00 (f4_sio): 8 bits MSB first, SCK0 low the first half of each
//             bit (the datum changes at its fall), high the second; TxD keeps the last bit until
//             TxRDY is cleared. Receive: with RSCK (SCM bit 2) 1 a store with TSK (bit 3) 1 and
//             RxE 1 clocks 8 bits in on the RSCK output (/CTS0's pin: low, high, the datum taken
//             at the rise; f4_sio2: RxE alone, or a transmit, does not); with RSCK 0 the datum is
//             taken at each rise of /CTS0 (8 rises a byte)
//   receive   asynchronous: a fall of RxD starts a frame; half a bit later a high RxD drops it (the
//             start glitch, rx_glitch); each bit is taken at its middle; at the first stop bit's
//             middle RxB <- the data (bit 7 0 with 7 bits), SCE's flags <- this character's
//             (ERP the parity, unless PRTY 01; ERF the stop bit 0; ERO the buffer not read since
//             the last character), SRIC raised, SEIC too on an error (f4_srx: both IF bits)
//   SCE       {RxD's level, 0000, ERP, ERF, ERO}; the flags are replaced at each character, not
//             cleared by a read; an RxB read (`rd_rxb`: the on-chip read cycle of RxB, also macro
//             service's) empties the buffer. RxB is not reset (silicon keeps it through reset)
/* verilator lint_off DECLFILENAME */
module v35_serial #(parameter bit IO_MODE = 1'b1) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        s_scm,           // a store of SCM (its value) ...
    input  wire [7:0]  v_scm,
    input  wire        s_txb,           // ... of TxB (its value)
    input  wire [7:0]  v_txb,
    input  wire        s_bg,            // ... of SCC or BRG
    input  wire [7:0]  scm,             // the stored SCM / SCC / BRG (v35_sfr's storage)
    input  wire [7:0]  scc,
    input  wire [7:0]  brg,
    input  wire        rd_rxb,          // RxB read (a ce_a strobe)
    input  wire        rxd_in,          // RxD and /CTS as the board drives them (asynchronous)
    input  wire        cts_in,
    output reg  [7:0]  rxb,
    output wire [7:0]  sce,
    output reg         txd,
    output reg         sck,             // SCK0 (the I/O mode's transmit clock)
    output reg         rsck,            // RSCK0 (/CTS0's pin as the receive clock) ...
    output wire        rsck_oe,         // ... while it drives it
    output reg         sr,              // the SRIC / STIC / SEIC requests (ce_a strobes)
    output reg         st,
    output reg         se
);
    // the inputs, two flops (asynchronous to the core)
    reg [1:0] rx_s = 2'b11, ct_s = 2'b11;
    reg       rx_l = 1'b1, ct_l = 1'b1;     // the levels at the last clock (the edges)
    wire      rxd = rx_s[1];
    wire      cts = ct_s[1];
    wire      io = IO_MODE && scm[1:0] == 2'b00;
    wire      txrdy = scm[7], rxe = scm[6];
    wire      cl8 = scm[3], sl2 = scm[2];
    wire [1:0] prty = scm[5:4];
    assign rsck_oe = io && scm[2];

    // the bit time: BRG x 2^(n+1) clocks (BRG 0 taken as 256, n above 8 as 8)
    reg  [17:0] per = 18'd2;
    wire [3:0]  n = scc[3:0] > 4'd8 ? 4'd8 : scc[3:0];
    always_ff @(posedge clock)
        if (ce_a)
            per <= {9'd0, brg == 8'd0, brg} << (n + 4'd1);
    wire [17:0] half = {1'b0, per[17:1]};

    // ---- the transmitter
    reg        tbf = 1'b0;              // TxB full
    reg  [7:0] tb = 8'd0;
    reg        tbusy = 1'b0;
    reg  [11:0] tsh = 12'hFFF;          // the frame: LSB first (asynchronous), MSB first (I/O)
    reg  [3:0] tn = 4'd0;               // the bits left
    reg  [17:0] tc = 18'd0;             // the bit's clocks
    reg        tio = 1'b0;              // the frame in flight is an I/O-mode one
    wire       tgo = !tbusy && tbf && txrdy && (io || !cts);
    wire [7:0] t_d = tb & (cl8 ? 8'hFF : 8'h7F);
    wire       t_par = prty == 2'b01 ? 1'b0 : prty[0] ? ^t_d : !(^t_d);
    // the asynchronous frame: start, data, parity, the stop bits (1s fill)
    function automatic logic [11:0] aframe(input logic [7:0] d, input logic c8, input logic pe,
                                           input logic p);
        logic [11:0] f;
        f = 12'hFFF;
        f[0] = 1'b0;
        if (c8) begin
            f[8:1] = d;
            if (pe) f[9] = p;
        end else begin
            f[7:1] = d[6:0];
            if (pe) f[8] = p;
        end
        aframe = f;
    endfunction
    wire [3:0] t_len = (cl8 ? 4'd9 : 4'd8) + (prty != 2'b00 ? 4'd1 : 4'd0) + (sl2 ? 4'd1 : 4'd0);

    // ---- the receiver
    localparam logic [2:0] R_IDLE = 3'd0, R_START = 3'd1, R_BITS = 3'd2, R_ICK = 3'd3,
                           R_ECK = 3'd4;
    reg  [2:0] rs = R_IDLE;
    reg  [17:0] rc = 18'd0;
    reg  [3:0] rn = 4'd0;               // the bits taken
    reg  [8:0] rsh = 9'd0;              // asynchronous: data then parity, bit n at n; I/O: MSB first
    reg        rbf = 1'b0;              // RxB full (not read)
    reg  [2:0] rerr = 3'd0;             // {ERP, ERF, ERO}
    assign sce = {rxd, 4'd0, rerr};
    wire       r_pe = prty != 2'b00;
    wire [3:0] r_all = (cl8 ? 4'd8 : 4'd7) + (r_pe ? 4'd1 : 4'd0);   // the bits before the stop
    wire [7:0] r_data = cl8 ? rsh[7:0] : {1'b0, rsh[6:0]};
    wire       r_pb = cl8 ? rsh[8] : rsh[7];
    wire       r_perr = r_pe && prty != 2'b01 && ((^r_data ^ r_pb) != !prty[0]);

    initial begin
        rxb = 8'd0; txd = 1'b1; sck = 1'b1; rsck = 1'b1; sr = 1'b0; st = 1'b0; se = 1'b0;
    end
    always_ff @(posedge clock) begin
        rx_s <= {rx_s[0], rxd_in};
        ct_s <= {ct_s[0], cts_in};
        if (!reset_n) begin
            tbf <= 1'b0; tbusy <= 1'b0; tn <= 4'd0; tc <= 18'd0; tio <= 1'b0;
            txd <= 1'b1; sck <= 1'b1; rsck <= 1'b1; sr <= 1'b0; st <= 1'b0; se <= 1'b0;
            rs <= R_IDLE; rc <= 18'd0; rn <= 4'd0; rbf <= 1'b0; rerr <= 3'd0;
            rx_l <= 1'b1; ct_l <= 1'b1;
        end else if (ce_a) begin
            sr <= 1'b0;
            st <= 1'b0;
            se <= 1'b0;
            rx_l <= rxd;
            ct_l <= cts;
            // ---- transmit
            if (tgo) begin
                tbusy <= 1'b1;
                tbf <= 1'b0;
                st <= 1'b1;
                tc <= 18'd0;
                tio <= io;
                if (io) begin
                    tsh <= {4'hF, tb};
                    tn <= 4'd7;
                    txd <= tb[7];
                    sck <= 1'b0;
                end else begin
                    tsh <= aframe(tb, cl8, r_pe, t_par);
                    tn <= t_len;
                    txd <= 1'b0;
                end
            end else if (tbusy) begin
                tc <= tc + 18'd1;
                if (tio && tc + 18'd1 == half)
                    sck <= 1'b1;
                if (tc + 18'd1 == per) begin
                    tc <= 18'd0;
                    if (tn == 4'd0) begin
                        tbusy <= 1'b0;
                        if (!tio)
                            txd <= 1'b1;
                    end else begin
                        tn <= tn - 4'd1;
                        if (tio) begin
                            tsh <= {tsh[10:0], 1'b1};
                            txd <= tsh[6];
                            sck <= 1'b0;
                        end else begin
                            tsh <= {1'b1, tsh[11:1]};
                            txd <= tsh[1];
                        end
                    end
                end
            end else if (!io || s_bg)
                txd <= 1'b1;            // the mark: an I/O-mode TxD holds its last bit until an
                                        // SCC / BRG store (f4_sio: not at SCM's)
            if (s_scm && v_scm[7] && !txrdy && !tbf)
                st <= 1'b1;             // the enable with the buffer empty
            if (s_txb) begin
                tb <= v_txb;
                tbf <= 1'b1;
            end
            // ---- receive
            if (rd_rxb)
                rbf <= 1'b0;
            case (rs)
                R_IDLE: begin
                    rc <= 18'd0;
                    rn <= 4'd0;
                    if (rxe && !io && rx_l && !rxd)
                        rs <= R_START;
                    else if (rxe && io && !scm[2] && !ct_l && cts) begin
                        rsh <= {rsh[7:0], rxd};     // I/O mode, the external clock: the first rise
                        rn <= 4'd1;
                        rs <= R_ECK;
                    end
                end
                R_START: begin
                    rc <= rc + 18'd1;
                    if (rc + 18'd1 == half) begin
                        rc <= 18'd0;
                        rs <= rxd ? R_IDLE : R_BITS;
                    end
                    if (!rxe)
                        rs <= R_IDLE;
                end
                R_BITS: begin
                    rc <= rc + 18'd1;
                    if (rc + 18'd1 == per) begin
                        rc <= 18'd0;
                        if (rn == r_all) begin
                            rxb <= r_data;              // the stop bit's middle
                            rerr <= {r_perr, !rxd, rbf};
                            rbf <= 1'b1;
                            sr <= 1'b1;
                            se <= r_perr || !rxd || rbf;
                            rs <= R_IDLE;
                        end else begin
                            rsh[rn] <= rxd;
                            rn <= rn + 4'd1;
                        end
                    end
                    if (!rxe)
                        rs <= R_IDLE;
                end
                R_ICK: begin
                    rc <= rc + 18'd1;
                    if (rc + 18'd1 == half) begin
                        rsck <= 1'b1;
                        rsh <= {rsh[7:0], rxd};
                        rn <= rn + 4'd1;
                    end
                    if (rc + 18'd1 == per) begin
                        rc <= 18'd0;
                        if (rn == 4'd8) begin
                            rxb <= rsh[7:0];
                            rerr <= {2'b00, rbf};
                            rbf <= 1'b1;
                            sr <= 1'b1;
                            se <= rbf;
                            rs <= R_IDLE;
                        end else
                            rsck <= 1'b0;
                    end
                end
                R_ECK: begin
                    if (!ct_l && cts) begin
                        rsh <= {rsh[7:0], rxd};
                        rn <= rn + 4'd1;
                    end
                    if (rn == 4'd8) begin
                        rxb <= rsh[7:0];
                        rerr <= {2'b00, rbf};
                        rbf <= 1'b1;
                        sr <= 1'b1;
                        se <= rbf;
                        rs <= R_IDLE;
                    end
                    if (!rxe)
                        rs <= R_IDLE;
                end
                default: rs <= R_IDLE;
            endcase
            // the internal clock's start: a store with TSK and RxE (I/O mode, RSCK 1)
            if (IO_MODE && s_scm && v_scm[1:0] == 2'b00 && v_scm[2] && v_scm[3] && v_scm[6]
                && rs != R_ICK) begin
                rs <= R_ICK;
                rc <= 18'd0;
                rn <= 4'd0;
                rsck <= 1'b0;
            end
        end
    end
endmodule
/* verilator lint_on DECLFILENAME */

// ============================================================================================
// (F4c) The DMA controller's request side (README "F4 (part C)"), measured on the socket
// (validation/v35s/dma.py: f4_dma; receipts validation/v35s/receipts/f4-f4_dm*). The transfers
// are the EU's: a request here is taken at an instruction start like a macro service (v35_intc
// `take_d`) and urom/dma.uasm moves the data through the channel block in internal RAM
// (IDB:E00 + 8 x the channel: +0 SAR, +2 DAR, +4 DARH, +5 SARH, +6 TC). This module holds
// DMAM's mode, W and EDMA, the channels' requests and the take's descriptor (registers only).
//
//   DMAM   MD2-0 (7:5), W (4), EDMA (3), TDMA (2, a trigger: reads 0); EDMA cleared at TC 0
//   000 / 100  memory to memory, single step / burst: started by a TDMA store with EDMA (not by
//              DMARQ: f4_dm2 burst_rq, step_rq); single step: one instruction between transfers
//   101 / 110  single transfer, I/O to memory / memory to I/O: one transfer per DMARQ rising edge
//              (an edge before EDMA's store is not counted: f4_dm3 io_lvl)
//   001 / 010  demand release: transfers while DMARQ is high after its rising edge
//   011 / 111  reserved: no request
// The store of DMAM clears the channel's DMARQ flags (the data book: "When the EDMA bit is set,
// the internal DMARQ flag is cleared").
//   (F4p) the order (validation/v35s/prio.py f4p_dma, f4p_x2): at a start that is not a DMA take
//   (`smp`) the highest requesting channel (channel 0 first) is armed, and so is a channel that
//   has transferred and still asks (`act`: a single-step channel overtaken by the other one);
//   the next start takes the highest armed channel. A single-step or single-transfer take
//   disarms its channel and lets one instruction run (`gate`) unless it was the channel's last
//   (TC 0: the overtaken channel goes on at once: ss_10, ss1_bu0); a burst or demand take keeps
//   its channel armed while it asks, so the other channel, macro service, NMI and the maskable
//   interrupt wait for the burst's end (bu_10, bu1_rq0, f4p_hb) and a channel asking during a
//   burst is armed at the first start after it (one instruction runs first: bu_01, bu0_rq1)
module v35_dma (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        we,              // an SFR store (v35_sfr's p_we) ...
    input  wire [7:0]  w_off,           // ... its offset and byte ((WO31) a word is two byte stores)
    input  wire [7:0]  w_lo,
    input  wire [7:0]  dmac0,           // DMAC0 / DMAC1 (v35_sfr's storage): PD 5:4, PS 1:0
    input  wire [7:0]  dmac1,
    input  wire [1:0]  dmarq,           // the DMARQ0/1 levels (the input levels 6, 7)
    input  wire        take,            // v35_intc's take_d (a ce_a strobe at the dispatch)
    input  wire        tend,            // the routine's TC update (a ce_a strobe) ...
    input  wire        tlast,           // ... TC reached 0
    input  wire        rs,              // a start that is not a DMA take (v35_intc: the CPU resumes)
    input  wire        smp,             // (F4p) a start or a string's take point that is not a DMA take
    output wire [7:0]  dmam0,           // the DMAM bytes as read
    output wire [7:0]  dmam1,
    output reg         dm_v,            // a transfer is requested (a register)
    output wire        dm_go,           // (F4p) a channel is armed: the next start takes it
    output reg         tk_ch,           // the take's descriptor: the channel ...
    output reg         tk_in,           // ... I/O to memory (the destination side alone)
    output reg         tk_out,          // ... memory to I/O (the source side alone)
    output reg         tk_w,            // ... word transfers
    output reg  [1:0]  tk_ps,           // ... SAR's step (01 +, 10 -, else none)
    output reg  [1:0]  tk_pd,           // ... DAR's
    output reg  [1:0]  dic              // DIC0 / DIC1 IF set (ce_a strobes, pf_set 12 / 13)
);
    reg [2:0] md0 = 3'd0, md1 = 3'd0;
    reg [1:0] w = 2'b00, edma = 2'b00, go = 2'b00, pend = 2'b00, dfl = 2'b00;
    reg [1:0] rq_s = 2'b00, rq_r = 2'b00, rq_p = 2'b00;
    reg       pick = 1'b0;              // the channel the next take serves (kept while none asks)
    reg [1:0] arm = 2'b00;              // (F4p) the channels armed at the last sampling start
    reg [1:0] act = 2'b00;              // (F4p) the channels that have transferred (to TC 0)
    reg       gate = 1'b0;              // (F4p) a single take: one instruction runs first
    reg [1:0] dic_p = 2'b00;            // DIC's IF to be set when the CPU resumes (f4_dma dic: the
                                        // instruction after the last transfer runs before the
                                        // interrupt is taken)
    initial begin
        dm_v = 1'b0;
        tk_ch = 1'b0;
        tk_in = 1'b0;
        tk_out = 1'b0;
        tk_w = 1'b0;
        tk_ps = 2'd0;
        tk_pd = 2'd0;
        dic = 2'b00;
    end
    assign dmam0 = {md0, w[0], edma[0], 3'b000};
    assign dmam1 = {md1, w[1], edma[1], 3'b000};
    wire [1:0] s_m = {we && w_off == 8'hA3, we && w_off == 8'hA1};
    wire [7:0] v_m0 = w_lo;
    wire [7:0] v_m1 = w_lo;
    function automatic logic m2m(input logic [2:0] m);
        m2m = m[1:0] == 2'b00;
    endfunction
    function automatic logic single(input logic [2:0] m);
        single = m == 3'b101 || m == 3'b110;
    endfunction
    function automatic logic demand(input logic [2:0] m);
        demand = m == 3'b001 || m == 3'b010;
    endfunction
    function automatic logic chain(input logic [2:0] m);    // back to back while requested
        chain = m == 3'b100 || demand(m);
    endfunction
    function automatic logic req(input logic [2:0] m, input logic en, input logic g,
                                 input logic p, input logic d, input logic lvl);
        req = en && (m2m(m) ? g : single(m) ? p : demand(m) ? d && lvl : 1'b0);
    endfunction
    wire [1:0] rq = {req(md1, edma[1], go[1], pend[1], dfl[1], rq_r[1]),
                     req(md0, edma[0], go[0], pend[0], dfl[0], rq_r[0])};
    wire [7:0] dmac_p = pick ? dmac1 : dmac0;
    wire [1:0] win = rq[0] ? 2'b01 : {rq[1], 1'b0};    // the highest requesting channel
    assign dm_go = |arm && !gate;
    wire [2:0] md_p = pick ? md1 : md0;
    always_ff @(posedge clock) begin
        rq_s <= dmarq;
        rq_r <= rq_s;
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            md0 <= 3'd0;
            md1 <= 3'd0;
            w <= 2'b00;
            edma <= 2'b00;
            go <= 2'b00;
            pend <= 2'b00;
            dfl <= 2'b00;
            rq_p <= 2'b00;
            pick <= 1'b0;
            arm <= 2'b00;
            act <= 2'b00;
            gate <= 1'b0;
            dm_v <= 1'b0;
            dic <= 2'b00;
            dic_p <= 2'b00;
        end else if (ce_a) begin
            rq_p <= rq_r;
            dic <= rs ? dic_p : 2'b00;
            if (rs)
                dic_p <= 2'b00;
            // channel 0
            if (rq_r[0] && !rq_p[0] && edma[0]) begin
                if (single(md0))
                    pend[0] <= 1'b1;
                if (demand(md0))
                    dfl[0] <= 1'b1;
            end
            if (!rq_r[0])
                dfl[0] <= 1'b0;
            if (take && !pick)
                pend[0] <= 1'b0;
            if (tend && tlast && !tk_ch) begin
                edma[0] <= 1'b0;
                go[0] <= 1'b0;
                pend[0] <= 1'b0;
                dfl[0] <= 1'b0;
                dic_p[0] <= 1'b1;
            end
            if (s_m[0]) begin
                md0 <= v_m0[7:5];
                w[0] <= v_m0[4];
                edma[0] <= v_m0[3];
                go[0] <= v_m0[3] && v_m0[2] && m2m(v_m0[7:5]);
                pend[0] <= 1'b0;
                dfl[0] <= 1'b0;
            end
            // channel 1
            if (rq_r[1] && !rq_p[1] && edma[1]) begin
                if (single(md1))
                    pend[1] <= 1'b1;
                if (demand(md1))
                    dfl[1] <= 1'b1;
            end
            if (!rq_r[1])
                dfl[1] <= 1'b0;
            if (take && pick)
                pend[1] <= 1'b0;
            if (tend && tlast && tk_ch) begin
                edma[1] <= 1'b0;
                go[1] <= 1'b0;
                pend[1] <= 1'b0;
                dfl[1] <= 1'b0;
                dic_p[1] <= 1'b1;
            end
            if (s_m[1]) begin
                md1 <= v_m1[7:5];
                w[1] <= v_m1[4];
                edma[1] <= v_m1[3];
                go[1] <= v_m1[3] && v_m1[2] && m2m(v_m1[7:5]);
                pend[1] <= 1'b0;
                dfl[1] <= 1'b0;
            end
            // the request; (F4p) the arms and the pick: the highest armed channel, else (a take
            // out of HALT, no start) the highest requesting
            dm_v <= |rq;
            if (smp) begin
                arm <= arm | win | (act & rq);
                gate <= 1'b0;
            end
            if (take) begin
                act[pick] <= 1'b1;
                if (chain(md_p))
                    arm[pick] <= rq[pick];
                else begin
                    arm[pick] <= 1'b0;
                    gate <= 1'b1;
                end
            end
            if (tend && tlast) begin
                arm[tk_ch] <= 1'b0;
                act[tk_ch] <= 1'b0;
                gate <= 1'b0;
            end
            if (s_m[0])
                act[0] <= 1'b0;
            if (s_m[1])
                act[1] <= 1'b0;
            if (arm[0] || arm[1])
                pick <= !arm[0];
            else if (|rq)
                pick <= !rq[0];
            if (take) begin
                tk_ch <= pick;
                tk_in <= md_p[0] && !md_p[1];
                tk_out <= md_p[1] && !md_p[0];
                tk_w <= pick ? w[1] : w[0];
                tk_ps <= dmac_p[1:0];
                tk_pd <= dmac_p[5:4];
            end
        end
    end
endmodule
