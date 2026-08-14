#include "ag32.h"

/*
 * Fabric-analog bring-up: DAC set, ADC read, comparator read.
 *
 * The AG32 ADC/DAC/comparator are hard-macro analog cores wrapped by fabric IP
 * and reached over the External-AHB (fabric) window at 0x60000000, not MCU-core
 * MMIO. This demo drives DAC0 to a mid-scale code, reads that code back through
 * ADC0 (per the vendor analog IP, DAC0's output is wired to ADC input channel 4
 * and DAC1's to channel 5), takes a second ADC reading on the external input
 * channel 0, and configures comparator unit 1 to compare DAC0 against an
 * internal reference tap, reading its live output.
 *
 * IMPORTANT -- everything here is PAD/FABRIC dependent: with no fabric analog IP
 * routed into the External-AHB window these reads return whatever the bus
 * yields, and the ADC end-of-conversion wait will simply time out (reported as
 * a negative), never hang. The DAC->ADC and DAC->CMP internal paths need the
 * analog IP present; channel 0 additionally needs an analog pad routed. Bounded
 * throughout; non-destructive.
 *
 * Mailbox at 0x20001000 (read with `agamemnon sram <bin> --words 10`):
 *   [0] 0x414e4c47  "ANLG" tag
 *   [1] DAC0 code written                       (10-bit)
 *   [2] ADC of DAC0 readback (channel 4) or -1  [PAD/FABRIC]
 *   [3] ADC of external channel 0 or -1         [PAD/FABRIC]
 *   [4] CMP0 unit-1 output (0/1)                [PAD/FABRIC]
 *   [5] ADC0 STAT readback
 *   [6] CMP0 DATA readback (raw)
 *   [7] CMP0 CHNL readback (input selects)
 *   [8] SYSCTL DEVICE_ID
 *   [9] 0xc0ffeea1  done sentinel
 */

static volatile uint32_t *const mailbox = (volatile uint32_t *)0x20001000u;

#define DAC_CODE     512u        /* mid of the 10-bit range            */
#define ADC_SCLK_DIV 9u          /* sample clock = APB/((div+1)*2)/13  */
#define ADC_TIMEOUT  50000u
#define CMP_PSEL_DAC0 2u         /* comparator + input select = DAC0   */
#define CMP_MSEL_REF  4u         /* - input select = internal ref tap  */

int main(void) {
    mailbox[0] = 0x414e4c47u;                 /* "ANLG" */

    ag32_dac_enable(AG32_DAC0);
    ag32_dac_set(AG32_DAC0, DAC_CODE);
    mailbox[1] = DAC_CODE;

    /* Short settle before sampling the DAC output through the ADC. */
    for (volatile uint32_t i = 0; i < 2000u; ++i) { }

    int32_t dac_via_adc = ag32_adc_convert(AG32_ADC0, AG32_ADC_CHANNEL(4u),
                                           ADC_SCLK_DIV, ADC_TIMEOUT);
    int32_t ext_channel = ag32_adc_convert(AG32_ADC0, AG32_ADC_CHANNEL(0u),
                                           ADC_SCLK_DIV, ADC_TIMEOUT);
    mailbox[2] = (uint32_t)dac_via_adc;
    mailbox[3] = (uint32_t)ext_channel;

    ag32_cmp_configure1(AG32_CMP0, CMP_PSEL_DAC0, CMP_MSEL_REF);
    for (volatile uint32_t i = 0; i < 2000u; ++i) { }
    mailbox[4] = (uint32_t)ag32_cmp_output1(AG32_CMP0);

    mailbox[5] = AG32_ADC0->STAT;
    mailbox[6] = AG32_CMP0->DATA;
    mailbox[7] = AG32_CMP0->CHNL;
    mailbox[8] = SYSCTL_DEVID;
    mailbox[9] = 0xc0ffeea1u;

    ag32_dac_disable(AG32_DAC0);
    for (;;) { }
}
