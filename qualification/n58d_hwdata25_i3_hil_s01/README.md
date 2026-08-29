# N5.8D HWDATA25 graph-legal-I3 HIL S01

This package is a bounded silicon discriminator for the accepted N5.8A typed
endpoint: `HWDATA[25]` / `MCU_DIN69` / `X10Y5_MCU_DIN69`, rooted at
`X13Y9_BufMUX07` with mandatory first hop to `X13Y9_InputMUX06`.

The N5.8C silicon-accepted composition terminates at
`X15Y9_SLICE2.I2` / `X15Y9_IMUX10`. This child retains that exact slice BEL,
output route, observation pad, stimulus, and control image. Its sole intended
functional change is I2/`INIT=F0F0` to I3/`INIT=FF00`, terminating at
`X15Y9_SLICE2.I3` / `X15Y9_IMUX11`.

The exact I3 input route after the mandatory first hop is:

```text
X13Y9_InputMUX06 -> X14Y9_RMUX55 -> X14Y10_RMUX31 ->
X15Y10_RMUX25 -> X15Y11_RMUX07 -> X15Y9_RMUX41 -> X15Y9_IMUX11
```

Candidate and control share the exact N5.8C-qualified observation route:

```text
X15Y9_OMUX08 -> X15Y9_RMUX03 -> X14Y9_RMUX15 -> X18Y9_RMUX69 ->
X18Y13_RMUX28 -> X18Y13_IOMUX00
```

The output terminates at L48 `PIN_18` / Pico GP8. The route-matched control
keeps the same LUT placement and output route but emits constant zero. The
SRAM-only RISC-V stimulus repeatedly writes zero and bit 25 at the External-AHB
window.

The experiment asks only whether this exact same-BEL I3 composition conducts.
It does not generalize to another I3 site, terminal, HWDATA lane, consumer,
fanout, AHB protocol semantic, timing/Fmax, package/device, or device-wide
nextpnr/vendor parity.

Two exact-toolchain output roots independently rebuilt candidate, control, and
stimulus. All eight raw fabric/firmware products were byte-identical between
roots; both routed checkpoints were also byte-identical after canonicalization.
Candidate emission closed 12/12 data pips and control emission closed 5/5,
with zero unmapped, predicted, or legacy-absolute selectors. The candidate
uses nextpnr heap placement with explicit seed 1. The fixed control uses the
CLI's conduction placement policy with cap 2 and internal seed 4; it does not
receive a false heap/seed-1 attribution.

Desk verification:

```text
python -B qualification/n58d_hwdata25_i3_hil_s01/audit_package.py
python -B -m pytest -q -p no:cacheprovider \
  qualification/n58d_hwdata25_i3_hil_s01/test_hil_s01.py \
  tests/test_mcu_endpoint_n58a.py
```

`package_manifest.json` deliberately does not authorize hardware. A separate
controller package, detached audit, and fresh short-lived one-use GO must bind
the frozen Git commit and all three exact SRAM payloads before board contact.
