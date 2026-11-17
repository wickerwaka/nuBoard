`timescale 1ns/1ps

// V35S core v2, front end (stage S2 of docs/v35s-core-v2.md): the bus-cycle kinds and widths
// and the fitted constants the front end reads ((Q1) the request rule's room function is gone:
// the queue counts its bytes, v35_queue.sv).
//
// The constants are the tracked fit's (validation/v35s/chains/fit.json, md5
// de193740eaf1dee0862d2220ae084909, fit 62), copied by hand for S2; S1's generated
// v35_consts.svh / v35_class_tbl.svh replace them (the names below are the fit's).
package v35_front_pkg;

    // ------------------------------------------------------------ bus cycle kinds and widths
    // (the same encodings as the old core's v35_chain_params.svh, so v35_sfr.sv reads them)
    localparam logic [2:0] K_NONE = 3'd0;
    localparam logic [2:0] K_FETCH = 3'd1;
    localparam logic [2:0] K_READ = 3'd2;
    localparam logic [2:0] K_WRITE = 3'd3;
    localparam logic [2:0] K_IO_READ = 3'd4;
    localparam logic [2:0] K_IO_WRITE = 3'd5;
    localparam logic [2:0] K_REFRESH = 3'd6;
    localparam logic [1:0] BW_WORD = 2'd0;
    localparam logic [1:0] BW_LO = 2'd1;
    localparam logic [1:0] BW_HI = 2'd2;

    function automatic logic k_io(input logic [2:0] k);
        k_io = k == K_IO_READ || k == K_IO_WRITE;
    endfunction
    function automatic logic k_read(input logic [2:0] k);
        k_read = k == K_FETCH || k == K_READ || k == K_IO_READ;
    endfunction

    // ------------------------------------------------------------ (A1) the EU request port
    // the cycle types on the bus unit's EU request port (req_cyc: the pin-level cycle; the SFR
    // page is decoded from the address by the bus unit)
    localparam logic [1:0] RQ_MEMR = 2'd0;
    localparam logic [1:0] RQ_MEMW = 2'd1;
    localparam logic [1:0] RQ_IOR = 2'd2;
    localparam logic [1:0] RQ_IOW = 2'd3;

    // ------------------------------------------------------------ fixed structure
    localparam int QUEUE_BYTES = 6;             // queue.QUEUE_BYTES
    localparam int BUS_BASE = 3;                // bus.BASE: B1 B2 B3
    localparam int WTC_MEM_LSB = 0;             // machine.waits_of: WTC field 0 (memory, fetch)
    localparam int WTC_IO_LSB = 14;             // ... field 7 (I/O, the SFR store)
    // (MX5c) the bits the queue stores beside each byte (the loader's byte tag: written with the
    // byte, opaque to the queue)
    localparam int QTAG_W = 6;

    // ------------------------------------------------------------ (consol) the pace's ports
    // The bus unit owns the front end's pace (README "consol"): the sequencer presents the word's
    // kind, the queue its count's compares, the loader the instruction stream's facts; the bus
    // unit returns the one registered hold (ph_nx).
    // the word's kind (the sequencer's, of the next word: wk_nx): the dispatch word (the
    // boundary), a FLUSH word, the bus-wait kinds' two bits (rl == RL_X, bi: B bi alone, S rl=x
    // alone, Y both)
    // (qprobe round 10) alt: the wait's second kind (the word's vk bit on a word that reads no
    // SR_VEC): with bi alone C, the commit word; with rl == RL_X and bi V, the late request word
    typedef struct packed {
        logic       disp, flush, rlx, bi, alt;
    } v35_wk_t;
    // the queue's count against its thresholds (the bytes fetched and not released), for one
    // clock: at most 4 / 5 (c4, c5) and with the running fetch's bytes at most 5 (cf), each with
    // the stream not waiting for a flush's target; below 3 / 2 (lt3, lt2); b4: a word delivered
    // with the count at most 4 (rule 4b)
    typedef struct packed {
        logic       c4, c5, cf, b4, lt3, lt2;
    } v35_lvc_t;
    // tick B: the next clock's compares before its releases, for both cases of the next clock's
    // delivery (a: a fetched word delivered then, n: none; the bus unit selects by its own
    // dlv_fetch_nx: the arrival's bytes and the discard of a flushed word are the queue's)
    typedef struct packed {
        v35_lvc_t   a, n;
    } v35_lvn_t;
    // tick A: this clock's count after its releases at most 4 (c4) and with the word in flight at
    // most 5 (cf), the line at the five-held threshold (r5: the count after the releases at most
    // 5 with a fetched word delivered now and not discarded, not suspended: the back-to-back
    // continuation, which the bus unit allows or bars), and no byte released now (nrl)
    typedef struct packed {
        logic       c4, cf, r5, nrl;
    } v35_lvq_t;
    // the instruction stream's facts for the next clock's boundary (the loader's, tick B): the
    // opcode register's instruction short of its lead (ld) or at its lead's end (le), its opcode
    // waits for three bytes behind it (m3: the decode's m3, a ModR/M opcode but FE / F7; qprobe
    // round 8, Q20), HALT released and not yet run (hp), and the
    // word then releases a staged HALT (hc: the line drops on that word's execution)
    typedef struct packed {
        logic       ld, le, m3, hp, hc;
    } v35_sf_t;


endpackage
