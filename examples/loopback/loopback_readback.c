// FLASH-BOOT readback app (SRAM stub, injected AFTER the boot ROM has already configured the fabric
// FROM FLASH). Unlike looptest4.c it does NOT FCB-config the fabric (no 0x20002000 bin, no config
// loop) -- it only READS FCB->STAT to confirm the boot ROM's flash-config succeeded, then runs the
// proven 2-bit GPIO loopback to confirm OUR design (mcu_loop2) is the one that came up from flash.
//   din0=GPIO4.1(out) dout0=GPIO4.2(in) ; din1=GPIO4.3(out) dout1=GPIO4.4(in) ; dout[i]=~din[i]
// Results @0x20001000: [0]=FCB STAT (expect 0x000f0002 = configured), [1..8]=(din,dout)x4, [9]=sentinel.
// This ISOLATES the one new variable (fabric configured from flash, not SRAM-injected); the GPIO
// path + loopback design are already silicon-proven, so a correct readback proves flash-boot worked.
typedef unsigned int u32;
#define R(a) (*(volatile u32*)(a))
#define GP   0x40018000u
#define DAT(mask) R(GP + ((mask) << 2))          // Stellaris-style masked GPIO data
void __attribute__((section(".text.start"))) _start(void){
  R(0x0300000C) &= ~0x27u;                        // -> HSI clock (parity with the config-time stub)
  R(0x03000060) |= (1u<<0)|(1u<<8);               // APB clk: FCB + GPIO4
  u32 stat=R(0x40010010);                         // FCB STAT: 0x000f0002 => fabric configured (from FLASH)
  R(0x40018420)=0;                                // GPIO4 software mode (AFSEL=0)
  R(0x40018400)=(1u<<1)|(1u<<3);                  // bit1,bit3 output (din); bit2,bit4 input (dout)
  volatile u32* out=(volatile u32*)0x20001000;
  out[0]=stat;
  const u32 dmask=(1u<<1)|(1u<<3);
  const u32 qmask=(1u<<2)|(1u<<4);
  for(u32 c=0;c<4;c++){
    u32 din=((c&1u)?(1u<<1):0u) | ((c&2u)?(1u<<3):0u);
    DAT(dmask)=din;                               // drive din0,din1
    u32 q=DAT(qmask);                             // read dout0,dout1
    out[1+2*c]=din;
    out[2+2*c]=q;
  }
  out[9]=0xC0FFEEF1u;                             // "flashboot" sentinel
  for(;;) __asm__ volatile("ebreak");
}
