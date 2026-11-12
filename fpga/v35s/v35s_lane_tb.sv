`timescale 1ns/1ps

// Harness regression with a scripted V35 bus in place of the socket CPU.
// The script follows the data book B1/B2/B3 shape: row address with /MREQ
// in B1, column address with /MSTB or /IOSTB from B2 to the end of B3.
module v35s_lane_tb;
    reg clock = 0;
    always #10 clock = !clock;

    reg debug_valid = 0, debug_write = 0;
    reg [19:0] debug_address = 0;
    reg [15:0] debug_write_data = 0;
    wire debug_ready, debug_error;
    wire [15:0] debug_read_data;

    reg a0 = 0, a19 = 0, a18_ube = 1;
    reg [8:0] mux = 0;
    reg [15:0] cpu_data = 16'h0000;
    reg mreq_n = 1, mstb_n = 1, iostb_n = 1, read_write = 1, refrq_n = 1;
    wire [15:0] data_in;
    wire data_drive, ready, reset_n, armed, powered, x1, busy, complete;
    wire [15:0] levels;
    wire [7:0] p0_levels, port_mode;
    wire vector_drive;
    reg [7:0] p0_out = 8'h00;
    reg [3:0] r2_out = 4'hf;
    reg [1:0] txd = 2'b11;

    v35s_harness #(
        .MODEL_PRESENT(0), .COLD_RESET_TICKS(2000), .POWER_SETTLE_TICKS(100)
    ) harness (
        .clock(clock),
        .debug_valid(debug_valid), .debug_write(debug_write),
        .debug_address(debug_address), .debug_write_data(debug_write_data),
        .debug_ready(debug_ready), .debug_error(debug_error),
        .debug_read_data(debug_read_data),
        .socket_a0(a0), .socket_a19(a19), .socket_a18_ube(a18_ube),
        .socket_mux_address(mux), .socket_data_out(cpu_data),
        .socket_mreq_n(mreq_n), .socket_mstb_n(mstb_n), .socket_iostb_n(iostb_n),
        .socket_read_write(read_write), .socket_refrq_n(refrq_n),
        .socket_p0(p0_out), .socket_p2_out(5'h1f), .socket_r2(r2_out),
        .socket_t0(2'b00), .socket_txd(txd),
        .socket_data_in(data_in), .socket_data_drive(data_drive),
        .socket_vector_drive(vector_drive),
        .socket_ready(ready), .socket_reset_n(reset_n),
        .input_levels(levels), .p0_levels(p0_levels), .port_mode(port_mode),
        .socket_armed(armed), .socket_powered(powered), .x1(x1),
        .busy(busy), .complete(complete)
    );

    integer errors = 0;
    task check(input bit condition, input string message);
        if (!condition) begin
            $display("FAIL: %s", message);
            errors = errors + 1;
        end
    endtask

    task access(input bit write, input [19:0] address, input [15:0] value,
                output [15:0] result);
        @(posedge clock);
        debug_valid <= 1;
        debug_write <= write;
        debug_address <= address;
        debug_write_data <= value;
        do @(posedge clock); while (!debug_ready);
        result = debug_read_data;
        if (debug_error) begin
            $display("FAIL: debug access %h rejected", address);
            errors = errors + 1;
        end
        debug_valid <= 0;
        @(posedge clock);
    endtask

    task rejected(input [19:0] address, input [15:0] value);
        @(posedge clock);
        debug_valid <= 1;
        debug_write <= 1;
        debug_address <= address;
        debug_write_data <= value;
        do @(posedge clock); while (!debug_ready);
        check(debug_error, $sformatf("write %h to %h rejected", value, address));
        debug_valid <= 0;
        @(posedge clock);
    endtask

    reg [15:0] scratch;
    task wr(input [19:0] address, input [15:0] value);
        access(1, address, value, scratch);
    endtask
    function automatic [15:0] rd_value(input [15:0] v); rd_value = v; endfunction

    localparam real T = 250.0;   // one CLKOUT state at 4 MHz

    // One bus cycle. kind: 0 memory, 1 I/O, 2 refresh.
    task bus_cycle(input integer kind, input bit write, input [19:0] address,
                   input bit ube_n, input [15:0] value, output [15:0] sampled);
        // B1: row address valid, /MREQ falls half a state later.
        a0 = address[0];
        a19 = address[19];
        a18_ube = address[18];
        mux = kind == 2 ? 9'h1ff : address[17:9];
        read_write = !write;
        #(T / 2);
        mreq_n = 0;
        if (kind == 2) refrq_n = 0;
        #(T / 2);
        // B2: column address and the strobe.
        if (kind != 2) begin
            mux = {address[9], address[8:1]};
            a18_ube = ube_n;
            if (kind == 1) iostb_n = 0; else mstb_n = 0;
            if (write) cpu_data = value;
        end
        #(T * 2);
        // End of B3: the CPU samples read data on the strobe's rising edge.
        sampled = (data_drive && !write) ? data_in : 16'hxxxx;
        mstb_n = 1;
        iostb_n = 1;
        mreq_n = 1;
        refrq_n = 1;
        #(T / 2);
        read_write = 1;
        cpu_data = 16'h0000;
        #(T / 2);
    endtask

    reg [15:0] got;
    reg [15:0] record [0:7];
    integer index;
    initial begin
        repeat (10) @(posedge clock);
        // Map 0x00000-0x00fff to page 0 and 0xff000-0xfffff to page 1.
        wr(20'h40, 16'h8000);
        wr(20'h42, 16'h80ff);
        // Reset vector words at 0xffff0 (page 1 offset 0xff0).
        wr(20'h11ff0, 16'hea00);
        wr(20'h11ff2, 16'h0010);
        wr(20'h10100, 16'h5a5a);   // page 0 offset 0x100
        wr(20'h0a, 16'h0000);
        wr(20'h8e, 16'h1e1f);
        // Arm and start a socket-only run.
        wr(20'h04, 16'h0001);
        access(0, 20'h04, 0, got);
        check(got[0], "armed");
        wr(20'h04, 16'h0202);
        wait (reset_n);
        check(harness.power_ticks >= 2000, "cold reset waited for power-on time");
        #(T * 4);

        bus_cycle(0, 0, 20'hffff0, 0, 0, got);
        check(got == 16'hea00, $sformatf("reset fetch word, got %h", got));
        bus_cycle(0, 0, 20'hffff2, 0, 0, got);
        check(got == 16'h0010, $sformatf("second fetch word, got %h", got));
        bus_cycle(2, 0, 20'h00000, 1, 0, got);
        bus_cycle(0, 1, 20'h00100, 0, 16'h1234, got);
        bus_cycle(0, 0, 20'h00101, 0, 0, got);
        check(got[15:8] == 8'h12, $sformatf("odd byte read, got %h", got));
        bus_cycle(1, 1, 20'h0ff10, 1, 16'h0002, got);
        #(T * 2);
        check(port_mode == 8'h02, $sformatf("marker set T2 to D, got %h", port_mode));
        bus_cycle(1, 1, 20'h0ff00, 1, 16'h0000, got);
        wait (complete);

        access(0, 20'h06, 0, got);
        check(got[5:4] == 2'd1, $sformatf("socket pass, status %h", got));
        access(0, 20'h16, 0, got);
        check(got == 7, $sformatf("seven socket records, got %0d", got));
        access(0, 20'h20000 + 20'h0100, 0, got);
        check(got == 16'h1234, $sformatf("write reached socket RAM, got %h", got));

        // Record 3 is the write; check its address, flags and data.
        for (index = 0; index < 8; index = index + 1)
            access(0, 20'h40000 + 3 * 16 + index * 2, 0, record[index]);
        check({record[3][3:0], record[2]} == 20'h00100, "write address");
        check(record[3][15:4] == 12'h080, $sformatf("write flags %h", record[3][15:4]));
        check(record[4] == 16'h1234, "write data");
        // Record 2 is the refresh cycle.
        for (index = 0; index < 8; index = index + 1)
            access(0, 20'h40000 + 2 * 16 + index * 2, 0, record[index]);
        check(record[3][15:4] == 12'h00d, $sformatf("refresh flags %h", record[3][15:4]));

        stimulus_tests();

        if (errors == 0)
            $display("PASS: v35s_lane_tb");
        $finish;
    end

    // ---------------------------------------------------------------- version 2
    // The schedule, serial stimulus, pin records and the INTAK answer.
    integer tick = 0;
    integer event_valid_tick = 0, int_tick = 0;
    reg int_seen = 0;
    reg watch_int = 0;
    always @(posedge clock) begin
        tick <= tick + 1;
        if (harness.socket_event_valid && harness.socket_event_data == 8'd3)
            event_valid_tick <= tick;
        if (watch_int && levels[5] && !int_seen) begin
            int_seen <= 1;
            int_tick <= tick;
        end
    end
    integer event_tick, change_tick, k;
    reg [15:0] word;

    task entry(input integer n, input [7:0] ev, input [9:8] serial,
               input [23:0] delay, input [23:0] hold, input [12:0] mask,
               input [12:0] value);
        wr(20'h60000 + n * 16 + 0, {6'd0, serial, ev});
        wr(20'h60000 + n * 16 + 2, delay[15:0]);
        wr(20'h60000 + n * 16 + 4, {8'd0, delay[23:16]});
        wr(20'h60000 + n * 16 + 6, hold[15:0]);
        wr(20'h60000 + n * 16 + 8, {8'd0, hold[23:16]});
        wr(20'h60000 + n * 16 + 10, {3'd0, mask});
        wr(20'h60000 + n * 16 + 12, {3'd0, value});
        wr(20'h60000 + n * 16 + 14, 16'd0);
    endtask

    // Wait for the socket lane's event, then for a change of levels[bit].
    task time_change(input integer bit_index, output integer delta);
        reg was;
        begin
            was = levels[bit_index];
            delta = 0;
            while (levels[bit_index] == was && delta < 100000) begin
                @(posedge clock);
                delta = delta + 1;
            end
        end
    endtask

    reg [10:0] frame;   // idle, start, 0x55 LSB first, stop
    integer bit_tick;
    integer i;

    task stimulus_tests;
        begin
            access(0, 20'h02, 0, got);
            check(got == 16'h0002, $sformatf("harness version 2, got %h", got));
            // Bit time 4 ticks: rejected below 2.
            rejected(20'ha4, 16'd1);
            rejected(20'ha0, 16'd33);
            wr(20'ha4, 16'd4);
            wr(20'ha8, 16'd11);
            frame = {1'b1, 8'h55, 1'b0, 1'b1};
            wr(20'h60200, {5'd0, frame});
            // e0: event 3, after 50 ticks set INT high (bit 5) and keep it.
            entry(0, 8'd3, 2'b00, 24'd50, 24'd0, 13'h0020, 13'h0020);
            // e1: chained, after 20 ticks pulse NMI (bit 1) low for 30 ticks.
            entry(1, 8'hff, 2'b00, 24'd20, 24'd30, 13'h0002, 13'h0000);
            // e2: event 4 starts the RxD0 stream at once.
            entry(2, 8'd4, 2'b01, 24'd0, 24'd0, 13'h0000, 13'h0000);
            // e3: event 9 (an event 7 arrives first and is unmatched).
            entry(3, 8'd9, 2'b00, 24'd0, 24'd0, 13'h0010, 13'h0000);
            access(0, 20'h60000 + 3 * 16 + 10, 0, got);
            check(got == 16'h0010, $sformatf("schedule read back, got %h", got));
            wr(20'ha0, 16'h0304);      // 4 entries, answer INTAK, drop INT on it
            wr(20'ha2, 16'h005a);      // vector 5Ah
            wr(20'hac, 16'h00ff);      // record P0 ...
            wr(20'hae, 16'h0100);      // ... and TxD0
            wr(20'h04, 16'h0202);
            wait (reset_n);
            #(T * 4);
            check(levels == 16'h1e1f, $sformatf("levels at rest, got %h", levels));

            // P0 changes while T2 is host-driven are not recorded; TxD0 is.
            p0_out = 8'h11;
            #(T * 2);
            txd = 2'b10;
            #(T * 2);
            txd = 2'b11;
            #(T);

            watch_int = 1;
            bus_cycle(1, 1, 20'h0ff12, 1, 16'h0003, got);
            event_tick = tick;
            time_change(5, change_tick);
            check(levels[5] == 1'b1, "INT raised by e0");
            #1;
            check(int_tick - event_valid_tick == 50 + 4,
                  $sformatf("e0: INT at %0d, event at %0d (expect 54 apart)",
                            int_tick, event_valid_tick));
            time_change(1, change_tick);
            check(levels[1] == 1'b0, "NMI pulsed low by e1");
            // 8 ticks to fetch the entry, 1 to start, the delay, 1 to apply.
            check(change_tick == 8 + 1 + 20 + 1, $sformatf("e1 delay: %0d ticks (expect 30)", change_tick));
            time_change(1, change_tick);
            check(levels[1] == 1'b1 && change_tick == 30,
                  $sformatf("NMI pulse 30 ticks, got %0d", change_tick));

            // T2 and R2 to the CPU (D): P0 and /INTAK become observable.
            bus_cycle(1, 1, 20'h0ff10, 1, 16'h000a, got);
            #(T * 2);
            check(port_mode == 8'h0a, $sformatf("T2/R2 = D, got %h", port_mode));
            p0_out = 8'h22;
            #(T * 2);
            p0_out = 8'h23;
            #(T * 2);

            // RxD0: the 11-bit frame at 4 ticks a bit, sampled mid-bit.
            bus_cycle(1, 1, 20'h0ff12, 1, 16'h0004, got);
            while (levels[9] == 1'b1) @(posedge clock);
            // The first bit (idle 1) is skipped by the wait; the start bit is low.
            repeat (2) @(posedge clock);
            for (i = 1; i < 11; i = i + 1) begin
                check(levels[9] == frame[i], $sformatf("RxD0 bit %0d", i));
                repeat (4) @(posedge clock);
            end
            check(levels[9] == 1'b1, "RxD0 returns to idle");

            // INTAK: /INTAK low (R2 bit 1) answers 5Ah on D7..D0 and drops INT.
            check(levels[5] == 1'b1, "INT still high before INTAK");
            r2_out = 4'b1101;
            #(T);
            check(vector_drive && data_in[7:0] == 8'h5a,
                  $sformatf("vector drive %b data %h", vector_drive, data_in));
            check(levels[5] == 1'b0, "INT dropped at INTAK");
            r2_out = 4'b1111;
            #(T);
            check(!vector_drive, "vector drive ends with INTAK");

            // An event nobody wants, then the one e3 waits for.
            bus_cycle(1, 1, 20'h0ff12, 1, 16'h0007, got);
            bus_cycle(1, 1, 20'h0ff12, 1, 16'h0009, got);
            #(T * 2);
            check(levels[4] == 1'b0, "e3 lowered /INTP2");
            bus_cycle(1, 1, 20'h0ff00, 1, 16'h0000, got);
            wait (complete);

            access(0, 20'hb4, 0, got);
            check(got[7:0] == 8'd4, $sformatf("four socket events, got %0d", got[7:0]));
            access(0, 20'hb6, 0, got);
            check(got[7:0] == 8'd1, $sformatf("one unmatched event, got %0d", got[7:0]));
            access(0, 20'hb0, 0, got);
            check(got[5:0] == 6'd4 && got[10:8] == 3'd4,
                  $sformatf("schedule done at entry 4, status %h", got));

            // Pin records: TxD0 low, TxD0 high, P0 22h (made visible by the
            // bank handoff: 23h... see below), each flagged 200h.
            access(0, 20'h16, 0, got);
            k = 0;
            for (index = 0; index < got; index = index + 1) begin
                access(0, 20'h40000 + index * 16 + 6, 0, word);
                if (word[15:4] == 12'h200) begin
                    access(0, 20'h40000 + index * 16 + 4, 0, record[0]);
                    access(0, 20'h40000 + index * 16 + 8, 0, record[1]);
                    $display("pin record %0d: %h%h", k, record[1], record[0]);
                    case (k)
                        0: check({record[1], record[0]} == 32'h0000_0000, "TxD0 low");
                        1: check({record[1], record[0]} == 32'h0100_0000, "TxD0 high");
                        2: check({record[1], record[0]} == 32'h0100_0011, "P0 visible (11h)");
                        3: check({record[1], record[0]} == 32'h0100_0022, "P0 22h");
                        4: check({record[1], record[0]} == 32'h0100_0023, "P0 23h");
                        default: ;
                    endcase
                    k = k + 1;
                end
                if (word[15:4] == 12'h100) begin
                    access(0, 20'h40000 + index * 16 + 8, 0, record[1]);
                    check(record[1][7:0] == 8'd3 || record[1][7:0] == 8'd4 ||
                          record[1][7:0] == 8'd7 || record[1][7:0] == 8'd9,
                          "event record data");
                end
            end
            // P13 (/INTAK) is recorded only if masked in: it is not, so 5.
            check(k == 5, $sformatf("five pin records, got %0d", k));
        end
    endtask

    // Safety: the harness never answers a write or a refresh.
    always @(posedge clock) begin
        if (vector_drive && !read_write) begin
            $display("FAIL: vector driven during a write");
            errors = errors + 1;
        end
        if (data_drive && (!read_write || !refrq_n)) begin
            $display("FAIL: data driven during write or refresh");
            errors = errors + 1;
        end
    end

    initial begin
        #5_000_000;
        $display("FAIL: timeout");
        $finish;
    end
endmodule
