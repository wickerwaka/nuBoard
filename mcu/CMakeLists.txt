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
    src/fpga_config.c
    src/nub_protocol.c
    src/nub_stream.c
    src/runtime_link.c
    src/runtime_crc.c
    src/sha256.c
    src/usb_descriptors.c
    src/usb_stack.c
)

pico_generate_pio_header(nuboard_mcu
    "${CMAKE_CURRENT_LIST_DIR}/src/fpga_spi.pio")

target_include_directories(nuboard_mcu PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/src"
)

target_compile_options(nuboard_mcu PRIVATE
    -Wall
    -Wextra
)

target_link_libraries(nuboard_mcu
    pico_stdlib
    hardware_clocks
    hardware_dma
    hardware_pio
    hardware_spi
    pico_unique_id
    pico_usb_reset
    tinyusb_device
)

# Bench diagnostic: firmware that powers FPGA rails at boot and holds them with
# the FPGA in reset. -DNUBOARD_RAIL_TEST=1v2 enables only 1.2 V; =both follows
# the normal sequence to 1.2 V plus 3.3 V. Never use it for normal operation.
set(NUBOARD_RAIL_TEST "" CACHE STRING "Bench rail test (empty, 1v2 or both)")
if(NUBOARD_RAIL_TEST STREQUAL "1v2")
    target_compile_definitions(nuboard_mcu PRIVATE NUBOARD_RAIL_TEST=1)
elseif(NUBOARD_RAIL_TEST STREQUAL "both")
    target_compile_definitions(nuboard_mcu PRIVATE NUBOARD_RAIL_TEST=2)
elseif(NOT NUBOARD_RAIL_TEST STREQUAL "")
    message(FATAL_ERROR "NUBOARD_RAIL_TEST must be empty, 1v2 or both")
endif()

target_compile_definitions(nuboard_mcu PRIVATE
    PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1
    PICO_USB_RESET_INCLUDE_DEFAULT_APP_DRIVER_CB=0
    PICO_USB_RESET_SUPPORT_MS_OS_20_DESCRIPTOR=0
)

# Expose stdio over USB CDC without reserving GPIOs for a UART console.
pico_enable_stdio_uart(nuboard_mcu 0)
pico_enable_stdio_usb(nuboard_mcu 0)

pico_add_extra_outputs(nuboard_mcu)
