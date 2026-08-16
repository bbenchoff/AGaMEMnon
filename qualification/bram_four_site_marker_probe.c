// SRAM-only probe for a vendor-routed four-BRAM marker image.
// The image maps b0..b3 low bytes to AHB bits 7:0..31:24 and initializes
// every word in those hard arrays to 0x11, 0x22, 0x44, and 0x88.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  volatile u32 *bram = (volatile u32 *)0x60000000u;
  const u32 expected = 0x88442211u;

  R(0x0300000cu) &= ~0x27u;
  R(0x03000060u) |= (1u << 0) | (1u << 8);
  R(0x03000030u) = 0u;

  R(0x40010000u) = (1u << 6);
  for (u32 i = 0; i < 24986u; ++i)
    R(0x4001000cu) = cfg[i];
  for (volatile u32 i = 0; i < 512u; ++i) ;

  u32 first = bram[0];
  u32 last = first;
  u32 mismatches = 0;
  for (u32 i = 0; i < 256u; ++i) {
    last = bram[i & 0xffu];
    if (last != expected)
      ++mismatches;
  }

  out[0] = R(0x40010010u);
  out[1] = first;
  out[2] = last;
  out[3] = mismatches;
  out[4] = expected;
  out[5] = 0xc0ffee04u;
  for (;;)
    __asm__ volatile("ebreak");
}
