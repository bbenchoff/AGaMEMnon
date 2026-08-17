# MCU and FPGA peripheral examples

AG32 combines a hard RISC-V MCU/peripheral subsystem with programmable logic.
Those halves use the word "peripheral" differently:

- MCU peripherals are already manufactured into the chip. Firmware enables a
  clock and operates a register block; it does not instantiate the peripheral.
- FPGA peripherals are RTL modules that consume LUTs, flip-flops, clocks, and
  I/O routes. They really are instantiated in Verilog.
- The active fabric configuration also routes most hard digital peripherals to
  package pins. A valid UART register block therefore does **not** prove that a
  UART TX signal currently reaches a pin.

The official AG32VF303 feature list includes 2 basic timers, 5 advanced timers,
5 UARTs, 2 I2C controllers, SPI, CAN 2.0, USB FS/OTG, watchdog, RTC, DMA,
Ethernet MAC, ADCs, DACs, and comparators. The official reference manual gives
the digital address map and instance counts used by
`hard_peripheral_inventory.c` and the open polling HAL.

## What is checked in

| Function | MCU example | FPGA example | Current evidence |
|---|---|---|---|
| Core timer | `timer_led_walk.c` uses 64-bit CLINT `MTIME`; `timer_interrupt.c` takes the machine-timer trap | `timer_tick.v` | MCU machine-timer (CLINT/MTIME) interrupt silicon-qualified, SRAM-only (`mcause` 0x80000007); walker images compile; FPGA combined simulation passes |
| Basic timer | `basic_timer_led_walk.c` polls hard `TIMER0` | `timer_tick.v` | MCU images compile; FPGA combined simulation passes |
| GPIO/LEDs | both walkers drive GPIO4 bits 1 through 4 | `gpio_walker.v` | LED1 was silicon-tested; all-four mapping comes from vendor board fabric |
| PWM | use the SDK GPTIMER API for hard PWM | `pwm4.v`, four 8-bit channels | FPGA combined simulation passes |
| UART | 5 hard instances plus open polling HAL and internal-loopback example | `uart_tx.v`, 8N1 transmitter | UART0 internal-loopback echoed byte 0xA5. Separate routes qualify PIN_10 TX and PIN_31 RX; an exact PIN_30/PIN_31 image transfers 4096 exact bytes each way simultaneously at 9600, 38400, and 115200 nominal baud. 7E1, 8E1, 8O1, 8N2, and parity-error reporting are also qualified at 38400. Flow control, FIFO/framing/break/overrun stress, UART1–4, and sub-percent absolute calibration remain open; FPGA combined simulation passes |
| SPI | 2 hard instances plus open eight-phase polling HAL | `spi_master.v`, one-byte mode-0 master | SPI0 master TX and active 1–4-byte TX-then-RX are silicon-qualified on exact L48 routes; the HAL normalizes reversed raw RX bytes to wire order. Simultaneous full-duplex, DUAL/QUAD, DMA/POLL, SPI1, and absolute SCK timing remain open. FPGA loopback simulation returns `0xA5` |
| I2C | 2 hard instances plus open polling master HAL | `i2c_writer.v`, one-byte single-master write | I2C0 active open-drain write/read is silicon-qualified on exact L48 pads, including one `2A A6` write, repeated START, and exact `5A C3 7E` read with ACK/ACK/NACK. Arbitrary lengths, stretching, I2C1, interrupts/DMA, and absolute SCL timing remain open. FPGA ACK-path simulation passes |
| CAN | 1 hard CAN 2.0 instance | no protocol-complete soft CAN block yet | **Not qualified.** No CAN bits observed on a wire and no ledger row; needs an external CAN transceiver |
| USB | hard USB FS/OTG controller and dedicated PHY | not a general-fabric soft peripheral | CDC upload was qualified on silicon |
| Watchdog/RTC | open APB-watchdog driver with read-only snapshot and supervised-reset example; open RTC driver (`ag32_rtc.h`) with counter probe | application-specific RTL counters | `WATCHDOG0` register snapshot and supervised timeout reset (`RST_CNTL` bit30 `SYS_RSTF_WDOG`) silicon-qualified, SRAM-only warm reset; RTC register/config path confirmed but counter advance unqualified pending a low-speed clock |
| DMA/CRC | open memory-to-memory DMA plus CRC driver/known-answer image | ordinary datapath/state-machine logic | `DMAC0` memory-to-memory 4-word copy and CRC-32/MPEG-2 known-answer (0x0376E6E7) both silicon-qualified, SRAM-only |
| External AHB | MCU reads the `0x60000000` fabric window | `mcu_ahb_constant_slave.v`, `mcu_ahb_register_bank.v` | constant ready/OKAY 32-bit reads and no-effect writes are silicon-qualified; the writable complete-byte waited bank with exact zero-extended word reads and aligned byte/halfword semantics is qualified per its ledger |
| Ethernet MAC | hard MAC instance | no soft MAC in this small suite | requires a board PHY and pin/clock mapping |
| ADC/DAC/comparator | hard analog blocks | cannot be synthesized from digital LUT RTL | A one-shot/static subset has been observed on the bench over the External-AHB window, but only through the **vendor `analog_ip` macro** that the open flow does not emit, and with no ledger row; see [ANALOG_FABRIC_BOUNDARY.md](ANALOG_FABRIC_BOUNDARY.md) |

