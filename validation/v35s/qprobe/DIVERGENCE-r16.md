# Divergence notes, round 16

RTL: unchanged in the worktree (the unlanded 6+7 copy; its REP MOVBK function fault is the
builder's). No corpus replay; the cross-tab is round 14's (`fd14-tab11.json`), re-classified by
`tab12.py` with the round-16 model: `traces/logs/tab12.txt`.

| | round 14 | round 16 model |
|---|---|---|
| diverging, filed | 10,017 | 10,017 |
| read, not built | 8,610 | 9,553 |
| partly read | 1,096 | 344 |
| probed, not read | 12 | 30 |
| not probed | 299 | 90 |

## What left "partly read" (752 runs) and why

- EXT / INS register-count rows (360): no timing rule was missing. Round 9's X ; X probes ran
  the second instance at another offset (the instruction advances its offset register) and
  with another count (AL reloaded by EXT). With the count in DH / BH and the offset update in
  the model: 120 / 120.
- call_m_dir (96): round 12's shape was fitted behind a store in the body and was wrong;
  re-read standing alone (48 / 48, JMP [d16] 48 / 48).
- brk3 (80): the routine was right; the misses were the vector stores in the probe's body.
- The 0F r,CL and r,imm rows: one fact for the page (the ModR/M byte's release is bus-idle),
  and the imm forms one word shorter.
- lahf: two words, not three.

## What is still partly read (344) and whether it is a real gap

- MUL / DIV on memory, about 250 runs: **not a gap in the instruction**. 144 / 144 in a clean
  frame; the signature is held under 90 % by round 12's 48 frame misses, which are in front of
  the MUL (the fetch behind MOV [BW],imm16 ; MOV r,imm16 at even alignment with waits). That
  frame effect is real and unread; it will also show in the corpus wherever a MOV mem,imm16 is
  followed by a MOV r,imm16 at W >= 1.
- lds_aw_ix 36: probe artefact (LDS ; LDS changes DS0); LES is exact.
- neg_m_bw_d16 21, mul_aw_cw_imm8 18: real, small.
- far transfers 21 (other causes): CALL far with waits, not re-probed.

## The model's misses now (form probes, 554 of 11,490)

330 are the interrupt-frame programs of rounds 14 / 15 that the model does not simulate
(`sw-*`, `t-*`: counted in the total, never meant to pass). The other 224, by description: Q42's
residue behind MOV mem,imm16 (`fw-c7-*`, `mm-*`: about 60), MUL r,r,imm8 at two waits (20), the
transfers' frame misses (11), CVTBD (24), the far transfers (16), ADD [d16],imm8 back to back
(9), EXT r,imm4 (7), NEG d16 (5), and the older rounds' singles.

## Build check

Not repeated (no new tree). The two older misses named in round 14's build check are diagnosed
in `rtl-spec12.md` C1 (JMP near: `v35_queue.sv`, the five-held continuation on the flush clock)
and C2 (LEA: one word and a `bi`).
