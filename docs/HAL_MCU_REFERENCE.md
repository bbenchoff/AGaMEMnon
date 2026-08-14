# AG32 MCU HAL reference

Reference for the **hard RISC-V half** of the AG32VF303CCT6 (`AGRV2KL48`,
LQFP-48): memory map, every peripheral block AGaMEMnon ships a header for, and
the provenance of every claim. The programmable-logic half is documented in
[HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md); the two meet at the
External-AHB window, the MCU↔fabric GPIO bridge, the fabric local interrupts,
and the IO ring.

This page is written for an engineer using the AG32 **without vendor tools**.
Every register table restates addresses and bit positions that are already
present in AGaMEMnon's own `agamemnon/sdk/include/*.h` headers, the public AG32
MCU Reference Manual (2025-05-15), or a cited extracted table. **No offset or
bit position on this page was invented.** Where sources disagree, the
disagreement is recorded as an open question instead of being resolved by guess.

---

## Provenance labels — read this first

Every table row and behavioural claim below carries one of three labels. They
are **not** interchangeable, and a tidy register table never implies a tested
one.

| Label | Meaning |
|---|---|
| **SILICON-QUALIFIED** | Observed working on the L48 bench through an electrically observable oracle, with a record in [`qualification/`](../qualification/) or the dated evidence cited inline. This is a *small* set. |
| **REGISTER-MAP DERIVED** | Taken from published or extracted register semantics and implemented as a clean polling driver. **Never exercised on silicon.** This is *most* of the HAL. |
| **RE-INFERRED / UNPROVEN** | Reverse-engineered, partially observed, or a known negative (something that did *not* work). Includes explicit failures. |

[STATUS.md](STATUS.md) is the authoritative qualification record. If this page
and `STATUS.md` ever disagree, `STATUS.md` wins and this page is stale.

### What is genuinely SILICON-QUALIFIED on the MCU side

| Block | Evidence | Ledger |
|---|---|---|
| CRC0 | CRC-32/MPEG-2 of ASCII `123456789` == `0x0376E6E7` | `hard_peripheral_evidence.jsonl` |
| DMAC0 | single-channel memory-to-memory 4-word SRAM copy | `hard_peripheral_evidence.jsonl` |
| UART0 internal loopback | `CR.LBE` echoed `0xA5`, status clean | `hard_peripheral_evidence.jsonl` |
| **UART0 external TX** | byte-exact `FF 55 41 00` captured on a routed L48 pad (2026-08-14) | bench, 2026-08-14 |
| **I2C0** | 315 transactions; address `0x55` write; correct NACKs with no slave present (2026-08-14) | bench, 2026-08-14 |
| **SPI0** | `11 22 33 44` × 108 and `0x55` × 233 decoded on routed pads, MSB-first with CS framing (2026-08-14) | bench, 2026-08-14 |
| WATCHDOG0 | disabled-state snapshot + supervised timeout warm reset with `RST_CNTL` bit30 exclusively set | `hard_peripheral_evidence.jsonl` |
| CLINT / MTIME | machine-timer interrupt taken, `mcause = 0x80000007` | `hard_peripheral_evidence.jsonl` |
| ADC0/1/2, DAC0/1, CMP0 **unit 1** | 12-bit one-shot conversion against a DAC stimulus; internal DAC0→ADC ch4 and DAC1→ADC ch5 taps | [ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md) |
| MCU→pad GPIO through the fabric IO ring | `GPIO4.1 → PIN_34 → LED1`; four-bit MCU↔fabric inverter loopback over all input combinations | [MCU_PIN_ROUTING.md](MCU_PIN_ROUTING.md) |
| FCB fabric-configuration path | `FCB_STAT == 0x000f0002` after streaming an image; used by every SRAM/flash configuration | [HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md) |
| Flash controller | full backup, 4-KiB sector erase, program, readback byte-compare; boot from an existing compressed-config pointer | [flashboot/](flashboot/FLASH_LAYOUT.md) |
| RV32 SRAM execution | signature, `DEVICE_ID`, `misa`, and SRAM PC read back over SWD | `qualification/README.md` |
| USB **device** path | flash-resident CDC-ACM uploader: enumerate, identify, read, page-erase, write, verify, restore, reset | [USB_CDC_UPLOADER.md](USB_CDC_UPLOADER.md) |
| From-scratch fabric base image | a generated (no vendor canvas byte) base image configures on hardware | [FABRIC_DEFAULT_CANVAS.md](FABRIC_DEFAULT_CANVAS.md) |

Everything else on this page is REGISTER-MAP DERIVED or RE-INFERRED.

> **Documentation drift to be aware of.** The bench results for **UART0
> external TX, I2C0, and SPI0** (all 2026-08-14) are recorded inline above and
> in the header comments of `ag32_spi.h` / `ag32_uart.h` / `ag32_i2c.h`, but the
> summary tables in `STATUS.md` and `PERIPHERAL_CATALOG.md` still describe SPI
> and I2C as *driver-only* and UART0 as *internal loopback only*. Those tables
> are behind, not contradicting. Treat this page's inline evidence and the
> header comments as current for those three blocks.

---

## Part identity

| Property | Value | How to confirm | Provenance |
|---|---|---|---|
| Part / package | AG32VF303CCT6 / `AGRV2KL48`, LQFP-48 | marking | SILICON-QUALIFIED |
| Core | **RV32IMAFC** | `misa` == `0x40801125` | SILICON-QUALIFIED |
| `DEVICE_ID` | `0x40200001` | read `0x03000100` | SILICON-QUALIFIED |
| Main flash | 256 KiB at `0x80000000` | | SILICON-QUALIFIED |
| SRAM | 128 KiB at `0x20000000` | | SILICON-QUALIFIED |
| Debug transport | ARM-style SWD / CMSIS-DAP | | SILICON-QUALIFIED |

The SWD DPIDR is **only the debug transport**. The debug AP is a RISC-V DMI
bridge, so a generic `cortex_m`/`mem_ap` OpenOCD target will not work; you need
an OpenOCD with AGM's `target create riscv -dap` extension
(`agamemnon install-openocd`). See [PROGRAMMING.md](PROGRAMMING.md).

---

## Five hard-won facts

These five cost hours each. Read them before writing any firmware.

### 1. MCU peripheral signals reach package pads *through the eFPGA IO ring*

There is no fixed alternate-function bond map. **A package pad carries a hard
peripheral signal only if the currently loaded fabric image routes it there.**
Enabling UART0 in firmware does not put UART0 on a pin. Loading a different
fabric image can silently move or remove a route you depended on.

Consequences:

- There is deliberately **no** `set_uart_pin(UART0, PIN_n)` API in AGaMEMnon,
  and there cannot be one without a paired fabric artifact.
- `GPIO4.1 → PIN_34 → LED1` works on the reference board because both the
  vendor-default fabric *and* the qualified minimal USB fabric happen to supply
  that route. It is a property of those images, not of the silicon.
- An unknown fabric image invalidates every hard-peripheral pin assumption.
  Keep a recovery transport and load a known fabric before driving a routed
  signal.
- I2C additionally needs open-drain pad behaviour and external pull-ups; CAN
  needs a transceiver; Ethernet needs a PHY. A logical route alone is not
  enough.

Policy and the current route evidence table live in
[MCU_PIN_ROUTING.md](MCU_PIN_ROUTING.md). The pad side (bond map, IO ring,
which tile a pin lands on) is in
[HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md). Provenance: **SILICON-QUALIFIED**
for the specific routes in that table, **RE-INFERRED** for the general absence
of a fixed mux.

### 2. Firmware must FCB-configure the fabric — loading the image is not enough

`agamemnon sram` places a fabric image at `0x20002000`. **That does nothing to
the FPGA by itself.** SRAM is not the configuration memory. Firmware has to
stream the image through the fabric-configuration bridge:

```c
uint32_t stat = ag32_fcb_config((const uint32_t *)0x20002000, 99944u / 4u);
/* 99944/4 == 24986 words: the 8-byte header + the 99,936-byte raw image */
if (stat != FCB_STAT_OK /* 0x000f0002 */) { /* configuration failed */ }
```

Without that call **every pad reads static** and every fabric-dependent
observation is meaningless. `FCB_STAT == 0x000f0002` is the success value
(ACTIVE | INIT_EMB | CFGDONE | CHIP_RSTB | DEVOE — see the FCB section). A CRC
failure reports `STAT_ERR_CRC` instead.

Fabric configuration from *flash* happens at **power-on only** — an ordinary
OpenOCD warm reset does not re-trigger it. Provenance: **SILICON-QUALIFIED**.

### 3. The clock tree is NOT uniform — two measured domains, ~18× apart

This is the single most expensive assumption on the part. Nothing in the
AGaMEMnon SDK configures the clock tree; firmware runs at whatever clock it
inherited. Three measurements on **one** SRAM-loaded, PLL-unconfigured L48 board
in **the same** firmware configuration on 2026-08-14:

| Domain | **Measured** | Method | Provenance |
|---|---|---|---|
| MTIME | **14.08 MHz** | counted against a host `sleep 1000` over the debug link, repeated, consistent | SILICON-QUALIFIED (measurement) |
| UART0 baud reference | **~14.47 MHz** | back-solved from the divisors the driver programmed (`IBRD`=1614, `FBRD`=37) against a 1786 µs logic-analyzer bit time (560 baud): `560 × 16 × 1614.578` | SILICON-QUALIFIED (measurement) |
| SPI0 shift-clock reference | **~258 MHz** | SCK measured directly at **1,294,708 Hz** with `ag32_spi_init(SPI0, 200)` (CSN 40,626 Hz, MOSI 323,771 Hz); corroborated by ~20.3k 4-byte transfers/s | SILICON-QUALIFIED (measurement) |

MTIME and UART0 agree with each other. **SPI0 agrees with neither** — it runs
close to the part's nominal ~248 MHz system clock.

**The concrete bug:** firmware called `ag32_pbus_hz(248000000)` and then
`ag32_uart_init(UART0, pbus, 9600)`. The UART transmitted at **~560 baud** —
roughly 17× slow — because the returned value described neither UART0's
reference clock nor anything else the UART consumes.

Read these as **MEASURED OBSERVATIONS of individual peripherals in one
configuration on one board**. None is a datasheet constant, and there is no
single chip-wide number to quote. The documented model
(`APB = SYSCLK / (PBUS_DIV + 1)`, shared by every APB peripheral) *cannot*
produce a UART/SPI ratio of ~18, so either the model or our reading of it is
incomplete. Two caveats on the numbers themselves: the register state that
produced them was not captured, and the SPI figure multiplies a measured SCK by
a programmed divider of 200, which is not one of the documented powers of two —
read it as "SPI0 runs from a fast, roughly system-rate clock", not as an exact
reference frequency.

What to actually do:

- **UART0**: use `ag32_uart_ref_hz_measured()`. It is the only APB reference
  clock that has been measured.
- **Anything else**: measure it. If you must guess, guessing the UART's domain
  is a **cross-domain assumption that SPI0 already falsifies**; record the value
  you used and publish `CLK_CNTL` / `PBUS_DIVIDER` / `MTIME_PSC` alongside your
  results so the domain can be re-derived. `i2c_probe.c` and `can_selftest.c`
  do exactly this and label the assumption in-source.
- Never pass a datasheet maximum to a baud/prescaler solver.

Full narrative: [MCU_CLOCKS.md](MCU_CLOCKS.md). This page is deliberately
consistent with it.

### 4. `ag32_spi_write` sub-word payloads are left-justified

The SPI controller shifts the **HIGH-order** bytes of the 32-bit `PHASE_DATA`
word first. A payload passed in the natural low lane never reaches the wire.
Measured 2026-08-14 with a logic analyzer on routed L48 pads:

| Call | Observed on the pins | Provenance |
|---|---|---|
| `ag32_spi_write(SPI0, 0x55, 1, …)` *(pre-fix)* | SCK/CSN clocked normally, **MOSI stayed driven LOW** (read 0 under both an external pulldown and pullup, so actively driven), every decoded word `0x00` | SILICON-QUALIFIED (negative) |
| `ag32_spi_write(SPI0, 0xFF000000, 1, …)` | MOSI toggled at 262 Hz, matching SCK/CSN | SILICON-QUALIFIED |
| `ag32_spi_write(SPI0, 0x11223344, 4, …)` | MOSI toggled at 374 Hz; SCK edge rate rose 262 → 937 Hz, consistent with 4× the clocks | SILICON-QUALIFIED |
| `ag32_spi_write(SPI0, 0x55, 1, …)` *(post-fix, in a loop)* | **233 decoded words, every one `0x55`** (histogram `{0x55: 233}`); 8-channel PIO capture at 12 MHz, decoded MSB-first with CS framing, SCK 1.30 MHz | SILICON-QUALIFIED |

`ag32_spi.h` therefore left-justifies sub-word TX payloads
(`data << (8 * (4 - bytes))`) so the public API does the obvious thing: passing
`0x55` with `bytes=1` puts `0x55` on the wire, and multi-byte payloads go out
most-significant byte first. A 4-byte payload is unchanged.

Two deliberate non-claims:

