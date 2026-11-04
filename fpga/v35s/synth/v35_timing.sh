#!/usr/bin/env bash
# (S7b) Static timing of one V35S core v2 module, or of the whole core, at the target fabric
# clock: efx_run compile (map, place, route, timing) of the module inside the timing wrapper
# (v35_tw.sv: its inputs from a register chain, its outputs into registers folded onto eight
# pins) on the T120F484 with `create_clock -period 15.625` (64 MHz) and no other constraint.
#
#   fpga/v35s/synth/v35_timing.sh MODULE [MODULE ...]
#
# MODULE: ucode loader arbiter queue bus eu (v35_eu with v35_ea) regram, or top (v35_top: every
# module, v35_sfr and v35_refresh). Output in build/fpga/v35s/timing/<top>${TAG}/; prints the
# Clock Relationship Summary, the worst slack, the five worst setup paths (begin, end, slack,
# logic levels) and the map's resources. Every run is inside a memory-capped systemd scope
# (MemoryMax 20G, MemorySwapMax 1G); run one at a time.
#
# Environment:
#   TAG=x          a suffix for the output directory
#   PERIOD=ns      the clock period (default 15.625)
#   V35_SRC=dir    the core's sources (default fpga/v35s/core/v35 of this tree)
#   EFFORT=n       the placer's effort level (default the project's 5)
set -eo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../.." && pwd)
export EFINITY_HOME=${EFINITY_HOME:-/home/wickerwaka/.local/efinity/2026.1}

