#ifndef AGAMEMNON_AG32_SYSCTL_H
#define AGAMEMNON_AG32_SYSCTL_H

/*
 * AG32 system control (RCC-class) block at 0x03000000: bus reset/clock gates,
 * the PBUS and MTIME dividers, and the clock-source status this SDK is allowed
 * to read.
 *
 * ============================================================================
 * READ THIS BEFORE COMPUTING ANY BAUD RATE, BIT TIME, OR PRESCALER
 * ============================================================================
 * Nothing in this header configures the clock tree. There is no PLL setup, no
 * source switch, and no frequency negotiation anywhere in the AGaMEMnon SDK.
 * Firmware runs at whatever clock it inherited, and `ag32_pbus_hz()` only
 * divides a number the CALLER supplied by the live PBUS divider. It cannot
 * detect a wrong argument.
 *
 * Worse, the clock tree is NOT CHARACTERIZED. On one SRAM-loaded,
 * PLL-unconfigured L48 board on 2026-08-14:
 *
 *   Domain   Measured           Method
 *   ------   ----------------   ------------------------------------------------
 *   MTIME    14.08 MHz          counted against a host `sleep 1000` over the
 *                               debug link, repeated, consistent
 *   UART0    ~14.47 MHz         back-solved from the divisors the PL011 driver
 *                               actually programmed for a requested 9600 baud
 *                               (IBRD 0x64e = 1614, FBRD 0x25 = 37) against the
 *                               1786 us bit time on a logic analyzer (560 baud):
 *                               560 * 16 * 1614.578
 *   SPI0     UNRESOLVED         Relative divisors 2..256 are silicon-qualified.
 *            absolute ref      The old driver asserted CTRL.SOFT_RESET, leaving
 *                              CTRL=0x00008202 and discarding the next divider
 *                              write; this caused the former flat SCK sweep.
 *
 * MTIME and UART0 agree with each other. SPI0's relative divider now works, but
 * its absolute reference still needs an independent simultaneous measurement.
 *
 * The concrete bug this caused: firmware called `ag32_pbus_hz(248000000)` and
 * `ag32_uart_init(UART0, pbus, 9600)`, and the UART transmitted at ~560 baud -
 * roughly 17x slow - because the returned value described neither the UART's
 * reference clock nor anything else the UART consumes. That is a real, measured
 * defect, and it is specific to the UART's domain.
 *
 * Do NOT read any of the numbers above as "the AG32 peripheral clock". Each is a
 * MEASURED OBSERVATION of one peripheral in one configuration on one board. None
 * is a datasheet constant. Which source feeds which peripheral, and by what
 * division, has not been established: the documented model
 * (APB = SYSCLK / (PBUS_DIV + 1), shared by every APB peripheral) does not
 * predict a UART/SPI ratio of ~18, so either the model or our reading of it is
 * incomplete. Treat the per-domain constants below as bring-up starting points
 * to be re-measured, not as a clock tree.
 *
 * What to do:
 *   - UART0: use `ag32_uart_ref_hz_measured()`. It is the only APB reference
 *     clock that has actually been measured.
 *   - Any other peripheral: measure it. If you must guess, guessing the UART's
 *     domain is a CROSS-DOMAIN ASSUMPTION that SPI0 already falsifies, so record
 *     the value you used and publish `CLK_CNTL` / `PBUS_DIVIDER` / `MTIME_PSC`
 *     alongside your results so the domain can be re-derived later.
 *   - `ag32_pbus_hz_actual()` models the documented PBUS relationship from live
 *     register reads plus a caller-supplied board profile. It is the right shape
 *     for a characterized tree; it is not yet backed by measurement.
 *   - `ag32_pbus_hz()` remains for callers that genuinely know their clock.
 *
 * No runtime clock-switch API is offered. See MCU_CLOCKS.md: the switch sequence
 * is unqualified on this fixture, the PLL rate is not an MCU-side programmable,
 * and shipping an unverified setter that can strand the part is worse than
 * making callers state their clock.
 *
 * One clock side effect worth knowing: `ag32_fcb_config()` in ag32.h clears the
 * CLK_CNTL source select plus the HSE and PLL enables before streaming a fabric
 * image, and nothing in this SDK switches back.
 */

