#!/usr/bin/env bash
# Verilator build of the core v2's function bench (docs/v35s-core-v2.md, "Verification",
# function; stage S3): v35_fn_pkg's functions (fpga/v35s/core/v35/v35_fn_pkg.sv: the ALU, the
# shifter, the multiplier, the divider stepped, the adjusts, the conditions) under
# fpga/v35s/v35_rf_tb.sv, driven by v35_rf_tb.cpp with validation/v35s/chains/rtl_vectors.py's
# --fn vectors (V35FN-1: the --regfile vectors that are one function application, the expected
# values the functional reference's). Binary: build/fpga/v35s/fn-tb/Vv35_rf_tb (the old core's
# register-file bench, build/fpga/v35s/rf-tb, is left as it was built).
#
#   fpga/v35s/build_rf_tb.sh
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --fn --family F0 F3 F23
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/v35s/fn-tb"
mkdir -p "$output_dir"

verilator --cc --exe --build -j 4 -Wall -Wno-DECLFILENAME -Wno-UNUSEDPARAM -Wno-UNUSEDSIGNAL \
    --timescale 1ns/1ps -O3 \
    --top-module v35_rf_tb --Mdir "$output_dir" \
    -I"$project_dir/core/v35" \
    "$project_dir/core/v35/v35_fn_pkg.sv" \
    "$project_dir/v35_rf_tb.sv" "$project_dir/v35_rf_tb.cpp"
