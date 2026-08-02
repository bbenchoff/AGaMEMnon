// SRAM-only External-AHB constant-slave qualification.
//
// The endpoint completes every transfer ready/OKAY and returns a fixed
// identification word on all 32 HRDATA lanes. Reads must return 0x4147414d
// ("AGAM") and writes must complete without effect. The design is fully
// combinational, so this test does not depend on the unresolved bus clock.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

#define BANK 0x60000000u
#define MAILBOX 0x20001000u

void __attribute__((section(".text.start"))) _start(void) {
  R(0x0300000Cu) &= ~0x27u;
  R(0x03000060u) |= (1u << 0) | (1u << 8);

  volatile u32 *out = (volatile u32 *)MAILBOX;
  for (u32 i = 0; i < 16u; ++i)
    out[i] = 0u;

  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  R(0x40010000u) = (1u << 6);
  for (u32 i = 0; i < 24986u; ++i)
    R(0x4001000Cu) = cfg[i];
  out[0] = R(0x40010010u); // FCB status, expect 0x000f0002

  out[1] = R(BANK + 0x0u);
  out[2] = R(BANK + 0x4u);
  out[3] = R(BANK + 0x40u);

  R(BANK + 0x0u) = 0xDEADBEEFu; // write accepted, no effect
  out[4] = R(BANK + 0x0u);

  u32 stable = 1u;
  for (u32 i = 0; i < 64u; ++i)
    if (R(BANK) != 0x4147414du)
      stable = 0u;
  out[5] = stable;

  out[6] = 0xC0FFEE45u;
  for (;;)
    __asm__ volatile("ebreak");
}
