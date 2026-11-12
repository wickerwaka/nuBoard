#!/usr/bin/env bash
# V35S behavioural tests: the scripted-bus lane regression and a dual-model
# differential run through the Python runner.
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
shared_dir="$repo_root/fpga/m68000"
tb_dir="$repo_root/build/fpga/v35s/tb-lane"

mkdir -p "$tb_dir"
verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style \
    --top-module v35s_lane_tb --Mdir "$tb_dir" \
    "$project_dir/v35s_lane_tb.sv" "$project_dir/v35s_harness.sv" \
    "$project_dir/v35s_lane.sv" "$project_dir/v35s_stim.sv" "$project_dir/v35s_model_stub.sv" \
    "$shared_dir/m68000_scope.sv" "$shared_dir/scope_encoder.sv" >/dev/null
"$tb_dir/Vv35s_lane_tb" | tee "$tb_dir/result.txt"
grep -qx "PASS: v35s_lane_tb" "$tb_dir/result.txt"

"$project_dir/build_sim.sh" dual >/dev/null
cd "$repo_root"
PYTHONPATH=host/src:. python3 -m validation.v35s.runner --backend dual-sim --mode both \
    --output build/validation/v35s/dual-sim.json \
    validation/v35s/programs/*.s
PYTHONPATH=host/src:. python3 -m unittest validation.v35s.test_v35s
# F0: the input schedule, pin records, the INTAK answer, the dump (needs the
# direct build for its register tests; they skip without it).
"$project_dir/build_sim.sh" direct >/dev/null
PYTHONPATH=host/src:. python3 -m unittest validation.v35s.test_stim
