`timescale 1ns/1ps

// V35S special function registers the chain-model lane needs (HDL plan, Phase D3): PRC, WTC,
// RFM and IDB, at their SFR offsets in the page IDB:F00-FFF (the data book's SFR map, as the
// ucore wrapper v35s_model.sv decodes it: RFM E1h, WTC E8h/E9h, PRC EBh, IDB FFh; IDB also at
// FFFFFh). Reset values from the data book and docs/v35s-bus-timing.md: PRC 4Eh (CLKOUT =
// fX/8), WTC FFFFh (two waits plus READY in every field), RFM FCh (refresh on, RFT 0, RFW 3),
// IDB FFh.
//
// Written by the core's SFR store: the internal cycle the chain model gives an on-chip store
// (sfr_cycle=io: 3 + the I/O waits, no pins; v35_biu.sv), taken here at that cycle's end
// (`wr` with the store's address, width and datum as issued). A word store at an even offset
// writes the offset and the next; a byte store writes its lane (an odd address the high one).
// Read by the bus unit (WTC: the memory field of block 0 and the I/O field, as the model reads
// them), the refresh controller (RFM: RFEN, RFT and RFW at reset; v35_refresh.sv) and the
// clock divider (PRC.PCK). The other SFRs (ports, timers, serial, interrupts) are not built:
// a store to one is accepted and dropped, a read of the page never reaches here (the chain
// model has no on-chip read).
module v35_sfr (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        wr,              // an SFR store's cycle ends ...
    input  wire [19:0] addr,            // ... its address (IDB:Fxx), width (V35_BW_*), datum
    input  wire [1:0]  width,
    input  wire [15:0] data,
    output reg  [7:0]  prc,
    output reg  [15:0] wtc,
    output reg  [7:0]  rfm,
    output reg  [7:0]  idb
);
    localparam logic [7:0] PRC_RESET = 8'h4E;
    localparam logic [15:0] WTC_RESET = 16'hFFFF;
    localparam logic [7:0] RFM_RESET = 8'hFC;
    localparam logic [7:0] IDB_RESET = 8'hFF;
    localparam logic [1:0] BW_WORD = 2'd0, BW_LO = 2'd1, BW_HI = 2'd2;   // as v35/v35_front_pkg.sv

    initial begin
        prc = PRC_RESET;
        wtc = WTC_RESET;
        rfm = RFM_RESET;
        idb = IDB_RESET;
    end

    task automatic put(input logic [7:0] offset, input logic [7:0] value);
        case (offset)
            8'hE1: rfm <= value;
            8'hE8: wtc[7:0] <= value;
            8'hE9: wtc[15:8] <= value;
            8'hEB: prc <= value;
            8'hFF: idb <= value;
            default: ;
        endcase
    endtask

    wire in_page = addr[19:12] == idb && addr[11:8] == 4'hF;
    wire top = addr == 20'hFFFFF;

    always @(posedge clock) begin
        if (!reset_n) begin
            prc <= PRC_RESET;
            wtc <= WTC_RESET;
            rfm <= RFM_RESET;
            idb <= IDB_RESET;
        end else if (wr) begin
            if (top) begin
                idb <= width == BW_LO ? data[7:0] : data[15:8];
            end else if (in_page) begin
                if (width == BW_WORD) begin
                    put(addr[7:0], data[7:0]);
                    put(addr[7:0] | 8'd1, data[15:8]);
                end else begin
                    put(addr[7:0], width == BW_HI ? data[15:8] : data[7:0]);
                end
            end
        end
    end
endmodule
