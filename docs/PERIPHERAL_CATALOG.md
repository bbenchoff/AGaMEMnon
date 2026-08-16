# AG32 peripheral catalog

Goal: a single reference for **every** AG32 peripheral the AGaMEMnon toolchain
must eventually know — both the hard MMIO blocks operated by the RISC-V core and
the programmable-logic (fabric) edge interfaces — with each block's base
address, function, register behavior (in prose), current AGaMEMnon
support/qualification state, and the concrete path to full support.

Scope conventions:

- **Silicon-qualified** — exercised by an electrically observable hardware
  oracle and recorded in a qualification ledger.
- **Driver-only** — a clean polling driver / register model is shipped, built
  from the published register manual, but not yet hardware-qualified.
- **Config-path** — the register/configuration surface is reachable and
  partially proven, but the headline function (e.g. timekeeping) is not.
- **Unknown / hardware-gated** — no shipped driver, or the block needs external
  hardware (transceiver, PHY, host) absent from the qualification bench.

Sources are cited by relative name. Public-side sources live in this repo
(`docs/`, `examples/riscv_mcu/`, `agamemnon/sdk/include/`,
`qualification/`). Register-map ground truth was cross-checked against the
vendor AGM PlatformIO SDK headers preserved in the sibling RE workbench
(`framework-agrv_sdk` `*.h`, `framework-agrv_ips/analog_ip.h`) and the public
AG32 MCU Reference Manual (2025-05-15) linked from
[`MCU_CLOCKS.md`](MCU_CLOCKS.md). Register names/offsets restated here are
already public in AGaMEMnon's own `sdk/include` headers and the vendor manual;
no proprietary binary content is reproduced.

`DEVICE_ID` on the qualification part reads `0x40200001` (AGRV2KL48 /
AG32VF303CCT6), RV32IMAFC, 256 KB flash, 128 KB SRAM.

## Address-space map

| Region | Base | Contents |
|---|---|---|
| CLINT (RISC-V core-local) | `0x02000000` | `MSIP`, `MTIMECMP`, `MTIME` |
| System control / RCC | `0x03000000` | reset, clock, power, MTIME prescaler, bus/APB/AHB gating, `DEVICE_ID` |
| APB peripherals | `0x40010000`–`0x4002Cxxx` | FCB, watchdog, SPI, GPIO, timers, UART, CAN, I2C, RTC/backup |
| AHB peripherals | `0x41000000`+ | DMAC0, USB0, CRC0, Ethernet MAC0 |
| External-AHB / fabric + analog IP | `0x60000000`+ | fabric slaves (constant/register banks), ADC/DAC/comparator analog IP |
| PLIC (external-interrupt controller) | `0x0C000000` | priority/enable/claim for 44 sources |
| Main flash (XIP + controller) | `0x80000000` | code/data + flash-control registers; option/FPGA-pointer bank at `0x81000000` |

The RTC/backup-domain block sits at `0x40000000` (below the APB window) and also
hosts the independent watchdog (IWDG) register.

## Master table

Instance families and counts are from
[`examples/riscv_mcu/hard_peripheral_inventory.c`](../examples/riscv_mcu/hard_peripheral_inventory.c)
(13 families, 33 instances). Bases/IRQ numbers are from vendor `AltaRiscv.h`;
qualification pointers are `hard_peripheral_evidence.jsonl` unless noted.

