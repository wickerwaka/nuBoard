#!/bin/sh
# acq26.sh round... : each round on the socket (twice per program), log per round, one summary line each
cd /home/wickerwaka/src/nuBoard/.claude/worktrees/agent-a2fca4e964ece5b07
for r in "$@"; do
  PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.qprobe.run --socket-fitted --round $r > build/qp/r26/acq-$r.log 2>&1
  echo "$r rc=$? $(tail -1 build/qp/r26/acq-$r.log | cut -c1-200)" >> build/qp/r26/acq-all.out
done
echo "ALL DONE" >> build/qp/r26/acq-all.out
PYTHONPATH=host/src:. uv run --with pyusb python -m nuboard.cli status > build/qp/r26/status-after.txt 2>&1
