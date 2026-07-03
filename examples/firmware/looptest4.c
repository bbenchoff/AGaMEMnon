// 2-bit MCU<->fabric loopback test (SRAM stub). Extends looptest.c to two GPIO bit-pairs:
//   din0 = GPIO4.1 (output), dout0 = GPIO4.2 (input)
//   din1 = GPIO4.3 (output), dout1 = GPIO4.4 (input)
// FCB_AutoConfigs the fabric from 0x20002000 (99944B = 24986 words), then sweeps all 4 (din0,din1)
// combos, reading (dout0,dout1) after each. For dout[i]=~din[i] the read dout bits invert the driven
// din bits. Results stored at 0x20001000 as (stat, {din,dout}x4, sentinel). SRAM-only.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
#define GP   0x40018000u
#define DAT(mask) R(GP + ((mask) << 2))     // Stellaris-style masked GPIO data
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x27u;                   // -> HSI clock (avoid FCB config overrun)
  R(0x03000060) |= (1u<<0)|(1u<<8);          // APB clk: FCB + GPIO4
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);                      // FCB CTRL = AUTO
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  u32 stat=R(0x40010010);
  R(0x40018420)=0;                            // GPIO4 software mode (AFSEL=0)
  R(0x40018400)=(1u<<1)|(1u<<3);              // bit1,bit3 output (din0,din1); bit2,bit4 input (dout)
  volatile u32* out=(volatile u32*)0x20001000;
  out[0]=stat;
  const u32 dmask=(1u<<1)|(1u<<3);            // din bits
  const u32 qmask=(1u<<2)|(1u<<4);            // dout bits
  for(u32 c=0;c<4;c++){
    u32 din=((c&1u)?(1u<<1):0u) | ((c&2u)?(1u<<3):0u);
    DAT(dmask)=din;                           // drive din0,din1
    u32 q=DAT(qmask);                         // read dout0,dout1
    out[1+2*c]=din;
    out[2+2*c]=q;
  }
  out[9]=0xC0FFEE04u;
  for(;;) __asm__ volatile("ebreak");
}
