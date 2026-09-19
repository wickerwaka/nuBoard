/* Minimal ordinary operand read and write, after the reset-vector fetches. */
        .text
        .global _start
_start:
        move.w  0x0200.w, %d0
        move.w  %d0, 0x0202.w
        move.l  #1, 0x00100004   /* Harness completion marker. */
stop:
        bra.s   stop
