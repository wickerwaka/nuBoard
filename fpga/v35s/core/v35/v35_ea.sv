`timescale 1ns/1ps

// V35S core v2 (MX0): the EA unit, driven by the microinstruction's EA step (v35_pkg::v35_ea_e;
// docs/v35s-mechanisms.md section 3.5: the ROM has no EA routine, the address is the pops and
// one add). Combinational, in the datapath's second tick: DISP the popped displacement (the
// direct forms' [d16]); BI the ModR/M mode's base (port A) + index (port B) + displacement
// (v35_fn_pkg::v35_ea_off: d8 sign-extended, d16, the mod 00 rm 110 direct form). bp: the mode
// is BP-based (the default segment SS). No clock and no count of its own.
module v35_ea
    import v35_pkg::*;
    import v35_fn_pkg::*;
(
    input  v35_ea_e    step,
    input  wire [7:0]  modrm,
    input  wire [15:0] base,
    input  wire [15:0] index,
    input  wire [15:0] disp,
    output logic [15:0] off,
    output logic       bp
);
    wire unused = &{1'b0, modrm[5:3]};
    logic [15:0] o;
    logic b;
    always_comb begin
        o = v35_ea_off(modrm[7:6], modrm[2:0], base, modrm[2] ? 16'd0 : index, disp, b);
        case (step)
            EA_DISP: begin
                off = disp;
                bp = 1'b0;
            end
            EA_BI: begin
                off = o;
                bp = b;
            end
            default: begin
                off = 16'd0;
                bp = 1'b0;
            end
        endcase
    end
endmodule
