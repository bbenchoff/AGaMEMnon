# MCU alternate-function and fabric-routing policy

The AG32 does not have a conventional fixed alternate-function matrix that
firmware can select by writing one pin-mux number. Most hard peripheral signals
pass through the programmable fabric before they reach package pins.

The published GPIO `AFSEL` bit has one documented job:

- `0` gives software control to the GPIO `DATA` and `DIR` registers;
- `1` gives hardware control of that GPIO line to the surrounding system.

It does not identify UART, SPI, I2C, CAN, or another source, and it does not
prove that the selected signal reaches a package pin. That second mapping is a
property of the loaded fabric image and the package bond map.

## Current evidence

| Route | State | Boundary |
|---|---|---|
| `GPIO4.1 -> PIN_34 -> LED1` | Silicon-qualified | Observed with the vendor-default and qualified USB fabric on the L48 reference board |
| `GPIO4[1:4] -> PIN_34..PIN_31 -> LED1..LED4` | Vendor-board mapping | Used by the factory fabric; only LED1 has the independent minimal-fabric silicon record |
| MCU GPIO4 to/from AGRV2K fabric | Silicon-qualified subset | Four-bit inverted loopback covered every input combination; this qualifies the exercised bridge routes, not arbitrary GPIO bits |
| MCU GPIO5 data/OE/input boundary unit | Silicon-qualified exact L48 subset | Pure-open output-data/OE lanes 0 and 1 return through input lane 2. The emitter selects terminal 8 on the seven inactive `BBMUXS` groups; zero-filled inactive terminals fail. No other GPIO5 lane or package pin is claimed |
| Fabric outputs `PIN_25..PIN_28` | Silicon-qualified | Exact L48 package and qualification harness only. As of 2026-08-15 all four reproduce from the ordinary CLI (`agamemnon build qualification/left_edge_outputs.v --pcf qualification/left_edge_outputs_L48.pcf --research-unsafe`, image sha256 `a63ab5bc26bb4852555fb93863f065ba020564ec77e801cd4d67d4bcf865aba3`, 35 pips / 0 unmapped / 0 predicted / 0 legacy-abs, Pico GP12 404,383 Hz, GP13 405,612 Hz, GP16 405,168 Hz, GP17 411,144 Hz, undriven GP8/`PIN_18` 0 Hz as the negative control, FCB `0x000f0002`). That recipe is the Python-architecture PCF placer, which composes experimental options and needs `--research-unsafe`. As of 2026-08-17, `agamemnon build qualification/left_edge_outputs.v --uarch --pcf qualification/left_edge_outputs_L48.pcf` (no `--research-unsafe`) also builds a release-strict, zero-unmapped/predicted/legacy-selector image that FCB-configures the real device to `0x000f0002` over a non-destructive SRAM session; a Pico toggle re-witness of that image has since closed, all four pads toggling under both pulls on exactly their intended lead (`io_evidence.jsonl` trial `pad-uarch-pcf-toggle-rewitness-20260817`) |
| Fabric outputs `PIN_10` through `PIN_19` | Silicon-qualified | All ten decimal physical top-edge L48 package leads are qualified through the ordinary `agamemnon build <source> --pcf <constraints>` flow. The closing PIN_10/PIN_11 matrix toggles each alone and both simultaneously under opposite Pico pulls, with every other observed lead static; the retained production pair repacks byte-identically. Their config tile carried stale selectors, so this also validates that active IOMUX fields are replaced rather than ORed. `PIN_n` is a decimal package-lead label, not hexadecimal indexing. The claim is exact per-pad output compositions on L48, not arbitrary alternate routes, other packages, bidirectionality, or electrical modes. As of 2026-08-17, nine of these ten (all but PIN_15) also build release-strict with `--uarch --pcf` and no `--research-unsafe` (`AGAMEMNON_VENDOR_OUT_SLICE` is now release-admitted for exactly the four qualified presentations, value-gated so nothing else is), and every one FCB-configured the real device to `0x000f0002` (`io_evidence.jsonl` trial `pad-uarch-pcf-release-strict-vehicle-config-accept-20260817`); PIN_15 as an output still fails to route under `--uarch` and still needs `--research-unsafe`; the Pico toggle re-witness of the `--uarch` vehicle's own images has since closed for all nine (`io_evidence.jsonl` trial `pad-uarch-pcf-toggle-rewitness-20260817`), each toggling under both pulls on exactly its intended lead and no other, matching the pre-existing research-unsafe-vehicle claim pad-for-pad |
| PIN_25 combined-cell OE/readback | Silicon-qualified exact subset | Hard-zero data with the recorded six-pip OE corridor qualifies constant release/drive-low, static readback, and local-self-toggle dynamic OE. The ordinary PCF path also qualifies stepped external PIN_10-controlled OE and simultaneous readback under both pulls through the exact `RMUX15 -> RMUX53 -> IMUX11` entry. High-rate simultaneous readback, the divergent RMUX20 branch, generic/open-drain/registered OE, and other corridors remain unqualified. Separately, a retained vendor-routed quad oracle silicon-qualifies active-high OE polarity and release/drive-low through the four distinct exact PIN_25-PIN_28 OE corridors (`bidir_left_quad_evidence.jsonl`); ordinary source ingress and simultaneous readback for PIN_26-PIN_28 remain unqualified |
| Fabric inputs `PIN_10`, `PIN_11`, `PIN_12`, `PIN_15`, `PIN_19` | Silicon-qualified subset | Exact L48 package. `PIN_12` is bounded to its exact scalar, single-consumer direct-combinational path; registered input was also exercised on `PIN_19` |
| UART0 ROM `TX/RX` on `PIN_30/PIN_31` | Application full duplex silicon-qualified; ROM protocol pending | An exact zero-LUT application image qualifies GPIO7.6/UART0_UARTTXD → PIN_30 → DAP CDC RX and DAP CDC TX → PIN_31 → GPIO6.1/UART0_UARTRXD. It passes 4096 exact bytes each way simultaneously at 9600/38400/115200. The mask-ROM protocol itself remains unqualified |
| Hard UART0 TX/RX, I2C0 SDA/SCL, SPI0 SCK/MOSI/CSN plus IO1 on L48 `PIN_10`–`PIN_17` and `PIN_30`/`PIN_31` | Silicon-qualified exact L48 subsets | One open peripheral-route image puts UART0 TX on `PIN_10`, I2C0 SDA/SCL on `PIN_11`/`PIN_15`, and SPI0 SCK/CSN/MOSI on `PIN_12`/`PIN_13`/`PIN_14`. Separate exact images qualify UART0 RX on `PIN_31` and full duplex on `PIN_30`/`PIN_31`; the latter transfers 4096 bytes each way at three nominal rates. An active RP2350 open-drain slave at `0x55` qualifies I2C bytes plus exact `2A A6`, repeated START, and `5A C3 7E` ACK/ACK/NACK. Another image adds SPI0 IO1 on `PIN_17`; an active RP2350 PIO slave qualifies 1–4-byte receive values and byte order. These routes are properties of the exact loaded images, not general part pin mappings; I2C needs external pull-ups |
| Hard UART/SPI/I2C signals on any other pin, and all CAN/Ethernet signals | Unqualified | Register drivers do not imply a package route, and the qualified routes above do not generalize to other pads, other instances, or untested signal directions |
| USB D+/D- | Dedicated hard PHY | Not ordinary fabric GPIO and not controlled through `GPIOAFSEL` |

