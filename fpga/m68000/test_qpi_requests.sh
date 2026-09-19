#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/m68000/qpi-request-ddr100"
mkdir -p "$output_dir"
verilator --binary --timing --build -j 4 -Wno-fatal \
    --top-module qpi_request_tb --Mdir "$output_dir" \
    "$project_dir/aps1604m_qpi.sv" "$project_dir/psram_model.sv" \
    "$project_dir/qpi_request_tb.sv"
"$output_dir/Vqpi_request_tb"
