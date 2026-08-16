// SRAM-only CPU-visible LBU/LHU oracle for the exact read-gated bank16.
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define R(a) (*(volatile u32 *)(a))

#define LOAD_W(dst, base) __asm__ volatile("lw %0, 0(%1)" : "=r"(dst) : "r"(base) : "memory")
#define LOAD_BU0(dst, base) __asm__ volatile("lbu %0, 0(%1)" : "=r"(dst) : "r"(base) : "memory")
#define LOAD_BU1(dst, base) __asm__ volatile("lbu %0, 1(%1)" : "=r"(dst) : "r"(base) : "memory")
#define LOAD_BU2(dst, base) __asm__ volatile("lbu %0, 2(%1)" : "=r"(dst) : "r"(base) : "memory")
#define LOAD_BU3(dst, base) __asm__ volatile("lbu %0, 3(%1)" : "=r"(dst) : "r"(base) : "memory")
#define LOAD_HU0(dst, base) __asm__ volatile("lhu %0, 0(%1)" : "=r"(dst) : "r"(base) : "memory")
#define LOAD_HU2(dst, base) __asm__ volatile("lhu %0, 2(%1)" : "=r"(dst) : "r"(base) : "memory")

static __attribute__((always_inline)) inline void fence_bus(void) {
  __asm__ volatile("fence iorw, iorw" ::: "memory");
}
static __attribute__((always_inline)) inline void gpio_reset(u32 asserted) {
  R(0x40018000u + ((1u << 1) << 2)) = asserted ? (1u << 1) : 0u;
}

#define CHECK_LOADS(base, state) do { \
  u32 raw0, raw1, b0, b1, b2, b3, h0, h2; \
  LOAD_W(raw0, base); \
  LOAD_BU0(b0, base); LOAD_BU1(b1, base); \
  LOAD_BU2(b2, base); LOAD_BU3(b3, base); \
  LOAD_HU0(h0, base); LOAD_HU2(h2, base); \
  LOAD_W(raw1, base); \
  if ((raw0 & 0xffffu) != ((state) & 0xffffu)) ++fabric_word_errors; \
  if (b0 != ((state) & 0xffu) || b1 != (((state) >> 8) & 0xffu) || \
      h0 != ((state) & 0xffffu)) ++fabric_low_lane_errors; \
  if (b2 != ((raw0 >> 16) & 0xffu) || b3 != ((raw0 >> 24) & 0xffu) || \
      h2 != (raw0 >> 16)) ++fabric_upper_relation_errors; \
  if ((b0 | b1 | b2 | b3) & 0xffffff00u) ++fabric_zeroext_errors; \
  if ((h0 | h2) & 0xffff0000u) ++fabric_zeroext_errors; \
  if ((raw1 & 0xffffu) != ((state) & 0xffffu)) ++retention_errors; \
  if (raw1 != raw0) ++upper_stability_errors; \
  raw_upper_and &= raw0 >> 16; raw_upper_or |= raw0 >> 16; \
  if (observations == 0u) { \
    sample_raw = raw0; \
    sample_lbu = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24); \
    sample_lhu = h0 | (h2 << 16); \
  } \
  ++observations; \
} while (0)

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out = (volatile u32 *)0x20001000u;
  volatile u32 *cfg = (volatile u32 *)0x20002000u;
  volatile u32 *word = (volatile u32 *)0x60000000u;
  volatile u16 *half = (volatile u16 *)0x60000000u;
  volatile u8 *byte = (volatile u8 *)0x60000000u;
  volatile u32 *canary = (volatile u32 *)0x20001800u;
  u32 sram_value_errors = 0, sram_zeroext_errors = 0;
  u32 fabric_word_errors = 0, fabric_low_lane_errors = 0;
  u32 fabric_upper_relation_errors = 0, fabric_zeroext_errors = 0;
  u32 retention_errors = 0, upper_stability_errors = 0;
  u32 raw_upper_and = 0xffffu, raw_upper_or = 0, observations = 0;
  u32 sample_raw = 0, sample_lbu = 0, sample_lhu = 0;

  R(0x0300000cu) &= ~0x27u;
  R(0x03000060u) |= (1u << 0) | (1u << 8);
  R(0x03000030u) = 0u;
  R(0x40018420u) = 0u; R(0x40018400u) = (1u << 1);
  gpio_reset(1u); R(0x40010000u) = (1u << 6);
  for (u32 i = 0; i < 24986u; ++i) R(0x4001000cu) = cfg[i];
  for (volatile u32 i = 0; i < 256u; ++i) ;
  u32 stat = R(0x40010010u);
  gpio_reset(0u);
  for (volatile u32 i = 0; i < 256u; ++i) ;

  *canary = 0xa53c80f1u;
  u32 w, b0, b1, b2, b3, h0, h2;
  LOAD_W(w, canary); LOAD_BU0(b0, canary); LOAD_BU1(b1, canary);
  LOAD_BU2(b2, canary); LOAD_BU3(b3, canary);
  LOAD_HU0(h0, canary); LOAD_HU2(h2, canary);
  if (w != 0xa53c80f1u || b0 != 0xf1u || b1 != 0x80u ||
      b2 != 0x3cu || b3 != 0xa5u || h0 != 0x80f1u || h2 != 0xa53cu)
    ++sram_value_errors;
  if (((b0 | b1 | b2 | b3) & 0xffffff00u) ||
      ((h0 | h2) & 0xffff0000u)) ++sram_zeroext_errors;

  u32 x = 0x517cc1b7u;
  for (u32 n = 0; n < 32u; ++n) {
    u32 p;
    if (n < 8u) p = 0x8001u ^ (0x1111u * n);
    else if (n < 16u) p = 1u << (n - 8u);
    else if (n < 24u) p = 1u << (n - 8u);
    else { x ^= x << 13; x ^= x >> 17; x ^= x << 5; p = x & 0xffffu; }
    word[0] = p; fence_bus(); CHECK_LOADS(word, p);
    u32 q = (p ^ 0xa55au) & 0xffffu;
    half[0] = (u16)q; fence_bus(); CHECK_LOADS(word, q);
    u32 low = (q ^ 0x5au) & 0xffu;
    byte[0] = (u8)low; fence_bus();
    u32 state = (q & 0xff00u) | low; CHECK_LOADS(word, state);
    u32 high = ((q >> 8) ^ 0xa5u) & 0xffu;
    byte[1] = (u8)high; fence_bus();
    state = (high << 8) | low; CHECK_LOADS(word, state);
  }

  out[0] = stat; out[1] = sram_value_errors; out[2] = sram_zeroext_errors;
  out[3] = fabric_word_errors; out[4] = fabric_low_lane_errors;
  out[5] = fabric_upper_relation_errors; out[6] = fabric_zeroext_errors;
  out[7] = retention_errors; out[8] = upper_stability_errors;
  out[9] = 32u; out[10] = observations;
  out[11] = raw_upper_and; out[12] = raw_upper_or;
  out[13] = sample_raw; out[14] = sample_lbu; out[15] = sample_lhu;
  out[16] = 0xc0ffee18u;
  for (;;) __asm__ volatile("ebreak");
}
