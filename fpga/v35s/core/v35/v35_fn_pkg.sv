`timescale 1ns/1ps

// V35S core v2: the function package (docs/v35s-core-v2.md, "Function path"; stage S3). The
// pure functions of the datapath (v35_eu.sv), copied from the old core's v35_eu_pkg
// (fpga/v35s/core/v35_eu.sv: v35_szp 1186, v35_alu 1199, v35_shift 1247, v35_mul 1316,
// v35_cond 1404, v35_bcd8 1652, v35_bit1 1699, v35_rot4 1713) with the `mut` (mutation) argument
// removed, and rewritten where the old function read opcode bytes or the flat register file:
//   v35_adjust   ADJ4A / ADJ4S / ADJBA / ADJBS (1609) by the decode's sub-operation (fmt.aop),
//                on AW and the PSW instead of v35_rf_t;
//   v35_div_*    the divider as a restoring divider, one step per clock (the sequencer runs it
//                under the divide's exec clocks): v35_div_init (the pre-check, the magnitudes),
//                v35_div_step (one quotient bit), v35_div_fin (signs, the flags, the trap);
//                v35_div (the old one-shot function, for the bench's reference only) iterates
//                them;
//   v35_ea_off   the memory operand's offset from the EA mode's base and index register values
//                (v35_eu reads them through the register RAM's ports) and the displacement.
// No opcode byte is compared here: the decode table's format bits (v35_pkg::v35_fmt_t) select
// the operation.
package v35_fn_pkg;
    // (the functions copied from v35_eu_pkg read only part of some arguments)
    /* verilator lint_off UNUSEDSIGNAL */

    localparam int V35_PSW_CY = 0, V35_PSW_P = 2, V35_PSW_AC = 4, V35_PSW_Z = 6,
                   V35_PSW_S = 7, V35_PSW_IE = 9, V35_PSW_DIR = 10, V35_PSW_V = 11;

    // S Z P of a result of width w
    function automatic logic [15:0] v35_szp(input logic [15:0] psw0, input logic [15:0] r,
                                            input logic w);
        logic [15:0] psw;
        psw = psw0;
        psw[V35_PSW_S] = w ? r[15] : r[7];
        psw[V35_PSW_Z] = w ? r == 16'd0 : r[7:0] == 8'd0;
        psw[V35_PSW_P] = ~^r[7:0];
        v35_szp = psw;
    endfunction

    // the ALU: op the 00-3F block's / the 80-83 group's bits 5:3 (ADD OR ADC SBB AND SUB XOR
    // CMP), w the word form; the result (CMP's: the difference) and the PSW: CY V AC S Z P
    // written, the logic operations clearing CY V AC (undefined_flags.md: AC always 0)
    function automatic logic [15:0] v35_alu(input logic [2:0] op, input logic w,
                                            input logic [15:0] a0, input logic [15:0] b0,
                                            input logic [15:0] psw0, output logic [15:0] psw);
        logic [16:0] r;
        logic [15:0] a, b, m, msb, res;
        logic cin, cy, v, ac;
        m = w ? 16'hFFFF : 16'h00FF;
        msb = w ? 16'h8000 : 16'h0080;
        a = a0 & m;
        b = b0 & m;
        cin = (op == 3'd2 || op == 3'd3) && psw0[V35_PSW_CY];
        cy = 1'b0;
        v = 1'b0;
        ac = 1'b0;
        case (op)
            3'd0, 3'd2: begin
                r = {1'b0, a} + {1'b0, b} + {16'd0, cin};
                v = |((a ^ r[15:0]) & (b ^ r[15:0]) & msb);
            end
            3'd3, 3'd5, 3'd7: begin
                r = {1'b0, a} - {1'b0, b} - {16'd0, cin};
                v = |((a ^ b) & (a ^ r[15:0]) & msb);
            end
            3'd1: r = {1'b0, a | b};
            3'd4: r = {1'b0, a & b};
            default: r = {1'b0, a ^ b};
        endcase
        if (op != 3'd1 && op != 3'd4 && op != 3'd6) begin
            cy = w ? r[16] : r[8];
            ac = a[4] ^ b[4] ^ r[4];
        end
        res = r[15:0] & m;
        psw = v35_szp(psw0, res, w);
        psw[V35_PSW_CY] = cy;
        psw[V35_PSW_V] = v;
        psw[V35_PSW_AC] = ac;
        v35_alu = res;
    endfunction

    // the shift group (D0-D3, C0/C1; the reg field): ROL ROR ROLC RORC SHL SHR SHL (6, the
    // undocumented alias) SHRA by n, the full count (shift_count_mask=cl8). A count of 0
    // changes nothing; the rotates are periodic in the width (ROLC / RORC in the width + 1),
    // the shifts settle after width + 1. CY the last bit out; V from the final state (the
    // shift-V law: left ops MSB ^ CY, right ops the two top bits); the shifts write S Z P and
    // clear AC, the rotates leave them.
    function automatic logic [15:0] v35_shift(input logic [2:0] op, input logic w,
                                              input logic [15:0] a0, input logic [8:0] n,
                                              input logic [15:0] psw0, output logic [15:0] psw);
        logic [15:0] a, m, msb, msb1;
        logic cy, c;
        int k, nb;
        psw = psw0;
        if (n == 9'd0)
            return a0;
        nb = w ? 16 : 8;
        m = w ? 16'hFFFF : 16'h00FF;
        msb = w ? 16'h8000 : 16'h0080;
        msb1 = msb >> 1;
        a = a0 & m;
        cy = psw0[V35_PSW_CY];
        case (op)
            3'd0, 3'd1: k = int'(n) % nb;
            3'd2, 3'd3: k = int'(n) % (nb + 1);
            default: k = int'(n) > nb ? nb + 1 : int'(n);
        endcase
        for (int i = 0; i < 17; i++) begin
            if (i < k) begin
                case (op)
                    3'd0: a = ((a << 1) | {15'd0, |(a & msb)}) & m;
                    3'd1: a = (a >> 1) | (a[0] ? msb : 16'd0);
                    3'd2: begin
                        c = |(a & msb);
                        a = ((a << 1) | {15'd0, cy}) & m;
                        cy = c;
                    end
                    3'd3: begin
                        c = a[0];
                        a = (a >> 1) | (cy ? msb : 16'd0);
                        cy = c;
                    end
                    3'd5: begin
                        cy = a[0];
                        a = a >> 1;
                    end
                    3'd7: begin
                        cy = a[0];
                        a = (a >> 1) | (a & msb);
                    end
                    default: begin
                        cy = |(a & msb);
                        a = (a << 1) & m;
                    end
                endcase
            end
        end
        if (op == 3'd0)
            cy = a[0];
        else if (op == 3'd1)
            cy = |(a & msb);
        psw[V35_PSW_CY] = cy;
        if (op == 3'd0 || op == 3'd2 || op == 3'd4 || op == 3'd6)
            psw[V35_PSW_V] = |(a & msb) ^ cy;
        else
            psw[V35_PSW_V] = |(a & msb) ^ |(a & msb1);
        if (op[2]) begin
            psw = v35_szp(psw, a, w);
            psw[V35_PSW_AC] = 1'b0;
        end
        v35_shift = a;
    endfunction

    // MULU / MUL: the double-width product ([15:0] for a byte form). CY = V = the high half is
    // not the low half's extension; MULU leaves S Z AC P, MUL writes them as the flags of the
    // low half added to itself (undefined_flags.md)
    function automatic logic [31:0] v35_mul(input logic sgn, input logic w,
                                            input logic [15:0] a, input logic [15:0] b,
                                            input logic [15:0] psw0, output logic [15:0] psw);
        logic [31:0] p, sa, sb;
        logic [15:0] lo, f;
        logic ext;
        psw = psw0;
        if (w) begin
            sa = sgn ? {{16{a[15]}}, a} : {16'd0, a};
            sb = sgn ? {{16{b[15]}}, b} : {16'd0, b};
            p = sa * sb;
            lo = p[15:0];
            ext = sgn ? p[31:16] != {16{p[15]}} : p[31:16] != 16'd0;
        end else begin
            sa = sgn ? {{24{a[7]}}, a[7:0]} : {24'd0, a[7:0]};
            sb = sgn ? {{24{b[7]}}, b[7:0]} : {24'd0, b[7:0]};
            p = {16'd0, 16'(sa * sb)};
            lo = {8'd0, p[7:0]};
            ext = sgn ? p[15:8] != {8{p[7]}} : p[15:8] != 8'd0;
        end
        if (sgn) begin
            void'(v35_alu(3'd0, w, lo, lo, psw0, f));
            psw[V35_PSW_S] = f[V35_PSW_S];
            psw[V35_PSW_Z] = f[V35_PSW_Z];
            psw[V35_PSW_AC] = f[V35_PSW_AC];
            psw[V35_PSW_P] = f[V35_PSW_P];
        end
        psw[V35_PSW_CY] = ext;
        psw[V35_PSW_V] = ext;
        v35_mul = p;
    endfunction

    // ---- the divider: restoring, one quotient bit per step ----
    // The state: the remainder (17 bits, the dividend's high half shifted in), the dividend's
    // low bits still to shift in (the quotient's bits enter behind them), the divisor's
    // magnitude, the operation (signed, word) and the signs. DIVU / DIV of num (DW:AW; a byte
    // form AW) by d (the old v35_div's law: the pre-check's flags and trap, the quotient's
    // sign, the remainder the dividend's sign).
    typedef struct packed {
        logic [16:0] r;         // the partial remainder
        logic [15:0] q;         // dividend low bits in, quotient bits out (LSB first in)
        logic [15:0] d;         // |divisor|
        logic        w;
        logic        sgn;
        logic        nneg;
        logic        dneg;
        logic        trap;      // the pre-check failed (the flags are its SUB's)
        logic [4:0]  n;         // steps left
        logic [15:0] hi;        // |num|'s high half (the pre-check's operand)
    } v35_div_t;

    function automatic v35_div_t v35_div_init(input logic sgn, input logic w,
                                              input logic [31:0] num, input logic [15:0] d0);
        v35_div_t s;
        logic [31:0] an;
        logic [15:0] ad;
        s = '0;
        s.w = w;
        s.sgn = sgn;
        if (w) begin
            s.nneg = sgn && num[31];
            s.dneg = sgn && d0[15];
            an = s.nneg ? 32'd0 - num : num;
            ad = s.dneg ? 16'd0 - d0 : d0;
            s.hi = an[31:16];
            s.r = {1'b0, an[31:16]};
            s.q = an[15:0];
            s.n = 5'd16;
        end else begin
            s.nneg = sgn && num[15];
            s.dneg = sgn && d0[7];
            an = {16'd0, s.nneg ? 16'd0 - num[15:0] : num[15:0]};
            ad = {8'd0, s.dneg ? 8'd0 - d0[7:0] : d0[7:0]};
            s.hi = {8'd0, an[15:8]};
            s.r = {9'd0, an[15:8]};
            s.q = {an[7:0], 8'd0};
            s.n = 5'd8;
        end
        s.d = ad;
        s.trap = s.hi >= ad;                        // the pre-check (d = 0 included)
        v35_div_init = s;
    endfunction

    // one restoring step: shift the next dividend bit in, subtract the divisor when it fits
    function automatic v35_div_t v35_div_step(input v35_div_t s0);
        v35_div_t s;
        logic [16:0] t;
        s = s0;
        if (s.n != 5'd0) begin
            t = {s.r[15:0], s.q[15]};
            s.q = {s.q[14:0], 1'b0};
            if (t >= {1'b0, s.d}) begin
                t = t - {1'b0, s.d};
                s.q[0] = 1'b1;
            end
            s.r = t;
            s.n = s.n - 5'd1;
        end
        v35_div_step = s;
    endfunction

    // the result once the steps are done: {remainder, quotient} ([15:8] / [7:0] of the low
    // word for a byte form), the PSW, the trap (the pre-check, or a signed quotient past
    // 2^(n-1) - 1)
    function automatic logic [31:0] v35_div_fin(input v35_div_t s, input logic [15:0] psw0,
                                                output logic [15:0] psw, output logic trap);
        logic [15:0] q, r;
        psw = psw0;
        trap = s.trap;
        if (s.trap) begin
            void'(v35_alu(3'd5, s.w, s.hi, s.d, psw0, psw));
            return 32'd0;
        end
        q = s.w ? s.q : {8'd0, s.q[7:0]};
        r = s.w ? s.r[15:0] : {8'd0, s.r[7:0]};
        if (!s.sgn) begin
            void'(v35_alu(3'd5, s.w, s.hi, s.d, psw0, psw));
        end else begin
            psw = v35_szp(psw0, q, s.w);
            psw[V35_PSW_CY] = 1'b0;
            psw[V35_PSW_AC] = 1'b0;
            psw[V35_PSW_V] = 1'b0;
            if (s.w ? q > 16'h7FFF : q > 16'h007F) begin
                trap = 1'b1;
                return 32'd0;
            end
            if (s.nneg != s.dneg)
                q = 16'd0 - q;
            if (s.nneg)
                r = 16'd0 - r;
        end
        v35_div_fin = s.w ? {r, q} : {16'd0, r[7:0], q[7:0]};
    endfunction

    // the whole divide (the bench's reference and the shape of the old one-shot v35_div)
    function automatic logic [31:0] v35_div(input logic sgn, input logic w,
                                            input logic [31:0] num, input logic [15:0] d0,
                                            input logic [15:0] psw0, output logic [15:0] psw,
                                            output logic trap);
        v35_div_t s;
        s = v35_div_init(sgn, w, num, d0);
        for (int i = 0; i < 16; i++)
            s = v35_div_step(s);
        v35_div = v35_div_fin(s, psw0, psw, trap);
    endfunction

    // Bcond's 16 conditions (the 70-7F row's low nibble, v35_fmt_t.ccode)
    function automatic logic v35_cond(input logic [15:0] psw, input logic [3:0] cc);
        logic t, cy, z, s, v, p;
        cy = psw[V35_PSW_CY];
        z = psw[V35_PSW_Z];
        s = psw[V35_PSW_S];
        v = psw[V35_PSW_V];
        p = psw[V35_PSW_P];
        case (cc[3:1])
            3'd0: t = v;
            3'd1: t = cy;
            3'd2: t = z;
            3'd3: t = cy || z;
            3'd4: t = s;
            3'd5: t = p;
            3'd6: t = s ^ v;
            default: t = (s ^ v) || z;
        endcase
        v35_cond = t ^ cc[0];
    endfunction

    // The adjusts as the V20 suite has them (funcref.Cpu._adjust), on AW and the PSW; aop the
    // decode's sub-operation (0 ADJ4A, 1 ADJ4S, 2 ADJBA, 3 ADJBS): ADJ4A / ADJ4S correct the low
    // digit by 6 when it exceeds 9 or AC is set and the high by 60h when CY is set or AL exceeds
    // 99h (9Fh with AC set); ADJBA / ADJBS add / subtract 6 to AL and 1 to AH when the low digit
    // exceeds 9 or AC is set, AL's high digit cleared; the flags the ALU's of AL +/- the
    // correction, CY and AC the decisions. Returns {PSW, AW}.
    function automatic logic [31:0] v35_adjust(input logic [1:0] aop, input logic [15:0] aw,
                                               input logic [15:0] psw0);
        logic [15:0] res, psw;
        logic [7:0] al, ah;
        logic sub, lo, hi, af, cf;
        logic [15:0] awo;
        al = aw[7:0];
        ah = aw[15:8];
        af = psw0[V35_PSW_AC];
        cf = psw0[V35_PSW_CY];
        sub = aop[0];
        awo = aw;
        if (!aop[1]) begin
            lo = al[3:0] > 4'd9 || af;
            hi = cf || {1'b0, al} > (af ? 9'h09F : 9'h099);
            res = v35_alu(sub ? 3'd5 : 3'd0, 1'b0, {8'd0, al},
                          (lo ? 16'h0006 : 16'h0000) | (hi ? 16'h0060 : 16'h0000), psw0, psw);
            awo[7:0] = res[7:0];
        end else begin
            lo = al[3:0] > 4'd9 || af;
            hi = lo;
            void'(v35_alu(sub ? 3'd5 : 3'd0, 1'b0, {8'd0, al}, lo ? 16'd6 : 16'd0, psw0, psw));
            if (lo) begin
                ah = sub ? ah - 1'b1 : ah + 1'b1;
                al = sub ? al - 8'(6) : al + 8'(6);
            end
            awo = {ah, 4'd0, al[3:0]};
        end
        psw[V35_PSW_CY] = hi;
        psw[V35_PSW_AC] = lo;
        v35_adjust = {psw, awo};
    endfunction

    // ADD4S / SUB4S's byte step (funcref.bcd_add8 / bcd_sub8, nuV30's law): a = the destination
    // byte, b = the source byte; {the carry / borrow (the high digit's adjust decision), the
    // byte's zero term (the V30 stage), the byte}
    function automatic logic [9:0] v35_bcd8(input logic sub, input logic [7:0] a,
                                            input logic [7:0] b, input logic cin);
        logic [4:0] lo, hi, dec;
        logic [3:0] dlo0, dlo, dhi0, dhi;
        logic c1, c2, fl, wrapb, fire, z;
        if (!sub) begin
            lo = {1'b0, a[3:0]} + {1'b0, b[3:0]} + {4'd0, cin};
            c1 = lo[4];
            dlo0 = lo[3:0];
            c2 = dlo0 > 4'd9;
            dlo = (c1 || c2) ? dlo0 + 4'd6 : dlo0;
            hi = {1'b0, a[7:4]} + {1'b0, b[7:4]} + {4'd0, c1} + {4'd0, c2};
            dhi0 = hi[3:0];
            fire = {1'b0, a[7:4]} + {1'b0, b[7:4]} + {4'd0, c1 | c2} > 5'd9;
            dhi = fire ? dhi0 + 4'd6 : dhi0;
            z = {1'b0, a} + {1'b0, b} + {8'd0, cin} == 9'd0;
        end else begin
            lo = {1'b0, a[3:0]} - {1'b0, b[3:0]} - {4'd0, cin};
            c1 = lo[4];
            dlo0 = lo[3:0];
            c2 = dlo0 > 4'd9;
            fl = c1 || c2;
            dlo = fl ? dlo0 - 4'd6 : dlo0;
            wrapb = fl && dlo0 < 4'd6;
            hi = {1'b0, a[7:4]} - {1'b0, b[7:4]} - {4'd0, c1} - {4'd0, wrapb};
            dhi0 = hi[3:0];
            dec = {1'b0, a[7:4]} - {1'b0, b[7:4]} - {4'd0, c1};
            fire = dec[4] || dec > 5'd9 || (dec[3:0] == 4'd9 && c2 && !c1);
            dhi = fire ? dhi0 - 4'd6 : dhi0;
            z = dec[3:0] == 4'd0 && dlo == 4'd0;
        end
        v35_bcd8 = {fire, z, dhi, dlo};
    endfunction

    // TEST1 / CLR1 / SET1 / NOT1 (the 0F second byte's bits 2:1) on the operand a with the
    // mask m: the result (TEST1: a) and the PSW (TEST1: S Z P of the masked value, CY AC V
    // cleared; the others none)
    function automatic logic [15:0] v35_bit1(input logic [7:0] sb, input logic [15:0] a,
                                             input logic [15:0] m, input logic w,
                                             input logic [15:0] psw0, output logic [15:0] psw);
        psw = psw0;
        case (sb[2:1])
            2'd0: begin
                psw = v35_szp(psw0, a & m, w);
                psw[V35_PSW_CY] = 1'b0;
                psw[V35_PSW_AC] = 1'b0;
                psw[V35_PSW_V] = 1'b0;
                v35_bit1 = a;
            end
            2'd1: v35_bit1 = a & ~m;
            2'd2: v35_bit1 = a | m;
            default: v35_bit1 = a ^ m;
        endcase
    endfunction

    // ROL4 / ROR4 on the byte a with AL: {AL, the operand} after (the data book's, the V35's:
    // AL's high digit kept; funcref.Cpu._page0f)
    function automatic logic [15:0] v35_rot4(input logic ror, input logic [7:0] a,
                                             input logic [7:0] al);
        v35_rot4 = ror ? {al[7:4], a[3:0], al[3:0], a[7:4]} : {al[7:4], a[7:4], a[3:0], al[3:0]};
    endfunction

    // The memory operand's offset of a ModR/M form (templates.RM): md / rm the ModR/M fields,
    // base / index the values of the mode's base and index registers (the register RAM's ports:
    // v35_ea_regs names them), disp the displacement bytes (d8 sign-extended; the direct form's
    // d16). bp: the mode is BP-based (the default segment SS).
    function automatic logic [15:0] v35_ea_off(input logic [1:0] md, input logic [2:0] rm,
                                               input logic [15:0] base, input logic [15:0] index,
                                               input logic [15:0] disp, output logic bp);
        logic [15:0] d;
        bp = (rm == 3'd2 || rm == 3'd3 || (rm == 3'd6 && md != 2'd0));
        d = md == 2'd1 ? {{8{disp[7]}}, disp[7:0]} : (md == 2'd2 ? disp : 16'd0);
        if (md == 2'd0 && rm == 3'd6)
            v35_ea_off = disp;                  // direct
        else if (!rm[2])
            v35_ea_off = base + index + d;      // BW / BP + IX / IY
        else
            v35_ea_off = base + d;              // IX, IY, BP, BW
    endfunction

    // The registers a ModR/M memory mode reads (REG16 indices: 3 BW, 5 BP, 6 IX, 7 IY): the
    // base (the only one for rm 4-7) and the index (rm 0-3). {index_v, index, base_v, base}
    function automatic logic [7:0] v35_ea_regs(input logic [1:0] md, input logic [2:0] rm);
        logic [2:0] b, i;
        logic bv, iv;
        bv = !(md == 2'd0 && rm == 3'd6);
        iv = !rm[2];
        case (rm)
            3'd0, 3'd1, 3'd7: b = 3'd3;         // BW
            3'd2, 3'd3, 3'd6: b = 3'd5;         // BP
            3'd4: b = 3'd6;                     // IX
            default: b = 3'd7;                  // IY (5)
        endcase
        i = rm[0] ? 3'd7 : 3'd6;                // IY / IX
        v35_ea_regs = {iv, i, bv, b};
    endfunction

    // ---- (MX0) the loops' steps: the shifter one step a word under the loop counter, the
    // multiplier one bit a word (the datapath runs them; v35_shift / v35_mul above are the
    // whole operation, kept for the function bench's reference)

    // one step of the shift group's operation op (the reg field) on a of width w, carry in cy:
    // {carry out, the result}
    function automatic logic [16:0] v35_shift1(input logic [2:0] op, input logic w,
                                               input logic [15:0] a0, input logic cy);
        logic [15:0] a, m, msb;
        logic c;
        m = w ? 16'hFFFF : 16'h00FF;
        msb = w ? 16'h8000 : 16'h0080;
        a = a0 & m;
        case (op)
            3'd0: begin c = |(a & msb); a = ((a << 1) | {15'd0, c}) & m; end
            3'd1: begin c = a[0]; a = (a >> 1) | (c ? msb : 16'd0); end
            3'd2: begin c = |(a & msb); a = ((a << 1) | {15'd0, cy}) & m; end
            3'd3: begin c = a[0]; a = (a >> 1) | (cy ? msb : 16'd0); end
            3'd5: begin c = a[0]; a = a >> 1; end
            3'd7: begin c = a[0]; a = (a >> 1) | (a & msb); end
            default: begin c = |(a & msb); a = (a << 1) & m; end
        endcase
        v35_shift1 = {c, a};
    endfunction

    // the flags after the loop (v35_shift's laws): CY the last bit out, V from the final state,
    // the shifts S Z P with AC cleared
    function automatic logic [15:0] v35_shift_fl(input logic [2:0] op, input logic w,
                                                 input logic [15:0] a, input logic cy,
                                                 input logic [15:0] psw0);
        logic [15:0] psw, msb, msb1;
        msb = w ? 16'h8000 : 16'h0080;
        msb1 = msb >> 1;
        psw = psw0;
        psw[V35_PSW_CY] = cy;
        if (op == 3'd0 || op == 3'd2 || op == 3'd4 || op == 3'd6)
            psw[V35_PSW_V] = |(a & msb) ^ cy;
        else
            psw[V35_PSW_V] = |(a & msb) ^ |(a & msb1);
        if (op[2]) begin
            psw = v35_szp(psw, a, w);
            psw[V35_PSW_AC] = 1'b0;
        end
        v35_shift_fl = psw;
    endfunction

    // the multiplier's state: the accumulator (the product's high part), the multiplier's
    // bits still to use (the product's low part enters from the top), the multiplicand's
    // magnitude, the product's sign
    typedef struct packed {
        logic [16:0] acc;
        logic [15:0] lo;
        logic [15:0] mc;
        logic        neg;
        logic        sgn;
    } v35_mul_t;

    function automatic v35_mul_t v35_mul_init(input logic sgn, input logic w,
                                              input logic [15:0] a, input logic [15:0] b);
        v35_mul_t s;
        logic na, nb;
        logic [15:0] ma, mb;
        logic [7:0] a8, b8;
        na = sgn && (w ? a[15] : a[7]);
        nb = sgn && (w ? b[15] : b[7]);
        a8 = na ? 8'd0 - a[7:0] : a[7:0];
        b8 = nb ? 8'd0 - b[7:0] : b[7:0];
        ma = w ? (na ? 16'd0 - a : a) : {8'd0, a8};
        mb = w ? (nb ? 16'd0 - b : b) : {8'd0, b8};
        s.acc = 17'd0;
        s.lo = mb;
        s.mc = ma;
        s.neg = na ^ nb;
        s.sgn = sgn;
        v35_mul_init = s;
    endfunction

    // one bit: add the multiplicand when the low bit is set, shift the pair right
    function automatic v35_mul_t v35_mul_step(input v35_mul_t s0);
        v35_mul_t s;
        logic [16:0] t;
        s = s0;
        t = s.lo[0] ? s.acc + {1'b0, s.mc} : s.acc;
        s.lo = {t[0], s.lo[15:1]};
        s.acc = {1'b0, t[16:1]};
        v35_mul_step = s;
    endfunction

    // the product after the steps (word: 16, byte: 8), negated when the signs differ; the
    // flags as v35_mul's
    function automatic logic [31:0] v35_mul_fin(input v35_mul_t s, input logic w,
                                                input logic [15:0] psw0, output logic [15:0] psw);
        logic [31:0] p;
        logic [15:0] lo, f, p16;
        logic ext;
        psw = psw0;
        if (w) begin
            p = {s.acc[15:0], s.lo};
            if (s.neg)
                p = 32'd0 - p;
            lo = p[15:0];
            ext = s.sgn ? p[31:16] != {16{p[15]}} : p[31:16] != 16'd0;
        end else begin
            p16 = {s.acc[7:0], s.lo[15:8]};
            if (s.neg)
                p16 = 16'd0 - p16;
            p = {16'd0, p16};
            lo = {8'd0, p16[7:0]};
            ext = s.sgn ? p16[15:8] != {8{p16[7]}} : p16[15:8] != 8'd0;
        end
        if (s.sgn) begin
            void'(v35_alu(3'd0, w, lo, lo, psw0, f));
            psw[V35_PSW_S] = f[V35_PSW_S];
            psw[V35_PSW_Z] = f[V35_PSW_Z];
            psw[V35_PSW_AC] = f[V35_PSW_AC];
            psw[V35_PSW_P] = f[V35_PSW_P];
        end
        psw[V35_PSW_CY] = ext;
        psw[V35_PSW_V] = ext;
        v35_mul_fin = p;
    endfunction

    /* verilator lint_on UNUSEDSIGNAL */
endpackage
