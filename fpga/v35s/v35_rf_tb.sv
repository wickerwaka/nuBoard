`timescale 1ns/1ps

// The Verilator bench top for the register file, the EA adder and the ALU (HDL plan, Phase D:
// D1, D2): the EU's decode (eu_decode), operand record (v35_operands) and the instruction's
// function as the EU applies it (v35_execute at the start, v35_deliver at each read's delivery,
// v35_wdata at each write's issue) from v35_eu_pkg, combinational. v35_rf_tb.cpp sequences an
// instruction: the start, then its cycles in order (a read's delivered word in, a write's datum
// out), from the vectors of validation/v35s/chains/rtl_vectors.py's regfile_vectors (the
// functional reference's walk of the corpus, random register files, random operands per ALU
// form) and of sst.py (SingleStepTests). Build: fpga/v35s/build_rf_tb.sh (build/fpga/v35s/rf-tb/).
module v35_rf_tb
    import v35_decoder_pkg::*;
    import v35_eu_pkg::*;
(
    input  wire [210:0] rf_in,              // v35_rf_t: the register file before the step
    input  wire [85:0]  x_in,               // v35_fx_t: the instruction's context before it
    input  wire [47:0]  code,               // the instruction's bytes, the opcode in [47:40]
    input  wire [15:0]  pc,                 // its code offset
    input  wire [15:0]  code_org,           // the IP of offset 0
    input  wire [3:0]   mutate,             // the package's mutations
    // a read cycle delivered: its request's width, address parity, I/O, its last cycle, the
    // bus word; the shift count (the record's)
    input  wire         d_w2,
    input  wire         d_odd,
    input  wire         d_io,
    input  wire         d_last,
    input  wire [15:0]  d_data,
    input  wire [8:0]   d_count,
    // a cycle issued: its request's kind (V35_RK_*), width, address parity, the first cycle
    // of an odd word, the request's last cycle
    input  wire [2:0]   w_kind,
    input  wire         w_w2,
    input  wire         w_odd,
    input  wire         w_first,
    input  wire         w_last,
    output logic        ok,                 // the decode knows the opcode
    output logic [2:0]  len,                // its length
    output logic [196:0] opr,               // v35_opnd_t (fmt, tmpl 0: the start's)
    output logic        obad,               // the function is not built (V35_EE_FUNC)
    output logic [210:0] s_rf,              // the start: the register file after v35_execute ...
    output logic [85:0] s_x,                // ... the context
    output logic        s_trap,             // ... a divide error
    output logic [210:0] d_rf,              // the delivery: the register file after ...
    output logic [85:0] d_x,
    output logic        d_tgt_v,            // ... RET's target
    output logic [15:0] d_tgt,
    output logic        d_trap,
    output logic [15:0] w_data,             // the issue: the cycle's datum ...
    output logic [85:0] w_x                 // ... the context after it (PUSH R's index)
);
    always_comb begin
        v35_op_t op;
        v35_opnd_t r;
        v35_fx_t x, xd, xw;
        op = eu_decode(code);
        ok = op.ok;
        len = op.length;
        r = v35_operands(v35_rf_t'(rf_in), code, pc, op, mutate, obad);
        opr = r;
        s_rf = v35_execute(v35_rf_t'(rf_in), code, op, r, code_org, mutate, x, s_trap);
        s_x = x;
        d_rf = v35_deliver(v35_rf_t'(rf_in), v35_fx_t'(x_in), d_w2, d_odd, d_io, d_last, d_data,
                           d_count, code_org, mutate, xd, d_tgt_v, d_tgt, d_trap);
        d_x = xd;
        w_data = v35_wdata(v35_rf_t'(rf_in), v35_fx_t'(x_in), w_kind, w_w2, w_odd, w_first,
                           mutate);
        xw = v35_fx_t'(x_in);
        if (w_last && int'(w_kind) == V35_RK_WRITE)
            xw.wk = xw.wk + 3'd1;
        w_x = xw;
    end
endmodule
