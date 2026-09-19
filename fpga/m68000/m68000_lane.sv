`timescale 1ns/1ps

// One independently writable memory image and bus trace per CPU. Both the
// socket and fx68k go through this responder, including its input pipeline.
module m68000_lane (
    input  wire         clock,
    input  wire         clear,
    input  wire         running,
    input  wire [31:0]  timestamp,
    input  wire [7:0]   wait_ticks,
    input  wire [31:0]  capture_start,
    input  wire [255:0] page_map,
    input  wire [23:0]  address,
    input  wire [15:0]  data_out,
    input  wire         as_n,
    input  wire         uds_n,
    input  wire         lds_n,
    input  wire         read_cycle,
    input  wire [2:0]   function_code,
    output reg  [15:0]  data_in,
    output wire         data_drive,
    output reg          dtack_n,
    output reg          berr_n,
    output reg  [1:0]   result,
    output reg          overflow,
    output reg  [11:0]  trace_count,
    output reg  [31:0]  total_count,
    output reg  [31:0]  signature,

    input  wire [15:0]  host_address,
    input  wire         host_write,
    input  wire [15:0]  host_data,
    output wire [15:0]  host_read_data,
    input  wire [13:0]  trace_address,
    output reg  [15:0]  trace_data
);
    initial begin
        data_in = 16'd0;
        dtack_n = 1'b1;
        berr_n = 1'b1;
        result = 2'd0;
        overflow = 1'b0;
        trace_count = 12'd0;
        total_count = 32'd0;
        signature = 32'hffffffff;
    end
    reg [45:0] pins_meta;
    reg [45:0] pins_sync;
    always @(posedge clock) begin
        pins_meta <= {address, data_out, as_n, uds_n, lds_n, read_cycle,
                      function_code[1:0]};
        pins_sync <= pins_meta;
    end

    // FC is kept separately so the complete three-bit code is captured.
    reg [2:0] fc_meta;
    reg [2:0] fc_sync;
    always @(posedge clock) begin
        fc_meta <= function_code;
        fc_sync <= fc_meta;
    end

    wire [23:0] sampled_address = pins_sync[45:22];
    wire [15:0] sampled_data = pins_sync[21:6];
    wire sampled_as_n = pins_sync[5];
    wire sampled_uds_n = pins_sync[4];
    wire sampled_lds_n = pins_sync[3];
    wire sampled_read = pins_sync[2];
    wire selected = !sampled_as_n && (!sampled_uds_n || !sampled_lds_n);

    reg mapped;
    reg [3:0] page;
    integer page_index;
    always @* begin
        mapped = 1'b0;
        page = 4'd0;
        for (page_index = 0; page_index < 16; page_index = page_index + 1) begin
            if (page_map[page_index * 16 + 15] &&
                page_map[page_index * 16 +: 12] == sampled_address[23:12]) begin
                mapped = 1'b1;
                page = page_index[3:0];
            end
        end
    end

    wire mmio = sampled_address[23:8] == 16'h1000;
    reg [14:0] bus_word = 15'd0;
    reg [15:0] write_data = 16'd0;
    reg write_high = 1'b0;
    reg write_low = 1'b0;
    wire [14:0] memory_address = running ? bus_word : host_address[15:1];
    wire [15:0] memory_write_data = running ? write_data : host_data;
    wire memory_write_high = running ? write_high : host_write;
    wire memory_write_low = running ? write_low : host_write;

    (* syn_ramstyle = "block_ram" *) reg [7:0] memory_high [0:32767];
    (* syn_ramstyle = "block_ram" *) reg [7:0] memory_low [0:32767];
    reg [7:0] read_high;
    reg [7:0] read_low;
    always @(posedge clock) begin
        if (memory_write_high)
            memory_high[memory_address] <= memory_write_data[15:8];
        if (memory_write_low)
            memory_low[memory_address] <= memory_write_data[7:0];
        read_high <= memory_high[memory_address];
        read_low <= memory_low[memory_address];
    end
    assign host_read_data = {read_high, read_low};

    reg [2:0] state = 3'd0;
    reg bus_qualified = 1'b0;
    reg idle_sample_seen = 1'b0;
    reg [7:0] delay_count = 8'd0;
    reg [31:0] start_time = 32'd0;
    reg [23:0] transaction_address = 24'd0;
    reg [15:0] transaction_data = 16'd0;
    reg [7:0] transaction_flags = 8'd0;
    reg transaction_mapped = 1'b0;
    reg transaction_mmio = 1'b0;

    // A complete-run fingerprint detects nondeterministic window replays.
    // Exact comparisons still use the records, never the fingerprint alone.
    function [31:0] fold_transaction;
        input [31:0] crc;
        input [47:0] record;
        reg [31:0] value;
        integer bit_index;
        begin
            value = crc;
            for (bit_index = 0; bit_index < 48; bit_index = bit_index + 1)
                value = (value >> 1) ^ ((value[0] ^ record[bit_index])
                    ? 32'h82f63b78 : 32'd0);
            fold_transaction = value;
        end
    endfunction

    wire [15:0] normalized_data = transaction_data & {
        {8{transaction_flags[1]}}, {8{transaction_flags[0]}}
    };
    wire capture_enabled = total_count >= capture_start && trace_count < 12'd2048;

    assign data_drive = running && selected && sampled_read && state >= 3'd2;

    // Each record: start tick, byte address, data/flags, end tick. Capture
    // completed transfers, including both halves of a TAS read/modify/write.
    (* syn_ramstyle = "block_ram" *) reg [127:0] trace_memory [0:2047];
    reg [127:0] trace_read;
    reg [2:0] trace_half;
    always @(posedge clock) begin
        trace_read <= trace_memory[trace_address[13:3]];
        trace_half <= trace_address[2:0];
        trace_data <= trace_read[trace_half * 16 +: 16];
        if (running && state == 3'd3 && !selected && capture_enabled)
            trace_memory[trace_count[10:0]] <= {
                timestamp, 8'd0, transaction_flags, transaction_data,
                8'd0, transaction_address, start_time
            };
    end

    always @(posedge clock) begin
        write_high <= 1'b0;
        write_low <= 1'b0;

        if (clear) begin
            state <= 3'd0;
            bus_qualified <= 1'b0;
            idle_sample_seen <= 1'b0;
            dtack_n <= 1'b1;
            berr_n <= 1'b1;
            result <= 2'd0;
            trace_count <= 12'd0;
            total_count <= 32'd0;
            signature <= 32'hffffffff;
            overflow <= 1'b0;
        end else if (!running) begin
            state <= 3'd0;
            bus_qualified <= 1'b0;
            idle_sample_seen <= 1'b0;
            dtack_n <= 1'b1;
            berr_n <= 1'b1;
        end else begin
            // Reset can leave the physical strobes asserted or undriven. Do
            // not acknowledge, write RAM, or capture anything until two idle
            // samples establish the start of a real bus transaction sequence.
            // Once qualified, retain normal TAS read/modify/write behavior.
            if (!bus_qualified) begin
                if (sampled_as_n && sampled_uds_n && sampled_lds_n) begin
                    idle_sample_seen <= 1'b1;
                    bus_qualified <= idle_sample_seen;
                end else begin
                    idle_sample_seen <= 1'b0;
                end
            end
            case (state)
                3'd0: begin
                    if (bus_qualified && selected && result == 0) begin
                        bus_word <= {page, sampled_address[11:1]};
                        start_time <= timestamp;
                        transaction_address <= sampled_address;
                        transaction_flags <= {
                            1'b0, !mapped && !mmio, fc_sync,
                            sampled_read, !sampled_uds_n, !sampled_lds_n
                        };
                        transaction_mapped <= mapped;
                        transaction_mmio <= mmio;
                        transaction_data <= sampled_data;
                        delay_count <= wait_ticks;
                        state <= 3'd1;
                    end
                end
                3'd1: begin
                    // The fixed two-cycle read pipeline precedes this delay.
                    if (delay_count != 0) begin
                        delay_count <= delay_count - 1'b1;
                    end else begin
                        // The first strobe starts the existing ACK timer, but
                        // the other byte strobe and write data can arrive later.
                        // Sample their settled values one cycle before ACK;
                        // do not alter the timer or infer a word from one byte.
                        transaction_flags[1:0] <= {
                            !sampled_uds_n, !sampled_lds_n
                        };
                        data_in <= transaction_mapped ? host_read_data : 16'd0;
                        if (transaction_flags[2])
                            transaction_data <= transaction_mapped
                                ? host_read_data : 16'd0;
                        else
                            transaction_data <= sampled_data;
                        state <= 3'd2;
                    end
                end
                3'd2: begin
                    // Data is stable for a system cycle before DTACK falls.
                    dtack_n <= !(transaction_mapped || transaction_mmio);
                    berr_n <= transaction_mapped || transaction_mmio;
                    if (!transaction_flags[2] && transaction_mapped) begin
                        write_data <= transaction_data;
                        write_high <= transaction_flags[1];
                        write_low <= transaction_flags[0];
                    end
                    state <= 3'd3;
                end
                3'd3: begin
                    if (!selected) begin
                        dtack_n <= 1'b1;
                        berr_n <= 1'b1;
                        state <= 3'd0;
                        if (total_count == 32'hffffffff) begin
                            overflow <= 1'b1;
                            result <= 2'd3;
                        end
                        total_count <= total_count + 1'b1;
                        signature <= fold_transaction(signature, {
                            transaction_flags, normalized_data, transaction_address
                        });
                        if (capture_enabled) begin
                            trace_count <= trace_count + 1'b1;
                        end
                        // Longword MMIO writes terminate only on the second
                        // word, after the real CPU has completed the access.
                        if (!transaction_flags[2] && transaction_mmio) begin
                            if (transaction_address == 24'h100002)
                                result <= 2'd2;
                            if (transaction_address == 24'h100006)
                                result <= 2'd1;
                        end
                    end
                end
                default: state <= 3'd0;
            endcase
        end
    end
endmodule
