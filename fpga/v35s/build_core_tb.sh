#!/usr/bin/env bash
# Verilator build of the chain-model core's bench (HDL plan, C4): fpga/v35s/core/v35_chain_core.sv
# (the bus unit v35_biu.sv, the queue v35_queue.sv, the decoder and the EU v35_decoder.sv and
# v35_eu.sv, the arbiter v35_arbiter.sv) under fpga/v35s/v35_core_tb.sv, driven by v35_core_tb.cpp
# with the vectors of validation/v35s/chains/rtl_vectors.py. Binary: build/fpga/v35s/core-tb/Vv35_core_tb.
#
#   fpga/v35s/build_core_tb.sh
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --core --family F4 F5 F6 F7 F10 F14 F15 F16 F19 F21 F22 F26 F29
#   the whole corpus (35 lists, 28,142 runs): --core --family F0 F0w F1 F2 ... F31 F32 F33
#
# The parameter include (core/v35_chain_params.svh) is generated: python -m
# validation.v35s.chains rtlgen (the build checks it first). LINT=1: lint the core alone (the
# synthesizable part, without the bench's state dump).
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/v35s/core-tb"
mkdir -p "$output_dir"

(cd "$repo_root" && PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen --check >/dev/null) || {
    echo "core/v35_chain_params.svh is stale: python -m validation.v35s.chains rtlgen" >&2
    exit 1
}

sources=("$project_dir/core/v35_decoder.sv" "$project_dir/core/v35_eu.sv"
         "$project_dir/core/v35_queue.sv" "$project_dir/core/v35_biu.sv"
         "$project_dir/core/v35_arbiter.sv" "$project_dir/core/v35_refresh.sv"
         "$project_dir/core/v35_chain_core.sv")

if [[ "${LINT:-0}" == 1 ]]; then
    verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDPARAM -Wno-UNUSEDSIGNAL \
        --timescale 1ns/1ps --top-module v35_chain_core -I"$project_dir/core" "${sources[@]}"
    exit 0
fi

verilator --cc --exe --build -j 4 -Wall -Wno-DECLFILENAME -Wno-UNUSEDPARAM -Wno-UNUSEDSIGNAL \
    -DV35S_STATE_DUMP --timescale 1ns/1ps -O3 \
    --top-module v35_core_tb --Mdir "$output_dir" \
    -I"$project_dir/core" \
    "${sources[@]}" "$project_dir/v35_core_tb.sv" "$project_dir/v35_core_tb.cpp"