| Peripheral | Base(s) | Function | AGaMEMnon state | Evidence / source |
|---|---|---|---|---|
| System control / RCC | `0x03000000` | reset flags, clock select, power, MTIME prescaler, PBUS divider, APB/AHB reset+gate, `DEVICE_ID` | Config-path (partial) | `ag32_sysctl.h`; reset-flag bit30 proven by watchdog trial |
| CLINT / MTIME | `0x02000000` | machine timer + software interrupt (`MSIP`) | Silicon-qualified | `timer_interrupt.c`, `mcause=0x80000007` |
| PLIC | `0x0C000000` | 36 internal + 8 external IRQ priority/claim | Driver-only | `ag32_interrupt.h`; `EXT_INT0..7` unconnected hypotheses |
| FCB0 (fabric config bridge) | `0x40010000` | streams config words into the eFPGA; APB-gated | Config-path (used as loader) | `ag32.h` `ag32_fcb_config()`, `FCB_STAT_OK` |
| WATCHDOG0 | `0x40011000` | windowed watchdog, supervised warm reset | Silicon-qualified | `watchdog_snapshot.c`, `watchdog_supervised.c` |
| SPI0, SPI1 | `0x40012000`, `0x40013000` | multi-phase SPI controller | SPI0 master-transmit and sub-word RX lane placement silicon-qualified on exact L48 routes; arbitrary slave-driven RX/duplex remains unproven; SPI1 driver-only | `ag32_spi.h`; `hard_peripheral_evidence.jsonl` |
| GPIO0–GPIO9 | `0x40014000` +`0x1000` | PL061-style GPIO, masked data, per-pin IRQ, alt-func mux | Config-path (GPIO4 exercised) | `ag32.h` GPIO4 macros; vendor `gpio.h` |
| TIMER0, TIMER1 (basic) | `0x4001E000`, `0x4001F000` | SP804-style dual 32/16-bit down-counters | Driver-only (raw MMIO) | `basic_timer_led_walk.c`; vendor `timer.h` |
| GPTIMER0–GPTIMER4 (advanced) | `0x40020000` +`0x1000` | STM32-TIM-style timers: capture/compare, PWM, break/dead-time | Driver shipped (`ag32_gptimer.h`), no silicon | vendor `gptimer.h` |
| UART0–UART4 | `0x40025000` +`0x1000` | PL011-style UART, FIFOs, fractional baud, loopback, DMA | UART0 internal loopback and external-pad TX silicon-qualified; independent PIO receiver decoded 64/64 exact bytes at 9600/38400/115200 nominal baud. RX/flow control and UART1–4 remain open | `uart_dma_loopback.c`; `ag32_uart.h`; `uart_baud_evidence.jsonl` |
| CAN0 | `0x4002A000` | SJA1000-style CAN 2.0 controller | Unknown / hardware-gated — **no CAN bits observed on a wire**, no ledger row | vendor `can.h`; `ag32_can.h` ships; needs transceiver |
| I2C0, I2C1 | `0x4002B000`, `0x4002C000` | OpenCores-style I2C master (prescaler + command/status) | I2C0 master-transmit **framing** silicon-qualified on L48 pads (needs external pull-up); reads/ACK unproven; I2C1 driver-only | `ag32_i2c.h`; `hard_peripheral_evidence.jsonl` |
| DMAC0 | `0x41000000` | PL080-style 8-channel DMA, linked-list descriptors | Silicon-qualified (mem-to-mem) | `uart_dma_loopback.c` |
| USB0 | `0x41001000` | ChipIdea/EHCI USB FS + OTG (host + device) | Device path silicon-qualified (via CDC uploader); host/OTG hardware-gated | STATUS "Bitstreams and programming"; vendor `usb.h` |
| CRC0 | `0x41002000` | CRC-32/MPEG-2 hardware unit | Silicon-qualified | `crc_self_test.c` == `0x0376E6E7` |
| Ethernet MAC0 | `0x41040000` | 10/100 MAC, MDIO, descriptor rings, hash filter | Unknown / hardware-gated | vendor `mac.h`; needs PHY |
| RTC + backup domain | `0x40000000` | 32-bit counter, prescaler, alarm, backup regs, `BDCR` clock select | Config-path (no timekeeping) | `rtc_count.c`; `ag32_rtc.h` |
| IWDG (independent WDT) | `0x40000034` (in RTC block) | LSI/LSE-clocked independent watchdog | Unknown (needs low-speed clock) | vendor `iwdg.h` |
| Flash controller | `0x80000000` / `0x81000000` | XIP, erase/program/verify, option + FPGA-config pointers | Silicon-qualified | STATUS; vendor `flash.h` |
| ADC0/1/2 | `0x60000000/1000/2000` | 12-bit SAR ADC, 16-deep sequencer, DMA | Silicon-qualified one-shot subset (vendor-macro fabric image) | `analog_probe.c`; `ag32_adc.h`; `ANALOG_FABRIC_BOUNDARY.md` |
| DAC0/1 | `0x60003000/4000` | 10-bit DAC, buffered, DMA | Silicon-qualified static-output subset | `analog_probe.c`; `ag32_dac.h` |
| Comparator CMP0 | `0x60005000` | dual analog comparator, selectable +/- inputs | Unit 1 silicon-qualified; unit 2 unproven | `analog_probe.c`; `ag32_comparator.h` |

Silicon-qualified hard blocks: **CRC0, DMAC0, UART0 (internal loopback + external
pad TX), I2C0 (master-transmit framing), SPI0 (master transmit), WATCHDOG0,
CLINT/MTIME, flash controller, USB device path** (9), plus the analog
**ADC0/1/2, DAC0/1, CMP0 unit 1** reached over External AHB (3 more, with the
vendor-macro caveat below **and** no append-only ledger row yet).
Config-path/partial: **SYSCTL/RCC, FCB0, GPIO, RTC** (4). Driver-only: **SPI1,
I2C1, PLIC, basic timers, UART1–4** . Unknown / hardware-gated: **GPTIMER, CAN,
Ethernet MAC, IWDG, USB host/OTG, CMP0 unit 2** .

