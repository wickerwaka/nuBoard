4 CLK signals with OE (4 FPGA signals)
8 open-collector bidir (8 FPGA signals?)
96 GPIO (108 FPGA signals)

HyperRAM: matched top-layer layout promoted into main-board. U2 and all
585 signal segments locked; CK/DQ0–7/RWDS spread 0.214807 mm, no vias.
Finish power/bypass and CS#/RESET# pull-up connections, resolve remaining
board opens, and implement/validate the HyperRAM controller and timing.
See notes/hyperram.md; routing/hyperram-top retains the reference snapshot.
QSPI RP2350 (6 signals)

LEDs (4 signals)

USB-C port and DC barrel jack

GT-USB-7010ASV usb

AP2112 for 3.3v and 1.2v regulation

ASE-50.000MHZ-ET crystal for fpga

IS66WVH8M8BLL-100B1LI, 8MB HyperRAM (signals routed/matched; power unfinished)

TPS2116 for power multiplexing
74LVCH8T245 for general signals. 8 signals each, plus DIR and OE.
TXS0108E for open-collector
74AHCT125 for clock signals
