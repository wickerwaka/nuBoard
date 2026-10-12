; Minimal bring-up: the reset vector far-jumps here, then report pass.
    MOV AW, 0              ; AW is undefined after reset
    MOV DW, 0FF00h
    OUT DW, AW
    HALT
spin:
    BR spin
