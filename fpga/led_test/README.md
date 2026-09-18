# Rear bank LED test

This diagnostic cycles through `T0..T2`, `B0..B2`, `L0..L2`, and
`R0..R2`. Each bank shows these states for half a second apiece:

1. both LEDs off (`OE_N=1`)
2. red LED on (`OE_N=0`, `DIR=0`)
3. green LED on (`OE_N=0`, `DIR=1`)

Only one bank is enabled at a time. The parallel data signals stay high
impedance, XY remains disabled, the clock buffers remain disabled, and the
normal DUT isolation/crowbar safety defaults are retained.

Build with:

```sh
./build.sh
```

Run the sequencer and output-mapping test with:

```sh
./test.sh
```

The passive-x4 image is written to
`build/fpga/led_test/outflow/led_test.hex.bin`.
