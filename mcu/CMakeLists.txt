cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD nuboard CACHE STRING "Target board")
set(PICO_BOARD_HEADER_DIRS ${CMAKE_CURRENT_LIST_DIR}/boards)

include(pico-sdk/pico_sdk_init.cmake)

project(nuboard_mcu C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(nuboard_mcu
    src/main.c
)

target_link_libraries(nuboard_mcu
    pico_stdlib
)

# Expose stdio over USB CDC without reserving GPIOs for a UART console.
pico_enable_stdio_uart(nuboard_mcu 0)
pico_enable_stdio_usb(nuboard_mcu 1)

pico_add_extra_outputs(nuboard_mcu)
