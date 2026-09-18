#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
output_dir="$repo_root/build/fpga/led_test/verilator"

mkdir -p "$output_dir"

verilator --binary --timing -j 0 \
    -Wno-PINMISSING \
    --top-module led_test_tb \
    --Mdir "$output_dir" \
    "$repo_root/fpga/template/aps1604m_psram.v" \
    "$repo_root/fpga/template/nuboard_template.v" \
    "$script_dir/nuboard_led_test.v" \
    "$script_dir/led_test_tb.v"

"$output_dir/Vled_test_tb"
