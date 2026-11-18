"""sim26.py OUTDIR run.py-args...: the qprobe runner's sim backend with the MAIN tree's RTL build (binary and ROM files:
cwd = the main tree), this worktree's generators. Nothing is written in the main tree."""
import sys
from pathlib import Path
sys.path[:0] = ["host/src", "."]
from validation.v35s.chains import acquire as A
MAIN = Path("/home/wickerwaka/src/nuBoard")
A.ROOT = MAIN
A.SIM_CORES["v35"] = (MAIN / "build/fpga/v35s/verilator-direct-v35/Vv35s_harness", A.SIM_CORES["v35"][1])
from validation.v35s.qprobe import run
sys.exit(run.main(["--backend", "sim", "--output-dir", sys.argv[1]] + sys.argv[2:]))
