// Silicon oracle for write-side isolation of held word +0 from +4/+8/+c.
// Reads at all four offsets intentionally alias the same retained state.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

static void gpio_reset(u32 asserted) {
  R(0x40018000u + ((1u << 1) << 2)) = asserted ? (1u << 1) : 0u;
}
static void fence_bus(void) {
  __asm__ volatile("fence iorw, iorw" ::: "memory");
}

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  volatile u32 *base = (volatile u32 *)0x60000000u;
  u32 immediate_errors = 0, foreign_write_errors = 0;
  u32 foreign_alias_errors = 0, overwrite_errors = 0;

  R(0x0300000cu) &= ~0x27u;
  R(0x03000060u) |= (1u << 0) | (1u << 8);
  R(0x03000030u) = 0u;
  R(0x40018420u) = 0u;
  R(0x40018400u) = (1u << 1);
  gpio_reset(1u);

  R(0x40010000u) = (1u << 6);
  for (u32 i = 0; i < 24986u; ++i)
    R(0x4001000cu) = cfg[i];
  for (volatile u32 i = 0; i < 256u; ++i) ;

  u32 stat = R(0x40010010u);
  u32 reset_initial = base[0] & 0xffffu;
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;

  u32 x = 0x6d2b79f5u;
  for (u32 n = 0; n < 100u; ++n) {
    u32 p;
    if (n == 0u) p = 0x0000u;
    else if (n == 1u) p = 0xffffu;
    else if (n == 2u) p = 0xaaaau;
    else if (n == 3u) p = 0x5555u;
    else if (n < 20u) p = 1u << (n - 4u);
    else if (n < 36u) p = 0xffffu ^ (1u << (n - 20u));
    else {
      x ^= x << 13;
      x ^= x >> 17;
      x ^= x << 5;
      p = x & 0xffffu;
    }

    base[0] = p;
    fence_bus();
    if ((base[0] & 0xffffu) != p) ++immediate_errors;

    // +4, +8 and +c span HADDR[3:2]. None may update the +0 state.
    base[1] = (p ^ 0x1357u) | 0xa5000000u;
    fence_bus();
    if ((base[0] & 0xffffu) != p) ++foreign_write_errors;
    base[2] = (p ^ 0x2468u) | 0x5a000000u;
    fence_bus();
    if ((base[0] & 0xffffu) != p) ++foreign_write_errors;
    base[3] = (p ^ 0xdeadbeefu);
    fence_bus();
    if ((base[0] & 0xffffu) != p) ++foreign_write_errors;

    // Reads are not decoded in this staged candidate and must still alias.
    // Recording this explicitly prevents a write-only result becoming a
    // broader address-isolation claim.
    if ((base[1] & 0xffffu) != p ||
        (base[2] & 0xffffu) != p ||
        (base[3] & 0xffffu) != p)
      ++foreign_alias_errors;

    u32 q = (p ^ 0xffffu) & 0xffffu;
    base[0] = q;
    fence_bus();
    if ((base[0] & 0xffffu) != q) ++overwrite_errors;
  }

  base[0] = 0xa55au;
  gpio_reset(1u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_asserted = base[0] & 0xffffu;
  base[1] = 0xffffu;
  base[2] = 0xffffu;
  base[3] = 0xffffu;
  base[0] = 0xffffu;
  fence_bus();
  u32 reset_blocked = base[0] & 0xffffu;

  out[0] = stat;
  out[1] = immediate_errors;
  out[2] = foreign_write_errors;
  out[3] = foreign_alias_errors;
  out[4] = overwrite_errors;
  out[5] = reset_initial;
  out[6] = reset_asserted;
  out[7] = reset_blocked;
  out[8] = 100u;
  out[9] = 0xc0ffee16u;
  for (;;)
    __asm__ volatile("ebreak");
}
