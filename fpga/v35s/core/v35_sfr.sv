`timescale 1ns/1ps

// V35S special function registers: the SFR page IDB:F00-FFF (and IDB at FFFFF) as data, from
// the F1 measurements on the socket (validation/v35s/onchip.py; receipts
// validation/v35s/receipts/f1-f1_sfr_*-socket*.json; README "F1").
//
// Written by the core's on-chip store at its cycle's end (`wr`: the internal cycle, 3 + the I/O
// waits, no pins; the address, width and datum as issued). A word store at an even offset
// writes the offset and the next; a byte store writes its lane (an odd address the high one).
// Read by the on-chip read: `rd_off` (the cycle's offset, a register) -> `rd_data` registered
// at `ce_rd`, {the byte at offset | 1, the byte at offset & ~1}; the 16-bit registers (TM0, MD0,
// TM1, MD1) by word whole.
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
//   constant  SCE0/1 80h, STBC 00h (writes ignored: STOP / HALT are F4's), ISPR 00h, RxB0/1 00h
//             (silicon: undefined, kept through reset), FF0/FF1 00h, FF4 02h, FF7 C7h, FF8 4Eh,
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
    input  wire [19:0] addr,            // ... its address (IDB:Fxx or FFFFF), width (V35_BW_*), datum
    input  wire [1:0]  width,
    input  wire [15:0] data,
    output reg  [7:0]  prc,
    // (MX5c, the core v2's registered stall) PRC as it stands after a write of the cycle that
    // `wr_at` says ends at the coming write enable (wr_at: wr's condition without its enable)
    input  wire        wr_at,
    output wire [7:0]  prc_at,
    output reg  [15:0] wtc,
    output reg  [7:0]  rfm,
    output reg  [7:0]  idb,
    // (F1) the on-chip read
    input  wire        ce_rd,
    input  wire [7:0]  rd_off,
    input  wire        rd_word,
    output reg  [15:0] rd_data,
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
    output wire [14:0] pf_set
);
    localparam logic [7:0] PRC_RESET = 8'h4E;
    localparam logic [15:0] WTC_RESET = 16'hFFFF;
    localparam logic [7:0] RFM_RESET = 8'hFC;
    localparam logic [7:0] IDB_RESET = 8'hFF;
    localparam logic [1:0] BW_WORD = 2'd0, BW_HI = 2'd2;   // as v35/v35_front_pkg.sv (BW_LO 1)

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

    // ---- the storage: one byte per offset; the bits no write reaches are constants ----------
    // PRC, WTC, RFM and IDB are their own registers (the function bench sets PRC and WTC
    // through them: fpga/v35s/v35_core2_tb.cpp); their bytes in `st` are not read
    reg [7:0] st [0:255];
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
    wire        w_word = width == BW_WORD && !top;
    wire [7:0]  w_lo = width == BW_HI ? data[15:8] : data[7:0];
    always @(posedge clock) begin
        if (!reset_n) begin
            for (i = 0; i < 256; i = i + 1)
                st[i] <= rst(8'(i));
            prc <= PRC_RESET;
            wtc <= WTC_RESET;
            rfm <= RFM_RESET;
            idb <= IDB_RESET;
        end else if (wr && (top || in_page)) begin
            if (byte_ok(w_off, w_word))
                st[w_off] <= w_lo & wmask(w_off);
            if (w_word && byte_ok(w_off | 8'd1, 1'b1))
                st[w_off | 8'd1] <= data[15:8] & wmask(w_off | 8'd1);
            if (w_off == 8'hEB)
                prc <= w_lo & 8'h4F;
            if (w_word && (w_off | 8'd1) == 8'hEB)
                prc <= data[15:8] & 8'h4F;
            if (w_off == 8'hE1)
                rfm <= w_lo;
            if (w_word && (w_off | 8'd1) == 8'hE1)
                rfm <= data[15:8];
            if (w_off == 8'hE8)
                wtc[7:0] <= w_lo;
            if (w_off == 8'hE9)
                wtc[15:8] <= w_lo;
            if (w_word && (w_off | 8'd1) == 8'hE9)
                wtc[15:8] <= data[15:8];
            if (w_off == 8'hFF)
                idb <= w_lo;
        end
    end
    // (F3) the IC registers' bytes and the stores that write them (the IF bit is the controller's)
    genvar gi;
    generate
        for (gi = 0; gi < 15; gi++) begin : g_ic
            localparam logic [7:0] O = IC_OFF[8*gi +: 8];
            assign ic_b[8*gi +: 8] = st[O];
            wire lo_hit = w_off == O;
            wire hi_hit = w_word && (w_off | 8'd1) == O;
            assign ic_we[gi] = wr && in_page && !top && (lo_hit || hi_hit);
            assign ic_wd[gi] = lo_hit ? w_lo[7] : data[15];
        end
    endgenerate
    assign intm = st[8'h40];

    // FLAG: the store's byte (bits 5 and 3) into the PSW
    assign flag_we = wr && in_page && !top && w_off == 8'hEA;
    assign flag_d = {w_lo[5], w_lo[3]};

    // ---- (F4) the peripherals ----------------------------------------------------------------
    // the store as the peripherals see it: a byte at w_off (w_lo), with a word the next (data hi)
    wire        p_we = wr && in_page && !top;
    wire [15:0] tm0, md0, tm1, md1;
    wire [7:0]  tmc0, tmc1;
    wire        tout;
    wire [2:0]  tf;
    wire        tbf;
    v35_timer timer (.clock, .reset_n, .ce_a, .we(p_we), .w_off, .w_word, .w_lo,
                     .w_hi(data[15:8]), .tm0, .md0, .tm1, .md1, .tmc0, .tmc1, .tout, .tf);
    v35_tbc tbc (.clock, .reset_n, .ce_a, .tb(prc[3:2]), .tbf);
    // the IF bits raised: TMIC0-2 (9-11), TBIC (14)
    assign pf_set = {tbf, 2'b00, tf, 9'd0};

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
    // keepers: f4_tout, P13 stays high after PMC1 bit 3 is cleared). TxD0/1 idle high (the serial
    // channels are part B); CLKOUT is not built
    wire [31:0] pv = {6'd0, 2'b11, 1'b0, ~pm2[6:4] & p2l[6:4], 1'b0, ~pm2[2:1] & p2l[2:1],
                      1'b0, ~pm1[7:6] & p1l[7:6], pmc1[5] ? tout : p1l[5], ~pm1[4] & p1l[4],
                      intak_n, 3'd0, ~pm0 & p0l};
    wire [31:0] pd = {8'hFF, 1'b1, ~pm2[6:4], 1'b1, ~pm2[2:1], 1'b1, ~pm1[7:6],
                      pmc1[5] || !pm1[5], ~pm1[4], pmc1[3], 3'b111, ~pm0};
    initial pins = 32'h0300_0000;
    always_ff @(posedge clock)
        pins <= (pd & pv) | (~pd & pins);

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

    function automatic logic [7:0] prc_put(input logic [7:0] p, input logic [7:0] offset,
                                           input logic [7:0] value);
        prc_put = offset == 8'hEB ? (value & 8'h4F) : p;
    endfunction
    assign prc_at = (!wr_at || top || !in_page) ? prc
                  : width == BW_WORD ? prc_put(prc_put(prc, addr[7:0], data[7:0]),
                                               addr[7:0] | 8'd1, data[15:8])
                  : prc_put(prc, addr[7:0], width == BW_HI ? data[15:8] : data[7:0]);

    initial poll_p14 = 1'b0;
    always_ff @(posedge clock)
        poll_p14 <= input_levels[5] && st[8'h09][4];
    initial int_on = 1'b0;
    always_ff @(posedge clock)
        int_on <= input_levels[5] && st[8'h0A][4];
    wire unused = &{1'b0, input_levels[15:6], input_levels[4:0]};
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
//             MS 1 (macro service, not built) leaves it out
//   the take  the sequencer's dispatch takes the offer (v35_loader `go`); `iack` (the entry's
//             IVEC word) clears the taken source's IF and sets its level in ISPR (NMI: clears
//             its request); FINT clears ISPR's highest-priority bit (f3_prio)
//   HALT      `wake`: NMI or any IF with MK 0 (and MS 0); f3_vec: a masked request does not
//             release HALT
// The resolution is a pipeline of registers (the groups' keys, two minimum stages, the offer),
// two CPU clocks from an IF / MK / PR / ISPR change to the offer: the latency the sequencer's
// boundary sees after a store (silicon's is longer: f3_lat; the gate's programs place an
// absorber after each release). Every output is a ce_a register.
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
    input  wire        take_n,          // the dispatch took NMI / the offer / the single step
    input  wire        take_i,          //   (ce_a strobes, one clock)
    input  wire        take_s,
    input  wire        iack,            // the entry's IVEC word executes (ce_a strobe)
    input  wire        fint,            // FINT executes (ce_a strobe)
    input  wire        int_on,          // (F3b) the INT request (v35_sfr's register)
    input  wire [14:0] pf_set,          // (F4) the peripherals' requests (ce_a strobes: IF <- 1)
    output reg         it_v,            // (F3b) INT is offered (the take strobe take_i covers it)
    output reg         tk_bs,           // (F3b) the last take is a bank switch (ENCS 1) ...
    output reg  [2:0]  tk_lv,           // ... at this level (the new bank)
    output reg         tk_int,          // (F3b) the last take is INT
    output reg  [14:0] ic_if,
    output reg  [7:0]  ispr,
    output reg         ir_v,            // a maskable request is offered
    output reg  [4:0]  ir_vec,
    output reg         nmi_v,           // NMI is pending
    output reg         wake,            // HALT's release
    output reg  [4:0]  tk_vec           // the vector of the last take (IVEC's)
);
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
    wire [14:0] rq = ic_if & ~mk & ~ms;
    function automatic logic [2:0] pr_of(input logic [3:0] i);
        pr_of = ic_b[8*i +: 3];
    endfunction

    // ---- the edges (sampled at the CPU clock) and the request registers --------------------
    reg  [3:0] lv = 4'hF;               // NMI, INTP0-2 as last sampled
    wire [3:0] lvn = input_levels[4:1];
    wire [3:0] es = {intm[6], intm[4], intm[2], intm[0]};
    wire [3:0] edge_c = (es & lvn & ~lv) | (~es & ~lvn & lv);
    reg        nmi_p = 1'b0;
    reg  [2:0] tk_k = 3'd0;             // the last take: {NMI, the offer, the step}
    reg  [3:0] tk_i = 4'd0;
    reg  [2:0] tk_l = 3'd0;
    reg  [3:0] ir_i = 4'd0;
    reg  [2:0] ir_l = 3'd0;
    reg        ir_bs = 1'b0;            // (F3b) the offer's member has ENCS 1
    reg        it_sel = 1'b0;           // (F3b) a take now takes INT, not the offer
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
        end else if (ce_a) begin
            lv <= lvn;
            if (take_n || take_i || take_s) begin
                // (F3b) INT chosen over the controller's offer (it_sel) is not the offer's take
                tk_k <= {take_n, take_i && !take_n && !it_sel, take_s && !take_n && !take_i};
                tk_int <= take_i && !take_n && it_sel;
                tk_bs <= take_i && !take_n && !it_sel && ir_bs;
                tk_lv <= ir_l;
                tk_i <= ir_i;
                tk_l <= ir_l;
                tk_vec <= take_n ? 5'd2 : take_i ? ir_vec : 5'd1;
            end
            for (int k = 0; k < 15; k++) begin
                if (wr && ic_we[k])
                    ic_if[k] <= ic_wd[k];
                else if (iack && tk_k[1] && tk_i == 4'(k))
                    ic_if[k] <= 1'b0;
                if (k < 3 && edge_c[k + 1])
                    ic_if[k] <= 1'b1;
                if (pf_set[k])
                    ic_if[k] <= 1'b1;
            end
            if (iack && tk_k[1])
                ispr <= ispr | (8'd1 << tk_l);
            else if (fint)
                ispr <= fint_f(ispr);
            if (edge_c[0])
                nmi_p <= 1'b1;
            else if (iack && tk_k[2])
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
            if (rq[i0 + 4'(m)]) begin
                gkey.v = 1'b1;
                gkey.idx = i0 + 4'(m);
                // (F3b) the member's ENCS; TB has no bank switching (f3_bsw tb_encs: vector 31
                // with ENCS written 1, TBIC's bit 4 reads 0)
                gkey.bs = !fixed7 && ic_b[8 * (i0 + 4'(m)) + 4];
            end
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
        ir_v = 1'b0;
        ir_vec = 5'd0;
        it_v = 1'b0;
        tk_bs = 1'b0;
        tk_lv = 3'd0;
        tk_int = 1'b0;
        nmi_v = 1'b0;
        wake = 1'b0;
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
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            for (j = 0; j < 3; j++) k2[j] <= '0;
            ir_v <= 1'b0;
            nmi_v <= 1'b0;
            wake <= 1'b0;
            it_v <= 1'b0;
            it_sel <= 1'b0;
        end else if (ce_a) begin
            k2[0] <= kmin(k1[0], k1[1]);
            k2[1] <= kmin(k1[2], k1[3]);
            k2[2] <= kmin(k1[4], k1[5]);
            ir_v <= kw.v && {1'b0, kw.lvl} < isp_l;
            ir_vec <= vec_of(kw.idx);
            ir_i <= kw.idx;
            ir_l <= kw.lvl;
            ir_bs <= kw.bs;
            // (F3b) INT (f3_int): taken before a pending request of any level but 0 (PR 1-7
            // wait for INT's handler's RETI, PR 0 goes first); ISPR plays no part (INT sets no
            // ISPR bit: the data book's "NMI and INT end without FINT"; f3_int: ISPR 00)
            it_v <= int_on;
            it_sel <= int_on && !(kw.v && {1'b0, kw.lvl} < isp_l && kw.lvl == 3'd0);
            nmi_v <= nmi_p && !(iack && tk_k[2]);
            wake <= nmi_p || (|rq) || int_on;  // (F3b) INT releases HALT, IE 0 too (f3_int)
        end
    end
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
//   start     a TMC0 store with TS0 1 (also when TS0 was already 1) loads TM0 from MD0 and
//             restarts the prescaler (f4_tout tout_rs: TM0 20 at the start is not counted; tout_flip:
//             a rewrite while running moves the next count-out); TMC1 with TS1 likewise
//   one-shot  MOD0 1: TM0 (TS0; SCLK/12 or /128 by TCLK0) and MD0 (MS0; /12 or /128 by MCLK)
//             count down from their own values; each at 0 raises TMIC0 / TMIC1 and clears its
//             start bit (TMC0 reads 01h after both: f4_tm tm0_os)
//   stopped   the count holds (tm_hold)
//   TOUT      a flop q (1 at reset and at each start from TS0 0) toggled at TM0's count-outs;
//             the pin is q ^ ALV while ENT0 is 1, else ~ALV (f4_tout: every store's level)
// The count-out is a registered strobe (`tf`, one ce_a); v35_intc sets the IF from it.
/* verilator lint_off DECLFILENAME */
module v35_timer (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        we,              // an SFR store at this ce_a (v35_sfr's decode) ...
    input  wire [7:0]  w_off,           // ... its offset, width, bytes
    input  wire        w_word,
    input  wire [7:0]  w_lo,
    input  wire [7:0]  w_hi,
    output reg  [15:0] tm0,
    output reg  [15:0] md0,
    output reg  [15:0] tm1,
    output reg  [15:0] md1,
    output reg  [7:0]  tmc0,
    output reg  [7:0]  tmc1,
    output wire        tout,
    output reg  [2:0]  tf               // TMIC0-2's request (a ce_a strobe)
);
    localparam logic [7:0] O_TM0 = 8'h80, O_MD0 = 8'h82, O_TM1 = 8'h88, O_MD1 = 8'h8A,
                           O_TMC0 = 8'h90, O_TMC1 = 8'h91;
    wire os = tmc0[0];                  // one-shot (MOD0)
    // the prescalers: the clocks to a count, less one
    wire [6:0] d0 = tmc0[6] ? 7'd127 : os ? 7'd11 : 7'd5;
    wire [6:0] dm = tmc0[4] ? 7'd127 : 7'd11;
    wire [6:0] d1 = tmc1[6] ? 7'd127 : 7'd5;
    reg  [6:0] p0 = 7'd0, pm = 7'd0, p1 = 7'd0;
    // a start's synchronisation: the count begins SD clocks after the store (f4_tout: the first
    // count-out 604 clocks after the store's TOUT level, the next 600 apart)
    localparam logic [2:0] SD = 3'd4;
    reg  [2:0] s0 = 3'd0, s1 = 3'd0;
    reg        q = 1'b1;
    assign tout = tmc0[3] ? q ^ tmc0[2] : !tmc0[2];
    // a store's bytes at an offset (a word store writes the offset and the next)
    wire        s_tmc0 = we && (w_off == O_TMC0);
    wire        s_tmc1 = we && (w_off == O_TMC1 || (w_word && w_off == O_TMC0));
    wire [7:0]  v_tmc1 = w_off == O_TMC1 ? w_lo : w_hi;
    initial begin
        tm0 = 16'hFFFF; md0 = 16'hFFFF; tm1 = 16'hFFFF; md1 = 16'hFFFF;
        tmc0 = 8'd0; tmc1 = 8'd0; tf = 3'd0;
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            tm0 <= 16'hFFFF; md0 <= 16'hFFFF; tm1 <= 16'hFFFF; md1 <= 16'hFFFF;
            tmc0 <= 8'd0; tmc1 <= 8'd0; tf <= 3'd0;
            p0 <= 7'd0; pm <= 7'd0; p1 <= 7'd0; q <= 1'b1;
            s0 <= 3'd0; s1 <= 3'd0;
        end else if (ce_a) begin
            tf <= 3'd0;
            // ---- the counts
            if (s0 != 3'd0)
                s0 <= s0 - 3'd1;
            if (s1 != 3'd0)
                s1 <= s1 - 3'd1;
            if (tmc0[7] && s0 == 3'd0) begin
                p0 <= p0 == d0 ? 7'd0 : p0 + 7'd1;
                if (p0 == d0) begin
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
            if (os && tmc0[5]) begin
                pm <= pm == dm ? 7'd0 : pm + 7'd1;
                if (pm == dm) begin
                    if (md0 == 16'd1 || md0 == 16'd0) begin
                        tf[1] <= 1'b1;
                        tmc0[5] <= 1'b0;
                        md0 <= 16'd0;
                    end else
                        md0 <= md0 - 16'd1;
                end
            end
            if (tmc1[7] && s1 == 3'd0) begin
                p1 <= p1 == d1 ? 7'd0 : p1 + 7'd1;
                if (p1 == d1) begin
                    if (tm1 == 16'd0) begin
                        tf[2:1] <= 2'b11;
                        tm1 <= md1;
                    end else
                        tm1 <= tm1 - 16'd1;
                end
            end
            // ---- the stores (after the counts: a store wins)
            if (we && w_word && w_off == O_TM0)
                tm0 <= {w_hi, w_lo};
            if (we && w_word && w_off == O_MD0)
                md0 <= {w_hi, w_lo};
            if (we && w_word && w_off == O_TM1)
                tm1 <= {w_hi, w_lo};
            if (we && w_word && w_off == O_MD1)
                md1 <= {w_hi, w_lo};
            if (s_tmc0) begin
                tmc0 <= w_lo & 8'hFD;
                if (w_lo[7]) begin
                    p0 <= 7'd0;
                    s0 <= w_lo[0] ? 3'd0 : SD;
                    if (!w_lo[0])
                        tm0 <= md0;
                    if (!tmc0[7])
                        q <= 1'b1;
                end
                if (w_lo[5])
                    pm <= 7'd0;
            end
            if (s_tmc1) begin
                tmc1 <= v_tmc1 & 8'hC0;
                if (v_tmc1[7]) begin
                    p1 <= 7'd0;
                    s1 <= SD;
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
