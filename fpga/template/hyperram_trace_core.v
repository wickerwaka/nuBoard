`timescale 1ns/1ps

// Buffered HyperRAM for trace capture. A producer fills a staging buffer,
// then queues "write buffer b to burst A"; reads queue "read burst A into
// buffer b". Each command completes with an entry in the done queue, after
// which the buffer may be refilled (write) or read out (read). Commands run
// in order, back to back.
//
// Everything on the user_* side, including both queues, is in the
// user_clock domain; the buffers' dual-clock RAMs and the queues' async
// FIFOs do the crossing. The HyperRAM side runs on the HyperRAM PLL.
//
// Bursts are BURST_WORDS 16-bit words and burst-aligned: burst A covers
// words A * BURST_WORDS onwards. user_*_address is {buffer, user word}.
module hyperram_trace_core #(
    parameter integer HR_MHZ = 100,
    parameter integer BURST_WORDS = 256,
    parameter integer BUFFER_BITS = 2,
    parameter integer USER_WIDTH = 64
) (
    input  wire        clk_hr,
    input  wire        clk_hr90,
    input  wire        clk_hr_cal,
    input  wire        pll_locked,

    input  wire                     user_clock,
    input  wire                     user_write_enable,
    input  wire [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_write_address,
    input  wire [USER_WIDTH-1:0]    user_write_data,
    input  wire [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_read_address,
    output wire [USER_WIDTH-1:0]    user_read_data,

    input  wire                             command_valid,
    output wire                             command_ready,
    input  wire                             command_write,
    input  wire [BUFFER_BITS-1:0]           command_buffer,
    input  wire [21-$clog2(BURST_WORDS):0]  command_burst,

    output wire                             done_valid,
    input  wire                             done_ready,
    output wire                             done_write,
    output wire [BUFFER_BITS-1:0]           done_buffer,
    output wire [$clog2(BURST_WORDS):0]     done_short,

    // clk_hr domain; id0 and id1 are stable once init_done is set.
    output wire        init_done,
    output wire [15:0] id0,
    output wire [15:0] id1,

    output wire        hr_ck,
    output wire        hr_cs_n,
    output wire        hr_reset_n,
    inout  wire        hr_rwds,
    inout  wire [7:0]  hr_dq
);
    localparam integer WORD_BITS = $clog2(BURST_WORDS);
    localparam integer BURST_BITS = 22 - WORD_BITS;
    localparam integer COMMAND_WIDTH = 1 + BUFFER_BITS + BURST_BITS;
    localparam integer DONE_WIDTH = 1 + BUFFER_BITS + WORD_BITS + 1;

    // Hold the controller in reset until the PLL has locked.
    (* async_reg = "true" *) reg locked_sync_1 = 1'b0;
    (* async_reg = "true" *) reg locked_sync_2 = 1'b0;
    reg reset = 1'b1;
    always @(posedge clk_hr) begin
        locked_sync_1 <= pll_locked;
        locked_sync_2 <= locked_sync_1;
        reset <= !locked_sync_2;
    end

    wire                   hr_command_valid_n;
    wire                   hr_command_pop;
    wire                   hr_command_write;
    wire [BUFFER_BITS-1:0] hr_command_buffer;
    wire [BURST_BITS-1:0]  hr_command_burst;
    wire                   command_full;
    assign command_ready = !command_full;

    hyperram_fifo #(.WIDTH(COMMAND_WIDTH), .ADDR_BITS(3)) command_fifo (
        .write_clock(user_clock),
        .write_enable(command_valid),
        .write_data({command_write, command_buffer, command_burst}),
        .full(command_full),
        .read_clock(clk_hr),
        .read_enable(hr_command_pop),
        .read_data({hr_command_write, hr_command_buffer, hr_command_burst}),
        .empty(hr_command_valid_n)
    );

    wire                   hr_done_full;
    wire                   hr_done_push;
    wire                   hr_done_write;
    wire [BUFFER_BITS-1:0] hr_done_buffer;
    wire [WORD_BITS:0]     hr_done_short;
    wire                   done_empty;
    assign done_valid = !done_empty;

    hyperram_fifo #(.WIDTH(DONE_WIDTH), .ADDR_BITS(3)) done_fifo (
        .write_clock(clk_hr),
        .write_enable(hr_done_push),
        .write_data({hr_done_write, hr_done_buffer, hr_done_short}),
        .full(hr_done_full),
        .read_clock(user_clock),
        .read_enable(done_ready),
        .read_data({done_write, done_buffer, done_short}),
        .empty(done_empty)
    );

    wire [BUFFER_BITS+WORD_BITS-1:0] buffer_read_address;
    wire [15:0]                      buffer_read_data;
    wire                             buffer_write_enable;
    wire [BUFFER_BITS+WORD_BITS-1:0] buffer_write_address;
    wire [15:0]                      buffer_write_data;

    hyperram_buffers #(
        .BURST_WORDS(BURST_WORDS),
        .BUFFER_BITS(BUFFER_BITS),
        .USER_WIDTH(USER_WIDTH)
    ) buffers (
        .user_clock(user_clock),
        .user_write_enable(user_write_enable),
        .user_write_address(user_write_address),
        .user_write_data(user_write_data),
        .user_read_address(user_read_address),
        .user_read_data(user_read_data),
        .hr_clock(clk_hr),
        .hr_read_address(buffer_read_address),
        .hr_read_data(buffer_read_data),
        .hr_write_enable(buffer_write_enable),
        .hr_write_address(buffer_write_address),
        .hr_write_data(buffer_write_data)
    );

    wire       phy_cs_n;
    wire       phy_ck_en;
    wire [7:0] phy_dq_out_hi;
    wire [7:0] phy_dq_out_lo;
    wire       phy_dq_oe;
    wire       phy_rwds_out_hi;
    wire       phy_rwds_out_lo;
    wire       phy_rwds_oe;
    wire [7:0] phy_dq_in_fall;
    wire [7:0] phy_dq_in_rise;
    wire       phy_rwds_in_fall;
    wire       phy_rwds_in_rise;

    hyperram_ctrl #(
        .HR_MHZ(HR_MHZ),
        .BURST_WORDS(BURST_WORDS),
        .BUFFER_BITS(BUFFER_BITS)
    ) controller (
        .clk_hr(clk_hr),
        .clk_hr_cal(clk_hr_cal),
        .reset(reset),
        .init_done(init_done),
        .id0(id0),
        .id1(id1),
        .command_valid(!hr_command_valid_n),
        .command_pop(hr_command_pop),
        .command_write(hr_command_write),
        .command_buffer(hr_command_buffer),
        .command_burst(hr_command_burst),
        .done_full(hr_done_full),
        .done_push(hr_done_push),
        .done_write(hr_done_write),
        .done_buffer(hr_done_buffer),
        .done_short(hr_done_short),
        .buffer_read_address(buffer_read_address),
        .buffer_read_data(buffer_read_data),
        .buffer_write_enable(buffer_write_enable),
        .buffer_write_address(buffer_write_address),
        .buffer_write_data(buffer_write_data),
        .hr_reset_n(hr_reset_n),
        .phy_cs_n(phy_cs_n),
        .phy_ck_en(phy_ck_en),
        .phy_dq_out_hi(phy_dq_out_hi),
        .phy_dq_out_lo(phy_dq_out_lo),
        .phy_dq_oe(phy_dq_oe),
        .phy_rwds_out_hi(phy_rwds_out_hi),
        .phy_rwds_out_lo(phy_rwds_out_lo),
        .phy_rwds_oe(phy_rwds_oe),
        .phy_dq_in_fall(phy_dq_in_fall),
        .phy_dq_in_rise(phy_dq_in_rise),
        .phy_rwds_in_fall(phy_rwds_in_fall),
        .phy_rwds_in_rise(phy_rwds_in_rise)
    );

    hyperram_phy phy (
        .clk_hr(clk_hr),
        .clk_hr90(clk_hr90),
        .clk_hr_cal(clk_hr_cal),
        .cs_n(phy_cs_n),
        .ck_en(phy_ck_en),
        .dq_out_hi(phy_dq_out_hi),
        .dq_out_lo(phy_dq_out_lo),
        .dq_oe(phy_dq_oe),
        .rwds_out_hi(phy_rwds_out_hi),
        .rwds_out_lo(phy_rwds_out_lo),
        .rwds_oe(phy_rwds_oe),
        .dq_in_fall(phy_dq_in_fall),
        .dq_in_rise(phy_dq_in_rise),
        .rwds_in_fall(phy_rwds_in_fall),
        .rwds_in_rise(phy_rwds_in_rise),
        .hr_ck(hr_ck),
        .hr_cs_n(hr_cs_n),
        .hr_rwds(hr_rwds),
        .hr_dq(hr_dq)
    );
endmodule
