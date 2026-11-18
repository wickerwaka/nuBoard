# Quartus build of the V35S core v2

Intel Quartus Prime 17.1 Lite, Cyclone V 5CSEBA6U23I7 (the MiSTer DE10-Nano part), one clock at
17 ns, no other constraint. Same file list and `SYNTHESIS` define as `../v35_timing.sh top`, and
the same timing wrapper (`../v35_tw.sv`, `../v35_tw.py`: input shift chain, registered outputs
folded onto eight pins), so the project has one real pin (`clk_sys`) and nine virtual pins.

    fpga/v35s/synth/quartus/run.sh          # map, fit, sta
    fpga/v35s/synth/quartus/run.sh map      # Analysis & Synthesis only (restages the sources)
    fpga/v35s/synth/quartus/run.sh fit|sta  # on the last staged project

`QUARTUS_BIN` (default `~/intelFPGA_lite/17.1/quartus/bin`) and `BUILD_DIR` (default
`build/fpga/v35s/quartus`) override the locations. The sources are copied into `$BUILD_DIR/stage`
(with the microcode hex files under `fpga/v35s/core/v35/`, where `$readmemh` finds them), the
project `v35s` is generated there by `v35s.tcl`, and the reports are `v35s.{map,fit,sta}.rpt`.
4 processors (`NUM_PARALLEL_PROCESSORS`). About 2 min map, 4-7 min fit, 1 min sta.

Notes for the Quartus 17.1 front end:

- `AUTO_ROM_RECOGNITION` stays on globally (that is what puts the six microcode banks in M10K)
  and is switched off for the loader instance in `v35s.tcl`: Verific crashes ("Can't extract a
  ROM based on this value") on the loader's decode-table functions otherwise. `ROMOFF=1` turns
  it off for the whole design (the ROMs then become logic).
- Quartus defines `SYNTHESIS` itself; the project sets it too, as the Efinity flow does.
