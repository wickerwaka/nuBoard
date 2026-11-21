`timescale 1ns/1ps

// V35S differential harness. The socketed CPU and the model core each get an
// identical v35s_lane responder. Both are clocked from the same X1 divider and
// leave reset on the same system tick.
//
// Debug register map (word addresses, 16-bit):
//   00 ID 0x7033            02 version
//   04 control: 0 arm, 1 start, 2 abort, 9:8 lane mode (1 model, 2 socket)
//   06 status:  0 busy, 1 complete, 3:2 model result, 5:4 socket result,
//               6 overflow, 7 timed out, 8 cold-reset wait active
//   08 X1 half period in 30 ns ticks (2..255; X1 = 16.67 MHz / value)
//   0a READY hold in ticks after the column strobe (0 = always ready)
//   (version 3) c2 READY from /MREQ's fall: 11:0 delay ticks, 12 start on read cycles,
//      13 start on write cycles; c4 11:0 hold ticks (0 = off); c6 7:0 the 128K blocks
//      (A19-A17 of the row) whose cycles start a window (reset FFh); 8e bit 13: READY held low
//   0c/0e run limit          10/12 run ticks
//   14/16 model/socket trace count
//   18 live socket pins (read)
//   1a-28 totals and signatures, 2a/2c capture start
//   2e-3c, 60-7e and 0x5xxxx: scope (m68000_scope ABI 4)
//   40-5e page map: 16 x {valid, 7'b0, A19..A12}
//   84/86 reset hold ticks (minimum 167 = 5 us)
//   88 port mode at start: 2 bits per bank T2, R2, R0, T0 (0 H, 1 Z, 2 D)
//   8a live port mode (read)
//   8c P0 drive levels while T2 is H
//   8e input levels: 0 N/S, 1 NMI, 2 /INTP0, 3 /INTP1, 4 /INTP2, 5 INT,
//      6 DMARQ0, 7 DMARQ1, 8 HLDRQ, 9 RxD0, 10 RxD1, 11 /CTS0, 12 /CTS1
//   90 marker count (socket, model in high byte)   92 last socket marker
//   94/96 ticks since arm (saturating)
//   98/9a live P0, {R2, P2 outputs}
//   (version 2) stimulus and output recording, v35s_stim.sv / v35s_lane.sv:
//   a0 schedule: 5:0 entry count (0-32), 8 answer INTAK with the vector,
//      9 drop INT at /INTAK's falling edge
//   a2 INTAK vector (7:0)
//   a4/a6 RxD0/RxD1 bit time in ticks (2-65535)
//   a8/aa RxD0/RxD1 pattern length in bits (0-2048)
//   ac/ae pin record mask, low/high word (pin vector below; 0 = no records)
//   b0/b2 socket/model stimulus status: 5:0 entry, 10:8 state, 12/13 RxD0/1
//      streaming (read)
//   b4 events {model, socket}   b6 unmatched events {model, socket}
//   b8 last events {model, socket}
//   ba/bc live socket pin vector low/high (unmasked)
//   be/c0 live input levels: socket, model
//   c8 (core v2 builds, write) the secure mode's translation table (C2h until version 3
//      took C2h for READY): {address 15:8, byte 7:0},
//      one entry a write, refused while busy; the core never initialises it (256 writes load
//      it). Model lane only: the socket's table is its mask's
//   Pin vector: 7:0 P0, 11 P13//INTAK, 12 P14, 13 P15/TOUT, 14 P16//SCK0,
//      15 P17, 17 P21//DMAAK0, 18 P22//TC0, 20 P24//DMAAK1, 21 P25//TC1,
//      22 P26//HLDAK, 24 TxD0, 25 TxD1, 26 /CTS0 pin; a bit records only
//      while its bank is CPU-driven (T2, R2, T0, R0 = D; TxD always).
//   0x60000-0x601ff schedule (32 x 8 words), 0x60200-0x602ff RxD0 pattern,
//   0x60300-0x603ff RxD1 pattern (writes go to both lanes; reads the socket's)
//   0x1xxxx model RAM (writes broadcast to both lanes), 0x2xxxx socket RAM,
//   0x3xxxx model trace, 0x4xxxx socket trace
module v35s_harness #(
    parameter MODEL_PRESENT = 1,
    // Ticks of the 33.33 MHz system clock (30 ns).
    parameter [31:0] COLD_RESET_TICKS = 32'd1_000_000,    // 30 ms after power-on
    // DUT power switches on with arming. Translators and X1 stay disabled
    // for 1 ms so no input is driven while the CPU supply is still ramping.
    parameter [31:0] POWER_SETTLE_TICKS = 32'd33_334
) (
    input  wire         clock,
    input  wire         debug_valid,
    input  wire         debug_write,
    input  wire [19:0]  debug_address,
    input  wire [15:0]  debug_write_data,
    output reg          debug_ready,
    output reg          debug_error,
    output reg  [15:0]  debug_read_data,

    // Socket pins, already permuted into CPU order.
    input  wire         socket_a0,
    input  wire         socket_a19,
    input  wire         socket_a18_ube,
    input  wire [8:0]   socket_mux_address,
    input  wire [15:0]  socket_data_out,
    input  wire         socket_mreq_n,
    input  wire         socket_mstb_n,
    input  wire         socket_iostb_n,
    input  wire         socket_read_write,
    input  wire         socket_refrq_n,
    input  wire [7:0]   socket_p0,
    input  wire [4:0]   socket_p2_out,     // DMAAK0, TC0, DMAAK1, HLDAK, TC1
    input  wire [3:0]   socket_r2,         // /CTS0, /INTP2, TOUT, /SCK0
    input  wire [1:0]   socket_t0,         // P14 (INT), P17 (READY) while T0 = D
    input  wire [1:0]   socket_txd,        // TxD0, TxD1
    output wire [15:0]  socket_data_in,
    output wire         socket_data_drive,
    output wire         socket_vector_drive,   // D7..D0 only: the INTAK answer
    output wire         socket_ready,
    output wire         socket_reset_n,
    output wire [15:0]  input_levels,      // the socket's, after its schedule
    output reg  [7:0]   p0_levels,
    output reg  [7:0]   port_mode,
    output reg          socket_armed,
    output wire         socket_powered,
    output reg          x1,
    output wire         busy,
    output reg          complete
);
    initial begin
        debug_ready = 1'b0;
        debug_error = 1'b0;
        debug_read_data = 16'd0;
        socket_armed = 1'b0;
        x1 = 1'b0;
        complete = 1'b0;
        p0_levels = 8'd0;
        port_mode = 8'd0;
    end

    reg [1:0] mode = 2'd2;
    reg [7:0] x_half = 8'd2;
    reg [7:0] ready_ticks = 8'd0;
    reg [13:0] ready_m_delay = 14'd0;   // (version 3) register C2h
    reg [11:0] ready_m_hold = 12'd0;    // (version 3) register C4h
    reg [7:0] ready_m_blocks = 8'hff;   // (version 3) register C6h
    reg [31:0] run_limit = 32'd50_000_000;
    reg [31:0] capture_start = 32'd0;
    reg [31:0] reset_ticks = 32'd1_667;
    reg [7:0] start_port_mode = 8'd0;
    reg run_aborted = 1'b0;
    reg [255:0] page_map = 256'd0;
    reg [1:0] state = 2'd0;
    reg [7:0] divider_count = 8'd0;
    reg [31:0] reset_count = 32'd0;
    reg [31:0] power_ticks = 32'd0;
    reg [31:0] run_ticks = 32'd0;
    reg timed_out = 1'b0;
    reg clear_lanes = 1'b1;
    reg [7:0] socket_markers = 8'd0;
    reg [7:0] model_markers = 8'd0;
    reg [15:0] last_marker = 16'd0;
    reg [15:0] base_levels = 16'h1e1f;
    reg [7:0] model_port_mode = 8'd0;
    reg [5:0] entry_count = 6'd0;
    reg intak_enable = 1'b0;
    reg int_release = 1'b0;
    reg [7:0] intak_vector = 8'hff;
    reg [15:0] bit_time0 = 16'd2, bit_time1 = 16'd2;
    reg [11:0] length0 = 12'd0, length1 = 12'd0;
    reg [31:0] pin_record_mask = 32'd0;

    wire clock_enabled = socket_armed || state != 0;
    wire x_edge = clock_enabled && divider_count == x_half - 1'b1;
    wire x_rise = x_edge && !x1;
    wire x_fall = x_edge && x1;
    wire executing = state == 2'd2;
    // The 30 ms power-on reset applies only when the socket CPU takes part.
    wire cold_wait = mode[1] && power_ticks < COLD_RESET_TICKS;
    assign socket_powered = socket_armed && power_ticks >= POWER_SETTLE_TICKS;
    assign busy = state != 0;
    // Registered 32-bit reset-hold compare; it only lengthens reset by a tick.
    reg reset_done = 1'b0;
    always @(posedge clock)
        reset_done <= state == 2'd1 && reset_count >= reset_ticks &&
                      reset_count >= 32'd167 && !cold_wait;
    assign socket_reset_n = executing && mode[1];

    always @(posedge clock) begin
        if (!clock_enabled) begin
            divider_count <= 8'd0;
            x1 <= 1'b0;
        end else if (x_edge) begin
            divider_count <= 8'd0;
            x1 <= ~x1;
        end else begin
            divider_count <= divider_count + 1'b1;
        end
        if (!socket_armed)
            power_ticks <= 32'd0;
        else if (power_ticks != 32'hffffffff)
            power_ticks <= power_ticks + 1'b1;
    end

    wire model_a0, model_a19, model_a18_ube;
    wire [8:0] model_mux_address;
    wire [15:0] model_data_out;
    wire model_mreq_n, model_mstb_n, model_iostb_n, model_read_write, model_refrq_n;
    wire model_core_intak_n;          // (F3b) the core v2's /INTAK (V35S_CORE_V35)
    wire [15:0] model_lane_data_in;
    wire model_data_drive, model_ready;
    wire [15:0] model_levels;
    wire model_vector_drive, socket_stim_vector_drive;
    wire [31:0] model_core_pins;      // (F4) the core v2's output pins (V35S_CORE_V35)
    // (F4) the port pins as nuboard_v35s.v drives the socket's (each bank while the lane's mode
    // has it H; 0 otherwise): P0 the host's levels (T2); P1: P10-P12 NMI, /INTP0-1 (B1), P13
    // /INTP2 (R2), P14 INT and P17 READY (T0), P15 / P16 low (R2); P2: DMARQ0 / DMARQ1 / HLDRQ
    // (B2, always), the R0 bits low
    wire [23:0] model_pins_in = {
        model_levels[8], 3'd0, model_levels[7], 2'd0, model_levels[6],
        model_port_mode[7:6] == 2'd0 && model_ready, 2'd0,
        model_port_mode[7:6] == 2'd0 && model_levels[5],
        model_port_mode[3:2] == 2'd0 && model_levels[4], model_levels[3:1],
        model_port_mode[1:0] == 2'd0 ? p0_levels : 8'd0
    };
    // The INTAK answer: the vector on D7..D0 while the lane asks for it.
    wire [15:0] model_data_in = model_vector_drive ?
        {model_lane_data_in[15:8], intak_vector} : model_lane_data_in;

`ifdef V35S_CORE_V35
    // the V35S core v2 (docs/v35s-core-v2.md; build_sim.sh direct v35)
    v35_top model (
`else
    v35s_model model (
`endif
        .clock(clock),
        .x_rise(x_rise),
        .x_fall(x_fall),
        .reset_n(executing && mode[0]),
        .ready(model_ready),
        .data_in(model_data_in),
        .input_levels(model_levels),
        .a0(model_a0),
        .a19(model_a19),
        .a18_ube(model_a18_ube),
        .mux_address(model_mux_address),
        .data_out(model_data_out),
        .mreq_n(model_mreq_n),
        .mstb_n(model_mstb_n),
        .iostb_n(model_iostb_n),
        .read_write(model_read_write),
`ifdef V35S_CORE_V35
        .intak_n(model_core_intak_n),   // (F3b) the core v2's /INTAK
        .pins_in(model_pins_in),        // (F4) the port pins as the board drives them
        .pins(model_core_pins),         // (F4) the core v2's output pins
        .tt_we(model_tt_we),            // (work order 29) the translation table's load port
        .tt_a(model_tt_a),
        .tt_d(model_tt_d),
`endif
        .refrq_n(model_refrq_n)
    );

