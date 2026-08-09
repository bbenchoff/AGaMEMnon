# AGaMEMnon projects

An `agamemnon.toml` manifest turns separate Verilog, firmware, pin, clock, and
flash-layout arguments into one reproducible project. Create a maintained
template:

```text
agamemnon new hello --board ag32vf303-l48 --template mcu-blink
cd hello
agamemnon doctor
agamemnon build
agamemnon run --transport dap
```

Available templates are `mcu-blink`, `fpga-blink`, `mcu-fpga`,
`mcu-fpga-registers`, `serv-blinky`, `uart`, `usb-cdc`, and `safe-recovery`.

`mcu-blink` is the fabric-free cold-start template. `mcu-fpga` is an alias for
`mcu-fpga-registers`; both replay the same immutable, silicon-qualified L48
ID/scratch route. The generated project verifies the source, routed-netlist,
board, device, uncompressed image, and compressed image hashes before retaining
its outputs. This exact profile does not enable or promote the generic
decoded-only `AGAMEMNON_MCU_ENTRY` option.

`serv-blinky` strictly replays the retained L48 SERV route and builds a small
MCU fabric loader. Its public source, constraints, route, pack environment,
and raw/compressed output hashes are pinned. It does not run fresh source
place-and-route or widen the qualified direct-D placement pool.

## Manifest

```toml
[project]
name = "example"
board = "ag32vf303-l48"
device = "AGRV2KL48"

[fabric]
sources = ["logic/bus.v", "logic/top.v"]
top = "top"
pcf = "board.pcf"
output = "build/fabric.bin"
uarch = true
mcu_bridge = true
freq = 10
hse = 8

[mcu]
sources = ["src/main.c", "src/interrupts.c"]
include_dirs = ["include"]
linker = "@sdk/link_sram.ld"
output = "build/mcu.bin"
march = "rv32imac"
mabi = "ilp32"

[flash]
mcu_address = 0x80010000
fabric_address = 0x80008100
```

`@sdk/link_sram.ld`, `@sdk/link_flash.ld`, and `@sdk/link_usb_app.ld` select
the maintained SDK link layouts. A project can instead name its own linker
script. Fabric builds accept multiple source files and an explicit top; direct
one-off builds can use repeated `--source` plus `--top`. `freq` is both the
emitted fabric PLL frequency and the timing-closure target. It defaults to the
qualified 10 MHz setting; a command-line `--freq` overrides the manifest.

`agamemnon run --transport dap` loads built MCU/fabric images into SRAM and is
the safe default. USB `run` performs `GO` only unless `--flash --backup FILE`
is explicitly requested. Mask-ROM UART remains a recovery workflow because it
requires the documented L48 harness change.

The `usb-cdc` template is an explicit external PlatformIO project. It pins the
AGM platform and points to the qualified patches; it does not pretend the
hard-USB stack is a freestanding FPGA module or silently redistribute the
unlicensed external AGM SDK.
