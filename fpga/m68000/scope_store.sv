`timescale 1ns/1ps

// PSRAM-side FIFO drain, burst cache, and explicit idle-only memory test.
// Host command buses remain stable from request_toggle through acknowledgement.
module scope_store (
    input wire clock,
    input wire locked,
    input wire clear_toggle,
    input wire capture_stopped,
    input wire fifo_empty,
    output wire fifo_pop,
    input wire fifo_valid,
    input wire [63:0] fifo_data,
    input wire command_toggle,
    input wire command_test,
    input wire [20:0] command_address,
    output reg acknowledge,
    output reg [15:0] response,
    output reg response_error,
    output reg drained,
    output reg [31:0] committed,
    output reg test_failed,
    output reg [20:0] test_error_address,
    output wire initialized,
    output wire fault,
    output wire [63:0] identity,
    output wire psram_ce_n,
    output wire psram_sclk,
    output wire [3:0] dq_out,
    output wire [3:0] dq_enable,
    input wire [3:0] dq_in
);
    initial begin
        acknowledge = 0;
        response = 0;
        response_error = 0;
        drained = 1;
        committed = 0;
        test_failed = 0;
        test_error_address = 0;
    end
    localparam [3:0] FILL = 0, WAIT_FIFO = 1, LAUNCH_WRITE = 2,
                     WAIT_WRITE = 3, WAIT_READ = 4, READ_REPLY = 5,
                     TEST_FILL = 6, TEST_VERIFY = 7, TEST_SETTLE = 8,
                     TEST_COMPARE = 9, HOST_COMMAND = 10;
    reg [3:0] state = FILL;
    reg [4:0] buffered = 0;
    (* syn_ramstyle = "block_ram" *) reg [63:0] burst_words [0:15];
    (* syn_ramstyle = "block_ram" *) reg [7:0] cache_low [0:63];
    (* syn_ramstyle = "block_ram" *) reg [7:0] cache_high [0:63];
    reg [13:0] cache_page = 0;
    reg cache_valid = 1'b0;
    reg read_half = 1'b0;
    reg [15:0] fetched_word;
    reg testing = 1'b0;
    reg test_reading = 1'b0;
    reg [20:0] test_address = 0;
    (* syn_keep = "true" *) reg test_last_page = 0;
    reg [4:0] test_word = 0;
    reg [7:0] verify_byte = 0;
    reg clear_seen = 0;
    (* async_reg = "true" *) reg clear_meta = 0, clear_sync = 0;
    (* async_reg = "true" *) reg stopped_meta = 1, stopped_sync = 1;
    (* async_reg = "true" *) reg command_meta = 0, command_sync = 0;
    reg request = 1'b0;
    reg request_write = 1'b0;
    reg [20:0] request_address = 0;
    reg [7:0] request_length = 0;
    wire ready, done, read_valid;
    (* syn_keep = "true" *) reg command_ready = 0;
    wire [3:0] write_word_index;
    reg [63:0] write_word;
    wire [6:0] read_index;
    wire [7:0] read_byte;
    reg burst_write = 1'b0;
    reg [3:0] burst_address = 0;
    reg [63:0] burst_data = 0;
    wire [5:0] cache_address = testing ? verify_byte[6:1] : command_address[6:1];
    wire [7:0] checked_byte = verify_byte[0] ? fetched_word[15:8] : fetched_word[7:0];
    (* syn_keep = "true" *) reg compare_failed = 1'b0;

    // Address-dependent, nonperiodic across page/bank boundaries. The second
    // pass reads all 2 MiB after all writes, detecting address aliasing too.
    function automatic [7:0] pattern(input [20:0] address);
        pattern = address[7:0] ^ address[15:8] ^ {3'd0, address[20:16]} ^ 8'ha7;
    endfunction

    assign fifo_pop = state == FILL && !testing && !fifo_empty && buffered < 16;

    // Single write ports and synchronous reads keep both staging buffers in
    // block RAM. Registering the write command also removes the large fanout
    // from the state/clear logic to every data bit at 200 MHz.
    always @(posedge clock) begin
        // The address stays fixed throughout each burst and verify pass, so
        // predecode the terminal page before it reaches completion controls.
        test_last_page <= test_address == 21'h1fff80;
        if (burst_write)
            burst_words[burst_address] <= burst_data;
        write_word <= burst_words[write_word_index];
        if (read_valid && !read_index[0])
            cache_low[{read_half, read_index[5:1]}] <= read_byte;
        if (read_valid && read_index[0])
            cache_high[{read_half, read_index[5:1]}] <= read_byte;
        fetched_word <= {cache_high[cache_address], cache_low[cache_address]};
    end

    aps1604m_qpi memory (
        .clock(clock), .locked(locked),
        .request(request), .request_write(request_write),
        .request_address(request_address), .request_length(request_length),
        .ready(ready), .done(done), .initialized(initialized), .fault(fault),
        .identity(identity), .write_word_index(write_word_index),
        .write_word(write_word), .read_valid(read_valid),
        .read_index(read_index), .read_byte(read_byte),
        .ce_n(psram_ce_n), .sclk(psram_sclk),
        .dq_out(dq_out), .dq_enable(dq_enable), .dq_in(dq_in)
    );

    always @(posedge clock) begin
        // The memory FSM's ready decode must not cascade through this FSM
        // into every request-address enable. Launch states consume this
        // registered observation once, then wait for completion. The request
        // release below still uses the immediate ready/accept handshake.
        command_ready <= ready;
        clear_meta <= clear_toggle;
        clear_sync <= clear_meta;
        stopped_meta <= capture_stopped;
        stopped_sync <= stopped_meta;
        command_meta <= command_toggle;
        command_sync <= command_meta;
        if (request && !ready)
            request <= 1'b0;
        burst_write <= 1'b0;

        if (clear_sync != clear_seen) begin
            clear_seen <= clear_sync;
            committed <= 0;
            buffered <= 0;
            drained <= 1'b0;
            cache_valid <= 1'b0;
            state <= FILL;
        end else if (fault || !locked) begin
            // A command always receives a bounded error response, even if the
            // PSRAM cannot initialize. No stale cache may masquerade as a read.
            if (command_sync != acknowledge) begin
                acknowledge <= command_sync;
                response_error <= 1'b1;
            end
            cache_valid <= 1'b0;
        end else begin
            case (state)
                FILL: begin
                    if (buffered == 16 || (stopped_sync && fifo_empty && buffered != 0)) begin
                        state <= LAUNCH_WRITE;
                    end else if (fifo_pop) begin
                        state <= WAIT_FIFO;
                    end else if (stopped_sync && fifo_empty && buffered == 0) begin
                        drained <= 1'b1;
                        if (command_sync != acknowledge)
                            state <= HOST_COMMAND;
                    end
                end

                HOST_COMMAND: begin
                    // FIFO-idle detection and the memory-ready decode must
                    // not cascade into every host-command initialization CE.
                    // Ownership is held until acknowledgement, so this extra
                    // cycle changes only command latency, never CPU timing.
                    if (command_ready) begin
                        response_error <= 1'b0;
                        if (command_test) begin
                            testing <= 1'b1;
                            test_reading <= 1'b0;
                            test_failed <= 1'b0;
                            test_error_address <= 0;
                            test_address <= 0;
                            test_word <= 0;
                            committed <= 0;
                            cache_valid <= 1'b0;
                            state <= TEST_FILL;
                        end else if (cache_valid && cache_page == command_address[20:7]) begin
                            state <= READ_REPLY;
                        end else begin
                            request_address <= {command_address[20:7], 7'd0};
                            request_length <= 64;
                            read_half <= 1'b0;
                            request_write <= 1'b0;
                            request <= 1'b1;
                            cache_page <= command_address[20:7];
                            cache_valid <= 1'b0;
                            state <= WAIT_READ;
                        end
                    end
                end

                WAIT_FIFO: begin
                    if (fifo_valid) begin
                        burst_write <= 1'b1;
                        burst_address <= buffered[3:0];
                        burst_data <= fifo_data;
                        buffered <= buffered + 1'b1;
                        state <= FILL;
                    end
                end

                LAUNCH_WRITE: begin
                    if (command_ready) begin
                        request_address <= testing ? test_address : {committed[17:0], 3'd0};
                        request_length <= {buffered, 3'd0};
                        request_write <= 1'b1;
                        request <= 1'b1;
                        state <= WAIT_WRITE;
                    end
                end

                WAIT_WRITE: begin
                    if (done) begin
                        buffered <= 0;
                        if (!testing) begin
                            committed <= committed + buffered;
                            state <= FILL;
                        end else if (test_last_page) begin
                            test_reading <= 1'b1;
                            test_address <= 0;
                            state <= TEST_FILL;
                        end else begin
                            test_address <= test_address + 128;
                            test_word <= 0;
                            state <= TEST_FILL;
                        end
                    end
                end

                WAIT_READ: begin
                    if (done) begin
                        if (!read_half) begin
                            // Fill the 128-byte cache using two 64-byte read
                            // bursts, releasing CE for refresh between them.
                            read_half <= 1'b1;
                            request_address <= request_address + 64;
                            request <= 1'b1;
                        end else begin
                            cache_valid <= !testing;
                            verify_byte <= 0;
                            state <= testing ? TEST_SETTLE : READ_REPLY;
                        end
                    end
                end

                READ_REPLY: begin
                    response <= fetched_word;
                    acknowledge <= command_sync;
                    state <= FILL;
                end

                TEST_FILL: begin
                    if (test_reading) begin
                        if (command_ready) begin
                            request_address <= test_address;
                            request_length <= 64;
                            read_half <= 1'b0;
                            request_write <= 1'b0;
                            request <= 1'b1;
                            state <= WAIT_READ;
                        end
                    end else if (test_word == 16) begin
                        buffered <= 16;
                        state <= LAUNCH_WRITE;
                    end else begin
                        burst_write <= 1'b1;
                        burst_address <= test_word[3:0];
                        for (integer byte_index = 0; byte_index < 8; byte_index = byte_index+1)
                            burst_data[byte_index*8 +: 8] <=
                                pattern({test_address[20:7], test_word[3:0], byte_index[2:0]});
                        test_word <= test_word + 1'b1;
                    end
                end

                TEST_SETTLE: state <= TEST_COMPARE;

                TEST_COMPARE: begin
                    // Register the comparison before it fans out to the test
                    // control state, counters, and response handshake.
                    compare_failed <= checked_byte != pattern({test_address[20:7], verify_byte[6:0]});
                    state <= TEST_VERIFY;
                end

                TEST_VERIFY: begin
                    if (compare_failed) begin
                        test_failed <= 1'b1;
                        test_error_address <= test_address + verify_byte;
                        response_error <= 1'b1;
                        acknowledge <= command_sync;
                        testing <= 1'b0;
                        state <= FILL;
                    end else if (verify_byte == 127) begin
                        if (test_last_page) begin
                            response <= 16'h600d;
                            acknowledge <= command_sync;
                            testing <= 1'b0;
                            state <= FILL;
                        end else begin
                            test_address <= test_address + 128;
                            state <= TEST_FILL;
                        end
                    end else begin
                        verify_byte <= verify_byte + 1'b1;
                        state <= TEST_SETTLE;
                    end
                end
                default: state <= FILL;
            endcase
        end
    end
endmodule
