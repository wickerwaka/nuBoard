# V35S core v2 model lane (V35S_CORE=v35 build.sh; appended to v35s.sdc).
#
# No multicycle or other timing exceptions: the core is to close timing on the plain clock
# period (target 2026-11-03: a 64 MHz fabric clock, 15.6 ns, with the CPU clock at 32 MHz, two
# fabric ticks a CPU clock; the long chains split across the ticks in the RTL, not relaxed by
# constraints). The clock itself is v35s.sdc's (clk_sys, 30 ns today).
#
# (S7a) Today's core is one feed-forward CPU clock (stages S1..S6 in one `ce` step); its whole
# chain is about 200 ns placed, so this build does not meet the plain 30 ns period: build.sh
# reports the negative slack and fails, as for the other lanes. The timing reading and the
# proposed two-tick structure are in the S7a hand-back (s7-timing-reading.md).
#
# If exceptions are ever added here: build.sh fails the build when the place-and-route log
# reports an SDC line it could not apply (a rejected cell pattern drops the constraint
# silently otherwise). Efinity's get_cells patterns split on spaces (use \S, not [^ ]) and
# have no lookahead; a module's output register takes its parent net's name when the design
# flattens (harness/model/<net>~FF).
