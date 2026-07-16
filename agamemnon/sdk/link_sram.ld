ENTRY(_start)
MEMORY { SRAM (rwx) : ORIGIN = 0x20000000, LENGTH = 0x1000 }
SECTIONS {
  .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > SRAM
  .data : { __data_start = .; *(.data*) __data_end = .; } > SRAM
  __data_load_start = LOADADDR(.data);
  .bss (NOLOAD) : { __bss_start = .; *(.bss*) *(COMMON) __bss_end = .; } > SRAM
  __global_pointer$ = MIN(__data_start + 0x800, MAX(__data_start + 0x800, __bss_end - 0x800));
  __stack_top = 0x20008000;
  ASSERT(. <= 0x20001000, "SRAM program overlaps result mailbox")
}
