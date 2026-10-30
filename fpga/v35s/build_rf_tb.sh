#!/usr/bin/env bash
# Verilator build of the register file's unit bench (HDL plan, Phase D, D1 and D2): v35_eu_pkg's
# eu_decode, v35_operands, v35_execute, v35_deliver and v35_wdata (fpga/v35s/core/v35_eu.sv) under
# fpga/v35s/v35_rf_tb.sv, driven by v35_rf_tb.cpp with the vectors of
# validation/v35s/chains/rtl_vectors.py (regfile_vectors) and sst.py (--rtl). Binary:
# build/fpga/v35s/rf-tb/Vv35_rf_tb.
#
#   fpga/v35s/build_rf_tb.sh
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --regfile --family F0
#   PYTHONPATH=host/src:. python3 -m validation.v35s.chains.sst --rtl
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/v35s/rf-tb"
mkdir -p "$output_dir"

(cd "$repo_root" && PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen --check >/dev/null) || {
    echo "core/v35_chain_params.svh is stale: python -m validation.v35s.chains rtlgen" >&2
    exit 1
}

verilator --cc --exe --build -j 4 -Wall -Wno-DECLFILENAME -Wno-UNUSEDPARAM -Wno-UNUSEDSIGNAL \
    --timescale 1ns/1ps -O3 \
    --top-module v35_rf_tb --Mdir "$output_dir" \
    -I"$project_dir/core" \
    "$project_dir/core/v35_decoder.sv" "$project_dir/core/v35_eu.sv" \
    "$project_dir/v35_rf_tb.sv" "$project_dir/v35_rf_tb.cpp"
