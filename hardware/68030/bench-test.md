# MC68030 bench qualification — not performed

No assembled board, host firmware, CPU sample or measurement instruments were available. All steps and results below are pending. Layout checks cannot establish electrical or timing compatibility.

1. With the daughter disconnected and unpowered, check the A1 corner, all 128 holes and the five reserved NC pins (D5, E12, F4, F10, K5). Verify all ten VCC pins and fourteen grounds, no power short, correct C16 polarity, and 5V_SELECT=GND with 3V3_SELECT isolated.
2. Check L00–L03 continuity and about 47 kΩ to GND through R1. Check R13–R14 continuity and about 47 kΩ to GND through R2. Verify isolation from each other and from every used bit. Review host output masks before connecting the host; all tied unused bits must stay LOW whenever a bank drives toward the CPU.
3. Budget at least 2.6 W for the CPU (about 0.55 A at 4.75 V, excluding external loading). Verify the host can supply this plus its own loads. Start with an appropriate current limit and stop on abnormal current/heating. Measure VCC at every CPU supply group and confirm 4.75–5.25 V, including transients during simultaneous switching, bursts and reset.
4. Start with a qualified continuous 12.5 MHz clock. Measure at U1 E1: 40–80 ns period for the grade, high/low pulse widths within the applicable table, rise/fall ≤4 ns for the 25 MHz grade. Keep /RESET asserted for ≥520 clocks after valid power, release and check the actual waveform. Check the CPU-generated 512-clock RESET instruction pulse separately.
5. Measure X/Y idle HIGH and asserted LOW at the socket with the TXS0108E enabled. Confirm the host only sinks or releases. Check reset release and arbitration/interrupt transitions with the 10 µs initial scheduling allowance; increase it if measurements require. Do not treat a sampled level at the FPGA as proof of the socket's transition time.
6. Qualify the **direct TTL/CMOS interface before functional sign-off**. The CPU guarantees only VOH≥2.4 V at 400 µA; the host expects about 0.7×VCCB and may require up to 0.9 mA to overcome a keeper. Precondition a released bidirectional conductor LOW, release host drive, then make the CPU drive HIGH in a controlled valid cycle. Capture CPU pin voltage, rise time, settling, translator output and any intermediate level. Exercise both transitions, all data lanes, addresses and control outputs at supply/temperature/load corners within the part rating. For always-driven outputs, use normal CPU transitions; never force the opposite host level.
7. Verify reset-vector reads and a simple loop using asynchronous 8-bit, 16-bit and 32-bit ports. Test byte/word/longword operands at all four address offsets, split/misaligned transfers, waits, reads and writes, CPU-space/interrupt-acknowledge cycles and error/retry sequences. Confirm no host bank drives during CPU writes or turnaround.
8. Test 32-bit synchronous reads and both cache fill types, correct modulo-four burst ordering, /CIIN, /CDIS, /CBACK withdrawal, partial fills and errors. Add waits or decline bursts until the schedule can supply each beat with measured margin. Test /MMUDIS and MMU-enabled operation with valid translation tables; this board does not supply firmware or tables.
9. Test /BR-/BG-/BGACK takeover, return to the CPU, requests during active cycles/cache execution, /RMC deferral and explicit single-wire arbitration. Scope both CPU and host output release. Keep R1 D; mask L0 unused bits LOW. Test released conductors only after ownership and float delays are established.
10. Increase clock toward 25 MHz only after voltage, rise/fall, propagation, data setup/hold and arbitration timing have measured positive margin. At 25 MHz a half-cycle is only 20 ns; CPU output delay alone can reach 20 ns, before host translation and logic. No 25 MHz guarantee is implied.

Record CPU full marking/mask, host revision, firmware commit, supply/load, clock waveform, temperature, test case, minimum margins and waveform filenames. Stop qualification of any condition that misses thresholds or timing; a room-temperature success is not a worst-case guarantee. Keep failures in the result log instead of masking them with opposing host drive or unplanned signal pulls.

| Measurement | Result |
| --- | --- |
| Assembly/continuity and NC isolation | Pending |
| Supply current, rail droop and thermal behavior | Pending |
| X/Y levels, reset timing and release | Pending |
| TTL output high / host keeper overdrive | Pending |
| 8/16/32-bit and misaligned bus cycles | Pending |
| Cache, burst and MMU modes | Pending |
| Arbitration, lock/retry and direction transitions | Pending |
| 12.5 MHz and 25 MHz timing margins | Pending |
