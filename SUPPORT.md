# Support

AGaMEMnon is a development preview with a deliberately narrow supported
hardware boundary. Start with:

```text
agamemnon --version
agamemnon doctor --no-hardware
```

When hardware is connected, run `agamemnon doctor`. UART target probing is
destructive to the current run state because it resets into ROM, so it occurs
only when `--uart-port PORT` is supplied.

## Supported reference target

- MCU/package: `AG32VF303CCT6`, LQFP-48
- Fabric target: `AGRV2KL48`
- Board definition: `agamemnon/sdk/boards/ag32vf303-l48.toml`
- Qualified probe path: AGM-compatible CMSIS-DAP and AGaMEMnon OpenOCD
  installed with `agamemnon install-openocd`

Other AG32 boards and packages are useful research targets, not implied
drop-in replacements.

## Where to look

| Problem | Read first |
|---|---|
| “What is this chip?” | [AG32 overview](docs/AG32_OVERVIEW.md) |
| Python or tool not found | [Installation](docs/INSTALLATION.md) |
| Build or command syntax | [Usage](docs/USAGE.md) |
| Project manifest problem | [Projects](docs/PROJECTS.md) |
| DAP, USB, UART, flash, or recovery | [Programming](docs/PROGRAMMING.md) |
| Unsupported route or primitive | [Support matrix](docs/STATUS.md) |
| Pin or silicon claim | [Hardware qualification](docs/HARDWARE_VALIDATION.md) |
| Known-good board, probe, or transport | [Known-good hardware](docs/KNOWN_GOOD_HARDWARE.md) |
| Provenance or redistribution | [Notices](NOTICE.md) |

## Before filing an issue

Collect:

```sh
agamemnon --version
agamemnon doctor --json --no-hardware
git rev-parse HEAD
git status --short
```

For a hardware report, also provide:

- exact chip marking, package, and board revision;
- host operating system;
- transport, probe, and wiring;
- full command with secrets and personal paths removed;
- complete error output;
- whether the operation was read-only, volatile, or persistent;
- whether a full flash backup exists;
- whether the board still responds over DAP or mask-ROM UART.

Do not attach a factory flash dump publicly unless you have reviewed it for
unique data and redistribution concerns.

## Programming safety

Prefer `sram` for first experiments. Before a persistent write:

1. Read [Programming](docs/PROGRAMMING.md).
2. Back up the complete flash.
3. Preserve the factory decompressor and configuration pointer.
4. Verify every changed byte by readback.
5. Confirm a recovery transport before changing boot-sensitive state.

The flash-resident USB uploader is convenient but is not a recovery path when
main flash is corrupt. Stock upstream OpenOCD cannot replace AGaMEMnon's
qualified OpenOCD for SWD/DAP operations. Run
`agamemnon doctor --probe-dap` before relying on DAP for recovery.

## Asking for help

Use a GitHub issue for reproducible bugs, documentation gaps, and hardware
qualification reports. Use GitHub Discussions for design questions once
Discussions are enabled. Security issues follow [SECURITY.md](SECURITY.md),
not the public issue tracker.
