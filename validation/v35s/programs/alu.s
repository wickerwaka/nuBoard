; Directed ALU, shift, multiply/divide, string and stack checks. Every result
; and the flags after it land in the result region at 0x0400, and every
; register is initialized first because the V35 leaves them undefined.
    XOR AW, AW
    MOV DS0, AW
    MOV DS1, AW
    MOV SS, AW
    MOV SP, 0800h
    MOV IX, 0400h          ; result pointer
    MOV IY, 0480h
    CLR1 DIR
    ; addition and subtraction
    MOV AW, 7FFFh
    ADD AW, 1
    MOV [IX], AW
    PUSH PSW
    POP BW
    MOV [IX+2], BW
    MOV AW, 0001h
    SUB AW, 2
    MOV [IX+4], AW
    PUSH PSW
    POP BW
    MOV [IX+6], BW
    MOV AL, 0FFh
    ADD AL, 1
    MOV [IX+8], AL
    MOV CW, 1234h
    ADDC CW, 0EDCCh
    MOV [IX+0Ah], CW
    ; logic and shifts
    MOV AW, 0F0F0h
    AND AW, 0FF00h
    OR AW, 000Fh
    XOR AW, 1111h
    MOV [IX+0Ch], AW
    MOV BW, 8001h
    SHL BW, 1
    MOV [IX+0Eh], BW
    MOV DW, 8001h
    SHRA DW, 1
    MOV [IX+10h], DW
    MOV AW, 1234h
    MOV CL, 4
    ROL AW, CL
    MOV [IX+12h], AW
    ; multiply and divide
    MOV AW, 1234h
    MOV CW, 0100h
    MULU CW
    MOV [IX+14h], AW
    MOV [IX+16h], DW
    MOV AW, 0FFFEh
    MOV CW, 3
    MUL CW
    MOV [IX+18h], AW
    MOV [IX+1Ah], DW
    MOV DW, 0
    MOV AW, 1000
    MOV CW, 7
    DIVU CW
    MOV [IX+1Ch], AW
    MOV [IX+1Eh], DW
    ; string move and compare
    MOV IX, 0420h
    MOV CW, 4
fill:
    MOV [IX], CW
    INC IX
    INC IX
    DBNZ fill
    MOV IX, 0420h
    MOV IY, 0430h
    MOV CW, 4
    REP
    MOVBKW
    MOV IX, 0420h
    MOV IY, 0430h
    MOV CW, 4
    REPE
    CMPBKW
    MOV [0440h], CW
    PUSH PSW
    POP AW
    MOV [0442h], AW
    ; a loop with a conditional branch
    MOV AW, 0
    MOV CW, 10
sum:
    ADD AW, CW
    DBNZ sum
    MOV [0444h], AW
    ; finish
    MOV DW, 0FF00h
    OUT DW, AW
    HALT
spin:
    BR spin
