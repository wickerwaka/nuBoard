# clk_sys is PLL_TR1 CLKOUT0, 33.33 MHz.
create_clock -period 30.000 -name clk_sys [get_ports {clk_sys}]
create_clock -period 100.000 -name spi_sck [get_ports spi_sck]
set_clock_groups -asynchronous -group [get_clocks clk_sys] -group [get_clocks spi_sck]
