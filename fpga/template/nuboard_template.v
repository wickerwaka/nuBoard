`timescale 1ns/1ps

// HR_MHZ and HR_CAL_PHASE describe the HyperRAM PLL configuration in
// template.isf, and HR_BURST_WORDS the HyperRAM burst length. build.sh
// regenerates this file for each configuration.
`include "hyperram_build.vh"

// Efinity recognizes this shape as a true dual-port block RAM. Keeping the
// storage in a small, dedicated module also makes the two clock domains clear:
// one port writes, while the other independently performs synchronous reads.
module nuboard_slot_ram (
    input  wire        write_clock,
    input  wire        write_enable,
    input  wire [11:0] write_address,
    input  wire [7:0]  write_data,
    input  wire        read_clock,
    input  wire [11:0] read_address,
    output reg  [7:0]  read_data
);
    (* syn_ramstyle = "block_ram" *)
    reg [7:0] memory [0:4095];

    always @(posedge write_clock) begin
        if (write_enable)
            memory[write_address] <= write_data;
    end

    always @(posedge read_clock) begin
        read_data <= memory[read_address];
    end
endmodule

module nuboard_template (
    input  wire        clk_50mhz,

    // HyperRAM PLL (PLL_TR1, referenced to the 50 MHz oscillator on A18).
    // These come from the Interface Designer, not from package pins.
    (* syn_peri_port = 0 *) input wire clk_hr,
    (* syn_peri_port = 0 *) input wire clk_hr90,
    (* syn_peri_port = 0 *) input wire clk_hr_cal,
    (* syn_peri_port = 0 *) input wire hr_pll_locked,
    output wire        heartbeat_out,

    output reg         spi_miso,
    input  wire        spi_cs_n,
    input  wire        spi_sck,
    input  wire        spi_mosi,
    output wire        fpga_irq_n,

    output wire        dut_isolate,
    output wire        dut_crowbar,

    // HyperRAM U2, driven by the HyperRAM test core.
    output wire        hr_ck,
    output wire        hr_cs_n,
    output wire        hr_reset_n,
    inout  wire        hr_rwds,
    inout  wire [7:0]  hr_dq,

    // Each edge has three independent eight-bit bidirectional banks. The
    // group and bit indices match the board net names: t2[3] is F_T23.
    inout  wire [7:0]  t0,
    inout  wire [7:0]  t1,
    inout  wire [7:0]  t2,
    output wire        t0_dir,
    output wire        t1_dir,
    output wire        t2_dir,
    output wire        t0_oe_n,
    output wire        t1_oe_n,
    output wire        t2_oe_n,

    inout  wire [7:0]  b0,
    inout  wire [7:0]  b1,
    inout  wire [7:0]  b2,
    output wire        b0_dir,
    output wire        b1_dir,
    output wire        b2_dir,
    output wire        b0_oe_n,
    output wire        b1_oe_n,
    output wire        b2_oe_n,

    inout  wire [7:0]  l0,
    inout  wire [7:0]  l1,
    inout  wire [7:0]  l2,
    output wire        l0_dir,
    output wire        l1_dir,
    output wire        l2_dir,
    output wire        l0_oe_n,
    output wire        l1_oe_n,
    output wire        l2_oe_n,

    inout  wire [7:0]  r0,
    inout  wire [7:0]  r1,
    inout  wire [7:0]  r2,
    output wire        r0_dir,
    output wire        r1_dir,
    output wire        r2_dir,
    output wire        r0_oe_n,
    output wire        r1_oe_n,
    output wire        r2_oe_n,

    // The TXS0108E translators provide automatic direction sensing for these
    // sideband signals, so the sixteen lines share one enable and have no DIR
    // pins. Bit indices match the board nets: tx[2] is F_TX2.
    inout  wire [3:0]  tx,
    inout  wire [3:0]  bx,
    inout  wire [3:0]  lx,
    inout  wire [3:0]  rx,
    output wire        xy_oe_n,

    // Each edge clock has a dedicated signal and external-buffer enable.
    output wire        tclk,
    output wire        tclk_en,
    output wire        bclk,
    output wire        bclk_en,
    output wire        lclk,
    output wire        lclk_en,
    output wire        rclk,
    output wire        rclk_en
);
    localparam [7:0] CMD_STATUS       = 8'h01;
    localparam [7:0] CMD_WRITE_PACKET = 8'h02;
    localparam [7:0] CMD_READ_PACKET  = 8'h03;
    localparam [7:0] CMD_ACK_PACKET   = 8'h04;
    localparam [7:0] CMD_GET_ID       = 8'h05;

    localparam [7:0] ABI_MAJOR = 8'd1;
    localparam integer SLOT_BYTES = 4096;
    localparam integer MAX_PAYLOAD = SLOT_BYTES - 16;

    reg write_toggle = 1'b0;
    reg write_error = 1'b0;
    reg app_seen_write = 1'b0;
    reg output_toggle = 1'b0;
    reg ack_toggle = 1'b0;

    // Each mailbox ownership toggle crosses through two flip-flops before the
    // receiving clock domain uses it. Data stays in its slot until the paired
    // toggle has crossed, so the toggle also acts as the coherency barrier.
    reg write_sync_1 = 1'b0;
    reg write_sync_2 = 1'b0;
    reg app_seen_sync_1 = 1'b0;
    reg app_seen_sync_2 = 1'b0;
    reg output_sync_1 = 1'b0;
    reg output_sync_2 = 1'b0;
    reg ack_sync_1 = 1'b0;
    reg ack_sync_2 = 1'b0;

    reg [31:0] inbound_length = 32'd0;
    reg [31:0] inbound_tag = 32'd0;
    reg [31:0] committed_length = 32'd0;
    reg [31:0] committed_tag = 32'd0;
    reg [31:0] outbound_tag = 32'd0;
    reg [31:0] expected_crc = 32'd0;
    reg [31:0] receive_crc = 32'hffffffff;

    wire inbound_pending_spi = write_toggle != app_seen_sync_2;
    wire inbound_pending_app = write_sync_2 != app_seen_write;
    wire outbound_pending_spi = output_sync_2 != ack_toggle;
    wire outbound_pending_app = output_toggle != ack_sync_2;
    assign fpga_irq_n = ~outbound_pending_app;

    always @(posedge spi_sck) begin
        app_seen_sync_1 <= app_seen_write;
        app_seen_sync_2 <= app_seen_sync_1;
        output_sync_1 <= output_toggle;
        output_sync_2 <= output_sync_1;
    end

    always @(posedge clk_50mhz) begin
        write_sync_1 <= write_toggle;
        write_sync_2 <= write_sync_1;
        ack_sync_1 <= ack_toggle;
        ack_sync_2 <= ack_sync_1;
    end

    function [31:0] crc32c_byte;
        input [31:0] crc;
        input [7:0] data;
        integer bit_index;
        reg [31:0] next;
        begin
            next = crc ^ {24'd0, data};
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                if (next[0])
                    next = (next >> 1) ^ 32'h82f63b78;
                else
                    next = next >> 1;
            end
            crc32c_byte = next;
        end
    endfunction

    function [7:0] identity_byte;
        input [5:0] index;
        begin
            case (index)
                0:  identity_byte = 8'h6e; // UUID: "nuBoard-template1"
                1:  identity_byte = 8'h75;
                2:  identity_byte = 8'h42;
                3:  identity_byte = 8'h6f;
                4:  identity_byte = 8'h61;
                5:  identity_byte = 8'h72;
                6:  identity_byte = 8'h64;
                7:  identity_byte = 8'h2d;
                8:  identity_byte = 8'h74;
                9:  identity_byte = 8'h65;
                10: identity_byte = 8'h6d;
                11: identity_byte = 8'h70;
                12: identity_byte = 8'h6c;
                13: identity_byte = 8'h61;
                14: identity_byte = 8'h74;
                15: identity_byte = 8'h65;
                16: identity_byte = 8'h01; // core version 1
                17: identity_byte = 8'h00;
                18: identity_byte = 8'h00;
                19: identity_byte = 8'h00;
                20: identity_byte = 8'h05; // build 5: buffered HyperRAM
                21: identity_byte = 8'h00;
                22: identity_byte = 8'h00;
                23: identity_byte = 8'h00;
                24: identity_byte = ABI_MAJOR;
                25: identity_byte = 8'h00;
                26: identity_byte = 8'h00; // ABI minor 0
                27: identity_byte = 8'h00;
                28: identity_byte = 8'h03; // echo and HyperRAM test
                default: identity_byte = 8'h00;
            endcase
        end
    endfunction

    function [7:0] response_byte;
        input [7:0] command;
        input [12:0] index;
        begin
            case (command)
                CMD_STATUS: begin
                    case (index)
                        0: response_byte = {
                            4'b0000,
                            inbound_pending_spi,
                            write_error,
                            outbound_pending_spi,
                            ~inbound_pending_spi
                        };
                        default: response_byte = 8'h00;
                    endcase
                end
                CMD_GET_ID: begin
                    if (index < 32)
                        response_byte = identity_byte(index[5:0]);
                    else
                        response_byte = 8'h00;
                end
                default: response_byte = 8'h00;
            endcase
        end
    endfunction

    reg [7:0] receive_shift = 8'h00;
    reg [2:0] bit_index = 3'd0;
    reg [7:0] command = 8'h00;
    reg command_valid = 1'b0;
    reg [12:0] byte_index = 13'd0;
    reg [31:0] acknowledge_tag = 32'd0;
    reg [7:0] transmit_shift = 8'h00;
    reg transaction_reset = 1'b1;
    wire [7:0] received_byte = {receive_shift[6:0], spi_mosi};
    wire [7:0] selected_response = response_byte(command, byte_index);

    reg [5:0] delay_count = 6'd0;
    reg [12:0] copy_index = 13'd0;
    reg [12:0] output_index = 13'd0;
    reg application_busy = 1'b0;
    reg copy_data_valid = 1'b0;
    reg input_finished = 1'b0;

    wire application_input_valid;
    wire application_input_ready;
    wire [7:0] application_input_data;
    wire application_input_last;
    wire application_output_valid;
    wire application_output_ready;
    wire [7:0] application_output_data;
    wire application_output_last;

    wire inbound_write_enable =
        !spi_cs_n && !transaction_reset && command_valid &&
        command == CMD_WRITE_PACKET &&
        bit_index == 3'd7 && byte_index < 13'd4096;
    wire [11:0] inbound_read_address =
        application_input_valid && application_input_ready
            ? copy_index[11:0] + 1'b1
            : copy_index[11:0];
    wire [7:0] inbound_read_data;

    wire outbound_write_enable =
        application_output_valid && application_output_ready;
    wire [11:0] outbound_read_address =
        command_valid && command == CMD_READ_PACKET
            ? byte_index[11:0] +
                (bit_index == 3'd7 ? 12'd1 : 12'd0)
            : 12'd0;
    wire [7:0] outbound_read_data;

    nuboard_slot_ram inbound_ram (
        .write_clock(spi_sck),
        .write_enable(inbound_write_enable),
        .write_address(byte_index[11:0]),
        .write_data(received_byte),
        .read_clock(clk_50mhz),
        .read_address(inbound_read_address),
        .read_data(inbound_read_data)
    );

    nuboard_slot_ram outbound_ram (
        .write_clock(clk_50mhz),
        .write_enable(outbound_write_enable),
        .write_address(output_index[11:0]),
        .write_data(application_output_data),
        .read_clock(spi_sck),
        .read_address(outbound_read_address),
        .read_data(outbound_read_data)
    );

    assign application_input_valid =
        application_busy && delay_count == 0 && copy_data_valid;
    assign application_input_data = inbound_read_data;
    assign application_input_last =
        copy_index == committed_length[12:0] + 13'd15;
    assign application_output_ready = application_busy;

    // HyperRAM trace buffer. The test harness inside the application is
    // its producer, on clk_50mhz with 64-bit words.
    localparam integer HR_BUFFER_BITS = 2;
    localparam integer HR_USER_WIDTH = 64;
    localparam integer HR_USER_ADDRESS_BITS =
        HR_BUFFER_BITS + $clog2(`HR_BURST_WORDS * 16 / HR_USER_WIDTH);
    localparam integer HR_BURST_BITS = 22 - $clog2(`HR_BURST_WORDS);

    wire                            hr_user_write_enable;
    wire [HR_USER_ADDRESS_BITS-1:0] hr_user_write_address;
    wire [HR_USER_WIDTH-1:0]        hr_user_write_data;
    wire [HR_USER_ADDRESS_BITS-1:0] hr_user_read_address;
    wire [HR_USER_WIDTH-1:0]        hr_user_read_data;
    wire                            hr_command_valid;
    wire                            hr_command_ready;
    wire                            hr_command_write;
    wire [HR_BUFFER_BITS-1:0]       hr_command_buffer;
    wire [HR_BURST_BITS-1:0]        hr_command_burst;
    wire                            hr_done_valid;
    wire                            hr_done_ready;
    wire                            hr_done_write;
    wire [HR_BUFFER_BITS-1:0]       hr_done_buffer;
    wire [$clog2(`HR_BURST_WORDS):0] hr_done_short;
    wire                            hr_init_done;
    wire [15:0]                     hr_id0;
    wire [15:0]                     hr_id1;

    // Replace this module with a core-specific application. The streams carry
    // one mailbox packet at a time and use valid/ready backpressure.
    nuboard_app #(
        .HR_MHZ(`HR_MHZ),
        .HR_CAL_PHASE(`HR_CAL_PHASE),
        .BURST_WORDS(`HR_BURST_WORDS),
        .BUFFER_BITS(HR_BUFFER_BITS),
        .USER_WIDTH(HR_USER_WIDTH)
    ) application (
        .clock(clk_50mhz),
        .input_valid(application_input_valid),
        .input_ready(application_input_ready),
        .input_data(application_input_data),
        .input_last(application_input_last),
        .output_valid(application_output_valid),
        .output_ready(application_output_ready),
        .output_data(application_output_data),
        .output_last(application_output_last),
        .user_write_enable(hr_user_write_enable),
        .user_write_address(hr_user_write_address),
        .user_write_data(hr_user_write_data),
        .user_read_address(hr_user_read_address),
        .user_read_data(hr_user_read_data),
        .command_valid(hr_command_valid),
        .command_ready(hr_command_ready),
        .command_write(hr_command_write),
        .command_buffer(hr_command_buffer),
        .command_burst(hr_command_burst),
        .done_valid(hr_done_valid),
        .done_ready(hr_done_ready),
        .done_write(hr_done_write),
        .done_buffer(hr_done_buffer),
        .done_short(hr_done_short),
        .pll_locked(hr_pll_locked),
        .init_done(hr_init_done),
        .id0(hr_id0),
        .id1(hr_id1)
    );

    hyperram_trace_core #(
        .HR_MHZ(`HR_MHZ),
        .BURST_WORDS(`HR_BURST_WORDS),
        .BUFFER_BITS(HR_BUFFER_BITS),
        .USER_WIDTH(HR_USER_WIDTH)
    ) hyperram (
        .clk_hr(clk_hr),
        .clk_hr90(clk_hr90),
        .clk_hr_cal(clk_hr_cal),
        .pll_locked(hr_pll_locked),
        .user_clock(clk_50mhz),
        .user_write_enable(hr_user_write_enable),
        .user_write_address(hr_user_write_address),
        .user_write_data(hr_user_write_data),
        .user_read_address(hr_user_read_address),
        .user_read_data(hr_user_read_data),
        .command_valid(hr_command_valid),
        .command_ready(hr_command_ready),
        .command_write(hr_command_write),
        .command_buffer(hr_command_buffer),
        .command_burst(hr_command_burst),
        .done_valid(hr_done_valid),
        .done_ready(hr_done_ready),
        .done_write(hr_done_write),
        .done_buffer(hr_done_buffer),
        .done_short(hr_done_short),
        .init_done(hr_init_done),
        .id0(hr_id0),
        .id1(hr_id1),
        .hr_ck(hr_ck),
        .hr_cs_n(hr_cs_n),
        .hr_reset_n(hr_reset_n),
        .hr_rwds(hr_rwds),
        .hr_dq(hr_dq)
    );

    // SPI mode 0: sample MOSI on rising edges. CS release leaves the captured
    // transaction intact for the commit block and only marks the receiver for
    // initialization on the first clock of the next transaction.
    always @(posedge spi_sck or posedge spi_cs_n) begin
        if (spi_cs_n) begin
            transaction_reset <= 1'b1;
        end else if (transaction_reset) begin
            transaction_reset <= 1'b0;
            receive_shift <= {7'd0, spi_mosi};
            bit_index <= 3'd1;
            command <= 8'h00;
            command_valid <= 1'b0;
            byte_index <= 13'd0;
            receive_crc <= 32'hffffffff;
            inbound_length <= 32'd0;
            inbound_tag <= 32'd0;
            expected_crc <= 32'd0;
            acknowledge_tag <= 32'd0;
        end else begin
            receive_shift <= {receive_shift[6:0], spi_mosi};
            if (bit_index == 3'd7) begin
                bit_index <= 3'd0;
                if (!command_valid) begin
                    command <= received_byte;
                    command_valid <= 1'b1;
                    byte_index <= 13'd0;
                end else begin
                    if (command == CMD_WRITE_PACKET) begin
                        case (byte_index)
                            4: inbound_tag[7:0] <= received_byte;
                            5: inbound_tag[15:8] <= received_byte;
                            6: inbound_tag[23:16] <= received_byte;
                            7: inbound_tag[31:24] <= received_byte;
                            8: inbound_length[7:0] <= received_byte;
                            9: inbound_length[15:8] <= received_byte;
                            10: inbound_length[23:16] <= received_byte;
                            11: inbound_length[31:24] <= received_byte;
                            12: expected_crc[7:0] <= received_byte;
                            13: expected_crc[15:8] <= received_byte;
                            14: expected_crc[23:16] <= received_byte;
                            15: expected_crc[31:24] <= received_byte;
                        endcase
                        if (byte_index >= 16)
                            receive_crc <= crc32c_byte(receive_crc,
                                                       received_byte);
                    end else if (command == CMD_ACK_PACKET) begin
                        case (byte_index)
                            0: acknowledge_tag[7:0] <= received_byte;
                            1: acknowledge_tag[15:8] <= received_byte;
                            2: acknowledge_tag[23:16] <= received_byte;
                            3: acknowledge_tag[31:24] <= received_byte;
                        endcase
                    end
                    byte_index <= byte_index + 1'b1;
                end
            end else begin
                bit_index <= bit_index + 1'b1;
            end
        end
    end

    // Chip-select release is the transaction commit edge. Keeping this logic
    // separate from the SPI shift clock avoids treating conditional logic as
    // an asynchronous reset and gives each toggle a single clocked driver.
    always @(posedge spi_cs_n) begin
        if (command == CMD_WRITE_PACKET && !inbound_pending_spi) begin
            if (inbound_length <= MAX_PAYLOAD &&
                byte_index == inbound_length[12:0] + 13'd16 &&
                ~receive_crc == expected_crc) begin
                write_toggle <= ~write_toggle;
                write_error <= 1'b0;
                committed_length <= inbound_length;
                committed_tag <= inbound_tag;
            end else begin
                write_error <= 1'b1;
            end
        end

        if (command == CMD_ACK_PACKET && byte_index == 4 &&
            acknowledge_tag == outbound_tag) begin
            ack_toggle <= output_sync_2;
        end
    end

    // Change MISO only on falling edges so it is stable at each rising edge.
    always @(negedge spi_sck or posedge spi_cs_n) begin
        if (spi_cs_n) begin
            spi_miso <= 1'b0;
            transmit_shift <= 8'h00;
        end else if (bit_index == 0) begin
            if (command == CMD_READ_PACKET && outbound_pending_spi) begin
                spi_miso <= outbound_read_data[7];
            end else begin
                transmit_shift <= selected_response;
                spi_miso <= selected_response[7];
            end
        end else begin
            if (command == CMD_READ_PACKET && outbound_pending_spi)
                spi_miso <= outbound_read_data[7 - bit_index];
            else
                spi_miso <= transmit_shift[7 - bit_index];
        end
    end

    // Packet sequencing for the application streams. The pending flags provide
    // backpressure; neither mailbox slot is overwritten. The input and output
    // sides are independent: an application may finish its output before, at,
    // or after the cycle in which the last input byte is consumed.
    always @(posedge clk_50mhz) begin
        if (!application_busy && inbound_pending_app &&
            !outbound_pending_app) begin
            application_busy <= 1'b1;
            delay_count <= 6'd32;
            copy_index <= 13'd0;
            output_index <= 13'd0;
            copy_data_valid <= 1'b0;
            input_finished <= 1'b0;
        end else if (application_busy) begin
            // Input side.
            if (delay_count != 0) begin
                delay_count <= delay_count - 1'b1;
            end else if (!copy_data_valid && !input_finished) begin
                // Prime the synchronous inbound RAM read before byte zero.
                copy_data_valid <= 1'b1;
            end else if (application_input_valid && application_input_ready) begin
                if (application_input_last) begin
                    copy_data_valid <= 1'b0;
                    input_finished <= 1'b1;
                    app_seen_write <= write_sync_2;
                end else begin
                    copy_index <= copy_index + 1'b1;
                end
            end

            // Output side.
            if (application_output_valid && application_output_ready) begin
                if (application_output_last) begin
                    application_busy <= 1'b0;
                    outbound_tag <= committed_tag;
                    output_toggle <= ~output_toggle;
                end else begin
                    output_index <= output_index + 1'b1;
                end
            end
        end
    end

    reg [21:0] heartbeat_count = 22'd0;
    reg heartbeat = 1'b0;
    always @(posedge clk_50mhz) begin
        if (heartbeat_count == 22'd2_499_999) begin
            heartbeat_count <= 22'd0;
            heartbeat <= ~heartbeat;
        end else begin
            heartbeat_count <= heartbeat_count + 1'b1;
        end
    end

    assign heartbeat_out = heartbeat;

    // The DUT-facing inout ports intentionally have no template drivers. They
    // therefore remain high impedance until an application adds drive logic.
    // Retaining the sampled input path prevents synthesis from deleting these
    // application-extension ports before package-pin assignment.
    (* syn_keep = "true" *)
    wire [111:0] dut_input_sample = {
        t0,
        t1,
        t2,
        b0,
        b1,
        b2,
        l0,
        l1,
        l2,
        r0,
        r1,
        r2,
        tx,
        bx,
        lx,
        rx
    };

    // Disable all twelve parallel translators. DIR is held low only to give
    // every control pin a deterministic level while its OE input is inactive.
    assign t0_dir = 1'b0;
    assign t1_dir = 1'b0;
    assign t2_dir = 1'b0;
    assign b0_dir = 1'b0;
    assign b1_dir = 1'b0;
    assign b2_dir = 1'b0;
    assign l0_dir = 1'b0;
    assign l1_dir = 1'b0;
    assign l2_dir = 1'b0;
    assign r0_dir = 1'b0;
    assign r1_dir = 1'b0;
    assign r2_dir = 1'b0;

    assign t0_oe_n = 1'b1;
    assign t1_oe_n = 1'b1;
    assign t2_oe_n = 1'b1;
    assign b0_oe_n = 1'b1;
    assign b1_oe_n = 1'b1;
    assign b2_oe_n = 1'b1;
    assign l0_oe_n = 1'b1;
    assign l1_oe_n = 1'b1;
    assign l2_oe_n = 1'b1;
    assign r0_oe_n = 1'b1;
    assign r1_oe_n = 1'b1;
    assign r2_oe_n = 1'b1;

    // U36 is a TXS0108 whose OE pin disables the device when low. The board
    // schematic calls this net ~F_XY_OE, hence the preserved _n port name.
    assign xy_oe_n = 1'b0;

    // Hold both sides of every external clock buffer inactive by default.
    assign tclk = 1'b0;
    assign tclk_en = 1'b0;
    assign bclk = 1'b0;
    assign bclk_en = 1'b0;
    assign lclk = 1'b0;
    assign lclk_en = 1'b0;
    assign rclk = 1'b0;
    assign rclk_en = 1'b0;

    // Safe board-level controls inherited from the heartbeat proof of concept.
    assign dut_isolate = 1'b1;
    assign dut_crowbar = 1'b0;
endmodule
