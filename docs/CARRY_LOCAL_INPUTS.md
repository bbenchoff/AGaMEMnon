# Registered carry local inputs

A full 32-bit feedback accumulator previously demanded 17 independent inputs
in a tile with only 16 reachable ingress wires: 16 addends plus the carry
sum-selector supply. Router retries cannot make that placement routable.

The native packer recognizes a bounded alternative. For one complete chain
of 32 registered arithmetic stages, with exactly one own-Q operand per stage,
one shared clock and no exported carry, it leaves the D selector unselected.
That input reads high in the witnessed footprint. The other operand retains
its ordinary routing input. Other chain shapes retain routed D/VCC.

The footprint is exactly X20Y12_SLICE0..15, X20Y11_SLICE0..15 and
X20Y10_SLICE0. The first slice is the combinational seed. The 32 arithmetic
members carry `AGRV2K_CARRY_D_DEFAULT_HIGH=IMUX_UNSELECTED_HIGH_V1`; the seed
does not. Own-Q on A also requires
`AGRV2K_CARRY_A_Q_FEEDBACK=LOCAL_PRESENTATION_V1` and the exact local
Q-presentation path. Own-Q on B uses the existing typed feedback path.

The graph protects the 32 A-feedback edges as `CARRY_QFB_A`. Ordinary nets
cannot use them. Native routing reserves the unselected D wires, and direct
packing independently checks the complete footprint, shared clock, register
shape, feedback ownership and absence of routed D inputs. Emission explicitly
clears all 384 D-selector bits and audits them again in the final image.

## Qualification witness

[`accumulator32_lfsr.v`](../qualification/accumulator32_lfsr.v) adds a 32-bit
LFSR value into a 32-bit accumulator every clock. A divided output samples
the accumulator's high bit. Reset clears the LFSR and output divider; the
accumulator retains its initial state, which the checker solves before
comparing the observed sequence.

Rebuild nextpnr from the same checkout, then run:

```text
python -m agamemnon.cli build qualification/accumulator32_lfsr.v --uarch --hard-carry --release-strict --no-native-clock-enable --freq 10 --pcf qualification/accumulator32_lfsr_L48.pcf -o accumulator.bin
```

The final ordinary CLI image passes at 10, 80, 90, 100 and 110 MHz. Three
fresh-load trials at 110 MHz produced 16,082 decoded bits with zero model
mismatches. The same image fails at 120 and 125 MHz; the vendor controls
pass before and after each test. Higher-frequency images change only the
PLL preamble and CRC, preserving the 10 MHz placement and routing.

An earlier diagnostic placement failed at 90 and 100 MHz, so that limit
must not be transferred to the final image. The final result still falls
short of the vendor's recorded 150 MHz result. These sampled trials do not
establish a general timing guarantee. The checker accounts for capture
slips and excludes uncertain capture edges.

The B-feedback variant also has a separate 10 MHz rate witness: the public
131071-increment counter builds with 32 D-default markers and no A markers,
then produces the expected 305–306 Hz in three fresh loads. This checks a
constant-increment counter, not every possible B-feedback design.

Exact build identities, positive results and timing failures are recorded in
[`carry_evidence.jsonl`](../qualification/carry_evidence.jsonl).
