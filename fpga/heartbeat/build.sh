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

output_dir="$repo_root/build/fpga/heartbeat/outflow"
work_dir="$repo_root/build/fpga/heartbeat/work"

mkdir -p "$output_dir" "$work_dir"
cd "$script_dir"
set -u
efx_run --prj -f compile heartbeat \
    --output_dir "$output_dir" \
    --work_dir "$work_dir"

# Efinity 2026.1 writes these two auxiliaries beside the sources even when
# output_dir is supplied.  Relocate them so generated files stay under build/.
if [[ -f heartbeat.peri.xml ]]; then
    mv heartbeat.peri.xml "$output_dir/"
fi
if [[ -f outflow/design_issue.xml ]]; then
    mv outflow/design_issue.xml "$output_dir/"
    rmdir outflow
fi

spi_image="$output_dir/heartbeat.hex.bin"
if [[ ! -s "$spi_image" ]]; then
    echo "error: Efinity did not produce the passive-SPI raw image: $spi_image" >&2
    exit 1
fi

# Fail closed if the export does not match the requested passive-x4 transport.
if ! strings "$spi_image" | grep -qx 'Width: 4'; then
    echo "error: passive-SPI image does not identify itself as Width: 4" >&2
    exit 1
fi
sha256sum "$spi_image"
