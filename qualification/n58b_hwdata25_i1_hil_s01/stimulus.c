// Retained SRAM-only RISC-V stimulus for the N5.8B HWDATA25 I1 discriminator.
// The fabric image is preloaded at 0x20002000. Repeated writes make HWDATA25
// alternate in long, capture-friendly epochs without using flash or reset.
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))

static void write_epoch(u32 value, u32 repeats)
{
    volatile u32 *fabric = (volatile u32 *)0x60000000;
    for (u32 i = 0; i < repeats; ++i)
        *fabric = value;
}

void __attribute__((section(".text.start"))) _start(void)
{
    R(0x0300000C) &= ~0x27u;
    R(0x03000060) |= (1u << 0);

    volatile u32 *cfg = (volatile u32 *)0x20002000;
    R(0x40010000) = (1u << 6);
    for (u32 i = 0; i < 24986u; ++i)
        R(0x4001000c) = cfg[i];
    (void)R(0x40010010);

    for (;;) {
        write_epoch(0u, 1024u);
        write_epoch(1u << 25, 1024u);
        write_epoch(0u, 512u);
        write_epoch(1u << 25, 512u);
    }
}
