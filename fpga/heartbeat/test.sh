#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/heartbeat/verilator"

mkdir -p "$output_dir"

verilator --binary --timing -j 0 \
    --top-module heartbeat_tb \
    --Mdir "$output_dir" \
    "$script_dir/heartbeat.v" \
    "$script_dir/heartbeat_tb.v"

"$output_dir/Vheartbeat_tb"
