#!/usr/bin/env bash
# efx_map (synthesis only) of one V35S core v2 module, or of the whole core, as the top, for the
# Trion T120F484 (docs/v35s-core-v2.md "Verification": the per-module synthesis check).
#
#   fpga/v35s/synth/v35_map.sh MODULE [MODULE ...]
#
# MODULE: ucode eu (v35_eu with v35_ea) loader arbiter queue bus regram, or top (v35_top: every
# module, v35_sfr and v35_refresh; the slot's ports the only pins). Each module is mapped with
# its own ports as the device's pins and `SYNTHESIS` defined, into build/fpga/v35s/synth/<top>/
# (log: <top>.log there); one summary line a module (LUT4 ADD FF RAM_5K MULT, the map's
# seconds) and the map report's per-module table.
#
# Environment:
#   TAG=x        a suffix for the output directory (build/fpga/v35s/synth/<top>x/)
#   PATCH=f.py   a Python script run as `python3 f.py PROJECT_DIR` on the copied sources before
#                the map (a cut experiment: edit the copies, never the tree)
#   V35_SRC=dir  the core's sources (default fpga/v35s/core/v35 of this tree)
#
# Efinity's elaboration of a large design can take tens of GB: every run goes inside a
# memory-capped systemd scope (MemoryMax 20G, MemorySwapMax 1G); the script re-executes itself
# in one unless it already runs in one (V35_SCOPED=1).
set -eo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../.." && pwd)
export EFINITY_HOME=${EFINITY_HOME:-/home/wickerwaka/.local/efinity/2026.1}

if [[ $# -lt 1 ]]; then
    sed -n '2,22p' "$0" >&2
    exit 2
fi

if [[ -z "${V35_SCOPED:-}" ]]; then
    exec systemd-run --user --scope -p MemoryMax=20G -p MemorySwapMax=1G -q \
        env V35_SCOPED=1 ${TAG:+TAG="$TAG"} ${PATCH:+PATCH="$PATCH"} ${V35_SRC:+V35_SRC="$V35_SRC"} \
        "$script_dir/v35_map.sh" "$@"
fi
if ! command -v efx_run >/dev/null; then
    exec "$repo_root/tools/efinity/efinity-run" env V35_SCOPED=1 "$script_dir/v35_map.sh" "$@"
fi
set -u

v35=${V35_SRC:-$repo_root/fpga/v35s/core/v35}
core=$(cd "$v35/.." && pwd)
pkgs=(v35_front_pkg.sv v35_pkg.sv v35_fn_pkg.sv)
hdrs=(v35_consts.svh v35_class_tbl.svh v35_decode_tbl.svh v35_ucode_tbl.svh)

map_one() {
    local name=$1 top files
    case $name in
        ucode|v35_ucode) top=v35_ucode; files=(v35_ucode.sv) ;;
        eu|v35_eu) top=v35_eu; files=(v35_ea.sv v35_eu.sv) ;;
        loader|v35_loader) top=v35_loader; files=(v35_loader.sv) ;;
        arbiter|v35_arbiter) top=v35_arbiter; files=(v35_arbiter.sv) ;;
        queue|v35_queue) top=v35_queue; files=(v35_queue.sv) ;;
        bus|v35_bus) top=v35_bus; files=(v35_bus.sv) ;;
        regram|v35_regram) top=v35_regram; files=(v35_regram.sv) ;;
        top|v35_top) top=v35_top
            files=(v35_bus.sv v35_queue.sv v35_loader.sv v35_arbiter.sv v35_ucode.sv v35_ea.sv
                   v35_eu.sv v35_regram.sv v35_trace.sv ../v35_sfr.sv ../v35_refresh.sv
                   v35_top.sv) ;;
        *) echo "unknown module $name" >&2; return 2 ;;
    esac
    local build_dir="$repo_root/build/fpga/v35s/synth/$top${TAG:-}"
    local project_dir="$build_dir/project" output_dir="$build_dir/outflow"
    local work_dir="$build_dir/work" log="$build_dir/$top.log"
    rm -rf "$build_dir"
    mkdir -p "$project_dir" "$output_dir" "$work_dir"
    local f names=()
    for f in "${pkgs[@]}" "${files[@]}"; do
        cp "$v35/$f" "$project_dir/"
        names+=("$(basename "$f")")
    done
    for f in "${hdrs[@]}"; do cp "$v35/$f" "$project_dir/"; done
    # v35_refresh's fitted integers (the old core's generated header, until it is retired)
    if [[ $top == v35_top ]]; then cp "$core/v35_chain_params.svh" "$project_dir/"; fi
    # the ROM's banks where v35_ucode's UCODE_DIR default names them (relative to the project)
    mkdir -p "$project_dir/fpga/v35s/core/v35"
    cp "$v35"/v35_ucode_b?.hex "$project_dir/fpga/v35s/core/v35/"
    : > "$project_dir/v35s.sdc"
    if [[ -n "${PATCH:-}" ]]; then python3 "$PATCH" "$project_dir"; fi
    python3 - "$repo_root/fpga/v35s/v35s.xml" "$project_dir/v35s.xml" "$top" "${names[@]}" <<'PY'
import re, sys
source, target, top, *files = sys.argv[1:]
text = open(source).read()
text = re.sub(r'        <efx:design_file name="[^"]+" version="default" library="default" />\n',
              '', text)
entries = ''.join(f'        <efx:design_file name="{n}" version="default" library="default" />\n'
                  for n in files)
anchor = '        <efx:top_vhdl_arch name="" />\n'
assert anchor in text
text = text.replace(anchor, entries + anchor)
text = text.replace('<efx:top_module name="nuboard_v35s" />', f'<efx:top_module name="{top}" />')
text = text.replace('<efx:isf_file name="v35s.isf" />', '<efx:isf_file name="" />')
text = text.replace('    </efx:synthesis>',
    '        <efx:param name="verilog-macros" value="SYNTHESIS" value_type="e_string" />\n'
    '    </efx:synthesis>')
open(target, 'w').write(text)
PY
    local t0 rc=0
    t0=$(date +%s)
    (cd "$project_dir" && efx_run --prj -f map v35s --output_dir "$output_dir" \
        --work_dir "$work_dir") > "$log" 2>&1 || rc=$?
    local secs=$(( $(date +%s) - t0 ))
    local rpt="$output_dir/v35s.map.rpt"
    if [[ $rc != 0 || ! -s "$rpt" ]]; then
        echo "$top: map failed (rc=$rc, $secs s); see $log"
        return 1
    fi
    awk -v top="$top" -v secs="$secs" '
        /^EFX_LUT4 / { lut = $3 } /^EFX_ADD / { add = $3 } /^EFX_FF / { ff = $3 }
        /^EFX_RAM_5K / { ram = $3 } /^EFX_MULT / { mult = $3 } /^EFX_DSP48 / { mult = $3 }
        END { printf "%s: LUT4 %s ADD %s FF %s RAM_5K %s MULT %s map %s s\n", top, lut, add, ff,
                     ram == "" ? 0 : ram, mult == "" ? 0 : mult, secs }' "$rpt"
    sed -n '/Module Resource Usage Distribution Estimates (begin)/,/Module Resource Usage Distribution Estimates (end)/p' \
        "$rpt" | grep -E '^ *\+?[a-zA-Z_]+:' || true
}

status=0
for m in "$@"; do
    map_one "$m" || status=1
done
exit $status
