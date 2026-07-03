// 4-bit MCU<->fabric loopback test (SRAM stub). Four independent bits, each dout = ~din:
//   din GPIO4_1 -> dout GPIO4_6 ; din GPIO4_3 -> dout GPIO4_4
//   din GPIO4_5 -> dout GPIO4_2 ; din GPIO4_7 -> dout GPIO4_0
// FCB_AutoConfigs the fabric from 0x20002000, sweeps all 16 (din) combos, reads (dout) after each.
// Results at 0x20001000 as (stat, {din_word,dout_word}x16, sentinel). SRAM-only.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
#define GP   0x40018000u
#define DAT(mask) R(GP + ((mask) << 2))         // Stellaris-style masked GPIO data
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x27u;                       // -> HSI clock
  R(0x03000060) |= (1u<<0)|(1u<<8);              // APB clk: FCB + GPIO4
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);                          // FCB CTRL = AUTO
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  u32 stat=R(0x40010010);
  R(0x40018420)=0;                                // GPIO4 software mode
  const u32 dmask=(1u<<1)|(1u<<3)|(1u<<5)|(1u<<7);   // din pins 1,3,5,7 (outputs)
  const u32 qmask=(1u<<0)|(1u<<2)|(1u<<4)|(1u<<6);   // dout pins 0,2,4,6 (inputs)
  R(0x40018400)=dmask;                            // set din pins output, dout pins input
  volatile u32* out=(volatile u32*)0x20001000;
  out[0]=stat;
  for(u32 c=0;c<16;c++){
    u32 din=0;
    for(u32 k=0;k<4;k++) if(c&(1u<<k)) din|=(1u<<(2*k+1));   // din pins 1,3,5,7
    DAT(dmask)=din;                               // drive the 4 din pins
    u32 q=DAT(qmask);                             // read the 4 dout pins
    out[1+2*c]=din;
    out[2+2*c]=q;
  }
  out[33]=0xC0FFEE08u;
  for(;;) __asm__ volatile("ebreak");
}