#include "ag32_device.h"

/* Register offsets from AG32_SYSCTL_BASE. */
#define AG32_SYSCTL_BOOT_MODE     AG32_REG32(AG32_SYSCTL_BASE + 0x00u)
#define AG32_SYSCTL_RST_CNTL      AG32_REG32(AG32_SYSCTL_BASE + 0x04u)
#define AG32_SYSCTL_PWR_CNTL      AG32_REG32(AG32_SYSCTL_BASE + 0x08u)
#define AG32_SYSCTL_CLK_CNTL      AG32_REG32(AG32_SYSCTL_BASE + 0x0cu)
#define AG32_SYSCTL_MISC_CNTL     AG32_REG32(AG32_SYSCTL_BASE + 0x18u)
#define AG32_SYSCTL_MTIME_PSC     AG32_REG32(AG32_SYSCTL_BASE + 0x30u)
#define AG32_SYSCTL_MTIME_COUNTER AG32_REG32(AG32_SYSCTL_BASE + 0x34u)
#define AG32_SYSCTL_PBUS_DIVIDER  AG32_REG32(AG32_SYSCTL_BASE + 0x38u)
#define AG32_SYSCTL_APB_RESET     AG32_REG32(AG32_SYSCTL_BASE + 0x40u)
#define AG32_SYSCTL_AHB_RESET     AG32_REG32(AG32_SYSCTL_BASE + 0x50u)
#define AG32_SYSCTL_APB_ENABLE    AG32_REG32(AG32_SYSCTL_BASE + 0x60u)
#define AG32_SYSCTL_AHB_ENABLE    AG32_REG32(AG32_SYSCTL_BASE + 0x70u)
#define AG32_SYSCTL_APB_DBGSTOP   AG32_REG32(AG32_SYSCTL_BASE + 0x80u)
#define AG32_SYSCTL_DEVICE_ID     AG32_REG32(AG32_SYSCTL_BASE + 0x100u)

#define AG32_APB_FCB0       (1u << 0)
#define AG32_APB_WATCHDOG0  (1u << 1)
#define AG32_APB_SPI0       (1u << 2)
#define AG32_APB_SPI1       (1u << 3)
#define AG32_APB_GPIO(n)    (1u << (4u + (uint32_t)(n)))
#define AG32_APB_TIMER(n)   (1u << (14u + (uint32_t)(n)))
#define AG32_APB_GPTIMER(n) (1u << (16u + (uint32_t)(n)))
#define AG32_APB_UART(n)    (1u << (21u + (uint32_t)(n)))
#define AG32_APB_CAN0       (1u << 26)
#define AG32_APB_I2C(n)     (1u << (27u + (uint32_t)(n)))

#define AG32_AHB_DMAC0      (1u << 0)
#define AG32_AHB_USB0       (1u << 1)
#define AG32_AHB_CRC0       (1u << 2)
#define AG32_AHB_MAC0       (1u << 3)

/*
 * CLK_CNTL. Documented status/divider fields only; this SDK reads them and
 * never writes a source switch. The two flash SPI divider fields must hold
 * equal safe values before SYSCLK is raised, which is one more reason the
 * switch is not exposed here.
 */
#define AG32_CLK_SOURCE_MASK  0x3u
#define AG32_CLK_SOURCE_HSI   0u   /* internal RC, selected out of reset */
#define AG32_CLK_SOURCE_HSE   1u   /* external crystal/resonator or bypass */
#define AG32_CLK_SOURCE_PLL   2u   /* PLL output (rate set by the fabric)  */
#define AG32_CLK_SOURCE_EXT   3u   /* fabric/external system clock input   */
#define AG32_CLK_HSE_ON       (1u << 2)
#define AG32_CLK_HSE_BYPASS   (1u << 3)
#define AG32_CLK_HSE_READY    (1u << 4)
#define AG32_CLK_PLL_ON       (1u << 5)
#define AG32_CLK_PLL_READY    (1u << 6)
#define AG32_CLK_SCLK_DIV_MASK        0xfu
#define AG32_CLK_SCLK_DIV_HIGH_SHIFT  8u
#define AG32_CLK_SCLK_DIV_LOW_SHIFT   12u

