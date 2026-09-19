`timescale 1ns/1ps

// Independent pin-level model of the commands used by the capture controller.
// This is a digital protocol/timing test, not an analog board model.
module psram_model #(
    parameter real OUTPUT_DELAY_NS = 5.5,
    parameter [63:0] IDENTITY = 64'h0d5d000000000123
) (
    input wire ce_n,
    input wire sclk,
    input wire [3:0] host_data,
    input wire [3:0] host_enable,
    output reg [3:0] data = 0
);
    reg [7:0] memory [0:2097151];
    reg qpi = 1'b0;
    reg reset_enabled = 1'b0;
    reg [7:0] command = 0;
    reg [23:0] address = 0;
    reg [7:0] mode_register = 8'h60;
    reg [3:0] write_high;
    integer cycles = 0;
    integer data_index;
    integer byte_address;
    reg [7:0] value;
    reg [3:0] next_data;
    realtime selected_at = 0;
    realtime released_at = 0;
    realtime previous_rise = 0;
    realtime previous_fall = 0;
    realtime required_half_period;
    realtime required_period;
    reg id_precondition = 0;
    integer completed_id_reads = 0;

    always @(negedge ce_n) begin
        if ($realtime - released_at < 18)
            $fatal(1, "PSRAM CE high time too short");
        selected_at = $realtime;
        cycles = 0;
        command = 0;
        address = 0;
    end

    always @(posedge ce_n) begin
        if ($realtime - selected_at > 4000)
            $fatal(1, "PSRAM refresh blocked for more than 4 us");
        // The external timing gate budgets a 20 ns CE hold window separately
        // from the 5 ns data hold window. Verify that protocol assumption.
        if (cycles != 0 && $realtime - previous_rise < 20)
            $fatal(1, "PSRAM CE hold window shorter than timing budget");
        released_at = $realtime;
        if (command == 8'h66)
            reset_enabled = 1'b1;
        else if (command == 8'h99 && reset_enabled) begin
            qpi = 1'b0;
            mode_register = 8'h60;
            reset_enabled = 1'b0;
            id_precondition = 0;
        end else if (command == 8'h35)
            qpi = 1'b1;
        else if (command == 8'h9f || command == 8'h8b && address == 0)
            id_precondition = 1;
        if (command == 8'h9f)
            completed_id_reads = completed_id_reads + 1;
        data <= 0;
    end

    always @(posedge sclk) begin
        if (ce_n)
            $fatal(1, "clock while PSRAM deselected");
        if (cycles == 0 && $realtime - selected_at < 3)
            $fatal(1, "PSRAM CE setup time too short");
        if (cycles != 0 && $realtime - previous_rise < 9.9)
            $fatal(1, "PSRAM clock exceeds 100 MHz");
        if (qpi && cycles >= 2 && command == 8'h8b &&
            $realtime - previous_rise < 19.9)
            $fatal(1, "PSRAM readback exceeds 50 MHz");
        if (!qpi && cycles >= 8 && command == 8'h9f &&
            $realtime - previous_rise < 39.9)
            $fatal(1, "SPI identification must run at 25 MHz");
        required_half_period = command == 8'h9f ? 20 :
                               command == 8'h8b ? 10 : 5;
        required_period = 2 * required_half_period;
        if ((qpi && cycles >= 2 || !qpi && cycles >= 8) &&
            ($realtime - previous_rise < required_period - 0.1 ||
             $realtime - previous_rise > required_period + 0.1))
            $fatal(1, "PSRAM command %h has wrong SCLK period", command);
        if (cycles >= 8 && $realtime - previous_fall < required_half_period - 0.1)
            $fatal(1, "PSRAM low pulse shorter than balanced clock budget");
        previous_rise = $realtime;
        if (!qpi) begin
            if (cycles < 8) begin
                if (host_enable != 1)
                    $fatal(1, "SPI command must drive only SI");
                command = {command[6:0], host_data[0]};
            end else if (cycles < 32 && command == 8'h9f) begin
                address = {address[22:0], host_data[0]};
            end
        end else if (cycles < 2) begin
            command = {command[3:0], host_data};
        end else if (cycles < 8) begin
            address = {address[19:0], host_data};
        end else if (command == 8'h82 || command == 8'hb1) begin
            if (host_enable != 15)
                $fatal(1, "quad write with undriven pins");
            if (!(cycles & 1)) begin
                write_high = host_data;
            end else begin
                if (command == 8'hb1) begin
                    mode_register = {write_high, host_data};
                end else begin
                    if (mode_register[6:5] != 3)
                        $fatal(1, "capture controller did not establish 512-byte wrap");
                    byte_address = address + ((cycles - 8) >> 1);
                    if ((byte_address >> 9) != (address >> 9) || byte_address >= 2097152)
                        $fatal(1, "burst crossed a page or chip boundary");
                    memory[byte_address] = {write_high, host_data};
                end
            end
        end
        if (qpi && cycles == 1 && command != 8'h82 && command != 8'h8b && command != 8'hb1)
            $fatal(1, "unsupported QPI command %h", command);
        if (!qpi && cycles == 7 && command != 8'h66 && command != 8'h99 &&
            command != 8'h35 && command != 8'h9f)
            $fatal(1, "unsupported SPI command %h", command);
        cycles = cycles + 1;
    end

    always @(negedge sclk) begin
        required_half_period = command == 8'h9f ? 20 :
                               command == 8'h8b ? 10 : 5;
        if (!ce_n && cycles >= 8 && $realtime - previous_rise < required_half_period - 0.1)
            $fatal(1, "PSRAM high pulse shorter than balanced clock budget");
        previous_fall = $realtime;
        if (!ce_n && !qpi && command == 8'h9f && cycles >= 32) begin
            if (host_enable != 0)
                $fatal(1, "host drives during SPI ID read");
            // A preceding dummy ID command is required after reset. Return
            // invalid bits until that command has actually terminated.
            next_data = {2'b00, id_precondition && IDENTITY[63 - ((cycles - 32) % 64)], 1'b0};
            data <= #(OUTPUT_DELAY_NS) next_data;
        end
        if (!ce_n && qpi && cycles >= 14 && command == 8'h8b) begin
            if (host_enable != 0)
                $fatal(1, "host drives during PSRAM read");
            data_index = cycles - 14;
            byte_address = {address[20:9], 9'd0} |
                           ((address[8:0] + (data_index >> 1)) & 511);
            value = memory[byte_address];
            next_data = data_index & 1 ? value[3:0] : value[7:4];
            data <= #(OUTPUT_DELAY_NS) next_data;
        end
    end
endmodule
