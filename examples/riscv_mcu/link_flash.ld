OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    /* Sectors 0..6 only. Sector 7 contains the qualified decompressor. */
    FLASH (rx)  : ORIGIN = 0x80000000, LENGTH = 0x7000
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 0x1000
}

__stack_top = 0x20020000;

SECTIONS
{
    .text : ALIGN(4)
    {
        KEEP(*(.text.start))
        *(.text*)
        *(.rodata*)
    } > FLASH

    .data : ALIGN(4)
    {
        __data_start = .;
        *(.sdata*)
        *(.data*)
        . = ALIGN(4);
        __data_end = .;
    } > RAM AT > FLASH
    __data_load_start = LOADADDR(.data);

    .bss (NOLOAD) : ALIGN(4)
    {
        __bss_start = .;
        *(.sbss*)
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > RAM

    __global_pointer$ = __data_start + 0x800;
    __flash_image_end = LOADADDR(.data) + SIZEOF(.data);
    ASSERT(__flash_image_end <= 0x80007000,
           "flash example overlaps decompressor at 0x80007000")
}

