#!/usr/bin/env bash
# Verilator builds of the V35S harness.
#
#   ./build_sim.sh [direct|spi|dual] [model|stub|chain|v35]
#
# direct  the harness alone, driven over its debug bus (socket idle)
# spi     the board top through the SPI mailbox, checking the safety outputs
# dual    a second model core stands in for the socket (runner regression)
#
# model  the forked nuV30 ucore (core/v35s_model.sv)
# chain  (WP82) the chain-model core in the model lane (core/v35s_chain_model.sv, the core
#        built with V35S_CHAIN_LANE): direct only, into build/fpga/v35s/verilator-direct-chain/;
#        the ucore build and every core bench are unchanged
# v35    the V35S core v2 (docs/v35s-core-v2.md: core/v35/v35_top.sv, macro V35S_CORE_V35):
#        direct only, into build/fpga/v35s/verilator-direct-v35/
#
# The model core is the forked nuV30 ucore in core/ucore (PROVENANCE.md). Its
# microcode ROM loads from fpga/v35s/core/ucore/ relative to the working
# directory, so run the binaries from the repository root.
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$project_dir/../.." && pwd)
shared_dir="$repo_root/fpga/m68000"
ucore_dir="$project_dir/core/ucore"
variant=${1:-direct}
model=${2:-model}

top_module=v35s_harness
main_file=sim_main.cpp
extra_sources=()
extra_options=()
case "$variant" in
    direct) ;;
    spi)
        top_module=nuboard_v35s
        main_file=sim_spi_main.cpp
        extra_sources=("$project_dir/nuboard_v35s.v"
                       "$project_dir/nuboard_mailbox.v"
                       "$shared_dir/nuboard_debug_bridge.sv")
        ;;
    dual)
        top_module=v35s_dual_sim
        extra_sources=("$project_dir/v35s_dual_sim.sv")
        extra_options=(-CFLAGS -DNUBOARD_DUAL_SIM)
        model=model
        ;;
    *) echo "usage: $0 [direct|spi|dual] [model|stub|chain|v35]" >&2; exit 2 ;;
esac

core_dir="$project_dir/core"
suffix=""
if [[ "$model" == chain ]]; then
    if [[ "$variant" != direct ]]; then
        echo "the chain core is built for the direct harness only" >&2
        exit 2
    fi
    (cd "$repo_root" && PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen --check >/dev/null) || {
        echo "core/v35_chain_params.svh is stale: python -m validation.v35s.chains rtlgen" >&2
        exit 1
    }
    model_sources=("$core_dir/v35_decoder.sv" "$core_dir/v35_eu.sv" "$core_dir/v35_queue.sv"
                   "$core_dir/v35_biu.sv" "$core_dir/v35_arbiter.sv" "$core_dir/v35_refresh.sv"
                   "$core_dir/v35_chain_core.sv" "$core_dir/v35_sfr.sv"
                   "$core_dir/v35s_chain_model.sv")
    model_present=1
    suffix="-chain"
    extra_options+=(-DV35S_CHAIN_LANE -O3 -I"$core_dir")
elif [[ "$model" == v35 ]]; then
    if [[ "$variant" != direct ]]; then
        echo "the v35 core is built for the direct harness only" >&2
        exit 2
    fi
    v35_dir="$core_dir/v35"
    model_sources=("$v35_dir/v35_front_pkg.sv" "$v35_dir/v35_pkg.sv" "$v35_dir/v35_fn_pkg.sv"
                   "$v35_dir/v35_bus.sv" "$v35_dir/v35_queue.sv" "$v35_dir/v35_loader.sv"
                   "$v35_dir/v35_arbiter.sv" "$v35_dir/v35_ucode.sv" "$v35_dir/v35_ea.sv" "$v35_dir/v35_eu.sv"
                   "$v35_dir/v35_regram.sv" "$v35_dir/v35_trace.sv" "$core_dir/v35_sfr.sv"
                   "$core_dir/v35_refresh.sv" "$v35_dir/v35_top.sv")
    model_present=1
    suffix="-v35"
    extra_options+=(-DV35S_CORE_V35 -O3 -I"$core_dir" -I"$v35_dir")
elif [[ "$model" == model ]]; then
    model_sources=("$ucore_dir/v30u_ss_pkg.sv" "$ucore_dir/v30u_ucrom.sv"
                   "$ucore_dir/v30u_biu.sv" "$ucore_dir/v30u_eu.sv"
                   "$ucore_dir/v30_core.sv" "$project_dir/core/v35s_model.sv")
    model_present=1
else
    model_sources=("$project_dir/v35s_model_stub.sv")
    model_present=0
fi

# Only the bare harness takes the parameter; the other tops set it themselves.
if [[ "$variant" == direct ]]; then
    extra_options+=(-GMODEL_PRESENT=$model_present)
fi

output_dir="$repo_root/build/fpga/v35s/verilator-$variant$suffix"
# (S7b) V35_SIM_DIR: the v35 core's build elsewhere (acquire.py's V35_SIM_BINARY runs it)
if [[ "$model" == v35 && -n "${V35_SIM_DIR:-}" ]]; then output_dir=$V35_SIM_DIR; fi
mkdir -p "$output_dir"
echo "\`define V35S_MODEL_PRESENT $model_present" > "$output_dir/v35s_build.vh"

verilator --cc --exe --timing --build -j 4 -Wno-fatal -Wno-lint -Wno-style \
    --timescale 1ns/1ps \
    --top-module "$top_module" --Mdir "$output_dir" \
    -I"$output_dir" -I"$ucore_dir" \
    "${model_sources[@]}" \
    "$project_dir/v35s_lane.sv" \
    "$shared_dir/m68000_scope.sv" \
    "$shared_dir/scope_encoder.sv" \
    "$project_dir/v35s_harness.sv" \
    "${extra_options[@]}" "${extra_sources[@]}" "$project_dir/$main_file"
