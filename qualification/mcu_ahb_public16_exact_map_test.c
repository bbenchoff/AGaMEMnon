// SRAM-only oracle for the exact L48 ID8/scratch16/counter3/W1C1 map.
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define R(a) (*(volatile u32 *)(a))

static inline void fence_bus(void) {
  __asm__ volatile("fence iorw, iorw" ::: "memory");
}
static inline void gpio_reset(u32 asserted) {
  R(0x40018000u + ((1u << 1) << 2)) = asserted ? (1u << 1) : 0u;
}

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out=(volatile u32 *)0x20001000u;
  volatile u32 *cfg=(volatile u32 *)0x20002000u;
  volatile u32 *word=(volatile u32 *)0x60000000u;
  volatile u16 *half=(volatile u16 *)0x60000000u;
  volatile u8 *byte=(volatile u8 *)0x60000000u;
  u32 id_errors=0, scratch_word_errors=0, scratch_half_errors=0;
  u32 scratch_byte_errors=0, counter_range_errors=0;
  u32 counter_coverage_errors=0, status_errors=0, foreign_errors=0;
  u32 reset_errors=0, zeroext_errors=0, seen=0, observations=0;

  R(0x0300000cu)&=~0x27u; R(0x03000060u)|=(1u<<0)|(1u<<8);
  R(0x03000030u)=0; R(0x40018420u)=0; R(0x40018400u)=(1u<<1);
  gpio_reset(1); R(0x40010000u)=(1u<<6);
  for(u32 i=0;i<24986u;++i) R(0x4001000cu)=cfg[i];
  for(volatile u32 i=0;i<256u;++i); u32 stat=R(0x40010010u);

  // Reset-held class contract and blocked writes.
  if((word[0]&0xffffu)!=0x4du || (word[1]&0xffffu)!=0u ||
     (word[2]&0xffffu)!=0u || (word[3]&0xffffu)!=0u)
    ++reset_errors;
  word[1]=0xa55au; word[3]=2u; fence_bus();
  if((word[1]&0xffffu)!=0u || (word[2]&0xffffu)!=0u ||
     (word[3]&0xffffu)!=0u) ++reset_errors;
  gpio_reset(0); for(volatile u32 i=0;i<256u;++i);

  for(u32 i=0;i<64u;++i) {
    u32 id=word[0];
    if((id&0xffffu)!=0x4du || byte[0]!=0x4du || byte[1]!=0u ||
       half[0]!=0x4du) ++id_errors;
    if((byte[0]|byte[1]|half[0])&0xffff0000u) ++zeroext_errors;
  }

  static const u16 patterns[8]={0x0000,0xffff,0x8001,0x5aa5,
                                0xa55a,0x00ff,0xff00,0x369c};
  for(u32 i=0;i<8u;++i) {
    u16 p=patterns[i]; word[1]=0xbeef0000u|p; fence_bus();
    if((word[1]&0xffffu)!=p) scratch_word_errors|=1u;
    if(half[2]!=p) scratch_word_errors|=2u;
    if(byte[4]!=(p&0xffu)) scratch_word_errors|=4u;
    if(byte[5]!=(p>>8)) scratch_word_errors|=8u;
    u16 q=p^0x5aa5u; half[2]=q; fence_bus();
    if((word[1]&0xffffu)!=q) ++scratch_half_errors;
    byte[4]=(u8)(p^0x3cu); fence_bus();
    byte[5]=(u8)((p>>8)^0xc3u); fence_bus();
    u32 expect=((u32)((p>>8)^0xc3u)<<8)|(u8)(p^0x3cu);
    if((word[1]&0xffffu)!=expect) ++scratch_byte_errors;
    ++observations;
  }

  word[1]=0x6d93u; fence_bus();
  for(u32 i=0;i<512u;++i) {
    u32 c=word[2];
    if((c&0xffffu)&~7u) ++counter_range_errors;
    seen|=1u<<(c&7u);
    if((word[0]&0xffffu)!=0x4du || (word[1]&0xffffu)!=0x6d93u ||
       (word[3]&0xffffu)!=0u)
      ++foreign_errors;
    for(volatile u32 j=0;j<(i&7u);++j);
  }
  if(seen!=0xffu) ++counter_coverage_errors;
  if((word[3]&0xffffu)!=0u) status_errors|=1u;

  // ID/counter writes must not alter the qualified scratch or status.
  word[0]=0xffffffffu; half[0]=0x1234u; byte[1]=0x77u;
  word[2]=0xffffffffu; half[4]=0x5678u; byte[9]=0x88u;
  if((word[0]&0xffffu)!=0x4du || (word[1]&0xffffu)!=0x6d93u ||
     (word[3]&0xffffu)!=0u) ++foreign_errors;

  // Qualification W1C hook: bit1 sets, bit0 clears, and set wins.
  word[3]=0u; fence_bus(); for(u32 i=0;i<8u;++i) (void)word[3];
  if((word[3]&1u)!=0u) status_errors|=2u;
  word[3]=2u; fence_bus(); for(u32 i=0;i<8u;++i) (void)word[3];
  if((word[3]&1u)!=1u) status_errors|=4u;
  word[3]=0u; byte[13]=0x99u; half[7]=0xabcd; fence_bus();
  for(u32 i=0;i<8u;++i) (void)word[3];
  if((word[3]&1u)!=1u) status_errors|=8u;
  word[3]=1u; fence_bus(); for(u32 i=0;i<8u;++i) (void)word[3];
  if((word[3]&1u)!=0u) status_errors|=16u;
  word[2]=2u; fence_bus(); for(u32 i=0;i<8u;++i) (void)word[3];
  if((word[3]&1u)!=0u) status_errors|=32u;
  word[3]=2u; fence_bus(); for(u32 i=0;i<8u;++i) (void)word[3];
  if((word[3]&1u)!=1u) status_errors|=64u;
  word[3]=3u; fence_bus(); for(u32 i=0;i<8u;++i) (void)word[3];
  if((word[3]&1u)!=1u) status_errors|=128u;
  if((word[1]&0xffffu)!=0x6d93u) ++foreign_errors;

  gpio_reset(1); for(volatile u32 i=0;i<256u;++i);
  if((word[0]&0xffffu)!=0x4du || (word[1]&0xffffu)!=0u ||
     (word[2]&0xffffu)!=0u || (word[3]&0xffffu)!=0u)
    ++reset_errors;
  word[1]=0xffffu; fence_bus();
  if((word[1]&0xffffu)!=0u) ++reset_errors;

  out[0]=stat; out[1]=id_errors;
  out[2]=(scratch_word_errors<<16)|(scratch_half_errors<<8)|scratch_byte_errors;
  out[3]=counter_range_errors; out[4]=counter_coverage_errors;
  out[5]=status_errors; out[6]=foreign_errors; out[7]=reset_errors;
  out[8]=zeroext_errors; out[9]=seen; out[10]=observations;
  out[11]=word[0]&0xffffu; out[12]=word[1]&0xffffu;
  out[13]=word[2]&0xffffu; out[14]=word[3]&0xffffu;
  out[15]=0xc0ffee1au;
  for(;;) __asm__ volatile("ebreak");
}
