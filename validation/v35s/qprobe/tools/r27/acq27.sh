#!/bin/sh
# acq27.sh round... : each round on the socket (every program twice), a log per round, one summary line each,
# the board's status read back at the end. (round 26's acq26.sh)
cd /home/wickerwaka/src/nuBoard/.claude/worktrees/agent-a2fca4e964ece5b07
mkdir -p build/qp/r27
for r in "$@"; do
  PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.qprobe.run --socket-fitted --round $r > build/qp/r27/acq-$r.log 2>&1
  echo "$r rc=$? $(tail -1 build/qp/r27/acq-$r.log | cut -c1-200)" >> build/qp/r27/acq-all.out
done
echo "ALL DONE" >> build/qp/r27/acq-all.out
PYTHONPATH=host/src:. uv run --with pyusb python -m nuboard.cli status > build/qp/r27/status-after.txt 2>&1
