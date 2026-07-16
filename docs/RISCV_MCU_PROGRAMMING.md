# Programming the AG32 RISC-V MCU

Yes: AGaMEMnon can load and run code in the AG32's hard RISC-V core and can
erase, program, read back, and byte-verify its main-flash firmware.

The qualified device reports:

```text
DEVICE_ID  0x40200001
misa       0x40801125  (RV32IMAFC)
SRAM       0x20000000..0x2001ffff  (128 KiB)
main flash 0x80000000..0x8003ffff  (256 KiB, 4-KiB erase sectors)
boot ROM   0x00010000..0x00011fff  (8 KiB)
```

The MCU and fabric share the same physical main flash but occupy independent
regions. A raw MCU binary is ordinary RV32 code linked for its execution
address; it is not an FPGA bitstream and does not go through Yosys or nextpnr.

## Supported paths

| Path | MCU operation | Persistent | Recovery properties |
|---|---|---:|---|
| `agamemnon sram` over SWD | load at `0x20000000`, set PC/SP, run, read results | No | safest development path; reset restores flash boot |
| `agamemnon flash` over SWD | sector erase, program, readback compare | Yes | works even when application flash is corrupt |
| USB CDC uploader | identify, read, page erase, write, verify, `GO`, reset | Yes | requires the uploader already installed in valid main flash |
| Pico UART0 mask ROM | identify, backup, erase, write, verify, reset | Yes | flash-independent; target wiring qualification is still pending |

SWD main-flash programming and the USB CDC path are silicon-qualified. The
USB qualification included an exact readback of the resident 17,784-byte
loader, a controlled sector write, a full-sector verification, restoration to
the pre-test bytes, software reset, and a new device-ID handshake.

## Binary and linker requirements

AGaMEMnon accepts raw binary bytes; it does not impose an ABI or runtime. A
firmware build must provide:

- RV32 code compatible with the core (the examples use `-march=rv32imac` and
  `-mabi=ilp32`, a conservative subset of the available RV32IMAFC ISA);
- an entry point at the address where it will run;
- stack initialization or a debugger-provided stack;
- `.data` copying and `.bss` clearing if the program needs a C runtime;
- peripheral register definitions matching the active fabric configuration.

The examples provide a minimal startup and three linker layouts:

| Linker | Address | Boundary |
|---|---:|---|
| `link_sram.ld` | `0x20000000` | code/data below the result mailbox at `0x20001000` |
| `link_flash.ld` | `0x80000000` | image ends before the decompressor at `0x80007000` |
| `link_usb_app.ld` | `0x80010000` | separate application region retaining the USB loader at flash base |

Build and run the checked-in examples from
[`examples/riscv_mcu`](../examples/riscv_mcu/README.md).

## Volatile development

`sram` is fabric-optional. For an MCU-only binary:

```powershell
./examples/riscv_mcu/build.ps1
agamemnon sram .tmp/riscv_mcu/sram_signature.bin --words 4 --sleep 100
```

The example was run on the qualification device and returned:

```text
0x52563332  RV32 signature
0x40200001  DEVICE_ID
0x40801125  misa
0x2000007a  PC inside the SRAM image
```

When `--fabric design.bin` is also supplied, AGaMEMnon places the uncompressed
fabric image at `0x20002000`; firmware may stream it through FCB and then use
the fabric's GPIO or External-AHB peripherals. This remains volatile.

## Persistent native flash boot

MCU reset code begins at `0x80000000`. Back up all 256 KiB before replacing it:

```powershell
agamemnon backup before-mcu.bin
agamemnon flash firmware.bin --addr 0x80000000 --backup before-mcu-second.bin
```

`flash` erases every 4-KiB sector touched by the binary, programs it through
the hard flash controller, dumps the written range, and compares the bytes.
Bytes outside the provided image but inside a touched erase sector become
erased unless the caller included them in the image. The complete backup is
therefore the recovery artifact, not merely a precaution.

On the qualified factory layout:

```text
0x80000000  MCU reset/application region
0x80007000  factory fabric decompressor area
0x80008100  compressed fabric image
```

Do not let an MCU image or its erase sectors cross `0x80007000`. The example
flash linker enforces that boundary. Restore a saved layout with:

```powershell
agamemnon flash before-mcu.bin --addr 0x80000000
```

## Programming and running through USB

An untouched stock board does not contain the qualified uploader. Install it
once through SWD or UART0 ROM, then use the right-hand target USB-C connector.
The standalone qualified loader occupies `0x80000000` and resets back into
itself.

To preserve it, link an application at a separate address, back up that whole
sector, program it through COM7, and use the loader's `GO` command. The example
uses `0x80010000`; do not use the upstream `0x80008000` default because it
overlaps the compressed fabric at `0x80008100`.

```powershell
$app = ".tmp/riscv_mcu/led_blink_usb_app.bin"
$size = (Get-Item $app).Length
agrv32flash -r pre-sector16.bin -S 0x80010000:4096 COM7
agrv32flash -w $app -S "0x80010000:$size" -v COM7
agrv32flash -g 0x80010000 COM7
```

Press reset to return to the uploader, then restore `pre-sector16.bin` if the
test application is no longer wanted.

The checked-in `led_blink_usb_app.bin` flow was exercised on silicon. The
172-byte image was verified over USB, `GO` transferred execution to
`0x80010000`, SWD sampled PC `0x80010090` and GPIO4.1 driven high, reset
returned to the uploader, and the original 4-KiB sector was restored and
compared byte-for-byte.

## What is not automatic

AGaMEMnon does not currently provide a general application partition manager,
interrupt/runtime library, RTOS, or durable resident-loader/application boot
policy. It programs the bytes and verifies them; the firmware author owns the
link address, startup, peripheral map, interrupts, and application handoff.

The USB uploader is a flash-resident service program, not mask-ROM USB boot or
USB DFU class. Overwriting its entry sector removes USB recovery after reset.
Keep SWD or the UART0 mask-ROM path available while developing a native
flash-boot application.
