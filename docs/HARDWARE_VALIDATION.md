# Hardware validation — AGaMEMnon on real AG32 silicon

**Hardware:** AG32 dev board (AG32VF303KCU6) + AGM CMSIS-DAP "DAP-Link" USB Blaster. **Core:** RISC-V RV32IMAFC, `misa = 0x40801125`, `DEVICE_ID = 0x40200001` (read from `0x03000100`). **Toolchain under test:** the open AGaMEMnon flow — `.bin` codec, physical map, open bitgen + CRC, LUT editor, nextpnr-agrv place & route, and the OpenOCD programmer. **No vendor `af.exe` in any path tested here.**

Every result below is a real capture from the attached board, not a simulation. The board is never left modified: SRAM config-injection touches no flash, every flash write is backup → write → verify → restore, and the flash-boot test kept a full 256 KB backup. Results are grouped from the earliest bring-up (2026-06-30) through the completed open loop (2026-07-02).

---

## 1. Board + transport

```
$ agamemnon probe
DEVICE_ID = 0x40200001  (AGRV2K OK)
# SWD DPIDR 0x2ba01477 ; [cpu] Examined RISC-V core ; XLEN=32, misa=0x40801125
```

The AG32 core is RISC-V RV32IMAFC (the ARM-style SWD DPIDR is only the debug transport), and the on-chip `DEVICE_ID` is exactly the device ID our fabric `.bin` header carries.

## 2. Flash layout

```
0x81000038: 80008100 7fff7eff     # logic config @ 0x80008100, marked COMPRESSED
agrv2k.FLASH size = 256kbytes
```

Matches the recovered map: MCU code at `0x80000000`, the fabric bitstream (LZW-compressed, our codec) at an option-byte-specified address (factory `0x80008100`) in the shared 256 KB SPI flash.

## 3. `.bin` codec byte-exact on an *unseen* on-silicon bitstream

The board held a logic image we had no saved copy of. Dumped and round-tripped through the open codec only: on-chip header `402000010000ffff` → LZW-decode → 99,936-byte raw image → re-encode → canonical `.bin`, **byte-exact vs the on-chip flash bytes**, both directions.

## 4. Full open write path (edit → encode → flash → read back → verify → restore)

A surgical, fully-restorable demonstration of the open output path against one LUT-init bit: dump logic, decode, flip exactly that bit, re-encode with our LZW, flash (sector-aligned, `verify_image` byte-exact), read back and decode — **exactly one raw byte changed on silicon** (`raw[73611]` bit `0x80` cleared) — then restore the original sector and confirm identical. End to end, our code only.

## 5. Open bitstream ACCEPTED + activated by the fabric-config engine

A RISC-V stub (`FCB_AutoConfig`, SRAM-loaded via OpenOCD) feeds a config to the FCB and reads `FCB->STAT` (`0x40010010`; `ACTIVE`=bit1, `ERR_ID`=bit4, `ERR_HEADER`=bit5, `ERR_CRC`=bit6).

```
vendor known-good config:               STAT = 0x000f0002   (ACTIVE, 0 errors)   harness valid
our open bitstream, no CRC:             STAT = 0x00000040   (ERR_CRC only)       → ID/HEADER OK
   → recovered: CRC-32/BZIP2 over header(8)+raw[:99932], big-endian, last word
our open bitstream WITH the CRC:        STAT = 0x000f0002   (ACTIVE, 0 errors)   identical to vendor
```

The AGRV2K configuration hardware accepts and activates a bitstream produced entirely by the open flow — device-ID, header, and CRC all validated by silicon.

## 6. Combinational logic computes (GPIO → fabric → GPIO)

A fabric inverter wired between two MCU GPIO bits, configured via the open flow and driven/read by a RISC-V stub:

```
STAT = 0x000f0002   (ACTIVE)
din=0 -> dout=1      # ~0
din=1 -> dout=0      # ~1
```

