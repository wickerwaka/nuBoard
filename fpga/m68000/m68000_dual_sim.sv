`timescale 1ns/1ps

// Simulation-only surrogate for exercising both independent memory lanes and
// the differential runner. A second fx68k is NOT a real-chip reference.
module m68000_dual_sim (
    input wire clock,
    input wire debug_valid,
    input wire debug_write,
    input wire [19:0] debug_address,
    input wire [15:0] debug_write_data,
    output wire debug_ready,
    output wire debug_error,
    output wire [15:0] debug_read_data
);
    wire [23:1] address;
    wire [15:0] data_out, data_in;
    wire as_n, uds_n, lds_n, read_cycle;
    wire [2:0] fc;
    wire dtack_n, berr_n, armed, reset_pull, halt_pull, cpu_clock;
    reg previous_clock = 1'b0;

    always @(posedge clock)
        previous_clock <= cpu_clock;

    m68000_harness harness (
        .clock(clock),
        .debug_valid(debug_valid),
        .debug_write(debug_write),
        .debug_address(debug_address),
        .debug_write_data(debug_write_data),
        .debug_ready(debug_ready),
        .debug_error(debug_error),
        .debug_read_data(debug_read_data),
        .socket_address({address, 1'b0}),
        .socket_data_out(data_out),
        .socket_as_n(as_n),
        .socket_uds_n(uds_n),
        .socket_lds_n(lds_n),
        .socket_read(read_cycle),
        .socket_fc(fc),
        .socket_reset_n(!reset_pull),
        .socket_halt_n(!halt_pull),
        .socket_data_in(data_in),
        .socket_data_drive(),
        .socket_dtack_n(dtack_n),
        .socket_berr_n(berr_n),
        .socket_armed(armed),
        .socket_reset_pull(reset_pull),
        .socket_halt_pull(halt_pull),
        .cpu_clock(cpu_clock),
        .busy(),
        .complete()
    );

    fx68k surrogate (
        .clk(clock),
        .HALTn(!halt_pull),
        .extReset(!armed || reset_pull),
        .pwrUp(!armed || reset_pull),
        .enPhi1(cpu_clock && !previous_clock),
        .enPhi2(!cpu_clock && previous_clock),
        .eRWn(read_cycle),
        .ASn(as_n),
        .LDSn(lds_n),
        .UDSn(uds_n),
        .E(),
        .VMAn(),
        .FC0(fc[0]),
        .FC1(fc[1]),
        .FC2(fc[2]),
        .BGn(),
        .oRESETn(),
        .oHALTEDn(),
        .DTACKn(dtack_n),
        .VPAn(1'b1),
        .BERRn(berr_n),
        .BRn(1'b1),
        .BGACKn(1'b1),
        .IPL0n(1'b1),
        .IPL1n(1'b1),
        .IPL2n(1'b1),
        .iEdb(data_in),
        .oEdb(data_out),
        .eab(address)
    );
endmodule