1. **`CTRL` bit 10 is not flipped.** The vendor register description names it an
   endianness select, and the vendor's own flash driver — with the same bit set —
   packs command bytes in the LOW lane, which is the *opposite* of what this
   board measured. The bit's real meaning is therefore **not established**
   (RE-INFERRED / UNPROVEN). The left-justification compensates for the
   behaviour observed in the configuration this SDK ships. Re-measure before
   trusting either reading if you reconfigure that bit.
2. **RX sub-word byte-lane placement is uncharacterized** (RE-INFERRED /
   UNPROVEN). `ag32_spi_write_read()` returns the raw `PHASE_DATA` word,
   unshifted. Do **not** assume RX mirrors TX.

Also note: the 4-byte capture decoded as `20 07 0A 01 28 00` rather than
`11 22 33 44`. The host decoder's CPOL/CPHA was almost certainly wrong, so that
byte sequence is **not** evidence about lane order. The load-bearing evidence is
the toggling-versus-stuck-at-zero comparison.

### 5. CAN0 is alive but no frames reach the wire yet

Register readback proves CAN0 is clocked and configurable. Frame transmission
does not work. Both halves are true and must not be merged.

| Observation | Verdict | Provenance |
|---|---|---|
| `MOD` reads back `0x01`, then `0x04` | the mode register takes writes; the core is clocked | SILICON-QUALIFIED |
| `BTR0`=`0x3F`, `BTR1`=`0x7F`, `OCR`=`0x1A` read back as written | bit timing and output control are configurable | SILICON-QUALIFIED |
| `SR` goes `0x3C` with **TBS set**, then `0x30` on a transmit request | the transmit buffer *does* release; the controller accepts the request | SILICON-QUALIFIED |
| TX pad idles correctly **recessive-high** | the output driver is sane | SILICON-QUALIFIED |
| **No bits shift out** | frame transmission does not work | RE-INFERRED / UNPROVEN |
| `TXFRAME` (offset `0x40`) read back `0x00` after writing `0x08` | the transmit-buffer layout / frame format is the open question | RE-INFERRED / UNPROVEN |

**Correction to an earlier belief:** "TBS never asserts" was wrong. It was a
bounded wait shorter than the ~25 ms frame time at `BRP=63`. TBS does assert.

The open question is the **TX buffer layout / frame format**, not clocking, not
bit timing, and not the pad. A real bus additionally needs an external
transceiver, which is absent from the bench.

---

## Address-space map

| Region | Base | Contents | Provenance |
|---|---|---|---|
| Boot ROM | `0x00010000` | mask ROM (option-byte read, fabric configuration, UART bootloader) | REGISTER-MAP DERIVED |
| CLINT | `0x02000000` | `MSIP`, `MTIMECMP`, `MTIME` | SILICON-QUALIFIED |
| System control / RCC | `0x03000000` | reset, clock, power, MTIME prescaler, bus gating, `DEVICE_ID` | partially SILICON-QUALIFIED |
| PLIC | `0x0C000000` | priority / enable / claim for 44 sources | REGISTER-MAP DERIVED |
| SRAM | `0x20000000`, 128 KiB (`0x20000` bytes) | data + SRAM-executed firmware | SILICON-QUALIFIED |
| RTC / backup domain | `0x40000000` | RTC, backup registers, IWDG at `+0x34` | config path only |
| Flash controller | `0x40001000` | erase / program / option control | SILICON-QUALIFIED |
| APB peripherals | `0x40010000` … `0x4002Cxxx` | FCB, watchdog, SPI, GPIO, timers, UART, CAN, I2C | mixed |
| AHB peripherals | `0x41000000` … `0x41040000` | DMAC0, USB0, CRC0, MAC0 | mixed |
| **External AHB / fabric window** | `0x60000000` | fabric slaves **and** the analog IP (ADC/DAC/CMP) | mixed |
| Main flash (XIP) | `0x80000000`, 256 KiB (`0x40000` bytes) | code/data | SILICON-QUALIFIED |
| Option bytes | `0x81000000` | boot policy + fabric-image pointers | REGISTER-MAP DERIVED |

Header: `agamemnon/sdk/include/ag32_device.h`.

### Peripheral base addresses (all from `ag32_device.h`)

| Block | Base | Count | Header | Provenance |
|---|---|---|---|---|
| RTC / backup | `0x40000000` | 1 | `ag32_rtc.h`, `ag32_iwdg.h` | REGISTER-MAP DERIVED (config path SILICON-QUALIFIED) |
| Flash controller | `0x40001000` | 1 | — (driven by `agamemnon/program.py`) | SILICON-QUALIFIED |
| FCB0 | `0x40010000` | 1 | `ag32.h` | SILICON-QUALIFIED |
| WATCHDOG0 | `0x40011000` | 1 | `ag32_watchdog.h` | SILICON-QUALIFIED |
| SPI0, SPI1 | `0x40012000`, `0x40013000` | 2 | `ag32_spi.h` | SPI0 SILICON-QUALIFIED; SPI1 REGISTER-MAP DERIVED |
| GPIO0…GPIO9 | `0x40014000` + `n·0x1000` | 10 | `ag32.h` (GPIO4 macros) | GPIO4 SILICON-QUALIFIED; rest REGISTER-MAP DERIVED |
| TIMER0, TIMER1 | `0x4001E000`, `0x4001F000` | 2 | `ag32.h` (raw macros) | REGISTER-MAP DERIVED |
| GPTIMER0…4 | `0x40020000` + `n·0x1000` | 5 | `ag32_gptimer.h` | REGISTER-MAP DERIVED |
| UART0…UART4 | `0x40025000` + `n·0x1000` | 5 | `ag32_uart.h` | UART0 SILICON-QUALIFIED; UART1–4 REGISTER-MAP DERIVED |
| CAN0 | `0x4002A000` | 1 | `ag32_can.h` | mixed — see fact 5 |
| I2C0, I2C1 | `0x4002B000`, `0x4002C000` | 2 | `ag32_i2c.h` | I2C0 SILICON-QUALIFIED; I2C1 REGISTER-MAP DERIVED |
| DMAC0 | `0x41000000` | 1 | `ag32_dma.h` | mem-to-mem SILICON-QUALIFIED |
| USB0 | `0x41001000` | 1 | — (no MMIO driver shipped) | device path SILICON-QUALIFIED via CDC uploader |
| CRC0 | `0x41002000` | 1 | `ag32_crc.h` | SILICON-QUALIFIED |
| MAC0 | `0x41040000` | 1 | `ag32_mac.h` | REGISTER-MAP DERIVED |
| ADC0/1/2 | `0x60000000` / `+0x1000` / `+0x2000` | 3 | `ag32_adc.h` | SILICON-QUALIFIED subset |
| DAC0/1 | `0x60003000`, `0x60004000` | 2 | `ag32_dac.h` | SILICON-QUALIFIED subset |
| CMP0 | `0x60005000` | 1 | `ag32_comparator.h` | unit 1 SILICON-QUALIFIED; unit 2 UNPROVEN |

Instance-count macros (`AG32_UART_COUNT`, `AG32_GPIO_COUNT`, …) are in
`ag32_device.h`; the drivers use them to reject an out-of-range instance
pointer.

---

## System control / RCC — `0x03000000`

Header: **`agamemnon/sdk/include/ag32_sysctl.h`** (recently revised with the
measured clock data). Legacy aliases in `ag32.h`.

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x00` | `BOOT_MODE` | BOOT0/BOOT1 pin state | REGISTER-MAP DERIVED |
| `0x04` | `RST_CNTL` | reset cause flags + software/external/FCB reset control | bit30 SILICON-QUALIFIED |
| `0x08` | `PWR_CNTL` | power control | REGISTER-MAP DERIVED |
| `0x0C` | `CLK_CNTL` | source select, HSE/PLL enable + ready, flash SCLK dividers | read path SILICON-QUALIFIED |
| `0x18` | `MISC_CNTL` | miscellaneous / debug control | REGISTER-MAP DERIVED |
| `0x30` | `MTIME_PSC` | MTIME prescaler + two control bits | REGISTER-MAP DERIVED |
| `0x34` | `MTIME_COUNTER` | MTIME counter view | REGISTER-MAP DERIVED |
| `0x38` | `PBUS_DIVIDER` | APB divider | REGISTER-MAP DERIVED |
| `0x40` | `APB_RESET` | per-peripheral APB reset | REGISTER-MAP DERIVED (used by every driver `init`) |
| `0x50` | `AHB_RESET` | per-peripheral AHB reset | REGISTER-MAP DERIVED |
| `0x60` | `APB_ENABLE` | per-peripheral APB clock gate | SILICON-QUALIFIED (FCB, GPIO4, TIMER0) |
| `0x70` | `AHB_ENABLE` | per-peripheral AHB clock gate | SILICON-QUALIFIED (CRC0, DMAC0) |
| `0x80` | `APB_DBGSTOP` | APB clock stop under debug | REGISTER-MAP DERIVED |
| `0x100` | `DEVICE_ID` | `0x40200001` | SILICON-QUALIFIED |

The vendor manual additionally names `BUS_CNTL`, `SWJ_CNTL` (JTAG/SWD pin
control), wakeup trigger/pending, and `RTCCR` calibration in this block.
AGaMEMnon does not ship offsets for those — **REGISTER-MAP DERIVED, offsets not
recorded here.** Do not guess them.

### `APB_ENABLE` / `APB_RESET` bit assignments (`0x60` / `0x40`)

| Bits | Macro | Peripheral |
|---|---|---|
| 0 | `AG32_APB_FCB0` | FCB0 |
| 1 | `AG32_APB_WATCHDOG0` | WATCHDOG0 |
| 2 | `AG32_APB_SPI0` | SPI0 |
| 3 | `AG32_APB_SPI1` | SPI1 |
| 4 + n | `AG32_APB_GPIO(n)` | GPIO0…GPIO9 (bits 4–13) |
| 14 + n | `AG32_APB_TIMER(n)` | TIMER0/1 (bits 14–15) |
| 16 + n | `AG32_APB_GPTIMER(n)` | GPTIMER0…4 (bits 16–20) |
| 21 + n | `AG32_APB_UART(n)` | UART0…UART4 (bits 21–25) |
| 26 | `AG32_APB_CAN0` | CAN0 |
| 27 + n | `AG32_APB_I2C(n)` | I2C0/1 (bits 27–28) |

Provenance: **REGISTER-MAP DERIVED**, except the FCB0 (bit 0), GPIO4 (bit 8),
and TIMER0 (bit 14) gates which are exercised on silicon.

### `AHB_ENABLE` / `AHB_RESET` bits (`0x70` / `0x50`)

| Bit | Macro | Peripheral | Provenance |
|---|---|---|---|
| 0 | `AG32_AHB_DMAC0` | DMAC0 | SILICON-QUALIFIED |
| 1 | `AG32_AHB_USB0` | USB0 | REGISTER-MAP DERIVED |
| 2 | `AG32_AHB_CRC0` | CRC0 | SILICON-QUALIFIED |
| 3 | `AG32_AHB_MAC0` | MAC0 | REGISTER-MAP DERIVED |

### `CLK_CNTL` (`0x0C`)

| Field | Bits | Meaning | Provenance |
|---|---|---|---|
| source select | `[1:0]` | `0` HSI, `1` HSE, `2` PLL, `3` external/fabric | REGISTER-MAP DERIVED (read path exercised) |
| `HSE_ON` | 2 | external oscillator enable | REGISTER-MAP DERIVED |
| `HSE_BYPASS` | 3 | bypass (clock input rather than crystal) | REGISTER-MAP DERIVED |
| `HSE_READY` | 4 | HSE ready (read-only) | SILICON-QUALIFIED (polled by `clkcfg_stub.c`) |
| `PLL_ON` | 5 | PLL enable | REGISTER-MAP DERIVED |
| `PLL_READY` | 6 | PLL locked (read-only) | SILICON-QUALIFIED (polled by `clkcfg_stub.c`) |
| flash SCLK div (high) | `[11:8]` | flash SPI divider, high field | REGISTER-MAP DERIVED |
| flash SCLK div (low) | `[15:12]` | flash SPI divider, low field | REGISTER-MAP DERIVED |

**The two flash SPI divider fields must hold equal safe values before `SYSCLK`
is raised.** That is one reason no runtime clock-switch setter is exposed.

`PBUS_DIVIDER[3:0]`: APB = `SYSCLK / (field + 1)`, field `0..15`.
`MTIME_PSC[15:0]`: MTIME ticks at `SYSCLK / (field + 1)`, plus `MTIME_PSC_OFF`
(bit 30) and `MTIME_PSC_DEBUG_STOP` (bit 31).

### Reset cause

`RST_CNTL` bit **30** is `SYS_RSTF_WDOG`. **SILICON-QUALIFIED:** after a
supervised WATCHDOG0 timeout, the host DAP read `RST_CNTL == 0x40000000` —
bit 30 set *exclusively*. Other reset-cause bits in this register are
REGISTER-MAP DERIVED and their positions are not recorded here.

### Usage pattern

```c
#include "ag32.h"

/* Silicon can tell you WHICH source drives SYSCLK and by what divider.
   It cannot tell you the absolute frequency of a crystal or an untrimmed RC
   oscillator, so you supply those. A 0 entry makes the helpers return 0
   rather than invent a rate. */
