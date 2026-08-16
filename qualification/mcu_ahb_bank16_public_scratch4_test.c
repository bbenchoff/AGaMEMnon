// SRAM-only oracle for the exact 16-bit public-scratch-shaped register at +4.
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define R(a) (*(volatile u32 *)(a))

#define DEF_LOAD(name, op, off) \
static __attribute__((always_inline)) inline u32 name(volatile void *base) { \
  u32 value; __asm__ volatile(op " %0, " #off "(%1)" : "=r"(value) : "r"(base) : "memory"); return value; \
}
DEF_LOAD(lw0, "lw", 0) DEF_LOAD(lw4, "lw", 4)
DEF_LOAD(lw8, "lw", 8) DEF_LOAD(lwc, "lw", 12)
DEF_LOAD(lbu0, "lbu", 0) DEF_LOAD(lbu1, "lbu", 1)
DEF_LOAD(lbu2, "lbu", 2) DEF_LOAD(lbu3, "lbu", 3)
DEF_LOAD(lbu4, "lbu", 4) DEF_LOAD(lbu5, "lbu", 5)
DEF_LOAD(lbu6, "lbu", 6) DEF_LOAD(lbu7, "lbu", 7)
DEF_LOAD(lbu8, "lbu", 8) DEF_LOAD(lbu9, "lbu", 9)
DEF_LOAD(lbuc, "lbu", 12) DEF_LOAD(lbud, "lbu", 13)
DEF_LOAD(lhu0, "lhu", 0) DEF_LOAD(lhu4, "lhu", 4)
DEF_LOAD(lhu2, "lhu", 2) DEF_LOAD(lhu6, "lhu", 6)
DEF_LOAD(lhu8, "lhu", 8) DEF_LOAD(lhuc, "lhu", 12)

static __attribute__((always_inline)) inline void fence_bus(void) {
  __asm__ volatile("fence iorw, iorw" ::: "memory");
}
static __attribute__((always_inline)) inline void gpio_reset(u32 asserted) {
  R(0x40018000u + ((1u << 1) << 2)) = asserted ? (1u << 1) : 0u;
}

#define CHECK_READS(base, state) do { \
  u32 _r0 = lw0(base), _r4 = lw4(base), _r8 = lw8(base), _rc = lwc(base); \
  if ((_r0 & 0xffffu) || ((_r4 & 0xffffu) != ((state) & 0xffffu)) || \
      (_r8 & 0xffffu) || (_rc & 0xffffu)) ++read_decode_errors; \
  (void)lw0(base); if ((lw4(base) & 0xffffu) != ((state) & 0xffffu)) ++preservation_errors; \
  (void)lw8(base); if ((lw4(base) & 0xffffu) != ((state) & 0xffffu)) ++preservation_errors; \
  (void)lwc(base); if ((lw4(base) & 0xffffu) != ((state) & 0xffffu)) ++preservation_errors; \
  u32 _b4=lbu4(base), _b5=lbu5(base), _b6=lbu6(base), _b7=lbu7(base); \
  u32 _h4=lhu4(base), _h6=lhu6(base), _raw2=lw4(base); \
  if (_b4 != ((state)&0xffu) || _b5 != (((state)>>8)&0xffu) || _h4 != ((state)&0xffffu)) ++subword_low_errors; \
  if (_b6 != ((_r4>>16)&0xffu) || _b7 != ((_r4>>24)&0xffu) || _h6 != (_r4>>16)) ++subword_upper_relation_errors; \
  if ((_b4|_b5|_b6|_b7)&0xffffff00u) ++zeroext_errors; \
  if ((_h4|_h6)&0xffff0000u) ++zeroext_errors; \
  if (lbu0(base) || lbu1(base) || lhu0(base) || lbu8(base) || lbu9(base) || lhu8(base) || lbuc(base) || lbud(base) || lhuc(base)) ++subword_zero_decode_errors; \
  if ((_raw2 & 0xffffu) != ((state)&0xffffu)) ++retention_errors; \
  if (_raw2 != _r4) ++upper_stability_errors; \
  raw_upper_and &= _r4>>16; raw_upper_or |= _r4>>16; \
  if (!observations) { sample_raw=_r4; sample_lbu=_b4|(_b5<<8)|(_b6<<16)|(_b7<<24); sample_lhu=_h4|(_h6<<16); } \
  ++observations; \
} while (0)

