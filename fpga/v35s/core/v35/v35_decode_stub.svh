// V35S core v2, stage S2: a HAND-WRITTEN STUB of the decode table (no generator), for the
// opcodes the S2 families (F0, F0w, F1, F2) and the chain image's prelude and reset vector
// use. S1's generated v35_decode_tbl.svh / v35_class_tbl.svh replace it; the field names are
// the plan's format word (docs/v35s-core-v2.md, "Modules and the state they own", loader:
// class, len, modrm, mod, reg, rm, imm, disp, w, dir, grp, fixed, page, seg, rep, cond), plus
// the stub-only `fn` (the scripted EU's operation selector, S2 only) and the decode attributes
// the S2 rules read (`port`, `regonly`, `ilock`).
//
// The only place in fpga/v35s/core/v35/ where opcode values appear.
//
// Sources: the frozen templates.decode (validation/v35s/chains/sim/templates.py: class, length,
// imm_bytes, modrm) and the V30 encodings; the class integers are fit.json's (md5
// de193740eaf1dee0862d2220ae084909), cited per entry in v35_class_stub below.

// ------------------------------------------------------------------ classes (stub subset)
localparam logic [6:0] CLS_TRAP_NOP = 7'd0;     // not modelled: two clocks, no bus
localparam logic [6:0] CLS_REG = 7'd1;          // reg: NOP (XCH AW,AW), MOV r16,r/m16, MOV sreg,r/m16
localparam logic [6:0] CLS_IMM = 7'd2;          // imm: MOV r,imm; ADD r/m16,imm16 (81 /0, register)
localparam logic [6:0] CLS_SHIFT_CL = 7'd3;     // shift_cl: SHL r/m16,CL (D3 /4, register)
localparam logic [6:0] CLS_OUT = 7'd4;          // out: OUT imm8,AL; OUT DW,AL
localparam logic [6:0] CLS_PUSH = 7'd5;         // push: PUSH r16
localparam logic [6:0] CLS_STORE = 7'd6;        // store: MOV [d16],AW (A3)
localparam logic [6:0] CLS_PREFIX = 7'd7;       // prefix: segment override
localparam logic [6:0] CLS_HALT = 7'd8;         // halt
localparam logic [6:0] CLS_BRANCH_FAR = 7'd9;   // branch_far: BR far (EA), the reset vector
localparam logic [6:0] CLS_STORE_IMM = 7'd10;   // store_imm: MOV r/m,imm (C6 /0, C7 /0)
localparam logic [6:0] CLS_PUSH_IMM = 7'd11;    // push_imm: PUSH imm16 (68)
localparam logic [6:0] CLS_POP_PSW = 7'd12;     // pop_psw: POP PSW (9D)

// ------------------------------------------------------------------ scripted-EU functions
localparam logic [4:0] FN_NONE = 5'd0;
localparam logic [4:0] FN_MOV_RM = 5'd1;        // reg ← r/m (register form)
localparam logic [4:0] FN_MOV_SREG = 5'd2;      // sreg ← r/m (register form)
localparam logic [4:0] FN_MOV_IMM = 5'd3;       // reg ← imm (w selects the width)
localparam logic [4:0] FN_ADD_IMM = 5'd4;       // r/m ← r/m + imm (register form)
localparam logic [4:0] FN_SHL = 5'd5;           // r/m ← r/m << CL (register form)
localparam logic [4:0] FN_OUT_IMM = 5'd6;       // port imm8 ← AL
localparam logic [4:0] FN_OUT_DW = 5'd7;        // port DW ← AL
localparam logic [4:0] FN_PUSH_R = 5'd8;        // [SS:SP-2] ← reg
localparam logic [4:0] FN_STORE_AW = 5'd9;      // [DS0:d16] ← AW
localparam logic [4:0] FN_PREFIX = 5'd10;
localparam logic [4:0] FN_HALT = 5'd11;
localparam logic [4:0] FN_JMPF = 5'd12;         // PS:PC ← seg:off
localparam logic [4:0] FN_STORE_IMM = 5'd13;    // [DS0:d16] ← imm (mod 00, rm 110 only)
localparam logic [4:0] FN_PUSH_IMM = 5'd14;     // [SS:SP-2] ← imm16
localparam logic [4:0] FN_POP_PSW = 5'd15;      // PSW ← [SS:SP]

