# Programming the AG32

AGaMEMnon has three programming paths with different recovery properties:

- CMSIS-DAP/SWD and OpenOCD drive the on-chip flash controller directly.
- A Raspberry Pi Pico 2 drives BOOT0, BOOT1, and NRST and streams the mask-ROM
  protocol through AG32 UART0. This path remains available when main flash is
  blank or corrupt.
- A flash-resident TinyUSB CDC ACM uploader exposes the AGM loader protocol on
  the target USB connector. This path is silicon-qualified for identify,
  read, erase, write, verify, restore, and reset, but depends on valid main
  flash and is not a ROM recovery mechanism.

| Transport | Untouched stock board | Recovery capable | Hardware modification |
|---|---|---|---|
| DAP/SWD | Yes, with AGaMEMnon's qualified OpenOCD | Yes | No |
| USB CDC | No; uploader must first be installed | No | No |
| UART mask ROM/Pico | ROM supports it | Yes | Current L48 board/harness requires added wiring |

The USB uploader is neither mask-ROM USB boot nor USB DFU class. See
[USB_CDC_UPLOADER.md](USB_CDC_UPLOADER.md) for its source corrections, backup
hashes, exact bench transcript, and recovery boundary.

An untouched stock board cannot upload over USB: its hardware is capable, but
the loader is absent from factory flash on the qualification unit. Install the
loader once through SWD or UART0 ROM, then use the right-hand target USB-C
connector for later transfers. The tested standalone loader returns to itself
after reset. Booting an uploaded application persistently requires a separate,
non-overlapping application layout; `0x80008000` must not be used because the
existing compressed fabric begins at `0x80008100`.

None of the three AGaMEMnon CLI transports uses the vendor `agrv` flash driver.
The native USB client implements the qualified loader protocol directly in
Python; `agrv32flash` remains useful only as an independent comparison tool.

For MCU binary format, linker addresses, startup requirements, and runnable
SRAM/native-flash/USB examples, see
[RISCV_MCU_PROGRAMMING.md](RISCV_MCU_PROGRAMMING.md).

Hardware commands require an OpenOCD executable implementing AGM's
RISC-V-over-ADIv5-DAP target option, `target create riscv -dap`. Stock upstream,
xPack, and OSS CAD Suite binaries do not contain that extension.

```bash
agamemnon install-openocd
agamemnon doctor --probe-dap
```

`AGAMEMNON_OOCD_CFG` and `AGAMEMNON_OOCD_SCRIPTS` override the packaged target
configuration and OpenOCD script directory. `AGAMEMNON_OPENOCD` remains an
explicit executable override.

DAP operations are single-attempt. If OpenOCD cannot start, reaches its
operation timeout, or exits nonzero during an SRAM/program session, AGaMEMnon
returns a concise transport error. It does not retry a write and does not
accept partial mailbox or readback output. After a failed mutation the target
state is explicitly unknown until it is identified and restored from the
mandatory backup.

The qualified build is official OpenOCD parent `a17c5f5a`, Gerrit 9590
patchset 2 (`9aa0f976`), plus AGaMEMnon's nested ADIv5-config repair
(`f96d840a`). The Windows artifact passed probe, halt, register and SRAM
read/write/restore, SRAM firmware execution, full flash backup, sector
program/readback/restore, full-device hash restoration, and reset recovery.
The machine-readable record is
[`evidence/openocd-windows-ag32.json`](evidence/openocd-windows-ag32.json).

## Commands

