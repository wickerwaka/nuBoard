`timescale 1ns/1ps

// Socket levels are not meaningful until reset release has produced an idle
// bus. In particular, reset-time low strobes must not write the vector RAM.
module m68000_lane_tb;
    reg clock = 1'b0;
    always #10 clock = ~clock;

    reg clear = 1'b1;
    reg running = 1'b0;
    reg [31:0] timestamp = 32'd0;
    reg [255:0] page_map = 256'h8000;
    reg as_n = 1'b0;
    reg uds_n = 1'b0;
    reg lds_n = 1'b0;
    reg read_cycle = 1'b0;
    reg [2:0] function_code = 3'd0;
    reg host_write = 1'b0;
    wire [15:0] data_in;
    wire [15:0] host_read_data;
    wire dtack_n;
    wire berr_n;
    wire [11:0] trace_count;
    wire [31:0] total_count;

    m68000_lane lane (
        .clock(clock),
        .clear(clear),
        .running(running),
        .timestamp(timestamp),
        .wait_ticks(8'd8),
        .capture_start(32'd0),
        .page_map(page_map),
        .address(24'd0),
        .data_out(16'd0),
        .as_n(as_n),
        .uds_n(uds_n),
        .lds_n(lds_n),
        .read_cycle(read_cycle),
        .function_code(function_code),
        .data_in(data_in),
        .data_drive(),
        .dtack_n(dtack_n),
        .berr_n(berr_n),
        .result(),
        .overflow(),
        .trace_count(trace_count),
        .total_count(total_count),
        .signature(),
        .host_address(16'd0),
        .host_write(host_write),
        .host_data(16'ha55a),
        .host_read_data(host_read_data),
        .trace_address(14'd0),
        .trace_data()
    );

    task tick;
        begin
            @(posedge clock);
            #1;
            timestamp = timestamp + 1'b1;
        end
    endtask

    initial begin
        tick();
        clear = 1'b0;
        host_write = 1'b1;
        tick();
        host_write = 1'b0;
        repeat (3) tick();
        if (host_read_data != 16'ha55a)
            $fatal(1, "test setup did not initialize vector RAM");

        running = 1'b1;
        repeat (32) begin
            tick();
            if (!dtack_n || !berr_n || trace_count != 0 || total_count != 0)
                $fatal(1, "reset-time strobes were accepted as a transaction");
        end
        if (host_read_data != 16'ha55a)
            $fatal(1, "reset-time strobes corrupted vector RAM");

        as_n = 1'b1;
        uds_n = 1'b1;
        lds_n = 1'b1;
        read_cycle = 1'b1;
        function_code = 3'd6;
        repeat (8) tick();

        as_n = 1'b0;
        uds_n = 1'b0;
        lds_n = 1'b0;
        repeat (24) tick();
        if (dtack_n || data_in != 16'ha55a)
            $fatal(1, "first real vector read was not served correctly");
        as_n = 1'b1;
        uds_n = 1'b1;
        lds_n = 1'b1;
        repeat (5) tick();
        if (trace_count != 1 || total_count != 1)
            $fatal(1, "first real vector read was not captured exactly once");
        $display("PASS: reset strobes ignored, vector RAM preserved, real read captured");
        $finish;
    end
endmodule
