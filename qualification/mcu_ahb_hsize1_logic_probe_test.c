// SRAM-only silicon oracle for the isolated External-AHB HSIZE[1] route.
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define R(a) (*(volatile u32 *)(a))

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  const u32 base = 0x60000000u;
  u32 word_errors = 0, half_errors = 0, byte_errors = 0;

  R(0x0300000cu) &= ~0x27u;
  R(0x03000060u) |= (1u << 0) | (1u << 8);
  R(0x03000030u) = 0u;
  R(0x40010000u) = (1u << 6);
  for (u32 i = 0; i < 24986u; ++i)
    R(0x4001000cu) = cfg[i];
  for (volatile u32 i = 0; i < 256u; ++i) ;

  u32 stat = R(0x40010010u);

  // Keep address and transfer size fixed within each block. HRDATA is a data-
  // phase value, while HSIZE belongs to the address phase; interleaving sizes
  // tests the following transfer rather than the isolated combinational route.
  (void)*(volatile u32 *)base;
  for (u32 i = 0; i < 256u; ++i)
    if ((*(volatile u32 *)base & 1u) != 1u) ++word_errors;
  (void)*(volatile u16 *)base;
  for (u32 i = 0; i < 256u; ++i)
    if ((*(volatile u16 *)base & 1u) != 0u) ++half_errors;
  (void)*(volatile u8 *)base;
  for (u32 i = 0; i < 256u; ++i)
    if ((*(volatile u8 *)base & 1u) != 0u) ++byte_errors;

  out[0] = stat;
  out[1] = word_errors;
  out[2] = half_errors;
  out[3] = byte_errors;
  out[4] = 256u;
  out[5] = 0xc0ffee16u;
  for (;;)
    __asm__ volatile("ebreak");
}
