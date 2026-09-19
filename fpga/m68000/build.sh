#!/usr/bin/env bash
set -eo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
efinity_home=${EFINITY_HOME:-/home/wickerwaka/.local/efinity/2026.1}
output_dir="$repo_root/build/fpga/m68000/outflow"
work_dir="$repo_root/build/fpga/m68000/work"
# Capture now uses BRAM exclusively; old PHY selections must not be ignored.
if [[ -n "${PSRAM_PHY:-}" ]]; then
    echo "PSRAM_PHY is no longer supported; capture uses BRAM" >&2
    exit 2
fi

mkdir -p "$output_dir" "$work_dir"
python3 "$repo_root/tools/check_m68000_build.py" --snapshot
cd "$script_dir"
# Upstream ROM paths are relative to the synthesis process working directory.
ln -sfn ../../build/deps/fx68k/hdl/microrom.mem microrom.mem
ln -sfn ../../build/deps/fx68k/hdl/nanorom.mem nanorom.mem
# Unified flow emits this generated database beside the project. Leaving it in
# place makes a later run import the same GPIO declarations twice.
rm -f "$script_dir/m68000.peri.xml" \
      "$script_dir/outflow/design_issue.xml"
trap 'rm -f "$script_dir/m68000.peri.xml" \
             "$script_dir/outflow/design_issue.xml"' EXIT
source "$efinity_home/bin/setup.sh"
set -u
efx_run --prj -f compile m68000 \
    --output_dir "$output_dir" \
    --work_dir "$work_dir"

if [[ -f m68000.peri.xml ]]; then
    mv m68000.peri.xml "$output_dir/"
fi

spi_image="$output_dir/m68000.hex.bin"
if [[ ! -s "$spi_image" ]]; then
    echo "error: Efinity did not produce $spi_image" >&2
    exit 1
fi
if ! strings "$spi_image" | grep -qx 'Width: 4'; then
    echo "error: output is not a passive-x4 image" >&2
    exit 1
fi
python3 "$repo_root/tools/check_m68000_build.py"
sha256sum "$spi_image"
