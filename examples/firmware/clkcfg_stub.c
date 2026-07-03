// SRAM stub: switch to HSI clock FIRST (the polled FCB_AutoConfig overruns at a fast clock ->
// FCB_STAT_ERR_CRC=0x40; the SDK's FCB path switches to HSI before config), enable FCB clk,
// FCB_AutoConfig the fabric from 0x20002000, then the loopback din/dout probe. Results @0x20001000.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x27u;                      // CLK_CNTL: source->HSI(bits0-1), HSE off(bit2), PLL off(bit5)
  R(0x03000060) |= (1u<<0)|(1u<<8)|(3u<<10);    // APB clk: FCB(0) + GPIO4(8) + GPIO6(10) area
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);                        // FCB CTRL = AUTO
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  u32 stat=R(0x40010010);
  // loopback probe (harmless for non-loopback designs)
  R(0x40018420)=0; R(0x40018400)=(1u<<1);
  R(0x40018000+((1u<<1)<<2))=0;      u32 r0=R(0x40018000+((1u<<2)<<2));
  R(0x40018000+((1u<<1)<<2))=(1u<<1);u32 r1=R(0x40018000+((1u<<2)<<2));
  R(0x20001000)=stat; R(0x20001004)=r0; R(0x20001008)=r1; R(0x2000100c)=0xC0FFEE02u;
  for(;;) __asm__ volatile("ebreak");
}
