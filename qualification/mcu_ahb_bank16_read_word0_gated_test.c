// SRAM-only discriminator for exact bank16 read-address output gating.
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define R(a) (*(volatile u32 *)(a))

#ifndef READ_MASK
#define READ_MASK 0x1u
#endif

static __attribute__((always_inline)) inline void fence_bus(void) {
  __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static __attribute__((always_inline)) inline void gpio_reset(u32 asserted) {
  R(0x40018000u + ((1u << 1) << 2)) = asserted ? (1u << 1) : 0u;
}

#define EXPECT(index, state) \
  (((READ_MASK >> (index)) & 1u) ? ((state) & 0xffffu) : 0u)

#define CHECK_SNAPSHOT(state) do { \
  u32 _r0 = word[0] & 0xffffu; \
  u32 _r1 = word[1] & 0xffffu; \
  u32 _r2 = word[2] & 0xffffu; \
  u32 _r3 = word[3] & 0xffffu; \
  if (_r0 != EXPECT(0, state)) ++read0_errors; \
  if (_r1 != EXPECT(1, state)) ++foreign_read_errors; \
  if (_r2 != EXPECT(2, state)) ++foreign_read_errors; \
  if (_r3 != EXPECT(3, state)) ++foreign_read_errors; \
} while (0)

#define CHECK_RETENTION(state) do { \
  u32 _foreign = word[1] & 0xffffu; \
  if (_foreign != EXPECT(1, state)) ++foreign_read_errors; \
  if ((word[0] & 0xffffu) != EXPECT(0, state)) ++preservation_errors; \
  _foreign = word[2] & 0xffffu; \
  if (_foreign != EXPECT(2, state)) ++foreign_read_errors; \
  if ((word[0] & 0xffffu) != EXPECT(0, state)) ++preservation_errors; \
  _foreign = word[3] & 0xffffu; \
  if (_foreign != EXPECT(3, state)) ++foreign_read_errors; \
  if ((word[0] & 0xffffu) != EXPECT(0, state)) ++preservation_errors; \
} while (0)

