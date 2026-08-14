#include "ag32.h"

/*
 * Fabric-analog qualification probe: DAC -> ADC sweep and comparator threshold
 * scan.
 *
 * The AG32 ADC/DAC/comparator are hard-macro analog cores wrapped by fabric IP
 * and reached over the External-AHB (fabric) window at 0x60000000, not MCU-core
 * MMIO. They only exist once a fabric image instantiating the analog IP has been
 * configured; this firmware does not configure the fabric, it only drives the
 * registers.
 *
 * Two STIMULUS-RESPONSE tests, because a single mid-scale write plus one read
 * cannot tell a working analog path from a stuck constant:
 *
 *   (A) DAC0 -> ADC0 channel-4 internal loopback SWEEP. DAC0's output is wired
 *       on-die to ADC input channel 4 (DAC1's to channel 5), so no external
 *       analog wiring is needed. Nine rising DAC codes are written and ADC0 is
 *       read after each. The verdict requires the readings to be non-decreasing
 *       AND to rise by at least half of full scale, so a stuck value FAILS.
 *   (B) CMP0 unit-1 threshold FLIP scan. Positive input = DAC0, negative input =
 *       each of the four internal VREF taps in turn. DAC0 is swept up from 0 and
 *       the code where the output first reads 1 is recorded. The verdict requires
 *       four flips, strictly increasing, none of them at code 0 (a flip already
 *       present at code 0 means the output is stuck high, not tracking).
 *   (C) One external ADC channel-0 read, reported and NOT relied on: that analog
 *       pad is not bonded on the L48 package, so it reads full scale there.
 *
 * Reference results from the qualifying L48 run (open flow, 2026-08-14):
 * the sweep returned 0, 512, 1024, 1536, 2054, 2575, 3085, 3598, 4095
 * (monotonic, ~4.00x linear = 12-bit result over 10-bit code, saturating), and
 * the flip codes were 94 / 188 / 281 / 373 against the vendor RTL's predicted
 * 93 / 186 / 279 / 372.
 *
 * CMP0 unit 2 is deliberately not exercised: it enables and reads back, but its
 * output stayed high at every DAC0 code under both positive-input selects, so
 * its input map is undocumented and unproven.
 *
 * Everything is bounded -- ADC conversions have an end-of-conversion timeout and
 * every sweep is at most 1024 steps -- so with no analog IP in the External-AHB
 * window this reports negatives and never hangs. Non-destructive; no flash.
 *
 * Mailbox at 0x20001000 (read with `agamemnon sram <bin> --words 28`):
 *   [0]  0x414e4c47  "ANLG" tag
 *   [1]  DAC sweep point count (9)
 *   [2]  sweep verdict: "PASS" 0x50415353 / "FAIL" 0x4641494c / "TIMO" 0x54494d4f
 *   [3..11] ADC0 channel-4 reading per DAC code {0,128,...,1023}
 *           (12-bit value, or 0xffffffff = -1 on EOC timeout)
 *   [12] CMP0 unit-1 flip DAC code, MSEL = VREF/4    (0xffffffff = never flipped)
 *   [13] CMP0 unit-1 flip DAC code, MSEL = VREF/2
 *   [14] CMP0 unit-1 flip DAC code, MSEL = 3*VREF/4
 *   [15] CMP0 unit-1 flip DAC code, MSEL = VREF
 *   [16] comparator verdict: "PASS" / "FAIL"
 *   [17] ADC0 external channel-0 reading or -1  [unbonded on L48: expect 0xfff]
 *   [18] ADC0 STAT readback
 *   [19] ADC0 CTRL readback
 *   [20] ADC0 CHNL readback
 *   [21] DAC0 CTRL readback
 *   [22] DAC0 DATA readback
 *   [23] CMP0 CTRL readback
 *   [24] CMP0 CHNL readback
 *   [25] CMP0 DATA raw readback
 *   [26] SYSCTL DEVICE_ID
 *   [27] 0xc0ffeea1  done sentinel
 */

static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

#define VERDICT_PASS 0x50415353u  /* "PASS" */
#define VERDICT_FAIL 0x4641494cu  /* "FAIL" */
#define VERDICT_TIMO 0x54494d4fu  /* "TIMO" */

#define ADC_SCLK_DIV  9u          /* sample clock = APB/((div+1)*2)/13   */
#define ADC_TIMEOUT   60000u      /* bounded EOC wait, reports -1        */
#define SWEEP_POINTS  9u
#define DAC_SETTLE    4000u       /* analog settle before a conversion   */
#define CMP_SETTLE    400u        /* analog settle before a compare read */
#define CMP_TAPS      4u
/* A working path must rise by at least half of full scale over the sweep. */
#define SWEEP_MIN_RISE (AG32_ADC_MAX_VALUE / 2u)

