#!/usr/bin/env bash
# Build the V35S harness image into build/fpga/v35s/.
#
#   ./build.sh                  socket lane only (model lane is an idle stub)
#   V35S_MODEL=1 ./build.sh     with the forked nuV30 ucore model lane
#   V35S_CORE=v35 ./build.sh    with the V35S core v2 (core/v35/, docs/v35s-core-v2.md) as
#                               the model lane (the harness's V35S_CORE_V35 branch)
#   V35S_PNR_EFFORT=n           the placer's effort level (default the project's 5)
#
# fpga/v35s/synth/v35_harness.sh runs the V35S_CORE=v35 build in a memory-capped scope and
# reports each stage's time and the resource and timing summaries.
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
        ${V35S_MODEL:+V35S_MODEL="$V35S_MODEL"} ${V35S_CORE:+V35S_CORE="$V35S_CORE"} \
        ${V35S_PNR_EFFORT:+V35S_PNR_EFFORT="$V35S_PNR_EFFORT"} \
        "$script_dir/build.sh" "$@"
fi
set -u

model=${V35S_MODEL:-0}
core=${V35S_CORE:-}
if [[ -n "$core" && "$core" != v35 ]]; then
    echo "error: V35S_CORE=$core (only v35 is known)" >&2
    exit 2
fi
if [[ "$core" == v35 && "$model" == 1 ]]; then
    echo "error: V35S_CORE=v35 and V35S_MODEL=1 are two model lanes; pick one" >&2
    exit 2
fi
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

macros=""
if [[ "$core" == v35 ]]; then
    # The V35S core v2 (core/v35/README.md). Its microcode ROM banks load from
    # fpga/v35s/core/v35/ relative to the project directory (v35_ucode's UCODE_DIR); the
    # harness picks the core with V35S_CORE_V35, the sim-only trace and checks drop out
    # under SYNTHESIS. core/model_v35.sdc holds no timing exceptions (the clocking directive).
    model=1
    v35_dir="$script_dir/core/v35"
    v35_files=(v35_front_pkg.sv v35_pkg.sv v35_fn_pkg.sv v35_bus.sv v35_queue.sv
               v35_loader.sv v35_arbiter.sv v35_ucode.sv v35_ea.sv v35_eu.sv v35_regram.sv
               v35_trace.sv v35_top.sv)
    for file in "${v35_files[@]}" v35_consts.svh v35_class_tbl.svh v35_decode_tbl.svh \
                v35_ucode_tbl.svh; do
        cp "$v35_dir/$file" "$project_dir/"
    done
    cp "$script_dir/core/v35_sfr.sv" "$script_dir/core/v35_refresh.sv" \
       "$script_dir/core/v35_chain_params.svh" "$project_dir/"
    mkdir -p "$project_dir/fpga/v35s/core/v35"
    cp "$v35_dir"/v35_ucode_b?.hex "$project_dir/fpga/v35s/core/v35/"
    design_files="v35_front_pkg.sv v35_pkg.sv v35_fn_pkg.sv v35_sfr.sv v35_refresh.sv"
    for file in "${v35_files[@]:3}"; do
        design_files="$design_files $file"
    done
    cat "$script_dir/core/model_v35.sdc" >> "$project_dir/v35s.sdc"
    macros="SYNTHESIS V35S_CORE_V35"
elif [[ "$model" == 1 ]]; then
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
python3 - "$script_dir/v35s.xml" "$project_dir/v35s.xml" "$model" "$macros" "${V35S_PNR_EFFORT:-}" $design_files <<'PY'
import sys
source, target, model, macros, effort, *files = sys.argv[1:]
text = open(source).read()
stub = '        <efx:design_file name="v35s_model_stub.sv" version="default" library="default" />\n'
entries = ''.join(
    f'        <efx:design_file name="{name}" version="default" library="default" />\n'
    for name in files)
assert stub in text
text = text.replace(stub, entries)
if macros:
    # (V35S_CORE=v35) one efx:defmacro per macro: efx_map takes a single name from the
    # verilog-macros param, every defmacro element as its own definition
    anchor = '        <efx:param name="max_threads" value="-1" value_type="e_integer" />\n    </efx:synthesis>'
    assert anchor in text
    defs = ''.join(f'        <efx:defmacro name="{m}" value="1" />\n' for m in macros.split())
    text = text.replace(anchor, anchor.replace('    </efx:synthesis>', defs + '    </efx:synthesis>'))
elif model == "1":
    # The ucore's sim-only checks and ROM path key off SYNTHESIS.
    anchor = '        <efx:param name="max_threads" value="-1" value_type="e_integer" />\n    </efx:synthesis>'
    assert anchor in text
    text = text.replace(anchor, anchor.replace('    </efx:synthesis>',
        '        <efx:param name="verilog-macros" value="SYNTHESIS" value_type="e_string" />\n    </efx:synthesis>'))
if effort:
    # (V35S_PNR_EFFORT=n) a quicker placement for a timing reading
    anchor = '<efx:param name="placer_effort_level" value="5" value_type="e_option" />'
    assert anchor in text
    text = text.replace(anchor, anchor.replace('"5"', f'"{effort}"'))
open(target, 'w').write(text)
PY

cd "$project_dir"
efx_run --prj -f compile v35s \
    --output_dir "$output_dir" \
    --work_dir "$work_dir"

# every SDC line must apply (a rejected cell pattern silently drops a multicycle)
if grep -E "WARNING *: (\[SDC .*(Unable to run|not a valid|no vaild|no valid)|No cells matched)" "$output_dir/v35s.log" \
        > "$build_dir/sdc-rejected.txt"; then
    echo "error: SDC constraints were not applied (see $build_dir/sdc-rejected.txt)" >&2
    exit 1
fi

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
echo "model=$model${core:+ core=$core} worst_slack_ns=$worst" >> "$summary"
if awk -v w="$worst" 'BEGIN { exit !(w < 0) }'; then
    echo "error: timing not met (worst slack $worst ns); see $summary" >&2
    exit 1
fi
sha256sum "$spi_image"
