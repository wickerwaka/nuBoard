#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
output_dir="$repo_root/build/fpga/template/verilator"
mkdir -p "$output_dir"

verilator --binary --timing -j 0 --top-module template_tb \
    --Mdir "$output_dir" \
    "$repo_root/fpga/template/aps1604m_psram.v" \
    "$repo_root/fpga/template/nuboard_template.v" \
    "$repo_root/fpga/template/template_tb.sv"
"$output_dir/Vtemplate_tb"
