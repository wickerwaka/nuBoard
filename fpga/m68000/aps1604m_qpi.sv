`timescale 1ns/1ps

// APS1604M-3SQR transaction engine. Requests describe a prefilled burst; there
// is no mid-command flow control because CE must periodically release refresh.
// The word source has four SCLK periods to respond to write_word_index.
module aps1604m_qpi #(
    parameter integer POWER_UP_US = 200
) (
    input  wire        clock,
    input  wire        locked,
    input  wire        request,
    input  wire        request_write,
    input  wire [20:0] request_address,
    input  wire [7:0]  request_length,
    output wire        ready,
    output reg         done,
    output reg         initialized,
    output reg         fault,
    output reg  [63:0] identity,
    output reg  [3:0]  write_word_index,
    input  wire [63:0] write_word,
    output reg         read_valid,
    output reg  [6:0]  read_index,
    output reg  [7:0]  read_byte,
    output wire        ce_n,
    output wire        sclk,
    output wire [3:0]  dq_out,
    output wire [3:0]  dq_enable,
    input  wire [3:0]  dq_in
);
    localparam [3:0] WAIT_BOOT = 0, IDLE = 1, HEADER = 2, DUMMY = 3,
                     WRITE_DATA = 4, READ_DATA = 5, HOLD = 6, GAP = 7,
                     CHECK_REQUEST = 8;
    reg [3:0] state = WAIT_BOOT;
    // Speed 0: 100 MHz writes; 1: 50 MHz quad reads; 2: 25 MHz SPI ID.
    // A logical falling edge advances the serializer. The pad stage follows
    // one engine cycle later, keeping data and the falling clock edge aligned.
    reg [1:0] speed = 0;
    reg [2:0] beat = 0;
    reg [2:0] last_beat = 0;
    (* syn_keep = "true" *) reg falling_step = 1'b1;
    reg clock_enable = 1'b0;
    reg chip_enable_n = 1'b1;
    // Power-up needs a long count; inter-command delays need only three bits.
    // Sharing one wide counter put a 16-bit zero comparator on every finish
    // handshake, even though those intervals never exceed five SCLK steps.
    reg [$clog2(POWER_UP_US * 100 + 1)-1:0] boot_wait = 0;
    reg [2:0] wait_count = 0;
    reg [2:0] boot_command = 0;
    reg [39:0] header_shift;
    reg [5:0] header_remaining;
    reg [63:0] data_shift;
    reg [8:0] nibble_index;
    reg [8:0] nibble_length;
    reg final_data_unit = 0;
    reg [3:0] high_nibble;
    reg [3:0] dummy_remaining;
    reg quad_command;
    reg reading;
    reg writing;
    reg boot_transaction;
    reg [3:0] data_output = 0;
    reg [3:0] data_enable = 0;
    reg clock_pin_enable = 0;
    reg clock_level = 0;
    reg read_pending = 0;
    reg read_sampled = 0;
    reg read_delivered = 0;
    reg [8:0] pending_index = 0;
    reg [8:0] sampled_index = 0;
    reg [8:0] delivered_index = 0;
    (* syn_keep = "true" *) reg [3:0] delivered_data = 0;
    (* syn_keep = "true" *) reg invalid_request = 0;
    wire [3:0] sampled_data;
    wire [2:0] next_beat = falling_step ? 3'd0 : beat + 1'b1;
    wire [1:0] requested_speed = initialized ? (request_write ? 0 : 1) :
        (boot_command == 2 || boot_command == 3 ? 2 : 0);
    wire [2:0] requested_last_beat =
        requested_speed == 0 ? 3'd0 : requested_speed == 1 ? 3'd1 : 3'd3;
    wire high_half = speed == 1 ? next_beat[0] : next_beat[1];
    wire pin_enable = clock_enable && locked && !fault;
    wire serial_identity = boot_transaction && (boot_command == 2 || boot_command == 3);
    wire [63:0] serial_word = {
        write_word[7:0], write_word[15:8], write_word[23:16], write_word[31:24],
        write_word[39:32], write_word[47:40], write_word[55:48], write_word[63:56]
    };

    assign ready = initialized && !fault && state == IDLE;

    // Use explicit initial statements for output variables: Efinity rejects
    // SystemVerilog port-declaration initializers. Internal declarations are
    // supported. These defaults keep the memory deselected during startup.
    initial begin
        done = 0;
        initialized = 0;
        fault = 0;
        identity = 0;
        write_word_index = 0;
        read_valid = 0;
        read_index = 0;
        read_byte = 0;
    end

    // Hardware data/enable/CE registers are instantiated at the top-level
    // pads. Model that same single-cycle stage here for the standalone tests.
    // ALL outgoing signals, including SCLK, receive the same pipeline delay.
`ifdef VERILATOR
    reg [3:0] pin_data = 0;
    reg [3:0] pin_enable_data = 0;
    reg pin_select_n = 1;
    reg [3:0] pin_input = 0;
    always @(posedge clock) begin
        pin_data <= data_output;
        pin_enable_data <= data_enable;
        pin_select_n <= chip_enable_n;
        pin_input <= dq_in;
    end
    assign dq_out = pin_data;
    assign dq_enable = pin_enable_data;
    assign ce_n = pin_select_n;
    assign sampled_data = pin_input;