The supporting observations are in
[hardware qualification](HARDWARE_VALIDATION.md),
[the UART ROM record](UART_BOOTLOADER.md), and the append-only files under
[`qualification/`](../qualification/).

## Rules for firmware and board definitions

1. Controller drivers stop at the register-block boundary. A driver may enable
   a UART or SPI instance without claiming a package pin.
2. Board code may name a peripheral pin only when it identifies the exact
   part, package, board, and compatible fabric configuration that supplies the
   route.
3. An unknown fabric image invalidates hard-peripheral pin assumptions.
   Firmware should retain recovery access and load a known matching fabric
   before driving a routed signal.
4. Software GPIO output examples clear `AFSEL` and use only board nets whose
   electrical destination is known. “Blink all GPIOs” is not a safe test.
5. I2C routes require open-drain behavior and external pull-ups. CAN requires a
   transceiver; Ethernet requires its PHY and clocks. A logical route alone is
   insufficient evidence.
6. Package evidence never transfers by pin number to L100, L64, Q32, another
   PCB, or another part marking.

AGaMEMnon therefore fails closed: there is no generic
`set_uart_pin(UART0, PIN_n)` API. Future named routes belong in a board
definition paired with a fabric artifact/hash and a support-matrix entry.

## Qualifying a new route

Record the exact chip marking, package, board revision, fabric artifact and
SHA-256, source and sink, direction, IO standard/electrical conditions,
firmware artifact, observable result, transport, and restoration result. Test
the route in isolation before using it as evidence for a larger design, then
submit the record through `agamemnon qualify`.

Passing synthesis or routed simulation is useful preflight evidence, but only
an external observation on the named hardware promotes a package route to
silicon-qualified.
