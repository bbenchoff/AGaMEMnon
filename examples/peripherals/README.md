# Peripheral examples

- [`fpga/`](fpga/) contains small reusable RTL blocks, a structural showcase
  that instantiates them together, a four-LED board wrapper, and a simulation.
- [`../riscv_mcu/`](../riscv_mcu/) contains the freestanding hard-MCU timer,
  GPIO, peripheral-inventory, native-flash, SRAM, and USB-launched examples.
- [`../usb_cdc_uploader/`](../usb_cdc_uploader/) contains the reproducible
  patch set for the silicon-qualified hard-USB CDC uploader.

The complete support/qualification matrix and electrical caveats are in
[`docs/PERIPHERAL_EXAMPLES.md`](../../docs/PERIPHERAL_EXAMPLES.md).
