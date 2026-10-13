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

## Bus-unit rules established so far

The rules below reproduce the prefetch scenarios' queue depths and the
whole NOP runway of every A6 window, cycle for cycle.

- **Queue capacity: 4 words.** A word slot is held from the start of its
  fetch until the EU has moved past it: until the EU takes a byte from a
  later word.
  - This gives 7 bytes queued past an instruction that ends on an even
    address and 6 past one that ends on an odd address.
  - After a 2-byte instruction such as `MULU CW`, the queue holds 3 words
    beyond it.
  - With NOPs, one fetch happens per two NOPs.
- **Refill:** a freed slot can be refilled from the next clock. Fetches run
  back to back, 3 clocks apart at 0 waits.
- **I/O recovery:** after an I/O cycle the bus stays idle one clock before
  the next cycle. A fetch follows an OUT 4 clocks after its start, against
  3 after a memory cycle.
- **Posted writes:** the EU hands a write to the bus unit and goes on. The
  marker OUT's write starts one clock after the next instruction has begun.
- **Odd targets:** after a flush, the first fetch is a byte fetch at an odd
  target.

## EU observations folded in or pending

- **NOP:** 4 clocks.
- **Shifts:** `SHL reg,imm8` takes its ModR/M byte 3 clocks after the
  opcode and ends 44 clocks after the opcode for a count of 16. Taken from
  the threshold scenario's word-release times.
- **Branches:**
  - Silicon takes a short branch's opcode about 3–4 clocks later than the
    model does after a NOP or SHL.
  - It starts no fetch while a jump is being decoded, where the model
    fetches.
  - The first instruction after a refill starts about 8 clocks after the
    target fetch; the model starts it as soon as the bytes arrive. *Pending.*
- **OUT imm8 at the end of the window:** 14 clocks from the start of the OUT
  to its write, against a measured retire-to-retire cost of 10. This points
  to decode overlapping the previous instruction's execution, a pipeline
  stage the model does not have yet. *Pending, and the main structural item
  left.*

## Status

Model status on `a6-timing`, 558 runs, 2026-10-12:

| Measure | Result |
| --- | --- |
| Runs that complete | all 558 |
| Exact windows | 0 |
| Cycles matching in place | 32% |
| Typical window error | model 7–12 clocks short |

The common shortfall is the missing decode/execute overlap and the
branch-refill decode delay above. Next:

1. Model the decode stage (prefetch of the next opcode, ModR/M take timing)
   from the threshold and branch scenarios.
2. Refit the step costs per class against A6, then the follow-up suites.
3. Check the semantics against SingleStepTests V20 (fetch the suite per
   `build/deps/nuV30/tests/v30/v20suite/README.md`).
