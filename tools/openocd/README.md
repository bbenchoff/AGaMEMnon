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

`release.py verify-source` proves the commit and both patch identities.
`release.py verify-environment` rejects compiler/package drift from the lock in
`manifest.json`.
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

The OS-Q binary is intentionally absent from every packaging path. It may be
supplied only to the hardware qualification script with `--oracle`.
