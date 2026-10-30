`timescale 1ns/1ps

// The Verilator bench top for the register file and the EA adder (HDL plan, Phase D, D1): the
// EU's decode (eu_decode), operand record (v35_operands) and register effects (v35_execute)
// from v35_eu_pkg, combinational, driven and read by v35_rf_tb.cpp from the vectors of
// validation/v35s/chains/rtl_vectors.py's regfile_vectors (templates.decode and
// templates.execute on every instruction the corpus starts, every ModR/M memory mode and
// random register files). Build: fpga/v35s/build_rf_tb.sh (binary in build/fpga/v35s/rf-tb/).
module v35_rf_tb
    import v35_decoder_pkg::*;
    import v35_eu_pkg::*;
(
    input  wire [179:0] rf_in,              // v35_rf_t: the register file before
    input  wire [47:0]  code,               // the instruction's bytes, the opcode in [47:40]
    input  wire [15:0]  pc,                 // its code offset
    input  wire [3:0]   mutate,             // v35_operands' and v35_execute's mutations
    output logic        ok,                 // the decode knows the opcode
    output logic [196:0] opr,               // v35_opnd_t (fmt, tmpl 0: the start's)
    output logic [179:0] rf_out,            // the register file after its execute
    output logic        obad,               // the record cannot be given
    output logic        xbad                // the register file cannot hold the effects
);
    always_comb begin
        v35_op_t op;
        v35_opnd_t r;
        op = eu_decode(code);
        ok = op.ok;
        r = v35_operands(v35_rf_t'(rf_in), code, pc, op, mutate, obad);
        opr = r;
        rf_out = v35_execute(v35_rf_t'(rf_in), code, op, r, mutate, xbad);
    end
endmodule
