#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/m68000/lane-test"
mkdir -p "$output_dir"

verilator --binary --timing --build -j 4 --top-module m68000_lane_tb \
    --Mdir "$output_dir" \
    "$project_dir/m68000_lane.sv" "$project_dir/m68000_lane_tb.sv"
"$output_dir/Vm68000_lane_tb"
