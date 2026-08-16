# RISC-V MCU firmware examples

These are freestanding programs for the AG32's hard RV32 core. They do not
require the AGM SDK, a C library, or a fabric build. The packaged startup code
sets the stack/global pointer and direct trap vector, copies `.data`, clears
`.bss`, calls `main`, and stops on `ebreak` if `main` returns.

## Build

From the repository root on Windows:

```powershell
./examples/riscv_mcu/build.ps1
```

The script accepts either the bundled `riscv-none-elf-gcc` or
`riscv64-unknown-elf-gcc` on `PATH`, and also recognizes PlatformIO's installed
`toolchain-agrv` package. On Linux/macOS:

```bash
sh examples/riscv_mcu/build.sh
```

Outputs are placed in `.tmp/riscv_mcu`:

| Image | Link address | Purpose |
|---|---:|---|
| `sram_signature.bin` | `0x20000000` | volatile core/device/ISA proof |
| `reset_counter_flash.bin` | `0x80000000` | persistent reset execution and SRAM mailbox |
| `led_blink_flash.bin` | `0x80000000` | native flash-boot LED1 blink |
| `led_blink_usb_app.bin` | `0x80010000` | USB-loaded LED1 blink that preserves the resident uploader |
| `timer_led_walk_flash.bin` | `0x80000000` | CLINT/MTIME-driven four-LED walk |
| `timer_led_walk_usb_app.bin` | `0x80010000` | USB-launched CLINT/MTIME four-LED walk |
| `basic_timer_led_walk_flash.bin` | `0x80000000` | polled hard TIMER0 four-LED walk |
| `basic_timer_led_walk_usb_app.bin` | `0x80010000` | USB-launched hard TIMER0 four-LED walk |
| `hard_peripheral_inventory.bin` | `0x20000000` | non-destructive generated peripheral-map catalog |
| `uart_dma_loopback.bin` | `0x20000000` | safe polling-HAL smoke test: SRAM DMA plus internal UART0 loopback |
| `exception_mailbox.bin` | `0x20000000` | recover from a machine-mode ECALL and record its trap CSRs |
| `software_interrupt.bin` | `0x20000000` | trigger and clear the core-local CLINT software interrupt |
| `timer_interrupt.bin` | `0x20000000` | schedule and clear a core-local MTIME interrupt |
| `local_interrupt[0-3].bin` | `0x20000000` | configure a volatile fabric image and capture the selected `local_int` lane in an SRAM mailbox |
| `local_interrupt_independent.bin` | `0x20000000` | arm lanes 0–3 in turn and trigger each from an External-AHB address bit; requires the matching four-source workbench image |
| `crc_self_test.bin` | `0x20000000` | hard CRC-32/MPEG-2 known-answer test with no pin or flash access |
| `watchdog_snapshot.bin` | `0x20000000` | read-only APB watchdog state snapshot |

The checked-in flash linker refuses to grow through `0x80007000`, where the
qualified board's factory decompressor begins. The USB application linker
starts at sector 16 (`0x80010000`), clear of the loader, decompressor, and
compressed fabric image in the qualified layout.

## 1. Volatile SRAM signature

This is the safest first MCU example. It writes four words at `0x20001000`
and does not touch flash or require a fabric image:

```powershell
agamemnon sram .tmp/riscv_mcu/sram_signature.bin --words 4 --sleep 100
```

Qualified output:

```text
[0] 0x52563332  "RV32"
[1] 0x40200001  DEVICE_ID
[2] 0x40801125  misa: RV32IMAFC
[3] 0x2000007a  executing inside the SRAM image
```

`agamemnon sram` loads the binary at `0x20000000`, sets PC and SP, runs it,
and reads the mailbox. Reset the board afterwards to return to its normal
flash image.

## 2. Load and run an application through USB

