`timescale 1ns/1ps

// Regress the independently synchronized byte strobes exposed by board capture.
// Sampling must not change ACK latency or turn genuine byte cycles into words.
module m68000_strobe_skew_tb;
    reg clock = 0;
    always #10 clock = ~clock;
    reg clear = 1;
    reg running = 0;
    reg host_write = 1;
    reg as_n = 1;
    reg uds_n = 1;
    reg lds_n = 1;
    reg read_cycle = 0;
    reg [15:0] data_out = 0;
    wire dtack_n;
    wire [15:0] host_read_data;

    m68000_lane dut (
        .clock(clock), .clear(clear), .running(running), .timestamp(32'd0),
        .wait_ticks(8'd8), .capture_start(32'd0), .page_map(256'h8000),
        .fuzz_enabled(1'b0), .fuzz_pc(16'd8), .fuzz_started(),
        .address(24'd0), .data_out(data_out), .as_n(as_n),
        .uds_n(uds_n), .lds_n(lds_n), .read_cycle(read_cycle), .function_code(3'd5),
        .data_in(), .data_drive(), .dtack_n(dtack_n), .berr_n(),
        .result(), .overflow(), .trace_count(), .total_count(), .signature(),
        .host_address(16'd0), .host_write(host_write), .host_data(16'h1122),
        .host_read_data(host_read_data), .trace_address(14'd0), .trace_data()
    );

    task automatic transfer(
        input bit reading,
        input [1:0] first_mask,
        input [1:0] final_mask,
        input [15:0] value,
        input [15:0] expected_word,
        input bit keep_as
    );
        integer elapsed;
        begin
            read_cycle = reading;
            data_out = ~value;
            as_n = 0;
            uds_n = !first_mask[1];
            lds_n = !first_mask[0];
            @(negedge clock);
            uds_n = !final_mask[1];
            lds_n = !final_mask[0];
            // Data also settles after selection, independently of the strobes.
            @(negedge clock);
            data_out = value;
            elapsed = 2;
            while (dtack_n) begin
                @(negedge clock);
                elapsed = elapsed + 1;
            end
            // Two synchronizers, selection, nine delay cycles, then ACK.
            if (elapsed != 13)
                $fatal(1, "ACK latency changed: %0d ticks", elapsed);
            if (dut.transaction_flags[1:0] != final_mask)
                $fatal(1, "incorrect byte mask: %b", dut.transaction_flags[1:0]);
            if (dut.transaction_data != (reading ? expected_word : value))
                $fatal(1, "incorrect settled data: %h", dut.transaction_data);
            repeat (4) @(negedge clock);
            as_n = !keep_as;
            uds_n = 1;
            lds_n = 1;
            repeat (8) @(negedge clock);
            if (host_read_data != expected_word)
                $fatal(1, "RAM expected %h, observed %h", expected_word, host_read_data);
        end
    endtask

    initial begin
        repeat (4) @(negedge clock);
        host_write = 0;
        clear = 0;
        running = 1;
        repeat (8) @(negedge clock);
        transfer(0, 2'b01, 2'b11, 16'habcd, 16'habcd, 0);
        transfer(0, 2'b10, 2'b11, 16'h5678, 16'h5678, 0);
        transfer(0, 2'b11, 2'b11, 16'h1234, 16'h1234, 0);
        transfer(0, 2'b10, 2'b10, 16'habff, 16'hab34, 0);
        transfer(0, 2'b01, 2'b01, 16'hffcd, 16'habcd, 0);
        transfer(1, 2'b01, 2'b11, 16'd0, 16'habcd, 0);
        transfer(1, 2'b10, 2'b11, 16'd0, 16'habcd, 0);
        transfer(1, 2'b11, 2'b11, 16'd0, 16'habcd, 0);
        transfer(1, 2'b10, 2'b10, 16'd0, 16'habcd, 0);
        // TAS-style read/write pair keeps AS asserted between byte cycles.
        transfer(1, 2'b01, 2'b01, 16'd0, 16'habcd, 1);
        transfer(0, 2'b01, 2'b01, 16'h00ef, 16'habef, 0);
        $display("PASS: skew, byte masks, settled data, TAS, and unchanged ACK latency");
        $finish;
    end

    initial begin
        #20000;
        $fatal(1, "strobe-skew watchdog");
    end
endmodule
