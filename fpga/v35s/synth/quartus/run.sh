#!/usr/bin/env bash
# Quartus build of V35S core v2 (see README.md). Usage: run.sh [map|fit|sta]   (default: all)
set -eo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../../../.." && pwd)
Q=${QUARTUS_BIN:-$HOME/intelFPGA_lite/17.1/quartus/bin}
v35=$repo/fpga/v35s/core/v35
b=${BUILD_DIR:-$repo/build/fpga/v35s/quartus}
if [[ ${1:-all} == map || ${1:-all} == all ]]; then   # restage from the sources
    rm -rf "$b"; mkdir -p "$b/stage/fpga/v35s/core/v35"
    cp "$v35"/v35_*pkg.sv "$v35"/v35_udecode_tbl.svh "$v35"/v35_l40.svh "$v35"/v35_bus.sv "$v35"/v35_queue.sv \
       "$v35"/v35_loader.sv "$v35"/v35_useq.sv "$v35"/v35_ea.sv "$v35"/v35_eu.sv \
       "$v35"/v35_regram.sv "$v35"/v35_trace.sv "$v35"/v35_top.sv \
       "$v35"/../v35_sfr.sv "$v35"/../v35_refresh.sv "$here/../v35_tw.sv" "$b/stage/"
    cp "$v35"/v35_urom_b?.hex "$v35"/v35_l40_*.hex "$b/stage/fpga/v35s/core/v35/"
    python3 "$here/../v35_tw.py" "$v35/v35_top.sv" v35_top "$b/stage/v35_tw_top.sv" >/dev/null
    # Quartus 17.1 takes one import in a module header: the wrapper's go before `module`
    python3 - "$b/stage/v35_tw_top.sv" <<'PY'
import re, sys
f = sys.argv[1]; t = open(f).read()
m = re.search(r"^module (\w+)\n((?:    import \w+::\*;\n)+)", t, re.M)
t = t[:m.start()] + re.sub(r"^    ", "", m.group(2), flags=re.M) + "module " + m.group(1) + "\n" + t[m.end():]
open(f, "w").write(t)
PY
    cp "$here/v35s.sdc" "$here/v35s.tcl" "$b/stage/"
fi
cd "$b/stage"
case ${1:-all} in
  map|all) "$Q/quartus_sh" -t v35s.tcl; "$Q/quartus_map" v35s ;;&
  fit|all) "$Q/quartus_fit" v35s ;;&
  sta|all) "$Q/quartus_sta" v35s ;;
esac
