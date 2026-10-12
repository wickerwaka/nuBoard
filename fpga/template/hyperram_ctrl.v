`timescale 1ns/1ps

// Fixed-burst HyperBus engine for one x8 HyperRAM, built for sustained
// throughput. Every transfer moves exactly BURST_WORDS words between the
// HyperRAM and one staging buffer:
//
//   write: buffer -> HyperRAM burst      read: HyperRAM burst -> buffer
//
// Commands arrive from a FIFO; each completion is pushed to another FIFO.
// The device keeps its power-up configuration: fixed 2x latency of 6 clocks,
// so data starts 11 clocks after the command-address. After reset the
// controller reads ID0 and ID1 from register space and then raises init_done.
//
// Each transfer is a fixed sequence of clock "slots": slot 0 lowers CS#,
// slots 1-3 carry the command-address, slot 15 is the first data word. The
// FSM's slot outputs pass through two pipeline registers before the I/O
// cells, while ck_en takes a separate path through the PHY; the extra stage
// lines each CK pulse up with the DQ word it must strobe. Every decode that
// steers the FSM is a registered flag, which keeps clk_hr fast.
module hyperram_ctrl #(
    parameter integer HR_MHZ = 100,
    parameter integer BURST_WORDS = 256,
    parameter integer BUFFER_BITS = 2,
    parameter integer LATENCY = 6
) (
    input  wire        clk_hr,
    input  wire        clk_hr_cal,
    input  wire        reset,

    output reg         init_done = 1'b0,
    output reg  [15:0] id0 = 16'd0,
    output reg  [15:0] id1 = 16'd0,

    // Command FIFO (first-word fall-through).
    input  wire                              command_valid,
    output reg                               command_pop = 1'b0,
    input  wire                              command_write,
    input  wire [BUFFER_BITS-1:0]            command_buffer,
    input  wire [21-$clog2(BURST_WORDS):0]   command_burst,

    // Completion FIFO.
    input  wire                              done_full,
    output reg                               done_push = 1'b0,
    output reg                               done_write = 1'b0,
    output reg  [BUFFER_BITS-1:0]            done_buffer = 0,
    output reg  [$clog2(BURST_WORDS):0]      done_short = 0,

    // Staging buffers, HyperRAM side. buffer_read_data is valid two clocks
    // after buffer_read_address.
    output reg  [BUFFER_BITS+$clog2(BURST_WORDS)-1:0] buffer_read_address = 0,
    input  wire [15:0]                                 buffer_read_data,
    output reg                                         buffer_write_enable = 1'b0,
    output reg  [BUFFER_BITS+$clog2(BURST_WORDS)-1:0] buffer_write_address = 0,
    output reg  [15:0]                                 buffer_write_data = 16'd0,

    output reg         hr_reset_n = 1'b1,
    output wire        phy_cs_n,
    output reg         phy_ck_en = 1'b0,
    output wire [7:0]  phy_dq_out_hi,
    output wire [7:0]  phy_dq_out_lo,
    output wire        phy_dq_oe,
    output wire        phy_rwds_out_hi,
    output wire        phy_rwds_out_lo,
    output wire        phy_rwds_oe,
    input  wire [7:0]  phy_dq_in_fall,
    input  wire [7:0]  phy_dq_in_rise,
    input  wire        phy_rwds_in_fall,
    input  wire        phy_rwds_in_rise
);
    localparam integer WORD_BITS = $clog2(BURST_WORDS);

    // Reset and power-up waits count ticks of 16 clocks; per-burst waits
    // count clocks.
    localparam integer RESET_COUNT = HR_MHZ / 16 + 2;          // tRP: 1 us
    localparam integer POWERUP_COUNT = HR_MHZ * 200 / 16 + 2;  // tVCS, tRH
    localparam integer RECOVERY_COUNT =
        (HR_MHZ * 40 + 999) / 1000 + 2;                       // tRWR, tCSHI
    localparam [11:0] RESET_TICKS = RESET_COUNT[11:0];
    localparam [11:0] POWERUP_TICKS = POWERUP_COUNT[11:0];
    localparam [5:0]  RECOVERY_CYCLES = RECOVERY_COUNT[5:0];
    localparam [5:0]  DRAIN_TIMEOUT = 6'd48;

    // Slot numbers. Latency runs from the third command-address clock, so
    // the first data word is on clock 3 + 2 * LATENCY. Reads clock two extra
    // words so the last real word is never cut short by CS# rising; the
    // extras are discarded.
    localparam integer FIRST_DATA = 3 + 2 * LATENCY;
    localparam integer PREFETCH_I = FIRST_DATA - 3;
    localparam integer BEFORE_DATA_I = FIRST_DATA - 1;
    localparam integer LAST_WRITE_I = FIRST_DATA + BURST_WORDS - 1;
    localparam integer LAST_READ_I = FIRST_DATA + BURST_WORDS + 1;
    localparam integer LAST_REGISTER_I = FIRST_DATA + 2;
    localparam integer LAST_WORD_I = BURST_WORDS - 1;
    localparam [9:0] SLOT_CA_LAST = 10'd3;
    localparam [9:0] SLOT_MASK_START = 10'd4;     // writes: RWDS from slot 5
    localparam [9:0] SLOT_CAPTURE_OPEN = 10'd8;
    localparam [9:0] SLOT_PREFETCH = PREFETCH_I[9:0];
    localparam [9:0] SLOT_BEFORE_DATA = BEFORE_DATA_I[9:0];
    localparam [9:0] LAST_WRITE = LAST_WRITE_I[9:0];
    localparam [9:0] LAST_READ = LAST_READ_I[9:0];
    localparam [9:0] LAST_REGISTER_READ = LAST_REGISTER_I[9:0];
    localparam [WORD_BITS:0] BURST_COUNT = BURST_WORDS[WORD_BITS:0];
    localparam [WORD_BITS:0] LAST_WORD = LAST_WORD_I[WORD_BITS:0];

    localparam [2:0] STATE_RESET_LOW = 3'd0;
    localparam [2:0] STATE_POWERUP   = 3'd1;
    localparam [2:0] STATE_IDLE      = 3'd2;
    localparam [2:0] STATE_SLOTS     = 3'd3;
    localparam [2:0] STATE_TAIL      = 3'd4;

    reg [2:0] state = STATE_RESET_LOW;
    reg [9:0] slot = 10'd0;
    reg [9:0] last_slot = 10'd0;

    reg [3:0]  prescale = 4'd0;
    reg        tick = 1'b0;
    reg [11:0] long_timer = RESET_TICKS;
    reg        long_done = 1'b0;
    reg [5:0]  timer = 6'd0;
    reg        timer_done = 1'b0;
    reg [5:0]  drain_timer = 6'd0;
    reg        drain_done = 1'b0;

    reg        is_read = 1'b0;
    reg        is_register = 1'b0;    // start-up ID read: one word
    reg [1:0]  id_step = 2'd0;
    reg [BUFFER_BITS-1:0] buffer = 0;
    reg [47:0] command_address = 48'd0;
    reg        command_seen = 1'b0;   // registered command_valid
    // done_full, registered. A completion pushed as IDLE begins reaches it
    // two clocks later, so a command is accepted only after two IDLE clocks;
    // otherwise a full done queue could drop that command's completion.
    reg        done_full_seen = 1'b0;
    reg [1:0]  idle_clocks = 2'd0;
    wire [21:0] command_word = {command_burst, {WORD_BITS{1'b0}}};

    // Slot decode, registered: each flag describes the current slot.
    reg ck_phase = 1'b0;      // slots 1 to last_slot
    reg ca_phase = 1'b0;      // slots 1 to 3
    reg mask_phase = 1'b0;    // writes: slot 5 onwards, host drives RWDS
    reg data_phase = 1'b0;    // first data slot to last_slot
    reg at_last_slot = 1'b0;

    // Read side.
    reg               capture_enable = 1'b0;
    reg [WORD_BITS:0] received = 0;
    reg               words_pending = 1'b0;

    // Slot outputs, combinational from registered state.
    reg        slot_cs_n;
    reg [15:0] slot_dq;
    reg        slot_dq_oe;
    reg        slot_rwds_oe;
    always @(*) begin
        slot_cs_n = state != STATE_SLOTS;
        slot_dq = 16'd0;
        slot_dq_oe = 1'b0;
        slot_rwds_oe = 1'b0;
        if (state == STATE_SLOTS) begin
            if (ca_phase) begin
                slot_dq_oe = 1'b1;
                case (slot[1:0])
                    2'd1: slot_dq = command_address[47:32];
                    2'd2: slot_dq = command_address[31:16];
                    default: slot_dq = command_address[15:0];
                endcase
            end else if (mask_phase) begin
                // RWDS is the write data mask. The memory drives it during
                // command-address, so take it over one slot later and hold
                // it low (no bytes masked) through latency and data.
                slot_rwds_oe = 1'b1;
                if (data_phase) begin
                    slot_dq_oe = 1'b1;
                    slot_dq = buffer_read_data;
                end
            end
        end
    end

    reg        stage_cs_n = 1'b1;
    reg [15:0] stage_dq = 16'd0;
    reg        stage_dq_oe = 1'b0;
    reg        stage_rwds_oe = 1'b0;
    reg        out_cs_n = 1'b1;
    reg [15:0] out_dq = 16'd0;
    reg        out_dq_oe = 1'b0;
    reg        out_rwds_oe = 1'b0;
    always @(posedge clk_hr) begin
        phy_ck_en <= state == STATE_SLOTS && ck_phase;
        stage_cs_n <= slot_cs_n;
        stage_dq <= slot_dq;
        stage_dq_oe <= slot_dq_oe;
        stage_rwds_oe <= slot_rwds_oe;
        out_cs_n <= stage_cs_n;
        out_dq <= stage_dq;
        out_dq_oe <= stage_dq_oe;
        out_rwds_oe <= stage_rwds_oe;
    end

    // The first byte of each HyperBus word is bits 15:8.
    assign phy_cs_n = out_cs_n;
    assign phy_dq_out_hi = out_dq[15:8];
    assign phy_dq_out_lo = out_dq[7:0];
    assign phy_dq_oe = out_dq_oe;
    assign phy_rwds_out_hi = 1'b0;
    assign phy_rwds_out_lo = 1'b0;
    assign phy_rwds_oe = out_rwds_oe;

    // Read capture on clk_hr_cal. RWDS is high for the first byte of each
    // word and low for the second. Depending on the capture phase a word
    // either lands in one cycle (falling sample first) or straddles two
    // (previous rising sample, then this falling sample).
    (* async_reg = "true" *) reg capture_sync_1 = 1'b0;
    (* async_reg = "true" *) reg capture_sync_2 = 1'b0;
    reg [7:0]  previous_dq_rise = 8'd0;
    reg        previous_rwds_rise = 1'b0;
    reg        capture_push = 1'b0;
    reg [15:0] capture_word = 16'd0;
    always @(posedge clk_hr_cal) begin
        capture_sync_1 <= capture_enable;
        capture_sync_2 <= capture_sync_1;
        previous_dq_rise <= phy_dq_in_rise;
        previous_rwds_rise <= phy_rwds_in_rise;
        capture_push <= 1'b0;
        if (capture_sync_2) begin
            if (phy_rwds_in_fall && !phy_rwds_in_rise) begin
                capture_push <= 1'b1;
                capture_word <= {phy_dq_in_fall, phy_dq_in_rise};
            end else if (previous_rwds_rise && !phy_rwds_in_fall) begin
                capture_push <= 1'b1;
                capture_word <= {previous_dq_rise, phy_dq_in_fall};
            end
        end
    end

    // The capture FIFO pops every cycle it holds a word, so stray words
    // from an earlier burst drain away while capture is closed.
    wire [15:0] fifo_data;
    wire fifo_empty;
    hyperram_fifo capture_fifo (
        .write_clock(clk_hr_cal),
        .write_enable(capture_push),
        .write_data(capture_word),
        .full(),
        .read_clock(clk_hr),
        .read_enable(1'b1),
        .read_data(fifo_data),
        .empty(fifo_empty)
    );

    reg        fifo_word_valid = 1'b0;
    reg [15:0] fifo_word = 16'd0;
    always @(posedge clk_hr) begin
        fifo_word_valid <= !fifo_empty;
        fifo_word <= fifo_data;
    end

    always @(posedge clk_hr) begin
        command_pop <= 1'b0;
        done_push <= 1'b0;
        buffer_write_enable <= 1'b0;
        command_seen <= command_valid;
        done_full_seen <= done_full;
        idle_clocks <= state != STATE_IDLE ? 2'd0 :
                       idle_clocks == 2'd2 ? 2'd2 : idle_clocks + 1'b1;
        // Completion fields are free-running; only done_push is conditional.
        done_write <= !is_read;
        done_buffer <= buffer;
        done_short <= is_read ? BURST_COUNT - received : {(WORD_BITS+1){1'b0}};

        // Captured words go to the buffer (or the ID registers) in order.
        if (capture_enable && fifo_word_valid && words_pending) begin
            if (is_register) begin
                if (id_step[0])
                    id1 <= fifo_word;
                else
                    id0 <= fifo_word;
            end else begin
                buffer_write_enable <= 1'b1;
                buffer_write_address <= {buffer, received[WORD_BITS-1:0]};
                buffer_write_data <= fifo_word;
            end
            received <= received + 1'b1;
            words_pending <= !is_register && received != LAST_WORD;
        end

        // Write data prefetch: address k is presented two slots before the
        // data slot that sends word k.
        if (state == STATE_SLOTS && slot == SLOT_PREFETCH)
            buffer_read_address <= {buffer, {WORD_BITS{1'b0}}};
        else
            buffer_read_address[WORD_BITS-1:0] <=
                buffer_read_address[WORD_BITS-1:0] + 1'b1;

        if (timer != 6'd0)
            timer <= timer - 1'b1;
        timer_done <= timer == 6'd0;
        if (drain_timer != 6'd0)
            drain_timer <= drain_timer - 1'b1;
        drain_done <= drain_timer == 6'd0;
        prescale <= prescale + 1'b1;
        tick <= prescale == 4'd15;
        // The long timer free-runs; only the reset and power-up states look
        // at long_done, and they leave as soon as it is set.
        if (tick)
            long_timer <= long_timer - 1'b1;
        long_done <= long_timer == 12'd0;

        if (reset) begin
            state <= STATE_RESET_LOW;
            long_timer <= RESET_TICKS;
            long_done <= 1'b0;
            init_done <= 1'b0;
            id_step <= 2'd0;
            hr_reset_n <= 1'b1;
            capture_enable <= 1'b0;
            words_pending <= 1'b0;
        end else begin
            case (state)
                STATE_RESET_LOW: begin
                    hr_reset_n <= 1'b0;
                    if (long_done) begin
                        hr_reset_n <= 1'b1;
                        long_timer <= POWERUP_TICKS;
                        long_done <= 1'b0;
                        state <= STATE_POWERUP;
                    end
                end
                STATE_POWERUP: begin
                    if (long_done)
                        state <= STATE_IDLE;
                end
                STATE_IDLE: begin
                    slot <= 10'd0;
                    ck_phase <= 1'b0;
                    ca_phase <= 1'b0;
                    mask_phase <= 1'b0;
                    data_phase <= 1'b0;
                    at_last_slot <= 1'b0;
                    received <= 0;
                    if (id_step != 2'd2) begin
                        // Start-up ID read. Register space does not
                        // auto-increment, so each register is one read.
                        is_read <= 1'b1;
                        is_register <= 1'b1;
                        words_pending <= 1'b1;
                        command_address <= {3'b111, 29'd0, 13'd0,
                                            2'd0, id_step[0]};
                        last_slot <= LAST_REGISTER_READ;
                        state <= STATE_SLOTS;
                    end else if (command_seen && idle_clocks == 2'd2 &&
                                 !done_full_seen) begin
                        command_pop <= 1'b1;
                        command_seen <= 1'b0;
                        is_read <= !command_write;
                        is_register <= 1'b0;
                        words_pending <= !command_write;
                        buffer <= command_buffer;
                        command_address <= {
                            !command_write,             // R/W#
                            1'b0,                       // memory space
                            1'b1,                       // linear burst
                            10'd0,
                            command_word[21:3],
                            13'd0,
                            command_word[2:0]
                        };
                        last_slot <= command_write ? LAST_WRITE : LAST_READ;
                        state <= STATE_SLOTS;
                    end
                end
                STATE_SLOTS: begin
                    at_last_slot <= slot + 10'd1 == last_slot;
                    if (slot == 10'd0) begin
                        ck_phase <= 1'b1;
                        ca_phase <= 1'b1;
                    end
                    if (slot == SLOT_CA_LAST)
                        ca_phase <= 1'b0;
                    if (slot == SLOT_MASK_START && !is_read)
                        mask_phase <= 1'b1;
                    if (slot == SLOT_BEFORE_DATA)
                        data_phase <= 1'b1;
                    if (is_read && slot == SLOT_CAPTURE_OPEN)
                        capture_enable <= 1'b1;
                    if (at_last_slot) begin
                        ck_phase <= 1'b0;
                        mask_phase <= 1'b0;
                        data_phase <= 1'b0;
                        timer <= RECOVERY_CYCLES;
                        timer_done <= 1'b0;
                        drain_timer <= DRAIN_TIMEOUT;
                        drain_done <= 1'b0;
                        if (!is_read)
                            done_push <= 1'b1;  // every word has left the buffer
                        state <= STATE_TAIL;
                    end
                    slot <= slot + 1'b1;
                end
                STATE_TAIL: begin
                    // CS# is high: wait out tRWR and, for reads, the last
                    // captured words (or a timeout if they never come).
                    if (timer_done &&
                        (!is_read || !words_pending || drain_done)) begin
                        capture_enable <= 1'b0;
                        words_pending <= 1'b0;
                        if (is_register) begin
                            id_step <= id_step + 1'b1;
                            if (id_step == 2'd1)
                                init_done <= 1'b1;
                        end else if (is_read) begin
                            done_push <= 1'b1;
                        end
                        state <= STATE_IDLE;
                    end
                end
                default: state <= STATE_RESET_LOW;
            endcase
        end
    end
endmodule
