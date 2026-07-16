#include "ag32.h"

/*
 * Walk the four on-board LEDs using the fixed RISC-V MTIME counter.
 *
 * GPIO4[1:4] reach PIN_34..PIN_31 only when the default L48 board fabric (or
 * an equivalent .ve mapping) is loaded.  MTIME itself does not depend on the
 * programmable fabric.  CLINT_TICKS_PER_STEP is intentionally configurable:
 * measure MTIME on a new clock configuration before treating it as wall time.
 */
#ifndef CLINT_TICKS_PER_STEP
#define CLINT_TICKS_PER_STEP 1000000ull
#endif

int main(void) {
    static const uint8_t pattern[] = {
        0x02, 0x04, 0x08, 0x10, 0x08, 0x04
    };
    unsigned i = 0;

    SYSCTL_APBCLK |= APBCLK_GPIO4;
    GPIO4_AFSEL &= ~BOARD_LED_MASK;
    GPIO4_DIR |= BOARD_LED_MASK;

    for (;;) {
        GPIO4_DATA(BOARD_LED_MASK) = pattern[i];
        i = (i + 1u) % (sizeof(pattern) / sizeof(pattern[0]));
        ag32_mtime_delay(CLINT_TICKS_PER_STEP);
    }
}