static const ag32_clk_sources_t sources = {
    .hsi_hz = 0,            /* measure it; do not assume 10 MHz  */
    .hse_hz = 8000000u,     /* reference-board crystal, board data */
    .pll_hz = 0,            /* set by the FABRIC bitstream, not an MCU register */
    .ext_hz = 0,
};

uint32_t src  = ag32_sysclk_source();     /* AG32_CLK_SOURCE_* */
uint32_t pdiv = ag32_pbus_divider();      /* 1..16, live */
uint32_t apb  = ag32_pbus_hz_actual(&sources);  /* documented model, unconfirmed */

/* For UART0, use the only measured APB reference: */
ag32_uart_init(AG32_UART0, ag32_uart_ref_hz_measured(), 115200u);
```

### Gotchas

- **No runtime clock-switch API is offered, deliberately.** The transition
  sequence is unqualified on this fixture, the PLL *rate* is not an MCU-side
  programmable (it is fixed by the fabric bitstream's `(SYSCLK,HSE)` pair), and
  shipping an unverified setter can strand the part.
- **`ag32_fcb_config()` has a clock side effect.** Its first line clears the
  `CLK_CNTL` source select plus the HSE and PLL enables
  (`0x27 == AG32_CLK_SOURCE_MASK | AG32_CLK_HSE_ON | AG32_CLK_PLL_ON`),
  selecting the reset-default source for the duration of the transfer and
  **leaving it selected**. Nothing in the SDK switches back. Do not derive a bit
  rate from an assumed `SYSCLK` afterwards.
- `ag32_pbus_hz(sysclk_hz)` divides a number **you** supplied. It cannot detect
  a wrong argument. Passing `248000000` produced the ~560-baud defect.
- The documented safe transition order (manual): reset starts on HSI → enable
  the target oscillator/PLL → wait for `HSE_RDY`/`PLL_RDY` → switch only after
  ready → never disable the source currently driving `SYSCLK` → set both flash
  divider fields to a safe equal value before increasing `SYSCLK` → switch back
  to HSI before disabling HSE or PLL. `examples/firmware/clkcfg_stub.c`
  implements a working instance of this (it also pulses `PLL_ON` if lock is slow).

---

## CLINT / MTIME and interrupts

Headers: `ag32.h` (`ag32_mtime`, `ag32_mtime_delay`),
`agamemnon/sdk/include/ag32_interrupt.h`.

### CLINT — `0x02000000`

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x0000` | `MSIP` | machine software interrupt pending | REGISTER-MAP DERIVED (exercised by `software_interrupt.c`, not ledgered) |
| `0x4000` | `MTIMECMP_LO` | 64-bit compare, low half | SILICON-QUALIFIED |
| `0x4004` | `MTIMECMP_HI` | 64-bit compare, high half | SILICON-QUALIFIED |
| `0xBFF8` | `MTIME_LO` | 64-bit free-running counter, low half | SILICON-QUALIFIED |
| `0xBFFC` | `MTIME_HI` | high half | SILICON-QUALIFIED |

MTIME counts the **system clock**, which makes it the yardstick for
frequency work — but see fact 3: it measured **14.08 MHz** in the SRAM-loaded,
PLL-unconfigured default, not 248 MHz.

`ag32_mtime()` re-reads the high half to survive a low-half rollover.
`ag32_mtimecmp_set()` writes `HI = UINT32_MAX` first so a 64-bit replacement
cannot produce a transient early match on RV32.

**SILICON-QUALIFIED:** `MTIMECMP` fired and the trap was taken with
`mcause == 0x80000007`.

### Two interrupt controllers, not one

| Path | Sources | Enabled via | Provenance |
|---|---|---|---|
| **CLINT** | machine software (cause 3), machine timer (cause 7) | `mie` `MSIE`/`MTIE` | timer SILICON-QUALIFIED |
| **CLINT local** | **fabric** `local_int[3:0]` → local causes **16–19** | `mie` bits `16 + n` (`AG32_MIE_LOCAL(n)`) — **not** the PLIC | SILICON-QUALIFIED subset — see [HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md) |
| **PLIC** | the 44 maskable peripheral/fabric sources | PLIC enable + `mie` `MEIE` (cause 11) | REGISTER-MAP DERIVED |

Some older vendor overview diagrams label the CPU interrupt block "ECLIC". The
maskable peripheral sources use a **PLIC** (`ag32_interrupt.h`, following AG32
MCU Reference Manual ch. 6).

### PLIC — `0x0C000000`, 44 sources, 16 priority levels

| Address | Function |
|---|---|
| `base + 4·irq` | per-source priority (0…15) |
| `base + 0x1000 + 4·word` | pending bitmap |
| `base + 0x2000 + 4·word` | enable bitmap |
| `base + 0x200000` | priority threshold |
| `base + 0x200004` | claim (read) / complete (write) |

Provenance: **REGISTER-MAP DERIVED.** No silicon claim on external PLIC
delivery.

### IRQ numbers (`enum ag32_irq`)

| IRQ | Source | IRQ | Source | IRQ | Source |
|---|---|---|---|---|---|
| 1 | FLASH | 16 | GPIO9 | 31 | I2C1 |
| 2 | RTC | 17 | TIMER0 | 32 | DMAC0 |
| 3 | FCB0 | 18 | TIMER1 | 33 | DMAC0_TC |
| 4 | WATCHDOG0 | 19 | GPTIMER0 | 34 | DMAC0_ERROR |
| 5 | SPI0 | 20 | GPTIMER1 | 35 | USB0 |
| 6 | SPI1 | 21 | GPTIMER2 | 36 | MAC0 |
| 7 | GPIO0 | 22 | GPTIMER3 | 37 | EXT0 |
| 8 | GPIO1 | 23 | GPTIMER4 | 38 | EXT1 |
| 9 | GPIO2 | 24 | UART0 | 39 | EXT2 |
| 10 | GPIO3 | 25 | UART1 | 40 | EXT3 |
| 11 | GPIO4 | 26 | UART2 | 41 | EXT4 |
| 12 | GPIO5 | 27 | UART3 | 42 | EXT5 |
| 13 | GPIO6 | 28 | UART4 | 43 | EXT6 |
| 14 | GPIO7 | 29 | CAN0 | 44 | EXT7 |
| 15 | GPIO8 | 30 | I2C0 | | |

`EXT0…EXT7` (37–44) are **RE-INFERRED / UNPROVEN**: they are treated as
*unconnected hypotheses* until a fabric path to them is proven. Do not build a
design that depends on `EXT_INTx`.

### Trap handling

Override the weak startup symbol:

```c
void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval);
```

`agamemnon/sdk/startup.S` installs a direct-mode machine trap entry and
preserves caller-saved registers. Rules:

- A **PLIC** handler must clear the peripheral's own interrupt condition **and**
  write the claimed source ID back to the completion register.
- A **recoverable exception** handler must advance `mepc` past the faulting
  instruction before returning (e.g. +4 past an `ECALL`) — otherwise it
  re-faults forever. `examples/riscv_mcu/exception_mailbox.c` demonstrates it.

Exception codes are in `enum ag32_exception`. Note **`LOAD_ACCESS` = 5** and
**`STORE_ACCESS` = 7**: those are the codes a **misaligned CPU access to the
fabric window** produces. The hard core faults deterministically and the access
never reaches the fabric — see [HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md).
Provenance: **SILICON-QUALIFIED**.

---

## GPIO — `0x40014000` + `n·0x1000`, GPIO0…GPIO9

Headers: `ag32.h` (GPIO4 macros only — there is no typed `ag32_gpio.h` yet).
This is a **PL061-class** block.

### Register map

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x000` … `0x3FC` | `DATA[256]` | **address-masked data.** Address bits `[9:2]` are a bit mask: `base + (mask << 2)` reads/writes only the masked pins | SILICON-QUALIFIED (GPIO4) |
| `0x400` | `DIR` | direction, 1 = output | SILICON-QUALIFIED (GPIO4) |
| `0x404` | `IS` | interrupt sense (level vs edge) | REGISTER-MAP DERIVED |
| `0x408` | `IBE` | both-edge select | REGISTER-MAP DERIVED |
| `0x40C` | `IEV` | interrupt event (polarity / rising) | REGISTER-MAP DERIVED |
| `0x410` | `IE` | interrupt mask/enable | REGISTER-MAP DERIVED |
| `0x414` | `RIS` | raw interrupt status | **RE-INFERRED** — see note |
| `0x418` | `MIS` | masked interrupt status | **RE-INFERRED** — see note |
| `0x41C` | `IC` | interrupt clear | **RE-INFERRED** — see note |
| `0x420` | `AFSEL` | alternate-function select | SILICON-QUALIFIED (GPIO4, cleared for software output) |

> **Open question — GPIO interrupt-register offsets.**
> [PERIPHERAL_CATALOG.md](PERIPHERAL_CATALOG.md) names `RIS`, `MIS`, and `IC`
> for this block but gives explicit offsets only for `IS`/`IBE`/`IEV`/`IE`
> (`0x404`–`0x410`) and `AFSEL` (`0x420`). No AGaMEMnon header defines
> `RIS`/`MIS`/`IC`. The `0x414` / `0x418` / `0x41C` values above are the
> **PL061 standard layout** implied by the surrounding offsets, not an
> independently recovered AG32 fact. Verify against a primary source before
> relying on them. The GPIO interrupt path has **no** silicon record at all.

### AFSEL — alternate-function muxing

`AFSEL` has exactly **one** documented job, and it is narrower than an
STM32-style pin mux:

| `AFSEL` bit | Effect |
|---|---|
| `0` | software control: the GPIO `DATA` and `DIR` registers own the line |
| `1` | hardware control: the surrounding system (a hard peripheral) drives that GPIO line |

**It does not identify *which* peripheral** — there is no UART/SPI/I2C selector
value. And it does **not** prove the signal reaches a package pin: that second
mapping is a property of the loaded fabric image and the package bond map
(fact 1). Provenance: **REGISTER-MAP DERIVED** for the semantics,
**SILICON-QUALIFIED** for the `AFSEL = 0` software-output path on GPIO4.

### Usage pattern

```c
ag32_apb_enable(AG32_APB_GPIO(4));

GPIO4_AFSEL = 0;                    /* software control of the whole port   */
GPIO4_DIR   = BOARD_LED_MASK;       /* 0x1E == bits 1..4 as outputs         */

/* Masked write: only bits in the mask are affected. */
GPIO4_DATA(BOARD_LED_MASK) = BOARD_LED_MASK;   /* all four LEDs on  */
GPIO4_DATA(1u << 1)        = 0;                /* LED1 off, others untouched */

/* Masked read of one bit. */
uint32_t led1 = GPIO4_DATA(1u << 1);
```

### Board mapping (reference L48 board)

| Signal | GPIO | Package pin | Provenance |
|---|---|---|---|
| LED1 | GPIO4.1 | `PIN_34` | SILICON-QUALIFIED |
| LED2 | GPIO4.2 | `PIN_33` | vendor-board mapping, REGISTER-MAP DERIVED |
| LED3 | GPIO4.3 | `PIN_32` | vendor-board mapping, REGISTER-MAP DERIVED |
| LED4 | GPIO4.4 | `PIN_31` | vendor-board mapping, REGISTER-MAP DERIVED |
| Button | — | `PIN_29` | see below |

`agamemnon/sdk/include/ag32_board_l48.h` carries these as
`AG32_BOARD_LED*_GPIO_BIT` / `AG32_BOARD_LED*_PACKAGE_PIN`. Only **LED1** has an
independent minimal-fabric silicon record; the other three come from the factory
fabric.

> **`PIN_29` is the board button.** It is a fabric-IO pad (`X0Y2`, z4) and it
> must **never** be driven as an output. See the bond map in
> [HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md).

### Gotchas

- "Blink all GPIOs" is **not** a safe test. Only drive nets whose electrical
  destination you know.
- GPIO4.1 doubles as the qualified **synchronous reset source** for fabric
  register banks. Toggling it can reset fabric state.
- Each GPIO instance has its own PLIC IRQ (7…16). The interrupt path is
  unqualified.

---

## UART0…UART4 — `0x40025000` + `n·0x1000`

Header: **`agamemnon/sdk/include/ag32_uart.h`**. This is a **PL011-class**
controller.

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x000` | `DR` | data; read also returns error bits in `[11:8]` | SILICON-QUALIFIED (UART0) |
| `0x004` | `RSR_ECR` | receive status / error clear | REGISTER-MAP DERIVED |
| `0x018` | `FR` | flags (read-only) | SILICON-QUALIFIED (UART0) |
| `0x024` | `IBRD` | integer baud divisor | SILICON-QUALIFIED (UART0) |
| `0x028` | `FBRD` | fractional baud divisor (6 bits) | SILICON-QUALIFIED (UART0) |
| `0x02C` | `LCR_H` | line control; **a write here latches `IBRD`/`FBRD`** | SILICON-QUALIFIED (UART0) |
| `0x030` | `CR` | control | SILICON-QUALIFIED (UART0) |
| `0x034` | `IFLS` | interrupt FIFO levels | REGISTER-MAP DERIVED |
| `0x038` | `IMSC` | interrupt mask | REGISTER-MAP DERIVED |
| `0x03C` | `RIS` | raw interrupt status | REGISTER-MAP DERIVED |
| `0x040` | `MIS` | masked interrupt status | REGISTER-MAP DERIVED |
| `0x044` | `ICR` | interrupt clear (`0x7FF` clears all) | REGISTER-MAP DERIVED |
| `0x048` | `DMACR` | DMA control | REGISTER-MAP DERIVED |

