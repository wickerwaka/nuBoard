`timescale 1ns/1ps

// Exercise the production-depth RAM and every bank, independently of PSRAM.
module scope_fifo_tb;
    reg write_clock = 0;
    reg read_clock = 0;
    always #10 write_clock = ~write_clock;
    always #5 read_clock = ~read_clock;
    reg reset = 1;
    reg write_valid = 0;
    reg [63:0] write_data = 0;
    reg pop = 0;
    wire write_ready, empty, read_valid;
    wire [15:0] occupancy;
    wire [63:0] read_data;
    integer expected = 0;
    integer read_count = 0;
    integer base = 0;

    scope_fifo fifo (
        .reset(reset), .write_clock(write_clock), .write_valid(write_valid),
        .write_data(write_data), .write_ready(write_ready), .occupancy(occupancy),
        .read_clock(read_clock), .pop(pop), .empty(empty),
        .read_valid(read_valid), .read_data(read_data)
    );

    always @(negedge read_clock) begin
        if (read_valid) begin
            if (read_data !== (64'hfeed123400000000 | 64'(expected)))
                $fatal(1, "FIFO bank/wrap corruption: expected %0d, got %h", expected, read_data);
            expected = expected + 1;
            read_count = read_count + 1;
        end
    end

    initial begin
        #100;
        @(negedge write_clock);
        reset = 0;
        repeat (4) @(negedge write_clock);
        for (integer round = 0; round < 2; round = round+1) begin
            base = round * 32768;
            for (integer row = 0; row < 32768; row = row+1) begin
                if (!write_ready)
                    $fatal(1, "FIFO filled before production capacity");
                write_valid = 1;
                write_data = 64'hfeed123400000000 | 64'(base + row);
                @(negedge write_clock);
            end
            write_valid = 0;
            if (write_ready || occupancy != 32768)
                $fatal(1, "FIFO did not report full at exactly 32768 records");
            @(posedge read_clock);
            #0.1 pop = 1;
            wait (read_count == base + 32768);
            @(posedge read_clock);
            #0.1 pop = 0;
            repeat (5) @(negedge write_clock);
            if (!empty || occupancy != 0 || !write_ready)
                $fatal(1, "FIFO did not drain cleanly");
        end
        // Drain concurrently at four times the producer's clock rate. This
        // catches publishing a reserved pointer before its staged RAM write.
        base = 65536;
        pop = 1;
        for (integer row = 0; row < 1024; row = row+1) begin
            if (!write_ready)
                $fatal(1, "concurrent FIFO producer unexpectedly blocked");
            write_valid = 1;
            write_data = 64'hfeed123400000000 | 64'(base + row);
            @(negedge write_clock);
        end
        write_valid = 0;
        wait (read_count == base + 1024);
        @(posedge read_clock);
        #0.1 pop = 0;
        repeat (5) @(negedge write_clock);
        if (!empty || occupancy != 0)
            $fatal(1, "concurrent FIFO stream did not drain");
        $display("PASS: production FIFO, every bank, full, wrap, concurrent staged writes");
        $finish;
    end
    initial begin
        #3000000;
        $fatal(1, "FIFO test watchdog");
    end
endmodule
