# AG32 UART0 bootloader through a Raspberry Pi Pico 2

Status as of 2026-07-15: the Pico firmware, host implementation, safety flow,
and LED demonstration images exist and are software-tested. The qualification
Pico has been reflashed and its USB/control interface works. End-to-end AG32
ROM communication is not yet qualified because the existing harness does not
connect the dedicated AG32 BOOT0 package pin. No AG32 flash write was attempted
during this bring-up.

This note separates facts stated by AGM, facts recovered from the mask ROM,
bench observations, and remaining inferences. That distinction matters until
the target returns device ID `0x40200001` over this new path.

## What the hardware documentation establishes

The AG32 reference manual's System Control section defines two relevant boot
modes:

- `BOOT0=0`, `BOOT1=x`: boot main flash;
- `BOOT0=1`, `BOOT1=0`: enter the flash-independent UART0 boot ROM.

The straps are sampled on the fourth rising edge of `SYSCLK` after reset, and
BOOT0 must not float. The LQFP-48 package table assigns:

| Package pin | Signal |
|---:|---|
| 7 | NRST |
| 20 | `PIN_20` / BOOT1 |
| 30 | `PIN_30` / UART0_TX |
| 31 | `PIN_31` / UART0_RX |
| 44 | dedicated BOOT0 |

AGM's DAP-Link v2.5 manual describes its Serial programming mode as target
UART TX/RX with target BOOT0 pulled high. Its Downloader screenshot selects
460800 baud, and the documented successful device-ID result is `0x40200001`.
The reset connection is optional in AGM's manual because an operator may press
the target reset button; the Pico uses it to automate entry and exit.

## What the dumped mask ROM establishes

The AG32 boot-ROM dump is an 8-KiB RV32 program at `0x00010000`. Its serial
command loop at approximately `0x00010aaa` reads two bytes and accepts them
when their sum is `0xff`: a command byte followed by its complement. Therefore
`00 ff`, `02 fd`, `13 ec`, `33 cc`, and `44 bb` are valid command frames. This
is not merely an assumption based on another MCU family.

The same disassembly provides:

- ACK `0x79`, NACK `0x1f`, and BUSY `0x76`;
- GET `0x00` and GET_ID `0x02`;
- extended read `0x13`, up to 1024 data bytes;
- extended write `0x33`, with a two-byte length and a ROM limit of 4096 bytes;
- extended page erase `0x44`;
- advertised ROM version `0x20` and command list
  `00 01 02 13 33 44 21 63 73 82 92 a2 a3 a1`;
- device ID read from fixed register `0x03000100`;
- UART initialization using 8-bit, no-parity, one-stop framing.

The host uses 460800 8N1 because that is the AGM Downloader configuration and
matches the UART setup recovered during the wider AG32 bring-up. A live logic
capture remains the final authority for exact on-wire timing.

## Implemented software

The checked-in Pico sketch is
[`pico/ag32_uart_programmer/ag32_uart_programmer.ino`](../pico/ag32_uart_programmer/ag32_uart_programmer.ino).
It provides:

- Pico UART1 on GP20/GP21 at 460800 8N1;
- push-pull BOOT0 selection on GP22;
- open-drain NRST on GP26, with a weak pull-up only while released;
- temporary BOOT1-low on GP27 across reset, then high impedance;
- a 2048-byte UART receive FIFO, large enough for one maximum ROM read;
- USB commands for boot selection, reset, UART transfer, status, and electrical
  diagnosis.

The host implementation is
[`agamemnon/uart_program.py`](../agamemnon/uart_program.py). The public CLI is:

```text
agamemnon uart-probe
agamemnon uart-backup OUTPUT
agamemnon uart-flash IMAGE --addr ADDRESS --backup FULL_BACKUP
agamemnon uart-reset
```

`uart-flash` deliberately cannot write without a complete 256-KiB backup. It
reads and fsyncs that backup before erase, reconstructs complete touched 4-KiB
sectors, erases only those pages, writes their complete images, and verifies
their complete readback. It lowers BOOT0 and resets into flash only after a
successful comparison. A failure leaves the target in ROM recovery.

Protocol and sector-preservation tests are in
[`tests/test_uart_program.py`](../tests/test_uart_program.py). The Pico sketch
was compiled with Arduino-Pico 5.4.2 and uploaded successfully to the Pico 2
on COM6. Current whole-repository test results belong in CI rather than this
transport-specific historical note.

## Hardware required on the LQFP-48 bench

The old Pico GPIO characterization harness uses GP0 through GP19 and does not
include AG32 package pin 44. Disconnecting the DAP does not create the missing
BOOT0 connection. Add:

| Pico 2 | Direction | AG32 target |
|---|---:|---|
| GP20 / UART1 TX | -> | package pin 31 / UART0_RX |
| GP21 / UART1 RX | <- | package pin 30 / UART0_TX |
| GP22 | -> | package pin 44 / BOOT0 |
| GP26 | open-drain -> | package pin 7 / NRST |
| GP27 | open-drain -> | package pin 20 / BOOT1 |
| GND | -- | target ground |

