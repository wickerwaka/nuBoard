# Generates the project v35s in the staging directory (run.sh).
load_package project
project_new v35s -overwrite
set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEBA6U23I7
set_global_assignment -name TOP_LEVEL_ENTITY v35_tw_top
set_global_assignment -name VERILOG_INPUT_VERSION SYSTEMVERILOG_2005
set_global_assignment -name VERILOG_SHOW_LMF_MAPPING_MESSAGES OFF
set_global_assignment -name VERILOG_MACRO "SYNTHESIS=1"
set_global_assignment -name NUM_PARALLEL_PROCESSORS 4
# Auto ROM recognition crashes Quartus 17.1 (Verific "Can't extract a ROM based on this value")
# in the loader's decode-table functions; set ROMOFF=1 to switch it off for the whole design
if {[info exists ::env(ROMOFF)] && $::env(ROMOFF)} {
    set_global_assignment -name AUTO_ROM_RECOGNITION OFF
}
set_instance_assignment -name AUTO_ROM_RECOGNITION OFF -to "v35_top:dut|v35_loader:loader"
set_global_assignment -name SDC_FILE v35s.sdc
foreach f {v35_front_pkg.sv v35_pkg.sv v35_fn_pkg.sv v35_bus.sv v35_queue.sv v35_loader.sv v35_useq.sv v35_ea.sv v35_eu.sv v35_regram.sv v35_trace.sv v35_sfr.sv v35_refresh.sv v35_top.sv v35_tw.sv v35_tw_top.sv} {
    set_global_assignment -name SYSTEMVERILOG_FILE $f
}
# the wrapper has 10 pins; virtual so the fit is about the logic
foreach p {si xo[0] xo[1] xo[2] xo[3] xo[4] xo[5] xo[6] xo[7]} {
    set_instance_assignment -name VIRTUAL_PIN ON -to $p
}
project_close
