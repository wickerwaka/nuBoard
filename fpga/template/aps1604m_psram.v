`timescale 1ns/1ps

// Byte-stream echo engine backed by the board's APS1604M-3SQR PSRAM.
//
// The controller uses the device's power-on SPI mode rather than QPI. SCLK is
// 25 MHz: one 50 MHz system-clock period high and one period low. Each byte is
// written with command 02h and read back with command 03h in its own command.
// This deliberately conservative pattern keeps CE# low for only 1.6 us,
// remains below the 33 MHz limit of 03h reads, and never crosses a page inside
// a write command.
module aps1604m_psram_echo (
    input  wire        clock,

    input  wire        input_valid,
    output wire        input_ready,
    input  wire [7:0]  input_data,
    input  wire        input_last,

    output reg         output_valid,
    input  wire        output_ready,
    output reg  [7:0]  output_data,
    output reg         output_last,

    output reg         initialized,
    output reg         psram_ce_n,
    output reg         psram_sclk,
    output reg         psram_si,
    input  wire        psram_so,
    output wire        psram_sio2,
    output wire        psram_sio3
);
    localparam [3:0] STATE_POWER_UP_WAIT = 4'd0;
    localparam [3:0] STATE_RESET_ENABLE = 4'd1;
    localparam [3:0] STATE_SEND_RISE = 4'd2;
    localparam [3:0] STATE_SEND_FALL = 4'd3;
    localparam [3:0] STATE_RESET_GAP = 4'd4;
    localparam [3:0] STATE_RESET = 4'd5;
    localparam [3:0] STATE_RESET_WAIT = 4'd6;
    localparam [3:0] STATE_IDLE = 4'd7;
    localparam [3:0] STATE_WRITE_GAP = 4'd8;
    localparam [3:0] STATE_READ_COMMAND = 4'd9;
    localparam [3:0] STATE_READ_TURNAROUND = 4'd10;
    localparam [3:0] STATE_READ_RISE = 4'd11;
    localparam [3:0] STATE_READ_FALL = 4'd12;
    localparam [3:0] STATE_OUTPUT = 4'd13;

    // The datasheet requires at least 150 us after power becomes stable. The
    // 8,192-cycle delay is 163.84 us at 50 MHz and is followed by 66h/99h.
    reg [13:0] power_up_count = 14'd0;
    reg [3:0] state = STATE_POWER_UP_WAIT;
    reg [3:0] state_after_send = STATE_POWER_UP_WAIT;
    reg [39:0] transmit_shift = 40'd0;
    reg [5:0] bits_remaining = 6'd0;
    reg [2:0] reset_wait_count = 3'd0;

    reg [20:0] address = 21'd0;
    reg latched_last = 1'b0;
    reg [7:0] read_shift = 8'd0;
    reg [2:0] read_bit = 3'd0;

    assign input_ready = initialized &&
                         state == STATE_IDLE &&
                         !output_valid;

    // These pins are only data lines in quad mode. Holding them low also
    // satisfies the device's power-up requirement for SIO[3:0].
    assign psram_sio2 = 1'b0;
    assign psram_sio3 = 1'b0;

    initial begin
        initialized = 1'b0;
        output_valid = 1'b0;
        output_data = 8'd0;
        output_last = 1'b0;
        psram_ce_n = 1'b1;
        psram_sclk = 1'b0;
        psram_si = 1'b0;
    end

    always @(posedge clock) begin
        case (state)
            STATE_POWER_UP_WAIT: begin
                psram_ce_n <= 1'b1;
                psram_sclk <= 1'b0;
                psram_si <= 1'b0;

                if (power_up_count == 14'd8_191) begin
                    state <= STATE_RESET_ENABLE;
                end else begin
                    power_up_count <= power_up_count + 1'b1;
                end
            end

            STATE_RESET_ENABLE: begin
                // Reset Enable command, 66h.
                psram_ce_n <= 1'b0;
                psram_si <= 1'b0;
                transmit_shift <= {8'h66, 32'd0};
                bits_remaining <= 6'd8;
                state_after_send <= STATE_RESET_GAP;
                state <= STATE_SEND_RISE;
            end

            STATE_SEND_RISE: begin
                psram_sclk <= 1'b1;
                state <= STATE_SEND_FALL;
            end

            STATE_SEND_FALL: begin
                psram_sclk <= 1'b0;

                if (bits_remaining == 1) begin
                    if (state_after_send == STATE_READ_TURNAROUND) begin
                        // A read keeps CE# asserted while ownership of SO
                        // changes from the command phase to the data phase.
                        state <= STATE_READ_TURNAROUND;
                    end else begin
                        psram_ce_n <= 1'b1;
                        state <= state_after_send;
                    end
                end else begin
                    transmit_shift <= {transmit_shift[38:0], 1'b0};
                    psram_si <= transmit_shift[38];
                    bits_remaining <= bits_remaining - 1'b1;
                    state <= STATE_SEND_RISE;
                end
            end

            STATE_RESET_GAP: begin
                // One 50 MHz period gives 20 ns of CE# high time; the minimum
                // interval between commands is 18 ns.
                state <= STATE_RESET;
            end

            STATE_RESET: begin
                // Reset command, 99h, immediately follows Reset Enable.
                psram_ce_n <= 1'b0;
                psram_si <= 1'b1;
                transmit_shift <= {8'h99, 32'd0};
                bits_remaining <= 6'd8;
                state_after_send <= STATE_RESET_WAIT;
                state <= STATE_SEND_RISE;
            end

            STATE_RESET_WAIT: begin
                psram_si <= 1'b0;

                // Three cycles provide 60 ns after reset, exceeding tRST.
                if (reset_wait_count == 3'd2) begin
                    initialized <= 1'b1;
                    state <= STATE_IDLE;
                end else begin
                    reset_wait_count <= reset_wait_count + 1'b1;
                end
            end

            STATE_IDLE: begin
                if (input_valid && input_ready) begin
                    // SPI Write, 02h; address bits A23:A21 are zero because
                    // this device implements byte addresses A20:A0.
                    psram_ce_n <= 1'b0;
                    psram_si <= 1'b0;
                    transmit_shift <= {
                        8'h02,
                        3'b000,
                        address,
                        input_data
                    };
                    bits_remaining <= 6'd40;
                    state_after_send <= STATE_WRITE_GAP;
                    latched_last <= input_last;
                    state <= STATE_SEND_RISE;
                end
            end

            STATE_WRITE_GAP: begin
                // Terminate the write for refresh and satisfy tCPH before the
                // read-back command begins.
                state <= STATE_READ_COMMAND;
            end

            STATE_READ_COMMAND: begin
                // SPI Read, 03h, has no dummy cycles at 25 MHz.
                psram_ce_n <= 1'b0;
                psram_si <= 1'b0;
                transmit_shift <= {8'h03, 3'b000, address, 8'd0};
                bits_remaining <= 6'd32;
                state_after_send <= STATE_READ_TURNAROUND;
                state <= STATE_SEND_RISE;
            end

            STATE_READ_TURNAROUND: begin
                // The PSRAM updates SO after the falling edge that ended the
                // address. Sample that bit on the following rising edge.
                read_shift <= 8'd0;
                read_bit <= 3'd7;
                state <= STATE_READ_RISE;
            end

            STATE_READ_RISE: begin
                psram_sclk <= 1'b1;
                read_shift <= {read_shift[6:0], psram_so};
                state <= STATE_READ_FALL;
            end

            STATE_READ_FALL: begin
                psram_sclk <= 1'b0;

                if (read_bit == 0) begin
                    psram_ce_n <= 1'b1;
                    output_data <= read_shift;
                    output_last <= latched_last;
                    output_valid <= 1'b1;
                    state <= STATE_OUTPUT;
                end else begin
                    read_bit <= read_bit - 1'b1;
                    state <= STATE_READ_RISE;
                end
            end

            STATE_OUTPUT: begin
                if (output_valid && output_ready) begin
                    output_valid <= 1'b0;
                    address <= address + 1'b1;
                    state <= STATE_IDLE;
                end
            end

            default: begin
                psram_ce_n <= 1'b1;
                psram_sclk <= 1'b0;
                psram_si <= 1'b0;
                output_valid <= 1'b0;
                initialized <= 1'b0;
                state <= STATE_POWER_UP_WAIT;
            end
        endcase
    end
endmodule