"Combined simulation passes" means that Icarus elaborated all six soft RTL
blocks together and observed the timer/GPIO, UART completion, SPI loopback,
and I2C ACK behavior. It does not mean that the combined design has been
placed, routed, or run on silicon. The individual open AGaMEMnon flow still has
the qualification limits described in [STATUS.md](STATUS.md).

## Build and run the MCU examples

Build every freestanding image:

```powershell
./examples/riscv_mcu/build.ps1        # Windows
```

```sh
sh examples/riscv_mcu/build.sh        # Linux/macOS
```

The new outputs are:

| Image | Address | Behavior |
|---|---:|---|
| `timer_led_walk_flash.bin` | `0x80000000` | CLINT-timed four-LED walk, native reset image |
| `timer_led_walk_usb_app.bin` | `0x80010000` | same program, launched by the resident USB uploader |
| `basic_timer_led_walk_flash.bin` | `0x80000000` | polls hard basic TIMER0 |
| `basic_timer_led_walk_usb_app.bin` | `0x80010000` | hard-timer program launched over USB |
| `hard_peripheral_inventory.bin` | `0x20000000` | non-destructive SDK register-map inventory |
| `crc_self_test.bin` | `0x20000000` | non-destructive hard-CRC-32/MPEG-2 known-answer, silicon-qualified |
| `watchdog_snapshot.bin` | `0x20000000` | read-only programmable-watchdog register snapshot, silicon-qualified |
| `watchdog_supervised.bin` | `0x20000000` | supervised watchdog timeout resets the MCU via `SYS_RSTF_WDOG`, silicon-qualified warm reset |
| `rtc_count.bin` | `0x20000000` | backup-domain RTC config + counter probe; config path confirmed, counter advance pending a low-speed clock |

The SRAM inventory does not enable or read optional peripherals. It hashes the
13 generated digital peripheral families and reports the table through the
standard SRAM mailbox:

```powershell
agamemnon sram .tmp/riscv_mcu/hard_peripheral_inventory.bin --words 5 --sleep 100
```

Expected fields are `"PERI"`, family count, total digital instance count,
catalog hash, and device ID. Avoid a program that blindly initializes every
hard block: USB and Ethernet have clock constraints, CAN and Ethernet need
external transceivers/PHYs, I2C needs pull-ups, watchdog intentionally resets
the MCU, and routed signals may contend for the same package pins.

