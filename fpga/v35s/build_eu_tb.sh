#!/usr/bin/env bash
# Verilator build of the decoder/EU bench (HDL plan, C3): fpga/v35s/core/v35_decoder.sv and
# core/v35_eu.sv (with core/v35_queue.sv and core/v35_biu.sv for the joint gate) under
# fpga/v35s/v35_eu_tb.sv, driven by v35_eu_tb.cpp with the vectors of
# validation/v35s/chains/rtl_vectors.py. Binary: build/fpga/v35s/eu-tb/Vv35_eu_tb.
#
#   fpga/v35s/build_eu_tb.sh
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --eu --family F1 F2 F3 F9 F11 F12 F20
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --joint3 --family F1 F2 F3 F9 F11 F12 F20
#
# The parameter include (core/v35_chain_params.svh) is generated: python -m
# validation.v35s.chains rtlgen (the build checks it first).
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/v35s/eu-tb"
mkdir -p "$output_dir"

(cd "$repo_root" && PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen --check >/dev/null) || {
    echo "core/v35_chain_params.svh is stale: python -m validation.v35s.chains rtlgen" >&2
    exit 1
}

verilator --cc --exe --build -j 4 -Wall -Wno-DECLFILENAME -Wno-UNUSEDPARAM -Wno-UNUSEDSIGNAL \
    -DV35S_STATE_DUMP --timescale 1ns/1ps -O3 \
    --top-module v35_eu_tb --Mdir "$output_dir" \
    -I"$project_dir/core" \
    "$project_dir/core/v35_decoder.sv" "$project_dir/core/v35_eu.sv" \
    "$project_dir/core/v35_queue.sv" "$project_dir/core/v35_biu.sv" \
    "$project_dir/v35_eu_tb.sv" "$project_dir/v35_eu_tb.cpp"
