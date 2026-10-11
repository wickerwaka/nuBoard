#!/usr/bin/env bash
# Build the Apple Container image that hosts the Efinity toolchain.
#
#   tools/efinity/setup-container.sh <efinity-linux-x64.tar.bz2> [<patch.zip>]
#
# The image is tagged nuboard-efinity:<version> and nuboard-efinity:latest.
# tools/efinity/efinity-run and the fpga/*/build.sh wrappers use :latest
# unless EFINITY_IMAGE says otherwise.
set -euo pipefail

usage() {
    echo "usage: $0 [--tag NAME] <efinity-*-linux-x64.tar.bz2> [<efinity-*-patch.zip>]" >&2
    exit 2
}

image=nuboard-efinity
while [[ $# -gt 0 ]]; do
    case $1 in
        --tag) [[ $# -ge 2 ]] || usage; image=$2; shift 2 ;;
        -h|--help) usage ;;
        -*) echo "error: unknown option $1" >&2; usage ;;
        *) break ;;
    esac
done
[[ $# -ge 1 && $# -le 2 ]] || usage

base=$1
patch=${2:-}
[[ -f "$base" ]] || { echo "error: base package not found: $base" >&2; exit 1; }
[[ -z "$patch" || -f "$patch" ]] || { echo "error: patch not found: $patch" >&2; exit 1; }

command -v container >/dev/null || {
    echo "error: Apple 'container' CLI not found; install it from" \
         "https://github.com/apple/container/releases" >&2
    exit 1
}
container system status >/dev/null 2>&1 || container system start

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)

# Version tag: the patch level when supplied, otherwise the base release.
version=$(basename "${patch:-$base}")
version=${version#efinity-}
version=${version%%-linux*}

context="$repo_root/build/efinity-container"
rm -rf "$context"
mkdir -p "$context"
# APFS clones are instant and use no extra space; fall back to a plain copy.
stage() { cp -c "$1" "$2" 2>/dev/null || cp "$1" "$2"; }
stage "$base" "$context/efinity.tar.bz2"
if [[ -n "$patch" ]]; then
    stage "$patch" "$context/patch.zip"
else
    # The Containerfile always copies patch.zip; an empty file means no patch.
    : > "$context/patch.zip"
fi
cp "$script_dir/Containerfile" "$script_dir/efinity-env" "$context/"

echo "Building $image:$version (linux/amd64) ..."
container build \
    --platform linux/amd64 \
    --memory "${EFINITY_BUILD_MEMORY:-4G}" \
    --cpus "${EFINITY_BUILD_CPUS:-4}" \
    --tag "$image:$version" \
    --tag "$image:latest" \
    --file "$context/Containerfile" \
    "$context"

rm -rf "$context"

echo "Verifying toolchain ..."
container run --rm --platform linux/amd64 "$image:$version" \
    bash -c 'command -v efx_run >/dev/null && echo "Efinity: $EFINITY_HOME" && cat "$EFINITY_HOME/scripts/sw_version.txt"'

echo "Done.  Run Efinity tools with: tools/efinity/efinity-run <command>"
