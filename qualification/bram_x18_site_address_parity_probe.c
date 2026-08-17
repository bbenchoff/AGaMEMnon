// SRAM-only full-depth probe for one open-flow arbitrary-site BRAM image.
// Compile with OBSERVED_BIT=8, 16, or 24 to match the selected site top.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

#ifndef OBSERVED_BIT
#define OBSERVED_BIT 8
#endif

static inline __attribute__((always_inline)) u32 parity9(u32 value) {
  value ^= value >> 8;
  value ^= value >> 4;
  value ^= value >> 2;
  value ^= value >> 1;
  return value & 1u;
}

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  volatile u32 *bram = (volatile u32 *)0x60000000u;

  R(0x0300000cu) &= ~0x27u;
  R(0x03000060u) |= (1u << 0) | (1u << 8);
  R(0x03000030u) = 0u;

  R(0x40010000u) = (1u << 6);
  for (u32 i = 0; i < 24986u; ++i)
    R(0x4001000cu) = cfg[i];
  u32 status = 0u, config_wait = 0u;
  for (; config_wait < 4096u; ++config_wait) {
    status = R(0x40010010u);
    if (status == 0x000f0002u)
      break;
  }

  if (status != 0x000f0002u) {
    out[0] = status;
    out[1] = config_wait;
    out[2] = 0xbadfcbu;
    out[13] = 0xc0ffee07u;
    for (;;)
      __asm__ volatile("ebreak");
  }

  u32 first_errors = 0u, settled_errors = 0u, upper_half_errors = 0u;
  u32 first_bad_address = 0xffffffffu, first_bad_value = 0u;
  u32 observed_ones = 0u, expected_ones = 0u;
  u32 power_of_two_observed = 0u;
  for (u32 address = 0; address < 512u; ++address) {
    u32 expected = parity9(address);
    u32 first_word = bram[address];
    u32 settled_word = bram[address];
    u32 first = (first_word >> OBSERVED_BIT) & 1u;
    u32 settled = (settled_word >> OBSERVED_BIT) & 1u;
    if (first != expected)
      ++first_errors;
    if (settled != expected) {
      ++settled_errors;
      if (first_bad_address == 0xffffffffu) {
        first_bad_address = address;
        first_bad_value = settled_word;
      }
    }
    if (address >= 256u && settled != expected)
      ++upper_half_errors;
    observed_ones += settled;
    expected_ones += expected;
    if (address != 0u && (address & (address - 1u)) == 0u && settled)
      power_of_two_observed |= address;
  }

  out[0] = status;
  out[1] = first_errors;
  out[2] = settled_errors;
  out[3] = upper_half_errors;
  out[4] = first_bad_address;
  out[5] = first_bad_value;
  out[6] = observed_ones;
  out[7] = expected_ones;
  out[8] = OBSERVED_BIT;
  out[9] = (bram[0] >> OBSERVED_BIT) & 1u;
  out[10] = (bram[256] >> OBSERVED_BIT) & 1u;
  out[11] = config_wait;
  out[12] = power_of_two_observed;
  out[13] = 0xc0ffee07u;
  for (;;)
    __asm__ volatile("ebreak");
}