The UART0-external-TX, I2C0, and SPI0 rows are transmit-side framing and
byte-exactness claims only, produced by workbench stimulus firmware that is not
part of this repository. None of them qualifies a *bit rate*: the programmed
baud, the 100 kHz I2C rate, and SPI0's SCK divider are all unproven, because no
peripheral reference clock other than UART0's has been measured. See
[MCU_CLOCKS.md](MCU_CLOCKS.md).

---

## Per-peripheral detail

### CRC0 — `0x41002000` (silicon-qualified)
STM32-style CRC unit. Registers: `DR` (data in / result out, `0x00`), byte
`IDR` scratch (`0x04`), `CR` control/reset (`0x08`), programmable `INIT`
(`0x10`) and `POL` (`0x14`). Default operation is CRC-32/MPEG-2. **Qualified:**
known-answer of ASCII `123456789` → `0x0376E6E7` on L48 silicon
(`crc_self_test.c`). **Missing:** any other polynomial/width/reflection mode,
and the `INIT`/`POL` programmable path. **Path:** add known-answer vectors for
alternate `POL`/`INIT`/reflection and log each.

### DMAC0 — `0x41000000` (silicon-qualified subset)
PL080-style controller: 8 channels, each with `SrcAddr`/`DstAddr`/`LLI`
(linked-list)/`Control`/`Configuration`. Global block has interrupt status +
terminal-count/error status and clear registers, software burst/single request
registers, and a `Sync` register. **Qualified:** single-channel memory-to-memory
4-word SRAM copy (`uart_dma_loopback.c`). **Missing:** peripheral-linked flow
control, descriptor chaining (`LLI`), wider/multi-channel transfers, and the
fabric DMA-request sidebands (see fabric-edge section). **Path:** qualify one
peripheral-linked channel (e.g. UART or ADC request), then descriptor chaining,
then a fabric-request handshake.

### UART0–UART4 — `0x40025000` +`0x1000`/instance (UART0 silicon-qualified)
PL011-style. Registers: `DR` data (`0x00`), `RSR_ECR` receive-status/error-clear
(`0x04`), `FR` flags (`0x18`), integer/fractional baud `IBRD`/`FBRD`
(`0x24`/`0x28`), line-control `LCR_H` (`0x2C`), control `CR` (`0x30`), FIFO-level
`IFLS` (`0x34`), interrupt mask/raw/masked/clear `IMSC`/`RIS`/`MIS`/`ICR`
(`0x38`–`0x44`), and `DMACR` (`0x48`). Loopback via `CR.LBE`. **Qualified:**
UART0 internal loopback echoed `0xA5`, status clean; and UART0 **TX** reached a
physical L48 pad (PIN_10) through an open peripheral-route fabric, byte-exact
against an off-chip logic-analyzer capture of a known stimulus. With the measured
UART reference, an independent Pico PIO receiver decoded 64/64 exact pattern
bytes at requested 9600, 38400, and 115200 baud. The former ~560-baud run is
retained as the negative for incorrectly passing `ag32_pbus_hz(248000000)`.
**Missing:** external RX, sub-percent absolute calibration, hardware flow control,
UART1–4, other oscillator states, and dynamic clock switching. **Path:** route RX
and run a real external-pin loopback while measuring the reference independently.

### SPI0, SPI1 — `0x40012000`, `0x40013000` (SPI0 transmit + RX lane qualified)
Vendor register model is a **multi-phase** controller: `CTRL` (`0x00`) plus eight
`PHASE_CTRL` (`0x10`–`0x2C`) and eight `PHASE_DATA` (`0x30`–`0x4C`) registers —
i.e. a programmable command/phase sequencer rather than a plain shift register.
`ag32_spi.h` ships a clean polling driver. **Qualified (SPI0 only):** master
transmit on physical L48 pads (SCK PIN_12, MOSI PIN_14, CSN PIN_13) — 233/233
decoded words all `0x55`, plus `11 22 33 44` with 108 pattern matches, **MSB-first
and requiring CS to frame words**. This also qualifies the sub-word byte-lane
fix: the controller shifts the *high-order* bytes of `PHASE_DATA`, so
`ag32_spi_write` left-justifies payloads. Sampled-high 1–4-byte RX phases prove
that valid receive bytes occupy the low-order lanes while upper bits are stale;
the API now masks them. **Missing:** arbitrary slave-driven RX values and
multi-byte order, full-duplex interoperability, DUAL/QUAD widths, DMA and POLL
phases, broader multi-phase sequences, and SPI1 entirely. The former divider defect is repaired: the old SDK asserted
`CTRL.SOFT_RESET`, which discarded the following configuration write. APB reset
plus direct programming qualifies powers of two 2–256 by exact readback and
strictly monotonic MTIME latency. SPI0's **absolute** reference clock remains
unresolved — see [MCU_CLOCKS.md](MCU_CLOCKS.md). **Path:** measure that reference
independently and characterize RX lanes against a real SPI slave.

