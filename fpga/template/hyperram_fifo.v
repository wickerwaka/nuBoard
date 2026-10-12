`timescale 1ns/1ps

// Small first-word-fall-through asynchronous FIFO with gray-coded pointers.
// read_data shows the oldest entry whenever empty is low.
module hyperram_fifo #(
    parameter integer WIDTH = 16,
    parameter integer ADDR_BITS = 3
) (
    input  wire             write_clock,
    input  wire             write_enable,
    input  wire [WIDTH-1:0] write_data,
    output wire             full,
    input  wire             read_clock,
    input  wire             read_enable,
    output wire [WIDTH-1:0] read_data,
    output wire             empty
);
    reg [WIDTH-1:0] memory [0:(1 << ADDR_BITS) - 1];
    reg [ADDR_BITS:0] write_binary = 0;
    reg [ADDR_BITS:0] write_gray = 0;
    reg [ADDR_BITS:0] read_binary = 0;
    reg [ADDR_BITS:0] read_gray = 0;
    (* async_reg = "true" *) reg [ADDR_BITS:0] write_gray_sync_1 = 0;
    (* async_reg = "true" *) reg [ADDR_BITS:0] write_gray_sync_2 = 0;
    (* async_reg = "true" *) reg [ADDR_BITS:0] read_gray_sync_1 = 0;
    (* async_reg = "true" *) reg [ADDR_BITS:0] read_gray_sync_2 = 0;

    wire [ADDR_BITS:0] write_binary_next = write_binary + 1'b1;
    wire [ADDR_BITS:0] read_binary_next = read_binary + 1'b1;

    always @(posedge write_clock) begin
        read_gray_sync_1 <= read_gray;
        read_gray_sync_2 <= read_gray_sync_1;
        if (write_enable && !full) begin
            memory[write_binary[ADDR_BITS-1:0]] <= write_data;
            write_binary <= write_binary_next;
            write_gray <= write_binary_next ^ (write_binary_next >> 1);
        end
    end

    always @(posedge read_clock) begin
        write_gray_sync_1 <= write_gray;
        write_gray_sync_2 <= write_gray_sync_1;
        if (read_enable && !empty) begin
            read_binary <= read_binary_next;
            read_gray <= read_binary_next ^ (read_binary_next >> 1);
        end
    end

    // Full when the write pointer is a whole lap ahead of the read pointer:
    // in gray code, the top two bits differ and the rest match.
    assign full = write_gray == {~read_gray_sync_2[ADDR_BITS:ADDR_BITS-1],
                                 read_gray_sync_2[ADDR_BITS-2:0]};
    assign empty = read_gray == write_gray_sync_2;
    assign read_data = memory[read_binary[ADDR_BITS-1:0]];
endmodule
