"""Retain nextpnr timing evidence independently of temporary build cleanup."""
from pathlib import Path
import hashlib
import json
import tempfile


class TimingReports:
    def __init__(self, output):
        output = Path(output).absolute()
        # Unique directories preserve repeated builds and recursive carry
        # fallback. No old report can be mistaken for this invocation's data.
        self.directory = Path(tempfile.mkdtemp(
            prefix=output.name + ".timing-", dir=output.parent))
        self.manifest = {"schema_version": 1, "output": str(output),
                         "qualification": False,
                         "constraint_coverage": "not_established",
                         "attempts": []}
        self._save()

    def _save(self):
        path = self.directory / "manifest.json"
        pending = path.with_suffix(".tmp")
        pending.write_text(json.dumps(self.manifest, indent=2) + "\n",
                           encoding="utf-8")
        pending.replace(path)

    def begin(self, source, metadata):
        number = len(self.manifest["attempts"]) + 1
        stem = "attempt_%03d" % number
        payload = Path(source).read_bytes()
        (self.directory / (stem + ".input.json")).write_bytes(payload)
        report = self.directory / (stem + ".timing.json")
        self.manifest["attempts"].append({
            **metadata, "number": number, "status": "running",
            "input": stem + ".input.json",
            "input_sha256": hashlib.sha256(payload).hexdigest(),
            "report": report.name, "log": stem + ".log"})
        self._save()
        return str(report)

    def finish(self, returncode, outcome, log):
        row = self.manifest["attempts"][-1]
        row.update(status="finished", returncode=returncode, outcome=outcome)
        payload = log.encode("utf-8")
        (self.directory / row["log"]).write_bytes(payload)
        row["log_sha256"] = hashlib.sha256(payload).hexdigest()
        path = self.directory / row["report"]
        if not path.exists():
            row["report_status"] = "missing"
        else:
            payload = path.read_bytes()
            row["report_sha256"] = hashlib.sha256(payload).hexdigest()
            try:
                report = json.loads(payload)
            except (ValueError, UnicodeError):
                row["report_status"] = "malformed"
            else:
                expected = {"fmax": dict, "critical_paths": list,
                            "detailed_net_timings": list}
                if not isinstance(report, dict) or any(
                        not isinstance(report.get(key), kind)
                        for key, kind in expected.items()):
                    row["report_status"] = "incomplete"
                else:
                    row["report_status"] = "available"
                    row["clock_fmax_count"] = len(report["fmax"])
                    row["critical_path_count"] = len(report["critical_paths"])
                    row["detailed_net_count"] = len(report["detailed_net_timings"])
        self._save()
