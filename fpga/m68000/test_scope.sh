#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
encoder_dir="$repo_root/build/fpga/m68000/encoder-test"
mkdir -p "$encoder_dir"
verilator --binary --timing --build -j 4 -Wno-fatal \
    --top-module scope_encoder_tb --Mdir "$encoder_dir" \
    "$project_dir/scope_encoder.sv" "$project_dir/scope_encoder_tb.sv"
"$encoder_dir/Vscope_encoder_tb"
output_dir="$repo_root/build/fpga/m68000/scope-test-bram"
mkdir -p "$output_dir"
verilator --binary --timing --build -j 4 -Wno-fatal \
    --top-module scope_tb --Mdir "$output_dir" \
    "$project_dir/scope_encoder.sv" "$project_dir/m68000_scope.sv" \
    "$project_dir/scope_tb.sv"
"$output_dir/Vscope_tb"
