# Synchronous reset in carry SUM slices

Set `AGRV2K_CARRY_RESET_FUSION=1` to let the native packer combine a carry SUM,
its synchronous reset gate, and its capture register. Only the literal `1`
enables the optimization; it is disabled by default.

The adder must have exactly one constant operand and one live operand. Folding
the constant frees a LUT input for reset. The packer changes only the SUM bank
of the truth table, preserving the original carry-out computation even while
reset is asserted. Both reset polarities and reset values are recognized from
the complete truth table, independently of cell or signal names.

The reset LUT must feed only a plain DFF and consume the SUM exclusively.
Additional dependencies, fanout, undefined truth, unsupported controls, keep
or unknown metadata, fixed reset LUTs, and ambiguous shared carry-SUM gates
retain ordinary packing. DFF placement constraints participate in whole-chain
preflight. This option does not enable the separate fixed long-chain local-input
profile or expand the admitted carry footprints.

For example, with the native backend installed:

```sh
AGRV2K_CARRY_RESET_FUSION=1 agamemnon build qualification/lfsr_probe.v \
  --pcf qualification/lfsr_probe.pcf --uarch --hard-carry \
  --no-native-clock-enable --release-strict --freq 10 -o lfsr.bin
```

## Evidence and limits

Compiled tests cover both constant operands and values, both reset polarities
and values, SUM/reset pin permutations, live carry export, disabled forms,
unsupported shapes and fixed-placement conflicts. They check every physical
truth-table row for both SUM and COUT.

The source-built resettable 16-bit LFSR with an eight-bit prescaler uses 36
slices instead of 44, retaining 24 registers and capturing eight carry SUMs
in their arithmetic slices. At 10 MHz its exact image passes two reset and
sequence captures with zero model mismatches and matching vendor controls
before and after. The ordinary 44-slice image passes the same contract.
See [carry evidence](../qualification/carry_evidence.jsonl).

This witness requires the ordinary-slice input-selection correction described
in [STATUS](STATUS.md#ordinary-slice-input-selection--2026-09-18). Earlier
images with either packing strategy stalled because of stale carry-input
selection on separate LFSR state slices.

The default qualified accumulator image is unchanged. The measured area saving
does not establish timing preservation, support for every reset/arithmetic
shape, or the exact first clock after host-driven reset release. The option
remains experimental and disabled by default.
