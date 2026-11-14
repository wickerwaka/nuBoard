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

    // ------------------------------------------------------------ fit integers (fit.json)
    localparam int FIT_HOLD_Q = 3;              // hold_q
    localparam int FIT_IO_RECOVER = 2;          // io_recover
    localparam int FIT_MIN_GAP = 0;             // min_gap


endpackage
