`timescale 1ns/1ps

// Request metadata changes with request, not a cycle early. The controller
// must validate the new fields before selecting the chip or producing clocks.
module qpi_request_tb;
    reg clock = 0;
    always #5 clock = ~clock;
    wire [4:0] passed;

    for (genvar item = 0; item < 4; item = item+1) begin : cases
        reg request = 0;
        reg write = 1;
        reg [20:0] address = 0;
        reg [7:0] length = 0;
        reg complete = 0;
        wire ready, initialized, fault, ce_n, sclk;
        wire [3:0] dq_out, dq_enable, dq_in;
        assign passed[item] = complete;

        aps1604m_qpi #(.POWER_UP_US(1)) dut (
            .clock(clock), .locked(1'b1), .request(request),
            .request_write(write), .request_address(address),
            .request_length(length), .ready(ready), .done(),
            .initialized(initialized), .fault(fault), .identity(),
            .write_word_index(), .write_word(64'd0),
            .read_valid(), .read_index(), .read_byte(),
            .ce_n(ce_n), .sclk(sclk), .dq_out(dq_out),
            .dq_enable(dq_enable), .dq_in(dq_in)
        );
        psram_model ram (
            .ce_n(ce_n), .sclk(sclk), .host_data(dq_out),
            .host_enable(dq_enable), .data(dq_in)
        );

        initial begin
            wait (initialized && ready);
            @(negedge clock);
            if (ram.completed_id_reads != 2 || dut.identity != 64'h0d5d000000000123)
                $fatal(1, "SPI identity reads=%0d id=%h", ram.completed_id_reads, dut.identity);
            case (item)
                0: length = 0;
                1: length = 129;
                2: begin
                    write = 0;
                    length = 65;
                end
                3: begin
                    address = 511;
                    length = 2;
                end
            endcase
            request = 1;
            wait (!ready);
            @(negedge clock);
            request = 0;
            wait (fault);
            repeat (4) @(negedge clock);
            if (!ce_n || sclk || ready)
                $fatal(1, "invalid request %0d did not fail closed", item);
            complete = 1;
        end
        always @(negedge ce_n) begin
            if (initialized)
                $fatal(1, "invalid request %0d selected PSRAM", item);
        end
    end

    // A bad known-good-die code must stop before QPI entry. It must remain
    // stopped, not retry initialization behind the host's back.
    begin : rejected_identity
        wire ce_n, sclk, initialized, fault;
        wire [3:0] dq_out, dq_enable, dq_in;
        reg complete = 0;
        assign passed[4] = complete;
        aps1604m_qpi #(.POWER_UP_US(1)) dut (
            .clock(clock), .locked(1'b1), .request(1'b0),
            .request_write(1'b0), .request_address(21'd0),
            .request_length(8'd0), .ready(), .done(),
            .initialized(initialized), .fault(fault), .identity(),
            .write_word_index(), .write_word(64'd0),
            .read_valid(), .read_index(), .read_byte(),
            .ce_n(ce_n), .sclk(sclk), .dq_out(dq_out),
            .dq_enable(dq_enable), .dq_in(dq_in)
        );
        psram_model #(.IDENTITY(64'h0d55000000000123)) ram (
            .ce_n(ce_n), .sclk(sclk), .host_data(dq_out),
            .host_enable(dq_enable), .data(dq_in)
        );
        initial begin
            wait (fault);
            #10000;
            if (initialized || !ce_n || sclk || ram.qpi || ram.completed_id_reads != 2)
                $fatal(1, "bad identity did not remain safely stopped");
            if (dut.identity != 64'h0d55000000000123)
                $fatal(1, "rejected identity was not retained");
            complete = 1;
        end
    end

    initial begin
        wait (&passed);
        $display("PASS: DDR100 SPI identity and zero/oversize/page-crossing requests fail closed");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "request rejection watchdog");
    end
endmodule
