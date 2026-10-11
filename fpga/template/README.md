# nuBoard FPGA template

This is the runtime companion for the streamed MCU firmware. It retains safe
DUT and buffer defaults, drives the 10 Hz configuration heartbeat on CSO, and
reuses CDI0..3 as a 10 MHz SPI mode-0 mailbox. NSTATUS becomes an active-low,
level-held interrupt in user mode.

The template provides one 4096-byte slot in each direction. A packet occupies
16 header bytes plus at most 4080 payload bytes. `READ_PACKET` is
non-destructive; the interrupt remains asserted until a matching `ACK_PACKET`.
The included `nuboard_stream_echo` application returns every accepted byte
unchanged, which exercises the mailbox, both slots, backpressure, and the CRC
and ACK handling without any external memory.

Revision 2 has no PSRAM. The template does not use the HyperRAM (U2) either: it
drives `HR_CS_N` and `HR_RESET_N` inactive-high so the device stays deselected,
and leaves CK, RWDS and DQ0-7 unassigned. Pin assignments in `template.isf`
follow `hardware/main-board/fpga_pin_map.csv`, including all four sideband
lines on each socket (`tx[3:0]`, `bx[3:0]`, `lx[3:0]`, `rx[3:0]`, which are
`F_TX0`..`F_TX3` and so on).

The application connects to the mailbox through byte-wide input and output
streams with `valid`, `ready`, and `last` signals. Replace it with a
core-specific application while retaining the mailbox and slot logic.

Run the behavioral test with:

```sh
./fpga/template/test.sh
```

Route a passive-x4 image with Efinity 2026.1 using:

```sh
./fpga/template/build.sh
```
