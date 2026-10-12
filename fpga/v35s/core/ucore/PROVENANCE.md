# ucore fork

These files are nuV30's ucore (`hdl/rtl/ucore/` at
`ddda5dfe792672680952e95de5625dfc372fa593`, https://github.com/wickerwaka/nuV30),
GPL-2.0 (see `LICENSE`). They were copied unmodified and are changed here only
where the V35S model needs it. Every change carries a `nuBoard:` comment.

Compare with the pinned checkout to see every change:

    python3 tools/fetch_v35s.py
    diff -r build/deps/nuV30/hdl/rtl/ucore fpga/v35s/core/ucore

Changes:

1. `v30u_eu.sv`: the reset-value block no longer assigns the next-state
   temporary `rep_chained`. Efinity rejects the second driver; the value was
   dead there.
2. `v30u_ucrom.sv`: the simulation default for `HEXDIR` is
   `fpga/v35s/core/ucore/`, because nuBoard simulations run from the
   repository root. The synthesis default `rtl/ucore/` is unchanged and
   `fpga/v35s/build.sh` places the tables there.