This path requires the flash-resident CDC uploader documented in
[`USB_CDC_UPLOADER.md`](../../docs/USB_CDC_UPLOADER.md). It is not present on
an untouched stock board.

Program the separately linked image with the native USB transport. The command
creates a complete pre-write backup, preserves unaffected bytes in the touched
4-KiB sector, and verifies the result:

```powershell
$app = ".tmp/riscv_mcu/led_blink_usb_app.bin"
agamemnon flash $app --addr 0x80010000 `
  --backup .tmp/riscv_mcu/pre-usb-app-full.bin `
  --transport usb --port COM7
agamemnon go 0x80010000 --transport usb --port COM7
```

LED1 (vendor default `GPIO4.1`, `PIN_34`) blinks. The program does not service
USB, so COM7 stops responding after `GO`; press reset to return to the uploader.
Restore the original sector through COM7 when finished, while taking another
complete backup before the restore write:

```powershell
$flash = [IO.File]::ReadAllBytes(".tmp/riscv_mcu/pre-usb-app-full.bin")
[byte[]]$sector16 = $flash[0x10000..0x10fff]
[IO.File]::WriteAllBytes(".tmp/riscv_mcu/pre-sector16.bin", $sector16)
agamemnon flash .tmp/riscv_mcu/pre-sector16.bin `
  --addr 0x80010000 `
  --backup .tmp/riscv_mcu/pre-usb-restore-full.bin `
  --transport usb --port COM7
```

This example retains the uploader at `0x80000000`. Reset still boots the
uploader; `GO 0x80010000` is what transfers control to the example.

This exact sequence was silicon-tested. After `GO`, SWD observed PC
`0x80010090`, GPIO4's APB clock enabled, GPIO4.1 configured as a software
output, and the LED data bit high. Reset returned to the COM7 uploader; the
saved 4-KiB sector was restored, read back again, and matched byte-for-byte.

## 3. Replace native flash boot

`led_blink_flash.bin` and `reset_counter_flash.bin` are linked for the MCU
reset address. Back up the complete flash before replacing sector 0:

```powershell
agamemnon backup .tmp/riscv_mcu/before-native-app.bin
agamemnon flash .tmp/riscv_mcu/led_blink_flash.bin `
  --addr 0x80000000 `
  --backup .tmp/riscv_mcu/before-native-app-second-copy.bin
```

After reset or power-on, the RV32 core runs the image directly. This operation
replaces the entry sector of the USB uploader, so USB programming will not
survive the reset. Restore the complete backup over SWD to return exactly to
the previous layout:

```powershell
agamemnon flash .tmp/riscv_mcu/before-native-app.bin `
  --addr 0x80000000 `
  --backup .tmp/riscv_mcu/before-native-restore.bin
