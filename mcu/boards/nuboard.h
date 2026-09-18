/*
 * SPDX-License-Identifier: MIT
 */

// This header is also included by the assembler. Keep it to preprocessor
// directives and pico_board_cmake_set calls.

#ifndef _BOARDS_NUBOARD_H
#define _BOARDS_NUBOARD_H

pico_board_cmake_set(PICO_PLATFORM, rp2040)

#define NUBOARD

// --- LEDs ---
#define PICO_DEFAULT_LED_PIN 29
#define PICO_DEFAULT_LED_PIN_INVERTED 1
#define NUBOARD_LED_1_PIN 29
#define NUBOARD_LED_2_PIN 28

// --- Power control ---
#define NUBOARD_FPGA_CRESET_N_PIN 7
#define NUBOARD_FPGA_1V2_EN_PIN 24
#define NUBOARD_FPGA_3V3_EN_PIN 25
#define NUBOARD_VCCB_MUX_D0_PIN 19
#define NUBOARD_VCCB_MUX_D1_PIN 18
#define NUBOARD_5V_SELECT_PIN 20
#define NUBOARD_3V3_SELECT_PIN 21

// --- FPGA passive-SPI configuration and JTAG ---
#define NUBOARD_FPGA_CDI0_PIN 0
#define NUBOARD_FPGA_CDI1_PIN 1
#define NUBOARD_FPGA_CDI2_PIN 2
#define NUBOARD_FPGA_CDI3_PIN 3
#define NUBOARD_FPGA_CCK_PIN 4
#define NUBOARD_FPGA_CSI_PIN 5
#define NUBOARD_FPGA_CSO_PIN 6
#define NUBOARD_FPGA_CDONE_PIN 8
#define NUBOARD_FPGA_SS_N_PIN 9
#define NUBOARD_FPGA_NSTATUS_PIN 10
#define NUBOARD_FPGA_CBUS0_PIN 11
#define NUBOARD_FPGA_CBUS1_PIN 12
#define NUBOARD_FPGA_CBUS2_PIN 13
#define NUBOARD_FPGA_TCK_PIN 14
#define NUBOARD_FPGA_TDI_PIN 15
#define NUBOARD_FPGA_TDO_PIN 16
#define NUBOARD_FPGA_TMS_PIN 17

// --- Flash: Winbond W25Q128JV, 16 MiB ---
#define PICO_BOOT_STAGE2_CHOOSE_W25Q080 1

#ifndef PICO_FLASH_SPI_CLKDIV
#define PICO_FLASH_SPI_CLKDIV 2
#endif

pico_board_cmake_set_default(PICO_FLASH_SIZE_BYTES, (16 * 1024 * 1024))
#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES (16 * 1024 * 1024)
#endif

#ifndef PICO_RP2040_B0_SUPPORTED
#define PICO_RP2040_B0_SUPPORTED 0
#endif

#endif
