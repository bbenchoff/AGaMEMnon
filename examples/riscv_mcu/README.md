# RISC-V MCU firmware examples

These are freestanding programs for the AG32's hard RV32 core. They do not
require the AGM SDK, a C library, or a fabric build. Shared startup code sets
the stack/global pointer, copies `.data`, clears `.bss`, calls `main`, and
stops on `ebreak` if `main` returns.

## Build

From the repository root on Windows:

```powershell
./examples/riscv_mcu/build.ps1
```

The script finds `riscv64-unknown-elf-gcc` on `PATH` or in PlatformIO's
installed `toolchain-agrv` package. On Linux/macOS:

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

Back up the complete target sector, program the separately linked image, and
verify it. PowerShell computes the exact byte count so `agrv32flash` erases
only the necessary 4-KiB page:

```powershell
$tool = "agrv32flash"
$app = ".tmp/riscv_mcu/led_blink_usb_app.bin"
$size = (Get-Item $app).Length

& $tool -r .tmp/riscv_mcu/pre-sector16.bin `
  -S 0x80010000:4096 COM7
& $tool -w $app -S "0x80010000:$size" -v COM7
& $tool -g 0x80010000 COM7
```

LED1 (vendor default `GPIO4.1`, `PIN_34`) blinks. The program does not service
USB, so COM7 stops responding after `GO`; press reset to return to the uploader.
Restore the sector through COM7 when finished:

```powershell
& $tool -w .tmp/riscv_mcu/pre-sector16.bin `
  -S 0x80010000:4096 -v COM7
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
  --addr 0x80000000
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
