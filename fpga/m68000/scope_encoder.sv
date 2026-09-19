`timescale 1ns/1ps

// Lossless change encoding at the observation clock. There is deliberately no
// backpressure connection to the CPU: a missed record stops this recorder only.
module scope_encoder #(
    parameter integer RECORD_LIMIT = 262144
) (
    input  wire        clock,
    input  wire        clear,
    input  wire        enabled,
    input  wire        running,
    input  wire        aborted,
    input  wire        memory_fault,
    input  wire [51:0] signals,
    input  wire [31:0] timestamp,
    input  wire [31:0] capture_start,
    input  wire [31:0] capture_end,
    output wire        record_valid,
    input  wire        record_ready,
    output wire [63:0] record_data,
    output reg         stopped,
    output reg  [3:0]  reason,
    output reg  [31:0] record_count,
    output reg  [31:0] first_tick,
    output reg  [31:0] last_tick,
    output reg  [31:0] missed_tick
);
    initial begin
        stopped = 1;
        reason = 6;
        record_count = 0;
        first_tick = 0;
        last_tick = 0;
        missed_tick = 0;
    end
    // Timestamp the acquisition, not the eventual FIFO write. Both pipeline
    // stages have matching validity and time tags, including the final sample.
    reg [51:0] meta_signals;
    reg [51:0] sync_signals;
    reg [31:0] meta_tick;
    reg [31:0] sync_tick;
    reg meta_valid = 1'b0;
    reg sync_valid = 1'b0;
    reg meta_running = 1'b0;
    reg sync_running = 1'b0;
    reg run_seen = 1'b0;
    reg observed = 1'b0;
    reg [51:0] previous_signals;
    reg [31:0] previous_tick;
    reg [51:0] emitted_signals;
    reg [31:0] emitted_tick;

    wire finishing = observed && !sync_valid;
    wire [51:0] candidate_signals = sync_valid ? sync_signals : previous_signals;
    wire [31:0] candidate_tick = sync_valid ? sync_tick : previous_tick;
    wire [31:0] elapsed = candidate_tick - emitted_tick;
    wire needed = record_count == 0 ||
                  candidate_signals != emitted_signals ||
                  elapsed >= 4095 || (finishing && elapsed != 0);

    assign record_valid = !stopped && !memory_fault &&
                          (sync_valid || finishing) && needed &&
                          record_count < RECORD_LIMIT;
    assign record_data = {record_count == 0 ? 12'd0 : elapsed[11:0],
                          candidate_signals};

    always @(posedge clock) begin
        meta_signals <= signals;
        sync_signals <= meta_signals;
        meta_tick <= timestamp;
        sync_tick <= meta_tick;
        meta_valid <= running && enabled && timestamp >= capture_start &&
                      timestamp <= capture_end;
        sync_valid <= meta_valid;
        meta_running <= running;
        sync_running <= meta_running;

        if (clear) begin
            meta_valid <= 1'b0;
            sync_valid <= 1'b0;
            meta_running <= 1'b0;
            sync_running <= 1'b0;
            run_seen <= 1'b0;
            observed <= 1'b0;
            stopped <= !enabled;
            reason <= enabled ? 4'd0 : 4'd6;
            record_count <= 32'd0;
            first_tick <= 32'd0;
            last_tick <= 32'd0;
            missed_tick <= 32'd0;
            emitted_tick <= 32'd0;
            emitted_signals <= 52'd0;
        end else if (!stopped) begin
            if (sync_running)
                run_seen <= 1'b1;
            if (memory_fault) begin
                stopped <= 1'b1;
                reason <= 4'd5;
                missed_tick <= candidate_tick;
            end else if (sync_valid || finishing) begin
                if (needed && (record_count == RECORD_LIMIT || !record_ready)) begin
                    stopped <= 1'b1;
                    reason <= record_count == RECORD_LIMIT ? 4'd3 : 4'd2;
                    missed_tick <= candidate_tick;
                    // last_tick already identifies the preceding valid tick.
                end else begin
                    if (sync_valid) begin
                        observed <= 1'b1;
                        previous_signals <= sync_signals;
                        previous_tick <= sync_tick;
                        last_tick <= sync_tick;
                    end
                    if (record_valid) begin
                        if (record_count == 0)
                            first_tick <= candidate_tick;
                        emitted_signals <= candidate_signals;
                        emitted_tick <= candidate_tick;
                        record_count <= record_count + 1'b1;
                    end
                    if (finishing) begin
                        stopped <= 1'b1;
                        reason <= aborted ? 4'd4 : 4'd1;
                    end
                end
            end else if (!sync_running && run_seen) begin
                // A capture window beyond the run end is a valid empty trace,
                // not a recorder that remains busy forever.
                stopped <= 1'b1;
                reason <= aborted ? 4'd4 : 4'd1;
            end
        end
    end
endmodule
