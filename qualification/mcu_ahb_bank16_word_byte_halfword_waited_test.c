// SRAM-only oracle for the exact qualified 16-bit word/byte/aligned-halfword composition.
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define R(a) (*(volatile u32 *)(a))

static __attribute__((always_inline)) inline void fence_bus(void) {
  __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static __attribute__((always_inline)) inline void gpio_reset(u32 asserted) {
  R(0x40018000u + ((1u << 1) << 2)) = asserted ? (1u << 1) : 0u;
}

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  volatile u32 *word = (volatile u32 *)0x60000000u;
  volatile u16 *half = (volatile u16 *)0x60000000u;
  volatile u8 *byte = (volatile u8 *)0x60000000u;
  u32 word_errors = 0, half_errors = 0, low_errors = 0, high_errors = 0;
  u32 upper_byte_mutations = 0, foreign_half_mutations = 0;
  u32 foreign_word_mutations = 0, overwrite_errors = 0;

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

  u32 x = 0x6d2b79f5u;
  for (u32 n = 0; n < 100u; ++n) {
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    u32 p = x & 0xffffu;
    word[0] = p;
    fence_bus();
    if ((word[0] & 0xffffu) != p) ++word_errors;

    // Aligned HSIZE=001 at +0 must commit both independent byte lanes.
    u32 q = (p ^ 0xa55au) & 0xffffu;
    half[0] = (u16)q;
    fence_bus();
    if ((word[0] & 0xffffu) != q) ++half_errors;

    u32 low = (q ^ 0x5au) & 0xffu;
    u32 expect = (q & 0xff00u) | low;
    byte[0] = (u8)low;
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++low_errors;
    u32 high = ((q >> 8) ^ 0xa5u) & 0xffu;
    expect = (high << 8) | low;
    byte[1] = (u8)high;
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++high_errors;

    byte[2] = (u8)(low ^ 0x33u); fence_bus();
    if ((word[0] & 0xffffu) != expect) ++upper_byte_mutations;
    byte[3] = (u8)(high ^ 0xccu); fence_bus();
    if ((word[0] & 0xffffu) != expect) ++upper_byte_mutations;

    // +2 is the other aligned halfword within the 32-bit bus word; +4/+8/+c
    // exercise the retained HADDR[3:2] write reject.
    half[1] = (u16)(q ^ 0x1111u); fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_half_mutations;
    half[2] = (u16)(q ^ 0x2222u); fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_half_mutations;
    half[4] = (u16)(q ^ 0x4444u); fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_half_mutations;
    half[6] = (u16)(q ^ 0x6666u); fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_half_mutations;

    word[1] = p ^ 0x1357u; fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_word_mutations;
    word[2] = p ^ 0x2468u; fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_word_mutations;
    word[3] = p ^ 0xdeadu; fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_word_mutations;

    q = (~p) & 0xffffu;
    half[0] = (u16)q;
    fence_bus();
    if ((word[0] & 0xffffu) != q) ++overwrite_errors;
  }

  word[0] = 0xa55au;
  gpio_reset(1u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_asserted = word[0] & 0xffffu;
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 reset_released = word[0] & 0xffffu;

  out[0] = stat;
  out[1] = word_errors; out[2] = half_errors;
  out[3] = low_errors; out[4] = high_errors;
  out[5] = upper_byte_mutations; out[6] = foreign_half_mutations;
  out[7] = foreign_word_mutations; out[8] = overwrite_errors;
  out[9] = reset_initial; out[10] = reset_asserted; out[11] = reset_released;
  out[12] = 100u; out[13] = 0xc0ffee16u;
  for (;;) __asm__ volatile("ebreak");
}