// ------------------------------------------------------------------ the format word
typedef struct packed {
    logic [6:0] cls;        // class
    logic [2:0] len;        // bytes without a ModR/M displacement (the loader adds it)
    logic       modrm;      // a ModR/M byte follows the opcode
    logic [1:0] mod;        // ModR/M fields: filled in by the loader on the ModR/M take
    logic [2:0] rg;         //   (`reg` is a keyword; a non-ModR/M form: its opcode register)
    logic [2:0] rm;
    logic [1:0] imm;        // immediate bytes (a port byte is not one)
    logic [1:0] disp;       // displacement / direct-address bytes (A3: 2; ModR/M forms: loader)
    logic       w;          // word operand
    logic       dir;        // d bit
    logic       grp;        // a group opcode (the operation in reg)
    logic       fixed;      // fixed-lookup group form
    logic       page;       // 0F page
    logic [2:0] seg;        // a prefix's segment: 0 DS1, 1 PS, 2 SS, 3 DS0 (+4: valid)
    logic [1:0] rep;
    logic [3:0] cond;
    // decode attributes the S2 rules read (generated in S1)
    logic       port;       // port-form IN/OUT (a port byte: wlatch_cls=port, io_older)
    logic       mem;        // a memory operand (no ModR/M look-ahead in S2: A3 and C6/C7)
    logic       ilock;      // io_interlock=reg_pfx: a register-only class held by a waiting OUT
    logic       ilock_reg;  // ... of INTERLOCK["reg"] (prefix excluded: wlatch_imm=reg_last,
                            //     io_take_nx's class reg is `cls == CLS_REG`)
    logic [4:0] fn;         // stub only: the scripted EU's operation
} fmt_t;

function automatic fmt_t v35_decode(input logic [7:0] op);
    fmt_t f;
    f = '0;
    f.cls = CLS_TRAP_NOP;
    f.len = 3'd1;
    f.fn = FN_NONE;
    case (op)
        8'h90: begin f.cls = CLS_REG; f.w = 1'b1; end                       // NOP
        8'h8B: begin f.cls = CLS_REG; f.len = 3'd2; f.modrm = 1'b1; f.w = 1'b1;
                     f.dir = 1'b1; f.fn = FN_MOV_RM; end
        8'h8E: begin f.cls = CLS_REG; f.len = 3'd2; f.modrm = 1'b1; f.w = 1'b1;
                     f.dir = 1'b1; f.fn = FN_MOV_SREG; end
        8'hB0, 8'hB1, 8'hB2, 8'hB3, 8'hB4, 8'hB5, 8'hB6, 8'hB7:
               begin f.cls = CLS_IMM; f.len = 3'd2; f.imm = 2'd1; f.rg = op[2:0];
                     f.fn = FN_MOV_IMM; end
        8'hB8, 8'hB9, 8'hBA, 8'hBB, 8'hBC, 8'hBD, 8'hBE, 8'hBF:
               begin f.cls = CLS_IMM; f.len = 3'd3; f.imm = 2'd2; f.rg = op[2:0];
                     f.w = 1'b1; f.fn = FN_MOV_IMM; end
        8'h81: begin f.cls = CLS_IMM; f.len = 3'd4; f.modrm = 1'b1; f.imm = 2'd2;
                     f.w = 1'b1; f.grp = 1'b1; f.fn = FN_ADD_IMM; end
        8'hD3: begin f.cls = CLS_SHIFT_CL; f.len = 3'd2; f.modrm = 1'b1; f.w = 1'b1;
                     f.grp = 1'b1; f.fn = FN_SHL; end
        8'hE6: begin f.cls = CLS_OUT; f.len = 3'd2; f.port = 1'b1; f.fn = FN_OUT_IMM; end
        8'hEF: begin f.cls = CLS_OUT; f.w = 1'b1; f.fn = FN_OUT_DW; end
        8'h50, 8'h51, 8'h52, 8'h53, 8'h54, 8'h55, 8'h56, 8'h57:
               begin f.cls = CLS_PUSH; f.rg = op[2:0]; f.w = 1'b1; f.fn = FN_PUSH_R; end
        8'hA3: begin f.cls = CLS_STORE; f.len = 3'd3; f.disp = 2'd2; f.w = 1'b1; f.mem = 1'b1;
                     f.fn = FN_STORE_AW; end
        8'h26: begin f.cls = CLS_PREFIX; f.seg = 3'd4; f.fn = FN_PREFIX; end   // DS1
        8'h2E: begin f.cls = CLS_PREFIX; f.seg = 3'd5; f.fn = FN_PREFIX; end   // PS
        8'h36: begin f.cls = CLS_PREFIX; f.seg = 3'd6; f.fn = FN_PREFIX; end   // SS
        8'h3E: begin f.cls = CLS_PREFIX; f.seg = 3'd7; f.fn = FN_PREFIX; end   // DS0
        8'hF4: begin f.cls = CLS_HALT; f.fn = FN_HALT; end
        8'hEA: begin f.cls = CLS_BRANCH_FAR; f.len = 3'd5; f.fn = FN_JMPF; end
        8'hC7: begin f.cls = CLS_STORE_IMM; f.len = 3'd4; f.modrm = 1'b1; f.imm = 2'd2;
                     f.w = 1'b1; f.grp = 1'b1; f.mem = 1'b1; f.fn = FN_STORE_IMM; end
        8'hC6: begin f.cls = CLS_STORE_IMM; f.len = 3'd3; f.modrm = 1'b1; f.imm = 2'd1;
                     f.grp = 1'b1; f.mem = 1'b1; f.fn = FN_STORE_IMM; end
        8'h68: begin f.cls = CLS_PUSH_IMM; f.len = 3'd3; f.imm = 2'd2; f.w = 1'b1;
                     f.fn = FN_PUSH_IMM; end
        8'h6A: begin f.cls = CLS_PUSH_IMM; f.len = 3'd2; f.imm = 2'd1; f.w = 1'b1;
                     f.fn = FN_PUSH_IMM; end                       // PUSH imm8 (sign-extended)
        8'h9D: begin f.cls = CLS_POP_PSW; f.w = 1'b1; f.fn = FN_POP_PSW; end
        default: ;
    endcase
    // io_interlock=reg_pfx (eu.INTERLOCK): reg, imm, shift_imm, shift_cl, mul, prefix
    f.ilock = (f.cls == CLS_REG || f.cls == CLS_IMM || f.cls == CLS_SHIFT_CL
               || f.cls == CLS_PREFIX) && !f.mem;
    f.ilock_reg = f.ilock && f.cls != CLS_PREFIX;
    return f;
