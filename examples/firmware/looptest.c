typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
void __attribute__((section(".text.start"))) _start(void){
  R(0x03000060) |= (1u<<0)|(1u<<8);          // APB clk: FCB + GPIO4
  // FCB_AutoConfig from loop.bin (uncompressed) at 0x20002000
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);                       // FCB CTRL = AUTO
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  u32 stat=R(0x40010010);
  // GPIO4 @ 0x40018000: DIR@0x400, AFSEL@0x420, DATA[mask] at base+(mask<<2)
  R(0x40018420)=0;                              // software mode
  R(0x40018400)=(1u<<1);                        // bit1 output (din), bit2 input (dout)
  R(0x40018000+((1u<<1)<<2))=0;                 // din=0
  u32 r0=R(0x40018000+((1u<<2)<<2));            // read dout (bit2)  expect ~0 -> bit2 set
  R(0x40018000+((1u<<1)<<2))=(1u<<1);           // din=1
  u32 r1=R(0x40018000+((1u<<2)<<2));            // read dout         expect ~1 -> bit2 clear
  R(0x20001000)=stat; R(0x20001004)=r0; R(0x20001008)=r1; R(0x2000100c)=0xC0FFEE02u;
  for(;;) __asm__ volatile("ebreak");
}
