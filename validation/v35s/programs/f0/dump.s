; F0: the register-bank and SFR dump (validation/v35s/dump.py). Every register
; gets a pattern, DUMPSTATE copies the banks and the default SFR list to
; 00800-00A0F, and the program then checks that every register survived.
    XOR AW, AW
    MOV DS0, AW
    MOV SS, AW
    MOV SP, 0800h
    MOV DS1, AW
    MOV AW, 1111h
    MOV CW, 2222h
    MOV DW, 3333h
    MOV BW, 4444h
    MOV BP, 5555h
    MOV IX, 6666h
    MOV IY, 7777h
    DUMPSTATE
    CMP AW, 1111h
    BNE fail
    CMP CW, 2222h
    BNE fail
    CMP DW, 3333h
    BNE fail
    CMP BW, 4444h
    BNE fail
    CMP BP, 5555h
    BNE fail
    CMP IX, 6666h
    BNE fail
    CMP IY, 7777h
    BNE fail
    CMP SP, 0800h
    BNE fail
    MOV AW, DS1
    CMP AW, 0
    BNE fail
    MOV [0400h], CW            ; one result word
    MOV DW, 0FF00h
    OUT DW, AW
    HALT
fail:
    MOV DW, 0FF02h
    OUT DW, AW
    HALT
