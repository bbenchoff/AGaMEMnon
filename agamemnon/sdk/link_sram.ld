ENTRY(_start)
MEMORY { SRAM (rwx) : ORIGIN = 0x20000000, LENGTH = 0x1000 }
SECTIONS {
  .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > SRAM
  .data : { __data_start = .; *(.data*) __data_end = .; } > SRAM
  __data_load_start = LOADADDR(.data);
  .bss (NOLOAD) : { __bss_start = .; *(.bss*) *(COMMON) __bss_end = .; } > SRAM
  __global_pointer$ = MIN(__data_start + 0x800, MAX(__data_start + 0x800, __bss_end - 0x800));
  /* Top of the 128 KiB SRAM (0x20000000 + 0x20000), clear of the staged fabric image at
     [0x20002000, 0x2001a668) -- matches agamemnon/program.py SRAM_SP and every historical
     qualification script. _start loads sp from this symbol directly, so it is the value that
     actually governs the runtime stack, regardless of any OpenOCD register preset. */
  __stack_top = 0x20020000;
  ASSERT(. <= 0x20001000, "SRAM program overlaps result mailbox")
}