void __attribute__((section(".text.start"))) _start(void) {
  volatile u32 *out=(volatile u32 *)0x20001000u;
  volatile u32 *cfg=(volatile u32 *)0x20002000u;
  volatile u32 *word=(volatile u32 *)0x60000000u;
  volatile u16 *half=(volatile u16 *)0x60000000u;
  volatile u8 *byte=(volatile u8 *)0x60000000u;
  volatile u32 *poison=(volatile u32 *)0x20001800u;
  u32 word_errors=0, half_errors=0, low_errors=0, high_errors=0;
  u32 reject_byte_errors=0, reject_half_errors=0, reject_word_errors=0;
  u32 read_decode_errors=0, preservation_errors=0, subword_low_errors=0;
  u32 subword_upper_relation_errors=0, subword_zero_decode_errors=0;
  u32 zeroext_errors=0, retention_errors=0, upper_stability_errors=0, reset_errors=0;
  u32 raw_upper_and=0xffffu, raw_upper_or=0, observations=0;
  u32 sample_raw=0, sample_lbu=0, sample_lhu=0;

  R(0x0300000cu)&=~0x27u; R(0x03000060u)|=(1u<<0)|(1u<<8);
  R(0x03000030u)=0; R(0x40018420u)=0; R(0x40018400u)=(1u<<1);
  gpio_reset(1); R(0x40010000u)=(1u<<6);
  for(u32 i=0;i<24986u;++i) R(0x4001000cu)=cfg[i];
  for(volatile u32 i=0;i<256u;++i); u32 stat=R(0x40010010u);
  gpio_reset(0); for(volatile u32 i=0;i<256u;++i);

  // Independent little-endian/zero-extension control in ordinary SRAM.
  poison[0]=0xa53c80f1u;
  if(lw0(poison)!=0xa53c80f1u || lbu0(poison)!=0xf1u || lbu1(poison)!=0x80u ||
     lbu2(poison)!=0x3cu || lbu3(poison)!=0xa5u ||
     lhu0(poison)!=0x80f1u || lhu2(poison)!=0xa53cu) ++zeroext_errors;

  u32 x=0x41c64e6du;
  for(u32 n=0;n<32u;++n) {
    u32 p;
    if(n<8u) p=0x8001u^(0x1111u*n);
    else if(n<16u) p=1u<<(n-8u);
    else if(n<24u) p=1u<<(n-8u);
    else { x^=x<<13; x^=x>>17; x^=x<<5; p=x&0xffffu; }

    word[1]=p; fence_bus(); if((lw4(word)&0xffffu)!=p) ++word_errors; CHECK_READS(word,p);
    u32 q=(p^0xa55au)&0xffffu;
    half[2]=(u16)q; fence_bus(); if((lw4(word)&0xffffu)!=q) ++half_errors; CHECK_READS(word,q);
    u32 low=(q^0x5au)&0xffu, state=(q&0xff00u)|low;
    byte[4]=(u8)low; fence_bus(); if((lw4(word)&0xffffu)!=state) ++low_errors; CHECK_READS(word,state);
    u32 high=((q>>8)^0xa5u)&0xffu; state=(high<<8)|low;
    byte[5]=(u8)high; fence_bus(); if((lw4(word)&0xffffu)!=state) ++high_errors; CHECK_READS(word,state);

    byte[0]=0x31u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_byte_errors;
    byte[6]=0x62u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_byte_errors;
    byte[8]=0x83u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_byte_errors;
    byte[12]=0xc4u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_byte_errors;
    half[0]=0x1010u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_half_errors;
    half[3]=0x3636u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_half_errors;
    half[4]=0x4848u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_half_errors;
    half[6]=0x6c6cu; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_half_errors;
    word[0]=0x01020304u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_word_errors;
    word[2]=0x18273645u; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_word_errors;
    word[3]=0xcafebabeu; fence_bus(); if((lw4(word)&0xffffu)!=state) ++reject_word_errors;
    CHECK_READS(word,state);
    for(u32 i=0;i<16u;++i) poison[i]=(state<<16)^i^x;
    if((lw4(word)&0xffffu)!=state) ++retention_errors;
  }

  word[1]=0xa55au; gpio_reset(1); for(volatile u32 i=0;i<256u;++i);
  if((lw4(word)&0xffffu)!=0u) ++reset_errors;
  word[1]=0x5aa5u; fence_bus(); if((lw4(word)&0xffffu)!=0u) ++reset_errors;
  gpio_reset(0); for(volatile u32 i=0;i<256u;++i);
  if((lw0(word)&0xffffu)||(lw4(word)&0xffffu)||(lw8(word)&0xffffu)||(lwc(word)&0xffffu)) ++reset_errors;

  out[0]=stat; out[1]=word_errors; out[2]=half_errors; out[3]=low_errors; out[4]=high_errors;
  out[5]=reject_byte_errors; out[6]=reject_half_errors; out[7]=reject_word_errors;
  out[8]=read_decode_errors; out[9]=preservation_errors; out[10]=subword_low_errors;
  out[11]=subword_upper_relation_errors; out[12]=subword_zero_decode_errors;
  out[13]=zeroext_errors; out[14]=retention_errors; out[15]=upper_stability_errors;
  out[16]=reset_errors; out[17]=32u; out[18]=observations;
  out[19]=raw_upper_and; out[20]=raw_upper_or; out[21]=sample_raw;
  out[22]=sample_lbu; out[23]=sample_lhu; out[24]=0xc0ffee24u;
  for(;;) __asm__ volatile("ebreak");
}
