OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    /* A separately linked application region; the USB loader remains at 0. */
    FLASH (rx)  : ORIGIN = 0x80010000, LENGTH = 0x30000
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
    ASSERT(__flash_image_end <= 0x80040000, "USB application exceeds main flash")
}

