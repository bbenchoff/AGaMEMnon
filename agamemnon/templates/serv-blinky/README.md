# SERV CPU blinky

This project strictly replays the retained L48 SERV blinky profile. The
fabric runs the public ISC-licensed SERV bit-serial RISC-V core with a
true-dual-port x2 BRAM register file. It repeatedly executes `addi` and `sw`;
a registered program-counter bit drives the onboard PIN_25 LED.

```text
agamemnon build
agamemnon run --transport dap
```

Hold PIN_10 high to reset and halt SERV. Release it to run. `run` loads the
MCU loader and fabric image into volatile SRAM and does not touch flash.

The template includes the exact public Verilog, board constraints, and routed
JSON used by the profile. Build strictly repacks the retained route and checks
every input and output hash. The raw image is 99,944 bytes with SHA-256
`fe7ecca298dc5bd929a12c3bf63c90a8323180a93016defa977de59580aa3d5a`;
the 9,722-byte compressed image has SHA-256
`2985f92decb6104b94647d9681ccd77d3a7f7246147cf027eebf90fda116d6b0`.

This exact replay is release-supported. Fresh source place-and-route remains
a developer target because arbitrary direct-D placement is not qualified; it
continues to fail closed and is not implied by this profile.
