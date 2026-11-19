# W40 trial: a 2,048 x 40 ROM with the X / Y tables in block RAM (2026-11-18, base 031367d)

This was a timing experiment and nothing in it lands. The variants are in the worktree
`/home/wickerwaka/src/nuBoard/.claude/worktrees/agent-aae585b35cbcec172` under
`fpga/v35s/core/v35w*`. That worktree is not committed. Efinity 2026.1 ran on the T120F484
at 17 ns with `fpga/v35s/synth/v35_timing.sh`, unmodified, in its 20G memory-capped scope.
The script's only exception is the clock.

## Verdict

**Yes, it meets timing. 2,048 x 40 with the tables in block RAM is timing-feasible at 17 ns.**
- **As the study laid it out:** the worst seed is **+2.228 ns**. The three seeds are
  +2.635 / +2.228 / +2.576, against the base's +3.029 / +2.588 / +3.356.
- **With repair 3** (three one-bit flops beside the word, no extra ROM width): the seeds are
  **+2.362 / +3.105 / +3.132** (worst +2.362, a base-type path: ROM early bits -> the bus unit's pace; the worst table-headed path is then +3.105).

The cost is about 0.4 to 0.8 ns on the worst seed, and it is structural. The RAM's
clock-to-out (3.666 ns, against a flop's ~0.3) now heads every path that starts at a late
field: about a third of the 2,000 worst endpoints.

**RAM_5K: 64 in all**, against 108. That is the main ROM's 20, X 1, Y 4, and the rest of the
core's 39 unchanged. The study's figure of 16 for the ROM assumed 1,024 x 5 blocks. Efinity
built 2,048 x 40 as 20 blocks of 2,048 x 2, with no depth mux in front of the data, which is
better for timing.

**Fields that must stay raw: none beyond the 40 bits.** Three late fields need a one-bit flop,
each loaded at ce_a beside the word from information the tick-B logic already has:
- `k_cur`, from the early KW bit.
- the EU's `post`, from the early POST bit (the `pd.post` flop already exists).
- `q_susp`, from a compare of the Y address with the three SUSP entries.

`x_ivec` / `x_fint` can be handled the same way (a compare of the X address with one entry
each); the repair runs did that, but the gain is not separately measured. With these flops, no
path to the bus unit's grant or the pins starts at a table RAM. The paths that still start at
the tables are the ALU (`alu` -> SIGMA, `c_snz`), the segment-register write enable (`wr`) and
the register write data (`ws`, `ist`). Those are the core of the late payload. At about +2.4 to
+3.1 they are no longer the worst.

The logic expansion the user rejected **measured +1.544 / +1.687 / +1.438**. That is 7 to 9
LUT levels from the ROM to the word register, with 10,362 LUT4 (+632 over the RAM variant). So
the study's 8-level estimate was right, and that variant is the worse one by about 1 ns.

## 1. Structural validity

### The word register (v35_useq at 031367d)

- **Reads:** the ROM banks are read at ce_b (`l0..l2 <= rom[raddr]`, and `!reset_n || ce_b`).
  The address `raddr` is formed in tick A from the registered word.
- **Loads:** the word register `q0..q2` loads `r0..r2` (the read data) **at every ce_a, and
  every clock in reset** (`!reset_n || ce_a`). It has no enable, hold, flush or forced value.
- **Derived bits:** `pd <= pre(word_nx)` loads with it.

What the sequencer does to the word in each case:

| Case | What happens | Reproducible by a RAM read-enable plus the address? |
|---|---|---|
| **Stall** (`ex` = 0) | `raddr = upc`, so the same word is read again at ce_b and reloaded at ce_a. Nothing holds the register. | Yes. The table address is a function of the re-read ROM data, so the tables re-read the same entries. |
| **Dispatch** | Only `raddr`'s source changes (dent / UROM_INT). The register loads normally. | Yes |
| **Reset** | The ROM reads UROM_RESET every clock and the register loads it every clock. | Yes, with read-enable `!reset_n \|\| ce_a`, which is the register's own enable. |
| **Power-up** | The flops' initial value is 0. | The RAM output's initial state is 0. It is overwritten in reset anyway. |

**Nothing bypasses the register.** No mux sits between `word_nx` and the held word after tick
A. `word_nx` is read only in tick B, and `word` only after ce_a. The table RAM is therefore an
exact replacement for the late half of the register.

### Every field's readers ("nx" = from the ROM data in tick B; "reg" = after the register)

| Field | L40 | Read from `word_nx` (tick B) | Read from `word` (after ce_a) |
|---|---|---|---|
| e | raw K | useq `pre` (erep), `si_nx`, wk_bn; top -> loader `e_pop_nx` | useq x_end / x_nb / x_nbi / sp_n; EU pist / prefix; top -> loader `e_pop`, UROM_REPP |
| f | raw K | useq `si_nx.f` | EU opr_v (F) |
| nb, bi, vk, rl, ro, flush | raw K | useq wk_nx (the bus unit's pace); loader `ro_nx`, `flush_w_nx` | loader `ro`, `rl`, `flush_w`; useq x_flush, x_nb, q_susp (flush); EU SR_VEC (vk) |
| pop | raw | loader `pop_nx` | loader `pop` |
| wid | raw | EU `weff_n`, early read address | EU `weff`, rsel |
| ra, rb | raw (or payload) | EU early read address `sa_n` / `sb_n` | EU `ra_next` / `rb_next`, lanes |
| seq, cond, tgt | SEQ + B | useq `pre` (disp, dispm, tki) | useq address (tick A), cnt, retr; EU trap_o; top start_trap; EU SR_VEC reads tgt[7:0] |
| **bus** | Y | **useq `pre.post`**, which feeds the slot stall `st_r` | EU request (post, kinds, rq_*); top trace |
| **ea** | Y | **useq `pre.erep`**, which feeds the loader (`e_rep_nx`) | EU EA step, addr_n, pist, prefix |
| **d1, d2** | Y | **EU `k_nx`** (the next word loads OPRW), which feeds `req_v_nx` | EU moves, aq_b, **k_cur** (req_v) |
| s1, s2, wr, ws, seg, pfx, susp, halt, ist | Y | none | EU moves, the write port, segv_e, prefix, SR_PC; useq q_susp, w_stop, halted, x_nbi; loader e_pfx, w_halt |
| alu, ax, ay, wf, cnt | X | none | EU ALU, flags, the macro-service / DMA ops; useq cnt_n, w_stop, **x_ivec / x_fint** (the interrupt controller) |

**The study's split holds.**
- Three late fields are read in tick B: `bus`, `ea` and `d1` / `d2`. Each is read only through
  a one-bit fact (post, erep, KW), and L40 encodes each of those raw:
  - POST: `B[10]`, or `RA[1:0] = 3` on a target form.
  - EREP: SEQ code 1.
  - KW: `B[0]` of form N.
- No other late field is read before the register. Every reader of the early fields reads the
  raw bits.
- The trial's `check_addr.py` confirms on all 1,883 packed words that the RTL's table-address
  select returns exactly the X / Y payloads `layout.decode` gives.

**One point the study did not raise.** Moving the late fields behind a RAM turns the bus
unit's tick-A delivery chain into a RAM-headed path wherever a late field joins it:
- `k_cur` -> `req_v` -> grant -> `pk_ma` -> the pins
- `q_susp` -> the queue's request -> grant
- `post` -> `rq_v_nx` -> the pace (`ph`)

These were the worst table-headed paths (section 2). They need the one-bit flops of repair 3.

## 2. The trial build and its timing

### What was built (`v35w`)

- **ROM:** one ROM of 2,048 x 40 in block RAM, read at ce_b.
- **Contents:** the study's packer (`fit_shared.run("PH")` + `layout.encode`) run on this
  tree's ROM (031367d: 1,883 words after tail sharing, hold counts and the ways out). Every word
  passed `check_roundtrip`.
- **X:** 256 x 18, its 156 used entries.
- **Y:** 512 x 35 ({POST half, index}), its 185 used entries.
- **Tables:** X and Y are block RAMs read at `!reset_n || ce_a`. Their address comes from the
  ROM output through the form decode:
  - esc = RA[4:2] = 7; t = SEQ[4] | SEQ[3]; hold = SEQ in {3, 12}.
  - The pages are N, NH, NT, R (full / X+Y pages), RH, RT, with entry 0 for "no payload".
  - The table outputs drive every late-field reader in place of the register's bits.
- **Early fields:** K, POP, WID, RA, RB, SEQ -> seq / cond, B -> tgt (with the two TKI
  entries) stay in flops.
- **Derived bits:** `pd` (post, disp, tki, erep) comes from the raw bits. `word_nx.d1` carries
  KW for the EU's `k_nx`.
- **Removed:** the high ROM part (1,024 words), `hi_b`, `rah` / `lt_h` and the r = hi ? h : l
  mux.

**Not faithful:**
- **Hold counts are not built.** SEQ 3 runs as NEXT and 12 as JMP. A real hold needs a
  register-driven term in the tick-A address select, plus an empty payload on held clocks:
  read an empty ROM word, or force the table address to 0. Either costs about a level on a
  register-driven input.
- The dispatch entries, UROM_RESET and UROM_INT are the present ROM's constants, not the
  packed ROM's addresses.
- The `+v35_chk` checks were not adapted.
- It does not simulate the corpus and was not run.

All variants lint clean in Verilator with `-DSYNTHESIS`.

### Whole core (17 ns, seeds 1..3)

| Variant | s1 | s2 | s3 | Worst | LUT4 | FF | RAM_5K |
|---|---|---|---|---|---|---|---|
| base 031367d (brief) | +3.029 | +2.588 | +3.356 | +2.588 | 9,932 | 2,629 | 108 |
| **W40, tables in RAM (`v35w`)** | **+2.635** | **+2.228** | **+2.576** | **+2.228** | 9,730 | 2,579 | **64** |
| W40 + repair 2 (`v35wr2`: KW, POST, IVEC / FINT flops) | +2.524 | +2.507 | +2.398 | +2.398 | 9,686 | 2,568 | 64 |
| **W40 + repair 3 (`v35wr3`: + SUSP flop)** | **+2.362** | **+3.105** | **+3.132** | **+2.362** | 9,669 | 2,570 | 64 |
| W40, tables as LUT logic before the register (`v35wl`) | +1.544 | +1.687 | +1.438 | +1.438 | 10,362 | 2,620 | 59 |

All runs have ADD 587 (the base's is not given in the brief). The LUT logic variant has 59
RAM_5K: the ROM's 20 plus 39.

### Worst setup path per seed

| Variant / seed | Slack | Path | Levels |
|---|---|---|---|
| W40 s1 | +2.635 | ROM -> `useq/ph` (the word kind -> the bus unit's pace; a base-type path) | 8 |
| W40 s2 | +2.228 | **xtab (`alu`) -> x_ivec -> `ic_if[13]` CE** (the interrupt controller's acknowledge) | 8 |
| W40 s3 | +2.576 | **xtab (`alu`) -> SIGMA -> `sig_lo[3]`** | 7 |
| repair 2 s1 | +2.524 | ytab (`susp`) -> q_susp -> grant -> `c_mux_address[0]` | 8 |
| repair 2 s2 | +2.507 | loader `df.ent[9]` (a base path) | 7 |
| repair 2 s3 | +2.398 | xtab (`alu`) -> SIGMA -> `c_snz` | 8 |
| repair 3 s1 | +2.362 | ROM -> `useq/ph` (base-type) | 7 |
| repair 3 s2 | +3.105 | ytab (`wr`) -> `eu/ds0[2]` CE | 7 |
| repair 3 s3 | +3.132 | xtab (`alu` / `ax`) -> EU ALU operand `x_b[1]` | 8 |

Repair 3's worst table-headed path per seed: s1 +3.777 (ytab `wr` -> `eu/ss[3]` CE), s2 +3.105, s3 +3.132.

### Paths that start at a table RAM (W40, whole core)

- The RAM's Tco is 3.666 ns. The rest of the time is LUTs and routing.

| Seed | Worst from X | Worst from Y |
|---|---|---|
| s1 | +3.029, `alu` -> `sig_lo[0]`, L6 | +2.995, `d1` (KW) -> k_cur -> req_v -> bus f1/f2 -> `pk_ma` -> `c_mux_address[3]`, L10 |
| s2 | +2.228, `alu` -> x_ivec -> `ic_if[13]` CE, L8 | +2.724, `bus` -> post -> `e_rqv_nx` -> `b_ph_nx` -> `useq/ph`, L7 |
| s3 | +2.576, `alu` -> `sig_lo[3]`, L7 | +2.694, `d1` (KW) -> `c_mux_address[0]`, L9 |

**Spread:** about 650 to 720 of the 2,000 worst endpoints start at a table RAM, in every
variant. The other endpoint families, worst over the seeds:

| Endpoint family | Worst slack | Field | Levels |
|---|---|---|---|
| ds0 / ds1 / ps_base segment write enables | +2.79 to +3.4 | `wr` | 5 to 8 |
| regram write data | +3.1 to +3.7 | `ws` / `ist` | |
| psw_f | +3.2 to +4.5 | `alu` / `ist` | |
| bus `grant_len_b`, `pd_b`, `c_a0` | +3.4 to +4.6 | `d1`, then `susp` after repair 2 | |

(`fields.sh` reports the worst path per family from either table.)

### The worst path into a table RAM address (from the main ROM's output)

| Run | To X | To Y |
|---|---|---|
| top s1 | +4.076, L5 | +4.339, L4 |
| top s2 | +3.060, L5 | +3.375, L5 |
| top s3 | +3.841, L5 | +3.741, L5 |
| useq alone | +6.051, L4 | +5.109, L3 |

This path has margin. The form / page select is 3 to 5 LUT levels in tick B, and it was never
the worst path.

### Modules alone

| Module | Base 031367d (measured here) | W40 |
|---|---|---|
| useq | +6.201; 629 LUT4, 516 FF, 69 RAM_5K | +5.109, ROM -> ytab RADDR, L3; 603 LUT4, 379 FF, 25 RAM_5K |
| eu (tables inside the module, their addresses from the wrapper's input chain: `v35we`) | +5.152, ALU x_b -> psw, L17; 4,200 LUT4, 1,312 FF | **+3.882, ytab (`wr`) -> `ds0[1]` CE, L5**; 4,171 LUT4, 1,307 FF, 5 RAM_5K. The worst from X is +4.502, `alu` -> `y_b[7]`, L7 |
| useq, tables as LUT logic | | +2.023, ROM -> word register, L8; 1,296 LUT4 |

## 3. Repairs

The trial is above +2.0 on every seed, so no repair was required. Three were tried because
the loss was 0.4 to 0.8 ns. **None of them widens the ROM word.**

1. **KW flop for `k_cur`** (`v35wr`, folded into 2). The EU's `k_cur` is read only under an
   unarmed write (`rq_un`), where the current word loads OPRW exactly when it is the arming
   word, which is the KW word. A flop of the early KW bit therefore replaces `d1 == OPRW ||
   d2 == OPRW`.
2. **POST flop and IVEC / FINT flops** (`v35wr2`):
   - The EU's `post`, and the trace's post, read `pd.post` (it already exists).
   - `x_ivec` / `x_fint` read flops of `xa == 123` / `xa == 115`. In this packing those are the
     only X entries with AL_IVEC / AL_FINT. The assembler would fix them at known codes.
   - **Result:** the k_cur and post paths left the worst list. Seeds +2.524 / +2.507 / +2.398.
     The worst table path became `susp` -> q_susp -> grant -> pins (+2.524, s1).
3. **SUSP flop** (`v35wr3`, + repair 2): `q_susp` / `sp_n` read a flop of `ya in {106, 107,
   108}`, the three Y entries with SUSP. This adds about one level to the tick-B address path,
   which has 3 ns or more to spare. Seeds +2.362 / +3.105 / +3.132. No table-headed path is under +3.1 on any seed.

**Not tried:**
- **Moving the page select.** The address path into the tables is never critical (+3.06 at
  worst).
- **Registering `alu` / `wr` / `ws` raw.** They are 6 + 5 + 4 bits. That is the "widen the raw
  word" option (40 -> 55 bits, 28 blocks of 2,048 x 2), and the margins do not call for it.

## 4. Logic expansion, measured (`v35wl`)

The tables were kept out of block RAM with `(* syn_romstyle = "logic" *)`.
- Without it, Efinity folded the case-statement X ROM back into a RAM_5K.
- Y had to be split into two 256-entry halves, selected by the POST bit: 17,920 bits exceeds
  efx_map's 10,240-bit bit-blast limit.

**Results:**
- **useq alone:** +2.023, 1,296 LUT4 against 603 for the RAM variant, so the tables plus the
  select cost about 690 LUT4 before cross-module optimisation.
- **Whole core:** **+1.544 / +1.687 / +1.438**, 10,362 LUT4 (+632 over the RAM variant, +430
  over the base). The worst path in every seed is ROM data -> the expanded word register
  (`word.s2`, `word.s1`, `word.alu`) at 7 to 9 levels.

**The study's estimates hold:**
- Its "about 8 levels" is confirmed (7 to 9 measured).
- Its "about 900 LUT4" lands at about 630 to 690 measured.

This variant misses the +2.0 guide on every seed, about 0.8 to 1.0 ns behind the RAM variant.

## Files

All under `/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad/v2/w40-trial/`:

- **Diffs:** `trial-v35w.diff` is the trial. The others are the variants, each a full diff
  against `fpga/v35s/core/v35` at 031367d:
  - `trial-v35we.diff`: the EU alone with the tables.
  - `trial-v35wr2.diff`, `trial-v35wr3.diff`: the repairs (repair 1 is included in both).
  - `trial-v35wl.diff`: the logic variant.
- **`gen/`:** the generator and edit scripts.
  - `gen_hex.py`: packs the ROM and writes the hex.
  - `check_addr.py`: checks the RTL address select against `layout.decode`.
  - `edit_useq.py`, `edit_eu.py`, `edit_kw.py`, `edit_post.py`, `edit_logic.py`.
  - `tabpaths.py`.
- **`hex/`:** the packed ROM (2,048 x 40), X and Y.
- **`logs/`:** the summary lines of every Efinity run, plus `fields.sh` / `fromtab.sh` (the STA
  queries for paths from and to the tables).
- **Full build outputs:** in the worktree's `build/fpga/v35s/timing/v35_{top,useq,eu}{base,w40*}`.
