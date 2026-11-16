# Round 10 divergence notes (additions and corrections to r9/divergence-table.md)

No new corpus replay was made this round (the RTL of this worktree is still the round-8 build;
`r9/fd9.jsonl` is the table's data). These notes re-read three "neighbour" rows of the round-9
cross-tab against the round-10 socket probes.

## 1. inc_m "behind the PUSH marker, 114 of 186": withdrawn as a neighbour effect

The probe of the exact chain (`LS; PUSH; INC word [BW]; PUSH marker; LS`, and nine relatives) is
reproduced by the model unchanged and by the round-8 RTL at all three waits and both alignments.
Re-tabulating the corpus runs that contain inc_m by chain name (`build/qp/incm_tab.py inc_m`):

| corpus chains | runs | outcome | what it is |
|---|---|---|---|
| `F5-push-inc_m-kN`, `F14-*-push-inc_bw*`, `F26-push-gih-inc-n0` | 42 | all equal | the plain chain: no effect |
| `F16-r-push-{dec,inc,neg,not}-inc_x`, `F15-k-push-not-*` | 36 | all equal | partners the RTL has |
| `F16-r-push-{div,divu,mul,mulu,mulub,rcl,rcr,rol,ror,sar,shl1,shlb,shr,test_imm,push}-inc_x` | 90 | all diverge, blamed on inc_m | the partner is an unread memory form; inc_m is only the oldest instruction in the window |
| `F15-k-push-{mulu,push,shl1}-inc_x` | 18 | diverge, blamed on inc_m | same |
| `F15-k-push-{mulu,push,shl1}-x_inc` | 18 | diverge, blamed on the partner | same chains, other order |
| `F5-push-inc_m-kN-odd`, `F5-out-inc_m-kN-odd` | 12 | diverge | the operand is a word at an odd address (two byte cycles each way): never measured |
| `F5 / F33 / F14 / F26 -out-inc*` | 16 of 54 | diverge | the OUT marker pairs; the 9 with the OUT imm8 marker are all W = 0 at even alignment: Q23 (spec 5 item A) |

So of the 136 inc_m misses about 108 belong to the partner's row (MUL / DIV / shift / rotate /
TEST imm / PUSH on memory: "own" of those forms), 12 to the odd-address operand, 16 to Q23.
The cross-tab's rule (the oldest instruction in the nine-byte window is the subject) mislabels
pair chains whose second member is the unread one. The same caution applies to every "pair"
and "predecessor" row whose partner is an unread form; a re-run of `fd9.py` that names the
subject by "first instruction the model does not have" would be the cheap fix, on the next
replay.

## 2. shl1 "behind the OUT imm8 marker, 72 of 72": confirmed, cause found

Probes `ib-*`: round-8 RTL 102 of 126, the misses exactly SHL AW,1 and TEST r,r behind OUT imm8
(6 + 6), SHL AW,1 behind OUT DW (6), TEST r,r behind OUT DW (2) and SHL AW,1 behind PUSH / a
store at 1 / 2 waits (2 + 2). Cause: a bus-idle word also waits for the EU's own cycle (Q26),
plus SHL r,1's second bus-idle word. The same rule should clear `test_dl_al` behind the OUT
marker (14 of 18) and the rare `mov_aw_dw` behind OUT imm8 is a different thing (no bus-idle
word in MOV r,r): left open.

## 3. cmp_aw_aw / cmp_aw_dw / mov_cw_imm1 "before Jcc / DBNZ only": confirmed as the branch's row

Probes `ic-*`, `id-*`, `ie-*`: round-8 RTL 195 of 414. Every miss is the branch (Q27, Q28): Jcc
behind a short predecessor at an even address at 1 / 2 waits (its fourth word waits for the
fetch its own opcode's pop started), Jcc taken at 2 waits (the second bus-idle word), and DBNZ /
BCWZ in every frame (routines not built: lead, positions). The CMP and the MOV CW rows should be
re-filed under be / bne / dbnz / dbnze / dbnzne / bcwz as "own".

## RTL (round-8 build) against the round-10 probes, by group

| group | runs | RTL exact | what the misses are |
|---|---|---|---|
| ia (INC mem behind P) | 84 | 84 | - |
| ip (PUSH marker behind write-ending routines) | 60 | 54 | XCH mem (not built) |
| ib (bus-idle-word routines behind P) | 126 | 102 | Q26, SHL r,1's second bus-idle word |
| ic + id (branches behind P) | 336 | 190 | Q27, Q28, the DBNZ routines |
| ie (DBNZ not taken, BCWZ) | 78 | 5 | routines not built |
| all | 684 | 435 | |
