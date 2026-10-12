#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source_dir="$repo_root/fpga/template"
output_dir="$repo_root/build/fpga/template/verilator"
mkdir -p "$output_dir"

hyperram_sources=(
    "$source_dir/sim/EFX_GPIO_V2.v"
    "$source_dir/hyperram_phy.v"
    "$source_dir/hyperram_fifo.v"
    "$source_dir/hyperram_ctrl.v"
    "$source_dir/hyperram_buffers.v"
    "$source_dir/hyperram_trace_core.v"
    "$source_dir/hyperram_tester.v"
    "$source_dir/sim/hyperram_model.sv"
)

# Two producer widths. The burst is shortened to keep simulation fast; the
# controller's burst logic does not depend on the length.
for variant in 64:64 16:32; do
    width=${variant%%:*}
    burst=${variant##*:}
    model_dir="$output_dir/hyperram-w$width"
    verilator --binary --timing -j 0 --top-module hyperram_tb \
        -GUSER_WIDTH="$width" -GBURST_WORDS="$burst" --Mdir "$model_dir" \
        "${hyperram_sources[@]}" "$source_dir/sim/hyperram_tb.sv"

    # Capture phases at every PLL setting, across the device's CK-to-data
    # delay range. Delays that put data edges exactly on a sample point (for
    # example 3.33 ns at 150 MHz) are real failing phases and are left out.
    for config in 100:1.0 100:3.0 100:5.5 50:5.5 150:1.0 150:5.5; do
        mhz=${config%%:*}
        tckd=${config##*:}
        for phase in 0 45 90 135 180 270; do
            "$model_dir/Vhyperram_tb" +mhz="$mhz" +phase="$phase" \
                +tckd="$tckd" | grep -E '^(PASS|FAIL)' | tee "$output_dir/hr.log"
            grep -q '^PASS' "$output_dir/hr.log"
        done
    done
done

verilator --binary --timing -j 0 --top-module template_tb \
    --Mdir "$output_dir/template" \
    -I"$source_dir" \
    "${hyperram_sources[@]}" \
    "$source_dir/nuboard_app.v" \
    "$source_dir/nuboard_template.v" \
    "$source_dir/template_tb.sv"
"$output_dir/template/Vtemplate_tb"
