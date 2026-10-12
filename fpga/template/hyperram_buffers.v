`timescale 1ns/1ps

// One 16-bit simple dual-port RAM with independent clocks; Efinity maps this
// shape onto block RAM.
module hyperram_buffer_ram #(
    parameter integer ADDR_BITS = 8
) (
    input  wire                 write_clock,
    input  wire                 write_enable,
    input  wire [ADDR_BITS-1:0] write_address,
    input  wire [15:0]          write_data,
    input  wire                 read_clock,
    input  wire [ADDR_BITS-1:0] read_address,
    output reg  [15:0]          read_data
);
    (* syn_ramstyle = "block_ram" *)
    reg [15:0] memory [0:(1 << ADDR_BITS) - 1];

    always @(posedge write_clock) begin
        if (write_enable)
            memory[write_address] <= write_data;
    end

    always @(posedge read_clock)
        read_data <= memory[read_address];
endmodule

// Staging buffers between a producer/consumer clock domain and the HyperRAM
// controller. There are 2^BUFFER_BITS buffers of BURST_WORDS 16-bit words.
// The user side is USER_WIDTH bits wide (16, 32, 64 or 128): user word n of
// a buffer holds burst words n * LANES to n * LANES + LANES - 1, the lowest
// in bits 15:0.
//
// Each direction has its own RAMs: the user writes data for HyperRAM writes
// into the "out" RAMs, and the controller writes HyperRAM read data into the
// "in" RAMs. Each buffer is LANES parallel 16-bit RAMs, so there is no
// reliance on mixed-width RAM inference.
//
// Latency: user_read_data follows user_read_address by one user clock;
// hr_read_data follows hr_read_address by two clk_hr cycles.
module hyperram_buffers #(
    parameter integer BURST_WORDS = 256,
    parameter integer BUFFER_BITS = 2,
    parameter integer USER_WIDTH = 64
) (
    input  wire                     user_clock,
    input  wire                     user_write_enable,
    input  wire [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_write_address,
    input  wire [USER_WIDTH-1:0]    user_write_data,
    input  wire [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_read_address,
    output wire [USER_WIDTH-1:0]    user_read_data,

    input  wire                     hr_clock,
    input  wire [BUFFER_BITS+$clog2(BURST_WORDS)-1:0] hr_read_address,
    output reg  [15:0]              hr_read_data = 16'd0,
    input  wire                     hr_write_enable,
    input  wire [BUFFER_BITS+$clog2(BURST_WORDS)-1:0] hr_write_address,
    input  wire [15:0]              hr_write_data
);
    localparam integer LANES = USER_WIDTH / 16;
    localparam integer LANE_ADDR_BITS =
        BUFFER_BITS + $clog2(BURST_WORDS * 16 / USER_WIDTH);

    wire [15:0] out_data [0:LANES-1];

    genvar lane;
    generate
        if (LANES == 1) begin : single
            hyperram_buffer_ram #(.ADDR_BITS(LANE_ADDR_BITS)) out_ram (
                .write_clock(user_clock),
                .write_enable(user_write_enable),
                .write_address(user_write_address),
                .write_data(user_write_data),
                .read_clock(hr_clock),
                .read_address(hr_read_address),
                .read_data(out_data[0])
            );
            hyperram_buffer_ram #(.ADDR_BITS(LANE_ADDR_BITS)) in_ram (
                .write_clock(hr_clock),
                .write_enable(hr_write_enable),
                .write_address(hr_write_address),
                .write_data(hr_write_data),
                .read_clock(user_clock),
                .read_address(user_read_address),
                .read_data(user_read_data)
            );
            always @(posedge hr_clock)
                hr_read_data <= out_data[0];
        end else begin : lanes
            localparam integer LANE_BITS = $clog2(LANES);
            // Lane selection follows the RAM's one-cycle read latency.
            reg [LANE_BITS-1:0] read_lane = 0;
            always @(posedge hr_clock) begin
                read_lane <= hr_read_address[LANE_BITS-1:0];
                hr_read_data <= out_data[read_lane];
            end

            for (lane = 0; lane < LANES; lane = lane + 1) begin : lane_ram
                hyperram_buffer_ram #(.ADDR_BITS(LANE_ADDR_BITS)) out_ram (
                    .write_clock(user_clock),
                    .write_enable(user_write_enable),
                    .write_address(user_write_address),
                    .write_data(user_write_data[16 * lane +: 16]),
                    .read_clock(hr_clock),
                    .read_address(hr_read_address[BUFFER_BITS+$clog2(BURST_WORDS)-1:LANE_BITS]),
                    .read_data(out_data[lane])
                );
                hyperram_buffer_ram #(.ADDR_BITS(LANE_ADDR_BITS)) in_ram (
                    .write_clock(hr_clock),
                    .write_enable(hr_write_enable &&
                                  hr_write_address[LANE_BITS-1:0] == lane),
                    .write_address(hr_write_address[BUFFER_BITS+$clog2(BURST_WORDS)-1:LANE_BITS]),
                    .write_data(hr_write_data),
                    .read_clock(user_clock),
                    .read_address(user_read_address),
                    .read_data(user_read_data[16 * lane +: 16])
                );
            end
        end
    endgenerate
endmodule
