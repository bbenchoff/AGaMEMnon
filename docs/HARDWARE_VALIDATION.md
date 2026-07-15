# Hardware validation

AGaMEMnon is qualified on an AG32 development board with an
AG32VF303KCU6/AGRV2K and the AGM CMSIS-DAP probe. The observed identifiers are:

```text
DEVICE_ID  0x40200001  (address 0x03000100)
misa       0x40801125  (RV32IMAFC)
FCB STAT   0x000f0002  (ACTIVE, no ID/header/CRC error)
```

Hardware trials use the open Yosys -> nextpnr `agrv2k` -> AGaMEMnon bitgen
path. Volatile trials load fabric and MCU firmware into SRAM. Flash trials take
a complete backup, program and byte-verify the intended region, and retain a
recovery path.

## Qualified results

| Capability | Hardware result |
|---|---|
| Fabric codec and CRC | Open images are accepted by FCB; a wrong CRC produces `ERR_CRC`; decode/encode is byte-exact on captured flash images |
| LUT logic | MCU-driven fabric inverter returns both correct polarities |
| Flip-flops | Registered feedback toggles and counters traverse their expected states |
| Global clock | Registered designs run at near and far logic tiles |
| Physical output | Fabric drives characterized L48 header paths and PIN_25-28; all four LED pads passed both isolated and concurrent tests |
| Physical input | PIN10, PIN11, PIN15, and PIN19 paths conduct; PIN19 also drives a packed FF |
| MCU GPIO bridge | Four-bit inverted loopback passes all 16 input combinations |
| External AHB write | Protocol-valid trials cover HWDATA[31:0] in eight four-bit groups, each passing 64/64 exact patterns |
| External AHB read | All 32 fabric-to-MCU lanes passed simultaneously for 64/64 exact reads |
| Random RTL | Fresh xorshift64 and nonlinear mixed64 images produce their routed-netlist states; the software matrix covers 72 designs |
| SERV | The current true-dual-port `addi`/`sw` example routes through the public strict flow; reset/run/reset hardware sampling proves continuing program-address progress and reset behavior |
| Dedicated carry | 4- and 8-stage same-tile chains pass; two simultaneous 3-stage chains cover the six predicted joint states; a 32-bit chain passes across the recovered three-tile corridor |
| Timing smoke | A physical TFF and LUT-arithmetic counter operate with the 100-MHz configuration; qualified SERV closes its 10-MHz target |
| BRAM Port A | The archived characterized x18 route produces dynamic values with the current bitgen |
| BRAM Port B | One exact isolated x2 read/control/corridor route produced four sequential values over 500 samples with zero predicted or unresolved selectors |
| PLL restore | After SRAM configuration, divider probes scale as expected across encoded 10, 25, 50, and 100-MHz PLL images instead of remaining on HSI |
| Serial mux | Three simultaneous 9,600-baud receivers on PIN10/11/15 buffer and round-robin onto PIN16 at 115,200 baud for 4,096/4,096 exact `ABC` transactions |
| SRAM configuration | Fabric plus MCU stub load and execute without writing flash |
| Flash controller | Main-flash sector erase, program, readback, and byte verification pass through the open controller implementation |
| Flash boot | An open compressed fabric image at the existing factory config location is loaded by the boot ROM after power cycle |

The append-only records and exact artifact hashes are under `qualification/`.
Software-only build evidence and hardware evidence are kept separate.

The LED-pad result is package-specific. The fingerprinted L48 harness maps
PIN_25/26/27/28 to Pico GP12/GP13/GP16/GP17. No equivalent physical bond map
or Pico wiring claim is made for L100, L64, or Q32.

## Routing evidence policy

FCB acceptance proves the header, device ID, CRC, and configuration protocol;
it does not prove that every selected path conducts. A successful large design
also does not sensitize every PIP it contains.

Routing promotion uses isolated source-to-observed-sink trials. A passing
trial promotes its traced unknown PIPs. A negative classification requires at
least two independent isolated failures with one remaining suspect. Fourteen
edges currently meet that negative standard. Whole-design route correlation
is retained as diagnostic evidence only; five correlation suspects were later
isolated and proved live.

## Current non-results

The following observations are deliberately not reported as successful
hardware capability:

- Some fresh BRAM Port-A and Port-B builds were FCB-accepted but static. The
  characterized archived Port-A corridor and one exact x2 Port-B corridor are
  live, so the remaining issue is selecting conducting corridors consistently,
  not bitstream acceptance. The Port-B result does not qualify other widths,
  tiles, initialization layouts, or collision modes.
- Alternate large SERV placements can remain static despite selector-clean
  bitgen, so only the exact reset/run/reset public example is promoted. A
  static whole design is not converted into a list of dead PIPs.
- The current true-dual-port SERV register file routes and runs the aliased
  `addi`/`sw` demo. Broader eight-operation and dependent four-instruction
  programs passed RTL and strict P&R but failed their silicon PC/signature
  observations, so general CPU/ISA compliance remains unqualified.
- Static free-running samples do not classify long-period random machines.
  Deterministic AHB-stepped trials are used when polling can alias state.
- Timing closure in nextpnr is not a silicon Fmax guarantee because exact wire
  classes, clock skew, IO, hard-block, and package delays are incomplete.
- Option-byte programming, UART bootloader transport, and native USB DFU are
  not hardware-qualified product paths.

## Reproduction commands

Build and inspect a routed design without hardware:

```bash
agamemnon build examples/designs/counter_ahb.v --uarch --verify \
  --write-routed counter_routed.json -o counter.bin
agamemnon verify counter_routed.json
```

Run a volatile hardware trial with a suitable MCU stub:

```bash
agamemnon probe
agamemnon sram firmware.bin --fabric counter.bin --words 10
```

Back up and program the existing factory fabric-config location:

```bash
agamemnon backup full-flash.bin
agamemnon flash design.bin.comp --addr 0x80008100 --backup full-flash.bin
```

These hardware commands require a compatible OpenOCD binary with AGM's
`riscv -dap` target extension and the shipped `agamemnon/openocd/agrv2k.cfg`.
The flash command erases full sectors, so preserve the factory decompressor
blob when using the compressed boot layout.