endfunction

// The displacement bytes a ModR/M byte adds (mod 00 rm 110: d16; mod 01: d8; mod 10: d16).
/* verilator lint_off UNUSEDSIGNAL */
function automatic logic [1:0] v35_modrm_disp(input logic [7:0] m);
    case (m[7:6])
        2'b00: v35_modrm_disp = m[2:0] == 3'b110 ? 2'd2 : 2'd0;
        2'b01: v35_modrm_disp = 2'd1;
        2'b10: v35_modrm_disp = 2'd2;
        default: v35_modrm_disp = 2'd0;
    endcase
endfunction
/* verilator lint_on UNUSEDSIGNAL */

// ------------------------------------------------------------------ class integers (stub)
// The class-table integers the front end reads outside rows (fit.json "cost"; absent = 0).
typedef struct packed {
    logic [2:0] nx;         // clocks from the last operand take to the next IR load
    logic [2:0] nx0;        // ... from the start of a form without operand bytes
    logic [1:0] wb;         // write-back clocks a wbsync successor waits for
    logic [1:0] hphase;     // unit_hold: the first held exec clock
    logic [1:0] lead;       // I/O: the setup's last clocks that no longer hold fetches
    logic [1:0] relatch;    // port_latch=relatch
} cls_t;

function automatic cls_t v35_class_stub(input logic [6:0] cls);
    cls_t c;
    c = '0;
    case (cls)
        CLS_REG: c.nx = 3'd1;                               // reg.nx 1
        CLS_SHIFT_CL: begin c.wb = 2'd2; c.hphase = 2'd2; end   // shift_cl.wb 2, .hphase 2
        CLS_OUT: begin c.lead = 2'd2; c.relatch = 2'd3; end     // out.lead 2, .relatch 3
        CLS_POP_PSW: c.wb = 2'd2;                           // pop_psw.wb 2
        default: ;
    endcase
    return c;
endfunction
