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
| MCU GPIO5 data/OE/input boundary unit | Exact route; failed L48 open silicon trial | L100/L48 routes and 65 vendor field bits match, but the open L48 image returns `!out_en` because its data LUT input is stuck low; no package pin is claimed |
| Fabric outputs `PIN_25..PIN_28` | Silicon-qualified | Exact L48 package and qualification harness only |
| Fabric inputs `PIN_10`, `PIN_11`, `PIN_15`, `PIN_19` | Silicon-qualified | Exact L48 package; registered input was also exercised on `PIN_19` |
| UART0 ROM `TX/RX` on `PIN_30/PIN_31` | Documented, target harness pending | The ROM/package assignment is documented, but the Pico-to-target qualification still needs the five-wire board addition |
| Hard UART/SPI/I2C/CAN/Ethernet signals on other pins | Unqualified | Register drivers do not imply a package route |
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
