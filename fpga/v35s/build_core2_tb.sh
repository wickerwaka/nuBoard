#!/usr/bin/env bash
# Verilator build of the core v2's whole-core function bench (docs/v35s-core-v2.md,
# "Verification", function; stage S6): v35_top (fpga/v35s/core/v35/) under
# fpga/v35s/v35_core2_tb.sv, the preload hooks in v35_core2_tb.vlt, driven by
# v35_core2_tb.cpp with validation/v35s/chains/sst.py --rtl's tests (SingleStepTests V20, one
# instruction from a preloaded state) and rtl_vectors.py --regfile's vectors (format
# V35SST-1). Binary: build/fpga/v35s/core2-tb/Vv35_core2_tb. Run from the repository root (the
# microcode ROM's banks load from fpga/v35s/core/v35/).
#
#   fpga/v35s/build_core2_tb.sh
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.sst --rtl
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --regfile --family F0 F23
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
core_dir="$project_dir/core"
v35_dir="$core_dir/v35"
output_dir="${V35_CORE2_TB_DIR:-$repo_root/build/fpga/v35s/core2-tb}"
mkdir -p "$output_dir"

verilator --cc --exe --build -j 4 -Wno-fatal -Wno-lint -Wno-style --savable \
    --timescale 1ns/1ps -O3 \
    --top-module v35_core2_tb --Mdir "$output_dir" \
    -I"$core_dir" -I"$v35_dir" \
    "$project_dir/v35_core2_tb.vlt" \
    "$v35_dir/v35_front_pkg.sv" "$v35_dir/v35_pkg.sv" "$v35_dir/v35_fn_pkg.sv" \
    "$v35_dir/v35_bus.sv" "$v35_dir/v35_queue.sv" "$v35_dir/v35_loader.sv" \
    "$v35_dir/v35_useq.sv" "$v35_dir/v35_ea.sv" "$v35_dir/v35_eu.sv" \
    "$v35_dir/v35_regram.sv" "$v35_dir/v35_trace.sv" "$core_dir/v35_sfr.sv" \
    "$core_dir/v35_refresh.sv" "$v35_dir/v35_top.sv" \
    "$project_dir/v35_core2_tb.sv" "$project_dir/v35_core2_tb.cpp"
