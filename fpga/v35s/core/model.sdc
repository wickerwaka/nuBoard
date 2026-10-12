# Model builds only (appended by build.sh). The ucore advances only on CE and
# CE_HALF, which v35s_model.sv derives from X1: a CPU state is at least two X1
# periods and an X1 period is at least four 30 ns ticks, so CE and CE_HALF
# are always at least two fabric clocks apart. Paths that start and end inside
# the core, and core outputs that v35s_model.sv samples only on those same
# enables, therefore have two clocks (60 ns), conservatively. Paths INTO the core from the
# wrapper (the CE logic itself) stay single-cycle.
set_multicycle_path -setup 2 -from [get_cells {harness/model/core/*}] -to [get_cells {harness/model/core/*}]
set_multicycle_path -hold 1 -from [get_cells {harness/model/core/*}] -to [get_cells {harness/model/core/*}]
set_multicycle_path -setup 2 -from [get_cells {harness/model/core/*}] -to [get_cells {harness/model/*}]
set_multicycle_path -hold 1 -from [get_cells {harness/model/core/*}] -to [get_cells {harness/model/*}]
# Core output registers take the wrapper's net name after flattening
# (harness/model/core_status[3]~FF and so on); they launch on the same enables.
# core_read_data also matches; it changes on a CPU-state enable and the core
# reads it only on CE.
set_multicycle_path -setup 2 -from [get_cells {harness/model/core_*}] -to [get_cells {harness/model/*}]
set_multicycle_path -hold 1 -from [get_cells {harness/model/core_*}] -to [get_cells {harness/model/*}]
