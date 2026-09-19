`timescale 1ns/1ps

module m68000_harness (
    input  wire         clock,
    input  wire         debug_valid,
    input  wire         debug_write,
    input  wire [19:0]  debug_address,
    input  wire [15:0]  debug_write_data,
    output reg          debug_ready,
    output reg          debug_error,
    output reg  [15:0]  debug_read_data,

    input  wire [23:0]  socket_address,
    input  wire [15:0]  socket_data_out,
    input  wire         socket_as_n,
    input  wire         socket_uds_n,
    input  wire         socket_lds_n,
    input  wire         socket_read,
    input  wire [2:0]   socket_fc,
    input  wire         socket_reset_n,
    input  wire         socket_halt_n,
    output wire [15:0]  socket_data_in,
    output wire         socket_data_drive,
    output wire         socket_dtack_n,
    output wire         socket_berr_n,
    output reg          socket_armed,
    output wire         socket_reset_pull,
    output wire         socket_halt_pull,
    output reg          cpu_clock,
    output wire         busy,
    output reg          complete
);
    initial begin
        debug_ready = 1'b0;
        debug_error = 1'b0;
        debug_read_data = 16'd0;
        socket_armed = 1'b0;
        cpu_clock = 1'b0;
        complete = 1'b0;
    end
    reg [1:0] mode = 2'd1;
    reg [7:0] clock_divider = 8'd5;
    reg [7:0] wait_ticks = 8'd8;
    reg [31:0] run_limit = 32'd10_000_000;
    reg [31:0] capture_start = 32'd0;
    reg run_aborted = 1'b0;
    reg [255:0] page_map = 256'd0;
    reg [1:0] state = 2'd0;
    reg [7:0] divider_count = 8'd0;
    reg [15:0] reset_count = 16'd0;
    reg [31:0] run_ticks = 32'd0;
    reg timed_out = 1'b0;
    reg clear_lanes = 1'b1;

    wire clock_enabled = socket_armed || state != 0;
    wire clock_edge = clock_enabled && divider_count == clock_divider - 1'b1;
    wire phi1 = clock_edge && !cpu_clock;
    wire phi2 = clock_edge && cpu_clock;
    wire executing = state == 2'd2;
    assign busy = state != 0;
    assign socket_reset_pull = socket_armed && (!executing || !mode[1]);
    assign socket_halt_pull = socket_armed && (!executing || !mode[1]);

    always @(posedge clock) begin
        if (!clock_enabled) begin
            divider_count <= 8'd0;
            cpu_clock <= 1'b0;
        end else if (clock_edge) begin
            divider_count <= 8'd0;
            cpu_clock <= ~cpu_clock;
        end else begin
            divider_count <= divider_count + 1'b1;
        end
    end

    wire [23:1] model_address;
    wire [15:0] model_data_out;
    wire [15:0] model_data_in;
    wire model_as_n;
    wire model_uds_n;
    wire model_lds_n;
    wire model_read;
    wire [2:0] model_fc;
    wire model_dtack_n;
    wire model_berr_n;
    wire model_reset_n;
    wire model_halt_n;

    fx68k model (
        .clk(clock),
        .HALTn(1'b1),
        .extReset(!executing),
        .pwrUp(!executing),
        .enPhi1(phi1),
        .enPhi2(phi2),
        .eRWn(model_read),
        .ASn(model_as_n),
        .LDSn(model_lds_n),
        .UDSn(model_uds_n),
        .E(),
        .VMAn(),
        .FC0(model_fc[0]),
        .FC1(model_fc[1]),
        .FC2(model_fc[2]),
        .BGn(),
        .oRESETn(model_reset_n),
        .oHALTEDn(model_halt_n),
        .DTACKn(model_dtack_n),
        .VPAn(1'b1),
        .BERRn(model_berr_n),
        .BRn(1'b1),
        .BGACKn(1'b1),
        .IPL0n(1'b1),
        .IPL1n(1'b1),
        .IPL2n(1'b1),
        .iEdb(model_data_in),
        .oEdb(model_data_out),
        .eab(model_address)
    );

    reg [1:0] debug_stage = 2'd0;
    reg debug_accept = 1'b1;
    reg [19:0] saved_address = 20'd0;
    reg [15:0] saved_data = 16'd0;
    reg saved_write = 1'b0;
    wire memory_write = debug_stage == 2'd1 && saved_write &&
                        saved_address[19:16] == 4'h1 && !busy;
    wire [15:0] model_host_data;
    wire [15:0] socket_host_data;
    wire [15:0] model_trace_data;
    wire [15:0] socket_trace_data;
    wire [11:0] model_trace_count;
    wire [11:0] socket_trace_count;
    wire [1:0] model_result;
    wire [1:0] socket_result;
    wire model_overflow;
    wire socket_overflow;
    wire [31:0] model_total;
    wire [31:0] socket_total;
    wire [31:0] model_signature;
    wire [31:0] socket_signature;

    // One 64-bit observation per lane: address[23:0], data[39:24],
    // AS/UDS/LDS/RW/DTACK/BERR[45:40], FC[48:46], CLK[49],
    // RESET_N[50], HALT_N[51], then twelve reserved zero bits.
    // Socket data is the actual FPGA input path, including driven read data.
    wire [15:0] model_bus_data = model_read ? model_data_in : model_data_out;
    wire [63:0] model_signals = {
        12'd0, model_halt_n, model_reset_n, cpu_clock, model_fc,
        model_berr_n, model_dtack_n, model_read, model_lds_n,
        model_uds_n, model_as_n, model_bus_data, model_address, 1'b0
    };
    wire [63:0] socket_signals = {
        12'd0, socket_halt_n, socket_reset_n, cpu_clock, socket_fc,
        socket_berr_n, socket_dtack_n, socket_read, socket_lds_n,
        socket_uds_n, socket_as_n, socket_data_out, socket_address
    };
    wire [15:0] scope_host_data;
    wire scope_ready, scope_error, scope_busy, scope_start_allowed;
    wire [1:0] scope_lane;
    wire scope_access = saved_address[19:16] == 4'h5 ||
                        (saved_address < 20'h100 &&
                         ((saved_address >= 20'h2e && saved_address <= 20'h3c) ||
                          saved_address >= 20'h60));

    m68000_scope scope (
        .clock(clock),
        .clear(clear_lanes),
        .running(executing),
        .run_busy(busy),
        .aborted(run_aborted),
        .model_signals(model_signals[51:0]),
        .socket_signals(socket_signals[51:0]),
        .timestamp(run_ticks),
        .debug_valid(debug_stage == 3 && scope_access && !saved_address[0]),
        .debug_write(saved_write),
        .debug_address(saved_address),
        .debug_write_data(saved_data),
        .debug_ready(scope_ready),
        .debug_error(scope_error),
        .debug_data(scope_host_data),
        .busy(scope_busy),
        .start_allowed(scope_start_allowed),
        .selected_lane(scope_lane)
    );

    m68000_lane model_lane (
        .clock(clock),
        .clear(clear_lanes),
        .running(executing && mode[0]),
        .timestamp(run_ticks),
        .wait_ticks(wait_ticks),
        .capture_start(capture_start),
        .page_map(page_map),
        .address({model_address, 1'b0}),
        .data_out(model_data_out),
        .as_n(model_as_n),
        .uds_n(model_uds_n),
        .lds_n(model_lds_n),
        .read_cycle(model_read),
        .function_code(model_fc),
        .data_in(model_data_in),
        .data_drive(),
        .dtack_n(model_dtack_n),
        .berr_n(model_berr_n),
        .result(model_result),
        .overflow(model_overflow),
        .trace_count(model_trace_count),
        .total_count(model_total),
        .signature(model_signature),
        .host_address(saved_address[15:0]),
        .host_write(memory_write),
        .host_data(saved_data),
        .host_read_data(model_host_data),
        .trace_address(saved_address[14:1]),
        .trace_data(model_trace_data)
    );

    m68000_lane socket_lane (
        .clock(clock),
        .clear(clear_lanes),
        .running(executing && mode[1]),
        .timestamp(run_ticks),
        .wait_ticks(wait_ticks),
        .capture_start(capture_start),
        .page_map(page_map),
        .address(socket_address),
        .data_out(socket_data_out),
        .as_n(socket_as_n),
        .uds_n(socket_uds_n),
        .lds_n(socket_lds_n),
        .read_cycle(socket_read),
        .function_code(socket_fc),
        .data_in(socket_data_in),
        .data_drive(socket_data_drive),
        .dtack_n(socket_dtack_n),
        .berr_n(socket_berr_n),
        .result(socket_result),
        .overflow(socket_overflow),
        .trace_count(socket_trace_count),
        .total_count(socket_total),
        .signature(socket_signature),
        .host_address(saved_address[15:0]),
        .host_write(memory_write),
        .host_data(saved_data),
        .host_read_data(socket_host_data),
        .trace_address(saved_address[14:1]),
        .trace_data(socket_trace_data)
    );

    wire [15:0] status = {
        8'd0, timed_out, model_overflow || socket_overflow,
        socket_result, model_result, complete, busy
    };
    wire lanes_finished = (!mode[0] || model_result != 0) &&
                          (!mode[1] || socket_result != 0);

    always @(posedge clock) begin
        clear_lanes <= 1'b0;
        debug_ready <= 1'b0;
        debug_error <= 1'b0;
        if (!debug_valid)
            debug_accept <= 1'b1;

        if (state == 2'd1 && phi2) begin
            if (reset_count == 16'd599) begin
                reset_count <= 16'd0;
                run_ticks <= 32'd0;
                state <= 2'd2;
            end else begin
                reset_count <= reset_count + 1'b1;
            end
        end else if (executing) begin
            run_ticks <= run_ticks + 1'b1;
            if (lanes_finished || run_ticks >= run_limit ||
                model_overflow || socket_overflow) begin
                state <= 2'd0;
                complete <= 1'b1;
                timed_out <= run_ticks >= run_limit;
            end
        end

        case (debug_stage)
            2'd0: begin
                if (debug_valid && debug_accept) begin
                    debug_accept <= 1'b0;
                    saved_address <= debug_address;
                    saved_write <= debug_write;
                    saved_data <= debug_write_data;
                    debug_stage <= 2'd1;
                end
            end
            2'd1: debug_stage <= 2'd2;
            2'd2: debug_stage <= 2'd3;
            2'd3: begin
                debug_stage <= 2'd0;
                debug_ready <= 1'b1;
                debug_read_data <= 16'd0;

                if (scope_access && !saved_address[0]) begin
                    debug_stage <= scope_ready ? 2'd0 : 2'd3;
                    debug_ready <= scope_ready;
                    debug_error <= scope_error;
                    debug_read_data <= scope_host_data;
                end else if (saved_address[0] ||
                    (busy && (saved_write || saved_address >= 20'h10000) &&
                     !(saved_write && saved_address == 4 && saved_data[2]))) begin
                    debug_error <= 1'b1;
                end else if (saved_address < 20'h00100) begin
                    if (saved_write) begin
                        case (saved_address[7:0])
                            8'h04: begin
                                if (saved_data[2]) begin
                                    state <= 2'd0;
                                    complete <= 1'b1;
                                    run_aborted <= 1'b1;
                                end else if (saved_data[1]) begin
                                    if (saved_data[9:8] == 0 ||
                                        (saved_data[9] && !socket_armed) ||
                                        (scope_lane == 1 && !saved_data[8]) ||
                                        (scope_lane == 2 && !saved_data[9]) ||
                                        !scope_start_allowed) begin
                                        debug_error <= 1'b1;
                                    end else begin
                                        mode <= saved_data[9:8];
                                        complete <= 1'b0;
                                        timed_out <= 1'b0;
                                        run_aborted <= 1'b0;
                                        clear_lanes <= 1'b1;
                                        reset_count <= 16'd0;
                                        state <= 2'd1;
                                    end
                                end else begin
                                    socket_armed <= saved_data[0];
                                    complete <= 1'b0;
                                end
                            end
                            8'h08: begin
                                // NMOS MC68000 requires a continuous >=4 MHz clock.
                                if (socket_armed || saved_data < 5 || saved_data > 6)
                                    debug_error <= 1'b1;
                                else
                                    clock_divider <= saved_data[7:0];
                            end
                            8'h0a: begin
                                if (saved_data < 2 || saved_data > 255)
                                    debug_error <= 1'b1;
                                else
                                    wait_ticks <= saved_data[7:0];
                            end
                            8'h0c: run_limit[15:0] <= saved_data;
                            8'h0e: run_limit[31:16] <= saved_data;
                            8'h2a: capture_start[15:0] <= saved_data;
                            8'h2c: capture_start[31:16] <= saved_data;
                            default: begin
                                if (saved_address >= 20'h40 && saved_address < 20'h60)
                                    page_map[saved_address[4:1] * 16 +: 16] <= saved_data;
                                else
                                    debug_error <= 1'b1;
                            end
                        endcase
                    end else begin
                        case (saved_address[7:0])
                            8'h00: debug_read_data <= 16'h6830;
                            8'h02: debug_read_data <= 16'h0001;
                            8'h04: debug_read_data <= {6'd0, mode, 7'd0, socket_armed};
                            8'h06: debug_read_data <= status;
                            8'h08: debug_read_data <= {8'd0, clock_divider};
                            8'h0a: debug_read_data <= {8'd0, wait_ticks};
                            8'h0c: debug_read_data <= run_limit[15:0];
                            8'h0e: debug_read_data <= run_limit[31:16];
                            8'h10: debug_read_data <= run_ticks[15:0];
                            8'h12: debug_read_data <= run_ticks[31:16];
                            8'h14: debug_read_data <= {4'd0, model_trace_count};
                            8'h16: debug_read_data <= {4'd0, socket_trace_count};
                            8'h1a: debug_read_data <= model_total[15:0];
                            8'h1c: debug_read_data <= model_total[31:16];
                            8'h1e: debug_read_data <= socket_total[15:0];
                            8'h20: debug_read_data <= socket_total[31:16];
                            8'h22: debug_read_data <= model_signature[15:0];
                            8'h24: debug_read_data <= model_signature[31:16];
                            8'h26: debug_read_data <= socket_signature[15:0];
                            8'h28: debug_read_data <= socket_signature[31:16];
                            8'h2a: debug_read_data <= capture_start[15:0];
                            8'h2c: debug_read_data <= capture_start[31:16];
                            8'h18: debug_read_data <= {
                                7'd0, socket_fc, socket_read, socket_lds_n,
                                socket_uds_n, socket_as_n, socket_halt_n, socket_reset_n
                            };
                            default: begin
                                if (saved_address >= 20'h40 && saved_address < 20'h60)
                                    debug_read_data <= page_map[saved_address[4:1] * 16 +: 16];
                                else
                                    debug_error <= 1'b1;
                            end
                        endcase
                    end
                end else begin
                    case (saved_address[19:16])
                        4'h1: debug_read_data <= model_host_data;
                        4'h2: begin
                            debug_read_data <= socket_host_data;
                            debug_error <= saved_write;
                        end
                        4'h3: begin
                            debug_read_data <= model_trace_data;
                            debug_error <= saved_write || saved_address[15];
                        end
                        4'h4: begin
                            debug_read_data <= socket_trace_data;
                            debug_error <= saved_write || saved_address[15];
                        end
                        default: debug_error <= 1'b1;
                    endcase
                end
            end
        endcase
    end
endmodule
