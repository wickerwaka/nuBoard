create_clock -period 20.000 -name clk_50mhz [get_ports clk_50mhz]
create_clock -period 100.000 -name spi_sck [get_ports spi_sck]
set_clock_groups -asynchronous -group [get_clocks clk_50mhz] -group [get_clocks spi_sck]

# build.sh appends the HyperRAM PLL clocks (clk_hr, clk_hr90, clk_hr_cal) for
# the configured frequency and capture phase.
