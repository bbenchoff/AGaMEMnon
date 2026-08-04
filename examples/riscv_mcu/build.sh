#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
OUT=${1:-"$ROOT/.tmp/riscv_mcu"}
if [ -n "${RISCV_PREFIX:-}" ]; then
    PREFIX=$RISCV_PREFIX
elif command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then
    PREFIX=riscv64-unknown-elf-
else
    PREFIX=riscv-none-elf-
fi
CC=${CC:-"${PREFIX}gcc"}
OBJCOPY=${OBJCOPY:-"${PREFIX}objcopy"}
EXAMPLE="$ROOT/examples/riscv_mcu"
GCC_MAJOR=$("$CC" -dumpversion | cut -d. -f1)
if [ "$GCC_MAJOR" -ge 12 ]; then
    MARCH=rv32imac_zicsr
else
    MARCH=rv32imac
fi

mkdir -p "$OUT"

build_example() {
    source=$1
    linker=$2
    name=$3
    "$CC" -march="$MARCH" -mabi=ilp32 -Os -g \
        -nostdlib -ffreestanding -fno-builtin \
        -ffunction-sections -fdata-sections -I "$ROOT/mcu" \
        -T "$EXAMPLE/$linker" -Wl,--gc-sections -Wl,-Map,"$OUT/$name.map" \
        "$ROOT/agamemnon/sdk/startup.S" "$EXAMPLE/$source" -o "$OUT/$name.elf"
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
build_example exception_mailbox.c link_sram.ld exception_mailbox
build_example software_interrupt.c link_sram.ld software_interrupt
build_example timer_interrupt.c link_sram.ld timer_interrupt
build_example local_interrupt0.c link_sram.ld local_interrupt0
build_example local_interrupt1.c link_sram.ld local_interrupt1
build_example local_interrupt2.c link_sram.ld local_interrupt2
build_example local_interrupt3.c link_sram.ld local_interrupt3
build_example local_interrupt_independent.c link_sram.ld local_interrupt_independent
build_example crc_self_test.c link_sram.ld crc_self_test
build_example watchdog_snapshot.c link_sram.ld watchdog_snapshot

printf 'Output: %s\n' "$OUT"
