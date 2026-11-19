#!/bin/sh
# acq27b.sh round... : as acq27.sh through tools/r27/run27.py (the READY-held and refresh runs of the stall maps)
cd /home/wickerwaka/src/nuBoard/.claude/worktrees/agent-a2fca4e964ece5b07
mkdir -p build/qp/r27
for r in "$@"; do
  PYTHONPATH=host/src:. uv run --with pyusb python validation/v35s/qprobe/tools/r27/run27.py --socket-fitted --round $r > build/qp/r27/acq-$r.log 2>&1
  echo "$r rc=$? $(tail -1 build/qp/r27/acq-$r.log | cut -c1-200)" >> build/qp/r27/acq-all.out
done
echo "ALL DONE B" >> build/qp/r27/acq-all.out
PYTHONPATH=host/src:. uv run --with pyusb python -m nuboard.cli status > build/qp/r27/status-after.txt 2>&1
