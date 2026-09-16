# RP2040 GPIO reference

The RP2040 is **U11** in [nuBoard.kicad_sch](../nuBoard.kicad_sch).
The assignments below were extracted from the schematic netlist. They describe
board wiring, not verified firmware behavior. Package pin numbers refer to U11.

| GPIO | Package pin | Signal | Board connection / purpose |
|---|---:|---|---|
| 0 | 2 | `FPGA_CDI0` | FPGA configuration data bit 0. |
| 1 | 3 | `FPGA_CDI1` | FPGA configuration data bit 1. |
| 2 | 4 | `FPGA_CDI2` | FPGA configuration data bit 2. |
| 3 | 5 | `FPGA_CDI3` | FPGA configuration data bit 3. |
| 4 | 6 | `FPGA_CCK` | FPGA configuration clock. |
| 5 | 7 | `FPGA_CSI` | FPGA configuration serial input. |
| 6 | 8 | `FPGA_CSO` | FPGA configuration serial output. |
| 7 | 9 | `FPGA_CRESET_N` | Active-low FPGA configuration reset; also J1 pin 10. |
| 8 | 11 | `FPGA_CDONE` | FPGA configuration-done indication. |
| 9 | 12 | `FPGA_SS_N` | Active-low FPGA configuration slave select. |
| 10 | 13 | `FPGA_NSTATUS` | FPGA configuration status. |
| 11 | 14 | `FPGA_CBUS0` | FPGA configuration bus/control bit 0. |
| 12 | 15 | `FPGA_CBUS1` | FPGA configuration bus/control bit 1. |
| 13 | 16 | `FPGA_CBUS2` | FPGA configuration bus/control bit 2. |
| 14 | 17 | `FPGA_TCK` | FPGA JTAG clock; also J1 pin 4. |
| 15 | 18 | `FPGA_TDI` | JTAG data into FPGA; also J1 pin 8. |
| 16 | 27 | `FPGA_TDO` | JTAG data from FPGA; also J1 pin 6. |
| 17 | 28 | `FPGA_TMS` | FPGA JTAG mode select; also J1 pin 2. |
| 18 | 29 | `VCCB_MUX_D1` | D1 control input of U9, the VCCB 3.3 V / 5 V power mux; 10 kΩ pull-up to `+3.3V_DUT`. |
| 19 | 30 | `VCCB_MUX_D0` | D0 control input of U9; 10 kΩ pull-up to `+3.3V_DUT`. |
| 20 | 31 | `5V_SELECT` | Daughter-board 5 V selection sense, J7 pin 1; 10 kΩ pull-up to `+3.3V_MCU`. |
| 21 | 32 | `3V3_SELECT` | Daughter-board 3.3 V selection sense, J6 pin 1; 10 kΩ pull-up to `+3.3V_MCU`. |
| 22 | 34 | Unconnected | Explicit no-connect. |
| 23 | 35 | Unconnected | Explicit no-connect. |
| 24 | 36 | `FPGA_1V2_EN` | Enable for FPGA 1.2 V regulator U7; 10 kΩ pull-down. |
| 25 | 37 | `FPGA_3V3_EN` | Enable for FPGA 3.3 V regulator U6; 10 kΩ pull-down. |
| 26 / ADC0 | 38 | Unconnected | Explicit no-connect. |
| 27 / ADC1 | 39 | Unconnected | Explicit no-connect. |
| 28 / ADC2 | 40 | `MCU_LED2` | Drives LED D4, active low, through a 1 kΩ series resistor. |
| 29 / ADC3 | 41 | `MCU_LED1` | Drives LED D3, active low, through a 1 kΩ series resistor. |

**26 GPIOs are connected; four are unused: GPIO22, GPIO23, GPIO26, and GPIO27.**
The dedicated QSPI pins connect to flash U10. USB, SWD, and RUN/reset use
separate pins outside GPIO0–29.
