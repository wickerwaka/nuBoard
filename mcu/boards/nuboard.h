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

