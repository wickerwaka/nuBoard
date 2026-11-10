#!/usr/bin/env bash
# The whole harness image with the V35S core v2 as its model lane (V35S_CORE=v35
# fpga/v35s/build.sh: map, place, route, bitstream into build/fpga/v35s/), in a memory-capped
# systemd scope (MemoryMax 20G, MemorySwapMax 1G), then a summary from the reports:
#
#   fpga/v35s/synth/v35_harness.sh
#
# Prints the wall time and each stage's time (the map, place and route reports' elapsed
# times), the map's resource summary and the per-module table of the core (harness/model),
# the placer's resource summary, the Clock Relationship Summary and the three worst setup
# paths (begin, end, slack, logic levels). The log is build/fpga/v35s/v35-harness.log; the
# summary is also written to build/fpga/v35s/v35-harness-summary.txt. Exit status: build.sh's
# (1 when timing is not met).
set -o pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../.." && pwd)
build_dir="$repo_root/build/fpga/v35s"
out="$build_dir/outflow"
log="$build_dir/v35-harness.log"
summary="$build_dir/v35-harness-summary.txt"
mkdir -p "$build_dir"

t0=$(date +%s)
rc=0
systemd-run --user --scope -p MemoryMax=20G -p MemorySwapMax=1G -q \
    env V35S_CORE=v35 ${V35S_PNR_EFFORT:+V35S_PNR_EFFORT="$V35S_PNR_EFFORT"} \
    "$repo_root/fpga/v35s/build.sh" > "$log" 2>&1 || rc=$?
wall=$(( $(date +%s) - t0 ))

{
    echo "V35S_CORE=v35 build.sh: exit $rc, wall ${wall} s (log $log)"
    if [[ -s "$out/v35s.map.rpt" ]]; then
        echo "map:   $(grep -m1 'Elapsed synthesis time' "$out/v35s.map.rpt" | sed 's/.*: *//')"
    else
        echo "map:   no report"
    fi
    if [[ -s "$out/v35s.place.rpt" ]]; then
        grep -E 'Elapsed time for (packing|placement)' "$out/v35s.place.rpt" | sed 's/^/place: /'
    fi
    if [[ -s "$out/v35s.route.rpt" ]]; then
        grep -E 'Elapsed time for (routing|Latest PnR Run)' "$out/v35s.route.rpt" \
            | sed 's/^/route: /'
    fi
    if [[ -s "$out/v35s.map.rpt" ]]; then
        echo
        echo "map resources:"
        sed -n '/Resource Summary (begin)/,/Resource Summary (end)/p' "$out/v35s.map.rpt" \
            | grep -E '^EFX_(LUT4|ADD|FF|RAM_5K|MULT|DSP)' | sed 's/^/  /'
        echo "the core (map's per-module estimate, harness/model and below):"
        sed -n '/Module Resource Usage Distribution Estimates (begin)/,/Module Resource Usage Distribution Estimates (end)/p' \
            "$out/v35s.map.rpt" | grep -E '^ *\+(model|bus|queue|loader|useq|eu|ea|regram|arbiter|refresh|sfr|trace):' \
            | sed 's/^/  /'
    fi
    if [[ -s "$out/v35s.place.rpt" ]]; then
        echo
        echo "placed:"
        sed -n '/Resource Summary (begin)/,/Resource Summary (end)/p' "$out/v35s.place.rpt" \
            | grep -v 'Resource Summary' | sed 's/^/  /'
    fi
    if [[ -s "$out/v35s.timing.rpt" ]]; then
        echo
        sed -n '/Clock Relationship Summary (begin)/,/Clock Relationship Summary (end)/p' \
            "$out/v35s.timing.rpt"
        echo
        echo "worst setup paths (clk_sys):"
        awk '/Path Detail Report \(clk_sys vs clk_sys\)/ { on = 1 }
             /Path Detail Report \(spi_sck/ { on = 0 }
             on && /^Path Begin/ { b = $0 } on && /^Path End/ { e = $0 }
             on && /^Slack/ { s = $0 } on && /^Logic Level/ {
                 n++; if (n <= 3) { print "  " n ": " b; print "     " e; print "     " s;
                                    print "     " $0 } }' "$out/v35s.timing.rpt"
    fi
} | tee "$summary"
exit $rc
