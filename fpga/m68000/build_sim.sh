#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
core_dir="$repo_root/build/deps/fx68k/hdl"
variant=${1:-direct}
top_module=m68000_harness
main_file=sim_main.cpp
extra_sources=()
extra_options=()
if [[ "$variant" == spi ]]; then
    top_module=nuboard_m68000
    main_file=sim_spi_main.cpp
    extra_sources=("$project_dir/nuboard_m68000.v"
                   "$project_dir/nuboard_mailbox.v"
                   "$project_dir/nuboard_debug_bridge.sv")
elif [[ "$variant" == dual ]]; then
    top_module=m68000_dual_sim
    extra_sources=("$project_dir/m68000_dual_sim.sv")
    extra_options=(-CFLAGS -DNUBOARD_DUAL_SIM)
elif [[ "$variant" != direct ]]; then
    echo "usage: $0 [direct|spi|dual]" >&2
    exit 2
fi
output_dir="$repo_root/build/fpga/m68000/verilator-$variant"
mkdir -p "$output_dir"

# The same upstream Verilator-compatible HDL is synthesized for the board.
verilator --cc --exe --timing --build -j 4 -Wno-fatal \
    --top-module "$top_module" --Mdir "$output_dir" \
    "$core_dir/verilator/fx68k.sv" \
    "$core_dir/verilator/fx68kAlu.sv" \
    "$core_dir/verilator/uaddrPla.sv" \
    "$project_dir/m68000_lane.sv" \
    "$project_dir/m68000_scope.sv" \
    "$project_dir/scope_encoder.sv" \
    "$project_dir/m68000_harness.sv" \
    "${extra_options[@]}" "${extra_sources[@]}" "$project_dir/$main_file"
