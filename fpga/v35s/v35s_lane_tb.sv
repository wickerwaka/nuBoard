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
        .socket_p0(8'h00), .socket_p2_out(5'h1f), .socket_r2(4'hf),
        .socket_data_in(data_in), .socket_data_drive(data_drive),
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

        if (errors == 0)
            $display("PASS: v35s_lane_tb");
        $finish;
    end

    // Safety: the harness never answers a write or a refresh.
    always @(posedge clock) begin
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
