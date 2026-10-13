# V35S cycle model (Phase 2, in progress)

The Python cycle model in `validation/v35s/model/` is the reference the new
RTL core will be written against ([`v35s-core-plan.md`](v35s-core-plan.md),
Phase 2). It runs a corpus image from reset and emits lane-format bus
traces. `python -m validation.v35s.fit` compares them with the silicon
corpus over each measurement window.

## Layout

| File | Role |
| --- | --- |
| `model/machine.py` | Clocked engine: bus cycles (B1 B2 waits B3), the prefetch queue, refresh, PRC/WTC/RFM, internal RAM and SFR storage, lane-format trace records |
| `model/eu.py` | Execution unit: decode and semantics for the V20/V35 instruction set, registers in the banked internal RAM, timing as named steps |
| `model/costs.py` | Every fitted number: bus-unit rules and per-step EU clocks |
| `fit.py` | Runs the model on corpus entries; `--prefetch ENTRY` compares the prefetch scenarios |

The EU is a generator. Each instruction yields its requests in order:
- `byte` takes a queue byte;
- `clocks` spends execution time;
- `read` and `write` are bus or internal accesses;
- `flush` handles a taken transfer.

The engine resolves them clock by clock against the bus unit.

## Fitting tools

| Tool | Scores |
| --- | --- |
| `fit.py` | whole windows and prefetch scenarios, cycle by cycle |
| `fit_costs.py` | per-placement instruction costs (window minus empty window), model against silicon |
| `fit_hide.py` | which routines hide a clock of a word load, from the odd-minus-even costs |
| `fit_steps.py` | EU step values, coordinate descent against `fit_costs`' measure |

The odd-minus-even cost of a form is independent of its step values, so it
scores the queue and decode structure on its own. Fit the structure with it
first, then the step values.

## Decode stage: what the data says

### Placement costs (A6, both placements)

| Form | Even | Odd |
| --- | --- | --- |
| NOP, XCH AW,r, CVTBW, PUSH r | 3/5, 3/5, 2/4, 8/10 | (odd pays 2) |
| INC/DEC r16, the flag operations, CVTWL, IN/OUT DW, LDM, MOVBK, POP r, POP R | — | odd pays 1 |
| 2-byte register forms | equal | equal |
| 2-byte memory reads | — | +1 at odd |
| TEST r,r, read-modify-write, the 0F immediate bit operations | — | −1 at odd |
| 3-byte imm16 forms | — | +2 at odd |

In a word-wide decoder, an instruction pays for loading the queue word that
its next byte sits in. These figures fit:
- a 2-clock word load;
- per routine, hiding one clock of either the next opcode's load (end) or an
  operand's load (mid).

`fit_hide.py` picks the hide bits routine by routine: total odd-minus-even
error 19 clocks over about 180 forms.

### Queue word release: the open question

The fetch that refills the slot behind a target at an even address (A6,
window clocks) depends on the target itself:

| Target | Refill fetch |
| --- | --- |
| register ModR/M forms, any length (ADD r,r 3 clocks, MULU CL 26) | 64 |
| imm8 / disp8 forms (MOV r8,imm, OUT imm, Bcc) | 67 |
| imm16 / disp16 forms | 68 |
| 1-byte forms | close to their end: CVTWL 71, POP r 73, STM 77, MOVBK 85, RET 90, PUSH R 138 |

Two queue models compete:

1. **Word register (implemented).** The EU moves the queue's head word into
   a word register, freeing its slot. There are 3 queue slots, plus the
   register.
   - It reproduces the depth scenarios and the NOP runways.
   - It cannot make the refill depend on the target's operands or length.
2. **Consumption.** There are 3 word slots, and a word frees when all of its
   bytes are consumed.
   - The next opcode is consumed by the previous instruction's last step.
   - Operand bytes are consumed at their micro-step: imm8/disp8 3 clocks
     after the opcode, imm16 at +4 and +7.
   - This is nuV30's "one queue byte per micro-op read".
   - It explains the table above, depth-odd, depth-2byte and the branch
     scenario, where silicon makes no fetch between a jump's decode and its
     refill.
   - It fails only depth-even, where silicon fills one word further while
     `SHL AW,16` runs.

The next step is to implement (2) as a queue mode, with operand reads placed
at their micro-steps. Then score both models on `fit.py`, `fit_costs.py` and
the prefetch scenarios. If neither closes depth-even, a directed board probe
should vary the bytes after a long instruction.

### Branches

- **Prefetch suspend (implemented, nuV30's SUSP):** a decided transfer stops
  prefetching until its flush.
- **Short branches:** silicon reaches the refill about 3 clocks later than
  the model. The time from the jump's opcode to its refill matches.
- **After a refill:** the first instruction at the target starts about 8
  clocks after the target fetch. Both are pending the queue-model decision,
  since both turn on when the jump's word is released.

## Bus-unit rules (stable under both queue models)

- **I/O recovery:** after an I/O cycle the bus stays idle one clock.
- **Posted writes:** the EU hands a write to the bus unit and goes on.
- **Odd targets:** after a flush the first fetch is a byte fetch at an odd
  target.
- **Refill:** back to back, 3 clocks apart at 0 waits.

## Status

On `a6-timing`, 558 runs, 2026-10-12: word-register model, fitted hide bits,
step values refitted by `fit_steps.py` (87 values changed):

| Measure | Result |
| --- | --- |
| Exact windows | 44 |
| Window length exact | 379 runs (68%) |
| Cycles matching in place | 72% (48% before the step refit, 32% at the previous checkpoint) |
| Window errors | mostly −1 to +3 clocks |

Window misses concentrate in:
- flow forms (branch and refill timing);
- the ±1 placement residue;
- traps.

The next step is unchanged: the consumption queue model.
