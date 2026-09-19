`timescale 1ns/1ps

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

module nuboard_mailbox (
    input wire clk_50mhz,
    output wire heartbeat_out,
    output reg spi_miso,
    input wire spi_cs_n,
    input wire spi_sck,
    input wire spi_mosi,
    output wire fpga_irq_n,

    // Streams include the 16-byte mailbox header. The application constructs
    // its reply header/CRC and must repeat the request's channel and tag.
    output wire application_input_valid,
    input wire application_input_ready,
    output wire [7:0] application_input_data,
    output wire application_input_last,
    input wire application_output_valid,
    output wire application_output_ready,
    input wire [7:0] application_output_data,
    input wire application_output_last
);
    localparam [7:0] CMD_STATUS       = 8'h01;
    localparam [7:0] CMD_WRITE_PACKET = 8'h02;
    localparam [7:0] CMD_READ_PACKET  = 8'h03;
    localparam [7:0] CMD_ACK_PACKET   = 8'h04;
    localparam [7:0] CMD_GET_ID       = 8'h05;

    localparam [7:0] ABI_MAJOR = 8'd1;
    localparam integer SLOT_BYTES = 4096;
    localparam integer MAX_PAYLOAD = SLOT_BYTES - 16;

    wire psram_initialized = 1'b0;

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
    reg psram_ready_sync_1 = 1'b0;
    reg psram_ready_sync_2 = 1'b0;

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
        psram_ready_sync_1 <= psram_initialized;
        psram_ready_sync_2 <= psram_ready_sync_1;
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
                0:  identity_byte = 8'h6e; // UUID: "nuBoard-68000-v1"
                1:  identity_byte = 8'h75;
                2:  identity_byte = 8'h42;
                3:  identity_byte = 8'h6f;
                4:  identity_byte = 8'h61;
                5:  identity_byte = 8'h72;
                6:  identity_byte = 8'h64;
                7:  identity_byte = 8'h2d;
                8:  identity_byte = 8'h36;
                9:  identity_byte = 8'h38;
                10: identity_byte = 8'h30;
                11: identity_byte = 8'h30;
                12: identity_byte = 8'h30;
                13: identity_byte = 8'h2d;
                14: identity_byte = 8'h76;
                15: identity_byte = 8'h31;
                16: identity_byte = 8'h01; // core version 1
                17: identity_byte = 8'h00;
                18: identity_byte = 8'h00;
                19: identity_byte = 8'h00;
                20: identity_byte = 8'h08; // build 8: single-lane BRAM change capture
                21: identity_byte = 8'h00;
                22: identity_byte = 8'h00;
                23: identity_byte = 8'h00;
                24: identity_byte = ABI_MAJOR;
                25: identity_byte = 8'h00;
                26: identity_byte = 8'h00; // ABI minor 0
                27: identity_byte = 8'h00;
                28: identity_byte = 8'h04; // generic debug application
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
                            3'b000,
                            psram_ready_sync_2,
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

    // Application stream handoff. The pending flags provide
    // backpressure; neither mailbox slot is overwritten.
    always @(posedge clk_50mhz) begin
        if (!application_busy && inbound_pending_app &&
            !outbound_pending_app) begin
            application_busy <= 1'b1;
            delay_count <= 6'd32;
            copy_index <= 13'd0;
            output_index <= 13'd0;
            copy_data_valid <= 1'b0;
        end else if (application_busy && delay_count != 0) begin
            delay_count <= delay_count - 1'b1;
        end else if (application_busy && !copy_data_valid) begin
            // Prime the synchronous inbound RAM read before writing byte zero.
            copy_data_valid <= 1'b1;
        end else if (application_busy) begin
            if (application_input_valid && application_input_ready) begin
                if (application_input_last) begin
                    copy_data_valid <= 1'b0;
                    app_seen_write <= write_sync_2;
                end else begin
                    copy_index <= copy_index + 1'b1;
                end
            end

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

endmodule
