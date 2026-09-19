`timescale 1ns/1ps

// Gray-pointer asynchronous FIFO. Bank reads feed a registered binary mux
// tree: no cycle crosses the whole RAM array plus an eight-way selection.
// Memory is never reset. Consumers may not assume a fixed pop latency.
module scope_fifo #(
    parameter integer ADDRESS_BITS = 15
) (
    input  wire        reset,
    input  wire        write_clock,
    input  wire        write_valid,
    input  wire [63:0] write_data,
    output wire        write_ready,
    output wire [ADDRESS_BITS:0] occupancy,
    input  wire        read_clock,
    input  wire        pop,
    output wire        empty,
    output wire        read_valid,
    output wire [63:0] read_data
);
    localparam integer POINTER_BITS = ADDRESS_BITS + 1;
    localparam integer BANK_BITS = ADDRESS_BITS > 12 ? 3 : 2;
    localparam integer ROW_BITS = ADDRESS_BITS - BANK_BITS;
    localparam integer BANKS = 1 << BANK_BITS;
    wire [63:0] bank_data [0:BANKS-1];
    reg [ROW_BITS-1:0] write_row = 0;
    reg [63:0] pending_write_data = 0;
    reg [BANK_BITS-1:0] read_bank = 0;
    reg [BANK_BITS-1:0] mux_bank = 0;
    reg [BANK_BITS+2:0] read_pipeline = 0;
    reg [BANK_BITS-1:0] select_pipeline [0:BANK_BITS-1];
    reg empty_flag = 1;
    reg [POINTER_BITS-1:0] write_binary = 0;
    reg [POINTER_BITS-1:0] write_gray = 0;
    reg [POINTER_BITS-1:0] read_binary = 0;
    reg [POINTER_BITS-1:0] read_gray = 0;
    (* syn_keep = "true" *) reg [POINTER_BITS-1:0] advance_gray = 1;
    (* async_reg = "true", syn_keep = "true" *) reg [POINTER_BITS-1:0] read_gray_meta = 0;
    (* async_reg = "true", syn_keep = "true" *) reg [POINTER_BITS-1:0] read_gray_sync = 0;
    (* async_reg = "true", syn_keep = "true" *) reg [POINTER_BITS-1:0] write_gray_meta = 0;
    (* async_reg = "true", syn_keep = "true" *) reg [POINTER_BITS-1:0] write_gray_sync = 0;
    reg full = 1'b0;
    (* async_reg = "true" *) reg [1:0] write_reset_pipe = 2'b11;
    (* async_reg = "true" *) reg [1:0] read_reset_pipe = 2'b11;
    wire write_reset = write_reset_pipe[1];
    wire read_reset = read_reset_pipe[1];
    wire push = write_valid && write_ready;
    wire take = pop && !empty;
    wire [POINTER_BITS-1:0] next_write = write_binary + {{ADDRESS_BITS{1'b0}}, push};
    // Do not put pop/reset control through the carry chain and then a Gray
    // comparison. Compute the increment independently and select afterwards.
    wire [POINTER_BITS-1:0] next_read = read_binary + 1'b1;
    wire [POINTER_BITS-1:0] next_write_gray = (next_write >> 1) ^ next_write;
    wire [POINTER_BITS-1:0] advance_read = read_binary + 2'd2;

    function automatic [POINTER_BITS-1:0] from_gray(input [POINTER_BITS-1:0] gray);
        integer bit_index;
        begin
            from_gray[POINTER_BITS-1] = gray[POINTER_BITS-1];
            for (bit_index = POINTER_BITS-2; bit_index >= 0; bit_index = bit_index-1)
                from_gray[bit_index] = from_gray[bit_index+1] ^ gray[bit_index];
        end
    endfunction

    assign occupancy = write_binary - from_gray(read_gray_sync);
    assign write_ready = !full && !write_reset && !reset;
    assign empty = empty_flag || read_reset || reset;
    assign read_valid = read_pipeline[BANK_BITS+2];

    // Asynchronous assertion, independent synchronous release in each domain.
    always @(posedge write_clock or posedge reset) begin
        if (reset)
            write_reset_pipe <= 2'b11;
        else
            write_reset_pipe <= {write_reset_pipe[0], 1'b0};
    end

    // A local register after each BRAM keeps its long clock-to-out path out
    // of the inter-bank mux. Each subsequent stage selects just two words.
    // Preserve these explicit timing boundaries through synthesis retiming.
    for (genvar level = 0; level <= BANK_BITS; level = level+1) begin : mux_tree
        (* syn_keep = "true" *) reg [63:0] words [0:(BANKS >> level)-1];
        for (genvar item = 0; item < (BANKS >> level); item = item+1) begin : nodes
            if (level == 0) begin : leaves
                always @(posedge read_clock)
                    words[item] <= bank_data[item];
            end else begin : branches
                always @(posedge read_clock)
                    words[item] <= select_pipeline[level-1][level-1] ?
                        mux_tree[level-1].words[item*2+1] : mux_tree[level-1].words[item*2];
            end
        end
    end
    assign read_data = mux_tree[BANK_BITS].words[0];
    always @(posedge read_clock or posedge reset) begin
        if (reset)
            read_reset_pipe <= 2'b11;
        else
            read_reset_pipe <= {read_reset_pipe[0], 1'b0};
    end

    always @(posedge write_clock or posedge write_reset) begin
        if (write_reset) begin
            write_binary <= 0;
            write_gray <= 0;
            read_gray_meta <= 0;
            read_gray_sync <= 0;
            full <= 1'b0;
        end else begin
            read_gray_meta <= read_gray;
            read_gray_sync <= read_gray_meta;
            write_binary <= next_write;
            // Publish only records whose registered write command reaches
            // BRAM on this edge, not the slot reserved by the current push.
            write_gray <= (write_binary >> 1) ^ write_binary;
            full <= next_write_gray == {~read_gray_sync[POINTER_BITS-1:POINTER_BITS-2],
                                       read_gray_sync[POINTER_BITS-3:0]};
        end
    end

    // Register each bank's read enable before its RAM port. A combinational
    // empty comparison must not drive all 512 physical BRAM read enables.
    for (genvar bank_index = 0; bank_index < BANKS; bank_index = bank_index+1) begin : banks
        (* syn_ramstyle = "block_ram" *)
        reg [63:0] memory [0:(1 << ROW_BITS)-1];
        reg enable_read = 0;
        reg enable_write = 0;
        (* syn_keep = "true" *) reg [ROW_BITS-1:0] local_read_row = 0;
        reg [63:0] output_word;
        assign bank_data[bank_index] = output_word;
        always @(posedge write_clock) begin
            if (enable_write)
                memory[write_row] <= pending_write_data;
        end
        // A local registered command keeps the encoder's decision logic out
        // of the high-fanout BRAM write-enable path.
        always @(posedge write_clock or posedge write_reset) begin
            if (write_reset)
                enable_write <= 1'b0;
            else
                enable_write <= push && write_binary[ADDRESS_BITS-1:ROW_BITS] == bank_index;
        end
        always @(posedge read_clock) begin
            enable_read <= take && read_binary[ADDRESS_BITS-1:ROW_BITS] == bank_index;
            // Each bank keeps its own address. Conditional updates prevent
            // equivalent-register merging into a 512-BRAM routing fanout.
            if (take && read_binary[ADDRESS_BITS-1:ROW_BITS] == bank_index)
                local_read_row <= read_binary[ROW_BITS-1:0];
            if (enable_read)
                output_word <= memory[local_read_row];
        end
    end

    always @(posedge read_clock or posedge read_reset) begin
        if (read_reset) begin
            read_binary <= 0;
            read_gray <= 0;
            advance_gray <= 1;
            write_gray_meta <= 0;
            write_gray_sync <= 0;
            empty_flag <= 1'b1;
            read_pipeline <= 0;
        end else begin
            write_gray_meta <= write_gray;
            write_gray_sync <= write_gray_meta;
            if (take) begin
                read_binary <= next_read;
                read_gray <= advance_gray;
                advance_gray <= (advance_read >> 1) ^ advance_read;
            end
            empty_flag <= take ? advance_gray == write_gray_sync :
                                 read_gray == write_gray_sync;
            read_pipeline <= {read_pipeline[BANK_BITS+1:0], take};
        end
    end

    always @(posedge write_clock) begin
        write_row <= write_binary[ROW_BITS-1:0];
        pending_write_data <= write_data;
    end

    always @(posedge read_clock) begin
        read_bank <= read_binary[ADDRESS_BITS-1:ROW_BITS];
        mux_bank <= read_bank;
        select_pipeline[0] <= mux_bank;
        for (integer stage = 1; stage < BANK_BITS; stage = stage+1)
            select_pipeline[stage] <= select_pipeline[stage-1];
    end
endmodule