`ifdef V35S_CORE_V35
    // (work order 29) register c8: one write a table entry, a one-clock tt_we
    reg model_tt_we = 1'b0;
    reg [7:0] model_tt_a = 8'd0, model_tt_d = 8'd0;
`endif
    reg [1:0] debug_stage = 2'd0;
    reg debug_accept = 1'b1;
    reg [19:0] saved_address = 20'd0;
    reg [15:0] saved_data = 16'd0;
    reg saved_write = 1'b0;
    wire memory_write = debug_stage == 2'd1 && saved_write &&
                        saved_address[19:16] == 4'h1 && !busy;
    wire [15:0] model_host_data, socket_host_data;
    wire [15:0] model_trace_data, socket_trace_data;
    wire [11:0] model_trace_count, socket_trace_count;
    wire [1:0] model_result, socket_result;
    wire model_overflow, socket_overflow;
    wire [31:0] model_total, socket_total;
    wire [31:0] model_signature, socket_signature;
    wire model_marker_valid, socket_marker_valid;
    wire [15:0] model_marker_data, socket_marker_data;
    wire [2:0] model_lane_state, socket_lane_state;
    wire model_event_valid, socket_event_valid;
    wire [7:0] model_event_data, socket_event_data;
    wire [15:0] socket_lane_data_in;
    wire [15:0] socket_levels;

    // Output pins in the recorder's order (see the map above). The model
    // cores drive none of these yet; a later stage adds them to v35_top.
    wire [31:0] socket_pins = {
        5'd0, socket_r2[0], socket_txd,
        1'b0, socket_p2_out[3], socket_p2_out[4], socket_p2_out[2], 1'b0,
        socket_p2_out[1], socket_p2_out[0], 1'b0,
        socket_t0[1], socket_r2[3], socket_r2[2], socket_t0[0], socket_r2[1], 3'd0,
        socket_p0
    };
