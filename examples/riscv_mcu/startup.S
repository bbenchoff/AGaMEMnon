/* Minimal RV32 startup shared by the SRAM and flash examples. */
.section .text.start, "ax", @progbits
.globl _start
.type _start, @function

_start:
    .option push
    .option norelax
    la      gp, __global_pointer$
    .option pop
    la      sp, __stack_top

    /* Copy initialized data when its load and run addresses differ. */
    la      t0, __data_load_start
    la      t1, __data_start
    la      t2, __data_end
1:
    bgeu    t1, t2, 2f
    lw      t3, 0(t0)
    sw      t3, 0(t1)
    addi    t0, t0, 4
    addi    t1, t1, 4
    j       1b

    /* Clear BSS. */
2:
    la      t1, __bss_start
    la      t2, __bss_end
3:
    bgeu    t1, t2, 4f
    sw      zero, 0(t1)
    addi    t1, t1, 4
    j       3b

4:
    call    main

    /* Returning from main is an observable debugger stop. */
5:
    ebreak
    j       5b

.size _start, . - _start

