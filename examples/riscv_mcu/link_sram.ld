OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    CODE (rwx) : ORIGIN = 0x20000000, LENGTH = 0x1000
}

__stack_top = 0x20020000;

SECTIONS
{
    .text : ALIGN(4)
    {
        KEEP(*(.text.start))
        *(.text*)
        *(.rodata*)
    } > CODE

    .data : ALIGN(4)
    {
        __data_start = .;
        *(.sdata*)
        *(.data*)
        . = ALIGN(4);
        __data_end = .;
    } > CODE
    __data_load_start = LOADADDR(.data);

    .bss (NOLOAD) : ALIGN(4)
    {
        __bss_start = .;
        *(.sbss*)
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > CODE

    __global_pointer$ = __data_start + 0x800;
    ASSERT(. <= 0x20001000, "SRAM example overlaps result mailbox at 0x20001000")
}

