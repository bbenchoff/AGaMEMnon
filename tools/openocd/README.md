# AGaMEMnon OpenOCD release

AG32 places its RISC-V Debug Module behind AP0 of an ARM ADIv5 DAP. Stock
OpenOCD does not currently expose that arrangement to the RISC-V target.
AGaMEMnon therefore builds a narrowly patched OpenOCD from official sources.

The immutable inputs are in `manifest.json`. Patch 1 is Gerrit change 9590,
patchset 2, unchanged. Patch 2 repairs its nested-config lookup; without it the
current patchset enters a JTAG scan on an SWD transport and asserts during
target examination.

Primary sources:

- [OpenOCD Gerrit change 9590](https://review.openocd.org/c/openocd/+/9590)
- [OpenOCD official Git/Gerrit repository](https://review.openocd.org/admin/repos/openocd)
- [GNU GPL version 2, source-distribution terms](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html#section3)

Build and package commands:

```sh
python tools/openocd/release.py prepare --source build/openocd-source
tools/openocd/build.sh linux build/openocd-source build/openocd-linux
python tools/openocd/release.py package --platform linux-x64 \
  --source build/openocd-source --prefix build/openocd-linux --output dist
```

On Windows, run the equivalent build in an MSYS2 UCRT64 shell:

```sh
tools/openocd/build.sh windows build/openocd-source build/openocd-windows
python tools/openocd/release.py package --platform windows-x64 \
  --source build/openocd-source --prefix build/openocd-windows --output dist
```

On macOS (Apple Silicon), build against Homebrew:

```sh
brew install bash autoconf automake libtool pkg-config hidapi libusb texinfo

# libjaylink's canonical host (gitlab.zapb.de) is frequently unreachable. The
# OpenOCD Gerrit mirror carries the identical pinned commit (0d23921a = tag
# 0.3.1); redirect the fetch to it. This is a fetch-time rewrite only, so the
# checked-out submodule commit -- and verify-source -- are byte-identical.
git config --global \
  url."https://review.openocd.org/libjaylink".insteadOf \
  https://gitlab.zapb.de/libjaylink/libjaylink.git

python3 tools/openocd/release.py prepare --source build/openocd-source
export PATH="$(brew --prefix libtool)/libexec/gnubin:$PATH"   # GNU libtoolize
tools/openocd/build.sh macos build/openocd-source build/openocd-macos
python3 tools/openocd/release.py package --platform macos-arm64 \
  --source build/openocd-source --prefix build/openocd-macos --output dist
```

`build.sh` reads its flags without `mapfile`, so it runs under the macOS system
bash (3.2) as well as Homebrew bash. macOS uses CMSIS-DAP over HIDAPI, so the
`hidapi` formula is required.

`release.py verify-source` proves the commit and both patch identities.
`release.py verify-environment` rejects compiler/package drift from the lock in
`manifest.json`. The macOS environment is checked through Homebrew, and because
Homebrew has no pinnable snapshot a rolled version only warns; a missing package
still fails.
`release.py package` creates normalized archives, SHA-256 manifests, a GPL
copy, provenance, and an SPDX 2.3 SBOM. The source archive is the complete
patched tree including the pinned JimTcl and libjaylink submodules.

Run the silicon gate only with a recoverable bench setup:

```sh
python tools/openocd/qualify_ag32.py \
  --openocd build/openocd-prefix/bin/openocd \
  --scripts build/openocd-prefix/share/openocd/scripts \
  --firmware build/sram_signature.bin \
  --output docs/evidence/openocd.json \
  --destructive-flash-test
```

The destructive gate saves all flash, writes and verifies one complete sector,
restores it in a `finally` block, and requires the final whole-device SHA-256
to match the initial backup.

`--firmware` is optional: omit it to skip the firmware-run check (building the
firmware needs `riscv64-unknown-elf-gcc`). Omit `--destructive-flash-test` for a
read-only run that still proves the `-dap` parser, the DEVICE_ID and `misa`
reads, SRAM read/write/restore, a full flash backup, and DAP reset recovery. The
macOS arm64 build was qualified that way on the L48 bench:
[`docs/evidence/openocd-macos-ag32.json`](../../docs/evidence/openocd-macos-ag32.json).

The OS-Q binary is intentionally absent from every packaging path. It may be
supplied only to the hardware qualification script with `--oracle`.
