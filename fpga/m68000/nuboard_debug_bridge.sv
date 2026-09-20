`timescale 1ns/1ps

// CPU-independent NDB1 mailbox application. READ/WRITE transfer up to 4068
// bytes. FILL repeats one word over up to 65534 bytes. WAIT executes locally
// and produces one completion packet/IRQ; the host does not poll registers.
module nuboard_debug_bridge (
    input wire clock,
    input wire input_valid,
    output wire input_ready,
    input wire [7:0] input_data,
    input wire input_last,
    output wire output_valid,
    input wire output_ready,
    output wire [7:0] output_data,
    output wire output_last,

    output reg debug_valid = 1'b0,
    output reg debug_write = 1'b0,
    output reg [19:0] debug_address = 20'd0,
    output reg [15:0] debug_write_data = 16'd0,
    input wire debug_ready,
    input wire debug_error,
    input wire [15:0] debug_read_data
);
    localparam RECEIVE = 4'd0;
    localparam VALIDATE = 4'd1;
    localparam ISSUE = 4'd2;
    localparam ACCESS = 4'd3;
    localparam ADVANCE = 4'd4;
    localparam CHECKSUM = 4'd5;
    localparam HEADER = 4'd6;
    localparam TRANSMIT = 4'd7;
    localparam TX_PREFETCH = 4'd8;
    localparam CRC_PREFETCH = 4'd9;

    localparam READ = 8'd0;
    localparam WRITE = 8'd1;
    localparam WAIT = 8'd2;
    localparam FILL = 8'd3;

    reg [3:0] state = RECEIVE;
    // Only the small headers have asynchronous/multiple-byte access. The
    // payload is a single-write, synchronous-read word RAM suitable for BRAM.
    // Reuse it for replies after request consumption; no large byte mux.
    reg [7:0] request_header [0:35];
    reg [7:0] reply_header [0:19];
    (* syn_ramstyle = "block_ram" *) reg [15:0] payload [0:2047];
    reg [15:0] payload_read_data;
    reg [7:0] input_low = 8'd0;
    reg [11:0] index = 12'd0;
    reg [12:0] received = 13'd0;
    reg oversized = 1'b0;
    reg [15:0] transfer_length = 16'd0;
    reg [15:0] offset = 16'd0;
    reg [11:0] reply_length = 12'd4;
    reg [7:0] operation = READ;
    reg [19:0] base_address = 20'd0;
    reg [15:0] wait_mask = 16'd0;
    reg [15:0] wait_value = 16'd0;
    reg [15:0] fill_value = 16'd0;
    reg [31:0] wait_budget = 32'd0;
    reg [31:0] crc = 32'hffffffff;

    wire [15:0] requested_length = {request_header[23], request_header[22]};
    wire [31:0] requested_address = {request_header[27], request_header[26],
                                     request_header[25], request_header[24]};
    wire [31:0] requested_budget = {request_header[35], request_header[34],
                                    request_header[33], request_header[32]};
    wire [11:0] receive_offset = index - 12'd28;
    wire [11:0] reply_offset = index - 12'd20;
    wire accessing_bus = state == ISSUE || state == ACCESS || state == ADVANCE;
    wire [10:0] payload_read_address = accessing_bus ? offset[11:1] : reply_offset[11:1];
    wire [7:0] reply_byte = index < 20 ? reply_header[index[4:0]] :
                           index[0] ? payload_read_data[15:8] : payload_read_data[7:0];
    wire receiving_word = state == RECEIVE && input_valid && index >= 28 && index[0];
    wire reading_word = state == ACCESS && debug_ready && !debug_error &&
                        (operation == READ || (operation == WAIT &&
                         (debug_read_data & wait_mask) == wait_value));
    // Mux the two producers BEFORE the RAM port. Separate indexed assignments
    // are inferred as incompatible write ports by Efinity, even when exclusive.
    wire payload_write_enable = receiving_word || reading_word;
    wire [10:0] payload_write_address = receiving_word ? receive_offset[11:1] : offset[11:1];
    wire [15:0] payload_write_data = receiving_word ? {input_data, input_low} : debug_read_data;

    assign input_ready = state == RECEIVE;
    assign output_valid = state == TRANSMIT;
    assign output_data = reply_byte;
    assign output_last = index == reply_length + 12'd15;

    function [31:0] crc_byte;
        input [31:0] previous;
        input [7:0] value;
        reg [31:0] next_crc;
        integer bit_index;
        begin
            next_crc = previous ^ {24'd0, value};
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                next_crc = (next_crc >> 1) ^ (next_crc[0] ? 32'h82f63b78 : 32'd0);
            crc_byte = next_crc;
        end
    endfunction

    // No reset/initialization on RAM. Every transmitted payload word was
    // written by a successful bus read, never by an incomplete request.
    always @(posedge clock) begin
        payload_read_data <= payload[payload_read_address];
        if (payload_write_enable)
            payload[payload_write_address] <= payload_write_data;
    end

    always @(posedge clock) begin
        if (accessing_bus && operation == WAIT && wait_budget != 0)
            wait_budget <= wait_budget - 1'b1;

        case (state)
            RECEIVE: begin
                if (input_valid) begin
                    if (index < 36)
                        request_header[index[5:0]] <= input_data;
                    if (!index[0])
                        input_low <= input_data;
                    if (input_last) begin
                        received <= {1'b0, index} + 1'b1;
                        state <= VALIDATE;
                    end else if (index == 12'd4095) begin
                        oversized <= 1'b1;
                    end else begin
                        index <= index + 1'b1;
                    end
                end
            end
            VALIDATE: begin
                // Mailbox ingress has already verified packet CRC and length.
                // Preserve channel/tag and construct a new response header.
                reply_header[1] <= request_header[1];
                reply_header[4] <= request_header[4];
                reply_header[5] <= request_header[5];
                reply_header[6] <= request_header[6];
                reply_header[7] <= request_header[7];
                reply_header[16] <= 8'd0;
                reply_header[17] <= 8'd0;
                reply_header[18] <= 8'd0;
                reply_header[19] <= 8'd0;
                reply_length <= 12'd4;
                index <= 12'd16;
                crc <= 32'hffffffff;
                offset <= 16'd0;
                operation <= request_header[20];
                transfer_length <= requested_length;
                base_address <= requested_address[19:0];
                wait_mask <= {request_header[29], request_header[28]};
                wait_value <= {request_header[31], request_header[30]};
                fill_value <= {request_header[29], request_header[28]};
                wait_budget <= requested_budget;

                if (oversized || received < 28 || request_header[0] != 1 ||
                    request_header[1] != 8'h44 || request_header[2] != 3 ||
                    request_header[3] != 0 ||
                    {request_header[19], request_header[18], request_header[17],
                     request_header[16]} != 32'h3142444e ||
                    request_header[21] != 0 || request_header[20] > FILL ||
                    requested_length == 0 || requested_length[0] ||
                    (request_header[20] != FILL && requested_length > 4068) ||
                    requested_address[0] || requested_address[31:20] != 0 ||
                    requested_address + {16'd0, requested_length} > 32'h100000 ||
                    (request_header[20] == READ && received != 28) ||
                    (request_header[20] == WRITE &&
                     {3'd0, received} != 16'd28 + requested_length) ||
                    (request_header[20] == WAIT &&
                     (received != 36 || requested_length != 2 ||
                      requested_budget == 0 || requested_budget > 100_000_000)) ||
                    (request_header[20] == FILL && received != 30)) begin
                    reply_header[16] <= 8'd1;
                    state <= CRC_PREFETCH;
                end else begin
                    if (request_header[20] == READ || request_header[20] == WAIT)
                        reply_length <= requested_length[11:0] + 12'd4;
                    state <= ADVANCE;
                end
            end
            // Allow the synchronous RAM read before ISSUE, including the
            // first word and every offset change.
            ADVANCE: state <= ISSUE;
            ISSUE: begin
                debug_address <= base_address + {4'd0, offset};
                debug_write <= operation == WRITE || operation == FILL;
                debug_write_data <= operation == FILL ? fill_value : payload_read_data;
                debug_valid <= 1'b1;
                state <= ACCESS;
            end
            ACCESS: begin
                if (debug_ready) begin
                    debug_valid <= 1'b0;
                    if (debug_error) begin
                        reply_header[16] <= 8'd1;
                        reply_length <= 12'd4;
                        state <= CRC_PREFETCH;
                    end else if (operation == WAIT &&
                                 (debug_read_data & wait_mask) != wait_value) begin
                        if (wait_budget == 0) begin
                            reply_header[16] <= 8'd3;
                            reply_length <= 12'd4;
                            state <= CRC_PREFETCH;
                        end else begin
                            state <= ADVANCE;
                        end
                    end else if (offset + 16'd2 == transfer_length) begin
                        state <= CRC_PREFETCH;
                    end else begin
                        offset <= offset + 16'd2;
                        state <= ADVANCE;
                    end
                end
            end
            // Prefetch cycles accommodate BRAM latency. On output stalls the
            // index and payload address stay fixed, preserving valid/data/last.
            CRC_PREFETCH: state <= CHECKSUM;
            CHECKSUM: begin
                crc <= crc_byte(crc, reply_byte);
                if (output_last) begin
                    state <= HEADER;
                end else begin
                    index <= index + 1'b1;
                    state <= CRC_PREFETCH;
                end
            end
            HEADER: begin
                reply_header[0] <= 8'd1;
                reply_header[2] <= 8'd3;
                reply_header[3] <= 8'd0;
                reply_header[8] <= reply_length[7:0];
                reply_header[9] <= {4'd0, reply_length[11:8]};
                reply_header[10] <= 8'd0;
                reply_header[11] <= 8'd0;
                reply_header[12] <= ~crc[7:0];
                reply_header[13] <= ~crc[15:8];
                reply_header[14] <= ~crc[23:16];
                reply_header[15] <= ~crc[31:24];
                index <= 12'd0;
                state <= TX_PREFETCH;
            end
            TX_PREFETCH: state <= TRANSMIT;
            TRANSMIT: begin
                if (output_ready) begin
                    if (output_last) begin
                        index <= 12'd0;
                        oversized <= 1'b0;
                        state <= RECEIVE;
                    end else begin
                        index <= index + 1'b1;
                        state <= TX_PREFETCH;
                    end
                end
            end
            default: state <= RECEIVE;
        endcase
    end
endmodule