### `FR` flags

| Bit | Name | Meaning |
|---|---|---|
| 0 | `CTS` | clear-to-send |
| 3 | `BUSY` | transmitter busy |
| 4 | `RXFE` | receive FIFO empty |
| 5 | `TXFF` | transmit FIFO full |
| 6 | `RXFF` | receive FIFO full |
| 7 | `TXFE` | transmit FIFO empty |

### `LCR_H` / `CR` / `DMACR` bits

| Register | Bit(s) | Name |
|---|---|---|
| `LCR_H` | 0 | `BRK` send break |
| `LCR_H` | 1 | `PEN` parity enable |
| `LCR_H` | 2 | `EPS` even parity select |
| `LCR_H` | 3 | `STP2` two stop bits |
| `LCR_H` | 4 | `FEN` FIFO enable |
| `LCR_H` | `[6:5]` | `WLEN` word length: `0`=5, `1`=6, `2`=7, `3`=8 bits |
| `CR` | 0 | `UARTEN` |
| `CR` | 7 | `LBE` internal loopback |
| `CR` | 8 | `TXE` |
| `CR` | 9 | `RXE` |
| `CR` | 14 | `RTSEN` |
| `CR` | 15 | `CTSEN` |
| `DMACR` | 0 / 1 / 2 | `RX` / `TX` / `DMAONERR` |

Provenance for the bit tables: **REGISTER-MAP DERIVED**, with `UARTEN`, `TXE`,
`RXE`, `LBE`, `FEN`, and `WLEN_8` exercised on silicon.

### Baud arithmetic

`ag32_uart_init()` computes `divisor64 = round(uart_clock_hz × 4 / baud)`, then
`IBRD = divisor64 >> 6` and `FBRD = divisor64 & 0x3F`, and writes `LCR_H` to
latch them. The 32-bit intermediate is safe because AG32 clocks are below 1 GHz;
the function returns `-1` rather than overflowing.

### Usage pattern

```c
/* Use the ONLY measured APB reference. Never a datasheet maximum. */
if (ag32_uart_init(AG32_UART0, ag32_uart_ref_hz_measured(), 115200u) == 0) {
    ag32_uart_putc(AG32_UART0, 'A', 100000u);
    ag32_uart_flush(AG32_UART0);

    uint8_t rx;
    int rc = ag32_uart_getc(AG32_UART0, &rx, 100000u);
    /* rc == -1 timeout, -2 framing/parity/break/overrun (DR[11:8] set) */
}
```

### Silicon evidence

| Claim | Provenance |
|---|---|
| Internal `LBE` loopback echoed `0xA5`, `uart_status = 0` | SILICON-QUALIFIED |
| **External TX byte-exact `FF 55 41 00`** on a routed L48 pad (2026-08-14) | SILICON-QUALIFIED |
| UART0 baud reference measured **~14.47 MHz** | SILICON-QUALIFIED (measurement) |
| Requested 9600 baud transmitted at **~560 baud** with an assumed 248 MHz clock | SILICON-QUALIFIED (negative — the defect of fact 3) |
| External RX, hardware flow control, UART1…UART4 | REGISTER-MAP DERIVED |
| Baud accuracy good enough to interoperate with another device | **not claimed.** The measured reference is a ~1 % back-solve, fine for loopback and bring-up, **not** for a link that must interoperate |

### Gotchas

- **`IBRD`/`FBRD` only take effect when `LCR_H` is written.** Program them, then
  write `LCR_H`.
- Reaching a package pad needs a fabric route (fact 1). UART0's mask-ROM
  `TX/RX` are documented on `PIN_30`/`PIN_31`, but that harness is not
  qualified.
- `ag32_uart_getc()` returns `-2` and clears `RSR_ECR` when `DR[11:8]` shows an
  error; the byte is discarded.

---

## SPI0, SPI1 — `0x40012000`, `0x40013000`

Header: **`agamemnon/sdk/include/ag32_spi.h`** (recently revised — read its
header comment). This is **not** a plain shift register: it is a
**multi-phase command sequencer**. A transfer is a list of up to eight phases,
each shifting 1…4 bytes (or a DMA-fed run) as TX, dummy-TX, RX, or poll.

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x00` | `CTRL` | global control (`SPCR`) | SILICON-QUALIFIED (SPI0) |
| `0x10` … `0x2C` | `PHASE_CTRL[0..7]` | per-phase type / byte count / wire width | SILICON-QUALIFIED (phases 0,1 on SPI0) |
| `0x30` … `0x4C` | `PHASE_DATA[0..7]` | per-phase payload | SILICON-QUALIFIED (phases 0,1 on SPI0) |

### `CTRL` bits

| Bit(s) | Name | Meaning | Provenance |
|---|---|---|---|
| 0 | `START` | launch the transfer | SILICON-QUALIFIED |
| 1 | `DONE` | transfer complete | SILICON-QUALIFIED |
| 2 | `ERROR` | transfer error | REGISTER-MAP DERIVED |
| `[7:4]` | `PHASES(n)` | number of phases minus one | SILICON-QUALIFIED (1 and 2 phases) |
| 8 | `DMA` | DMA-fed phase | REGISTER-MAP DERIVED |
| 9 | `WP` | write protect | REGISTER-MAP DERIVED |
| 10 | `LITTLE` / `ENDIAN` | vendor's byte-order select — **meaning NOT established** | **RE-INFERRED / UNPROVEN** |
| `[19:12]` | `DIV(n)` | SCK divider; `0` means 256 | SILICON-QUALIFIED at 8 and 200 |
| 20 | `IRQ` | interrupt enable | REGISTER-MAP DERIVED |
| 31 | `RESET` | soft reset | SILICON-QUALIFIED |

### `PHASE_CTRL` fields

| Bits | Name | Values |
|---|---|---|
| `[5:4]` | phase type | `0` TX, `1` DUMMY, `2` RX, `3` POLL |
| `[19:8]` | byte count | 12-bit |
| `[21:20]` | wire width | `0` SINGLE, `1` DUAL, `2` QUAD |

Provenance: **REGISTER-MAP DERIVED**, with TX and RX single-wire 1–4-byte phases
exercised on silicon.

### Clock domain

`SPI0`'s shift-clock reference measured **~258 MHz** (fact 3) — a *different,
fast* domain from the UART's ~14.5 MHz. `SCK = reference / divider`. The
documented divider values are the powers of two `2, 4, 8, 16, 32, 64, 128, 256`;
`ag32_spi_init()` accepts other even values, but **how the hardware treats an
out-of-set divider is uncharacterized** (RE-INFERRED). Measure SCK if you need a
real bit rate.

### Usage pattern

```c
ag32_spi_init(AG32_SPI0, 8u);      /* divider: SCK = fast-domain / 8 */

/* Payload is passed RIGHT-justified; the driver left-justifies it because the
   controller shifts the HIGH-order bytes of PHASE_DATA first (fact 4). */
ag32_spi_write(AG32_SPI0, 0x55u, 1u, 200000u);          /* 0x55 on MOSI   */
ag32_spi_write(AG32_SPI0, 0x11223344u, 4u, 200000u);    /* MSB first      */

uint32_t rx;   /* RAW phase word — sub-word RX lane placement UNMEASURED */
ag32_spi_write_read(AG32_SPI0, 0x9Fu, 1u, &rx, 1u, 200000u);
```

### Silicon evidence

| Claim | Provenance |
|---|---|
| `11 22 33 44` × 108 decoded on routed pads | SILICON-QUALIFIED |
| `0x55` × 233 decoded after the lane fix (histogram `{0x55: 233}`) | SILICON-QUALIFIED |
| **MSB-first**, **CS framing required** for a correct decode | SILICON-QUALIFIED |
| SCK 1,294,708 Hz at divider 200 | SILICON-QUALIFIED (measurement) |
| Sub-word TX payloads must be left-justified | SILICON-QUALIFIED |
| RX sub-word byte-lane placement | **RE-INFERRED / UNPROVEN** |
| `CTRL` bit 10 endianness meaning | **RE-INFERRED / UNPROVEN** (vendor name contradicts the board) |
| DMA phases, POLL phases, DUAL/QUAD width, SPI1 | REGISTER-MAP DERIVED |

### Gotchas

- **The hardware requires an RX phase to be last, not first.**
  `ag32_spi_write_read()` orders TX then RX for that reason.
- `ag32_spi_write()` preserves only `DIV`, `LITTLE`, and `WP` from the existing
  `CTRL` when it launches; anything else you set is dropped.
- A completed transfer is `DONE` set and `ERROR` clear. The wait is bounded, so
  an unrouted SPI0 reports `-2` rather than hanging.

---

## I2C0, I2C1 — `0x4002B000`, `0x4002C000`

Header: **`agamemnon/sdk/include/ag32_i2c.h`**. **OpenCores-style master.**
Note the two register aliases at the same offsets.

| Offset | Write name | Read name | Function | Provenance |
|---|---|---|---|---|
| `0x00` | `PRERLO` | `PRERLO` | prescaler, low byte | SILICON-QUALIFIED (I2C0) |
| `0x04` | `PRERHI` | `PRERHI` | prescaler, high byte | SILICON-QUALIFIED (I2C0) |
| `0x08` | `CTR` | `CTR` | control (core enable, interrupt enable) | SILICON-QUALIFIED (I2C0) |
| `0x0C` | `TXR` | `RXR` | transmit / receive data | SILICON-QUALIFIED (I2C0) |
| `0x10` | `CR` | `SR` | command / status | SILICON-QUALIFIED (I2C0) |

### `CTR`, `CR`, `SR` bits

| Register | Bit | Name | Meaning |
|---|---|---|---|
| `CTR` | 7 | `EN` | core enable |
| `CTR` | 6 | `IEN` | interrupt enable |
| `CR` | 7 | `STA` | generate START |
| `CR` | 6 | `STO` | generate STOP |
| `CR` | 5 | `RD` | read from slave |
| `CR` | 4 | `WR` | write to slave |
| `CR` | 3 | `NACK` | send NACK on this read |
| `CR` | 0 | `IACK` | interrupt acknowledge |
| `SR` | 7 | `RXNACK` | **no** acknowledge received |
| `SR` | 6 | `BUSY` | bus busy |
| `SR` | 5 | `AL` | arbitration lost |
| `SR` | 1 | `TIP` | transfer in progress |
| `SR` | 0 | `IF` | interrupt flag |

Provenance: **REGISTER-MAP DERIVED** for the full bit set;
`EN`, `STA`, `STO`, `WR`, `RD`, `NACK`, `TIP`, `RXNACK`, and `AL` are exercised
by the qualified scan.

### Prescaler

`ag32_i2c_init()` programs `PRER = pbus_hz / (5 × scl_hz) - 1`, split across
`PRERLO`/`PRERHI`. **`pbus_hz` is trusted, not measured** — I2C0's own reference
clock has never been measured. `i2c_probe.c` borrows
`ag32_uart_ref_hz_measured()` and labels that in-source as an explicit
**cross-domain assumption** (SPI0 already falsifies a single APB rate). Verify
SCL with a scope.

### Usage pattern

```c
/* Cross-domain assumption: record it, then verify SCL on a scope. */
ag32_i2c_init(AG32_I2C0, ag32_uart_ref_hz_measured(), 100000u);

int rc = ag32_i2c_start(AG32_I2C0, 0x55u, /*read=*/0, 100000u);
/* rc: 0 ACK, -1 timeout, -2 arbitration lost, -3 NACK (no such device) */
if (rc == 0)
    ag32_i2c_write(AG32_I2C0, 0xAAu, /*stop=*/1, 100000u);
else
    AG32_I2C0->CR = AG32_I2C_CR_STO;   /* always release the bus */
