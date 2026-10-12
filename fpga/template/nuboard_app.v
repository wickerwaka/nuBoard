`timescale 1ns/1ps

// Template application. Each mailbox packet arrives as a byte stream starting
// with its 16-byte header (ABI, channel, flags[2], tag[4], length[4],
// crc32c[4]) and the reply must be a complete packet in the same format.
//
//   channel 1   HyperRAM test commands, answered with a result packet.
//   otherwise   echoed back unchanged.
//
// The HyperRAM test harness (hyperram_tester) runs in this clock domain and
// drives the user side of hyperram_trace_core.
//
// HyperRAM command payload (little endian):
//   0     operation: 0 write then read back, 1 get last result,
//                    2 read ID registers, 3 write only, 4 read back only
//   1     pattern:   0 PRBS, 1 address, 2 walking ones, 3 toggle
//   4-7   seed
//   8-11  first burst
//   12-15 burst count
//
// The reply payload is RESULT_BYTES long; see result_byte() for the layout.
module nuboard_app #(
    parameter integer HR_MHZ = 100,
    parameter integer HR_CAL_PHASE = 90,
    parameter integer BURST_WORDS = 256,
    parameter integer BUFFER_BITS = 2,
    parameter integer USER_WIDTH = 64
) (
    input  wire        clock,

    input  wire        input_valid,
    output wire        input_ready,
    input  wire [7:0]  input_data,
    input  wire        input_last,

    output wire        output_valid,
    input  wire        output_ready,
    output wire [7:0]  output_data,
    output wire        output_last,

    // User side of hyperram_trace_core, in this clock domain.
    output wire                     user_write_enable,
    output wire [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_write_address,
    output wire [USER_WIDTH-1:0]    user_write_data,
    output wire [BUFFER_BITS+$clog2(BURST_WORDS*16/USER_WIDTH)-1:0]
                                    user_read_address,
    input  wire [USER_WIDTH-1:0]    user_read_data,
    output wire                             command_valid,
    input  wire                             command_ready,
    output wire                             command_write,
    output wire [BUFFER_BITS-1:0]           command_buffer,
    output wire [21-$clog2(BURST_WORDS):0]  command_burst,
    input  wire                             done_valid,
    output wire                             done_ready,
    input  wire                             done_write,
    input  wire [BUFFER_BITS-1:0]           done_buffer,
    input  wire [$clog2(BURST_WORDS):0]     done_short,

    // HyperRAM status (clk_hr domain; id0 and id1 are stable once
    // init_done is set).
    input  wire        pll_locked,
    input  wire        init_done,
    input  wire [15:0] id0,
    input  wire [15:0] id1
);
    localparam integer WORD_BITS = $clog2(BURST_WORDS);
    localparam integer BURST_BITS = 22 - WORD_BITS;
    localparam [7:0] HYPERRAM_CHANNEL = 8'd1;
    localparam [6:0] RESULT_BYTES = 7'd56;
    localparam [BURST_BITS:0] TOTAL_BURSTS = 1 << BURST_BITS;

    localparam [7:0] OP_TEST       = 8'd0;
    localparam [7:0] OP_GET_RESULT = 8'd1;
    localparam [7:0] OP_READ_ID    = 8'd2;
    localparam [7:0] OP_WRITE      = 8'd3;
    localparam [7:0] OP_READ       = 8'd4;

    localparam [7:0] STATUS_OK        = 8'd0;
    localparam [7:0] STATUS_NOT_READY = 8'd1;
    localparam [7:0] STATUS_BAD_OP    = 8'd2;
    localparam [7:0] STATUS_TIMEOUT   = 8'd3;
    localparam [7:0] STATUS_RANGE     = 8'd4;

    localparam [2:0] STATE_HEADER    = 3'd0;
    localparam [2:0] STATE_ECHO_HEAD = 3'd1;
    localparam [2:0] STATE_ECHO_BODY = 3'd2;
    localparam [2:0] STATE_COMMAND   = 3'd3;
    localparam [2:0] STATE_EXECUTE   = 3'd4;
    localparam [2:0] STATE_WAIT      = 3'd5;
    localparam [2:0] STATE_CRC       = 3'd6;
    localparam [2:0] STATE_SEND      = 3'd7;

    function [31:0] crc32c_byte;
        input [31:0] crc;
        input [7:0] data;
        integer bit_index;
        reg [31:0] next;
        begin
            next = crc ^ {24'd0, data};
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                if (next[0])
                    next = (next >> 1) ^ 32'h82f63b78;
                else
                    next = next >> 1;
            end
            crc32c_byte = next;
        end
    endfunction

    reg [2:0]  state = STATE_HEADER;
    reg [7:0]  header [0:15];
    reg [7:0]  payload [0:15];
    reg [6:0]  index = 7'd0;
    reg        header_only = 1'b0;

    (* async_reg = "true" *) reg locked_sync_1 = 1'b0;
    (* async_reg = "true" *) reg locked_sync_2 = 1'b0;
    (* async_reg = "true" *) reg init_sync_1 = 1'b0;
    (* async_reg = "true" *) reg init_sync_2 = 1'b0;
    always @(posedge clock) begin
        locked_sync_1 <= pll_locked;
        locked_sync_2 <= locked_sync_1;
        init_sync_1 <= init_done;
        init_sync_2 <= init_sync_1;
    end

    // Test harness.
    reg         test_start = 1'b0;
    reg         test_write = 1'b0;
    reg         test_read = 1'b0;
    reg  [1:0]  test_pattern = 2'd0;
    reg  [31:0] test_seed = 32'd0;
    reg  [BURST_BITS-1:0] test_first = 0;
    reg  [BURST_BITS:0]   test_count = 0;
    wire        test_busy;
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
        .clock(clock),
        .reset(!init_sync_2),
        .start(test_start),
        .do_write(test_write),
        .do_read(test_read),
        .pattern(test_pattern),
        .seed(test_seed),
        .start_burst(test_first),
        .burst_count(test_count),
        .busy(test_busy),
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

    wire core_ready = locked_sync_2 && init_sync_2 && !test_busy;
    reg [28:0] wait_count = 29'd0;

    // Snapshot of the result, taken before the reply is built so the CRC and
    // the transmitted bytes always agree.
    reg [7:0]  result_status = 8'd0;
    reg [7:0]  result_operation = 8'd0;
    reg [7:0]  result_flags = 8'd0;
    reg [31:0] result_words = 32'd0;
    reg [31:0] result_errors = 32'd0;
    reg [31:0] result_missing = 32'd0;
    reg [31:0] result_first_address = 32'd0;
    reg [15:0] result_expected = 16'd0;
    reg [15:0] result_actual = 16'd0;
    reg [15:0] result_error_bits = 16'd0;
    reg [15:0] result_id0 = 16'd0;
    reg [15:0] result_id1 = 16'd0;
    reg [31:0] result_write_cycles = 32'd0;
    reg [31:0] result_read_cycles = 32'd0;

    localparam integer BUFFER_COUNT = 1 << BUFFER_BITS;
    localparam [15:0] MHZ_FIELD = HR_MHZ[15:0];
    localparam [15:0] PHASE_FIELD = HR_CAL_PHASE[15:0];
    localparam [15:0] BURST_FIELD = BURST_WORDS[15:0];
    localparam [15:0] WIDTH_FIELD = USER_WIDTH[15:0];
    localparam [15:0] BUFFERS_FIELD = BUFFER_COUNT[15:0];
    wire [31:0] count_field = {{(31-BURST_BITS){1'b0}}, test_count};

    function [7:0] result_byte;
        input [5:0] i;
        begin
            case (i)
                0:  result_byte = result_status;
                1:  result_byte = result_operation;
                2:  result_byte = {6'd0, test_pattern};
                3:  result_byte = result_flags;      // locked, init, busy
                4:  result_byte = MHZ_FIELD[7:0];
                5:  result_byte = MHZ_FIELD[15:8];
                6:  result_byte = PHASE_FIELD[7:0];
                7:  result_byte = PHASE_FIELD[15:8];
                8:  result_byte = BURST_FIELD[7:0];
                9:  result_byte = BURST_FIELD[15:8];
                10: result_byte = WIDTH_FIELD[7:0];
                11: result_byte = WIDTH_FIELD[15:8];
                12: result_byte = result_words[7:0];
                13: result_byte = result_words[15:8];
                14: result_byte = result_words[23:16];
                15: result_byte = result_words[31:24];
                16: result_byte = result_errors[7:0];
                17: result_byte = result_errors[15:8];
                18: result_byte = result_errors[23:16];
                19: result_byte = result_errors[31:24];
                20: result_byte = result_missing[7:0];
                21: result_byte = result_missing[15:8];
                22: result_byte = result_missing[23:16];
                23: result_byte = result_missing[31:24];
                24: result_byte = result_first_address[7:0];
                25: result_byte = result_first_address[15:8];
                26: result_byte = result_first_address[23:16];
                27: result_byte = result_first_address[31:24];
                28: result_byte = result_expected[7:0];
                29: result_byte = result_expected[15:8];
                30: result_byte = result_actual[7:0];
                31: result_byte = result_actual[15:8];
                32: result_byte = result_error_bits[7:0];
                33: result_byte = result_error_bits[15:8];
                34: result_byte = result_id0[7:0];
                35: result_byte = result_id0[15:8];
                36: result_byte = result_id1[7:0];
                37: result_byte = result_id1[15:8];
                38: result_byte = BUFFERS_FIELD[7:0];
                39: result_byte = BUFFERS_FIELD[15:8];
                40: result_byte = result_write_cycles[7:0];
                41: result_byte = result_write_cycles[15:8];
                42: result_byte = result_write_cycles[23:16];
                43: result_byte = result_write_cycles[31:24];
                44: result_byte = result_read_cycles[7:0];
                45: result_byte = result_read_cycles[15:8];
                46: result_byte = result_read_cycles[23:16];
                47: result_byte = result_read_cycles[31:24];
                48: result_byte = test_seed[7:0];
                49: result_byte = test_seed[15:8];
                50: result_byte = test_seed[23:16];
                51: result_byte = test_seed[31:24];
                52: result_byte = count_field[7:0];
                53: result_byte = count_field[15:8];
                54: result_byte = count_field[23:16];
                55: result_byte = count_field[31:24];
                default: result_byte = 8'd0;
            endcase
        end
    endfunction

    reg [31:0] reply_crc = 32'hffffffff;
    wire [31:0] reply_crc_out = ~reply_crc;
    reg [7:0] send_byte;
    always @(*) begin
        case (index)
            0, 1, 2, 3, 4, 5, 6, 7: send_byte = header[index[3:0]];
            8:  send_byte = {1'b0, RESULT_BYTES};
            9:  send_byte = 8'd0;
            10: send_byte = 8'd0;
            11: send_byte = 8'd0;
            12: send_byte = reply_crc_out[7:0];
            13: send_byte = reply_crc_out[15:8];
            14: send_byte = reply_crc_out[23:16];
            15: send_byte = reply_crc_out[31:24];
            default: send_byte = result_byte(index[5:0] - 6'd16);
        endcase
    end

    assign input_ready =
        state == STATE_HEADER || state == STATE_COMMAND ||
        (state == STATE_ECHO_BODY && output_ready);
    assign output_valid =
        state == STATE_ECHO_HEAD || state == STATE_SEND ||
        (state == STATE_ECHO_BODY && input_valid);
    assign output_data =
        state == STATE_ECHO_HEAD ? header[index[3:0]] :
        state == STATE_SEND      ? send_byte :
                                   input_data;
    assign output_last =
        state == STATE_ECHO_HEAD ? header_only && index == 7'd15 :
        state == STATE_SEND      ? index == 7'd15 + RESULT_BYTES :
                                   input_last;

    wire [7:0] operation = payload[0];
    wire [31:0] request_first =
        {payload[11], payload[10], payload[9], payload[8]};
    wire [31:0] request_count =
        {payload[15], payload[14], payload[13], payload[12]};
    wire [32:0] request_end = {1'b0, request_first} + {1'b0, request_count};
    wire [32:0] total_bursts = {{(32-BURST_BITS){1'b0}}, TOTAL_BURSTS};

    always @(posedge clock) begin
        test_start <= 1'b0;
        case (state)
            STATE_HEADER: begin
                if (input_valid) begin
                    header[index[3:0]] <= input_data;
                    index <= index + 1'b1;
                    if (index == 7'd15) begin
                        index <= 7'd0;
                        header_only <= input_last;
                        if (header[1] == HYPERRAM_CHANNEL) begin
                            payload[0] <= 8'hff;
                            state <= input_last ? STATE_EXECUTE
                                                : STATE_COMMAND;
                        end else begin
                            state <= STATE_ECHO_HEAD;
                        end
                    end
                end
            end
            STATE_ECHO_HEAD: begin
                if (output_ready) begin
                    index <= index + 1'b1;
                    if (index == 7'd15) begin
                        index <= 7'd0;
                        state <= header_only ? STATE_HEADER
                                             : STATE_ECHO_BODY;
                    end
                end
            end
            STATE_ECHO_BODY: begin
                if (input_valid && output_ready && input_last)
                    state <= STATE_HEADER;
            end
            STATE_COMMAND: begin
                if (input_valid) begin
                    if (index < 7'd16)
                        payload[index[3:0]] <= input_data;
                    if (index != 7'd127)
                        index <= index + 1'b1;
                    if (input_last)
                        state <= STATE_EXECUTE;
                end
            end
            STATE_EXECUTE: begin
                index <= 7'd0;
                wait_count <= 29'd0;
                result_status <= STATUS_OK;
                result_operation <= operation;
                if (operation == OP_GET_RESULT) begin
                    state <= STATE_CRC;
                end else if (operation != OP_TEST && operation != OP_READ_ID &&
                             operation != OP_WRITE && operation != OP_READ) begin
                    result_status <= STATUS_BAD_OP;
                    state <= STATE_CRC;
                end else if (!core_ready) begin
                    result_status <= STATUS_NOT_READY;
                    state <= STATE_CRC;
                end else if (operation == OP_READ_ID) begin
                    state <= STATE_CRC;
                end else if (request_end > total_bursts ||
                             request_count == 32'd0) begin
                    result_status <= STATUS_RANGE;
                    state <= STATE_CRC;
                end else begin
                    test_start <= 1'b1;
                    test_write <= operation == OP_TEST || operation == OP_WRITE;
                    test_read <= operation == OP_TEST || operation == OP_READ;
                    test_pattern <= payload[1][1:0];
                    test_seed <= {payload[7], payload[6], payload[5], payload[4]};
                    test_first <= request_first[BURST_BITS-1:0];
                    test_count <= request_count[BURST_BITS:0];
                    state <= STATE_WAIT;
                end
            end
            STATE_WAIT: begin
                // test_busy rises the clock after test_start.
                wait_count <= wait_count + 1'b1;
                if (wait_count > 29'd2 && !test_busy) begin
                    state <= STATE_CRC;
                end else if (&wait_count) begin
                    result_status <= STATUS_TIMEOUT;
                    state <= STATE_CRC;
                end
            end
            STATE_CRC: begin
                if (index == 7'd0) begin
                    // Snapshot the harness outputs; they are stable here.
                    reply_crc <= 32'hffffffff;
                    result_flags <= {5'd0, test_busy, init_sync_2, locked_sync_2};
                    result_words <= words_tested;
                    result_errors <= error_count;
                    result_missing <= missing_count;
                    result_first_address <= {10'd0, first_error_address};
                    result_expected <= first_error_expected;
                    result_actual <= first_error_actual;
                    result_error_bits <= error_bits;
                    result_id0 <= init_sync_2 ? id0 : 16'd0;
                    result_id1 <= init_sync_2 ? id1 : 16'd0;
                    result_write_cycles <= write_cycles;
                    result_read_cycles <= read_cycles;
                    index <= 7'd1;
                end else begin
                    reply_crc <= crc32c_byte(reply_crc, result_byte(index[5:0] - 6'd1));
                    if (index == RESULT_BYTES) begin
                        index <= 7'd0;
                        state <= STATE_SEND;
                    end else begin
                        index <= index + 1'b1;
                    end
                end
            end
            STATE_SEND: begin
                if (output_ready) begin
                    if (output_last) begin
                        index <= 7'd0;
                        state <= STATE_HEADER;
                    end else begin
                        index <= index + 1'b1;
                    end
                end
            end
            default: state <= STATE_HEADER;
        endcase
    end
endmodule
