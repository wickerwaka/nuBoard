`timescale 1ns/1ps

module scope_encoder_tb;
    reg clock = 0;
    always #10 clock = ~clock;
    reg clear = 0, running = 0, aborted = 0, fault = 0, ready = 1;
    reg [51:0] signals = 0;
    reg [31:0] timestamp = 0, capture_start = 0, capture_end = 32'hffffffff;
    wire valid, stopped;
    wire [63:0] data;
    wire [3:0] reason;
    wire [31:0] count, first_tick, last_tick, missed_tick;
    integer accepted = 0;
    reg [63:0] records [0:7];
    scope_encoder #(.RECORD_LIMIT(4)) dut (
        .clock(clock), .clear(clear), .enabled(1'b1), .running(running),
        .aborted(aborted), .memory_fault(fault), .signals(signals),
        .timestamp(timestamp), .capture_start(capture_start), .capture_end(capture_end),
        .record_valid(valid), .record_ready(ready), .record_data(data),
        .stopped(stopped), .reason(reason), .record_count(count),
        .first_tick(first_tick), .last_tick(last_tick), .missed_tick(missed_tick)
    );
    always @(posedge clock) begin
        if (clear)
            accepted = 0;
        else if (valid && ready) begin
            records[accepted] = data;
            accepted = accepted + 1;
        end
    end
    task reset_capture;
        begin
            @(negedge clock);
            clear = 1;
            running = 0;
            aborted = 0;
            fault = 0;
            ready = 1;
            @(negedge clock);
            clear = 0;
        end
    endtask
    task finish_capture;
        begin
            running = 0;
            repeat (5) @(negedge clock);
            if (!stopped)
                $fatal(1, "encoder failed to stop after pipeline flush");
        end
    endtask
    initial begin
        reset_capture();
        for (integer tick = 0; tick < 8; tick = tick+1) begin
            running = 1;
            timestamp = tick;
            signals = 52'(tick);
            @(negedge clock);
        end
        finish_capture();
        if (reason != 3 || count != 4 || missed_tick != 4 || last_tick != 3)
            $fatal(1, "capacity did not preserve exact prefix");
        for (integer row = 0; row < 4; row = row+1)
            if (records[row] != {row == 0 ? 12'd0 : 12'd1, 52'(row)})
                $fatal(1, "capacity prefix record mismatch");

        reset_capture();
        ready = 0;
        running = 1;
        timestamp = 7;
        repeat (4) @(negedge clock);
        finish_capture();
        if (reason != 2 || count != 0 || missed_tick != 7)
            $fatal(1, "first-record FIFO overflow not reported");

        reset_capture();
        capture_start = 1000;
        running = 1;
        timestamp = 0;
        repeat (10) @(negedge clock);
        finish_capture();
        if (reason != 1 || count != 0)
            $fatal(1, "empty window is not cleanly complete");

        reset_capture();
        capture_start = 0;
        running = 1;
        timestamp = 0;
        @(negedge clock);
        aborted = 1;
        finish_capture();
        if (reason != 4 || count != 1 || first_tick != 0 || last_tick != 0)
            $fatal(1, "single-tick abort lost its final observation");

        reset_capture();
        fault = 1;
        repeat (2) @(negedge clock);
        if (!stopped || reason != 5 || valid)
            $fatal(1, "memory fault did not stop the encoder");
        $display("PASS: encoder capacity, first-record overflow, empty window, abort, fault");
        $finish;
    end
endmodule
