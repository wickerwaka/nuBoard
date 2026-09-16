# nuBoard RP2040 firmware

This directory contains the firmware for the RP2040 on the nuBoard main board.
It provides a USB CDC serial console for controlling the two LEDs, FPGA power
rails, and the VCCB rail selector. UART stdio is disabled.

All outputs start off: both LEDs are dark, both FPGA regulator enables are low,
and the VCCB selector is set to `D0=1, D1=1`. FPGA `CRESET_N` on GPIO7 is
driven low at startup and held low at all times.

## Console

Open the board's USB serial device at any baud rate. The console accepts:

```text
led1 [on|off]
led2 [on|off]
1v2_fpga [on|off]
3v3_fpga [on|off]
vccb [off|3v3|5v]
help
```

Commands with no argument report the current state. Commands that change an
output print the resulting state. The VCCB settings drive its mux as follows:

| State | D0 / GPIO19 | D1 / GPIO18 |
|---|---:|---:|
| `off` | 1 | 1 |
| `3v3` | 0 | 1 |
| `5v` | 0 | 0 |

## Clone

The Raspberry Pi Pico SDK is included as a Git submodule. After cloning the
repository, initialize it with:

```sh
git submodule update --init --recursive
```

## Build

Install an Arm GNU toolchain, CMake, and a `picotool` version compatible with
the checked-out SDK, then run:

```sh
cd mcu
cmake -S . -B build
cmake --build build
```

If CMake finds an older incompatible `picotool`, tell the SDK to fetch its
matching version instead:

```sh
cmake -S . -B build -DPICOTOOL_FORCE_FETCH_FROM_GIT=ON
cmake --build build
```

The flashable UF2 file is written to `build/nuboard_mcu.uf2`.
