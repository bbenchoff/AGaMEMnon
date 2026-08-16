// SRAM-only retention oracle for the waited external-feedback 16-bit bank.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

static void gpio_reset(u32 asserted) {
  R(0x40018000u + ((1u << 1) << 2)) = asserted ? (1u << 1) : 0u;
}

static void churn_sram(u32 seed) {
  volatile u32 *poison = (volatile u32 *)0x20001800u;
  for (u32 i = 0; i < 64u; ++i) {
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    poison[i & 15u] = seed;
  }
}

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  volatile u32 *bank = (volatile u32 *)0x60000000u;
  u32 immediate_errors = 0, poison_errors = 0, repeat_errors = 0;
  u32 upper_observations = 0, patterns = 0;

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
  u32 reset_initial = bank[0] & 0xffffu;
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

    bank[0] = p;
    u32 got = bank[0];
    if ((got & 0xffffu) != p) ++immediate_errors;
    if (got >> 16) ++upper_observations;

    churn_sram((~p << 16) | (p ^ 0xffffu));
    got = bank[0];
    if ((got & 0xffffu) != p) ++poison_errors;
    if (got >> 16) ++upper_observations;
    got = bank[0];
    if ((got & 0xffffu) != p) ++repeat_errors;
    if (got >> 16) ++upper_observations;
    ++patterns;
  }

  bank[0] = 0xa55au;
  gpio_reset(1u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_asserted = bank[0] & 0xffffu;
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_released = bank[0] & 0xffffu;

  out[0] = stat;
  out[1] = patterns;
  out[2] = immediate_errors;
  out[3] = poison_errors;
  out[4] = repeat_errors;
  out[5] = upper_observations;
  out[6] = reset_initial;
  out[7] = reset_asserted;
  out[8] = reset_released;
  out[9] = 0xc0ffee16u;
  for (;;)
    __asm__ volatile("ebreak");
}
