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
