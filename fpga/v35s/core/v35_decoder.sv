`timescale 1ns/1ps

// V35S decoder (HDL plan, Phase C3): the loader's state and its methods, written from the
// frozen chain model (validation/v35s/chains/sim/frozen/decoder.py, the Decoder) and the spec
// (docs/v35s-chain-rtl-spec.md, A2 "Decoder", A3 "From the decoder").
//
// The decoder serves the EU's take steps from the queue and loads the next opcode into the
// IR (opcode_take=prefetch, bytes_per_clock=1, ir_port=False, modrm_commit=byte,
// modrm_mate=imm). Its methods run inside the EU's clock (v35_eu.sv): the EU calls take,
// commit, loads_after and start, the machine calls load_ir after the EU's tick and again in
// the post-issue pass. Every method that reads or changes the queue does so through the
// queue's op port (v35_queue.sv's ops: avail, take, commit, irload), which is the EU
// module's; this package holds the decoder's state type, the views of the other machines the
// two read (the queue's state between ops, the bus unit's before and after the choice), and
// the decoder's own bookkeeping as functions of the same names as the frozen methods.
//
// State (v35_dec_t, rtl_vectors.DFIELDS): the IR (its opcode's address; the byte is the
// queue's), the address of the next byte to leave the queue (the model's byte addresses,
// kept by the decoder), need, nx, ready_at as an offset, ir_hold, ea_end as an offset,
// modrm_next, and the ModR/M's word-mate as "the next byte is the mate" (the model's
// modrm_addr is only compared with the next byte's address less one).
package v35_decoder_pkg;
`include "v35_chain_params.svh"

    // ---- the queue's state the EU and the decoder read (v35_queue.sv's v35_qstate_t fields,
    // rtl_vectors.QVIEW, in this order MSB first)
    typedef struct packed {
        logic [V35_W_Q_COUNT-1:0]   count;
        logic                       latched;
        logic                       flag;
        logic                       rq_valid;
        logic [V35_W_Q_AGE-1:0]     rq_age;
        logic                       inflight;
        logic                       ab_valid;
        logic [V35_W_Q_AB_LEFT-1:0] ab_left;
        logic                       ab_this;
        logic                       retry;
        logic                       retry_loop;
        logic                       rt_valid;
        logic [V35_W_Q_OFF-1:0]     rt_off;
        logic                       shift_held;
        logic                       sh_valid;
        logic [V35_W_Q_OFF-1:0]     sh_off;
        logic                       dropped;
        logic                       drop_hold;
        logic                       b2b_now;
        logic                       arrived_now;
        logic                       take_now;
        logic                       take_prev;
        logic                       ir_now;
        logic                       latch_in_now;
    } v35_qview_t;

    // ---- the bus unit's state the EU reads (rtl_vectors.BVIEW, MSB first)
    typedef struct packed {
        logic [2:0] kind;           // the cycle on the bus (V35_K_NONE: idle)
        logic [2:0] pos;            // t - its start
        logic [2:0] len;            // its length
        logic       free;           // bus.free(t)
        logic       finf;           // a fetch in flight
        logic       in_wait;        // a memory cycle in a wait state
        logic       fprev;          // last_fetch_end == t - 1
        logic       wl;             // t < the data latch's busy end (wlatch)
        logic [2:0] fsince;         // t - last_fetch_end (0: a fetch runs, 7: 7 or more)
        logic       flen3;          // bus.length("fetch") == 3 (no memory waits)
    } v35_bview_t;

    // ---- the decoder's state (rtl_vectors.DFIELDS, MSB first)
    typedef struct packed {
        logic        ir_v;
        logic [19:0] ir_addr;
        logic [19:0] taddr;
        logic [2:0]  need;
        logic [1:0]  nx;
        logic [1:0]  ra_off;        // ready_at - t (clipped at 0)
        logic        ir_hold;       // ir_load=disp_data
        logic [1:0]  ea_off;        // ea_end - t (clipped): ea_ir_room's t < ea_end
        logic        modrm_next;
        logic        mate_next;
        logic        imm_reg;
        logic        stopped;
    } v35_dec_t;

    // the decoder's (and the EU's) state the queue reads with each op (v35_queue.sv's
    // v35_qsnap_t, rtl_vectors.DSNAP: ir, need0, ir_hold, ea, imm16 from bit 0)
    function automatic logic [4:0] dec_snap(input v35_dec_t d, input logic imm16);
        dec_snap = {imm16, d.ea_off != 2'd0, d.ir_hold, d.need == 3'd0, d.ir_v};
    endfunction

    // the clock's start: the offsets move on a clock
    function automatic v35_dec_t dec_begin(input v35_dec_t d);
        dec_begin = d;
        if (d.ra_off != 2'd0) dec_begin.ra_off = d.ra_off - 2'd1;
        if (d.ea_off != 2'd0) dec_begin.ea_off = d.ea_off - 2'd1;
    endfunction

    // Decoder.start: the EU starts an instruction of `length` bytes (the IR consumed); the
    // next opcode may load at once when it has no operand bytes (ready_at = t)
    function automatic v35_dec_t dec_start(input v35_dec_t d, input logic [2:0] length,
                                           input logic [1:0] nx, input logic modrm,
                                           input logic imm_reg);
        dec_start = d;
        dec_start.ir_v = 1'b0;
        dec_start.ir_addr = 20'd0;    // (canonical: no opcode held)
        dec_start.modrm_next = modrm;
        dec_start.mate_next = 1'b0;     // modrm_addr = None
        dec_start.imm_reg = imm_reg;
        dec_start.ea_off = 2'd0;        // ea_end = None
        dec_start.need = length - 3'd1;
        dec_start.nx = nx;
        dec_start.ra_off = 2'd0;
    endfunction

    // one byte of Decoder.take (the loop's body): the byte at taddr leaves the queue. mate:
    // it is the ModR/M's odd word-mate with operand bytes still to come after this call's k
    // (modrm_mate=imm); commit_one: it is the ModR/M byte (modrm_commit=byte)
    function automatic v35_dec_t dec_take_byte(input v35_dec_t d, input logic [2:0] k,
                                               output logic mate, output logic commit_one);
        dec_take_byte = d;
        mate = d.taddr[0] && d.mate_next && (d.need > k) && d.imm_reg;
        commit_one = d.modrm_next;
        dec_take_byte.mate_next = d.modrm_next && !d.taddr[0];
        dec_take_byte.modrm_next = 1'b0;
        dec_take_byte.taddr = d.taddr + 20'd1;
    endfunction

    // the end of Decoder.take: need counts the bytes; the last one starts the nx clocks
    function automatic v35_dec_t dec_take_end(input v35_dec_t d, input logic [2:0] k);
        dec_take_end = d;
        dec_take_end.need = d.need - k;
        if (k != 3'd0 && d.need == k)
            dec_take_end.ra_off = d.nx;
    endfunction

    // the conditions of Decoder.loads_after (the queue's available() is the caller's op)
    function automatic logic dec_loads_after_cond(input v35_dec_t d, input logic [2:0] n);
        dec_loads_after_cond = !d.ir_v && d.need == n && d.nx == 2'd0 && !d.ir_hold
                               && !d.stopped;
    endfunction

    // the conditions of Decoder.load_ir before the queue's available() (the IR hold is
    // tested after it, as the model's `and` chain does)
    function automatic logic dec_load_cond(input v35_dec_t d);
        dec_load_cond = !d.ir_v && d.need == 3'd0 && d.ra_off == 2'd0 && !d.stopped;
    endfunction

    // Decoder.load_ir's load (after the queue's irload op): the IR holds the byte at taddr
    function automatic v35_dec_t dec_load(input v35_dec_t d);
        dec_load = d;
        dec_load.ir_v = 1'b1;
        dec_load.ir_addr = d.taddr;
        dec_load.taddr = d.taddr + 20'd1;
        dec_load.mate_next = 1'b0;      // the byte after the ModR/M left as the opcode
    endfunction
endpackage
