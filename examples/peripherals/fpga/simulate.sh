#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
DIR="$ROOT/examples/peripherals/fpga"
OUT=${1:-"$ROOT/.tmp/peripherals"}
mkdir -p "$OUT"

iverilog -g2012 -s tb_peripheral_showcase -o "$OUT/peripheral_showcase_tb.vvp" \
  "$DIR/timer_tick.v" "$DIR/gpio_walker.v" "$DIR/pwm4.v" \
  "$DIR/uart_tx.v" "$DIR/spi_master.v" "$DIR/i2c_writer.v" \
  "$DIR/peripheral_showcase.v" "$DIR/tb_peripheral_showcase.v"
vvp "$OUT/peripheral_showcase_tb.vvp"
