# Contributing to AGaMEMnon

AGaMEMnon accepts code, documentation, reverse-engineering notes, reproducible
designs, and hardware evidence. The most valuable contribution is one whose
claim can be independently reproduced and whose boundary is explicit.

The campaign evidence makes the required categories explicit: report
build/routability, independent-model agreement, vendor-reference usability,
and open-silicon correctness separately. A clean emitted image that fails the
model-backed board contract is a correctness escape, not a routing success to
be promoted or a test to be relaxed.

## Before opening a change

1. Search existing issues and the [roadmap](ROADMAP.md).
2. Read the [support vocabulary](docs/AG32_OVERVIEW.md#evidence-vocabulary).
3. Keep unrelated refactoring separate from a behavioral or evidence change.
4. Identify every third-party source or artifact; see [NOTICE.md](NOTICE.md).

For a large architecture change, start with an issue describing the intended
claim, evidence source, affected package, and failure policy.

## Development setup

```sh
git clone https://github.com/bbenchoff/AGaMEMnon
cd AGaMEMnon
python -m pip install -e ".[programming]"
python -m pip install pytest
agamemnon doctor --no-hardware
python tools/check_docs.py
python tools/check_path_leaks.py
pytest -q
```

The hardware-free test suite does not require a board. End-to-end Verilog
build tests run when Yosys and the AGRV2K nextpnr backend are available.

## Pull requests

A pull request should state:

- what changed and why;
- whether the change is software-tested, build-supported, or
  silicon-qualified;
- the exact board, package, probe, tool versions, and clock settings involved;
- commands needed to reproduce the result;
- tests run and their outcome;
- provenance and licensing of new data or third-party material;
- any recovery path used before a persistent flash write.

Do not broaden a support claim from one package, pin, tile, corridor, width,
clock, or protocol mode to another without matching evidence.

## Hardware evidence

Hardware observations belong in append-only JSONL records under
`qualification/` when an existing schema fits. Corrections add a record that
references the superseded observation; they do not rewrite history.

Include:

| Field | Example |
|---|---|
| Device | `AG32VF303CCT6`, marking photographed or transcribed |
| Fabric/package | `AGRV2KL48`, LQFP-48 |
| Board | vendor development board and revision if visible |
| Probe/transport | AGM CMSIS-DAP, USB loader 2.1, or Pico UART |
| Host tools | AGaMEMnon commit, Yosys, nextpnr, compiler, OpenOCD |
| Inputs | source, PCF, routed JSON, firmware, and hashes |
| Conditions | clocks, voltage, relevant wiring, reset/boot state |
| Oracle | exact electrical, register, serial, or readback observation |
| Recovery | backup and restoration result for persistent tests |

FCB acceptance proves configuration framing and CRC; it does not prove that a
routed path conducts. Whole-design correlation is diagnostic evidence, not an
isolated edge qualification.

## Code and documentation

- Support Python 3.8 or newer.
- Keep hardware access fail-safe: reads and volatile SRAM operations should be
  the default; persistent writes require explicit intent and verification.
- Reject unsupported device behavior instead of silently approximating it.
- Add tests for parsing, pack/encode behavior, safety checks, and regressions.
- Label examples that compile but have not run on silicon.
- Use package-specific pin names and link the evidence behind a physical claim.

## Commit and review hygiene

Do not commit secrets, local flash backups, personally identifying serial
numbers, or unlicensed vendor packages. Avoid adding generated build output
unless it is a deliberate qualification fixture with a recorded hash and
purpose.

By contributing, you represent that you have the right to submit the material
under the repository's license and notices.
