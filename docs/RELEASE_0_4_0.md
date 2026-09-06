# AGaMEMnon v0.4.0

This release packages the qualified L48 improvements through implementation
revision `aa1201158eb34da35b10e7c9402abf9b8599d726`. It is an incremental open
toolchain release, **not vendor parity**. Later shared BRAM-tree negotiation,
direct-D/BRAM identity bridges and high-address logic ingress remain development
work and are not included in this release.

## What changed since v0.3.0

- Native endpoint, register-control, carry and placement legality checks;
  generalized local-output reachability and protected hard-input ingress.
- Correct F/Q ownership for secondary OMUX outputs, with coordinated
  requalification of retained public maps, SERV and carry fixtures.
- Corrected PIN10 input selection and SPI MISO pad ownership. The four corpus
  SPI receive forms have bounded controlled silicon recovery; broader modes,
  rates, lengths and compositions are not implied.
- Generalized BRAM constant/clock handling and graph-derived identity bridges.
  Initialized single-port x1/x18 ROM admission is content-independent within
  the characterized X13Y4/L48, 10 MHz MCU bus, 8 MHz HSE, write-disabled mode.
- Source-specific BRAM control encoding, portable runtime clock-admission
  data, and improved failure-stage diagnostics.
- Retained negative-image fences and rejection of unqualified/nonportable
  selector translations. Accepted compilation is still not a silicon proof.

## Qualification boundary

The reconciled research corpus has 74 bounded successes, 2 correctness escapes,
14 no-image classifications, 10 vendor-reference failures, 2 unstable references
and 3 incomplete harnesses: 105 classifications in total. The often quoted
74/76 denominator includes only emitted stable vendor-valid cases; it is not a
whole-toolchain completion percentage. Paired structural coverage is 38/51;
the sealed holdout remains empty. Some recovered rows use retained routes or
explicit options, so these counts do not promise ordinary source compilation
for every row on every host.

Supplemental evidence covers full-depth read-only 8192x1, 4096x2, 2048x4,
1024x9 and 512x18 ROMs, the x18 storage-bit identity matrix, and an explicit-carry
waitstate variant. These are not extra corpus successes. Neither unchanged
waitstate16 form is promoted by its rewritten variant.

The bounded four-arm RAM experiment passed eight silicon runs and 4,000
samples on this implementation baseline. Two initialized arms required
research-only admission. This is not general RAM support or a release template:
address independence, retention after writes stop, dual-port collisions and
broader read/write controls remain unqualified.

The baseline complete Windows regression passed 2,399 tests with 554 skips and
zero failures/errors. Skipped native/tool-dependent checks are not passes.
That source-checkout result does not substitute for tagged wheel and SDK
archive smoke tests on Windows and Linux. Downloadable artifacts exist only
after the release workflow passes; see the
[release page](https://github.com/bbenchoff/AGaMEMnon/releases/tag/v0.4.0).

## Installation and upgrade

Use the wheel or matching Windows/Linux SDK archives from the release page.
Verify the adjacent SHA-256 file before extracting. The SDK archives contain
pinned synthesis/place-and-route and MCU compiler tools; the wheel alone does
not. Compatible DAP OpenOCD is installed separately with
`agamemnon install-openocd`. Source installations can select the tag explicitly:

```sh
git clone --branch v0.4.0 https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
python3 -m pip install -e ".[programming]"
agamemnon --version
agamemnon doctor --no-hardware
```

On Windows use `python` where appropriate. Rebuild the AGRV2K nextpnr backend
from the same release: mixing a new Python package with an older custom native
backend is not a supported upgrade. Follow [Installation](INSTALLATION.md) for
tool paths and [Programming](PROGRAMMING.md) before connecting hardware.

## Remaining limitations

General writable/dual-port RAM, wider direct-D/register controls, all clock and
timing combinations, dense mixed designs, broad physical I/O compositions and
other device/package variants remain incomplete. Retained hart-hanging images
are fenced; absence from a negative registry does not establish safety for an
unseen design. SRAM-first control/qualification remains essential. See
[Status](STATUS.md), [Roadmap](../ROADMAP.md), and the feature-specific evidence.

Historical reports retain their original dated counts and negative results.
Use this release scope and current support matrix for present claims, not an
old experiment's conclusion in isolation.
