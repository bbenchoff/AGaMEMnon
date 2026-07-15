// SRAM-only deterministic hardware oracle for generate_ahb_step().
// Load at 0x20000000 with the fabric image at 0x20002000. Each AHB store
// advances the fabric once; the following load records that exact state.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

void __attribute__((section(".text.start"))) _start(void)
{
    R(0x0300000C) &= ~0x27u;
    R(0x03000060) |= (1u << 0);
    volatile u32 *cfg = (volatile u32 *)0x20002000;
    R(0x40010000) = (1u << 6);
    for (int i = 0; i < 24986; ++i)
        R(0x4001000c) = cfg[i];

    volatile u32 *out = (volatile u32 *)0x20001000;
    out[0] = R(0x40010010);
    for (int i = 0; i < 128; ++i) {
        R(0x60000000) = (u32)i;
        for (volatile int delay = 0; delay < 32; ++delay)
            ;
        out[1 + i] = R(0x60000000);
    }
    out[129] = 0xC0FFEE61u;
    for (;;)
        __asm__ volatile("ebreak");
}