```

### Silicon evidence

| Claim | Provenance |
|---|---|
| **315 transactions** driven on I2C0 (2026-08-14) | SILICON-QUALIFIED |
| Address `0x55` **write** framed correctly | SILICON-QUALIFIED |
| **Correct NACKs with no slave present** | SILICON-QUALIFIED |
| Real slave acknowledge, clock stretching, repeated START, slave mode, I2C1 | REGISTER-MAP DERIVED |
| I2C0's own reference clock | **not measured** |

### Gotchas

- **I2C needs open-drain pads and external pull-ups.** A push-pull fabric route
  is not an I2C bus. With a floating bus every address NACKs, which is the
  honest result — not a driver bug.
- Always close a probe with `STO`. `i2c_probe.c` does this after every candidate
  address so the bus is never left held.
- `ag32_i2c_wait()` folds three conditions into one return: `-1` timeout (TIP
  never cleared), `-2` arbitration lost, `-3` NACK received.

---

## CAN0 — `0x4002A000`

Header: **`agamemnon/sdk/include/ag32_can.h`**. **SJA1000 / PeliCAN-class**
controller with **two register personalities**: bit timing and acceptance
filters are only writable while `MOD.RESET` is set; the frame windows are only
meaningful in operating mode.

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x00` | `MOD` | mode | SILICON-QUALIFIED (readback) |
| `0x04` | `CMR` | command (write-only) | SILICON-QUALIFIED (accepted) |
| `0x08` | `SR` | status (read-only) | SILICON-QUALIFIED (readback) |
| `0x0C` | `IR` | interrupt, read-clears | REGISTER-MAP DERIVED |
| `0x10` | `IER` | interrupt enable | REGISTER-MAP DERIVED |
| `0x18` | `BTR0` | bus timing 0 | SILICON-QUALIFIED (readback) |
| `0x1C` | `BTR1` | bus timing 1 | SILICON-QUALIFIED (readback) |
| `0x20` | `OCR` | output control | SILICON-QUALIFIED (readback) |
| `0x2C` | `ALC` | arbitration-lost capture (read-only) | REGISTER-MAP DERIVED |
| `0x30` | `ECC` | error-code capture (read-only) | REGISTER-MAP DERIVED |
| `0x34` | `EWLR` | error-warning limit | REGISTER-MAP DERIVED |
| `0x38` | `RXERR` | receive error counter | REGISTER-MAP DERIVED |
| `0x3C` | `TXERR` | transmit error counter | REGISTER-MAP DERIVED |
| `0x40` … `0x70` | `FRAME[0..12]` **/** `ACR[0..3]`+`AMR[0..3]` | shared 13-word window: frame info + id + data in operating mode; acceptance code/mask in reset mode | **RE-INFERRED / UNPROVEN** — see below |
| `0x74` | `RMC` | receive message counter (read-only) | REGISTER-MAP DERIVED |
| `0x78` | `RBSA` | receive buffer start address | REGISTER-MAP DERIVED |
| `0x80` … `0x17C` | `RXFIFO[0..63]` | 64-word receive FIFO | REGISTER-MAP DERIVED |
| `0x180` … `0x1B0` | `TXBUF[0..12]` | transmit-buffer read-back window | REGISTER-MAP DERIVED |

### Bit fields

| Register | Bits | Names |
|---|---|---|
| `MOD` | 0…4 | `RESET`, `LISTEN` (listen-only), `SELFTEST`, `AFM` (single acceptance filter), `SLEEP` |
| `CMR` | 0…4 | `TR` transmit request, `AT` abort, `RRB` release receive buffer, `CDO` clear data overrun, `SRR` self-reception request |
| `SR` | 0…7 | `RBS` receive buffer status, `DOS` data overrun, `TBS` transmit buffer released, `TCS` transmission complete, `RS` receiving, `TS` transmitting, `ES` error, `BS` bus-off |
| `IR`/`IER` | 0…7 | `RX`, `TX`, `ERR`, `DO`, `WU`, `EP`, `AL`, `BE` |
| `BTR0` | `[5:0]` / `[7:6]` | `BRP` / `SJW` |
| `BTR1` | `[3:0]` / `[6:4]` / `7` | `TSEG1` / `TSEG2` / `SAM` |
| `FRAME[0]` | 7 / 6 / `[3:0]` | `FF` extended id / `RTR` remote / `DLC` |
| `OCR` | — | `0x1A` = push-pull normal output driver |

Provenance: **REGISTER-MAP DERIVED**, except the `MOD`/`BTR0`/`BTR1`/`OCR`/`SR`
values listed in fact 5.

### Silicon evidence and the open question

See **fact 5** above for the full table. Summary:

- **SILICON-QUALIFIED:** CAN0 is clocked and configurable. `MOD` reads back
  `0x01` then `0x04`; `BTR0=0x3F` / `BTR1=0x7F` / `OCR=0x1A` read back as
  written; `SR` goes `0x3C` with **TBS set** → `0x30` on a transmit request; the
  TX pad idles recessive-high.
- **RE-INFERRED / UNPROVEN:** no bits shift out. `TXFRAME` (`0x40`) read back
  `0x00` after writing `0x08`, so the **transmit-buffer layout / frame format is
  the open question.**
- The `ag32_can_transmit()` frame packing in the header
  (`FRAME[0]` = DLC, `FRAME[1]` = `id[10:3]`, `FRAME[2]` = `id[2:0] << 5`,
  `FRAME[3+i]` = data) is the *documented PeliCAN* layout. Given the `0x40`
  readback it may not be the layout this controller actually uses. **Treat the
  frame window as unverified.**
- A real bus needs an external transceiver, absent from the bench.
- `ag32_can_transmit()` waits **bounded** for `TBS`. The historic "TBS never
  asserts" conclusion came from a wait shorter than the ~25 ms frame time at
  `BRP=63` — size your timeout against the actual bit rate.

`examples/riscv_mcu/can_selftest.c` uses `MOD.SELFTEST` + `CMR.SRR` so the TX→RX
datapath can in principle be proven with no transceiver. Its bit timing is
solved from `ag32_uart_ref_hz_measured()` as an explicit, labelled cross-domain
assumption.

---

## USB0 — `0x41001000`

**No MMIO driver is shipped.** ChipIdea/EHCI-class OTG core (host + device).
Register groups per the vendor register map (**REGISTER-MAP DERIVED**, offsets
not restated here because AGaMEMnon ships none): capability
(`CAPLENGTH`/`HCIVERSION`/`HCSPARAMS`/`HCCPARAMS`), operational
(`USBCMD`/`USBSTS`/`USBINTR`/`FRINDEX`), `PERIODICLISTBASE`/`ASYNCLISTADDR`
(host) aliased with `DEVICEADDR`/`ENDPOINTLISTADDR` (device), `PORTSC`, `OTGSC`,
`USBMODE`, and endpoint prime/flush/status/complete/`ENDPTCTRL[]`, driven by
qTD/dTD/queue-head descriptors. Two general-purpose timers are embedded.

| Claim | Provenance |
|---|---|
| **Device** path: enumerate, identify, read, page-erase, write, verify, restore, reset | **SILICON-QUALIFIED** via the flash-resident CDC-ACM uploader — see [USB_CDC_UPLOADER.md](USB_CDC_UPLOADER.md) |
| MCU-MMIO USB driver | not implemented |
| **Host** / OTG | hardware-gated (no host on the bench) |
| Required 60 MHz USB PLL point | REGISTER-MAP DERIVED (manual requirement); not exercised |

**Gotcha:** the AG32's USB connector does **not** imply a factory USB
bootloader. AGaMEMnon's USB transport is an application you install in main
flash first, and it is **not** a recovery path when main flash is corrupt.
USB D+/D- are a dedicated hard PHY — not ordinary fabric GPIO, and not
controlled through `AFSEL`.

---

## Ethernet MAC0 — `0x41040000`

Header: **`agamemnon/sdk/include/ag32_mac.h`**. 10/100 MAC with MDIO station
management, TX/RX descriptor rings, and a 64-bit multicast hash filter.
**Provenance: REGISTER-MAP DERIVED throughout — hardware-gated, no board PHY.**

| Offset | Name | Function |
|---|---|---|
| `0x00` | `CTRL` | control |
| `0x04` | `STAT` | status (write the bit back to clear) |
| `0x08` | `MACMSB` | station address, upper 16 bits |
| `0x0C` | `MACLSB` | station address, lower 32 bits |
| `0x10` | `MDIO` | MDIO command/status |
| `0x14` | `TXBASE` | transmit descriptor table base |
| `0x18` | `RXBASE` | receive descriptor table base |
| `0x20` | `HTMSB` | hash table, upper 32 bits |
| `0x24` | `HTLSB` | hash table, lower 32 bits |

| Register | Bits | Names |
|---|---|---|
| `CTRL` | 0,1,2,3,4,5,6,7,10,11,16 | `TX_EN`, `RX_EN`, `TX_INTEN`, `RX_INTEN`, `FULLDPX`, `PROMISC`, `RESET` (self-clearing), `SPEED100`, `PHY_INTEN`, `MCAST_EN`, `RMII` |
| `STAT` | 0…8 | `RX_ERR`, `TX_ERR`, `RX_INT`, `TX_INT`, `RX_AHBERR`, `TX_AHBERR`, `TOO_SMALL`, `INV_ADDR`, `PHY_CHG` (`0x1FF` clears all) |
| `MDIO` | 0,1,2,3,`[5:4]`,`[10:6]`,`[15:11]`,`[31:16]` | `WRITE`, `READ`, `LINK_FAIL` (ro), `BUSY` (ro), `MDCSC` clock scaler, `REG`, `PHY`, `DATA` |
| descriptor `CTRL` | `[10:0]`,11,12,13 | length, `EN` (owned by MAC when set), `WRAP` (last in ring), `INTEN` |

A descriptor is `{ CTRL, ADDR }`; `ADDR` must be 4-byte aligned.
`ag32_mac_set_address()` puts `addr[0]` — the first byte on the wire — in the
top of `MACMSB`.

**Gotchas:** `STAT` is write-1-to-clear, not read-to-clear. `CTRL.RESET` is
self-clearing; `ag32_mac_reset()` polls it with a bounded timeout. Moving real
traffic needs an external PHY, which the bench does not have.

---

## Timers, RTC and watchdogs

### Basic timers TIMER0/TIMER1 — `0x4001E000` / `0x4001F000`

**ARM SP804-class dual timer.** Two sub-timers per instance; the second is at
`+0x20`. Macros in `ag32.h` cover sub-timer 1 only.

| Offset | Name | Provenance |
|---|---|---|
| `0x00` | `LOAD1` | REGISTER-MAP DERIVED |
| `0x04` | `VALUE1` | REGISTER-MAP DERIVED (SP804 layout; no AGaMEMnon macro) |
| `0x08` | `CTRL1` | REGISTER-MAP DERIVED |
| `0x0C` | `INTCLR1` | REGISTER-MAP DERIVED |
| `0x10` | `RIS1` | REGISTER-MAP DERIVED |
| `0x14` | `MIS1` | REGISTER-MAP DERIVED (SP804 layout; no AGaMEMnon macro) |
| `0x18` | `BGLOAD1` | REGISTER-MAP DERIVED (SP804 layout; no AGaMEMnon macro) |

`CTRL` bits defined in `ag32.h`: `SIZE32` (bit 1), `PERIODIC` (bit 6),
`ENABLE` (bit 7). The SP804 class also defines one-shot (bit 0), prescale
(`[3:2]`), and interrupt enable (bit 5) — **RE-INFERRED here, not defined by any
AGaMEMnon header.**

`examples/riscv_mcu/basic_timer_led_walk.c` drives TIMER0 by raw MMIO
(periodic, 32-bit, `RIS`-polled). It is compile-tested and runs on the board as
an LED walk, but there is **no ledgered evidence row**, so TIMER0 is
**REGISTER-MAP DERIVED**, not qualified.

### Advanced timers GPTIMER0…4 — `0x40020000` + `n·0x1000`

Header: **`agamemnon/sdk/include/ag32_gptimer.h`**. **STM32-TIM-class**:
prescaler/auto-reload time base, four capture/compare channels, PWM, input
capture, break/dead-time. **Provenance: REGISTER-MAP DERIVED throughout — no
silicon exercise.**

| Offset | Name | Offset | Name |
|---|---|---|---|
| `0x00` | `CR1` | `0x20` | `CCER` |
| `0x04` | `CR2` | `0x24` | `CNT` |
| `0x08` | `SMCR` | `0x28` | `PSC` |
| `0x0C` | `DIER` | `0x2C` | `ARR` |
| `0x10` | `SR` | `0x30` | `RCR` |
| `0x14` | `EGR` | `0x34`…`0x40` | `CCR[0..3]` |
| `0x18` | `CCMR0` (ch0/ch1) | `0x44` | `BDTR` |
| `0x1C` | `CCMR1` (ch2/ch3) | | |

Key fields:

| Register | Field | Meaning |
|---|---|---|
| `CR1` | 0 `CEN`, 1 `UDIS`, 2 `URS`, 3 `OPM`, 4 `DIR` (0 up / 1 down), `[6:5]` `CMS`, 7 `ARPE`, `[9:8]` `CKD` | time-base control |
| `CR2` | `[6:4]` `MMS` | master mode / TRGO source |
| `SMCR` | `[2:0]` `SMS`, `[6:4]` `TS`, 14 `ECE` | slave mode / trigger / external clock |
| `DIER` | 0 `UIE`, `1+ch` `CCIE`, 6 `TIE`, 7 `BIE`, 8 `UDE`, `9+ch` `CCDE` | interrupt / DMA enables |
| `SR` | 0 `UIF`, `1+ch` `CCIF`, 6 `TIF`, 7 `BIF`, `9+ch` `CCOF` | status — **cleared by writing 0** |
| `EGR` | 0 `UG`, `1+ch` `CCG`, 6 `TG`, 7 `BG` | event generation, write-1 |
| `CCMR` | two 8-bit halves, one per channel. Output view: `CCS[1:0]`, `OCxFE[2]`, `OCxPE[3]`, `OCxM[6:4]`, `OCxCE[7]`. Input view: `CCS[1:0]`, `ICxPSC[3:2]`, `ICxF[7:4]` | register index `ch >> 1`, shift 8 for the odd channel |
| `CCER` | four bits per channel: `CCxE`, `CCxP`, `CCxNE`, `CCxNP` at `ch*4 + 0..3` | channel enable / polarity |
| `BDTR` | `[7:0]` `DTG`, 12 `BKE`, 13 `BKP`, 14 `AOE`, **15 `MOE`** | break and dead-time |

Output-compare modes: `FROZEN`=0, `TOGGLE`=3, `PWM1`=6 (active while
`CNT < CCR`), `PWM2`=7 (active while `CNT >= CCR`).

```c
ag32_gptimer_init(AG32_GPTIMER0, /*prescaler=*/99u, /*reload=*/999u);
ag32_gptimer_pwm_output(AG32_GPTIMER0, 0u, AG32_GPTIMER_OCM_PWM1, 500u);
ag32_gptimer_start(AG32_GPTIMER0);
```

**Gotchas:** `SR` flags clear on a **0** write, so `ag32_gptimer_clear_flags()`
writes `~mask`. `ag32_gptimer_init()` forces an update (`EGR.UG`) to latch
`PSC`/`ARR`, then clears the `UIF` that raised. **`BDTR.MOE` must be set** or an
advanced-timer output never drives — `ag32_gptimer_pwm_output()` sets it. The
timer's own clock domain has not been measured.

### RTC and backup domain — `0x40000000`

Header: **`agamemnon/sdk/include/ag32_rtc.h`**. 16-bit registers on 32-bit
strides.

| Offset | Name | Offset | Name |
|---|---|---|---|
| `0x00` | `CRH` (interrupt enables) | `0x18` | `CNTH` |
| `0x04` | `CRL` (flags) | `0x1C` | `CNTL` |
| `0x08` | `PRLH` (prescaler load) | `0x20` | `ALRH` |
| `0x0C` | `PRLL` | `0x24` | `ALRL` |
| `0x10` | `DIVH` (live divider, ro) | `0x28` | `RCYC` (read minimum cycle) |
| `0x14` | `DIVL` (ro) | `0x30` / `0x32` | `BDCR` / `BDRST` |

`CRL` flags: `SEC` (0), `ALR` (1), `OW` overflow (2), `RSF` registers
synchronized (3), **`RTOFF` operation-off / write-ready (5)**.
`BDCR`: `LSEON` (0), `LSERDY` (1), `RTCSEL` at `[9:8]` (`1` = LSE, `2` = LSI),
`RTCEN` (15).

`PERIPHERAL_CATALOG.md` additionally names an `RTCCR` calibration register and
backup data registers from `0x40`; those offsets are **not** in
`ag32_rtc.h` — REGISTER-MAP DERIVED, not restated here.

| Claim | Provenance |
|---|---|
| `BDCR` `RTCEN` + LSI-select **stick** (`BDCR` → `0x8200`); the backup domain is writable | **SILICON-QUALIFIED (config path)** |
| The counter **does not advance** — `first == second == 0` over a ~2 M MTIME window | **SILICON-QUALIFIED (negative)**: no low-speed clock runs on the bench (no LSI enable, no 32 kHz LSE crystal) |
| Timekeeping, alarms, the `SEC`/`ALR` interrupt path | **not qualified** |

`ag32_rtc_counter()` re-reads `CNTH` to survive a low-half rollover.
`ag32_rtc_enable()` returns non-zero if `RTCEN` did not read back, and
deliberately does **not** spin unbounded on `LSERDY` or `RSF` — those flags never
assert without a running low-speed clock.

### APB watchdog WATCHDOG0 — `0x40011000`

Header: **`agamemnon/sdk/include/ag32_watchdog.h`**. Manual section 9.3. This is
**not** the independent watchdog of 9.2.

| Offset | Name | Provenance |
|---|---|---|
| `0x000` | `LOAD` | SILICON-QUALIFIED |
| `0x004` | `VALUE` (ro) | SILICON-QUALIFIED |
| `0x008` | `CONTROL` | SILICON-QUALIFIED |
| `0x00C` | `INTCLR` (wo) | SILICON-QUALIFIED |
| `0x010` | `RIS` (ro) | SILICON-QUALIFIED (read) |
| `0x014` | `MIS` (ro) | REGISTER-MAP DERIVED |
| `0xC00` | `LOCK` | SILICON-QUALIFIED |

`CONTROL`: `INT_ENABLE` (bit 0), `RESET_ENABLE` (bit 1).
`LOCK` unlock key: **`0x1ACCE551`**; write anything else (the driver writes 0) to
re-lock.

| Claim | Provenance |
|---|---|
| Disabled-state snapshot: `VALUE=0xFFFFFFFF`, `CONTROL=0`, `RIS=0` | SILICON-QUALIFIED |
| Supervised timeout: armed with `LOAD=0x00200000` and reset-enable, never fed → the **second** timeout warm-reset the MCU and set `RST_CNTL` bit30 `SYS_RSTF_WDOG` **exclusively** | SILICON-QUALIFIED |

**Gotcha:** every register write needs the unlock key first; the driver
unlock→write→lock brackets each operation, including `ag32_watchdog_feed()`.
Note it is the **second** timeout that resets — the first raises the interrupt.

### Independent watchdog (IWDG) — `RTC_BASE + 0x34`

Header: **`agamemnon/sdk/include/ag32_iwdg.h`**. A **single 16-bit register**
inside the RTC/backup domain, clocked by the low-speed oscillator so it survives
a stopped main clock.

| Field | Bits | Meaning |
|---|---|---|
| prescaler | `[2:0]` | divides the low-speed clock |
| `STOP_FREEZE` | 4 | freeze in stop mode |
| `STANDBY_FREEZE` | 5 | freeze in standby |
| `CLKSEL_LSE` | 6 | `0` = LSI, `1` = LSE |
| `ENABLE` | 8 | watchdog enable |
| reload | `[15:12]` | write key **`0xA000`** to kick the counter |

**Provenance: REGISTER-MAP DERIVED / hardware-gated.** Every backup-domain write
must first wait for RTC `CRL` bit 5 (`RTOFF`), and **that flag never asserts
without a running low-speed clock** — which the bench does not have. All waits in
`ag32_iwdg.h` are therefore bounded and return `-1` on timeout. Same blocker as
the RTC counter.

---

## CRC0 — `0x41002000`

Header: **`agamemnon/sdk/include/ag32_crc.h`**. STM32-style unit.

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x00` | `DR` | data in / result out (also byte-addressable) | SILICON-QUALIFIED |
| `0x04` | `IDR` | 8-bit scratch | REGISTER-MAP DERIVED |
| `0x08` | `CR` | control / reset | SILICON-QUALIFIED |
| `0x10` | `INIT` | programmable initial value | REGISTER-MAP DERIVED |
| `0x14` | `POL` | programmable polynomial | REGISTER-MAP DERIVED |

