`timescale 1ns/1ps

module scope_tb;
    reg clock = 0;
    always #10 clock = ~clock;
    reg clear = 0;
    reg running = 0;
    reg [31:0] timestamp = 0;
    reg [51:0] signals = 0;
    reg valid = 0;
    reg write = 0;
    reg [19:0] address = 0;
    reg [15:0] write_data = 0;
    wire ready, error;
    wire [15:0] read_data;
    wire busy, start_allowed;
    m68000_scope dut (
        .clock(clock),
        .clear(clear), .running(running), .run_busy(running),
        .aborted(1'b0), .timestamp(timestamp),
        .model_signals(signals), .socket_signals(~signals),
        .debug_valid(valid), .debug_write(write), .debug_address(address),
        .debug_write_data(write_data), .debug_ready(ready),
        .debug_error(error), .debug_data(read_data), .busy(busy),
        .start_allowed(start_allowed)
    );

    task automatic access(input bit wr, input [19:0] addr, input [15:0] value,
                          output reg [15:0] result, input bit expected_error = 0);
        integer budget;
        begin
            @(negedge clock);
            valid = 1;
            write = wr;
            address = addr;
            write_data = value;
            budget = 10000;
            do begin
                @(negedge clock);
                budget = budget - 1;
                if (!budget)
                    $fatal(1, "debug timeout at %h", addr);
            end while (!ready);
            if (error != expected_error)
                $fatal(1, "debug error at %h", addr);
            result = read_data;
            valid = 0;
            @(negedge clock);
        end
    endtask

    reg [15:0] value;
    reg [63:0] record;
    integer count;
    integer decoded_tick;
    integer previous_tick;
    initial begin
        #100;
        access(0, 'h30, 0, value);
        if (value != 4)
            $fatal(1, "expected BRAM scope ABI 4");
        access(1, 'h36, 1, value);
        @(negedge clock);
        clear = 1;
        @(negedge clock);
        clear = 0;
        repeat (10) @(negedge clock);
        for (integer tick = 0; tick < 9000; tick = tick+1) begin
            running = 1;
            timestamp = tick;
            // Includes long unchanged periods forcing delta-counter records.
            signals = tick < 4200 ? 52'h123456789abcd : 52'h123456789abce;
            @(negedge clock);
        end
        running = 0;
        #10000;
        access(0, 'h60, 0, value);
        if (value != 4)
            $fatal(1, "capture not cleanly drained: %h", value);
        access(0, 'h64, 0, value);
        count = value;
        if (count != 5)
            $fatal(1, "expected five change/timeout/end records, got %0d", count);
        decoded_tick = 0;
        previous_tick = 0;
        for (integer row = 0; row < count; row = row+1) begin
            if ((row % 8192) == 0)
                access(1, 'h38, 16'(row / 8192), value);
            for (integer word_index = 0; word_index < 4; word_index = word_index+1) begin
                access(0, 20'h50000 + (row % 8192)*8 + word_index*2, 0, value);
                record[word_index*16 +: 16] = value;
            end
            decoded_tick = decoded_tick + record[63:52];
            if (record[51:0] !== (decoded_tick < 4200 ? 52'h123456789abcd : 52'h123456789abce))
                $fatal(1, "bad snapshot row %0d: %h", row, record);
            if (row > 0 && decoded_tick <= previous_tick)
                $fatal(1, "nonmonotonic sample timestamp");
            previous_tick = decoded_tick;
        end
        if (decoded_tick != 8999)
            $fatal(1, "terminal timestamp lost: %0d", decoded_tick);

        // Fill every BRAM bank at one record per tick, then keep the CPU running.
        @(negedge clock);
        clear = 1;
        @(negedge clock);
        clear = 0;
        repeat (10) @(negedge clock);
        for (integer tick = 0; tick < 32784; tick = tick+1) begin
            running = 1;
            timestamp = tick;
            signals = tick;
            @(negedge clock);
        end
        running = 0;
        #100000;
        access(0, 'h60, 0, value);
        if (value != 20)
            $fatal(1, "capacity was not reported: %h", value);
        access(0, 'h64, 0, value);
        count = value;
        if (count != 32768)
            $fatal(1, "wrong BRAM record capacity: %0d", count);
        access(0, 'h74, 0, value);
        if (value != 32768)
            $fatal(1, "wrong first missed tick: %0d", value);
        access(0, 'h68, 0, value);
        if (value != count)
            $fatal(1, "accepted prefix not fully committed");
        for (integer row = 0; row < count; row = row+1) begin
            if ((row % 8192) == 0)
                access(1, 'h38, 16'(row / 8192), value);
            for (integer word_index = 0; word_index < 4; word_index = word_index+1) begin
                access(0, 20'(20'h50000 + (row % 8192)*8 + word_index*2), 0, value);
                record[word_index*16 +: 16] = value;
            end
            if (record !== {row == 0 ? 12'd0 : 12'd1, 52'(row)})
                $fatal(1, "FIFO wrap/overflow prefix corrupted at %0d", row);
        end

        // Non-destructive repeat read of the last record, then reject writes
        // and the removed external-memory test command.
        access(0, 'h5fff8, 0, value);
        if (value != 32767)
            $fatal(1, "final record changed during download");
        access(1, 'h50000, 0, value, 1);
        access(1, 'h38, 4, value, 1);
        access(1, 'h88, 1, value, 1);
        access(1, 'h38, 0, value);

        // Exactly filling the buffer on the final tick is complete, not a
        // capacity failure: no additional change record was lost.
        @(negedge clock);
        clear = 1;
        @(negedge clock);
        clear = 0;
        for (integer tick = 0; tick < 32768; tick = tick+1) begin
            running = 1;
            timestamp = tick;
            signals = tick;
            @(negedge clock);
        end
        running = 0;
        repeat (8) @(negedge clock);
        access(0, 'h60, 0, value);
        if (value != 4)
            $fatal(1, "exact-capacity terminal capture should be complete: %h", value);

        // Live captures cannot be read or reconfigured by the host.
        @(negedge clock);
        clear = 1;
        @(negedge clock);
        clear = 0;
        running = 1;
        timestamp = 0;
        repeat (8) @(negedge clock);
        access(0, 'h50000, 0, value, 1);
        access(1, 'h36, 2, value, 1);
        running = 0;
        repeat (8) @(negedge clock);

        // Lane selection applies before encoding: only socket values appear.
        access(1, 'h36, 2, value);
        @(negedge clock);
        clear = 1;
        @(negedge clock);
        clear = 0;
        repeat (10) @(negedge clock);
        for (integer tick = 0; tick < 100; tick = tick+1) begin
            running = 1;
            timestamp = tick;
            signals = tick;
            @(negedge clock);
        end
        running = 0;
        #100000;
        for (integer word_index = 0; word_index < 4; word_index = word_index+1) begin
            access(0, 20'(20'h50000 + word_index*2), 0, value);
            record[word_index*16 +: 16] = value;
        end
        if (record !== {12'd0, {52{1'b1}}})
            $fatal(1, "selected socket capture contains wrong lane: %h", record);

        access(0, 'h50320, 0, value, 1);
        $display("PASS: BRAM selected lane, timeout records, full capacity, all banks, repeat reads, stale-tail rejection");
        $finish;
    end
    initial begin
        #300000000;
        $fatal(1, "scope test watchdog");
    end
endmodule
