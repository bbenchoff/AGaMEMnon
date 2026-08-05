# FPGA parity ledger

This is the public, generated summary of the AG32-Docs family-level feature ledger.
It distinguishes recovered encodings, open-flow implementation, and silicon
qualification. A companion machine manifest covers all 136 parameter
declarations on the six primitive families actually present on AGRV2K. It
separates declarations, candidate domains, backend acceptance, open support,
and behavior rather than treating Verilog widths as legality evidence.

| Feature | Encoding | Open flow | Silicon | Packages | Current boundary |
|---|---|---|---|---|---|
| 164-byte global/configuration-chain preamble | complete | supported | qualified_subset | L48 | Idle plus five qualified SYSCLK/HSE profiles are generated declaratively and replace inherited preamble bytes. |
| Non-preamble tile-grid reset/default canvas | partial | partial | qualified_subset | L48 | Placed slice residue is cleared and supported fields are overlaid exactly, but the canvas still supplies incompletely decoded defaults. |
| LUT4 and flip-flop RTL | complete | supported | qualified | L48 | Combinational logic, counters, shifts, state machines, constants, feedback, and physical-input registers are qualified. |
| General fabric routing selectors | partial | partial | qualified_subset | L48 | Conflict-free physical and unanimous relative selectors are fail-closed; 14 isolated dead edges override corpus attribution. |
| Global clock distribution | partial | partial | qualified_subset | L48 | Near and far logic tiles run from the qualified HSE/PLL profiles. |
| PLL configuration | partial | partial | qualified_subset | L48 | Qualified pairs are (100,8), (50,8), (25,8), (10,8), and (100,16) MHz. |
| Internal/external oscillator modes | partial | absent | unqualified | L100, L64, L48, Q32 | Static recovery separates OSC pad-chain fields, dedicated crystal pads, virtual HSI/HSE/OSC sources, and MCU controls. The qualified clock path still uses HSE into fixed PLL profiles; no general oscillator source is implemented. |
| BRAM9K modes and routing | partial | partial | qualified_subset | L48 | One x18 Port-A path, one exact x2 Port-B read/control path, and all nine X13Y4 read-only x9 data bits are qualified through exact per-lane projections. Bits0..2 cover three INIT projections over the exercised 0..255 range; bits3, 4, and 5 independently match word-address bit3; and bits6, 7, and 8 match word-address bits0, 1, and 2 respectively for 256/256 reads. The narrow-width wrapper maps logical bits6..8 to physical DataOutA15, DataOutA16, and DataOutA7. HADDR11/AddressA12 also distinguishes word addresses 0 and 512 through the exact X14Y7 slice3 footprint. The x9 flow emits the hard-HSE boundary, complete exact route-through footprints, and direct q4/q5/q6/q7/q8 corridors; q5 specifically uses the silicon-qualified BufMUX13/RMUX92/RMUX75/RMUX20/BBMUXE07 path. A simultaneous q4/q5 oracle qualifies the exact q4 BufMUX12/RMUX75 corridor and source-dependent RMUX43-to-BBMUXE06 selector; an atomic reservation of that path enables a strict-open nine-output image that returns all 256 identity words over HADDR[9:2]. q8 is zero over that bounded range and retains its independent two-state proof. The remaining high-address range, writes, other modes/sites, output registers, and collisions remain fail-closed. On each port, width candidates still decode byte-exactly only within the documented lowered subset. |
| Dedicated carry chains | partial | partial | qualified_subset | L48 | Same-tile short chains and one 33-site corridor with up to 32 arithmetic stages are opt-in and qualified. |
| Package pin/bank legality | complete | supported | qualified_subset | L100, L64, L48, Q32 | Distinct recovered bond maps exist for all packages; only L48 is silicon-qualified and other packages warn explicitly. |
| Physical input routing | partial | partial | qualified_subset | L48 | PIN_10, PIN_11, PIN_15, and PIN_19 are qualified; PIN_19 also has a registered path. |
| Physical output routing | partial | partial | qualified_subset | L48 | Characterized header outputs and L48 PIN_25 through PIN_28 are qualified. |
| MCU External-AHB slave boundary | partial | partial | qualified_subset | L48 | Global source matching and bounded corridor negotiation close all 32 HRDATA lanes plus independent HREADYOUT/HRESP sources. The constant ready/OKAY endpoint, distinct HADDR[3] and HADDR[5] logic-ingress corridors, four exact direct-D sites, an eight-state counter, and a 16-bit LFSR are silicon-qualified. The default bus clock measures exactly 10 MHz relative to undivided HSI/MTIME; GPIO4.1-fed synchronous reset-to-zero and re-arm are qualified. A complete five-bit posted-storage footprint passes all 32 values, aligned immediate write/read, both back-to-back write orders, persistence, and HADDR2-tagged offset isolation. HWDATA0 through HWDATA5 each have one exact registered consumer; direct HWDATA0 at lane-zero storage and all four X14Y11 slice5 HWDATA5 terminals are live. The slice5 DD88 storage/data/own-Q footprint follows HWDATA5 exactly with commit tied high, while routed-control six-bit variants retain exact bits 0..4 but lane5 remains constant one. The full register bank, integrated reset, hard MCU_RESETN, unrestricted direct-D lowering, waits, errors, storage lanes 5 through 7, and byte access remain open. The X14Y8 slice8 sparse wrong-edge identity case fails closed after a retained constant-one silicon negative. Vendor LUT-buffer arcs are never exposed as transparent PIPs. |
| MCU GPIO fabric boundary | partial | partial | qualified_subset | L48 | The four-bit GPIO4 inverter loopback is silicon-qualified. On L48, exact GPIO5 output-data/output-enable lanes 0 and 1 plus return input lane 2 are silicon-qualified through the pure open flow. The hard boundary requires terminal 8 on the seven inactive BBMUXS groups; zero-filled inactive terminals are not electrically safe. The qualification covers the two exact source pairs and one return lane only, not the full GPIO matrix or package pins. |
| IO electrical attributes | partial | partial | qualified_subset | L48 | Basic qualified input/output configurations are emitted for the exercised L48 pads; the decoded device supplies a checked 15-chain/four-alias/26-field static inventory, two-pad pull-up/open-drain oracles, and the complete 2–30 mA CFG_PDRCTRL mapping. |
| Static timing and constraints | not_applicable | partial | qualified_subset | L48 | LUT/FF/carry arcs and worst delay per driving mux family provide conservative fatal timing closure. |
| Project, source, and constraint compatibility | not_applicable | partial | software_only | L100, L64, L48, Q32 | The CLI supports ordinary synthesizable RTL, project inputs, PCF, and frequency targets for the documented open flow. |
| Vendor primitive and parameter compatibility | partial | partial | software_only | L100, L64, L48, Q32 | The 43-family multi-device library surface is explicitly joined to AGRV2K: four direct CELL_TYPEs, RIO through IO_TYPE, and the implicit core logic site are device-present; 37 library families are not declared on this device. |
| LZW, raw image, CRC, and AGASC handling | complete | supported | software_only | L100, L64, L48, Q32 | Canonical images round-trip byte-exactly; raw configuration, CRC, sparse named features, and LUT editing are supported. |
| Fully from-scratch configuration image | partial | partial | unqualified | none | The full preamble and supported feature fields are generated openly, but the non-preamble canvas is still inherited. |

The detailed workbench ledger also records vendor surfaces, concrete gaps, and
evidence paths. A feature marked `partial` must fail closed outside its documented
subset; package qualification does not transfer between packages.

The derived parameter ledger is
`agamemnon/chipdb/agrv2k_parameter_manifest.json`. Its BRAM width records
separate the six model candidates from the five direct modes accepted by
the open emitter; `legal_values` remains null pending stronger proof. The
RIO drive-current, pull-up, and open-drain domains are populated, but
their open support is empty and electrical behavior unqualified.
