// SRAM-only hardware oracle for mcu_ahb_retained1_external_feedback.v.
// HRDATA0 is retained state and HRDATA1 is its external feedback witness.
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
  u32 disagreement_errors = 0, patterns = 0;
  u32 immediate_high = 0, poison_high = 0, repeat_high = 0;

  R(0x0300000cu) &= ~0x27u;
  R(0x03000060u) |= (1u << 0) | (1u << 8); // FCB + GPIO4 clocks
  R(0x03000030u) = 0u;
  R(0x40018420u) = 0u;                    // GPIO4 software mode
  R(0x40018400u) = (1u << 1);             // GPIO4.1 output
  gpio_reset(1u);

  R(0x40010000u) = (1u << 6);
  for (u32 i = 0; i < 24986u; ++i)
    R(0x4001000cu) = cfg[i];
  for (volatile u32 i = 0; i < 256u; ++i) ;

  u32 stat = R(0x40010010u);
  u32 reset_initial = bank[0] & 3u;
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;

  for (u32 n = 0; n < 128u; ++n) {
    u32 value = ((n * 73u) ^ (n >> 1)) & 1u;
    bank[0] = value;

    u32 got = bank[0] & 3u;
    immediate_high += got & 1u;
    if ((got & 1u) != value) ++immediate_errors;
    if (((got >> 1) ^ got) & 1u) ++disagreement_errors;

    // This changes hard HWDATA through unrelated SRAM traffic.  The posted
    // capture control follows the poison; a genuinely held bit must not.
    churn_sram((n << 24) ^ (value ? 0xa5a55a5au : 0x5a5aa5a5u));
    got = bank[0] & 3u;
    poison_high += got & 1u;
    if ((got & 1u) != value) ++poison_errors;
    if (((got >> 1) ^ got) & 1u) ++disagreement_errors;

    got = bank[0] & 3u;
    repeat_high += got & 1u;
    if ((got & 1u) != value) ++repeat_errors;
    if (((got >> 1) ^ got) & 1u) ++disagreement_errors;
    ++patterns;
  }

  bank[0] = 1u;
  gpio_reset(1u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_asserted = bank[0] & 3u;
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_released = bank[0] & 3u;

  out[0] = stat;
  out[1] = patterns;
  out[2] = immediate_errors;
  out[3] = poison_errors;
  out[4] = repeat_errors;
  out[5] = disagreement_errors;
  out[6] = immediate_high;
  out[7] = poison_high;
  out[8] = repeat_high;
  out[9] = reset_initial;
  out[10] = reset_asserted;
  out[11] = reset_released;
  out[12] = 0xc0ffee01u;
  for (;;)
    __asm__ volatile("ebreak");
}
