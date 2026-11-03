`timescale 1ns/1ps

// The function bench of the core v2 (docs/v35s-core-v2.md, "Verification", function; stage S3):
// v35_fn_pkg's pure functions (fpga/v35s/core/v35/v35_fn_pkg.sv), combinational, one function
// application per vector: the ALU, INC / DEC (the ALU with CY kept, as v35_eu applies it), the
// shifter, the multiplier, the divider (v35_div: v35_div_init and v35_div_step iterated, then
// v35_div_fin, the steps v35_eu runs a clock each), the adjusts and the conditions.
// v35_rf_tb.cpp reads validation/v35s/chains/rtl_vectors.py's V35FN-1 lines (--fn: derived
// from the --regfile vectors, the expected values the functional reference's) and compares the
// selected function's outputs. Build: fpga/v35s/build_rf_tb.sh (build/fpga/v35s/fn-tb/).
module v35_rf_tb
    import v35_fn_pkg::*;
(
    input  wire [2:0]   op,
    input  wire         w,
    input  wire         sgn,
    input  wire [31:0]  a,
    input  wire [15:0]  b,
    input  wire [8:0]   n,
    input  wire [15:0]  psw,
    input  wire [3:0]   cc,
    output logic [15:0] alu_res,
    output logic [15:0] alu_psw,
    output logic [15:0] inc_res,
    output logic [15:0] inc_psw,
    output logic [15:0] sh_res,
    output logic [15:0] sh_psw,
    output logic [31:0] mul_res,
    output logic [15:0] mul_psw,
    output logic [31:0] div_res,
    output logic [15:0] div_psw,
    output logic        div_trap,
    output logic [15:0] adj_aw,
    output logic [15:0] adj_psw,
    output logic        cond
);
    always_comb begin
        logic [31:0] j;
        logic [15:0] p;
        alu_res = v35_alu(op, w, a[15:0], b, psw, alu_psw);
        inc_res = v35_alu(op, w, a[15:0], 16'd1, psw, p);
        p[V35_PSW_CY] = psw[V35_PSW_CY];
        inc_psw = p;
        sh_res = v35_shift(op, w, a[15:0], n, psw, sh_psw);
        mul_res = v35_mul(sgn, w, a[15:0], b, psw, mul_psw);
        div_res = v35_div(sgn, w, a, b, psw, div_psw, div_trap);
        j = v35_adjust(op[1:0], a[15:0], psw);
        adj_aw = j[15:0];
        adj_psw = j[31:16];
        cond = v35_cond(psw, cc);
    end
endmodule
