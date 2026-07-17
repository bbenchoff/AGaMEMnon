# Provenance and third-party notices

AGaMEMnon's source code is offered under the [MIT License](LICENSE). That
license applies to original project code and documentation for which the
project has the right to grant it. It does not relicense third-party tools,
vendor documents, or vendor-originated binary material.

This notice is a technical provenance record, not legal advice.

## Fabric database

Most files under `agamemnon/chipdb/` are derived databases recovered through
format analysis, routing observations, controlled experiments, and
silicon-backed qualification. Large database files are stored with Git LFS.
The methods and supported interpretation are documented in
`docs/ARCHITECTURE.md`, `docs/BITSTREAM_FORMAT.md`, `docs/STATUS.md`, and
`qualification/`.

Emitted images use `agamemnon/chipdb/fabric_default.bin`, a 2.8 KiB compressed
configuration originating from vendor-tool output. AGaMEMnon overlays
open-generated logic and routing and clears residual slice state, while this
baseline supplies a design-invariant global preamble including default clock
and IO configuration.

Accordingly:

- “no vendor executable in the build path” is accurate;
- “generated entirely without vendor-originated configuration bytes” is not;
- a fully open, from-scratch replacement for the preamble remains future work;
- users with redistribution or product-compliance requirements should review
  this file and the baseline's provenance before shipping generated images.

## External FPGA tools

Yosys, nextpnr, OSS CAD Suite, compilers, simulators, and their runtime
libraries retain their respective upstream licenses. AGaMEMnon does not claim
ownership of them. Release bundles must include the notices and source offers
required by each bundled component.

## OpenOCD

AG32 SWD/DAP support requires an OpenOCD build carrying AGM's
`target create riscv -dap` extension. Stock upstream and OSS CAD Suite builds
do not provide it.

The known prebuilt `os-q/tool-agrv_openocd` package identifies as GPLv2 but
does not include the corresponding patched source tree. AGaMEMnon therefore
does not redistribute that binary. The bundle builder accepts either:

- no OpenOCD, producing a build-only SDK; or
- a compatible OpenOCD tree paired with the exact corresponding GPL source,
  which is audited and copied into the bundle.

## AGM SDK and USB framework

The pinned `os-q/framework-agrv_sdk` tree does not contain a top-level license
file at the commit recorded in `tools/bundle/manifest.json`. AGaMEMnon does not
copy or redistribute that framework. The optional PlatformIO/USB examples
point users at pinned external repositories so they can evaluate those terms
themselves.

## Vendor documentation

AGM manuals, data sheets, product pages, and tool downloads are linked as
primary sources. They are not covered by AGaMEMnon's MIT license merely
because a project document links to them.

## Contributions

Contributors must identify imported code, generated data, captured vendor
output, or third-party artifacts in their pull request. Do not add a binary,
manual, SDK file, or copied implementation unless its provenance and
redistribution terms are explicit.
