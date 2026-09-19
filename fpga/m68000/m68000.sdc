create_clock -period 20.000 -name clk_50mhz [get_ports clk_50mhz]
create_clock -period 100.000 -name spi_sck [get_ports spi_sck]
# CS release commits a transaction. Ownership toggles cross two-flop barriers;
# packet RAM remains stable until its corresponding acknowledgement.
create_clock -period 100.000 -name spi_commit [get_ports spi_cs_n]
set_clock_groups -asynchronous -group [get_clocks clk_50mhz] -group [get_clocks spi_sck] -group [get_clocks spi_commit]
# Mode 0: MCU launches MOSI on falling edges, FPGA samples rising edges.
set_input_delay -clock spi_sck -clock_fall -max 10.000 [get_ports spi_mosi]
set_input_delay -clock spi_sck -clock_fall -min 0.000 [get_ports spi_mosi]
set_output_delay -clock spi_sck -max 10.000 [get_ports spi_miso]
set_output_delay -clock spi_sck -min 0.000 [get_ports spi_miso]

# Socket pins enter a two-flop pipeline. External translator/CPU timing and
# bidirectional turnaround require bench qualification; do not call internal
# timing closure a socket timing signoff. CPU phases are still 50 MHz enables.
