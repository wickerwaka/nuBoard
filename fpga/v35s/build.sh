#!/usr/bin/env bash
# Build the V35S harness image into build/fpga/v35s/.
#
#   ./build.sh              socket lane only (model lane is an idle stub)
#   V35S_MODEL=1 ./build.sh with the v35_core model lane
#
# Shared CPU-independent modules are used in place from fpga/m68000.
set -eo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
export EFINITY_HOME=${EFINITY_HOME:-/home/wickerwaka/.local/efinity/2026.1}

# Re-run inside the Efinity environment: the native install on Linux, or the
# Apple Container built by tools/efinity/setup-container.sh elsewhere.
if ! command -v efx_run >/dev/null; then
    exec "$repo_root/tools/efinity/efinity-run" env \
        ${V35S_MODEL:+V35S_MODEL="$V35S_MODEL"} \
        "$script_dir/build.sh" "$@"
fi
set -u

model=${V35S_MODEL:-0}
build_dir="$repo_root/build/fpga/v35s"
project_dir="$build_dir/project"
output_dir="$build_dir/outflow"
work_dir="$build_dir/work"
rm -rf "$project_dir"
mkdir -p "$project_dir" "$output_dir" "$work_dir"

shared=(nuboard_debug_bridge.sv scope_encoder.sv m68000_scope.sv)
for file in "${shared[@]}"; do
    cp "$script_dir/../m68000/$file" "$project_dir/"
done
cp "$script_dir"/nuboard_v35s.v "$script_dir"/nuboard_mailbox.v \
   "$script_dir"/v35s_harness.sv "$script_dir"/v35s_lane.sv \
   "$script_dir"/v35s.isf "$script_dir"/v35s.sdc "$project_dir/"

if [[ "$model" == 1 ]]; then
    # The forked nuV30 ucore (core/ucore/PROVENANCE.md). Its microcode ROM
    # loads from rtl/ucore/ relative to the project directory under SYNTHESIS.
    ucore_dir="$script_dir/core/ucore"
    mkdir -p "$project_dir/rtl/ucore"
    cp "$ucore_dir"/*.svh "$project_dir/"
    cp "$ucore_dir"/ucrom.hex "$ucore_dir"/ucdecode.hex "$project_dir/rtl/ucore/"
    design_files="v30u_ss_pkg.sv v30u_ucrom.sv v30u_biu.sv v30u_eu.sv v30_core.sv v35s_model.sv"
    for file in v30u_ss_pkg.sv v30u_ucrom.sv v30u_biu.sv v30u_eu.sv v30_core.sv; do
        cp "$ucore_dir/$file" "$project_dir/"
    done
    cp "$script_dir/core/v35s_model.sv" "$project_dir/"
    cat "$script_dir/core/model.sdc" >> "$project_dir/v35s.sdc"
else
    cp "$script_dir/v35s_model_stub.sv" "$project_dir/"
    design_files="v35s_model_stub.sv"
fi
echo "\`define V35S_MODEL_PRESENT $model" > "$project_dir/v35s_build.vh"

# Rewrite the model entry in the project file for this configuration.
python3 - "$script_dir/v35s.xml" "$project_dir/v35s.xml" "$model" $design_files <<'PY'
import sys
source, target, model, *files = sys.argv[1:]
text = open(source).read()
stub = '        <efx:design_file name="v35s_model_stub.sv" version="default" library="default" />\n'
entries = ''.join(
    f'        <efx:design_file name="{name}" version="default" library="default" />\n'
    for name in files)
assert stub in text
text = text.replace(stub, entries)
if model == "1":
    # The ucore's sim-only checks and ROM path key off SYNTHESIS.
    anchor = '        <efx:param name="max_threads" value="-1" value_type="e_integer" />\n    </efx:synthesis>'
    assert anchor in text
    text = text.replace(anchor, anchor.replace('    </efx:synthesis>',
        '        <efx:param name="verilog-macros" value="SYNTHESIS" value_type="e_string" />\n    </efx:synthesis>'))
open(target, 'w').write(text)
PY

cd "$project_dir"
efx_run --prj -f compile v35s \
    --output_dir "$output_dir" \
    --work_dir "$work_dir"

spi_image="$output_dir/v35s.hex.bin"
if [[ ! -s "$spi_image" ]]; then
    echo "error: Efinity did not produce $spi_image" >&2
    exit 1
fi
# grep -q would exit early and fail the pipeline with SIGPIPE under pipefail.
if ! strings "$spi_image" | grep -x 'Width: 4' >/dev/null; then
    echo "error: output is not a passive-x4 image" >&2
    exit 1
fi

timing="$output_dir/v35s.timing.rpt"
summary="$build_dir/timing-summary.txt"
sed -n '/Clock Relationship Summary (begin)/,/Clock Relationship Summary (end)/p' \
    "$timing" > "$summary"
worst=$(awk '/Clock Relationship Summary \(begin\)/ { on = 1 }
             /Clock Relationship Summary \(end\)/ { on = 0 }
             on && NF >= 4 && $(NF-1) ~ /^-?[0-9.]+$/ {
                 if (min == "" || $(NF-1) + 0 < min) min = $(NF-1) + 0
             }
             END { print min }' "$timing")
echo "model=$model worst_slack_ns=$worst" >> "$summary"
if awk -v w="$worst" 'BEGIN { exit !(w < 0) }'; then
    echo "error: timing not met (worst slack $worst ns); see $summary" >&2
    exit 1
fi
sha256sum "$spi_image"
