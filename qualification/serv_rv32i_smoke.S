/* Source of the instruction words embedded in serv_rv32i_smoke.v.
 *
 * This is a focused, self-checking RV32I instruction-signature workload.  It
 * covers dependent immediate, shift, logical, store, and both taken and
 * not-taken control-flow operations.  It is not the complete
 * riscv-arch-test suite.
 */
    .section .text
    .globl _start
_start:
    addi x1, x0, 5
    slli x2, x1, 2
    xori x3, x2, 7
    addi x4, x0, 19
    bne  x3, x4, fail
    beq  x3, x4, okay
fail:
    sw   x0, 0(x0)
    jal  x0, fail
okay:
    sw   x3, 0(x0)
    jal  x0, okay
