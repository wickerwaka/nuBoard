`timescale 1ns/1ps

// SPI-only behavioral model for the command subset used by the template.
// Keeping the model independent of the controller ensures the echo test fails
// if command bits, address bits, write data, or read sampling are incorrect.
module aps1604m_spi_model (
    input  wire ce_n,
    input  wire sclk,
    input  wire si,
    output reg  so
);
    reg [7:0] memory [0:255];
    reg [7:0] command;
    reg [20:0] address;
    reg [7:0] write_shift;
    integer bit_count;
    integer read_bit;

    integer reset_enable_count = 0;
    integer reset_count = 0;
    integer write_count = 0;
    integer read_count = 0;
    reg reset_enabled = 1'b0;

    initial begin
        so = 1'b0;
        command = 8'd0;
        address = 21'd0;
        write_shift = 8'd0;
        bit_count = 0;
        read_bit = 0;
    end

    always @(negedge ce_n) begin
        command = 8'd0;
        address = 21'd0;
        write_shift = 8'd0;
        bit_count = 0;
        read_bit = 0;
        so = 1'b0;
    end

    always @(posedge sclk) begin
        if (!ce_n) begin
            if (bit_count < 8) begin
                command = {command[6:0], si};
            end else if (bit_count < 32) begin
                address = {address[19:0], si};
            end else if (command == 8'h02) begin
                write_shift = {write_shift[6:0], si};

                if (bit_count == 39)
                    memory[address[7:0]] = write_shift;
            end

            bit_count = bit_count + 1;
        end
    end

    always @(negedge sclk) begin
        if (!ce_n && command == 8'h03 &&
            bit_count >= 32 && read_bit < 8) begin
            so = memory[address[7:0]][7 - read_bit];
            read_bit = read_bit + 1;
        end
    end

    always @(posedge ce_n) begin
        if (command == 8'h66) begin
            reset_enabled = 1'b1;
            reset_enable_count = reset_enable_count + 1;
        end else if (command == 8'h99 && reset_enabled) begin
            reset_enabled = 1'b0;
            reset_count = reset_count + 1;
        end else if (command == 8'h02 && bit_count == 40) begin
            write_count = write_count + 1;
        end else if (command == 8'h03 && bit_count == 40) begin
            read_count = read_count + 1;
        end
    end
endmodule

module template_tb;
    reg clk = 0;
    reg spi_cs_n = 1;
    reg spi_sck = 0;
    reg spi_mosi = 0;
    wire spi_miso;
    wire heartbeat_out;
    wire fpga_irq_n;
    wire dut_isolate;
    wire dut_crowbar;
    wire psram_ce_n;
    wire psram_sclk;
    wire psram_si;
    wire psram_so;
    wire psram_sio2;
    wire psram_sio3;

    wire [7:0] t0;
    wire [7:0] t1;
    wire [7:0] t2;
    wire t0_dir;
    wire t1_dir;
    wire t2_dir;
    wire t0_oe_n;
    wire t1_oe_n;
    wire t2_oe_n;

    wire [7:0] b0;
    wire [7:0] b1;
    wire [7:0] b2;
    wire b0_dir;
    wire b1_dir;
    wire b2_dir;
    wire b0_oe_n;
    wire b1_oe_n;
    wire b2_oe_n;

    wire [7:0] l0;
    wire [7:0] l1;
    wire [7:0] l2;
    wire l0_dir;
    wire l1_dir;
    wire l2_dir;
    wire l0_oe_n;
    wire l1_oe_n;
    wire l2_oe_n;

    wire [7:0] r0;
    wire [7:0] r1;
    wire [7:0] r2;
    wire r0_dir;
    wire r1_dir;
    wire r2_dir;
    wire r0_oe_n;
    wire r1_oe_n;
    wire r2_oe_n;

    wire tx;
    wire ty;
    wire bx;
    wire by;
    wire lx;
    wire ly;
    wire rx;
    wire ry;
    wire xy_oe_n;

    wire tclk;
    wire tclk_en;
    wire bclk;
    wire bclk_en;
    wire lclk;
    wire lclk_en;
    wire rclk;
    wire rclk_en;

    always #10 clk = ~clk;

    nuboard_template dut (
        .clk_50mhz(clk),
        .clk_50mhz_alias(clk),
        .heartbeat_out(heartbeat_out),
        .spi_miso(spi_miso),
        .spi_cs_n(spi_cs_n),
        .spi_sck(spi_sck),
        .spi_mosi(spi_mosi),
        .fpga_irq_n(fpga_irq_n),
        .dut_isolate(dut_isolate),
        .dut_crowbar(dut_crowbar),
        .psram_ce_n(psram_ce_n),
        .psram_sclk(psram_sclk),
        .psram_si(psram_si),
        .psram_so(psram_so),
        .psram_sio2(psram_sio2),
        .psram_sio3(psram_sio3),

        .t0(t0),
        .t1(t1),
        .t2(t2),
        .t0_dir(t0_dir),
        .t1_dir(t1_dir),
        .t2_dir(t2_dir),
        .t0_oe_n(t0_oe_n),
        .t1_oe_n(t1_oe_n),
        .t2_oe_n(t2_oe_n),

        .b0(b0),
        .b1(b1),
        .b2(b2),
        .b0_dir(b0_dir),
        .b1_dir(b1_dir),
        .b2_dir(b2_dir),
        .b0_oe_n(b0_oe_n),
        .b1_oe_n(b1_oe_n),
        .b2_oe_n(b2_oe_n),

        .l0(l0),
        .l1(l1),
        .l2(l2),
        .l0_dir(l0_dir),
        .l1_dir(l1_dir),
        .l2_dir(l2_dir),
        .l0_oe_n(l0_oe_n),
        .l1_oe_n(l1_oe_n),
        .l2_oe_n(l2_oe_n),

        .r0(r0),
        .r1(r1),
        .r2(r2),
        .r0_dir(r0_dir),
        .r1_dir(r1_dir),
        .r2_dir(r2_dir),
        .r0_oe_n(r0_oe_n),
        .r1_oe_n(r1_oe_n),
        .r2_oe_n(r2_oe_n),

        .tx(tx),
        .ty(ty),
        .bx(bx),
        .by(by),
        .lx(lx),
        .ly(ly),
        .rx(rx),
        .ry(ry),
        .xy_oe_n(xy_oe_n),

        .tclk(tclk),
        .tclk_en(tclk_en),
        .bclk(bclk),
        .bclk_en(bclk_en),
        .lclk(lclk),
        .lclk_en(lclk_en),
        .rclk(rclk),
        .rclk_en(rclk_en)
    );

    aps1604m_spi_model psram (
        .ce_n(psram_ce_n),
        .sclk(psram_sclk),
        .si(psram_si),
        .so(psram_so)
    );

    task automatic spi_byte(input [7:0] tx, output [7:0] rx);
        integer bit_number;
        begin
            rx = 0;
            for (bit_number = 7; bit_number >= 0; bit_number = bit_number - 1) begin
                spi_mosi = tx[bit_number];
                #20 spi_sck = 1;
                #5 rx[bit_number] = spi_miso;
                #15 spi_sck = 0;
            end
        end
    endtask

    task automatic start_transaction;
        begin
            spi_cs_n = 0;
            #20;
        end
    endtask

    task automatic end_transaction;
        begin
            #20 spi_cs_n = 1;
            #40;
        end
    endtask

    reg [7:0] received;
    reg [7:0] packet [0:18];
    integer index;

    initial begin
        #1;
        if ({dut_isolate, dut_crowbar, psram_ce_n, xy_oe_n} !== 4'b1010)
            $fatal(1, "unsafe scalar output state");

        if ({psram_sclk, psram_si, psram_sio2, psram_sio3} !== 4'b0000)
            $fatal(1, "unsafe PSRAM startup state");

        if ({t0_dir, t1_dir, t2_dir,
             b0_dir, b1_dir, b2_dir,
             l0_dir, l1_dir, l2_dir,
             r0_dir, r1_dir, r2_dir} !== 12'h000)
            $fatal(1, "unsafe parallel direction state");

        if ({t0_oe_n, t1_oe_n, t2_oe_n,
             b0_oe_n, b1_oe_n, b2_oe_n,
             l0_oe_n, l1_oe_n, l2_oe_n,
             r0_oe_n, r1_oe_n, r2_oe_n} !== 12'hfff)
            $fatal(1, "unsafe parallel enable state");

        if ({tclk, tclk_en, bclk, bclk_en,
             lclk, lclk_en, rclk, rclk_en} !== 8'h00)
            $fatal(1, "unsafe edge clock state");

        // Identity transaction and ABI qualification.
        start_transaction();
        spi_byte(8'h05, received);
        for (index = 0; index < 32; index = index + 1) begin
            spi_byte(8'h00, received);
            if (index == 0 && received !== 8'h6e) begin
                $display("identity[0]=%02x", received);
                $fatal(1, "identity UUID mismatch");
            end
            if (index == 24 && received !== 8'h01)
                $fatal(1, "ABI major mismatch");
        end
        end_transaction();

        // Write a FIRST|LAST channel-2 packet containing "abc".
        packet[0] = 8'h01;
        packet[1] = 8'h02;
        packet[2] = 8'h03;
        packet[3] = 8'h00;
        packet[4] = 8'h44;
        packet[5] = 8'h33;
        packet[6] = 8'h22;
        packet[7] = 8'h11;
        packet[8] = 8'h03;
        packet[9] = 8'h00;
        packet[10] = 8'h00;
        packet[11] = 8'h00;
        packet[12] = 8'hb7;
        packet[13] = 8'h3f;
        packet[14] = 8'h4b;
        packet[15] = 8'h36;
        packet[16] = "a";
        packet[17] = "b";
        packet[18] = "c";

        // A corrupt payload CRC must not consume the inbound slot.
        packet[12] = packet[12] ^ 8'h01;
        start_transaction();
        spi_byte(8'h02, received);
        for (index = 0; index < 19; index = index + 1)
            spi_byte(packet[index], received);
        end_transaction();
        packet[12] = packet[12] ^ 8'h01;

        start_transaction();
        spi_byte(8'h01, received);
        spi_byte(8'h00, received);
        end_transaction();
        if (received[2] !== 1'b1 || received[0] !== 1'b1)
            $fatal(1, "CRC failure was not reported without consuming slot");
        if (fpga_irq_n !== 1'b1)
            $fatal(1, "rejected packet asserted IRQ");

        start_transaction();
        spi_byte(8'h02, received);
        for (index = 0; index < 19; index = index + 1)
            spi_byte(packet[index], received);
        end_transaction();

        // Controller initialization plus nineteen write/read-back operations
        // complete well within this 300 us bound at 25 MHz SCLK.
        repeat (15000) @(posedge clk);
        #1;
        if (fpga_irq_n !== 1'b0)
            $fatal(1, "PSRAM-backed completion did not assert IRQ");

        if (psram.reset_enable_count != 1 || psram.reset_count != 1)
            $fatal(1, "PSRAM reset sequence was not observed exactly once");

        if (psram.write_count != 19 || psram.read_count != 19)
            $fatal(1, "echo did not perform one PSRAM round trip per byte");

        start_transaction();
        spi_byte(8'h01, received);
        spi_byte(8'h00, received);
        end_transaction();
        if (received[4] !== 1'b1)
            $fatal(1, "mailbox status did not report initialized PSRAM");

        // READ_PACKET is non-destructive before ACK.
        start_transaction();
        spi_byte(8'h03, received);
        for (index = 0; index < 19; index = index + 1) begin
            spi_byte(8'h00, received);
            if (received !== packet[index]) begin
                $display(
                    "echo[%0d]: expected=%02x received=%02x psram=%02x,%02x,%02x,%02x",
                    index,
                    packet[index],
                    received,
                    psram.memory[0],
                    psram.memory[1],
                    psram.memory[2],
                    psram.memory[3]);
                $fatal(1, "echo mismatch at byte %0d", index);
            end
        end
        end_transaction();
        if (fpga_irq_n !== 1'b0)
            $fatal(1, "READ_PACKET destructively cleared IRQ");

        // Queue another inbound packet while the first outbound packet waits
        // for ACK. The application must apply backpressure instead of
        // overwriting either slot.
        start_transaction();
        spi_byte(8'h02, received);
        for (index = 0; index < 19; index = index + 1)
            spi_byte(packet[index], received);
        end_transaction();

        start_transaction();
        spi_byte(8'h01, received);
        spi_byte(8'h00, received);
        end_transaction();
        if (received[0] !== 1'b0 || received[3] !== 1'b1)
            $fatal(1, "inbound backpressure was not reported");

        // ACK_PACKET releases the slot and IRQ only for the matching tag.
        start_transaction();
        spi_byte(8'h04, received);
        spi_byte(8'h44, received);
        spi_byte(8'h33, received);
        spi_byte(8'h22, received);
        spi_byte(8'h11, received);
        end_transaction();
        repeat (4) @(posedge clk);
        if (fpga_irq_n !== 1'b1)
            $fatal(1, "ACK_PACKET did not release IRQ");

        // Force the divider terminal count to test heartbeat without 100 ms.
        @(negedge clk);
        dut.heartbeat_count = 22'd2_499_999;
        @(posedge clk);
        #1;
        if (heartbeat_out !== 1'b1)
            $fatal(1, "heartbeat did not toggle");

        $display(
            "PASS: SPI, CRC, backpressure, PSRAM echo, ACK, IRQ, heartbeat");
        $finish;
    end
endmodule
