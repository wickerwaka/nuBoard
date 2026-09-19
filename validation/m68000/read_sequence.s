/* Build with --defsym READ_COUNT=0 or 8. Markers bracket only the read block. */
        .text
        .global _start
_start:
        lea     0x0200.w, %a0
        move.w  #0x1111, 0x0400.w

        .if READ_COUNT == 8
        move.w  (%a0)+, %d0
        move.w  (%a0)+, %d1
        move.w  (%a0)+, %d2
        move.w  (%a0)+, %d3
        move.w  (%a0)+, %d4
        move.w  (%a0)+, %d5
        move.w  (%a0)+, %d6
        move.w  (%a0)+, %d7
        .else
        .if READ_COUNT != 0
        .error "READ_COUNT must be 0 or 8"
        .endif
        .endif

        move.w  #0x2222, 0x0402.w
        .if READ_COUNT == 8
        movem.w %d0-%d7, 0x0300.w /* Verify all eight loaded values after timing. */
        .endif
        move.l  #1, 0x00100004   /* Harness completion marker. */
stop:
        bra.s   stop
