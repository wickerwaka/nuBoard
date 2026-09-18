cmake_minimum_required(VERSION 3.16)
project(nuboard_native_tests C)
enable_testing()
add_executable(
    protocol_test
    protocol_test.c
    ../mcu/src/nub_protocol.c
    ../mcu/src/nub_stream.c
    ../mcu/src/sha256.c
    ../mcu/src/runtime_crc.c
)
target_include_directories(protocol_test PRIVATE ../mcu/src)
target_compile_options(protocol_test PRIVATE -Wall -Wextra -Werror)
add_test(NAME protocol_test COMMAND protocol_test)
