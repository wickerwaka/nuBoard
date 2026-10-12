`timescale 1ns/1ps

// V35S model lane, first core.
//
// The execution engine is nuV30's unmodified ucore (`v30_core`, V20 microcode,
// de-muxed bus) from the pinned checkout in build/deps/nuV30. It still runs
// its own V30 bus unit; this wrapper turns each announced V30 bus cycle into a
// V35-shaped cycle. The ucore latches read data at T2 whatever READY says, so
// instead of inserting waits the wrapper FREEZES the core (no CE, no CE_HALF)
// in T2 until the V35 cycle has delivered its data.
//
// What is V35 here, from the silicon measurements in docs/v35s-bus-timing.md:
//   * CLKOUT is X1 / 2, 4 or 8 (PRC.PCK); one bus state per CLKOUT.
//   * A cycle is B1, B2, waits, B3. /MREQ falls mid-B1; /MSTB (read) or
//     /IOSTB falls mid-B2; a memory-write /MSTB falls mid-way through the
//     state before B3; every strobe rises mid-B3.
//   * Waits per 128 KiB block and for I/O come from WTC (reset FFFFh: two
//     waits plus READY). Refresh cycles come from RFM (reset FCh).
//   * Data accesses to the internal RAM and SFRs (xxE00-xxFFF, xx = IDB, and
//     FFFFF) never reach the bus; instruction fetches always do.
//
// What is NOT V35 yet: the V30 bus unit's prefetch policy and T-state timing
// decide when cycles are requested, the general registers do not live in the
// internal RAM, and the V35-only instructions and peripherals are absent.
module v35s_model (
    input  wire        clock,
    input  wire        x_rise,
    input  wire        x_fall,
    input  wire        reset_n,
    input  wire        ready,
    input  wire [15:0] data_in,
    input  wire [15:0] input_levels,
    output reg         a0,
    output reg         a19,
    output reg         a18_ube,
    output reg  [8:0]  mux_address,
    output reg  [15:0] data_out,
    output reg         mreq_n,
    output reg         mstb_n,
    output reg         iostb_n,
    output reg         read_write,
    output reg         refrq_n
);
    initial begin
        a0 = 1'b0;
        a19 = 1'b0;
        a18_ube = 1'b0;
        mux_address = 9'd0;
        data_out = 16'd0;
        mreq_n = 1'b1;
        mstb_n = 1'b1;
        iostb_n = 1'b1;
        read_write = 1'b1;
        refrq_n = 1'b1;
    end

    // ---------------------------------------------------------------- SFRs
    reg [7:0] prc = 8'h4e;
    reg [15:0] wtc = 16'hffff;
    reg [7:0] rfm = 8'hfc;
    reg [7:0] idb = 8'hff;
    // Registers, not block RAM: as a block RAM, synthesis folds cycle_address
    // into the RAM address register, which puts the core's address logic on
    // a single-cycle path.
    (* syn_ramstyle = "registers" *) reg [7:0] internal_ram [0:255];
    reg [7:0] sfr [0:255];

    // ---------------------------------------------------------- CPU clock
    // One bus state per CLKOUT period of 2, 4 or 8 X1 periods. The divider
    // runs freely (the core is clocked through reset too) and a PCK change
    // takes effect at the next state boundary, so every CE is preceded by a
    // CE_HALF as v30_core requires.
    reg [2:0] x_count = 3'd0;
    reg [1:0] pck = 2'd2;
    wire [2:0] x_last = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd3 : 3'd7;
    wire [2:0] x_mid = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd2 : 3'd4;
    wire state_start = x_rise && x_count == 3'd0;
    wire state_mid = x_rise && x_count == x_mid;
    always @(posedge clock) begin
        if (x_rise) begin
            if (x_count == x_last) begin
                x_count <= 3'd0;
            end else begin
                x_count <= x_count + 1'b1;
            end
            if (x_count == 3'd0)
                pck <= prc[1:0];
        end
    end

    // ---------------------------------------------------------- the core
    wire [19:0] core_address;
    wire [15:0] core_write_data;
    wire [3:0] core_status;
    wire [1:0] core_qs;
    wire [2:0] core_bs;
    wire core_rd_n, core_ube_n, core_buslock_n;
    reg [15:0] core_read_data = 16'hffff;
    wire core_ready = 1'b1;
    wire core_ce, core_ce_half;

    v30_core core (
        .CLK(clock),
        .CE(core_ce),
        .CE_HALF(core_ce_half),
        .RESET(!reset_n),
        .READY(core_ready),
        .INT(input_levels[5]),
        .NMI(1'b0),
        .POLL_N(1'b0),
        .DATA_I(core_read_data),
        .ADDR_O(core_address),
        .DATA_O(core_write_data),
        .STATUS_O(core_status),
        .QS(core_qs),
        .BS(core_bs),
        .RD_N(core_rd_n),
        .UBE_N(core_ube_n),
        .BUSLOCK_N(core_buslock_n),
        .SS_ADDR(9'd0),
        .SS_WDATA(16'd0),
        .SS_WE(1'b0),
        .SS_RDATA(),
        .SS_ERR(),
        .SS_BUS_QUIET()
    );

    // V30 max-mode status: 000 INTA, 001 I/O read, 010 I/O write, 011 HALT,
    // 100 fetch, 101 memory read, 110 memory write, 111 passive.
    localparam [2:0] BS_INTA = 3'd0, BS_IOR = 3'd1, BS_IOW = 3'd2, BS_HALT = 3'd3,
                     BS_FETCH = 3'd4, BS_MEMR = 3'd5, BS_MEMW = 3'd6, BS_PASSIVE = 3'd7;

    // ------------------------------------------------- request capture
    // The V30 T-state is reconstructed from BS and READY exactly as nuV30's
    // tb_demux_min does it: a cycle starts at T1 (BS active from TI or T4),
    // READY is sampled in T3/TW, and back-to-back cycles never pass through
    // a passive BS.
    localparam [2:0] T_I = 3'd0, T_1 = 3'd1, T_2 = 3'd2, T_3 = 3'd3,
                     T_W = 3'd4, T_4 = 3'd5;
    reg [2:0] t_state = T_I;
    wire bs_active = core_bs != BS_PASSIVE;
    wire [2:0] t_next =
        t_state == T_I ? (bs_active ? T_1 : T_I) :
        t_state == T_1 ? T_2 :
        t_state == T_2 ? T_3 :
        (t_state == T_3 || t_state == T_W) ? (core_ready ? T_4 : T_W) :
        (bs_active ? T_1 : T_I);

    reg cycle_open = 1'b0;      // a captured cycle not yet completed
    // Whole states are skipped while the core waits in T2, so a CE_HALF
    // always separates two CEs.
    reg frozen = 1'b0;
    assign core_ce = state_start && !(t_state == T_2 && cycle_open);
    assign core_ce_half = state_mid && !frozen;
    reg [2:0] cycle_bs = BS_PASSIVE;
    reg [19:0] cycle_address = 20'd0;
    reg cycle_ube_n = 1'b1;

    wire cycle_io = cycle_bs == BS_IOR || cycle_bs == BS_IOW;
    wire cycle_write = cycle_bs == BS_IOW || cycle_bs == BS_MEMW;
    wire cycle_internal = !cycle_io && cycle_bs != BS_FETCH &&
        ((cycle_address[19:12] == idb && cycle_address[11:9] == 3'b111) ||
         cycle_address == 20'hfffff);
    wire cycle_bus = cycle_open && !cycle_internal &&
        (cycle_bs == BS_IOR || cycle_bs == BS_IOW || cycle_bs == BS_FETCH ||
         cycle_bs == BS_MEMR || cycle_bs == BS_MEMW);

    // Waits for the cycle: WTC field per 128 KiB block (6 and 7 share one),
    // the top field for I/O. 3 means two waits plus external READY.
    wire [2:0] wtc_field = cycle_io ? 3'd7 :
                           cycle_address[19:17] == 3'd7 ? 3'd6 : cycle_address[19:17];
    wire [1:0] wtc_mode = wtc[wtc_field * 2 +: 2];
    wire [1:0] cycle_waits = wtc_mode == 2'd3 ? 2'd2 : wtc_mode;
    wire [1:0] refresh_waits = rfm[3:2] == 2'd3 ? 2'd2 : rfm[3:2];

    // ------------------------------------------------- refresh timer
    reg [8:0] refresh_row = 9'd0;
    reg [7:0] refresh_timer = 8'd0;
    reg refresh_pending = 1'b0;
    wire [7:0] refresh_period = 8'd16 << rfm[1:0];

    // ------------------------------------------------- V35 bus engine
    localparam [2:0] E_IDLE = 3'd0, E_B1 = 3'd1, E_B2 = 3'd2, E_WAIT = 3'd3,
                     E_B3 = 3'd4;
    reg [2:0] engine = E_IDLE;
    reg engine_refresh = 1'b0;
    reg [1:0] wait_left = 2'd0;
    reg engine_ready_mode = 1'b0;

    wire [7:0] internal_offset = cycle_address[7:0];
    wire internal_sfr = cycle_address[8];
    function [7:0] sfr_read;
        input [7:0] offset;
        begin
            case (offset)
                8'he1: sfr_read = rfm;
                8'he8: sfr_read = wtc[7:0];
                8'he9: sfr_read = wtc[15:8];
                8'heb: sfr_read = prc;
                8'hff: sfr_read = idb;
                default: sfr_read = sfr[offset];
            endcase
        end
    endfunction

    task sfr_write;
        input [7:0] offset;
        input [7:0] value;
        begin
            case (offset)
                8'he1: rfm <= value;
                8'he8: wtc[7:0] <= value;
                8'he9: wtc[15:8] <= value;
                8'heb: prc <= value;
                8'hff: idb <= value;
                default: sfr[offset] <= value;
            endcase
        end
    endtask

    always @(posedge clock) begin
        if (!reset_n) begin
            cycle_open <= 1'b0;
            t_state <= T_I;
            frozen <= 1'b0;
            engine <= E_IDLE;
            mreq_n <= 1'b1;
            mstb_n <= 1'b1;
            iostb_n <= 1'b1;
            refrq_n <= 1'b1;
            read_write <= 1'b1;
            prc <= 8'h4e;
            wtc <= 16'hffff;
            rfm <= 8'hfc;
            idb <= 8'hff;
            refresh_timer <= 8'd0;
            refresh_pending <= 1'b0;
        end else begin
            // T1 opens a cycle; the core then stalls in T2 until the
            // V35-shaped cycle (or the internal access) completes.
            if (state_start)
                frozen <= !core_ce;
            if (core_ce) begin
                t_state <= t_next;
                // UBE_N settles a clock after the announcement (an odd word's
                // second, even byte cycle otherwise inherits the first
                // cycle's /UBE), so it is taken on the T1 -> T2 edge, still
                // before the column phase that drives it.
                if (t_state == T_1)
                    cycle_ube_n <= core_ube_n;
                if (t_next == T_1) begin
                    cycle_bs <= core_bs;
                    cycle_address <= core_address;
                    if (core_bs == BS_HALT || core_bs == BS_INTA) begin
                        cycle_open <= 1'b0;
                        core_read_data <= 16'hffff;
                    end else begin
                        cycle_open <= 1'b1;
                    end
                end
            end

            // Internal RAM and SFR data accesses: one state, no bus cycle.
            if (state_start && cycle_open && cycle_internal && t_state != T_I) begin
                if (cycle_write) begin
                    if (!cycle_address[0]) begin
                        if (internal_sfr) sfr_write(internal_offset, core_write_data[7:0]);
                        else internal_ram[internal_offset] <= core_write_data[7:0];
                    end
                    if (!cycle_ube_n) begin
                        if (internal_sfr) sfr_write(internal_offset | 8'd1, core_write_data[15:8]);
                        else internal_ram[internal_offset | 8'd1] <= core_write_data[15:8];
                    end
                    if (cycle_address == 20'hfffff)
                        idb <= core_write_data[15:8];
                end else begin
                    core_read_data <= cycle_address == 20'hfffff
                        ? {idb, 8'hff}
                        : internal_sfr
                            ? {sfr_read(internal_offset | 8'd1), sfr_read(internal_offset & 8'hfe)}
                            : {internal_ram[internal_offset | 8'd1],
                               internal_ram[internal_offset & 8'hfe]};
                end
                cycle_open <= 1'b0;
            end

            // Refresh requests accumulate at the configured period.
            if (state_start && rfm[4]) begin
                if (refresh_timer == refresh_period - 1'b1) begin
                    refresh_timer <= 8'd0;
                    refresh_pending <= 1'b1;
                end else begin
                    refresh_timer <= refresh_timer + 1'b1;
                end
            end

            case (engine)
                E_IDLE: begin
                    if (state_start) begin
                        read_write <= 1'b1;
                        if (refresh_pending) begin
                            refresh_pending <= 1'b0;
                            engine_refresh <= 1'b1;
                            mux_address <= refresh_row;
                            refresh_row <= refresh_row + 1'b1;
                            a0 <= 1'b0;
                            a19 <= 1'b0;
                            a18_ube <= 1'b0;
                            wait_left <= refresh_waits;
                            engine <= E_B1;
                        end else if (cycle_bus) begin
                            engine_refresh <= 1'b0;
                            mux_address <= cycle_address[17:9];
                            a0 <= cycle_address[0];
                            a19 <= cycle_address[19];
                            a18_ube <= cycle_address[18];
                            read_write <= !cycle_write;
                            wait_left <= cycle_waits;
                            engine_ready_mode <= wtc_mode == 2'd3;
                            engine <= E_B1;
                        end
                    end
                end
                E_B1: begin
                    if (state_mid) begin
                        if (engine_refresh) refrq_n <= 1'b0;
                        else mreq_n <= 1'b0;
                    end
                    if (state_start) begin
                        if (!engine_refresh) begin
                            mux_address <= {cycle_address[9], cycle_address[8:1]};
                            a18_ube <= cycle_ube_n;
                            if (cycle_write) data_out <= core_write_data;
                        end
                        engine <= E_B2;
                    end
                end
                E_B2, E_WAIT: begin
                    // Read and I/O strobes fall mid-B2; a memory-write strobe
                    // falls mid-way through the last state before B3.
                    if (state_mid && !engine_refresh) begin
                        if (cycle_io)
                            iostb_n <= 1'b0;
                        else if (!cycle_write || wait_left == 2'd0)
                            mstb_n <= 1'b0;
                    end
                    if (state_start) begin
                        if (wait_left != 2'd0) begin
                            wait_left <= wait_left - 1'b1;
                            engine <= E_WAIT;
                        end else if (engine == E_WAIT && engine_ready_mode &&
                                     !engine_refresh && !ready) begin
                            engine <= E_WAIT;
                        end else begin
                            engine <= E_B3;
                        end
                    end
                end
                E_B3: begin
                    if (state_mid) begin
                        mreq_n <= 1'b1;
                        mstb_n <= 1'b1;
                        iostb_n <= 1'b1;
                        refrq_n <= 1'b1;
                        if (!engine_refresh) begin
                            if (!cycle_write)
                                core_read_data <= data_in;
                            cycle_open <= 1'b0;
                        end
                        engine <= E_IDLE;
                    end
                end
                default: engine <= E_IDLE;
            endcase
        end
    end
endmodule
