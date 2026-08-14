# Provenance and third-party notices

AGaMEMnon's source code is offered under the [MIT License](LICENSE). That
license applies to original project code and documentation for which the
project has the right to grant it. It does not relicense third-party tools,
vendor documents, or vendor-originated binary material.

This notice is a technical provenance record, not legal advice.

## Fabric database

Most files under `agamemnon/chipdb/` are derived databases recovered through
format analysis, routing observations, controlled experiments, and
silicon-backed qualification. Database files are stored as normal Git objects.
The methods and supported interpretation are documented in
`docs/ARCHITECTURE.md`, `docs/BITSTREAM_FORMAT.md`, `docs/STATUS.md`, and
`qualification/`.

`selector_conflict_atlas.agdb` is explicitly vendor-derived normalized data.
It reduces parsed vendor routing observations to physical edge keys and
selector-pair counts, preserves disagreements rather than asserting a correct
answer, and records the source hash in its metadata. The raw 1.7 GiB parsed
corpus, vendor routes/checkpoints, executables, manuals, and SDK are not
included. `research_knowledge_manifest.json` hashes the normalized public
database and states the non-release claim boundary. Neither artifact is
represented as independently derived or silicon-qualified.

Since 2026-08-14 emitted images no longer read
`agamemnon/chipdb/fabric_default.bin`: the design-neutral base is synthesized
from scratch (`agamemnon/engine/default_frame.py`) out of the project's
derived databases (including the decoded, vendor-derived DATA tables
`logictile_config_template.csv` and `border_edge_partial_cells.csv`), with no
byte copied from the canvas at build time; the synthesized base is byte-exact
to the decoded canvas across the preamble and body, carries a freshly
recomputed valid CRC, and is silicon-qualified
(`qualification/fabric_base_evidence.jsonl`). `fabric_default.bin` — a 2.8 KiB
compressed configuration originating from vendor-tool output — is still
shipped as a decode reference and differential anchor and is selectable via
`AGAMEMNON_BASELINE`. Note it is not directly loadable: its stored CRC is
stale and the configuration block rejects it.

The reviewed reference file is exactly 2,839 bytes with SHA-256
`6093e876041bab9f8d1f6058235713a6b8ced1024455070fe2b358e87915a041`.
The bundle builder rejects a wheel containing another copy. Its license is
recorded as `NOASSERTION`; inclusion here is a disclosed provenance decision,
not a claim that the vendor-originated bytes became MIT-licensed.

Accordingly:

- “no vendor executable in the build path” is accurate;
- “no byte is copied from the vendor canvas at build time” is now accurate for
  default builds;
- “contains no vendor-derived information” is **not** accurate: the base is
  synthesized from derived databases recovered from vendor artifacts, as
  disclosed above, and the byte values it reproduces originate in vendor-tool
  output;
- users with redistribution or product-compliance requirements should review
  this file and the databases' provenance before shipping generated images.

## External FPGA tools

Yosys, nextpnr, OSS CAD Suite, compilers, simulators, and their runtime
libraries retain their respective upstream licenses. AGaMEMnon does not claim
ownership of them. Release bundles must include the notices and source offers
required by each bundled component. Every assembled SDK also includes
`COMPONENTS.json`, a hash-bound top-level component/license inventory. Nested
components in OSS CAD Suite and the GNU toolchain retain the notices included
in those upstream distributions.

## OpenOCD

AG32 SWD/DAP support requires an OpenOCD build carrying AGM's
`target create riscv -dap` extension. Stock upstream and OSS CAD Suite builds
do not provide it.

AGaMEMnon builds its release from official OpenOCD parent
`a17c5f5a6dac6625cd5b01dfc3234f57cb58f1f3`, applies Gerrit change 9590
patchset 2, and applies the separately shipped nested-config repair. Every
binary archive carries the GPL text, patches, provenance, hashes, and SBOM and
is published beside the complete patched source archive.

macOS binary archives also carry the dynamically linked libusb and HIDAPI
runtime libraries, their license files, and their exact upstream source
archives. Those components retain their upstream licenses and are identified
in the release SBOM; AGaMEMnon's MIT license does not relicense them. The
bundled HIDAPI library is distributed under its offered BSD 3-Clause option;
libusb remains LGPL-2.1-or-later.

The prebuilt `os-q/tool-agrv_openocd` executable remains a comparison oracle.
It is never copied by the build, packaging, bundle, installer, or release
workflow.

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