### I2C0, I2C1 — `0x4002B000`, `0x4002C000` (I2C0 transmit framing silicon-qualified)
OpenCores-style master: `PRERLO`/`PRERHI` clock prescaler (`0x00`/`0x04`), `CTR`
control/enable (`0x08`), `TXR`/`RXR` shared transmit/receive at `0x0C`, and
`CR`/`SR` shared command/status at `0x10` (START/STOP/READ/WRITE/ACK commands;
TIP/busy/ack-received status). `ag32_i2c.h` ships. **Qualified (I2C0 only):**
master-transmit *framing* on physical L48 pads (SDA PIN_11, SCL PIN_15) — 288
decoded transactions, every one `addr=0x55` direction W, with correct
START/STOP/address/direction/data phases. The per-byte NACKs are the **expected**
result because no slave is on the bus. **Requires an external pull-up:** the bus
is open-drain, and with no pull-up the engine stalls and a capture reads flat
zero. **Missing:** reads, ACK handling against a real slave, clock stretching,
repeated START, 10-bit addressing, slave mode, the programmed 100 kHz rate
(I2C0's own reference clock has never been measured — the driver borrows UART0's
as a labelled cross-domain assumption), and I2C1 entirely. **Path:** bus a real
device on SRAM-only firmware and verify SCL with a scope.

### CAN0 — `0x4002A000` (unknown / hardware-gated)
SJA1000-style controller with dual register personalities (reset vs operating
mode): `MOD`, `CMR`, `SR`, `IR`/`IER`, bus-timing `BTR0/1`, `OCR`, arbitration/
error capture `ALC`/`ECC`, error counters `EWLR`/`RXERR`/`TXERR`, TX/RX frame +
data windows, acceptance code/mask filters, a 64-word RX FIFO, and a 13-word TX
buffer. **Blocked:** needs an external CAN transceiver (absent on bench); no
driver shipped. **Path:** add transceiver, ship a driver, qualify loopback then
two-node traffic.

### USB0 — `0x41001000` (device path silicon-qualified; host/OTG gated)
ChipIdea/EHCI OTG core: capability registers (`CAPLENGTH`/`HCIVERSION`/
`HCSPARAMS`/`HCCPARAMS`), operational `USBCMD`/`USBSTS`/`USBINTR`/`FRINDEX`,
`PERIODICLISTBASE`/`ASYNCLISTADDR` (host) aliased with `DEVICEADDR`/
`ENDPOINTLISTADDR` (device), `PORTSC`, `OTGSC`, `USBMODE`, and endpoint
prime/flush/status/complete/`ENDPTCTRL[]` registers driven by qTD/dTD/queue-head
descriptor structures. Two general-purpose timers are embedded in the block.
**Qualified:** the **device** path is exercised through the flash-resident USB
CDC-ACM uploader on L48 (enumerate, identify, read, page-erase, write, verify,
restore, reset) — see STATUS "Bitstreams and programming". **Missing:** an
MCU-MMIO USB driver in the `riscv_mcu` examples, USB **host**/OTG (no host on
bench), and the required 60 MHz USB PLL point. **Path:** a minimal MMIO device
enumeration example under MCU control; host mode needs a connected host.

### Ethernet MAC0 — `0x41040000` (unknown / hardware-gated)
10/100 MAC: `CTRL`/`STAT`, `MACMSB`/`MACLSB` address, `MDIO` PHY management,
`TXBASE`/`RXBASE` descriptor-table pointers, and `HTMSB`/`HTLSB` hash filter.
**Blocked:** needs a board PHY (absent). A register-map-derived driver now ships
(`ag32_mac.h`), but it has never been exercised — no PHY, no silicon. **Path:**
PHY hardware + MDIO bring-up + descriptor-ring driver.

### Basic timers TIMER0/TIMER1 — `0x4001E000`/`0x4001F000` (driver-only)
ARM SP804-style dual timer. Per sub-timer: `Load`, `Value`, `Ctrl` (size32,
periodic, enable, interrupt-enable, prescale), `IntClr`, raw/masked interrupt
status `RIS`/`MIS`, background-load. AGaMEMnon drives TIMER0 by raw MMIO in
`basic_timer_led_walk.c` (periodic 32-bit, RIS-polled). **Missing:** a ledgered
silicon record and a typed driver; TIMER1 unexercised. **Path:** add a
`hard_peripheral_evidence` row for a timed TIMER0 interrupt.

