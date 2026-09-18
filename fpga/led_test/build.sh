#!/usr/bin/env bash
set -eo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
efinity_home=${EFINITY_HOME:-/home/wickerwaka/.local/efinity/2026.1}
output_dir="$repo_root/build/fpga/led_test/outflow"
work_dir="$repo_root/build/fpga/led_test/work"

mkdir -p "$output_dir" "$work_dir"
cd "$script_dir"

rm -f "$script_dir/led_test.peri.xml" \
      "$script_dir/outflow/design_issue.xml"
trap 'rm -f "$script_dir/led_test.peri.xml" \
             "$script_dir/outflow/design_issue.xml"' EXIT

source "$efinity_home/bin/setup.sh"
set -u

efx_run --prj -f compile led_test \
    --output_dir "$output_dir" \
    --work_dir "$work_dir"

if [[ -f led_test.peri.xml ]]; then
    mv led_test.peri.xml "$output_dir/"
fi

spi_image="$output_dir/led_test.hex.bin"
if [[ ! -s "$spi_image" ]]; then
    echo "error: Efinity did not produce $spi_image" >&2
    exit 1
fi

if ! strings "$spi_image" | grep -qx 'Width: 4'; then
    echo "error: output is not a passive-x4 image" >&2
    exit 1
fi

sha256sum "$spi_image"
