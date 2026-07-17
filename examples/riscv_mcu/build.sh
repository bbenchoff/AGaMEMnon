#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
OUT=${1:-"$ROOT/.tmp/riscv_mcu"}
PREFIX=${RISCV_PREFIX:-riscv64-unknown-elf-}
CC=${CC:-"${PREFIX}gcc"}
OBJCOPY=${OBJCOPY:-"${PREFIX}objcopy"}
EXAMPLE="$ROOT/examples/riscv_mcu"

mkdir -p "$OUT"

build_example() {
    source=$1
    linker=$2
    name=$3
    "$CC" -march=rv32imac_zicsr -mabi=ilp32 -Os -g \
        -nostdlib -ffreestanding -fno-builtin \
        -ffunction-sections -fdata-sections -I "$ROOT/mcu" \
        -T "$EXAMPLE/$linker" -Wl,--gc-sections -Wl,-Map,"$OUT/$name.map" \
        "$EXAMPLE/startup.S" "$EXAMPLE/$source" -o "$OUT/$name.elf"
    "$OBJCOPY" -O binary "$OUT/$name.elf" "$OUT/$name.bin"
    size=$(wc -c < "$OUT/$name.bin")
    printf '%-26s %6s bytes\n' "$name" "$size"
}

build_example sram_signature.c link_sram.ld sram_signature
build_example reset_counter.c link_flash.ld reset_counter_flash
build_example led_blink.c link_flash.ld led_blink_flash
build_example led_blink.c link_usb_app.ld led_blink_usb_app
build_example timer_led_walk.c link_flash.ld timer_led_walk_flash
build_example timer_led_walk.c link_usb_app.ld timer_led_walk_usb_app
build_example hard_peripheral_inventory.c link_sram.ld hard_peripheral_inventory
build_example basic_timer_led_walk.c link_flash.ld basic_timer_led_walk_flash
build_example basic_timer_led_walk.c link_usb_app.ld basic_timer_led_walk_usb_app
build_example uart_dma_loopback.c link_sram.ld uart_dma_loopback

printf 'Output: %s\n' "$OUT"
