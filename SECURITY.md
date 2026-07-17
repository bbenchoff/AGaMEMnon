# Security policy

AGaMEMnon controls device reset, SRAM execution, and persistent flash writes.
Treat bugs that can bypass address, backup, erase, verification, transport, or
bundle-provenance safeguards as security-sensitive.

## Reporting

Do not open a public issue for a vulnerability.

Use GitHub's private vulnerability-reporting flow from the repository
**Security** tab when it is enabled. If that flow is unavailable, contact the
maintainer through the private contact method listed on the repository owner's
GitHub profile and include “AGaMEMnon security” in the subject.

Include:

- affected commit or version;
- operating system and transport;
- impact and required preconditions;
- minimal reproduction;
- whether hardware, flash contents, or host files can be damaged or exposed;
- a proposed fix, if available.

Do not include third-party secrets, unique factory dumps, or exploit details
in an initially public channel.

## Supported versions

Until the first tagged release, only the current `main` branch receives
security fixes. This policy will be replaced with a version table when stable
release branches exist.

## Scope

Relevant reports include:

- writes outside the explicitly requested flash region;
- missing or bypassable backup/readback safeguards;
- unsafe boot-pin or reset behavior;
- command injection through paths, manifests, serial devices, or tool output;
- malicious project files escaping the intended working tree;
- bundle substitution, checksum failure, or mismatched tool provenance;
- redistribution of a binary without required corresponding source;
- crashes that leave the target in an unrecoverable or misleading state.

Ordinary unsupported RTL, incomplete device coverage, and documented hardware
limitations belong in the normal issue tracker unless they cross one of these
boundaries.