`CR`: `RESET` (bit 0); `POLYSIZE` at `[4:3]` (`0`=32, `1`=16, `2`=8, `3`=7);
`REVERSE` input at `[6:5]` (`0` none, `1` byte, `2` halfword, `3` word);
`REVERSE_OUTPUT` (bit 7).

```c
ag32_crc_configure(AG32_CRC32_POLYNOMIAL /*0x04C11DB7*/, 0xFFFFFFFFu, 0u);
uint32_t crc = ag32_crc_bytes("123456789", 9);   /* == 0x0376E6E7 */
```

| Claim | Provenance |
|---|---|
| CRC-32/MPEG-2 known-answer: ASCII `123456789` → **`0x0376E6E7`** (poly `0x04C11DB7`, init `0xFFFFFFFF`, no reflection, no final XOR) | SILICON-QUALIFIED |
| Any other polynomial, width, or reflection mode; the `INIT`/`POL` programmable path | REGISTER-MAP DERIVED |

**Gotcha:** `ag32_crc_write8()` writes `DR` as a **byte** (`AG32_REG8`). Feeding
the same data as words gives a different result — the known-answer above is the
byte-access form.

---

## DMAC0 — `0x41000000`

Header: **`agamemnon/sdk/include/ag32_dma.h`**. **PL080-class**, 8 channels with
linked-list descriptors.

| Offset | Name | Offset | Name |
|---|---|---|---|
| `0x000` | `INT_STATUS` (ro) | `0x018` | `RAW_ERR_STATUS` (ro) |
| `0x004` | `INT_TC_STATUS` (ro) | `0x01C` | `ENABLED_CHANNELS` (ro) |
| `0x008` | `INT_TC_CLEAR` | `0x020`…`0x02C` | `SOFT_BREQ`/`SREQ`/`LBREQ`/`LSREQ` |
| `0x00C` | `INT_ERR_STATUS` (ro) | `0x030` | `CONFIG` |
| `0x010` | `INT_ERR_CLEAR` | `0x034` | `SYNC` |
| `0x014` | `RAW_TC_STATUS` (ro) | `0x100` + `n·0x20` | `CHANNEL[n]` |

Each channel: `SRC`, `DST`, `LLI`, `CONTROL`, `CONFIG`.

`CONTROL`: transfer size `[11:0]`, `SWIDTH` `[20:18]`, `DWIDTH` `[23:21]`,
`SINC` (26), `DINC` (27), `TC_IRQ` (31). Widths: `8`=0, `16`=1, `32`=2.
`CONFIG` bit 0 is the channel enable; flow-control value 0 is memory-to-memory.

```c
ag32_dma_init();                                   /* AHB gate + reset + enable */
if (ag32_dma_copy32(0, dst, src, 4u) == 0)
    ag32_dma_wait(0, 1000000u);                    /* 0 ok, -1 timeout, -2 error */
```

| Claim | Provenance |
|---|---|
| Single-channel **memory-to-memory 4-word SRAM copy** | SILICON-QUALIFIED |
| Peripheral-linked flow control, `LLI` descriptor chaining, wider/multi-channel transfers | REGISTER-MAP DERIVED |
| Fabric DMA request sidebands (`EXT_DMA0..3_REQ` → DMAC selectors 1–4, `FCB0_DMA_REQ` = 5) | **RE-INFERRED / UNPROVEN** — pulse polarity/duration and level-vs-pulse semantics of `DMACCLR`/`DMACTC` are not characterized. See [HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md) |

**Gotchas:** `ag32_dma_copy32()` rejects unaligned pointers, `words` outside
1…4095, and a channel already in `ENABLED_CHANNELS` (returns `-2`). Clear the
per-channel TC/error bits before starting, as the driver does. ADC/DAC also bind
to DMA selectors (ADC2/DAC1 share) — untested.

---

## Analog: ADC0/1/2, DAC0/1, CMP0 — on the External-AHB window, not MCU MMIO

**These are not MCU-core MMIO peripherals.** They are analog hard blocks
instantiated as **fabric IP** and memory-mapped in the External-AHB window at
`0x60000000`. **They only exist once a fabric image that instantiates the analog
IP wrapper has been configured** (fact 2 applies).

> **Important scope limit.** The MCU side is fully open — AGaMEMnon SDK drivers,
> SRAM staging, FCB configuration, External-AHB reads. But the fabric image used
> for qualification instantiates the **vendor `analog_ip` hard-macro wrapper**,
> which AGaMEMnon's own bitgen does **not** emit. So the qualification below is
> of the analog blocks and their register path on the L48 part — **not** a claim
> that the open flow can synthesize or place the analog IP.

Headers: `ag32_adc.h`, `ag32_dac.h`, `ag32_comparator.h`. Full narrative:
[ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md).

The window decodes as `sel = haddr[15:12]`, **word accesses only**
(REGISTER-MAP DERIVED, from the vendor RTL wrapper).

**No reset/power-on values are recorded for any analog register** in any source
available here. Values quoted below are post-write readbacks, not resets. Do not
treat them as defaults.

### ADC0/1/2 — `0x60000000` / `+0x1000` / `+0x2000`

12-bit SAR with a 16-entry channel sequencer.

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x00` | `CTRL` | `START` (0, set-only — **self-clears on EOC in one-shot mode**), `STOP` (1, set-only), `CONT` (2), `DMAEN` (3), `SCLK_DIV` `[31:16]` | START/SCLK_DIV SILICON-QUALIFIED; CONT/DMAEN REGISTER-MAP DERIVED |
| `0x04` | `STAT` | `EN` (0, converter running), `EOC` (1) | SILICON-QUALIFIED |
| `0x08` | `DATA` | latest 12-bit result (`0xFFF` max); **reading clears `EOC`** | SILICON-QUALIFIED |
| `0x3C` | `CHNL` | **write:** sequence length **minus one** in `[3:0]`. **read:** `{ chnl_sel[4:0] @ 8, seq_cnt[3:0] @ 4, seq_length[3:0] @ 0 }` | write side SILICON-QUALIFIED (length 1); **read-side packing REGISTER-MAP DERIVED and not modelled by `ag32_adc.h`** |
| `0x40`…`0x7C` | `SEQ[0..15]` | channel sequence, 5-bit raw index per step | SILICON-QUALIFIED (single entry) |

Sample rate = `APB / ((SCLK_DIV + 1) · 2) / 13` (**REGISTER-MAP DERIVED**; and
see fact 3 — *which* APB is unclear). Writing `CHNL` or any `SEQ` entry
**restarts** the converter (`adc_en` drops). Raw `SEQ` value = logical channel
+ 1, so `AG32_ADC_CHANNEL(n)` == `n + 1` and the DAC taps at logical channels
4 and 5 are raw values 5 and 6.

### DAC0/1 — `0x60003000` / `0x60004000`

10-bit (`0x3FF` max).

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x00` | `CTRL` | `EN` (0), `BUFEN` output buffer (1), `DMAEN` (2), `SCLK_DIV` `[31:16]` | EN/BUFEN SILICON-QUALIFIED; DMAEN REGISTER-MAP DERIVED |
| `0x04` | `DATA` | 10-bit output code | SILICON-QUALIFIED |

