// SRAM stub: configure FCB conservatively on HSI, then reproduce the SDK's
// SYS_SwitchPLLClock(0) sequence so the fabric runs at the PLL rate encoded in
// its bitstream.  Results @0x20001000; no flash writes.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x03u;                      // SYS_SwitchHSIClock
  R(0x0300000C) &= ~0x24u;
  R(0x03000060) |= (1u<<0)|(1u<<8)|(3u<<10);    // APB clk: FCB(0) + GPIO4(8) + GPIO6(10) area
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);                        // FCB CTRL = AUTO
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  u32 stat=R(0x40010010);
  u32 clk=R(0x0300000C) & 0xffff00f7u;          // divider=0, primary HSE
  clk |= (1u<<2)|(1u<<5);                       // HSE + PLL enable
  R(0x0300000C)=clk;
  while(!(R(0x0300000C)&(1u<<4))) {}            // HSE ready
  u32 retry=0;
  while(!(R(0x0300000C)&(1u<<6))) {             // PLL lock; SDK pulses enable
    if(++retry>5000u){
      retry=0;
      R(0x0300000C)=clk&~(1u<<5);
      R(0x0300000C)=clk;
    }
  }
  R(0x0300000C)=R(0x0300000C)|2u;               // source = PLL
  // loopback probe (harmless for non-loopback designs)
  R(0x40018420)=0; R(0x40018400)=(1u<<1);
  R(0x40018000+((1u<<1)<<2))=0;      u32 r0=R(0x40018000+((1u<<2)<<2));
  R(0x40018000+((1u<<1)<<2))=(1u<<1);u32 r1=R(0x40018000+((1u<<2)<<2));
  R(0x20001000)=stat; R(0x20001004)=r0; R(0x20001008)=r1; R(0x2000100c)=0xC0FFEE02u;
  for(;;) __asm__ volatile("ebreak");
}
