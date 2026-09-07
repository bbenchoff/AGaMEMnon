# AGaMEMnon v0.4.0

AGaMEMnon v0.4.0 is an open, bounded toolchain release for the AG32 AGRV2K L48
envelope. It does not claim full vendor parity, universal timing, or correctness
for arbitrary RTL and placement.

## Install

Download the six SDK release files from the [v0.4.0 release page](https://github.com/bbenchoff/AGaMEMnon/releases/tag/v0.4.0):

```text
agamemnon_ag32-0.4.0-py3-none-any.whl
agamemnon_ag32-0.4.0-py3-none-any.whl.sha256
agamemnon-sdk-linux-x64.tar.gz
agamemnon-sdk-linux-x64.tar.gz.sha256
agamemnon-sdk-windows-x64.zip
agamemnon-sdk-windows-x64.zip.sha256
```

Verify the sidecars before installation. Extract the matching Linux or Windows
SDK archive, activate its environment (`activate.sh` or `activate.ps1`), and
check:

```sh
agamemnon --version
```

The result must be `agamemnon 0.4.0`. A wheel-only installation is also
available for inspection and offline verification:

```sh
python -m pip install agamemnon_ag32-0.4.0-py3-none-any.whl
agamemnon --version
agamemnon doctor --no-hardware
```

The SDK archives include the pinned OSS CAD Suite, RISC-V toolchain, AGRV2K
nextpnr build, runtime files where required, the wheel, and offline smoke
fixtures. The OpenOCD transport is distributed separately:

```sh
agamemnon install-openocd --version v0.1.0
```

Use the platform archive and matching checksum for Linux or Windows. The
published OpenOCD workflow covered four platform builds and its verification
gate; installation is still a transport capability and does not establish a
new silicon qualification.

## Supported envelope

- Python inspection, project creation, offline verification, MCU compilation,
  and the bundled FPGA build flow are supported capabilities when their
  required host tools are available.
- Normal native builds use source-typed F/Q ownership for odd fabric sites.
  The installed `regbank16` and `util20` profiles reproduce their exact
  sampled hardware-tested raw and compressed images. This substantiates those
  bounded profiles; it does not qualify every odd-site composition.
- Exact retained AHB, carry, clock, physical-I/O, BRAM read-only, and selected
  BRAM write profiles remain available at their named part, package, route,
  frequency, and observable contract. Read the qualification records before
  treating any profile as a reusable design pattern.
- The ordinary placement density hint is `--cap 16` for the documented
  publication examples. This is a hint for placement search, not a capacity
  guarantee and not a claim about every CLI default.
- `--release-strict` limits routing to the release-admitted routing policy. It is
  the tightest selector gate, but an accepted edge may be release-admitted by
  exact encoding evidence without a conduction witness at that position; it
  does not establish silicon correctness. Ordinary tiered routing remains
  evidence-tiered; research-unsafe routing is an explicit experiment mode and
  does not promote an image to release scope.

## Limits and fences

The release retains 74 negative fences across 18 defect IDs. They prevent known
unsupported or silent-wrong images from being emitted. The fences remain part
of the safety boundary and are not failures of the release package.

Generic FSM and feedback behavior is not broadly qualified. Dense wide-state,
arbitrary BRAM write/dual-port, unqualified clock-region, broad peripheral,
bidirectional, alternate-package, electrical-margin, and AHB-master/DMA claims
remain outside the current qualification envelope. A successful decode, route,
CRC, or configuration acceptance does not establish silicon correctness. Timing
is qualified only for the named contracts and frequencies in the evidence
records.

The complete evidence, exact hashes, historical results, and terminal workflow
records are in [RELEASE_VALIDATION_0_4_0.md](RELEASE_VALIDATION_0_4_0.md)
and the linked qualification records. See also [STATUS.md](STATUS.md) and
[INSTALLATION.md](INSTALLATION.md) for current support and setup guidance.
Those records retain dated failed and cancelled runs without making them
current publication claims.

See the [roadmap](../ROADMAP.md) for the remaining correctness, capacity and
timing work beyond this release.
