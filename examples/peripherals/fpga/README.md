# Soft FPGA peripheral blocks

This directory contains independent Verilog-2001-compatible building blocks:

- `timer_tick.v`: programmable clock divider/tick source
- `gpio_walker.v`: four-output walking-one pattern
- `pwm4.v`: four 8-bit PWM comparators on one phase counter
- `uart_tx.v`: 8N1 transmitter
- `spi_master.v`: one-byte SPI mode-0 master
- `i2c_writer.v`: one-byte 7-bit-address I2C write controller
- `peripheral_showcase.v`: instantiates every block above
- `showcase_top.v`: safe four-LED package wrapper
- `tb_peripheral_showcase.v`: combined behavioral testbench

Run `simulate.ps1` or `simulate.sh`; success prints `PASS peripheral showcase`.
See [`docs/PERIPHERAL_EXAMPLES.md`](../../../docs/PERIPHERAL_EXAMPLES.md) for
build commands, interface limitations, pin safety, USB, and the MCU examples.