Use a BOOT0 test pad or target-side boot jumper if the board exposes one;
soldering directly to the package leg should be the last choice. Recommended
passives are 1-kohm series resistors in GP22/GP26/GP27 and a 10-kohm target-side
pull-up on NRST. BOOT0 should have a 10-kohm default pull-down so an unpowered
or disconnected Pico leaves the board in normal flash boot. BOOT1 must be low
while ROM boot is latched.

Both boards use 3.3-V signaling, but their VBUS/3V3 rails must not be joined.
They need only a common ground.

### DAP-Link coexistence

The DAP-Link UART TX and Pico GP20 are push-pull outputs aimed at the same AG32
RX input. They must never be wired together. The current bench solution is to
disconnect the DAP-Link TX path. A durable adapter should instead provide one
of:

1. a jumper selecting DAP TX or Pico TX;
2. a 3.3-V 2:1 logic mux;
3. an output-enable buffer that guarantees the inactive TX is high impedance.

AG32 TX may feed both DAP RX and Pico GP21 because both are inputs. A small
interposer with a keyed six-pin Pico programming header, BOOT0 access, reset
pull-up, default boot pulls, and explicit TX selection is the recommended
repeatable hardware change.

## Current bench evidence

The following observations were made without erasing or writing AG32 flash:

1. The Pico enumerated on COM6 and answered its version, reset, status, and
   UART bridge commands.
2. With the DAP disconnected, released NRST initially read low. Enabling the
   Pico's weak pull-up made it read high; a permanent target-side pull-up is
   preferable.
3. After selecting ROM boot and waiting at least 100 ms after reset, the line
   connected to GP21/AG32 UART0_TX became and remained idle-high. This indicates
   that the target is powered and that the observed TX line is electrically
   driven.
4. Valid command/complement pairs `7f 80`, `00 ff`, and `02 fd` produced no
   reply.
5. The dedicated BOOT0 package pin 44 is not present in the old harness.

The best current inference is that the AG32 has not actually sampled
`BOOT0=1`, consistent with the missing pin-44 connection. A missing GP20 to
target-RX connection remains the other plausible cause. The evidence does not
support changing the ROM protocol or writing flash blindly.

## Qualification sequence after the hardware change

Do these in order:

1. Check continuity and confirm BOOT0 changes at the target pad while NRST is
   asserted and released.
2. Run the read-only probe:

   ```powershell
   agamemnon uart-probe --port COM6
   ```

   Continue only after it reports device ID `0x40200001`.
   `uart-flash` enforces the same check internally after connecting and aborts
   before backup, erase, or program on any mismatch.
3. Take two full reads and compare them:

   ```powershell
   agamemnon uart-backup before-a.bin --port COM6
   agamemnon uart-backup before-b.bin --port COM6
   Get-FileHash before-a.bin,before-b.bin
   ```

4. Flash the compressed LED fabric at the board's existing compressed-image
   pointer, preserving the decompressor sector:

   ```powershell
   agamemnon uart-flash .tmp/uart_led_demo/led_ahb.bin.comp `
     --addr 0x80008100 --backup before-led-fabric.bin --port COM6
   ```

5. Flash the 36-byte walking-pattern MCU image:

   ```powershell
   agamemnon uart-flash .tmp/uart_led_demo/led_blink.bin `
     --addr 0x80000000 --backup before-led-mcu.bin --port COM6
   ```

The LED sources and build recipe are in
[`examples/uart_led_demo`](../examples/uart_led_demo/README.md). Each visible
Johnson-pattern step is triggered by another protocol-valid External-AHB write
from the newly flashed MCU firmware.

## Sources

Primary AGM-derived documentation and silicon artifacts:

- [AG32 MCU Reference Manual, current AGM-hosted revision](https://www.ag32mcu.com/wp-content/uploads/2026/02/AG32-MCU-Reference-Manual20250930%E4%BF%AE%E8%AE%A2%E7%89%88%EF%BC%89.pdf),
  especially System Control boot modes, the LQFP-48 package table, and UART;
- `AG32-Docs/docs/reference/markdown/AGM_DAP_LINK_v2.5.md`, the research
  workbench transcription of section "Programming AG32 Series MCU";
- `AG32-Docs/tools/dumps/bootrom.asm`, the qualification-device boot-ROM
  disassembly;
- `AG32-Docs/docs/guides/AG32VF303_Bringup.md`, which records the ROM-dump
  provenance and earlier UART observations;
- `AG32-Docs/tools/arch_dec_agr.txt`, used as a second check on UART0 and
  boot-pin package assignments.

The `AG32-Docs` research workbench is not currently public, and those derived
artifacts are not redistributed in this repository. They are listed by exact
path for provenance rather than presented as public links.

Pico implementation sources:

- [Arduino-Pico `SerialUART` interface](https://github.com/earlephilhower/arduino-pico/blob/master/cores/rp2040/SerialUART.h), including selectable TX/RX pins, 8N1 configuration, FIFO sizing, and overflow reporting.
- [Raspberry Pi Pico-series documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html).

The boot-ROM command descriptions in this note are reverse-engineering results,
not a protocol specification published by AGM. They are kept separate from the
manual-derived claims for that reason.