if [[ $# -lt 1 ]]; then
    sed -n '2,20p' "$0" >&2
    exit 2
fi
if [[ -z "${V35_SCOPED:-}" ]]; then
    exec systemd-run --user --scope -p MemoryMax=20G -p MemorySwapMax=1G -q \
        env V35_SCOPED=1 ${TAG:+TAG="$TAG"} ${PERIOD:+PERIOD="$PERIOD"} \
        ${V35_SRC:+V35_SRC="$V35_SRC"} ${EFFORT:+EFFORT="$EFFORT"} \
        "$script_dir/v35_timing.sh" "$@"
fi
if ! command -v efx_run >/dev/null; then
    exec "$repo_root/tools/efinity/efinity-run" env V35_SCOPED=1 "$script_dir/v35_timing.sh" "$@"
fi
set -u

v35=${V35_SRC:-$repo_root/fpga/v35s/core/v35}
period=${PERIOD:-15.625}
pkgs=(v35_front_pkg.sv v35_pkg.sv v35_fn_pkg.sv)
hdrs=(v35_consts.svh v35_class_tbl.svh v35_decode_tbl.svh v35_ucode_tbl.svh)

time_one() {
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
    local build_dir="$repo_root/build/fpga/v35s/timing/$top${TAG:-}"
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
    mkdir -p "$project_dir/fpga/v35s/core/v35"
    cp "$v35"/v35_ucode_b?.hex "$project_dir/fpga/v35s/core/v35/"
    cp "$script_dir/v35_tw.sv" "$project_dir/"
    local mfile=${files[-1]}
    python3 "$script_dir/v35_tw.py" "$v35/$mfile" "$top" "$project_dir/v35_tw_top.sv" > /dev/null
    names+=(v35_tw.sv v35_tw_top.sv)
    # the clock alone: no exception of any kind
    printf 'create_clock -period %s -name clk_sys [get_ports {clk_sys}]\n' "$period" \
        > "$project_dir/v35s.sdc"
    # the interface: the board's I/O bank voltages and its system PLL (CLKOUT0 = clk_sys), the
    # chain's input on spi_mosi's pin and the fold's eight outputs on output pins of the board
    {
        grep '^design.set_device_property' "$repo_root/fpga/v35s/v35s.isf"
        echo 'design.create_pll_input_clock_gpio("sys_pll_refclk")'
        echo 'design.assign_pkg_pin("sys_pll_refclk", "A18")'
        echo 'design.create_block("sys_pll", "PLL")'
        echo 'design.assign_resource("sys_pll", "PLL_TR1", "PLL")'
        echo 'design.set_property("sys_pll", {"REFCLK_SOURCE": "EXTERNAL", "EXT_CLK": "EXT_CLK0", "REFCLK_FREQ": "50.0", "FEEDBACK_MODE": "LOCAL", "FEEDBACK_CLK": "CLK0"}, None, "PLL")'
        echo 'design.set_property("sys_pll", {"CLKOUT0_EN": "1", "CLKOUT0_PIN": "clk_sys", "CLKOUT0_CONN_TYPE": "gclk"}, None, "PLL")'
        echo 'design.set_property("sys_pll", {"M": "2", "N": "3", "O": "2", "CLKOUT0_DIV": "52", "CLKOUT0_PHASE": "0"}, None, "PLL")'
        echo 'design.assign_pkg_pin("si", "R8")'
        local pins=(A12 A8 A4 C12 C7 C3 U5 V2) k
        for k in 0 1 2 3 4 5 6 7; do
            echo "design.assign_pkg_pin(\"xo[$k]\", \"${pins[$k]}\")"
        done
    } > "$project_dir/v35s.isf"
    python3 - "$repo_root/fpga/v35s/v35s.xml" "$project_dir/v35s.xml" "${EFFORT:-}" \
        "${names[@]}" <<'PY'
import re, sys
source, target, effort, *files = sys.argv[1:]
text = open(source).read()
text = re.sub(r'        <efx:design_file name="[^"]+" version="default" library="default" />\n',
              '', text)
entries = ''.join(f'        <efx:design_file name="{n}" version="default" library="default" />\n'
                  for n in files)
anchor = '        <efx:top_vhdl_arch name="" />\n'
assert anchor in text
text = text.replace(anchor, entries + anchor)
text = text.replace('<efx:top_module name="nuboard_v35s" />', '<efx:top_module name="v35_tw_top" />')
anchor = '        <efx:param name="max_threads" value="-1" value_type="e_integer" />\n    </efx:synthesis>'
assert anchor in text
text = text.replace(anchor, anchor.replace('    </efx:synthesis>',
    '        <efx:defmacro name="SYNTHESIS" value="1" />\n    </efx:synthesis>'))
if effort:
    a = '<efx:param name="placer_effort_level" value="5" value_type="e_option" />'
    assert a in text
    text = text.replace(a, a.replace('"5"', f'"{effort}"'))
open(target, 'w').write(text)
PY
    local t0 rc=0
    t0=$(date +%s)
    (cd "$project_dir" && efx_run --prj -f compile v35s --output_dir "$output_dir" \
        --work_dir "$work_dir") > "$log" 2>&1 || rc=$?
    local secs=$(( $(date +%s) - t0 ))
    local rpt="$output_dir/v35s.timing.rpt"
    echo "== $top (period $period ns, $secs s, efx_run exit $rc; log $log)"
    if grep -E "WARNING *: (\[SDC .*(Unable to run|not a valid|no vaild|no valid)|No cells matched)" \
            "$output_dir/v35s.log" 2>/dev/null; then
        echo "   SDC lines rejected (above)"
    else
        echo "   SDC: every line applied (one create_clock, no exceptions)"
    fi
    if [[ -s "$output_dir/v35s.map.rpt" ]]; then
        sed -n '/Resource Summary (begin)/,/Resource Summary (end)/p' "$output_dir/v35s.map.rpt" \
            | grep -E '^EFX_(LUT4|ADD|FF|RAM_5K|MULT|DSP)' | tr -s ' ' | sed 's/^/   map: /'
    fi
    if [[ ! -s "$rpt" ]]; then
        echo "   no timing report"
        return 1
    fi
    sed -n '/Clock Relationship Summary (begin)/,/Clock Relationship Summary (end)/p' "$rpt" \
        | sed 's/^/   /'
    echo "   worst setup paths:"
    awk '/Path Detail Report \(clk_sys vs clk_sys\)/ { on = 1 }
         on && /^Path Begin/ { b = $0 } on && /^Path End/ { e = $0 }
         on && /^Slack/ { s = $0 } on && /^Logic Level/ {
             n++; if (n <= 5) { print "   " n ": " b; print "      " e; print "      " s;
                                print "      " $0 } }' "$rpt"
}

status=0
for m in "$@"; do
    time_one "$m" || status=1
done
exit $status
