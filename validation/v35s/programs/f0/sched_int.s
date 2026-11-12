; F0 harness check: the marker-triggered schedule drives INT (sched_int.stim.json).
; Event 1 asks for INT; the program waits in HALT, so it does not depend on the
; tick INT lands on. The handler records that it ran, announces event 2 (the
; schedule drops INT) and passes. Simulation check of the harness (the ucore
; model takes INT with the vector it reads, FFh); INT/INTAK on silicon is F3's
; measurement.
    BR start                    ; two bytes: the handler is at 0102h
handler:
    MOV word [0400h], 1234h
    MOV DW, 0FF12h
    MOV AW, 2                   ; event 2: drop INT
    OUT DW, AW
    MOV DW, 0FF00h
    OUT DW, AW
spin:
    BR spin
start:
    XOR AW, AW
    MOV DS0, AW
    MOV SS, AW
    MOV SP, 0800h
    MOV word [03FCh], 0102h     ; vector FFh: the handler
    MOV word [03FEh], 0
    MOV word [0400h], 0
    MOV DW, 0FF12h
    MOV AW, 1                   ; event 1: raise INT
    EI
    OUT DW, AW
wait:
    HALT
    BR wait
