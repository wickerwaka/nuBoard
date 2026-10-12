`timescale 1ns/1ps

// Behavioural x8 HyperRAM for simulation: fixed 2x latency, linear bursts,
// memory and register reads, masked memory writes. Read data and RWDS follow
// each CK edge by tCKD (set at run time with +tckd=<ns>), so the controller's
// RWDS-based read capture is exercised at different board and device delays.
// The delay is a 250 ps delay line on the pad drivers: delayed nonblocking
// assignments would drop overlapping events once tCKD exceeds half a clock.
//
// The latency count starts with the third command-address clock, so the
// first data word is transferred on clock 3 + 2 * LATENCY.
module hyperram_model #(
    parameter integer LATENCY = 6,
    parameter [15:0] ID0 = 16'h0c83,
    parameter [15:0] ID1 = 16'h0001
) (
    input  wire       ck,
    input  wire       cs_n,
    input  wire       reset_n,
    inout  wire [7:0] dq,
    inout  wire       rwds
);
    localparam integer FIRST_DATA_EDGE = 4 + 4 * LATENCY;

    logic [15:0] memory [0:(1 << 22) - 1];

    realtime tckd = 3.0;
    integer inject_address = -1;
    // When >= 0, the next memory read stops strobing data after this many
    // words (a short read), then the setting clears itself.
    integer short_after = -1;
    integer errors = 0;
    initial begin
        void'($value$plusargs("tckd=%f", tckd));
        void'($value$plusargs("inject=%d", inject_address));
    end

    // Undelayed driver state, set at the CK and CS# edges.
    logic [7:0] dq_out = 8'd0;
    logic       rwds_out = 1'b0;
    logic       drive_dq = 1'b0;
    logic       drive_rwds = 1'b0;

    localparam integer TAPS = 64;
    logic [10:0] delay_line [0:TAPS-1];
    integer taps = 12;
    initial begin
        for (int i = 0; i < TAPS; i++)
            delay_line[i] = 11'd0;
        #0;
        taps = int'(tckd / 0.25);
        if (taps < 1)
            taps = 1;
        if (taps > TAPS - 1)
            taps = TAPS - 1;
        forever begin
            #0.25;
            for (int i = TAPS - 1; i > 0; i--)
                delay_line[i] = delay_line[i - 1];
            delay_line[0] = {drive_dq, drive_rwds, rwds_out, dq_out};
        end
    end
    wire [10:0] delayed = delay_line[taps];
    assign dq = delayed[10] ? delayed[7:0] : 8'bz;
    assign rwds = delayed[9] ? delayed[8] : 1'bz;

    integer edge_index = 0;
    logic [47:0] command_address = 48'd0;
    logic        is_read = 1'b0;
    logic        is_register = 1'b0;
    logic [21:0] address = 22'd0;
    logic [15:0] write_word = 16'd0;

    function automatic [15:0] read_word(input logic [21:0] word_address);
        logic [15:0] value;
        if (is_register)
            value = word_address == 22'd0 ? ID0 :
                    word_address == 22'd1 ? ID1 : 16'h0000;
        else
            value = memory[word_address];
        if (!is_register && inject_address >= 0 &&
            word_address == inject_address[21:0])
            value = value ^ 16'h0020;
        return value;
    endfunction

    // RWDS is high during command-address: fixed latency is always 2x.
    always @(negedge cs_n) begin
        edge_index = 0;
        if (!reset_n) begin
            $display("hyperram_model: CS# asserted during reset");
            errors = errors + 1;
        end
        rwds_out = 1'b1;
        drive_rwds = 1'b1;
    end

    always @(posedge cs_n) begin
        drive_dq = 1'b0;
        drive_rwds = 1'b0;
        if (is_read && !is_register && edge_index > FIRST_DATA_EDGE)
            short_after = -1;
    end

    always @(posedge ck or negedge ck) begin
        if (!cs_n) begin
            integer data_edge;
            integer word;
            logic [15:0] value;

            if (edge_index < 6) begin
                command_address[47 - 8 * edge_index -: 8] = dq;
                if (edge_index == 5) begin
                    is_read = command_address[47];
                    is_register = command_address[46];
                    address = {command_address[34:16], command_address[2:0]};
                    if (!command_address[45]) begin
                        $display("hyperram_model: wrapped burst requested");
                        errors = errors + 1;
                    end
                    if (!is_read && is_register) begin
                        $display("hyperram_model: unexpected register write");
                        errors = errors + 1;
                    end
                    // Reads keep RWDS low through the latency; for writes
                    // the host takes RWDS over as the data mask.
                    rwds_out = 1'b0;
                    if (!is_read)
                        drive_rwds = 1'b0;
                end
            end else if (edge_index >= FIRST_DATA_EDGE) begin
                data_edge = edge_index - FIRST_DATA_EDGE;
                word = data_edge / 2;
                if (is_read) begin
                    // Register reads repeat the addressed register; only
                    // memory reads advance through the burst.
                    value = read_word(is_register ? address
                                                  : address + word[21:0]);
                    dq_out = (data_edge % 2 == 0) ? value[15:8] : value[7:0];
                    rwds_out = data_edge % 2 == 0;
                    if (!is_register && short_after >= 0 && word >= short_after)
                        rwds_out = 1'b0;
                    drive_dq = 1'b1;
                end else if (data_edge % 2 == 0) begin
                    if (!rwds)
                        write_word[15:8] = dq;
                    else
                        write_word[15:8] = memory[address + word[21:0]][15:8];
                end else begin
                    if (!rwds)
                        write_word[7:0] = dq;
                    else
                        write_word[7:0] = memory[address + word[21:0]][7:0];
                    memory[address + word[21:0]] = write_word;
                end
            end
            edge_index = edge_index + 1;
        end
    end
endmodule
