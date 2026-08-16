// SRAM-only full-depth address probe for the four-site vendor BRAM oracle.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

static inline __attribute__((always_inline)) u32 lane(u32 address, u32 marker) {
  u32 high_fold = (address & 0x100u) ? 0xa5u : 0u;
  return ((address & 0xffu) ^ high_fold ^ marker) & 0xffu;
}

static inline __attribute__((always_inline)) u32 expected_word(u32 address) {
  return lane(address, 0x11u)
      | (lane(address, 0x22u) << 8)
      | (lane(address, 0x44u) << 16)
      | (lane(address, 0x88u) << 24);
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
    out[10] = 0xc0ffee05u;
    for (;;)
      __asm__ volatile("ebreak");
  }

  u32 first_errors = 0, settled_errors = 0, upper_half_errors = 0;
  u32 first_bad_address = 0xffffffffu, first_bad_value = 0u;
  u32 observed_xor = 0u, expected_xor = 0u;
  for (u32 address = 0; address < 512u; ++address) {
    u32 expected = expected_word(address);
    u32 first = bram[address];
    u32 settled = bram[address];
    if (first != expected)
      ++first_errors;
    if (settled != expected) {
      ++settled_errors;
      if (first_bad_address == 0xffffffffu) {
        first_bad_address = address;
        first_bad_value = settled;
      }
    }
    if (address >= 256u && settled != expected)
      ++upper_half_errors;
    observed_xor ^= settled;
    expected_xor ^= expected;
  }

  out[0] = status;
  out[1] = first_errors;
  out[2] = settled_errors;
  out[3] = upper_half_errors;
  out[4] = first_bad_address;
  out[5] = first_bad_value;
  out[6] = observed_xor;
  out[7] = expected_xor;
  out[8] = expected_word(0u);
  out[9] = expected_word(256u);
  out[10] = 0xc0ffee05u;
  out[11] = config_wait;
  for (;;)
    __asm__ volatile("ebreak");
}
