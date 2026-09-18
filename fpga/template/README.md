# nuBoard FPGA template

This is the runtime companion for the streamed MCU firmware. It retains safe
DUT and buffer defaults, drives the 10 Hz configuration heartbeat on CSO, and
reuses CDI0..3 as a 10 MHz SPI mode-0 mailbox. NSTATUS becomes an active-low,
level-held interrupt in user mode.

The template provides one 4096-byte slot in each direction. A packet occupies
16 header bytes plus at most 4080 payload bytes. `READ_PACKET` is
non-destructive; the interrupt remains asserted until a matching `ACK_PACKET`.
The included `aps1604m_psram_echo` application passes every accepted byte
through the board's
[APS1604M-3SQR PSRAM](https://www.mouser.com/datasheet/2/1127/APM_PSRAM_QSPI_APS1604M_3SQR_v2_7_PKG-1954896.pdf)
before echoing it. It waits 163.84 us after entering user mode, issues the
required `66h`/`99h` reset sequence, and uses conservative 25 MHz SPI-mode
single-byte writes and reads. This keeps `CE#` assertion below 8 us and avoids
both page-boundary and minimum-frequency restrictions. A successful mailbox
echo therefore proves an external-memory write and read-back for every byte.

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