The fabric computed `NOT din` and the MCU observed it, both polarities.

## 7. Sequential logic computes — a flip-flop toggles

A clocked toggle-FF, place-and-routed through the open flow, flips its registered output on each clock on silicon. This closed the register-select encoding (`CFG_OMUX` sel = 2) and proved the open flow handles clocked designs, not just combinational ones.

## 8. General clock distribution, including far tiles

A toggle-FF swept across tiles clocks correctly at scattered locations, including far tiles (e.g. (14,4)). Per-tile clock configuration is data-complete for all 132 LogicTiles, and the open fabric-clock source (the HSE→PLL→global-clock preamble) is emitted directly by bitgen — no vendor clocked baseline required. Tiles that fail to clock were proven to be path-specific *routing* limits, not clock limits.

## 9. MCU ↔ fabric GPIO — 4-bit loopback, auto-placed

Four independent MCU GPIO bits, each looped through its own fabric LUT inverter, with placement solved automatically from the routing data. All four invert on silicon across **16/16 input combinations**, reproduced. This is the MCU-edge bridge (`alta_mcu`/`alta_rv3200`) driven entirely through the open flow.

## 10. MCU AHB memory-bus write — the CPU writes a fabric register

The MCU writes the fabric over the External-AHB bus and the fabric captures it:

```
R(0x60000000) = 1   -> fabric register <= 1   -> GPIO4.2 readback = 0x4
R(0x60000000) = 0   -> fabric register <= 0   -> GPIO4.2 readback = 0x0
```

The bulk data path (memory-mapped fabric slave at `0x60000000`) works, built entirely through the open flow. The 1-bit write path is proven; 32-bit width and the `hrdata` read path are the remaining bus work.

## 11. Flash-boot — an open bitstream self-boots (the iceprog milestone)

Our compressed open bitstream (a 2-bit loopback) was written to the fabric-config region of flash; the MCU stub and option bytes were left factory-intact; the board was physically power-cycled. The boot ROM read our config from flash, ran the decompression algorithm, and configured the fabric with **no debugger in the config loop**. A read-only readback then confirmed the loopback inverts on all four combinations (`STAT = 0x000f0002`).

```
flash write (our compressed config) -> power-cycle -> boot ROM configures fabric from flash
readback: din=0x0->0x14, din=0x2->0x10, din=0x8->0x4, din=0xa->0x0   (all invert)  => FLASH-BOOT PROVEN
```

The full flash was backed up first; the write touched only the fabric-config sector; recovery paths (restore the backup, or the BOOT0=1 flash-independent serial ROM) were staged throughout.

## What this establishes

The complete open loop is proven on real hardware: Verilog → synthesis → place & route → bitstream generation → configuration → **computing and clocked logic** → **MCU↔fabric data exchange** → **self-boot from flash**, with no proprietary binary in the path and the board always returned to its original state. This is the IceStorm-equivalent (icepack/iceprog) layer for the AG32, plus the MCU-integration and flash-boot pieces the AG32's MCU+fabric architecture requires — all done and validated on silicon. What remains (routing byte-exactness tail, timing, wider bels/bus) is coverage and breadth; see `STATUS.md`.

## Reproducing

```
agamemnon probe                                              # read-only board check
agamemnon build examples/designs/comb.v -o comb.bin          # Verilog -> .bin, self-contained
agamemnon backup full_flash.bin                              # full 256KB backup first
agamemnon flash comb.bin --addr 0x80008100 --backup full_flash.bin   # program logic + verify
# to undo, re-flash the region from the backup you took:
agamemnon flash full_flash.bin --addr 0x80000000            # restore from the full-flash dump
```

Requires yosys + nextpnr-generic on `$PATH` (or `$AGAMEMNON_OSS`), and — for the programming/silicon steps — an OpenOCD built with `riscv -dap` (resolved via `$AGAMEMNON_OPENOCD` / the shipped `agamemnon/openocd/agrv2k.cfg`) and a connected board.
