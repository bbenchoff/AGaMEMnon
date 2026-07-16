ENTRY(_start)
MEMORY { FLASH (rx) : ORIGIN = 0x80010000, LENGTH = 0x30000; SRAM (rwx) : ORIGIN = 0x20000000, LENGTH = 0x20000 }
SECTIONS {
  .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > FLASH
  .data : { __data_start = .; *(.data*) __data_end = .; } > SRAM AT> FLASH
  __data_load_start = LOADADDR(.data);
  .bss (NOLOAD) : { __bss_start = .; *(.bss*) *(COMMON) __bss_end = .; } > SRAM
  __global_pointer$ = MIN(__data_start + 0x800, MAX(__data_start + 0x800, __bss_end - 0x800));
  __stack_top = 0x20020000;
}
