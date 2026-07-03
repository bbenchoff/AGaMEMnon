// AHB bus silicon test: FCB-config the open fabric AHB slave, then have the MCU WRITE the fabric
// register over the memory bus (External AHB @ 0x60000000) and read the captured bit back on GPIO4.2.
// datareg <- hwdata[0], exposed on GPIO4.2. Write 1 -> expect GPIO4.2 set (0x4); write 0 -> clear.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x27u;                        // -> HSI clock (avoid FCB config overrun)
  R(0x03000060) |= (1u<<0)|(1u<<8);               // APB clk: FCB + GPIO4
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);                          // FCB CTRL = AUTO
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  u32 stat=R(0x40010010);
  R(0x40018420)=0; R(0x40018400)=0;               // GPIO4 software mode, bit2 = input (readback)
  volatile u32* out=(volatile u32*)0x20001000;
  out[0]=stat; out[1]=0xDEAD; out[2]=0xDEAD;      // sentinels: if a store hangs, these persist
  // --- AHB WRITE 1 over the memory bus, then read the fabric register back ---
  R(0x60000000) = 0x1u;                           // MCU -> mem_ahb -> fabric slave: datareg <= 1
  for(volatile int i=0;i<50;i++);                 // let the capture settle
  out[1]=R(0x40018000+((1u<<2)<<2)) & (1u<<2);    // GPIO4.2 readback (expect 0x4)
  // --- AHB WRITE 0 ---
  R(0x60000000) = 0x0u;                           // datareg <= 0
  for(volatile int i=0;i<50;i++);
  out[2]=R(0x40018000+((1u<<2)<<2)) & (1u<<2);    // GPIO4.2 readback (expect 0x0)
  out[3]=0xC0FFEE60u;
  for(;;) __asm__ volatile("ebreak");
}