DMA sample rate = `APB / (1 + SCLK_DIV)` (**REGISTER-MAP DERIVED**).

### CMP0 — `0x60005000`

**Dual** comparator; each unit has independently selectable + and − inputs.

| Offset | Name | Function |
|---|---|---|
| `0x00` | `CTRL` | `EN1` (0), `HYST1` (1), `MODE1` (2), `EN2` (8), `HYST2` (9), `MODE2` (10) |
| `0x04` | `CHNL` | `PSEL1` `[1:0]`, `MSEL1` `[6:4]`, `PSEL2` `[9:8]`, `MSEL2` `[14:12]` |
| `0x08` | `DATA` | `DATA1` (bit 0), `DATA2` (bit 8) — 1 = positive input higher |

Input selects (unit 1's map is **silicon-confirmed**):

| Value | `PSEL` | Value | `MSEL` |
|---|---|---|---|
| 1 | external analog input 1 | 4 | VREF/4 |
| 2 | **DAC0** (`AG32_CMP_PSEL_DAC0`) | 5 | VREF/2 |
| | | 6 | 3·VREF/4 |
| | | 7 | VREF |

Only `PSEL = 2` → DAC0 and `MSEL = 4…7` → the four VREF taps are backed by the
vendor-RTL extraction. `ag32_comparator.h` additionally documents the ranges as
`PSEL` 1…2 and `MSEL` 1…7 and names `PSEL = 1` "external analog input 1" —
**those wider ranges and that name are unsourced in the extraction**
(RE-INFERRED). `PSEL` values 0 and 3, and `MSEL` values 0…3, have no recorded
meaning at all. Do not guess them.

### Silicon evidence (all L48, open MCU flow, 2026-08-14)

| Claim | Provenance |
|---|---|
| ADC0, ADC1, **and** ADC2 do 12-bit single-channel one-shot conversion | SILICON-QUALIFIED |
| DAC0, DAC1 10-bit output verified through ADC readback | SILICON-QUALIFIED |
| **Internal taps: DAC0 → ADC channel 4, DAC1 → ADC channel 5, on all three ADC instances**, no external analog wiring | SILICON-QUALIFIED |
| DAC0 sweep `{0,128,256,384,512,640,768,896,1023}` read back on ADC0 channel 4 as **strictly monotonic, ~4.00× linear** (the ideal 12-bit-result over 10-bit-code ratio), **saturating at full scale**; reproduced on ADC1/ADC2 and via DAC1→channel 5 | SILICON-QUALIFIED (see the exact-series caveat below) |
| CMP0 **unit 1** flipped at DAC0 codes **94 / 188 / 281 / 373** for MSEL = VREF/4, VREF/2, 3·VREF/4, VREF — a ≈93-code-spaced, 1:2:3:4-shaped progression against the **93 / 186 / 279 / 372** predicted from the vendor RTL | SILICON-QUALIFIED |
| External-AHB → analog register path: reads/writes of every register above from open MCU firmware | SILICON-QUALIFIED |
| **CMP0 unit 2** | **RE-INFERRED / UNPROVEN.** Register-readable and its enable takes (`CTRL` reads back `0x100`), but its output read **high at every DAC0 code** — code 0 *and* code 1023 — under **both** `PSEL2` selects. Its positive-input mux maps to different nets than unit 1's in an undocumented way. The vendor example never exercised it. **Not working, not merely untested.** |
| **External ADC channels 0–3 read full scale (`0xFFF`)** | **RE-INFERRED / UNPROVEN** — see the bonding caveat below. A full-scale reading with no analog pad driven is not a measurement, whatever its cause. |
| CMP hysteresis and mode bits; ADC/DAC DMA and continuous-scan modes; multi-entry sequencer runs | REGISTER-MAP DERIVED — unexercised |
| DAC DMA sample rate `APB / (1 + SCLK_DIV)` (in `ag32_dac.h`) | REGISTER-MAP DERIVED — **no vendor-RTL source recorded for the DAC formula**; the ADC formula does have one |

> **Caveat — do not quote an exact ADC sweep series.**
> `ag32_adc.h`, `STATUS.md`, and `ANALOG_FABRIC_BOUNDARY.md` all state the ADC0
> channel-4 readback as `0, 512, 1024, 1536, 2054, 2575, 3085, 3598, 4095`. The
> RE workbench's lab record for the same campaign lists the run-1 series as
> `0, 511, 1024, 1538, 2054, 2573, 3085, 3594, 4095` — **four of the nine points
> differ** (511↔512, 1538↔1536, 2573↔2575, 3594↔3598), and the header's series
> also matches none of the other per-instance runs. The qualitative result —
> monotonic, ~4.00× linear, saturating at full scale, reproduced across all three
> ADCs and both DACs — is unaffected and is what the qualification actually
> rests on. **Treat the exact nine numbers as unreconciled** and do not quote
> them as *the* measured series.

> **Caveat — "channels 0–3 are not bonded on L48" is an inference, and a
> contested one.** `ag32_adc.h` states it as fact. Two things weaken it:
> 1. The workbench lab record for the same runs explicitly declines to
>    characterize bonding — it calls the `0xFFF` reading "expected, not
>    qualified" and says "L48 analog-pad bonding not characterized here."
> 2. A datasheet-derived pin table in the workbench
>    (`AG32-Docs/docs/reference/PINS_DATASHEET.md`,
>    `AG32-Docs/tools/agamemnon/chipdb/pins_datasheet.csv`) lists
>    **`ADC_IN0`…`ADC_IN3` as alternate functions of `PIN_10`…`PIN_13`** — pads
>    that *are* in the 34-pad L48 fabric-IO set and that have been driven as
>    working digital IO on the bench.
>
> So the honest position is: **full-scale reads were observed; the cause is not
> established.** Candidate explanations — the analog die pad is genuinely a
> separate, unbonded pad; the pad was not switched into analog mode; or nothing
> was driving it and it floated high — have not been separated. Either way, do
> not build on channels 0–3, and do not repeat "not bonded" as a settled fact.

```c
/* Self-contained ADC proof: drive a DAC code, watch the ADC follow. */
ag32_dac_enable(AG32_DAC0);                      /* EN | BUFEN */
ag32_dac_set(AG32_DAC0, 512u);
int32_t code = ag32_adc_convert(AG32_ADC0, AG32_ADC_CH_DAC0,
                                /*sclk_div=*/0u, /*timeout=*/100000u);
/* expect ~2054 (12-bit result vs 10-bit code, ~4.00x) */
```

The strict **open** flow additionally exposes three read-only ADC0 *routes*
(`AGRV2K_ADC0_DB0`, `AGRV2K_ADC0_DB1`, `AGRV2K_ADC0_EOC`) as build-supported,
hardware-unqualified corridors. That is route support only — no configuration,
ownership arbitration, timing, or electrical claim. See
[HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md).

---

## FCB0 — fabric configuration bridge — `0x40010000`

Header: `ag32.h` (`ag32_fcb_config`). This is how the MCU loads a fabric image
(the mechanism behind `agamemnon sram --fabric`).

### Register map

| Offset | Name | Access | Function | Provenance |
|---|---|---|---|---|
| `0x00` | `CTRL` | rw | command strobes / mode flags; bit 6 = `AUTO` | SILICON-QUALIFIED (AUTO) |
| `0x04` | `ADDR` | rw | configuration-chain address | REGISTER-MAP DERIVED |
| `0x08` | `DATA` | rw | configuration data (addressed mode) | REGISTER-MAP DERIVED |
| `0x0C` | `AUTO` | rw | **auto-mode data sink** — this is where `ag32_fcb_config()` streams the image | SILICON-QUALIFIED |
| `0x10` | `STAT` | ro | status; error bits are write-1-to-clear | SILICON-QUALIFIED |
| `0x14` | `INT` | rw | interrupt enables mirroring the `STAT` event bits | REGISTER-MAP DERIVED |

> **Register-map disagreement — flagged, not resolved.** `ag32.h` defines
> `FCB_DATA` at offset **`0x0C`** and streams every configuration word there.
> The extracted FCB register model in the RE workbench
> (`AG32-Docs/tools/agamemnon/fcb/fcb_regs.py`) names **`0x08` = `DATA`** and
> **`0x0C` = `AUTO`**. Both can be true: `0x0C` is plausibly the *auto-mode*
> data port and `0x08` the addressed-mode one. Streaming to `0x0C` with
> `CTRL.AUTO` set is **silicon-proven**, so the working recipe is not in doubt —
> but the name and the purpose of `0x08` are **not established**. Do not write
> to `0x08` expecting it to behave like `0x0C`.

### `CTRL` bits (`0x00`) — REGISTER-MAP DERIVED except `AUTO`

| Bit | Value | Name | Meaning |
|---|---|---|---|
| 0 | `0x00000001` | `INIT` | initialize the configuration SRAM |
| 1 | `0x00000002` | `WRITE` | write operation |
| 2 | `0x00000004` | `READ` | read operation |
| 3 | `0x00000008` | `UPDATE` | update the current configuration chain |
| 4 | `0x00000010` | `ACTIVATE` | activate the FPGA configuration |
| 5 | `0x00000020` | `DEACTIVATE` | de-activate |
| **6** | **`0x00000040`** | **`AUTO`** | **reset into / enter auto-configuration mode** — SILICON-QUALIFIED |
| 7 | `0x00000080` | `DMA` | the FCB is the DMA flow controller |
| 16 | `0x00010000` | `INIT_EMB` | (no documented gloss) |
| 17 | `0x00020000` | `CFGDONE` | (no documented gloss) |
| 18 | `0x00040000` | `CHIP_RSTB` | (no documented gloss) |
| 19 | `0x00080000` | `DEVOE` | (no documented gloss) |

### `STAT` bits (`0x10`) — read-only; error bits write-1-to-clear

| Bit | Value | Name | Meaning | Provenance |
|---|---|---|---|---|
| 0 | `0x00000001` | `INIT` | configuration-SRAM initialization complete | REGISTER-MAP DERIVED |
| **1** | `0x00000002` | **`ACTIVE`** | FPGA configuration active | SILICON-QUALIFIED |
| 4 | `0x00000010` | `ERR_ID` | device-ID error | REGISTER-MAP DERIVED |
| 5 | `0x00000020` | `ERR_HEADER` | image-header error | REGISTER-MAP DERIVED |
| **6** | **`0x00000040`** | **`ERR_CRC`** | CRC error | SILICON-QUALIFIED |
| 16 | `0x00010000` | `INIT_EMB` | | SILICON-QUALIFIED (asserted on success) |
| 17 | `0x00020000` | `CFGDONE` | | SILICON-QUALIFIED (asserted on success) |
| 18 | `0x00040000` | `CHIP_RSTB` | | SILICON-QUALIFIED (asserted on success) |
| 19 | `0x00080000` | `DEVOE` | | SILICON-QUALIFIED (asserted on success) |
| — | `0x00000070` | `ERR_ALL` | `ERR_ID | ERR_HEADER | ERR_CRC`; write this value back to clear | REGISTER-MAP DERIVED |

**`FCB_STAT_OK` == `0x000f0002`** therefore decodes exactly as:

| State | Bits |
|---|---|
| asserted | `ACTIVE` (1), `INIT_EMB` (16), `CFGDONE` (17), `CHIP_RSTB` (18), `DEVOE` (19) |
| clear | `INIT` (0) — *not* asserted in the success value |
| clear | `ERR_ID` / `ERR_HEADER` / `ERR_CRC` — i.e. `stat & ERR_ALL == 0` |

**Compare against `FCB_STAT_OK` as a whole.** The CRC the FCB checks is the
CRC-32/BZIP2 over `header[0:8] + raw[0:99932]`, stored big-endian — see
[BITSTREAM_FORMAT.md](BITSTREAM_FORMAT.md).

> **Why "nothing reaches a pad" until `STAT` is right.** The vendor architecture
> dump maps the FCB global signals `cfgdone → CHIP_CFG_DONE`,
> `chip_rstb → CHIP_RSTB`, and **`devoe → IO_GHIZ`** — i.e. `DEVOE` releases the
> fabric IO ring's global high-Z. That makes the observed "every pad reads
> static until `FCB_STAT == 0x000f0002`" behaviour mechanically sensible.
> Provenance: **RE-INFERRED** — this mapping comes from the architecture dump,
> not from a register description or a comment in the extracted model.

### Usage pattern

```c
/* The SRAM loader places the fabric image at 0x20002000. */
uint32_t stat = ag32_fcb_config((const uint32_t *)0x20002000u, 99944u / 4u);
if (stat != FCB_STAT_OK) { /* 0x40 => bad CRC */ }
```

Equivalent explicit sequence (`examples/firmware/clkcfg_stub.c`):

```c
AG32_SYSCTL_CLK_CNTL  &= ~0x03u;            /* select HSI                    */
AG32_SYSCTL_CLK_CNTL  &= ~0x24u;            /* clear HSE_ON | PLL_ON         */
AG32_SYSCTL_APB_ENABLE |= AG32_APB_FCB0;    /* gate the FCB clock on         */
FCB_CTRL = FCB_CTRL_AUTO;                   /* bit 6                         */
for (int i = 0; i < 24986; ++i)             /* 99,944 / 4 words              */
    FCB_DATA = image[i];
uint32_t stat = FCB_STAT;                   /* expect 0x000f0002             */
```

### Gotchas

- **The clock side effect of fact 3 applies:** `ag32_fcb_config()` clears the
  source select and the HSE/PLL enables and **does not restore them**. If your
  design needs the PLL, re-run the switch sequence afterwards
  (`clkcfg_stub.c` does).
- **FCB acceptance is not functional qualification.** `0x000f0002` proves the
  image header, device ID, CRC, and configuration protocol. It says nothing
  about whether a route conducts.
- The FCB0 APB clock gate (`APB_ENABLE` bit 0) must be on first.
- Fabric configuration **from flash** happens only at power-on, not on a warm
  reset.

---

## Flash controller — `0x40001000` — and the boot ROM

AGaMEMnon programs main flash through this controller using generic OpenOCD
memory operations; it does **not** need the vendor `agrv` flash driver.

| Offset | Name | Function | Provenance |
|---|---|---|---|
| `0x04` | `KEYR` | main-flash unlock: write `0x45670123` then `0xCDEF89AB` | SILICON-QUALIFIED |
| `0x08` | `OPTKEYR` | option-byte unlock, same key pair | REGISTER-MAP DERIVED (unsupported path) |
| `0x0C` | `SR` | status; bit 0 busy | SILICON-QUALIFIED |
| `0x10` | `CR` | operation control and start | SILICON-QUALIFIED |
| `0x14` | `AR` | sector address for erase | SILICON-QUALIFIED |
| `0x2C` | `CFG` | access configuration; AGaMEMnon writes `0x8001045A` | SILICON-QUALIFIED |

`CR` values: `0x42` sector erase + start (using `AR`); `0x8211` enable
programming (subsequent memory writes program flash); `0x80` lock/idle.

```text
init:   KEYR=0x45670123; KEYR=0xCDEF89AB; CFG=0x8001045A;
        AR=0x34; CR=0x4040; CR=0x80
erase:  unlock; AR=sector_base; CR=0x42; CR=0x80; wait; verify erased
program: unlock; CR=0x8211; write words to the flash address; CR=0x80;
         wait; read back and compare
```

**Erase granularity is 4 KiB.** `agamemnon/program.py` uses a bounded delay plus
byte-for-byte readback verification — it deliberately does **not** use `SR.BSY`
as its completion loop.

### Flash and option layout (qualified board)

| Address | Contents | Provenance |
|---|---|---|
| `0x80000000`…`0x8003FFFF` | main flash (256 KiB) | SILICON-QUALIFIED |
| `0x80000000` | MCU firmware / reset vector | SILICON-QUALIFIED |
| `0x80007000` | compressed-image decompressor (option-controlled) | SILICON-QUALIFIED (this board) |
| `0x80008100` | compressed fabric image (option-controlled) | SILICON-QUALIFIED (this board) |
| `0x80010000` | sector 16 — where USB-loaded applications are linked, clear of the loader | SILICON-QUALIFIED |
| `0x81000000` | option bytes (separate controller region) | REGISTER-MAP DERIVED |

Option-byte fields, stored as `(value, bitwise-complement)` pairs; blank is
`0xFFFFFFFF` (**REGISTER-MAP DERIVED**, values observed on the qualified board):

| Address | Board value | Purpose |
|---|---|---|
| `0x81000000` | `ffff5aa5` | read protection + user option bits |
| `0x81000004`…`0x8100001F` | all ones | main-flash write-protection bitmap |
| `0x81000020` | `a857ffff` | oscillator trim + user data |
| `0x81000030` | blank | **uncompressed** fabric pointer |
| `0x81000038` | `80008100`, `7fff7eff` | **compressed** fabric pointer |
| `0x81000040` | `80007000`, `7fff8fff` | decompressor pointer |

### Boot sequence

1. The mask ROM reads option bytes.
2. It selects the fabric image and decompressor mode — a valid **uncompressed**
   pointer first, otherwise the compressed pointer plus the decompressor.
3. It obtains the 99,936-byte raw configuration and **streams it into the FCB**.
4. With **BOOT0 low** it branches to MCU firmware at `0x80000000`; with
   **BOOT0 high** it enters the mask-ROM UART bootloader.

Provenance: **SILICON-QUALIFIED** for boot from an existing compressed-config
pointer; the BOOT0-high UART ROM path is documented and implemented but its
target-side link needs the five-wire Pico harness addition.

### Gotchas

- **Back up all of flash before any write**, then write, then byte-verify.
  `agamemnon flash --backup` enforces the first step.
- Preserve every *complete* affected 4-KiB sector — especially the sector shared
  by the decompressor and the compressed image.
- Replacing sector 0 with a native application **replaces the USB uploader's
  entry sector**, so USB programming will not survive the next reset. Restore
  the complete backup over SWD to get it back.
- New option-pointer programming is exposed as an explicit opt-in and is **not**
  a supported deployment path.
- Neither SWD nor the BOOT0 ROM path depends on valid main-flash contents. Those
  are the recovery routes.

---

## The External-AHB window at `0x60000000` — the MCU's door into the fabric

Summary from the firmware side; the fabric side is in
[HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md).

| Path | Direction | Summary | Provenance |
|---|---|---|---|
| External AHB, `0x60000000` | MCU master → fabric slave | 32-lane simultaneous read is qualified; writes qualified in protocol-valid 4-bit groups; a complete-byte ID/scratch/counter/W1C bank with aligned byte/halfword semantics, one controlled write wait, and exact zero-extended 32-bit reads | SILICON-QUALIFIED subset |
| External AHB, fabric master | fabric → MCU SRAM | no route, no qualification | roadmap |
| MCU GPIO ↔ fabric | both | four-bit inverter loopback over all input combinations; exact L48 GPIO5 data/OE lanes 0–1 plus input lane 2 | SILICON-QUALIFIED subset |
| `local_int[3:0]` | fabric → MCU | delivers CLINT **local causes 16–19** with matching `mip` bits, enabled via `mie` directly (**not** the PLIC) | SILICON-QUALIFIED subset |
| `ext_dma_*` | both | 4-bit request outputs / 2× 4-bit inputs | RE-INFERRED / UNPROVEN |
| `EXT_INT0..7` (PLIC 37–44) | fabric → MCU | unconnected hypotheses | RE-INFERRED / UNPROVEN |

Two firmware-visible facts worth repeating:

- **Misaligned CPU accesses to the fabric window fault deterministically in the
  hard core** (`mcause` 5 = load access, 7 = store access) and **never reach the
  fabric**. That is why the qualified aligned surface is complete.
  **SILICON-QUALIFIED.**
- **`HRESP` from the fabric does not become an MCU access fault** on L48. An
  exact two-cycle error response added 511 MTIME ticks across 256 reads and
  exposed an `0xffffff4f` active-response witness, but raised **zero** load or
  store access traps after a passing `ecall` trap-path control. This is retained
  architectural negative evidence, and the "HRESP → MCU exception" claim is
  **RETIRED**. **SILICON-QUALIFIED (negative).**

See [MCU_AHB_INTERFACE.md](MCU_AHB_INTERFACE.md),
[MCU_AHB_REGISTER_BANK.md](MCU_AHB_REGISTER_BANK.md), and
[HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md).

---

## Provenance tally

Counted by block/feature entry on this page.

| Tier | Count | Entries |
|---|---:|---|
| **SILICON-QUALIFIED** | **16** | CRC0 known-answer · DMAC0 mem-to-mem · UART0 internal loopback · UART0 external TX · I2C0 · SPI0 · WATCHDOG0 (snapshot + supervised reset) · CLINT/MTIME timer interrupt · ADC0/1/2 one-shot · DAC0/1 · CMP0 unit 1 + internal DAC→ADC taps · MCU→pad GPIO through the IO ring · FCB config path · flash controller (backup/erase/program/verify + boot from existing pointer) · RV32 SRAM execution · USB device path (CDC uploader) |
| *of which negative results* | 5 | SPI low-lane payload stuck at `0x00` · UART ~560 baud from an assumed clock · RTC counter does not advance · CAN0 frames do not shift · `HRESP` raises no MCU fault |
| **REGISTER-MAP DERIVED** | **18** | SYSCTL/RCC (most fields) · PLIC · GPIO0–3, 5–9 and the GPIO interrupt path · UART1–4 and most UART bit fields · SPI1, SPI DMA/POLL/DUAL/QUAD · I2C1 and slave mode · CAN0 interrupt/error/filter/FIFO registers · USB0 register groups · Ethernet MAC0 (entire block) · TIMER0/1 · GPTIMER0–4 (entire block) · RTC beyond the config path · IWDG · CRC0 alternate poly/width/reflection · FCB `ADDR`/`DATA`/`INT` and the non-AUTO `CTRL` strobes · FCB `ERR_ID`/`ERR_HEADER` classes · ADC `CHNL` read-side packing (not modelled by the HAL) · analog register reset values (**none recorded anywhere**) |
| **RE-INFERRED / UNPROVEN** | **15** | GPIO `RIS`/`MIS`/`IC` offsets (PL061-implied, unconfirmed) · SP804 `VALUE`/`MIS`/`BGLOAD` and the extra `CTRL` bits · SPI `CTRL` bit 10 endianness · SPI RX sub-word lane placement · SPI out-of-set divider behaviour · CAN0 TX frame-window layout · CMP0 unit 2 (enables, reads high at all codes) · external ADC channels 0–3 full-scale reads (cause unestablished) · CMP0 `PSEL` 1…2 / `MSEL` 1…7 ranges and the "external analog input 1" name · `ext_dma_*` sideband semantics · `EXT_INT0..7` · FCB `0x08` name/purpose vs `ag32.h`'s `0x0C` · FCB `DEVOE → IO_GHIZ` mechanism · DAC DMA rate formula (no RTL source) · the exact nine-point ADC sweep series (two sources disagree) |

---

## Open questions worth escalating

1. **The clock tree is not characterized.** Which source feeds which peripheral,
   and by what division, is unknown. The documented single-APB model cannot
   explain a measured UART/SPI ratio of ~18. Nothing downstream of a baud or
   prescaler solve can be trusted until this is resolved.
2. **CAN0 TX buffer layout.** `TXFRAME` (`0x40`) read back `0x00` after writing
   `0x08`. The PeliCAN frame packing in `ag32_can.h` may be wrong for this
   controller.
3. **SPI `CTRL` bit 10.** The vendor names it an endianness select and its own
   flash driver packs the LOW lane with the bit set; this board shifts the HIGH
   lane first with the same bit set. One of the two readings is wrong.
4. **SPI RX sub-word lane placement** is unmeasured, and TX is known *not* to be
   the obvious lane — so RX must not be assumed to mirror it.
5. **GPIO interrupt-register offsets** (`RIS`/`MIS`/`IC`) are PL061-implied, not
   independently recovered, and no AGaMEMnon header defines them.
6. **CMP0 unit 2's positive-input mux** maps somewhere other than unit 1's, in an
   undocumented way.
7. **The "ADC channels 0–3 are not bonded on L48" claim is contested.**
   `ag32_adc.h` asserts it; the lab record declines to characterize bonding; and
   a datasheet-derived pin table lists `ADC_IN0..3` as alternate functions of
   `PIN_10..PIN_13`, which are bonded and demonstrably drivable L48 pads. The
   full-scale reads are real; their cause is not established.
8. **The exact ADC sweep series is unreconciled** between the SDK header /
   `STATUS.md` / `ANALOG_FABRIC_BOUNDARY.md` (`…512, 1024, 1536, 2054, 2575,
   3085, 3598…`) and the workbench lab record (`…511, 1024, 1538, 2054, 2573,
   3085, 3594…`) — four of nine points. The conclusion is unaffected; the numbers
   should be reconciled or stopped being quoted.
9. **FCB offset `0x08`**: `ag32.h` calls `0x0C` the data port; the extracted
   register model calls `0x08` `DATA` and `0x0C` `AUTO`. The proven recipe uses
   `0x0C`; `0x08`'s role is unverified.
10. **No analog register reset values exist in any source.** Every value on
    record is a post-write readback.
11. **RTC/IWDG are blocked on a low-speed clock** that this board does not run.
    Both are config-reachable and functionally untestable until LSI or a 32 kHz
    LSE crystal is available.
12. **Summary-table drift:** `STATUS.md` and `PERIPHERAL_CATALOG.md` still list
    SPI/I2C as driver-only and UART0 as loopback-only, and
    `PERIPHERAL_CATALOG.md`'s own master table and fabric-analog section disagree
    about DAC0/1 (silicon-qualified vs "unknown"). The evidence is real; the
    summary tables need updating.

---

*Cross-reference: [HAL_FPGA_REFERENCE.md](HAL_FPGA_REFERENCE.md) ·
[STATUS.md](STATUS.md) (authoritative) · [MCU_CLOCKS.md](MCU_CLOCKS.md) ·
[PERIPHERAL_CATALOG.md](PERIPHERAL_CATALOG.md) ·
[MCU_PIN_ROUTING.md](MCU_PIN_ROUTING.md) ·
[ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md) ·
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md)*
