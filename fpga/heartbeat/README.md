# nuBoard heartbeat FPGA image

This Efinity project targets the exact fitted `T120F484C3` in passive SPI x4
mode with configuration CRC enabled.  It divides the 50 MHz oscillator on A20
to a 10 Hz, 50% duty heartbeat on the CSO/user-I/O ball U5.  A18, which is
wired to the same oscillator net, is constrained as an unused input.

Build with Efinity 2026.1.  The wrapper keeps all generated files under the
repository's ignored `build/` directory:

```sh
./fpga/heartbeat/build.sh
```

The raw passive-configuration image is
`build/fpga/heartbeat/outflow/heartbeat.hex.bin`. This is the raw passive-SPI
image; Efinity's `.bit` and `.bit.bin` outputs are for JTAG. The same directory
contains
the timing and pin reports used to verify the 50 MHz constraint and every
safety-critical ball assignment.
