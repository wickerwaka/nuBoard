#!/usr/bin/env bash
# Build the template image.
#
#   ./build.sh                               100 MHz HyperRAM, 90 degree capture
#   HR_MHZ=125 HR_CAL_PHASE=135 ./build.sh   one HyperRAM sweep configuration
#
# The default build goes to build/fpga/template/. A build with HR_MHZ or
# HR_CAL_PHASE set goes to build/fpga/template-hr<MHz>-p<phase>/. Each build
# compiles a private copy of the project, so the sources stay untouched and
# several configurations can build at once.
set -eo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
export EFINITY_HOME=${EFINITY_HOME:-/home/wickerwaka/.local/efinity/2026.1}

# Re-run inside the Efinity environment: the native install on Linux, or the
# Apple Container built by tools/efinity/setup-container.sh elsewhere.
if ! command -v efx_run >/dev/null; then
    exec "$repo_root/tools/efinity/efinity-run" env \
        ${HR_MHZ:+HR_MHZ="$HR_MHZ"} \
        ${HR_CAL_PHASE:+HR_CAL_PHASE="$HR_CAL_PHASE"} \
        "$script_dir/build.sh" "$@"
fi

if [[ -n "${HR_MHZ:-}" || -n "${HR_CAL_PHASE:-}" ]]; then
    hr_mhz=${HR_MHZ:-100}
    hr_phase=${HR_CAL_PHASE:-90}
    build_dir="$repo_root/build/fpga/template-hr${hr_mhz}-p${hr_phase}"
else
    hr_mhz=100
    hr_phase=90
    build_dir="$repo_root/build/fpga/template"
fi
case "$hr_phase" in
    0|45|90|135|180|270) ;;
    *) echo "error: HR_CAL_PHASE must be 0, 45, 90, 135, 180 or 270" >&2
       exit 2 ;;
esac
if ! [[ "$hr_mhz" =~ ^[0-9]+$ ]]; then
    echo "error: HR_MHZ must be a whole number of MHz" >&2
    exit 2
fi
set -u

project_dir="$build_dir/project"
output_dir="$build_dir/outflow"
work_dir="$build_dir/work"
rm -rf "$project_dir"
mkdir -p "$project_dir" "$output_dir" "$work_dir"

cp "$script_dir"/*.v "$script_dir/template.xml" "$project_dir/"
sed -e "s/@HR_MHZ@/$hr_mhz/g" -e "s/@HR_CAL_PHASE@/$hr_phase/g" \
    "$script_dir/template.isf" > "$project_dir/template.isf"
# Burst length: the largest power of two, up to one 512-word row, that keeps
# CS# low for under tCSM = 4 us including about 20 clocks of command,
# latency and read over-run.
hr_burst=512
while (( (hr_burst + 20) > 4 * hr_mhz && hr_burst > 16 )); do
    hr_burst=$((hr_burst / 2))
done
cat > "$project_dir/hyperram_build.vh" <<EOF
\`define HR_MHZ $hr_mhz
\`define HR_CAL_PHASE $hr_phase
\`define HR_BURST_WORDS $hr_burst
EOF

# PLL output clocks, written the way Interface Designer reports them in
# outflow/template.pt.sdc. The three are related; the read capture FIFO
# makes clk_hr_cal to clk_hr transfers safe at any phase.
{
    cat "$script_dir/template.sdc"
    awk -v mhz="$hr_mhz" -v phase="$hr_phase" 'BEGIN {
        t = 1000.0 / mhz
        c = t * phase / 360.0
        printf "create_clock -period %.3f -name clk_hr [get_ports {clk_hr}]\n", t
        printf "create_clock -waveform {%.3f %.3f} -period %.3f -name clk_hr90 [get_ports {clk_hr90}]\n", t / 4, t * 3 / 4, t
        printf "create_clock -waveform {%.3f %.3f} -period %.3f -name clk_hr_cal [get_ports {clk_hr_cal}]\n", c, c + t / 2, t
        print "set_clock_groups -asynchronous -group [get_clocks {clk_hr clk_hr90 clk_hr_cal}] -group [get_clocks clk_50mhz] -group [get_clocks spi_sck]"
        print "set_false_path -from [get_clocks clk_hr_cal] -to [get_clocks clk_hr]"
        print "set_false_path -from [get_clocks clk_hr] -to [get_clocks clk_hr_cal]"
    }'
} > "$project_dir/template.sdc"

cd "$project_dir"
efx_run --prj -f compile template \
    --output_dir "$output_dir" \
    --work_dir "$work_dir"

spi_image="$output_dir/template.hex.bin"
if [[ ! -s "$spi_image" ]]; then
    echo "error: Efinity did not produce $spi_image" >&2
    exit 1
fi
if ! strings "$spi_image" | grep -qx 'Width: 4'; then
    echo "error: output is not a passive-x4 image" >&2
    exit 1
fi

# Summarise timing. Negative slack is reported rather than fatal so that a
# sweep still produces every image; tools/hyperram-sweep.py shows the flag.
timing="$output_dir/template.timing.rpt"
summary="$build_dir/timing-summary.txt"
{
    echo "hr_mhz=$hr_mhz hr_cal_phase=$hr_phase hr_burst_words=$hr_burst"
    grep -m1 '^HR_PLL' "$output_dir/template.log" || true
    sed -n '/Clock Relationship Summary (begin)/,/Clock Relationship Summary (end)/p' "$timing"
} > "$summary"
worst=$(awk '/Clock Relationship Summary \(begin\)/ { on = 1 }
             /Clock Relationship Summary \(end\)/ { on = 0 }
             on && NF >= 4 && $(NF-1) ~ /^-?[0-9.]+$/ {
                 if (min == "" || $(NF-1) + 0 < min) min = $(NF-1) + 0
             }
             END { print min }' "$timing")
echo "worst_slack_ns=$worst" >> "$summary"
if awk -v w="$worst" 'BEGIN { exit !(w < 0) }'; then
    echo "WARNING: timing not met (worst slack $worst ns); see $summary" >&2
fi
sha256sum "$spi_image"