### Advanced timers GPTIMER0–4 — `0x40020000` +`0x1000` (unknown)
STM32-TIM-style: `CR1/CR2`, slave-mode `SMCR`, `DIER`, `SR`, `EGR`, capture/
compare-mode `CCMR0/1`, `CCER`, `CNT`, `PSC`, `ARR`, repetition `RCR`, four
`CCR0..3`, break/dead-time `BDTR`. Capable of PWM, input capture, encoder mode.
**State:** a register-map-derived driver ships (`ag32_gptimer.h`) plus a
`gptimer_pwm.c` example; **no silicon**. **Path:** PWM-output and input-capture
bench tests.

### GPIO0–GPIO9 — `0x40014000` +`0x1000` (config-path; GPIO4 exercised)
PL061-style. The data register is address-masked: `GpioDATA[256]` maps address
bits [9:2] as a write/read bit-mask, so `base + (mask<<2)` touches only the
masked pins (used as `GPIO4_DATA(mask)`). Control: `GpioDIR` (`0x400`),
interrupt sense/both-edge/event/mask `GpioIS/IBE/IEV/IE` (`0x404`–`0x410`),
raw/masked status `GpioRIS/MIS`, clear `GpioIC`, and alternate-function select
`GpioAFSEL` (`0x420`). Each GPIO instance has its own PLIC IRQ. AGaMEMnon uses
GPIO4 (LED mask `0x1E`) on silicon to walk board LEDs and as a fabric reset
source. **Missing:** a full GPIO-matrix / package-pin driver and per-instance
qualification; interrupt path unproven. **Path:** typed GPIO driver + per-pin
IRQ and alt-func qualification (roadmap "GPIO and hard-peripheral routes").

### System control / RCC — `0x03000000` (config-path, partial)
`BOOT_MODE` (BOOT0/1 pins), `RST_CNTL` (reset flags + software/external/FCB
reset control), `PWR_CNTL`, `CLK_CNTL` (HSE/PLL enable+ready, source select,
flash SCLK divider high/low fields), `BUS_CNTL`, `SWJ_CNTL` (JTAG/SWD pin
control), `MISC/DBG_CNTL`, wakeup trigger/pending, `MTIME_PSC`/`MTIME_COUNTER`,
`PBUS_DIVIDER`, per-bus `APB_RESET`/`AHB_RESET`/`APB_CLKENABLE`/`AHB_CLKENABLE`/
`APB_CLKSTOP`, and `DEVICE_ID` at `0x100`. **Qualified:** reset-cause readback
(`RST_CNTL` bit30 `SYS_RSTF_WDOG` set exclusively after supervised watchdog
reset); `DEVICE_ID` read; APB clock-enable used to gate FCB/GPIO4/TIMER0.
**Missing (deliberately):** no runtime HSI/HSE/PLL clock-switch API — the
source-select encoding and PLL multiplier register are not fully documented and
AGaMEMnon will not copy the vendor sequence (see `MCU_CLOCKS.md`). **Path:**
recover source-select + PLL programming model, measure each operating point on
the fixture, then expose a bounded setter with HSI fallback.

### CLINT / MTIME — `0x02000000` (silicon-qualified)
`MSIP` software interrupt at `0x0000`, `MTIMECMP` at `0x4000`, `MTIME` at
`0xBFF8` (64-bit split lo/hi). MTIME is the free-running system-clock reference
(also the clock-independent yardstick for PLL-frequency qualification).
**Qualified:** machine-timer interrupt taken, `mcause=0x80000007`
(`timer_interrupt.c`); `software_interrupt.c` exercises `MSIP`. **Path:** none
essential; already the backbone of the timing oracles.

### PLIC — `0x0C000000` (driver-only)
Platform-level interrupt controller for 44 sources (36 internal + 8 external),
16 priority levels. `ag32_interrupt.h` provides the ISR-table plumbing;
per-peripheral IRQ numbers are enumerated (FLASH=1 … MAC0=36, EXT_INT0..7 =
37–44). Local (CLINT) causes 16–19 are the four fabric `local_int` lanes and are
**not** PLIC sources. **Missing:** `EXT_INT0..7` are unconnected hypotheses
until a fabric path is proven; no silicon claim on external PLIC delivery.
**Path:** prove and qualify one `EXT_INTx` fabric source.

### RTC + backup domain — `0x40000000` (config-path, no timekeeping)
`CRH`/`CRL` control, `PRLH`/`PRLL` prescaler load, `DIVH`/`DIVL` divider,
`CNTH`/`CNTL` 32-bit counter, `ALRH`/`ALRL` alarm, `RCYC`, `BDCR` backup-domain
control (LSE enable/ready/bypass, `RTCEN` bit15, `RTCSEL` LSE/LSI/local at
[9:8]), `BDRST`, embedded `IWDG` at `0x34`, `RTCCR` calibration, and backup data
registers from `0x40`. **Qualified:** `BDCR` `RTCEN`+LSI-select stick and a
writable backup domain (`rtc_count.c`, `BDCR`→`0x8200`). **Missing:** the
counter does **not** advance — no low-speed clock runs on the bench (LSI-enable
or a 32 kHz LSE crystal absent), so timekeeping and alarms are unqualified.
**Path:** enable a low-speed clock (LSI or LSE crystal) and qualify counter
advance + alarm interrupt.

