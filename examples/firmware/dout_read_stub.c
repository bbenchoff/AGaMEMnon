// SRAM stub: HSI clock, FCB_AutoConfig the fabric from 0x20002000, then sample GPIO4.2 (dout) 64
// times into 0x20001000.. . A mix of 0x0 and 0x4 across the samples => the fabric FF is toggling.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x27u;                        // -> HSI clock (avoid FCB config overrun)
  R(0x03000060) |= (1u<<0)|(1u<<8);               // APB clk: FCB + GPIO4
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);                          // FCB CTRL = AUTO
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  u32 stat=R(0x40010010);
  R(0x40018420)=0; R(0x40018400)=0;               // GPIO4 software mode, bit2 = input (dout)
  volatile u32* out=(volatile u32*)0x20001000;
  out[0]=stat;
  for(int i=0;i<64;i++) out[1+i]=R(0x40018000+((1u<<2)<<2)) & (1u<<2);  // sample dout (bit2)
  out[65]=0xC0FFEE02u;
  for(;;) __asm__ volatile("ebreak");
}
