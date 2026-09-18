# nuBoard RP2040 firmware

The firmware exposes a composite USB device, streams a host-supplied passive-x4
image into the FPGA, qualifies the runtime mailbox, and owns fail-closed power
sequencing. No FPGA image is compiled into the firmware.

See [`docs/protocol.md`](../docs/protocol.md) for the ABIs and power rules.

```sh
git submodule update --init --recursive
cmake -S mcu -B build/mcu -DCMAKE_BUILD_TYPE=Release
cmake --build build/mcu
```

The output is `build/mcu/nuboard_mcu.uf2`. CDC accepts only `help`, `info`, and
`status`; use the Python CLI for all mutating operations. Interface 4 retains
the standard Raspberry Pi vendor reset interface for `picotool -f` workflows.
