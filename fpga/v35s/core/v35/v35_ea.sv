`timescale 1ns/1ps

// V35S core v2 (MX0): the EA unit, driven by the microinstruction's EA step (v35_pkg::v35_ea_e;
// docs/v35s-mechanisms.md section 3.5: the ROM has no EA routine, the address is the pops and
// one add). Combinational, in the datapath's second tick: DISP the popped displacement (the
// direct forms' [d16]); BI the ModR/M mode's base (port A) + index (port B) + displacement
// (v35_fn_pkg::v35_ea_off: d8 sign-extended, d16, the mod 00 rm 110 direct form). bp: the mode
// is BP-based (the default segment SS). No clock and no count of its own.
// (MX1) The add's path, in the datapath's tick B: the RAM's read data (ports A and B, the
// base and the index) -> the 3-input 16-bit sum (the displacement sign-extended by the mode)
// -> the address register; a request reads the address register a word later (the assembler
// rejects a posting word with ea=BI), so the sum never reaches the request's 20-bit address in
// the same tick. About 10 levels with two carry chains: README "MX1".
// Quartus 17.1 reads one import in a module header, so the imports sit in $unit scope
// verilator lint_off IMPORTSTAR
import v35_pkg::*;
import v35_fn_pkg::*;
// verilator lint_on IMPORTSTAR
module v35_ea
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
