    .text
    .global _start
_start:
    move.w #8191,%d0
1:
    nop
    dbf %d0,1b
    move.l #1,0x100004
2:
    bra.s 2b