### IWDG — `0x40000034` (unknown)
Independent watchdog living inside the RTC/backup block: 3-bit prescaler,
reload-key (`0xA000`) + 4-bit reload, enable, stop/standby freeze, LSI/LSE clock
select. **Blocked:** shares the missing low-speed clock, so like the RTC counter
it cannot be qualified on the current bench. **Path:** same low-speed-clock
prerequisite, then a supervised IWDG-reset trial.

### Flash controller — `0x80000000` / options `0x81000000` (silicon-qualified)
Controller registers: key/option-key unlock, `SR`, `CR`, `AR` address, option
byte `OBR`/`WRPR`, `CONFIG`, and a DMA/read-control path. The option/FPGA bank
holds RDP/USER/DATA, oscillator config/cal, and four FPGA-config pointers
(plain + compressed + inverse copies) that the boot ROM follows to configure the
fabric from flash. **Qualified:** full-flash backup, erase, program, and
byte-verify readback; native and USB transports; boot from an existing
compressed-config pointer (STATUS "Bitstreams and programming"). **Missing:**
new option-pointer programming is opt-in / not deployment-supported. **Path:**
qualify option-pointer reprogramming with a staged recovery path.

### FCB0 — `0x40010000` (config-path, used as loader)
Fabric-configuration bridge. `ag32.h` streams a config image via `FCB_CTRL`
(auto mode), `FCB_DATA`, and polls `FCB_STAT` for `0x000F0002`. This is how the
MCU loads an SRAM fabric image (central to `agamemnon sram`). **Missing:** a
typed public driver and a ledgered standalone FCB record (it is exercised
implicitly by every SRAM/flash configuration). **Path:** document the FCB
status/word protocol and add an explicit qualification row.

---

## Fabric-edge peripherals (MCU ↔ eFPGA boundary)

The eFPGA reaches the MCU through the generated logic-macro contract (vendor
`gen_vlog`) rather than a fixed MMIO block. State summary from
[`STATUS.md`](STATUS.md) and [`MCU_FABRIC_ROADMAP.md`](MCU_FABRIC_ROADMAP.md):