/* PBUS_DIVIDER: documented as APB = SYSCLK / (field + 1), field 0..15. */
#define AG32_PBUS_DIVIDER_MASK 0xfu

/* MTIME_PSC: MTIME ticks at SYSCLK / (field + 1) with two control bits. */
#define AG32_MTIME_PSC_MASK       0xffffu
#define AG32_MTIME_PSC_OFF        (1u << 30)
#define AG32_MTIME_PSC_DEBUG_STOP (1u << 31)

/*
 * ---------------------------------------------------------------------------
 * MEASURED per-domain reference clocks. NOT datasheet constants.
 * ---------------------------------------------------------------------------
 * Both were observed on ONE SRAM-loaded, PLL-unconfigured L48 board on
 * 2026-08-14, in the same firmware configuration. They AGREE with each other to
 * ~3%, which is consistent with a single APB reference near 14 MHz -- it is NOT
 * evidence of separate domains. They still describe the peripherals they were
 * measured on, not a guaranteed chip-wide rate, and the register state that
 * produced them was not captured, so a future run must re-derive the tree from
 * CLK_CNTL / PBUS_DIVIDER / MTIME_PSC rather than trust these.
 */

/* MTIME tick rate, counted against a known host delay over the debug link. */
#define AG32_MTIME_HZ_MEASURED 14080000u

/*
 * UART0's baud reference, back-solved from the divisors the driver programmed
 * against the bit time on a logic analyzer. The only APB reference clock that
 * has been measured. Accurate to roughly the ~1 % of a back-solve, and bounded
 * below by whatever source drives it - fine for loopback and register bring-up,
 * NOT good enough for a link that must interoperate with another device.
 */
#define AG32_UART_REF_HZ_MEASURED 14470000u

/*
 * SPI0's absolute shift-clock reference is NOT KNOWN, so no reference constant
 * is published for it.
 *
 * An earlier AG32_SPI0_REF_HZ_MEASURED of 258000000 was removed: it was computed
 * as (measured SCK 1,294,708 Hz) * (requested divider 200). The old SDK had
 * asserted CTRL.SOFT_RESET and the hardware retained its reset divider, so 200
 * was never latched and that product is meaningless.
 *
 * The old reset-divider capture was roughly 1.3-1.7 MHz. Preserve its upper
 * estimate only as a historical analyzer-sizing value; do not use it as current
 * SCK calibration. The repaired driver qualifies relative divisors 2..256.
 */
#define AG32_SPI0_RESET_SCK_HZ_HISTORICAL 1670000u
#define AG32_SPI0_SCK_HZ_MEASURED AG32_SPI0_RESET_SCK_HZ_HISTORICAL

/*
 * The nominal internal-oscillator figure carried by the vendor board profile,
 * recorded only for contrast with the measurements above. Not measured here.
 */
#define AG32_HSI_HZ_VENDOR_NOMINAL 10000000u

/* Reference-board external crystal. Board data, not a measurement. */
#define AG32_HSE_HZ_REFERENCE_BOARD 8000000u

/*
 * Board clock profile. Silicon can report WHICH source drives SYSCLK and by
 * what divider, but it cannot report the absolute frequency of a crystal or an
 * untrimmed RC oscillator, so the caller supplies those. Leave an entry 0 when
 * its rate is unknown: the helpers then return 0 rather than inventing a rate.
 */
typedef struct {
    uint32_t hsi_hz;   /* internal RC; measure it, do not assume it   */
    uint32_t hse_hz;   /* external crystal/resonator or bypass input  */
    uint32_t pll_hz;   /* PLL output, i.e. the fabric's SYSCLK pair   */
    uint32_t ext_hz;   /* fabric/external system-clock input          */
} ag32_clk_sources_t;

static inline void ag32_apb_enable(uint32_t mask) {
    AG32_SYSCTL_APB_ENABLE |= mask;
}

static inline void ag32_ahb_enable(uint32_t mask) {
    AG32_SYSCTL_AHB_ENABLE |= mask;
}

