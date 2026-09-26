# AGaMEMnon v0.5.0 — release preparation

**Publication is pending.** This branch prepares the version metadata and notes;
the final integrated software, SDK and hardware gates have not all passed.
See [release validation](RELEASE_VALIDATION_0_5_0.md) for the remaining evidence.
The [release page](https://github.com/bbenchoff/AGaMEMnon/releases/tag/v0.5.0)
becomes the download source only after those gates pass and publication completes.

Current hardware blockers are reproducible LFSR and x1 BRAM failures. The older
BRAM activity oracle could pass without reads; it does not qualify the historical
39-mode matrix. Stronger source-paired checks distinguish passing vendor images
from failing open implementations. See the
[bounded current results](../qualification/release05_current_hardware_results.json).
These supported vendor modes remain in the qualification scope.

## Changes being qualified

- Empty observed-value sets are rejected. Matching nonempty sets report model
  consistency rather than hardware correctness, and module failures propagate
  to the exit status.
- Optional SRST mapping searches are bounded after an admissible build completes.
  Searches without an admissible baseline retain their normal policy; unsafe,
  timing and unknown failures still propagate. The reproduced x18 build timeout
  completes in approximately 192 seconds on candidate `2daf606`, versus the
  previous 1,800-second deadline without final products. This is a build result,
  not a memory-function qualification.
- Small writable inferred memories can lower to LUTs and registers, with enables
  represented in the data path. Logic-mapped memories try buffered placement
  early in the existing retry sequence. The ordinary FIFO reproducer now passes
  its model and controlled hardware trials on the earlier fix candidate. A later
  repeated-reset check still has one unexplained failure in 64 direct-reset trials.
- Asynchronous-clear lowering preserves register feedback and reset polarity,
  including registers with enables. Positive- and negative-reset examples and an
  enable holdout have controlled hardware evidence; wider compositions still
  need qualification.
- Route retries retain the ordinary router costs on their initial attempt and
  use congestion avoidance after a rejected implementation. Selector inference
  rejects codewords contradicted by exact source observations. These changes
  address demonstrated wrong-result and placement failures without making route
  acceptance a guarantee of correct silicon behavior.
- Short dedicated-carry chains have additional admitted placement sites. The
  HSE=8 MHz PLL ratio model admits computed dividers within its legal envelope;
  open-flow counter examples cover 33, 62 and 77 MHz. Placement acceptance and
  valid PLL configuration do not establish a design's timing margin.
- Qualified BRAM source examples declare the required constant placement and
  complete reserved trees, including write-data branches. All four fresh source
  profiles reproduce the corrected, paired-hardware-tested images on integration
  candidate `1ee501b`. Their contract is fixed-address, single-observed-lane
  write/hold behavior, not general inferred BRAM support.
- SDK packaging includes normalized routing data and native runtime tables.
  Native-tool paths and synthesis Tcl libraries are staged safely for paths with
  spaces. Failed installed builds retain diagnostics, and archive smoke image
  identities are checked against the CLI and qualification record.
- Shared BRAM driver packing retains every terminal's placement constraints,
  including terminals with no admissible source. Incompatible shared requests
  fail instead of silently dropping a required connection. Retained MCU-map
  composition uses the packaged, hash-checked database independently of a local
  development cache.

## Intended installation artifacts

The release workflow builds one wheel and embeds that exact wheel in the Windows
and Linux SDK archives. Each artifact has a SHA-256 sidecar:

```text
agamemnon_ag32-0.5.0-py3-none-any.whl
agamemnon-sdk-linux-x64.tar.gz
agamemnon-sdk-windows-x64.zip
```

After publication, verify the sidecars, activate the matching SDK environment,
and check `agamemnon --version` reports `agamemnon 0.5.0`. A wheel alone does not
install all native FPGA/MCU tools. Follow [installation](INSTALLATION.md) and
`agamemnon doctor --no-hardware` for the required capabilities. The OpenOCD
transport remains a separate installation.

## Qualification limits

The release target is a reliable default flow for ordinary L48 designs, not full
vendor parity. Final qualification must include the maintained 12-design corpus,
independent reset/enable/memory/arithmetic holdouts, fresh installed builds and
controlled board observations on the combined candidate.

General BRAM sites, widths and interactions; complete MCU/fabric AHB master and
DMA behavior; alternate packages and electrical modes; dense designs; and measured
timing margins remain separate open areas. A heartbeat checks only its named
oracle, and software model agreement is not independent proof of silicon behavior.
Known refusals remain visible; they are containment rather than feature completion.
See [supported scope](STATUS.md) and the [roadmap](../ROADMAP.md).
