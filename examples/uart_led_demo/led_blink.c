// Walking/fill LED pattern. The boot ROM configures led_ahb from flash before
// entering this code at 0x80000000, so firmware only needs to write the AHB
// fabric register.
typedef unsigned int u32;
#define REG32(address) (*(volatile u32 *)(address))
#define LEDS REG32(0x60000000u)

static void delay(void) {
  for (volatile u32 count = 0; count < 900000u; ++count)
    __asm__ volatile ("nop");
}

void __attribute__((section(".text.start"), noreturn)) _start(void) {
  for (;;) {
    LEDS = 1u;  // each protocol-valid write advances the fabric LED state
    delay();
  }
}