static inline void ag32_apb_reset(uint32_t mask) {
    AG32_SYSCTL_APB_RESET |= mask;
    AG32_SYSCTL_APB_RESET &= ~mask;
}

static inline void ag32_ahb_reset(uint32_t mask) {
    AG32_SYSCTL_AHB_RESET |= mask;
    AG32_SYSCTL_AHB_RESET &= ~mask;
}

/* Which source is driving SYSCLK right now: one of AG32_CLK_SOURCE_*. */
static inline uint32_t ag32_sysclk_source(void) {
    return AG32_SYSCTL_CLK_CNTL & AG32_CLK_SOURCE_MASK;
}

static inline int ag32_clk_hse_ready(void) {
    return (AG32_SYSCTL_CLK_CNTL & AG32_CLK_HSE_READY) ? 1 : 0;
}

static inline int ag32_clk_pll_ready(void) {
    return (AG32_SYSCTL_CLK_CNTL & AG32_CLK_PLL_READY) ? 1 : 0;
}

/* Live APB divisor, 1..16 (register field + 1). */
static inline uint32_t ag32_pbus_divider(void) {
    return (AG32_SYSCTL_PBUS_DIVIDER & AG32_PBUS_DIVIDER_MASK) + 1u;
}

/* Live MTIME divisor, 1..65536. */
static inline uint32_t ag32_mtime_divider(void) {
    return (AG32_SYSCTL_MTIME_PSC & AG32_MTIME_PSC_MASK) + 1u;
}

/*
 * UART0's measured baud reference clock. Use this for UART0 instead of any
 * assumed SYSCLK. It is a measurement of UART0 specifically: SPI0's absolute
 * reference in the same configuration has not been independently measured, so
 * passing this to another peripheral is a
 * cross-domain assumption you must record and ideally re-measure.
 */
static inline uint32_t ag32_uart_ref_hz_measured(void) {
    return AG32_UART_REF_HZ_MEASURED;
}

/*
 * SYSCLK per the documented model: the live source select resolved against a
 * board profile. Returns 0 when the selected source's rate was left unknown -
 * callers must treat 0 as "do not compute a bit rate from this".
 */
static inline uint32_t ag32_sysclk_hz(const ag32_clk_sources_t *sources) {
    if (!sources)
        return 0u;
    switch (ag32_sysclk_source()) {
    case AG32_CLK_SOURCE_HSI: return sources->hsi_hz;
    case AG32_CLK_SOURCE_HSE: return sources->hse_hz;
    case AG32_CLK_SOURCE_PLL: return sources->pll_hz;
    default:                  return sources->ext_hz;
    }
}

/*
 * APB/PBUS clock per the documented model: the live source select and live
 * divider, with the source rate from the caller's board profile. Returns 0 if
 * that source's rate is unknown.
 *
 * This is the right shape for a characterized clock tree and is strictly better
 * than handing `ag32_pbus_hz()` a hoped-for SYSCLK, but the model is NOT yet
 * confirmed on silicon. The two measurements we have (MTIME, UART0) agree to ~3%
 * and are consistent with one APB rate; SPI0 could not be placed at all because
 * its SCK ignores the programmed divider, so it neither confirms nor refutes the
 * single-rate model. Verify against the peripheral you care about.
 */
static inline uint32_t ag32_pbus_hz_actual(const ag32_clk_sources_t *sources) {
    uint32_t sysclk = ag32_sysclk_hz(sources);
    if (!sysclk)
        return 0u;
    return sysclk / ag32_pbus_divider();
}

/*
 * Divide a CALLER-SUPPLIED SYSCLK by the live PBUS divider.
 *
 * This does NOT configure, measure, or validate the clock tree. `sysclk_hz` is
 * taken on trust: pass the frequency the peripheral you are programming is
 * ACTUALLY clocked at, never a datasheet maximum. Passing 248000000 for UART0 on
 * this bench produced ~560 baud where 9600 was requested. Prefer
 * ag32_uart_ref_hz_measured() for UART0 and a measurement for anything else.
 */
static inline uint32_t ag32_pbus_hz(uint32_t sysclk_hz) {
    return sysclk_hz / ag32_pbus_divider();
}

#endif
