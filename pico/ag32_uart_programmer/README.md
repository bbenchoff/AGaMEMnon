# Pico 2 AG32 UART programmer

This Arduino sketch turns a Raspberry Pi Pico 2 into AGaMEMnon's USB-to-UART
programming adapter. It drives AG32 BOOT0 and NRST, speaks to the mask-ROM
loader through UART0, and returns the target to normal flash boot after a
verified write.

The LQFP-48 wiring is GP20 to `PIN_31/UART0_RX`, GP21 from
`PIN_30/UART0_TX`, GP22 to BOOT0 (package pin 44), GP26 to NRST (package pin
7), GP27 to `PIN_20/BOOT1`, and a common ground. Do not join either board's
power rail. GP26 is open-drain with a weak input pull-up when released, and
GP27 is released as soon as the boot mode has latched.

If the board's DAP-Link serial TX is already connected to AG32 UART0_RX,
disconnect or mux that output before adding GP20. DAP-Link RX may stay attached
to the target TX line. Never parallel the Pico and DAP-Link push-pull TX pins.

Build and upload with the Earle Philhower Arduino-Pico core:

```powershell
arduino-cli compile --fqbn rp2040:rp2040:rpipico2 pico/ag32_uart_programmer
arduino-cli upload -p COM6 --fqbn rp2040:rp2040:rpipico2 pico/ag32_uart_programmer
```

The host-facing protocol is an implementation detail; use the `agamemnon
uart-*` commands documented in [Programming](../../docs/PROGRAMMING.md).
For bench diagnosis, `STATUS` reports the observed target RX, boot-strap, and
reset levels without changing them.
