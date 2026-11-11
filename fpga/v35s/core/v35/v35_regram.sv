`timescale 1ns/1ps

// V35S core v2: the register RAM (docs/v35s-core-v2.md, "Function path"; stage S3). The V35's
// eight register banks (and, later, the data RAM it overlays) as internal RAM: 256 bytes in
// two 128 x 8 halves, even bytes and odd bytes, so a 16-bit register is one word at an even
// slot and a byte register one half. The bank is PSW.RB; a bank's 32 bytes hold the word
// registers at slot offsets 1Eh (AW) down to 10h (IY) and the segment registers at 0Eh (DS1)
// down to 08h (DS0) (validation/v35s/model/eu.py:17-18): the word address is {RB, slot[4:1]}.
//
// Ports: A reads and writes (the operand / result register), B reads (the second operand,
// the EA's base, SP). (MX0) Each read port's address is registered at `ce_b` (a block RAM's
// read address register: the microinstruction names the registers it reads in its first
// tick), the data is the word at that address in the clock's second tick; the write is at
// `ce_a` (one word or one half), so a word reads what the words before it wrote. Two copies of each half, one per read port, so each copy is a simple
// dual-port RAM (one write, one read).
//
// Registered state (widths) and the model variables it replaces:
//   ea 64 x 16, eb 64 x 16 ... as 4 x 128 x 8 RAM    the register banks (v35_rf_t's flops in the
//                                                     old core; the model's regs dict)
//   ra_q 7, rb_q 7                                    the read address registers
// Reset contents: zero but PS = FFFFh in every bank (the chain wrapper's init_s: PS FFFFh; the
// prelude loads the rest; the PSW's RB 7 at reset is the EU's).
module v35_regram (
    input  wire        clock,
    input  wire        ce_a,
    input  wire        ce_b,          // (S7b) the CPU clock's second tick (the pipeline registers)
    // port A: read address for the next clock, write (at ce_a)
    input  wire [6:0]  ra_next,     // {bank, slot[4:1]}
    input  wire        wa_en,
    input  wire [6:0]  wa_addr,
    input  wire [1:0]  wa_be,       // byte enables {odd, even}
    input  wire [15:0] wa_data,
    output wire [15:0] ra_data,
    // port B: read address for the next clock
    input  wire [6:0]  rb_next,
    output wire [15:0] rb_data
);
    reg [7:0] ae [0:127];           // port A's copy, even bytes
    reg [7:0] ao [0:127];           //               odd bytes
    reg [7:0] be [0:127];           // port B's copy
    reg [7:0] bo [0:127];
    // (MX5) the read ports are read at ce_b (the data a register from then on): every reader is
    // in tick B (ce_b to ce_a: the sources, the ALU, the EA, the write port), and no write lands
    // between a ce_b and the next ce_a, so the data read at ce_b is what the old port (the
    // address registered at ce_b, the data the array's current contents) shows all through tick
    // B. The RAM reads before it writes (no write-through on the read port: README "MX5")
    reg [15:0] ra_d = 16'd0;
    reg [15:0] rb_d = 16'd0;

    // PS (slot 0Ch: word 6 of every bank) = FFFFh, the rest 0
    localparam logic [15:0] PS_RESET = 16'hFFFF;
    integer i;
    initial begin
        for (i = 0; i < 128; i = i + 1) begin
            ae[i] = (i[3:0] == 4'd6) ? PS_RESET[7:0] : '0;
            ao[i] = (i[3:0] == 4'd6) ? PS_RESET[15:8] : '0;
            be[i] = (i[3:0] == 4'd6) ? PS_RESET[7:0] : '0;
            bo[i] = (i[3:0] == 4'd6) ? PS_RESET[15:8] : '0;
        end
    end

    always_ff @(posedge clock) begin
        if (ce_a) begin
            if (wa_en && wa_be[0]) begin
                ae[wa_addr] <= wa_data[7:0];
                be[wa_addr] <= wa_data[7:0];
            end
            if (wa_en && wa_be[1]) begin
                ao[wa_addr] <= wa_data[15:8];
                bo[wa_addr] <= wa_data[15:8];
            end
        end
        // (MX0) the read addresses latch at ce_b: the word's register selectors are decided
        // in its first tick (the ROM word is a register from ce_a), the data is read in its
        // second; a write at the last ce_a is read back (no forwarding needed)
        if (ce_b) begin
            ra_d <= {ao[ra_next], ae[ra_next]};
            rb_d <= {bo[rb_next], be[rb_next]};
        end
    end

    assign ra_data = ra_d;
    assign rb_data = rb_d;

endmodule
