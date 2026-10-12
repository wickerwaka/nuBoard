; Bring CLKOUT out on P07 so the scope can time bus states against it.
; P0 is an input port at reset and the host drives it (T2 = H). Internal
; SFR writes never reach the bus, so each bank handoff is announced first
; with an OUT to the marker port 0xFF10 (fpga/v35s/v35s_lane.sv).
    MOV DW, 0FF10h
    MOV AW, 0001h          ; T2 disabled while the port changes direction
    OUT DW, AW
    MOV AW, 0F000h
    MOV DS0, AW            ; SFRs at 0xFFF00 while IDB = 0xFF
    MOV byte [0FF00h], 55h ; P0 output latch
    MOV byte [0FF01h], 00h ; PM0: P00-P07 outputs
    MOV byte [0FF02h], 80h ; PMC0: P07 = CLKOUT
    MOV DW, 0FF10h
    MOV AW, 0002h          ; T2 now driven by the CPU
    OUT DW, AW
    XOR AW, AW
    MOV DS0, AW
    MOV AW, 1234h
    MOV [0400h], AW        ; aligned word write
    MOV [0403h], AW        ; odd word write
    MOV AL, [0400h]        ; byte read
    MOV AW, [0403h]        ; odd word read
    IN AW, DW              ; I/O read of the marker port
    MOV DW, 0FF00h
    OUT DW, AW
    HALT
spin:
    BR spin