To launch either `*_usb_app.bin`, follow the backup/write/verify/GO recipe in
[RISCV_MCU_PROGRAMMING.md](RISCV_MCU_PROGRAMMING.md). The CDC uploader must
already be resident at `0x80000000`; stock factory firmware did not provide it.

### GPIO safety

"Blink every GPIO" is unsafe on this board. Package GPIO candidates overlap
USB, oscillators, DAP/debug, boot UART, CAN, I2C, and other connected devices.
The MCU examples deliberately mean **all four board LEDs**, not every package
pin. Vendor default L48 fabric maps `GPIO4[1:4]` to `PIN_34..PIN_31`. The
qualified minimal USB fabric only proves the LED1 route (`GPIO4.1/PIN_34`), so
LED2 through LED4 require the default board fabric or an equivalent `.ve` map.
See [MCU pin routing](MCU_PIN_ROUTING.md) for the fail-closed alternate-function
and package-evidence rules.

## Simulate the FPGA peripherals

Run the combined testbench:

```powershell
$env:AGAMEMNON_OSS = "C:/path/to/oss-cad-suite"
./examples/peripherals/fpga/simulate.ps1
```

or:

```sh
sh examples/peripherals/fpga/simulate.sh
```

`peripheral_showcase.v` is the structural all-soft-peripherals example. It
instantiates the timer, LED walker, four PWMs, UART transmitter, SPI master,
and I2C writer together. The interfaces remain top-level signals so a real
board design can give each one explicit pins and electrical constraints.

`showcase_top.v` is intentionally smaller at the package boundary: it exposes
only the four previously qualified fabric LED pads (`PIN_25..PIN_28`). Use it
as a safe blink build. A full package top needs a board-specific PCF and must
not guess where SPI, I2C, or UART are connected.

```powershell
agamemnon build examples/peripherals/fpga/showcase_all.v --uarch `
  --pcf examples/peripherals/fpga/showcase_L48.pcf `
  -o .tmp/peripheral_showcase.bin
```

The soft I2C block emits open-drain **drive-low enables**, not push-pull SCL/SDA
levels. A hardware wrapper must use tri-state-capable I/O cells and external
pull-ups. It deliberately omits arbitration and clock stretching. The SPI
block is mode 0 and transfers one byte per `start`; the UART block is transmit
only. These small blocks are examples and building blocks, not replacements
for fully featured protocol IP.

## USB belongs to the MCU hard subsystem

The AG32 USB connector reaches the chip's dedicated USB PHY/controller, not
ordinary fabric GPIOs. Consequently:

- MCU firmware can use USB device, host, or OTG support when the required USB
  fabric/clock configuration and software stack are present.
- The known-working CDC uploader uses the hard controller plus TinyUSB; see
  [USB_CDC_UPLOADER.md](USB_CDC_UPLOADER.md) and
  [`examples/usb_cdc_uploader`](../examples/usb_cdc_uploader/README.md).
- A plain Verilog USB peripheral cannot be attached to D+/D- through the open
  L48 GPIO flow. The FPGA can still implement packet buffers, accelerators, or
  custom MCU-visible control logic behind the hard USB device firmware.

## Sources

- [AGM AG32 product page](https://www.agm-micro.com/products.aspx?id=3113&p=37)
- [AG32 MCU Reference Manual, revision 1.2](https://www.agm-micro.com/upload/userfiles/files/AG32%20MCU%20Reference%20Manual%2820250515%E4%BF%AE%E8%AE%A2%E7%89%88%EF%BC%89.pdf)
- [AG32 MCU datasheet](https://www.agm-micro.com/upload/userfiles/files/AG32_DATASHEET_202303.pdf)
- [AGRV2K programmable-logic manual](https://www.agm-micro.com/upload/userfiles/files/AGRV2K_Rev2_0.pdf)
- The external AGM PlatformIO SDK was used only as a cross-check. Its pinned
  tree has no top-level license and none of its driver code is copied here.

