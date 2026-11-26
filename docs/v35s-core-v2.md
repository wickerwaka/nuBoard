# V35S core v2: a synthesizable SystemVerilog CPU from the chain model


Approved plan of 2026-11-02 (the design record for `fpga/v35s/core/v35/`). Appendices A and B are the
two design reports the plan was written from; where they disagree with the plan body, the body rules.
Progress, gates and divergences are recorded in the "Record" section at the end.
## Context

The chain-timing model in `validation/v35s/chains/sim/` (fit 62, 34,555 of
35,168 corpus runs cycle-exact against the socketed µPD70337; refresh-off
30,361 of 30,536) describes the V35S as five interacting machines with fitted
structure. The first RTL attempt (`fpga/v35s/core/v35_{queue,arbiter,eu,
decoder,chain_core}.sv`, generated params in `v35_chain_params.svh`) ported
the Python: it iterates the model's per-clock phase loop to a fixpoint over
~1,046-bit state with settle registers and spatially unrolled op stages
(JSLOT 40, NXQ 8, NXOP 6). It is a cycle-exact executable spec, not hardware,
and does not synthesize (Efinity OOM past 52 GB). Only `v35_biu.sv`,
`v35_refresh.sv` and `v35_sfr.sv` are hardware-shaped.

The user now wants a synthesizable core for the Trion T120F484 that
**recreates the abstract machines with a structure that makes sense for
silicon, using the model as a guide, not porting it**. Decisions taken with
the user (2026-11-02):

1. **Full function** for every opcode the corpus covers (ALU, flags,
   registers, memory, I/O); unmodeled opcodes trap/NOP.
2. **Microcode ROM EU**: one row per timed step, indexed by class, plus
   hardwired loop counters (shift, MUL/DIV, BCD, strings, bit fields).
3. **Registers in a 256-byte internal RAM** (8 banks × 32 B + data RAM),
   PC/PSW as flops; EU register access through RAM ports.
4. **New tree** `fpga/v35s/core/v35/`, reusing the harness slot and the
   corpus replay scoring; the old chain core and `rtlgen` are retired once
   the new core passes the corpus gate.

The user also lifted the 2026-10-31 "no RTL work" directive by this request.
The "no refresh-on work" focus stands: refresh-on lists (F8 F13 F17 F18 F27
F28) are out of the RTL gates; the refresh controller is reused as-is and
the refresh rules are not ported in the first delivery.

Execution model is unchanged: Opus agents implement, this session writes
briefs, reviews, gates, documents and commits (standing authorization to
commit at verified, documented stopping points).

## Governing principles

- **Silicon is the reference, the model is the guide.** The gate for every
  stage is `replay --core v35 --score`: per family, RTL-exact against the
  silicon corpus ≥ model-exact (fit 62's number). "RTL = model" is a
  diagnostic, not a requirement: where a silicon-shaped structure differs
  from the model's phase order and the corpus does not care, the RTL keeps
  the silicon-shaped form and the difference is written down.
- **One registered state update per CPU clock, feed-forward inside it.**
  Six combinational stages (below) in a fixed order; no settle registers, no
  iteration, no block that reads its own outputs. Enforced by a lint test.
- **No timestamps.** Every model `x_t == t` comparison becomes a "this
  clock" strobe where the event is produced, a registered "last clock"
  copy, a flag captured at the later of two events, or a down-counter.
  State widths come from the spec's A2 table and the C-decisions
  (`docs/v35s-chain-rtl-spec.md`).
- **Rules live where a silicon designer would put them.** Class integers
  are row immediates or a small class table; situation rules become flags
  or timers in the named module, microcode row attributes, or decode
  attributes (format bits) produced by the generator. RTL never compares
  opcode bytes outside the generated decode table (lint).
- **Structure by hand, data by generator.** Module structure is written by
  hand from the mechanism descriptions. The decode table, class table,
  microcode rows and constants are generated from `fit.json` and the frozen
  `templates.steps` by a new script, with a test that regenerates and diffs
  and an inverse check that the ROM expands back to the model's step lists.
- **The model is not edited by RTL work.** A silicon miss found during
  bring-up is a model question (facts, enum, fit) handled by the chain-model
  work, then reflected in regenerated data; RTL carries no rule the model
  lacks.

## Architecture

```
v35_top (slot ports = fpga/v35s/core/v35s_model.sv:25-43; instance `model`)
 ├ PCK divider + reset exit     (from v35s_chain_model.sv:89-151)   ce, ce_mid
 ├ v35_sfr        (reused as is)              prc wtc rfm idb
 ├ v35_refresh    (reused, state ports dropped)   rf_pending → arbiter
 ├ v35_bus        (v35_biu.sv trimmed; pin timing verbatim :290-350)
 ├ v35_queue      6 bytes + 1-byte write-port latch, room, request flag, b2b
 ├ v35_loader     IR, take handshake, format word, need/ready, ir_hold
 ├ v35_ucode      microcode ROM + sequencer, loop counters, holds, floors
 ├ v35_eu         operands, EA, ALU/flags, write data, request record, PC/PSW
 ├ v35_arbiter    setup counting, request window, fetch holds, grant
 ├ v35_regram     256×8 as two 128×8 BRAMs (even/odd), two 16-bit ports
 └ v35_trace      (`ifndef SYNTHESIS`) event trace for diffing against the model
```

### Modules and the state they own

| Module | Registered state (widths) | Replaces in the model |
| --- | --- | --- |
| `v35_bus.sv` | current cycle (valid, kind 3, pos 3, len 3, addr 20, width 2, data 16, internal) + cycle flags set at start (b2b, thru, commit, on_start, after_post, lea_start, disp_in_flight, ir_before, take_near); delivery registers (valid, word 16, odd, commit, slot, disp); `fetch_end_prev`, `cpu_end_prev`, `fetch_run(_prev)`; `io_win` 2; `io_start_age` 4 sat; `last_write_age` 4 sat; `wlatch` 3; `abort_v, abort_pos` 2 | `bus.current`, `Cycle.b2b/thru/commit`, `last_fetch_end`, `last_io_end`, `wlatch_until`, `abort_end`, the `cycles[-k:]` look-backs |
| `v35_queue.sv` | storage 8×8 (8 inside a clock), head 3, tail 3, cnt 4; `lat_v, lat_full`; `uncommitted`; `flag`; order flags `rq_v, rq_older_slot, rq_at_take, rq_take_own, rq_after_io`; `inflight`; `fetch_addr` 20; `b2b_at` 1; `retry, retry_loop, retry_cnt` 9; `shift_held, shift_cnt` 9; `nop_held, io_held`; `slot_fetch`; `gdisp_v, gdisp_cnt` 3; the F23–F25/F33 hold flags (~30 bits); once-per-form commitments `pb_done, pr_done, nb_done` | `bytes`, `latched`, `flag`, `requested_at` vs `posted` comparisons, `b2b_at == t`, `retry_at`, `shift_until`, `gdisp_until`, `*_start == start_clock` |
| `v35_loader.sv` | `ir_v, ir` 8, `ir_page`; `need` 3; `ra_cnt` 5 (ready_at as countdown); `ir_hold`; `ea_cnt` 2; `modrm_next, skip, mate_next, imm_reg, fresh, lea_wait, stopped`; format word `fmt` (~40 b: class 7, len 3, modrm, mod 2, reg 3, rm 3, imm 2, disp 2, w, dir, grp, fixed, page, seg 3, rep 2, cond 4) + decode attributes the room rule reads | `decoder.*`, `decoder.cls` reads in `room()` |
| `v35_ucode.sv` | `upc` 10 (class base + k 4); current row 48; `res_cnt` 11 (resume as countdown); `sync_mode` 2, `owed` 2 (fetches owed 0..2); `mr_sync`; `wbu_cnt` 3; `exec_par, hold_done_fetch/abort` (unit hold); `floor_n` 4, `dfloor` 1+3; `mt_floor` 1+2, `page_mt` 1+3+1+3; `pf_cnt` 7 sat (fetch-free clocks since start: replaces the at-post back-count); `mf_cnt` 4; `halted`; `start_prev, start_age` 4 sat; `done_v, done_age, wb, lea_fwb_cnt` | `resume`, `sync`, `wb_until`, `unit_hold`'s `(t-exec_t-hphase)` parity, `_submit`'s back-count (eu.py:1780-1798), the page_* timers |
| `v35_eu.sv` | `pc` 16, `psw` 16, `ps_shadow` 16; `ea_off, ea_seg`; `opa, opb, res`; `rd_latch`; `imm, disp, port`; request records: 1 slot + 2 queued (kind 3, addr 20, width 2, data 16, setup 7, count 7, free_need 3, through, lead 2, issued 2, posted_now, ready_prev, lift_done, done_v, done_cnt 3, detached, nowait, grp, imm1, floor flags ≈ 85 b each); divider iteration state | `Request` (arbiter.py:47-110), `ready_since == t` → `ready && !ready_prev` |
| `v35_arbiter.sv` | `win` 2 (counting/eve/free/issuable), `free_held, grp_held`, `run`, refresh-boundary flags | the spec's posted-request window family; `_choose` is pure logic |
| `v35_regram.sv` | 2 × 128×8 BRAM | `v35_rf_t` flops; bank = `{psw.RB, slot}` as in `validation/v35s/model/eu.py:17-18` |

### The six-stage clock (no iteration)

| Stage | Model phase | Inputs | Produces |
| --- | --- | --- | --- |
| S0 | — | registers | `bus_free, fetch_inflight, in_wait, fetch_past_b2, dlv_now, abort_end_now`, request `ready/holding/counts` |
| S1 | C, A | S0 | `avail = cnt + delivered bytes` (bypass when cnt<2), `owed−1`, read `done_now`, `retry → flag` |
| S2 | T | S1 + EU/loader regs | the EU row: start gate, holds, `pops_T` (0..2), ModR/M commit, `post_T`, sync update, strobes `take_now, disp_now, mate_now, start_now` |
| S3 | L | S2 | `pop_L` (IR load), `room`, `fetch_want`, `rq_now`, `flag_X` |
| S4 | X | S0–S3 | `_choose` as one priority tree → **issue strobe** {none, fetch, data, io, nowrite-slot, abort}, request field writes, new cycle flags |
| S5 | P | S4 strobe | the **restricted second EU pass**, enabled only by an I/O issue this clock (a detached OUT or an owned I/O whose `done_at` is now) or by `ir_hold` clearing on an EU data cycle: (i) the start gate with the I/O interlock satisfied, (ii) the started form's first row if it acts this clock (one take of ≤1 byte, a lead take, one post, or loading `res_cnt`), (iii) a second IR load, (iv) the `io_ir_hold / io_take=unit / port_issue / nop_hold` flag writes. **Nothing in S5 feeds S4.** |
| S6 | E | S5 | `head += pops`, latch-in decision (`lat_v` next from the fixed write-port owner chain), `b2b_at` next (fetch ends now and the flag as it stands is up, with the page_dcommit / page_run / page_b2b / xfer_nt_b2b branches), the `latch_start / one_idle / bcd_fetch` resume adjustments |

The four genuine same-clock dependencies resolve as S1→S2 (delivery before
take), S2→S3→S4 (takes/posts/IR load → room/request → arbiter), S4→S6
(grant → b2b commit and write-port result at the edge), S4→S5 (an I/O
issue releases the EU on its issue clock; a memory write releases at
end+1, so S5 is bounded to the I/O clock and the `ir_hold` clear).

**Write port owner chain (fixed priority, S6):** (a) a committed take or IR
load this clock holds the port; (b) else the latch drains one byte if the
storage has room; (c) a delivered word's first byte always stores, its
second byte stores if the port is free and there is room, else enters the
latch. No arbitration depends on the grant.

**S5 budget check.** The generator enumerates, per I/O-interlocked class,
the actions of rows 0/1 on a start clock and asserts they fit the S5
vocabulary (today: reg → take or clocks; imm → lead take + clocks;
shift/mul/div → take; prefix → clocks; lea → chain take; ret → post +
issued; transfers → take or clocks). If a class ever needs more, its start
is delayed to the next clock with `res_cnt` pre-decremented and the
affected families (F3 OUT-interlocked starts, F12 A, F19 D, F15 O, F14 G,
F16 L, F7) decide at the gate.

## Microcode

**Row** (48 bits, `v35_pkg::uc_row_t`): `op` 5 (CLOCKS, NOWAIT, TAKE, DATA,
POST, POST_IO, SLOT, ISSUED, WAIT, WBSYNC, FLUSH, FLUSH_FROM, DECIDE, HALT,
FETCH_HOLD, FETCH_RELEASE, QUIET, FROM_START, HELD_CLOCKS, SPLIT_FLOOR,
END; SENT unused under the fit), `nsrc` 3 + `imm` 8/9 (literal; EA table by
mode; 2×count shift loop; unit length (+ sign clocks); bit-field cost;
string element loop; literal + waits; CL-dependent), `wait` 3 (none / own
done / own issued / slot empty / wb done / fetch-quiet / flush gap / halt),
request descriptor 16 (`rkind` 3, `asrc` 3: EA / SP−2 / SP / port imm /
port DW / IX / IY / vector / EA+2, width sel 2, `setup_src` 2, `free_src`
2, `through`, `nowait`, `grp`, `detached`, `restart`), `tag` 4 (ea, mexec,
loop, tail, exec, lead, chain, word, port, dlv, room, raise, forever, bf),
`tdelay` 1 (next row this clock or next), `skip` 3 (no disp / no imm /
register form / not crossing / CW==0 / hold not armed), `arm` 3 (set
`ir_hold`, fetch_hold arm/lift, flush_from, fetch_release, capture
`exec_t`), `wsrc` 3 (res / reg / imm / PSW / PC / PS / EA / string),
`wb` 2, `last`, `sync`, `boundary`.

Zero-time model steps fold into the next timed row as side-effect fields, so
the ROM has at most one timed action per clock. The `port_latch=relatch`
dynamic insertion becomes two fixed rows after every port-take row, skipped
when the slot held no detached I/O.

**Class table** (~90 bits × 83 classes): the integers read outside rows:
`nx, nx0, wb, mwb, rwb, uwb, xwb, flwb, fwb, wbsync, wbsync0, hphase, mtail,
mtx, sidle, relatch, lead, setup_free, grp_free, fsetup, ftail, dfloor,
istart, fgrp, fgrp_free, dhold, hold, nhold, chold, fgap, nfgap, cfgap, gap,
ugap, ufree, grpcl, last`; plus the 7-entry EA table and `hold_q`,
`io_b2b_q`, `wlatch`, `io_recover` constants.

**Hardwired, not in rows:** shift loop counter (CL&1Fh / imm / 1), the
16-iteration restoring divider under the class's exec clocks, BCD pair
counter (CL), string element counter (CW with REP exit on Z), the
unit-hold parity toggle, `wlatch` 4, `io_recover` 2, the floors
(`dfloor`, `istart`, `fgrp`, `mt_floor`), `pf_cnt`.

**ROM size:** ≤ 83 × 14 rows × 48 b = 56 kbit worst case; realistically
600–750 rows (≈ 30–36 kbit) after rows shared by format collapse via `skip`
bits. One or two block RAMs. Loop counts fit the 11-bit `res_cnt`
(SHL by 255 = 510 clocks; whole-register INS 1,998).

**Generator** `validation/v35s/chains/ucgen.py` (new; `rtlgen.py` is not
reused): enumerate every form the frozen decoder accepts (opcode × ModR/M ×
0F byte) under `fit.json`, call frozen `templates.steps` (+ nothing for
refresh in the first delivery), map tuples to rows with symbolic sources,
dedup identical row lists, and emit `fpga/v35s/core/v35/v35_ucode.hex`,
`v35_ucode_tbl.svh` (format → template base), `v35_decode_tbl.svh`,
`v35_class_tbl.svh`, `v35_consts.svh`; header carries fit.json's md5.
`test_ucgen.py`: regenerate-and-diff; **inverse check**: expand each form's
rows back to step tuples with the fit's integers and assert equality with
`templates.steps` for every enumerated form; S5 budget check; size bounds
(rows ≤ 2048, templates ≤ 512).

## Function path

- **Decode table** (generated): 256 native + 256 0F entries from
  `fpga/v35s/core/ucore/pla3_tables.svh` (has_modrm, w-from-bit0,
  dir-from-bit1, prefix, sreg_mov, modrm_store) joined with
  `build/deps/nuV30/docs/facts/instructions.json` (immediate bytes, 0F
  page) and the frozen `templates.decode` (class); group opcodes get a
  reg-field override table. Length = 1 + page + modrm + disp(mod, rm) +
  imm, computed by the loader from `fmt` and the ModR/M byte on its take
  (the model decodes from the image at start; hardware cannot, see Risks).
  Unknown opcodes → class `trap_nop`, listed in the header.
- **Register RAM:** two 128×8 BRAMs (even/odd) give a word at any even slot;
  port A for operand read and write-back, port B for the second read (EA
  index, ALU operand B, SP). `PSW.RB` selects the bank; `PS` is shadowed in
  a flop so the fetch address adder needs no RAM port.
- **Functions** (`v35_fn_pkg.sv`, verbatim from `v35_eu_pkg` with the `mut`
  argument removed): `v35_alu` (v35_eu.sv:1199), `v35_szp` (1186),
  `v35_shift` (1247), `v35_mul` (1316, DSP), `v35_cond` (1404),
  `v35_adjust` / `v35_bcd8` / `v35_bit1` / `v35_rot4` (1602–1713);
  `v35_div` rewritten as a restoring divider sequenced under `div.exec`;
  `v35_ea_off` (1426) becomes `v35_ea.sv` (base from port B, index from
  port A, disp from the loader, segment = prefix / SS for BP forms / DS0,
  DS1 for string destinations). `v35_execute` / `v35_deliver` /
  `v35_wdata` (1721–2258) are untied from the template split: operand A
  from port A, operand B = `rd_latch` (lane-selected) or imm, the ALU row
  registers `res`/`psw`, a DATA/POST write row builds `req_data` by
  `wsrc`, the END row writes back to port A under `wb`.
- **Not in scope of this plan:** interrupts, bank-switch instructions
  (BRKCS, TSKSW, MOVSPA/B, RETRBI, FINT, BTCLR, STOP), POLL, CHKIND, BRKV,
  FPO escapes, READY, refresh-on timing rules. They trap/NOP.

## Verification

| Level | Tool | When |
| --- | --- | --- |
| ROM = model templates | `test_ucgen.py` inverse check, regenerate-and-diff | every test run |
| RTL run = silicon | `replay --core v35 --score`: RTL-exact ≥ model-exact per family (fit 62's numbers); `--jobs 8`, output dir removed first (memory `v35s-chain-lane-bulk-runs`) | every stage gate, listed families; whole refresh-off corpus at S5 |
| first divergence | `v35_trace.sv` (`+v35_trace=FILE`, one line per CPU clock: cycle starts in `normalize.Event` vocabulary + strobes S/T/L/P/I/B/A/R/W with the wait reason) and new `validation/v35s/chains/evtrace.py` (hooks on the frozen `Machine`: bus starts, EU starts, takes, IR loads, posts, issues) printing the first divergent clock ±8 | the first failing run of a family |
| function | `fpga/v35s/v35_rf_tb` retargeted to `v35_fn_pkg` + `rtl_vectors.py --regfile` (58,508 vectors, funcref.py); `sst.py --rtl` (V20 v1_native) | S3 (ALU/shift/mul), S6 (all) |
| board | `runner.py --socket-fitted --mode both --program-only programs/{smoke,clocks,alu}.s` | S6 |
| structure lint | `test_v35_struct.py`: no settle/iterate constructs, no `always_comb` reading its own outputs, no opcode literals outside `v35_decode_tbl.svh`, state widths within A2 | every test run |
| synthesis | per-module `efx_map` in `systemd-run --user --scope -p MemoryMax=20G` (memory `v35s-chain-rtl-efinity-trial`); whole core at S7 | S3, S4 (module), S7 (core) |

Resource targets (S7): core ≤ 9,000 LUT4, ≤ 6,000 FF, ≤ 28 BRAM (ROM ≤ 24
accounted conservatively, regram 2), 2 DSP; map < 20 min; timing met at
30 ns with the existing 2-cycle multicycle (`core/model.sdc`).

## Stages and work packages

Each stage is one or more Opus work packages (worktree agents; one
main-tree agent only when nothing else edits main). Gates are run by the
overseer; agents never commit, never edit `validation/v35s/chains/sim/**`,
`fit.json`, or `docs/*.md`.

| Stage | Files | Gate |
| --- | --- | --- |
| **S1 generator + ROM** | `validation/v35s/chains/ucgen.py`, `test_ucgen.py`; `fpga/v35s/core/v35/v35_pkg.sv`, `v35_ucode.hex`, `v35_ucode_tbl.svh`, `v35_decode_tbl.svh`, `v35_class_tbl.svh`, `v35_consts.svh` | inverse check equal for every form; decode lengths equal `templates.decode(...).length`; S5 budget check; size bounds |
| **S2 front end** | `v35_top.sv`, `v35_bus.sv`, `v35_queue.sv`, `v35_loader.sv`, `v35_arbiter.sv` (fetch + scripted data/I/O posts), bench `fpga/v35s/v35_front_tb.sv` with a scripted EU; `build_sim.sh` case `v35` (macro `V35S_CORE_V35`), harness `ifdef` branch, `acquire.SIM_CORES["v35"]`, `test_chain_lane.py` set, `replay.py` help; `v35_trace.sv`, `evtrace.py` | F0, F1, F2 |
| **S3 register classes** | `v35_ucode.sv`, `v35_eu.sv` (register path), `v35_regram.sv`, `v35_fn_pkg.sv`, `v35_rf_tb` retarget | F3, F9, F11, F12, F20; `--regfile` vectors on ALU/shift/mul; module `efx_map` |
| **S4 memory classes + arbiter** | full request record, window FSM, I/O slot, aborted cycle, nowrite slot, `alu_busy`; `v35_ea.sv` | F4–F7, F10, F14–F16, F19, F21, F22; module `efx_map` |
| **S5 the rest of the corpus** | 0F page rows and `page_*` flags/timers, BCD, bit fields, digit rotates, strings (fetch_hold/release, quiet, split_floor), transfers (flush/decide, far, BRK/RETI vectors), LDEA, PUSH R/POP R, PREPARE/DISPOSE, I/O frames, conversions | F23–F26, F29–F40, F36–F38; then the whole refresh-off corpus: every family RTL-exact ≥ model-exact |
| **S6 function** | untied execute/deliver/wdata, divider, PSW masks, trap_nop | `--regfile` 58,508 vectors 0 bad; `sst.py --rtl` pass set ≥ the old core's (1,651,237); board programs match with `--mode both` |
| **S7 synthesis + retirement** | `fpga/v35s/build.sh` branch `V35S_CORE=v35` (xml rewrite, `model.sdc`), `fpga/v35s/synth/` module tops | targets above; then delete `v35_{queue,arbiter,eu,decoder,chain_core}.sv`, `v35s_chain_model.sv`, `v35_chain_params.svh`, `rtlgen.py`, `rtl_vectors.py` (keep `--regfile` → move into ucgen tests), `test_rtlgen.py`, `test_rtl_vectors.py`, the old benches; `docs/v35s-hdl-plan.md` marked superseded |

Bring-up order inside S2–S5 (each family isolates the mechanisms it adds,
so a divergence is caught in the simplest family): F0 fill → F2 release →
F3 register costs (+S5 pass, unit hold) → F6 starvation (hold_fetch, abort
FSM, reissue) → F4/F5 memory (request window, EA, io_recover) → F7
neighbours (relatch, nop_hold) → F9/F11/F12 shifts and prefixes → F14–F16
displaced forms (nowrite slot, free_run, slot_fetch, abort_unit=loop) →
F19–F22 immediates and RMW → F23/F30/F35 transfers → F24/F31 strings →
F32/F34/F39/F40 the 0F page → F25 LDEA → F29 I/O frames → F33 miscellany →
F36–F38 remaining data forms.

## Rule disposition

Of the spec's 108 "special" fitted rules plus the 29 enums fitted after the
spec (fits 45–62 and the WP124/125 candidates, treated as adopted), the
design puts: 21 as emergent from the structure (e.g. `room_ir=arrival_idle`,
`io_hold=posted_b2b`, `hold_fetch=le_q`, `start_sync=b2b_modrm`); 61 as a
registered flag or timer in a named module (latch port family, S5 flags,
arbiter window family, `pf_cnt`, the `page_*` timers, `lea_wb`); 29 as
microcode row attributes (`rmw_alu=through`, `io_count=nowait`,
`disp16=word`, `abort_unit=loop` loading `retry_cnt`, the string/cvt/mul_imm
row families); 23 as decode attributes (format bits: register-only class,
port-form IN/OUT, one-byte register form, long one-byte form, register
shift/MUL/DIV unit, fixed-lookup group form, two-byte-immediate register
form, ModR/M-latched-at-start form, far transfer, memory-indirect transfer,
one-byte-immediate memory form, group RMW form, base+index+d16 mode, 0F
register form / bit field, 0F memory form, TEST1 [m], full-queue-plus-latch
start, even-half operand byte, MUL imm, LDEA, DBNZ, transfer class, DW-count
request); and 3 as documented divergences checked by the corpus: the
start-time oracle decode (hardware decodes length/class from the opcode and
ModR/M as they arrive; no refresh-off timing is expected to move), a P-pass
start exceeding the S5 budget (none today, enforced by `test_ucgen`), and
`page_b2b_win=run`'s two-cycle look-back (replaced by a `take_near` flag
carried from the previous fetch into its b2b successor; F34 rbit / F32 k=2
cells would catch a difference).

## Risks

- **The fixpoint temptation.** Any "needs a retick" finding is logged as a
  divergence candidate and scored, never coded as iteration; the lint test
  rejects settle constructs.
- **Per-opcode hacks leaking in.** Exceptions must be a row field or a
  format bit from the generator; RTL compares `fmt`/row fields only.
- **The 0F `page_*` rules (23 fields).** Built last (S5) as flags/timers
  (`pf_cnt`, `dlv_commit`, `mt_floor`, `full_latch`) and format bits; a
  lower F32/F34 score is accepted at S5 entry, the whole-corpus gate closes
  it.
- **Hardware decode vs the model's start-time oracle.** `need` is exact
  once the ModR/M byte is taken; before it, the loader's take count comes
  from the opcode's format. The inverse check and F2/F4/F14 gates show
  whether any family reads the difference.
- **Wide comparators / synthesis.** No stamps; counters ≤ 11 bits; ROM in
  BRAM; per-module `efx_map` at S3 and S4 catches any module over ~1,500
  LUTs early.
- **Reset and the prelude.** The RTL runs the real reset exit and prelude
  (as `v35s_chain_model` does); `score.pre_score` reports the pre-window
  separately; gates use the from-`t_fill` score.
- **Divider timing.** 16 restoring steps fit under `div.exec` 39; split over
  two clocks per step if 30 ns is missed.
- **Model drift.** Fit 62 is tracked; WP124/125 candidates (+97) are
  committed unfitted. The generator reads whatever `fit.json` is tracked;
  adopting fits 63/64 later only regenerates data.

## Order against the chain-model work

The chain-model work is paused at fit 62 (memory `v35s-pause-after-fit62`).
S1 and S2 need nothing further from it. If fits 63/64 (WP124/125) are
adopted later, `ucgen` regenerates and the inverse check re-verifies; the
RTL structure does not change.

## First actions after approval

1. Write `docs/v35s-core-v2.md` from this plan (architecture, stage gates,
   rule disposition, divergences) and update the memories
   (`v35s-no-rtl-no-refresh-focus` → RTL work resumed under this plan).
2. Launch S1 (generator, worktree agent) and S2's front-end modules
   (`v35_bus`, `v35_queue`, `v35_loader`, `v35_top`, bench, build and
   replay plumbing; a second worktree agent) in parallel; S2's gate needs
   S1's decode table only for `need`, so the bench can start with a
   hand-written stub table.


# Appendix A: block architecture (design agent report, 2026-11-02)

## 0. Governing choices

- One CPU clock = one `ce` (the wrapper's `state_start`); every module's state is written only at `ce`. Inside a clock the combinational logic is a fixed chain, evaluated once: `delivery (registered) → EU stage A (take / IR-load / post decisions) → queue room → arbiter grant → EU stage B (issue-released advance) → next state`. No settle registers, no iteration.
- The model's phase order is not reproduced. Where the chain above cannot express a model behaviour, the corpus gate decides; the chosen divergences are written down, not patched per opcode.
- Microcode rows carry literal counts. Class integers are resolved by the generator; only data-dependent counts (shift count, mul/div, BCD pairs, string elements, bit-field cost, waits) come from hardwired counters selected by a row field.

## 1. Block diagram and modules

```
v35_top (slot ports = v35s_model.sv:25-43; instance name `model`)
 ├ PCK divider + reset exit (copied from v35s_chain_model.sv:89-151)   ce, ce_mid
 ├ v35_sfr (reused)                 prc wtc rfm idb
 ├ v35_refresh (reused, state ports dropped)      rf_pending → arbiter; rf_start ←
 ├ v35_bus    (v35_biu.sv trimmed: no _x outputs, no STATE_DUMP)
 ├ v35_queue  ─ q_* ─┐
 ├ v35_loader ─ ld_* ┼─ v35_arbiter ─ grant_* → v35_bus
 ├ v35_ucode  ─ uc_* ┘      ↑ issue
 ├ v35_eu     (datapath) ── req_* ┘
 ├ v35_regram (256×8, two 16-bit ports)
 └ v35_trace  (`ifndef SYNTHESIS`)
```

| Module | Responsibility | Registered state (widths) |
|---|---|---|
| `v35_bus.sv` | one cycle at a time; pin timing verbatim from `v35_biu.sv:290-350`; read latch mid‑B3; delivery registers | `cur_valid, cur_kind[2:0], cur_pos[2:0], cur_len[2:0], cur_addr[19:0], cur_width[1:0], cur_data[15:0], cur_internal`; `dlv_valid, dlv_kind[2:0], dlv_addr[19:0], dlv_width[1:0], dlv_data[15:0]`; `io_recover[1:0]`; `wlatch[2:0]`; `fetch_since[3:0]`; `refresh_row[8:0]` |
| `v35_queue.sv` | 6 bytes + 1-byte latch; byte-wide write port with a fixed owner chain; room; request flag; fetch pointer; b2b commit; abort/retry | `byte[6][7:0], head[2:0], count[2:0]`, `latch[7:0], latch_v, latch_full`, `flag`, `fetch_ip[15:0]`, `inflight`, `b2b`, `abort_pos[1:0], abort_v, retry, retry_loop`, `shift_hold`, `io_held`, `req_age[6:0]` (saturating), `drop, drop_hold` (refresh) |
| `v35_loader.sv` | IR, operand take handshake, decode-table lookup to a format word, `need`, `ready` countdown, `ir_hold`, `ea_end` | `ir_v, ir[7:0], ir_page`, `need[2:0]`, `ready[1:0]`, `ir_hold`, `ea_end[1:0]`, `modrm_next`, `fmt` (format word, ~40 b: class[6:0], len[2:0], modrm, mod[1:0], reg[2:0], rm[2:0], imm[1:0], disp[1:0], w, dir, grp, fixed, page, sfx seg[2:0], rep[1:0], cond[3:0]) |
| `v35_ucode.sv` | ROM + sequencer: cursor, current row, wait evaluation, loop counters, unit-hold phase, floors | `tmpl[8:0], k[3:0]`, `row` (48 b), `cnt[8:0]` (resume − t), `sync_mode[1:0], sync_n[1:0]`, `wb_cnt[1:0]`, `hphase, hold_cycle`, `floor_d[2:0], floor_i[3:0]`, `rf_hold[2:0]`, `halted, halt_t[1:0]`, `loop_n[8:0]` |
| `v35_eu.sv` | operands, EA, ALU/flags, write data, request record, PC/PSW | `pc[15:0], psw[16], ps_shadow[16]`, `ea_off[16], ea_seg[16]`, `opa[16], opb[16], res[16]`, `rd_latch[16]`, `imm[16], disp[16], port[8]`, `req` (valid, kind[2:0], addr[19:0], width[1:0], data[15:0], setup[6:0], count[6:0], free[2:0], grp, detached, second_half, not_before[2:0], lift, ready_since) ×1 slot + 2 queued (kind/addr/width/data/setup only), `div` iteration state (33 b + 4 b) |
| `v35_regram.sv` | 8 banks × 32 B + data RAM in 256 B; port A r/w 16/8, port B read 16 | two 128×8 BRAM halves (even/odd), inferred |
| `v35_arbiter.sv` | setup counting, request window FSM, fetch holds, grant | `win[1:0]` (counting/eve/free/issuable), `free_held, grp_held`, `last_io_start_age[3:0]`, `run` (fetch run), `after_refresh, beat_eval, t4_at` |

Named interfaces (all combinational within the clock unless marked reg):

- bus → *: `dlv_*` (reg), `bus_busy, bus_fetch_inflight, bus_in_wait, bus_fetch_last` (this clock is a fetch's last), `bus_fetch_end_prev` (reg), `io_recover_win`, `wlatch_busy`.
- loader ↔ queue: `ld_take_n[1:0]`, `ld_irload`, `ld_commit` → queue; `q_avail[2:0], q_head0[7:0], q_head1[7:0]` → loader.
- loader → ucode/eu: `op_start`, `fmt`, `take_last` (the instruction's last operand byte taken this clock), `take_bytes[15:0]`, `need`.
- queue → arbiter/eu: `q_room[3:0]` (signed), `q_stored[2:0]`, `q_want`, `q_b2b` (reg), `q_latched`, `q_inflight`, `q_abort_v`.
- ucode ↔ eu: `uc_row` fields out; `ok_take, ok_data, ok_issued, ok_sent, ok_wb, ok_sync, ok_loop, ok_quiet, alu_busy` in.
- eu → arbiter: `req_*`, `req_post` (posted this clock); arbiter → eu/ucode: `issue` (the slot's cycle starts this clock), `issue_nowrite`, `issue_half`, `count_inc`.
- arbiter → bus: `grant_start, grant_kind[2:0], grant_addr[19:0], grant_width[1:0], grant_data[15:0], grant_latch`.
- eu ↔ regram: `ra_addr[7:0], ra_we[1:0], ra_wdata[15:0], ra_rdata[15:0]`; `rb_addr[7:0], rb_rdata[15:0]`. Bank address = `{psw[14:12], slot[4:0]}` with `REG16/SEG` slot offsets from `validation/v35s/model/eu.py:17-18`; data-RAM accesses (IDB:E00–EFF with RAMEN) use the same port A with the linear low byte.

The four same-clock dependencies, without iteration:

1. Delivery before take: `dlv_*` are registers written at the previous `ce` (the cycle ended last clock, `data_ready=0`). The queue's `q_avail` adds the delivered word combinationally before the loader's take; no loop because `dlv_*` depend on nothing in this clock.
2. Takes/posts/IR-load feed room → arbiter: stage A (loader take, IR load, EU post) uses only registered state plus `dlv_*`; `q_room` is a pure function of (registered queue state, `ld_take_n`, `ld_irload`, `dlv_valid`); the arbiter reads `q_room`, `q_want`, `req_*`. Strictly feed-forward.
3. Grant → b2b commit and write-port arbitration at clock end: the queue's next-state logic takes `grant_start && grant_kind==FETCH` and `bus_fetch_last`. `b2b_next = bus_fetch_last && want_after_delivery(room with the ending word stored and the IR slot as the rule counts)`; registered → `q_b2b` read by the arbiter next clock. The write port owner is a fixed priority: (a) a committed take or IR load this clock, (b) else the latch drains one byte if storage has room, (c) a delivered word's first byte always stores, its second byte stores if the port is free and room, else enters the latch. No arbitration depends on the grant.
4. Issue releases the EU on the issue clock: `issue` is computed by the arbiter after stage A; stage B of the sequencer consumes it: a row waiting on `issued/wait/sent/data(write)` completes, the cursor advances through zero-time rows, and a following `clocks` row starts its countdown this clock. Stage B may not take bytes or post a new request this clock (a take or post row reached in stage B executes next clock); it may load the IR when `ir_hold` is released (model `machine.py:185-188`), with the room change seen by the request flag at next clock. This is the one deliberate departure from the model's retick (which could take on the same clock); the gate measures it. (Appendix B refines this: a memory write releases at end+1 in the model too, so the second pass is bounded to I/O issue clocks and the `ir_hold` clear.)

## 2. Microcode

Row format (48 bits, `v35_pkg::uc_row_t`):

| Field | Bits | Meaning |
|---|---|---|
| `kind` | 5 | CLOCKS, NOWAIT, TAKE, DATA, POST, POST_IO, SLOT, ISSUED, SENT, WAIT, WBSYNC, FLUSH, FLUSH_FROM, DECIDE, HALT, FETCH_HOLD, FETCH_RELEASE, QUIET, FROM_START, HELD_CLOCKS, SPLIT_FLOOR, END |
| `n` | 9 | literal clocks (0..510) / take count (0..2) / hold length |
| `nsel` | 3 | 0 literal; 1 EA table by `fmt.mode` (hardwired 7 entries, fit `ea`); 2 shift loop (`per_shift_count`×count); 3 mul/div unit length (literal + `mneg` sign clocks); 4 bit-field cost (`v35_bf_cost`); 5 string element loop; 6 literal + waits; 7 CL-dependent (`grpcl`) |
| `tag` | 3 | none/exec/loop/loop_odd/mexit/tail/ea/shift — drives the boundary map and the unit hold |
| `bkind` | 3 | read/write/io_read/io_write/nowrite/refresh-internal (SFR) |
| `asrc` | 3 | EA / SP−2 / SP / port imm / port DW / vector / far+2 / string src-dst |
| `wsel` | 2 | width: `fmt.w` / byte / word |
| `setup` | 7 | setup clocks |
| `free` | 3 | last fetch-free setup clocks (7 = all) |
| `grp` | 1 | group-free rule (free clocks only on an idle bus) |
| `tkind` | 3 | take: plain/lead/chain/word/port/opcode2 |
| `wsrc` | 3 | write datum: res / reg / imm / PSW / PC / PS / EA / string |
| `wb` | 2 | write-back clocks owed to the successor's WBSYNC when this is the last row |
| `last`, `sync`, `boundary` | 3 | template end; take sync after this take; refresh boundary bit |

Wait conditions by kind (evaluated in `v35_ucode`): CLOCKS counts `cnt` down, stalling at a boundary while `rf_hold` or the unit hold (`tag∈{exec,loop,...}` and a fetch past its second clock, every second clock from `hphase`) holds; NOWAIT counts only when `!bus_in_wait`; TAKE completes when the loader returns `take_n ≥ need-for-this-row` and, with `sync`, then waits `sync_n` fetches (owed: in flight + requested on the take clock, 0..2; lapses when `q_room<2 && !q_inflight && !q_abort_v`); DATA posts `req` (setup/free/grp from the row) and waits for `issue` (write) or `dlv_valid && dlv_kind==req.kind` (read); POST posts and advances; ISSUED/WAIT/SENT wait on `issue`/delivery/`issue`; WBSYNC waits while `wb_cnt≠0`; SLOT waits for the I/O latch release; FLUSH/DECIDE run the transfer gap counter against `fetch_since`; floors (`dfloor`, `istart`, `fgrp`) are timers armed by TAKE rows and checked by DATA/POST rows.

Hardwired (not in rows): the shift loop counter (CL & 1Fh / imm / 1), the restoring divider's 16 iterations under the class's exec, the BCD pair counter (CL), the string element counter (CW, with REP exit on Z), the unit-hold phase toggle, `wlatch` 4, `io_recover` 2, `rfm_delay` 3, the floors, the refresh hold.

Generator `validation/v35s/chains/ucgen.py` (new): enumerates every form the frozen decoder accepts (opcode × ModR/M × 0F byte, as `rtlgen.py` did) under the fit, calls frozen `templates.steps` + `refresh_hold_steps`, maps each tuple to a row with symbolic sources (`asrc`, `nsel`), dedups identical row lists into templates, and emits: `fpga/v35s/core/v35/v35_ucode.hex` (rows), `v35_ucode_tbl.svh` (`v35_tmpl_of(fmt)`: class × {mem, disp, imm, signed, byte, cross} → template base), `v35_decode_tbl.svh` (§3), and `v35_consts.svh` (EA table, `hold_q`, `io_b2b_q`, widths). Header carries fit.json's md5. `test_ucgen.py`: (a) regenerate and diff; (b) inverse check: expand each form's template back to step tuples with the fit's integers substituted and assert equality with `templates.steps` for every enumerated form (that is the S1 gate); (c) ROM bound: rows ≤ 2048, templates ≤ 512.

## 3. Function path

Decode table (`v35_decode_tbl.svh`, generated by `ucgen.py`): 256 native + 256 ext entries from `pla3_tables.svh` (has_modrm, w-from-bit0, dir-from-bit1, 1BL/prefix, sreg_mov, modrm_store) joined with `build/deps/nuV30/docs/facts/instructions.json` (`encoding` → immediate bytes, 0F page) and frozen `templates.decode` (class). Group opcodes (`GROUP_OPCODES`) get a reg-field override table (16 × 8). Length = 1 + page + modrm + disp(mod, rm) + imm; the loader computes it from `fmt` and the ModR/M byte on its take, so `need` is exact before the displacement arrives. Unknown opcodes: class `trap_nop` (one-row template, 2 clocks, no bus) — the generator lists them in the header.

Register RAM: two 128×8 BRAMs (even/odd bytes) give a 16-bit word at any even slot; byte access selects a half. Port A: EU operand read in the TAKE/pre clocks, write-back at the last CLOCKS row or a dedicated WB cycle; Port B: second register read (EA index, ALU second operand, SP for stack). PSW.RB selects the bank; PS is shadowed in `ps_shadow` so the fetch address adder (`{ps_shadow,4'b0} + fetch_ip`) needs no RAM port; every PS write updates both.

Functions (`v35_fn_pkg.sv`: verbatim from `v35_eu_pkg` with `mut` removed): `v35_alu`, `v35_szp`, `v35_shift` (single-step form, iterated by the loop counter — or the full-count form if timing permits; decide in S3), `v35_mul` (combinational, DSP), `v35_cond`, `v35_adjust`, `v35_bcd8`, `v35_bit1`, `v35_rot4`. `v35_div` is rewritten as a 16-iteration restoring divider sequenced under the class's exec clocks. `v35_ea_off` becomes `v35_ea.sv`: base from port B, index from port A (two reads in the pre clocks), disp from the loader, segment = prefix / SS for BP forms / DS0, string destination DS1; `phys = {seg,4'b0} + off`.

Data flow in step with microcode: a read's `dlv_data` → `rd_latch` (lane-selected by `dlv_addr[0]`, width) = operand B; operand A from port A; the ALU row (the `clocks` row tagged `alu`, or the first exec clock) registers `res`/`psw`; a DATA/POST write row builds `req_data` by `wsrc`; the END row writes back to port A (`wb` clocks). Immediates and displacements are latched by the loader as bytes arrive (`imm`, `disp`), so a store's write datum is ready when its POST row issues.

## 5. Debugging against the model

`v35_trace.sv` (`ifndef SYNTHESIS`, `+v35_trace=FILE`) writes one line per CPU clock with anything to say: `t  X kind addr width data` on a cycle start (same vocabulary as `normalize.Event`), and strobes `S pc cls tmpl`, `T n`, `L`, `P kind`, `I`, `B` (b2b), `A` (abort), `R` (room, flag), `W` (wait reason: sync/data/issued/wb/hold/floor). Python `validation/v35s/chains/evtrace.py`: runs the frozen `Machine` with a small hook list (bus starts from `bus.cycles`, EU starts from `eu.trace`, takes/IR loads/posts from thin wrappers around `Decoder.take`, `load_ir`, `EU._post`, `Queue.issue`) into the same line format, aligns both at `t_fill` with `normalize`, and prints the first divergent clock with ±8 clocks of both traces and the RTL's wait reason. `replay --score --show N` remains the scorer; `evtrace` is for the first failing run of a family.

## 6. Risks and containment

- Fixpoint temptation. Stage A/B split is fixed in `v35_ucode`'s header and enforced by a lint test (`test_v35_struct.py`: grep for `settle`, `for ... iterate`, `always_comb` blocks that read their own outputs). Any "needs a retick" finding is logged as a divergence candidate, not coded.
- Class‑keyed exceptions leaking in. Every exception must be expressible as a row field or a `fmt` bit produced by the generator; RTL compares only `fmt`/row fields, never opcode bytes (lint: no `8'h..` opcode literals outside `v35_decode_tbl.svh`). The 108 "special" rules are triaged: P → row/format data or one guard in the named module; C → the five cleaner mechanisms (explicit write port, `alu_busy`, window FSM, boundary stall, b2b carrying the reissue) built once each; M → not built until re‑measured.
- The 0F `page_*` rules (23 fields, fits 57–62). Build the page as ordinary templates (`tkind=opcode2` chained take) first; add `page_*` behaviours only as boundary bits/floors in rows (`page_mt_end`, `page_disp`) or as `fmt.page` guards in the queue's IR‑slot rule and the arbiter's hold. Accept a lower F32 score at S5 entry; it is the last gate.
- Wide comparators / synthesis blow‑up. No clock stamps: all A2 stamps are countdowns ≤ 9 bits or 1‑bit "this clock" flags; room is 4 bits; the ROM is BRAM, not a case statement; `tmpl_of` is a small table; per‑module synthesis in S7 catches any module over 1,500 LUTs early (S3 and S4 each end with a module‑level `efx_map`).
- EU releasing on the issue strobe. `issue` → stage B is one comb path; its depth is bounded (arbiter grant ≈ 3 levels of priority). The multicycle constraint covers it; stage B's restricted vocabulary (no take, no post) keeps the path from looping back into room.
- Reset and the prelude. The model starts at the POP PSW read; the RTL runs the real reset exit and prelude (as `v35s_chain_model` does). `score.pre_score` reports the pre‑window separately; S2's gate uses the from‑`t_fill` score and records the pre‑window drift.
- Divider / multiplier timing. Mul is a DSP; the 16‑step divider fits under `div.exec` 39; if the restoring step misses 30 ns, split it over two clocks (still < exec).


# Appendix B: the fitted mechanisms as hardware state (design agent report, 2026-11-02)

Scope: the refresh-off machines (F8/F13/F17/F18/F27/F28 excluded). Model references are `validation/v35s/chains/sim/*.py`; "A2/A3/A4" is `docs/v35s-chain-rtl-spec.md`. The WP124/WP125 candidate enums are treated as adopted. Fitted values quoted are from `validation/v35s/chains/fit.json` (83 classes, 685 integers, max integer 105, max 18 per class).

## 1. State table (registered state, one update per CPU clock)

Principle: every model stamp `x_t == t` becomes a combinational "this clock" strobe where the event is produced; `== t-1` a registered copy; an order between two stamps a flag captured when the later event happens; a "no earlier than clock N" a down-counter. Widths follow A2/C2–C4 where they were measured.

### Bus unit (BIU) (`bus.py`, plus the arbiter's history, A3 "History the arbiter reads")

| Element | Bits | Set | Cleared | Replaces |
| --- | --- | --- | --- | --- |
| `c_v, c_kind, c_pos, c_len, c_addr, c_width, c_data` | 1+3+3+3+20+2+16 | issue strobe at edge | `c_pos == c_len-1` at edge | `bus.current` |
| `c_b2b, c_thru, c_commit, c_on_start, c_after_post, c_lea_start, c_disp_in_flight, c_ir_before, c_take_near` | 9 flags | at the fetch's start (b2b_at, thru, start_now, slot has fixed read, LDEA started now, IR valid, take_now/take_prev); `c_disp_in_flight` set by a displacement take while `c_pos>0` | with the cycle | `Cycle.b2b/.thru/.commit` (bus.py:28-31), `cur.start == start_clock` (eu.py:827), `x.start > pfree` (eu.py:1794), `lea_fend` (eu.py:317), `_page_b2b`'s `ir_t <= bus_start` / `take_t+1` (queue.py:450-454), `_disp_in_flight` (queue.py:411) |
| `dlv_v, dlv_word, dlv_odd, dlv_commit, dlv_slot, dlv_disp` | 1+16+1+1+1+1 | edge ending a fetch's B3 (copies the cycle flags) | next edge | `arrived_t == t`, `f[-1].commit` (eu.py:519-522), `slot_word`, `_page_take_ask`'s look-back (arbiter.py:500) |
| `fetch_end_prev`, `cpu_end_prev` | 1, 1 | fetch / non-fetch ended last clock | each edge | `last_fetch_end == t-1`, `retry_after` trigger (machine.py:169) |
| `fetch_run` (current fetch started b2b after a fetch), `fetch_run_prev` | 1, 1 | at a fetch start when `fetch_end_prev` | at cycle end / next fetch | `_fetch_run` (arbiter.py:458), `prev=True` form |
| `io_win` | 2 (countdown 0..3) | I/O B3 (+1 if `io_ext`/`disp_io`) | counts down | `t <= last_io_end + io_recover` (arbiter.py:529), `disp_io=extend` (arbiter.py:213-224) |
| `gap` | 1 | `disp_io` / `disp_io_wait` extension | next clock | `last_end = c.end+1` |
| `io_start_age` | 4 sat | I/O issue | — | `ios[-1].start` (arbiter.py:571-575) |
| `last_write_age` | 4 sat | write B3 | — | `str_single_start=write` (eu.py:348) |
| `wlatch` | 3 countdown (wlatch=4) | write issue, read delivery, reg-form last take, slot | — | `wlatch_until` |
| `abort_v, abort_pos` | 1+2 | arbiter abort strobe | pos==2 | `abort_end` (queue.py:637) |

### Prefetch queue (`queue.py`)

| Element | Bits | Set / cleared | Replaces |
| --- | --- | --- | --- |
| storage 8×8, `head`, `tail`, `cnt` | 64+3+3+4 | tail: the delivery's bytes at the edge (first byte always, second only when it enters); head: pops_T + pop_L + pops_P | `bytes` (8 inside a clock, C2 decision 1) |
| `lat_v` (second byte waits), `lat_full`, `lat_in_now` | 1+1+1 | set at delivery edge when a commit/IR load held the port (`_port_busy`, queue.py:258, `modrm_port`) or `cnt>6`; cleared at the first edge with the port free and `cnt<=6` (`check`, queue.py:235) | `latched`, `latch_full`, `latch_in_t` |
| `uncommitted` | 1 | take in progress (`take_commit=at_end`) | `uncommitted` |
| `flag` | 1 | evaluated on change clocks (`_evaluates`, queue.py:497) by T, L, X (issue reissue), P; forced by `t4/io_run` (refresh, not built) | `flag` |
| `rq_v`, `rq_now` (comb), `rq_older_slot`, `rq_at_take`, `rq_take_own`, `rq_after_io` | 1+1+1+1+1+1 | `rq_v` set in X when wanted and not inflight; `rq_older_slot` captured when the slot's request posts/promotes with `rq_v` up; `rq_at_take` = raised on a take clock not committed b2b; `rq_take_own` = raised on `fetch_end_prev && dlv_disp`; `rq_after_io` = raised with `io_start_age` since | `requested_at` compared with `posted` (arbiter.py:582,600,628), `== take_t` (arbiter.py:504), `>= ios[-1].start`, `< t` (eu.py:292) |
| `inflight` | 1 | fetch/abort issue; delivery / abort end | `inflight` |
| `fetch_addr` | 20 | issue +2 (odd target +1), flush | `fetch_addr` |
| strobes `arrive_now, removed_now, qport_now, ir_now, take_now, disp_now, mate_now, start_now`; regs `take_prev, removed_prev` | 8 comb + 2 | produced in S1/S2/S3/S5 | all the `*_t == t` stamps; `take_t >= t-1`; `page_fl_eval=next` (queue.py:507-511) |
| `starts_sat` | 2 | start | `starts > 2` |
| `b2b_at` | 1 | E of a fetch's last clock | `b2b_at == t` |
| `abort_now_start` | 1 | abort and start on one clock | `abort_t == start_clock` |
| `retry, retry_loop, retry_cnt, abort_ref` | 1+1+9+1 | abort; `retry_cnt` loaded by the loop row (`resume - per_shift_count` / `- mtail`, eu.py:893-899) | `retry_at` |
| `shift_held, shift_cnt` | 1+9 | count_latch (eu.py:1111-1118, 911-912) | `shift_until` |
| `nop_held, io_held` (+ "start since" each) | 2+2 | machine.py:196-227 | `nop_held`, `io_held` |
| `slot_fetch` | 1 | nowrite slot fetch | `slot_fetch` |
| `gdisp_v, gdisp_cnt`; `pdisp` not built (`page_disp=go`) | 1+3 | grp_disp (eu.py:1165) | `gdisp_until` |
| `discard, flush_held_v, flush_cnt, str_held (v,inf,cnt4), str_raise (v,cnt3), xfer_abort, lea_ea (v,cnt2), odd_xfer (v, fed, nt2, until v+cnt3), th_armed, th_from_v, hold_dlv, cvt_held` | ~30 | F23/F24/F25/F33 rows and flags as E3/WP77 built them | same names |
| `pb_done, pr_done, nb_done, nb_v` | 4 | once-per-form commitments, cleared at start | `pb_start/pr_start/nb_start == start_clock`, `nb_at` |

### Loader / IR (`decoder.py`)

| Element | Bits | Notes |
| --- | --- | --- |
| `ir_v, ir_byte` | 1+8 | loaded in L (and in P), emptied by a start |
| `need` | 3 | `take` decrements; `start` loads `op_len-1` |
| `ra_cnt` | 5 signed | `ready_at`: loaded `nx` at the last take (`nx0` at an operand-less start), +1 for `io_take_nx` (eu.py:1053), −(page_mt wait) (eu.py:1051), ±1 `one_idle`/`long_exec` |
| `ir_hold` | 1 | set at start (`ir_load=disp_data`, `xfer_mem_ir`) or by `page_ir=delivery` (eu.py:1095); cleared by the displacement's delivery-clock take or the EU data cycle's issue (S5) |
| `ea_cnt` | 2 | `ea_end` countdown (eu.py:883) |
| `modrm_next, skip, mate_next, imm_reg, fresh, lea_wait, stopped` | 7 | as C3/WP79 |
| decode attributes for the room rule: `pre_room_cls, far_cls, xfer_mem_cls, imm16_reg` | 4 | replace `decoder.cls` reads in `room` (queue.py:100-104, 217) |

### EU sequencer (`eu.py`, rows from `templates.py`)

| Element | Bits | Notes |
| --- | --- | --- |
| `upc` (class base + k), `k` | 10+4 | ROM address; `k` for `steps[k]` tests (`decide` row for `_nt_b2b`, `wbsync` row for `wb_fetch`) |
| `res_cnt`, `res_past` | 11+1 | `resume` as a countdown; loaded by clocks rows (row imm, `2*count`, `bf_cost`, `exec+cl`...), moved by holds (+1 unit/long/rot4 waits, `latch_start`, −1 `one_idle`) |
| `left, left_nw, taken, op_len, imm_bytes, disp, width` | 2+3+3+3+2+2+1 | |
| `sync_mode` (none/count/defer), `owed` | 2+2 | `sync` as "fetches still owed" (C4 decision 5); `defer` resolves next clock (`imm_landed`) |
| `mr_sync_v, mr_owed` | 1+2 | `page_imm_sync=lead` (eu.py:1036) |
| format bits: `modrm, mem, unit, fixed, ro, page, page_mem, page_reg, page_fixed, page_imm, full_latch, imm_half, half_word, grp_form, gdisp_cls, cl_count, mode_bix, bf_cross, regonly, interlocked` | ~20 | from the decode at start |
| `start_now` (comb), `start_prev`, `start_age` | 1+1+4 sat | `start_clock` compares (`lookup_start` eu.py:960, `floor_n`) |
| `fetch_start` | 1 | a fetch issued on the start clock |
| `done_v, done_age, wb, wbu_cnt` | 1+2+2+3 | `done_t`, `wb`, `wb_until` (C3 decision 8) |
| `lea_fwb_cnt` | 3 | `lea_wb=fetch`: loaded `fwb` at the end of the `c_lea_start` fetch |
| `halted, halt_prev` | 2 | `halt_status` |
| `latch_held, latch_cnt, latch_wait_now, port_now, port_held[3]` | 1+3+1+1+3 | `latch_until`, `latch_wait`, `port_t/port_held` |
| `floor_n, dfloor_v, dfloor_cnt` | 4+1+3 | `imm_count=start`, `disp_floor` |
| `exec_v, exec_par, hold_done_fetch, hold_done_abort` | 1+1+1+1 | `unit_hold` (eu.py:608-635): boundary = `(t-exec_t-hphase)` even → a toggling parity bit started `hphase` clocks after `exec_t` |
| `unit_early, reg_early, shift_latched, cvt_armed, gdisp_late, lea_split, rot4_v, rot4_hit, long_from, refill, zfail, str_rep, str_single, sreg` | ~15 | as named |
| `mt_floor_v, mt_cnt`, `page_mt_v, page_mt_cnt, page_mt_d_v, page_mt_d_cnt`, `mw_from_v` | 1+2, 1+3+1+3, 1 | WP116/118/125 (eu.py:987-1052) |
| `pf_cnt` | 7 sat | replaces the back-count at post (eu.py:1780-1798): reset at the start (and again at `mt_floor`), increments on every clock with no fetch on the bus, reset by a fetch (except one with `c_b2b && c_after_post` or `c_thru && pthru`); at the fixed read's post `count = min(pf_cnt, setup)` |
| `mf_cnt` | 4 | the same for `mul_imm_count=sync` (eu.py:1811-1816) |

### Request records (`arbiter.py:47-110`)

Three positions (slot, q0, q1), shifting on `_promote`; `own` a 2-bit index. Per record: `v, kind(3), addr(20), width(2), second_half, setup(7), count(7), free_need(3)+all, free_orig(3), through(7), lead(2), issued(2), posted_now, ready_prev, lift_done, done_v, done_cnt(3), floor_hold, free_held_prev, grp_held_prev, detached, port, moved, dw_moved, nowait, free_bus, imm1, gdisp, dwlike, restart, run_wait, pfree_v, pthru(2), ftail(2), io_ext, sreg, sreg_held, sreg_ok_v, sreg_at_v` ≈ 85 bits each. `ready_since == t` becomes `ready && !ready_prev` (`ready_prev` set at the first choice where it was issuable, arbiter.py:730). `posted` survives only as `posted_now` and the queue's order flags.

Arbiter: no state of its own beyond the above (A2:100-104); it writes the request fields and the BIU history.

## 2. One-clock evaluation order

Six combinational stages, strictly feed-forward; everything is latched at the single CPU-clock edge.

| Stage | Model phase | Reads | Produces |
| --- | --- | --- | --- |
| S0 | — | registers only | `bus_free`, `fetch_inflight`, `in_wait`, `fetch_past_b2` (c_pos≥2), `delivery_now = dlv_v`, `abort_end_now`, request `ready`/`holding`/`counts()` (arbiter.py:137-177 read only registered bus state and `in_wait`) |
| S1 | C, A | S0 | `avail = cnt + dlv_bytes` (bypass muxes from `dlv_word` when `cnt<2`), `owed−1`, `own.done_now` for a delivered read, `retry` → `flag` on `cpu_end_prev` (queue.py:643), `room_pre` |
| S2 | T | S1 + EU/loader regs | the EU row: holds (`unit_hold` from `fetch_past_b2`), the start gate (`_start` eu.py:175-313: all inputs registered or S1), the row action: `pops_T` (0..2), ModR/M commit, `post_T` into slot/q0, sync update using `room_after_T` → `flag_T`; `take_now/disp_now/mate_now/start_now` strobes |
| S3 | L | S2 | `pop_L` (IR load, `load_ir` decoder.py:85), `ir_now`; `room_L`, then the queue's `wants_fetch` (queue.py:556) → `fetch_want`, `rq_now`, `flag_X` |
| S4 | X | S0–S3 | `_choose` (arbiter.py:507-843) as one priority tree: data vs fetch (`_fetch_first`: `b2b_at` reg, `became_ready_now && rq_now`, `imm1`), the nowrite slot, the abort test (`triple = start_now && take_now && ir_now && starts_sat`), the fetch issue (reissue `flag` with the word reserved, queue.py:611-617, `free_idle` → `nb_cnt`). Output: issue strobe {none, fetch, data, io, nowrite-slot, abort} + request field writes + `b2b/thru/commit` for the new cycle |
| S5 | P | S4 strobe | the restricted second EU pass, enabled only by `io_issue_now` (a detached OUT's issue or an owned I/O's `done_at = t`, eu.py:2008-2017) or by `ir_hold` clearing on an EU data cycle (machine.py:185-189): (i) the start gate re-evaluated with the I/O interlock satisfied (`io_busy_start=issue`), (ii) the started form's first row if it acts this clock (a 1-byte take with `pops_P`, a lead take, a post into the free slot, or loading `res_cnt`), (iii) a second IR load `pop_P`, (iv) `io_ir_hold`, `io_take=unit`, `port_issue`, `nop_hold` flag writes (machine.py:196-227). No S5 output feeds S4. |
| S6 | E | S5 | `head += pops_T+pop_L+pops_P`; `check`: `lat_v` next = `dlv_v && (port_busy_now || cnt_next>6)` where `port_busy_now = (removed_now && !(modrm_commit_only && !arrive_now)) || ir_now` (queue.py:258-266); `b2b_at` next = fetch ends now && `_raised` (flag/room after S5) with the `page_dcommit`, `page_run`, `page_b2b`, `xfer_nt_b2b` branches (queue.py:371-409); `latch_start`/`one_idle`/`bcd_fetch` resume adjustments (machine.py:231-257) |

The four genuine dependencies: delivery→take is S1→S2; takes/posts/IR load→room/request→arbiter is S2→S3→S4; arbiter→b2b commit and latch result is S4→S6 (both are edge writes that read the strobe); the I/O issue releasing the EU on the issue clock is S4→S5. A memory write releases at `c.end+1`, not on its issue clock (eu.py:2017), so S5 is only the I/O issue clock and the `ir_hold` clear — this is what bounds the second pass.

What the retick needs and the approximation if S5 is cut down: the model's P tick can run a whole chain of zero-clock rows. S5 is limited to {start, one first-row action, one post, one IR load}. The generator must enumerate, per interlocked class (`INTERLOCK["reg_pfx"]` + lea, transfers, div: eu.py:68, 587-596), the actions of row 0/1 on a start clock and assert they fit; today they are: `reg` → take (pre 0) or clocks (pre0 4); `imm` → lead take + clocks 3; `shift_imm/shift_cl/mul/div` → take; `prefix` → clocks 2; `lea` → chain take; `ret*` → post read + `issued`; `branch_*/call` → take or clocks. All fit. If a class ever needs more, the fallback is to delay that start to t+1 with `res_cnt` pre-decremented; the families that would see it are F3 (OUT NOP OUT, `io_interlock`/`io_busy_start`), F12 A (`io_ir_hold`), F19 D (`io_take_nx`), F15 O (`sync_io`), F16 L / F14 G (`io_take=unit`), F7 (`nop_hold`).

## 3. Microcode vocabulary

A row is executed on the clock the sequencer reaches it; zero-time steps of the model are folded into the next timed row as side-effect fields, so the ROM has at most one timed action per clock and no in-clock iteration. Row format (≈48 bits):

- `op` (5): the timed action.
- `nsrc` (3) + `imm` (8): count source — row immediate; `op_len-1`; `disp`; `imm_bytes`; `2*count` (loop counter); `bf_cost−span`; `exec+cl`; `cost−r` (hrel split).
- `wait` (3): none / own `done_now` / own `issued` / slot empty / `wbu_cnt==0` / fetch-quiet / flush-gap / halt.
- request descriptor (16): `rkind` (3: read, write, io_read, io_write, nowrite, none), `asrc` (3: EA, SP−2, SP, port, IX+i, IY+i, vector, EA+2), `width` from format, `setup_src` (2: row imm / class setup / `fsetup+cl` / `rsetup+imm+1`), `free_src` (2: `setup_free` / `grp_free` / all / 0 / `ufree`), `through` (1, `rmw_alu`), `nowait` (1), `grp` (1, `free_bus`), `detached` (1), `restart` (1).
- `tag` (4): ea, mexec, loop, tail, exec, lead, chain, word, port, dlv, room, raise, forever, bf.
- `tdelay` (1): the next row starts this clock (0: `continue`, e.g. `lead`, `page_imm_sync=lead`) or next (1: `resume = t+1`).
- `skip` (3): skip the row if no displacement / no immediate / register form / not crossing / CW==0 / hold not armed.
- `arm` (3): side effects on the row's first clock: set `ir_hold`, `fetch_hold` arm/lift, `flush_from`, `fetch_release`, `exec_t` capture.

The 21 step kinds:

| Kind | Row meaning | Hardwired state read |
| --- | --- | --- |
| `clocks` | `res_cnt := n` (n from `nsrc`); loop rows reload per iteration from `count`; `tag` fixes `exec_t`, `ea_cnt`, `clk_tag` | `unit_hold` parity, `io_exec` (c_on_start && io), `long_exec/rot4` wait holds, `mt_floor` |
| `nowait` | `left_nw := n (+1 if start_prev && fetch_start)`, decrement on `!in_wait` | `in_wait`, `str_io_setup` run flag |
| `take` | pop `nsrc` bytes (1/clock, 2 for `word`), `late_read`/`late_fetch` holds, ModR/M commit, `page_mt` wait, then sync set (`owed := inflight + asked`), `tdelay` | `avail`, `fetch_past_b2`, `arrive_now`, `lat_v`, `ir_v` (`loads_after`) |
| `data` | post + wait `done_now` in one row | slot free, `done_v` |
| `post` | post and go on (`tdelay 0`) | slot/q0 free |
| `post_io` | post detached; `latch_held := 1` | slot/q0 free |
| `slot` | wait until the slot has no cycles left; then `res := latch_cnt` | slot `v` |
| `issued` | wait `own.issued != 0` | request |
| `sent` | unused under the fit (`burst_wait=data`), not built | — |
| `wait` | wait `own.done_now`, retire | request |
| `wbsync` | wait `wbu_cnt == 0` | EU |
| `flush` | wait `!fetch_inflight && fetch_end_age > gap`, then flush queue, `pc := target`, `refill := 1` | BIU ages, `abort_now`/`decide_abort` |
| `decide` | as flush without the flush (gap = `nfgap`/`cfgap`; `nb_v`/`odd_until` select `fe_age_old`) | same |
| `halt` | `halted := 1`, `stopped := 1` | — |
| `fetch_hold` | arm `str_held` for n clocks / `th_armed` (BF_TAKE_HOLD, `dlv`) / lift (n=0) / `room` skip | `cnt` |
| `fetch_release` | `str_held := t+n` or infinite; `raise` tag → `str_raise` | — |
| `flush_from` | `flush_held := t+n` | — |
| `quiet` | wait `!fetch_inflight && !fetch_want` | S3's `fetch_want` (previous clock's registered copy suffices: the model's `wants_fetch` here reads the same state) |
| `from_start` | `res := max(t, start_age→start+n)` if `cvt_armed` else `t+n2` | `start_age`, `cvt_armed` |
| `held_clocks` | `wb += n` if `cvt_armed` | `cvt_armed` |
| `split_floor` | wait `ls_age >= n` of the split second half | `ls_split, ls_age` |

The dynamic insertion of `("slot",), (post, …)` on a port take under `port_latch=relatch` (eu.py:1895-1901) becomes two fixed rows after every port-take row, skipped when the slot held no detached I/O at the take.

Per-row immediates (read by a row): `pre, pre0, exec, exec0, post, cl, igap, cpre, grp, grp1, loop, loop1, first, mid, wmid, setup, setup0, rsetup, wsetup, xsetup, xrsetup, xwsetup, rwsetup, tsetup, vsetup, usetup, rfree, rfree0, tfree, spre, wpre, mexec, bmexec, smexec, sexec, rexec, nexec, zexec, cexit, rexit, zexit, rpre, xfetch, zfetch, xsplit, dadd, dclk, fdisp, mhold, phold, pdhold, hx, hrel, cond, span, xspan, sthru, alu`. Class-table constants (read by hardwired logic outside a row, indexed by the running class): `nx(3), nx0(5), wb(2), mwb(2), rwb(2), uwb(2), xwb(2), flwb(2), fwb(3), wbsync(1), wbsync0(1), hphase(2), mtail(2), mtx(1), sidle(2), relatch(2), lead(2), setup_free(3), grp_free(3), fsetup(2), ftail(2), dfloor(2), istart(3), fgrp(2), fgrp_free(2), dhold(2), hold(5), nhold(3), chold(3), fgap(4), nfgap(1), cfgap(4), gap(1), ugap(1), ufree(3), grpcl(2), last(1)` ≈ 90 bits × 83 classes ≈ 7.5 kbit, plus the EA table (7×2 bits).

ROM size: 83 classes × ≤14 rows = 1,162 rows × 48 bits = 56 kbit worst case; with rows shared by format (the 212–330 templates C3/WP79 enumerated collapse onto class rows with `skip` bits) the realistic count is 600–750 rows ≈ 30–36 kbit, one 36-kbit block RAM or two M9K-class blocks. Count loops are one row each with the 11-bit `res_cnt` / 9-bit count register (SHL by 255 = 510 clocks; INS whole-register 1,998, WP79 decision 11).

## 4. Rule disposition

Buckets: (a) emerges from the structure; (b) a registered flag/timer in a named module; (c) a microcode row attribute; (d) a decode attribute a silicon designer still needs; (e) not expressible without look-back/iteration.

Counts over the A4 register's 108 special rules plus the 29 post-A4 fitted enums listed above (137): (a) 21, (b) 61, (c) 29, (d) 23, (e) 3. (Many rules sit in two buckets; the primary is counted.)

(a): `room_ir=arrival_idle`, `hold_count=ahead`, `latch_hold`, `latch_midtake`, `abort_latched` (`owed==0`), `abort_reg_end=early`, `abort_unit_end=early`, `io_hold=posted_b2b`, `hold_fetch=le_q`, `free_idle_b2b`, `dw_port=hold`, `wlatch_src`, `slot_latch`, `port_ready=issue`, `dw_count_b2b` (reads this clock's count), `start_sync=b2b_modrm`, `late_read`'s `loads_after`, `_io_form`, `_nt_b2b`'s row test, `refill_start`'s class test (IR decode), `page_disp=go`.

(b) (module in brackets): `latch_disp`, `modrm_mate`, `modrm_port`, `count_latch`, `latch_start`, `imm_landed`, `port_landed`, `port_issue` [queue/BIU latch port]; `abort_fetch=retry`, `retry_first`, `abort_reg` [BIU abort FSM + queue retry]; `request_reissue=no_mem`, `nop_hold`, `io_ir_hold`, `io_take=unit`, `sync_io`, `io_take_nx`, `io_busy_start`, `io_exec` [S5 flags]; `io_b2b`, `io_older`, `imm_start` (second room evaluation with `ir_v=0`), `page_mtake=eu`, `page_mt_end=exec`, `page_mwait=commit` (`dlv_commit`), `wlatch_hold` [EU start gate]; `arbiter=b2b`, `free_run`, `free_hold`, `free_idle`, `slot_fetch`, `grp_io_hold`, `imm1_first`, `dw_count`, `dw_slot`, `dw_lift`, `disp_io`, `disp_io_wait`, `io_recover`, `port_latch=relatch`, `halt_status` [arbiter/request flags]; `grp_disp`, `gdisp_dlv`, `ea_ir_room`, `ea_b2b`, `disp_floor`, `imm_count`, `lookup_start`, `ir_load=disp_data`, `page_ir=delivery`, `slot_room`, `slot_idle` [queue/EU timers]; `page_cl=thru`, `page_commit=post`, `page_run`, `page_b2b`, `page_b2b_win=run`, `page_dcommit`, `page_imm_run`, `page_mem=fixed` (`pf_cnt`), `page_imm_sync`, `page_ir_room=end`, `page_fl_end`, `page_fl_eval`, `mul_imm_count` (`mf_cnt`), `lea_wb=fetch`, `lea_room`, `lea_slot`, `lea_disp`, `one_idle`, `long_exec`, `rot4_exec`, `unit_hold`, `xfer_odd/xfer_nt/xfer_nt_b2b/decide_abort/flush_hold/xfer_abort` [BIU cycle flags + EU counters].

(c): `rmw_alu=through`, `grp_free_bus`, `io_count=nowait`, `bf_read=fixed`, `str_in_io`, `str_out_rd`, `sync_req=disp`, `post_on_take`, `disp16=word`, `disp_take`, `pop_mem_order`, `push_mem_write`, `rmw_shift`, `shift_count=late`, `shift_cl_mem`, `shift_mem_imm`, `grp_ops/grp_fixed/imm8_grp/fixed_lookup/fixed_lookup_grp`, `dest_route`, `grp_read`, `abort_unit=loop` (loop row loads `retry_cnt`), `cvt_hold/cvt_tail/cvt_from`, `bcd_fetch`, `mul_imm_reg/read/hold/half`, `mem_order/imm_order/imm_head/ea_post/grp_mode`, `page_take=own`, `ret_imm_hold`, `prepare_order`, `burst_wait`, `str_*` row families.

(d) decode attributes: "register-only class" (`io_interlock=reg_pfx` with `reg_div`, `lea_form=reg`, `branch_reg=reg`); "port-form IN/OUT" (`wlatch_cls`, `dw_port`); "one-byte register form" (`nop_hold`, `one_idle`); "long one-byte form" (`long_exec`, `one_idle=long`); "register shift/MUL/DIV unit" (`unit_hold`, `abort_reg`, `abort_unit`, `io_take=unit`, `sync_io`); "fixed-lookup group form" (`abort_fixed`, `fixed_floor`); "two-byte-immediate register form" (`room_ir_imm`); "ModR/M-latched-at-start form" TEST r,r / INC-DEC r8 (`room_ir_pre=modrm`, `pre_modrm`); "far transfer" (`far_room`); "memory-indirect transfer" (`xfer_mem_room`, `xfer_mem_ir`, `late_disp_word=split`, `xfer_mem_disp`); "one-byte-immediate memory form" (`imm1_first`); "group RMW form" (`grp_disp`, `gdisp_dlv`); "base+index+d16 mode" (`disp_io_wait=bix`); "0F register form / bit field" (`page_start=reg`, `page_b2b`, `page_mtake`, `page_imm_sync`); "0F memory form" (`page_mem`, `page_cl`, `page_ir`, `page_dio=free`, `page_mwait`); "TEST1 [m]" (`page_mtest=wait`, `test1_head`); "full-queue-plus-latch start" (`page_ir_room=end`, `page_fl_*`: a flag set at start from `cnt==6 && lat_v && !inflight`); "operand byte is the even half of its word" (`half_word`: `cvt_hold`, `bf_imm_hold`, `mul_imm_hold`, `ret_imm_hold`, `imm_half`, `xfer_odd`); "MUL imm" (`mul_imm_exec=hold`); "LDEA" (`lea_io=recover`, `lea_wb`); "DBNZE/DBNZNE" (`xfer_nt=dbnz_z`); "transfer class" (`xfer_abort`, `TRANSFERS`); "string / BCD / bit-field request counts as DW" (`str_count`, `bf_count`, `burst_count`).

(e): (1) the start-time oracle decode: the model decodes the whole instruction from the image at the start (eu.py:217), including a ModR/M byte not yet queued (3 corpus starts, all refresh-on) and immediates (463 starts: their values matter only to count loops, which the loop row loads at the take, and to `half_word`, which is the pc's parity, so no timing divergence is expected refresh-off); (2) a P-pass start whose first rows exceed S5's budget, checked by the generator's enumeration (none today); (3) `page_b2b_win=run`'s two-cycle look-back (queue.py:462-470) replaced by `c_take_near` carried from the previous fetch into a b2b successor — equivalent whenever the fetch before the current one is the one the take landed in, which `cycles[-4:]` filtering also assumes; F34 rbit/F32 k=2 cells would catch a difference.

## 5. Risk list and bring-up order

Most likely to differ after restructuring, in decreasing order: (1) the S5 pass (families F3 OUT-interlocked starts, F12 A, F19 D, F15 O, F14 G/F16 L); (2) the latch-port counting (`_latched_now` queue.py:271 rephrased as `port_busy_now`; F0 even/odd at 0 waits, F12 B, F21 d8, F19 D/F20); (3) the request flag's change clocks and the `requested_at` order flags (F6, F21, F15 P `slot_fetch`, F14 T `grp_io_hold`); (4) `pf_cnt` versus the model's at-post back-count (F34 mbit, F32 0F memory forms); (5) the E-stage b2b decision reading S5's state (F7 OUT OUT, F19 D `nop_hold`); (6) the 9-bit count loops and `retry_cnt` (F16 S/L); (7) the E-stage resume adjustments `one_idle`/`latch_start`/`bcd_fetch` (F33 long forms, F3 k4 MOV r,imm8, F32 BCD).

Bring-up order (each step adds the mechanisms the family isolates, so a divergence is caught in the simplest family that reads it):

1. F0 fill — BIU cycles, storage/head/tail, the latch port, `room`, `b2b_at`, reissue, `fetch_run`.
2. F2 release — takes, IR load, `on_change` evaluation, `late_read`, `nx`, `wbsync`.
3. F3 register costs — ROM rows for reg/imm/shift/mul/prefix, `unit_hold` parity, `abort_reg`, the S5 pass (OUT NOP OUT), `wlatch`, `latch_start`.
4. F6 starvation — `hold_fetch=le_q`, the abort FSM and retry, `request_reissue=no_mem`.
5. F4/F5 memory — request slot and window (`counts`, `free_need`, `through`), EA table, `io_recover`, `grp_free_bus`, `dw_count`, `imm_count`.
6. F7 neighbours — relatch rows, `dw_port`, `nop_hold`, `port_issue`, `io_b2b`.
7. F9/F11/F12 shifts and prefixes — `late_read` at waits, `count_latch`, `imm_landed`, `io_take_nx`, `io_ir_hold`, `shift_count=late`, the 9-bit loop.
8. F14–F16 displaced forms — `nowait` lookup, `lookup_start`, nowrite slot (`slot_room/slot_idle`), `free_run`, `slot_fetch`, `abort_unit=loop`, `io_take=unit`, `sync_io`, `pop_mem_order`.
9. F19–F22 immediates and RMW — `imm1_first`, `disp_floor`, `ir_load=disp_data`, `ea_ir_room/ea_b2b`, `free_hold/free_idle`, `dw_count_b2b`, `rmw_alu`, `disp16=word`, `modrm_mate`, `port_landed`.
10. F23/F30/F35 transfers — flush/decide rows, `fetch_end_age` and `fe_age_old`, `xfer_odd/nt/nt_b2b`, `decide_abort`, `refill_start`, odd-target fetch.
11. F24/F31 strings — `fetch_hold/release`, `quiet`, `nowait`, `split_floor`, compact REP rows, `str_single_*`, `str_in_io/str_out_rd`.
12. F32/F34/F39/F40 the 0F page — `pf_cnt`, `pthru`/`c_thru`, `dlv_commit`, `page_mt*` timers, `full_latch`, `pb/pr_done`, `page_dcommit`, `page_fl_*`, BCD and bit-field rows.
13. F25 LDEA — `lea_room/lea_slot/lea_disp/lea_wb`, PUSH R/POP R burst rows, PREPARE.
14. F29 I/O frames — `disp_io`, `disp_io_wait`, `grp_disp`, `gdisp_dlv`, `dw_lift`.
15. F33 miscellany — `one_idle=long`, `long_exec`, `incdec`, `cvt_*`, `mul_imm_*`, `room_ir_pre=modrm`, `pre_modrm`.
16. F36–F38 remaining data forms — class aliases (`BASE_CLASS`), `op AL,imm8`, the signed MUL/DIV rows.

Critical model files: `queue.py` (room 288-339, `_latched_now` 271, check 235, end_clock 368-409, requesting/wants_fetch 518-581, issue 601, abort/retry 630-665); `eu.py` (`_start` 175-561, `_unit_hold` 608, tick 696-1373, `_submit` 1736-1836 incl. the back-count 1780-1798, `_post` 1909, issue/complete 1995-2034); `arbiter.py` (Request 47-110, counts 137, arbitrate 180-242, `_fetch_first` 429, `_page_take_ask` 487, `_choose` 507-843); `templates.py` (`_head` 943, `_ea_setup`/`_group` 1014-1108, `_steps` 1185, `_wp78_steps` 1600-1748, `_string_steps` 1779); `machine.py` (run 149-286: the C A T L R X P E order, the P-phase rules 185-228, the E-phase adjustments 230-257).

## Clocking and timing (directive of 2026-11-03)

The harness's fabric clock (30 ns) and CPU clock (eight fabric ticks) are not the target. The core
must be able to run at a **fabric clock of 64 MHz with a CPU clock of 32 MHz**: two fabric ticks
per CPU clock. The work of one CPU clock is split across those ticks with state machines or
pipelining (two clock enables, or one clock enable at twice the CPU rate), never left as one
combinational chain. **No multicycle or other special timing constraints**: the design closes
timing on the plain clock period, in every module, and a stage's gate includes a static-timing
result at 64 MHz with zero constraint exceptions.

What this means for the structure of Appendix B §2: the six evaluation stages of a CPU clock keep
their order and their meaning, but they are spread over the two fabric ticks (and over registered
pipeline boundaries inside a tick where a chain is still too deep), and the architectural state
still updates once per CPU clock. Where the model evaluates several sequential decisions in one
clock (three microcode rows in a pass, the P pass after the arbiter's grant), the generator
pre-resolves what can be pre-resolved into the ROM (zero-time rows folded, skip decisions as row
attributes), and what remains is a small state machine stepping one decision per tick. The
corpus gate (RTL = model on every refresh-off run) stays the regression for every such change;
the model is a guide to the behaviour, never to the depth of the logic.

Background: S7a's first whole-core place-and-route (2026-11-03) stalled on a 275 ns feed-forward
chain (the T pass's three row evaluators, the arbiter's priority tree and the P pass's three
evaluators in series inside one CPU clock) against a 30 ns clock with partly rejected multicycle
constraints. The user's direction is to fix the structure, not the constraints.

## S8: the table-driven sequencer (decided 2026-11-03)

S7b showed that the two-tick structure cannot be closed by reorganising the sequencer's RTL: a row's
semantics are 15–20 LUT levels, a CPU clock needs a start and up to three rows in series, and the start reads
the live IR format (scratchpad v2/s7b/s7b-depth-reading.md; v35_ucode 62 / 59 levels a tick against a budget
of about 6–8). The user decided to redesign the sequencer. S8 replaces evaluation with selection: the
generator computes outcomes, the ROM carries them, the RTL selects.

**Principles.** Silicon exactness stays the gate (the corpus at both spacings, the write data, SST and the
vectors unchanged). The clocking directive stands: two enables, no multicycle or input constraint; any tick
beyond two means another pipeline register set, never more time for a path. Area and ROM width are the
currency. A behaviour change is allowed only where the corpus shows no run (the registered start's W_DEC
wait: 0 of 30,536 runs by the `+v35_wdec` probe) and is counted by the trace. The inverse check covers every
table entry, not a sample: a Python mirror of the model's step semantics evaluates each (row, condition
vector), (pair, vector) and (template, avail) entry and compares it with the steps the model runs on that
clock. RTL still compares format bits and row fields only (test_v35_struct).

**Architecture.**

1. *The registered start.* The start's gate inputs, format, class constants, template key and the
   ModR/M-derived run bits come from the decode ahead's registers written at the previous `ce_a` (`nf_fmt`,
   the class entry, `ka_key`, the run bits), not from the live IR format. In-tick the start reads only S1's
   strobes (a fetch in flight, room and latch values, `b2b_now`, the delivery, `fl_now`). A start whose
   decode ahead was not the live format (the ModR/M or 0F second byte arriving on the start clock) waits a
   clock (W_DEC, Divergences 19 / 28 widened to the whole format; `+v35_wdec` counts it; 0 on the corpus).
2. *Row outcome words.* For each row, ucgen enumerates the row kind's P-known condition vector (the wait's
   inputs, the skip and arm conditions, `n == 0`, `io_exec`, the exec flags, `post_ok`, the gap compares; 1–8
   bits, the median 3) and emits the outcome per vector value beside the row: complete, cont, the take
   count, post, the pass-state deltas and the strobes that are not plain functions of the static fields.
   The RTL selects the entry by the registered vector (a mux) and applies the three in-tick quantities after
   it: avail (a compare / subtract against the take count), the ModR/M byte's length / disp / mode (a
   2-level decode of the byte when it arrives on the clock), `str_exit`. The vector's field list per row kind
   is generated into `v35_pkg.sv` and checked by test_ucgen.
3. *Pass tables for the in-form chains.* A pass never chains evaluators. The measured in-form pairs
   (POST → TAKE, DATA → CLOCKS, LEAD TAKE → DATA, DATA → DATA, POST_IO → CLOCKS, NOWAIT → DATA, DATA → POST,
   DECIDE → CLOCKS, DATA → SPLIT_FLOOR and the rest of the ~60 kind pairs on the corpus) are a table per
   row-kind pair × the union vector, generated as logic (`v35_pass_tbl.svh`) or a small ROM, the row words
   supplying the static parts; the third row (pop_mem's delivery / post / clocks, a lead take's clocks after a
   start) is one fixed case. Anything outside the generated pairs is `voc_miss`, 0 on the corpus.
4. *The cross-form pass.* The next form's template is known a clock ahead; its row-0 outcome per avail
   (0..8) is read a tick early from a table indexed by the template base (231 × 9 entries, about 50 kbit, or
   logic). Case E (the cursor row ends the form) is then: the row's "ends the form" bit selects the row-0
   outcome, avail less the row's take count picks the entry — two selects and a subtract.
5. *The P step* keeps S7b's case structure, its first-row action taken from the same outcome words.
6. *Budget.* The core's block RAM stays within what the harness leaves (the harness uses 920 of 1,056
   RAM_5K): the core ≤ 80 RAM_5K. Sequencer LUT4 ≤ 12,000 (S7b 10,797). Depth, module-local by the
   levelizer: v35_ucode tick A and tick B ≤ 12 levels (from 62 / 59), confirmed by one routed run of
   `v35_timing.sh ucode` at 15.625 ns with the worst path and slack reported; whole-top runs only when the
   per-module runs close.

**Work packages.** S8a (generator): the vector lists, the outcome words, the pass tables, the template
row-0 table, the mirror and the extended inverse check; test_ucgen regenerate-and-diff. S8b (RTL): the
registered start, the select-based T pass and P step, the ROM banks widened or paralleled for the outcome
words, the loader's interface (the decode ahead's registers as the start's source), v35_trace's W_DEC count.
S8a and S8b run in one worktree agent (the RTL's select structure and the generator's table format are one
design); the hand-back is a diff against the S7b landing. Gates: the S7b gates (corpus at both spacings with
`+v35_chk`, data, SST, regfile, fn, lint × 4, fast tests, nine modules) plus the depth and resource budgets
above.

**What S8 does not solve.** After S8 the same-clock chain outside the sequencer remains: arrival → the IR
load → room / request → the arbiter's choice → P → the decode ahead → the ROM address, estimated 20–25 levels
in tick A and 15–20 in tick B against about 6–8 a tick at 64 MHz. Closing two ticks at 64 MHz then needs
speculation (the arbiter and P computed for both outcomes of the take and the IR load, selected late; the
next template for each pop count); without it, the fabric clock the design closes at is lower. That is S9's
question, decided from S8's routed numbers with the user.

## Record

- 2026-11-02: plan approved; S1 (generator) and S2 (front end) launched as worktree work packages.
- 2026-11-02, **S1 landed**: `validation/v35s/chains/ucgen.py` (+ `ucgen` subcommand), `test_ucgen.py`
  (12 tests: regenerate-and-diff, the inverse check equal on all 108,302 expansions of the 45,819 enumerated
  forms, decode length/class/EA mode per form, the S5 budget over 63 interlocked start pairs, size bounds,
  hex/struct round trip), `test_v35_struct.py` (the structure lint). Generated under `fpga/v35s/core/v35/`:
  1,133 rows × 64 bits in 231 templates, 84 classes (trap_nop + 83), a 93-bit `v35_fmt_t`, decode tables for
  256 native + 256 0F opcodes + 17 group overrides, the class table (84 × 122 bits). Departures from the plan's
  row sketch (recorded in the README): 64-bit rows; `sync` implied by a TAKE's tag; `wsrc` deferred to S6;
  no `boundary` (refresh out of scope); REP/BCD strings as one element body looped n times; bit-field
  crossing and the compare exit as skip rows; relatch as one row; 288 register forms the decoder accepts
  but no template runs decode as trap_nop.
- 2026-11-02, **S2 landed**: `fpga/v35s/core/v35/` front end — `v35_top` (slot, PCK divider, reset exit, SFR
  store latch), `v35_bus` (pin timing from `v35_biu`, delivery registers, I/O recovery window, data latch,
  the 3-clock aborted fetch cycle), `v35_queue` (8-byte ring + 1-byte write-port latch, room at each
  stage, the request flag on change clocks, b2b at a fetch's last clock, the no_mem reissue, abort/retry
  as a countdown, the holds), `v35_loader` (IR, need, ready countdown, ModR/M commit and word-mate
  strobes, IR loads in L and P), `v35_arbiter` (one request slot, setup counting, the fetch holds, the
  choice; window FSM / nowrite slot / alu_busy left as named inputs for S4), the throw-away
  `v35_eu_script`, `v35_trace`, `evtrace.py`, and the `--core v35` build/replay plumbing. **Gate: F0 18/18,
  F0w 20/20, F1 54/54, F2 120/120 RTL-exact, all also pre-window exact and strobe-identical to the model on
  every run.** Verilator `-Wall` clean. Divergences (README): register-only decided from the opcode in
  the stub; `refill_start=full_io` / `flush_hold` approximated before the pre-window only; the SFR
  store's datum sampled at the cycle's end; each EU pass evaluates at most two rows. The structure lint
  now flags only read-before-assign inside an `always_comb` and ignores zero literals; the S2 stub's
  opcode literals are allowed until S3 retires it.
- 2026-11-02, **S3 landed**: `v35_ucode` (the ROM sequencer: four banks of 64-bit rows read as a four-row
  window registered at `ce`, the T pass of at most three rows and the P pass of at most one operand byte, the
  resume countdown, take sync, unit-hold parity, wb_until, latch_until and NOWAIT counters), `v35_eu` (the
  register-class datapath: operands through the RAM ports named a clock ahead, exec at the last operand
  byte's take or the read's delivery, one register write per clock plus one pending, a stepped restoring
  divider, the request record by `asrc`/`wsel`/`xop`), `v35_regram` (4 × 128 × 8), `v35_fn_pkg` (the
  functions lifted from `v35_eu_pkg`); the stub decode and `v35_eu_script` retired; the loader decodes
  through `v35_fmt_of` a clock ahead; the function bench retargeted (`rtl_vectors.py --fn`, format V35FN-1).
  Generator: decode attributes `breg`, `idle1` and the datapath attributes `xop aop opa opb wd nwr sx stk`
  derived from the opcode and group field (no opcode literal in the RTL); `v35_fmt_t` 115 bits. **Gate: F0
  18/18, F0w 20/20, F1 54/54, F2 120/120, F3 840/840, F9 408/408, F11 132/132, F12 204/204 RTL-exact; F20
  3,165/3,594 (model 3,594)**; all 5,390 pre-window exact; no decode miss and no dropped write on any run.
  The 429 F20 misses are one mechanism: a PUSH or OUT posted while a detached OUT holds the single request
  slot (the model queues it behind the I/O, `eu.queued`; S2's slot makes the EU wait), which is S4's
  request path — confirmed on F20-r-push-l0-pfxmovr-outimm-pE-w0 at t_fill+94. Lint `-Wall` clean in all four
  macro configurations; function bench 19,578 vectors 0 bad; `efx_map` of ucode + eu + regram 13,296 LUT4 /
  631 FF / 32 RAM_5K / 8 MULT in 200 s (the ROM banks as plain 64-bit vectors infer block RAM; packed-struct
  arrays folded into LUTs). Departures recorded in the README: three rows per T pass; the four-row ROM
  window with decode a clock ahead (a start whose template is not in the window waits a clock: none in the
  gate); segment registers and CW as flops rather than RAM entries (to be stored through to the bank as
  well: S4); one write per clock. Risk noted for S7: the three modules alone exceed the whole-core LUT and
  BRAM targets; S4's module check reports ucode, eu and arbiter separately.
- 2026-11-02, **S4 landed**: the full request path in `v35_arbiter` (the slot and two queued positions
  shifting as registers for `eu.queued`; the record fields fit 62 reads, `ready && !ready_prev` for
  `ready_since`; the setup counting, `free_run` / `free_hold`, `grp_io_hold` from an `rq_aio` order flag,
  `slot_fetch`, `hold_fetch` in full, `io_recover`, port_latch's `not_before`, the `dw_port` hold, the
  nowrite slot, `dw_count`; one priority tree in S4), the bus cycle flags `after_post` / `disp_in_flight` /
  `ir_before`, `v35_ea` (mode decode, base/index from the RAM ports, the segment select) split out of
  `v35_eu`, the memory-form rows with the floors as countdowns, `rmw_alu=through` (a `dclk` class-table
  column; the class table is 124 bits), `mexec` / `unit_early`, the loader's `ir_hold`; segment registers
  and CW stored through to the register RAM with flop shadows. Generator: a trailing `("clocks", 0)` after
  a sync take is a NOP row the canonical form had dropped (F19 adddwi_nop started its successor four clocks
  early): 1,140 rows, inverse check equal. Seven bring-up mechanisms closed (the queued request; POP r/m
  aiming SP until its stack post; a PORT take's own I/O setting `own_v`; a third T-pass row inside a running
  form for pop_mem's delivery + post + clocks on one clock; a per-pass `pnew` for OWN_DONE; memory MUL's
  sign clocks from the delivered datum; the NOP row). **Gate: all 20 families RTL = model on 16,670 runs
  (F0–F22 without the refresh-on lists): RTL-exact = model-exact everywhere, F22 1,314/1,320 sharing the
  model's six, pre-window exact throughout; the e22ec6f baseline had 3,969 misses.** Lint `-Wall` clean in
  four configurations; function bench 9,527 vectors 0 bad; the nine offline modules unchanged. Divergences
  9–12 (README): three request positions (a fourth post waits: none in the gate); the running form's own
  request takes its EA / result live at issue and store_imm's immediate at B2; the P pass reads the T pass's
  environment where the model's retick would see a changed one; `alu_busy` is the record's `through`.
  Per-module `efx_map` (LUT4 / FF / RAM_5K / MULT): arbiter 1,427 / 289 / 0 / 0; ucode 10,594 / 360 / 28 /
  0; eu + ea 5,785 / 422 / 0 / 8; regram 16 / 14 / 4 / 0; queue 858 / 154 / 0 / 0; bus 230 / 152 / 0 / 0;
  loader 3,469 / 54 / 20 / 0; sum 22,379 LUT4, about 2.5× the S7 target. The LUT reading for S7: ucode's P
  pass ≈ 4,300 and the third T row ≈ 1,150 because each `do_row` copy carries the 348-bit pass state (six
  copies); eu's `mkreq` is instantiated twice; the loader evaluates `v35_fmt_of` six times a clock. S7's
  cuts: one `do_row` with the format word and class constants as registered sideband and P as a restricted
  re-evaluation; one `mkreq`; one decode lookup.
- 2026-11-02, **S5a landed**: the transfers (start-time `taken` / `zfail` / `n0` from the PSW and CW at the
  decode a clock ahead, with the generated `tsel` / `zpol` / `xshort` / `rot4r` bits; FLUSH / FLUSH_C /
  DECIDE acting: the queue's flush and discard, the odd-target fetch, flush_hold, xfer_odd / xfer_nt /
  xfer_nt_b2b, decide_abort, refill_start, far_room, stack_wb, ret_far_fetch; PC / PS / SP written by the
  datapath, BRK and RETI vectors), the strings' element loop (CW / CL counts, the REP compare exits as
  skip-ahead rows, fetch_hold / release, QUIET, SPLIT_FLOOR / FROM_START, str_held, str_single_start as a
  last-write counter, dwlike), LDEA and the stack frame (lea_wb / lea_disp / lea_room, PUSH R / POP R,
  PREPARE / DISPOSE), the I/O frame probes, the register miscellany (one_idle=long, long_exec, incdec, the
  conversions under cvt_hold, mul_imm_count=sync counted forward, rot4's wait) and the data forms. Widths
  corrected from the corpus: `free_need` 7 bits (BRK's 8, a memory shift's 16), `str_held` 6 bits. The
  pass budget grew: a skipped row costs no row, the P pass evaluates a third row in a running form, a FLUSH
  reached in P is not acted on (diag-reported; none in the gate). The prelude's BR far now runs the real
  flush_hold / refill_start rows (Divergence 4 closed) and the pre-window still matches. **Gate: the 32
  refresh-off families without a 0F form, 25,742 runs, every one RTL = model (model-exact 25,647; the
  95 misses all the model's own and shared), pre-window exact throughout, `--diag` silent.** Lint clean in
  four configurations; function bench 0 bad on F0 F3 F23 F24 F25 F30 F31 F33 F38 (funcref raises
  NotModelled on F35 F36 F37 for opcodes E3, 9C, FF /2: pre-existing); the nine offline modules unchanged.
  Divergences 13–18 (README): the REP prefix decoded with the queue's head byte as its string opcode; IX / IY
  / CW as flops written through to the RAM when the port is free; the pass-budget changes; the element
  loop's exits taken from the datapath at the loop row; model history kept as counters; QUIET waiting on
  the request as the clock began. Per-module `efx_map` LUT4: arbiter 1,615, ucode 13,091, eu + ea 7,679,
  queue 1,030, loader 3,962, bus 248, regram 16; sum 27,641 (S4: 22,379), RAM_5K 44, MULT 9; the growth is
  inside the existing `do_row` / `mkreq` / `v35_fmt_of` instances (no copy added). S5b (the 0F page and the
  whole refresh-off corpus) launched.
- 2026-11-03, **S5b landed — the whole refresh-off corpus matches**: the 0F page (the escape decode a
  clock ahead with `modrm_skip` and the page-1 re-decode; TEST1 / CLR1 / SET1 / NOT1 on registers and
  memory, ROL4 / ROR4, EXT / INS with the crossing alternatives, the bit-field cost and the pointer step,
  the BCD strings under bcd_fetch=hold), the page_* rules in their modules (`pf_cnt` and `mt_floor` and
  the page_mt timers and the full latch in the sequencer; `pb_done` / `pr_done`, page_b2b and page_run in
  the queue; `pfree` counting, `pthru` with `take_ask`, ftail and page_imm_run in the arbiter; `c_thru` and
  `c_take_near` in the bus; page_dio=free). ucgen emits `bit1r` / `pmt` / `pgb2b` / `pcl` and the BIT1 /
  ROT4 / BF operations (`v35_fmt_t` 125 bits, decode entries 211). Fixed on the way, all structural:
  page_imm_run as a property of the form, the BCD pair index counting an element that ended in the same
  pass, the `pfree` read's DW count cleared, the skip run of up to four crossing rows passing in no time
  with the held tail flag `tlr`, crossing rows decided only once the field is known (`bf_ok`). **Gate: the
  whole refresh-off corpus, 36 families, 30,536 runs, every one RTL = model; RTL-exact = model-exact
  30,361 (fit 62's refresh-off number); the 175 misses all the model's own and shared; pre-window exact
  on every run; `--diag` silent.** Lint clean in four configurations (one fix at integration: the window
  summary's loop temporary moved to module scope so the structure lint's early-read rule passes; logic
  unchanged, gate rerun on the committed tree); 23 ucgen / structure / lane tests green; function bench
  19,752 vectors 0 bad over 28 families (funcref lacks E3, 9C, FF /2, FF /4, E1: F35–F37, F39, F40
  unvectored; the 0F datapath has no function vectors, checked only by the agent's write-data comparison
  against the silicon corpus: F32, F34, F40 agree on every run, F39 on all but the LDEA → OUT AL cells);
  the nine offline modules unchanged. **Open for S6:** AL read by an OUT right after LDEA is 20h (18 F25
  runs and 6 F39 runs, data only, timing exact); Divergence 26 (the EA latch records its mode) closed the
  LDEA [BW] address bug of S5a. Divergences 19–26 (README): the 0F start before its bytes arrive runs what
  the window holds and is re-decoded at the ModR/M take; page_b2b_win=run as the bus's `c_tn`; `pf_cnt`;
  the skip run and the tail flag; page_imm_sync's lapse applied on the next clock; the full-latch end check
  reading the room after the P pass; the bit field's register updates spread over the form; the EA latch's
  mode. Per-module `efx_map` LUT4: arbiter 1,738, ucode 16,370, eu + ea 8,589, loader 4,768, queue 1,053,
  bus 259, regram 16; sum 32,793 (S5a 27,641), FF 1,855, RAM_5K 55 (loader 23: the 0F decode table), MULT 9.
  No evaluator copy added; the ucode growth is the 0F rows' attributes through the six `do_row` copies (a
  first version reading the window rows in every copy mapped to 23,233 and was replaced by a 4-bit window
  summary computed once a clock). Not built, by design: refresh timing, interrupts and bank switching, the
  trap_nop list, the WP125 candidates at their defaults. Next: S6 (function) and S7 (synthesis, retirement).
- 2026-11-03, **clocking directive** (section "Clocking and timing"): fabric 64 MHz, CPU clock 32 MHz (two
  fabric ticks per CPU clock), long chains split over ticks with state machines or pipelining, no multicycle
  or special constraints. S7a's whole-core place-and-route had stalled on a 275 ns chain (six row evaluators,
  the arbiter tree and the decode ahead in series) under 30 ns with partly rejected multicycle lines; it was
  stopped. S7's goal becomes timing closure at 64 MHz by structure; the area work continues under it.
- 2026-11-03, **S6 landed — the function path**: a whole-core function bench (`fpga/v35s/v35_core2_tb`, the real
  `v35_top` with the post-reset state preloaded through Verilator hooks, one instruction per test, about 1 ms a
  test) runs the SingleStepTests V20 suite and the `--regfile` vectors as single-instruction tests; `sst.py
  --rtl` and `rtl_vectors --regfile` are retargeted to it; `replay --core v35 --score --data` compares every
  memory, stack and I/O write datum of the replays with the silicon record; funcref models E0/E1/E3, EA/9A,
  C2/CA/CB/CF, CC/CD, 9C–9F, C4/C5, F0 and FF /2–/5. Thirteen datapath bugs fixed structurally, among them:
  LDEA's exec in the P pass read the EA of the form after T (the OUT's port byte as an offset: AL = 20h);
  PUSH r/m pushed the stale read; store_imm's untaken bytes at B2; an RMW write issued before its exec takes
  the result at B2; CVTBW/CVTWL/SAHF read 0 for AW; a move whose read delivered after the ports turned
  dropped its write; segment wrap at FFFFh (offset + base, `w16`, the queue's fetch wrapping in PS); BCWZ
  decided by CW − 1 (ucgen's `tsel` order); C6/C7 /1–/7 without MOV's attributes; a start-clock post used the
  previous form's segment prefix; RET imm16 added the immediate after SP left the ports (`sp_ret`); PREPARE's
  imm16 read as a byte; an empty BCD string's flags. **Gate, all rerun on main:** timing unchanged (36 families,
  30,536 / 30,536 RTL = model, `--diag` silent); write data 106,824 / 106,824 agreeing in every family (at
  cc0704f 104,574, with 1,776 runs differing); SST `--rtl --all` 2,849,080 pass / 0 fail over RTL_FILES and the
  100 new S6_FILES (old core 1,651,237 over RTL_FILES), counted apart: trap condition 24,387, PREPARE level
  1,941, V20's ROL4/ROR4 AL 18,368, V20's fixed PSW bits 26,281, on-chip page 887, unlisted 82, trap_nop
  register forms (F6/F7 /1–/3, FF /0 /1 /6 /7, C6/C7 reg, F6 /0, REP before a non-string form) ≈45,000, and
  three decoder divergences (F6 /1 mem, F7 /1 mem, FF /7 mem: the model decodes them as rmw without an
  immediate) ≈22,500; `--regfile` 69,099 + 38,760 vectors 0 bad (the count exceeds the plan's 58,508 because
  today's generator over today's corpus produces more); function bench 19,752 / 0 bad; lint clean in four
  configurations; 30 fast tests (incl. the new `test_sst_rtl`) green; the nine offline modules unchanged.
  eu + ea `efx_map` 8,589 → 9,123 LUT4 (the second EA adder, the datum at B2, segment-relative addressing in
  both `mkreq` instances). Divergences 27–29 (README). Decisions: trap_nop stays NOP (the README lists what
  a trap needs); V20 semantics adopted where the corpus is silent (CVTDB base 10, CVTBD by 0, the empty BCD
  string's flags, C6/C7 aliases); ROL4/ROR4's AL and PSW bits 1/3/5 stay the V35's. Open for S7: the reset
  blocks of v35_queue (take / transfer holds), v35_bus (`w_v`, `tk_prev`) and v35_ucode (`mf_*`) are
  incomplete (the bench restores a post-reset snapshot instead); MOV PS,r/m does not redirect the queue.
- 2026-11-03, **S7a landed — the build branch and the first area pass**: `V35S_CORE=v35 fpga/v35s/build.sh`
  builds the harness image with the core as the model lane (two `efx:defmacro` elements for SYNTHESIS and
  V35S_CORE_V35, the ROM banks under the project, `core/model_v35.sdc` with no timing exceptions, the build
  failing on any SDC line the place-and-route could not apply); `fpga/v35s/synth/v35_map.sh` maps one module
  or the core as a top and `v35_harness.sh` runs the whole build in the memory-capped scope with stage times
  and the timing summary. Area, behaviour-preserving (the gate after each step): each pass slot's row
  evaluator implements only the row features its slot meets on the corpus (`voc_t`, measured over all
  30,536 runs; `voc_miss` reported), the start's template by a registered key compare instead of three
  lookups and four window reads, one advance and one arm instance a row, the skip run as a per-position
  table, no second P start (none on the corpus; reported); the loader reads the decode tables once a clock
  (the decode ahead) and assembles the IR's and the re-decodes' formats from the registered entry
  (`v35_fmt_asm`, emitted by ucgen); queued arbiter positions trimmed to the request, pair flag and
  not_before count. Per-module `efx_map` LUT4: ucode 16,370 → 8,832, loader 4,768 → 2,318 (RAM_5K 23 → 0),
  arbiter 1,738 → 1,703, eu + ea 9,123 (S6's), queue 1,053, bus 259, regram 16; the whole core 31,260 →
  21,894 LUT4, 2,000 FF, 32 RAM_5K, 9 MULT (map 820 s → 491 s). Targets not reached (core 9,000; sequencer
  5,000; loader 1,500; arbiter 1,200). Timing: no routed report; the placer's register-to-register estimate
  of the core's one feed-forward CPU clock was 205–211 ns (about 70–90 LUT levels): queue arrival → the T
  pass's gate and three rows → the IR load → room / request → the arbiter tree → the P pass → the decode
  ahead → the template base → the ROM address. The multicycle work was withdrawn under the clocking
  directive; the depth reading and the two-tick proposal are at the scratchpad's v2/s7/s7-timing-reading.md
  and drive S7b. **Gate, rerun on main after the three-way merge with S6 (one conflict in v35_arbiter: both
  functions kept):** 36 families 30,536 / 30,536 RTL = model, `--diag` silent; write data 106,824 / 106,824;
  SST 2,849,080 pass / 0 fail; `--regfile` 69,099 + 38,760 vectors 0 bad; function bench 19,752 / 0 bad; lint
  clean in four configurations; 30 fast tests green; the nine offline modules unchanged. Divergences 27–30
  (README). Open from S6 for S7b: the reset blocks of v35_queue, v35_bus and v35_ucode are incomplete.
- 2026-11-03, **S7b checkpoint landed (steps 1–3 of the two-tick work)**: two clock enables through
  `v35_top`: `ce_a` the CPU clock's edge (every architectural register) and `ce_b` one fabric tick inside the
  clock (the pipeline registers that hold tick A's results; nothing architectural); `ce_a` waits for a
  `ce_b` after the reset exit. Every module's tick-A results (S1–S4: arrival, the T pass, the IR load, room /
  request, the arbiter's choice and grant) are registered at `ce_b`; tick B (S5–S6) and the `ce_a` blocks
  read only those registers and the architectural ones. The P pass is a case step (the data step against the
  other first row, the measured follow-on rows evaluated beside it, anything else reported as `voc_miss`);
  the ROM window is read by tracked offsets instead of 11-bit address subtracts. Simulation variants:
  `+v35_ticks=2` (the core's registers update only on `ce_a` and the clock's middle tick, exactly the target's
  two ticks, pins and the 30 ns recording unchanged), `+v35_ceb=K` (ce_b K ticks after the middle), `+v35_chk`
  (a sim-only check that every `ce_b` register equals its tick-A source at `ce_a`); replay passes them through
  `V35_PLUSARGS`, `V35_SIM_BINARY` / `V35_SIM_DIR` run a second build beside a gate. The timing wrapper
  (`fpga/v35s/synth/v35_tw.sv`, `v35_tw.py`, `v35_timing.sh`: a module's inputs from a shift chain, its
  outputs registered and folded onto eight pins, `create_clock -period 15.625`, no other constraint) is written
  and not yet run. **Structural finding (the agent's, directed on the same day):** the read datum is on the
  pins only from the middle of its delivery clock (where the V35 samples it), and tick A needs it (S1's bytes
  into the T pass, the start's ModR/M decode, the IR); with `ce_b` at the middle the datum reaches tick A from
  the live pins, an input-to-register path through all of tick A that at the target would have no time at
  all. Direction given: the datum register at the sample point is the *start* of tick A — `ce_a` moves to the
  clock's middle, `ce_b` to its edge, the bus starts a cycle at the edge from the grant registered there, the
  core's state is a half clock later than the model's convention while the pins stay. The one same-clock
  dependency found (the write datum of an RMW whose write issued before its exec ran is the exec's result, S5)
  is resolved by driving every write datum at mid-B2 from one register written at `ce_a` (the recorder keeps
  the last data sample while the strobe is low, so the write-data gate stays like for like; the pin change is
  README Divergence 31 in the agent's tree). Step 4 is the T pass as one row decision by cases evaluated side
  by side (no ROM compound rows: 65 % of the chained T passes cross a form boundary, which no row can fold),
  step 5 the arbiter's precomputed holds, step 6 the eu/ea pipeline registers (the reset blocks of v35_queue,
  v35_bus and v35_ucode are complete in the agent's tree), step 7 the timing runs; the swap is in the agent's
  tree, not in this checkpoint. Map in the agent's step-3 tree (LUT4 / FF): ucode 10,103 / 1,219 (S7a 8,832 /
  498), loader 2,182 / 558, arbiter 1,810 / 705, queue 1,105 / 315, bus 264 / 225, regram 16 / 14, eu + ea
  9,231 / 917; its levelizer's module-local LUT depth: ucode tick A 63 / tick B 61, eu tick B 62, arbiter tick
  A 44, queue 20, loader 19, bus 4, against ~5–6 a tick at the target. **Gate, rerun on main:** 36 families at
  the eight-tick spacing with `+v35_chk` 30,536 / 30,536 RTL = model (model-exact = RTL-exact 30,361), `--diag`
  silent, 0 check reports; the same at `+v35_ticks=2`, per-family tables identical; write data 106,824 /
  106,824 at both; SST 2,849,080 pass / 0 fail; `--regfile` 69,099 + 38,760 vectors 0 bad; function bench
  19,752 / 0 bad; lint clean in four configurations; 30 fast tests green; the nine offline modules unchanged.
- 2026-11-03, **S7b landed — the two-tick core; timing does not close by structure**: `ce_a` at the CPU
  clock's middle (every architectural register and the read-datum register: the datum is sampled where the
  V35 samples it, mid-B3, and tick A = S1–S4 runs from that register to the edge), `ce_b` at the edge (the
  pipeline registers; tick B = S5–S6 runs from the edge to the middle); `ce_a` waits for a `ce_b` after the
  reset exit; the SFR store writes at `ce_a`. The pins keep the model's timing (B1 / B2 at the edge from the
  registered grant, the strobes and the read latch at the middle from the cycle's next state) with one pin
  change: every write datum is driven at mid-B2 from one register written at `ce_a` (README Divergence 31;
  the lane keeps the last data sample while the strobe is low, for both lanes, so the write-data comparison
  is like for like). Every module has a `ce_b` register block and its tick-B logic reads tick A only through
  it (`+v35_chk` compares each `ce_b` register with its source). The P pass is one case step (Divergence 32);
  the T pass is split by cases (the cursor row's evaluator beside `fol`, the state a row leaves when it goes
  on; the second and third rows from that state; a `fol`-versus-evaluator check silent on the corpus,
  `t_fmiss` in `voc_miss`); ROM-window rows by tracked offsets; the reset blocks of v35_queue, v35_bus and
  v35_ucode complete (the whole-core bench passes with a bare reset, `V35_C2_BARE=1`; S6's open item closed).
  Plusargs `+v35_ticks=2`, `+v35_ceb=K` (1..3 after the middle), `+v35_chk`, `+v35_wdec`; `V35_PLUSARGS`,
  `V35_SIM_DIR`, `V35_SIM_BINARY`. Timing tooling: `fpga/v35s/synth/v35_tw.sv` + `v35_tw.py` (a module's
  inputs from a shift chain, its outputs registered and folded onto eight pins) and `v35_timing.sh` (efx_run
  compile at 15.625 ns, one create_clock, no exceptions, inside the memory scope). Not done, by decision after
  step 4: the generator's compound rows, the arbiter's precomputed holds, the eu/ea pipeline registers.
  **Depth (the reason for S8):** v35_ucode module-local LUT levels after step 2 88 / 79, final 62.5 / 59.4
  (tick A / tick B); the other modules eu + ea 16 / 62, arbiter 44 / 8, queue 20 / 20, loader 17 / 19, bus
  4 / 4. Routed v35_ucode in the timing wrapper (857 s, every SDC line applied): worst setup slack −47.269 ns,
  hold +0.307 ns; the worst path `wa[1]` → `wb_hold`, 57 logic levels, 62.2 ns, about 1.1 ns a level (so a
  15.625 ns tick holds about 12–14 levels, not the 5–6 estimated from the placer); 10,991 LUT4, 738 ADD,
  2,736 FF, 28 RAM_5K in the wrapper. `efx_map` LUT4 / FF: ucode 10,797 / 1,234 (S7a 8,832 / 498), loader
  2,182 / 558, arbiter 1,810 / 705, queue 1,105 / 315, bus 264 / 225, regram 16 / 14, eu + ea 9,231 / 917.
  Reorganising the RTL did not move the depth (step 4: 64 / 61 → 62.5 / 59.4) because the state a row leaves is
  most of the row's semantics; hence S8. Start-path probe (`+v35_wdec`): 0 of 30,536 runs with a start whose
  live format differs from the decode ahead's registered one (the inverted comparison fires on all 54 F1
  runs). **Gate, rerun on main after the final patch (applied verbatim over the checkpoint):** 36 families at
  the eight-tick spacing with `+v35_chk` 30,536 / 30,536 RTL = model (model-exact = RTL-exact 30,361), `--diag`
  silent, 0 check reports; the same at `+v35_ticks=2 +v35_chk`, per-family tables identical; write data
  106,824 / 106,824 at both; SST 2,849,080 pass / 0 fail; `--regfile` 69,099 + 38,760 vectors 0 bad; function
  bench 19,752 / 0 bad on the 28-family list and 23,328 / 0 bad on all 41 families; lint clean in four
  configurations; 30 fast tests green; the bare-reset SST test green; the nine offline modules unchanged.
- 2026-11-03, **retirement of the chain core (the plan's S7 step)**: deleted `fpga/v35s/core/v35_chain_core.sv`,
  `v35_queue.sv`, `v35_arbiter.sv`, `v35_eu.sv`, `v35_decoder.sv`, `v35_biu.sv`, `v35s_chain_model.sv` and the
  generated `v35_chain_params.svh`; `validation/v35s/chains/rtlgen.py`, `test_rtlgen.py` and the `rtlgen`
  subcommand; the old benches `v35_core_tb`, `v35_eu_tb`, `v35_queue_tb`, `v35_biu_tb` with their build
  scripts; the chain lane (`build_sim.sh direct chain`, the harness's `V35S_CHAIN_LANE` branch, acquire's and
  replay's `--core chain`, now rejected with a message naming this record, the chain-lane end-to-end test);
  `rtl_vectors.py`'s old modes (biu, --queue, --joint, --eu, --joint3, --core; 3,675 → 933 lines, `--fn` and
  `--regfile` byte-identical, no rtlgen import) and the vector tests of those modes (the module keeps funcref,
  SST and `--regfile` coverage, 5 tests; nothing covers `--fn`). `v35_refresh.sv` carries
  `FIT_REFRESH_INTERVAL` (16), `FIT_RFM_DELAY` (3) and `v35_refresh_on` as its own localparams / function (from
  the frozen fit; ucgen should emit them later). `build.sh`, `synth/v35_map.sh` and `synth/v35_timing.sh` no
  longer copy the params header; `v35_lint.vlt` drops its two waivers. 36 files, +142 / −23,270. Before the
  deletion the two old test modules already failed on main (43 tests: 115 failures, 18 errors; `test_rtlgen`
  could not set up), so nothing that worked was lost. `docs/v35s-hdl-plan.md` and `docs/v35s-chain-rtl-spec.md`
  carry superseded / note banners; the remaining mentions in `core/v35/v35_top.sv`, `v35_front_pkg.sv`,
  `ucgen.py` and the README are comments in S8's files, fixed when S8 lands. **Gate, rerun on main:** 36
  families with `+v35_chk` 30,536 / 30,536 RTL = model (30,361 exact both sides), check and `--diag` silent;
  write data 106,824 / 106,824; SST 2,849,080 pass / 0 fail; `--regfile` 69,099 + 38,760 vectors 0 bad; `--fn`
  19,752 / 0 bad; lint clean in four configurations; 30 fast tests green with no skip (the chain-lane skip is
  gone); the remaining vector tests 5 / 5; the nine offline modules unchanged; the ucore model lane still
  builds (`build_sim.sh direct`).
- 2026-11-06, **queue strategy** (user's direction after reviewing the code: "we are not building simple
  machines"): `docs/v35s-queue-strategy.md`. The queue becomes a six-byte FIFO with a prefetch pointer, a
  level request line (`free >= 2`, `free = 6 - cnt - 2·inflight`), two priority hints for the arbiter
  (`q_low`: cnt ≤ hold_q; `q_starved`), `pop`, `flush(addr)` and `susp` from the EU: about 20 ports and 30
  bits of state beyond the bytes, from 164 ports and 71 registers. The ~45 fitted queue situations move:
  the request's sampling and back-to-back commitment to the bus unit, the fetch holds to the arbiter's use
  of the hints, every hold to microcode suspend windows emitted by ucgen, the seventh-slot family to the
  loader's pop timing, the one-shot commitments to an optional row strobe, the take sync to the loader's
  stall on `avail`; the latched-byte rules are a structural variant (byte-wide write port + one-byte
  latch) tried after the plain word write. The gate becomes RTL-exact against silicon within an accepted
  per-family loss budget (5–10 % in the families that rest on the queue's situations) with every miss
  classified as EU / microcode-recoverable, bus-unit sampling, or a true queue gap; only the last may
  change the queue, and only through a structural knob. The model is not edited. Work package proposed,
  not launched.
- 2026-11-07, **Q1 landed — the queue as a simple machine (the baseline for the recovery stages)**: per
  `docs/v35s-queue-strategy.md`. `v35_queue.sv` is 248 lines, 24 ports (from 164) and, beyond the six bytes,
  `cnt`, `unrel`, `pfp`, `inflight`, `discard`, `odd` plus variant B's `lat` / `lat_byte` (34 bits, from 71
  registers); no input names a form, class, row or EU step. Request line `free = CAP − cnt − unrel − stg −
  2·inflight` with CAP 7 (B, the staging byte counted) or 6 (A, `-DV35_QUEUE_A`), plus physical room for the
  word (stored + latched + in flight ≤ 7). Two structural knobs approved as kind-(c) findings: the **read /
  release split** (`rd` frees storage and advances the window, `rel` releases the room at the take step's
  end: a read pointer and a release pointer; what take_commit=at_end / release=byte described) and the **IR as
  the staging byte**, the seventh slot counted free when empty (the loader reports it unavailable while the
  form has operand bytes outstanding except on a delivery clock: room_ir=arrival_idle's refinement, needed:
  990 vs 303 of 1,032 on F0–F3). Variant B (byte-wide write port, one-byte latch, fixed owner chain) is the
  default: 23,691 RTL-exact against A's 7,858. Kept as EU rules reading the bus unit and the line (the brief's
  literal step 4 gave 0 exact runs in every family): start_sync and the take sync (owed = a fetch on the bus +
  the line at the take, decremented by the delivery). The holds are the sequencer's `susp` (str_hold, flush_hold /
  flush_from, xfer_odd / xfer_nt, bf_imm_hold / cvt_hold, nop_hold, io_ir_hold, count_latch, io_take=unit's
  drop) from existing generated attributes (ucgen unchanged); nop_hold / io_ir_hold cleared by a flush, nop_hold
  armed only with no memory request waiting (two hangs fixed: 264 runs never finished before). The bus unit
  samples the line at the arbiter's decision point (b2b = the line high at a fetch's last clock, none while a
  memory request waits in the slot); the arbiter adds two one-bit samples, `lup` (the line rose this clock)
  and `lup_p` (the line was up when the request posted: the I/O lead's hold; +1,795 runs alone), and loses all
  request dating. Not built: latch_hold (the line cannot carry "raised but held"; it broke the take sync),
  the situational latch rules, modrm_mate, str_raise, refill_start, the one-shot commitments, the per-form
  seventh-slot refinements, request dating, a fifth window byte. `room_f` removed from v35_front_pkg; the
  loader owns `pc`, `unc`, `relc`, `stg`; the bus unit owns `b2b`; `+v35_qdbg`, the trace's `U` (suspend) and
  free bytes in `R`; `evtrace --keys`; `build_sim.sh` reads `V35_SIM_DEFINES`. Step by step (whole corpus,
  RTL-exact of fit 62's 30,361): literal step 2 (no syncs) 0; B first full run 19,533; + split, staging, no
  latch_hold 21,896; + `lup_p` 23,691; A final 7,858. **Classification of the 6,680 misses** (first divergent
  clock; the agent's tables at the scratchpad's v2/q1/): (a) EU / microcode 2,725 (OUT starts early 547, RET
  375, PUSH 325, a write where the model posts nowrite 219, a read issued where the model fetches 173, ...);
  (b) bus unit / arbiter with the same line 884 (fetch late 584, early 300); (c) 3,071: the triple-clock
  aborted fetch 1,527 + 38 (a level line that only falls on pops cannot produce it; the one experiment aborted
  nearly everything and was dropped: **the open queue question for the user**) and 793 + 713 fetches where the
  line differs from the model's room, not yet split between (b) and (c). Area (efx_map LUT4 / ADD / FF): queue
  1,108 / 277 / 315 → B 542 / 52 / 106; arbiter 1,810 / 150 / 705 → 1,767 / 139 / 687; sequencer 10,797 / 739 /
  1,234 → 10,916 / 809 / 1,281 (it owns the suspend windows and the take sync now). **Gate, rerun on main:**
  whole corpus 23,691 / 30,361 RTL-exact (RTL = model 23,736) at both spacings, per-family tables identical,
  0 incomplete runs, `+v35_chk` silent; write data 106,824 / 106,824 at both; SST 2,849,080 / 0; `--regfile`
  69,099 + 38,760 vectors 0 bad; `--fn` 19,752 / 0 bad; lint clean in four configurations for B and A; 35 fast
  tests (the remaining vector tests included); the nine offline modules unchanged. **Per-family baseline**
  (RTL-exact / model-exact, loss): F0 18/18 (−0), F0w 20/20 (−0), F1 54/54 (−0), F2 120/120 (−0), F3 783/840 (−57), F4 428/456 (−28), F5 740/840 (−100), F6 552/576 (−24), F7 403/432 (−29), F9 340/408 (−68), F10 198/204 (−6), F11 66/132 (−66), F12 164/204 (−40), F14 608/732 (−124), F15 706/840 (−134), F16 762/1014 (−252), F19 1129/1290 (−161), F20 3160/3594 (−434), F21 2731/3576 (−845), F22 1072/1314 (−242), F23 57/360 (−303), F24 902/902 (−0), F25 521/577 (−56), F26 775/906 (−131), F29 304/427 (−123), F30 1061/1467 (−406), F31 192/234 (−42), F32 468/846 (−378), F33 921/1026 (−105), F34 998/1547 (−549), F35 396/1038 (−642), F36 726/750 (−24), F37 132/432 (−300), F38 801/864 (−63), F39 797/1318 (−521), F40 586/1003 (−417).
- 2026-11-07, **Q2 landed — the triple-clock aborted fetch has a mechanism** (a two-hour search by a Fable
  agent at the user's direction; its reading at the scratchpad's v2/q2/q2-reading.md, the README's "Q2"
  subsection). **Discriminator:** all 1,565 aborts are one shape: a form's start, the take of its single
  operand byte and the IR load on one clock, the queue full the clock before, the two reads raising the request
  line from nothing to *exactly a word's room* on a free bus; the identical take and IR load with the identical
  queue and bus state but no start (F9-none-movr_nop0, clock 185) fetches normally in silicon, and a word plus
  one fetches normally. The start clock is the only clock the EU consumes two queue bytes (the opcode and the
  first operand; the IR load is a look-ahead copy); with the fit's own `bytes_per_clock=1` the reading is a
  bus-controller count that moves one byte a clock: the request commits on a word's room, the count lags a byte
  on that clock, the confirmation point sees a word less one and abandons. **Hypotheses measured** on F3 F9
  F11 F14 F16 (3,126 runs, 386 aborts; recovered / newly broken): the dropped request held in the bus unit until
  a cycle ends: killed (85 hangs, register-only chains starve); the hold as the sequencer's existing drop window
  (lifted by a cycle end or the count loop's exit): 345 / 0; without the start strobe: 173 / 1,473 (the prelude's
  doubles fetch normally); without "exactly a word": 0 / 2,559; + the loop window for memory MUL / DIV: 381 / 0;
  + lifted by a flush and at the aborted cycle's end for a transfer: the nine corpus hangs gone. **As landed:**
  `q_word` on the queue (the line up with room for exactly one word), `abort_tri` in the arbiter (free bus, no
  fetch in flight, the start, take and IR-load strobes, `q_word`) OR-ed into the existing aborted cycle, the drop
  window in the sequencer (`dr_v` opened by a start's abort, `dr_loop` for unit forms, `dr_xfer` for transfers),
  behind the macro `V35_Q2_TRI`; 70 lines. The three strobes are a proxy for "two pops this clock"; the
  count-lag form (the queue's room-side count applying one byte a clock) is Q3's question. The five F16 shift
  cases of the model's `abort_latched` variant and 342 corpus aborts are not recovered. **Gate, rerun on main:**
  whole corpus 24,920 / 30,361 RTL-exact (from 23,691; RTL = model 24,971) at both spacings, tables identical,
  0 incomplete, `+v35_chk` silent, no family lower than Q1 (F16 762 → 947, F20 3,160 → 3,420, F21 2,731 →
  2,893, F14 608 → 695, F15 706 → 783, F30 1,061 → 1,127, F11 66 → 124, F31 192 → 234 = all, F7 403 → 430, ...);
  write data 106,824 / 106,824 at both; SST 2,849,080 / 0; `--regfile` 69,099 + 38,760 vectors 0 bad; `--fn`
  19,752 / 0 bad; lint clean in four configurations; 35 fast tests; the nine offline modules unchanged.
- 2026-11-07, **Q3 measured — the aborted fetch is not a count-path lag; Q2 kept** (an Opus agent in a
  worktree from 4f70754; README "Q3"). The question Q2 left: does the three-strobe abort (`t_start && take_now
  && l_pop` with the line at exactly a word on a free bus) fall out of a queue count that moves one byte a
  clock (the fit's bytes_per_clock=1)? Built behind a macro: the loader reports the bytes the EU consumes on a
  clock, the queue applies one on the clock and the rest a clock later, the arbiter abandons a fetch committed
  on a free bus whose request the lagging count does not confirm; no EU strobe in the arbiter. **Finding:** the
  corpus has five kinds of clock (A the abort: start + take + IR load; B take + IR load, no start; C start +
  ModR/M take with bytes outstanding; D start + ModR/M take, no IR load, room rising two to a word; E a wide
  take of two operand bytes) and silicon fetches on B–E; A and B are identical in every queue count (pops,
  releases, staging byte), A and D differ only by the IR load, A and E only by the start and the IR load, so
  no one-byte-a-clock count singles A out: counting storage pops breaks B and E, counting the seven slots
  breaks D and E, counting the opcode plus the IR load breaks one-byte forms; the one count reproducing A alone
  (an operand byte plus the opcode when the IR reloads on its start's clock) is the three strobes restated and
  still lags on E. Seven counts measured on F3 F9 F11 F14 F16 (Q2 2,946): the best lag 2,888 (58 D-clock runs
  broken, 37 hanging: a false abort on a register form opens the drop window, which waits for a data cycle's
  end a register-only chain never produces), the strobe-restated count 2,946. Whole corpus: the best lag 24,448
  against Q2's 24,920 (0 gained, 472 lost, 63 hangs, write data 106,761 / 106,824), the strobe-restated count
  24,777 (143 lost, all E clocks). **Reading:** the abort is the coincidence of the start's opcode leaving, an
  operand byte leaving and the IR reloading on one clock, which Q2 states directly; the silicon count path, if
  there is one, is not a bytes-per-clock lag. **Not landed:** the lag code (125 lines, two more queue ports) is
  a rejected mechanism; the side build with its macro off reproduced Q2 run for run at both spacings with the
  function gates, lint (nine configurations) and the 35 tests unmoved, so main stays 4f70754's core. The patch
  and per-run tables are in the scratchpad's v2/q3/. Still open: the 342 unrecovered aborts and the five
  abort_latched cases; Q1's (a) 2,725 EU / microcode and (b) 884 bus-sampling misses.
- 2026-11-07, **R1 landed — six fitted rules the simple queue left behind, rebuilt as EU / bus-unit rules** (an
  Opus agent in a worktree from 541d91e, about four and a half hours; README "R1"). The target was Q1's class (a):
  the fitted rules the old queue applied through its situation ports. Re-classified on 541d91e with a rebuilt
  classifier (the hand-back's classify.py; the RTL trace has no "nowrite" post kind, so a CMP / TEST memory form's
  model `P:nowrite` against the RTL's `P:write` was a naming difference, 213 of Q1's 256 "P" misses): (a) 2,574,
  (b) 1,135, (c) 1,742. **The rules,** each behind a macro in v35_front_pkg.sv (default 1), measured one at a time
  on its families then cumulatively on the corpus, 0 runs lost at every step: (1) `V35_R1_REFILL`
  refill_start=full_io, the start gate's hold after a flush while a fetch is on the bus or the line stood at the
  last clock (`rfl`, one registered bit; `Q1_REFILL` now takes the macro), +1,143 (F35 378, F23 258, F39 168, F30
  105, F40 100, F37 78, F34 56); (2) `V35_R1_PGRUN` page_run=field, the arbiter lets a waiting 0F read not hold the
  back-to-back sample once per form (`pr_used`, one bit), +177; (3) `V35_R1_NEED` hold_count=ahead, the arbiter's
  `hold_le` lapses whenever the line stands while the running form has operand bytes outstanding (the loader's
  `need_t`, a new arbiter input; not for a `whole` request), +651; (4) `V35_R1_IRH` ea_ir_room under
  ir_load=disp_data, the loader's `stg` counts the empty IR as occupied while its load is held for the form's data
  cycle with no operand byte left, +418 (F21 302); (5) `V35_R1_NOMEM` request_reissue=no_mem, a fetch issued
  beside a waiting memory request leaves the arbiter's view of the line down until the queue next changes (`nm`,
  one bit), and (6) `V35_R1_FHDATE` free_hold=delivery's dating in `fetch_first` (`fh_date`), together +47. The
  queue (v35_queue.sv) is untouched: no port, no state, no input naming a form; no opcode literal; ucgen untouched;
  the three new bits have ce_b copies and `+v35_chk` is silent. The one clocking note: rule 3 adds `need_t` as one
  AND term in the arbiter's fetch-hold tree. **Result:** (a) 2,574 → 762 (start holds 1,670 → 216, I / I+L 718 →
  356, P 43, L+T / T 28 and the suspend kind 119 untouched). **Gaps recorded:** the suspend misses (119; F30 54,
  F34 34, F16 20) are a (c) gap, a count-byte shift starting on a word's delivery clock where the model's room
  counts the latched byte; the 0F read's setup count on an OUT's issue clock (I: F32 114, F34 72, F39 30, F40 30,
  the arbiter's request record, open); starts beside a 4-clock fetch at w1 (F10 F12 F14 F15 F19 F20, a (c) gap:
  the counts differ before the start); a start one clock early after a 0F register bit form (page_b2b, not built);
  P 43, L+T 22, T 6, L+S+T on not-taken branches with the model's aborted cycle. **Gate, rerun on main:** whole
  corpus 27,356 / 30,361 RTL-exact (from 24,920; RTL = model 27,415) at both spacings, per-family tables identical,
  0 failing, `+v35_chk` silent, 22 families up and none lower (F21 2,893 → 3,384, F23 57 → 315, F35 396 → 792,
  F39 853 → 1,054, F32 468 → 660, F34 998 → 1,169, F40 640 → 776, F37 132 → 246, F30 1,127 → 1,232, F22 1,072 →
  1,166, ...); write data 106,824 / 106,824 at both; SST 2,849,080 / 0; `--regfile` 69,099 + 38,760 vectors 0 bad;
  `--fn` 19,752 / 0 bad; lint clean in five configurations; 35 fast tests; the nine offline modules unchanged (941
  tests, the four known failures). With the six macros at 0 the build reproduces 541d91e run for run on F21 F22 F23
  F32 F35. Remaining: (a) 762, (b) 1,173, (c) 1,080 at the default spacing, the per-family table in the README.
- 2026-11-07, **R2 landed — three sampling rules in the arbiter; the classifier corrected** (an Opus agent in a
  worktree from 0a696bc, about 3.7 hours; README "R2"). The target was class (b): the request line the same on
  both sides on the first divergent clock, the bus unit or arbiter fetching or holding differently. **Two findings
  before any rule.** First, the model never honours a fallen request (request_hold=lapse instrumented at the first
  divergent clock, the hand-back's an/why.py): every model fetch at room −1 with the line down is the nowrite slot
  on a word's delivery clock (slot_room=word, 243 runs), xfer_nt_b2b=decide (140) or page_b2b=reg (167), one-shot
  commitments. Second, the classifier read the model's line at the END of the clock, after an issue reserved the
  word and cleared the flag, so 277 "same line" (b) misses are the model's line up against the RTL's down: (c).
  Corrected on 0a696bc: (a) 762, (b) 896, (c) 1,357 (the classifier's classify2.py / recls.py). **The rules,** each
  behind a macro in v35_front_pkg.sv (default 1), all in v35_arbiter.sv, no register and no comparator added, the
  queue untouched: (1) `V35_R2_SLOT` slot_room=word, the nowrite slot on a word's delivery clock runs a fetch
  whatever the line shows (the cycle was chosen at the fetch's last clock before the word was written; `sl_dlv`
  from `fetch_end_prev`, `fetch_inflight`), +186 (F22 78, F19 51, F5 18, F15 15); (2) `V35_R2_GDLUP` grp_disp=hold's
  take-clock exemption on the line as sampled at the last clock (`lup`) or a delivery clock, +46 (F37 42, F29 4);
  (3) `V35_R2_DWLUP` dw_lift=moved, a DW-form I/O request moving into the slot takes the line as sampled before the
  move-in clock, +18 (F29). With the three macros at 0 the build matches 0a696bc run for run on F5 F19 F22 F29 F37.
  **Recorded as (c), two examples each:** xfer_nt_b2b=decide (140: F35 72, F39 23, F30 21) and page_b2b=reg (167:
  F34 77, F32 58, F39 24) each need a byte of room and an empty latch plus the decide-row strobe or the format's
  page bit (a form-free version, back to back on `q_low` sampled at the issue, broke 706 of 1,400 runs and was
  dropped); grp_disp=hold's room after the clock's reads (126: F37 66, F29 30), two clocks identical in the line,
  `lup`, `q_low` and every strobe where the model holds on one and fetches on the other; latch_hold (102) and
  abort_latched (38) need the latched byte. Open: 10 runs of the 0F memory bit forms where page_run's once-per-form
  commitment is spent a clock late. **Gate, rerun on main:** whole corpus 27,606 / 30,361 RTL-exact (from 27,356;
  RTL = model 27,674) at both spacings, per-family tables identical, 0 failing, `+v35_chk` silent, ten families up
  and none lower (F22 1,166 → 1,244, F19 1,173 → 1,224, F37 246 → 288, F29 312 → 334, F5 809 → 827, F15 810 → 825,
  F14 704 → 713, F16 959 → 965, F36 738 → 744, F38 861 → 864 = all); write data 106,824 / 106,824 at both; SST
  2,849,080 / 0; `--regfile` 69,099 + 38,760 vectors 0 bad; `--fn` 19,752 / 0 bad; lint clean in five
  configurations; 35 fast tests; the nine offline modules unchanged. Remaining under the corrected reading: (a) 762,
  (b) 583, (c) 1,420, of which the largest shape (about 570 runs, F23 F35 F39 F30) is a transfer form's start clock
  where silicon runs the aborted fetch and the RTL fetches normally with the line already standing (free 2 against
  the model's room 1), and about 170 are F21 displacement forms at the two wider spacings only.
- 2026-11-08, **R3 landed — the transfer's aborted fetch, the displacement's late release, the seventh-slot
  refinements and the latched-byte abort** (an Opus agent in a worktree from 8d0547e, about five hours; README
  "R3"). The target was the largest class-(c) shapes, where the RTL's request line differs from the model's on a
  clock the EU takes bytes. **The rules,** each behind a macro in v35_front_pkg.sv (default 1), measured one at a
  time on their families then cumulatively on the corpus: (1) `V35_R3_XREL` xfer_abort=word as the loader releasing
  a transfer's displacement byte one clock late, on the start clock only (the byte is the bus unit's target adder's,
  not the EU's; `xl_t` into the existing `relc`, one ce_b register), so the room shows exactly a word and Q2's
  abort fires unchanged, +474 / −7 on the corpus (releasing late on every take of a transfer lost 117); (2)
  `V35_R3_XRW` the same rule at the model's room 2, a second term `q_short` on the queue's existing `q_word` output
  (`occ == CAP − 1` with one byte read and unreleased), the arbiter's `abort_tri` accepting it with the line down
  and the take sync counting the aborted cycle as asked, winning the 7 back; (3) `V35_R3_DREL` latch_disp, a memory
  form's displacement taken on a delivery clock with the IR load released a clock late, +171 (on every delivery
  clock it lost 165); (4) `V35_R3_LEAR` lea_room=ir, the loader's `stg` ignoring the IR during LDEA's EA clocks (the
  sequencer's existing `lea_xk_t`), and (5) `V35_R3_MATE` modrm_mate=imm, `stg` staying counted when the ModR/M
  byte's odd word-mate is taken on its delivery clock in a register form with bytes to come (a new sequencer take
  fact `mate_t`), together +128; (6) `V35_R3_ALAT` abort_latched, a byte latched on an earlier clock as room for the
  abort test only (the second `q_short` term), +38 (F20 21, F21 12, F16 5). The queue gains no port and no state:
  `q_word`'s definition carries the two abort-test terms from the queue's own counts. The loader gains three
  sequencer facts (`disp_tk`, `lea_room`, `mate`). **Not one release rule:** the immediate-form take with the
  model's line down at room 2 (162 runs) is the model's on_change flag missing a room rise from a P-pass take, not
  a count difference (a release form scored +42 / −168, rejected; it needs a "not re-evaluated" state on the line);
  the register start + take where the RTL's physical-room check holds the line (161; counting the empty IR as a
  place scored +12 / −35 with 4 hangs, rejected). **Classification after:** (a) 833 (71 runs whose first divergence
  moved on to an EU event), (b) 624, (c) 497 (the 162 on_change, the 161 phys_ok, about 121 more model-idle cases
  with the line down at room 1–2, 31 F33 inc_al, 10 F35 far call, 12 F34 bit-memory forms). R2's list had 52 runs
  labelled (c) that the corrected classifier calls (b). **Gate, rerun on main:** whole corpus 28,408 / 30,361
  RTL-exact (from 27,606; RTL = model 28,507) at both spacings, per-family tables identical, 0 failing, `+v35_chk`
  silent, 20 families up and none lower (F21 3,384 → 3,546, F39 1,054 → 1,176, F35 792 → 891, F40 776 → 874, F30
  1,232 → 1,316, F37 288 → 348, F34 1,169 → 1,212, F20 3,420 → 3,452, F23 315 → 345, ...); write data 106,824 /
  106,824 at both; SST 2,849,080 / 0; `--regfile` 69,099 + 38,760 vectors 0 bad; `--fn` 19,752 / 0 bad; lint clean
  in five configurations; 35 fast tests; the nine offline modules unchanged. With the six macros at 0 the build
  reproduces 8d0547e run for run on F10 F16 F20 F21 F23 F25 F35 (10,380 runs).
- 2026-11-08, **the core's macros move to a header** (overseer). Per-module synthesis had been broken since Q2:
  Efinity compiles each file as its own unit, so a macro defined in v35_front_pkg.sv (V35_Q2_TRI, the R1 / R2 / R3
  macros) never reached v35_queue / v35_loader / v35_arbiter / v35_ucode (`syntax error near '&&'`, `q_short is not
  declared`); Verilator, compiling one unit, never showed it. The macros are now fpga/v35s/core/v35/v35_macros.svh
  (include-guarded), included by the package and by the four modules; the synth scripts and build.sh copy it.
  Lint clean in six configurations (including `-DV35_R1_NEED=0`), the three simulators rebuilt, F3 / F9 / F23
  replay 804 / 379 / 345 as on 08a2c58. **Per-module timing at 15.625 ns on the R3 core** (`v35_timing.sh queue
  arbiter loader`, TAG r3): v35_queue 568 LUT4 / 52 ADD / 236 FF, worst slack +4.835 ns at 10 logic levels (the
  simple machine closes at 64 MHz); v35_arbiter 1,769 LUT4 / 139 ADD / 1,122 FF, worst slack −18.144 ns at 39
  levels from the slot request's valid bit (the arbiter's choice tree is a long chain and the next timing target
  after the sequencer); v35_loader did not time: the wrapper's post-synthesis netlist was empty ("all logic is
  eliminated"), to be looked at with the wrapper.
- 2026-11-08, **R4 landed — the remaining EU misses and the bus-unit holds** (an Opus agent in a worktree from
  08a2c58, about five hours of rule work; README "R4"). The target was class (a) of the corrected classifier (833
  runs whose first divergence is an EU event) and the class-(b) holds where the request line is the same on both
  sides (624). The (a) misses were re-read against the frozen model instrumented at the first divergent clock (the
  model's request record per clock, the line of `EU._start` that held a start, every EU attribute assignment with
  its source line). **Ten rules,** each behind a macro in v35_macros.svh (default 1), none touching v35_queue.sv,
  no request dated, no input naming a form to the queue or the bus unit, measured alone on their families then
  cumulatively on the corpus with no run lost at any step: (1) `V35_R4_PTHRU` page_cl=thru's order: a fetch runs
  inside a CL-index 0F read's CL clocks only when requested after the read's post; the record's existing post
  sample `lup_p` is "requested no later than the post", so such a fetch is an ordinary one that restarts the
  fetch-free count (+250 alone, F32 F34 F39 F40: the `I` shape, the read issued two clocks early); (2)
  `V35_R4_NMB` request_reissue=no_mem decided at the fetch's issue: the waiting memory request holds the bus
  unit's back-to-back sample only when it already waited at the issue (the arbiter's `nm`, a new output
  `b2b_hold_o`) and free_run does not count a commitment NMB let through (one register `nmb`), +90 (stores in
  F22 F21 F19 F26 F29 F5, transfers in F39 F40); (3) `V35_R4_IOST` io_b2b's stored count leaves out the arriving
  word's second byte on its delivery clock (word_latch=byte_d), +44; (4) `V35_R4_CLAT` count_latch's room
  subtracts the latched byte only when the form has no operand bytes left (the loader's `need_l`), +98, the
  `susp` shape's shifts and bit forms; (5) `V35_R4_SRZ` str_raise: the ROM's REL_RAISE row attribute, unread since
  S5a, ends the aborted start's drop window `rs_n` clocks into the exit (a 4-bit countdown), +21 (F30 CW = 0
  strings); (6) `V35_R4_DASK` imm_landed's deferred take sync also counts the line on the clock after the take
  (`fetch_req` at tick A's end, before the grant), +50; (7) `V35_R4_LAPS` the take sync's lapse counts the
  delivered word's latched byte as room, +120 (the start a clock early after a 0F register bit form, F34 F39
  F32); (8) `V35_R4_DRX` xfer_abort=word's retry by the format's `xfer` bit (BRK is a call by base class), +18
  (F37); (9) `V35_R4_XNT` xfer_nt=odd's decide waits only for the fetches issued before the odd hold's lift, not
  the one its release raised (`xo` / `xo_s`), +24 (F23 F30 F35); (10) `V35_R4_GIOD` grp_io_hold's dating through
  the record's existing `ghp`, as R1's free_hold dating, +6 (F14 F15). Cumulative steps: PTHRU + NMB 28,748, +
  IOST 28,792, + CLAT + SRZ 28,911, + DASK + LAPS 29,083, + DRX + XNT + GIOD 29,208; the rules alone sum to +721,
  79 runs need two or more together. **New state:** `nmb` (arbiter, with its ce_b copy), `rz_v` / `rz_cnt` and
  `xo` / `xo_s` (sequencer, ce_a registers written from tick-B facts); the arbiter's choice tree gains an AND of
  `lup_p` and an OR of `ghp`, no comparator against a count. Two bring-up prints under `ifndef SYNTHESIS`
  (`+v35_adbg=FILE` the slot and choice per clock, `+v35_sdbg=FILE` the take sync and suspend windows).
  **Findings:** the start holds' counts before the start are equal on every example (R1's "counts differ" came
  from the RTL's trace field after its own start); the `susp` shape is not the latched byte (R3's `lat_v` is not
  needed for it); the (b) holds all need a queue count or an EU-step input the rules forbid and are recorded with
  examples: xfer_nt_b2b / page_b2b one-shot commitments (332, free ≥ 1 and an empty latch; xfer_nt_b2b also the
  DECIDE strobe), grp_disp's take-clock room after the reads (138), grp_disp's read against a fetch no older than
  the read (36; a `gr_hold && !lup_p` form scored +30 / −30, the losses raised on the post clock itself),
  latch_hold (102, `lat_v` at the arbiter), grp_io_hold's order (6; a one-bit sample of the line at the I/O issue
  scored +12 / 0 on ten families but was not run on the corpus and is not landed), latch_start (22 (a), the latch
  draining that clock), ten small (a) runs unexamined (F34 mbit d16 / d8, F25 LDEA). **Classification after:** (a)
  833 → 32, (b) 624 → 624 (F21 and F26 down 10, F34 and F40 up 10, first divergences moved past a recovered
  clock), (c) 497 → 498. **Gate, rerun on main:** whole corpus 29,208 / 30,361 RTL-exact (from 28,408) at both
  spacings, per-family tables identical, 0 failing, `+v35_chk` silent, 24 families up and none lower (F34 1,212 →
  1,428, F32 660 → 784, F30 1,316 → 1,404, F39 1,176 → 1,251, F40 874 → 920, F26 851 → 897, F22 1,244 → 1,274, F16
  970 → 990, F19 1,232 → 1,252, F37 348 → 366, F35 891 → 909, ...); write data 106,824 / 106,824 at both; SST
  2,849,080 / 0; `--regfile` 69,099 + 38,760 vectors 0 bad; `--fn` 19,752 / 0 bad; lint clean in five
  configurations (the agent: eight, and with the ten macros at 0); 35 fast tests; the nine offline modules
  unchanged. With the ten macros at 0 the build reproduces 08a2c58 run for run on F14 F19 F22 F23 F26 F30 F32 F34
  F37 (8,970 runs). The user asked for a pause after this package; no R5 is launched.
- 2026-11-08, **arbiter strategy** (user's direction after R4: "nothing this complex would exist on real
  hardware ... the EU is the only part of the CPU that is allowed to know anything about the type of operation
  being executed"): `docs/v35s-arbiter-strategy.md`. The arbiter module (904 lines, 108 ports, three 130-bit
  request records, a 39-level choice tree at −18 ns) is deleted. The bus unit gains an EU request port of a
  cycle type (memory / I/O read / write), address, width, datum sampled at B2, a reservation line (nuV30's
  `eu_soon`: no fetch starts while it is up unless the queue's `q_low` hint overrides it), and `req_ack` /
  `req_done` (the F / OPR interlock); its grant is one fixed priority: the back-to-back committed fetch, the
  EU's request, the queue's fetch, nothing, plus the aborted cycle and the odd pair as built. Every request
  attribute (setup counts and their six counting modes, fetch-free tails, I/O leads, detached I/O, group and
  RMW clocks, imm1, gdisp, sreg, floors, relatch, the 0F page's counts) leaves the bus unit: the counts become
  microcode rows and sequencer counters on bus facts, the holds become the reservation window, the three
  request positions become one write buffer in the EU, the nowrite slot and the dating variants are dropped,
  and the bus cycle flags that encoded EU state leave the bus unit. The gate is RTL-exact against silicon
  within a 10–15 % per-family loss budget in the families that rest on the attributes, every miss classified
  (EU-expressible, grant with the same four inputs, or needs an instruction attribute at the bus unit: the
  last is recorded and never built there); the model is not edited; ucgen may gain row attributes with the
  inverse check kept green. Work package A1 launched the same day.
- 2026-11-08, **A1 landed** (worktree agent; `v2/a1/`): the arbiter is gone. `v35_arbiter.sv` (904 lines, 108
  ports) is deleted; the bus unit (577 lines from 703, 69 ports from 81) grants from two request ports, the
  queue's (`fetch_req`, `q_low`, `q_word`, `fetch_addr`) and the EU's nine signals (`req_v`, `req_cyc` 2 bits
  memory / I/O read / write, `req_addr`, `req_width`, `req_data` taken at B2, `req_resv`, `req_ack`, `req_done`,
  `done_data`), plus Q2's three read strobes for the aborted fetch; the structure test's two new `Ports` tests
  enforce that no port of the bus unit or the queue names or types an instruction and that the bus unit's
  inputs are exactly those. **The grant** (about four logic levels on registered facts, no comparator against a
  count): (0) the odd pair's second half and the aborted fetch (Q2's triple clock; a back-to-back commitment
  whose line fell with no EU request standing); (1) the back-to-back committed fetch, its sample at the
  previous fetch's last clock held by `req_v || req_resv` (`A1_B2BH` 1); (2) the EU's request, a memory cycle
  blocked within io_recover of an I/O cycle (`A1_IOREC` 1: the turnaround is the bus unit's); (3) the queue's
  fetch if `fetch_req && (!req_resv || (q_low && the reservation is a memory cycle's))` (`A1_IOQL` 1: an I/O
  cycle's reservation is absolute); (4) nothing. Rules 1 and 3 are the overseer's decision after the step-2
  measurement: the strategy's first wording (rule 1 by `req_v` alone, `q_low` over any reservation) is the
  macros at 0 and scored 20,943 (−8,264, 28.3 %; 5,017 of its 5,213 (b) misses were `q_low` overriding an I/O
  reservation silicon holds absolutely); + rule 3 22,413 (+1,470 / −0 after an empty slot was made to present
  a memory read: ten F29 gih d16 runs had been lost to the empty slot reading as an I/O write), + rule 1 22,674
  (+261 / −0 after the EU's last-clock reservation was defined: at a fetch's last clock it is the waiting
  memory request if it waited at the fetch's issue (R4's NMB), the EA clocks running on, and the I/O lead's
  block, a 0F form's waiting read exempt once per form; memory-typing the hold lost 994, `req_v` or a memory
  reservation lost 32). **The EU's bus interface** (v35_ucode.sv, 4,916 lines from 4,350, 134 ports from 166,
  about 560 lines): the request register `bq0` with the row's counts (setup, fn, lead, through, the count-mode
  bits, the floor), the entry behind it `bq1` (the write buffer: a request posted behind a detached I/O counts
  from the clock that I/O issues), `req_resv` as the OR of the setup hold and the windows the arbiter took as
  inputs, the setup count pausing on `in_wait` (nowait rows) or on `busy` / `io_win` (group forms,
  `A1_GRP`), the pair's second-half address, the B2 datum register, EU registers replacing the bus cycle
  flags (`bq_os bq_wl bq_th bq_pa bq_fas bq_fnt`); `req_t` loses its thirty attributes in the shared package.
  **Recovered rules** (strategy §5 step 4; each alone on the 6,517 runs the steps move, then cumulative, 0 lost
  per step): `A1_FFD` fetch_first's dating +695 (with imm1_first's EU-side exemption; without it 34 F22
  add8_d16 runs lost), `A1_LEAD` the I/O lead +1,849, `A1_FRUN` free_run=run +456, `A1_FHOLD`
  free_hold=delivery +157, `A1_SREG` +48, `A1_MFR` +93, `A1_PAGE` the 0F page's counts as sequencer counters
  on bus facts +483 (with page_run=field's exemption of the back-to-back sample, which fixed six F32 / F34
  set1_mw_cl losses), `A1_BCD` +33, `A1_SF` slot_fetch=slot +36 with the others on, `A1_RL` port_latch=relatch
  +931 (its first 131 losses were the I/O lead's block missing from the last-clock reservation; 0 after),
  `A1_DW`; `A1_GIO` and `A1_GDR` showed no effect and are left at 0. Cumulative: + FFD + LEAD 25,242, + FRUN +
  FHOLD 25,863, + SREG + MFR + PAGE + BCD 26,662, + SF + RL 28,058 (the middle rows measured before the
  last-clock reservation's final form; the final source's whole-corpus run against the rule-1 step is +5,384 /
  −0). **Not built** (recorded): the nowrite slot's rules (slot_room=word: 180 runs, F22 72, F19 51), disp_io=
  extend (110: the I/O issued on a displacement's take clock runs a clock longer; the bus unit would need the
  take or a cycle-length request), free_idle, request_reissue=no_mem beyond the sample bit, grp_io_hold and
  grp_disp's read hold. **Gates found three fixes:** an I/O word at an odd port was given the byte width
  (8 test_rtl_vectors failures on OUT word), the bench's `halted` reference and the bus unit's pin wires for
  the bench. **Classification of the final core's 1,175 misses** (a1-misses.jsonl; the classifier's labels (a)
  191, (b) 11, (c) 973, with the agent's reading of the hold shapes): wlatch_hold's window yielding to `q_low`
  254 (F21 F22 F19; the EU could reserve with the cycle type of the I/O it waits to post, absolute under rule
  3), wlatch_hold against a back-to-back fetch 183 (F20 F25 F29; latch_wait into the last-clock reservation),
  slot_room=word 180 (needs a slot attribute at the bus unit: not built), `req_v` a clock early on store paths
  175 (F22 105: the store's count or floor in the sequencer), disp_io=extend 110, grp_disp's window yielding to
  `q_low` 106 (F37 54, F29 34, F39 18) and free_hold / slot_fetch / grp_io_hold yielding 67 / 42 / 24 (memory
  reservations silicon holds absolutely: a rule 3 question), a start a clock early after an OUT 16, rule 1's
  sample 11, ea_b2b 7. **Gate, rerun on main:** whole refresh-off corpus 28,059 / 30,361 RTL-exact (from 29,208; −1,149 net, the agent's tree 28,058 as in
  R4 one F30 run apart) at both spacings, per-family tables identical, 0 failing, `+v35_chk` silent; the
  per-family losses are the new baseline ($S/v2/a1/main/fam-v35_chk.txt): F22 1,274 → 1,033 (18.3 % of its runs:
  over the 15 % budget), F29 354 → 309 (65 lost, 20 gained: 14.3 % gross), F37 366 → 312 (12.5 %), F19 1,252 →
  1,143 (8.4 %), F26 897 → 811, F21 3,560 → 3,398, F20 3,464 → 3,407, F5 831 → 776, F36 744 → 707, F15 837 → 798,
  eight families unchanged, none up; write data 106,824 / 106,824 at both; SST 2,849,080 / 0 with R4's
  categories; `--regfile` 69,099 + 38,760 vectors 0 bad; `--fn` 19,752 / 0 bad; lint clean in the five
  configurations without v35_arbiter.sv; 37 fast tests (the two `Ports` tests new); the nine offline modules
  unchanged (941, the four known failures). The over-budget F22 and the rule-1 / rule-3 definitions are
  reported to the user for decision; the recovery agenda above is the candidate next package.
- 2026-11-09, **decisions and the first fit after A1.** The user: rule 3 as built (an I/O cycle's reservation is
  absolute, a memory cycle's yields to `q_low`) stands; F22's 18.3 % loss is accepted. **The whole core at 64 MHz**
  (`TAG=a1 fpga/v35s/synth/v35_timing.sh top`, 15.625 ns, one create_clock, every SDC line applied): 24,147 LUT4,
  2,015 ADD, 3,153 FF, 32 RAM_5K, 8 MULT (the sequencer 13,018 LUT4, the EU 7,903, the loader 2,035, the queue 607,
  the bus unit 301: the arbiter's 1,700 gone, the sequencer up about 6,000 for its bus interface); worst setup
  slack −179.5 ns, hold +0.3; the worst path queue `lat` → the sequencer's row arithmetic (imm / add / sub) → the
  bus interface's counters (`ba0.setup`, `bq_flo`, `bq_inc`, `bq_cx`) → the EU's divider operand and remainder
  (`f_now.opb`, `dv_op`, `rem`, 55 levels) → `equal` / `run_n.n0` / `wa_e` → the ROM bank's read address, 202
  logic levels, about 195 ns: the S7a whole-clock chain again, now with the divider on the row-decision path and
  the bus interface in it. **The harness image** (`fpga/v35s/synth/v35_harness.sh`, 30 ns clock): map 281 s,
  placement 59 min 37 s (the timing-driven placer on an unmeetable path: over the one-hour rule), routing 20 min
  26 s; 28,760 LUT4, 5,912 FF, 952 / 1,056 RAM_5K (the harness's buffers 920), 8 MULT, 29.7 % of the logic
  elements; worst slack −173.9 ns, the path queue `cnt` → ROM bank read address, 186 levels; build.sh exits 1 on
  the timing check but the bitstream build/fpga/v35s/outflow/v35s.hex.bin (3.55 MB) is written. The worst paths
  begin and end at `ce_a` registers, so in the harness's eight-tick CPU clock they have 240 ns, not one tick's
  120 ns; whether every `ce_b`-ending path fits a tick is not shown by the report's path list. Closing 64 MHz
  remains S8 (paused) and S9; the divider and the bus interface's counters join the list of chains to split.
- 2026-11-09, **mechanism note** (user's rule: "Every delay being introduced by the model needs to have a
  machine explanation ... Arbitrary delays with no explanation are not allowed. We should not be looking
  ahead at the next opcode to influence timing of the current one"): `docs/v35s-mechanisms.md`, with the
  evidence in `docs/v35s-mechanisms/` (classes.md: the 84 classes with their forms, the model's step lists
  with every integer named, the V35S / V30 / data book cost per form from the a6-timing corpus, the V30
  routine and the open items; integers.md; rules.md: section 4's lists hold 150 items and 168 names, not
  137, and 64 A4 rules are in no list; v30-structure.md; v30-opcodes.md; collected read-only by an Opus
  agent at aa7c92f). The note supersedes section 4 above and the arbiter strategy's attribute placement:
  nine mechanisms with their timing laws (the microsequencer with the `E` pop and one overlapped post-`E`
  word; one queue byte per microinstruction from the word register; the register file as internal RAM with
  the write hold that is the whole `wb` family, from the data book's bracketed RAMEN = 0 counts and M2's
  +3 per write; the ALU and the loops; the EA as the loader's address march, since the ROM has no EA
  routine; bus requests with the `F` interlock and the A1 port; the bus unit's measured laws; transfers;
  and the fitted names with no act behind them, dropped), the sequencer that results (a registered ROM
  word per clock, the next address from a register, the decode from the popped byte, a microprogram
  assembler with a book check replacing ucgen and the inverse check), a per-class accounting from the data
  book's formulas against the measured costs, the three-bin rule disposition, the method (misses
  classified as routine shape / bus-unit law / unexplained, never a count) and six work packages MX0–MX5.
  Two V35-specific loop mechanisms are named as open on silicon: the shift's 2 clocks per count against
  the V30's 1, and the string element's 18 against the V30's 8. Open to the user before MX0: the data
  book's formulas as every routine's first draft, and whether Q2's aborted fetch stays a bus-unit mechanism.
- 2026-11-10, **MX0 landed** (the assembler, the sequencer, the register-form routines; one Opus worktree agent
  over six rounds MX0–MX0f directed from the overseer's traces). **Built:** `validation/v35s/chains/uasm.py`
  (749 lines) reads the microinstruction word's layout from `v35_pkg.sv` (the single source: 86 bits, 3 × 32-bit
  ROM banks; RAM read ports A / B and the write port with a selector and a data source; two moves; the ALU op
  and W; the EA step; the bus request with its segment and the reservation; the pop with its target; E; F; the
  loop counter's load; next / jump / call / return / loop / dispatch with a condition and a target; prefix,
  flush, halt, trap — no count, class or attribute field, enforced by `test_uasm` and
  `test_v35_struct.test_the_word_has_no_count_field`) and assembles `fpga/v35s/core/v35/urom/{core,reg,loop,
  bus}.uasm` (one line one microinstruction, the comment naming the act; a routine header names its opcodes,
  its form, the book's formula and any declared difference with its reason) into `v35_urom_b{0,1,2}.hex` and
  `v35_udecode_tbl.svh` (the only place an opcode literal appears); `test_uasm`'s book check compares every
  routine's length at EA = 3, W = 0 with `v35_book_clocks.json` (55 rows) and rejects a difference that is
  longer than the book, "measured" alone, or a fit. `v35_useq.sv` (251 lines, 26 ports) replaces `v35_ucode.sv`
  (4,916): a registered ROM word a clock, the microaddress from a register, the stalls (queue, F, slot, hold,
  halt, and the dispatch stall below), the loop counter, a one-level return register (the V20 ROM has no nested
  FARJMP), the E word popping the opcode and its ModR/M together with the next address decoded from the popped
  byte through the registered decode. `v35_loader.sv` 704 → 287 lines (the word register, the pops, the decode
  table), `v35_eu.sv` 1,870 → 473 (the shifter one shift per iteration, the divider one step per word, no
  multiplier block); ucgen.py, test_ucgen.py, the ucode hex / class / decode tables and v35_consts deleted. The
  routines cover the gate families' instruction set (69 routines, 411 words at MX0; the trap routine pops an
  unimplemented form's bytes by its format and ends). **The laws found on the way** (each measured against the
  alternative, selectable by a macro in v35_macros.svh): (1) `V35_MX0B_WR` = 1, the word register: the EU's
  byte source is a registered word loaded from the queue's stored bytes only (never the arriving word or the
  latch), one load a clock, a pop finding it empty stalls; the queue gained one output (`stored`); measured
  against popping the stored bytes directly and against a load clock of its own: no change at the gate (the
  immediates' late takes are not the word register). (2) `V35_MX0C_DISPATCH` = 2, the dispatch stall: the word
  after E, which hands the staged opcode to its routine's entry, waits while the bus unit runs a fetch cycle
  (issue clock through last clock), and a form with a ModR/M byte also waits on a back-to-back fetch's issue
  clock; read from the bus unit's existing outputs. This is the frozen model's `_start` (start_sync=b2b_modrm,
  rules.md item 16, binned "emerges from the structure": it did not). It removes the wait dependence entirely:
  the restart fetch's mean offset from silicon goes from −0.5 / −3.0 / −8.9 clocks at 0 / 1 / 2 waits to a flat
  value in every family; placed on the E word instead (variant 3) the dependence returns. (3) The data book's
  "measured = book + 1 or 2" offset is this stall: the a6 method timed each form between I/O markers, the form's
  pops make room, the room issues a fetch, and the marker dispatches inside it; so the routines were re-derived
  from the book with the stall in place (MX0d), then shortened where silicon's direct measurement, less the
  stall, shows a book clock absent (MX0e: PUSH r16 13 → 8, OUT imm8 11 → 9, OUT DW 8 → 5, IN DW −3, NOP 4 → 3,
  XCH / MOV sreg / CVTBW −1; 12 routines, every one declared with its measurement). (4) `V35_MX0F_QSTART` = 1:
  Q2's triple-clock start is the E word's opcode pop, not the routine's entry (the MX0e core aborted a fetch on
  MOV CL,imm8's entry clock; model and RTL agree at +94). **OPEN words:** 122, each marking a data-book clock no
  act names (POP r16 5, POP PSW 7, OUT imm8 4, IN DW 8, IN imm8 10, BR far 7, SHL r,CL 5, MULU 9 / 10, DIVU 14 /
  16, DI / EI 2 / 10, CVTWL 5, PUSH imm 2 / 2, OUT DW 1, MOV acc,[d16] 1): the agenda. **Gate (verified on main,
  `+v35_chk`, both spacings identical, 0 failing, chk silent):** F0 F0w F1 F2 F3 F9 F11 F12 together 9 / 1,796
  exact (A1 1,691; F0 2, F9 7), F20 0 / 3,594 (A1 3,407), the whole refresh-off corpus 19 / 30,536 (A1 28,059;
  28,040 lost, 0 gained), every miss classified: (i) routine shape 24,907, (ii) bus-unit law 0, (iii) 5,610
  (offsets over 3 clocks at 0 waits and the F0w mixed-wait runs). The residuals every chain carries, traced to
  the clock and left open: the instruction after the shift +1 (SHL r,CL's OPEN words and MOV r8,imm8's book 5
  against the model's 4 cannot be separated on these chains; the ModR/M back-to-back clause stalls one clock the
  model does not); OUT imm8's port byte by parity (+2 at pE, −3 at pO: the model holds the fetch under the
  posted I/O write with a lead and issues the write at pop + 14, after the routine has ended — a bus-unit
  attribute with no act, as A1 recorded for the I/O lead); MOV [d16],acc +1. Write data: the gate families 0
  differing, the corpus 64,664 / 106,824 (the rest trap until MX1); `--regfile` on the gate families 0 bad
  (12,338 pass, 11,758 trap_nop; `test_rtl_vectors`' 1,900 bar counts trap_nop until MX1 lands, said in the
  test); `--fn` 9,525 / 0 bad; SST deferred to MX4; lint clean in the five configurations and with each macro's
  alternatives; 35 fast tests; the nine offline modules unchanged. **Depth and timing (overseer, on the MX0
  sources before MX0b; the later rounds add a stall and a word register):** whole-core map 3,741 LUT4, 274 ADD,
  862 FF, 41 RAM_5K (the ROM 19, the decode tables 18), 0 MULT in 19 s (A1 24,147 / 3,153 / 32 / 8 in about 5
  min); the levelizer's worst depth 24.6 (A1 202), queue `cnt` → the queue's room arithmetic → the bus grant;
  routed at 15.625 ns worst slack −10.3 ns (A1 −179.5), 26 levels, `useq/rom0`'s read port → the EU's request →
  the grant → the cycle registers (the next split, MX5); hold +0.3. **Mechanism-note corrections** are appended
  to docs/v35s-mechanisms.md ("Corrections from MX0"). The loss against A1 is the rule's expected cost and is
  recorded, not patched: the A1 core remains at 049e8c5.
- 2026-11-10, **MX1 landed** (the memory forms; the same Opus worktree agent, one round). **Built:** the EA as
  mechanisms §3.5 says, no EA routine: the word after E of a ModR/M memory cell (a decode bit `ea`) calls the
  EA head of the registered ModR/M's mode (`urom/ea.uasm`: the displacement's pops, none / one / two, and a
  return; the loader's `dcall` / `dret`, the sequencer's return register loaded at the dispatch), and the
  routine's first word is the add (`ea=BI ra=BASE rb=INDEX`, SS the default for a BP mode); no word tests a
  mode, the EA's clocks are the pops and the add. Two head sets by the routine's header: `ea=book` carries the
  book's EA clocks the pops do not fill as OPEN words (mod 00: one OPEN and one book error, eu-timing M4),
  `ea=bare` the pops alone for the routines whose own acts already exceed the book. `urom/mem.uasm` (loads,
  load+ALU, CMP, TEST, XCH, stores, MOV mem,imm, the segment moves, LES / LDS, LDEA, group 1 RMW and CMP,
  INC / DEC / NOT / NEG mem, TEST mem,imm, MULU / MUL / DIVU / DIV mem jumping into loop.uasm's loops, the memory
  shifts, PUSH / POP mem) and `urom/stack.uasm` (PUSH / POP sreg, PUSH R / POP R unrolled one word a register,
  TRANS, PREPARE level 0, DISPOSE): 121 routines, 1,005 of 1,024 ROM words (MX2 widens `UADDR_W` or OPEN
  words leave); OPEN words 383 in 50 routines (MX0 122; PUSH R / POP R 123 of them). The assembler: `ea=book|
  bare`, a per-path `diff=m00:K,d8:K,d16:K,dir:K`, `bookx=` for a book note's formula, `length` per path, the
  book check per path; `test_declared_differences_name_silicon` amended per ruling 3: a positive difference only
  on a path with no OPEN word and a reason naming the pops, a negative one naming its measurement, a fit
  rejected; a deliberately bad routine caught; EA tests (heads only pop and return, every memory routine starts
  with the add, the decode cells' bits, the EA clocks per path). Datapath: the request slot frees on the
  cycle's end (`rq_busy`), a read's datum latched at its end also when that clock posts the next request,
  `AL_ADD`, `SG_DSP`, the request address never reads the EA sum in the same tick (about 10 levels for the add;
  the deepest new path the arriving datum's lanes into the ALU on an F word, the ALU path plus about 3, with the
  split named if routing needs it). PUSH r16 reads its register after SP's write (PUSH SP pushes SP − 2, F36).
  No port of the bus unit or the queue changed. **Function gates (verified on main):** write data 93,540 /
  106,824 (MX0 64,664; every gate family 0 differing; the 3,972 left are MX2's transfers, MX3's 0F / bit /
  MUL imm forms and MX4's strings), `--regfile` on all 36 families 69,099 + 38,760 vectors 0 bad (pass 62,288
  + 30,857, trap_nop 5,854 + 6,744 + 300; a `PFX_OVERLAP` kind counted apart for a bench artefact), `--fn`
  19,752 / 0 bad, the SingleStepTests bar restored to `pass` over 1,900 for the implemented files with a named
  `LATER` set (MX2 / MX3 files required to be wholly trap_nop), lint clean in the five configurations and each
  macro's alternatives, 45 fast tests, the nine offline modules unchanged (the four known failures). **Timing
  (both spacings identical, 0 failing, chk silent):** unchanged, 19 / 30,536 exact (A1 28,059), the MX1 gate
  families 10 / 14,388 (A1 13,332; all F16), the MX0 gate 9 unchanged; (i) 26,946, (ii) 0, (iii) 3,571; the
  restart dt flat but F15 / F25 / F39. On the k2 runs the memory routines sit within a clock of silicon
  (SHL mem,1 2–3 short, MULU mem 3–4 short, CMP [BW],imm16 2 short, MOV mem,imm's interval +2 to +5 open).
  **Root cause of the flat count, traced by the overseer on main with the frozen model's event trace against
  the RTL's (`evtrace`; the model is exact on every run used):** the model's start S of an instruction is the
  clock its ModR/M byte is taken from the queue (the opcode prefetched into the IR earlier, with no effect on
  the room); the fetch that take's room triggers is issued on the same clock and never blocks the start (the
  machine's T phase precedes X), and a started instruction is never stalled by a fetch. The RTL's E pop of the
  opcode and ModR/M is that clock and triggers the same fetch, but the stall sits on the DISP word, one clock
  later, under that fetch: F3-push-add_aw_dw-k1-pE-w0, model ADD S 81 with fetch 10052 at 81 and the next PUSH
  S 84 on the b2b fetch's issue clock; RTL E 81, DISP waits 82–87, entry 88. Every instruction that makes
  room pays it, so the first divergence is the restart fetch or the marker in most runs and the memory forms
  are never reached. The same traces give silicon's S-to-S costs: ADD reg,reg 3 (the V20's read word, the ALU
  on E, the write post-E), NOP / XCH AW,r 4, MOV r16,imm16 5 and r8,imm8 4 with the immediate's first byte
  taken at S + 3 in every immediate class (the model's `pre` 3: one open mechanism, an operand-byte path
  latency the opcode / ModR/M path lacks), PUSH r16 9, SHL r,CL 12 + 2n, MOV CL,imm8 4, a load [BW] posting
  its read at S + 5 with S-to-S 11. MX0's measurement of the stall on the E word (README MX0d) was confounded
  by the book-shaped routine lengths of that round. **MX1b** is sent to the agent: the stall on the E word
  (a fetch granted on an earlier clock; a back-to-back fetch's issue clock for a ModR/M form), the register
  forms re-derived to those costs with the pops at the measured clocks (named acts first, OPEN words on the
  chain evidence, each citing the run), then the memory forms on the k2 runs; the baseline for it is this
  commit. Hand-back and verification: /tmp scratchpad v2/mx1/ (mx1.diff, mx1-table.md, mx1-k2.txt,
  mx1-book.txt), v2/mx1/main/ (verify.out, the traces, side.py).
- 2026-11-10, **MX1b landed** (the same agent, one round on the overseer's trace finding above). **Built:** (1) the
  dispatch law moves to the E word (`V35_MX0C_DISPATCH` 4, the default): the E word, the opcode's pop with its
  ModR/M, does not execute while a fetch granted on an earlier clock is in flight through its last clock, and a
  ModR/M form's E not on a back-to-back fetch's issue clock; a fetch granted on the E clock never blocks it; the
  dispatch and the routine's words never stall on a fetch. The same gate as MX0d's value 3, which measured 0 exact
  only because the routines were then sized for the stall a clock later; measured and not kept: the stall ending a
  clock before the fetch's last (−3 / −6 / −10 at 0 / 1 / 2 waits) and the staging slot freed at the E pop. The
  machine explanation on record is unchanged (the opcode's read from the queue and a fetch in flight exclude each
  other); it is the pop the law gates. `V35_MX1_EAFREE` removed as moot; the trace gained an `E` item. (2) The
  register-form routines re-derived so that E-to-E and the pop clocks equal the model's S-to-S and take clocks on
  an exact k1 / k4 run named in each `why=`: ADD / CMP / MOV reg,reg 3 (the registers' RAM read a word of its own,
  the ALU on E, the write after: the V20's shape; the book's 2 one short of silicon, the added word a named act),
  NOP / XCH AW,r 4, the byte-immediate forms 4 (book 5) and the word-immediate forms 5 (book 6) with the immediate
  popped at S + 3 (and S + 4), PUSH r16 9 (the post at S + 5), MOV [d16],acc 9 (book 8), SHL r,CL 12 + 2n (the
  shifter's load on its own word), SHL r,imm8 11 + 2n and SHL r,1 9 (silicon 12 + 2n and 10: one clock each still
  open), OUT imm8 10, OUT DW 7, POP r16 11, IN DW 12, IN imm8 16. Every immediate form shows the same three clocks
  before its first pop (one OPEN word before the pop), and a d8 displacement is taken at S + 3 too: the one open
  mechanism this suggests is an operand-byte path latency the opcode / ModR/M path lacks. (3) The memory forms on
  the k2 runs: [BW] posts its read at S + 4 (issued S + 5 as the model's), displacement forms at S + 6; the d8
  head's OPEN word before the pop, the d16 head's dropped (a book error of one at mod 10); a read-modify-write's
  write issues two clocks after the datum; loads keep E at the model's next S with the OPEN words under the cycle;
  group 1's immediates popped after the datum; at mod 00 against the book: MOV / ADD / CMP reg,mem 11 (10), ADD
  mem,reg 13, TEST mem,reg 13, XCH 16, MOV mem,reg 8, ADD mem,imm 14 / 14 / 15, CMP mem,imm 14 / 14 / 15 (11 / 12 /
  12), INC / DEC / NOT / NEG mem 13 (16), SHL mem,1 19, PUSH mem 17, MULU mem16 40 (36). The book check per ruling
  3, amended and accepted: a path over the book may carry OPEN words only when its reason says "silicon longer than
  the book" and names the exact run (the frozen model exact on it); named acts beyond the book are declared as
  such. ROM 1,042 words (`UADDR_W` 11), OPEN words 439 in 67 routines. **Verified on main (both spacings identical,
  0 failing, chk silent):** 479 / 30,536 exact (MX1 19; A1 28,059), the MX0 gate families 118 / 1,796 (9), the
  MX1 gate families 232 / 14,388 (10), no family lost a run (F3 48, F9 49, F20 66, F21 44, F36 39, F16 37); (i)
  14,153, (ii) 0, (iii) 15,904; write data 93,540 / 106,824, register vectors 0 bad, function vectors 0 bad, lint
  clean in five configurations and the macro's values 0 / 2 / 3, 45 tests, the nine offline modules unchanged.
  The PUSH frame now matches silicon at the start of F4-push-ld_bw-k1-pE-w0 (the write 78, the fetches 81 and 84,
  the read 87). **Open after MX1b, with the overseer's reading of the w0 / w1 traces of F3-push-nop-k4-pE:** the
  restart dt is about −2 / −3 / −4 at 0 / 1 / 2 waits in most families and the largest (i) bucket is the PUSH
  marker's write −1 at 1 wait and −2 at 2 (F21 880, F20 740, F3 284): the LS head's SHL AW,CL (n = 31) runs 75
  clocks on silicon at 0 waits and 76 at 1 wait against the RTL's 74, which is the frozen model's `unit_hold` (a
  register shift, MULU / MUL or DIVU / DIV pauses at its two-clock iteration boundary while a fetch is past its
  second clock, until the clock after its last, once per fetch; rules.md item 94, fitted true over the corpus);
  the same law covers MX0f's "instruction after the shift +1" and OUT's port byte at S + 5 after the shift. The
  prelude's MOV r16,imm16 stream fetches three clocks later than the model's (its room counts the staging slot as
  occupied while bytes are owed; the model's room_ir = arrival_idle counts an empty IR as free on a word's arrival
  clock and when idle). The immediate store pops its datum after its write issues in the model (a datum taken by
  the bus after B2, not built). **MX1c** is sent: the loop's hold under a fetch as a sequencer mechanism (macro
  `V35_MX1C_UHOLD`, the explanation recorded as a hypothesis: the iteration and the fetched word's delivery share
  a resource), then the arrival-clock room law as a queue law under 6(ii) with the corpus as its measurement.
- 2026-11-10, **MX1c landed** (the same agent). **The overseer's unit-hold reading was wrong**: the agent wrapped
  the frozen model's `_unit_hold` and `_start` in a probe; on F3-push-nop-k4-pE at every wait and on F0-ls the
  hold never fires during the LS's shift (it fires once each on F16-l-push-mulu_dw-pE-w1 and F3-push-mulu_dw-k4-
  pE-w2). The shift's 75 / 76 / 77 clocks at 0 / 1 / 2 waits are the model's take sync (`take_sync=pending`,
  eu.py 1164–1219): the exec starts at S + 4 / 5 / 6 after the ModR/M's take at S, once the fetch in flight or
  requested on that clock has delivered. **Built:** (1) the take sync behind `V35_MX1C_TSYNC` (default 0): a
  register form's ModR/M popped on its E word, or its immediate byte, arms it; displacement bytes, the memory
  forms' bytes and port numbers (a new pop target `pop=port`, the model's port_sync=none) do not; the routine's
  next words that pop nothing wait until the fetched words in flight or requested on the arming clock have
  arrived (at most two, `tw`, traced `W:sync`); E words and the dispatch never wait; the delivery's own clock
  frees the word; a request held back by the EU's own reservation is not counted; a lapsed request ends the
  wait. Measured on F0 F1 F2 F3 F9 F12: the LS's shift 75 / 76 / 77 as the model's, the restart dt flat across
  the waits in every family (+0.83, −0.50, +0.97, −1.21, +1.25, −1.03 at 0, 1 and 2 waits alike; MX1b's grew a
  clock a wait), the unexplained bucket 783 → 124, but a uniform clock (the PUSH frame +1, the OUT frame −1)
  leaves 0 exact: on F3-push-nop-k4-pE-w0 the model takes the immediate and loads its next-opcode register on
  one clock (−4) and starts SHL at −3; the RTL loads the word register at −4 and the staging register at −3
  and starts SHL at −2 (`V35_MX0B_WR` 0 the same). Left off until that clock is found. (2) The room law
  (`V35_MX1C_ROOM` 1, the default): the staging slot is free on a word's arrival clock when it is empty (the
  model's room_ir = arrival_idle); the loader reads the bus unit's existing delivery strobe (`q_arrive`), no
  queue or bus port changed, neither file edited; the prelude's MOV r16,imm16 stream at 1 wait matches the
  model clock for clock. Variant 2 (free whenever empty) 0 exact on the MX0 gate families. **Verified on main
  (both spacings identical, 0 failing, chk silent):** 485 / 30,536 exact (MX1b 479; F3 +2, F40 +4, nothing
  lost), the MX0 gate families 120 / 1,796, the MX1 gate families 232 / 14,388; (i) 14,224, (ii) 0, (iii)
  15,827; write data 93,540 / 106,824, register and function vectors 0 bad, lint clean in five configurations
  and at TSYNC 1 / ROOM 0 / ROOM 2, 45 tests; no Python changed, so the nine offline modules are as at MX1b.
  OPEN words split: 421 book clocks, 18 beyond the book (silicon longer, measured: ld, ld_alu, cmp_rm, cmp_mr,
  xch_m, the group-1 CMP mem,imm forms, MULU mem16, IN imm8), 9 named acts beyond the book. The note's item 7
  is corrected to the take sync. **MX1d** is sent: the model takes a delivered word's byte on its arrival clock
  (machine.py `queue.arrive(addr, t, t)`) and loads the IR on the last take's clock, while MX0b's word register
  loads from the stored bytes only, never the arriving word; the take sync releases the pop exactly on the
  delivery clock, so the byte path is a clock late on every synced pop. MX1d builds the delivery-clock bypass
  (and the staging load on the last pop's clock), measured against `V35_MX0B_WR`'s values, then switches the
  take sync on.
- 2026-11-10, **MX1f landed** (the same agent; MX1d and MX1e, the delivery-clock bypass and the latch hold, land
  with it). **The uniform clock was the room's count.** A per-clock comparison of the RTL's room facts against
  the frozen model's on the prelude's 6-clock MOV r16,imm16 (F3-push-nop-k4-pE-w0, RTL E −55 against the
  model's S −60) found the E clock counted alike and the first take's clock two bytes short in the RTL: the
  immediate's low byte (the RTL released it on its pop; the model's take step is the immediate word,
  `take_commit=at_end`, the first byte counted until the second is taken) and the delivered word's second
  byte in the latch (not counted on its delivery clock by the RTL; counted by the model while the
  instruction is mid-take). Those two bytes raised the RTL's extra fetch, the 6-clock MOV, and set the
  prelude's phase. **Built**, each behind a macro with the alternative measured: (1) `V35_MX1C_ROOM` 3, a
  take step's bytes released at the step's end (a popped low byte with bytes still owed, the immediate's or
  a d16 displacement's, held and released with the next pop or the E pop; the arrival-clock staging law
  kept); (2) the byte path the queue's storage (`V35_MX0B_WR` 0 with `V35_MX1D_ARRIVE` 1: the pops read
  the stored bytes with the arriving word bypassed; under the word register its bytes sat outside the six
  storage bytes so the latch never filled where the model's does); (3) the latch hold (`V35_MX1E_LHOLD` 1),
  the take sync and its E gate (`V35_MX1C_TSYNC` 1, `V35_MX1E_TSE` 1) on; (4) `V35_MX1F_ASKL` 1: the take
  sync counts the request the room raises whether or not the latch holds it off the bus, the model's
  `asked`; it needs the queue's raised request, a new output `fetch_raise` through v35_top into the
  sequencer, **the one port added to the queue since MX0** (the overseer's ruling: the raised request is a
  quantity the queue already holds, the no-port rule was the overseer's conservatism for the bus unit's
  interface, not the user's; without it the gate families fall 285 → 126 and the restart dt grows with the
  waits again); (5) shift_cl at the book's 11 + 2n: silicon's twelfth clock is the take sync's wait (the
  exec starts on the delivery of the word the ModR/M's take asked for), one OPEN word fewer; (6) OUT's
  write-back wait (`V35_MX1F_WB` 1): the agent's probe of the model (`an/probe4.py`,
  F3-out-shl_cl4-k2-pE-w0) placed the shift's done_t at OUT's own start and wb_until two clocks on, OUT's
  wbsync waiting those two, its three pre clocks and the port take at S + 5 (S + 3 after a NOP); built as a
  word flag `wb` on the E words of the routines whose result's write-back runs on past E (the shifts, the
  register multiplies and divides, CVTBW, CVTWL) and a decode bit `wbs` on OUT imm8 (its routine reads the
  accumulator first): the E word that pops a `wbs` opcode waits out the write-back's two clocks, the
  result's write then the flags'; only OUT imm8 waits (OUT DX, IN and the register forms have no wbsync;
  the register forms' first word is at E + 2, the write-back's end); the overseer's fallback (the entry
  word waiting, variant 2) measures identical; the wb 1 and wb 3 classes are not flagged, a one- or
  three-clock flag being a count. **Traced** (F3-push-nop-k4-pE-w0): every prelude MOV at 7 from E to E on
  the model's S, one fetch per MOV at S + 4 and the arrival's at S on alternate MOVs as the model's, SHL's E
  at −3, 10050 at −2, the shift 75, the PUSH frame's write at 78, the NOPs 81 / 85 / 89 / 93, the second
  shift 74; F3-out-shl_cl4-k2-pE-w0 the port take at S + 5 and the I/O write at +84 as the model's.
  **Verified on main (both spacings identical, 0 failing, chk silent):** 1,285 / 30,536 exact (MX1c 485;
  the MX0 gate families 285 / 1,796; every family gained or held: F3 50 → 124, F6 3 → 49, F9 49 → 90, F16
  37 → 102, F21 44 → 208, F36 39 → 85, F38 29 → 67; F10, F24, F31 at 0, F23 at 2); per run 897 gained and
  97 lost (F20 35, F9 10, F3 8, F36 8); the restart dt flat across the waits in every family (F0 +0.00, F1
  −0.83, F2 +0.03, F3 −1.25, F9 +0.26, F11 +0.14, F12 −1.18; F15's −1.50 / −1.61 / −1.72 the widest); the
  agent's variants on the gate families: take sync off 0, ASKL 0 126, ROOM 1 97, WR 3 283, WB 2 285, WB 0
  253; classification (i) 22,321, (ii) 0, (iii) 6,930; the function gates unmoved (write data 93,540 /
  106,824; register vectors 69,099 + 38,760 and function vectors 19,752, 0 bad; the agent's whole-core
  SingleStepTests run 0 bad with POP ALL now passing where it trapped); lint clean in five configurations
  and the variants; 45 fast tests; the nine offline modules 941 tests with the four known fit-tracking
  failures. OPEN words: 421 book clocks, 18 beyond the book with their runs, 8 named acts beyond the book.
  **The largest residual, not built:** 7,013 runs whose first divergence is the chain's final OUT DX's I/O
  write early by exactly the wait count (−1 at 1 wait, −2 at 2): the frozen model issues that write
  `setup0` clocks after its post without counting the running cycle's wait states (`io_count=nowait`),
  while the RTL posts on a fixed word and the write waits the running fetch out. A bus-unit question: what
  the running cycle is at the post and how the write starts under it, probed before anything is built.
  Also standing: OUT imm8's port byte at an odd address (the parity residual) and the fetch after an I/O
  write one clock later in the model. MX1g sent for the I/O write under a running cycle's wait states.
- 2026-11-10, **MX1g landed** (the same agent). **Two bus-unit laws, both from probes of the frozen model, both
  built behind macros with no port added.** (1) The I/O write under a memory cycle's wait states
  (`V35_MX1G_BW` 1): the agent's probe (`an/probe5.py`, the model's arbitrate wrapped) on F0-ls-pE-w1 / w2
  (their only MX1f miss the chain's final OUT DW,AW write, silicon 89 / 91 against the RTL's 88 / 89) showed
  the model's I/O and DW-form request setup (`io_count=nowait`, arbiter.py Request.counts) counting every
  clock but the post's own, HALT's start and each wait state of the running fetch (the write at S + 8 / 9 /
  10 at 0 / 1 / 2 waits); nothing overlaps and nothing is aborted (the overseer's candidates (a) and (b)
  do not occur). The paused clocks are OUT's moves of DW into the bus unit's address register (S + 2) and
  AW into its write datum (S + 3). Machine reading: those moves cross the internal bus between the units,
  which a memory cycle in its wait states holds for the datum it latches from the pins until READY. Built
  as a sequencer stall on the bus unit's existing `in_wait` output (wired in as `bus_wait`): any microword
  whose move writes the address register or the write datum waits while a memory cycle is in a wait state,
  whatever the opcode (variant 2, the address register only, 765 against 819 on the gate families). (2)
  The fetch after an I/O write (`V35_MX1G_IOH` 1): the probe (`an/probe6.py`, F3-out-nop-k2-pE-w0) placed
  the write at +84 to +86, the request up from +84 and the bus free at +87, the fetch at +88: the model's
  io_ir_hold (machine.py, `queue.io_held`), a request raised by the IR load on the I/O's issue clock held
  until the next start or until the line falls; not the bus unit's idle rule (min_gap 0; io_recover gates
  memory data cycles only), not the write's data hold. The agent's reading: on an I/O issue clock the bus
  unit's request input is the I/O's, and a line that rises then is first sampled at the next start's
  opcode pop. Built in v35_bus.sv on existing inputs. **The overseer records this reading as provisional**:
  the release at the next start is an EU event in a bus-unit law, and a registered sample of the request
  (a line rising on the issue clock seen a clock late, no start dependence) may measure the same; it is to
  be measured before the reading is confirmed. It gains 10 runs on the gate families (819 → 829) and 6
  alone. **Verified on main (both spacings identical, 0 failing, chk silent):** 3,552 / 30,536 exact
  (MX1f 1,285; the MX0 gate families 829 / 1,796 with F0 18 / 18, F3 380, F9 264; every family gained or
  held: F21 208 → 704, F3 124 → 380, F16 102 → 280, F9 90 → 264, F36 85 → 232; 2,267 runs gained, 0
  lost); the restart dt per family unchanged from MX1f; classification (i) 17,262, (ii) 0, (iii) 9,722;
  the function gates unmoved (write data 93,540 / 106,824; register vectors 69,099 + 38,760 and function
  vectors 19,752, 0 bad; the agent's SingleStepTests set as MX1f); lint clean in five configurations and
  the variants; 45 fast tests; the nine offline modules 941 with the four known failures. **The (i)
  bucket split** (`an/split_i.py`, keyed on the first divergent event, the model's instruction at it and
  RTL − silicon): OUT imm8 at an odd port byte 4,092 runs (3,952 at −5: the model's fetch held behind the
  posted I/O write with its lead), kept apart; then OUT imm8's fetch −1 (501), PUSH r's stack write +1
  (317) and −1 (289), POP mem's stack read −3 (306), the I/O write after OUT at −2 (265 + 235), CALL near's
  fetch +2 (253), CMP mem,imm's read −1 (229), MOV r,r/m's fetch +3 (216), a load's read −1 (213): the
  stack forms and CALL are MX2's, the loads' and stores' −1 / −2 growing with the waits are the memory
  requests' setup under wait states (the model's data_while_fetch counting, not the I/O rule), the next
  bus-unit probe. MX2 sent: the transfers and the stack, with the IOH alternative and the memory setup
  probe in the same round.
- 2026-11-10, **MX2 part 1 landed** (the same agent, handed back early at the end of its context; the transfers go
  to a fresh agent). **The two probes.** (a) The post-I/O fetch hold's registered-sample alternative
  (`V35_MX1G_IOH` 2: the line's rise on an I/O issue clock seen a clock late, no start dependence) measured
  825 against 829 on the gate families and 4,062 against 4,158 on the corpus, gaining nothing and losing 96
  (F33 32, F21 24, F20 16; e.g. F33-out-dec_aw-k4-pE-w1): on those runs the bus is free before the next
  instruction has started and the model holds the fetch to that start. IOH 1 stays; its reading stays
  provisional. (b) The memory loads' and stores' reads early by the wait count are the take sync, not a
  counting rule: the agent's probe on F4-push-ld_bw_ix-k1-pO-w0 / w1 / w2 placed the model's read at S + 5
  / 6 / 7 with the request's setup 0 and the form's two EA clocks starting on the delivery of the fetch the
  ModR/M's take issued (S + 3 + w); the RTL had armed the sync on a register-mode ModR/M only (MX1c's
  exemption). Built as `V35_MX2_TSM` 1: a memory form's ModR/M pop on E arms the take sync and in a memory
  form the sync gates the EA's add only, the heads' book EA clock standing (a first version that dropped
  mod 00's head gained 982 and lost 376 on the prefixed forms, where no fetch is owed at the pop and the
  head's clock stands: F21-none-es-add-bw-pE-w0). The reading is the take sync's own (the operand byte's
  path and the fetched word's write sharing the queue's port), now with no form exempt but the displacement
  and port bytes. Traced: the load's read at S + 5 / 6 / 7 and the prefixed ADD mem,reg exact. **Verified
  on main (both spacings identical, 0 failing, chk silent):** 4,572 / 30,536 exact (MX1g 3,552; 1,020
  gained, 0 lost: F21 704 → 968, F20 189 → 429, F6 109 → 178, F38 153 → 218, F19 33 → 91, F15 109 → 160;
  the MX0 gate families unchanged at 829); classification (i) 16,455, (ii) 0, (iii) 9,509; the function
  gates unmoved (write data 93,540 / 106,824; register vectors 69,099 + 38,760 and function vectors 19,752,
  0 bad); lint clean in five configurations and the variants; 45 fast tests; the nine offline modules 941
  with the four known failures; ROM unchanged (1,042 words). Open from the probe: the load's own length
  is off by the waits (11 against 10 at 0 waits, 13 against 14 at 2): its five OPEN words after the post
  sit on the model's 0-wait positions where the model waits for the datum and two clocks, a routine
  question about the F word's place. **The transfers probed, not built** (README "MX2 (part 1)" §2): the
  model flushes once no fetch is in flight and the class's gap has passed since the last fetch's end (BR
  short 5, BR near 3, a taken conditional 8, not taken 1), no earlier than its exec clocks after the
  take, empties the queue and issues the target's fetch on the flush's clock; the target's first
  instruction starts only when no fetch is in flight or wanted (BR short at 104 after four refill
  fetches on F23-push-br-n0-pE-w0). The agent's proposed readings, to be tested class by class in part 2:
  the V20 ROM's SUSP (a word that suspends prefetching and waits while a fetch cycle runs) before FLUSH,
  the gap being the routine's words between them from the book's formula, and the refill as the take
  sync's port reading (the target's E word waiting while the refill's fetch run lasts). MX2 part 2 sent to
  a fresh agent: urom/xfer.uasm, the flush and refill traced against the model, the PUSH frame's
  residuals, the gate on F23 F30 F35 F37.
- 2026-11-10, **MX2 landed** (a fresh opus55 worktree agent, from cf2d12f). **The transfers and the stack built**
  (urom/xfer.uasm): BR short / near / far, the sixteen conditional branches taken and not taken, DBNZ /
  DBNZE / DBNZNE / BCWZ, CALL near / far, RET / RET imm16 / RETF / RETF imm16, BR and CALL through a
  register and through memory (the far forms' second read), BRK 3 / BRK imm8 / BRKV, RETI; each from the
  book's formula with the words on the frozen model's clocks from a run it is exact on, named in the header;
  every positive difference "silicon longer than the book" with its run, the negative ones (the not-taken
  conditionals, BCWZ, DBNZE, CALL far) book errors with a run; the book check counting the refill's first
  fetch before the target's E word and checking two-valued formulas on both paths. **The mechanisms:** the
  SUSP word (the queue's request line held low from the word to the FLUSH, the word waiting while a fetch
  is on the bus; the queue's existing `susp` port), FLUSH with the target from SIGMA as the V20's
  `SIGMA -> PC FLUSH` (the reset's far branch moved into xfer.uasm), the refill gate (the E word that pops
  the target's opcode waits while a fetch is in flight or while the request line was up at the end of the
  previous clock; this clock's line would loop through E's own pop), the instruction pointer as a
  register source (two 16-bit offset registers in the loader), the vector source, a zero segment, the
  condition decoded from the encoding (`xc`), the E word popping a short transfer's displacement with its
  opcode (`e2`, arming the take sync), an F word after a write waiting the write's end under RAMEN, and
  `V35_MX2_E2H` 1 (the displacement counted in the room one clock more, Q2's triple clock then aborting
  where the model's does; linted at 0, not replayed). No bus-unit or queue port changed, neither file
  edited. **The PUSH frame's residuals:** PUSH r +1 after MOV AW,DW was MX1b's separate register-read word
  in the reg,reg routines, which the take sync then delayed a clock: ADD / CMP / MOV reg,reg are back on the
  book's 2, silicon's 3 the sync's wait (+248 / −6 alone; MX1 correction 2 withdrawn for them); PUSH r −1
  after MULU r16 is MULU's own 34 against the book's 32, open; POP mem −3 is the model's stack read posted
  at the start holding the fetch, not built. MOV [d16],acc's reservation moved from its E pop to its last
  pop (+72). **Verified on main (both spacings identical, 0 failing, chk silent):** 5,765 / 30,536 exact
  (MX2 part 1 4,572; 1,246 gained, 53 lost); F23 6 → 153, F30 154 → 219, F35 51 → 264, F37 36 → 63; the
  MX0 gate families 829 → 956 (F3 425, F9 315); F20 429 → 720, F39 55 → 143, F36 239 → 290; F26 45 → 43
  the one family net down. **The 53 losses, each named:** 34 are a register form before the OUT marker
  (F20 F12 F7 F26 F2), the model's io_older (an OUT waiting out a fetch requested before its start) that the
  withdrawn read word had absorbed; 19 are short transfers not taken at an odd address (DBNZE / DBNZNE in
  F35 / F40, BNE / BE in F34), the model's xfer_nt (the re-raised fetch request held to the instruction's
  end) that the trap routine had matched by accident. Write data 96,786 / 106,824 (93,540); register vectors
  69,099 + 38,760 with 0 bad (pass 97,109 from 93,145, trap_nop 8,634 from 12,598); function vectors
  19,752, 0 bad; the agent's SingleStepTests run 0 bad; lint clean in five configurations and with E2H 0 /
  TSM 0; 46 fast tests (test_uasm's taken / not-taken check added); the nine offline modules 941 with the
  four known failures. ROM 1,473 / 2,048 words, the microword 91 bits; OPEN words 661 in 87 routines (the
  transfers 229). **The overseer's ruling on the not-taken decide's wait (`fw`):** a microword flag with no
  count (the word waits while a fetch cycle runs or delivers its word, the model's untaken=wait; SUSP's
  wait alone starts the next instruction a clock early on F23-push-bne-n0-k1-pE-w1), kept as built; its
  reading is provisional: the queue's port (the decide's not-taken exit continuing into the next E pop,
  which the delivered word's write into the queue blocks that clock, the take sync's accepted mechanism
  one clock wider) over the instruction pointer's read; the sources name neither, and whether the take
  sync's E gate and `fw` are one law a clock apart is for the user's eye and a later probe. **Open
  (MX2):** DBNZ / BCWZ / DBNZE taken, where the model stops fetch requests from S + 2 before the routine can
  know the outcome (not causal in a routine, recorded, not built; −14 at odd parity); the target OUT after a
  refill (the model's refill_start=full_io decodes the next opcode, forbidden); the model's IR load a clock
  after a register form's ModR/M take (nx 1); the memory-indirect forms and BRK at odd parity under the
  model's group setup; OUT imm8 at an odd port byte (4,092 runs; caps F23 / F35 / F37 by 90 / 309 / 108);
  the load's tail length under waits. MX3 sent to a fresh agent: the I/O probes (the odd-port OUT, io_older,
  full_io, the IR load's clock) first, then the loops and the 0F page.
- 2026-11-10, **MX3 part 1 landed** (the MX3 agent, handed back after the brief's item 1; the loops and the
  0F page not started). **The four I/O probes, each per clock in the frozen model and in the RTL's traces;
  one law built, one variant measured both ways and left off, two recorded with no machine reading.**
  (a) **OUT imm8 at an odd port byte** is 8,015 runs now (MX2's gains moved the rest of the pO frames'
  first divergences here): the fetch after the port byte's pop issued at +77 where silicon holds it to +82.
  The model's frame is three holds: on the post's clock only the reservation's queue rule holds a fetch,
  and the parity is the count (the pO queue holds 4 bytes at the port pop, the shift's last fetch having
  put both its bytes behind the staged opcode, the pE queue 3; the port byte's arrival is not involved);
  from the next clock the posted I/O holds every fetch; on the lead's first clock (setup − lead, the lead
  a fitted 2) a fetch requested no later than the post goes first and the I/O follows its end. The first
  two are A1's rule 3 if OUT imm8 raises its reservation on the port-pop word and the bus unit learns the
  kind with the post; the third has no act the agent could name (a FIFO law at the post's clock is one
  late; the first two alone put the fetch after the I/O, which silicon refutes). Not built; **the user's
  ruling asked** (note item 23, with the overseer's candidate reading). (b) **The 34 MX2 losses are the
  model's wlatch, not io_older**: an I/O port form's start no earlier than the register form's last operand
  take + 4; io_older never fires on them. Built as `V35_MX3_WBR` 1 (MX1f's write-back law extended,
  provisional): a register form that took an operand byte (a register ModR/M or a popped immediate) and
  writes its result on the post-E word holds the register file's write port the clock after E, and the E
  word that pops a `wbs` opcode (OUT imm8,acc) stands that clock. The assembler derives the word bit
  `wp` (never hand-written; alu_rr, mov_rr, xch_rr, mov_sr, mov_rs, alu_ai8 / ai16, grp1_rb / rw); the
  sequencer's `wpn` stands the E word once. The variant on every post-E write (INC / DEC r16, XCH AW,r,
  CVTBW too) measured −131 / +103: the model has no wlatch after a form with no operand byte, the fact
  the reading does not yet explain. The model's window (the take + 4) and the RTL's (E + 1) agree on every
  corpus run (the take sync holds E to S + 3); IN imm8 is not `wbs` and no run exercises it. (c) **The
  target OUT after a refill (refill_start=full_io)**: F23-out-br-n0-pE-w0 against w1, the w0 and w1
  delivery clocks have the same queue and request line and differ only in the fetch's length and the
  opcode, the two facts the model uses; a delivery-clock gate for every opcode would stop the non-I/O
  targets the RTL matches; no causal reading, item 21 stands. (d) **The staging load a clock after the
  E word's ModR/M pop** (the model's nx 1): `V35_MX3_IRL` 1 (a register-mode ModR/M) 5,930, +145 / −42;
  2 (any ModR/M or e2 byte) 5,893, −79; the runs that separate them F9-push-movr_nop0-pO-w0 (MOV reg,reg,
  gained) against F9-none-nop2-pE-w1 (SHL AW,CL, lost: the model's take and IR load on one clock). The
  model's delay is per class (reg 1; TEST, the shifts and MUL 0; adjust and flag 1); nothing in the RTL
  separates them at the staging load but the routine: off at 0, the +103 open. **The unit hold** probed:
  the model's `_unit_hold` fires on two corpus runs (MULU r16 after PUSH: F16-l-push-mulu_dw-pE-w1,
  F3-push-mulu_dw-k4-pE-w2), at an iteration boundary while a fetch is past its second clock; the
  reading offered is MX1g's BW law with B3 included (the iteration's step on the internal bus the fetch's
  datum phase holds); not built. **Verified on main (both spacings identical, 0 failing, chk silent):**
  5,827 / 30,536 exact (MX2 5,765; 62 gained: F20 +32, F38 +7, F3 +5, F12 +5, F7 +4, F40 +4, F26 +2,
  F34 +2, F2 +1; 0 lost); the MX0 gate families 956 → 967; F23 153, F30 219, F35 264, F37 63 unchanged;
  F32 12, F33 72, F34 83, F39 143, F40 172. Write data 96,786 / 106,824 (as MX2); register vectors
  69,099 + 38,760 with 0 bad (pass 97,109); function vectors 19,752, 0 bad; lint clean in five
  configurations and with WBR 0, IRL 1 / 2; the fast tests; the nine offline modules 941 with the four
  known failures. ROM 1,473 / 2,048 words, the microword 92 bits (`wp`). v35_bus.sv and v35_queue.sv
  untouched, no port added. **Open (MX3 part 1):** the release in (a), the user's ruling (8,015 runs);
  the staging load's clock (an act separating the reg-class routines from the shifts, or a ruling); the
  target IN / OUT after a refill; the one-byte forms' exemption from the write-port hold. MX3 part 2
  sent: the loops, the BCD and bit forms, the 0F page, MULU r16's two clocks, the unit hold.
- 2026-11-10, **MX3 part 2 landed** (a fresh opus55 worktree agent from d780a67, handed back early: the loops
  done, the 0F page not started). **The multiply and divide units rebuilt on the book's formulas**
  (urom/loop.uasm): the two operands read on ports A and B in one word, the unit loaded on the next, the
  loop from the entry's third clock (one step a word, the counter from the width), the book's OPEN clocks
  behind the loop where MX1 had them before it, the divide's pre-check folded into the finish's jump.
  **MULU r16's 34 resolved:** the book's 32, one clock silicon longer than the book (F14-g-push-mulu_aw-pO-w0,
  no fetch under the loop: 33), and the unit hold's clock at pE; MULU r8 25 plus the hold; DIVU the book
  plus two (F16-l-push-divu_ix-pE-w0). **Signed MUL / DIV** on the same shape: the book's low end plus
  silicon-longer clocks (MUL r16 +4, r8 +5; DIV r16 +6, r8 +6; F33-out-mul_cw-ld-k1-pE-w0 and
  F33-out-div_cw-ld-k1-pE-w0), the sign clocks the book's range on conditional paths: MUL +8 negation on the
  new F1 condition (the units' sign latch, the V20's F1), +1 with the low half zero and +1 more with the
  high half zero (SIGMA's zero test; the word form); DIV +7 on DN (the dividend's sign) and +2 on F1 (the
  quotient's). MUL r8 and DIV r8 have no corpus run (the a6 sweep alone). **The unit hold built**
  (`V35_MX3B_UH` 1, item 26's reading, provisional): a multiply or divide step waits while a fetch is past
  its second clock, read from the bus unit's existing `fetch_past_b2`; off loses 39 and gains 0. **The
  unit's suspension of a dropped request** (`V35_MX3B_US` 1, new, provisional): a fetch request the bus
  unit dropped with an aborted cycle at a unit form's start (F3-push-mulu_dw-k2-pE-w0: Q2's triple-clock
  abort at +116, silicon's fetch at +147 where the RTL re-raised at +119) is held through the queue's
  existing `susp` from the unit's load word to its result word; a request not dropped still goes
  (F16-l-out-mulu_aw-pE-w0; suspending every request loses 29); the sequencer gains the bus unit's
  existing abort grant as an input, no bus-unit or queue port added; off loses 18 and gains 0. **The
  adjusts and converts:** ADJ4A / ADJ4S and ADJBA / ADJBS at the book's 9 and 17 (none exact: ADJ4A's
  fetch 3 late and its OUT port 1 early, ADJBA's OUT write 4 early, the model's wb 3); CVTBD on the divide
  unit at the book's 19 plus one (12 of 18 exact, the six pO OUT frames the pending ruling's); CVTDB on
  the multiply unit by ten at the book's 20, exact; MUL r16,r/m,imm (69 / 6B) on the signed shape at the
  book's low end, none exact (the model's mul_imm_reg=gap and mul_imm_hold; the memory forms' fetch under
  the multiply, silicon +134 against +93). New ALU ops AL_ADJ / AL_CVBI / AL_CVBF / AL_CVDI / AL_CVDF (25
  to 29 of 32), conditions F1 and DN (the 3-bit field full). The `wp` derivation unchanged. **Verified on
  main (both spacings identical, 0 failing, chk silent):** 5,965 / 30,536 exact (part 1 5,827; 138 gained:
  F16 +39, F33 +39, F3 +18, F40 +18, F14 +12, F15 +12; 0 lost); the MX0 gate families 967 → 985; F32 12,
  F34 83, F39 143 unchanged (the 0F page not built); F23 F30 F35 F37 unchanged. Write data 96,948 / 106,824
  (96,786); register vectors 69,099 + 38,760 with 0 bad (pass 98,574 from 97,109); function vectors 19,752,
  0 bad; the SingleStepTests 27 3F D4 D5 at 10,000 and 6B at 9,996 (the reference's on-chip page), dropped
  from test_rtl_vectors' later list; lint clean in five configurations and with UH 0 / US 0 / WBR 0 / IRL 1;
  46 fast tests; the nine offline modules 941 with the four known failures. ROM 1,669 / 2,048 words.
  **Open (MX3 part 2):** the 0F page (a 0F memory form's EA call on its ModR/M byte, the ALU field widened,
  a (CL + 1) / 2 counter load for the BCD strings); the memory unit forms' read two clocks early at pE w0
  (silicon's read at the last fetch's end plus the cycle's length, +3 a wait state, F5-push-mulu_m-k1-pE:
  the model's group setup, no reading); OUT imm8 after a multiply (12 runs: the model's MULU write-back
  the shift's); the adjusts; MUL imm's fetch holds. MX3 part 3 sent: the 0F page.
- 2026-11-10, **whole-core timing on the MX3 part 2 sources** (overseer, on the user's question; `v35_timing.sh top`
  at 15.625 ns, no exceptions, 143 s). v35_top.sv did not include v35_macros.svh (the macros reached it through
  the other files' includes under Verilator; Efinity's parser compiles each file alone and `V35_MX0F_QSTART ?`
  expanded empty): the include added, lint unchanged. Map 4,504 LUT4, 368 ADD, 1,026 FF, 72 RAM_5K (MX0 3,741 /
  274 / 862 / 41). **Worst setup slack −15.151 ns** (MX0 −10.3), hold +0.306; the worst path 28 logic levels,
  30.6 ns of data path: the ROM bank's read data (3.7 ns) → 13 LUT levels of the word's decode and the
  sequencer's stall terms to the pop count → the queue's room arithmetic (three adders in series) → 11 LUT
  levels of the room → the fetch request → the bus unit's grant → the cycle registers (the refresh row's clock
  enable the reported endpoint; `in_q`, `fmt.len`, `fmt.xc`, `c_addr` and the sequencer's `tw` / `wbn` / `rf`
  the other reported ends). The same S2 → S3 → S4 chain MX0's run named, two levels and 5 ns longer with MX1 to
  MX3's stall terms. At this path the fabric closes near 32 MHz (a CPU clock of 16 MHz), half the directive's
  target; the report lists only the ten worst paths, so the spectrum below it is not shown. MX5 (the split of
  the word → pops → room → request → grant chain across the two ticks) remains the planned closure.
- 2026-11-10, **direction: MX5 before MX4** (the user, on the whole-core timing above: "run MX5 right after MX3
  part 3 lands"). MX5 closes the 64 MHz tick by structure (the brief: scratchpad v2/mx5-brief.md: tick A's chain
  shortened by assembler-derived word bits, flat stall terms and a parallel room computation, then work moved
  across the ticks by registers, state machines or speculation with a late select; no multicycle constraint; the
  corpus, the misses and `+v35_chk` identical to the base). MX4 (the strings) follows on the closed structure.
- 2026-11-10, **MX3 part 3 landed** (a fresh opus55 worktree agent from 647b149, handed back early: the 0F page's
  structure, the BCD strings, the bit operations and the digit rotates built; INS / EXT not built, the part 2
  probes not started). **The structure (no macro, always on):** the E word that pops 0F pops the second byte
  with it (the model's page_take=own; the decode's `pg` bit; no page head word; the dispatch reads the second
  level keyed on the second byte, whose `w` bit loads the form's width); a new sequencer act SQ_EAC on the
  routine's first word, which pops the ModR/M byte and lets its mode pick the next word (register mode: the
  routine's label; a memory mode: the EA head of that mode called, returning to the add; mod 00 with ea=bare:
  the next word), MX1's EA-head choice applied to the byte being popped (`ec_reg`, `ec_call`, `ec_head` from
  the loader, registered at ce_b, about 3 levels after the staged byte in tick A, one more source in tick B's
  next-address case; not a third decode level because the cell is keyed on the second byte alone); the ALU
  field widened to 6 bits (35 ops; BIT, BCDI / BCDS / BCDF, R4 on v35_fn_pkg's existing functions; the BCD
  carry on `scy`, a zero flop `bz`); the counter loaded with (CL + 1) / 2 as a word's act (CN_CLH, a 7-bit
  incrementer in tick B); the `wp` derivation counts a 0F routine's ModR/M pop as an operand byte taken and a
  flags write after E (TEST1) as a write (provisional, with item 22). The second byte does not arm the take
  sync (the model's chained take); the EAC pop does, and the memory path's add waits as under TSM. The book
  machine takes a register path plus the four EA paths for a 0F routine. **The routines (urom/page.uasm):**
  ADD4S / SUB4S per byte pair the book's 30 (the source read, the destination read 6 after its end, the write 9
  after that, the next source 6 after the write's end), the fixed part +1 silicon longer than the book
  (F32-push-add4s-n4-k1-pE-w0), the source address moved on the entry word under the BW law; CMP4S per pair
  the book's 25, +2 (F32-out-cmp4s-n4-k1-pE-w0); TEST1 / CLR1 / SET1 / NOT1 register paths 9 clocks start to
  start, the routine's words plus the take sync (the book's 6-8 a book error by the sync's clocks), memory
  paths the book's EA + n plus the EAC pop with the CL index 3 clocks before the read (F32-push-set1_mw_cl,
  test1_mw_cl, not1_mb_imm k1-pE-w0 exact); ROL4 / ROR4 register the book's 17 / 21 plus the sync, ROL4 [m]
  the book's EA + 20, ROR4 [m] = ROL4 + 4 (the book's EA + 26 a book error of 2). **Page rules:** page_take=own
  built; page_start=reg holds by structure; the b2b ModR/M start clause and the model's mode-first take clock
  (E + 3 memory CL, E + 2 register) not causal, recorded (the RTL pops at E + 2 for both, those runs exact);
  page_mem / page_cl / page_grp covered by the words after the sync, their residual the read W clocks early in
  the OUT frame at w1 / w2 (no reading); bcd_fetch=hold not built, no reading. **Verified on main (both spacings
  identical, 0 failing, chk silent):** 6,207 / 30,536 exact (part 2 5,965; 242 gained: F32 12 → 128, F34 83 →
  123, F39 143 → 187, F40 190 → 232; 0 lost); the MX0 gate families 985, F23 F30 F33 F35 F37 unchanged. F32's
  730 misses: 309 the pO OUT frame (item 23's ruling), 180 INS / EXT, 15 the frame's controls, 226 built forms
  (the open items). Write data 99,906 / 106,824 (96,948); register vectors 69,099 + 38,760 with 0 bad (pass
  104,763 from 98,574); function vectors 19,752, 0 bad; SingleStepTests 0F15 0F1A 0F20 0F22 0F26 passing and
  dropped from the later list (0F33 / 0F39 stay); lint clean in five configurations and with UH 0 / US 0 /
  WBR 0 / IRL 1; 46 fast tests; the nine offline modules 941 with the four known failures. ROM 1,922 / 2,048
  words (UADDR_W 11), the microword 93 bits. v35_top.sv carries the macro include of d8ea945 over the agent's
  copy. **Open (MX3 part 3):** INS / EXT (180 F32 runs, SST 0F33 / 0F39: the bit-field ALU steps, the crossing
  word, the offset register and IX / IY steps; the model's bf_* rules need readings); OUT imm8 after a 0F
  register form or a digit rotate (item 23's hold at pE; at w1 / w2 the `wp` stand on E where the model delays
  the port take: a probe candidate is the stand on OUT's entry word as WB 2 does); the 0F memory forms' read W
  early at w1 / w2; the part 2 probes; v35_bcd8's depth in tick B (a split candidate for MX5); the two pending
  rulings untouched. **MX5 sent next** (the user's direction): timing closure at 64 MHz; MX4 (the strings) and
  INS / EXT follow on the closed structure.
- **MX5 round 1 landed (2026-11-10): the two ticks shortened, not yet closed; structure only.** Ten splits,
  each a register at a stage boundary holding a function of registered values or a late select over values
  formed early, each written as the old function and compared by `+v35_chk` every clock (the core README
  "MX5" lists them with the reason each leaves behaviour unchanged): the ROM read at ce_b at the next address
  formed in tick A, the word a plain ce_a register (tick A loses the bank's 3.7 ns); the word's derived bits
  (the stall terms' field compares) decoded from the next word's read data in tick B; the loader's tick A
  expanded on the sequencer's late bit `ex` and on `z` (the bytes owed after the clock are none, written as
  compares against a target), selected last; the staging register's decode and the dispatch's facts as
  registers loaded with their sources (test_v35_struct's MX1 rule reads `dsp_f`); the queue's room as
  thresholds read from a thermometer by `rel` then by `stg` / `unc_a` (the three adders in series gone),
  `eq_r` a register of cnt + latch + unrel, the fetch address's two sums formed early with the flush selecting
  last; the bus unit's SFR compare on `req_addr` (a write is never a fetch); the register RAM read at ce_b
  (read-first, 3.7 ns out, was 6.5); the take sync's count expanded on the request facts; the ALU's operands
  with the RAM ports at the last select. No macro default, routine, ROM word or law moved; no port added to
  the queue or the bus unit (new useq → loader ports `w_disp` / `w_dispm` / `w_popany`, loader port
  `flush_w`). **Tools:** v35_tw.py casts named-type ports (the loader times alone); v35_timing.sh reports the
  2,000 worst endpoints through sta_tclsh (`NPATHS`, `STA_ONLY`, `DETAIL_TO`) and v35_spectrum.py gives the
  failing count per module and a histogram. **Measured (the overseer's rerun on main, identical to the
  hand-back):** the top 5,488 LUT4 / 414 ADD / 1,229 FF / 73 RAM_5K (fec2386 4,874 / 403 / 1,035 / 73),
  worst setup −5.058 ns (fec2386 −12.412), 496 of 2,000 endpoints failing (839), hold +0.307; the worst path
  `q_stored[1]` → the head byte's three select levels (4.3 ns) → the head byte's lookups → z → rel / rd → the
  room → fetch_req → the grant → the pins' enables, 17 levels; by module useq 354 failing (worst −3.70, tw_b),
  dut pins 62 (−5.06), bus 47 (−4.21), eu 30 (−2.35, the divider's init from the RAM data), loader 2, queue 1.
  Alone: useq +5.167 (6 levels), loader +2.778, queue +5.385 (6 levels), bus +6.160 (1 level), eu −1.242 (27
  levels, word → ALU → psw[6]; 29 endpoints within −1.3 .. 0). Placement moves the top's worst by about 1 ns
  between runs (−4.245 at the step before the last). **Verified on main:** 6,207 / 30,536 exact at both
  spacings, the per-family tables and the per-run first divergences identical to fec2386, chk silent (now
  also the ROM address, the derived bits, ds, df, z, flush, the room's facts and eq_r), write data 99,906,
  register vectors 107,859 with 0 bad, function vectors 19,752 with 0 bad, lint clean in five configurations
  and the macro alternatives, 46 fast tests, the nine offline modules with the four known failures.
  **Rulings for round 2 (the overseer's):** tick A by option (a), the head byte's decode moved before the
  queue's head select (per candidate source selected by the registered head select, or the bytes decoded as
  written and the attribute bits carried through the storage as opaque bits), the queue gaining ports for its
  own registered facts only; option (b) refused (the loader's outcomes would enter the bus unit's grant,
  against the arbiter direction of 2026-11-08, and triple it); option (c), a third tick, refused as the
  user's clock targets are two ticks at 64 MHz. Tick B by the operands read a tick earlier: the register RAM
  read at ce_a at the next word's address formed in tick B from the ROM's read data, the write landing at
  ce_a forwarded, the operands held in ce_b registers so the ALU and the divider's init start from flops; a
  register split inside the ALU refused as it would move when psw is visible. The gate adds margin: the
  top's worst setup ≥ +1.0 ns on the run, or ≥ 0 on three placement seeds.
- **MX5 round 2 landed (2026-11-11): tick B closed, tick A not yet; structure only.** Three more splits, each
  checked by `+v35_chk` every clock (the core README "MX5", "Round 2"): the head byte decoded before the
  queue's head select (the overseer's option (a), first form: the queue gains four outputs each driven by
  one of its own registers, `h_q0` / `h_lat` / `h_latv` / `h_odd`; the loader forms the head byte's lookups
  per candidate byte and selects by the registered facts that pick the head; test_v35_struct's Ports rule
  names the four; `v35_udec2(op, byte)` stays behind the select since replicating it per candidate costs 72
  RAM blocks); the opcode's decode as a register `d1r` loaded with op's next value; the operands a tick
  earlier (each register RAM port also reads at ce_a at the next word's selectors formed in tick B from the
  ROM's read data `word_nx` and the loader's `opc_nx` / `modrm_nx` / `fmt_nx`, the bank psw.RB as it stands,
  the same-ce_a write forwarded byte by byte, the operands captured in ce_b registers `x_b` / `y_b`; every
  other tick-B reader keeps the ce_b read). v35_timing.sh takes `SEED` (the place-and-route seed; the same
  sources and seed reproduce the slack exactly). **Measured (the overseer's rerun on main, identical to the
  hand-back):** the top 5,914 LUT4 / 414 ADD / 1,253 FF / 73 RAM_5K (round 1 5,488 / 414 / 1,229 / 73),
  worst setup −5.002 ns at seed 1 (−4.491 seed 2, −5.267 seed 3), 344 failing endpoints (seeds 2 / 3: 242 /
  77), hold +0.307. The worst path, 17 levels and 20.2 ns of data: the staging register `s_b` → the
  candidates' umodrm → z's compare → the candidate select → the ex / z selects → `rel` (10.8 ns) → the room's
  selects → `fetch_req` (4.0) → `g_fetch` (1.9) → the pins' clock enables (3.5, of which 2.0 routing on a
  fan-out of 52). Tick B in the top: one endpoint at −0.852 (`x_b` → the divider's init). Alone: useq +5.257,
  loader +3.253, queue +5.668, bus +6.160, eu +3.680 (was −1.242). **Verified on main:** 6,207 / 30,536 at
  both spacings, the tables and the per-run first divergences identical to 6281c60, chk silent (now also the
  head decode's select, d1r, x_b / y_b), write data 99,906, register vectors 107,859 with 0 bad, function
  vectors 19,752 with 0 bad, lint clean in five configurations and the macro alternatives, 47 fast tests,
  the nine offline modules with the four known failures. **Rulings for round 3 (the overseer's):** the second
  form of option (a) allowed (the byte-only facts decoded on the delivered word before storage and carried
  beside the byte as opaque bits; the generated table emitted as two functions); the stall outcome `ex`
  computed in tick B from the ce_a registers' next values and held in a ce_a register, since it reads the
  arrival event and registered facts but never the arriving datum's content (q_stall reads `ds2` and the
  byte counts), and likewise every loader fact that reads registered state only, leaving in tick A only the
  arriving word's own decode; the bus unit's grant expanded on its own `fetch_req` input; the pins' enables
  formed per group from duplicated logic; the room's 4.0 ns select tightened; the divider's init split as a
  state-machine step only if no clock moves. A third tick stays refused; if the gate is still not met the
  agent hands back the worst path's composition level by level for the user's measured choice.
- **MX5 round 3 landed (2026-11-11): tick A within 0.26 ns of closing on one seed of three; structure only.**
  Six more splits, each checked by `+v35_chk` every clock (the core README "MX5", "Round 3"): the bus unit's
  grant written once as a function of the request line and selected by it last (Shannon on its own input);
  the pins' registers loaded per group through kept selects with no inferred enable (the `g_fetch` fan-out
  of 50 is gone; the outputs are wires from those registers); the room's tests as compares of the loader's
  three inputs against kept thresholds formed from registers (occ <= c as rel >= E − (c + unc_a − stg)); the
  byte-only decode facts as a 6-bit tag formed on the delivered word and stored beside each byte through
  the storage and the latch (the queue gains `dlv_tag` in, `h_q0t` / `h_latt` out, opaque to it; the
  assembler emits v35_umodrm's two shares `v35_umdsp(mb)` and `v35_umimm(op, r01)`, the opcode's share a
  register beside s_b and op); the stall outcome {ex, ex_pop, st_oth, why} as a ce_a register `st_r` loaded
  with the stalls of the next values (new next-value outputs on the bus unit, the queue, the loader, the
  EU and v35_sfr's `prc_at`; the bus unit's inputs unchanged); the loader's fetch-path outcomes registered
  for the three cases (ex with z, ex without z, not ex) and selected in tick A by z1f last, z's cases a
  register `zc` so each candidate's z is a compare on its tag. test_v35_struct's Ports rule names the
  queue's `h_*` and `*_nx` outputs. Ruling 6 (the divider) not needed: +2.4 in the top. **Measured (the
  overseer's rerun on main, identical to the hand-back):** 6,413 LUT4 / 403 ADD / 1,345 FF / 73 RAM_5K
  (round 2 5,914 / 414 / 1,253 / 73); worst setup **+0.729 / +0.913 / −0.261 ns on seeds 1 / 2 / 3** (round
  2 −5.002 / −4.491 / −5.267), failing endpoints 0 / 0 / 2, hold +0.307; alone useq +5.026, loader +3.516,
  queue +5.309, bus +5.396, eu +4.090, regram +10.093. The worst path (seed 3, 15 LUT levels, 15.577 ns
  against 15.316): the bus unit's datum register (2.2 with its route) → the delivered byte's upage decode
  and tag compare (5 LUTs, 5.0) → the loader's select (1, 1.4) → the room's compares and selects (5, 4.6) →
  the grant's cofactor and the pin group's select (2, 2.4). The delivered byte is the one content-dependent
  input left in tick A; the rest is LUT4 fan-in. Equivalent sources map 1 to 4 ns apart (the synthesizer
  serialises wide decodes unless nodes are kept), more than the ~1.2 ns spread across seeds. **Verified on
  main:** 6,207 / 30,536 at both spacings, the tables and the per-run first divergences identical to
  6a629bb, chk silent (now also the expanded grant, the pins' selects, the room's compares, the tags, st_r
  and the registered outcomes), write data 99,906, register vectors 107,859 with 0 bad, function vectors
  19,752 with 0 bad, lint clean in five configurations and the macro alternatives, 48 fast tests, the nine
  offline modules with the four known failures. **Round 4 (the overseer's rulings):** the grant and the
  pins' selects expanded on fetch_req, q_low and q_word together (allowed, the bus unit's own inputs); the
  room re-measured in its per-release-count form with kept cofactors on the present sources; the delivered
  bytes' z as one kept function; an inequivalent datum copy made by decoding the pins before a register
  refused (no input reaches logic before a register); the gate as written, ≥ 0 on all three seeds meeting it.
  If a seed is still under 0 after that, the residual goes to the user as a measured choice.
- **MX5 round 4 (2026-11-11): the three candidates measured, none kept; the sources stand at 64076f3.** On
  three seeds each: the grant and the pins expanded on fetch_req, q_low and q_word together −2.286 / −1.108 /
  −1.204 (the worst path moved onto the grant's ce_b registers); the room per release count with kept
  cofactors and rel selecting last −5.146 / −4.961 / −5.874 (the synthesizer folded the kept thresholds back
  into each cofactor's arithmetic; rel takes the values 0..3 in the corpus, 3 in 8 runs, so the select is
  8-way); each delivered byte's z as one kept function of the byte and zc −1.928 / −1.035 / −0.769 (still 5
  LUTs after the datum register, the head select grown to two); the pairs worse. Candidates 2 + 3 replayed
  on F3 F4 F16 F33 F34 F38 (5,820 runs) identical with chk silent. The core README gains "Round 4" with the
  table. **MX5 closes here as a measured residual for the user:** the whole core at 15.625 ns routes at
  +0.729 / +0.913 / −0.261 ns on seeds 1 / 2 / 3 with one create_clock and no exception, every module alone
  ≥ +3.5 ns, hold +0.307; the one path under budget on seed 3 is the word arriving from the bus on its own
  delivery clock (its decode → the pop decision → the room → the request → the grant → the pin's D, 15 LUT
  levels, 15.577 against 15.316 ns), the remaining depth LUT4 fan-in rather than logic that moves under the
  two-tick structure. The choices are the user's: accept the design at the seeds that close (a placement
  choice, no constraint); lower the CPU clock's target below 32 MHz (a 17 ns tick closes every seed with
  about 1.5 ns of margin); or allow a third fabric tick per CPU clock (the arriving word's decode and the
  pop decision in a tick of their own), which the overseer refused on the user's directive.
- **MX4 landed (2026-11-11): the string forms (urom/str.uasm), the shared OPEN delay; 6,207 → 6,400 / 30,536.**
  The REP prefix is the 0F page's structure (the E word pops the string opcode with the prefix, the dispatch
  reads a second decode level on it, the prefix's condition in the first level's xc); the prefix's own word is
  the routine's first (CW into SIGMA), the zero test the second; CW lives in the register RAM and is
  decremented through the ALU each element; per element the read with its F, the write with its F (RAMEN),
  the index steps (AL_STEP, new: x ± the format's width by PSW.DIR, its step `stepk` a ce_a register loaded
  into y_b so the step is AL_ADD's adder), the count's test, the jump back; the REP compares post the next
  element's read before their tests (silicon's overrun); the exits E with wb at the model's done_t. A run of
  K + 1 act-free OPEN clocks is one word calling a shared ladder of K OPEN words that returns (every routine
  rewritten so: the same words on the same clocks), 720 words saved against the strings' 242: the ROM 1,922 →
  1,451 of 2,048. No loader or bus-unit change; tick A's request chain untouched. Mechanism note items 35–40.
  **Verified on main:** F24 0 → 4, F30 219 → 320, F31 0 → 46, F33 111 → 143, F39 187 → 197, every other family
  unchanged (the MX0 gate families 985), 0 lost, both spacings identical, chk silent, the per-run first
  divergences differing from cd7bcf3's only in those five families (1,005 runs), write data 99,906 → 105,444
  (every string write agreeing), register vectors 107,859 and function vectors 19,752 with 0 bad, the
  SingleStepTests string files added to the sample, lint clean, 48 fast tests, the nine modules with the four
  known failures. F24's ceiling is item 23 (every F24 / F31 frame ends with the M1 OUT imm8: the pO half at the
  M0 OUT, 286 pE runs behind the OUT's fetch hold). Not built: F29 (16 / 456, the dio / pi shapes unread), INS /
  EXT (597 words free), the REP fetch hold (the model's str_fetch=hold: a release act would be a new word bit),
  chold, split_floor, the single forms right after an I/O write (one clock, about 90 runs).
  **Timing (the overseer's rerun):** the hand-back's +0.375 / +0.622 / +0.278 came from a source differing from
  the diff only in a checker reference wire; the diff's text mapped 80 FF heavier in the EU and −0.838 on seed
  2. The checker's references moved under `ifndef SYNTHESIS` (the landed text): 6,552 LUT4 / 403 ADD / 1,345 FF /
  73 RAM_5K, worst setup **−0.669 / −0.958 / +0.001 / −0.568 / −0.250 ns on seeds 1 .. 5**, every worst path the
  delivery chain (the arriving byte's tag 7 levels → z1f → ld_rel → the room 6 levels → request → grant → a pin
  or drop_b), none MX4's; at 17 ns +0.962 / +0.721. Three equivalent texts span 1.6 ns on one seed: the core
  sits inside the placement spread at 15.625 ns. The longest leg is the arriving byte's tag decoded in tick A.
  **User rulings (2026-11-11):** (1) "You can expand the ROM. I never enforced a block ram budget, you did": the
  core's 80-RAM_5K budget (MX1 item 6, from the harness's 920 of the T120's 1,056) was the overseer's and is
  dropped; the device's total shared with the harness is the only bound, the harness's capture depth the user's
  to trim. (2) The arriving byte's decode as a block-RAM table at the data pins (the chip's PLAs are lookup
  tables): MX5 round 5, launched from this landing.
- **MX5 round 5 (2026-11-11): the arriving byte's tag as a block-RAM table at the data pins, measured, not
  kept; the sources stand at 74a17eb.** Built as briefed (two 256 × 6 tables in the bus unit addressed by
  `data_in` on the datum register's enable, output unregistered, inferred as EFX_RAM_5K, contents checked
  against bt_f, the loader and the queue reading the table's tag, the checker silent on the whole corpus;
  behaviour identical, 6,400 / 30,536, 0 per-run differences). Timing worse on every seed: **−1.699 / −1.229 /
  −1.052 / −1.978 / −1.199 ns** on seeds 1 .. 5 (the base −0.669 / −0.958 / +0.001 / −0.568 / −0.250), 75 RAM_5K.
  The cause is the device: a Trion RAM_5K's unregistered read is 3.666 ns clock-to-out against a flip-flop's
  0.366, and the tag's route at fan-out 10 to 16 adds 1.4 to 1.6 ns, so the tag stands at 5.0 to 5.2 ns and
  z1f (four levels on: the compare against zc and the head select) at 7.9 to 8.5 ns, later than the seven
  LUT levels it replaced (6.2 to 7.4). The overseer's estimate (the RAM's clock-to-out plus two levels,
  about +2 ns) was wrong on the RAM's clock-to-out. Also measured: with the tag free, seeds 1 and 4 would
  still fail on paths from `q_stored` (−0.496) and `q_hlv` (−0.227): the tick-A chain behind the tag is
  itself at the period. The core README gains "Round 5" with the table; the diff is kept at the scratchpad's
  v2/mx5e/. The residual returns to the user's choice (accept a closing seed, lower the target, a third tick).
- **The clock target lowered (2026-11-11, the user: "Lower it to 17ns").** The fabric period is 17 ns (58.8
  MHz), the CPU clock two ticks of it (29.4 MHz); two ticks, one create_clock, no exception, as before.
  `v35_timing.sh` defaults to 17. **Measured at 17 ns on 74a17eb's sources:** worst setup +0.962 / +0.721 /
  +0.433 / +0.465 / −0.057 ns on seeds 1 .. 5 (0 / 0 / 0 / 0 / 2 endpoints of 2,000 failing; seed 5's is the
  delivery chain again); alone useq +6.239, loader +4.478, queue +6.339, bus +7.165, eu +4.898, regram
  +11.951. Four seeds of five close; the margin is about half a nanosecond, inside the placement spread.
- **Full-function plan approved (2026-11-11).** docs/v35s-function-plan.md: timing set aside, every opcode,
  the interrupt controller and the peripherals built in stages F0 .. F5, each led by a socket measurement and
  gated on the RTL in simulation equalling the socket's program-visible behaviour. The user's rulings on the
  Software Guard table (pass-through), the RTL in simulation, refresh (still out) and STOP are recorded there.
  Launched: F1 (on-chip memory; owns the board), F0 (harness inputs and port capture; simulation and Efinity,
  no board) and F2's first part (INS / EXT; simulation only).
- **F0 landed (2026-11-11): the harness's scheduled inputs, output pins in the trace, serial stimulus, the dump
  routine.** fpga/v35s/v35s_stim.sv (one per lane): a program's OUT to event port FF12h starts host-loaded
  schedule entries (up to 32: delay, set or pulse N/S, NMI, INTP0-2, INT, DMARQ0/1, HLDRQ, RxD0/1, CTS0/1,
  start an RxD bit stream); /INTAK answered with a host-set vector on D7-D0 (gated by R//W, /REFRQ and the
  bank mode); changes on masked CPU-driven pins become trace records (flag bit 9; the mask 0 by default, so
  existing traces are unchanged); validation/v35s/dump.py and the `DUMPSTATE` line copy the eight banks and
  listed SFRs to the result region. Harness version 2; the runner accepts 1 or 2. No core source changed
  (tick A and tick B untouched; the core's timing as 74a17eb's). **Verified on main:** fpga/v35s/test.sh,
  test_v35s and test_stim (16 + 17), the core's fast tests; the agent's corpus gate 6,400 with 0 runs
  differing. The socket image built in the agent's worktree meets timing at 30 ns (+6.794 ns; 926 of 1,056
  RAM_5K, the base 920); **not yet loaded on the board** (F1 owns it). Open: silicon's INTAK cycle is
  unmeasured (F3 measures before relying on the answer path); pin recording and the RxD streams have not
  run against the part; the register-map text for docs/v35s-harness.md is at the scratchpad's v2/f0/.
- **F2a landed (2026-11-11): INS and EXT (urom/bf.uasm); 6,400 → 6,520 / 30,536.** Four routines on the 0F
  page (0F 31 / 33 / 39 / 3B), the field moving one bit per two-word loop through {tmpc, tmpb} (silicon's
  per-bit costs: EXT within a word 107 − 2o − 4w, crossing 61 + 2o; INS within a word a constant 94, crossing
  4 a spilled bit); six ALU operations (BFR BFL BFI BFM BFK BFU), tmpb's ALU write path, the counter loaded
  from SIGMA's low four bits (a port from the EU to the sequencer): all tick B, nothing on the delivery
  chain. The ROM 1,451 → 1,569. **Verified on main:** F32 128 → 158, F34 123 → 177, F39 197 → 233, every other
  family unchanged, 120 gained, 0 lost, both spacings identical, chk silent, write data 106,824 / 106,824 (every
  write in the corpus now agrees), the four SingleStepTests files passing in full (39,906 tests), vectors 0
  bad, lint clean, 48 fast tests. **FPGA at 17 ns:** worst setup +2.229 / +0.927 / +1.351 / +1.609 / +2.319 on
  seeds 1 .. 5 (the baseline +0.962 / +0.721 / +0.433 / +0.465 / −0.057), 6,805 LUT4 / 421 ADD / 1,395 FF / 73
  RAM_5K, useq alone +6.353, eu +5.587: no regression (the delivery chain mapped at 14 to 15 levels this
  time). The landing gate is three seeds from here (the user). Open: the bit-field forms behind item 23's OUT
  frame; the model's fetch-free setup rule (bf_read=fixed) and bf_imm_hold not built; the memory ModR/M
  forms unmeasured.
- **F1 landed (2026-11-11): on-chip memory, the SFR page as data, IDB, RAMEN, the PSW bits; merged on F2a.**
  Measured on the socket first (programs validation/v35s/programs/f1_*.s from validation/v35s/onchip.py, the
  receipts in validation/v35s/receipts/, the per-offset table in docs/v35s-sfr-socket.md). Against the data
  book: SCE0 / SCE1 reset to 80h (the book 00h); EMS, SRMS, STMS, TMMS1 / 2 reset to 44h and TMMS0 to C4h (the
  book undefined); several priority fields read a fixed 7; a 16-bit timer register ignores a byte write;
  write-only and some undocumented offsets read the last byte on the internal bus; bank 7's slots are the
  live registers both ways, a DS0 / SS / DS1 slot write acting on the next data access and a PS slot write
  on the fetch only after a branch; RAMEN = 0 sends E00-EFF to the bus, the SFRs staying internal; IDB moves
  RAM and SFRs together and is writable at FFFFF whatever it holds; RETI restores the bank; with BRKI = 0
  IN and OUT trap to vector 19 with the instruction's own PC pushed, SAHF's BRKI acting one instruction
  late and POP PSW's at once. **Built:** the bus unit's on-chip decision on the request register against
  IDB (an internal cycle, no pins, reads as well as stores), a third read copy of the register RAM and a
  registered SFR read into the bus unit's data register, internal RAM writes at the next ce_b, v35_sfr.sv
  as masked storage with the measured reset values for every documented SFR (function later: F3 / F4),
  FLAG linked to the PSW, RETI writing the whole PSW across the bank change. Not built: bus-residue reads,
  the PS slot steering the fetch, live peripheral state, the vector-19 trap (F2). **Verified on main (the
  merge's ROM regenerated, 1,572 words):** the six F1 programs equal on socket and RTL (the excluded bytes
  are residue reads and live or undefined state, each with a stated reason), the corpus 6,520 with 0 runs
  differing from F2a's at both spacings, chk silent, vectors 0 bad, lint clean, 48 fast tests. **FPGA at 17
  ns:** +1.415 / +1.201 / +1.595 on seeds 1 / 2 / 3, 7,857 LUT4 / 421 ADD / 1,759 FF / 75 RAM_5K (F2a 6,805 /
  421 / 1,395 / 73), alone useq +6.353, loader +4.361, queue +6.339, bus +7.542, eu +4.821, regram +11.738.
  **The harness version 2 image is on the board** (the version 1 image kept as v35s.hex.bin.v1-backup);
  the socket passes smoke, clocks and alu with the cycle counts unchanged (21 / 73 / 368).
- **F2b landed (2026-11-12): the remaining opcodes and traps (urom/trap.uasm); 6,520 → 6,541.** Measured on the
  socket first (validation/v35s/traps.py, traps_undef.py; programs f2_*.s; receipts f2-*). Against the data
  book: with BRKI = 0 every IN / OUT form, INM / OUTM and their REP forms trap to vector 19 before any cycle,
  pushing the instruction's own PC (its first prefix's), the handler entered with BRKI set, a return
  re-executing the instruction; the FPO escapes trap to vector 7 with no memory cycle, the escape's own PC
  pushed; CHKIND compares signed and pushes the next PC; PUSH SP by FF /6 pushes SP, by 54 SP − 2; 8F /1-7
  are POP, C6 / C7 /1-7 MOV imm; a REP prefix before a non-string opcode is ignored (REP IDIV does not negate
  the quotient, unlike the V20 suite); of 223 undefined 0F bytes 36 are NOPs of 2 to 4 bytes, 131 run away;
  silicon's TEST1 reg8,imm3 keeps AC and IDIV leaves it set (the RTL clears it: recorded, not changed).
  **Built:** the trap body with the vector named in the word (`vk`), the instruction's start offset
  `ins_ip` in the loader, the I/O trap as the dispatch's select on two register bits (the decode's io bit
  and BRKI), FPO, CHKIND (a signed compare), POLL on the P14 level, BTCLR over the SFR page, the register
  cells (pop_rm, push_rm, mov_rmi), REP before a non-string as a refetch; IN acc,DW's read a byte cycle
  (the 21 corpus gains). The word 93 → 95 bits, the ROM 1,572 → 1,662 words, 79 RAM_5K. **The timing gate
  sent the first version back:** it gave the undefined 0F NOPs their lengths by widening v35_upage, the
  arriving byte's tag in tick A, and seed 2 fell to −0.850 ns (the tag 6 levels where the base has 5);
  the second version restores the tag's functions byte for byte and refetches past the extra bytes in two
  three-word routines: **+1.276 / +1.243 / +1.231 on seeds 1 / 2 / 3** (the base +1.415 / +1.201 / +1.595),
  7,995 LUT4 / 423 ADD / 1,740 FF, alone useq +6.804, loader +4.584, queue +6.339, bus +7.542, eu +4.274,
  regram +11.738. **Verified on main:** the corpus 6,541 with 21 gained and 0 lost at both spacings, chk
  silent, vectors 0 bad (the I/O-trap vectors counted apart from the V20 reference), lint clean, 48 fast
  tests, the six F1 and six F2 program sets and the 101 built undefined cases equal to the socket. Not
  built: SAHF's per-form lateness on BRKI (9 measured cases, no machine explanation yet), REP + segment
  prefix + string, FE /2-6's byte-wide stack forms, D6, the 0F holes' internal sequences, the divide
  error's vector 0 (F3 measures its pushed PC).
- **F3 parts A and B landed (2026-11-12): the interrupt controller, vectored and bank-switch entry, the bank
  instructions, INT / INTAK, BRKN / BRKS; corpus 6,541 unchanged.** Measured on the socket first
  (validation/v35s/intr.py, banks.py; programs f3_*.s with their .stim.json schedules; receipts f3-*, two
  board sessions each, identical). **Against the data book (part A):** a store of IF = 1 with MK = 0 requests
  the interrupt for every IC register tried and a store of IF = 0 cancels it; the first register of a group
  sets the level for the whole group (EXIC1/2's PR reads 7); a second NMI nests inside the NMI handler; after
  HALT with IE = 1 or NMI the pushed PC is HALT + 1 or + 2 by the request's clock phase; the take follows a
  release by several clocks (EI + 4 INC AW, POP PSW or an IF / MK store + 6 INC + NOP, RETI + 1 INC); no
  single step after a prefix, EI, DI, MOV sreg or POP SS, one after a whole REP string, and a maskable request
  at the same end wins and that step is lost; the divide error is vector 0 with the next instruction's PC;
  the handler keeps MD. **(part B):** TSKSW loads the PC and the whole PSW from bank n's save slots and the
  bank that runs is that PSW's RB; MOVSPA copies SS:SP from the bank the current bank's PSW save names; the
  requesting member's own IC register decides vectored against bank switch while the bank is the group
  leader's PR; TB stays vectored; INT is taken before a pending maskable request of PR 1-7 and after PR 0,
  sets no ISPR bit, and releases HALT; the INTAK cycle is two /INTAK pulses (2 clocks low, 1 high, 2 low)
  with no other strobe; BRKS clears MD and the next interrupt (N/S high) restores it; BRKCS keeps BRKI and
  the flags. A development run entered secure mode by a RETI to a frame with MD 0; the next reset recovered
  the part completely, on which evidence BRKS was then run alone with N/S left high (N/S was never driven
  low: its sampling is built from the book, unmeasured). **Built:** v35_intc (in core/v35_sfr.sv: the 15 IF
  bits and ISPR, INTM edges, a four-stage registered priority resolution, FINT, HALT's wake, the member's
  ENCS, INT's place), the take at the dispatch in v35_top (`igo`: NMI, then the offer with IE now and at the
  last start, then the step with BRK now and at the last start; the new word bit `nb` on the E words of the
  prefixes, EI, DI and the segment loads: the word 96 bits, three banks full), urom/trap.uasm `intr`, FINT,
  `dve`, 0F 9A; urom/bank.uasm (the bank-switch entry, BRKCS, TSKSW, RETRBI, MOVSPA, MOVSPB, BRKN, BRKS) on
  new values of existing fields (register selects for the bank's save slots, six ALU ops, the bus request
  BQ_INTA: no fourth ROM bank); the acknowledge as an I/O read with the strobes held and the new `intak_n`
  pin; MD from the registered N/S at reset and on every entry, the secure translation a pass-through (the
  user's ruling). The ROM 1,662 → 1,731 words. **The timing gate sent part A back:** with the take's select
  in the loader's `dent` the seeds read +0.579 / +0.934 / −0.141; no term had joined the delivery chain, but
  the mapper shares the delivered byte's decode between the byte's tag and the dispatch's decode of the same
  byte and chose a form two levels deeper. The repair moves the select into the sequencer's DISP case
  (`nx_a` in tick A, `ig_b` beside `d1_b` in tick B), the loader's text the base's: part A alone +1.382 /
  +1.437 / +1.094. **Verified on main (A + B + the repair): +1.303 / +0.392 / +1.249 on seeds 1 / 2 / 3**
  (the base +1.276 / +1.243 / +1.231; seed 2's worst path is the delivery chain at the base's 14 levels:
  placement, not depth), 7,952 LUT4 / 423 ADD / 1,892 FF / 79 RAM_5K, alone useq +6.148, loader +4.608,
  queue +6.339, bus +8.572, eu +5.062, regram +11.738; the corpus 6,541 with 0 runs differing at both
  spacings, chk silent, write data 106,824 / 106,824, vectors 0 bad, lint clean, 48 fast tests; the program
  gates equal to the socket: intr 6, banks 5, onchip 6, traps 6, the 101 undefined cases. **Gate masks:**
  the stack's data (the handler's log holds every frame); the jitter tests' log entries except vector, depth,
  test, ISPR and IC bytes (the RTL always takes at HALT + 1); the current bank's CW slot during REP MOVBKW
  (silicon reads the count from before the string, the RTL the live count). **Not built:** macro service
  (part C: with F4, where its users are); a REP string interrupted between elements; the multi-clock latency
  after a release and HALT's + 2 take point (timing); whether ISPR holds INT off and INT against NMI and the
  step (unmeasured: the RTL takes INT on IE alone, below NMI); the memory forms of BRKCS, TSKSW, MOVSPB; a
  successful DIVU's flags (silicon F002, the RTL sets S P CY).
- **F4 part A landed (2026-11-12): the ports, the time base, TM0 / TM1 with TOUT; corpus 6,541 unchanged.**
  Measured on the socket first (validation/v35s/periph.py; programs f4_*.s; receipts f4-*, two sessions).
  **Against the data book:** interrupts taken in HALT land on a 16-clock grid (a 600-clock source gives
  intervals of 599 or 615), so exact periods are read from TOUT's pin records; a TMC0 store with TS0 = 1
  loads TM0 from MD0 and restarts the prescaler even while running, the first count-out 604 clocks after the
  store and then exactly (MD0 + 1) × 6 or × 128 apart; TOUT is a flop set at reset and at each start from
  TS0 = 0, toggled at each count-out, the pin ENT0 ? q ^ ALV : ~ALV; each TM1 count-out sets both TMIC1 and
  TMIC2; one-shot mode counts TM0 and MD0 down from their own values, each raising its request and clearing
  its own start bit; port bits read the pin in input mode and the latch in output mode, P1 bits 3:0 always
  the pins, a word store to P0 also writes PM0; the time base fires at 2^10, 2^13, 2^16 clocks (2^20 not
  timed: longer than a run); PT reads 00h at every PMT threshold on this board (PT0-7 held low: the
  comparator is unmeasurable here and not built). **Built:** the ports in v35_sfr (reads (PM & pin) | (~PM &
  latch), `pins_in` through two flops, the registered output vector `pins` with /INTAK on P13 and TOUT on
  P15), v35_timer (the counters, prescalers, a 4-clock start synchronisation, the TOUT flop, registered
  count-out strobes), v35_tbc (20 bits with the PRC tap), `pf_set` into v35_intc; the simulation harness
  gives the core the board's port levels and records the core's pins. **Gate:** the four program sets equal
  to both socket sessions (writes, result regions, settled pin sequences, stub intervals within the 16-clock
  grid, 14 / 14 TOUT intervals tick-exact); the corpus 6,541 with 0 runs differing at both spacings, chk
  silent, vectors 0 bad, lint clean, 48 fast tests; intr 6, banks 5, onchip 6, traps 6 and the 101 undefined
  cases still equal. **FPGA at 17 ns: +1.400 / +1.098 / +1.200 on seeds 1 / 2 / 3** (the base +1.303 / +0.392
  / +1.249), 8,509 LUT4 / 511 ADD / 2,110 FF / 79 RAM_5K; the modules alone unchanged. **Not built:**
  CLKOUT, the PT comparator, the one-shot start's 2-clock residue, whether q toggles with ENT0 = 0
  (unobservable).
- **F4 part B landed (2026-11-12): the two serial channels and macro service; corpus 6,541 unchanged.**
  Measured on the socket first (validation/v35s/serial.py; programs f4_stx, f4_srx, f4_ms, f4_sio, f4_sio2;
  two sessions, identical). **Against the data book:** macro service needs no IE and runs in HALT without
  releasing it (the CPU wakes only when the count ends); at MSC 0 or a character match the MS bit is cleared
  and IF set, the source's next take an ordinary vectored interrupt; MK 1 holds the service; the mode
  encodings the book leaves unreadable: MSM 000 a byte, 001 a word, 100 a byte with the character search (a
  match still counts MSC down), DIR 0 memory to SFR, the channel block +0 MSC, +1 SFRP, +2 SCHR, +4 MSP,
  +6 MSS; **the reserved MSM values (010, 011, 101, 110, 111) hang the program, and the MS registers reset
  to MSM 010**; a receive error sets both SRIC's and SEIC's IF; SCE's error flags are replaced at every
  character and not cleared by a read; RxB survives reset; in the I/O interface mode a TxB store with TxRDY
  starts 8 bits MSB first, SCK0 low then high in each bit, TxD holding its last bit until an SCC or BRG
  store (which of the two: not separated), reception started only by a store with TSK and RxE. As the book:
  a bit is BRG × 2^(n+1) clocks (five settings timed exactly from TxD edges), the frame and parity forms,
  STIC on the move to the shift register, /CTS holding the move, a start glitch under half a bit ignored,
  overrun keeping the newest byte. **Built:** v35_serial (two instances in core/v35_sfr.sv: the bit timer,
  transmitter, receiver, the I/O-mode clocks, TxD0/1, SCK0 and RSCK0 on the pin vector); macro service as a
  take in v35_top after NMI and before the maskable offer whatever IE is (also ending the HALT stall), the
  pick and the mode latch in v35_intc, the transfer a 59-word microcode routine (urom/ms.uasm) over the
  on-chip path, seven ALU ops and the segment select SG_TA; the word still 96 bits, the ROM 1,731 → 1,794
  words. **Gate:** serial 4 program sets equal to both socket sessions (writes, regions, pin sequences),
  periph 4, intr 6, banks 5, onchip 6, traps 6, the 101 undefined cases; the corpus 6,541 with 0 runs
  differing at both spacings, chk silent, vectors 0 bad, lint clean, 48 fast tests. **FPGA at 17 ns: +1.005
  / +0.733 / +0.493 on seeds 1 / 2 / 3** (the base +1.400 / +1.098 / +1.200): every seed passes and the worst
  paths keep the base's 14-15 levels, but each seed gave up 0.4-0.7 ns as the core grew to 9,165 LUT4 / 528
  ADD / 2,319 FF; the margin is watched at part C's landing. **Not built / open:** the reserved MSM hang
  (the RTL runs them as mode 000); macro-service priority among sources and against ISPR (unmeasured: the
  RTL uses the default order and ignores ISPR); which store marks TxD in I/O mode.
- **F4 part C (DMA) landed (2026-11-12): the two DMA channels; corpus 6,541 unchanged.** Measured on the
  socket first (validation/v35s/dma.py; program f4_dma gated, f4_dmx / f4_dmi / f4_dm2 / f4_dm3 measured
  only; two sessions, identical). **Against the data book:** the channel block is in internal RAM, not the
  SFR page: IDB:E00 + 8 × the channel, +0 SAR, +2 DAR, **+4 DARH, +5 SARH** (the book's figure has the two
  the other way round), +6 TC; the address is SARH × 1000h + SAR (an add); TDMA reads 0; EDMA is cleared
  when TC reaches 0; **DMARQ does not start the memory-to-memory modes (only TDMA) and TDMA does nothing in
  the I/O modes**; transfers are taken at instruction starts (the instruction after the TDMA store runs
  first; single step alternates one instruction, one transfer; burst runs back to back; a store clearing
  EDMA lets one more through); I/O to memory is one memory write at DAR with DMAAK low and the data not
  driven by the CPU, memory to I/O one read at SAR with DMAAK low, memory to memory a read and a write with
  no DMAAK; TC0 / TC1 are low for 2 clocks inside the last transfer's last cycle; a single transfer follows
  each DMARQ rising edge by 32-39 clocks (an edge before EDMA's store is not counted); demand release runs
  while DMARQ is high and resumes on the next high; a transfer in HALT does not release it, and after the
  last transfer one instruction runs before DIC's interrupt. **Built:** v35_dma (core/v35_sfr.sv: DMAM's
  MD / W / EDMA, the software start, the pending edge, the demand flag, the request with channel 0 first,
  EDMA's clear and DIC's IF at TC 0); the take in v35_top after NMI and the macro service and before the
  maskable offer (`dm_arm` sampled at each start; `rs_hlt` so a take out of HALT resumes the HALT as no
  boundary); the transfer a 49-word microcode routine (urom/xfer_dma.uasm `dmv`, entered through the
  bank-switch entry's `dm_q`) over the on-chip path, the macro service's ALU ops reading the DMA
  descriptor under `tk_dm` and one new op DMS (the address step; the 6-bit ALU op field is now full); the
  DMA cycle in v35_bus (`req_dk` from the EU, registered at the grant as the INTAK cycle's is) driving
  DMAAK0/1 and TC0/1 on P21 / P24 / P22 / P25 by PMC2. The word still 96 bits, the ROM 1,794 → 1,848 words.
  **Gate:** dma 1 program set (15 tests) equal to both socket sessions (writes with the source-page reads
  in sequence, regions with the undriven I/O-to-memory data masked, settled pin sequences), serial 4,
  periph 4, intr 6, banks 5, onchip 6, traps 6, the 101 undefined cases; the corpus 6,541 with 0 runs
  differing at both spacings, write data 106,824 / 106,824, chk silent, vectors 0 bad, lint clean, 48 fast
  tests. **FPGA at 17 ns: +0.677 / +0.701 / +0.590 on seeds 1 / 2 / 3** (the base +1.005 / +0.733 /
  +0.493): every seed passes, 9,223 LUT4 / 578 ADD / 2,399 FF / 79 RAM_5K; **the worst paths are now 16
  levels (the base 14-15), from the bus unit's done data to the grant length and the address mux**; the
  modules alone: useq +6.238, loader +4.180, queue +6.339, bus +7.991 (was +8.572), eu +5.331, regram
  +11.738. The margin is 0.6-0.7 ns on every seed; the next landing that deepens the grant path gets a
  timing pass rather than a waiver. **Not built / open:** channel priority when both request at once
  (unmeasured: channel 0 first), the demand mode's transfer counts by pulse length (measured only), TC
  with 0 or 1 programmed waits (unmeasured); bus hold, READY and STOP / STBC were measured in this part
  (receipts f4-f4_hx-socket.json, f4-f4_rdy-socket.json) and are built in part D.
- **F4 part D landed (2026-11-12): bus hold, READY, STBC / STOP, and the vectored entry in silicon's order;
  corpus 6,541 unchanged. F4 is complete.** Measured on the socket first (validation/v35s/dma.py; programs
  f4_hold, f4_rdy, f4_stop and its reset re-run f4_stop_r; two sessions each, equal to the tick).
  **Against the data book / the earlier reading:** **a WTC field of 3 is 2 waits** (5-clock cycles, as
  field 2; the core had 3 waits, so every program at the reset WTC ran one clock a cycle long); with PMC1
  bit 7 a read or an I/O cycle is extended by READY low, a memory write is not (its strobe falls after
  READY's sample; the harness cannot hold READY early on a write, so that case is built as the mechanism
  implies, not measured); HLDRQ needs PMC2 bit 7, /HLDAK falls 1.5 clocks after the cycle in flight ends
  and rises 1.5 clocks before the next, a burst DMA waits under hold as the CPU does, and hold is granted
  in HALT; **STBC's SBF (bit 0) is set by a store with bit 0 = 1, never cleared by a store, kept through
  reset, 0 at power-on, and STOP does not set it** (part C's "01h after a STOP" came from earlier stores in
  the same program); STOP is quiet until NMI, the first cycle 2^19 + 38 clocks after NMI's edge with IE 1
  or 0, and an unmasked INTP0 pulse during STOP neither releases it nor sets its IF. **Built:** v35_bus
  `hold` (a ce_a register stopping every grant but a pair's second half) and /HLDAK at the pins' edge;
  the READY cycle (a grant bit registered beside the INTAK and DMA ones, READY sampled at the pins' edge,
  the cycle's first wait held while low); v35_sfr: HLDRQ through two CPU-clock flops by PMC2 bit 7, P26
  /HLDAK by PMC2 bit 6, `sbf` with no reset; STOP as urom/xfer_stop.uasm (a halt word marked by the
  counter field's last free value), v35_top's `stp` and a 19-bit release counter running while NMI is
  pending (its own counter: the time base's behaviour in STOP is unmeasured), v35_intc's `frz` holding
  the INTP samplers. **The vectored hardware entry** (urom/xfer_vt.uasm `iv_x`): the gate's timer program
  showed silicon reads the vector offset, pushes PSW, reads the vector segment, pushes PS, pushes PC; the
  corpus's BRK 3 has the same order and the RTL's BRK routine already had it, so the hardware entry is
  that routine's words with the vector address from the take and the interrupted PC; no clock added, BRK
  and the trap entries untouched. ROM 1,848 → 1,871 words; the word still 96 bits. **A test flaw found
  and fixed:** periph's tm_hold saved a PSW whose parity bit was a timer count over a timed loop (equal
  before only by coincidence); the program now ends on a count-independent flag setting and was
  re-measured (two sessions). **Gate:** dma 5 program sets equal to both socket sessions with their
  timing checks (f4_rdy's 218 cycle lengths within a tick; /HLDAK's edges; the STOP release 524,671
  against 524,701 clocks, tolerance 64), serial 4, periph 4, intr 6, banks 5, onchip 6, traps 6, the 101
  undefined cases; the corpus 6,541 with 0 runs differing at both spacings, write data 106,824 / 106,824,
  chk silent, vectors 0 bad, lint clean, 48 fast tests. **FPGA at 17 ns: +0.478 / +0.677 / +1.382 on
  seeds 1 / 2 / 3** (the base +0.677 / +0.701 / +0.590): every seed passes, the worst paths 16 levels as
  the base (done data to the address mux / the sequencer), 9,366 LUT4 / 596 ADD / 2,421 FF / 79 RAM_5K;
  modules alone: useq +6.238, loader +4.689, queue +6.339, bus +7.953, eu +5.331, regram +11.738.
  **Not built / open (timing, recorded):** the back-to-back interrupt interval is 193 clocks against
  silicon's 204 (within the gate's 16: the lead-in to the entry 12 against 20, the entry 50 against 48,
  about 8 on the RETI side where the RTL had prefetched); after a STOP release the RTL fetches one word
  before the entry (silicon none); under hold during POP's reads silicon keeps the bus idle about 6
  clocks longer than the 1.5-clock rule (h_w); at 2 waits a taken DBNZ fetches one more word on the RTL
  (40 clocks an iteration against 37) and instructions storing to the SFR page run about 4 clocks short;
  WTC's per-block memory fields (the bus unit reads field 0 for all memory); SBF on the FPGA clears at
  configuration, not at the socket's power.
- **F5 first batch landed (2026-11-12): the fuzz, and five flag / function rules it found; corpus 6,541
  unchanged. The fuzz's main sets do not pass yet.** validation/v35s/fuzz.py (run, gate, triage,
  shrink, cover), fuzz_gen.py (a seeded generator keeping a model of the registers, segments, SP, the
  eight banks and the stack, so a program stays self-contained and shrinks by deleting items),
  fuzz_layers.py (sets f5a 300 plain programs, f5b 150 with bank switching, f5c 160 with INTP0 / TM0 /
  NMI / single step, f5d 100 with random stores to the writable SFRs), fuzz_flags.py (f5x: a flag survey
  of register forms; f5r: directed regressions). 105 instruction forms, 85,858 fuzzed executions, each
  set in two socket sessions. **Measured on silicon and built** (the V20 suite's rules kept behind
  funcref.V20_UNDEF): AND / OR / XOR / TEST, the shifts, TEST1 and CVTBD keep AC (the core cleared it);
  signed MUL multiplies magnitudes and leaves S Z AC P when the signs agree, else the flags of 0 - the
  product's low half; a DIVU / DIV that completes leaves S Z P of the remainder's magnitude, AC the
  pre-check's nibble borrow, CY = V = 0; EXT / INS leave the PSW; **CVTDB multiplies by its immediate
  byte** (the core multiplied by 10). **Gate:** f5x 26 programs (2,860 cases) equal on both socket
  sessions and the RTL; every earlier program gate equal (dma 5 on both sessions, serial 4, periph 4,
  intr 6, banks 5, onchip 6, traps 6, 101 undefined cases); corpus 6,541 with 0 runs differing at both
  spacings, chk silent, vectors 0 bad, lint clean, 48 fast tests. **FPGA at 17 ns: +0.713 / +1.328 /
  +1.718 on seeds 1 / 2 / 3** (the base +0.478 / +0.677 / +1.382), 9,354 LUT4 / 596 ADD / 2,408 FF / 79
  RAM_5K, worst paths 10-15 levels. **Open (batch 2): f5a-f5d are 0 equal of 710 against the RTL.** Known
  classes: PREPARE with a level >= 1 is not built (about 58 programs); a word at an odd I/O port runs two
  byte cycles on silicon; INS with AL / AH as the offset register reads AW before the step; XCH memory,
  reg where the address uses that register; one program runs away on the RTL only; the flags of ADD4S /
  SUB4S / CMP4S and of a signed DIV that overflows; two f5d programs loop on silicon (unattributed); the
  dumps include SFRs with undefined reset values (TMMS0 bit 7 differs between sessions), so every set is
  re-taken once the prologue stores them. Measured, not built: EXT / INS with an offset or width byte
  above 15 can stop the CPU inside the instruction (receipt f5-extins-range-socket.json).
- **F5 second batch landed (2026-11-13): 660 of 710 fuzz programs equal on both socket sessions and the
  RTL (the first batch: 0); corpus 6,541 unchanged.** **The reference made clean and re-taken** (f5a 300,
  f5b 150, f5c 160, f5d 100, f5r 12, f5x 32: socket against socket-2 equal on all 748, none retried;
  receipts f5-<set>-socket(-2).json.gz): the prologue stores every SFR the book leaves undefined at reset
  (the fuzz reads them as operands, so a program's first run saw the previous program's values: the
  cause of the unstable capture windows); the two f5d programs that looped on silicon were a generator
  flaw (an excluded register still used in an address moved a store onto the FPO vector); a trace
  longer than one capture window is re-run until every window is the same execution, and the gate
  refuses one that never stitches; the interrupt handler's count store is dropped from the compared
  write order (it lands where the take does, and the RTL's clocks are not silicon's). **Measured on
  silicon and built** (funcref carries each; the V20 suite's rules behind funcref.V20_UNDEF): PREPARE
  uses its level byte whole (0-255; BP pushed, the L - 1 display words at SS:[old BP - 2], ... copied,
  then the frame pointer; urom/zz_late.uasm); a signed DIV whose quotient is out of range traps after
  the steps with the completing divide's flags; ADD4S / SUB4S / CMP4S leave the last byte step's flags
  (CY its carry, Z every byte zero, S and P of the last byte, AC its low digit's adjust, V the adjust's
  overflow); a word at an odd I/O port is two byte cycles (the bus pair now carries I/O); an I/O write's
  datum is held from its post (a core bug: the next instruction's PUSH reloaded it); a segment prefix
  reaches the opcode through BUSLOCK and through a REP before a non-string opcode, a trap after them
  pushes the first prefix's offset, and no step or interrupt boundary falls between such a REP and its
  opcode; a memory shift or rotate by a zero count reads and does not write; INS reads AW before
  stepping an AL / AH offset register, EXT writes the offset register before AW, ROL4 / ROR4 write AL
  before the operand. tools: validation/v35s/fuzz_hist.py (the first-difference histogram: 687 programs
  differing at the base, 50 now). **Gate:** f5d 100 / 100, f5a 294 / 300, f5b 147 / 150, f5c 119 / 160,
  f5x 32, f5r 12 equal on both sessions; every earlier program gate equal; corpus 6,541 with 0 runs
  differing at both spacings, write data 106,824 / 106,824, chk silent, vectors 0 bad, lint clean, 48
  fast tests. **FPGA at 17 ns: +0.216 / +0.773 / +0.605 on seeds 1 / 2 / 3** (the base +0.713 / +1.328 /
  +1.718; all pass, margin down about 0.5-1.1 ns), 9,425 LUT4 / 600 ADD / 2,444 FF / 79 RAM_5K, seed 1's
  worst path 15 levels ending at the bus unit's address register. **Open (batch 3, 50 programs):** an
  RTL hang after a redirect to an odd address (24 programs, also on the earlier RTL: the E word waits on
  the queue's refill forever); the single step over POP PSW / FINT / MOV PSW,AH (13); NMI programs not
  yet attributed (9); singles (an FPO1 trap's pushed PC, SET1 DIR / TEST1 / MUL imm flags, one OUT
  datum).
- **F5 third batch landed (2026-11-13): 709 of 710 fuzz programs equal on both socket sessions and the
  RTL (f5a 299 / 300, f5b 150, f5c 160, f5d 100).** **The hang (24 programs, an RTL bug since the
  reservation was built):** the EU's reservation (no fetch starts while a routine's data cycle is
  announced) was released only by a bus acknowledge; a routine ending without the cycle it announced
  (the zero-count memory shift) or an interrupt taken in place of the popped opcode's routine left it
  standing, and after a redirect to an odd address (queue at 5 bytes) or the bank-switch take's flush
  (queue empty) the E word waited for a fetch the reservation refused. The reservation register now
  also clears on a routine's E word and on the take's dispatch (v35_eu resv_r; no term added to the
  grant). **Measured on silicon and built:** no single step is taken at the start after POP PSW, RETI
  or FINT (intr.py f5_step / f5_step2; the data book: nor a maskable interrupt after RETI / POP PSW):
  seg=NBI on those E words drops the interrupt and step arms for one start (v35_top; NMI, macro
  service and DMA not held); a segment prefix after a REP before a non-string opcode reaches the
  opcode with the REP's offset the instruction's start (rep_nx's cells). **RTL bug fixed:** TEST1
  reg,imm read its bit index after E from a byte register the next short transfer's pop had reloaded
  (now from tmpb). **Test flaw fixed:** the NMI frame's exclusion counted 3 records where an odd SP
  makes 6. **Gate:** as above; f5x 34, f5r 18 equal on both sessions; intr 8 sets and every earlier
  program gate equal; corpus 6,541 with 0 runs differing at both spacings, write data 106,824 /
  106,824, chk silent, vectors 0 bad, lint clean, 48 fast tests. **FPGA at 17 ns: +1.001 / +0.957 /
  +1.565 on seeds 1 / 2 / 3** (the base +0.216 / +0.773 / +0.605), 9,631 LUT4 / 600 ADD / 2,468 FF / 79
  RAM_5K, worst paths 15 levels. **Open:** f5a_061: an OUT followed by CVTBD / CVTDB drives the
  follower's immediate as its datum on silicon (f5o, 220 cases on two sessions: measured, not built);
  FINT's hold of the maskable interrupt is built by analogy with its measured hold of the step (the
  controller's latency hid it in f5_stepi); REP + segment prefix + a string instruction runs the string
  once on the RTL; f5c_026 takes its timer interrupt twice on all three sides (not traced); batch 3's
  three new regressions were not shown to fail on the earlier RTL. Batch 4: a second generation of
  fuzz sets with fresh seeds (all 710 programs so far are the ones the fixes were found on).
- **F5 fourth batch landed (2026-11-13): a second generation of fuzz sets with fresh seeds (f5e-h, 710
  programs) was 707 equal on its first pass, before any fix.** The three that differed are the open
  OUT + CVTBD / CVTDB datum class. **Measured on silicon and built:** REP followed by segment prefixes
  or BUSLOCK and then a string instruction repeats the string under the last override (zz_late.uasm
  rep_sx / rep_lk; an E word with ea=REP hands the popped opcode to the string routine: v35_useq
  w_erep, v35_loader erep_b; the EU reads the override from the prefix byte); a word at offset FFFFh
  has its second byte at the linear address + 1, past the segment's end, not at the segment's offset
  0 (v35_eu lin2; found by the new gap set f5i, 13 → 200 equal; funcref and rtl_vectors follow the
  socket, the V20 suite's wrap cases listed as the category SEG_WRAP). **Measured, confirming what was
  built by analogy:** FINT holds the maskable interrupt for one start (intr.py f5_fint2). **Measured,
  not built:** an interrupt inside a REP string is taken after an element, pushes the first prefix's
  offset and the string resumes (f5_repint; the RTL takes it after the string). **Traced:** f5c_026's
  repeated timer take is the fuzz writing MD0 = 0. Batch 3's six regressions (f5r, now 22) fail on the
  earlier RTL. **Gate:** f5a 299 / 300, f5b 150, f5c 160, f5d 100, f5e 299 / 300, f5f 148 / 150, f5g
  160, f5h 100, f5i 200, f5x 34, f5r 22 equal on both socket sessions and the RTL (1,616 of 1,620
  fuzz programs; the four are the one class); intr 8 sets and every earlier program gate equal; corpus
  6,541 with 0 runs differing at both spacings, write data 106,824 / 106,824, chk silent, vectors 0
  bad, lint clean, 48 fast tests. **FPGA at 17 ns: +0.884 / +0.740 / +1.084 on seeds 1 / 2 / 3** (the
  base +1.001 / +0.957 / +1.565), 9,623 LUT4 / 618 ADD / 2,446 FF / 79 RAM_5K. **Open:** the OUT +
  CVTBD / CVTDB datum (f5a_061, f5e_026, f5f_043, f5f_108: timing-derived, not built); the interrupt
  inside a REP string; fuzz coverage of SP through 0000h, combined interrupt scenarios, POLL / HALT
  and the register forms of 62 / 8D / C4 / C5 (batch 5).
- **F5 fifth batch landed (2026-11-13): an interrupt is taken inside a REP string; a third generation
  of fuzz sets with fresh seeds (f5j-n, 1,000 programs) was 993 equal on its first pass.** The seven
  are the OUT + CVTBD / CVTDB datum class. **Measured on silicon (intr.py f5_si_ops / edge / long /
  inv / async and f5_repint, both sessions) and built:** NMI and the maskable interrupt are taken at
  the end of an element after which the string goes on (its bus cycles, index steps, CW's decrement
  and the exit tests done); an element that ends the string exits first and the take is at the next
  start; the PC pushed is the first prefix's offset, and RETI re-enters the whole prefixed string with
  CW / IX / IY as they stand; the single step is not taken inside a string (one trap after its last
  element); ADD4S / SUB4S / CMP4S, long shifts, PREPARE and DIV are not interruptible. Built as a take
  point in the microcode: a new sequencing value SQ_TKI (`tki=L`, no microword bit added; v35_useq
  `sgo`, v35_top `sgo = g_n || g_i`), one TKI word per REP loop in urom/str.uasm after its exit tests,
  costing no clock when nothing is pending; the grant and delivery path untouched; the ROM 1,885 →
  1,892 words. **RTL bug fixed:** REP BUSLOCK left `pist` stale (v35_eu). f5_si_async is measured
  only (which element a scheduled request lands on is decided by the clocks). **Fuzz coverage added**
  (fuzz_gap2.py): SP through 0000h / FFFFh, combined interrupt scenarios (nesting, NMI inside a
  handler, step + INT on one boundary, HALT, a take inside a prefixed REP string), POLL, HALT, the
  illegal register forms of 62 / 8D / C4 / C5 / FE / FF; MD0 / MD1 / TMC kept out of the timer
  scenario's operands; four generator flaws fixed for the new sets. **Gate:** 2,609 of 2,620 fuzz
  programs (f5a-n) equal on both socket sessions and the RTL, f5x 34 and f5r 22 equal; intr 13 sets
  (11 on the second session) and every earlier program gate equal; corpus 6,541 with 0 runs differing
  at both spacings, write data 106,824 / 106,824, chk silent, vectors 0 bad, lint clean, 48 fast
  tests. **FPGA at 17 ns: +1.092 / +0.963 / +1.072 on seeds 1 / 2 / 3** (the base +0.884 / +0.740 /
  +1.084), 9,521 LUT4 / 618 ADD / 2,431 FF / 79 RAM_5K. **Deferred by the user's ruling (2026-11-13):
  the OUT + CVTBD / CVTDB datum is not built until the timing work resumes** (the 11 differing
  programs: f5a_061, f5e_026, f5f_043, f5f_108, f5j_062, f5j_134, f5l_140, f5l_145, f5n_088, f5n_138,
  f5n_146). **Open (batch 6):** macro service and DMA arriving during a long string (the RTL serves
  them after it; not measured); NMI inside a single-stepped string; D6 not measured; BRKS and STOP not
  in the fuzz; fuzz_hist stops with an exception on f5j-n.
- **F5 sixth and seventh batches and a timing repair landed together (2026-11-14).** **Measured on
  silicon and built (batch 6):** a macro service and a DMA request are served between a REP string's
  elements (dma.py f5_sdma / f5_sms / f5_sasync, gated in function by f5_sms_inv / f5_sdma_inv): taken
  at the string's take point in the dispatch's order (v35_top sgo, take_m, take_d, dm_arm at a TKI
  word; no microcode change); NMI and the maskable interrupt in a single-stepped string measured
  (f5_si_step / f5_si_nstep), the RTL already equal. **Batch 7:** D6 measured as CLR1 r/m8 with the bit
  number in the ModR/M reg field (d6.py f5_d6 / f5_d6b; the memory form always writes the byte back,
  flags untouched) and built: D6's first-level cell a ModR/M routine and a second-level case, made
  through the generator with every other entry byte-identical and the arriving-byte tag functions
  unchanged; routines d6clr_m / d6clr_r in zz_late.uasm, no new microword bit, the ROM 1,892 → 1,910
  words; its clocks are not measured (function only). **Timing repair:** batch 6 alone failed seed 2 at
  17 ns (+0.539 / -0.230 / +0.763) on the standing thin path, the bus datum register → the loader's
  tags → the bytes released → the queue's room → the grant → the bus address register (16 levels);
  batch 6's terms are not on it (27 more LUT4 moved the placement). The delivered word's tags are now a
  register loaded with the datum register's own enable, D and initial value (v35_loader tg_lo / tg_hi
  from v35_bus done_nx / done_ld; a chk term compares them with the decode of the datum on every
  clock): the decode leaves tick A; no function or clock changed. **Gate (the three together):** corpus
  6,541 with 0 runs differing at both spacings, write data 106,824 / 106,824, chk silent, vectors 0
  bad (D6's 256 added), lint clean, 48 fast tests; dma 7, serial 4, periph 4, intr 15, banks 5, onchip
  6, traps 6, d6 2 sets equal, undefined opcodes 101 / 101; fuzz 3,057 of 3,070 programs equal on both
  socket sessions and the RTL (a fourth generation f5p-u 300 / 300, 299 on its first pass with the one
  a generator flaw; f5v with D6 in the pool 148 / 150); the 13 differing are the deferred OUT + CVTBD
  / CVTDB class. **FPGA at 17 ns: +1.061 / +1.600 / +1.849 on seeds 1 / 2 / 3** (the base +1.092 /
  +0.963 / +1.072), 9,570 LUT4 / 618 ADD / 2,442 FF / 81 RAM_5K. **Measured, not built:** a DMA
  transfer addressed at the internal RAM page is an external bus cycle on silicon (f5_sdma_iram; needs
  a request bit between the EU's request and the grant's on-chip decode); the exact element a macro
  service / DMA / asynchronous interrupt lands on (clock-decided). **Not in the fuzz:** BRKS, STOP
  (its standby flag survives reset into later programs). fuzz_hist's exception on f5j-n fixed.
- **The macro-service and DMA priorities measured on the socket and built (2026-11-14; the user's
  request; validation/v35s/prio.py, 13 programs equal on two socket sessions).** **Macro service among
  sources:** silicon settles macro-service and vectored requests in one priority decision: within a
  group the first requesting member in its fixed order whatever its kind; between groups the level (the
  PR of the group's first register), then the default order; with IE 1 a vectored request beats a lower
  macro service (the RTL had a fixed order, PR ignored, macro service always first). **Against ISPR, IE
  and NMI:** ISPR holds a macro service as it holds a vectored request (served inside a lower level's
  handler even with IE 0, waiting at an equal or higher level for FINT); with IE 0 a group whose first
  requesting member is vectored holds its later members' macro services; NMI's handler holds none, and
  NMI goes first when both are pending; the count's end is a vectored request at the source's level
  (confirmed). Built in v35_intc (one winner key for both kinds; the F4b ms_pick chain removed).
  **DMA:** channel 0 first when both ask, in every mode tried (confirmed); a burst is never broken (the
  RTL let channel 0 in); an overtaken single-step channel resumes at once after channel 0's last
  transfer; built in v35_dma (arm / act / gate registers). **Across kinds at one boundary** (an
  instruction start and a REP string's take point alike): DMA, NMI, macro service, the maskable
  interrupt, the single step (the RTL had DMA third); built in v35_top's take terms. **TC:** low for 2
  clocks from mid-B2 at 0, 1 and 2 waits alike (the RTL: none at 0, one clock at 1); built (v35_bus
  dkt). **Gate:** prio's four gated sets (f4p_ms, f4p_hb, f4p_hr, f4p_dma) equal on both sessions and
  the RTL, every earlier program and fuzz gate as before (fuzz 3,057 of 3,070), corpus 6,541 with 0
  runs differing at both spacings, write data 106,824 / 106,824, chk silent, vectors 0 bad, lint clean,
  48 fast tests. **FPGA at 17 ns: +1.513 / +0.980 / +1.709 on seeds 1 / 2 / 3** (the base +1.061 /
  +1.600 / +1.849), 9,521 LUT4 / 618 ADD / 2,458 FF / 81 RAM_5K. **Measured, not built:** the reserved
  macro-service modes 010 and 111 stop the CPU (not even NMI is taken; only reset recovers; the RTL
  runs them as mode 000); the controller's requests arriving late after a DMA transfer (clock-decided:
  f4p_x1-x7 measured only). **Found, open (the next batch):** the RTL loses an NMI arriving together
  with a macro service inside a chain of segment prefixes (f4p_x3; the same before this batch); silicon
  takes NMI between prefixes (the RTL holds every take to the instruction after the chain).

- **2026-11-14, requests among prefixes (F4q), measured on the socket first
  (validation/v35s/pfxtake.py, 11 programs, two sessions identical).** **The lost NMI (f4p_x3):** the
  NMI was taken and its frame pushed, but its handler never ran: a take at a segment-prefixed
  instruction's start ran its routine with the prefix's format still loaded, so the loader kept
  ins_ip at the interrupted prefix through the routine's E word, and a macro service (or DMA, or a
  second NMI) at the handler's first instruction resumed at / pushed that stale start. Fixed in the
  loader: ins_ip is kept only through a prefix's own E word (`epfx_b`, a tick-B register of
  epop && word.pfx). **Silicon among prefixes:** nothing is taken between prefixes (NMI, the maskable
  interrupt, macro service, a DMA single transfer, the single step; chains of 8 and 320; segment
  overrides, REP / REPC before a non-string opcode, BUSLOCK, mixes): each after the prefixed
  instruction or at a string's first take point, as the RTL's hold already did (the previous entry's
  "silicon takes NMI between prefixes" was a misreading). **The instruction start silicon pushes or
  resumes at is the opcode's offset less (the count of its prefix bytes modulo 4)**, every prefix kind
  counting (swept 1-9, 15-17, 31-33, 63-65, 127-129, 255-257, 320): 1-3 prefixes the first prefix
  (the RTL before), 4 the opcode itself, 5 the fifth prefix. It holds for NMI and the maskable
  interrupt at a REP string's take point, where a macro service or DMA transfer resumes the string,
  and for the FPO trap; the returned-to instruction runs with only the bytes from there on (n mod 4 =
  1: the override lost, later elements from DS0; n mod 4 = 0: REP lost, one more element, CW left at
  3Fh). Built: v35_eu `sist` (a ce_a register, ip - 1 - has_modrm - k, k the two-bit distance from
  the first prefix) read by SR_PC's ist where `pist` was; pist narrowed to 2 bits; no microcode
  changed. **Gate:** pfxtake's 10 gated sets (f4q_l, f4q_rep1-3, f4q_mix, f4q_ns, f4q_nmi, f4q_step,
  f4q_fpo, f4q_svc) equal on both sessions and the RTL; f4q_nmis (an NMI landing inside a string:
  clock-decided element) measured only; every earlier program and fuzz gate as before (fuzz 3,057 of
  3,070), corpus 6,541 with 0 runs differing at both spacings, write data 106,824 / 106,824, chk
  silent, vectors 0 bad, lint clean, 48 fast tests. **FPGA at 17 ns: +1.648 / +1.374 / +1.968 on
  seeds 1 / 2 / 3** (the base +1.513 / +0.980 / +1.709), 9,542 LUT4 / 634 ADD / 2,467 FF / 81 RAM_5K.
  **Open:** the I/O trap with 4 or more prefixes not measured (the same rule built for it).
- **2026-11-14, the V20 SingleStepTests suite run again and made a standing gate; the interface plan
  approved.** `sst --rtl` had not run since the bank and trap work: 32,144 RTL fails and 324
  reference fails, **none of them the RTL's**. The bench held the N/S pin low (now the socket's rest
  levels, 1E1Fh) and missed the second half of a request pair; the bench preloaded one register bank
  where RETI switches banks (all eight preloaded now); funcref lagged silicon on RETI (the whole PSW
  loaded, the bank switched) and on PUSH SP by FF /6 (SP pushed, V20's SP - 2 a listed class); the
  ROL4 class's AL write order. No RTL changed. After: **pass 2,502,497, 0 RTL fail, 0 reference
  fail**, every difference in a named class (V20's fixed PSW bits 27,428, ROL4 / ROR4 AL 18,692,
  PUSH SP FF /6 308, undefined flags 397,403, PREPARE level 1,941, trap 24,387, trap_nop FF /7,
  REP before a non-string opcode 1,340, on-chip page 887, unlisted 82, odd word across the segment
  end 35). `sst --rtl` and `sst --all` are lines of the landing gate from here. Every other gate as
  the previous entry. **Direction (user, 2026-11-14): timing accuracy and simplicity.** The modules
  were evaluated for coupling that silicon would not have (149 signals crossing six modules, v35_bus
  with 60 outputs, a 12-term sequencer stall of which 9 are rule-only, loader events read by the bus
  grant, two fitted integers, ~250 lines of glue in v35_top). The plan is
  `docs/v35s-core-v2-interfaces.md` (approved): A cleanup, B glue into its owners, C the queue a
  self-contained FIFO, D the rule-only stalls and bus phase outputs removed (the corpus exact count
  falls and is reported, not gated, from D), E timing rebuilt one mechanism at a time.
- **2026-11-14, interface plan step A: the core cleaned with no behaviour change.** All 61
  compile-time switches collapsed to their built value and `v35_macros.svh` deleted (37 had no use
  left in the RTL; 24 replaced, with the branches not built and the logic they left dead: the
  largest the loader's word register of MX0b). 35 module outputs and 8 inputs removed (v35_bus 60
  to 40 outputs: 15 with no reader, 5 read only by the trace; loader 6, useq 5, queue 2, eu 2),
  with the registers that only fed them. The trace and the benches read the modules' own nets from
  a simulation-only block in v35_top. Core 5,117 to 4,534 lines. Left: `V35_QUEUE_A` (set by lint
  configuration 5), the dead inputs (bus `rfm`, queue `rd_b`, eu `ex` / `op` / `dh`), `ex_pop`
  (now the same term as `ex`). **Gate:** corpus 6,541 with 0 runs differing at both spacings; every
  corpus run's pin record equal to the base's (30,536 runs, 1,849,104 rows a spacing); the
  per-clock trace byte-identical on 718 runs at both spacings; write data 106,824 / 106,824, chk
  silent, vectors 0 bad, lint clean, 48 fast tests, SingleStepTests 0 fails, every program and fuzz
  line as the base. **FPGA at 17 ns: +1.556 / +1.563 / +1.550 on seeds 1 / 2 / 3** (the base
  +1.648 / +1.374 / +1.968), 9,591 LUT4 / 634 ADD / 2,468 FF / 81 RAM_5K. **Gate size (user,
  2026-11-14), steps A to C:** the agent's run is the only one (the overseer checks the landed tree
  equal to the agent's and runs Efinity); programs and fuzz reduced to a short set against the
  first socket session; the full gate returns at step D.
- **2026-11-14, interface plan step B: the glue out of v35_top into its owners, no behaviour
  change.** The on-chip cycle (capture, SFR strobes, lane swap, the internal-RAM pending write, the
  read datum mux) is in v35_bus, the on-chip address decoded once; v35_top's copies of the grant are
  gone. The take logic and STOP are inside v35_intc (the smaller interface: 11 links become
  internal), reading named facts from the sequencer (an instruction boundary, a string's take
  point, an E word and its marks, the halt word, the acknowledge and FINT decodes). `ex_pop` merged
  into `ex`; `rmem` from the loader, `dlv_fetch` from the bus; the EU decodes the segment write-hit
  itself. v35_top 752 to 562 lines: clocking, reset exit, pin idling, wiring, the trace and
  simulation observation (left: the N/S pin sampler, the bench's reset hook). test_v35_struct gains
  the port budget (per-module and per-pair ceilings, v35_top's registers and logic limited to named
  lists, no new `_nx` output). Whole port lists: bus 40 to 46 outputs, useq 13 to 20, eu 42 to 40,
  intc 17 to 20 (the glue's wires became direct ones; steps C and D lower them). Left for C / D:
  bus `oc_off` / `oc_word` beside `sfr_a` / `sfr_w`, fetch in flight held by bus and queue, the
  head address, the tags, `rqp` / `tw` / `drop`, every `_nx`. **Gate (the short gate, run once by
  the agent; the landed tree checked equal to the agent's):** corpus 6,541 with 0 runs differing,
  pin records (30,536 runs) and 718 per-clock traces identical at both spacings, write data
  106,824 / 106,824, chk silent, vectors 0 bad, lint clean, 52 fast tests, SingleStepTests 0 fails,
  programs dma 7 / intr 6 / onchip 3 / banks 5 / traps 6 / prio 4 / pfxtake 10 equal, fuzz f5x f5r
  f5n f5u f5v as the base. **FPGA at 17 ns: +2.286 / +1.613 / +2.355 on seeds 1 / 2 / 3** (the
  base +1.556 / +1.563 / +1.550), 9,481 LUT4 / 634 ADD / 2,475 FF / 81 RAM_5K.
- **2026-11-14, interface plan step C: the queue boundary, no behaviour change.** The loader's
  read is a pop count (`pop_n`, 0 to 2 bytes a clock); the queue's dead `rd_b` input, the bus
  unit's `rfm` input, the queue's variant A with `V35_QUEUE_A` / `VARIANT_B` and lint
  configuration 5 are gone (the gate has four lint configurations); the N/S pin sampler is in the
  EU (v35_top keeps no register of its own but the reset hook); the bus unit's `oc_off` /
  `oc_word` merged into `sfr_a` / `sfr_w`. `rel` / `stg` stand under a "legacy, step D" block.
  test_v35_struct pins the queue's whole port list. **Not made (each raises a per-pair ceiling;
  left to step D, where the legacy links fall):** the head address into the queue (queue to loader
  14 to 15; an ungated patch exists), `q_flush_addr` into the queue (eu to queue 1 to 2). The
  fetch in flight needed no code change: the queue owns the word owed, the bus the cycle; the
  duplicates for step D are listed in the core README's step C section (`fetch_req_b`, `fr_prev`,
  `rqp`, `tw`, `drop`, the phase outputs, `abort_go`, `q_low`, `q_word`, `fetch_raise`).
  **Gate (the short gate, run once by the agent; the landed tree checked equal to the agent's):**
  corpus 6,541 with 0 runs differing, pin records (30,536 runs) and 718 per-clock traces identical
  at both spacings, write data 106,824 / 106,824, chk silent, vectors 0 bad, lint clean (four
  configurations), 53 fast tests, SingleStepTests 0 fails, programs dma 7 / intr 6 / onchip 3 /
  banks 5 / traps 6 / prio 4 / pfxtake 10 equal, fuzz f5x f5r f5n f5u f5v as the base. **FPGA at
  17 ns: +1.996 / +1.768 / +1.875 on seeds 1 / 2 / 3** (the base +2.286 / +1.613 / +2.355),
  9,454 LUT4 / 634 ADD / 2,465 FF / 81 RAM_5K.
- **2026-11-15, interface plan step D: the plain machine (timing changes, function intact).**
  Measured first on a throwaway build (each rule off alone; all off 0 exact; the
  take sync and the staging-room rule each move every run; removing the aborted fetch alone gains
  74 runs net; the I/O recovery window buys nothing). **Removed:** the sequencer stalls (`st_bw`,
  `st_uh`, `st_wp`, `st_wbw`, `st_tsy` with `tw` / `rqp` / `drop`, `st_fch`, `st_rfl`, the fetch
  wait of `st_sus`), the reservation with the low-queue hint (alone, removing the hint deadlocks
  PUSH imm16), the aborted fetch cycle, the bus unit's `ioh` hold, recovery window and phase
  outputs, the queue's `u_sus` / `lat_hold` / `unc_a` / `q_low` / `q_word`, the loader's hold /
  hold2 / staging-room rule, the microword flags `wb` / `wp` / `fw` / `resv` (the word is 92
  bits; the microcode otherwise word for word the same, 1,910 words) and all three `FIT_`
  integers. **Added (function):** a write-datum latch in the bus unit (datum and width captured at
  B2; the pair's second half and on-chip stores read it), proven no change before the removals.
  **Kept:** the RAMEN write hold: function-bearing beyond the latch (RETRBI reads a bank word of
  the internal RAM while the store to it is still on the bus); its plain form (hold only stores
  into the internal RAM) is step E's. SUSP and `nb` (function), the bus unit's back-to-back
  priority, the queue's room on its own count (7 bytes, a word in flight counts 2, request at 5 or
  fewer). **Structure:** the head offset (`hip`) and the flush address in the queue; bus to useq
  12 signals to 0, loader to bus 3 to 0, useq inputs 54 to 33, loader outputs 38 to 25; the
  budget 156 / 178 to 129 / 146 (two pairs up by one: queue to loader 15, eu to queue 2);
  test_v35_struct bans the removed names and `FIT_`. **Corpus (reported, not gated, from here):
  0 exact of 30,536 at both spacings** (6,541 before); write data 106,824 / 106,824, chk silent.
  **Full gate (agent's run and the overseer's on the landed tree, verify.out identical):** vectors
  0 bad, lint clean (four configurations), 54 fast tests, SingleStepTests 0 fails, every program
  set equal on both socket sessions but periph f4_tm (timing only: handler entry intervals up to
  28 to 30 clocks off against a tolerance of 16; writes 563 / 563 and pins equal), fuzz as the
  last full gate (the same programs differing). **FPGA at 17 ns: +1.384 / +2.079 / +1.916 on
  seeds 1 / 2 / 3** (the base +1.996 / +1.768 / +1.875), 9,209 LUT4 / 629 ADD / 2,421 FF /
  79 RAM_5K.
- **2026-11-15, interface plan step E1: where the plain machine leaves silicon, and two queue
  mechanisms.** Measured with no RTL change: every corpus run leaves silicon in the shared
  prelude, at the first fetch after its POP PSW read (the RTL's queue one word ahead; at 1 / 2
  waits also 3 / 4 clocks early). **Kept, both in v35_queue, no port added:** M1 the queue is six
  bytes (the latch no longer a seventh place of room; the latch is now unreachable, removal left
  for E2); M2 the request line is formed from the registered count (a pop's room reaches the bus
  unit a clock later; the decoder's pop leaves the request line). Each alone moves the first
  fetch the wrong way; together it is silicon's word on silicon's clock on all 10,420 zero-wait
  runs. **Corpus 0 exact (0 lost, 0 gained);** mean matched prefix 1.00 to 2.02 events.
  **Rejected:** "the E word / every microword / every pop waits while a fetch is in flight"
  (the MOV r16,imm16 train per two instructions 12 / 13 / 15, 16 / 19 / 22, 12 / 15 / 18 at
  0 / 1 / 2 waits against silicon's 14 / 16 / 19). **Open:** the EU's pace against the fetches
  (that train; SHL's 12 + 2n against 11 + 2n), the POP PSW read's one clock per wait state.
  Gate: write data 106,824 / 106,824, chk silent, vectors 0 bad, lint clean, 54 fast tests,
  SingleStepTests 0 fails, the short program and fuzz set as step D (periph f4_tm timing only).
  **FPGA at 17 ns: +2.561 / +2.676 / +1.984 on seeds 1 / 2 / 3** (the base +1.384 / +2.079 /
  +1.916), 9,230 LUT4 / 629 ADD / 2,444 FF / 79 RAM_5K.
- **2026-11-15, interface plan step E2: no mechanism found for the EU's pace; the queue's latch
  removed.** About 120 single-stall candidates (one act x one registered fact: a fetch in flight,
  the request line, a request flop, a wait state, the fetch's phases, any cycle's datum phase)
  traced against the frozen model's internal events on the three prelude sites: none reproduces
  the MOV r16,imm16 train, the POP PSW read's wait slope and SHL's 12 + 2n together. The nearest:
  "every word waits while any cycle is past B2" (SHL exact, the POP PSW slope right, the train's
  period right at 1 / 2 waits but its fetch grouping wrong). A solver shows no single EU stall
  can give silicon's train on the six-byte queue with the present routine shapes (the two starts
  of a pair depend on two different fetches). The model's own state that is missing: the opcode
  register as a counted place freed by the start (against E1 M1 at the POP PSW site) and up to
  two words owed at the last operand take. Nothing kept; corpus 0 exact, 0 lost, 0 gained.
  **Landed:** the unreachable latch out of v35_queue and the loader's head select (queue to
  loader 15 to 11 signals); pin records 30,536 / 30,536 identical at both spacings, the short
  gate as E1 (a lint tie added after the gate run, re-linted clean in four configurations and
  re-replayed on five families). **FPGA at 17 ns: +2.771 / +2.222 / +2.540 on seeds 1 / 2 / 3**
  (the base +2.561 / +2.676 / +1.984), 9,095 LUT4 / 629 ADD / 2,411 FF / 79 RAM_5K. Next (E3):
  an offline structural search with the pop positions and the queue's geometry free, fitted to
  the pins' bus events only.
- **2026-11-15, interface plan step E3: an offline structural search, no RTL change, nothing
  found.** An abstract front-end simulator searched jointly over the queue's geometry (6 / 7
  places, the opcode register none / outside / counted, the room's delay, the restart
  threshold, the delivered word's clock), the pop positions and step counts per form (the book
  +/- 2) and up to two resource stalls (the adder, the queue's read port, a wait-state freeze,
  a cycle's datum phase, the decode register's age), fitted to the pins' bus events only
  (F0 F0w F1 F2 F3: 1,052 runs, 34,908 events; held-out sets fixed before fitting). **0 of 5,112
  structures reproduce even the shared prelude at the three wait settings**; 0 waits alone is
  reproducible. What defeats them is the train's wait dependence with the queue full: silicon's
  EU waits for particular words (those its own pops asked for), not for a phase of any cycle.
  Outside the menu, only an owed-word wait (step D's removed take sync as a counter in the
  queue, with seven counted places and the room from the same clock's pops, against E1's M1 and
  M2) reproduces the prelude (114 / 114 events, 16 free choices against 54 events) and it fails
  off the prelude: 23 of 1,012 fit programs exact, 17 of 3,866 and 4 of 1,512 held out; every
  even-parity run needs a different restart threshold after the PAD NOP, and the long routines
  are wait-dependent in a way it does not give. Corpus records consistent (0 of 3,171 repeat
  acquisitions differ; 0 of 26,326 programs with runs differing in pin timing). The direction of
  step E is with the user.
- **2026-11-15, qprobe: targeted socket tests of the front end, read and built.** The user's
  direction: the corpus is too complex to read the front end from; a small set of tests from a
  known queue state instead. Frame of every program: the corpus prelude, a marker OUT, a long
  shift (queue full, bus idle), the body, a marker OUT, a second long shift; 0 / 1 / 2 waits,
  both alignments, each run twice. Rounds 1-4: 1,842 socket runs and 1,842 repeats, 0 failed,
  0 repeats differing (receipts `validation/v35s/receipts/qprobe/QPr{1..4}-w{0,1,2}.json.gz`;
  tools `validation/v35s/qprobe/`: gen, run, read, model, search). **The reading** (model.py, a
  200-line clocked model, reproduces every bus event from the fill to the second marker on
  1,214 of the 1,428 runs of rounds 1-3, among them all 378 of round 3 which no rule was read
  from): at most seven bytes held beyond the running instruction; a fetch starts from idle when
  the count falls to four, on the pop's own clock (five right after a bus cycle unless a
  boundary executes on that clock); the next opcode leaves the queue on a particular word of
  the running routine (NOP 1 of 4, INC 1 of 2, CBW 1 of 3, the immediate forms with the
  immediate, OUT DW 5 of 8, SHL r,CL the last but one); **an instruction boundary cannot happen
  while a fetch cycle is in flight, except on its last clock** (this alone gives NOP 4 / 4 /
  4.5, INC 2.5 / 3 / 3.5, MOV r,r one bus cycle each, MOV r16,imm16 7 / 8 / 9.5 clocks at 0 / 1
  / 2 waits: the prelude's train steps E1-E3 could not give); some words wait for a running
  fetch (the word four clocks before an EU cycle, the immediate's pop word, SHL r,CL's 4th word
  hence 12 + 2n + waits, a jump's flush word, the target's fetch five clocks later); the first
  instruction after a flush starts when four bytes of the new stream are delivered; a ModR/M
  instruction's boundary needs three bytes behind its opcode (the count measured on 180 runs,
  its mechanism not understood); alignment changes only the one byte held at the start; no
  register-forwarding stall. **Built:** the queue seven bytes, its request line from an
  occupancy that follows the measured release clocks (E1's registered line and the bus unit's
  back-to-back commitment removed); microword fields `ro` / `rl` / `bi` (96 bits, the three
  banks full); sequencer stalls `st_bnd` and `st_bi`; NOP / XCH, CBW, the immediate forms, OUT
  DW, SHL r,CL, SHL r,1, JMP short and Jcc reshaped. **Small set, fill to marker: round 1 330 /
  330 (the base 7), round 2 460 / 720, round 3 378 / 378; from the first marker on 0 / 1,428
  and corpus exact 0 of 30,536** (pre exact 9,736): OUT imm8 (the corpus's marker), PUSH and
  the memory forms are not read. The five-clock flush wait is applied to every flush, measured
  on JMP short and Jcc only. Function on the short gate: write data 106,824 / 106,824 at both
  spacings, 0 FAIL, chk silent, lint clean in four configurations, vectors rf-a 69,464 / rf-b
  39,103 / fn 19,749 0 bad, 54 fast tests, SST rc 0, the fuzz subset's differing lines the
  base's (f5n x3, f5v x2). **Three program lines newly differ from the socket, all with the
  self-check passing on both sides and every write present:** intr f3_vec and f3_prio (the
  stored result bytes differ: the interrupt is taken at another instruction boundary) and
  periph f4_tout (a one-shot period 837 against 855 clocks, tolerance 16; f4_tm likewise, a
  known timing-only line). They are consequences of the timing half rebuilt and are targets of
  the next rounds. **FPGA at 17 ns: +2.699 / +2.897 / +2.370 on seeds 1 / 2 / 3** (the base
  +2.771 / +2.222 / +2.540), 9,114 LUT4 / 642 ADD / 2,431 FF / 81 RAM_5K; the request line
  formed in the clock of the pop costs nothing. Next: OUT imm8, bus-idle words after an EU
  cycle, the prelude as probe programs, PUSH / POP and memory forms, the other flushes.
- **2026-11-15, qprobe rounds 5-7: the merged reading built; corpus 13,268 of 30,536 exact.**
  Three more socket rounds (870 runs, each twice, 0 failed; receipts QPr5..7 beside the others;
  the cumulative reading in `validation/v35s/qprobe/RESULTS.md`, the merged model `model_m.py`
  reproducing 2,596 of 2,712 small-set runs to the program's end and predicting the corpus
  prelude behind a long shift 6 of 6 unfitted). **Read:** the boundary waits for any bus cycle
  in flight, the EU's own included, except on its last clock, and while a memory cycle is
  posted and not started; HALT acts when its opcode is popped (prefetch stops, an EU cycle not
  yet started is held one clock: the one-clock lateness of every chain's END); OUT imm8 / IN
  imm8 start no sooner than three clocks after their own opcode's pop and MOV sreg two, the
  others one (a decode stage at the pop: the count measured, why these forms take longer a
  guess); the bus unit has a sequencing stage two clocks ahead of the pins which request words,
  OUT DW's first word and SHL r,CL's fourth wait for, while the boundary, the immediate's pop
  word and the flush wait for the pin cycle; a memory cycle comes four clocks after its request
  word, the word taken only in a running fetch's last two clocks; OUT DW is six words; JMP
  far's fetch comes three clocks after the flush, not five. **Built:** all of it but the JMP
  near / far and CALL / RET shapes (not a reading yet; the five-clock flush wait still applies
  to every flush) and a three-run corner (no free word encoding); the word still 96 bits in
  three banks. **Function faults found and fixed on the way:** (1) round 5 removed the wait
  after an external memory write and CALL far's second push overwrote the datum register
  before the bus unit took the first (31 corpus runs running away): F again waits for its
  write's end; (2) the same overwrite across an instruction boundary under a held-back grant:
  the datum now travels with the request, taken at the post (`rq_d`), with a sim-only test
  (`dma hwd`, HLDRQ at 24 offsets over write trains: the old path differs on 15 writes); (3) a
  store posted on its routine's last word let MOVSPA read a stale PSW save (banks f3_bins):
  stores post one word earlier. **Small set: 2,580 of 2,712 to the end, 2,576 from the first
  marker on. Corpus at both spacings: 13,268 exact, 0 lost, 0 FAIL, write data 106,824 /
  106,824**; lint clean in four configurations, vectors 0 bad, 56 fast tests, SST rc 0; dma,
  onchip, banks, traps, prio, pfxtake, serial equal; intr f3_vec / f3_prio, periph f4_tm /
  f4_tout and the fuzz subset's five lines differ as before. **FPGA at 17 ns failed as built
  (-0.259 / -1.047 / -0.330)** on the on-chip write hold's address path (register RAM, segment
  add, page hit, stall), the second-level decode in front of the ROM address, the zero test
  into the condition, and the delivery-to-count-to-stall chain; a behaviour-neutral repair
  (operand captures for the request address, the second-level entry split over the two ticks,
  the ROM address's late candidates selected last, the count's compares from registers; small
  set receipts byte-identical, corpus 13,268, each old expression kept as a `+v35_chk`
  reference) gives **+2.253 / +2.014 / +1.387**, 10,010 LUT4 / 675 ADD / 2,620 FF / 90 RAM_5K.
  **The interface budget grew over rounds 1-6** (bus in 10 to 18, queue in 9 to 17, sequencer in
  29 to 40, loader out 25 to 37; bus to sequencer 0 to 5): each rule was built as its own
  next-clock fact between modules. A consolidation step (one owner for the queue's count, one
  place for the pace rules, one stall back to the sequencer, the budget not to be raised) is
  in progress on this tree.
- **2026-11-16, the front end consolidated: one owner for the count, one for the pace; no
  behaviour change.** The user asked whether the modules were being coupled again: they were
  (see the entry above). Now **the queue owns the count** (`ob`: bytes fetched and not
  released, every threshold compare, the request line; the loader exports only this word's
  releases `rls` and its stream facts `sf_nx`; the loader's duplicate count register and its
  dispatch-time reset, which never acted, are gone) and **the bus unit owns the pace rules and
  returns one hold** (`ph_nx`) to the sequencer, which presents a four-bit word-kind code
  (`wk_nx`: dispatch, flush, release, bus-idle) decoded from the existing microword fields; the
  facts about cycles in flight, the sequencing stage, the give-way, REQ_PRI and HALT's line
  stop are internal to it. The bus unit's B2 write-datum latch is removed (the datum travels
  with the request). 8 port names added, 30 removed; module outputs / inputs **152 / 178 to
  136 / 156**: bus 22 / 18 to 17 / 17 (66e9ff7: 16 / 10), queue 17 / 17 to 15 / 10 (17 / 9),
  loader 37 / 38 to 28 / 34 (25 / 34), sequencer 23 / 40 to 23 / 30 (20 / 29). The budget test
  was edited with the user's approval (sequencer to bus 0 to 2, the stall bus to sequencer 5 to
  1, EU to bus 8 to 9 with EU to sequencer 16 to 14); **from here agents may lower the budget
  and may not raise it.** A loader reference check that fired between the ticks (a five-bit
  reference wrapping on values nothing reads) was corrected. Proof: the small set's 21 sim
  receipts byte-identical; corpus at both spacings 13,268 exact with 0 of 30,536 rows differing
  from the previous landing, pin records identical run by run at the default spacing, write
  data 106,824 / 106,824, 0 FAIL, chk silent; lint, vectors, 56 fast tests, SST, the program
  gates and the fuzz subset line for line as before; `dma hwd` equal. **FPGA at 17 ns: +3.041
  / +2.846 / +2.907** (the base +2.253 / +2.014 / +1.387), 10,035 LUT4 / 658 ADD / 2,582 FF /
  90 RAM_5K; the request address is now registered a tick early (`aq_b`, about 184 LUT4), and
  the worst paths are no longer the pace (the loader's second-level decode into the ROM
  address; the EU's flush offset).
- **2026-11-16, qprobe round 8 built (microcode and one decode bit; no port changed): corpus
  15,342 of 30,536 exact.** Read on the socket in round 8 (912 runs) and built: the EA modes
  measured directly (the heads read by analogy hold, except base + index + d16, one word longer,
  not built: it needs a head name), a routine's second bus cycle two clocks after the first
  one's datum word (ADD [mem],r16), the group opcodes' bus-idle fourth word and their not
  waiting for three bytes (the loader's `m3`, from a generated decode bit; FE / F7 excluded),
  one flush tail for every transfer (the target's fetch 8 clocks after the routine's last
  input), INT 3's lead, POP sreg's width (a function fault of the first pass, found by the
  vectors). **Rule applied to by-analogy forms: an extension beyond what was measured stays
  only if it loses no corpus run**; LDEA's measured form (it needs a head the dispatch cannot
  name) and the byte / other-op read-modify-write forms were reverted on it. Corpus at both
  spacings 15,342 exact (13,268): 2,114 gained, 40 lost, 0 FAIL, chk silent, write data
  106,824 / 106,824; small set rounds 1-8 3,252 of 3,612 (2,985), none lost. The 40 lost are
  ADD [mem],AW before the OUT imm8 marker at W = 0; round 9 on the socket shows the plain store
  misses the same way and reads it as the follower's start (the next opcode leaves the queue
  on the write cycle's first clock: `validation/v35s/qprobe/RESULTS.md` Q23), work order 5.
  Lint, vectors, 56 fast tests, SST, the program gates and the fuzz subset as before (the same
  timing-only differing lines). **FPGA at 17 ns: +2.191 / +2.085 / +1.864**, 10,092 LUT4 / 658
  ADD / 2,580 FF / 90 RAM_5K: 0.7 to 1.0 ns less than the consolidation with no structure
  changed; the path that moved is to be named before the next build adds to it.
  **Position against cause (round 9, `validation/v35s/qprobe/DIVERGENCE-r9.md`):** every
  instruction of every corpus run scored by predecessor and successor class. Of 14,858 misses
  attributed to an instruction: its own routine 8,297, a neighbour with a clear split 1,902
  (predecessor 837, successor 694, both 371), undetermined (wait- or alignment-dependent in
  every frame) 4,659. Forms exact in isolation and still corpus subjects are pair effects:
  stores and read-modify-writes before OUT imm8 (Q23), a group memory form behind a stack
  write, SHL r,1 behind an I/O cycle, and CMP / MOV CW,imm16 standing in for the Jcc / DBNZ
  behind them.
- **2026-11-16, qprobe round 10 on the socket (684 runs; reading only, no RTL): two neighbour
  effects become rules, the third is withdrawn.** (`validation/v35s/qprobe/RESULTS.md` Q26-Q31,
  `DIVERGENCE-r10.md`; the model reproduces 684 of 684 and 4,979 of 6,288 over all rounds, none
  lost.) **Q26**: a bus-idle word waits for the EU's own bus cycle too, not only for fetches
  (SHL r,1 and TEST r,r behind an OUT; corrects Q13). **Q27 / Q28**: every conditional branch
  has a bus-idle fourth word and DBNZ has a lead of two; with the routines in bus terms no rule
  names a predecessor ("CMP r,r / MOV CW,imm16 before Jcc / DBNZ" was the branch's own
  routine). "INC mem behind a stack write" was the positional attribution blaming it for
  unread partners and for word operands at odd addresses: the probe matches the model and the
  round-8 RTL unchanged. Read from data already acquired: the memory-immediate forms (a request
  on the third word keeps the chained fetch its slot), PUSH / POP mem, the 0F CL bit forms on a
  register (88 of 96). Tested and rejected as a rule: "the commit word is three words after the
  last queue byte" (8 measured exceptions, 351 runs). Work order 6 needs no new cross-module
  signal.
- **2026-11-16, work order 5 built (microcode and decode content only, no `.sv` file, no port):
  corpus 16,673 of 30,536 exact.** The next opcode released on the write cycle's first clock
  (Q23) needed no new signal: the E word after the write's post became a bus-idle release word
  (`e ro bi`), and since a posted EU request wins the bus and a bus-idle word waits out a
  fetch's pin cycle, it follows the write when a fetch delays it (`c40` 168 of 168; a write
  delayed by refresh or HLDRQ, not a fetch, would still release early: no run shows it). Also
  XCH mem,r, TEST mem,r, SHL / SHR / SAR r,imm8 (the CL routine with its own head), and C7 as
  the sixth whole opcode for the modes without a displacement. Corpus at both spacings 16,673
  (15,342): 1,332 gained, 1 lost (XCH [d16],AW, a mode by analogy that gains 5 and cannot be
  split from the measured [BW] form), 0 FAIL, chk silent, write data 106,824 / 106,824; small
  set rounds 1-9 3,959 of 5,592, none lost; everything else line for line as before, `dma hwd`
  equal. **FPGA at 17 ns: +3.169 / +2.557 / +3.198**, 10,220 LUT4 / 658 ADD / 2,596 FF / 90
  RAM_5K. The round-8 margin loss was two paths with no RTL change (the EU request into the
  stall; the second-level decode into the ROM address): placement, and it came back.
  **Process (user, 2026-11-16): larger batches per validation.** Work orders 6 and 7 and the
  head name UROM_EAQ16X (approved by the user; an allow-list entry, no port) are one build with
  one gate.
- **2026-11-16, qprobe rounds 11 and 12 on the socket (reading only;
  `validation/v35s/qprobe/RESULTS.md` Q32-Q41, `DIVERGENCE-r11.md`, `DIVERGENCE-r12.md`,
  `INTR-r12.txt`).** Round 11 (1,368 runs): a word at an odd address is two back-to-back byte
  cycles behaving as one EU cycle (Q32); the write that falls due at a fetch's end is the slot
  decision with two corrections (a request on the clock before the decision holds it; a posted
  write whose datum is not yet taken does not compete: Q33); single strings, REP (a prefix
  routine, a 14-word head, a period per form, a tail; Q34 / Q35) and register MUL / DIV (fixed
  lengths with sign terms, no operand dependence; Q36). Round 12 (4,834 runs): the register
  immediate forms, the 0F memory and imm8 bit forms, ROL4 / ROR4, EXT / INS inside one word,
  the 4S forms, MUL / DIV on memory and with an immediate, PREPARE / DISPOSE. **Interrupt
  recognition measured**: taken only at instruction boundaries (never inside a long shift,
  MULU or an RMW, never between a prefix and its instruction), the acknowledge 16 clocks after
  the boundary, MOV sreg holding it off for exactly one instruction, REP breaking between
  iterations; with the bus quiet an NMI edge must be at the pin 14.5 clocks before the staging
  pop of the instruction that will not run (the RTL takes it about 10 clocks sooner). Open: 0
  to 3 further clocks in trains of short instructions, and INTP0 across an RMW train. The
  model reproduces 7,484 of 7,656 runs of rounds 1-11. Of 13,481 diverging corpus runs on the
  work-order-5 tree about 10,200 are on forms now read and about 3,300 are not read or not
  probed.
- **2026-11-16, qprobe round 13 on the socket (reading only;
  `validation/v35s/qprobe/RESULTS.md` Q42-Q45, `DIVERGENCE-r13.md`, `INTR-r13.txt`).**
  **Q42** replaces Q33's "armed" condition: after an EU write at W = 0 the fetch chained to
  the fetch behind the write gives way to a boundary arriving fresh on its clock, and is not
  started when the EU's next word is bus-idle; nothing depends on the queue count or the
  store. **Q43**: CMP mem,imm16, the mem,imm bit forms, DBNZE / DBNZNE (four routines of
  their own, 60 of 60), REPC / REPNC (REPNE / REPE on the carry). **Q44**: EXT / INS across
  a word, JMP / CALL r16 (the "two clocks late at odd alignment" was a wrong shape, not a
  rule), INT 3, BRK imm8, far JMP / CALL through memory, RETI, MUL r,r,imm. **Q45,
  interrupts**: an NMI edge is taken in front of X when at the pin 15.5 clocks before X's
  opcode leaves the queue, 14.5 from an idle bus with a full queue (149 of 278 thresholds;
  a train of NOPs alone shows 17.5, open); INTP0 is edge-latched (pulse width has no
  effect) on a 16-clock grid, and is not presented while read-modify-writes run back to
  back (the NMI is); NMI wins over INTP0 on the same clock. The model reproduces 7,495 of
  7,656 runs of rounds 1-11 and 819 of 852 of round 13's family probes. Split of the 13,481
  diverging runs of the work-order-5 rows: read and not built 11,182, partly or not read
  1,468, not probed 831.
- **2026-11-16, qprobe round 14 on the socket (3,826 runs; reading only;
  `validation/v35s/qprobe/RESULTS.md` Q46-Q54, `DIVERGENCE-r14.md`, `INTR-r14.txt`).** Read
  against the work-order 6 and 7 tree (not yet landed: see the next entry). **Interrupts**: the
  "16-clock grid" is a scan over the eight priority levels, two clocks a level, and EI sets its
  phase (POP PSW and a mask clear do not); a raised request is taken in front of the first
  instruction whose opcode has not left the queue, the vector read 17 clocks after that pop
  (19 behind NOP / XCH AW,r); EI is 13 clocks; an NMI arriving after a maskable request has
  been raised does not displace it (first come; replaces round 13's "NMI wins"); timer 0 goes
  through the same scan; order and vectors are the RTL's, only the timing differs. The INTP0
  edge "held back by read-modify-writes" is an instruction class (ALU mem,reg including CMP
  mem,reg, ADD mem,imm8; not INC / NOT / SHL / XCH on memory, not BUSLOCK): mechanism open,
  and it would need a new level at the EU / controller boundary, so it is not ordered. Open:
  HALT released one instruction late in two programs; three EI runs one round off. **Forms**:
  the not-probed block read (451 of 456): the 80 group on memory, shifts on memory by imm8 and
  CL, LDS / LES, MOV mem,sreg and sreg,mem, PUSH imm8, CVTWL, MUL r,mem,imm; JMP / CALL r16
  have a second bus-idle word (the "four bytes held" stall withdrawn). **Build check of the
  6 and 7 tree**: PUSH with a displacement reads 5 clocks early, one DBNZ-taken run one clock
  late; older: JMP near at even alignment, LEA. Split of the 10,017 diverging runs filed on
  the 6 and 7 rows: read and not built 8,610, partly read 1,096, not probed 299. Not measured:
  the INT pin with INTAK and TOUT's edge (they need marker writes to FF10h; the user lifted
  that limit for round 15).
- **2026-11-16, qprobe round 15 on the socket (1,533 runs; reading only; marker writes to FF10h
  allowed by the user for this; `validation/v35s/qprobe/RESULTS.md` Q55-Q60, `DIVERGENCE-r15.md`,
  `INTR-r15.txt`, `INT-r15.txt`).** **INT / INTAK**: INT bypasses the level scan (thresholds
  as the NMI's from the second instruction on; after EI one instruction later); from the pop P
  of the first instruction not executed, INTAK is low P+8..P+10, high one clock, low
  P+11..P+13, and the table read starts at P+23 (P+19 for a vectored source); the RTL has
  three clocks between the pulses and the table read 5 after the second. INT is first against
  INTP0 and against an NMI on the same edge (the NMI then at the handler's entry). **TOUT**:
  the start store acts 13.5 clocks after its instruction begins, first edge 3.9 + 6(n+1)
  clocks later; the request flag behaves as a pin edge 2.9 to 4.9 clocks before TOUT's edge
  and then waits for the scan. **The scan confirmed**: INTP0 at levels 5, 2, 0 is exactly two
  clocks a level earlier than level 7. **The held-back request, class closed**: every
  two-operand ALU instruction with a memory first operand (00-3F with the direction bit
  clear, 80-83 on memory, CMP included; not DEC, NEG, TEST); the timer's request is held too,
  so it is the setting of the request flag that waits, not the pin's edge detector. Building
  it needs a hold level from the EU to the controller (a new cross-module signal): not
  ordered, the user's decision. Open: the late HALT release (16 programs, no rule; INT never
  shows it). **Forms**: CMP mem,AW / AL, TEST / CMP AL,imm, XCH AW,DW, IN AW,DW, ADJ4A,
  ADJBA / ADJBS read (249 of 288; NEG [BW+d16] and LAHF partly, CVTBD not). **Harness note**:
  in the direct sim build the INTAK answer does not reach the core, so INT probes cannot be
  scored in sim yet.
- **2026-11-16, qprobe round 16 on the socket (790 runs, a fresh agent; reading only;
  `validation/v35s/qprobe/RESULTS.md` Q61-Q67, `DIVERGENCE-r16.md`).** **The 0F page**: every
  0F instruction releases its ModR/M byte on a bus-idle third word (r,imm / ROL4 / ROR4 / EXT
  / INS one word shorter than modelled, m,CL one longer); this one fact explains the
  "NOP;X;SHL at even alignment with waits" misses across 19 forms and "TEST1 r,imm twice",
  with no new wait kind. EXT / INS with a register count had no timing rule missing (the
  probe's count register was reloaded by EXT). MUL / DIV on memory, INT 3 / BRK imm8 confirmed
  in clean frames; CALL / JMP [d16] reshaped (48 of 48 each); LAHF is CLC's routine. Not read:
  NEG [BW+d16] (19 of 24), CVTBD. **Two RTL diagnoses for the builder**: JMP near at even
  alignment is the queue's flush gating (`!flush` cancels the back-to-back fetch silicon
  still makes on the flush clock and discards; the target's fetch follows 4 clocks after that
  fetch's last clock), not the routine; LEA is one empty word short and lacks the bus-idle E
  word. Open: ADD [d16],imm8 late when its boundary finds four bytes held (a byte-count rule
  tested and rejected), CALL far with waits, OUTM twice, the EI scan-phase outliers (three
  positions now, reproducible), the late HALT release. The model reproduces 10,175 of 10,700
  form runs of rounds 1-15 and 761 of 774 of round 16. Round 14's rows re-classified: read
  and not built 9,553, partly read 344, not probed 90, probed and not read 30.
- **2026-11-16, ruling (user): the held-back maskable request is a known difference, not
  built.** On the chip a two-operand ALU instruction with a memory first operand (00-3F with
  the direction bit clear, 80-83 on memory, CMP included) keeps a maskable request (INTPn,
  timer 0) from setting its request flag until the instruction ends; NMI and INT are not
  affected (qprobe Q53, Q58). The core does not do this: building it needs a hold level from
  the EU to the interrupt controller (a new cross-module signal) for an effect whose
  mechanism is not known. Effect of the difference: a maskable interrupt arriving during
  such an instruction (or a back-to-back train of them) is taken at an earlier boundary than
  on the chip. Revisit only if a socket round finds the mechanism.
- **2026-11-16, work orders 6 and 7 built as one batch (one gate): corpus 20,154 of 30,536
  exact.** Built from rounds 10 and 11: a bus-idle word waits for any running cycle, the EU's
  own included (`bz_nx`, a subset of the old fetch level, registers only; Q26); a word at an
  odd address is one EU cycle to the boundary and the bus-idle level (`bp_nx`; Q32); the
  conditional branches' bus-idle fourth word, DBNZ's lead of two, BCWZ (Q27 / Q28); the
  memory-immediate forms with the request on the third word (Q29); PUSH / POP [BW], SHL
  [BW],1, MOV [BW],imm8, the 0F CL bit forms; the seven single strings and REP for MOVBK /
  STM / LDM / INM / OUTM (Q34 / Q35); the bus-idle third word of MUL / DIV (Q36); the EA head
  UROM_EAQ16X for [BW+d16]-class modes (one loader compare). **A second wait kind, `alt`**:
  the microword is full at 96 bits, so the kind's fifth bit reuses the word's `vk` bit (read
  only by vector words; the assembler refuses `alt` on a word with a vector source); the
  useq-to-bus port is one bit wider, no port added. **FF is the seventh and last whole
  opcode** (the measured PUSH [BW] apart from the displacement modes that keep the round-9
  routine). ROM 2,025 of 2,048 words. Corpus at both spacings 20,154 (16,673): 3,483 gained,
  2 lost, 0 FAIL, chk silent, write data 106,824 / 106,824; small set rounds 1-9 4,747 of
  5,592, round 10 683 of 684, round 11 805 of 1,368; vectors 0 bad, lint clean, the program
  gates and fuzz line for line as before, `dma hwd` equal. Not landed on its own (the gate found a function fault, next entry). **FPGA at 17 ns for this tree alone: +2.496 / +2.553 /
  +2.260**, 10,226 LUT4 / 657 ADD / 2,577 FF / 90 RAM_5K. **Kept losses:** ADD [d16],imm8
  (2 corpus and 4 small-set runs lost, 30 corpus gained; splitting the mode needs an eighth
  whole opcode); MULU r8 behind MOV BW,imm16 at one alignment (1 small-set run; the reading
  model misses it too). **Reverted by the corpus:** DBNZE / DBNZNE as DBNZ (they have their
  own routines, Q43), SET1 / NOT1 r16,CL by analogy. **Not built:** the chained fetch against
  a posted write (Q33: every RTL store loads its datum on the posting word, so "unarmed" has
  no state to read; round 13 replaces the rule, Q42); REP as a real prefix routine with its
  boundary waits, the CW = 0 exit and the REPE / REPNE compare loops (the previous E word
  pops prefix and string opcode together: a loader / decode change); POP mem and the 83
  forms with a displacement (the bare heads release the displacement before the request
  word); PUSH R / POP R (ROM room); the F6 three-bytes exemption (no probe moves).
- **2026-11-16/17, work orders 6 to 9 landed as one batch: corpus 23,702 of 30,536 exact.**
  The landing gate of the 6 and 7 tree found a function fault the vectors and the corpus do
  not see: the rebuilt REP MOVBK read on-chip RAM before writing IX back, so the snapshot copy
  that runs over its own IX slot stored the old value (two bank programs and every fuzz
  program, one byte). Fixed (IX stepped and written on the two words between the request and
  the read's post, IY before the write; no bus clock moved); the builder's loop now includes
  the bank gate and one fuzz set. **Work orders 8 and 9 on top**: the register-immediate
  forms, CMP mem,imm16, the 0F page (r,imm, mem,CL, mem,imm bit forms, ROL4 / ROR4, ADD4S /
  SUB4S / CMP4S, EXT / INS including across a word), MUL / DIV on memory, MUL r,r,imm,
  PREPARE / DISPOSE, JMP / CALL r16, RET imm16, INT 3, BRK imm8, RETI, the [d16] transfers,
  DBNZE / DBNZNE's four routines, PUSH R / POP R (unrolled). **REP is a real prefix routine**
  (`rep_p`, a decode bit `rp`: the prefix's E pops the prefix alone, its own E the string
  opcode, so the string's boundary gets every boundary wait). **The posted write (Q33)**: C6 /
  C7 post with a bus value MEMWD and the word that takes the immediate arms the write; the
  existing port bit `req_ia` on a memory write now means "datum loaded by this word" (an
  overloaded meaning, to review); Q42's first half built. **Displacement cells**: assembler
  cell kinds that skip the EA head so a routine pops and releases its own displacement (PUSH /
  POP mem with a displacement, the [d16] transfers) without a new head name. **ROM**: the
  address is 12 bits (the user: growth to 4,096 is fine while developing), 2,426 words in two
  physical parts chosen by the registered top address bit; the word stays 96 bits (`trap`
  became a sequencing value). The whole opcodes are 0F 64 65 F2 F3 FF 8F. **Interrupts**:
  the acknowledge runs INT 3's words 16 clocks after the boundary, a broken REP leaves through
  its own exit; the NMI / INTP delays are two untuned 10-clock constants and a free-running
  grid, placeholders that work order 10's level scan replaces. Corpus at both spacings 23,702
  (6 and 7 tree 20,154; last landing 16,673): against the 6 and 7 rows 3,678 gained, 130
  lost (103 MOV mem,imm16 with a displacement, mostly one wait: its whole-opcode slot went to
  8F; 16 REP INM / OUTM with CW = 0; 10 bit-imm register forms; 1), 0 FAIL, chk silent, write
  data 106,824 / 106,824; small set 1,980 gained, 56 lost (the same MOV form); vectors 0 bad,
  fast tests and SST pass, banks 5 equal, fuzz as before (f5n 3 and f5v 2 timing-only), the
  program gates line for line as at the last landing, `dma hwd` equal. (The gate's first
  default-spacing replay lost a simulator process and was rerun: complete and identical.)
  **FPGA at 17 ns: +1.297 / +1.274 / +1.450**, 10,559 LUT4 / 657 ADD / 2,601 FF / 107 RAM_5K:
  all pass, about 1 ns lost to a new chain from the segment select through the address add
  into the sequencer's `ex` register (19 to 29 levels); breaking it is in the next build.
  Not built: the REP compares' read-ahead and REPC / REPNC, EXT across a word's extra word,
  the 83 group's request ahead of a displacement, Q42's second half, the build-check items
  (DBNZ taken, JMP near at even alignment, LEA). The next build (work orders 10 to 12) takes
  the kept losses first.
- **2026-11-17, work orders 10 to 12 landed as one batch: corpus 25,422 of 30,536 exact.**
  **The `ex` chain** of the last landing was the posted-write term reading the on-chip
  compare of the post's linear address; it now reads the unarmed state without the compare (a
  MEMWD post is always on the word before K, where the term is 0 either way; a `+v35_chk`
  assertion, silent over the corpus, says so). **The whole-opcode limit is lifted**: opcodes
  with identical second-level tables share a number (the four REP pages; 80 / 82 / 83), so C7
  and the 80-83 group with a displacement have their own cells; a cell may end in another
  routine's words (the assembler's release check follows the jump). **Built**: the 0F page's
  bus-idle third word, CALL / JMP [d16], LEA, the forms of rounds 14 and 15 (the 80 group and
  shifts on memory, LDS / LES, MOV mem,sreg / sreg,mem, PUSH imm8, CVTWL, MUL r,mem,imm, EI,
  CMP mem,AW / AL, TEST / CMP AL,imm, XCH AW,DW, IN AW,DW, ADJ4A, ADJBA / ADJBS), F6 exempt
  from the three-bytes wait. **The queue's flush**: on the clock a flush word executes the
  fetch the ordinary rule would make is still made at the old address and its word discarded
  (a register `fdb` holds the request line until it arrives, then the flush wait); no flush
  probe lost. **Interrupts** (all inside v35_intc): pins sampled every second clock, the
  level scan (`sc`, two clocks a level, reset by EI), the request raised when the winner's
  level equals the scan's and held with its source, first come between a maskable request /
  INT and NMI, HALT released by the scan's raise; the INT acknowledge is one 6-clock cycle
  with both INTAK pulses; the acknowledge's vector read loads address 0 (it had used a stale
  address: the "INTAK answer not reaching the core" in sim was this core fault). **Measured
  latencies without a mechanism, to be explained or removed (socket round 17): INTP_DLY = 11
  (pin edge to request flag), two register stages between the scan's raise and the EU,
  NMI_DLY = 10.** The held-back request, the late HALT release and the EI outliers are not
  built. Corpus at both spacings 25,422 (23,702): 1,941 gained, 221 lost (149 LEA with a
  displacement: the [BW] shape applied to modes that were never probed, the same change
  gaining 214; 72 in the new displacement cells, each outweighed on its form but 81 [d16],
  4 gained / 10 lost, whose cell gains 139 elsewhere), 0 FAIL, chk silent, write data
  106,824 / 106,824; small set rounds 1-13 9,006 of 9,630 (8,576), 4 lost; interrupt probes
  clock-exact 1,715 of 4,630 (1,175). **Program gates: f3_vec, f3_order / f3_prio now equal
  (intr 6 equal, 0 differ);** f4_tm and f4_tout still differ on periods only; everything else
  as before, fuzz as before, `dma hwd` equal. **FPGA at 17 ns: +1.317 / +0.971 / +0.859**
  (all pass), 10,631 LUT4 / 642 ADD / 2,627 FF / 108 RAM_5K; the worst path is now the
  loader's decode RAM into the ROM address (8 levels between two block RAMs; loader 3.529 and
  useq 5.846 per module, both under their earlier floors): a timing repair leads the next
  build. ROM 2,509 words. Not built: the commit word passing the Q42 fetch (needs the next
  word's release a tick earlier), EXT across a word's extra word, the REP compares'
  read-ahead, Q42's second half.
- **2026-11-17, qprobe round 17 on the socket (3,398 runs; reading and a build check of
  2a30b50; `validation/v35s/qprobe/RESULTS.md` Q68-Q74, `DIVERGENCE-r17.md`).** Re-based: the
  corpus replays to 25,422 on the agent's copy too. Split of the 5,114 diverging runs (4,775
  filed): read and not built 4,628, partly read 85, not probed 50. **LEA per mode** (576 of
  576): every mode is five words and the displacement leaves on the bus-idle fourth word with
  the next opcode (`P . . BN .`, `P . . BNP .`, `P . . BNPP2 .`; two registers + d16 one word
  more); the landed RTL has the extra word twice on the displaced modes. **Q33 restated
  (Q69)**: ADD / CMP word [d16],imm16 follow Q33's table and are reads, so "unarmed write
  datum" is withdrawn: a request made on the word that releases the displacement only
  reserves the bus and competes from its due clock (request word + 4); a request on the
  decision's eve still holds the chained-fetch decision (model 8,286 of 8,496 on rounds 8-17,
  none lost). CVTBD is 21 words with a bus-idle sixth. **Build check**: C7 with a
  displacement at odd alignment W = 2 (the K word clears the unarmed state on the fetch's
  last clock, so the grant no longer honours the decided chained fetch: one register in the
  bus unit), C7 at W = 0 (Q33 fact 2 not built: 148 of 175 runs on the displaced store
  forms), SET1 / CLR1 / NOT1 mem,imm twice, PUSH [d16] at even alignment, CALL far [d16];
  on-chip SFR stores take 3 to 5 clocks longer in the RTL than on silicon. **Interrupt
  latencies decomposed (W = 0 only)**: INT and INTPn are sampled every clock and a level
  counts after two equal samples; the INTP flag is set on the divided clock 4.1 to 6.1 clocks
  after the edge (the RTL's 11 lumps 5 to 7 clocks that belong to the EU side); NMI passes a
  filter in time (never at 1.75 clocks, always at 2.0, at every phase), not a clocked
  sampler; INT needs 9.125 clocks from pin to the pop it pre-empts; HALT release is on a
  2-clock lattice. Unknown and marked so: what makes the 7 to 8 clocks on the EU side common
  to every source, NMI's 3 to 4 further clocks and their bus dependence, whether NMI's filter
  is a time or a count on a faster clock.
- **2026-11-17, qprobe round 18 on the socket (6,036 runs in 20 families; a reading, no RTL
  change; `validation/v35s/qprobe/RESULTS.md` Q75-Q81, `DIVERGENCE-r18.md`).** **INT (Q75)**:
  the instruction pushed is the one whose pop is the first at or after edge + 9.125 clocks, on
  1,760 of 1,760 runs (NOP / INC trains at W = 1 and 2, CBW, MOV r,imm, a read cycle per
  instruction, inside MULU, inside a 76-clock shift, mixed trains at W = 0 and 2): a fixed 7
  CPU clocks behind the two-sample level to a level the next pop reads; not the divided
  clock, not a microcode sample point, not the bus unit, not the queue. What the seven stages
  are is unknown. Behind a jump the pop that counts is 2 clocks before the last word in front
  of the target. **NMI (Q76)**: the request stands 8.875 clocks after the edge like INT's;
  then a second stage INT lacks. In opcode-only trains one rule fits every steady-state run
  (806 of 856): the first pop S after the request stands loads normally and the pop replaced
  is the first at least 5 clocks after S not made on the first word of the instruction S
  loaded. Across EU bus cycles and long instructions silicon takes it earlier (3 to 7 clocks,
  404 of 904 by the rule): unknown, not to be built. **NMI filter (Q77)**: never at 1.75
  clocks, always at 1.875, at 16 eighth-clock positions: a time. **Scan (Q78)**: the 16-clock
  grid is locked to EI (the cut-off moves exactly 3.0 clocks with a CBW in front of EI); the
  scan's level-7 look cuts off 4 clocks earlier than a program read of the flag; with the
  request set by a store to EXIC0 the vector read is 50 clocks after the store's cycle at 23
  positions with no grid (inferred: a store to a request control register restarts the scan
  as EI does). **Q79**: the two readings of the reserving request predict identical traces on
  1,872 candidate programs, so spec 13 A1 stands. **REP compares (Q80, 768 runs)**: one loop
  for all eight forms and four prefixes; k compared, k + 1 read, CW - k left; CMPM iterations
  10 clocks once then 12 whatever ends the loop; the count exit is one word longer than the
  condition exit. The landed RTL has the head one word short and one exit length; at W = 2
  the spacing differs in part of the forms (not diagnosed). **Q81**: set1_rw_cl (156 corpus
  runs) is a build fault (silicon's SET1 / NOT1 r16,CL is the byte forms' routine; the RTL
  keeps a short `b1sclw_r`); br_n1 (211) is shared by model and RTL: a transfer whose opcode
  arrives alone behind a previous flush starts W clocks early at W = 1 and 2 (silicon: second
  flush fetch 8 clocks after the end of the fetch bringing the displacement); the word that
  waits is not identified. Not started: NEG [BW+d16], EXT across a word, ADD [d16],imm8 with
  four bytes held, CALL far with waits, OUTM twice. Open for the user: whether a seven-stage
  delay of measured length and unknown purpose may be built for INT.
- **2026-11-17, qprobe round 19 on the socket (4,370 runs in 35 families; a reading, no RTL
  change; `validation/v35s/qprobe/RESULTS.md` Q82-Q87, `DIVERGENCE-r19.md`).** **The vectored
  sources' EU side is a mechanism, not a delay (Q82, Q83)**: in NMI runs the bus unit is
  occupied for 2 clocks with nothing on the pins (332 of 332 EU cycles whose first clock is c
  or c + 1 are exactly 2 late, c = the first clock the level stands at the EU, e + 8.875;
  0 of 163 at c + 2; none in 632 INT runs; present in INTP0 and timer runs). The rule, 5,092
  of 5,128 NMI runs of rounds 17-19 at W = 0 to 2: (1) the event is the first clock >= c on
  which the microcode's current word is an instruction's first word, its N word (executing or
  waiting), a word waiting for the EU's own cycle, or a loop word (SHL by CL, MULU); (2) the
  occupation starts at the event; (3) five clocks after its first clock the first pop is
  replaced and the vector read follows 17 later. Round 18's opcode-only rule is the special
  case where the only events are pops. INTPn goes through the same stage (78 of 78, a test);
  the timer shows the occupation (rule not scored). Inferred: the occupation is the internal
  acknowledge. Unknown: the 3 clocks behind it, loop words of DIV / strings / REP, 36 misses,
  the rule in front of jump targets (507 of 576). **INT's stage 4 (Q85)** is a line carrying
  the level and then a request latch at the loader: a 2- or 3-clock pulse is taken by the
  first pop >= e + 9.125 at every phase and up to 68 clocks later; IE gates the latch, not
  the line's input (a request that entered before DI is never taken behind it and is cleared,
  not masked; a held level is taken at the second pop behind EI). What the seven clocks are
  is still unknown. **br_n1 (Q86)**: JMP short's displacement word is a bus-idle word
  (`. . . BP . . F N .`); `r18j` 60 of 60 from 48, the non-interrupt socket set 12,215 of
  13,404 from 12,203, none lost; spec 14 A2 withdrawn. **REP compares with waits (Q87)**:
  each read's waits add serially (CMPBK 9 + W, CMPM 10 + W then 12 + W); the RTL's later CMPM
  iterations are 12 at every wait. Not started: the unread forms of spec 13 D, HLDRQ / PRC /
  HALT probes of stage 4. Open for the user: building the unexplained 7-clock line for INT;
  two signals across the EU / bus-unit boundary for the occupation handshake against the
  port budget; building the event list with DIV / strings / REP left without events.
- **2026-11-17, rulings (user) on the interrupt build after round 19.** (1) INT may be built
  as a seven-clock line of measured length between the two-sample level and the IE-gated
  latch at the loader, its purpose recorded as unknown (an explicit exception to the
  "every delay needs a machine explanation" rule, for this line only). (2) The port budget
  may be raised by the two signals of the vectored sources' occupation handshake across the
  EU / bus-unit boundary (request, done), and by no more. (3) The event-word list may be
  built as measured, with DIV, strings and REP left without events until they are read (a
  known difference for NMI / INTPn timing across those routines).
- **2026-11-17, the round-17 build landed (work order 13 in part, a timing repair).** One
  gate, one three-seed timing run. **Timing repair, behaviour-neutral** (12,054 small-set pin
  traces identical): the sequencer's DISPM source withdrawn (no ROM word used it, but the ROM
  address select carried the loader's whole second-level entry path; `uasm` now rejects
  `dispm` and no longer generates the second-level entry tables, so the limit of seven
  whole-opcode numbers is gone; the `dec2` port stays with its entry field unread); the
  multiply's finish formed a tick earlier (`mf_b` / `mfn_b`); the segment value captured at
  ce_b (`segv_b`), removing the `word.ea` to `ex` chain; the new registers compared every
  clock under `+v35_chk`. **Built**: LEA per mode as cells of 8D (`ldea`, `ldea_d8`,
  `ldea_d16`, `ldea_dir`, `ldea_d16x`; the extra word of [base+index+d16] placed before the
  add by analogy), CVTBD (21 words, bus-idle sixth), C7 with a displacement at odd alignment
  W = 2 (one register `dcu` in the bus unit: the write was still unarmed on the running
  fetch's last clock). **Gate**: corpus 25,662 of 30,536 exact at both spacings (from 25,422;
  251 gained, 11 lost: LEA with d16 or the direct address at even alignment W = 0 in
  PUSH / OUT frames, a frame Q68 does not separate; kept, the same forms gain 84), writes
  106,824 / 106,824, chk silent; vectors 0 bad; 56 fast tests; SST; program gates as the
  previous landing (periph f4_tm / f4_tout, f5n x3, f5v x2 the same timing-only lines);
  f4_hwd equal. **FPGA at 17 ns: +2.815 / +3.217 / +3.230** (from +1.317 / +0.971 / +0.859);
  9,438 LUT4, 642 ADD, 2,541 FF, 98 RAM_5K; per module useq 6.106, loader 4.042, eu 4.397,
  queue 7.135, bus 6.393. ROM 2,532 words. No port added. **Not built**: the reserving
  request (spec 13 A1; a sketch within the existing ports), the on-chip SFR store's extra
  clocks (narrowing the RAMEN hold to internal-RAM stores recovers 3 but breaks f4_dma's
  write order; reverted), REP compares, EXT across a word, SET1 / CLR1 / NOT1 twice,
  PUSH [d16], CALL far [d16]: all in the next batch (work order 14).
- **2026-11-17, qprobe round 20 on the socket (3,722 runs; a reading, no RTL change;
  `validation/v35s/qprobe/RESULTS.md` Q88-Q94, `DIVERGENCE-r20.md`).** **The strict bus-idle
  word (Q88, Q89, Q94)**: a bus-idle word that releases a 16-bit operand (d16, imm16, a far
  pointer's segment) also waits on the clock a chained fetch starts: the fetch runs and the
  word executes the clock after its last clock; a bus-idle word releasing one byte or nothing
  does not. Measured on LEA d16 / direct (1,224 of 1,224, from 1,179; the 11 corpus runs lost
  in ce9ea43 are this state: the boundary finds four bytes held with the bus idle), MOV
  r16,imm16 (closes round 12's MUL / DIV-on-memory rows, 48 runs), JMP far and CALL far (the
  segment word: 72 of 72, 114 of 114), MOV / ADD word mem,imm16 with d16; inferred by the same
  statement on CMP / TEST mem,imm16, ADD AW,imm16, the 81 group on a register, LEA [two
  registers + d16] (no run changes). Why three bytes differ from two is unknown. **Read**: NEG
  / NOT / INC [BW+d16] and [BW+d8], OUTM twice (bus-idle fifth word), CVTBD's operand word
  bus-idle, the 0F page's register commit word a plain bus-idle word (+27), TEST [d16],AW,
  TEST word mem,imm16, POP [BW+IX+d16] (one extra word behind the stack read), SHL / SAR
  r,imm8 (11 + 2n words, 360 of 360). Model on rounds 1-19: 12,322 of 13,404 (from 12,215,
  none lost). **Open**: ADD mem,imm8 with d16 / direct when the boundary finds four bytes
  held with the bus idle (two chained fetches then the read; three candidate rules fail), EXT
  r,imm4 behind short instructions (22 misses). **Transfers (Q90)**: JMP near / CALL near have
  no wait on the displacement word (108 of 108); the far forms wait on the segment word.
  **Interrupts (Q92, Q93)**: INT's 9.125 clocks hold right up to HALT's own pop; a request
  behind that pop releases HALT at a fixed first slot (vector read 35 clocks after HALT's pop
  for INT, 31 for NMI: NMI's event / occupation stage is not passed on the way out of HALT,
  inferred); under NMI, MOVBK needs no new event words (144 of 144), STMB's words 1-5 are
  events, DIV byte signed fits MULU's offsets (134 of 136), LDMB and the REP exits are not
  closed. Not started: the vectored rule in front of jump targets, scan figures at W = 1 / 2.
- **2026-11-17, qprobe round 21 on the socket (3,918 runs; a reading, a fresh split and a build
  check of ce9ea43; `validation/v35s/qprobe/RESULTS.md` Q95-Q99, `DIVERGENCE-r21.md`).**
  **Split of the 4,874 diverging corpus runs**, per encoding, scored by model and RTL sim:
  read with the RTL also differing on the probes 1,856 (carried by specs 13-17); read with
  the RTL exact on the probes 1,628 (the corpus state is not the probes'); partly read 492;
  probed, not read 439 (REP compares 462 by their own scorer, C7 [d16], EI); not probed 171
  (from 903); thin 11; not filed 277. 2,250 of the diverging runs have the subject directly
  behind the frame's marker (OUT imm8 1,610, PUSH 640), 1,697 of them at even alignment.
  **A state neither model nor RTL has**: X directly behind OUT imm8 at even alignment (frame
  OUT ; X ; OUT even: model 24 of 84, RTL 20; odd 69 / 66; behind PUSH 168 of 168 both);
  about 1,150 corpus runs; no rule yet (the first fetch behind the I/O cycle a clock later,
  or an early bus-idle word passing on that fetch's second-last clock: inferred from six
  traces). **Build fault**: OR / AND / SUB / XOR / ADC / SBB [BW],r16 and ADD / OR / SUB
  [BW],r8 run ADD [BW],r16's routine on silicon (66 of 66 each); the RTL 3 of 66 except ADD
  word; 189 corpus runs. **Reads behind an EU cycle (Q96; closes round 20's ADD mem,imm8
  state)**: once the first fetch behind an EU cycle is on the pins, a read requested from
  then on is not arbitrated against the chain: the chain runs until more than five bytes are
  held, then the read goes (+75, none lost; `r21m` 492 of 498, RTL 423); not so for writes.
  **EXT / INS r,imm4**: the imm4 leaves on the datum word, a bus-idle word two (EXT) or three
  (INS) words behind it (+29). The strict bus-idle word is a word kind, not a byte count (no
  run of 16,224 changes with "every word-wide pop"). New shapes: RMW with d16 / direct / two
  registers, XCH [d16], DEC and SHL 1 with d16, C7 with two registers + displacement, SET1
  word on memory by CL, TEST / CMP AW,imm16, CVTDB (19 words), DI, far transfers through
  [BW], CMP r,[BW+d16], CMP [d16],imm8. Model: 17,532 of 18,972 non-interrupt socket runs.
  Unknown: the corpus divergence behind the PUSH marker (the frame is exact in both).
- **2026-11-17, qprobe round 22 on the socket (4,026 runs; a reading, no RTL change;
  `validation/v35s/qprobe/RESULTS.md` Q100-Q107, `DIVERGENCE-r22.md`).** Read with the new
  corpus tools (`validation/v35s/qprobe/tools/`): the model on the corpus 24,101 -> 25,396
  exact of 30,536 (-12); runs both model and RTL miss 1,828 -> 899. **"X directly behind OUT
  imm8 at even alignment" is three things**: (A1, Q101a) the fetch wanted under OUT's I/O
  cycle starts on c3 + 1 but gives way a clock when a request word executed on c3 (or a V
  request executes on c3 + 1), or when the EU executed act-less words on c3 and c3 + 1 with
  no request outstanding (identical on all 23,670 socket runs to "not started on a clock
  whose executed word is followed by a bus-idle word"); it is the phase, not the form; the
  same behind OUT imm8,AW and OUT DW, never behind PUSH, a store, IN or POP; an outcome rule,
  the register unknown; corpus 256 runs. (A2, Q101b) the 0F page's commit word and SHL
  r,imm8's sixth word pass on the chain's second fetch's third-last clock (corpus 335; why
  three is unknown; not so for slot words). (B, Q102) missing bus-idle words: MULU / MUL /
  DIV r a second one (the fifth), CVTWL, IN AL / AW,DW, LODS, ADJ4, TEST m,imm16, XCH
  [d16],r (corpus 344). **Behind the PUSH marker**: a comparison artefact: the model's and
  the reader's window cut a PUSH-marker run at the first write, the lead's, in front of X;
  with the cut at the marker's own write the frame is 158 of 168 (the corrected cut is in
  `build/qp/cmp22.py` / `bc22.py` of the package). JMP / CALL near [BW]: for FF /2../5 on
  memory the three-byte test counts the bytes a fetch delivers on its last clock (A3). REP
  INM / OUTM word with CW = 0: 12 words, bus-idle fifth. Socket set: 22,378 of 23,670 (+952,
  none lost). Unread: EXT / INS behind OUT at even alignment with waits (114 corpus runs),
  stores against a chained fetch (Q33's table), Q95's open row (9 runs). No interrupt probes.
- **2026-11-17, work order 14 landed with the round 19 and 20 non-interrupt rules (full
  gate).** **Built**: the reserving request (spec 13 A1: bus value `BQ_RSV` on the word that
  releases the displacement in the C7, 81 and TEST displacement cells; `rq_rs` in the EU,
  shown as `req_ia` with `req_v` low, `req_ia` carrying the INT acknowledge only while the
  request is presented; `dr`, `rh`, `rs1` beside `dc` in the bus unit); SET1 / NOT1 r16,CL
  through the byte routine (`b1sclw` removed); the REP compares (head one word longer, exits
  26 / 27 clocks, later CMPM iterations 12 + W); JMP short's bus-idle displacement word; the
  strict bus-idle word as a `uasm` flag (the bus-idle bit plus the level the commit word
  already waits on; on every word releasing a 16-bit operand); the 0F page's register commit
  word a plain bus-idle word; SHL / SAR r,imm8, CVTBD, OUTM, the TEST cells, POP
  [BW+IX+d16], NEG / NOT / INC / DEC with displacement; PUSH [d16], CALL far [d16]. ROM
  2,669 words (the high part 1,024). No port added. **Gate**: corpus 27,604 of 30,536 exact
  at both spacings (from 25,662; 1,948 gained, 6 lost: SET1 AW,CL behind OUT at even
  alignment x3, the unread state of round 22; SHL r,imm8 by 8 as a CALL target with RET
  behind x3, a post-flush state), writes 106,824 / 106,824, chk silent; vectors 0 bad; 56
  tests; SST; program gates as before (f4_tm's timer periods move by a clock inside the same
  timing-only line; f4_tout, f5n x3, f5v x2 unchanged); f4_hwd equal. **FPGA at 17 ns:
  +3.331 / +3.367 / +3.088**; 9,532 LUT4, 642 ADD, 2,538 FF, 108 RAM_5K. Small set 15,080 of
  15,384 (builder). **Known**: the interrupt probes drop (pushed 2,960 -> 2,702 of 7,122)
  because the strict bit on MOV [d16],imm16 moves every interrupt frame's vector stores
  toward silicon against the fitted interrupt delays, which the interrupt rebuild removes.
  Not built: C_NOCH (next batch, inside the ports).
- **2026-11-17, process rulings (user).** Builders verify with the fast loop only and the
  overseer runs the one full gate at landing; the second-spacing replay and three-seed
  timing run every third landing, one spacing and seed 1 in between. Corpus tools added
  (`validation/v35s/qprobe/tools/`): the reading model on the corpus, clustering of
  divergences by state, a ROM-against-model routine check.
- **2026-11-17, the interrupt rebuild handed back and held (rulings, user).** Built in a
  worktree on top of 0272563 as spec 15 I's stage machine with spec 16's event words
  (hand-back `r19/rtl`): interrupt probes all-exact 1,634 -> 3,083 of 6,278, pc-exact 2,476
  -> 4,486, the short-pulse hang fixed, NMI_DLY / INTP_DLY / `ird` removed. Rulings: the two
  extra bits (`ev`, `pop`) on the existing `wk_nx` port are allowed beside the two handshake
  signals (`oc_rq`, `oc_dn`); the batch is not landed while f4_dma differs (silicon takes the
  DMA-end vector one instruction earlier than the rebuilt path, which has never been measured
  for that source): a socket probe of the DMA-end request comes first. Open in the batch:
  INTP0 one instruction late in CBW / INC trains and INT 2 clocks early in front of HALT
  (attributed by the builder to where the RTL pops the next opcode in NOP / INC / CBW; not
  verified).
- **2026-11-17, work order 17 landed (light gate: one spacing, seed 1).** **Built**: the
  whole write-back ALU group on memory through `rmw` (`rmw_b` removed; a build fault found
  by round 21 and by the ROM check); reads behind an EU cycle (Q95: `lc`, `ych`, `wkm` in the
  bus unit: a read whose request word executed inside the chain behind an EU cycle does not
  compete with the fetch on the clock after a chain fetch's last clock); C_NOCH inside the
  existing ports (a commit word that releases one byte presents the word-kind's unused code,
  "alt alone"; the bus unit waits it as a commit word except on the clock the fetch chained
  behind the fetch after a memory write starts: `lw`, `few`); SHL-group mem,1 with d16 /
  direct, C7 [base+index+d16], JMP / CALL far through [BW], TEST / CMP AW,imm16, CVTDB (19
  words), DI, EXT / INS r,imm4. ROM 2,763 words. No port added. **Gate**: corpus 28,127 of
  30,536 exact (from 27,604; 524 gained, 1 lost: F33 out-cvtdb at even alignment), writes
  106,824 / 106,824, chk silent; vectors 0 bad; 56 tests; SST; program gates as the previous
  landing with the same timing-only lines; f4_hwd equal. **FPGA at 17 ns, seed 1: +3.529**;
  9,505 LUT4, 2,545 FF, 108 RAM_5K; loader 3.956, useq 5.954. Builder's fast loop: small set
  15,167 of 15,384, interrupt probes pushed 2,947 of 7,122 (from 2,702, the ALU frames), ROM
  check 35 -> 16 mismatched encodings. Not built: SET1 / CLR1 / TEST1 / NOT1 mem,CL with a
  displacement (next batch).
- **2026-11-17, work order 18 landed in part (light gate: one spacing, seed 1).** **Built**:
  the missing bus-idle words of spec 18 B (MULU / MUL / DIVU / DIV r a second one as the
  fifth word, CVTWL, ADJ4A / ADJ4S, LODS, XCH mem,r, IN DW, TEST mem,imm16; REP INM / OUTM
  with CW = 0); spec 18 A3 (a decode attribute `ml` on the FF /2../5 memory cells, passed to
  the bus unit on a free code of the existing `sf_nx` port: the three-byte wait applies to
  them except on a fetch's last clock; JMP / CALL near [BW] as `P . B Y D`); SET1 / CLR1 /
  TEST1 / NOT1 mem,CL with a displacement (hold heads `eas0` / `eas8` / `eas16` that pop
  without releasing, selected by the 0F cell's `eab` bit; the release on a later word by the
  pop field's free value `PP_RD`, the loader adding the displacement's bytes by mode). ROM
  2,813 words. No port added (three free codes of existing signals used; the unmeasured
  memory forms of BRKCS, TSKSW and MOVSPB now take the bare heads). **Gate**: corpus 28,539
  of 30,536 exact (from 28,127; 424 gained, 12 lost: the predicted OUT ; MOV r,r ; IN DW
  runs at even alignment, against 123 IN DW runs gained), writes 106,824 / 106,824, chk
  silent; vectors 0 bad; 56 tests; SST; program gates as the previous landing; f4_hwd equal.
  **FPGA at 17 ns, seed 1: +2.924** (from +3.529); 9,550 LUT4, 2,535 FF, 108 RAM_5K; loader
  3.791. Small set (corrected PUSH-marker cut) 22,585 of 23,328. The ROM check
  (`tools/romcheck.py`, patched for hold heads, `pop=rd` and the `ml` decode): 7 mismatched
  encodings, none a build fault. Not built, awaiting a ruling: spec 18 A1 (the late first
  fetch behind OUT) and A2 (the commit word against the chain's second fetch); designs in
  the hand-back `r22/rtl/rtl.md`. The next landing is a full gate.
- **2026-11-17, rulings (user) after round 22.** (1) Spec 18 A1, the late first fetch behind
  OUT, may be built as a gating rule on the fetch start, recorded as measured with the
  register's identity unknown. (2) Spec 18 A2, the commit word passing on the third-last
  clock of the chain's second fetch, may be built: an explicit exception to the "every delay
  needs a machine explanation" rule for this constant, backed out if timing falls under
  +2.0 ns. (3) The three free codes used in work order 18 in place of ports are accepted,
  with the unmeasured memory forms of BRKCS, TSKSW and MOVSPB on the bare heads. (4)
  Stopping line: every state or form carrying more than 20 corpus runs is read and built;
  the rest is listed as known differences.
- **2026-11-17, landed: spec 18 A1 and A2 (full gate: both spacings, three seeds).**
  **Built** (v35_bus, two lines of v35_useq, one ROM word): A1, the late first fetch behind
  an I/O write: on the clock the write's result is delivered with a fetch pending, the fetch
  gives way one clock (keeping its slot, as EU_EPRI's) when (case 1) a memory request word
  ran on the cycle's last clock or a V word runs now, or (case 2) words with no act ran on
  the last clock and now and no request is outstanding. Registers `lo` / `lo_b`, `wkp`,
  `ry1`, `pl1`, `rqo` (`rqo`: a memory request word has run and its cycle is not granted;
  not in the design, needed: without it 147 small-set runs were lost). Case 2 is the
  outcome form; the "followed by a bus-idle word" form needs the next word's kind and was
  not built. A2, the commit word against the chain's second and later fetches: it passes
  from the fetch's third-last clock (the ruled exception; the comment and the back-out
  condition are at the constant); SHL r,imm8's sixth word is a commit word. The strict
  bus-idle word had shared the commit word's kind code and must not take A2 (226 socket
  runs lost in the model): it now presents the kind's free code flush with alt (no ROM word
  has both), the port unchanged; a fourth free-code use, of the kind ruled acceptable for
  work order 18. ROM 2,813 words. **Gate**: corpus 29,167 of 30,536 exact at both spacings
  (from 28,539; 628 gained, 0 lost; per-family tables identical), writes 106,824 / 106,824,
  chk silent; vectors 0 bad; 56 tests; SST; program gates as the previous landing (dma 7/0,
  intr 6/0, onchip 3/0, banks 5/0, traps 6/0, prio 4/0, pfxtake 10/0, serial 4/0, f5x 34/0,
  f5r 22/0, f5u 40/0; the known period-only lines periph 2, f5n 3, f5v 2); f4_hwd equal.
  **FPGA at 17 ns: +3.124 / +2.842 / +2.072** (all pass; seed 3 the lowest so far); 9,571
  LUT4, 2,542 FF, 108 RAM_5K; bus 6.605, useq 6.055, loader 3.791. Small set 22,842 of
  23,328. ROM check: 5 mismatched encodings. Runs the model has and the RTL lacks: 785 to
  207 (EXT / INS with DL about 110; forms behind PUSH at W = 0 about 30; Bcc / BR short
  behind RET or OUT at W = 1 about 35). The frame-trailer cluster (172 runs) is not carried
  by A1: the model misses it too, so it is an unread rule.
- **2026-11-17, socket round 23 (the DMA-end request; the word a request is read on).**
  1,500 runs, each twice, 0 failed (171 repeats differ in the strobe field only). RESULTS.md
  Q108, Q109; work order 19 (`qprobe/tools/r23/SPEC19.md`, with the round's analysis tools).
  **Q108**: DIC0 / DIC1 is a scanned source like INTPn, entering at the request flag: the
  request stands at the EU on the first clock of the level's 16-clock scan lattice (the one
  EI restarts; INTP0's, to the clock) that is at least 7 clocks behind the terminal write's
  first pin clock, then the event, the 2-clock occupation, 5 clocks and the replaced pop as
  for INTPn. Memory-to-memory burst on channel 0 at level 7: 104 of 104; channel 1: 104 of
  104; level 5: 104 of 104 (lattice 4 clocks earlier, as INTP0's); I/O to memory single: 74
  of 74 (threshold bracketed 5 to 8). A fixed path from the terminal cycle is rejected (56
  of 104 at best). TC0 on the pin is low from the terminal write + 0.5 to + 2.38 clocks.
  Inferred: the flag is set by the terminal count (TC0's fall lies inside the window) or by
  the word that posts the terminal write; the socket does not separate them. Not run:
  W = 1 / 2, DMA in HALT, demand release. **Q109** (existing traces): INT's latch and the
  vectored take's "replace this pop" are read on the clock the pop word runs (NOP word 1
  of 4, INC 1 of 2, CBW 1 of 3, MOV r,[BW] 4 of 5), not on the boundary word: one lead of
  9.125 clocks fits every train with the pop as anchor, none with the boundary; `r19qp0`
  78 of 78 against 50 to 62. For the held interrupt rebuild: keep its scanned path for DIC
  and move only where DIC's flag is set (from the resume to the terminal cycle); read the
  latches on the pop and hold the decision to the boundary.
- **2026-11-17, socket round 24 (the clusters over the stopping line).** 1,170 runs, each
  twice, 0 failed. RESULTS.md Q110 to Q117; work order 20 (`qprobe/tools/r24/SPEC20.md`,
  with `rtl-miss-model-exact.json`: per RTL miss row the rules that carry it). The reading
  model is now exact on 26,926 corpus runs (from 25,396, none lost) and on 1,006 of the
  RTL's 1,369 misses (from 207); small set 22,426 of 23,670. **Read**: (A1, Q113) at a
  flush target the decode lead of OUT / IN imm8 and RET runs from the clock the new
  stream's fourth byte is in the queue, not from the pop (306 rows; the "frame trailer"
  cluster was the marker OUT at a flush target); (A3, Q112) a request word on a fetch's
  last clock cancels the back-to-back fetch at any count, and a pop on the next clock
  raises it again (146); (A4, Q111) a bus-idle word that pops does not pass on the first
  clock of a fetch that starts with four or fewer held (92; a bus-idle word without a pop
  passes as before); (A5, Q114) RET near has a decode lead of 2 (54); (B, Q115) ADJBA /
  ADJBS / EI have a bus-idle third word (36), PUSH imm ends as PUSH r (8); (A6, Q110) the
  bit-field head's commit word (EXT / INS behind an I/O write at even alignment, W = 1 / 2)
  passes on the chain's second fetch's fourth-last clock, where ROL4 / ROR4 / SHL r,imm8
  stay on the third-last (112; three decompositions fit and no probe separates them: a
  ruling is asked before it is built). The 277 runs the model did not parse needed parser
  forms only (249 now exact). Section C: 297 rows the model reads with no new rule (build
  items; 152 are "fetch late by 1" at W = 1 / 2 around transfers). **Over the line and not
  read**: REP string successors 88, d16 / direct stores against the chain 78 (two more
  readings rejected), ADD4S / SUB4S / CMP4S 39, single string forms behind PUSH at W = 1 /
  2 25. CVTDB behind an EU cycle is open (42 socket runs, 6 corpus rows).
- **2026-11-17, rulings (user) after round 24.** (1) The bit-field head's second commit-word
  kind (spec 20 A6, 112 corpus runs) is not built: a known difference. (2) CVTDB behind an
  EU cycle is left as a known difference. (3) The four unread states over the stopping
  line (REP string successors, d16 / direct stores against the chain, ADD4S / SUB4S /
  CMP4S, single string forms behind PUSH with waits) are to be explored with new probes.
- **2026-11-18, the interrupt rebuild reworked to work order 19: handed back, still held.**
  Hand-back `r23/rtl/` (diff against 9614ced; worktree agent-a543213fcd602d45f). Re-based
  onto the landed tree (the corpus unchanged row by row: 29,167, none lost or gained). I-5
  built: requests read on the pop word and held to the boundary; the probe set (8,952
  runs) pc-exact 6,689 to 7,868, all-exact 4,309 to 5,084 (HEAD: 4,448 / 2,812); INT and
  NMI gain (NOP, CBW, INT before HALT now exact rows), INTP0 falls (1,102 to 903 pc-exact):
  with the late read gone the sim's scan lattice shows 3 clocks late against silicon's
  (5 / 6 against 2 / 3 mod 16) for INTP0 and DIC alike. I-4 built: DIC's flag set on the
  first clock of the terminal-count window (the TC pin's signal; no port, one intc output
  fewer); f4_dma is now one instruction early instead of one late: **the landing condition
  is not met**. The DMA transfer itself is not silicon's: the RTL's is an EU routine with a
  flush and refetch (terminal write 17 to 140 clocks late against the socket), silicon
  steals bus cycles; the round-23 families cannot be judged until that is built. Also
  open: the vector read 1 to 3 clocks late after a correct take in fetch-limited trains
  (the dispatch waits for an opcode byte it will not use); f4_tm now differs in writes;
  FPGA seed 1 +2.032 (worst path bus `d_kind` to `ex`). The pop reaches the interrupt
  controller on the unused code of the existing `x_nb` port (a ruling is asked).
- **2026-11-18, socket round 25 (the four unread states over the line, by new probes).**
  1,794 runs, each twice, 0 failed. RESULTS.md Q118 to Q126; work order 21
  (`qprobe/tools/r25/SPEC21.md`, B1 to B7, with `rtl-miss-model-exact.json` for 1,245 of
  the RTL's 1,369 miss rows and `unread25.txt`). The reading model: corpus 27,467 exact
  (from 26,926, none lost); small set 22,529 of 23,670; round 25 1,794 of 1,794. No state
  over 20 rows is left unread (largest: SHL [m],CL behind a marker 15). **Read**: (Q118)
  the "REP successors" were word string elements at an odd pointer: a pair of byte cycles
  (IY for MOVBK's write, CMPBK's first read, STM, CMPM, INM's write; IX for the others);
  (Q119) behind a store whose write is a pair at W = 0 an opcode with a decode lead starts
  one clock later (the lead counts from the pair's second byte cycle); (Q120, measured, no
  mechanism) at W = 0 the wait behind the last string element's pair is one clock longer
  (not behind a first read, an earlier iteration's write, or at W = 1 / 2; 88 corpus rows
  with Q118: a ruling is asked before it is built); (Q123) a write whose request word ran
  at or after the chain's first pin clock does not stop the chain's next fetch at five or
  fewer held: round 21's rule for reads, now for writes (the store's `G` word waits with
  the write; 48 rows); (Q125) a request armed on the clock it is due does not stop a fetch
  from the idle bus at four or fewer held (23); (Q124) MOV [d16],AW has its request word
  second; (Q122) ADD4S / SUB4S / CMP4S: a 12-word head with a bus-idle third word (the
  13-word head was a stall under MOV CL,imm8's refill), ADJ4S 9 words; a seventh-word
  bus-idle act is inferred from 2 runs; (Q121) the single MOVBK / CMPBK / CMPM / INM
  lack the bus-idle word the REP heads have (fourth word; INM fifth).
- **2026-11-18, the core builds with Quartus (light gate).** Quartus Prime 17.1 Lite,
  Cyclone V 5CSEBA6U23I7, project `fpga/v35s/synth/quartus/` (`run.sh [map|fit|sta]`, the
  Efinity top's file list and wrapper, one clock at 17 ns): 6,795 ALMs, 4,665 registers,
  36 M10K (the microcode ROM 30, the register RAM's six 128 x 8 copies 6), no DSP; Fmax
  73.6 MHz, +3.42 ns at 17 ns. Syntax edits for the 17.1 parser, none of behaviour:
  package imports in front of the module header, four `void'()` casts replaced, the
  refresh unit's `$error` checks out of synthesis, the grant struct's `len` renamed
  `blen`, declarations ahead of use in the loader, one dead-branch index kept in range.
  ROM recognition is off for the loader instance (Quartus crashes extracting a ROM from a
  decode table; which one is not isolated). Quartus warns of don't-care values on three
  struct fields in the loader (lines 382, 470, 471) and a truncation at 376: not checked
  in the netlist. **Gate**: corpus 29,167, identical run for run; vectors, tests, SST,
  program gates and f4_hwd as the previous landing. Efinity seed 1 at 17 ns +2.397 (from
  +3.124 with no logic change: 9,701 LUT4 from 9,571; seed-to-seed spread of this size is
  to be expected of the tool).
- **2026-11-18, the build-fault batch and work order 20 (light gate, three seeds).** Corpus
  30,054 of 30,536 (from 29,167: +887, none lost; F37 +122, F34 +132, F35 +146, F23 +72,
  F30 +61), writes 106,824 of 106,824; vectors 0 bad, 56 tests, SST, every program gate
  and f4_hwd as the previous landing. ROM 2,832 words. **Built**: (1) EXT across a word
  with DL as the offset: the `[n < 16]` word (88 runs; a full-word field skips it on the
  counter); (2) CH_BNEXT: the fetch chained behind a memory write does not start on the
  clock of a word that releases nothing and is followed by a bus-idle word (41). The
  assembler marks such words (`nb`, 200 words, from the ROM's static successors); the
  mark travels on the word-kind port's free code flush+alt without bi. One microword of
  look-ahead inside the routine, not the next opcode; (3) transfers to OUT imm8 with one
  wait (151): the lead counter starts at 2 when the E word waited for the staging slot
  alone (`ew`). **A compensation, not the mechanism**: silicon's word pops the arriving
  opcode on its delivery clock, the RTL's slot loads at the end of it; (4) work order 20:
  A1 the lead at a flush target, A3 the request word on a fetch's last clock (memory
  requests only), A4 the popping bus-idle word (free code disp+bi), A5 RET's lead 2, the
  ADJBA / ADJBS / EI and PUSH imm shapes, SAHF one word. INT 3's decode lead is removed
  (22 corpus runs and 8 socket runs gained, QPr8-ld-int3-n-pE-w0 lost; Q22 had measured a
  lead of 3: to be probed again). **Not built**: A6 (ruled), JMP / CALL far's request
  word without a cycle (16 runs). **Timing at 17 ns**: seeds 1 / 2 / 3 +2.423 / +1.935 /
  +1.543, 9,611 LUT4, 2,548 FF, 108 RAM_5K. All pass, but two seeds are under the +2.0 ns
  line set for spec 18 A2. The three worst paths are three different ones and none is
  A2's (seed 1 loader `mra` to the address mux, seed 2 the DMA gate to the ROM address,
  seed 3 the loader's staged byte to `ex`). A timing repair with no change of behaviour
  is ordered; whether A2 stays is the user's ruling.
- **2026-11-18, timing repair 1 (FULL gate, no change of behaviour).** 17 ns, seeds 1 / 2 /
  3: +2.760 / +3.402 / +3.221 (from +2.423 / +1.935 / +1.543); 9,759 LUT4, 2,608 FF, 108
  RAM_5K. Corpus 30,054 at both spacings, 0 rows differing from the previous landing;
  vectors, 56 tests, SST, every program gate and f4_hwd as before. Eight restructurings
  (core README "Timing repair 1"): the loader's release count precomputed into registers;
  the queue's occupancy thresholds formed in tick B; the bus unit's `fr` expanded on the
  queue's three late signals; the sequencer's ROM address select merged into one late
  bit; the EU's effective width and SIGMA-zero as registers; the loader's `d1_nx` from the
  registered decodes and the ModR/M pop's decode registered; the SFR store decode
  registered at ce_b. No port added or widened. **Measured, not in the tree**: with spec
  18 A2 removed the seeds are +3.690 / +3.479 / +2.880, so A2 costs about 0.9 ns on seed
  1 and nothing measurable on the others; with A2 in every seed is over its +2.0 line.
  Left: the pace path (ROM word, word kind, the bus hold `ph_nx`, `ex`), which needs the
  kind in ROM bits (a fourth bank). **Gate fault found**: the replay drops the
  simulator's stderr without `--diag`, so "chk silent" was never checked at earlier
  landings; the gate replays with `--diag` from this landing on (0 checker lines at both
  spacings).
- **2026-11-18, work order 21 (light gate, three seeds).** Corpus 30,181 of 30,536 (from
  30,054: +127, none lost), writes all agreeing, checker silent (`--diag`); vectors, 56
  tests, SST, every program gate and f4_hwd as before. 17 ns: +3.565 / +3.413 / +3.268;
  9,711 LUT4, 2,619 FF, 108 RAM_5K; ROM 2,848 words. **Built**: B4 the single string
  forms' bus-idle word (25 rows; bodies `sb3` / `sb4` / `sb5`); B5 the 4S 12-word head
  with the bus-idle third word and ADJ4S as its own nine-word routine (39; the
  seventh-word act not built and not needed); B6 an armed write requested inside the
  fetch chain behind an EU cycle does not stop the chain's next fetch at five or fewer
  held (48; a write posted unarmed excluded as in the model; PUSH r16's first word
  became the model's `e ro bi` shape, without which 28 runs were lost); B7 a request
  armed on the clock it is due gives way to a fetch from the idle bus at four or fewer
  held (15 of 23). **Not built**: B1 gains nothing (the pair is already in the RTL; its
  88 rows are B3's clock, Q120, awaiting a ruling); B2 and B7's other 8 rows (24) need
  the first clock of a write's last byte cycle in the loader's lead counter: no existing
  level carries it, a ruling on a bus-to-loader bit is asked; Q124 (MOV [d16],AW's
  request word second) was built and backed out: no corpus row moves and f4_dma's write
  order then differs from the socket at write 711: to be read against round 25's runs.
- **2026-11-18, socket round 26 (the open items of work order 21, INT 3, Q124, EI).** 5,042
  runs, each twice, 0 failed. RESULTS.md Q127 to Q134; work order 22
  (`qprobe/tools/r26/SPEC22.md`, C1 to C6). The reading model: corpus 27,491 (+24, none
  lost); round 26's unscheduled runs 3,606 of 3,606; of the RTL's 355 miss rows 240 are
  model-exact. **Read**: (Q127) the "lead from the pair's second byte cycle" is the pop:
  a store's N word executes on the first clock of the write's last byte cycle (INT
  stepped a clock at a time, 808 runs; for three edges an interrupt replaces a
  different instruction, so it is functional). It needs a bus-to-sequencer bit "the
  second byte cycle of an EU pair starts now": a ruling is asked; (Q128) Q120 is a second
  kind of wait word, `J`: it executes on the later of last + 1 and four clocks after the
  pair's second cycle starts (MOVBK / INM single's write, CMPBK's second read, the last
  element of REP MOVBK / STM / INM / CMPBK, and CALL near's push at SP odd). Not a bus
  state: REP STM's last element and CALL far's second push stand in the same state and
  differ. What `J` asks the bus unit for is unknown; (Q130) INT 3 has no decode lead
  (192 new runs, 16 predecessors; Q22 was its bus-idle third and fifth words); the run
  lost at the last landing is a `CH_EPRI` build fault behind MOV [d16],imm16, the same
  for eight other subjects; (Q124, Q131) MOV [d16],AL / AW have the request word second
  (119 runs on the pins); a DMA transfer never arbitrates against the store, f4_dma's
  write 711 is DIC0's interrupt push (inferred: the late scan lattice was hiding a
  clock); (Q132) EI restarts the interrupt scan on its first word: the request stands
  at the EU on E1 + 24 (87 of 92; two cells 20 clocks early unexplained).
- **2026-11-18, work order 22 C5 (light gate, three seeds); C4 and C6 not built.** The
  `CH_EPRI` give-way behind a memory write's fetch (v35_bus `fx` / `fx_b`, `chx_nx`): the
  boundary's back-to-back hold no longer holds the dispatch word in front of the rule, and
  the rule covers a fetch granted behind the write, not only one pending under the EU
  cycle. Socket: `QPr8-ld-int3-n-pE-w0` exact, `QPr26l` 216 of 216 (from 208). Corpus
  30,181, no run changed; every program gate and f4_hwd as before; checker silent. 17 ns:
  +3.623 / +3.307 / +3.114; 9,737 LUT4, 2,624 FF. **C6 (EI's scan restart on its first
  word) cannot be built in the present controller**: the stages behind the scan are
  shorter than silicon's and the late restart is what aligns them; every phase tried that
  gains round 26's EI runs loses round 17 / 19 INTP0 runs, and the take rule is not Q83's.
  It belongs to the held interrupt rebuild. **C4 (MOV [d16],AL / AW's request word
  second)** was built on trial (QPr26k 480 of 480, QPr26g 318 of 324, QPr25b 1,025 of
  1,026) and backed out: f4_dma still differs at write 711 without C6.
- **2026-11-18, microcode size: measurements and a study (no build).** The user's goal: a
  ROM nearer the V30 / V35 class. `docs/v35s-urom-options.md` (the ROM measured: 758
  distinct words in 2,848, 2,426 hold slots in 3,897 routine clocks; width and depth
  options; a 40-bit word splits only 75 words and fills 2 % of the holds),
  `docs/v35s-urom-study.md` (the iterative operations against the V20's own microcode,
  `build/deps/nuV30/docs/V20UC.TXT`, 1,028 words of 29 bits: the per-bit steps are
  already loops; the set-up and finish codes are the macro ones; about 294 of 1,073 holds
  in four families explained, the divide's and the bit fields' stretches not),
  `docs/v35s-open-issues.md` (the rulings awaited).
- **2026-11-18, work orders 23 and 24 (FULL gate, three seeds): the microcode-size round's
  first two builds.** The user's rulings are in `docs/v35s-urom-study.md` section 9.
  **WO23, ROL4 / ROR4 as one-bit rotate steps:** the composite `R4` / `v35_rot4` is gone;
  `AL_ROL12` rotates {tmpb[7:0], tmpc[3:0]} left by one (131,072 cases against the old
  function, 0 bad); ROR4 is the one-word repeat under `cnt=BITS` (8), ROL4 four step
  words (a count of 4 from the opcode needs a free `cnt` value or op3 in the sequencer:
  not granted); the register paths end in `r4_tail`; clocks with no act 38 to 14, the new
  acts marked inferred. Round 27's Q135 (1,200 socket runs): no operand dependence, ROR4
  minus ROL4 = 4 in 600 of 600. **WO24, tail sharing in the assembler:** `uasm.py`'s
  layout pass emits each identical tail once (NEXT becomes JMP at the same clock; forced
  `upc + 1` successors get copies; rep_p's E word pinned); `--no-share` gives the
  unshared ROM; `test_uasm.TailSharing` walks both ROMs from every entry through every
  branch. No RTL text changed. **ROM 2,848 to 2,160 words** (2,859 unshared, 34 copies);
  still over 2,048, so the high part stays (about 110 words used). Gate: corpus 30,181 at
  both spacings, no run changed; every program gate, f4_hwd, vectors and SST as before;
  checker silent (the builder showed it does not catch a mis-pointed shared jump: the
  per-run rows and the assembler test do). 17 ns: +3.029 / +2.588 / +3.356; 9,932 LUT4,
  2,629 FF, 108 RAM_5K (the decode table's entry numbers moved; seed 2 is 0.7 ns under
  the last landing). The gate's pin-record line has compared against step E1's records
  since then and says nothing; a reference from this landing is kept for the next.
  Documents of the round: `docs/v35s-urom-v20-techniques.md` (what keeps the V20 ROM
  small and what each technique saves here), `docs/v35s-urom-w40-layout.md` (a 2,048 x 40
  layout; its expansion in logic is judged too deep, tables in block RAM to be tried).
- **2026-11-18, qprobe round 27 installed (Q135–Q141; about 10,000 socket runs, each
  twice).** For the microcode-size round. ROL4 / ROR4: no operand dependence, 4 clocks
  apart in 600 of 600. MULU: no data-dependent clock (r8 25, r16 33 words). MUL: 36 / 43,
  +8 when the operand signs differ, +1 when that product's low half is zero, +1 more when
  the whole product is zero. DIVU r16 41 words for every high half tried (round 9's "2
  shorter" was the old reading model). DIV: +7 for a negative dividend, +2 when the signs
  differ, nothing else. A prefetch reaches only clocks 1 to 5 of these instructions
  (clocks 3 and 5 hold for it). A refresh cycle, used as a stimulus only, reaches every
  clock: it costs one clock except in fixed two-clock windows (MULU r16 one at clock 24,
  DIVU r16 one at 34, DIV r8 five, INS nine, ROR4 none), read as the words where a counted
  sequence leaves. **RTL differences found:** MUL r8 lacks the two +1 zero terms (48
  runs; MUL r16 has them); READY at fX/2 never lengthens a cycle in the RTL (silicon: one
  clock per 8 ticks of hold).
- **2026-11-18, work order 25 (FULL gate, three seeds): middle sharing; ROM 2,160 to 1,704
  words, no RTL change.** The assembler stores 70 repeated runs once, each ending in RET;
  the run's first word at each use becomes the CALL (one return register, no nesting:
  nothing reachable from a callee before its RET takes part; vector words cannot call; E
  words and the `UROM_REPP` word are left out). `--tail-only` reproduces the last
  landing's ROM bit for bit; `test_uasm.TailSharing` walks both ROMs with their return
  registers (3,998 states) and catches a call aimed one word late. Six unreachable
  placeholder words deleted (the five named and `sahf_u`). The high ROM part is empty.
  Gate: corpus 30,181 at both spacings, no run changed; **pin records 0 of 30,536 differ
  against the last landing** (the first real pin comparison since land 20); program
  gates, f4_hwd, vectors, SST as before; checker silent. 17 ns: +3.079 / +3.073 / +3.753;
  9,771 LUT4, 2,618 FF, **87 RAM_5K** (from 108: the mapper drops the empty high part).
  Also recorded: `docs/v35s-urom-w40-trial.md`, the timing trial of the 2,048 x 40 word
  (tables in block RAM in place of the word register for the late fields: +2.362 /
  +3.105 / +3.132 with five one-bit flops beside the word, 64 RAM_5K; the same tables as
  logic +1.44 to +1.69, rejected).
- **2026-11-18, work order 26 (FULL gate, three seeds): the 40-bit packer (check only),
  the high ROM part removed, MUL r8's zero terms.** (A) `uasm.py` packs every stored word
  into the L40 form (`docs/v35s-urom-w40-layout.md`: 40 bits plus an X / Y table entry),
  decodes it back and compares field for field, early bits included; the sharing pass
  refuses a jump or middle call on a word that cannot carry one. **The ROM is 1,877 words
  in this layout (1,704 without it), margin 171 of 2,048**; the 96-bit ROM uses the same
  layout so the two images can be compared address for address. X 148 of 256, Y 174 of
  512; the NT pages are full. TRAP's B carries the vector number. Three source edits
  (rep_stm, rep_cmpbk, rep_cmpm c5) and two delay calls taking their first clock as a
  word; no clock moved. (B) v35_useq has one 2,048-word ROM (`hi_b`, `rah`, banks b3..b5
  gone); the assembler fails above 2,048. (C) mul8's negation path has the two + 1 zero
  terms by mul16's mechanism: round 27's r27b 756 of 756 (from 708); mul_m8 unchanged
  (not measured). Gate: corpus 30,181 at both spacings, no run changed, 0 failed, 0
  incomplete; pin records 0 of 30,536 differ; program gates, f4_hwd, vectors, SST as
  before; checker silent. 17 ns: +2.921 / +2.943 / +2.846; 9,574 LUT4, 2,625 FF, 87
  RAM_5K.
- **2026-11-19, work order 27 (FULL gate, three seeds): the core reads the 2,048 x 40
  microcode ROM.** v35_useq reads `v35_l40_rom.hex` (40 bits) with the X table (256 x 18:
  alu ax ay wf cnt) and the Y table (512 x 35) in block RAM, clocked at `!reset_n || ce_a`
  in place of the word register for the late fields; the early fields (K's bits, POP, WID,
  RA, RB, SEQ's decode, the target) are flops of the ROM read as before. Five one-bit
  flops stand beside the word for the facts read before the tables answer: POST and KW
  (EU), SUSP, IVEC, FINT (sequencer). No port added; the interface budget is unchanged.
  The 96-bit ROM remains as a simulation-only reference: under `+v35_chk` the assembled
  word is compared whole with it every clock (shown to fire on one planted ROM bit and
  one planted X bit). The checker's limit: a run that hangs loses its output, so the gate
  also requires 0 failed and 0 incomplete. The assembler writes the L40 files in every
  build and `--check` covers them. Gate: corpus 30,181 at both spacings, no run changed,
  0 failed, 0 incomplete; pin records 0 of 30,536 differ against the last landing;
  program gates, f4_hwd, vectors, SST as before; checker silent. 17 ns: +3.432 / +3.174 /
  +2.968; 9,603 LUT4, 2,568 FF, **64 RAM_5K** (87 before; 108 at the start of the
  round): main ROM 20, X 1, Y 4, the rest 39. Not built in: the main ROM forced to
  1,024 x 5 blocks (16 blocks in place of 20; the builder measured +3.257 / +3.002 /
  +3.088, 60 RAM_5K).
- **2026-11-19, work order 28 (FULL gate, three seeds): the loader's decode tables out of
  block RAM.** The loader's source has no memory, but the mapper had built 33 RAM_5K from
  the generated `case` tables: 29 for the dispatch's second level (`df <= dsp_f(op_nx,
  mp_nx)`, retimed into 256-entry columns of the second byte per opcode, about 276 columns
  in one 14-block ROM, duplicates not merged) and 4 for two copies of `v35_udec1`. The
  generator (`uasm udec2_forms`) now proves per opcode which bits of the second byte the
  second decode reads: {mod is 3, reg} for 60 opcodes, {mod, one mode bit, reg} for 14,
  the whole byte only for the 0F page and the REP page; equal tables share a case item
  (45 items); entries are 11 bits (`UENT_W`; `UADDR_W` stays 12, it is the 96-bit
  reference word's target width). The dispatch reads the registered first decode
  (`d1_nx`), `df` carries op3 and w (`dm` gone), `d1r` holds in reset. The old table stays
  as `v35_udec2_ref` for `+v35_chk`; `test_uasm.CompactDecode` compares both on all 65,536
  (opcode, byte) pairs. No port added; ROM / X / Y images identical. Gate: corpus 30,181
  at both spacings, no run changed, 0 failed, 0 incomplete; pin records 0 of 30,536
  differ; program gates, f4_hwd, vectors, SST as before; checker silent. 17 ns: +3.227 /
  +3.672 / +2.344 (the builder's seeds 4 and 5: +3.320 / +3.263; the base on five seeds
  +2.668 to +3.432; seed 3's worst path is the EU's X -> c_snz, untouched, and that
  seed's worst before too; loader alone +4.164 from +3.670). 9,543 LUT4, 2,599 FF,
  **34 RAM_5K** (64 before): loader 3 (one udec1 copy 2, the REP page 1), useq 25,
  regram 6.
- **2026-11-19, work order 29: the secure mode's opcode translation table** (committed on
  the builder's fast gate at the user's request; the FULL gate's result is the next
  entry). The user's rulings: the table is a block RAM loaded a byte at a time through a
  top-level port (`tt_we`, `tt_a[7:0]`, `tt_d[7:0]`); the core does not initialize it (no
  1:1 default, no loaded flag: a user who does not want the feature holds N/S at N; in
  the FPGA an unloaded table reads 00h); prefixes and the opcode behind a prefix / REP /
  BUSLOCK are translated, the 0F page's second byte, ModR/M bytes and operands are not
  (the data book: "only the first byte of each opcode is decoded"); the interface budget
  raised for exactly bus -> queue `dlv_nx`, queue -> loader `tq[15:0]`, eu -> loader
  `psw_md`. Site (design: the staging load, the table read one tick early): two 256 x 8
  RAMs in v35_queue addressed at ce_a from the next clock's two head bytes; the loader's
  twin flops `sx0_b` / `sx1_b` take `MD ? raw : table` at ce_b beside `sb0_b`; the staging
  load picks between flops at the depth it had. Every MD writer is followed by a flush.
  Harness debug register C2h writes one entry; the runner refuses N/S low on a socket
  lane; the program gates and the vector bench load the 1:1 table as stimulus (the vector
  bench directly into the arrays: its snapshot driver cannot use the port).
  validation/v35s/secure.py: 1:1 table in secure mode equals normal mode on every bus
  cycle (no clock cost); a permutation table with the program encoded through its inverse
  equals the plain program, N/S low from reset and entered through BRKS; eight negative
  controls differ as predicted. Builder's fast gate: corpus subset 8,313 of 8,502, 0 rows
  and 0 pin records differ with the table unloaded and with the permutation loaded;
  vectors 0 bad; 17 ns +3.221 / +3.314 / +3.179; 9,568 LUT4, 2,617 FF, 36 RAM_5K.
- **2026-11-19, work order 29's FULL gate (three seeds).** Corpus 30,181 at both spacings,
  no run changed, 0 failed, 0 incomplete; pin records 0 of 30,536 differ against the last
  landing; program gates, f4_hwd, vectors, SST as before (every line of the gate equal to
  work order 28's); checker silent; secure.py's 14 benches all as predicted. 17 ns:
  +3.221 / +3.314 / +3.179; 9,568 LUT4, 2,617 FF, 36 RAM_5K. The EU mapped alone reads
  +2.350 (from +4.515): a module-alone figure, not seen in the top (not looked into).
- **2026-11-19, the WTC's memory blocks measured (validation/v35s/wtc.py, programs
  f4_wtc_*; socket receipts taken twice, equal).** The user's finding: the core reads one
  WTC field (bits 1:0) for every memory cycle and fetch, and READY (PMC1 bit 7) through
  that field alone. The silicon follows the data book: the field is chosen per bus cycle
  from that cycle's own address (fields 0..5 the 128K blocks from 00000h, field 6
  C0000h-FFFFFh, field 7 all I/O), for fetches, data reads and writes, each half of a
  word that straddles a block boundary, stack and string cycles, DMA cycles; READY
  lengthens only cycles in a block whose field is 3; on-chip accesses take no waits from
  any field; refresh waits are RFM's alone. "By block" predicts 95,082 of 95,082 measured
  cycles. In simulation all eight programs differ in the windows with a non-uniform WTC.
  Also found: the core gives on-chip accesses field 7's waits (the silicon none). Not
  measured: READY on memory writes (the harness lane cannot place it), the interrupt
  acknowledge, DMA with an I/O side. The fix is the next work order.
- **2026-11-19, work order 30: the wait field per bus cycle (v35_bus only; no port, no
  microcode).** A memory cycle or fetch takes the WTC field of its own address's block
  (A19-A17, the top two blocks one field), an I/O cycle field 7, an on-chip cycle none
  (3 clocks, no READY; it took field 7's waits). The fetch's field is read straight from
  the fetch address at the grant, an EU or DMA request's from the request register. A
  first version registered the fetch's field at ce_b; the full gate's secure negative
  control A_nc_modrm (a runaway that executes MOV PS,r16, which does not redirect the
  queue) granted a fetch at the new PS with the old block's field, caught by the new
  checker; the register was removed. validation/v35s/wtc_ps.py is the directed sim bench
  for that sequence (four WTC values; fails on the first version). All eight f4_wtc
  programs equal their socket receipts by window. Committed on the gate so far (the
  program sets still running): corpus 30,181 at both spacings, no run changed, write
  data unchanged, checker silent; pin records: 30,532 runs are the last landing's with
  one step of -64 ticks after the prelude's WTC store (its on-chip cycle 5 clocks to 3),
  the four F0w runs with field 7 at 2 lose 2 clocks at each later on-chip store too;
  lint, vectors, 75 tests, SST clean. 17 ns: +3.133 / +3.208 / +2.979; 9,611 LUT4,
  2,617 FF, 36 RAM_5K. Remaining against silicon (the next work order, measured by
  validation/v35s/onchip_t.py): the first WTC store takes effect one fetch late (an SFR
  word is two byte cycles on silicon); periph's one-shot period 829 against 855.
- **2026-11-19, work order 30's FULL gate.** The rest of the gate as the last landing's:
  program sets (dma 7, intr 6, onchip 3, banks 5, traps 6, prio 4, pfxtake 10, serial 4
  equal; periph 2 equal 2 differ, the differing periods moved: the one-shot 829 clocks
  against silicon's 855), the fuzz sets unchanged, f4_hwd equal; wtc 8 of 8 equal by
  window; secure.py's 15 benches as predicted; wtc_ps 4 pass. Sim receipts refreshed.
- **2026-11-19, on-chip access timing measured (validation/v35s/onchip_t.py, programs
  f4_oc_{a,s,k,t,v,e}; two captures, 2,305 of 2,305 windows equal).** On silicon an
  on-chip access is timed as an external cycle at 0 waits (21 instruction forms and three
  REP strings equal their external twins to the tick; the prefetcher blocked as during an
  external data cycle). A word in the SFR page is two byte cycles, low address first
  (+3 clocks; internal RAM words one cycle). The timer unit's registers (FF80h-83h,
  88h-8Bh, 90h, 91h) stretch each byte cycle 1 to 6 clocks to end on a free-running
  6-clock grid (the MD0 variation in f4_wtc_x). A store takes effect early in its cycle
  (a port pin half a clock after the start). The core: reads equal; stores 2 to 2.5
  clocks long (the EU's hold); SFR words one cycle; no timer wait. Windows equal in
  simulation at this commit: a 155/239, s 99/187, k 49/55, t 291/552, v 873/1154,
  e 41/118. Also seen on external memory (not pursued): MOV byte m,imm8 12 clocks
  against 9 to 10.5; a prefixed accumulator read after an OUT 1 clock long; REP MOVBKW
  at odd addresses 1 clock short. Inferred, not measured: the internal cause. Not
  measured: RAMEN = 0, a relocated IDB, on-chip accesses by DMA / interrupt frames /
  macro service, a word at an odd SFR offset, the /12 and /128 count-out phases.
- **2026-11-19, work order 31: on-chip accesses timed as the silicon's (full gate).**
  (A) An on-chip store lands in its cycle's first clock and the EU's hold after it is
  gone (`wr_hold`, `wr_hold_nx`, the sequencer's `st_hld`, `prc_at`); a new checker
  reports any dispatch while an on-chip store is unlanded (silent; the ordering is
  checked, not proved by construction). (B) A word in the SFR page is the bus unit's
  pair: two byte cycles, low address first, lanes by the byte's address; each half
  writes its byte, the 16-bit timer registers take the word at the high byte's cycle;
  internal RAM words stay one cycle. Macro service's word-mode SFR transfer is the one
  microcode path that gets longer (not timed on silicon). (C) Timer-register byte cycles
  are granted 4 clocks and hold their wait until a modulo-6 counter of the CPU clock
  from reset (bus unit) reaches its release phase. **The release phase is offset by the
  33 clocks the silicon's prelude spends on refresh and the core does not** (one
  constant for every window; it becomes the silicon's from-reset value when refresh is
  built). Port budget lowered: eu out 38 to 36, useq in 30 to 28, eu to useq 14 to 12.
  onchip_t windows equal: a 215/239, s 163/187, k 51/55, t 520/552, v 1154/1154,
  e 74/118 (none lost; the rest are external-memory differences, chiefly MOV byte
  m,imm8 3 clocks long, a store behind NOPs at 2 waits 1 clock long, and the silicon's
  half-clock pin phase). wtc 8 of 8 by window and the first WTC store now takes effect
  at silicon's fetch (whole-trace first differences are the fetch / CALL-push order).
  Corpus 30,181 at both spacings, no run changed, write data unchanged, checker silent;
  pin records: every run the last landing's records with time shifts only, three
  classes by WTC family (elapsed -200 / +48 / +80 ticks: the prelude's three on-chip
  stores). Program and fuzz sets, f4_hwd, vectors, lint, 75 tests, SST as the last
  landing; periph 2 equal 2 differ (tout_os 829 against 855; tm1_i6 589/611 against
  599/615; tm0_os and tout_alv1 now within tolerance); secure 15 as predicted; wtc_ps
  pass. 17 ns: +2.997 / +3.424 / +3.402; 9,397 LUT4, 2,628 FF, 36 RAM_5K. Not measured
  on silicon: word reads of a running timer (two byte reads 6 clocks apart), words at
  odd SFR offsets, the /12 and /128 count-out phases.
- **2026-11-20, from-reset phases measured (validation/v35s/phase.py, programs f5_ph_*;
  every capture twice).** Reset to the first fetch is 25 CPU clocks on silicon and in the
  core (the chip's clock divider is not reset; a refresh cycle at boundary 15, the fetch at
  25). DI is 4 clocks, equal to the core, so it is not the cause of f5_si_edge's clock.
  **The interrupt request's path is not on a free-running phase from reset:** with a
  request pending, the take after EI is at one fixed clock at every absolute phase (136
  windows, store-set and INTP0 requests); the core alternates with absolute parity, from
  v35_intc's `ph` toggle against a scan counter EI restarts. The pin's two-clock lattice
  follows the distance from the store before it, not reset. **The timer chain is fixed to
  reset and refresh does not move it:** a timer register's cycle ends at 0 mod 6 clocks
  from the first clock after the release, /6 count edges at 2.5 mod 6, the /12 one-shot
  count-out at 8.5 mod 12, /128 count-outs on /12 edges (132, 132, 120 apart); the core
  restarts its prescalers at the store (72 and 128 exactly). Silicon's grid constant from
  reset is 3; the core's is offset for the corpus prelude's missing refresh, and that
  offset differs by prelude. Also seen: an 18-clock period from the request-control store
  while a request is pending with IE 0 (two phases of it take early / 18 late); a periodic
  TM0 request taken on a 16-clock lattice locked to the timer, not EI. Trial (not landed):
  the request's passage as one register on the scan counter's low bit makes all 15 intr
  programs equal and puts two TOUT periods outside tolerance. Not measured: the scan
  counter's phase from reset, NMI and INT against phase, the /128 tick to better than 4
  clocks. The committed f5_si_edge sim receipt predates 5e17029 (stale).
- **2026-11-20, work order 32 landed (user ruling: land with the stated losses).** v35_intc:
  the free-running `ph` toggle is gone; the request's passage is one register on the scan
  counter's low bit, the INTP0-2 sampler runs on the same bit, and a store to a request
  control register restarts the scan as EI does. v35_timer: the count clocks are one chain
  from reset (a copy of the bus unit's divide-by-six, halved for /12, a seven-bit count whose
  carry is held to the next /12 edge for /128); a start is taken by the first edge of its
  clock instead of restarting the prescalers. G_REL moved to v35_front_pkg, still 0. No port,
  no microcode change. Full gate: corpus 30,181 exact at both spacings, pin records 0 differ;
  intr 15 of 15 equal (f5_si_edge with them; the gate now runs the whole set); phase takes in
  front of silicon's instruction 177 of 192 (was 21), the rest the 18-clock phases; one-shot
  /12 count-out 76 or 82 after its start and /128 count-outs 132 132 120 apart, as silicon;
  onchip_t, wtc (8 by window), wtc_ps, secure, f4_hwd, fuzz sets, vectors, lint, tests, SST as
  the last landing. **Lost:** periph period tests tm0_i6, tm0_md, tm0_os, tm0_os128 and the
  three TOUT tests leave the 16-clock tolerance (tm1_i6 enters it); 95 qprobe schedule runs
  (160 gained; 1,632 of 13,950 exact). One cause for the periph rows: the take's lattice is the
  core's 16-clock scan round restarted by the TMIC store, where silicon's is locked to the
  timer; not built. Also not built: the 18-clock round, EI's restart at its first word (a
  port), a second stage for INTP_DLY (the flag read wants 5, the takes 11). 17 ns: +3.239 /
  +2.718 / +3.199 (seeds 4, 5: +3.589 / +3.296; seed 2's worst path is in the loader,
  untouched); 9,404 LUT4, 2,606 FF, 36 RAM_5K. User ruling of the same day: the grid constant
  goes to silicon's 3 in the next build.
- **2026-11-20, the take lattice measured (validation/v35s/lattice.py, 27 programs f5_la_*,
  983 windows, every capture twice, all repeat-equal).** The lattice of a request's take is
  the level scan's 16-clock round, locked to the scan's last restart and nothing else. The
  scan is restarted by IE rising through any instruction (EI, POP PSW, RETI) and by a store
  to any request control register; not by the timer's start, a count-out, the request, the
  take, FINT, DI, a PSW load with IE already 1, other SFR or RAM stores, or HALT. A periodic
  source's takes are therefore re-locked by each handler's RETI: take to take is K + 16 m
  with K the handler's and return path's constant (periph's 599 599 615 599 is K = 599). The
  earlier reading (locked to the timer) is withdrawn: f5_ph_t had K = 0 mod 16. One counter
  serves TM0, TM1 and INTP0; level L is examined 2 L clocks after the restart. **The 18 is
  16 plus an offer slot:** with IE 0 each level holding an unmasked request adds two clocks
  to the round (18, 20, 22, 24 for one to four levels); HALT with IE 0 is released at a slot;
  IE rising in a slot's first clock takes that slot's request at once, in its second clock
  does not restart, anywhere else restarts. **The pin has one delay** (3 to 5.4 clocks to the
  flag read, 3.1 to 4.6 to the take); the core's INTP_DLY 11 hides that it accepts an internal
  request 7 to 8 clocks late for a lattice point. Trial (not landed): any IE rise restarting
  the scan re-locks at RETI but 9 clocks late after a PSW pop; the restart belongs at the PSW
  word's read. Unexplained: four windows where EI lands in the second clock of one level's
  slot beside another pending level. Not measured: a request blocked by the in-service level,
  macro service, NMI and INT, the time base as a source, a control store inside a slot.
- **2026-11-20, READY measured (validation/v35s/ready.py, 20 programs rdy_*, every capture
  twice).** READY is looked at only under wait field 3 with PMC1 bit 7; fields 0, 1, 2 and
  on-chip cycles ignore it. **Sampling point:** CLKOUT's falling edge in the middle of the
  cycle's third state (the first built-in wait), 1.0 clock after the strobe's fall (/MSTB on a
  read or fetch, /IOSTB on I/O), then every clock; the strobe rises 2.0 clocks after the first
  sample that finds READY high. The built-in waits are not counted first; a low pulse ending
  before the first sample is ignored. Latest READY-high that still ends the cycle / earliest
  that stretches, ticks after the strobe's fall: fX/8 +31 / +32, fX/4 +14 / +15, fX/2 +7 / +8.
  **Memory writes obey READY** (the earlier "not extended" was the harness timing READY from
  the strobe, which on a write falls only after a high sample): with READY low as a level the
  write stalls with /MREQ low, address and data out, /MSTB high. **The core at f72264a samples
  half a clock early** (`rdy_q` loaded at ce_b, used at the next ce_a): steps 17 ticks early at
  fX/8, and at fX/2 it never sees the harness's READY; the earlier equality at a 160-tick hold
  was a coincidence. Trial (one line, `rdy_hold` reads the pin flop at ce_a; not landed): all
  sweep and kind programs equal within 2 ticks (the two pin flops). Equal in the core already:
  one wait per clock of READY low (to 34 waits), all access kinds, per-block and I/O fields,
  pins frozen during the extension, the next cycle 1.0 clock after the end, an interrupt
  waiting for the stretched cycle. Second difference: a near CALL behind a cycle of 4 or more
  waits pushes 2 to 3 clocks early in the core; mechanism not found. Not measured: a write's
  sampling edge and a late READY fall (the harness's fall is fixed at strobe + 120 ns), READY
  at reset release, DMA with a stretched cycle. Seen in passing: a byte write's idle lane and
  idle address pins differ; RETF's pops 10.5 clocks apart on silicon at fX/2 against 9.
- **2026-11-20, READY measured from /MREQ (harness version 3: READY low from `delay` to
  `delay + hold` ticks after a cycle's /MREQ falls, single ticks, by direction and block;
  docs/v35s-harness.md; programs rdy_m*, every capture twice).** One rule for every external
  cycle (read, fetch, IN, OUT, memory write byte / word / odd halves, at fX/8, fX/4, fX/2):
  READY is sampled on CLKOUT's falling edge 2.0 clocks after the falling edge on which /MREQ
  falls, then on every following falling edge; a point sample (30 ns or less at fX/4 and
  fX/2), bracketed from both sides (fX/8: latest rise that ends the cycle +63 ticks, earliest
  that stretches +64, latest fall that stretches +62, earliest that does not +63). One sample
  low is one wait. Nothing is sampled after the first high sample (a READY low after a
  write's /MSTB fell does nothing); the cycle ends 2.0 clocks after it. A write's /MSTB falls
  1.0 clock after the first high sample and rises 1.0 later; address, data and R/W stand from
  the start. No carry-over between cycles. The core at ac17084 samples half a clock early,
  reads and writes alike; with the one-line fix (`rdy_hold` reads the pin flop at ce_a; not
  landed) all 12 sweeps are equal (1,950 run-windows, 44 within a tick of an edge), one tick
  early from the pin flops. The previous image is kept as build/.../v35s-harness-v2.hex.bin.
  Not measured: READY at reset release, with DMA, with refresh; the scheduled READY level
  (built, not run).
- **2026-11-20, the request's passage to the EU measured (validation/v35s/passage.py, 90
  programs f5_pa_*, 2,742 windows, every capture twice). Work order 33 is held by the user
  for this (its 8-clock passage had no mechanism).** The eight clocks are silicon's and are
  not the controller's: the INT pin, which bypasses the level scan, has them too (INT's
  rise to the first /INTAK 15 clocks at the earliest, 10 to the boundary; the core 9). The
  cut-off is a count of CPU clocks in front of the instruction boundary, sharp to one clock
  over 36 sled lengths and 13 instruction kinds, the same against a 2-clock INC and a
  40-clock DIVU and at fX/8, /4, /2. IE sits in front of the passage: with INT standing,
  POP PSW ; INC ; INC takes after the second INC (one instruction when it is long enough);
  the core takes after one. EI raises IE in its first to third clock of 13 (its eight idle
  words are the passage); POP PSW and RETI load IE at the PSW word's read: work order 33's
  move of EI's IE to its third word is silicon. NMI and controller requests need 4 clocks
  more than INT (14 to the boundary), and in those clocks the bus unit shows a two-clock hold
  6 to 8 clocks before the earliest boundary (every NMI and controller program, 0 of 128 INT
  windows; no single rule found). The last stage is a sample at a point of the ending
  instruction: the earliest vector read moves by 0 (INC, ROL, DIVU, shift by CL, memory
  read), +1 (CVTBW, a REP string's end), +2 (store, PUSH, NOP, MULU), +4 (BR); the core has
  +1, +1, +4 for store, MULU, BR. A taken request's vector read is 3 clocks behind BRK 3's
  from the same boundary; no fetch starts from two clocks before a boundary that takes. A
  standing HALT is left 16 to 17 clocks after the request (INT and NMI). Work order 33 as
  built reproduces the scan-side tables but places its 8 wrongly (the slot 4 to 5 late after
  a restart, the passage 4 to 5 short). **Still without a mechanism:** what the 8-clock line
  is (three independent readings give 8; nothing shows on the pins). Tests named to decide
  it: an INT edge against a level-0 slot, IE cleared inside the passage, FINT releasing a
  blocked request. Not measured: register-bank response, macro service, INTP0 against a
  boundary. "Boundary" here is the vector read less 16.
- **2026-11-20, the passage's three deciding tests (passage.py programs2, f5_pb_*, 20 programs,
  609 windows, every capture twice, all repeat-equal).** The eight clocks are a fixed delay
  behind a held request bit and stay without a mechanism. **The input is a flip-flop:** an INT
  pulse two clocks wide is taken (18 clocks after INT fell), one clock wide is not; raise,
  drop, raise takes at the first raise's boundary. **IE gates both ends and clears it:** INT
  pulsed with IE 0 leaves nothing; a request DI or POP PSW overtakes is never taken with IE 0
  at any of 25 clock positions (INT and controller); a caught pulse, DI, EI: no take (25 of
  25). No commit point. **INT and the controller share the one bit, first come:** INT beside a
  TM0 request wins only when its edge is 3 clocks or more ahead of the request's slot, at
  level 7 as at level 0; the choice is made at the slot (about 14 clocks before the boundary),
  the loser is served afterwards. **Not the scan:** INT and NMI latencies are constant over 32
  single clocks and 4-tick steps with the scan's phase fixed; no lattice of 8 or 16. **New
  scan rule:** with level P in service the round is 2(P+1) clocks (8 at P = 3, 12 at P = 5),
  set by the in-service level; after FINT the count runs on upward and the release enters at
  the scan. NMI: a 16-tick pulse is caught, 12 is not. Ruled out for the eight clocks: the
  scan or half a round, a shift of the pin's level, a level that must stand for 8 clocks, an
  EU-only stage, a commit point, priority resolution. A shift register and a counter behind
  the bit cannot be told apart. The core (both trees) needs INT to stand 14 clocks, keeps a
  16-clock round with a level in service, and with a 13-clock INT pulse reads a vector at
  0006xh no request has (not examined). Not measured: a one-clock pulse at other phases, NMI
  beside INT, a mask store or ISPR clearing inside the delay; the bus hold's rule.

**2026-11-20, request-passage probe, third set (`validation/v35s/passage.py` actions `pc`, `pcb`,
`pcrows`, `pco`; programs `f5_pc_*`, 50 programs, 1,722 windows, two socket sessions, 50 of 50
EQUAL):** measurement only, no RTL. **The controller's extra clocks:** from the clock a slot
  (or NMI's catch) sets the request bit to the instruction's look is 14 clocks against INT's 8:
  6 more set to set (the earlier "4" is pin to pin, work order 35's "5" is the 6 less the set's
  own clock). They are 6 silent clocks in which the request can be withdrawn without a trace,
  the two-clock on-chip cycle that holds the bus unit, then 6 silent clocks. Independent of
  level, source (TM0, INTP0, stored flag, NMI), a level in service and other pending or masked
  requests. **The vector is fixed at the set:** a better level arriving afterwards changes
  neither vector nor clock. **Cancellable up to the look:** a mask store, a flag clear or any
  request control store cancels the take; a store rewriting the register as it stands drops
  the bit and the request is found again with its 14 clocks. The two-clock cycle is not run
  when the mask is written within about 4 clocks of the set and never with IE 0. When the
  request vanishes in the looking instruction, 10 clocks pass with no bus cycle and no take.
  Not explained: what the cycle carries and why it sits 6 clocks after the set; the onset of
  the dropped entry. **The look is one fixed clock of the instruction's own routine, not held
  open to the dispatch:** a store with 0, 1, 2 waits has the same latest edge to the tick (INT
  9 clocks before the write's start, NMI 13.5), OUT with 0 and 2 I/O waits likewise. INT's
  latest edge to the next dispatch: 10 (INC, MULU, DIVU, shift by CL, memory read, BR), 11
  (CVTBW, store, PUSH, on-chip store), 12 / 13 (store with 1 / 2 waits), 11 / 13 (OUT with 0 /
  2 waits), 12 (NOP, XCH): NOP, XCH and CVTBW look 2 clocks after dispatch as INC does, with
  2, 2 and 1 clocks behind the look. Not explained: MULU's look 2 clocks earlier for NMI and
  TM0 than for INT; the vector read 3 clocks later behind BR and the on-chip store for NMI.
  Not measured: a DMA end as source, strings, a store to a six-clock-grid register (the f4_dma
  case), serial sources, macro service. Work order 35's tree against this: the count is right;
  it resolves priority after the set, takes a masked request at the mask store's end, keeps
  the set through a request control store, and its `e_pend` makes the INT sample follow the
  dispatch (1 to 3 clocks late behind stores, OUT, CVTBW, NOP, XCH). Boundaries equal over
  1,704 windows: base 971, work order 35 1,451.

**2026-11-20, request-passage probe, fourth set (`validation/v35s/passage.py`, programs
`f5_pd_*`, 62 programs, 2,106 windows, two power-ups, 62 of 62 EQUAL):** measurement only.
  **A store to a six-clock-grid register looks at the same fixed clock from its dispatch as
  any other store; the grid wait sits behind the look as wait states do.** Latest INT edge at
  the store's dispatch D + 0 (NMI D - 4.5) for a P0 latch store, DMAM0, an external store and
  for TMC1 / MD1 at all six grid phases (wait w = 1..6, never 0): 11 + w clocks to the next
  dispatch. TM0 and a DMA end as sources agree. Only the timer unit's registers wait on the
  grid; DMAM0, DMAC0 and the channel block are 11 clocks at every phase. **f4_dma's `dic`
  take:** the store there is a PS-prefixed external store at two waits, not a grid store;
  DIC0's request is raised in the last transfer, about half a clock before its write strobe
  starts (not at the end of the DMA service), then runs the level scan and the usual 14
  clocks; the store behind the burst writes 22 clocks after the burst's last write ends and
  8 of 16 scan phases take there (6 of 16 with no waits). The core's burst tail is 21 to 24
  clocks longer than silicon's (last write end to the next store's write 37 / 46 against 16 /
  22 at 0 / 2 waits) and its request later by about as much, which is why a sample held open
  to the dispatch (`e_pend`) was needed to pass; no store kind has an open look. Not
  explained: NMI's cut-off 4 clocks earlier in the two-wait, queue-not-full frame (2 are the
  write starting early); the fetches behind the store 3 clocks late on NMI's last four taking
  edges. Not measured: the DMA flag against a strobe with waits, single-step and demand
  transfers, channel 1, a word store to a grid register, TM0 / TM1 count registers.

**2026-11-21, landing of work orders 34, 36, 37 and the READY sample fix (the interrupt rebuild,
work orders 35 / 38, is not in it):**
  - **CLKOUT on P07** (`v35_sfr.sv`): with PMC0 bit 7 the pin's register loads the CPU clock's
    level (1 from the clock's edge, 0 from its middle); 50 % duty at every PCK, no gated or
    derived clock. Against the socket (`validation/v35s/clkout.py`): the ten scope receipt sets
    and HALT EQUAL with silicon's one-tick lead declared; PM07 = 1 does not block it.
  - **Port pins take an SFR store at the clock's edge before it lands** (new port `sfr_pend`,
    v35_bus to v35_sfr, registers only, allowed by the user 2026-11-20): select and deselect
    shapes are silicon's (no runt with the latch at 1, a high runt with it at 0, the released
    pin high) and the pin is at silicon's 2.47 / 2.5 clocks (fX/8) and 2.375 / 2.5 (fX/2) from
    the next fetch; f4_tout's deselect to marker 2418 (silicon 2418 / 2419). The rule is for
    every output port bit.
  - **PCK changes only at the X1/8 divider's wrap** (`v35_top.sv`): the divider runs free from
    reset and a PRC store's PCK is taken at its first wrap, so the clock stays on the reset
    grid (silicon: every change at one X1/8 phase, a rise, a whole first phase).
  - **READY is sampled at the cycle's position 2 directly** (`v35_bus.sv`, `rdy_q` deleted):
    `ready gate --edge-ticks 2` 8 EQUAL (0 before). The pin is to have a single flip-flop
    (user's ruling).
  - **Harness:** version 3 had put READY's delay register on C2h, the simulation-only secure
    table load's address, so the secure bench failed from 56f00ac on; the table load is now
    C8h and the bench reads as predicted. The model lane's scope field P0 carries the core's.
  - **Silicon facts recorded, not built:** in STOP CLKOUT stops high at the rise 10 CPU clocks
    after the clock STOP starts in, at every PCK, no bus cycle in them, mechanism not found
    (user's ruling: left unbuilt; needs a port from the interrupt controller); it restarts
    with a fall aligned to X1, runs through the 2^19-clock settling count. Changing fX/2 to
    fX/4 upsets silicon's bus unit in 9 of 9 alignments (stalls, malformed cycles, runs that
    never end) with CLKOUT clean: a chip malfunction, not built. HALT's release vector read is
    37 clocks after the NMI on silicon, 34 in the core.
  - **Gate (land37):** corpus at both spacings RTL-exact 30,181 of 30,536, lost 0, gained 0,
    0 pin records differ; every program and fuzz set as the baseline but ready (8 equal);
    secure bench as predicted; three seeds at 17 ns +3.053 / +3.400 / +3.144; 9,465 LUT4,
    2,646 FF, 36 RAM_5K.
  - **Losses accepted by the user, all from the 3-clock SFR-store excess:** f4_tout's timer
    edge to deselect 6432 (exact) now 6416 in three places; f4_ms and f4_sio pin records 16
    ticks farther from the socket; clkout part C windows 6 of 9 equal (7); clk_pk28_7 and
    clk_pk24_7 change clock 36.5 (silicon 34.5; 34.5 before by coincidence).

**2026-11-21, request-passage probe, fifth set (`validation/v35s/passage.py` action `pe`,
programs `f5_pe_*`, 15 programs, 600 windows, two power-ups, 15 of 15 EQUAL):** measurement
  only. **IE rising in the first clock of a slot takes that slot's request at once, whatever
  better level is also pending** (EI, POP PSW, RETI; pairs 6/3, 7/0, 3/2 and sources
  exchanged; a real handler FINT ; sled ; RETI with levels 3, 5, 6 pending): the worse
  level's vector is read at the first boundary (EI 34 clocks after mark 1, POP PSW 35 after
  the PSW word's read, RETI 44), the better level after its handler. A rise in the slot's
  second clock gives the better level at its next slot. Work order 38's `sl_ie` (such a slot
  does not claim when a better level requests) is not silicon's rule; f3_prio's grp_levels
  read DIC0 on silicon because its RETI did not rise in level 6's first clock: the core's
  handler RETI is at least one clock off against a scan re-phased at FINT. With level 0 in
  service a sled in front of FINT moves the RETI against nothing; a sled behind FINT sweeps
  the slots (the slots sit at a fixed distance from FINT). Not explained, not to be built: in
  3/2 a rise in the better level's second clock gives it again at the worse level's slot
  time. Not measured: f3_prio's own handler tail on the socket.

**2026-11-21, request-passage probe, sixth set (`validation/v35s/passage.py` action `pf`,
programs `f5_pf_a` / `b` / `c` / `x`; f3_prio traced on the socket, with and without refresh;
two sessions, all EQUAL):** measurement only. **FINT is 6 clocks on silicon with a level in
  service (5 with none, one window) and 3 in the core**: the only instruction of f3_prio's
  handler tail (CALL push, FINT, RET, DEC, five POPs, POP PSW, RETI) off silicon's clock; RET,
  DEC, the POPs, POP PSW, RETI, NOP, DI, ROL are exact over 244 clocks. f3_prio's grp_levels
  tail from FINT's fetch to the RETI's PSW word read is 238 clocks as the gate runs it, 33 of
  them 15 refresh cycles the core does not serve; 205 with refresh off (the core 201), and
  silicon reads DIC0 either way: IE rises outside every first clock and the scan restarts.
  **The scan's phase holds exactly over 300 clocks behind FINT**: with levels 3, 5, 6 pending
  and nothing in service the round is 22 clocks (16 plus 2 a requesting level); level 6's
  first clock is met with the PSW word's read 199 + 22k clocks behind FINT's fetch (FINT
  behind a CALL), 90 + 22k behind the interrupt entry (f5_pe_h4). Work order 39's `FINT_RUN`
  switch is exact in f5_pe_h4 by two errors cancelling and 2 clocks late in every long-tail
  window; to be judged again with FINT at 6 clocks. Not separable on the pins: where in
  FINT's clocks ISPR is cleared. Behind the RETI silicon's second return fetch comes 7 clocks
  after the first, the core's 5.

**2026-11-21, dispatch-pacing analysis and passage probe, seventh set (`validation/v35s/passage.py`,
programs `f5_pg_a` .. `d`, 100 windows, two sessions EQUAL):** measurement only. The one clock
  by which the core's dispatch trails silicon's behind DIVU, MULU, ROL by CL, a memory read
  and BR in the passage frames is **not at the dispatch**: silicon holds the dispatch word
  behind a fetch started on an instruction's last clock as the core does. It is inside the
  instruction that follows in those frames, the mark's store: **the bus cycle of MOV dmem,acc
  and MOV acc,dmem (st_dir, ld_dir) starts on the routine's fifth clock when no fetch has
  started inside the routine, the core always on the sixth; with a fetch started on the
  routine's fourth clock both start it on the sixth, behind that fetch.** The deciding
  variable is the queue's fill at the routine's start (7 held: no fetch). Passage window
  bodies, 65 programs: 615 instances without the fetch are one clock early on silicon, 0 in
  step; 2,630 with it are in step, 0 early; the untaken twins show it in 32 of 32 windows, so
  it is not an interrupt effect. All 936 corpus instances have the fetch in the way, which is
  why the corpus is exact. Refuted: "dispatch not held behind a prefix" (loses 109 of 960 F2 /
  F3 runs), "not held for any word" (breaks the INC trains). A naive trial posting the cycle
  one word earlier gains passage (boundary and clock 941 to 1,264 of 1,904) but loses 16
  corpus runs at 1 and 2 waits, where silicon still lets a fetch chained on the routine's
  third or fourth clock go first. Not explained: whether the request is due a clock sooner or
  a leading word is a wait that a full queue satisfies; MOV byte [d16],imm8 2 to 3 clocks
  early on silicon in the same frames; 26 early segments without the signature.

**2026-11-21, passage probes, eighth to tenth sets (`validation/v35s/passage.py` actions `pi`,
`pj` and the FINT set; two socket sessions each, every program EQUAL):** measurement only.
  - **The scan around FINT (`f5_pi_p{P}_{j}`, 35 programs, 1,540 windows):** with level P in
    service the round is 2(P+1) clocks and its level-0 clock falls 8 clocks before the take's
    vector read plus whole rounds, for every P 0..6: the count is fixed against the take.
    FINT's clear is seen 8 clocks after FINT's fetch; the round in progress is not cut at P,
    the count runs on to level 7, then full rounds (16 plus 2 a pending level) follow. The
    slot of level L begins at F + 8 - phi + 2L + 2b + m(16 + 2n), phi the in-service round's
    phase at the clear, b the pending levels better than L, n all pending levels. Fits all 70
    rows and predicts f5_pe_h4 and f5_pf_a / c exactly. Work order 40's core sees the clear a
    clock early and has the in-service phase off by -1, -1, +1, +2, -1, -2 for P = 0, 1, 2, 3,
    5, 6.
  - **FINT's length (520 windows, 0 to 4 waits):** FINT is two steps, each two clocks unless
    a fetch cycle starts on the step's first clock, when the step lasts to that cycle's end;
    step 1 releases FINT's second byte on its first clock. Four lengths with c = 3 + code
    waits: 4, 2 + c, c + 2, 2c. The level in service does not enter (the earlier "6 with a
    level, 5 with none" was FINT's place against the fetches); stack waits do not enter; no
    bus hold; other on-chip accesses in FINT's place behave as the core does. Reproduces
    f5_pf_x (21; FINT ; FINT 26), the timer stub (RETI's read 126 from the vector read) and
    refresh-off f3_prio (RET's read +31, the fifth fetch +20). Not produced: a FINT
    dispatched with a fetch in flight.
  - **MOV dmem,acc / MOV acc,dmem (`f5_pj_*`, 510 windows, 0 to 2 waits):** the cycle starts
    on the routine's first clock + 5 whenever no fetch occupies that clock, behind the fetch
    otherwise; the core starts it on + 6 at the earliest. "No fetch there" and "7 held at the
    start" are the same states by the queue's own rules; it is not a wait for bytes. MOV
    [d16],reg by ModR/M: the core exact. MOV byte [d16],imm8 runs on silicon as the ModR/M
    store cycle for cycle (write due on + 6); the core's routine is on silicon's clock in 47
    of 102 windows, 2 to 3 clocks late at no waits; every prelude SFR store is this form.
  - **Timer handler loop (diagnosis of periph f4_tb / f4_tm on the rebuild, no socket run):**
    silicon's take-to-take is K + 16m with K = 151; the 1,024-clock count-out walks +7 a
    period in the 16-clock window, hence 1031 / 1015. After RETI silicon makes five refetches
    whatever the return address's parity; the core dropped the fifth at an even return
    address (the HALT stop cancelling a fetch on the clock HALT's opcode is popped).

**2026-11-22, landing of the interrupt request rebuild (work orders 35, 38, 39, 40, 41 and the
HALT-stop fix):**
  - **Request passage** (`v35_sfr.sv`, v35_intc): one request flip-flop R shared first come
    by INT (two samples high) and the scan's slots, gated by IE at both ends, cleared by IE 0
    and by the take; its delay is a count with the two accepted measured constants (user's
    rulings of 2026-11-20): RESP = 8 clocks from R's set to the look, and the controller's 6
    clocks set to set for slot and NMI requests (ACK = 5 in the count's bookkeeping). The
    vector is fixed at the set; any store to a request control register drops a slot's R and
    the request is found again with its full count. INT's first acknowledge is 15 clocks
    after the edge (9 before); the 14-clock hold requirement and the phantom vector read at
    0006xh are gone. DIC's request is raised in the last transfer.
  - **The look** (`v35_useq.sv`): the word that releases the next opcode, held open over a
    held dispatch word; INT's cut-off is silicon's for all 18 measured kinds. EI raises IE
    on its first word. RETI loads the PSW on its D word; the slot claim reads IE from the
    datum, the scan's restart from the register (port `psw_ie_r`, v35_eu to v35_intc, allowed
    by the user 2026-11-21). IE rising in a slot's first clock takes that slot's request.
  - **Scan:** restarts at IE rises and request control stores, offer slots with IE 0, round
    2(P+1) with level P in service running on at FINT's clear (registered one clock behind
    FINT's first word). HALT's release count is loaded only while it is 0.
  - **FINT** is two steps, the second a word held while a fetch runs: exact in 460 of 460
    probe windows, f5_pf_x, the timer stub (RETI's read 126) and refresh-off f3_prio.
  - **DMA service** keeps the queue: DAR written back before the destination write, the
    routine ends with a re-dispatch of the popped opcode; last write end to the next store's
    write 17 / 20 clocks at 0 / 2 waits (silicon 16 / 22; 37 / 46 before).
  - **HALT stop** (`v35_bus.sv`) starts the clock after HALT's opcode is popped, so the fifth
    refetch behind RETI is made at an even return address as on silicon.
  - **Gate (land41 against land37):** corpus at both spacings RTL-exact 30,181 of 30,536,
    lost 0, gained 0, 0 pin records differ; intr 15, dma 7, periph 2 equal 2 differ (f4_tb
    1031 / 1015 as silicon), every other program and fuzz set as the baseline; secure bench
    as predicted. Passage probes: boundary-and-clock equal 4,214 of 11,289 windows. Three
    seeds at 17 ns +2.195 / +3.256 / +3.037 (worst path useq xtab to eu x_b, not of this
    work); 9,663 LUT4, 2,666 FF, 36 RAM_5K.
  - **Costs accepted by the user:** onchip_t 1 equal 5 differ becomes 0 equal 6 differ (the
    timer grid constant G_REL 3); the worst timing seed at +2.195.
  - **Not built:** the in-service count's phase against the take (silicon: level-0 clock 8
    clocks before the vector read; in the core only a restart 9 clocks after the acknowledge
    reproduces it, so the slot map behind FINT is one clock off; a probe for the event is
    running); the two-clock on-chip cycle in the controller's 6 clocks; the dropped entry's
    10 dead clocks; no fetch into a taking boundary (needs a port); NMI's unexplained rows;
    f4_tout's tout_os (823 against 855); the take lattice gate is still 0 of 27 (the core's
    prefixed and immediate stores run long).

**2026-11-22, passage probe, eleventh set (`validation/v35s/passage.py`, 163 programs, two
sessions, every program EQUAL):** measurement only. **The in-service round's level-0 clock is
  2 scan clocks after the entry's acknowledge of the interrupt controller; in a vectored
  entry that is 8 clocks before the start of the take's vector read.** Waits on the vector,
  stack and code block (0 to 4) move the vector read's end, the pushes and the handler's
  first fetch by up to 12 clocks and the count by nothing (120 of 120 rows); the take's
  boundary kind (INC, NOP, MULU, store, HALT) moves it by nothing: the phase is set at the
  entry, not carried from the slot. By entry: a controller request and NMI (with or without
  a level in service) restart the scan there; BRK does not; the INT pin's entry does not at
  its vector read; a register-bank-switching entry (no vector read) has it one clock
  earlier against the interrupted code's last fetch. The request flag's clear is near the
  same clock: TM0's next count-out is lost with its TOUT edge 6.5 clocks or more before the
  vector read and kept from 5.5, where the core loses up to 16.97 and keeps from 15.97: the
  core's acknowledge (15 clocks before the vector read) is 10 to 12 clocks earlier than
  silicon's. passage3's dropped entry at boundary + 10 is the same clock. The landed core's
  in-service phase follows EI instead (level 0 at the vector read less 6, 7, 2, 2, 8, 2, 8
  over the frames) and NMI's entry does not restart its scan. Unexplained: INT's entry
  leaves the count 3 clocks behind the handler's EI lattice (5 in six HALT-frame rows); the
  bank entry's one clock. Not run: refresh / DMA / HOLD displacing the vector read, NMI or
  BRK under waits, BRKV, macro service.
- **2026-11-22, direct-address MOV (work order 42, landed).** `MOV dmem,acc` and
  `MOV acc,dmem` post their request on the address word, so the data cycle starts on S+5
  when no fetch occupies it; `MOV byte [d16],imm8` has its own routine (`st_imm8_dir`) in
  the ModR/M direct store's shape. The store needed one bus-unit rule the probe had not
  predicted: a request posted inside a fetch chain does not stop the chain's next fetch
  (`lcb` in v35_bus.sv; registers only, no port, no integer). User rulings: land it; `lcb`
  accepted as the mechanism; `MOV word [d16],imm16` is to be probed on the socket, then
  built. Gate (land42 against land41): corpus 30,181 of 30,536 at both spacings, lost 0,
  gained 0; every program set and fuzz line as before except periph 3 equal 1 differ
  (f4_tout now EQUAL, tout_os and tm0_os gone from the lists) and onchip_t 1 equal 5
  differ (f4_oc_a EQUAL; windows differing in length: oc_e 34 to 2, oc_s 25 to 1, oc_t 21
  to 1, oc_k 4 and oc_v 1 unchanged). Probe set f5_pj: 408 of 408 windows. Timing at
  17 ns: +2.994 / +2.509 / +3.063 over three seeds; 9,691 LUT4, 2,659 FF, 36 RAM_5K.
  Pin records: all 30,536 runs move, in the prelude only (the scored window is
  unchanged), around the store to PRC at 10010h. Against silicon the gaps 10016h to
  10018h and 10018h to 1001Ah are now equal at every wait setting (before: the first only
  at wait 0, the second never). The gap 10014h to 10016h is 3 slow clocks (96 ticks) long
  at every wait setting; before it was equal at wait settings 1 and 2 (20,128 runs) and 96
  long at wait 0. The prelude's total error falls from 192 to 224 ticks to 96. Silicon
  still has refresh on in that part of the prelude and the simulation does not model it;
  the remaining 3 clocks are not explained.
- **2026-11-22, passage probe, twelfth set (f5_pj_wj_*, f5_pj_wx_*, 6 programs, 246 windows,
  two power-ups equal).** `MOV word [d16],imm16` on the socket: the landed core (c5485d0) is
  equal in 246 of 246 whole windows, so the existing routine stays and nothing is built.
  With S the routine's first clock and B the clock of the word that releases the address
  bytes (S+3 at the earliest; bus-idle and strict, so it waits out a running or chained
  fetch): a fetch starts on B; the immediate bytes are popped on B+1 and B+2; the write is
  posted unarmed on B+3 and armed on B+4. At 0 waits the write starts on B+4 (S+7) at any
  queue count; at 1 and 2 waits with 3 or fewer bytes held a chained fetch goes first; with
  4 or more the write starts at the end of the fetch from B. An odd address is the same as
  two byte cycles. The form is not the direct store's shape: at 0 waits its write is one
  clock later than `MOV [d16],reg` and `MOV byte [d16],imm8` in 34 of 34 windows. A word
  store to internal RAM takes one 3-clock slot (inferred from the fetch gap; no pin cycle).
  Work order 42's trial routine (posting on S+4) gives 0 of 246 windows and is dropped. The
  strict wait rests on one lead (PUSH, odd alignment). Not run: a prefixed external form,
  reg fields other than 0, an SFR target, 3 waits / READY.
- **2026-11-23, store timing with internal RAM disabled (validation/v35s/wstore.py, f5_ws_*,
  9 programs, two power-ups equal).** Prompted by the M90 project's figures (the core about
  2 clocks slower per write than an M90 board's V35 at PRC 0Ch). On our socket, 16
  back-to-back copies of each form at 0 waits, refresh off, both alignments. With PRC bit 6
  (RAMEN) set (4Eh, 4Ch) the core at 9ec59bf equals silicon in 55 of 55 whole windows. With
  it clear (0Eh, 0Ch) silicon's stores are 2 to 3 clocks shorter and the core is unchanged:
  16 of 67 windows equal (the reads and `MOV word [si],imm16`). Steady clocks per operation,
  RAMEN 1 / RAMEN 0: mov [si],ax 8 / 6; push ax 9 / 6.5; stosw, stosb 13.5 / 11.5;
  mov [si+2],ax and A3 9 / 7.5; mov [d16],dx 9 / 9 (bus-bound already); mov word [si],imm16
  10 / 10; rep stosw, stosb 9 / 7 an element; rep movsw 18 / 13; reads unchanged. The
  divider bits do nothing to these. From the pins at RAMEN 0: the routine no longer waits
  for the write's end (the next instruction starts on the write's first or second clock
  where RAMEN 1 gives the third after it), stores become bus-bound, and the fetch ahead of
  the first write is no longer held back. In the core `prc[6]` reaches only the on-chip
  address decode. No single rule derived: stosw saves 2 where push saves 3; why the C7 form
  is untouched is untested. Run only at 0 waits, even data addresses, external memory.
  Not built.
- **2026-11-23, RAMEN 0 store rule probed (validation/v35s/wstore2.py, f5_wt_*, 12 programs,
  676 windows per RAMEN setting as twins differing only in the PRC value, two power-ups
  equal).** At RAMEN 1 the core at 0f31fc8 equals silicon in 664 of 664 windows that hold no
  PRC store. With W the clock a write's pin cycle starts, L its last clock, P the posting
  word and S' the next instruction's first word (S' = L + 1 at RAMEN 1), silicon at RAMEN 0
  does, for plain stores: (A) the words in front of the post are unchanged, and the write
  starts on P + 1 or after the last clock of a fetch covering P + 1 (328 of 328 windows, 23
  single-write forms, 0 to 2 waits); (B) the announced request no longer holds the fetch
  chain, so a fetch takes the slot and the write follows it (+1 at 0 waits, +2 and +3 at 1
  and 2 waits); (C) the wait for the write's end is gone, S' = W, following the grant, not
  the post; the saving stays 3 clocks a write at 1 and 2 waits. Holds for MOV m,r in every
  EA form, PUSH r, STM, A3, RMW (read and read-to-write distance unchanged), XCH, PUSH mem,
  POP mem, PUSH R, REP STM; an odd-address word counts C from its second cycle. Unchanged
  (88 of 88): plain loads, POP r, LDM, ADD r,m, CMP r,m, TEST, IN, OUT, NOP. FFE40h at
  RAMEN 0 is an ordinary external cycle. A store to PRC acts on the first store behind it,
  in both directions. Not covered by the rule and without a mechanism: C6 / C7 immediate
  stores ignore the bit (56 of 64 windows equal record for record); CALL near's push starts
  3 clocks later with the rest on RAMEN 1's clocks; BRK / RETI are 10 clocks shorter (RETI's
  reads 6 apart for 9); CMP mem,reg is 2 shorter and CMPBKW 3 with no write; MOVBKW's write
  is 1 clock earlier against its read (2 at waits); an on-chip SFR store also gains the 3
  clocks. Few windows: stosw's bus-idle third word waiting a clock on the previous write's
  last clock; a request posted during a write starting no earlier than L + 3 at waits. Not
  run: 3 waits / READY, CALL far / reg / mem, RET, POP R, PREPARE, pin interrupts, PUSH PSW /
  sreg / imm, block I/O, REP compares. Not built.
- **2026-11-23, RAMEN 0, third set (validation/v35s/wstore3.py, f5_wu_*, 10 programs, 592
  windows per setting, two power-ups equal).** No single mechanism. What orders most of the
  data: at RAMEN 1 the microprogram runs each data access to its end before going on; at
  RAMEN 0 it goes on while the access runs and stops only where it needs the datum. A step
  behind a write is 3 clocks earlier at 0 waits and 4 at 1 wait (the cycle's length), also
  for PUSH R, PREPARE, PUSH PSW / sreg / imm. A read whose datum the next step does not need
  lets the next read come as much earlier: RETI's and POP R's reads 6 apart for 9, RET far's
  second read 3 earlier (8 of 8 each). A read whose datum is the result is unchanged (MOV
  r,m, POP r / PSW / sreg, RET, RET imm, DISPOSE, LDM, ADD r,m, CMP r,m, TEST, CMPM). SFR
  and FFE40h targets behave as the same routine on external memory. Separate effects: (a)
  the request word reserves nothing, so a fetch slips in front of the write; (b) the next
  request starts no earlier than L + 3 behind a write and L + 4 behind a read (RETI and POP
  R sit on the read bound); (c) a compare that stores nothing (CMP m,r, CMP m,imm) ends 2
  clocks earlier at any wait count, to CMP r,m's length. Unexplained: MOV m,imm keeps
  RAMEN 1's clocks in all eight EA forms (64 of 64) though ADD m,imm and CMP m,imm change;
  CALL's push is later (near +3 with the length unchanged; register and memory +2; far +1
  and 0) on an idle bus, and BRK's pushes +1, +1, +2; MOVBK / CMPBK's second cycle is 8
  clocks after the read's start at 0 and 1 wait and 9 at 2 (RAMEN 1: 9 / 10 / 11); the first
  read is a clock later in RETI and REPNE CMPM. Core defects found at RAMEN 1, one clock
  each (570 of 592 equal): BRKV 8 of 8, MOV byte [IX+d8],imm8 8 of 8, CALL far 3, PREPARE 3.
  Not run: pin interrupt or NMI entry, 2 waits and READY, block I/O, bit / BCD forms on
  memory, DMA. Not built.
- **2026-11-24, acknowledge placement and scan restart (work order 43, landed), with the
  loader's flat decode fields.** The vectored entry's acknowledge of the controller moves to
  its silicon place (a second word of the entry at IVEC + 9; the decision and the vector stay
  at IVEC), and does the in-service set, the request flag's clear, NMI's clear and the scan
  restart; the flag's clear is a register behind it. No port, no counter. Builder's counts
  against the eleventh probe set (Z - R equal to silicon, before / after): controller
  requests 44 / 132 of 132; BRK 0 / 8; NMI 1 / 8 and 0 / 8; vectored entry rows 0 / 24. The
  flag's clear: lost up to 6.97 clocks before the vector read and kept from 5.97 (silicon
  6.5 / 5.5; before 16.97 / 15.97). Lattice clocks off 6,564 to 6,552. Lost, by user ruling:
  f5_pr_bank_p3_1 10 to 8 and f5_pr_bank_p3_2 10 to 6 of 44 windows; the core's bank-switch
  entry is 3 clocks short from last fetch to the handler's first fetch (27 / 25 for
  silicon's 30), which is older than this work and open. Not built: the second take's scan
  one clock later than the first take's rule (pe_h4's order of two later takes); INT's 3 / 5
  clocks; EI's one clock. v35_loader.sv: `v35_lin_t` carries the decode's len / e2 / pg as
  flat members (Quartus 17 mis-synthesizes a nested member read of a function's struct
  argument; found on the M90 DE10 build). Gate (land43 against land42): every line of
  verify.out identical, pin records 0 differ; timing +2.640 / +2.980 / +2.959; 9,639 LUT4,
  2,659 FF.
- **2026-11-24, RAMEN 0 experiment build (work order 44, not landed; build/overseer/wo44/).**
  Bus unit only, gated on `ramen`, behaviour at RAMEN 1 unchanged window for window: the
  EU's wait for its own memory cycle ends at the hand-over instead of the cycle's end, the
  dispatch word no longer waits for that cycle, and the `rh` reservation is dropped. It
  recovers about one of the three clocks silicon saves a store at 0 waits (follower read +3
  to +2 clocks off; +3 to +1 at 1 wait). The other two are the store routine's own E word
  and dispatch word behind the post: silicon's next instruction starts on the write's first
  clock, about two clocks before the core's post word, so no change of a wait reaches it.
  MOV m,imm is singled out by the routines themselves: the C6 / C7 tails are the only
  memory-write tails whose E word releases operand bytes (the datum comes from the
  instruction stream), and silicon keeps RAMEN 1's hold and reservation there. CALL's push
  on silicon sits where RAMEN 1's F ended; nothing explains it. Not built: the read side
  (POP R, RETI), CMP m,r's fixed word, F on W (needs prc[6] in the EU, a port). User ruling:
  a design study of the store tails before any rebuild.
- **2026-11-24, RAMEN design study and fourth store set (build/overseer/ramen-design/DESIGN.md;
  validation/v35s/wstore4.py, f5_wv_*, 10 programs, 344 windows a setting, two power-ups
  equal; the core at a7cbcf1 is exact on all 344 at RAMEN 1).** Picture: the routine's
  address, datum and post sit on the same clocks in both modes; the routine's end moves. At
  RAMEN 0 the next opcode's pop (E) and the dispatch ride on the routine's last two words
  and the post word is the dispatch word (as OUT's write is in the core), so the next
  instruction starts on the write's first clock. At RAMEN 1 E and the dispatch are two words
  of their own behind the post, the boundary then meets the running write, and F behind a
  write waits its length: RAMEN 1 = RAMEN 0 + the end hold (2 clocks) + the boundary's wait
  on the write (1 + waits) + the F wait. Falling out of it: the fetch in front of the write
  (the earlier E frees queue room; no reservation change); CMP m,r's 2 clocks (the end hold
  with no write); MOV m,imm unchanged (its last word takes the immediate from the queue on
  the write's first clock, so the end cannot overlap); on-chip targets. An internal-RAM
  access at RAMEN 1 costs what a 0-wait external one does, so a decode step is not the
  cause. Trial (worktree, not landed; a mark on the word in front of the post, F's wait
  behind a write at RAMEN 1 only, the request slot freeing a clock later behind a write,
  the segment prefix standing through the early dispatch; about 30 routines marked, ROM
  1,922 to 1,932 words), whole windows RAMEN 1 / RAMEN 0, base to trial: f5_ws 55 to 55 /
  19 to 61 of 67; f5_wt 664 to 674 / 208 to 578 of 676; f5_wu 570 to 570 / 184 to 395 of
  592; f5_wv 344 to 344 / 12 to 256 of 344; nothing lost; corpus subset of 7,158 runs
  unchanged. At RAMEN 0 the trial is exact on word writes at 0 waits, word writes at 2
  waits with READY held 0 / 10 / 15 / 18.5 clocks (96 of 96), byte writes at even and odd
  addresses (56 of 56); the pair `26 89 07 ; 26 89 57 02` 40 of 64 (the fetch-chain rule
  fitted at RAMEN 1); REP STMW and REP MOVBKW 0 of 32 each (silicon's REP STM element is
  max(W + 7, L + 4); the trial one clock short). Open: CALL near's push on Y + 7 for Y + 4
  with no mechanism (CALL forms 0 of 52, BRK 0 of 36); the read side (POP R, RETI, RET far,
  MOVBK, CMPBK) designed, not trialled; one gap in PUSH R; XCH mem and memory shifts need a
  second mark. The design needs prc[6] in v35_useq and v35_eu.
- **2026-11-24, RAMEN delta design (build/overseer/ramen-design2/DELTA.md; f5_wv_r_*, 84
  windows a setting, two captures equal, the core exact on its RAMEN 1 half).** Trial on top
  of the first, not landed. REP STM at RAMEN 0 is a second body entered by one conditional
  jump on RAMEN on a head word with no act: the count's test stands in front of the write
  (first write a clock later, 7 words an element); the index write-back word is bus-idle and
  waits for the previous write through its last clock (L + 4 at waits); the exit is two
  clocks shorter. Why silicon tests the count in front of the write at RAMEN 0 is not
  explained; three one-rule derivations from the RAMEN 1 body fail on counted windows. REP
  MOVBK likewise a second body: four words under the read, F on the word that takes the
  datum, then the count test and the post. The fetch-chain mark `ych` (a request word
  executed inside the fetch chain) belongs to the instruction and the boundary clears it:
  one term, no RAMEN term in the bus unit; at RAMEN 1 no boundary falls between a request
  word and its grant so it never acts; at RAMEN 0 it gives the pair `26 89 07 ; 26 89 57 02`
  64 of 64 (40) and the PRC-flip windows 24 of 24 (20). Trial scores RAMEN 1 / RAMEN 0:
  f5_ws 55 / 67 of 67; f5_wt 676 / 596 of 676; f5_wu 570 / 403 of 592; f5_wv 344 / 344 of
  344; f5_wv_r 84 / 84; f5_pj 756 of 756; corpus subset 8,070 runs unchanged. ROM 1,932 to
  1,953 words. Open: RETI, POP R, RET far, CMPBK, MOVBK single; PUSH R's gap; CALL's and
  BRK's pushes.
- **2026-11-24, work order 45 landed (microcode only; gate build/overseer/land45 against
  land43).** Three of the four RAMEN 1 one-clock differences of the third store set. CALL far
  and JMP far: the seventh word counts as a request word (the code of the memory request
  word), so the fetch the offset's release started is not followed by a five-held
  continuation in front of the segment word; f5_wu CALL far 8 of 8. MOV byte [IX+d8],imm8: a
  body `st_imm8_d8` in the shape of the word form's, write on S + 6 and the fetch on S + 3,
  8 of 8. BRKV taken: the jump enters BRK 3's first word (one taken micro-jump more), 7 of
  8. Corpus RTL-exact 30,181 to 30,197 of 30,536 at both spacings, lost 0, gained 16 (F35
  +8, F40 +8, far JMP / CALL at 0 waits); f5_wu at RAMEN 1 570 to 588 of 592; every program
  set's line as land43; timing +2.994 / +3.284 / +2.565 ns; 9,697 LUT4, 2,659 FF, 36 RAM_5K;
  no port, no budget change. Open: BRKV window 84 (a fetch started on S; silicon has the
  wait and one clock more) and behind full-queue leads; PREPARE not built, no mechanism; the
  far forms' request word also waits while a fetch has two clocks or more left, which no
  corpus run exercises; in the passage programs' unscored prelude the far jump is on
  silicon's clocks but the discarded fetch on the flush clock is issued at 1016Eh for
  silicon's 0016Eh (PS written two words before the FLUSH); F35 CALL far ; RET far imm (2
  runs) now first differ at RET far imm's stack read, 2 clocks early.
- **2026-11-24, RAMEN design, third round (build/overseer/ramen-design3/DESIGN3.md;
  wstore4.py groups c and d, f5_wv_c_* / f5_wv_d_*, 520 windows, two captures equal).** Trial
  on the delta trial with work order 45, not landed. The read side, PUSH R, CALL and BRK fit
  at RAMEN 0 on the existing bodies, no second body: (1) an access wait `fa`, an F word that
  takes nothing and waits for its cycle at RAMEN 1 only, the datum taken by an ordinary F in
  front of the next post; (2) plain words under an access, which RAMEN 1 runs inside the
  cycle (at most three) and RAMEN 0 counts; (3) mode posts `p1` / `p0`, the same cycle posted
  on one word at RAMEN 1 and one to three words later at RAMEN 0; (4) the request-word wait
  read for the EU's own write (two clocks or more left), both modes. CALL's push is not
  waiting on the FLUSH, the target or the queue: it is posted a fixed number of words later
  (near 3, reg / mem 2, far 1 and 2). Trial RAMEN 1 / RAMEN 0: f5_ws 55 / 67 of 67; f5_wt
  676 / 660 of 676; f5_wu 588 / 561 of 592; f5_wv b r y 428 / 428; group c 186 / 161 of 188;
  group d 59 / 59 of 72; f5_pj 756 of 756. Why silicon has the words under the access and
  the late posts is read from the pins, not explained; the design says only why RAMEN 1
  hides them. Open: BRK's third push a clock late at 2 waits, CALL near / far one window
  each behind a store lead, PREPARE 8,1 at waits, the REP compares untried, PUSH DS0; at
  RAMEN 1 BRKV taken differs behind every full-queue lead (first fetch three clocks later
  on silicon) and PREPARE at j0 / j1 alignment 0.
- **2026-11-24, work order 46 landed: RAMEN 0 on the write side (gate build/overseer/land46
  against land45).** `ramen` (PRC bit 6) enters v35_useq and v35_eu (the user's ruling; no
  other port, the budget untouched, no RAMEN term in the bus unit). At RAMEN 0 a routine's
  end rides on its last two words: the next opcode's pop and the dispatch on marked words
  (the mark accepted only on NEXT / JMP / CALL / RET words and a LOOP's exit; the assembler
  checks on the packed image that the decode selects exactly the marked words, after the
  trial's decode was found to match the divide-error word); the prefix clear one word
  behind E; a second mark (nb with bi) for XCH mem and the memory shifts' counter step; REP
  STM and REP MOVBK as second bodies entered by a jump on DN with vk (`rz`), for these two
  only; the fetch-chain mark `ych` cleared at the instruction boundary. Corpus and pin
  records: 0 runs differ from land45 (30,197 of 30,536); every program-set line equal;
  timing +2.587 / +2.643 / +2.867 ns; 9,764 LUT4, 2,675 FF, 36 RAM_5K; ROM 1,926 to 1,961
  words. Store sets, whole windows RAMEN 1 / RAMEN 0: f5_ws 55 of 55 / 67 of 67; f5_wt 676 /
  612 of 676; f5_wu 588 / 419 of 592; f5_wv b y 344 / 344 of 344; f5_wv_r 84 / 84; groups c
  186 / 0 of 188 and d 59 / 16 of 72. Exact at RAMEN 0: word and byte stores at 0 waits,
  word stores with READY held to 18.5 clocks, the pair `26 89 07 ; 26 89 57 02`, REP STM
  and REP MOVBK. Not exact at RAMEN 0, on RAMEN 1 timing: CALL, BRK, PUSH R, POP R, RETI,
  RET far, MOVBK / CMPBK single, the REP compares, PREPARE, PUSH DS0 (work order 47 and
  the fourth design round). The store sets are in the gate as a report: per program the
  equal-window count, which may not go down (the user's ruling). Rulings of the day for the
  third design round: words under the access and late posts accepted with each pin-read
  word count OPEN; codes fa / p1 / p0 allowed; one access-wait signal useq to eu, the pair
  ceiling 3 to 4, useq out 23 to 24, eu in 38 to 39; the 2-wait residue (BRK's third push,
  PREPARE 8,1, CALL near / far one window each) recorded open, not chased.
- **2026-11-24, RAMEN design, fourth round (build/overseer/ramen-design4/DESIGN4.md; no
  socket use).** Trial on the third round's tree, not landed. REP STM and REP MOVBK on one
  body in both modes, the second bodies and the mode branch gone: the write a late post,
  the request word's wait for the EU's own write (L + 4 at waits), the count's test on the
  RAMEN 1 post word, REP MOVBK's read an access wait; the exit F, a word, a bus-idle word,
  five words, E (at RAMEN 1 the bus-idle word replaces a word with no act; no window or
  corpus run exercises its wait). REPNE CMPMW 8 of 8 (the first read a late post with an
  access wait); REPNE CMPBKW 8 of 8 with the loop reworded at its RAMEN 1 clocks and the
  pointer and count steps reordered (function bench not run in the trial). BRK's third push
  at 2 waits 20 of 20: the RAMEN 1 post word still waits for the request slot when it posts
  nothing at RAMEN 0. Trial RAMEN 1 / RAMEN 0: f5_wt 676 / 660 of 676; f5_wu 588 / 577 of
  592; group c 186 / 169 of 188; group d 59 / 59 of 72; the rest whole. ROM 1,976 to 1,961
  words. Open: PUSH sreg (a fetch one clock in front of the early end's E, 3 windows), PREPARE
  8,1 at waits, CALL near / far behind a store lead at 2 waits (one window each), no data
  for a REP compare ending on its condition or at waits; section 5 lists the word counts
  read from the pins.
- **2026-11-24, work order 47 landed: RAMEN 0 on the read side, PUSH R, CALL and BRK;
  REP STM and REP MOVBK on one body (gate build/overseer/land47 against land46).** The
  third round's elements: the access wait `fa` (F with the flush bit: an F word that takes
  nothing, a wait at RAMEN 1 only; the EU keeps its datum-valid flag through the one new
  signal `w_fa`, useq to eu), mode posts `p1` (a post with vk, RAMEN 1 only) and `p0` (a
  post with flush, RAMEN 0 only), words under the access, and the request word's wait for
  the EU's own write in the bus unit (no RAMEN term). Routines: RETI, POP R, RET far, MOVBK
  and CMPBK single, PUSH R, CALL near / reg / [d16] / far, BRK 3's body; each word count
  read from the pins is OPEN in its routine's why (why silicon has those words is not
  explained; the user's ruling). From the fourth round: REP STM and REP MOVBK on one body
  for both settings, the second bodies and the `rz` branch removed (at RAMEN 1 the exit has
  a bus-idle word for a word with no act; no reachable RAMEN 1 state exercises its wait:
  the queue is full at the exit, socket groups ha / hc); a p1 word that posts nothing at
  RAMEN 0 still waits for the request slot (BRK's third push at 2 waits). The fourth
  round's REP CMPBK loop was not built: it stepped IX and held CW across the take point
  (intr 10 / 5, dma 5 / 2 in the builder's run; vectors and corpus cannot see it). Budget by
  the user's ruling: useq out 24, eu in 39, pair useq to eu 4. Corpus, pins and every
  program-set line as land46 (30,197 of 30,536); timing +3.139 / +2.745 / +3.093 ns; 9,704
  LUT4, 2,668 FF, 36 RAM_5K; ROM 1,961 to 1,949 words. Store sets at RAMEN 0: f5_wt 676 of
  676; f5_wu 562 of 592; group c 166 of 188, d 43 of 72; RAMEN 1 lines unchanged.
- **2026-11-24, RAMEN design rounds 5 to 8 (build/overseer/ramen-design5 .. 8; wstore4
  groups e f g ha hc i and the READY sweeps).** (5) REP CMPBK cannot be done on one body
  (18 clocks an element at RAMEN 1, 13 at RAMEN 0, the take point a non-waiting word on the
  source read's third clock): left as landed, the user's ruling. REP CMPM with its loop and
  take point kept, the first element's datum wait one word on: 108 of 108. PUSH sreg: a
  release mark `er` one word in front of the early end. CALL near / far, PUSH imm16 and BR
  near one clock early behind a store whose block has 2 waits: a word that releases operand
  bytes and is not bus-idle waits while the EU's memory write has a clock left after the
  next. PREPARE at RAMEN 1, levels 3 and 4: every copy after the first a clock later on
  silicon; one word on the loop's back edge. (6) "An F behind a write passes from the
  write's next-to-last clock at RAMEN 0" refuted: 546 windows lost, 11 gained; PREPARE
  level 1 and up at waits stays one clock a wait off at RAMEN 0, open (no word-level
  choice, the user's ruling). (6 to 8) Code fetches stretched by READY: everything exact
  from 0 to 18.5 clocks but the commit word (`bi alt`) against the second fetch of a chain;
  silicon's commit word is later than the third-last clock by floor(N) - 1 clocks for READY
  low N clocks (half clocks never matter) and executes on the clock in which READY is first
  high; the core decides the stall before that clock, so the pin flop, the synchronizer's
  first flop and the raw pin are each one clock late; the harness is excluded (one lane
  module for both lanes). Recorded and parked (the user's ruling); the third-last-clock
  constant stays a known exception.
- **2026-11-25, work order 48 landed: the fifth design round (gate build/overseer/land48
  against land47).** REP CMPM at RAMEN 0 with its loop and take point as landed: the first
  read a mode post, an access wait with IY's step, the datum wait on the post's fifth word;
  the first element writes CW on its own two book clocks (the trial wrote it on the loop's
  test word). PUSH sreg: the release mark `er` (vk with flush on a plain word), E forced on
  the next word without a release of its own; two flops in the sequencer. The release-word
  wait inside the existing word-kind code (rl=x with flush, no bi): a word that releases
  operand bytes and is not bus-idle waits while the EU's memory write has a clock left after
  the next; no port, no budget change; five bus readers restated so every older code reads
  as before. PREPARE: a word on the copy loop's back edge (RAMEN 1, levels 3 and 4: 0 to 42
  of 48). The assembler's layout gives back its own jumps when an NT page of the 40-bit
  format is full (X NT and Y NT stay exactly full; a further distinct word may need a
  format decision). Corpus, pins and every program-set line as land47 (30,197 of 30,536);
  timing +2.877 / +2.750 / +2.895 ns; 9,852 LUT4, 2,664 FF, 36 RAM_5K; ROM 1,950 words.
  Store sets RAMEN 1 / RAMEN 0: group e 216 / 108 of 216 (REP CMPM whole, REP CMPBK as
  landed); f 72 / 72; i 96 / 96; g 105 / 18 of 120; ha and hc 55 of 60 each and the READY
  sweeps s and t 8 of 12 / 2 of 6 with READY low (the parked commit word); u 16 of 16.
  Open at RAMEN 0: REP CMPBK, PREPARE at waits and level 1 and up, CALL memptr16 beyond
  [d16] unmeasured.
- **2026-11-25, the 339 corpus misses classified (build/overseer/miss339/MISSES.md,
  groups.jsonl, SOCKET-ROWS.md; head 235ddea).** All 339 core misses are chain-model exact
  and the chain model's 175 misses are all RTL-exact; no run is missed by both. Groups: A
  the bit-field head's commit word, 114 (F32 F34 F39, pE, W 1 / 2; EXT / INS read 1 late;
  ruled not built 2026-11-17); B the `J` wait behind a no-wait pair, 88 (F24 F30, W 0; the
  cycle behind the last string element 1 early; not a bus state); C the store's release on
  the write's last byte cycle, 26 (successor's fetch 1 early; no microcode-only fix, each
  route one bit over the port budget); F a request word against a two-wait fetch, 20; G a
  five-held back-to-back fetch, 16; E1 SHL [m],CL's fourth word, 15 (trial: `bi` to `rl=x`
  as SHL r,CL's, 15 gained, 0 lost on 2,772 runs); D RET far imm16, 12 (trial: on RET far's
  measured words, the immediate released on the second datum word; 12 gained, 0 lost); E2
  IN acc,DW's request word, 12 (three trials fail); H two-register d16 stores, 11; K the
  `P C` commit word against the third fetch of a chain, 6 (trial: one more condition on the
  third-last-clock constant); L CVTDB behind an EU cycle, 6 (ruled); I M N, 13. The reading
  model is exact on 224 of the 339 (rules measured, not built); 115 are unread states.
- **2026-11-25, the RAMEN 1 leftovers studied (build/overseer/r1-left/DESIGN.md; r1left.py,
  f5_wx_a .. e, 21 programs, two captures equal).** Trials on 235ddea, not landed. (1) BRKV:
  the "full-queue lead" rows are BRKV not taken (the filler clears V); silicon's not-taken
  BRKV is 6 clocks from its first word (the book's 3); one structure gives both paths: BRK
  3's first three words, then the V test on the fourth. (2) PREPARE: the level byte released
  one word later; only seen with seven bytes held. (3) BRKCS reg16 measured `P . BP . . B .
  . . . . F N .`: the 0F page's ModR/M head and a bus-idle sixth word; RETRBI the page's
  bus-idle third word; the interrupt's bank entry on BRKCS's words from the first is an
  inference from one distance (30 for the core's 27). (4) Fetches of the old stream up to
  and on the flush clock go out at the old PS, in BR far and RET far imm16 alike: the
  stream's segment base as a register of the queue loaded with the stream's offset (RTL, 20
  flops, no port). (5) RET far imm16 `. . Y D . . Y D . . F N .`. (6) The prelude gap is
  refresh: sixteen refresh phases against the RFM store give six layouts on silicon; closed
  under the no-refresh rule, nothing built. New: BR far [d16] / CALL far [d16] behind j0 at
  odd alignment, first read a clock earlier on silicon (4 windows). Trial, five items
  together: store sets 5,208 to 5,262 of 5,616 windows, 0 down; f5_wx a 60 / 60, b 72 / 72,
  c 90 / 94, d 30 / 30, e 30 / 30; corpus subset lost 0, gained 12; ROM 1,950 to 1,959.
- **2026-11-25, the program sets that differ analysed (build/overseer/progsets/
  PROGSETS.md).** wtc's 8 "differ" are the ungated whole-trace lines (8 of 8 equal by
  window); STOP's function is built and gated, only CLKOUT in STOP is not; the fuzz five
  are OUT then CVTBD / CVTDB (ruled 2026-11-13); the phase gate dies on a receipt name and
  never compares seven programs. Causes: P1 TOUT's pin on the clock's edge; P2 a fetch
  behind a memory write gives way to a boundary once, silicon's next fetch too; P3 a
  request word waits for the EU's own I/O write as for its memory write (one frame); P4
  HALT's fetch stop cancels a fetch pending behind the EU's cycle; P5 EI restarts the scan
  a clock early; P6 the controller's two-clock bus cycle before a take is not built (needs
  a wire intc to bus); P7 which INC a take falls behind, unread; P8 a request reaches the
  scan two clocks late; P9 HALT is a stalled state where silicon tests for release every
  second clock; P10 INTP0's flag by frame; P11 REP MOVBKW at two odd addresses; P12 one
  TMIC0 read. Trial of P1 to P4 together: corpus 0 rows differ, onchip_t 2 / 4 (f4_oc_e
  118 of 118), f5_ph_s 30 of 32, f5_la_q 23 of 24, store lines as land48.
- **2026-11-25, socket rows for the corpus groups (build/overseer/miss339-rows/ROWS.md;
  rows339.py, f5_wy_*, 16 programs, 1,058 windows, two captures equal).** MOV PS,r/m loads
  PS at once and the fetch address keeps the old segment until the next flush (24 of 24;
  a short branch's refill is at the new segment): the stream's segment base is the queue's,
  loaded at a flush. Group A, the bit-field head: under READY low 2 to 5 clocks the commit
  point stays on the fetch's fourth-last clock, where READY is still sampled low, so a
  fourth-last rule cannot be causal; the head's fourth word is a plain bus-idle word and
  the fifth is the commit word, passing as every other commit word does; trial (the `bi
  alt` one word later in ext, exti, ins, insi; ROM unchanged) gains 114 of 114 on F32 F34
  F39, lost 0. Group B: the extra clock of the `J` wait depends on the pair's second byte
  cycle alone (there for 3+3, 4+3, 5+3 clocks, absent for 3+4, 3+5, 4+4, 5+5): four clocks
  from the second cycle's start; no mechanism. K reproduced; under READY on the third
  fetch's ready clock; held. BR far / CALL far [mem]: 18 windows with the first read a
  clock early on silicon, the popping bus-idle word passing on the last clock of the fetch
  that delivers its byte (the open delivery-clock pop; corpus group M the same). E1 as
  work order 49 builds it. F G H I E2 reproduced, unread; two guessed rules refuted (18
  gained / 140 lost; 0 / 3,972). The request word behind a long I/O write (P3) was not
  exercised (I/O waits left at 0).
- **2026-11-25, second socket session for the corpus groups (build/overseer/miss339-rows2/
  ROWS2.md; rows339.py, 12 more f5_wy_* programs, 2,144 windows, two captures equal).** P3:
  the request word's wait for the EU's own I/O write holds for PUSH r16 and POP r16 (8
  windows at 2 I/O waits, none lost); PUSH imm8 (10 windows, one or two clocks later on
  silicon) and CALL near behind a five-clock I/O write (4, a second fetch the core has and
  silicon has not) stay open. F: stepped across a fetch, RET imm16 and PUSH sreg have the
  request word one word too late in the core (the `open` word belongs behind it); trial,
  the two words changed places: 17 corpus runs gained, 0 lost on 5,448; probe f 206 to 214
  of 216, s2 428 to 493 of 496. B: `J` words are REP STMW, REP MOVBKW, MOVBKW, INMW, REP
  INMW, CALL near; `D` words STMW single, CALL far, BRK 3, RET, PUSH / POP, PUSH R, loads,
  stores, RMW; a first half stretched by READY keeps the clock, a stretched second half
  does not; no property the microcode names separates the sets. G: one state (an I/O
  write, one single-byte instruction, the form at an odd address). H: two d16 immediate
  stores in a row, every even alignment. E2: OUT ; MOV r,r ; IN at even alignment. Unread.
- **2026-11-25, rulings on the corpus groups.** B (the `J` wait, 88 runs) and the small
  groups G, H, E2 and PUSH imm8 (about 45 runs) are described differences: the rows and
  reductions above are the record, no further probe. K (6 runs) is held for a mechanism:
  no further condition on the third-last-clock constant. A (the bit-field head), C (one
  bus-to-loader bit allowed), D, E1 and the request word of PUSH sreg / RET imm16 go into
  work order 49. The delivery-clock pop is in design.
- **2026-11-25, interrupt path and HALT design note (build/overseer/int-design/
  DESIGN-INT.md; intprobe.py, 10 f5_lc_* and 2 f4_od_* programs, 409 windows, two captures
  equal).** HALT on silicon is a loop of two words: one tests the release, the other the
  take, so each test is made every second clock; a release is followed by an E whose start
  takes no maskable request; with IE 0 the E follows 11 clocks after the controller's
  count starts. Trial (the loop as six words in core.uasm and four in xfer_stop.uasm, ROM
  1,956; EI's restart and the INT pin's claim a register behind IE's rise; the request seen
  by the scan as its strobe raises it and the timer's strobe a clock ahead; a fixed
  two-clock hold of the fetch as a stand-in for the controller's cycle): corpus 30,197 with
  0 lost, every function gate and store line as the baseline, windowed sets 2,650 to 3,141
  equal of 4,101 (IE 0 release 320 of 320 from 0; pin release 23 of 32 twice; phase set 111
  equal from 1); two windows of the new probe f5_lc_pb lost, six gained. Open: the take out
  of HALT with IE 1 is 4 clocks early or late (the two take kinds inverted where no fetch
  is pending at HALT's pop; the selecting signal not found). The controller's cycle on
  silicon (f5_lc_sj by level) is a two-clock bus cycle granted at the first fetch slot at
  or after the naming + 6, the count standing until the grant; it is not granted on an
  idle bus with no fetch wanted. The fixed hold is right only when the count's two clocks
  fall on a fetch slot (110 phase windows equal, 126 right takes one clock late, none of
  them an equal window). The take boundary by level is the grant plus the instruction
  boundary, not a rule of its own. INTP's sampler: with EI's restart corrected, one
  residual of under a clock at the slot's threshold. OUT ; CVTBD / CVTDB is a datum rule:
  at 2 I/O waits the pins show the CVT's sign-extended immediate (the odd pair's first
  half keeps AL), at 0 waits AL / AW; clocks equal in every window. REP STMW / MOVBKW with
  IY odd at 0 waits leave the string one clock later on silicon (7 of 24 windows). CLKOUT
  in STOP: no new rows. Rows still wanted: H1 H2 P6a P6b P10a R2a R3a P11a (section 7).
- **2026-11-25, rulings on the interrupt and HALT design.** The controller's bus cycle is
  left out of the next batch (no fixed hold, the allowed intc-to-bus wire stays unused);
  rows P6a and P6b first, then a design on the grant. The timer's pre-strobe net inside
  v35_sfr.sv (v35_timer to v35_intc) is within the rules. The IE 0 release count is
  accepted as ACK + RESP - 4, the two fewer being the loop's two words. The HALT loop is
  built now with the IE 1 take recorded open. OUT ; CVT's datum rule waits for rows R2a.
  Next socket session: P6a, P6b, R2a, P10a, R3a, P11a (H1 and H2 not chosen).
- **2026-11-26, interrupt rows socket session (build/overseer/int-rows/ROWS-INT.md;
  introws.py, 15 trace programs with 660 windows and 26 CLKOUT runs, two captures equal).**
  The controller's bus cycle: two clocks at 0, 1 and 2 memory waits (no wait field, no
  READY); on a free bus with the queue full it runs at once and needs no fetch (DIVU
  frames 28 of 28 equal on the landed core); it never breaks a running cycle and goes
  ahead of the next fetch; while a fetch is pending and not started (a flush's gap, the
  clocks behind a pop) it waits and takes that fetch's first two clocks, the count
  standing. As a mechanism: a third requester at the bus arbiter, a request from the
  controller and a grant back. Open: which signal is "pending" behind a pop (silicon has
  it one or two clocks ahead of the core's request line); an RTL trial, not rows. OUT's
  datum: MOV AL,imm, ADD AL,imm, PUSH AW and MOV [m],imm behind an OUT at 1 and 2 waits
  do not reach the pins; of 14 followers only CVTBD and CVTDB do, so the immediate-pop
  rule is refuted; what fits is the multiply / divide loop's operand register being the
  write datum register. INTP0's sampler: 8 to 12 ticks of 32 behind the clock boundary,
  half a clock later than the core's, at both parities. CLKOUT in STOP: the stop delay is
  a count of its own in CPU clocks, the same over four alignments at /2 and /8 and with a
  held request. REP STMW / MOVBKW at an odd destination: the late exit is not the count
  test (CW 1, 2, 3, 8 alike); it is the write pair's second half at 0 waits. Rows named
  for later: R2c, P10b, P11b.
- **2026-11-26, rulings on the interrupt rows.** The grant wire v35_bus to v35_intc is
  allowed beside the request wire (these two signals only); a Fable trial of the grant
  with the "fetch pending" term comes first, an Opus build only when the trial loses
  nothing exact. INTP0's sampler move is trialled with it. OUT's datum under a running
  I/O write (CVTBD / CVTDB) is a described difference: no build, no further rows. CLKOUT's
  stop in STOP is to be built as a count of its own in the clock generator, a named
  measured constant.
- **2026-11-26, delivery-clock pop design (build/overseer/dpop-design/DESIGN.md).** The
  item as worded in ROWS.md is withdrawn: in none of the 22 windows is the popped byte
  delivered by the fetch that ends on the word; it is long in the queue. What is open is
  one word, the bus-idle word that pops and releases nothing (the third word of BR far
  [d16] and CALL far [d16], the only such word in the ROM): it passes on a fetch's last
  clock in 22 windows and waits in 42, the two sets confounded (odd alignment, low byte,
  five held, against even, high byte, four held). Every other word kind waits or passes as
  the core has it (over 30,000 confirmed events). A fitted trial on that one word gains 22
  windows and 4 corpus runs (group M) with 0 lost; not landed. The E word popping the
  arriving opcode on its delivery clock is not distinguishable on the pins by any row on
  file. Proposed rows: dpop.py (f5_wz_n, f5_wz_o; simulated, not captured).
- **2026-11-26, rulings on the pop design.** The far [d16] word: capture the proposed
  rows first (dpop.py), nothing lands until they are read. The E word's pop of the
  arriving opcode on its delivery clock is closed: the compensation stays, recorded as not
  distinguishable on the pins.
- **2026-11-26, far [d16] word rows (build/overseer/dpop-rows/ROWS-DPOP.md; dpop.py,
  f5_wz_n and f5_wz_o, 72 windows each, two captures equal) and ruling.** The third word
  of BR far [d16] and CALL far [d16] meets a fetch's last clock in 76 of 144 windows:
  silicon passes the 28 with five held (the queue's request line down) and holds the 48
  with four or three; the six deciding windows (odd alignment, low byte, three held) are
  held. So the passing follows the held count, not the byte's place or the alignment; no
  new wire. Other bus-idle words on silicon still hold with the line down (plain 151,
  popping and releasing 464, releasing 78 events): why this word differs is not known.
  Ruling: land it declared OPEN (a word kind of its own, the measured condition named), in
  work order 50. Also ruled: work order 50's loss of f5_lc_pb w14 and w30 is accepted
  (the INTP sampler's residual at silicon's sled parity; six windows gained).
- **Work order 49 landed (2026-11-26): the RAMEN 1 leftovers, the corpus groups with a
  mechanism, and the gate fixes.** Corpus RTL-exact 30,381 of 30,536 (from 30,197; 184
  gained, 0 lost): the bit-field head's commit word as its fifth word 114 (F32 F34 F39),
  the store release bit 26, the request word of PUSH sreg / RET imm16 one word earlier 17,
  SHL [m],CL's fourth word 15, RET far imm16 12. Built: BRKV as BRK 3's first three words
  with the V test on the fourth; PREPARE's level byte released one word later; BRKCS and
  RETRBI with their bus-idle words, three head words on the bank entry (an inference from
  one distance); RET far imm16 as measured; all four declared OPEN. P1 to P4 of the
  program-set analysis. One bit bus to loader (`wl_b`, an off-chip write's grant restarts
  the lead count; budget bus out 18, loader in 37, pair bus-loader 5, user-allowed). The
  queue's stream-segment register (`fps`): the stream keeps its segment to the next flush.
  phase.py compares all 12 programs; clk_pck compares the anchors silicon reached. Store
  sets: nine programs up, none down (f5_wu_k_r1, f5_wu_v1 both, f5_wv_c_r1, f5_wv_d_r1,
  f5_wv_g_r1 equal). Leftovers probe: a, b, d, e equal, c 90 of 94. onchip_t 2 / 4.
  Timing at 17 ns +3.060 / +2.945 / +3.110 ns; 9,754 LUT4, 569 ADD, 2,687 FF, 36 RAM_5K;
  ROM 1,959 words. Gate changes ruled by the user: wtc_ps rewritten for the stream
  segment (MOV PS, a NOP sled, BR as the flush; sled fetches judged against the old
  block's wait field, fetches behind the flush against the new one, both counts non-zero;
  21 judged per case for 14; a core taking the field by the EU's PS fails it). Accepted
  loss: f5_wy_a2 w0 and w4 (EXT and INS imm4 under READY low two clocks) now one clock
  early as ROL4 and SHL r,imm8 are in the same windows: with the parked commit word under
  READY-stretched fetches. Pin records: five runs change with identical rows (the store
  release bit; 9 of 18 events equal to silicon before, 17 after); 16 gained runs are not
  one shifted step (12 RET far imm16, 4 RET imm16 chains). Report lines added to the
  gate with the no-loss rule: the leftovers probe, the corpus-group rows, the interrupt
  probe, the CLKOUT set, wtc by window (baseline for them: build/overseer/land48x).
- **2026-11-26, controller-cycle grant and sampler trial (build/overseer/int-design2/
  DESIGN-INT2.md).** The grant with the two ruled wires: the "fetch pending" term rides
  in the queue's level struct (room for a word seen a clock later, or a byte released
  leaving five or fewer held, for the two clocks behind it); the fetch side is then exact
  in f5_ld_* 200 of 200, f5_lc_sj 48 of 48, phase 200 of 200, f5_lc_k* 98 of 100
  (f5_lc_sn's NOP train misses 18). Not buildable as trialled: dma f4_dma hangs through a
  hole in the HALT loop (the loop's take test says yes, the dispatch's own term says no
  three clocks later, and the no-take path waits for a fetch the halted prefetcher never
  makes; reachable without the grant by a request named about nine clocks in front of
  HALT's pop: work order 50 must close it), and f4_tm's write stream changes. The take
  boundary by level re-read with fetches right: neither the count nor the grant, the
  take's sample at a fetch-starved boundary. INTP0's sampler half a clock later (three
  lines in v35_intc): nothing lost on the full list, 39 windows gained; into work order
  50. Rulings: the pending term's two clocks are not accepted as a measured stage, the
  grant is held for a mechanism; after work order 50 lands, one trial of the grant with
  the take boundary on top.
- **Work order 50 landed (2026-11-26): HALT as a microcode loop, the interrupt path's
  first corrections, the far [d16] word.** HALT is a loop of two words (one tests the
  release, the other the take; a release is followed by an E whose start takes no
  maskable request), STOP the same loop with no take test; the halted stall is gone. The
  IE 0 release count is ACK + RESP - 4 (the count starts at the loop's release-test word).
  EI's restart of the scan and the INT pin's claim see IE's rise a register late. The
  scan sees a request as its strobe raises it; the timer's strobe a clock ahead (a net
  inside v35_sfr). INTP0's sampler half a clock later. The third word of BR far [d16] and
  CALL far [d16] is a word kind of its own that executes on a fetch's last clock when the
  queue's request line is down (declared OPEN: measured, why this word is not known). In
  HALT the take test is the dispatch's own term read ahead (`!nb_r && (nmi_v || g_ih)`)
  so the loop cannot reach the dispatch with nothing to take; the hang this closes was
  seen only in the grant trial and a directed sweep (haltsweep.py, 36 programs, in the
  gate) does not reproduce it on this tree. Open: the take out of HALT with IE 1 (4
  clocks early or late where no fetch is pending at HALT's pop). Not built: the
  controller's bus cycle (held for a mechanism), CLKOUT's stop count. Corpus 30,385 of
  30,536 (+4, F37; 0 lost). Lattice 9 of 27 programs equal (f5_la_w1 .. w9 all 40 of 40; h7
  and h0 24 of 32), phase 3 of 12, no program's count down; f5_lc_pa / pb,
  f5_ld_pa .. pd, f5_wx_c, f5_wy_m, f5_wz_n / o equal. Timing at 17 ns +2.985 / +2.873 /
  +2.703 ns; 9,812 LUT4, 569 ADD, 2,704 FF, 36 RAM_5K; ROM 1,966 words; no budget change.
