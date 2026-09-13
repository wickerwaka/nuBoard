#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -x "$repo_dir/bin/konnect" ]; then
    exec "$repo_dir/bin/konnect" "$@"
fi
if command -v konnect >/dev/null 2>&1; then
    exec konnect "$@"
fi
echo "Install Konnect on PATH or place its executable at $repo_dir/bin/konnect" >&2
exit 127
