# S2 Packaging and Example Audit

This record describes the bounded S2 packaging and example checkpoint. It is
not a declaration that the whole release-hardening campaign is complete.

## Qualified cold paths

- A fresh `mcu-blink` project builds the fabric-free MCU example on Windows.
- A fresh `mcu-fpga` project strictly replays the public
  `l48-id-scratch8-2026-08-04` profile on Windows and Linux/WSL. The profile
  contains public Verilog and normalized pure-open routed JSON, not a vendor
  bitstream or a private campaign artifact.
- The replayed raw image is 99,944 bytes with SHA-256
  `4cd1551d1202c9768554b75deddcace93291e8444b6d6c82f9762936a7dc737b`.
  Its compressed form is 3,948 bytes with SHA-256
  `6d262bfe73a2c6fcfb9ff779f34bdc3b6cc840ba1a867000ccafa92fa724c71a`.
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

## Remaining release gates

- Repair fresh SERV source routing within the BRAM and direct-D ownership
  campaign; the exact profile does not promote arbitrary placement.
- Obtain a green run from the new native macOS isolated-wheel CI job. The job
  is part of this review unit; a successful hosted run remains the evidence.
- Publish and independently reproduce the final SDK archive/tag. A local wheel
  smoke test is necessary evidence, not the release artifact itself.
- Run hardware exercises when an accessible target is available. This S2 unit
  used neither vendor tools nor hardware and makes no new silicon claim.

