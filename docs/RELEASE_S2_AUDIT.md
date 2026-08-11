# S2 Packaging and Example Audit

This record describes the bounded S2 packaging and example checkpoint. It is
not a declaration that the whole release-hardening campaign is complete.

## Qualified cold paths

- A fresh `mcu-blink` project builds the fabric-free MCU example on Windows.
- A fresh `mcu-fpga` project strictly replays the public
  `l48-complete-byte-waited-2026-08-05` profile on Windows and Linux/WSL. The profile
  contains public Verilog and normalized pure-open routed JSON, not a vendor
  bitstream or a private campaign artifact.
- The replayed raw image is 99,944 bytes with SHA-256
  `7d6cd01be47998176120324f8a131843cc96248221645e9f040cdf3950c99d81`.
  Its compressed form is 4,873 bytes with SHA-256
  `962bbe0ffb86a26b8acd9fabeabf250b66e37212566d4c64b8b71699f60b6cf1`.
- Icarus simulation exercises all 256 scratch-byte values and the immutable ID
  behavior. The template firmware configures the fabric, checks the ID and
  scratch reset value, performs two write/read cycles, verifies that an ID
  write is ignored, and verifies scratch persistence.
- An isolated wheel installation can find the registry, source, and routed
  profile and can reproduce the same byte-exact image outside the source tree.
- The installed wheel also exposes `--template serv-blinky`. It strictly
  replays the retained 2,186-PIP L48 route at raw SHA-256
  `fe7ecca298dc5bd929a12c3bf63c90a8323180a93016defa977de59580aa3d5a`
  and compressed SHA-256
  `2985f92decb6104b94647d9681ccd77d3a7f7246147cf027eebf90fda116d6b0`.
- Public CI run `31325435464` on commit `ad2c680` reproduced the installed
  wheel on native macOS arm64/Python 3.9. The same commit passed the Linux and
  Windows wheel/test jobs and the complete AGRV2K end-to-end build.
- Current CI also carries a dedicated native Windows x64/Python 3.9
  `installed-wheel-windows` job. It builds a wheel from the clean checkout,
  installs only that wheel into an isolated environment, and runs the same
  data, scaffold, qualified-image, and strict-bitgen smoke used on Linux and
  macOS. Hosted CI run `31353513414` completed successfully on public commit
  `945e9e1`, including the installed-wheel gates. A later publication commit
  must still pass the same matrix.

The exact profile is the register example and MCU/fabric showcase for this
checkpoint. It does not promote arbitrary MCU/fabric routing. The generic
decoded-only `AGAMEMNON_MCU_ENTRY` path remains fail-closed before synthesis.

## Retained SERV evidence

The retained SERV route is now an exact hash-bound project profile, and its
pinned Icarus protocol test passes. Fresh SERV source place-and-route is not in
the qualified cold-build envelope: direct-D cells exceed the currently
qualified direct-D site pool, and replaying the retained checkpoint as hard
placement constraints produces a packing conflict. S2 does not treat the
retained artifact as proof of fresh-source closure.

## Remaining release gate

- The annotated but unpublished `v0.1.1` tag remains bound to its historical
  release-preparation commit. The continuing candidate uses version `0.1.2`;
  the old tag must not be moved or reused.
- Obtain the same green hosted Linux, macOS arm64, and Windows
  installed-wheel matrix on the final publication commit; current public main
  already has a successful reference run (`31353513414`).
- Publish and independently reproduce the final SDK archives/tag. The tag
  workflow builds, hashes, offline-smokes, and publishes the wheel plus the
  Linux and Windows SDK bundles; local wheel evidence alone is not the release
  artifact.

Fresh arbitrary SERV placement remains post-release breadth because the exact
supported profile already fails closed outside its hash-bound route. Additional
hardware exercises may extend evidence when a target is accessible; S2 relies
on the retained L48 silicon records and makes no new hardware claim.

