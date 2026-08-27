ENTRY(_start)

/*
 * R5 buffered-observer window.  This separately versioned linker preserves
 * the byte-exact R3/R4 linker while placing code and observer scratch above
 * the staged fabric image and below 0x2001c000.
 */
MEMORY {
  OBSERVER_SRAM (rwx) : ORIGIN = 0x2001b000, LENGTH = 0x1000
}

SECTIONS {
  .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > OBSERVER_SRAM
  .data : { __data_start = .; *(.data*) __data_end = .; } > OBSERVER_SRAM
  __data_load_start = LOADADDR(.data);
  .ag32_hil_observer_scratch (NOLOAD) : ALIGN(4) {
    __ag32_hil_observer_scratch_start = .;
    KEEP(*(.ag32_hil_observer_scratch))
    __ag32_hil_observer_scratch_end = .;
  } > OBSERVER_SRAM
  .bss (NOLOAD) : { __bss_start = .; *(.bss*) *(COMMON) __bss_end = .; }
      > OBSERVER_SRAM
  __global_pointer$ = MIN(__data_start + 0x800,
                          MAX(__data_start + 0x800, __bss_end - 0x800));
  __stack_top = 0x20020000;

  ASSERT(ADDR(.text) == 0x2001b000,
         "R5 observer entry moved from 0x2001b000")
  ASSERT(__ag32_hil_observer_scratch_start >= 0x2001b000,
         "buffered observer scratch escaped high SRAM")
  ASSERT(__ag32_hil_observer_scratch_end <= 0x2001c000,
         "buffered observer scratch escaped the R5 4 KiB window")
  ASSERT(. <= 0x2001c000,
         "R5 observer exceeds dedicated 4 KiB SRAM window")
}
