# nuBoard RP2040 firmware

This directory contains the firmware for the RP2040 on the nuBoard main board.
The initial firmware blinks `MCU_LED1` on GPIO 29 and `MCU_LED2` on GPIO 28
together at 1 Hz. Both LEDs are active low. USB CDC stdio is enabled and the
UART stdio backend is disabled.

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
