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

// (A1) the arbiter removed (docs/v35s-arbiter-strategy.md; README "A1"): the bus unit's grant
// is one fixed priority over the EU request port; the request attributes are the sequencer's
//   A1_IOREC   io_recover: 1 the bus unit's turnaround (no EU memory cycle while io_win), 2 no
//              EU cycle at all while io_win, 0 the EU's own wait (req_v held)
`ifndef A1_IOREC
`define A1_IOREC 1
`endif
//   A1_B2BH    the back-to-back sample's hold at a fetch's last clock (rule 1): 1 req_v or req_resv
//              standing (the grant's definition: at a fetch's last clock the EU's reservation is
//              its waiting memory request, the EA clocks running on, the I/O lead's block); 0
//              req_v only (the strategy's first wording); 2 req_v or a memory cycle's reservation
`ifndef A1_B2BH
`define A1_B2BH 1
`endif
//   A1_IOQL    the grant's rule 3: the queue's low hint overrides a memory cycle's reservation, not
//              an I/O cycle's (the port's cycle type; 0: any reservation, the strategy's first
//              wording, the step-2 record)
`ifndef A1_IOQL
`define A1_IOQL 1'b1
`endif
//   A1_GRP     the group forms' grp clocks pause on an I/O cycle or its recovery and count the
//              free ones on an idle bus (grp_free_bus; 0: counted as any memory request's)
`ifndef A1_GRP
`define A1_GRP 1'b1
`endif
// the recovered rules (step 5: each the sequencer's, on bus facts; 1 built, 0 not built: GIO and GDR
// showed no effect alone or with the others and are left at 0):
//   A1_FFD     _fetch_first's dating: a request that became issuable on the clock the line rose
//              waits a clock (the fetch goes first)
`ifndef A1_FFD
`define A1_FFD 1'b1
`endif
//   A1_LEAD    the I/O lead: in its lead clocks only a fetch standing since the post goes, on
//              the clock the hold lifts
`ifndef A1_LEAD
`define A1_LEAD 1'b1
`endif
//   A1_FRUN    free_run=run: the delivery-clock fetch runs through a request's fetch-free clocks
`ifndef A1_FRUN
`define A1_FRUN 1'b1
`endif
//   A1_FHOLD   free_hold=delivery: no fetch on the delivery clock that takes the first free clock
`ifndef A1_FHOLD
`define A1_FHOLD 1'b1
`endif
//   A1_GIO     grp_io_hold: a group request's free clocks hold a fetch over an I/O cycle
`ifndef A1_GIO
`define A1_GIO 1'b0
`endif
//   A1_SF      slot_fetch=slot: a request moved in behind an I/O holds a fetch to its free clocks
`ifndef A1_SF
`define A1_SF 1'b1
`endif
//   A1_GDR     grp_disp=hold's read: held to its fetch-free group clocks
`ifndef A1_GDR
`define A1_GDR 1'b0
`endif
//   A1_SREG    sreg_store=own: MOV r/m,sreg's write after a clock issuable but for a fetch
`ifndef A1_SREG
`define A1_SREG 1'b1
`endif
//   A1_RL      port_latch=relatch: the waiting detached I/O held relatch clocks after a port take
`ifndef A1_RL
`define A1_RL 1'b1
`endif
//   A1_DW      dw_count=bus: a DW-form I/O request's clock taken by a cycle starting
`ifndef A1_DW
`define A1_DW 1'b1
`endif
//   A1_MFR     mul_imm_count=sync: MUL imm memory's read counted from mul_from
`ifndef A1_MFR
`define A1_MFR 1'b1
`endif
//   A1_PAGE    the 0F page's read counts (page_free's restart, run_wait, pthru, ftail,
//              page_imm_run) as sequencer counters on bus facts (0: the plain fetch-free tail)
`ifndef A1_PAGE
`define A1_PAGE 1'b1
`endif
//   A1_BCD     bcd_fetch=hold: a BCD string started on an idle bus counts its first read's setup
//              a clock longer
`ifndef A1_BCD
`define A1_BCD 1'b1
`endif

// (MX0b) the EU's byte source: 0 the queue's stored bytes (ripeness), 1 the word register
// loaded at the end of a clock that leaves it empty, 2 the word register loaded on a clock of
// its own (README "MX0b")
// (MX1e) 3 a FIFO of the word register and the window; (MX1f) 0 the default with
// V35_MX1D_ARRIVE 1: the storage the model's queue (README "MX1f")
`ifndef V35_MX0B_WR
`define V35_MX0B_WR 0
`endif
// (MX0c) the dispatch's stall: 0 none, 1 while the bus unit runs a fetch cycle, 2 and a
// ModR/M form on a back-to-back fetch's issue clock (both on the word after E), 3 the same
// law on the E word (the staged opcode's pop) (README "MX0c", "MX0d"); (MX1b) 4, the
// default: the law on the E word, the pop (with its ModR/M) the law gates, the routine's words
// and the dispatch never stalled on a fetch (the same gate as 3, measured with the routines on
// the frozen model's positions: README "MX1b")
// (MX0f) V35_MX0F_QSTART: the start Q2's triple clock reads (1: the E word's opcode pop;
// 0: the routine's entry word, MX0e)
`ifndef V35_MX0F_QSTART
`define V35_MX0F_QSTART 1
`endif
`ifndef V35_MX0C_DISPATCH
`define V35_MX0C_DISPATCH 4
`endif
// (MX1c) V35_MX1C_TSYNC: the take sync (1 built, measured: the restart flat across the waits, a
// uniform clock off; 0 the default until the staging load clock is found): README "MX1c"
// (MX1f) 1 the default: with the model's room accounting the traces match (README "MX1f")
`ifndef V35_MX1C_TSYNC
`define V35_MX1C_TSYNC 1
`endif
// (MX1c) V35_MX1C_ROOM: the staging slot's count while bytes are owed (v35_loader): 0 MX0's,
// 1 free on a word's arrival clock, 2 free whenever empty; (MX1f) 3 the default: 1 and a take
// step's bytes released at its end (a word operand's low byte held until its high byte's pop)
`ifndef V35_MX1C_ROOM
`define V35_MX1C_ROOM 3
`endif
// (MX1d) V35_MX1D_ARRIVE: the byte path takes a delivered word's bytes on its delivery clock
// (1) or from the clock after (0, MX0b's ripeness): README "MX1d"
`ifndef V35_MX1D_ARRIVE
`define V35_MX1D_ARRIVE 1
`endif
// (MX1e) V35_MX1E_LHOLD: the request line held while a latched byte cannot drain (1; 0 not)
`ifndef V35_MX1E_LHOLD
`define V35_MX1E_LHOLD 1
`endif
// (MX1e) V35_MX1E_TSE: the take sync gates the E word too (1) or not (0)
// (MX1f) V35_MX1F_ASKL: the take sync counts a request the latch holds off the bus (the frozen
// model's asked: the request raised; the queue's fetch_raise, a port the coordinator's ruling
// is asked for) (1, the default) or only the line (0)
`ifndef V35_MX1F_ASKL
`define V35_MX1F_ASKL 1
`endif
// (MX1f) V35_MX1F_WB: the write-back wait (v35_useq): 0 none, 1 the E word that pops a wbs
// opcode waits out its own write-back's two clocks (the model's placement), 2 the wbs routine's
// entry word waits the two clocks after the post-E word
`ifndef V35_MX1F_WB
`define V35_MX1F_WB 1
`endif
// (MX1g) V35_MX1G_BW: the bus wait (v35_useq): a word moving into the bus unit's address
// register (1, the default, and 2) or write datum (1) waits while a memory cycle is in a wait
// state; 0 none
// (MX1g) V35_MX1G_IOH: the fetch line raised by the staging load on an EU I/O cycle's issue
// clock is not granted before the EU's next start (v35_bus): 1 the default; 0 none
// (MX2) V35_MX2_TSM: the take sync armed by a memory form's ModR/M pop too, the
// sync gating the EA's add only in a memory form: 1; 0 the register forms' only (MX1c)
`ifndef V35_MX2_TSM
`define V35_MX2_TSM 1
`endif
`ifndef V35_MX1G_IOH
`define V35_MX1G_IOH 1
`endif
`ifndef V35_MX1G_BW
`define V35_MX1G_BW 1
`endif
`ifndef V35_MX1E_TSE
`define V35_MX1E_TSE 1
`endif
`endif // V35_MACROS_SVH
