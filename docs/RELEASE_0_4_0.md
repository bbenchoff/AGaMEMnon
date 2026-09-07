# AGaMEMnon v0.4.0

This is the **unpublished integrated v0.4.0 candidate**, combining the earlier
release preparation with the subsequent Qin, odd-slice and retained-replay
work. Its final SDK artifact gate remains open. Full CI `34089341861` and
OpenOCD `34088837146` passed; Windows and Linux empty-home public OpenOCD
installation checks passed. SDK workflow `34089520106` completed with both
platform archive-assembly failures because `pip_usage.csv` and
`rrg_rmux_imux_full.csv` were classified as research-only; its earlier
regression stage passed. That stale preflight is now corrected; replacement
SDK run `34094652131` is awaiting a terminal result.
It is an incremental open toolchain release candidate, **not vendor parity**.
Release assets will appear on the [v0.4.0 release page](https://github.com/bbenchoff/AGaMEMnon/releases/tag/v0.4.0) after publication.

The earlier implementation baseline `aa1201158eb34da35b10e7c9402abf9b8599d726`
and its historical campaign results below are retained evidence, not test
results for this integrated tree. Ordinary-source regbank16 and util20 builds
with experimental odd support now pass their sampled silicon contracts 3/3,
with passing references and controls. See the
[exact candidate identities and limits](../qualification/ORDINARY_ODD_CONTRACTS_20260906.md).
The native source-typed odd-site path is now enabled by default. Fresh installed
builds without the experimental variable reproduce those exact images; see
[default verification](../qualification/ODD_DEFAULT_REPRODUCTION_20260907.md).
This does not admit every experimental branch or arbitrary odd-site composition.
Negative fences remain 74 across 18 IDs.

The fallback slot policy now accounts for compatible odd sites, and local-Qin
lowering removes feedback buffers in those two fresh builds. Compact util20
routing and addsub16 emission remain unresolved. Default emission reproduces
58/58 migrated retained images; authenticated research-only replay reproduces
58/58 original images without changing their pins. These are distinct image
versions: see [retained reproduction](../qualification/RETAINED_IMAGE_VERSIONS.md).
The isolated wheel repack check passed after two missing runtime datasets were
packaged. Full installed synthesis/P&R/programming validation remains open;
see [installed SRAM evidence](../qualification/INSTALLED_PUBLIC_SRAM_20260906.md).

Release qualification additionally repaired the Python emission validator's
missing IPAD-name admission for already characterized physical inputs. It
joins verified input rows to the exact L48 bond map; unlisted pads and malformed
native identities remain refused. No pad encoding or historical image changed.

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

## Historical baseline qualification and current limits

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
That historical source-checkout result does not substitute for the current
wheel, SDK archive, and installed-workflow gates. v0.4.0 is not yet published;
downloadable release artifacts should be taken from the release page only
after publication.

## Installation and upgrade

When v0.4.0 is published, use its wheel or matching Windows/Linux SDK archives
from the release page and verify the adjacent SHA-256 file before extracting.
The SDK archives contain pinned synthesis/place-and-route and MCU compiler
tools; the wheel alone does not. Compatible DAP OpenOCD is now published as
`openocd-v0.1.0` and is installed separately with `agamemnon install-openocd`.
Until publication, use a commit checkout; the v0.4.0 tag is not available:

```sh
git clone https://github.com/bbenchoff/AGaMEMnon
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

Current SDK checkpoint (2026-09-07): run `34089520106` failed archive assembly after passing its regression stage. Commit `348f94f` corrected the stale classification of the two required normalized runtime tables; the actual candidate-wheel preflight now passes. Replacement SDK run `34094652131` is still running, so complete Windows/Linux archive validation remains open.
