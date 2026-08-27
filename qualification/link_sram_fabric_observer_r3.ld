ENTRY(_start)

/*
 * R3 observer-only SRAM window.  The live probe executes above the staged
 * fabric image [0x20002000, 0x2001a668), leaving 0x20000000/+4 exclusively
 * for the two fabric-master marker words.  Keep this scoped linker separate
 * from the shared low-SRAM SDK contract.
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
         "R3 observer entry moved from 0x2001b000")
  ASSERT(__ag32_hil_observer_scratch_start >= 0x2001b000,
         "buffered observer scratch escaped high SRAM")
  ASSERT(__ag32_hil_observer_scratch_end <= 0x20020000,
         "buffered observer scratch exceeds physical SRAM")
  ASSERT(. <= 0x2001c000,
         "R3 observer exceeds dedicated 4 KiB SRAM window")
}
