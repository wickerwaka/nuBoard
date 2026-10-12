`timescale 1ns/1ps

// Buffered HyperRAM core plus test harness against the behavioural model.
// Parameters (set with -G): USER_WIDTH, BURST_WORDS.
// Run-time options:
//   +mhz=<n>      HyperRAM clock (default 100)
//   +phase=<deg>  clk_hr_cal phase (default 90)
//   +tckd=<ns>    device CK-to-data delay (default 3.0)
// The producer clock runs at 37 MHz, unrelated to the HyperRAM clock.
module hyperram_tb #(
    parameter integer USER_WIDTH = 64,
    parameter integer BURST_WORDS = 64
);
    localparam integer BUFFER_BITS = 2;
    localparam integer WORD_BITS = $clog2(BURST_WORDS);
    localparam integer BURST_BITS = 22 - WORD_BITS;
    localparam integer USER_ADDRESS_BITS =
        BUFFER_BITS + $clog2(BURST_WORDS * 16 / USER_WIDTH);

    real period = 10.0;
    real phase = 90.0;
    integer mhz = 100;
    integer phase_degrees = 90;

    reg clk_hr = 1'b0;
    reg clk_hr90 = 1'b0;
    reg clk_hr_cal = 1'b0;
    reg user_clock = 1'b0;
    reg pll_locked = 1'b0;

    initial begin
        void'($value$plusargs("mhz=%d", mhz));
        void'($value$plusargs("phase=%d", phase_degrees));
        period = 1000.0 / mhz;
        phase = phase_degrees;
    end
    initial begin
        #1;
        forever #(period / 2.0) clk_hr = ~clk_hr;
    end
    initial begin
        #1;
        #(period / 4.0);
        forever #(period / 2.0) clk_hr90 = ~clk_hr90;
    end
    initial begin
        #1;
        #(period * phase / 360.0);
        forever #(period / 2.0) clk_hr_cal = ~clk_hr_cal;
    end
    always #13.5 user_clock = ~user_clock;

    wire                         user_write_enable;
    wire [USER_ADDRESS_BITS-1:0] user_write_address;
    wire [USER_WIDTH-1:0]        user_write_data;
    wire [USER_ADDRESS_BITS-1:0] user_read_address;
    wire [USER_WIDTH-1:0]        user_read_data;
    wire                         command_valid;
    wire                         command_ready;
    wire                         command_write;
    wire [BUFFER_BITS-1:0]       command_buffer;
    wire [BURST_BITS-1:0]        command_burst;
    wire                         done_valid;
    wire                         done_ready;
    wire                         done_write;
    wire [BUFFER_BITS-1:0]       done_buffer;
    wire [WORD_BITS:0]           done_short;
    wire                         init_done;
    wire [15:0]                  id0;
    wire [15:0]                  id1;

    wire       hr_ck;
    wire       hr_cs_n;
    wire       hr_reset_n;
    wire       hr_rwds;
    wire [7:0] hr_dq;

    hyperram_trace_core #(
        .HR_MHZ(20),
        .BURST_WORDS(BURST_WORDS),
        .BUFFER_BITS(BUFFER_BITS),
        .USER_WIDTH(USER_WIDTH)
    ) dut (
        .clk_hr(clk_hr),
        .clk_hr90(clk_hr90),
        .clk_hr_cal(clk_hr_cal),
        .pll_locked(pll_locked),
        .user_clock(user_clock),
        .user_write_enable(user_write_enable),
        .user_write_address(user_write_address),
        .user_write_data(user_write_data),
        .user_read_address(user_read_address),
        .user_read_data(user_read_data),
        .command_valid(command_valid),
        .command_ready(command_ready),
        .command_write(command_write),
        .command_buffer(command_buffer),
        .command_burst(command_burst),
        .done_valid(done_valid),
        .done_ready(done_ready),
        .done_write(done_write),
        .done_buffer(done_buffer),
        .done_short(done_short),
        .init_done(init_done),
        .id0(id0),
        .id1(id1),
        .hr_ck(hr_ck),
        .hr_cs_n(hr_cs_n),
        .hr_reset_n(hr_reset_n),
        .hr_rwds(hr_rwds),
        .hr_dq(hr_dq)
    );

    reg         start = 1'b0;
    reg         do_write = 1'b0;
    reg         do_read = 1'b0;
    reg  [1:0]  pattern = 2'd0;
    reg  [31:0] seed = 32'd0;
    reg  [BURST_BITS-1:0] start_burst = 0;
    reg  [BURST_BITS:0]   burst_count = 0;
    wire        busy;
    wire [31:0] words_tested;
    wire [31:0] error_count;
    wire [31:0] missing_count;
    wire [21:0] first_error_address;
    wire [15:0] first_error_expected;
    wire [15:0] first_error_actual;
    wire [15:0] error_bits;
    wire [31:0] write_cycles;
    wire [31:0] read_cycles;

    hyperram_tester #(
        .BURST_WORDS(BURST_WORDS),
        .BUFFER_BITS(BUFFER_BITS),
        .USER_WIDTH(USER_WIDTH)
    ) tester (
        .clock(user_clock),
        .reset(!init_done),
        .start(start),
        .do_write(do_write),
        .do_read(do_read),
        .pattern(pattern),
        .seed(seed),
        .start_burst(start_burst),
        .burst_count(burst_count),
        .busy(busy),
        .words_tested(words_tested),
        .error_count(error_count),
        .missing_count(missing_count),
        .first_error_address(first_error_address),
        .first_error_expected(first_error_expected),
        .first_error_actual(first_error_actual),
        .error_bits(error_bits),
        .write_cycles(write_cycles),
        .read_cycles(read_cycles),
        .user_write_enable(user_write_enable),
        .user_write_address(user_write_address),
        .user_write_data(user_write_data),
        .user_read_address(user_read_address),
        .user_read_data(user_read_data),
        .command_valid(command_valid),
        .command_ready(command_ready),
        .command_write(command_write),
        .command_buffer(command_buffer),
        .command_burst(command_burst),
        .done_valid(done_valid),
        .done_ready(done_ready),
        .done_write(done_write),
        .done_buffer(done_buffer),
        .done_short(done_short)
    );

    hyperram_model memory (
        .ck(hr_ck),
        .cs_n(hr_cs_n),
        .reset_n(hr_reset_n),
        .dq(hr_dq),
        .rwds(hr_rwds)
    );

    // CS# high time between write bursts, in clk_hr cycles. The first burst
    // of a pass waits for its buffer to fill, so it is not counted.
    integer cs_high = 0;
    integer max_gap = 0;
    integer bursts_seen = 0;
    wire writing = tester.state == 2'd1;
    always @(posedge clk_hr) begin
        if (hr_cs_n) begin
            cs_high <= cs_high + 1;
        end else begin
            if (cs_high != 0 && writing && bursts_seen != 0 && cs_high > max_gap)
                max_gap <= cs_high;
            if (cs_high != 0 && writing)
                bursts_seen <= bursts_seen + 1;
            cs_high <= 0;
        end
    end

    integer failures = 0;

    task automatic run(input bit write_pass, input bit read_pass,
                       input [1:0] kind, input [31:0] seed_value,
                       input integer first, input integer count);
        integer timeout;
        begin
            @(posedge user_clock);
            do_write = write_pass;
            do_read = read_pass;
            pattern = kind;
            seed = seed_value;
            start_burst = first[BURST_BITS-1:0];
            burst_count = count[BURST_BITS:0];
            start = 1'b1;
            @(posedge user_clock);
            start = 1'b0;
            @(posedge user_clock);
            timeout = 0;
            while (busy && timeout < 1000000) begin
                @(posedge user_clock);
                timeout = timeout + 1;
            end
            if (busy) begin
                $display("FAIL: test timed out");
                $finish;
            end
        end
    endtask

    task automatic expect_clean(input string name, input integer count);
        begin
            if (words_tested != count * BURST_WORDS || error_count != 0 ||
                missing_count != 0) begin
                $display("FAIL: %s: words %0d errors %0d missing %0d first @%06x exp %04x got %04x bits %04x",
                         name, words_tested, error_count, missing_count,
                         first_error_address, first_error_expected,
                         first_error_actual, error_bits);
                failures = failures + 1;
            end
        end
    endtask

    integer gap_limit;
    integer first_gap = 0;
    initial begin
        #200;
        pll_locked = 1'b1;
        wait (init_done);
        if (id0 !== 16'h0c83 || id1 !== 16'h0001) begin
            $display("FAIL: ID registers %04x %04x", id0, id1);
            failures = failures + 1;
        end

        // Six bursts through four buffers wraps the buffer ring.
        max_gap = 0;
        bursts_seen = 0;
        run(1, 1, 2'd0, 32'h1234_5678, 5, 6);
        expect_clean("prbs", 6);
        // Back to back: CS# stays high only for recovery and command setup,
        // provided the 37 MHz producer can outpace the HyperRAM.
        gap_limit = 12;
        if (USER_WIDTH / 16 * 37 > mhz && max_gap > gap_limit) begin
            $display("FAIL: %0d-cycle gap between bursts", max_gap);
            failures = failures + 1;
        end
        first_gap = max_gap;
        run(1, 1, 2'd1, 32'h0000_a5a5, (1 << BURST_BITS) - 3, 3);
        expect_clean("address", 3);
        run(1, 1, 2'd2, 32'd0, 0, 2);
        expect_clean("walking", 2);
        run(1, 1, 2'd3, 32'h0000_00ff, 17, 5);
        expect_clean("toggle", 5);

        // A single flipped bit must be reported exactly.
        memory.inject_address = 17 * BURST_WORDS + 9;
        run(0, 1, 2'd3, 32'h0000_00ff, 17, 5);
        memory.inject_address = -1;
        if (error_count != 1 || missing_count != 0 ||
            first_error_address != 22'(17 * BURST_WORDS + 9) ||
            error_bits != 16'h0020) begin
            $display("FAIL: injected error: errors %0d missing %0d @%06x bits %04x",
                     error_count, missing_count, first_error_address,
                     error_bits);
            failures = failures + 1;
        end

        // A burst that stops strobing early is reported as missing words.
        // (Its buffer still holds the same data from the previous read, so
        // the stale words happen to compare equal.)
        memory.short_after = 10;
        run(0, 1, 2'd3, 32'h0000_00ff, 17, 5);
        if (missing_count != BURST_WORDS - 10) begin
            $display("FAIL: short read: errors %0d missing %0d",
                     error_count, missing_count);
            failures = failures + 1;
        end
        memory.short_after = -1;

        if (memory.errors != 0)
            failures = failures + memory.errors;

        if (failures == 0)
            $display("PASS: hyperram width=%0d burst=%0d mhz=%0d phase=%0d tckd=%0.2f gap=%0d",
                     USER_WIDTH, BURST_WORDS, mhz, phase_degrees,
                     memory.tckd, first_gap);
        else
            $display("FAIL: %0d failures (width=%0d burst=%0d mhz=%0d phase=%0d tckd=%0.2f)",
                     failures, USER_WIDTH, BURST_WORDS, mhz, phase_degrees,
                     memory.tckd);
        $finish;
    end
endmodule
