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
    output reg         poll_p14         // (F2b) the P14 pin as POLL reads it: the INT level while
                                        //   PM1 bit 4 makes P14 an input, else low (registered)
);
    localparam logic [7:0] PRC_RESET = 8'h4E;
    localparam logic [15:0] WTC_RESET = 16'hFFFF;
    localparam logic [7:0] RFM_RESET = 8'hFC;
    localparam logic [7:0] IDB_RESET = 8'hFF;
    localparam logic [1:0] BW_WORD = 2'd0, BW_HI = 2'd2;   // as v35/v35_front_pkg.sv (BW_LO 1)

    // ---- the offsets (measured) -------------------------------------------------------------
    localparam logic [2:0] K_ST = 3'd0, K_C = 3'd1, K_PIN = 3'd2, K_RES = 3'd3, K_W16 = 3'd4,
                           K_FLAG = 3'd5, K_IDB = 3'd6;
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
            8'h60, 8'h70, 8'h6B, 8'h7B, 8'hE0, 8'hFC, 8'hF0, 8'hF1, 8'hF4, 8'hF7, 8'hF8,
            8'hF9: kind = K_C;
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
    // FLAG: the store's byte (bits 5 and 3) into the PSW
    assign flag_we = wr && in_page && !top && w_off == 8'hEA;
    assign flag_d = {w_lo[5], w_lo[3]};

    // ---- the read ---------------------------------------------------------------------------
    // P1: P17 READY high, P16 / P15 low (the harness's R2 bank), P14 INT, P13-P11 INTP2-0, P10 NMI
    wire [7:0] p1 = {1'b1, 2'b00, input_levels[5], input_levels[4], input_levels[3],
                     input_levels[2], input_levels[1]};
    function automatic logic [7:0] rbyte(input logic [7:0] o);
        case (kind(o))
            K_ST: rbyte = o == 8'hEB ? prc : o == 8'hE1 ? rfm : o == 8'hE8 ? wtc[7:0]
                        : o == 8'hE9 ? wtc[15:8] : (st[o] & wmask(o)) | ones(o);
            K_W16: rbyte = st[o];
            K_PIN: rbyte = o == 8'h08 ? p1 : 8'h00;
            K_FLAG: rbyte = {2'b00, psw_f[1], 1'b0, psw_f[0], 3'b000};
            K_IDB: rbyte = idb;
            K_C: rbyte = cval(o);
            default: rbyte = 8'h00;
        endcase
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
    wire unused = &{1'b0, input_levels[15:6], input_levels[0]};
endmodule
