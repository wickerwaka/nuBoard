# Round 8, item 1: what the 17,280 non-exact corpus runs are made of

One replay of the corpus at the default spacing on this worktree (its RTL is 75e32c6's
behaviour; `+v35_chk` silent, 0 FAIL): **13,256 runs identical to silicon over the whole kept
list** (the scorer's own count: 13,268 RTL-exact), 17,280 not. The prelude part is silicon's
in every run (pre exact 30,536 of 30,536).

Method (`build/qp/fd8.py`, from step E1's firstdiv.py; `subj8.py`, `cat8.py`): per run, the
first bus event that differs (prelude tail and chain, aligned at the POP PSW read). It is
attributed to the *subject*: the oldest instruction whose first byte lies in the nine bytes
below the highest address silicon had fetched before that event (what can be running or
queued), skipping markers, NOPs, pads and drainers. In the cost-frame chains this names the
instruction under test. It is an attribution by position, not a proof of cause: the "register
forms" row is mostly the form *behind* a register instruction (CMP ; Jcc, ADD DW,imm ; OUT DW,
MOV CW,imm ; DBNZ), and "LS / END only" is a marker followed directly by the long shift.

## By mechanism family

| family | runs | share | forms | largest forms (runs) |
|---|---|---|---|---|
| read-modify-write and read-op on memory (ADD/INC/NOT/SHL/TEST/CMP mem...) | 4960 | 29% | 92 | add_m_aw 486, pop_m 318, add_m_imm 276, inc_m 246, push_m 162, add_m_imm_d16 144 |
| string / REP forms | 1929 | 11% | 35 | rep_stm_w 255, rep_inm_w 203, rep_movbk_w 196, rep_outm_w 155, repe_cmpbk_w 128, rep_ldm_w 118 |
| 0F page: bit and field ops, BCD (TEST1 SET1 CLR1 NOT1 EXT INS ROL4 ROR4 ADD4S ...) | 1854 | 11% | 57 | test1_mw_cl 150, set1_rw_cl 112, rol4_dl 108, ext_bl_dh 108, ext_dl_dh 84, ext_bl_i7 72 |
| register forms (MOV r,imm ; ALU r,r ; CMP ...) - the subject is probably the next form | 1806 | 10% | 50 | cmp_aw_aw 247, add_dw_imm0 242, cmp_aw_dw 132, mov_aw_dw 122, add_dw_imm2a01 120, add_dw_imm 92 |
| store immediate to memory (MOV mem,imm) | 1454 | 8% | 10 | st_imm_bw 321, st_imm_bw_d8 265, st_imm_bw_d16 262, st_imm_dir 168, st_imm_bw_ix_d16 122, st_imm_bw_ix_d8 95 |
| plain loads / stores / LDEA / XLAT / LDS-type | 1241 | 7% | 55 | st_bw 149, st_acc_dir 118, ld_bw_ix_d16 88, st_bw_ix_d16 78, st_acc_000e 75, ldea_bw 75 |
| CALL / RET / BR indirect and far, DBNZ, Jcc, INT / BRK / IRET | 1196 | 7% | 70 | call_n2 372, br_bw 90, dbnz_n0 67, be_n0 59, call_m_dir 52, bne_n0 35 |
| shifts by imm8 / by CL on register, MULU / MUL / DIV, loops in the EU | 1124 | 7% | 27 | shl_imm8 228, shl_imm4 156, shl1 112, mulu_aw 84, mul_cw 60, mul_aw_m_imm8 60 |
| PUSH / POP memory, PUSH / POP sreg, PUSH imm, PUSHA / POPA, PREPARE / DISPOSE | 1000 | 6% | 17 | pop_m_dir 138, pop_m_d8 138, pop_m_bw_ix_d8 96, pop_m_bw_ix_d16 96, pop_m_bw_d16 96, pop_m_bw_ix 84 |
| I/O forms (IN / OUT) | 309 | 2% | 5 | in_al_dw 144, out_dw_b 76, out_imm_al 47, in_aw_dw 36, out_dw_al 6 |
| LS / END only near (a marker followed by the long shift or the END) | 279 | 2% | 2 | LS 277, END 2 |
| other | 128 | 1% | 9 | shlb_m_imm4 36, shl_al_imm4 36, shlb_m_cl 12, lock_add_m_aw 12, cli 10, lahf 8 |

## Reading of the table

- **No single form dominates**: 429 forms, the largest 486 runs (2.8 %). The misses are the
  unread routines, family by family, not a front-end rule: the front end carries every run
  through the prelude and through the register-form chains.
- **Memory operands with more than one bus cycle or an immediate after the EA are 43 %**
  (read-modify-write and read-op 29 %, store-immediate 8 %, PUSH / POP memory 6 %): one reading
  (the second cycle of a routine: where its request word sits against the first cycle's end,
  and where the immediate leaves the queue against the EA bytes) should move most of them.
- Strings / REP 11 %, the 0F page 11 %, flushes 7 %, EU loops (shift by imm8, MULU / MUL / DIV)
  7 %, plain loads / stores in the EA modes not measured 7 %.
- Round 8's programs (`gen_r8.py`) cover these in that order: `rw-*`, `ea-*`, `es-*`, `st-*`,
  `t-*` / `em3-*`, `fl-*`, `si-*`. Not covered yet: PUSH / POP memory (FF /6, 8F /0), the REP
  forms beyond REP MOVBK, IN AL,DW, MUL / DIV.

## By form (top 120 of 429; an example run; the two commonest first differing events as
## kind, RTL minus silicon in clocks, or "other event" when the RTL makes a different event)

```
   486  add_m_aw                   F5-push-add_m_aw-k1-pE-w0                data_read -2: 383, fetch other event: 54
   372  call_n2                    F23-push-callret-pE-w0                   fetch -1: 193, fetch -3: 97
   321  st_imm_bw                  F5-push-st_imm_bw-k1-pE-w0               data_write other event: 174, data_write -4: 102
   318  pop_m                      F5-push-pop_m-k1-pE-w0                   stack_read -2: 130, stack_read -3: 122
   277  LS                         F0w-wtc8000-pE                           stack_write -4: 59, io_write -3: 52
   276  add_m_imm                  F5-push-add_m_imm-k1-pE-w0               data_read -4: 191, fetch other event: 35
   265  st_imm_bw_d8               F19-i-push-l0-stimmd8-pE-w0              data_write other event: 79, data_write -1: 69
   262  st_imm_bw_d16              F5-push-st_imm_bw_d16-k1-pE-w0           fetch other event: 100, fetch -3: 95
   255  rep_stm_w                  F24-out-r-rep-stm-w-n0-pE-w0             data_write -4: 74, data_write -2: 70
   247  cmp_aw_aw                  F23-out-be-n0-pE-w0                      fetch -1: 82, fetch -2: 51
   246  inc_m                      F5-push-inc_m-k1-pE-w0                   data_read -5: 102, fetch other event: 96
   242  add_dw_imm0                F10-push-adddwi-outdw-pE-w0              fetch -1: 179, fetch -3: 48
   228  shl_imm8                   F14-o-none-shl8-pE-w0                    fetch -2: 55, fetch -4: 46
   203  rep_inm_w                  F24-out-r-rep-inm-w-n0-pE-w0             io_read -3: 56, io_read -2: 52
   196  rep_movbk_w                F24-out-r-rep-movbk-w-n0-pE-w0           data_read -2: 64, data_read -4: 64
   168  st_imm_dir                 F21-push-l0-sti-dir-pE-w0                fetch -3: 71, fetch other event: 51
   162  push_m                     F5-push-push_m-k1-pE-w0                  data_read -5: 54, fetch other event: 42
   156  shl_imm4                   F3-push-shl_imm4-k1-pE-w0                fetch -2: 54, fetch -4: 25
   155  rep_outm_w                 F24-out-r-rep-outm-w-n0-pE-w0            data_read -3: 40, data_read -2: 36
   150  test1_mw_cl                F32-out-test1_mw_cl-k1-pE-w0             data_read -5: 74, data_read -4: 36
   149  st_bw                      F5-push-st_bw-k1-odd-pE-w0               fetch -1: 122, data_read -2: 9
   144  add_m_imm_d16              F5-push-add_m_imm_d16-k1-pE-w0           fetch other event: 66, fetch -3: 44
   144  in_al_dw                   F5-push-in_al_dw-k1-pE-w0                io_read -2: 55, io_read -4: 46
   138  cmp_m_imm                  F5-push-cmp_m_imm-k1-pE-w0               data_read -4: 81, fetch other event: 21
   138  test_dir_aw                F14-t-push-test_dir_aw-pE-w0             fetch other event: 78, fetch -3: 35
   138  pop_m_dir                  F15-p-push-pop_dir-pE-w0                 stack_read other event: 73, stack_read -2: 46
   138  pop_m_d8                   F15-p-push-pop_bw_d8-pE-w0               stack_read -2: 64, stack_read other event: 55
   132  cmp_aw_dw                  F34-out-nt-be-d-k1-pO-w1                 fetch -6: 30, fetch -1: 17
   128  repe_cmpbk_w               F24-out-r-repe-cmpbk-w-n0-pE-w0          data_read -4: 42, data_read -2: 40
   126  test_m_aw                  F5-push-test_m_aw-k1-pE-w0               data_read -5: 41, data_read -4: 31
   126  not_m                      F5-push-not_m-k1-pE-w0                   data_read -5: 48, fetch other event: 42
   122  mov_aw_dw                  F7-push-mov_aw_dw-add_m_aw-pO-w0         fetch other event: 28, io_read -4: 22
   122  st_imm_bw_ix_d16           F21-push-l0-sti-bw_ix_d16-pE-w0          fetch -1: 56, fetch -4: 32
   120  shl_m1                     F5-push-shl_m1-k1-pE-w0                  data_read -5: 44, fetch other event: 39
   120  add_m_imm_d8               F22-push-l0-add_d8-pE-w0                 data_read -1: 32, fetch -2: 30
   120  add_m_imm_dir              F22-push-l0-add_dir-pE-w0                fetch other event: 46, fetch -3: 44
   120  cmp_m_imm_d16              F22-push-l0-cmp_d16-pE-w0                fetch other event: 46, fetch -3: 44
   120  test_m_imm_d16             F22-push-l0-test_d16-pE-w0               fetch -5: 44, fetch -3: 42
   120  add_dw_imm2a01             F35-out-ctl-adddw-pE-w0                  fetch -1: 120
   118  st_acc_dir                 F5-out-st_acc_dir-k1-pE-w0               fetch other event: 60, fetch -5: 36
   118  add_m_imm8_d16             F22-push-l0-add8_d16-pE-w0               fetch other event: 45, fetch -3: 44
   118  rep_ldm_w                  F24-out-r-rep-ldm-w-n0-pE-w0             data_read -2: 38, data_read -4: 38
   112  shl1                       F3-out-shl1-k1-pE-w0                     fetch -1: 52, io_read -2: 14
   112  set1_rw_cl                 F32-out-set1_rw_cl-k1-pE-w0              fetch -5: 27, fetch -4: 20
   108  rol4_dl                    F32-out-rol4_dl-k1-pE-w0                 fetch -4: 26, fetch -2: 21
   108  ext_bl_dh                  F32-out-ext_bl_dh-k1-pE-w0               data_read -6: 52, data_read -5: 27
   104  repne_cmpm_w               F24-out-r-repne-cmpm-w-n0-pE-w0          data_read -4: 34, data_read -2: 32
    96  add_m_aw_bw_ix_d16         F21-push-l0-add-bw_ix_d16-pE-w0          fetch other event: 40, fetch -1: 27
    96  pop_m_bw_d16               F21-push-l0-pop-bw_d16-pE-w0             stack_read other event: 50, stack_read -2: 34
    96  pop_m_bw_ix_d8             F21-push-l0-pop-bw_ix_d8-pE-w0           stack_read -2: 48, stack_read other event: 36
    96  pop_m_bw_ix_d16            F21-push-l0-pop-bw_ix_d16-pE-w0          stack_read other event: 50, stack_read -2: 34
    95  st_imm_bw_ix_d8            F21-push-l0-sti-bw_ix_d8-pE-w0           fetch other event: 25, data_write -1: 23
    94  st_imm_bw_ix               F21-push-l0-sti-bw_ix-pE-w0              data_write other event: 47, data_write -4: 34
    92  add_dw_imm                 F2-push-add_dw_imm-pE-w0                 fetch -1: 46, fetch -3: 34
    90  mulu_m                     F5-push-mulu_m-k1-pE-w0                  fetch other event: 30, data_read -5: 30
    90  cmp_m_imm8                 F19-i-push-l0-cmpimm8-pE-w0              data_read -3: 69, fetch other event: 9
    90  br_bw                      F35-out-ind-brr-n0-pE-w0                 fetch 2: 36, fetch 4: 18
    88  ld_bw_ix_d16               F4-push-ld_bw_ix_d16-k1-pE-w0            fetch -1: 78, fetch other event: 10
    88  st_imm8_bw                 F19-i-push-l0-stimm8-pE-w0               data_write -3: 55, data_write other event: 20
    87  mov_cw_imm1                F23-push-dbnz-c1-n0-pO-w0                fetch -5: 48, fetch -1: 18
    84  mulu_aw                    F14-g-push-mulu_aw-pE-w0                 fetch -1: 17, fetch -2: 13
    84  pop_m_bw_ix                F21-push-l0-pop-bw_ix-pE-w0              stack_read -3: 42, stack_read -2: 35
    84  ext_dl_dh                  F32-out-ext_dl_dh-k1-pE-w0               data_read -6: 40, data_read -5: 20
    81  add_m_aw_bw_ix             F21-push-l0-add-bw_ix-pE-w0              data_read -2: 72, fetch other event: 6
    78  st_bw_ix_d16               F21-push-l0-st-bw_ix_d16-pE-w0           fetch -1: 70, fetch other event: 8
    78  add_m_aw_bw_d16            F21-push-l0-add-bw_d16-pE-w0             fetch other event: 48, fetch -3: 27
    78  add_m_aw_dir               F21-push-l0-add-dir-pE-w0                fetch other event: 48, fetch -3: 27
    76  out_dw_b                   F19-d-push-adddwi-outb-pE-w1             fetch -3: 21, fetch other event: 21
    75  ldea_bw                    F25-push-ldea-bw-pO-w0                   stack_write -4: 20, fetch 1: 15
    75  st_acc_000e                F37-out-ctl-vec3-pE-w0                   data_read -2: 74, fetch -1: 1
    74  add_m_aw_bw_d8             F21-push-n1-add-bw_d8-pO-w0              fetch other event: 26, data_read -2: 18
    74  add_m_aw_bw_ix_d8          F21-push-n1-add-bw_ix_d8-pO-w0           fetch other event: 26, data_read -2: 18
    72  movbk_w                    F24-out-s-movbk-w-k1-pE-w0               data_read -3: 62, data_read -4: 5
    72  cmpbk_w                    F24-out-s-cmpbk-w-k1-pE-w0               data_read -3: 62, data_read -4: 5
    72  stm_w                      F24-out-s-stm-w-k1-pE-w0                 data_write -2: 47, data_write -1: 15
    72  inm_w                      F24-out-s-inm-w-k1-pE-w0                 io_read -3: 67, io_read -4: 5
    72  ext_bl_i7                  F32-out-ext_bl_i7-k1-pE-w0               data_read -7: 26, data_read -5: 18
    69  add4s                      F32-out-add4s-n2-k1-pO-w0                data_read -2: 23, data_read -3: 23
    67  dbnz_n0                    F23-push-dbnz-c1-n0-pE-w0                fetch -2: 17, fetch -3: 17
    66  add_aw_m                   F5-push-add_aw_m-k1-pE-w0                fetch other event: 18, data_read -2: 18
    66  cmp_aw_m                   F5-push-cmp_aw_m-k1-pE-w0                fetch other event: 18, data_read -2: 18
    66  set1_mw_cl                 F32-out-set1_mw_cl-k1-pE-w0              data_read -5: 32, data_read -4: 15
    66  mov_cl2                    F32-out-add4s-n2-k1-pE-w0                data_read -2: 22, data_read -3: 22
    62  ld_bp_iy_d16               F4-push-ld_bp_iy_d16-k1-pE-w0            fetch -1: 56, fetch other event: 6
    60  xch_m_aw                   F5-push-xch_m_aw-k1-pE-w0                data_read -2: 21, fetch other event: 15
    60  push_r                     F25-push-pushr-pE-w0                     stack_write -3: 35, stack_write -2: 15
    60  prepare_00                 F25-push-prepare-pE-w0                   stack_write other event: 60
    60  push_ds0                   F25-push-push_ds0-pE-w0                  stack_write -3: 60
    60  set1_mw_cl_bw_ix           F32-out-set1_mw_cl_bw_ix-k1-pE-w0        data_read -5: 30, data_read -4: 15
    60  ins_bl_dh                  F32-out-ins_bl_dh-k1-pE-w0               data_read -6: 27, data_read -5: 14
    60  ins_bl_i7                  F32-out-ins_bl_i7-k1-pE-w0               data_read -7: 20, data_read -5: 14
    60  mul_cw                     F33-out-mul_cw-ld-k1-pE-w0               fetch -1: 18, fetch -2: 12
    60  mul_aw_m_imm8              F33-out-mul_aw_m_imm8-k1-pE-w0           data_read -3: 27, fetch 3: 12
    59  be_n0                      F23-out-be-n0-pO-w0                      fetch -1: 31, fetch -3: 24
    56  xch_aw_dw                  F10-push-xch-indw-pE-w0                  data_read -2: 21, io_read -2: 17
    54  dec_m                      F16-r-push-dec-x_x-pE-w0                 data_read -5: 21, fetch other event: 15
    52  mul_aw_m_imm16             F33-out-mul_aw_m_imm16-k1-pE-w0          data_read -4: 23, data_read -3: 12
    52  call_m_dir                 F37-out-indm-callm-n0-pE-w0              fetch -3: 46, data_read other event: 4
    50  set1_rb_cl                 F32-out-set1_rb_cl-k1-pE-w0              fetch -5: 12, fetch -4: 11
    50  repc_cmpm_w                F33-out-repc-cmpm-w-n1-stc-pE-w0         data_read -4: 16, data_read -2: 14
    49  mov_dw_aw                  F10-push-movdwaw-indw-pE-w0              io_read -4: 12, data_read -2: 9
    48  mulu_dw                    F3-push-mulu_dw-k1-pE-w0                 fetch -1: 14, fetch -2: 8
    48  nops / marker only         F6-push-ld_bw-n2d4-pE-w0                 fetch -1: 48
    48  neg_m                      F14-t-push-neg_bw-pE-w0                  data_read -5: 21, fetch other event: 15
    48  and_aw_m                   F15-a-push-and_aw_bw-pE-w0               fetch other event: 12, data_read -2: 12
    48  and_m_imm8                 F15-a-push-and_bw_imm8-pE-w0             fetch other event: 12, data_read -3: 12
    48  clr1_mw_cl                 F32-out-clr1_mw_cl-k1-pE-w0              data_read -5: 21, data_read -4: 10
    47  out_imm_al                 F7-push-out_imm_al-add_m_aw-pE-w0        fetch -1: 16, io_read -3: 12
    46  clr1_mw_imm                F32-out-clr1_mw_imm-k1-pE-w0             fetch other event: 23, data_read -2: 20
    46  set1_mw_imm                F32-out-set1_mw_imm-k1-pE-w0             fetch other event: 23, data_read -2: 20
    42  push_aw                    F7-push-push_aw-add_m_aw-pE-w0           fetch -3: 12, fetch other event: 8
    42  test_m_imm                 F14-t-push-test_bw_imm-pE-w0             data_read other event: 19, data_read -4: 14
    42  divu_m                     F14-g-push-divu_bw-pE-w0                 data_read -5: 27, fetch other event: 9
    42  or_m_aw                    F15-a-push-or_bw_aw-pE-w0                data_read -2: 18, fetch other event: 12
    42  mov_cl_imm                 F19-d-push-movcl-inb-pE-w0               io_read -2: 9, data_read -2: 8
    42  ext_dl_bh                  F32-out-ext_dl_bh-k1-pE-w0               data_read -6: 21, data_read -5: 11
    42  ext_dl_i11                 F32-out-ext_dl_i11-k1-pE-w0              data_read -7: 17, data_read -5: 11
    42  ins_dl_bh                  F32-out-ins_dl_bh-k1-pE-w0               data_read -6: 21, data_read -5: 11
    42  ins_dl_i11                 F32-out-ins_dl_i11-k1-pE-w0              data_read -7: 17, data_read -5: 11
    41  rep_inm_b                  F24-out-r-rep-inm-b-n0-pE-w0             io_read -2: 12, io_read -3: 12
429 classes, 17280 runs, 13256 exact
```