static const uint32_t dac_codes[SWEEP_POINTS] = {
    0u, 128u, 256u, 384u, 512u, 640u, 768u, 896u, 1023u
};

static const uint32_t cmp_taps[CMP_TAPS] = {
    AG32_CMP_MSEL_VREF_DIV4, AG32_CMP_MSEL_VREF_DIV2,
    AG32_CMP_MSEL_VREF_3DIV4, AG32_CMP_MSEL_VREF
};

static void settle(uint32_t iterations) {
    for (volatile uint32_t i = 0; i < iterations; ++i) { }
}

int main(void) {
    mailbox[0] = 0x414e4c47u;                 /* "ANLG" */
    mailbox[1] = SWEEP_POINTS;

    ag32_dac_enable(AG32_DAC0);

    /* ---- (A) DAC0 -> ADC0 channel-4 loopback sweep ---- */
    int timed_out = 0;
    int monotonic = 1;
    int32_t previous = 0;
    int32_t first = 0;
    int32_t last = 0;
    for (unsigned k = 0; k < SWEEP_POINTS; ++k) {
        ag32_dac_set(AG32_DAC0, dac_codes[k]);
        settle(DAC_SETTLE);
        int32_t value = ag32_adc_convert(AG32_ADC0, AG32_ADC_CH_DAC0,
                                         ADC_SCLK_DIV, ADC_TIMEOUT);
        mailbox[3 + k] = (uint32_t)value;
        if (value < 0) {
            timed_out = 1;
            continue;
        }
        if (k == 0u)
            first = value;
        else if (value < previous)
            monotonic = 0;
        previous = value;
        last = value;
    }
    if (timed_out)
        mailbox[2] = VERDICT_TIMO;
    else if (monotonic && (uint32_t)(last - first) >= SWEEP_MIN_RISE)
        mailbox[2] = VERDICT_PASS;
    else
        mailbox[2] = VERDICT_FAIL;

    /* ---- (B) CMP0 unit-1 threshold flip scan against the four VREF taps ---- */
    int flips_ok = 1;
    uint32_t previous_flip = 0u;
    for (unsigned tap = 0; tap < CMP_TAPS; ++tap) {
        ag32_cmp_configure1(AG32_CMP0, AG32_CMP_PSEL_DAC0, cmp_taps[tap]);
        uint32_t flip = 0xffffffffu;
        for (uint32_t code = 0; code <= AG32_DAC_MAX_VALUE; ++code) {
            ag32_dac_set(AG32_DAC0, code);
            settle(CMP_SETTLE);
            if (ag32_cmp_output1(AG32_CMP0)) {
                flip = code;
                break;
            }
        }
        mailbox[12 + tap] = flip;
        /* A flip at code 0 means the output was already high: stuck, not
         * tracking. Later taps must sit strictly above earlier ones. */
        if (flip == 0xffffffffu || flip == 0u || flip <= previous_flip)
            flips_ok = 0;
        else
            previous_flip = flip;
    }
    mailbox[16] = flips_ok ? VERDICT_PASS : VERDICT_FAIL;

    /* ---- (C) external channel 0: reported, not relied on (unbonded on L48) ---- */
    ag32_dac_set(AG32_DAC0, AG32_DAC_MAX_VALUE / 2u);
    settle(DAC_SETTLE);
    mailbox[17] = (uint32_t)ag32_adc_convert(AG32_ADC0, AG32_ADC_CHANNEL(0u),
                                             ADC_SCLK_DIV, ADC_TIMEOUT);

    /* ---- raw register readbacks: bus liveness independent of the verdicts ---- */
    mailbox[18] = AG32_ADC0->STAT;
    mailbox[19] = AG32_ADC0->CTRL;
    mailbox[20] = AG32_ADC0->CHNL;
    mailbox[21] = AG32_DAC0->CTRL;
    mailbox[22] = AG32_DAC0->DATA;
    mailbox[23] = AG32_CMP0->CTRL;
    mailbox[24] = AG32_CMP0->CHNL;
    mailbox[25] = AG32_CMP0->DATA;
    mailbox[26] = SYSCTL_DEVID;

    ag32_cmp_disable1(AG32_CMP0);
    ag32_dac_disable(AG32_DAC0);
    mailbox[27] = 0xc0ffeea1u;                /* done */

    for (;;) { }
}
