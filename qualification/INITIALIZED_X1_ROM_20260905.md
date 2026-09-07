# Ordinary initialized x1 ROM support

The ordinary strict source-to-image flow now admits the characterized single
Port-A x1 ROM mode. Admission is based on hardware configuration, not a source
digest, module/cell name, INIT value, saved route or image allowlist. Synthesis,
placement, routing, clock validation and selector/negative-image checks still
run normally; this is not an unsafe/research bypass.

## Supported contract

- One BRAM at X13Y4 on AGRV2KL48; Port A width code 15 (x1), Port B unobserved.
- MCU bus default clock profile, GCLK0, 8 MHz HSE and 10 MHz fabric clock.
- CLKMODE zero, connected Clk0 and ClkEn0, no second clock or explicit read/write
  control routes. The characterized ROM control footprint disables writes.
- The ordinary x1 lowering's Port-B input/output clock enables are one; Port-A
  clock/reset enables and Port-B reset enables are zero.
- Experimental output-register, write-through, packed/delay and site-control
  configurations are excluded. All thirteen physical Port-A address positions
  must be represented; their contents and logic origins are not allowlisted.

Within this contract, arbitrary initialized x1 contents and depths fitting the
memory are eligible; routing/resource feasibility still applies. This does not
admit x18 initialized reads, writes, dual-port operation, other BRAM sites,
alternative clock/control modes, or timing closure beyond the existing clock
policy. These remain development work, not a revised definition of parity.

Width code zero is x18, not a disabled-port code. Port-B read use includes both
cell consumers and top-level outputs. An unconnected write port selects the
characterized write-disabled control footprint; it is not proof that an
unselected physical input reads zero. Native constant-high writes still refuse
instead of silently degrading to ROM.

## Evidence

Before admission, full-depth address-plane/complement silicon qualification
passed 78 positive runs and 39 exact negatives with three passing public32
controls. The 26 patterns uniquely label every address and exercise both stored
values at every location. Positive runs cover 2,555,904 first/settled reads.
The asymmetric full-depth and fresh ROM256 images each independently passed
three full-oracle silicon repetitions with exact zero negatives and controls.
Evidence is retained in AG32-Docs commit
`7c1d6d8aba33a8da3afee1d282f602a3775a7814` and its referenced prior witnesses.

With semantic admission enabled, fresh strict RTL builds now complete without
INIT restoration or image patches:

| Depth | Build time | Ordinary emitted image SHA-256 |
| --- | --- | --- |
| 256 | 40.46 s | `48c32bf97e849700a436ee15ec26f241d0d130ffa10854abcb0faec63aa53b1f` |
| 8192 | 86.09 s | `290a197dd68f80697af6f721d72f0b73d9808935c4175751eb19a1706f22bb97` |

Both images and their validated routes are byte-identical to the respective
witnessed artifacts. No new hardware result is claimed for the build commands
themselves; byte identity connects them to the prior silicon observations.

Independent admission tests vary names and contents and reject unqualified
width/site/control/clock/write/Port-B/multiple-memory contexts. The old policy
fails all eight new positive cases and passes its nineteen initial refusal
controls. Additional experimental-mode refusal cases are included afterward.
Focused follow-up passes 82; broader checks pass 148 with three native-tool
skips. All three pass separately with native/synthesis tools configured
(136.77 seconds), including the named unconditional-write refusal. Ordinary
initialized packing also reproduces all 26 witnessed address-plane images
byte-for-byte without post-pack edits. The complete pre-admission
suite passed 2,236 with 484 skips; it is not a post-admission full-suite result.
