#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
core_dir="$repo_root/build/deps/fx68k/hdl"
output_dir="$repo_root/build/fpga/m68000/pin-test"
mkdir -p "$output_dir"

verilator --binary --timing --build -j 4 -Wno-fatal -Wno-PINMISSING \
    --top-module m68000_pins_tb --Mdir "$output_dir" \
    "$core_dir/verilator/fx68k.sv" \
    "$core_dir/verilator/fx68kAlu.sv" \
    "$core_dir/verilator/uaddrPla.sv" \
    "$project_dir/m68000_lane.sv" \
    "$project_dir/m68000_scope.sv" \
    "$project_dir/scope_encoder.sv" \
    "$project_dir/m68000_harness.sv" \
    "$project_dir/nuboard_mailbox.v" \
    "$project_dir/nuboard_debug_bridge.sv" \
    "$project_dir/nuboard_m68000.v" \
    "$project_dir/m68000_pins_tb.sv"

cd "$core_dir"
"$output_dir/Vm68000_pins_tb"
