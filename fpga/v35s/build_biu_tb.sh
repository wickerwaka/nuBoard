#!/usr/bin/env bash
# Verilator build of the bus-unit bench (HDL plan, C1): fpga/v35s/core/v35_biu.sv under
# fpga/v35s/v35_biu_tb.sv, driven by v35_biu_tb.cpp with the vectors of
# validation/v35s/chains/rtl_vectors.py. Binary: build/fpga/v35s/biu-tb/Vv35_biu_tb.
#
#   fpga/v35s/build_biu_tb.sh
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --family F0 F0w
#
# The parameter include (core/v35_chain_params.svh) is generated: python -m
# validation.v35s.chains rtlgen (the build checks it first).
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/v35s/biu-tb"
mkdir -p "$output_dir"

(cd "$repo_root" && PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen --check >/dev/null) || {
    echo "core/v35_chain_params.svh is stale: python -m validation.v35s.chains rtlgen" >&2
    exit 1
}

verilator --cc --exe --build -j 4 -Wall -Wno-DECLFILENAME -Wno-UNUSEDPARAM -Wno-UNUSEDSIGNAL \
    -DV35S_STATE_DUMP --timescale 1ns/1ps \
    --top-module v35_biu_tb --Mdir "$output_dir" \
    -I"$project_dir/core" \
    "$project_dir/core/v35_biu.sv" "$project_dir/v35_biu_tb.sv" "$project_dir/v35_biu_tb.cpp"
