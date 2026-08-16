// SRAM-only oracle for the exact qualified 16-bit word/byte composition.
// Halfword behavior is deliberately outside this experiment.
typedef unsigned int u32;
typedef unsigned char u8;
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
  volatile u32 *word = (volatile u32 *)0x60000000u;
  volatile u8 *byte = (volatile u8 *)0x60000000u;
  u32 word_errors = 0, low_errors = 0, high_errors = 0;
  u32 upper_byte_mutations = 0, foreign_mutations = 0, overwrite_errors = 0;

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
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    u32 p = x & 0xffffu;

    // A word transfer must commit both independent byte tokens.
    word[0] = p;
    fence_bus();
    if ((word[0] & 0xffffu) != p) ++word_errors;

    // Byte +0 changes only the low byte.
    u32 low = (p ^ 0x5au) & 0xffu;
    u32 expect = (p & 0xff00u) | low;
    byte[0] = (u8)low;
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++low_errors;

    // Byte +1 changes only the high byte.
    u32 high = ((p >> 8) ^ 0xa5u) & 0xffu;
    expect = (high << 8) | low;
    byte[1] = (u8)high;
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++high_errors;

    // Bytes +2/+3 are outside this 16-bit word and must preserve it.
    byte[2] = (u8)(low ^ 0x33u);
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++upper_byte_mutations;
    byte[3] = (u8)(high ^ 0xccu);
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++upper_byte_mutations;

    // Aligned words +4/+8/+c must not commit into word zero.
    word[1] = p ^ 0x1357u;
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_mutations;
    word[2] = p ^ 0x2468u;
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_mutations;
    word[3] = p ^ 0xdeadu;
    fence_bus();
    if ((word[0] & 0xffffu) != expect) ++foreign_mutations;

    u32 q = (~p) & 0xffffu;
    word[0] = q;
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
  out[1] = word_errors;
  out[2] = low_errors;
  out[3] = high_errors;
  out[4] = upper_byte_mutations;
  out[5] = foreign_mutations;
  out[6] = overwrite_errors;
  out[7] = reset_initial;
  out[8] = reset_asserted;
  out[9] = reset_released;
  out[10] = 100u;
  out[11] = 0xc0ffee16u;
  for (;;)
    __asm__ volatile("ebreak");
}
