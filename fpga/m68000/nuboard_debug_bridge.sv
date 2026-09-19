`timescale 1ns/1ps

// CPU-independent NDB1 mailbox application. WAIT executes in the FPGA and
// produces one completion packet/IRQ; USB does not poll the target register.
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

    output reg debug_valid,
    output reg debug_write,
    output reg [19:0] debug_address,
    output reg [15:0] debug_write_data,
    input wire debug_ready,
    input wire debug_error,
    input wire [15:0] debug_read_data
);
    initial begin
        debug_valid = 1'b0;
        debug_write = 1'b0;
        debug_address = 20'd0;
        debug_write_data = 16'd0;
    end
    localparam RECEIVE = 4'd0;
    localparam VALIDATE = 4'd1;
    localparam ISSUE = 4'd2;
    localparam ACCESS = 4'd3;
    localparam ADVANCE = 4'd4;
    localparam CHECKSUM = 4'd5;
    localparam HEADER = 4'd6;
    localparam TRANSMIT = 4'd7;
    localparam TX_PREFETCH = 4'd8;

    reg [3:0] state = RECEIVE;
    reg [7:0] buffer [0:511];
    reg [8:0] index = 9'd0;
    reg [9:0] received = 10'd0;
    reg oversized = 1'b0;
    reg [8:0] transfer_length = 9'd0;
    reg [8:0] offset = 9'd0;
    reg [8:0] reply_length = 9'd4;
    reg [7:0] operation = 8'd0;
    reg [19:0] base_address = 20'd0;
    reg [15:0] wait_mask = 16'd0;
    reg [15:0] wait_value = 16'd0;
    reg [31:0] wait_budget = 32'd0;
    reg [31:0] crc = 32'hffffffff;
    reg [7:0] transmit_byte = 0;

    wire [15:0] requested_length = {buffer[23], buffer[22]};
    wire [31:0] requested_address = {buffer[27], buffer[26], buffer[25], buffer[24]};
    wire [31:0] requested_budget = {buffer[35], buffer[34], buffer[33], buffer[32]};

    assign input_ready = state == RECEIVE;
    assign output_valid = state == TRANSMIT;
    assign output_data = transmit_byte;
    assign output_last = index == reply_length + 9'd15;

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

    always @(posedge clock) begin
        // Register the buffer mux before the mailbox RAM write port. A
        // prefetch cycle follows each index change; stalls preserve the byte.
        transmit_byte <= buffer[index];
        if ((state == ISSUE || state == ACCESS || state == ADVANCE) &&
            operation == 2 && wait_budget != 0)
            wait_budget <= wait_budget - 1'b1;

        case (state)
            RECEIVE: begin
                if (input_valid) begin
                    buffer[index] <= input_data;
                    if (input_last) begin
                        received <= {1'b0, index} + 1'b1;
                        state <= VALIDATE;
                    end else if (index == 9'd511) begin
                        oversized <= 1'b1;
                    end else begin
                        index <= index + 1'b1;
                    end
                end
            end
            VALIDATE: begin
                // Preserve the channel/tag in bytes 1 and 4..7. The mailbox
                // has already checked packet length and payload CRC32C.
                buffer[16] <= 8'd0;
                buffer[17] <= 8'd0;
                buffer[18] <= 8'd0;
                buffer[19] <= 8'd0;
                reply_length <= 9'd4;
                index <= 9'd16;
                crc <= 32'hffffffff;
                offset <= 9'd0;
                operation <= buffer[20];
                transfer_length <= requested_length[8:0];
                base_address <= requested_address[19:0];
                wait_mask <= {buffer[29], buffer[28]};
                wait_value <= {buffer[31], buffer[30]};
                wait_budget <= requested_budget;

                if (oversized || received < 28 || buffer[0] != 1 ||
                    buffer[1] != 8'h44 || buffer[2] != 3 || buffer[3] != 0 ||
                    {buffer[19], buffer[18], buffer[17], buffer[16]} != 32'h3142444e ||
                    buffer[21] != 0 || buffer[20] > 2 ||
                    requested_length == 0 || requested_length > 256 ||
                    requested_length[0] || requested_address[0] ||
                    requested_address[31:20] != 0 ||
                    requested_address + {16'd0, requested_length} > 32'h100000 ||
                    (buffer[20] == 0 && received != 28) ||
                    (buffer[20] == 1 && {6'd0, received} != 16'd28 + requested_length) ||
                    (buffer[20] == 2 && (received != 36 || requested_length != 2 ||
                      requested_budget == 0 || requested_budget > 100_000_000))) begin
                    buffer[16] <= 8'd1;
                    state <= CHECKSUM;
                end else begin
                    if (buffer[20] != 1)
                        reply_length <= requested_length[8:0] + 9'd4;
                    state <= ISSUE;
                end
            end
            ISSUE: begin
                debug_address <= base_address + {11'd0, offset};
                debug_write <= operation == 1;
                debug_write_data <= {buffer[29 + offset], buffer[28 + offset]};
                debug_valid <= 1'b1;
                state <= ACCESS;
            end
            ACCESS: begin
                if (debug_ready) begin
                    debug_valid <= 1'b0;
                    if (debug_error) begin
                        buffer[16] <= 8'd1;
                        reply_length <= 9'd4;
                        state <= CHECKSUM;
                    end else if (operation == 2 &&
                                 (debug_read_data & wait_mask) != wait_value) begin
                        if (wait_budget == 0) begin
                            buffer[16] <= 8'd3;
                            reply_length <= 9'd4;
                            state <= CHECKSUM;
                        end else begin
                            state <= ADVANCE;
                        end
                    end else begin
                        if (operation != 1) begin
                            buffer[20 + offset] <= debug_read_data[7:0];
                            buffer[21 + offset] <= debug_read_data[15:8];
                        end
                        if (offset + 9'd2 == transfer_length) begin
                            state <= CHECKSUM;
                        end else begin
                            offset <= offset + 9'd2;
                            state <= ADVANCE;
                        end
                    end
                end
            end
            ADVANCE: state <= ISSUE;
            CHECKSUM: begin
                crc <= crc_byte(crc, buffer[index]);
                if (index == reply_length + 9'd15)
                    state <= HEADER;
                else
                    index <= index + 1'b1;
            end
            HEADER: begin
                buffer[0] <= 8'd1;
                buffer[2] <= 8'd3;
                buffer[3] <= 8'd0;
                buffer[8] <= reply_length[7:0];
                buffer[9] <= {7'd0, reply_length[8]};
                buffer[10] <= 8'd0;
                buffer[11] <= 8'd0;
                buffer[12] <= ~crc[7:0];
                buffer[13] <= ~crc[15:8];
                buffer[14] <= ~crc[23:16];
                buffer[15] <= ~crc[31:24];
                index <= 9'd0;
                state <= TX_PREFETCH;
            end
            TX_PREFETCH: state <= TRANSMIT;
            TRANSMIT: begin
                if (output_ready) begin
                    if (output_last) begin
                        index <= 9'd0;
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
