`timescale 1ns/1ps

// Per-lane stimulus for the V35S harness (one instance beside each lane).
//
// A program announces an event with an OUT to the event port FF12h (low byte
// = event number); the lane passes it here. The host-loaded schedule then
// drives this lane's input levels, so the socket and the model each follow
// their own program's announcements and never each other's clock.
//
// Schedule: up to 32 entries of eight 16-bit words, run in order:
//   w0  [7:0] event (FFh = start as soon as the previous entry has ended),
//       [8] start the RxD0 stream, [9] start the RxD1 stream
//   w1  delay ticks [15:0]     w2 [7:0] delay ticks [23:16]
//   w3  hold ticks [15:0]      w4 [7:0] hold ticks [23:16]
//   w5  mask [12:0]            w6 value [12:0] (input_levels bit order)
//   w7  reserved
// An entry waits for its event, waits `delay` ticks, then sets the masked
// levels to `value` and starts the flagged serial streams. With hold = 0 the
// levels stay set; otherwise after `hold` ticks the masked levels take
// ~value (a pulse). The next entry is fetched in the eight ticks after.
// An event latches until an entry waits for it; one that arrives while
// another is pending, or that the waiting entry does not want, is counted
// as unmatched and dropped.
//
// Serial: each RxD stream shifts a host-loaded pattern (word 0 bit 0 first,
// up to 2,048 bits) at `bit_time` ticks per bit; the host composes start and
// stop bits. While a stream runs it owns its RxD level; afterwards RxD
// returns to the schedule's level.
//
// INTAK: while this lane's /INTAK is low and observable (R2 = D on the
// socket), and answering is enabled, `vector_drive` asks the harness to put
// `vector` on D7..D0. With `int_release`, /INTAK's falling edge also drops
// INT (input_levels bit 5), as an interrupt controller would.
module v35s_stim (
    input  wire         clock,
    input  wire         clear,
    input  wire         running,
    input  wire [15:0]  base_levels,

    // Host access (both lanes' copies are written together).
    input  wire [8:0]   host_word,     // 0-255 schedule, 256-383 RxD0, 384-511 RxD1
    input  wire         host_write,
    input  wire [15:0]  host_data,
    output wire [15:0]  host_read_data,

    input  wire [5:0]   entry_count,
    input  wire [15:0]  bit_time0,
    input  wire [15:0]  bit_time1,
    input  wire [11:0]  length0,
    input  wire [11:0]  length1,
    input  wire         intak_enable,
    input  wire         int_release,
    input  wire [7:0]   vector,

    input  wire         event_valid,
    input  wire [7:0]   event_number,
    input  wire         intak_n,       // the pin, unsynchronised
    input  wire         intak_observable,

    output reg  [15:0]  levels,
    output reg          vector_drive,
    output wire [15:0]  status,
    output reg  [7:0]   event_count,
    output reg  [7:0]   unmatched_count,
    output reg  [7:0]   last_event
);
    initial begin
        levels = 16'h1e1f;
        vector_drive = 1'b0;
        event_count = 8'd0;
        unmatched_count = 8'd0;
        last_event = 8'd0;
    end

    // ------------------------------------------------------------ memories
    (* syn_ramstyle = "block_ram" *) reg [15:0] schedule_ram [0:255];
    (* syn_ramstyle = "block_ram" *) reg [15:0] serial0_ram [0:127];
    (* syn_ramstyle = "block_ram" *) reg [15:0] serial1_ram [0:127];

    localparam [2:0] S_LOAD = 3'd0, S_WAIT = 3'd1, S_DELAY = 3'd2, S_HOLD = 3'd3,
                     S_DONE = 3'd4;
    reg [2:0] state = S_LOAD;
    reg [5:0] pointer = 6'd0;
    reg [3:0] word_count = 4'd0;

    reg [6:0] serial0_index_word = 7'd0;   // address the streams read next
    reg [6:0] serial1_index_word = 7'd0;
    wire [7:0] schedule_address = running ? {pointer[4:0], word_count[2:0]} : host_word[7:0];
    wire [6:0] serial0_address = running ? serial0_index_word : host_word[6:0];
    wire [6:0] serial1_address = running ? serial1_index_word : host_word[6:0];
    reg [15:0] schedule_q = 16'd0;
    reg [15:0] serial0_q = 16'd0;
    reg [15:0] serial1_q = 16'd0;
    reg [1:0] host_select = 2'd0;
    always @(posedge clock) begin
        if (host_write && !running) begin
            if (!host_word[8])
                schedule_ram[host_word[7:0]] <= host_data;
            else if (!host_word[7])
                serial0_ram[host_word[6:0]] <= host_data;
            else
                serial1_ram[host_word[6:0]] <= host_data;
        end
        schedule_q <= schedule_ram[schedule_address];
        serial0_q <= serial0_ram[serial0_address];
        serial1_q <= serial1_ram[serial1_address];
        host_select <= host_word[8:7];
    end
    assign host_read_data = !host_select[1] ? schedule_q :
                            !host_select[0] ? serial0_q : serial1_q;

    // ------------------------------------------------------------ schedule
    reg [7:0] entry_event = 8'd0;
    reg [1:0] entry_serial = 2'd0;
    reg [23:0] entry_delay = 24'd0;
    reg [23:0] entry_hold = 24'd0;
    reg [13:0] entry_mask = 14'd0;      // (version 3) bit 13: READY held low
    reg [13:0] entry_value = 14'd0;
    reg [23:0] count = 24'd0;
    reg pending = 1'b0;
    reg [7:0] pending_event = 8'd0;
    reg [15:0] schedule_levels = 16'h1e1f;
    reg [1:0] start_serial = 2'd0;   // one-tick start requests

    // /INTAK through two flops.
    reg [1:0] intak_sync = 2'b11;
    reg intak_low_last = 1'b0;
    always @(posedge clock)
        intak_sync <= {intak_sync[0], intak_n};
    wire intak_low = intak_observable && !intak_sync[1];

    wire waiting = state == S_WAIT && entry_event != 8'hff && pending;
    wire take = waiting && pending_event == entry_event;
    wire drop = waiting && pending_event != entry_event;

    always @(posedge clock) begin
        start_serial <= 2'd0;
        // A run starts from entry 0; after it the state stays readable.
        if (clear) begin
            event_count <= 8'd0;
            unmatched_count <= 8'd0;
            last_event <= 8'd0;
            state <= S_LOAD;
            pointer <= 6'd0;
            word_count <= 4'd0;
            pending <= 1'b0;
        end
        if (!running) begin
            schedule_levels <= base_levels;
            intak_low_last <= 1'b0;
            vector_drive <= 1'b0;
        end else begin
            vector_drive <= intak_enable && intak_low;
            intak_low_last <= intak_low;

            // The waiting entry takes a latched event it wants and drops one it
            // does not; a new event replaces a latched one nobody took.
            if (event_valid) begin
                event_count <= event_count + 1'b1;
                last_event <= event_number;
                pending <= 1'b1;
                pending_event <= event_number;
                if (pending && !take)
                    unmatched_count <= unmatched_count + 1'b1;
            end else if (take || drop) begin
                pending <= 1'b0;
                if (drop)
                    unmatched_count <= unmatched_count + 1'b1;
            end

            case (state)
                S_LOAD: begin
                    if (pointer >= entry_count || pointer[5]) begin
                        state <= S_DONE;
                    end else begin
                        // Word k's read data arrives one tick after its address.
                        word_count <= word_count + 1'b1;
                        case (word_count)
                            4'd1: begin
                                entry_event <= schedule_q[7:0];
                                entry_serial <= schedule_q[9:8];
                            end
                            4'd2: entry_delay[15:0] <= schedule_q;
                            4'd3: entry_delay[23:16] <= schedule_q[7:0];
                            4'd4: entry_hold[15:0] <= schedule_q;
                            4'd5: entry_hold[23:16] <= schedule_q[7:0];
                            4'd6: entry_mask <= schedule_q[13:0];
                            4'd7: begin
                                entry_value <= schedule_q[13:0];
                                word_count <= 4'd0;
                                state <= S_WAIT;
                            end
                            default: ;
                        endcase
                    end
                end
                S_WAIT: begin
                    count <= entry_delay;
                    if (entry_event == 8'hff || take)
                        state <= S_DELAY;
                end
                S_DELAY: begin
                    if (count != 0) begin
                        count <= count - 1'b1;
                    end else begin
                        schedule_levels[13:0] <= (schedule_levels[13:0] & ~entry_mask) |
                                                 (entry_value & entry_mask);
                        start_serial <= entry_serial;
                        if (entry_hold == 0) begin
                            pointer <= pointer + 1'b1;
                            state <= S_LOAD;
                        end else begin
                            count <= entry_hold - 1'b1;
                            state <= S_HOLD;
                        end
                    end
                end
                S_HOLD: begin
                    if (count != 0) begin
                        count <= count - 1'b1;
                    end else begin
                        schedule_levels[13:0] <= (schedule_levels[13:0] & ~entry_mask) |
                                                 (~entry_value & entry_mask);
                        pointer <= pointer + 1'b1;
                        state <= S_LOAD;
                    end
                end
                default: ;
            endcase

            // An interrupt controller drops INT once the CPU acknowledges.
            if (int_release && intak_low && !intak_low_last)
                schedule_levels[5] <= 1'b0;
        end
    end

    // ------------------------------------------------------------ serial
    reg serial0_active = 1'b0, serial1_active = 1'b0;
    reg [10:0] serial0_bit = 11'd0, serial1_bit = 11'd0;
    reg [15:0] serial0_ticks = 16'd0, serial1_ticks = 16'd0;
    reg [15:0] serial0_word = 16'hffff, serial1_word = 16'hffff;

    always @(posedge clock) begin
        if (!running) begin
            serial0_active <= 1'b0;
            serial1_active <= 1'b0;
            serial0_index_word <= 7'd0;
            serial1_index_word <= 7'd0;
        end else begin
            // While idle the RAM presents word 0; while running, the word after
            // the current one (the bit time is at least two ticks).
            if (start_serial[0] && length0 != 0) begin
                serial0_active <= 1'b1;
                serial0_bit <= 11'd0;
                serial0_ticks <= bit_time0 - 1'b1;
                serial0_word <= serial0_q;
                serial0_index_word <= 7'd1;
            end else if (serial0_active) begin
                if (serial0_ticks != 0) begin
                    serial0_ticks <= serial0_ticks - 1'b1;
                end else begin
                    serial0_ticks <= bit_time0 - 1'b1;
                    serial0_bit <= serial0_bit + 1'b1;
                    if ({1'b0, serial0_bit} + 12'd1 >= length0)
                        serial0_active <= 1'b0;
                    if (serial0_bit[3:0] == 4'hf) begin
                        serial0_word <= serial0_q;
                        serial0_index_word <= serial0_bit[10:4] + 7'd2;
                    end
                end
            end else begin
                serial0_index_word <= 7'd0;
            end

            if (start_serial[1] && length1 != 0) begin
                serial1_active <= 1'b1;
                serial1_bit <= 11'd0;
                serial1_ticks <= bit_time1 - 1'b1;
                serial1_word <= serial1_q;
                serial1_index_word <= 7'd1;
            end else if (serial1_active) begin
                if (serial1_ticks != 0) begin
                    serial1_ticks <= serial1_ticks - 1'b1;
                end else begin
                    serial1_ticks <= bit_time1 - 1'b1;
                    serial1_bit <= serial1_bit + 1'b1;
                    if ({1'b0, serial1_bit} + 12'd1 >= length1)
                        serial1_active <= 1'b0;
                    if (serial1_bit[3:0] == 4'hf) begin
                        serial1_word <= serial1_q;
                        serial1_index_word <= serial1_bit[10:4] + 7'd2;
                    end
                end
            end else begin
                serial1_index_word <= 7'd0;
            end
        end
    end

    // Registered output: RxD0 is bit 9, RxD1 bit 10.
    always @(posedge clock) begin
        levels <= schedule_levels;
        if (serial0_active)
            levels[9] <= serial0_word[serial0_bit[3:0]];
        if (serial1_active)
            levels[10] <= serial1_word[serial1_bit[3:0]];
    end

    assign status = {2'd0, serial1_active, serial0_active, 1'b0, state, 2'd0, pointer};
endmodule
