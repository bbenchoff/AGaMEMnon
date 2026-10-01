# AGaMEMnon v0.5.0

AGaMEMnon turns ordinary Verilog into an AG32 L48 fabric image with open tools only.
This release finds and removes the routing-table errors that made some default builds
produce silently wrong images, bounds every place-and-route attempt, fences one BRAM
mode that failed on silicon, and adds opt-in router-chosen LUT input pins. It is a
bounded L48 release, not vendor parity. See [release validation](RELEASE_VALIDATION_0_5_0.md)
for the evidence behind each claim.

## Tested on hardware

Results are from the release candidate on one AG32VF303CCT6 (L48) board, loaded into
SRAM, with a known-good reference image between designs.

| Check | Result |
|---|---|
| Maintained corpus and holdouts, 18 fresh default builds | 18/18 pass; 19/19 references |
| Stronger fast and slow RAM holdouts, 2 loads x 32 resets | 64/64 and 64/64 (0/32 before this release) |
| Stronger FIFO and LFSR holdouts, 2 loads x 32 resets | 61/64 and 61/64; see Known limitations |
| Designs that built wrong images during release preparation, rebuilt | pass |
| Router-chosen LUT inputs on, 38 designs | 38/38 pass (38/38 with it off) |

Software: the full Python suite and the native-toolchain complement pass with no
failures; installed wheels pass on Linux, Windows and macOS; the SDK archives build.

## What changed

- **Wrong routing-table rows are refused.** Five default images that read back wrong
  on silicon were each traced on the board to one routing connection: rerouting only
  the net that used it made the image pass, and none was a timing effect (the first
  failed identically at 4, 10 and 40 MHz). All five take their selector codeword from
  a table that generalises codewords seen at one row or column to others, and the
  vendor's own bitgen has none of them. A vendor-bitgen check of every unconfirmed
  entry of that table found nine more, and six further connections select a different
  source than modelled. The flow refuses these 20 and retries around them; the device
  graph is unchanged. [Evidence](../qualification/afexe_absent_refusal_20260929.json).
- **Never-proven route shapes are refused.** Routes through a source/destination pair
  and tile offset that no board-passing design has used are refused and retried (2,416
  pips, about 1% of fabric routing), as are 207 pips isolated by pass/fail board
  comparisons. [Evidence](../qualification/unproven_shape_refusal_20260929.json).
- **Every place-and-route attempt is bounded at 300 s.** nextpnr's router2 could
  oscillate indefinitely; a timed-out attempt moves on to the next seed.
- **x1 single-port BRAM writes need `PORTA_OUTREG=1`.** The unregistered form failed on
  silicon while the registered form and the vendor image passed.
- **A completed build is kept** when an optional alternative reset mapping fails its
  bounded search.
- **Opt-in router-chosen LUT inputs** (`AGAMEMNON_LUT_PIN_SWAP=1`). The router may land
  a signal on any eligible input of a LUT and the truth table is permuted to match, as
  the vendor router does, with the vendor's freeze rules for feedback, register-bypass
  and carry inputs. Off, output is byte-identical to before. (After v0.5.0 this became
  the default; `AGAMEMNON_LUT_PIN_SWAP=0` turns it off. See the changelog.)
- Earlier 0.5 changes (memory lowering, asynchronous clear, route retries, the PLL ratio
  model, BRAM source profiles, SDK packaging) are listed in the [changelog](../CHANGELOG.md).

## Known limitations

- **Synchronize external resets.** A design that feeds an asynchronous input pin
  straight into a synchronous reset across many registers can start some registers a
  clock later than others. The stronger FIFO and LFSR holdouts do this and miss about
  3 in 64 reset releases; the same RTL with a two-flop reset synchronizer passed 96/96
  and 128/128. The vendor's images of the unsynchronized RTL pass, most likely because
  its reset routing has less skew; skew-aware reset routing is future work.
- **Some dense designs refuse to build**, for example with a forced `--seed`, when every
  legal route needs a refused connection. The build stops with a message instead of
  emitting an image.
- **Router-chosen LUT inputs are opt-in.** Their board A/B found no defect, but they
  change most images, including every byte-exact qualified fixture, so enabling them by
  default needs its own requalification.
- **Build success is not silicon evidence.** Test a new design on hardware.
- BRAM: x18 and x2 dual-port writes, x4 dual-port writes and read-only modes at X13Y4
  are the supported set. Timing is conservative and does not model clock skew. Other
  packages, the MCU AHB master and DMA, analog, and most hard-peripheral modes remain
  outside the tested scope. See [supported scope](STATUS.md) and the
  [roadmap](../ROADMAP.md).

## Installation artifacts

The release workflow builds one wheel and embeds that exact wheel in the Windows
and Linux SDK archives. Each artifact has a SHA-256 sidecar:

```text
agamemnon_ag32-0.5.0-py3-none-any.whl
agamemnon-sdk-linux-x64.tar.gz
agamemnon-sdk-windows-x64.zip
```

Verify the sidecars, activate the matching SDK environment, and check that
`agamemnon --version` reports `agamemnon 0.5.0`. A wheel alone does not install
all native FPGA/MCU tools. Follow [installation](INSTALLATION.md) and
`agamemnon doctor --no-hardware` for the required capabilities. The OpenOCD
transport remains a separate installation. Downloads are on the
[release page](https://github.com/bbenchoff/AGaMEMnon/releases/tag/v0.5.0).