| Command | Behavior |
|---|---|
| `agamemnon probe` | reads `DEVICE_ID`; no persistent write |
| `agamemnon probe --transport usb [--port PORT]` | identifies the resident CDC uploader and AG32 |
| `agamemnon probe --transport uart [--port PORT]` | resets through Pico into ROM and identifies AG32 |
| `agamemnon sram FW --fabric FABRIC` | loads fabric and firmware into SRAM and runs them |
| `agamemnon backup FILE` | reads the complete 256-KiB main flash |
| `agamemnon flash FILE --addr ADDR --backup FILE` | backs up full flash, erases touched sectors, programs, reads back, and verifies |
| `agamemnon backup FILE --transport usb` | reads all flash through USB CDC |
| `agamemnon flash FILE --addr ADDR --backup FILE --transport usb` | preserves sectors and verifies through USB CDC |
| `agamemnon go ADDR --transport usb` | launches a separately linked application |
| `agamemnon image ...` | plans or writes MCU and uncompressed fabric regions |
| `agamemnon image ... --write-options` | opt-in, unsupported option-byte pointer operation |
| `agamemnon uart-probe [--port PORT]` | resets into the serial ROM and reads the device ID |
| `agamemnon uart-backup FILE [--port PORT]` | reads all 256 KiB through UART0 |
| `agamemnon uart-flash FILE --addr ADDR --backup FILE [--port PORT]` | preserves sectors, writes, verifies, and resets into flash |
| `agamemnon uart-reset [--port PORT]` | selects normal boot and resets the target |

Native mask-ROM USB boot and USB DFU class are not implemented. The separate
flash-resident CDC ACM uploader is silicon-qualified on the LQFP-48 bench.

## Pico 2 UART programmer

Flash the checked-in bridge firmware first (the port shown here is an example):

```powershell
arduino-cli compile --fqbn rp2040:rp2040:rpipico2 pico/ag32_uart_programmer
arduino-cli upload -p COM6 --fqbn rp2040:rp2040:rpipico2 pico/ag32_uart_programmer
```

For the qualified LQFP-48 AG32 board, add these wires to the existing Pico
harness:

| Pico 2 | Direction | AG32 LQFP-48 signal | Package pin |
|---|---:|---|---:|
| GP20 / UART1 TX | -> | UART0_RX / `PIN_31` | 31 |
| GP21 / UART1 RX | <- | UART0_TX / `PIN_30` | 30 |
| GP22 | -> | BOOT0 | 44 |
| GP26 | open-drain -> | NRST | 7 |
| GP27 | open-drain -> | `PIN_20` / BOOT1 | 20 |
| GND | -- | GND | any board ground |

Cross TX and RX as shown. Both sides are 3.3-V logic. Keep the AG32 board on
its normal supply and the Pico on USB; **do not connect Pico VBUS or 3V3 to the
AG32 power rail**. The Pico drives BOOT1 low only while reset is being latched,
then releases GP27 so target firmware can use `PIN_20`. NRST is only driven low
and otherwise is released with the Pico's weak input pull-up enabled.

The strap pins may have passive pull resistors, but they must not be hard-tied
or actively driven by another device. Remove a hard BOOT0/BOOT1 strap before
connecting the Pico. A 1-kohm series resistor in each Pico control lead
(GP22/GP26/GP27) is recommended for contention protection; it is not needed to
change the logic protocol.

The qualification board's AGM DAP-Link adapter (the existing target serial
port, COM5 on the bench) is also wired to UART0. **Disconnect or mux the
DAP-Link TX-to-AG32-UART0_RX path before connecting Pico GP20.** Two push-pull
TX outputs must not be connected together. DAP-Link RX may remain connected to
AG32 UART0_TX because it is only another input. If the board has no removable
UART jumper, open its TX solder bridge or add a 3.3-V two-input UART mux; a
series resistor alone is not a reliable bus selector.

Install the host dependency and check the link:

```bash
python -m pip install -e ".[programming]"
agamemnon uart-probe --port COM6
```

The AG32 ROM uses UART0 at 460800 baud, 8 data bits, no parity, and one stop
bit. The Pico owns that target-side baud rate; the USB CDC baud selected by the
host is immaterial. If exactly one Pico is connected, `--port` can be omitted.

The bridge firmware and host protocol are software-tested, and the Pico on the
qualification bench has been flashed and USB-smoke-tested. Target-side UART
qualification requires the five signal wires above; until that is completed,
the UART path must not be described as silicon-qualified.

