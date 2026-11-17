# V35S validation-loop tools: corpus_model, cluster, romcheck

Three plain Python scripts. Run them from a repo checkout root with `PYTHONPATH=host/src:.`
(they also put `host/src` and `.` on the path themselves). They read the silicon corpus
(`build/validation/v35s/corpus`, symlinked into a worktree if needed) and, for the synthetic
programs of romcheck, the nuV30 assembler (`build/deps/nuV30`). Nothing in the tree is written;
`uasm` is never run (romcheck imports the assembler module and calls `assemble()` in memory).
Each script has `--help`. Parallelism: `--jobs` (default 3).

Typical loop (about 5 minutes for all three on the whole corpus):

    T=path/to/tools; M=path/to/landNN/miss-v35_chk.jsonl
    python3 $T/corpus_model.py --rtl-miss $M --out cm.jsonl --offsets offsets.json   # ~1.5 min
    python3 $T/romcheck.py --cache chains.json --out romcheck.json                     # ~1 min
    python3 $T/romcheck.py --rom-root OTHER_TREE --cache chains.json --out rc2.json    # another ROM
    python3 $T/cluster.py --model cm.jsonl --rtl-miss $M --chains chains.json --out clusters.json

`chains.json` is a cache of the corpus chains (ids, code, chain base; no traces) that romcheck
and cluster build on first use (~15 s) and share.

## A. corpus_model.py: the reading model on the corpus

Runs `validation/v35s/qprobe/model_m.py`'s `simulate` on every corpus run (30,536 in the
families of the miss list) and compares its bus events with the run's silicon trace.

- Input to the model: the corpus run record as it is (chain, code_hex, chain_base: the model's
  qprobe input format is the corpus's). The model starts at the end of the first long shift.
- Clock mapping: the model's clocks are the qprobe frame's (M0 = 0); the corpus frame has no M0,
  so one offset per frame group (waits x parity x prelude marker) maps them to the run's clocks.
  It is calibrated once (`--offsets`, `--recalibrate`) as the most common difference between
  silicon's and the model's first event after the fill over every 7th run. On the corpus it is
  unanimous to within 0.6 % of the sampled runs: w0 +20 / +17, w1 +22 / +20, w2 +26 / +24 (even /
  odd).
- Exactness: silicon's events after t_fill up to and including the END block's OUT to FF00h
  against the model's events in the same span, as (clock, kind, fetch address); kinds F, R
  (data or stack read), W (data or stack write), O (I/O write), I (I/O read).
  **Difference from `replay --score`**: replay compares (clock, kind, address, width, length)
  over the whole trace after t_fill. Not compared here: data-cycle addresses and I/O ports (the
  model tracks DW only from MOV DW,imm16 and no data addresses: function, not timing), widths
  and lengths (the model's follow from the waits), and anything after the END's OUT.
- Not modelled: runs with a refresh cycle in the window (none in the 30,536), F0w (waits by WTC,
  20 runs). `no routine`: the model raised KeyError in `info()` / `routine()` (an opcode or
  ModR/M form not in its tables), reported with the encoding and form. `model error`: any other
  exception (pointer / vector values the model does not track, RET with no CALL, running
  outside the chain after a wrong transfer target).
- Output per run (JSON lines): status, model-exact, the first divergence (index, silicon
  event, model event, class, clock from M0), the model's timeline (its boundaries in run clocks
  with the bytes held), the model keys used. Totals, the no-routine list and the cross-tab
  against one or more miss lists (`--rtl-miss A B`).

## B. cluster.py: divergence clustering

For every diverging run (the RTL rows of the miss list, and the model misses from A) a
first-divergence signature: the instruction executing at the divergence (from A's model
timeline; the chain's form name, or M<i>:<kind>, LS:*, END:*, PAD), the instruction before it,
parity, waits, the bytes held at its boundary (the model's count), the divergent event's kind
(fetch / read / write / io early or late by n, missing / extra, kind vs kind), and whether the
subject sits directly behind the frame's first marker. Views: 1 the whole signature; 2 without
the instruction (states across instructions); 3 coarse (predecessor, parity, frame). Each
cluster prints its count and three example run ids; `--out` saves every row's signature and
every view's cluster -> run ids.

Limits: the attribution uses the model's timeline, which is right only up to the model's own
first divergence (rows past it are flagged `timeline_ok: false`); runs the model cannot run get
the subject's name with `?` and no held count. The RTL rows' class comes from the miss list's
(silicon, RTL) event pair alone (no RTL event list is read), so "missing" / "extra" are only
detected as "kind vs kind".

## C. romcheck.py: the ROM against the model's routine strings

For every encoding the corpus holds as a subject (prefixes stripped), the ROM path the
sequencer executes for it (decode cell, the dispatch's EA head chosen as `v35_loader.sv` does,
including `eaq16x`; the 0F EAC call; calls, jumps, loops) is turned into the model's act
notation and compared with model_m's routine for the same encoding, three ways: the literal
word string; a timing-equivalence simulation in the model's own machine (the ROM-derived routine
substituted for the subject on 42 synthetic programs and up to 24 corpus runs; any bus event
different = differs); the decode facts beside the routine (lead, the three-bytes wait). It also
lists model keys whose encodings run different ROM routines.

The act mapping (documented in `--help`): ro N; rl=1 P; rl=2 P P2; the loader's ModR/M release
P on the first word; bi B; bi + alt C; bi + alt on an rl=2 word I (the main tree's `strict`);
rl=x + bi the Y wait, + alt V; rl=x alone the slot wait (X with an I/O request, else S), + alt
A; f D; flush F (its bi dropped: the model's F waits as B does); MEMWD's arming word K; a post
on word p: the routine's first post, or one three words after an rl=x word, puts the request
act on word p-3 (the model's POST_LAT 4 = the RTL's post + grant), a later post Z / U on word
p-1 (Z_LAT 2); `bus=RSV` (main tree) is not a post.

Exact: the ROM path (the sequencer's next-address rules, the dispatch's heads), the releases
and wait kinds, the post positions. Approximate: request timing is taken from the post's word
position in an unstalled path (a stall between the rl=x word and the post moves the RTL's
request but not the derived one); the counter from SIGMA and data-dependent conditions
(SGN / DTRAP / SGD / DN: taken false) make the EXT / INS / BCD / multiply-sign paths
approximate, so those encodings are reported `not covered`. Not derived: the model's G
(the word that completes the clock before the EU's cycle) and Q acts (no ROM bit; they show as
shape differences, which the simulation then judges), REP strings (the model builds them from
the prefix and CW), prefixes (the model runs them as their own instruction, `PFX`).
Transfers that need stack or pointer state get no simulation (`shape differs, no sim run`).
