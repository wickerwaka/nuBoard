`timescale 1ns/1ps

// HyperRAM throughput test harness, written as a trace producer would use
// hyperram_trace_core. It runs in the user clock domain and moves one user
// word (USER_WIDTH / 16 HyperRAM words) per clock.
//
//   write pass  fill each free buffer with pattern data and queue it; a
//               buffer is free again when its write completes.
//   read pass   queue reads into free buffers; as each completes, check it
//               against the pattern and free it.
//
// Both passes keep every buffer busy, so the HyperRAM controller is the
// bottleneck and write_cycles / read_cycles measure its throughput.
module hyperram_tester #(
    parameter integer BURST_WORDS = 256,
    parameter integer BUFFER_BITS = 2,
    parameter integer USER_WIDTH = 64
) (
    input  wire        clock,
    input  wire        reset,

    input  wire        start,
    input  wire        do_write,
    input  wire        do_read,
    input  wire [1:0]  pattern,
    input  wire [31:0] seed,
    input  wire [21-$clog2(BURST_WORDS):0] start_burst,
    input  wire [22-$clog2(BURST_WORDS):0] burst_count,

    output reg         busy = 1'b0,
    output reg  [31:0] words_tested = 32'd0,
    output reg  [31:0] error_count = 32'd0,
    output reg  [31:0] missing_count = 32'd0,
    output reg  [21:0] first_error_address = 22'd0,
    output reg  [15:0] first_error_expected = 16'd0,
    output reg  [15:0] first_error_actual = 16'd0,
    output reg  [15:0] error_bits = 16'd0,
    output reg  [31:0] write_cycles = 32'd0,
    output reg  [31:0] read_cycles = 32'd0,

    output reg                      user_write_enable = 1'b0,
    output reg  [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_write_address = 0,
    output reg  [USER_WIDTH-1:0]    user_write_data = 0,
    output reg  [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_read_address = 0,
    input  wire [USER_WIDTH-1:0]    user_read_data,

    output reg                              command_valid = 1'b0,
    input  wire                             command_ready,
    output reg                              command_write = 1'b0,
    output reg  [BUFFER_BITS-1:0]           command_buffer = 0,
    output reg  [21-$clog2(BURST_WORDS):0]  command_burst = 0,

    input  wire                             done_valid,
    output wire                             done_ready,
    input  wire                             done_write,
    input  wire [BUFFER_BITS-1:0]           done_buffer,
    input  wire [$clog2(BURST_WORDS):0]     done_short
);
    localparam integer LANES = USER_WIDTH / 16;
    localparam integer WORD_BITS = $clog2(BURST_WORDS);
    localparam integer BURST_BITS = 22 - WORD_BITS;
    localparam integer USER_BITS = $clog2(BURST_WORDS / LANES);
    localparam integer BUFFERS = 1 << BUFFER_BITS;
    localparam [USER_BITS-1:0] LAST_USER_WORD = {USER_BITS{1'b1}};

    localparam [1:0] PATTERN_PRBS    = 2'd0;
    localparam [1:0] PATTERN_ADDRESS = 2'd1;
    localparam [1:0] PATTERN_WALKING = 2'd2;

    localparam [1:0] STATE_IDLE  = 2'd0;
    localparam [1:0] STATE_WRITE = 2'd1;
    localparam [1:0] STATE_READ  = 2'd2;

    // 32-bit Galois LFSR, advanced 16 steps per HyperRAM word so that
    // consecutive words are not simple shifts of one another.
    function [31:0] lfsr_advance;
        input [31:0] value;
        integer step;
        reg [31:0] next;
        begin
            next = value;
            for (step = 0; step < 16; step = step + 1)
                next = next[0] ? (next >> 1) ^ 32'h80200003 : next >> 1;
            lfsr_advance = next;
        end
    endfunction

    function [15:0] pattern_word;
        input [1:0]  kind;
        input [31:0] lfsr_value;
        input [21:0] address;
        input [31:0] seed_value;
        begin
            case (kind)
                PATTERN_PRBS:    pattern_word = lfsr_value[15:0];
                PATTERN_ADDRESS: pattern_word = address[15:0] ^
                                     {address[21:16], 10'd0} ^ seed_value[15:0];
                PATTERN_WALKING: pattern_word = (16'd1 << address[3:0]) ^
                                     {16{address[4]}};
                default:         pattern_word = seed_value[15:0] ^
                                     {16{address[0]}};
            endcase
        end
    endfunction

    reg [1:0]  state = STATE_IDLE;
    reg        read_after = 1'b0;
    reg [1:0]  kind = PATTERN_PRBS;
    reg [31:0] seed_value = 32'd0;
    reg [31:0] seed_lfsr = 32'd1;
    reg [BURST_BITS-1:0] first_burst = 0;
    reg [BURST_BITS:0]   total_bursts = 0;

    // Pattern generator: one user word of LANES HyperRAM words per step.
    reg [31:0] lfsr = 32'd1;
    reg [21:0] word_address = 22'd0;
    reg [31:0] lane_lfsr [0:LANES];
    reg [USER_WIDTH-1:0] pattern_data;
    integer g;
    always @(*) begin
        lane_lfsr[0] = lfsr;
        for (g = 0; g < LANES; g = g + 1) begin
            pattern_data[16 * g +: 16] = pattern_word(
                kind, lane_lfsr[g], word_address + g[21:0], seed_value);
            lane_lfsr[g + 1] = lfsr_advance(lane_lfsr[g]);
        end
    end
    wire [31:0] lfsr_next = lane_lfsr[LANES];

    // Buffer bookkeeping. Commands complete in order, so the fill, issue
    // and check positions each walk the buffers round-robin.
    reg [BUFFERS-1:0]     free = {BUFFERS{1'b1}};
    reg [BUFFER_BITS-1:0] fill_buffer = 0;     // write: next to fill
    reg [USER_BITS-1:0]   fill_index = 0;
    reg                   filled = 1'b0;       // waiting to queue it
    reg [BURST_BITS:0]    bursts_queued = 0;
    reg [BURST_BITS:0]    bursts_done = 0;
    reg [BURST_BITS-1:0]  next_burst = 0;
    reg [BUFFER_BITS-1:0] check_buffer = 0;    // read: next to check
    reg [USER_BITS-1:0]   check_index = 0;
    reg                   checking = 1'b0;
    reg [BUFFER_BITS:0]   reads_ready = 0;     // completed, not checked

    // Read check pipeline. The address register updates on one edge and the
    // buffer RAM registers its data on the next, so the expected data is
    // delayed two clocks to match.
    reg                  issue_valid = 1'b0;
    reg [USER_WIDTH-1:0] issue_expected = 0;
    reg [21:0]           issue_address = 22'd0;
    reg                  compare_valid = 1'b0;
    reg [USER_WIDTH-1:0] compare_expected = 0;
    reg [21:0]           compare_address = 22'd0;
    reg                  have_error = 1'b0;

    assign done_ready = done_valid;

    integer lane;
    reg [BUFFERS-1:0] set_free;
    reg [BUFFERS-1:0] clear_free;
    reg [4:0]         lane_errors;
    reg               found;
    reg [15:0]        difference;
    reg [15:0]        bits;

    always @(posedge clock) begin
        set_free = 0;
        clear_free = 0;
        user_write_enable <= 1'b0;
        issue_valid <= 1'b0;
        compare_valid <= issue_valid;
        compare_expected <= issue_expected;
        compare_address <= issue_address;

        if (state == STATE_WRITE)
            write_cycles <= write_cycles + 1'b1;
        if (state == STATE_READ)
            read_cycles <= read_cycles + 1'b1;

        // Completions: writes free their buffer; reads wait to be checked.
        if (done_valid) begin
            bursts_done <= bursts_done + 1'b1;
            if (done_write) begin
                set_free[done_buffer] = 1'b1;
            end else begin
                missing_count <= missing_count + {{(31-WORD_BITS){1'b0}}, done_short};
                reads_ready <= reads_ready + 1'b1;
            end
        end

        if (command_valid && command_ready) begin
            command_valid <= 1'b0;
            clear_free[command_buffer] = 1'b1;
            bursts_queued <= bursts_queued + 1'b1;
            next_burst <= next_burst + 1'b1;
            if (command_write) begin
                fill_buffer <= fill_buffer + 1'b1;
                filled <= 1'b0;
            end
        end

        // Compare stage.
        if (compare_valid) begin
            lane_errors = 5'd0;
            found = have_error;
            bits = error_bits;
            for (lane = 0; lane < LANES; lane = lane + 1) begin
                difference = user_read_data[16 * lane +: 16] ^
                             compare_expected[16 * lane +: 16];
                if (difference != 16'd0) begin
                    lane_errors = lane_errors + 1'b1;
                    if (!found) begin
                        found = 1'b1;
                        first_error_address <= compare_address + lane[21:0];
                        first_error_expected <= compare_expected[16 * lane +: 16];
                        first_error_actual <= user_read_data[16 * lane +: 16];
                    end
                end
                bits = bits | difference;
            end
            error_bits <= bits;
            have_error <= found;
            error_count <= error_count + {27'd0, lane_errors};
            words_tested <= words_tested + LANES;
        end

        if (reset) begin
            state <= STATE_IDLE;
            busy <= 1'b0;
            command_valid <= 1'b0;
        end else begin
            case (state)
                STATE_IDLE: begin
                    if (start && (do_write || do_read)) begin
                        busy <= 1'b1;
                        kind <= pattern;
                        seed_value <= seed;
                        seed_lfsr <= seed == 32'd0 ? 32'h1 : seed;
                        lfsr <= seed == 32'd0 ? 32'h1 : seed;
                        first_burst <= start_burst;
                        next_burst <= start_burst;
                        total_bursts <= burst_count;
                        word_address <= {start_burst, {WORD_BITS{1'b0}}};
                        read_after <= do_write && do_read;
                        set_free = {BUFFERS{1'b1}};
                        fill_buffer <= 0;
                        fill_index <= 0;
                        filled <= 1'b0;
                        check_buffer <= 0;
                        check_index <= 0;
                        checking <= 1'b0;
                        reads_ready <= 0;
                        bursts_queued <= 0;
                        bursts_done <= 0;
                        write_cycles <= 32'd0;
                        read_cycles <= 32'd0;
                        words_tested <= 32'd0;
                        error_count <= 32'd0;
                        missing_count <= 32'd0;
                        error_bits <= 16'd0;
                        have_error <= 1'b0;
                        first_error_address <= 22'd0;
                        first_error_expected <= 16'd0;
                        first_error_actual <= 16'd0;
                        state <= do_write ? STATE_WRITE : STATE_READ;
                    end
                end
                STATE_WRITE: begin
                    if (!filled && bursts_queued != total_bursts &&
                        free[fill_buffer]) begin
                        user_write_enable <= 1'b1;
                        user_write_address <= {fill_buffer, fill_index};
                        user_write_data <= pattern_data;
                        lfsr <= lfsr_next;
                        word_address <= word_address + LANES[21:0];
                        fill_index <= fill_index + 1'b1;
                        if (fill_index == LAST_USER_WORD) begin
                            filled <= 1'b1;
                            command_valid <= 1'b1;
                            command_write <= 1'b1;
                            command_buffer <= fill_buffer;
                            command_burst <= next_burst;
                        end
                    end
                    if (bursts_done == total_bursts &&
                        bursts_queued == total_bursts) begin
                        if (read_after) begin
                            lfsr <= seed_lfsr;
                            word_address <= {first_burst, {WORD_BITS{1'b0}}};
                            next_burst <= first_burst;
                            bursts_queued <= 0;
                            bursts_done <= 0;
                            fill_buffer <= 0;
                            check_buffer <= 0;
                            state <= STATE_READ;
                        end else begin
                            busy <= 1'b0;
                            state <= STATE_IDLE;
                        end
                    end
                end
                STATE_READ: begin
                    // Queue reads into free buffers, in buffer order.
                    if (!command_valid && bursts_queued != total_bursts &&
                        free[fill_buffer]) begin
                        command_valid <= 1'b1;
                        command_write <= 1'b0;
                        command_buffer <= fill_buffer;
                        command_burst <= next_burst;
                        fill_buffer <= fill_buffer + 1'b1;
                    end
                    // Check completed buffers in the same order.
                    if (!checking && reads_ready != 0) begin
                        checking <= 1'b1;
                        check_index <= 0;
                    end
                    if (checking) begin
                        user_read_address <= {check_buffer, check_index};
                        issue_valid <= 1'b1;
                        issue_expected <= pattern_data;
                        issue_address <= word_address;
                        lfsr <= lfsr_next;
                        word_address <= word_address + LANES[21:0];
                        check_index <= check_index + 1'b1;
                        if (check_index == LAST_USER_WORD) begin
                            checking <= 1'b0;
                            set_free[check_buffer] = 1'b1;
                            check_buffer <= check_buffer + 1'b1;
                            if (!(done_valid && !done_write))
                                reads_ready <= reads_ready - 1'b1;
                            else
                                reads_ready <= reads_ready;
                        end
                    end
                    if (bursts_done == total_bursts && reads_ready == 0 &&
                        !checking && !issue_valid && !compare_valid &&
                        bursts_queued == total_bursts) begin
                        busy <= 1'b0;
                        state <= STATE_IDLE;
                    end
                end
                default: state <= STATE_IDLE;
            endcase
        end

        free <= (free | set_free) & ~clear_free;
    end
endmodule
