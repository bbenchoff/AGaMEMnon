# Architecture

AGaMEMnon is organized as a synthesis front end, a data-driven nextpnr
architecture, a strict bitstream generator, and optional programming tools.

```text
Verilog
  -> Yosys technology mapping
  -> generated AGRV2K device database
  -> nextpnr Viaduct `agrv2k` backend
  -> routed JSON
  -> strict bitgen
  -> uncompressed and compressed fabric images
```

## Target device

AGRV2K combines an RV32IMAFC microcontroller with an embedded FPGA containing
2,112 LUT4s, 2,112 flip-flops, four 9-Kbit BRAMs, a PLL, global clocks, an MCU
bridge, and a programmable IO ring. The fabric occupies 132 logic tiles plus
IO, BRAM, clock, and MCU-edge tiles.

AGaMEMnon recognizes `AGRV2KL100`, `AGRV2KL64`, `AGRV2KL48`, and
`AGRV2KQ32`. Package-pin legality is available for all four. A complete
physical bond map is available only for L48, so physical PCF routing for other
packages fails closed.

## Synthesis

`agamemnon/synth/` contains the Yosys scripts, primitive declarations, and
technology maps. The synthesis path maps ordinary Verilog into AGRV2K LUT,
flip-flop, clock, IO, MCU-edge, carry, and BRAM cells.

Dedicated carry lowering is opt-in because only specific physical footprints
are qualified. BRAM inference is accepted only for patterns represented by the
integrated hard-block model; unsupported semantics must use soft logic or fail.

## Chip database

`agamemnon/chipdb/` is the runtime architecture database. It contains:

- 50,046 named routing nodes;
- logic, IO, MCU-edge, carry, clock, and BRAM bel definitions;
- the general and special-block routing graphs;
- physical configuration locations for logic and routing features;
- strict routing-selector tables;
- conduction allowlists and isolated dead-edge classifications;
- L48 physical pin mappings;
- conservative cell and wire timing data;
- the design-neutral fabric-default image used by bitgen.

Large derived tables are tracked with Git LFS and included in the wheel. The
release package contains no AGM executable or proprietary routed design.

## Device database generation

`agamemnon/engine/arch.py` constructs the active graph from the shipped chip
database. `emit_uarch_db.py` records that graph as flat CSV files consumed by
the C++ nextpnr backend:

| File | Contents |
|---|---|
| `dev_meta.csv` | database metadata and architecture parameters |
| `dev_wires.csv` | wire names, types, and coordinates |
| `dev_bels.csv` | bel names, types, coordinates, and z values |
| `dev_belpins.csv` | bel-pin wiring and direction |
| `dev_pips.csv` | source, destination, type, delay, and location |

The active graph is filtered by package mapping, conduction evidence, clean
selector availability, requested MCU/IO features, BRAM corridors, and carry
mode. Unsupported resources are not exposed to nextpnr.

## Place and route

The C++ Viaduct backend lives in
`agamemnon/engine/uarch/agrv2k/agrv2k.cc`. It provides:

- LUT/LUT+FF and standalone-FF packing;
- constant and global-clock packing;
- regional, connectivity-aware placement;
- density-controlled retry and route-driven fanout splitting;
- exact MCU lane binding;
- characterized L48 physical IO endpoints;
- BRAM packing and slot-exact input binding;
- constructive same-tile and qualified-corridor carry placement;
- conservative timing arcs;
- replay of exact qualification checkpoints.

The normal release entry point is `agamemnon build --uarch`. The CLI isolates
Yosys and nextpnr runtime environments, preflights the nextpnr loader, creates
or reuses the generated database, and runs strict bitgen only after routing.

## Routing trust boundary

A general routed connection selects a two-hot pair in its destination RMUX or
IMUX block. The release tables contain conflict-free physical encodings and
tile-relative encodings that are unanimous across all physical observations.
Conflicting, predicted, or unresolved selectors are not accepted.

Architecture generation and bitgen independently enforce this rule. Passing
nextpnr is therefore insufficient by itself: every configurable routed PIP
must also have a release encoding when the image is generated.

## Bitstream generation

`agamemnon/engine/bitgen_seq.py` converts routed JSON to the fixed 99,936-byte
raw fabric configuration. It clears design-dependent routing and logic fields
from `chipdb/fabric_default.bin`, applies placed logic, routing, clock, IO,
carry, MCU-edge, and supported BRAM features, then writes the configuration
CRC.

`agamemnon/engine/to_bin.py` adds the eight-byte device header for the
99,944-byte uncompressed SRAM image. `lzw_codec.py` creates the compressed
flash image. See [BITSTREAM_FORMAT.md](BITSTREAM_FORMAT.md).

## Verification

`verify_netlist.py` simulates the placed LUT INIT values, routed LUT and
flip-flop connectivity, carry chains, and MCU read-lane binding. It reports the
reachable observation set and can compare hardware observations for soundness.

This verifier checks the generated design model. Electrical routing and
hard-block behavior are qualified separately on silicon; their supported
boundary is listed in [STATUS.md](STATUS.md).

## Programming

`agamemnon/program.py` drives a CMSIS-DAP/OpenOCD connection. It supports
device probing, volatile SRAM execution, full-flash backup, main-flash sector
erase, programming, and byte readback verification. The implementation uses
the open flash-controller register sequence, not the vendor flash driver.

The transport still requires an OpenOCD build with AGM's unpublished
`riscv -dap` target extension. See [PROGRAMMING.md](PROGRAMMING.md).

`agamemnon/uart_program.py` is the independent recovery transport. A Pico 2
controls BOOT0, BOOT1, and NRST and forwards the AG32 mask-ROM protocol on
UART0. Writes require a full backup, reconstruct complete touched sectors, and
verify their complete readback before resetting into flash; this path does not
require OpenOCD or executable code in main flash.
