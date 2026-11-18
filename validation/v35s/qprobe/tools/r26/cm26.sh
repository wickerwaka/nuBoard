#!/bin/sh
# cm26.sh NAME [K=V ...]: corpus_model on the whole corpus with the options, to r26/work/NAME.jsonl (+ .txt); RTL miss list of land21
S=/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad
cd /home/wickerwaka/src/nuBoard/.claude/worktrees/agent-a2fca4e964ece5b07
n=$1; shift
if [ $# -gt 0 ]; then set -- --opt "$@"; fi
PYTHONPATH=host/src:. python3 validation/v35s/qprobe/tools/corpus_model.py --rtl-miss $S/v2/qprobe/land21/miss-v35_chk.jsonl --offsets $S/tools/out/offsets.json --jobs ${JOBS:-5} --out $S/v2/qprobe/r26/work/$n.jsonl "$@" > $S/v2/qprobe/r26/work/$n.txt 2>&1
