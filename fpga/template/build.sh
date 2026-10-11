#!/usr/bin/env bash
set -eo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
export EFINITY_HOME=${EFINITY_HOME:-/home/wickerwaka/.local/efinity/2026.1}

# Re-run inside the Efinity environment: the native install on Linux, or the
# Apple Container built by tools/efinity/setup-container.sh elsewhere.
if ! command -v efx_run >/dev/null; then
    exec "$repo_root/tools/efinity/efinity-run" "$script_dir/build.sh" "$@"
fi

output_dir="$repo_root/build/fpga/template/outflow"
work_dir="$repo_root/build/fpga/template/work"

mkdir -p "$output_dir" "$work_dir"
cd "$script_dir"
# Unified flow emits this generated database beside the project. Leaving it in
# place makes a later run import the same GPIO declarations twice.
rm -f "$script_dir/template.peri.xml" \
      "$script_dir/outflow/design_issue.xml"
trap 'rm -f "$script_dir/template.peri.xml" \
             "$script_dir/outflow/design_issue.xml"' EXIT
set -u
efx_run --prj -f compile template \
    --output_dir "$output_dir" \
    --work_dir "$work_dir"

if [[ -f template.peri.xml ]]; then
    mv template.peri.xml "$output_dir/"
fi

spi_image="$output_dir/template.hex.bin"
if [[ ! -s "$spi_image" ]]; then
    echo "error: Efinity did not produce $spi_image" >&2
    exit 1
fi
if ! strings "$spi_image" | grep -qx 'Width: 4'; then
    echo "error: output is not a passive-x4 image" >&2
    exit 1
fi
sha256sum "$spi_image"