`ifdef V35S_CORE_V35
    // (F4) the core v2's output pins, recorded as the socket's are
    wire [31:0] model_pins = model_core_pins;
`else
    wire [31:0] model_pins = 32'd0;
`endif
`ifdef V35S_CORE_V35
    // (F3b) the core v2 drives /INTAK (P13); the lane answers the vector while it is low and
    // the model's R2 bank is announced CPU-driven, as for the socket
    wire model_intak_n = model_core_intak_n;
`else
    wire model_intak_n = 1'b1;
`endif
    // Pins a bank in mode D lets the FPGA see.
    function [31:0] observable;
        input [7:0] modes;
        begin
            observable = 32'h0300_0000;
            if (modes[1:0] == 2'd2) observable = observable | 32'h0000_00ff;   // T2: P0
            if (modes[3:2] == 2'd2) observable = observable | 32'h0400_6800;   // R2
            if (modes[7:6] == 2'd2) observable = observable | 32'h0000_9000;   // T0
            if (modes[5:4] == 2'd2) observable = observable | 32'h0076_0000;   // R0
        end
    endfunction

    // One 52-bit observation per lane for the scope:
    //   [15:0] data bus, [24:16] multiplexed address pins, 25 A18//UBE,
    //   26 A19, 27 A0, 28 R//W, 29 /MREQ, 30 /MSTB, 31 /IOSTB, 32 /REFRQ,
    //   33 X1, 34 /RESET, 35 READY, 36 data driven by the harness,
    //   39:37 lane state, 47:40 P0 (P07 = CLKOUT; the core v2's P0 too: work
    //   order 34, below), 51:48 R2 pins (socket) or
    //   zero (model). Socket data is the actual FPGA input path.
    wire [15:0] model_bus_data = model_data_drive ? model_data_in : model_data_out;
`ifdef V35S_CORE_V35
    // (work order 34) the core v2's P0 as the socket's scope field sees it: the core's pins
    // while the lane's T2 is CPU-driven (D), the host's levels while host-driven (H), else 0
    wire [7:0] model_scope_p0 = model_port_mode[1:0] == 2'd2 ? model_core_pins[7:0]
                              : model_port_mode[1:0] == 2'd0 ? p0_levels : 8'd0;
`else
    wire [7:0] model_scope_p0 = 8'd0;
`endif
    wire [51:0] model_signals = {
        4'd0, model_scope_p0, model_lane_state, model_data_drive, model_ready,
        executing && mode[0], x1, model_refrq_n, model_iostb_n, model_mstb_n,
        model_mreq_n, model_read_write, model_a0, model_a19, model_a18_ube,
        model_mux_address, model_bus_data
    };
    wire [51:0] socket_signals = {
        socket_r2, socket_p0, socket_lane_state, socket_data_drive, socket_ready,
        socket_reset_n, x1, socket_refrq_n, socket_iostb_n, socket_mstb_n,
        socket_mreq_n, socket_read_write, socket_a0, socket_a19, socket_a18_ube,
        socket_mux_address, socket_data_out
    };
    wire [15:0] scope_host_data;
    wire scope_ready, scope_error, scope_busy, scope_start_allowed_live;
    // Registered: the scope interval only changes through earlier debug
    // writes, so the start decision sees the same value one clock later.
    reg scope_start_allowed = 1'b0;
    always @(posedge clock)
        scope_start_allowed <= scope_start_allowed_live;
    wire [1:0] scope_lane;
    wire scope_access = saved_address[19:16] == 4'h5 ||
                        (saved_address < 20'h100 &&
                         ((saved_address >= 20'h2e && saved_address <= 20'h3c) ||
                          (saved_address >= 20'h60 && saved_address < 20'h80)));

    m68000_scope #(.TICK_REPORT(16'd3000)) scope (
        .clock(clock),
        .clear(clear_lanes),
        .running(executing),
        .run_busy(busy),
        .aborted(run_aborted),
        .model_signals(model_signals),
        .socket_signals(socket_signals),
        .timestamp(run_ticks),
        .debug_valid(debug_stage == 3 && scope_access && !saved_address[0]),
        .debug_write(saved_write),
        .debug_address(saved_address),
        .debug_write_data(saved_data),
        .debug_ready(scope_ready),
        .debug_error(scope_error),
        .debug_data(scope_host_data),
        .busy(scope_busy),
        .start_allowed(scope_start_allowed_live),
        .selected_lane(scope_lane)
    );

    // (version 3) READY at each lane's CPU: the lane's (strobe-timed and /MREQ-timed) and the
    // schedule's level 13 (1 = READY held low)
    wire model_lane_ready, socket_lane_ready;
    assign model_ready = model_lane_ready && !model_levels[13];
    assign socket_ready = socket_lane_ready && !socket_levels[13];

    v35s_lane model_lane (
        .clock(clock), .clear(clear_lanes), .running(executing && mode[0]),
        .timestamp(run_ticks), .ready_ticks(ready_ticks),
        .ready_m_delay(ready_m_delay), .ready_m_hold(ready_m_hold),
        .ready_m_blocks(ready_m_blocks),
        .capture_start(capture_start), .page_map(page_map),
        .a0(model_a0), .a19(model_a19), .a18_ube(model_a18_ube),
        .mux_address(model_mux_address), .data_out(model_data_out),
        .mreq_n(model_mreq_n), .mstb_n(model_mstb_n), .iostb_n(model_iostb_n),
        .read_write(model_read_write), .refrq_n(model_refrq_n),
        .data_in(model_lane_data_in), .data_drive(model_data_drive), .ready(), .ready_out(model_lane_ready),
        .result(model_result), .overflow(model_overflow),
        .marker_valid(model_marker_valid), .marker_data(model_marker_data),
        .trace_count(model_trace_count), .total_count(model_total),
        .signature(model_signature), .lane_state(model_lane_state),
        .host_address(saved_address[15:0]), .host_write(memory_write),
        .host_data(saved_data), .host_read_data(model_host_data),
        .trace_address(saved_address[14:1]), .trace_data(model_trace_data),
        .event_valid(model_event_valid), .event_data(model_event_data),
        .pins(model_pins), .pin_mask(pin_record_mask & observable(model_port_mode))
    );

    v35s_lane socket_lane (
        .clock(clock), .clear(clear_lanes), .running(executing && mode[1]),
        .timestamp(run_ticks), .ready_ticks(ready_ticks),
        .ready_m_delay(ready_m_delay), .ready_m_hold(ready_m_hold),
        .ready_m_blocks(ready_m_blocks),
        .capture_start(capture_start), .page_map(page_map),
        .a0(socket_a0), .a19(socket_a19), .a18_ube(socket_a18_ube),
        .mux_address(socket_mux_address), .data_out(socket_data_out),
        .mreq_n(socket_mreq_n), .mstb_n(socket_mstb_n), .iostb_n(socket_iostb_n),
        .read_write(socket_read_write), .refrq_n(socket_refrq_n),
        .data_in(socket_lane_data_in), .data_drive(socket_data_drive), .ready(), .ready_out(socket_lane_ready),
        .result(socket_result), .overflow(socket_overflow),
        .marker_valid(socket_marker_valid), .marker_data(socket_marker_data),
        .trace_count(socket_trace_count), .total_count(socket_total),
        .signature(socket_signature), .lane_state(socket_lane_state),
        .host_address(saved_address[15:0]), .host_write(memory_write),
        .host_data(saved_data), .host_read_data(socket_host_data),
        .trace_address(saved_address[14:1]), .trace_data(socket_trace_data),
        .event_valid(socket_event_valid), .event_data(socket_event_data),
        .pins(socket_pins), .pin_mask(pin_record_mask & observable(port_mode))
    );

    // ------------------------------------------------------------ stimulus
    wire stim_write = debug_stage == 2'd1 && saved_write &&
                      saved_address[19:16] == 4'h6 && saved_address[15:10] == 0 && !busy;
    wire [15:0] socket_stim_host_data, model_stim_host_data;
    wire [15:0] socket_stim_status, model_stim_status;
    wire [7:0] socket_events, model_events, socket_unmatched, model_unmatched;
    wire [7:0] socket_last_event, model_last_event;

    v35s_stim socket_stim (
        .clock(clock), .clear(clear_lanes), .running(executing && mode[1]),
        .base_levels(base_levels),
        .host_word(saved_address[9:1]), .host_write(stim_write),
        .host_data(saved_data), .host_read_data(socket_stim_host_data),
        .entry_count(entry_count), .bit_time0(bit_time0), .bit_time1(bit_time1),
        .length0(length0), .length1(length1), .intak_enable(intak_enable),
        .int_release(int_release), .vector(intak_vector),
        .event_valid(socket_event_valid), .event_number(socket_event_data),
        .intak_n(socket_r2[1]), .intak_observable(port_mode[3:2] == 2'd2),
        .levels(socket_levels), .vector_drive(socket_stim_vector_drive),
        .status(socket_stim_status), .event_count(socket_events),
        .unmatched_count(socket_unmatched), .last_event(socket_last_event)
    );

    v35s_stim model_stim (
        .clock(clock), .clear(clear_lanes), .running(executing && mode[0]),
        .base_levels(base_levels),
        .host_word(saved_address[9:1]), .host_write(stim_write),
        .host_data(saved_data), .host_read_data(model_stim_host_data),
        .entry_count(entry_count), .bit_time0(bit_time0), .bit_time1(bit_time1),
        .length0(length0), .length1(length1), .intak_enable(intak_enable),
        .int_release(int_release), .vector(intak_vector),
        .event_valid(model_event_valid), .event_number(model_event_data),
        .intak_n(model_intak_n), .intak_observable(model_port_mode[3:2] == 2'd2),
        .levels(model_levels), .vector_drive(model_vector_drive),
        .status(model_stim_status), .event_count(model_events),
        .unmatched_count(model_unmatched), .last_event(model_last_event)
    );

    assign input_levels = socket_levels;
    assign socket_vector_drive = socket_stim_vector_drive;
    assign socket_data_in = socket_stim_vector_drive ?
        {socket_lane_data_in[15:8], intak_vector} : socket_lane_data_in;

    wire [15:0] status = {
        7'd0, state == 2'd1 && cold_wait, timed_out,
        model_overflow || socket_overflow,
        socket_result, model_result, complete, busy
    };
    wire lanes_finished = (!mode[0] || model_result != 0) &&
                          (!mode[1] || socket_result != 0);
    // Bank modes 3 are reserved and treated as disabled.
    function [7:0] legal_modes;
        input [7:0] value;
        integer index;
        begin
            for (index = 0; index < 4; index = index + 1)
                legal_modes[index * 2 +: 2] =
                    value[index * 2 +: 2] == 2'd3 ? 2'd1 : value[index * 2 +: 2];
        end
    endfunction

    always @(posedge clock) begin
        clear_lanes <= 1'b0;
`ifdef V35S_CORE_V35
        model_tt_we <= 1'b0;
`endif
        debug_ready <= 1'b0;
        debug_error <= 1'b0;
        if (!debug_valid)
            debug_accept <= 1'b1;

        // Port handoff: the program announces each bank transition with an
        // OUT to the marker port, because internal SFR writes never reach the
        // bus. Only the socket lane's markers move physical banks.
        if (socket_marker_valid && executing) begin
            port_mode <= legal_modes(socket_marker_data[7:0]);
            last_marker <= socket_marker_data;
            socket_markers <= socket_markers + 1'b1;
        end
        if (model_marker_valid && executing) begin
            model_markers <= model_markers + 1'b1;
            model_port_mode <= legal_modes(model_marker_data[7:0]);
        end

        if (state == 2'd1) begin
            if (reset_done) begin
                // Leave reset on an X1 falling edge so both lanes see the
                // same phase relationship on every run.
                if (x_fall) begin
                    run_ticks <= 32'd0;
                    state <= 2'd2;
                end
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
                                    if (busy) begin
                                        state <= 2'd0;
                                        complete <= 1'b1;
                                        run_aborted <= 1'b1;
                                    end
                                end else if (saved_data[1]) begin
                                    if (saved_data[9:8] == 0 ||
                                        (saved_data[8] && !MODEL_PRESENT) ||
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
                                        reset_count <= 32'd0;
                                        port_mode <= start_port_mode;
                                        model_port_mode <= start_port_mode;
                                        socket_markers <= 8'd0;
                                        model_markers <= 8'd0;
                                        state <= 2'd1;
                                    end
                                end else begin
                                    socket_armed <= saved_data[0];
                                    port_mode <= start_port_mode;
                                    complete <= 1'b0;
                                end
                            end
                            8'h08: begin
                                // 16.67 MHz / 2 = 8.33 MHz is the fastest X1;
                                // 16.67 MHz would exceed the uPD70337-8's 16.
                                if (saved_data < 2 || saved_data > 255)
                                    debug_error <= 1'b1;
                                else
                                    x_half <= saved_data[7:0];
                            end
                            8'h0a: begin
                                if (saved_data > 255)
                                    debug_error <= 1'b1;
                                else
                                    ready_ticks <= saved_data[7:0];
                            end
                            8'h0c: run_limit[15:0] <= saved_data;
                            8'h0e: run_limit[31:16] <= saved_data;
                            8'h2a: capture_start[15:0] <= saved_data;
                            8'h2c: capture_start[31:16] <= saved_data;
                            8'h84: reset_ticks[15:0] <= saved_data;
                            8'h86: reset_ticks[31:16] <= saved_data;
                            8'h88: begin
                                start_port_mode <= legal_modes(saved_data[7:0]);
                                port_mode <= legal_modes(saved_data[7:0]);
                                model_port_mode <= legal_modes(saved_data[7:0]);
                            end
                            8'h8c: p0_levels <= saved_data[7:0];
                            8'h8e: base_levels <= saved_data & 16'h3fff;
                            8'hc2: ready_m_delay <= saved_data[13:0];
                            8'hc4: ready_m_hold <= saved_data[11:0];
                            8'hc6: ready_m_blocks <= saved_data[7:0];
                            8'ha0: begin
                                if (saved_data[5:0] > 6'd32)
                                    debug_error <= 1'b1;
                                else begin
                                    entry_count <= saved_data[5:0];
                                    intak_enable <= saved_data[8];
                                    int_release <= saved_data[9];
                                end
                            end
                            8'ha2: intak_vector <= saved_data[7:0];
                            8'ha4: if (saved_data < 2) debug_error <= 1'b1;
                                   else bit_time0 <= saved_data;
                            8'ha6: if (saved_data < 2) debug_error <= 1'b1;
                                   else bit_time1 <= saved_data;
                            8'ha8: if (saved_data > 2048) debug_error <= 1'b1;
                                   else length0 <= saved_data[11:0];
                            8'haa: if (saved_data > 2048) debug_error <= 1'b1;
                                   else length1 <= saved_data[11:0];
                            8'hac: pin_record_mask[15:0] <= saved_data;
                            8'hae: pin_record_mask[31:16] <= saved_data;
`ifdef V35S_CORE_V35
                            8'hc8: begin
                                model_tt_we <= 1'b1;
                                model_tt_a <= saved_data[15:8];
                                model_tt_d <= saved_data[7:0];
                            end
`endif
                            default: begin
                                if (saved_address >= 20'h40 && saved_address < 20'h60)
                                    page_map[saved_address[4:1] * 16 +: 16] <= saved_data;
                                else
                                    debug_error <= 1'b1;
                            end
                        endcase
                    end else begin
                        case (saved_address[7:0])
                            8'h00: debug_read_data <= 16'h7033;
                            8'h02: debug_read_data <= 16'h0003;
                            8'h04: debug_read_data <= {6'd0, mode, 7'd0, socket_armed};
                            8'h06: debug_read_data <= status;
                            8'h08: debug_read_data <= {8'd0, x_half};
                            8'h0a: debug_read_data <= {8'd0, ready_ticks};
                            8'h0c: debug_read_data <= run_limit[15:0];
                            8'h0e: debug_read_data <= run_limit[31:16];
                            8'h10: debug_read_data <= run_ticks[15:0];
                            8'h12: debug_read_data <= run_ticks[31:16];
                            8'h14: debug_read_data <= {4'd0, model_trace_count};
                            8'h16: debug_read_data <= {4'd0, socket_trace_count};
                            8'h18: debug_read_data <= {
                                5'd0, socket_reset_n, x1, socket_refrq_n,
                                socket_iostb_n, socket_mstb_n, socket_mreq_n,
                                socket_read_write, socket_a0, socket_a19,
                                socket_a18_ube, socket_lane_state == 0
                            };
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
                            8'h84: debug_read_data <= reset_ticks[15:0];
                            8'h86: debug_read_data <= reset_ticks[31:16];
                            8'h88: debug_read_data <= {8'd0, start_port_mode};
                            8'h8a: debug_read_data <= {8'd0, port_mode};
                            8'h8c: debug_read_data <= {8'd0, p0_levels};
                            8'h8e: debug_read_data <= base_levels;
                            8'h90: debug_read_data <= {model_markers, socket_markers};
                            8'h92: debug_read_data <= last_marker;
                            8'h94: debug_read_data <= power_ticks[15:0];
                            8'h96: debug_read_data <= power_ticks[31:16];
                            8'h98: debug_read_data <= {8'd0, socket_p0};
                            8'h9a: debug_read_data <= {7'd0, socket_r2, socket_p2_out};
                            8'ha0: debug_read_data <= {6'd0, int_release, intak_enable,
                                                       2'd0, entry_count};
                            8'ha2: debug_read_data <= {8'd0, intak_vector};
                            8'ha4: debug_read_data <= bit_time0;
                            8'ha6: debug_read_data <= bit_time1;
                            8'ha8: debug_read_data <= {4'd0, length0};
                            8'haa: debug_read_data <= {4'd0, length1};
                            8'hac: debug_read_data <= pin_record_mask[15:0];
                            8'hae: debug_read_data <= pin_record_mask[31:16];
                            8'hb0: debug_read_data <= socket_stim_status;
                            8'hb2: debug_read_data <= model_stim_status;
                            8'hb4: debug_read_data <= {model_events, socket_events};
                            8'hb6: debug_read_data <= {model_unmatched, socket_unmatched};
                            8'hb8: debug_read_data <= {model_last_event, socket_last_event};
                            8'hba: debug_read_data <= socket_pins[15:0];
                            8'hbc: debug_read_data <= socket_pins[31:16];
                            8'hbe: debug_read_data <= socket_levels;
                            8'hc0: debug_read_data <= model_levels;
                            8'hc2: debug_read_data <= {2'd0, ready_m_delay};
                            8'hc4: debug_read_data <= {4'd0, ready_m_hold};
                            8'hc6: debug_read_data <= {8'd0, ready_m_blocks};
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
                        4'h6: begin
                            // Writes were taken at stage 1 (stim_write).
                            debug_read_data <= socket_stim_host_data;
                            debug_error <= saved_address[15:10] != 0;
                        end
                        default: debug_error <= 1'b1;
                    endcase
                end
            end
        endcase
    end
endmodule
