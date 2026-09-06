# Build timing reports

The ordinary native build ladder requests nextpnr's JSON report and detailed
net timings for every placement/routing attempt. The CLI prints the retained
directory beside the requested image, for example `image.bin.timing-abc123/`.
Reports survive temporary build cleanup, failed attempts, repeated invocations,
and the recursive hard-carry fallback. Checkpoint replay does not execute this
ladder and does not generate a new timing analysis.

Each directory contains `manifest.json`, exact synthesized attempt inputs,
logs, and any raw timing reports nextpnr produced. The manifest records the
seed, placement mode, fanout limit, requested frequency, exit code, build
outcome, file hashes, and report availability. A running record is written
before launching nextpnr; if the process is interrupted it remains running,
not a successful or completed analysis. Missing, malformed, and incomplete
reports are recorded separately from available reports.

An available report is not proof of timing closure. The manifest explicitly
sets `qualification: false` and `constraint_coverage: not_established`.
Clock Fmax and path/net counts describe the supplied model. They do not prove
that external MCU launch/capture constraints, all hard-block delays, clock skew,
hold, or process/voltage/temperature corners have been modeled or qualified.
An empty Fmax map remains visible as zero analyzed clock Fmax entries.

Reports are diagnostic artifacts and do not change the existing routing,
frequency acceptance, bitstream admission, or silicon qualification gates.