#define CHECK_PHASE_PAIRS(state) do { \
  u32 _a, _b; \
  _a = word[0] & 0xffffu; _b = word[1] & 0xffffu; \
  if (_a != EXPECT(0, state) || _b != EXPECT(1, state)) ++phase_pair_errors; \
  _a = word[1] & 0xffffu; _b = word[0] & 0xffffu; \
  if (_a != EXPECT(1, state) || _b != EXPECT(0, state)) ++phase_pair_errors; \
  _a = word[0] & 0xffffu; _b = word[2] & 0xffffu; \
  if (_a != EXPECT(0, state) || _b != EXPECT(2, state)) ++phase_pair_errors; \
  _a = word[2] & 0xffffu; _b = word[0] & 0xffffu; \
  if (_a != EXPECT(2, state) || _b != EXPECT(0, state)) ++phase_pair_errors; \
  _a = word[0] & 0xffffu; _b = word[3] & 0xffffu; \
  if (_a != EXPECT(0, state) || _b != EXPECT(3, state)) ++phase_pair_errors; \
  _a = word[3] & 0xffffu; _b = word[0] & 0xffffu; \
  if (_a != EXPECT(3, state) || _b != EXPECT(0, state)) ++phase_pair_errors; \
  _a = word[1] & 0xffffu; _b = word[2] & 0xffffu; \
  if (_a != EXPECT(1, state) || _b != EXPECT(2, state)) ++phase_pair_errors; \
  _a = word[2] & 0xffffu; _b = word[3] & 0xffffu; \
  if (_a != EXPECT(2, state) || _b != EXPECT(3, state)) ++phase_pair_errors; \
  _a = word[3] & 0xffffu; _b = word[1] & 0xffffu; \
  if (_a != EXPECT(3, state) || _b != EXPECT(1, state)) ++phase_pair_errors; \
} while (0)

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  volatile u32 *word = (volatile u32 *)0x60000000u;
  volatile u16 *half = (volatile u16 *)0x60000000u;
  volatile u8 *byte = (volatile u8 *)0x60000000u;
  u32 read0_errors = 0, foreign_read_errors = 0, preservation_errors = 0;
  u32 phase_pair_errors = 0, half_errors = 0, low_errors = 0, high_errors = 0;
  u32 rejected_write_mutations = 0, overwrite_errors = 0, reset_errors = 0;

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
  u32 reset_initial = word[0] & 0xffffu;
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;

  u32 x = 0x5d31a8e7u;
  for (u32 n = 0; n < 64u; ++n) {
    u32 state;
    if (n < 16u)
      state = 1u << n;
    else if (n < 32u)
      state = (~(1u << (n - 16u))) & 0xffffu;
    else if (n == 32u)
      state = 0xa55au;
    else if (n == 33u)
      state = 0x5aa5u;
    else {
      x ^= x << 13; x ^= x >> 17; x ^= x << 5;
      state = x & 0xffffu;
      if (state == 0u) state = 0x6d2bu;
    }

    word[0] = state;
    fence_bus();
    CHECK_SNAPSHOT(state);
    CHECK_RETENTION(state);
    CHECK_PHASE_PAIRS(state);

    u32 q = (state ^ 0xa55au) & 0xffffu;
    half[0] = (u16)q;
    fence_bus();
    state = q;
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++half_errors;
    CHECK_SNAPSHOT(state);
    CHECK_RETENTION(state);

    u32 low = (q ^ 0x5au) & 0xffu;
    byte[0] = (u8)low;
    fence_bus();
    state = (state & 0xff00u) | low;
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++low_errors;
    CHECK_SNAPSHOT(state);
    CHECK_RETENTION(state);

    u32 high = ((q >> 8) ^ 0xa5u) & 0xffu;
    byte[1] = (u8)high;
    fence_bus();
    state = (high << 8) | low;
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++high_errors;
    CHECK_SNAPSHOT(state);
    CHECK_RETENTION(state);

    byte[2] = (u8)(low ^ 0x33u); fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    byte[3] = (u8)(high ^ 0xccu); fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    half[1] = (u16)(q ^ 0x1111u); fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    half[2] = (u16)(q ^ 0x2222u); fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    half[4] = (u16)(q ^ 0x4444u); fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    half[6] = (u16)(q ^ 0x6666u); fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    word[1] = state ^ 0x1357u; fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    word[2] = state ^ 0x2468u; fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    word[3] = state ^ 0xdeadu; fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++rejected_write_mutations;
    CHECK_SNAPSHOT(state);
    CHECK_RETENTION(state);

    state = (~state) & 0xffffu;
    half[0] = (u16)state;
    fence_bus();
    if ((word[0] & 0xffffu) != EXPECT(0, state)) ++overwrite_errors;
    CHECK_SNAPSHOT(state);
    CHECK_RETENTION(state);
  }

  word[0] = 0xa55au;
  gpio_reset(1u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_initial_vector[4] = {
    word[0] & 0xffffu, word[1] & 0xffffu,
    word[2] & 0xffffu, word[3] & 0xffffu,
  };
  for (u32 i = 0; i < 4u; ++i)
    if (reset_initial_vector[i] != 0u) ++reset_errors;
  u32 reset_asserted = reset_initial_vector[0];
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_released_vector[4] = {
    word[0] & 0xffffu, word[1] & 0xffffu,
    word[2] & 0xffffu, word[3] & 0xffffu,
  };
  for (u32 i = 0; i < 4u; ++i)
    if (reset_released_vector[i] != 0u) ++reset_errors;
  u32 reset_released = reset_released_vector[0];

  out[0] = stat;
  out[1] = read0_errors; out[2] = foreign_read_errors;
  out[3] = preservation_errors; out[4] = phase_pair_errors;
  out[5] = half_errors; out[6] = low_errors; out[7] = high_errors;
  out[8] = rejected_write_mutations; out[9] = overwrite_errors;
  out[10] = reset_errors; out[11] = reset_initial;
  out[12] = reset_asserted; out[13] = reset_released;
  out[14] = 64u; out[15] = READ_MASK; out[16] = 0xc0ffee17u;
  for (;;) __asm__ volatile("ebreak");
}
