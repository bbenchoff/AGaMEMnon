#include "ag32.h"

/* Poll hard basic TIMER0 and advance all four board LEDs on each period. */
#ifndef TIMER0_PERIOD_TICKS
#define TIMER0_PERIOD_TICKS 5000000u
#endif

int main(void) {
    static const uint8_t pattern[] = {
        0x02, 0x04, 0x08, 0x10, 0x08, 0x04
    };
    unsigned i = 0;

    SYSCTL_APBCLK |= APBCLK_GPIO4 | APBCLK_TIMER0;
    GPIO4_AFSEL &= ~BOARD_LED_MASK;
    GPIO4_DIR |= BOARD_LED_MASK;

    TIMER0_CTRL1 = 0;
    TIMER0_LOAD1 = TIMER0_PERIOD_TICKS;
    TIMER0_INTCLR1 = 1;
    TIMER0_CTRL1 = TIMER_CTRL_SIZE32 | TIMER_CTRL_PERIODIC | TIMER_CTRL_ENABLE;

    for (;;) {
        if (TIMER0_RIS1) {
            TIMER0_INTCLR1 = 1;
            GPIO4_DATA(BOARD_LED_MASK) = pattern[i];
            i = (i + 1u) % (sizeof(pattern) / sizeof(pattern[0]));
        }
    }
}