- **External-AHB slave (fabric is the slave, MCU master).** MCU reads/writes a
  fabric endpoint in the `0x60000000` region. **Silicon-qualified:** all 32 read
  data lanes in one read; 32 write lanes in protocol-valid 4-bit groups;
  registered `HADDR[4:2]` plus additional address bits; a complete-byte
  ID/scratch/counter/W1C register bank with one controlled wait, aligned
  byte/halfword semantics, GPIO4.1 synchronous reset, and exact 32-bit reads; a
  constant slave returning `0x4147414d`; default `bus_clk = sys_gck` at exactly
  one bus clock per MTIME tick (the absolute rate, long printed as 10 MHz, is an
  [open question](MCU_CLOCKS.md#external-ahb-bus-clock)).
  A separate exact 16-bit held scratch is also silicon-qualified for aligned
  word/halfword and independent-byte write/hold/read, foreign-write rejection,
  SRAM-churn retention, repeated reads, one wait, and GPIO reset. Its low-16
  aligned word reads at +0/+4/+8/+c are isolated as `[state, 0, 0, 0]`.
  A hash-bound derivative moves that exact scratch to public offset +4, and the
  default exact public32 profile composes it with canonical ID32
  `0x4147414d`, counter3, and W1C1. Three complete hardware runs qualify exact
  raw 32-bit reads, unsigned byte/halfword lanes, zero extension, coexistence,
  and the retained lower-map matrix for that pinned L48 image. A distinct exact
  GPIO5-W1C derivative removes the bit1 self-test hook and uses MCU GPIO5 DATA0
  as a sustained-level set source. Base-negative, OR-control, and three
  production runs retain the full map and qualify low/hold/clear,
  high/set-priority, and reset dominance. GPIO5 is software-controlled
  qualification stimulus, not a package-pin or autonomous asynchronous event.
  **Missing:** hard `MCU_RESETN`, signed-load semantics, higher/full-window
  address decode, one reset-rearmed HCLK-synchronous counter event is qualified; a generic application-owned status-set socket, misaligned transfers, bursts
  (fail-closed), fabric-sourced HRESP→MCU-exception (retired), explicit
  BUSCLK/PLL3 clocking.
- **External-AHB master (fabric is the master).** **Unknown/roadmap:** no
  route/qualification yet; the plan is read-only reserved-SRAM transactions
  first, then bounded writes with canaries.
- **Fabric local interrupts `local_int[3:0]`.** Deliver CLINT local causes
  16–19 with matching `mip` bits, enabled directly via `mie` (not PLIC).
  **Silicon-qualified subset:** four independent sources routed simultaneously;
  an AHB-backed one-hot command bank does mask/ack/set/re-arm with masked hold;
  timing measured (21 MTIME ticks/op; a tick count, not a frequency).
  **Missing:** state readback,
  active-pending pre-`mie` visibility, POR/alternate-clock, hard reset; state is
  shared across the selected lane, not four simultaneous pending bits.
- **DMA request sidebands.** The macro contract exposes 4-bit request outputs
  `DMACBREQ`/`DMACLBREQ`/`DMACSREQ`/`DMACLSREQ` and 4-bit inputs `DMACCLR`/
  `DMACTC`; `EXT_DMA0..3_REQ` map to DMAC selectors 1–4, `FCB0_DMA_REQ` is 5.
  ADC0/1/2 and DAC0/1 bind to these selectors (ADC2/DAC1 share). **Unknown:**
  pulse polarity/duration and level-vs-pulse semantics of `DMACCLR`/`DMACTC` are
  not yet characterized; no silicon handshake qualified.
- **GPIO matrix at the fabric edge.** MCU GPIO↔fabric bridge: **silicon-
  qualified subset** — 4-bit inverter loopback over all input combinations; L48
  GPIO5 data/OE lanes 0–1 + input lane 2 through pure-open images. **Missing:**
  full GPIO-matrix / package-pin generality; output-enable/open-drain electrical
  behavior is human-gated.
- **`EXT_INT0..7` (PLIC external).** **Unknown** — treated as unconnected
  hypotheses until a wrapper/oracle proves a fabric path.

### Fabric-analog IP (ADC / DAC / comparator)
These are analog hard blocks instantiated as fabric IP and memory-mapped in the
External-AHB region, **not** MCU-core MMIO peripherals (vendor
`analog_ip.h`):

- **ADC0/1/2** (`0x60000000/1000/2000`): 12-bit (`0xFFF`) SAR with `CTRL`
  (start/stop/continuous/DMA-enable + `SCLK_DIV`), `STAT` (enabled/EOC), `DATA`,
  `CHNL` sequence length, and a 16-entry `SEQ[]` channel list (17 channels).
  Sample rate = APB / (1+`SCLK_DIV`) / 2 / 13. **State (updated 2026-08-14):**
  **SILICON-QUALIFIED** on L48 through the `0x60000000` window with the vendor
  `analog_ip` macro instantiated — a DAC0 sweep drove a monotonic, ~4.00x-linear,
  saturating response on ADC0/ADC1/ADC2 channel 4 (see `ANALOG_FABRIC_BOUNDARY.md`;
  the exact codes are a sample, not a constant). External channels 0–3 read full
  scale (`0xfff`), which means only that **no usable analog input was
  presented — the cause is not established.** An earlier "those analog pads are
  not bonded on L48" explanation is **withdrawn**: the datasheet-derived pin
  table puts `ADC_IN0..IN3` on PIN_10..PIN_13, and those pads are bonded and
  harness-confirmed working as digital IO. Unconfirmed candidates: the analog
  input mux is not enabled for those channels; the pad is held in digital mode
  by the fabric IO ring; the input is unconnected on this board; or a
  reference/bias is unconfigured. Treat them as UNPROVEN, not known-absent.
- **DAC0/1** (`0x60003000/4000`): 10-bit (`0x3FF`), `CTRL` (enable/buffer/DMA +
  `SCLK_DIV`) and `DATA`. **State (updated 2026-08-14):** static-output subset
  observed on L48 through the same vendor-macro path — DAC0 and DAC1 codes drove
  the internal DAC0→ADC-ch4 / DAC1→ADC-ch5 taps monotonically. `ag32_dac.h`
  ships. **Missing:** DMA and continuous modes, output buffering behavior, and
  any external analog pin claim.
- **Comparator CMP0** (`0x60005000`): dual comparator, `CTRL` (EN1/EN2), `CHNL`
  (+/- input selects), `DATA` (per-comparator output). **State (updated
  2026-08-14):** **unit 1** flipped at DAC0 codes 94/188/281/373 for the four
  internal VREF taps, against 93/186/279/372 predicted from vendor RTL. **Unit 2
  is UNPROVEN, not working:** its enable takes but its output read high at every
  DAC0 code under both PSEL2 selects. Hysteresis and mode bits are unexercised.

> None of the analog observations above has an append-only row under
> `qualification/`, and the fabric image they used instantiates the **vendor
> `analog_ip` macro, which AGaMEMnon's bitgen does not emit.** They are lab
> results on the L48 part, not entries in the qualification record and not
> evidence that the open flow can synthesize analog IP.

Path for all three: independent MCU register definitions + open drivers + pin
tables + non-destructive bench tests; determine ownership/reset/idle before
driving an analog input from fabric (roadmap "Analog blocks and cross-links").

---

## Gaps to full peripheral knowledge (ranked)

1. **Analog subsystem (ADC/DAC/comparator).** Drivers now ship (`ag32_adc.h`,
   `ag32_dac.h`, `ag32_comparator.h`) and a one-shot/static subset has been
   observed on the bench, so this is no longer a blank unknown. What remains:
   promote those observations into an append-only ledger row; explain why
   external ADC channels 0–3 read full scale; resolve CMP0 unit 2; cover DMA and
   continuous-scan modes; and — the structural gap — make the **open flow emit
   the analog IP**, which it currently cannot.
2. **MCU clock/PLL programming model (RCC).** Blocks a real clock-switch API and
   any peripheral needing a precise baud/sample clock (UART baud, ADC/DAC rate,
   USB 60 MHz). Recover source-select + PLL multiplier encoding and measure.
3. **DMA fabric handshake + peripheral-linked/descriptor modes.** DMAC0 core is
   proven mem-to-mem only; the request-sideband polarity/timing and
   peripheral-linked flow control are unqualified.
4. **GPIO as a typed, general driver.** Only GPIO4 raw-MMIO and a narrow GPIO5
   fabric subset are exercised; no matrix/IRQ/alt-func qualification.
5. **Advanced timers (GPTIMER0–4).** Five capable timers with zero driver
   coverage — needed for PWM/capture and timer/trigger cross-links.
6. **UART RX, absolute calibration, and UART1–4.** UART0 internal loopback and
   external-pad TX at three nominal rates are proven; external RX, sub-percent
   absolute calibration, and hardware flow control remain.
7. **SPI/I2C receive paths and bit rates.** SPI0 and I2C0 transmit framing is
   proven on pads, and SPI0 low-order RX lane placement is proven; what remains
   is arbitrary slave-driven RX/duplex and multi-byte RX order, DUAL/QUAD,
   a real-slave ACK, I2C reads, clock stretching, repeated START, absolute
   SPI reference timing, and the unmeasured I2C reference clock.
8. **RTC/IWDG low-speed clock.** Both are config-reachable but blocked on an
   absent LSI/LSE clock; needs a clock source before timekeeping/IWDG-reset.
9. **CAN and Ethernet MAC.** Hardware-gated (transceiver / PHY absent).
   Register-map-derived drivers now ship (`ag32_can.h`, `ag32_mac.h`) but
   neither has moved traffic. For CAN specifically, **no bits have been observed
   on a wire** and no ledger row exists, so the transmit-buffer/frame layout is
   the open question.
10. **USB as an MCU-MMIO driver + host/OTG.** Device path proven only via the
    flash-resident CDC uploader; no MMIO example and no host mode.
11. **Fabric AHB master + `EXT_INT0..7`.** Entirely roadmap; no route yet.

## KNOWN vs UNKNOWN summary

- **KNOWN (base + register map + prose behavior):** every block in the master
  table — bases and register layouts are recovered from vendor `AltaRiscv.h` /
  the per-peripheral vendor headers and restated here.
- **KNOWN + silicon-proven:** CRC0, DMAC0 (mem-to-mem), UART0 (loopback + pad
  TX), I2C0 (transmit framing), SPI0 (master transmit), WATCHDOG0, CLINT/MTIME,
  flash controller, USB device (CDC), plus the qualified fabric-edge subsets
  (External-AHB slave, `local_int`, GPIO bridge/GPIO5).
- **Observed on the bench but NOT in any ledger:** ADC0/1/2 one-shot, DAC0/1
  static output, CMP0 unit 1 — all via the vendor `analog_ip` macro.
- **KNOWN registers, UNKNOWN silicon behavior:** SPI/I2C receive paths, SPI1,
  I2C1, basic timers, UART1–4, PLIC external delivery, GPIO matrix/IRQ, RCC
  clock-switch.
- **UNKNOWN function / gated:** GPTIMER, CAN, Ethernet MAC, IWDG, CMP0 unit 2,
  ADC external channels and electrical behavior, USB host/OTG, fabric AHB
  master, `EXT_INT0..7`.

No register address in this document was invented; each is sourced from the
cited vendor SDK header, AGaMEMnon `sdk/include` header, or `examples/riscv_mcu`
program, and functional descriptions are paraphrased, not copied.