`else
    assign dq_out = data_output;
    assign dq_enable = data_enable;
    assign ce_n = chip_enable_n;
    assign sampled_data = dq_in;
`endif
    always @(posedge clock) begin
        // Select before the register, not on the half-cycle path from this
        // register to the DDR pad. Slow clocks repeat the preceding HI level.
        clock_pin_enable <= speed == 0 ? pin_enable : clock_level;
        clock_level <= pin_enable && high_half;
    end

    generate
        begin : ddr_phy
`ifndef VERILATOR
            // Writes use both output edges. Slower reads hold the same level
            // through both half-cycles, yielding a true 50% duty cycle.
            EFX_ODDIO #(.IS_CLK_INVERTED(0), .MODE("DDIO")) clock_output (
                .CLK(clock), .I_HI(clock_level),
                .I_LO(clock_pin_enable), .O(sclk)
            );
`else
            reg pin_clock = 1'b0;
            always @(posedge clock)
                pin_clock <= clock_level;
            always @(negedge clock)
                pin_clock <= clock_pin_enable;
            assign sclk = pin_clock;
`endif
        end
    endgenerate

    always @(posedge clock) begin
        beat <= next_beat;
        // Look ahead one cycle; a rate decoder must not sit on every wide
        // serializer register's clock-enable path.
        falling_step <= next_beat == last_beat;
        done <= 1'b0;
        read_valid <= 1'b0;
        read_pending <= falling_step && state == READ_DATA && locked && !fault;
        pending_index <= nibble_index;
        // The first delay matches the outgoing pad stage; the second matches
        // the input pad register. Never spend the 20 ns return budget routing
        // an unregistered pad signal across the FPGA fabric.
        read_sampled <= read_pending;
        sampled_index <= pending_index;
        // A fabric input stage separates the pad-to-core route from the
        // byte assembler's placement and fanout. Keep its time tag alongside.
        delivered_data <= sampled_data;
        read_delivered <= read_sampled;
        delivered_index <= sampled_index;
        invalid_request <= request_length == 0 ||
            request_length > (request_write ? 128 : 64) ||
            {1'b0, request_address[8:0]} + request_length > 512;
        if (read_delivered && locked && !fault) begin
            if (serial_identity) begin
                identity <= {identity[62:0], delivered_data[1]};
            end else if (!delivered_index[0]) begin
                high_nibble <= delivered_data;
            end else begin
                read_byte <= {high_nibble, delivered_data};
                read_index <= delivered_index[7:1];
                read_valid <= !boot_transaction;
            end
        end

        if (!locked) begin
            clock_enable <= 1'b0;
            chip_enable_n <= 1'b1;
            data_output <= 4'd0;
            data_enable <= 0;
            initialized <= 1'b0;
            state <= WAIT_BOOT;
            wait_count <= 0;
            boot_wait <= 0;
            boot_command <= 0;
            speed <= 0;
            beat <= 0;
            last_beat <= 0;
            falling_step <= 1'b1;
            // Losing lock after qualification is fatal, not an automatic retry.
            if (initialized)
                fault <= 1'b1;
        end else if (falling_step && !fault) begin
            case (state)
                WAIT_BOOT: begin
                    if (boot_wait == POWER_UP_US * 100 - 1) begin
                        boot_wait <= 0;
                        state <= IDLE;
                    end else begin
                        boot_wait <= boot_wait + 1'b1;
                    end
                end

                IDLE: begin
                    if (!initialized || request)
                        state <= CHECK_REQUEST;
                end

                CHECK_REQUEST: begin
                    // The request fields are stable before this state. The
                    // registered bounds/page check must not cascade into all
                    // of the command launch registers on a single edge.
                    if (initialized && invalid_request) begin
                        fault <= 1'b1;
                    end else begin
                        chip_enable_n <= 1'b0;
                        clock_enable <= 1'b1;
                        // Readback has a longer round-trip through FPGA I/O.
                        // SPI 9F identification is limited to 33 MHz by the
                        // device, so use 25 MHz before entering QPI mode.
                        speed <= requested_speed;
                        beat <= 0;
                        last_beat <= requested_last_beat;
                        falling_step <= requested_last_beat == 0;
                        boot_transaction <= !initialized;
                        quad_command <= initialized || boot_command == 5;
                        reading <= initialized ? !request_write :
                                   (boot_command == 2 || boot_command == 3);
                        writing <= initialized && request_write;
                        data_enable <= initialized || boot_command == 5 ? 4'hf : 4'h1;
                        nibble_index <= 0;
                        // Valid transfers have at least two nibbles (or 64
                        // SPI ID bits). Predict the terminal unit thereafter.
                        final_data_unit <= 0;
                        write_word_index <= 0;
                        nibble_length <= initialized ? {request_length, 1'b0} : 9'd64;
                        header_remaining <= initialized ? 6'd8 :
                                            boot_command == 5 ? 6'd10 :
                                            boot_command == 2 || boot_command == 3 ? 6'd32 : 6'd8;
                        if (initialized) begin
                            header_shift <= {request_write ? 8'h82 : 8'h8b,
                                             3'd0, request_address, 8'd0};
                            data_output <= 4'h8;
                        end else begin
                            // Reset, dummy/qualified SPI ID, QPI entry, MR0.
                            // The dummy 9F satisfies the ID precondition after
                            // reset. Each ID burst stays below 4 us at 25 MHz.
                            case (boot_command)
                                0: begin
                                    header_shift <= 40'h6600000000;
                                    data_output <= 4'd0;
                                end
                                1: begin
                                    header_shift <= 40'h9900000000;
                                    data_output <= 4'd1;
                                end
                                4: begin
                                    header_shift <= 40'h3500000000;
                                    data_output <= 4'd0;
                                end
                                5: begin
                                    header_shift <= 40'hb100000060;
                                    data_output <= 4'hb;
                                end
                                default: begin
                                    header_shift <= 40'h9f00000000;
                                    data_output <= 4'd1;
                                    identity <= 0;
                                end
                            endcase
                        end
                        state <= HEADER;
                    end
                end

                HEADER: begin
                    // Dead after the final header unit and reloaded for the
                    // next command. Avoid gating forty shift-register enables
                    // with the header counter's terminal comparison.
                    if (quad_command)
                        header_shift <= {header_shift[35:0], 4'd0};
                    else
                        header_shift <= {header_shift[38:0], 1'b0};
                    if (header_remaining != 1) begin
                        header_remaining <= header_remaining - 1'b1;
                        if (quad_command) begin
                            data_output <= header_shift[35:32];
                        end else begin
                            data_output <= {3'd0, header_shift[38]};
                        end
                    end else if (reading) begin
                        data_enable <= 0;
                        dummy_remaining <= 6;
                        state <= serial_identity ? READ_DATA : DUMMY;
                    end else if (writing) begin
                        data_shift <= serial_word;
                        data_output <= serial_word[63:60];
                        state <= WRITE_DATA;
                    end else begin
                        clock_enable <= 1'b0;
                        wait_count <= 2;
                        state <= HOLD;
                    end
                end

                DUMMY: begin
                    if (dummy_remaining == 1)
                        state <= READ_DATA;
                    else
                        dummy_remaining <= dummy_remaining - 1'b1;
                end

                WRITE_DATA: begin
                    final_data_unit <= nibble_index + 9'd2 == nibble_length;
                    // The shift register is dead after the final nibble and
                    // is reloaded before the next burst. Advance it even on
                    // that final step so the wide end-of-burst comparison
                    // does not fan out to 64 register enables.
                    if (nibble_index[3:0] == 15)
                        data_shift <= serial_word;
                    else
                        data_shift <= {data_shift[59:0], 4'd0};
                    if (final_data_unit) begin
                        clock_enable <= 1'b0;
                        wait_count <= 2;
                        state <= HOLD;
                    end else begin
                        nibble_index <= nibble_index + 1'b1;
                        if (nibble_index[3:0] == 11)
                            write_word_index <= write_word_index + 1'b1;
                        if (nibble_index[3:0] == 15) begin
                            data_output <= serial_word[63:60];
                        end else begin
                            data_output <= data_shift[59:56];
                        end
                    end
                end

                READ_DATA: begin
                    final_data_unit <= nibble_index + 9'd2 == nibble_length;
                    // Read the previous nibble at the next falling edge, not
                    // the intervening rise. The 20 ns return window includes
                    // the FPGA's outbound clock and inbound pad delays.
                    // The physical output stage adds one engine cycle. The
                    // matching read_pending strobe samples above, not here.
                    nibble_index <= nibble_index + 1'b1;
                    if (final_data_unit) begin
                        clock_enable <= 1'b0;
                        // Two 40 ns steps allow the final SPI bit to settle
                        // without exceeding the memory's 4 us refresh limit.
                        wait_count <= serial_identity ? 1 : 2;
                        state <= HOLD;
                    end
                end

                HOLD: begin
                    if (wait_count == 0) begin
                        chip_enable_n <= 1'b1;
                        data_enable <= 0;
                        // Reset requires 50 ns; use this gap for every command.
                        wait_count <= 5;
                        state <= GAP;
                    end else begin
                        wait_count <= wait_count - 1'b1;
                    end
                end

                GAP: begin
                    if (wait_count != 0) begin
                        wait_count <= wait_count - 1'b1;
                    end else begin
                        if (boot_transaction) begin
                            if (boot_command == 3 && identity[63:48] != 16'h0d5d)
                                fault <= 1'b1;
                            if (boot_command == 5) begin
                                initialized <= identity[63:48] == 16'h0d5d;
                                fault <= identity[63:48] != 16'h0d5d;
                            end else begin
                                boot_command <= boot_command + 1'b1;
                            end
                        end else begin
                            done <= 1'b1;
                        end
                        state <= IDLE;
                    end
                end

                default: fault <= 1'b1;
            endcase
        end
        // Keep CE's pad input driven by one register, not a long shared
        // lock/fault decode. Loss of lock deselects above; latched faults also
        // leave every outgoing command idle without restarting the engine.
        if (fault) begin
            chip_enable_n <= 1'b1;
            clock_enable <= 1'b0;
            data_enable <= 0;
        end
    end
endmodule
