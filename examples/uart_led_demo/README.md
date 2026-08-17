# UART-programmed LED demo

This persistent demo uses an External-AHB write strobe to advance a four-bit
Johnson state in the fabric, driving the LQFP-48 board LEDs on `PIN_25` through
`PIN_28`. Each visible fill/chase step therefore proves that the MCU firmware
issued another protocol-valid write.

Build the fabric with the public `agrv2k` nextpnr flow and compile the
freestanding RV32 firmware at the main-flash reset address:

```powershell
$env:AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic.exe"
agamemnon build examples/uart_led_demo/led_ahb.v --uarch --mcu --research-unsafe `
  --pcf examples/uart_led_demo/led_ahb_L48.pcf `
  --write-routed .tmp/uart_led_demo/led_ahb_routed.json `
  -o .tmp/uart_led_demo/led_ahb.bin

riscv64-unknown-elf-gcc -march=rv32imac -mabi=ilp32 -Os -nostdlib `
  -ffreestanding -T examples/uart_led_demo/link_flash.ld `
  -o .tmp/uart_led_demo/led_blink.elf examples/uart_led_demo/led_blink.c
riscv64-unknown-elf-objcopy -O binary `
  .tmp/uart_led_demo/led_blink.elf .tmp/uart_led_demo/led_blink.bin
```

```sh
export AGAMEMNON_UARCH_NEXTPNR="$PWD/third_party/nextpnr/build/nextpnr-generic"
agamemnon build examples/uart_led_demo/led_ahb.v --uarch --mcu --research-unsafe \
  --pcf examples/uart_led_demo/led_ahb_L48.pcf \
  --write-routed .tmp/uart_led_demo/led_ahb_routed.json \
  -o .tmp/uart_led_demo/led_ahb.bin

riscv64-unknown-elf-gcc -march=rv32imac -mabi=ilp32 -Os -nostdlib \
  -ffreestanding -T examples/uart_led_demo/link_flash.ld \
  -o .tmp/uart_led_demo/led_blink.elf examples/uart_led_demo/led_blink.c
riscv64-unknown-elf-objcopy -O binary \
  .tmp/uart_led_demo/led_blink.elf .tmp/uart_led_demo/led_blink.bin
```

The qualified board already points its compressed fabric configuration at
`0x80008100`. Back up and write the two regions through the Pico adapter:

```powershell
agamemnon uart-flash .tmp/uart_led_demo/led_ahb.bin.comp `
  --addr 0x80008100 --backup .tmp/uart_led_demo/pre-fabric.bin --port COM6
agamemnon uart-flash .tmp/uart_led_demo/led_blink.bin `
  --addr 0x80000000 --backup .tmp/uart_led_demo/pre-mcu.bin --port COM6
```

```sh
# on Linux/macOS the Pico bridge appears as /dev/ttyACM0 (adjust as needed)
agamemnon uart-flash .tmp/uart_led_demo/led_ahb.bin.comp \
  --addr 0x80008100 --backup .tmp/uart_led_demo/pre-fabric.bin --port /dev/ttyACM0
agamemnon uart-flash .tmp/uart_led_demo/led_blink.bin \
  --addr 0x80000000 --backup .tmp/uart_led_demo/pre-mcu.bin --port /dev/ttyACM0
```

Each command makes its own complete 256-KiB backup, preserves bytes adjacent
to the payload in touched sectors, verifies full-sector readback, and resets
only after success.