The complete source trail, ROM-protocol findings, current bench transcript,
and proposed programming interposer are documented in
[UART_BOOTLOADER.md](UART_BOOTLOADER.md).

## Volatile SRAM execution

```bash
agamemnon sram firmware.bin --fabric design.bin --words 10
```

The command places:

```text
0x20000000  firmware
0x20001000  result words
0x20002000  99,944-byte uncompressed fabric image
```

The firmware calls `ag32_fcb_config()`, performs the test or application work,
and stores optional observations at `0x20001000`. SRAM execution does not touch
flash and is the preferred development and qualification path.

## Main-flash programming

Create a complete backup before every write:

```bash
agamemnon backup full-flash.bin
agamemnon flash payload.bin --addr 0x80020000 --backup full-flash.bin
```

Main flash occupies `0x80000000..0x8003ffff`. `flash` erases every 4-KiB sector
spanned by the payload, programs through the controller at `0x40001000`, reads
the region back into a unique fresh temporary file, requires a successful dump
with the exact expected length, and compares it byte-for-byte. A dump failure,
truncation, or byte mismatch exits nonzero.
Before any DAP, USB, or mask-ROM UART mutation or execute command, the host
performs a separate identity read and requires device ID `0x40200001`.

Option bytes occupy a separate region at `0x81000000` and are not modified by
`flash`.

The UART equivalent makes the backup mandatory and preserves complete touched
sectors automatically:

```bash
agamemnon uart-flash payload.bin --addr 0x80020000 \
  --backup pre-uart-write.bin --port COM6
```

It first reads and fsyncs the entire main flash to the backup file, overlays the
payload on the saved sector images, erases only the touched 4-KiB pages, writes
those complete pages, and compares their complete readback. Only after a clean
comparison does it lower BOOT0 and reset into flash. A failed write leaves
BOOT0 high in serial-ROM recovery.

## Existing compressed boot layout

On the qualified board, option bytes select a compressed fabric image at
`0x80008100` and a decompressor at `0x80007000`. Replace the image without
changing the option pointers:

```bash
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

The decompressor and fabric image can share a 4-KiB erase sector. Preserve and
restore the complete affected sector; erasing only the visible image fragment
can destroy part of the decompressor.

Fabric configuration from flash occurs on power-on. A debugger warm reset does
not rerun the complete fabric boot sequence.

## Image planning

```bash
agamemnon image --fabric design.bin --mcu firmware.bin
agamemnon image --fabric design.bin --mcu firmware.bin \
  --flash --backup full-flash.bin
```

Without `--flash`, `image` prints a write plan. With `--flash`, it writes the
MCU and uncompressed fabric regions through the same verified main-flash path.
Those writes do not change the boot ROM's fabric pointer. `--flash` always
requires a complete `--backup`; the capture is size-checked and atomically
published before any erase begins.

`--write-options` also attempts to write the uncompressed-config pointer at
`0x81000030`. This operation is not a supported deployment path. It requires
an explicit flag, `--flash`, the main-flash backup, and a distinct
`--option-backup` containing all 128 option bytes. It must not be used to claim
a bootable layout.

## Recovery

- Keep the complete 256-KiB backup off-board.
- Restore it with
  `agamemnon flash full-flash.bin --addr 0x80000000 --backup pre-restore.bin`.
- The SWD debug path is independent of main-flash contents.
- With the Pico adapter, restore over the flash-independent ROM path with
  `agamemnon uart-flash full-flash.bin --addr 0x80000000 --backup pre-restore.bin`.
- `uart-reset` drives BOOT0 low and pulses NRST without writing flash.

See [flashboot/FLASH_LAYOUT.md](flashboot/FLASH_LAYOUT.md) for the memory map
and [flashboot/flash_controller.md](flashboot/flash_controller.md) for the
controller register sequence.
