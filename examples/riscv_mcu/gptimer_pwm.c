#include "ag32.h"

/*
 * GPTIMER advanced-timer time-base + edge-aligned PWM bring-up.
 *
 * Programs GPTIMER0 as an up-counting time base (PSC prescaler, ARR period),
 * forces an update to latch the shadow registers, starts the counter, and
 * samples CNT three times across bounded software delays to prove the counter
 * is running. It then configures channel 0 as a PWM1 output at ~50% duty and
 * reads the capture/compare registers back to prove the PWM control path
 * landed. Everything is MCU-internal (APB); the actual PWM waveform only
 * reaches a package pin once the fabric routes GPTIMER0_CH0 through GPIO
 * alternate-function to a pad, so the pin toggle itself is pad/fabric
 * dependent. No flash, no destructive writes; all waits are bounded.
 *
 * Mailbox at 0x20001000 (read with `agamemnon sram <bin> --words 10`):
 *   [0] 0x47505430  "GPT0" tag
 *   [1] init status         (0 = time base programmed, <0 = bad index)
 *   [2] pwm config status   (0 = channel 0 armed as PWM1, <0 = rejected)
 *   [3] CNT sample 1
 *   [4] CNT sample 2
 *   [5] CNT sample 3        (samples differ => counter advancing)
 *   [6] CR1 readback        (bit0 CEN, bit7 ARPE set once PWM armed)
 *   [7] ARR<<16 | CCR0low   (period vs 50% compare threshold)
 *   [8] CCER<<16 | CCMR0low (CC0E enable + PWM1/OCPE mode field)
 *   [9] SYSCTL DEVICE_ID
 */

static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

#define GPT_PERIOD   0xFFFFu      /* 16-bit auto-reload period          */
#define GPT_PSC      0x0007u      /* divide the timer clock by 8        */
#define GPT_DUTY     0x8000u      /* ~50% of GPT_PERIOD                 */

static uint32_t spin_sample(void) {
    for (volatile uint32_t i = 0; i < 4000u; ++i) { }
    return ag32_gptimer_counter(AG32_GPTIMER0);
}

int main(void) {
    mailbox[0] = 0x47505430u;                 /* "GPT0" */

    int init = ag32_gptimer_init(AG32_GPTIMER0, GPT_PSC, GPT_PERIOD);
    mailbox[1] = (uint32_t)init;

    ag32_gptimer_start(AG32_GPTIMER0);

    uint32_t s1 = spin_sample();
    uint32_t s2 = spin_sample();
    uint32_t s3 = spin_sample();

    int pwm = ag32_gptimer_pwm_output(AG32_GPTIMER0, 0,
                                      AG32_GPTIMER_OCM_PWM1, GPT_DUTY);
    mailbox[2] = (uint32_t)pwm;

    mailbox[3] = s1;
    mailbox[4] = s2;
    mailbox[5] = s3;
    mailbox[6] = AG32_GPTIMER0->CR1;
    mailbox[7] = (AG32_GPTIMER0->ARR << 16) | (AG32_GPTIMER0->CCR[0] & 0xffffu);
    mailbox[8] = ((AG32_GPTIMER0->CCER & 0xffffu) << 16) |
                 (AG32_GPTIMER0->CCMR0 & 0xffffu);
    mailbox[9] = SYSCTL_DEVID;

    for (;;) { }
}
