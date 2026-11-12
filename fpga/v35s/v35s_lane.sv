`timescale 1ns/1ps

// One independently writable memory image and bus trace per CPU. Both the
// socket V35S and the model core go through this responder, including its
// two-flop input pipeline, so their traces are directly comparable.
//
// The V35 bus is not address/data multiplexed. Nine address pins carry
// A9..A17 while MREQ is asserted (row) and A1..A9 once MSTB or IOSTB is
// asserted (column). A0 and A19 have dedicated pins; A18 shares a pin with
// /UBE and is valid in the row phase, /UBE in the column phase. Refresh
// cycles assert /REFRQ and are recorded but never answered.
module v35s_lane (
    input  wire         clock,
    input  wire         clear,
    input  wire         running,
    input  wire [31:0]  timestamp,
    input  wire [7:0]   ready_ticks,
    input  wire [31:0]  capture_start,
    input  wire [255:0] page_map,

    input  wire         a0,
    input  wire         a19,
    input  wire         a18_ube,
    input  wire [8:0]   mux_address,   // pins A9/A1 .. A17/A9
    input  wire [15:0]  data_out,
    input  wire         mreq_n,
    input  wire         mstb_n,
    input  wire         iostb_n,
    input  wire         read_write,    // high = read
    input  wire         refrq_n,

    output reg  [15:0]  data_in,
    output reg          data_drive,
    output reg          ready,
    output reg  [1:0]   result,
    output reg          overflow,
    output reg          marker_valid,
    output reg  [15:0]  marker_data,
    output reg          event_valid,
    output reg  [7:0]   event_data,
    output reg  [11:0]  trace_count,
    output reg  [31:0]  total_count,
    output reg  [31:0]  signature,
    output wire [2:0]   lane_state,

    input  wire [15:0]  host_address,
    input  wire         host_write,
    input  wire [15:0]  host_data,
    output wire [15:0]  host_read_data,
    input  wire [13:0]  trace_address,
    output reg  [15:0]  trace_data,

    // Output pins recorded on change (flag 9): the raw pins and the mask of
    // pins to record (zero bits are recorded as zero and never trigger).
    input  wire [31:0]  pins,
    input  wire [31:0]  pin_mask
);
    localparam [15:0] PORT_PASS   = 16'hff00;
    localparam [15:0] PORT_FAIL   = 16'hff02;
    localparam [15:0] PORT_MARKER = 16'hff10;
    localparam [15:0] PORT_EVENT  = 16'hff12;

    initial begin
        data_in = 16'd0;
        data_drive = 1'b0;
        ready = 1'b1;
        result = 2'd0;
        overflow = 1'b0;
        marker_valid = 1'b0;
        marker_data = 16'd0;
        event_valid = 1'b0;
        event_data = 8'd0;
        trace_count = 12'd0;
        total_count = 32'd0;
        signature = 32'hffffffff;
    end

    // Strobes and R/W idle high.
    reg [32:0] pins_meta = 33'h1_f000_0000;
    reg [32:0] pins_sync = 33'h1_f000_0000;
    always @(posedge clock) begin
        pins_meta <= {mreq_n, mstb_n, iostb_n, refrq_n, read_write,
                      a0, a19, a18_ube, mux_address, data_out};
        pins_sync <= pins_meta;
    end
    wire s_mreq_n   = pins_sync[32];
    wire s_mstb_n   = pins_sync[31];
    wire s_iostb_n  = pins_sync[30];
    wire s_refrq_n  = pins_sync[29];
    wire s_read     = pins_sync[28];
    wire s_a0       = pins_sync[27];
    wire s_a19      = pins_sync[26];
    wire s_a18_ube  = pins_sync[25];
    wire [8:0] s_mux = pins_sync[24:16];
    wire [15:0] s_data = pins_sync[15:0];
    wire strobe = !s_mstb_n || !s_iostb_n;
    wire any_active = !s_mreq_n || !s_refrq_n || strobe;

    reg [2:0] state = 3'd0;
    assign lane_state = state;
    reg bus_qualified = 1'b0;
    reg idle_sample_seen = 1'b0;
    reg [31:0] start_time = 32'd0;
    reg [15:0] strobe_offset = 16'd0;
    reg [8:0] row = 9'd0;
    reg row_a18 = 1'b0;
    reg row_a0 = 1'b0;
    reg row_a19 = 1'b0;
    reg row_refresh = 1'b0;
    reg strobe_seen = 1'b0;
    reg cycle_io = 1'b0;
    reg cycle_read = 1'b0;
    reg cycle_ube_n = 1'b1;
    reg col_mux8 = 1'b0;
    reg [19:0] cycle_address = 20'd0;
    reg cycle_mapped = 1'b0;
    reg [15:0] cycle_data = 16'd0;
    reg [7:0] ready_count = 8'd0;

    wire [19:0] column_address = {
        row_a19, row_a18, row[8:0], s_mux[7:0], row_a0
    };

    reg mapped;
    reg [3:0] page;
    integer page_index;
    always @* begin
        mapped = 1'b0;
        page = 4'd0;
        for (page_index = 0; page_index < 16; page_index = page_index + 1) begin
            if (page_map[page_index * 16 + 15] &&
                page_map[page_index * 16 +: 8] == column_address[19:12]) begin
                mapped = 1'b1;
                page = page_index[3:0];
            end
        end
    end

    reg [14:0] bus_word = 15'd0;
    reg [15:0] write_data = 16'd0;
    reg write_high = 1'b0;
    reg write_low = 1'b0;
    wire [14:0] memory_address = running ? bus_word : host_address[15:1];
    wire [15:0] memory_write_data = running ? write_data : host_data;
    wire memory_write_high = running ? write_high : host_write;
    wire memory_write_low = running ? write_low : host_write;

    (* syn_ramstyle = "block_ram" *) reg [7:0] memory_high [0:32767];
    (* syn_ramstyle = "block_ram" *) reg [7:0] memory_low [0:32767];
    reg [7:0] read_high;
    reg [7:0] read_low;
    always @(posedge clock) begin
        if (memory_write_high)
            memory_high[memory_address] <= memory_write_data[15:8];
        if (memory_write_low)
            memory_low[memory_address] <= memory_write_data[7:0];
        read_high <= memory_high[memory_address];
        read_low <= memory_low[memory_address];
    end
    assign host_read_data = {read_high, read_low};

    // A complete-run fingerprint detects nondeterministic window replays.
    // Exact comparisons still use the records, never the fingerprint alone.
    function [31:0] fold_transaction;
        input [31:0] crc;
        input [47:0] record;
        reg [31:0] value;
        integer bit_index;
        begin
            value = crc;
            for (bit_index = 0; bit_index < 48; bit_index = bit_index + 1)
                value = (value >> 1) ^ ((value[0] ^ record[bit_index])
                    ? 32'h82f63b78 : 32'd0);
            fold_transaction = value;
        end
    endfunction

    // Flags: 0 read, 1 I/O, 2 refresh, 3 /UBE, 4 unmapped, 5 marker port,
    // 6 A17/A9 pin in the column phase, 7 strobe seen, 8 event port,
    // 9 pin record (written by the pin recorder below, never by a cycle).
    wire [11:0] cycle_flags = {
        3'd0, cycle_io && !cycle_read && cycle_address[15:0] == PORT_EVENT,
        strobe_seen, col_mux8,
        cycle_io && !cycle_read && cycle_address[15:0] == PORT_MARKER,
        strobe_seen && !cycle_io && !cycle_mapped,
        cycle_ube_n, row_refresh, cycle_io, cycle_read
    };
    wire byte_low = !row_a0;
    wire byte_high = !cycle_ube_n;
    wire [15:0] normalized_data = (strobe_seen && !row_refresh)
        ? cycle_data & {{8{byte_high}}, {8{byte_low}}} : 16'd0;
    // Registered: total_count and trace_count change only in state 6 and are
    // stable for several clocks before the next state 6 reads this.
    reg capture_enabled = 1'b1;
    always @(posedge clock)
        capture_enabled <= total_count >= capture_start && trace_count < 12'd2048;

    // ---------------------------------------------------------- pin recorder
    // A change of the masked, synchronised pins queues {tick, pins}; the queue
    // drains into the trace between bus records. A record is never written in
    // states 2 and 5 (the only states before 6) nor on the tick after any
    // write, so capture_enabled is always current when either write uses it.
    localparam [11:0] PIN_FLAGS = 12'h200;
    reg [31:0] pins_meta_r = 32'd0;
    reg [31:0] pins_sync_r = 32'd0;
    reg [31:0] pins_last = 32'd0;
    always @(posedge clock) begin
        pins_meta_r <= pins;
        pins_sync_r <= pins_meta_r;
    end
    wire [31:0] pins_masked = pins_sync_r & pin_mask;
    reg [63:0] pin_queue [0:7];
    reg [2:0] pin_head = 3'd0;
    reg [2:0] pin_tail = 3'd0;
    reg [3:0] pin_used = 4'd0;
    reg wrote_last = 1'b0;
    wire [63:0] pin_head_entry = pin_queue[pin_head];
    wire [31:0] pin_head_tick = pin_head_entry[63:32];
    wire [31:0] pin_head_value = pin_head_entry[31:0];
    wire pin_change = running && pins_masked != pins_last;
    wire pin_pop = running && pin_used != 0 && !wrote_last &&
                   state != 3'd2 && state != 3'd5 && state != 3'd6;
    always @(posedge clock) begin
        pins_last <= pins_masked;
        if (pin_change && pin_used != 4'd8)
            pin_queue[pin_tail] <= {timestamp, pins_masked};
    end

    (* syn_ramstyle = "block_ram" *) reg [127:0] trace_memory [0:2047];
    reg [127:0] trace_read;
    reg [2:0] trace_half;
    always @(posedge clock) begin
        trace_read <= trace_memory[trace_address[13:3]];
        trace_half <= trace_address[2:0];
        trace_data <= trace_read[trace_half * 16 +: 16];
        if (running && state == 3'd6 && capture_enabled)
            trace_memory[trace_count[10:0]] <= {
                timestamp, strobe_offset, normalized_data,
                cycle_flags, cycle_address, start_time
            };
        else if (pin_pop && capture_enabled)
            trace_memory[trace_count[10:0]] <= {
                pin_head_tick, 16'd0, pin_head_value[31:16],
                PIN_FLAGS, 4'd0, pin_head_value[15:0], pin_head_tick
            };
    end

    always @(posedge clock) begin
        write_high <= 1'b0;
        write_low <= 1'b0;
        marker_valid <= 1'b0;
        event_valid <= 1'b0;
        wrote_last <= (running && state == 3'd6) || pin_pop;
        if (!running || clear) begin
            pin_head <= 3'd0;
            pin_tail <= 3'd0;
            pin_used <= 4'd0;
        end else begin
            if (pin_change && pin_used != 4'd8)
                pin_tail <= pin_tail + 1'b1;
            if (pin_pop)
                pin_head <= pin_head + 1'b1;
            pin_used <= pin_used + {3'd0, pin_change && pin_used != 4'd8} - {3'd0, pin_pop};
            if (pin_change && pin_used == 4'd8) begin
                // A full queue loses a change: fail the run visibly.
                overflow <= 1'b1;
                result <= 2'd3;
            end
            if (pin_pop) begin
                if (total_count == 32'hffffffff) begin
                    overflow <= 1'b1;
                    result <= 2'd3;
                end
                total_count <= total_count + 1'b1;
                signature <= fold_transaction(signature, {
                    PIN_FLAGS, pin_head_value[31:16], 4'd0, pin_head_value[15:0]
                });
                if (capture_enabled)
                    trace_count <= trace_count + 1'b1;
            end
        end

        if (clear) begin
            state <= 3'd0;
            bus_qualified <= 1'b0;
            idle_sample_seen <= 1'b0;
            data_drive <= 1'b0;
            ready <= 1'b1;
            result <= 2'd0;
            trace_count <= 12'd0;
            total_count <= 32'd0;
            signature <= 32'hffffffff;
            overflow <= 1'b0;
        end else if (!running) begin
            state <= 3'd0;
            bus_qualified <= 1'b0;
            idle_sample_seen <= 1'b0;
            data_drive <= 1'b0;
            ready <= 1'b1;
        end else begin
            // Reset can leave strobes undefined. Two idle samples establish
            // the start of a real bus sequence before anything is answered.
            if (!bus_qualified) begin
                if (!any_active) begin
                    idle_sample_seen <= 1'b1;
                    bus_qualified <= idle_sample_seen;
                end else begin
                    idle_sample_seen <= 1'b0;
                end
            end
            // Ticks from the start of the cycle to the first strobe sample.
            if ((state == 3'd1 || state == 3'd2) && strobe_offset != 16'hffff)
                strobe_offset <= strobe_offset + 1'b1;

            case (state)
                3'd0: begin
                    if (bus_qualified && any_active && result == 0) begin
                        start_time <= timestamp;
                        strobe_offset <= 16'd0;
                        strobe_seen <= 1'b0;
                        cycle_data <= 16'd0;
                        cycle_io <= 1'b0;
                        cycle_read <= 1'b1;
                        cycle_ube_n <= 1'b1;
                        col_mux8 <= 1'b0;
                        cycle_mapped <= 1'b0;
                        state <= 3'd1;
                    end
                end
                3'd1: begin
                    // Row phase: one tick after the cycle starts, so every
                    // translator path has settled into the sampled register.
                    row <= s_mux;
                    row_a18 <= s_a18_ube;
                    row_a0 <= s_a0;
                    row_a19 <= s_a19;
                    row_refresh <= !s_refrq_n;
                    cycle_address <= {s_a19, s_a18_ube, s_mux, 8'd0, s_a0};
                    state <= 3'd2;
                end
                3'd2: begin
                    if (strobe) begin
                        state <= 3'd3;
                    end else if (!any_active) begin
                        state <= 3'd6;
                    end
                end
                3'd3: begin
                    // Column phase, one tick after the strobe is seen.
                    strobe_seen <= 1'b1;
                    cycle_io <= !s_iostb_n;
                    cycle_read <= s_read;
                    cycle_ube_n <= s_a18_ube;
                    col_mux8 <= s_mux[8];
                    cycle_address <= column_address;
                    cycle_mapped <= !row_refresh && !s_mstb_n && mapped;
                    bus_word <= {page, column_address[11:1]};
                    ready_count <= ready_ticks;
                    ready <= ready_ticks == 0;
                    state <= 3'd4;
                end
                3'd4: begin
                    // The memory address was registered last tick; the block
                    // RAM returns data on the next edge.
                    state <= 3'd5;
                end
                3'd5: begin
                    if (ready_count != 0)
                        ready_count <= ready_count - 1'b1;
                    else
                        ready <= 1'b1;
                    if (cycle_read && !row_refresh) begin
                        if (!data_drive) begin
                            data_in <= cycle_mapped ? host_read_data : 16'd0;
                            cycle_data <= cycle_mapped ? host_read_data : 16'd0;
                        end
                        data_drive <= strobe;
                    end else if (strobe) begin
                        // Write data is valid while the strobe is low. Keep
                        // the last sample taken before the strobe rises.
                        cycle_data <= s_data;
                    end
                    if (!strobe) begin
                        data_drive <= 1'b0;
                        ready <= 1'b1;
                        state <= 3'd6;
                    end
                end
                3'd6: begin
                    if (total_count == 32'hffffffff) begin
                        overflow <= 1'b1;
                        result <= 2'd3;
                    end
                    total_count <= total_count + 1'b1;
                    signature <= fold_transaction(signature, {
                        cycle_flags, normalized_data, cycle_address
                    });
                    if (capture_enabled)
                        trace_count <= trace_count + 1'b1;
                    if (strobe_seen && !cycle_read && cycle_mapped) begin
                        write_data <= cycle_data;
                        write_high <= byte_high;
                        write_low <= byte_low;
                    end
                    if (strobe_seen && !cycle_read && cycle_io) begin
                        if (cycle_address[15:0] == PORT_PASS)
                            result <= 2'd1;
                        if (cycle_address[15:0] == PORT_FAIL)
                            result <= 2'd2;
                        if (cycle_address[15:0] == PORT_MARKER) begin
                            marker_valid <= 1'b1;
                            marker_data <= cycle_data;
                        end
                        if (cycle_address[15:0] == PORT_EVENT) begin
                            event_valid <= 1'b1;
                            event_data <= cycle_data[7:0];
                        end
                    end
                    state <= 3'd7;
                end
                3'd7: begin
                    if (!any_active)
                        state <= 3'd0;
                end
            endcase
        end
    end
endmodule
