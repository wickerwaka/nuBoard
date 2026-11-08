// V35S core v2: the build-time macros of the core (Q2, R1, R2, R3): one `ifndef / `define per
// rule, 1 built, 0 the earlier core, so a side build can turn a rule off (-DV35_R1_NEED=0).
// A header, not the package: Efinity compiles each file as its own unit, so a macro
// defined in v35_front_pkg.sv does not reach the modules; every module that reads one
// includes this file (Verilator includes it once).
`ifndef V35_MACROS_SVH
`define V35_MACROS_SVH

// (Q2) V35_Q2_TRI: the triple clock's aborted fetch and its retry window (1: built;
// 0: the Q1 core)
`ifndef V35_Q2_TRI
`define V35_Q2_TRI 1'b1
`endif
// (R1) the EU / microcode rules R1 recovers, one macro each (1: built; 0: the 541d91e core)
//   V35_R1_REFILL  refill_start=full_io: after a flush no start while a fetch is on the bus or
//                  the request line stands (the sequencer's Q1_REFILL)
`ifndef V35_R1_REFILL
`define V35_R1_REFILL 1'b1
`endif
//   V35_R1_PGRUN   page_run=field: a 0F memory form's waiting read does not hold the bus unit's
//                  back-to-back sample, once per form (the arbiter's pr_used)
`ifndef V35_R1_PGRUN
`define V35_R1_PGRUN 1'b1
`endif
//   V35_R1_NEED    hold_count=ahead: the arbiter's hold_fetch=le_q subtracts the loader's operand
//                  bytes still to take (need_t) from the bytes counted
`ifndef V35_R1_NEED
`define V35_R1_NEED 1'b1
`endif
//   V35_R1_IRH     ea_ir_room (ir_load=disp_data): the loader's staging byte is occupied while the
//                  IR load is held for the form's data cycle and no operand byte is left
`ifndef V35_R1_IRH
`define V35_R1_IRH 1'b1
`endif
//   V35_R1_NOMEM   request_reissue=no_mem: the arbiter's view of the line stays down
//                  after a fetch issued beside a waiting memory request until the queue changes
`ifndef V35_R1_NOMEM
`define V35_R1_NOMEM 1'b1
`endif
//   V35_R1_FHDATE  free_hold=delivery: the held fetch dates from the clock its hold ends, so it
//                  goes before a request that became issuable then (the arbiter's fetch_first)
`ifndef V35_R1_FHDATE
`define V35_R1_FHDATE 1'b1
`endif
// (R2) the bus unit's / arbiter's sampling of the request line R2 recovers, one macro each
// (1: built; 0: the 0a696bc core)
//   V35_R2_SLOT    slot_room=word: the left-out write's slot chosen on a word's delivery clock
//                  runs a fetch (the bus unit chose the slot's cycle before the word was written:
//                  the delivered word is room)
`ifndef V35_R2_SLOT
`define V35_R2_SLOT 1'b1
`endif
//   V35_R2_GDLUP   grp_disp=hold's take clock: a fetch goes on the displacement's take clock only
//                  when the line stood before the take (the arbiter's `lup`), not on the room
//                  the take itself frees (room for two words after a two-byte take)
`ifndef V35_R2_GDLUP
`define V35_R2_GDLUP 1'b1
`endif
//   V35_R2_DWLUP   dw_lift=moved: a DW-form I/O request moved into the slot takes the bus unit's
//                  sample from before the move-in (`lup`, the line up on a bus without a fetch
//                  in flight) as its post's sample, not the line on the move-in clock
`ifndef V35_R2_DWLUP
`define V35_R2_DWLUP 1'b1
`endif
// (R3) the loader's release timing, one macro each (1: built; 0: the 8d0547e core)
//   V35_R3_XREL    xfer_abort=word: a transfer's displacement byte goes to the bus unit's target
//                  adder, not the EU: the loader releases its room a clock after its take step
//                  ends (the queue counts it on the take clock), so the triple clock's abort
//                  test sees a word where the model's room is 3; on the start clock
//                  (the take with the start and the IR load; 2: any take of a transfer)
`ifndef V35_R3_XREL
`define V35_R3_XREL 1
`endif
//   V35_R3_XRW     xfer_abort=word's room 2: the queue's q_word is also up when the line is a
//                  byte short of a word only by a byte read and not yet released (the transfer's
//                  late displacement byte): the triple clock's abort test sees the read-based room
`ifndef V35_R3_XRW
`define V35_R3_XRW 1'b1
`endif
//   V35_R3_DREL    latch_disp: a memory form's displacement (its last byte) is the EA adder's: taken
//                  on a word's delivery clock with the IR load (the port the EU's, the second
//                  byte latched) its room is released a clock late: one byte less room on that
//                  clock, as the model's counted latched byte (2: without the IR load too)
`ifndef V35_R3_DREL
`define V35_R3_DREL 1
`endif
//   V35_R3_LEAR    lea_room=ir: during LDEA's EA clocks after its last operand byte the loader's
//                  staging byte does not count the IR's opcode (the sequencer's lrc window)
`ifndef V35_R3_LEAR
`define V35_R3_LEAR 1'b1
`endif
//   V35_R3_MATE    modrm_mate=imm: on a word's delivery clock a register form's first immediate
//                  byte, the ModR/M byte's odd word-mate, taken with operand bytes to come: the
//                  loader's staging byte stays counted (the word's slot not yet free)
`ifndef V35_R3_MATE
`define V35_R3_MATE 1'b1
`endif
//   V35_R3_ALAT    abort_latched: the queue's q_word is also up when the line is a byte short of a
//                  word by a byte latched on an earlier clock (room for the abort test only)
`ifndef V35_R3_ALAT
`define V35_R3_ALAT 1'b1
`endif
// (R4) the remaining EU misses and the bus-unit holds (README "R4"); 1: built, 0: the 08a2c58 core
//   V35_R4_PTHRU   page_cl=thru's order: a fetch runs in a 0F CL-index read's CL clocks only when
//                  the line rose after the read's post (the request record's post sample `lup_p`
//                  down); a request standing at the post is an ordinary fetch that restarts the
//                  read's fetch-free count
`ifndef V35_R4_PTHRU
`define V35_R4_PTHRU 1'b1
`endif
//   V35_R4_NMB     request_reissue=no_mem at the issue: a memory request waiting in the slot holds
//                  the bus unit's back-to-back sample only if it waited at the fetch's issue and
//                  the queue has not changed since (the arbiter's `nm`)
`ifndef V35_R4_NMB
`define V35_R4_NMB 1'b1
`endif
//   V35_R4_IOST    io_b2b's shallow queue: on the delivery clock (a fetch ended on t-1) the arriving
//                  word's second byte is in the write port's latch for the clock, not a stored byte
`ifndef V35_R4_IOST
`define V35_R4_IOST 1'b1
`endif
//   V35_R4_CLAT    count_latch's room: a count-byte shift's take on a delivery clock with operand
//                  bytes still to take leaves the word's latched second byte uncounted
`ifndef V35_R4_CLAT
`define V35_R4_CLAT 1'b1
`endif
//   V35_R4_SRZ     str_raise (str_fetch=hold, CW = 0): the REL_RAISE row's clock count ends the
//                  aborted start's drop window in the exit (the request raised again there)
`ifndef V35_R4_SRZ
`define V35_R4_SRZ 1'b1
`endif
//   V35_R4_DASK    imm_landed's deferred take sync counts the request the line shows on the clock
//                  after the take (queue.asked there), not only the fetch in flight
`ifndef V35_R4_DASK
`define V35_R4_DASK 1'b1
`endif
//   V35_R4_LAPS    the take sync's lapse (no room for a word, nothing in flight): on a word's
//                  delivery clock its second byte, in the write port's latch, is room
`ifndef V35_R4_LAPS
`define V35_R4_LAPS 1'b1
`endif
//   V35_R4_DRX     xfer_abort=word's retry at the aborted cycle's end for every transfer by base
//                  class (the format's xfer bit: BRK is a call), not only the listed classes
`ifndef V35_R4_DRX
`define V35_R4_DRX 1'b1
`endif
//   V35_R4_XNT     xfer_nt=odd's decide: a not-taken transfer's test waits only for the fetches
//                  issued before its odd hold's lift (odd_until), not for the one its release raised
`ifndef V35_R4_XNT
`define V35_R4_XNT 1'b1
`endif
//   V35_R4_GIOD    grp_io_hold's dating: the fetch it held dates from the clock the hold ends and
//                  goes before a group read that became issuable on that clock
`ifndef V35_R4_GIOD
`define V35_R4_GIOD 1'b1
`endif

`endif // V35_MACROS_SVH
