`timescale 1ns/1ps

// Scope ABI 4: a single-clock, append-only 256 KiB BRAM capture buffer.
// Filling the buffer stops only recording. Host reads never consume records.
module m68000_scope #(
    parameter integer ADDRESS_BITS = 15
) (
    input wire clock,
    input wire clear,
    input wire running,
    input wire run_busy,
    input wire aborted,
    input wire [31:0] timestamp,
    input wire [51:0] model_signals,
    input wire [51:0] socket_signals,
    input wire debug_valid,
    input wire debug_write,
    input wire [19:0] debug_address,
    input wire [15:0] debug_write_data,
    output reg debug_ready,
    output reg debug_error,
    output reg [15:0] debug_data,
    output wire busy,
    output wire start_allowed,
    output wire [1:0] selected_lane
);
    localparam integer CAPACITY = 1 << ADDRESS_BITS;
    localparam integer ROW_BITS = ADDRESS_BITS > 12 ? 12 : ADDRESS_BITS;
    localparam integer BANK_BITS = ADDRESS_BITS > 12 ? ADDRESS_BITS - 12 : 1;
    localparam integer BANKS = 1 << (ADDRESS_BITS - ROW_BITS);

    initial begin
        debug_ready = 0;
        debug_error = 0;
        debug_data = 0;
    end
    reg [1:0] lane = 0;
    reg [1:0] bank = 0;
    reg [31:0] capture_start = 0;
    reg [31:0] capture_end = 32'hffffffff;
    reg access_seen = 0;
    reg [2:0] read_pending = 0;
    reg [BANK_BITS-1:0] read_bank = 0;
    reg [1:0] read_quarter = 0;
    wire stopped, record_valid;
    wire [3:0] reason;
    wire [63:0] record_data;
    wire [31:0] accepted, first_tick, last_tick, missed_tick;

    // A local write stage distributes address/data to each BRAM bank. A full
    // record per 20 ns tick is accepted; there is no drain clock or backpressure.
    reg write_pending = 0;
    reg [ADDRESS_BITS-1:0] write_address = 0;
    reg [63:0] write_data = 0;
    wire [63:0] bank_data [0:BANKS-1];
    wire [17:0] read_address = {bank, debug_address[15:0]};
    wire [ADDRESS_BITS-1:0] read_record = read_address[ADDRESS_BITS+2:3];
    wire memory_access = debug_address[19:16] == 4'h5;
    wire [63:0] selected_record = bank_data[read_bank];

    assign busy = !stopped || write_pending || (read_pending != 0);
    assign selected_lane = lane;
    assign start_allowed = !busy && capture_start <= capture_end;

    scope_encoder #(.RECORD_LIMIT(CAPACITY)) encoder (
        .clock(clock), .clear(clear), .enabled(lane != 0),
        .running(running), .aborted(aborted), .memory_fault(1'b0),
        .signals(lane == 2 ? socket_signals : model_signals),
        .timestamp(timestamp), .capture_start(capture_start), .capture_end(capture_end),
        .record_valid(record_valid), .record_ready(1'b1), .record_data(record_data),
        .stopped(stopped), .reason(reason), .record_count(accepted),
        .first_tick(first_tick), .last_tick(last_tick), .missed_tick(missed_tick)
    );

    for (genvar index = 0; index < BANKS; index = index + 1) begin : banks
        (* syn_ramstyle = "block_ram" *) reg [63:0] memory [0:(1 << ROW_BITS)-1];
        reg [63:0] read_word;
        always @(posedge clock) begin
            if (write_pending && !clear && (write_address >> ROW_BITS) == index)
                memory[write_address[ROW_BITS-1:0]] <= write_data;
            read_word <= memory[read_record[ROW_BITS-1:0]];
        end
        assign bank_data[index] = read_word;
    end

    always @(posedge clock) begin
        write_pending <= record_valid && !clear;
        if (record_valid) begin
            write_address <= accepted[ADDRESS_BITS-1:0];
            write_data <= record_data;
        end

        debug_ready <= 0;
        debug_error <= 0;
        if (!debug_valid)
            access_seen <= 0;
        if (read_pending != 0) begin
            read_pending <= read_pending - 1'b1;
            if (read_pending == 1) begin
                debug_data <= selected_record[read_quarter * 16 +: 16];
                debug_ready <= 1;
            end
        end
        if (debug_valid && !access_seen) begin
            access_seen <= 1;
            debug_ready <= 1;
            debug_data <= 0;
            if (memory_access) begin
                // Prevent reading live/uncommitted records or stale tail data.
                if (debug_write || busy || run_busy || debug_address[0] ||
                    {14'd0, read_address} >= (accepted << 3)) begin
                    debug_error <= 1;
                end else begin
                    read_bank <= BANK_BITS'(read_record >> ROW_BITS);
                    read_quarter <= debug_address[2:1];
                    read_pending <= 2;
                    debug_ready <= 0;
                end
            end else if (debug_write) begin
                if (busy || run_busy) begin
                    debug_error <= 1;
                end else begin
                    case (debug_address[7:0])
                        8'h32: capture_start[15:0] <= debug_write_data;
                        8'h34: capture_start[31:16] <= debug_write_data;
                        8'h36: begin
                            if (debug_write_data > 2)
                                debug_error <= 1;
                            else
                                lane <= debug_write_data[1:0];
                        end
                        8'h38: begin
                            if (debug_write_data >= 4)
                                debug_error <= 1;
                            else
                                bank <= debug_write_data[1:0];
                        end
                        8'h3a: capture_end[15:0] <= debug_write_data;
                        8'h3c: capture_end[31:16] <= debug_write_data;
                        default: debug_error <= 1;
                    endcase
                end
            end else begin
                case (debug_address[7:0])
                    8'h2e: debug_data <= accepted[15:0];
                    8'h30: debug_data <= 4;
                    8'h32: debug_data <= capture_start[15:0];
                    8'h34: debug_data <= capture_start[31:16];
                    8'h36: debug_data <= {14'd0, lane};
                    8'h38: debug_data <= {14'd0, bank};
                    8'h3a: debug_data <= capture_end[15:0];
                    8'h3c: debug_data <= capture_end[31:16];
                    8'h60: debug_data <= {11'd0, reason == 3, 1'b0,
                                         stopped && !write_pending, write_pending, !stopped};
                    // Bit 4 means ready; bit 5 is zero (no external memory PHY).
                    8'h62: debug_data <= {11'd0, 1'b1, reason};
                    8'h64, 8'h68, 8'h78: debug_data <= accepted[15:0];
                    8'h66, 8'h6a, 8'h7a: debug_data <= accepted[31:16];
                    8'h6c: debug_data <= first_tick[15:0];
                    8'h6e: debug_data <= first_tick[31:16];
                    8'h70: debug_data <= last_tick[15:0];
                    8'h72: debug_data <= last_tick[31:16];
                    8'h74: debug_data <= missed_tick[15:0];
                    8'h76: debug_data <= missed_tick[31:16];
                    8'h7c: debug_data <= ADDRESS_BITS;
                    8'h7e: debug_data <= 20;
                    default: debug_error <= 1;
                endcase
            end
        end
    end
endmodule
