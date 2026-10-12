`timescale 1ns/1ps

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
    wire hr_ck;
    wire hr_cs_n;
    wire hr_reset_n;
    wire hr_rwds;
    wire [7:0] hr_dq;

    // HyperRAM PLL outputs at 100 MHz: 0, 90 and 90 degrees.
    reg clk_hr = 0;
    reg clk_hr90 = 0;
    reg hr_pll_locked = 0;
    always #5 clk_hr = ~clk_hr;
    initial begin
        #2.5;
        forever #5 clk_hr90 = ~clk_hr90;
    end

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

    wire [3:0] tx;
    wire [3:0] bx;
    wire [3:0] lx;
    wire [3:0] rx;
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
        .clk_hr(clk_hr),
        .clk_hr90(clk_hr90),
        .clk_hr_cal(clk_hr90),
        .hr_pll_locked(hr_pll_locked),
        .heartbeat_out(heartbeat_out),
        .spi_miso(spi_miso),
        .spi_cs_n(spi_cs_n),
        .spi_sck(spi_sck),
        .spi_mosi(spi_mosi),
        .fpga_irq_n(fpga_irq_n),
        .dut_isolate(dut_isolate),
        .dut_crowbar(dut_crowbar),
        .hr_ck(hr_ck),
        .hr_cs_n(hr_cs_n),
        .hr_reset_n(hr_reset_n),
        .hr_rwds(hr_rwds),
        .hr_dq(hr_dq),

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
        .bx(bx),
        .lx(lx),
        .rx(rx),
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

    hyperram_model hyperram_memory (
        .ck(hr_ck),
        .cs_n(hr_cs_n),
        .reset_n(hr_reset_n),
        .dq(hr_dq),
        .rwds(hr_rwds)
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

    function automatic [31:0] crc32c_byte(input [31:0] crc, input [7:0] data);
        integer bit_number;
        reg [31:0] next;
        begin
            next = crc ^ {24'd0, data};
            for (bit_number = 0; bit_number < 8; bit_number = bit_number + 1)
                next = next[0] ? (next >> 1) ^ 32'h82f63b78 : next >> 1;
            crc32c_byte = next;
        end
    endfunction

    reg [7:0] command [0:15];
    reg [7:0] reply [0:71];

    // Send a 16-byte HyperRAM command on channel 1 and read the reply.
    task automatic hyperram_command(input [31:0] tag);
        reg [31:0] crc;
        integer timeout;
        begin
            crc = 32'hffffffff;
            for (index = 0; index < 16; index = index + 1)
                crc = crc32c_byte(crc, command[index]);
            crc = ~crc;
            start_transaction();
            spi_byte(8'h02, received);
            spi_byte(8'h01, received);              // ABI
            spi_byte(8'h01, received);              // channel 1
            spi_byte(8'h03, received);              // FIRST | LAST
            spi_byte(8'h00, received);
            spi_byte(tag[7:0], received);
            spi_byte(tag[15:8], received);
            spi_byte(tag[23:16], received);
            spi_byte(tag[31:24], received);
            spi_byte(8'd16, received);
            spi_byte(8'h00, received);
            spi_byte(8'h00, received);
            spi_byte(8'h00, received);
            spi_byte(crc[7:0], received);
            spi_byte(crc[15:8], received);
            spi_byte(crc[23:16], received);
            spi_byte(crc[31:24], received);
            for (index = 0; index < 16; index = index + 1)
                spi_byte(command[index], received);
            end_transaction();

            timeout = 0;
            while (fpga_irq_n !== 1'b0 && timeout < 400000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (fpga_irq_n !== 1'b0)
                $fatal(1, "HyperRAM command produced no reply");

            start_transaction();
            spi_byte(8'h03, received);
            for (index = 0; index < 72; index = index + 1) begin
                spi_byte(8'h00, received);
                reply[index] = received;
            end
            end_transaction();

            crc = 32'hffffffff;
            for (index = 16; index < 72; index = index + 1)
                crc = crc32c_byte(crc, reply[index]);
            if (reply[1] !== 8'h01 || reply[8] !== 8'd56 ||
                {reply[7], reply[6], reply[5], reply[4]} !== tag ||
                {reply[15], reply[14], reply[13], reply[12]} !== ~crc)
                $fatal(1, "malformed HyperRAM reply header");

            start_transaction();
            spi_byte(8'h04, received);
            spi_byte(tag[7:0], received);
            spi_byte(tag[15:8], received);
            spi_byte(tag[23:16], received);
            spi_byte(tag[31:24], received);
            end_transaction();
            repeat (4) @(posedge clk);
        end
    endtask

    initial begin
        #1;
        if ({dut_isolate, dut_crowbar, xy_oe_n} !== 3'b100)
            $fatal(1, "unsafe scalar output state");

        // Until its PLL locks the HyperRAM stays deselected and out of reset.
        if ({hr_cs_n, hr_reset_n} !== 2'b11)
            $fatal(1, "HyperRAM is not deselected");
        hr_pll_locked = 1;

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

        // The echo needs the start-up delay plus one cycle per byte.
        repeat (2000) @(posedge clk);
        #1;
        if (fpga_irq_n !== 1'b0)
            $fatal(1, "echo completion did not assert IRQ");

        start_transaction();
        spi_byte(8'h01, received);
        spi_byte(8'h00, received);
        end_transaction();
        if (received[7:4] !== 4'b0000)
            $fatal(1, "reserved mailbox status bits are not zero");

        // READ_PACKET is non-destructive before ACK.
        start_transaction();
        spi_byte(8'h03, received);
        for (index = 0; index < 19; index = index + 1) begin
            spi_byte(8'h00, received);
            if (received !== packet[index]) begin
                $display("echo[%0d]: expected=%02x received=%02x",
                         index, packet[index], received);
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

        // The queued packet is echoed next; acknowledge it too.
        repeat (2000) @(posedge clk);
        if (fpga_irq_n !== 1'b0)
            $fatal(1, "queued packet was not echoed");
        start_transaction();
        spi_byte(8'h04, received);
        spi_byte(8'h44, received);
        spi_byte(8'h33, received);
        spi_byte(8'h22, received);
        spi_byte(8'h11, received);
        end_transaction();
        repeat (4) @(posedge clk);

        // HyperRAM over the mailbox: read the ID registers, then test a
        // range. The core finishes its power-up wait before accepting work,
        // so retry while it reports not-ready.
        for (index = 0; index < 16; index = index + 1)
            command[index] = 8'h00;
        command[0] = 8'd2;
        reply[16] = 8'd1;
        while (reply[16] == 8'd1) begin
            hyperram_command(32'h0000_1001);
            if (reply[16] == 8'd1)
                repeat (2000) @(posedge clk);
        end
        // Result payload starts at reply[16]: ID0 at +34, MHz at +4,
        // phase at +6, burst length at +8, producer width at +10.
        if (reply[16] !== 8'd0 || {reply[51], reply[50]} !== 16'h0c83 ||
            {reply[53], reply[52]} !== 16'h0001 ||
            {reply[21], reply[20]} !== 16'd100 ||
            {reply[23], reply[22]} !== 16'd90 ||
            {reply[25], reply[24]} !== 16'd256 ||
            {reply[27], reply[26]} !== 16'd64)
            $fatal(1, "HyperRAM ID reply: status %0d id0 %02x%02x",
                   reply[16], reply[51], reply[50]);

        command[0] = 8'd0;                  // write then read back
        command[1] = 8'd0;                  // PRBS
        command[4] = 8'h78;
        command[5] = 8'h56;
        command[6] = 8'h34;
        command[7] = 8'h12;
        command[8] = 8'd5;                  // first burst 5
        command[12] = 8'd3;                 // 3 bursts of 256 words
        hyperram_command(32'h0000_1002);
        if (reply[16] !== 8'd0 ||
            {reply[31], reply[30], reply[29], reply[28]} !== 32'd768 ||
            {reply[35], reply[34], reply[33], reply[32]} !== 32'd0 ||
            {reply[39], reply[38], reply[37], reply[36]} !== 32'd0 ||
            {reply[59], reply[58], reply[57], reply[56]} == 32'd0)
            $fatal(1, "HyperRAM test reply: status %0d words %0d errors %0d",
                   reply[16], {reply[31], reply[30], reply[29], reply[28]},
                   {reply[35], reply[34], reply[33], reply[32]});

        // Out-of-range bursts are refused.
        command[8] = 8'hff;
        command[9] = 8'h3f;                 // burst 16383 of 16384
        command[12] = 8'd2;
        hyperram_command(32'h0000_1003);
        if (reply[16] !== 8'd4)
            $fatal(1, "out-of-range request status %0d", reply[16]);

        // Force the divider terminal count to test heartbeat without 100 ms.
        @(negedge clk);
        dut.heartbeat_count = 22'd2_499_999;
        @(posedge clk);
        #1;
        if (heartbeat_out !== 1'b1)
            $fatal(1, "heartbeat did not toggle");

        $display(
            "PASS: SPI, CRC, backpressure, echo, ACK, IRQ, heartbeat, HyperRAM ID and test");
        $finish;
    end
endmodule