```

`reset_counter_flash.bin` uses the same flow. It maintains this warm-reset
mailbox at `0x20001000`:

```text
word 0  0x434e5452  "CNTR"
word 1  execution count
word 2  0x40200001  DEVICE_ID
word 3  PC inside 0x80000000 flash image
```

SRAM retention across a warm reset is useful for diagnosis but is not
nonvolatile storage; a power cycle may clear or randomize it.

## Board and fabric dependency

The RV32 core, SRAM, flash controller, System Control, and FCB are hard silicon.
GPIO peripheral addresses and package-pin routing come from the active fabric
configuration. `led_blink.c` assumes the vendor default mapping
`GPIO4.1 -> PIN_34 -> LED1`, which is present in both the vendor default board
logic and the qualified minimal USB fabric. If a custom fabric remaps GPIO,
change `LED1`/the peripheral address or provide matching fabric.

The four-LED timer examples use `GPIO4[1:4]`. The vendor default L48 fabric
maps those bits to the four board LEDs; the qualified minimal USB fabric only
guarantees `GPIO4.1`, so load a matching fabric before expecting all four.
See [the peripheral matrix](../../docs/PERIPHERAL_EXAMPLES.md) for the hard-MCU
versus soft-FPGA distinction and safe pin rules.

## Open polling HAL smoke test

`uart_dma_loopback.bin` exercises two open drivers without relying on a
package-pin route. DMA channel 0 copies four words inside SRAM. UART0 is put in
the controller's internal loopback mode before transmitting `0xA5`; no UART pin
is driven. Run it through DAP like the signature example:

```powershell
agamemnon sram .tmp/riscv_mcu/uart_dma_loopback.bin --words 8 --sleep 100
```

The mailbox is `"HAL0"`, packed DMA status, packed UART status/received byte,
device ID, the UART reference clock the baud divisor was solved from, and
`CLK_CNTL` / `PBUS_DIVIDER` / `MTIME_PSC`. A zero DMA status/mismatch and low
byte `0xA5` are success.

The baud clock is measured, not assumed: `ag32_uart_ref_hz_measured()` returns
UART0's back-solved ~14.47 MHz reference. No part of the SDK configures the clock
tree, and UART0's is the **only** peripheral reference that has actually been
measured — SPI0's absolute reference is unresolved, although its documented
power-of-two divider is silicon-qualified by relative timing and exact readback.
Do not assume a single peripheral clock (see
[MCU_CLOCKS.md](../../docs/MCU_CLOCKS.md#measured-default-clock-on-an-sram-loaded-part)).
Words 5–7 publish the three clock registers so a run can re-derive the domain
instead of trusting a constant.

This image is compile-tested but has not yet been added to the
silicon-qualified matrix. The published-register SPI and I2C polling APIs are
available through `ag32.h`; they need an intentional fabric route and, for I2C,
external pull-ups, so this safe diagnostic does not start them.

## Trap and interrupt examples

The canonical startup in `agamemnon/sdk/startup.S` installs a direct-mode
machine trap entry, preserves the interrupted code's caller-saved registers,
and calls:

```c
void ag32_trap_handler(uint32_t mcause, uint32_t mepc, uint32_t mtval);
```

Applications override that weak symbol. `exception_mailbox.c` demonstrates
the important exception rule: a recoverable handler must write `mepc` past the
faulting instruction before returning. `software_interrupt.c` and
`timer_interrupt.c` demonstrate the two core-local CLINT paths without touching
flash, fabric, or package pins.

All three write their result at `0x20001000` and can be run with the same
volatile `agamemnon sram ... --words 4` workflow as `sram_signature.bin`.
They are compiled in CI, but are not yet claimed as silicon-qualified.

External peripheral interrupts use the PLIC, not the CLINT. The complete
published source IDs 1 through 44 and safe enable/claim/complete helpers are in
`ag32_interrupt.h`. A PLIC handler must clear the peripheral's own interrupt
condition and then write the claimed source ID to the completion register.

## Hard CRC known-answer test

`crc_self_test.c` enables only the hard AHB CRC block and feeds the standard
ASCII `"123456789"` vector as byte accesses. With polynomial `0x04C11DB7`,
initial value `0xFFFFFFFF`, no reflection, and no final XOR, CRC-32/MPEG-2 is
`0x0376E6E7`. The mailbox contains `"CRC0"`, the observed result, the expected
result, and `"PASS"` or `"FAIL"`.

This is compile-tested and non-destructive, but remains a hardware
qualification candidate until its mailbox result is appended to the evidence
record.

## APB watchdog snapshot

`watchdog_snapshot.c` covers the programmable 32-bit APB watchdog described in
manual section 9.3, not the separate option-controlled independent watchdog.
It preserves the APB clock-gate state and never unlocks, starts, feeds, or
reprograms the block. Its four mailbox words are `"WDT0"`, current count,
control, and packed raw/masked/lock status.

Run it immediately after reset through the volatile SRAM path. The register
layout and active control API are compile-tested, but neither is claimed as
silicon-qualified until this snapshot and an intentionally supervised timeout
test are recorded.
