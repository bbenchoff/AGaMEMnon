#include <stdint.h>

#include "ag32.h"

/* Vendor default fabric maps GPIO4.1 to PIN_34 / board LED1. */
#define LED1 (1u << 1)

static void delay(volatile uint32_t count)
{
    while (count--) {
        __asm__ volatile("nop");
    }
}

int main(void)
{
    SYSCTL_APBCLK |= APBCLK_GPIO4;
    GPIO4_AFSEL &= ~LED1;
    GPIO4_DIR |= LED1;

    for (;;) {
        GPIO4_DATA(LED1) = LED1;
        delay(3000000u);
        GPIO4_DATA(LED1) = 0;
        delay(3000000u);
    }
}

