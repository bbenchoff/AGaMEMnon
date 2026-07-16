#include "ag32_board_l48.h"

int main(void) {
    SYSCTL_APBCLK |= APBCLK_GPIO4;
    GPIO4_AFSEL &= ~BOARD_LED_MASK;
    GPIO4_DIR |= BOARD_LED_MASK;
    for (;;) {
        GPIO4_DATA(BOARD_LED_MASK) = 0x02;
        ag32_mtime_delay(1000000);
        GPIO4_DATA(BOARD_LED_MASK) = 0x00;
        ag32_mtime_delay(1000000);
    }
}
