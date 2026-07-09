// FCB-config the fabric, then AHB-write 0x60000000 = 1/0 at ~1 Hz. The open ahb_pad slave captures
// bit0 into datareg @(14,9) and drives PIN_18 -> visible blink at the MCU-controlled rate.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x27u;
  R(0x03000060) |= (1u<<0)|(1u<<8)|(3u<<10);
  volatile u32* cfg=(volatile u32*)0x20002000;
  R(0x40010000)=(1u<<6);
  for(int i=0;i<24986;i++) R(0x4001000c)=cfg[i];
  (void)R(0x40010010);
  for(;;){
    R(0x60000000)=1u;                          // AHB write hwdata0=1 -> datareg<=1 -> PIN_18 high
    for(volatile u32 d=0; d<450000u; d++);
    R(0x60000000)=0u;                          // datareg<=0 -> PIN_18 low
    for(volatile u32 d=0; d<450000u; d++);
  }
}
