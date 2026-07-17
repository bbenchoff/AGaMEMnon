# Pico 2 AG32 UART programmer

This Arduino sketch turns a Raspberry Pi Pico 2 into AGaMEMnon's USB-to-UART
programming adapter. It drives the AG32 BOOT0 and NRST straps, speaks to the
flash-independent mask-ROM loader through UART0 at 460800 8N1, and returns the
target to normal flash boot after a verified write. It is the hardware half of
`agamemnon uart-probe`, `uart-backup`, `uart-flash`, and `uart-reset`.

## From logic analyzer to programmer

The Pico did not start as a programmer. AG32 bring-up needed an electrical
oracle — an instrument that could confirm a routed fabric design really drove
its package pins — so a Pico 2 was wired to the development board as a cheap,
scriptable logic analyzer. GP0 through GP19 form that characterization
harness, including the qualified fabric LED pads PIN_25 through PIN_28, and it
remains the observation side of the silicon evidence in
[hardware qualification](../../docs/HARDWARE_VALIDATION.md).

Because that Pico was already on the bench and sharing ground with the target,
it grew a second job. The AG32 mask ROM contains a UART0 bootloader that works
even when main flash is corrupt, and five more wires — UART0 RX and TX, BOOT0,
BOOT1, and NRST on GP20–GP22, GP26, and GP27 — are all it takes to drive it.
The same board became the recovery-capable programming transport behind the
`agamemnon uart-*` commands. The ROM protocol recovery, host safety flow, and
current qualification boundary are documented in
[UART bootloader](../../docs/UART_BOOTLOADER.md).

## What the firmware does

- selects the boot mode: push-pull BOOT0 on GP22, with BOOT1 driven low only
  while the straps latch and then released so firmware may use PIN_20;
- resets the target through an open-drain NRST on GP26, driven low or released
  with a weak pull-up, never driven high;
- bridges USB CDC to UART1 at 460800 8N1 with a 2048-byte receive FIFO, large
  enough to hold one maximum 1024-byte ROM read while the host performs USB
  command/response round trips;
- reports electrical state without changing it: `STATUS` reads the observed
  target RX, boot-strap, and reset levels, and `SENSE` tests whether the
  target TX line is actively driven or floating.

## Wiring

| Pico 2 | Direction | AG32 LQFP-48 |
|---|---:|---|
| GP20 / UART1 TX | -> | package pin 31 / `PIN_31` / UART0_RX |
| GP21 / UART1 RX | <- | package pin 30 / `PIN_30` / UART0_TX |
| GP22 | -> | package pin 44 / BOOT0 |
| GP26 | open-drain -> | package pin 7 / NRST |
| GP27 | open-drain -> | package pin 20 / `PIN_20` / BOOT1 |
| GND | -- | target ground |

Both boards use 3.3-V logic. Join ground only; never join either board's 3V3
or VBUS rail.

If the board's DAP-Link serial TX is already connected to AG32 UART0_RX,
disconnect or mux that output before adding GP20. DAP-Link RX may stay
attached to the target TX line. Never parallel the Pico and DAP-Link push-pull
TX pins. Recommended series resistors and default boot-strap pulls are in
[UART bootloader](../../docs/UART_BOOTLOADER.md).

## Build and upload

Build and upload with the Earle Philhower Arduino-Pico core:

```powershell
arduino-cli compile --fqbn rp2040:rp2040:rpipico2 pico/ag32_uart_programmer
arduino-cli upload -p COM6 --fqbn rp2040:rp2040:rpipico2 pico/ag32_uart_programmer
```

## Using it

The host-facing ASCII protocol (`PING`, `STATUS`, `SENSE`, `BOOT`, `UART`) is
an implementation detail; use the `agamemnon uart-*` commands documented in
[Programming](../../docs/PROGRAMMING.md):

```text
agamemnon uart-probe --port COM6
agamemnon uart-backup full-flash.bin --port COM6
agamemnon uart-flash image.bin --addr 0x80000000 --backup full-flash.bin --port COM6
agamemnon uart-reset --port COM6
```

`uart-flash` refuses to write without a complete, verified 256-KiB backup, and
it lowers BOOT0 and resets into flash only after a successful byte comparison.
A failure leaves the target in ROM recovery.
