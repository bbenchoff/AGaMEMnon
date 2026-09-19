"""Regenerate (or check) the registered physical device-graph profiles.

`agamemnon/engine/special_routes.py` binds every physical-I/O device graph
to an exact identity (row count + SHA-256 of `dev_pips.csv`).  The base graphs
and their shared-control and historical variants are pinned in that module.
Options that legitimately change the graph for ordinary builds -- today the
BRAM Port-B exit corridor and the board-witnessed BRAM site-read paths -- make
further profiles, keyed by admission, the shared-control marker and the exact
option set.  Those identities live in `physical_graph_profiles.json` beside
the module so that a graph change (a selector withdrawal, a corridor
correction) is one regeneration instead of a hand edit per profile.

Usage, from the repository root with the pinned tools installed:

    python qualification/regen_physical_graph_profiles.py          # rewrite
    python qualification/regen_physical_graph_profiles.py --check  # verify

`--check` exits non-zero and names every profile whose source-fresh graph no
longer matches the registered identity.  Regeneration is a reviewed change:
the JSON diff must be explained by the graph change that motivated it.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agamemnon.engine import special_routes as sr  # noqa: E402

CHIPDB = ROOT / "agamemnon" / "chipdb"
ENGINE = ROOT / "agamemnon" / "engine"


def emit(profile, out_dir):
    """Emit one profile from source into an empty directory; return its identity."""
    command = [
        sys.executable, str(ENGINE / "emit_uarch_db.py"),
        "--arch", str(ENGINE / "arch.py"),
        "--data", str(CHIPDB),
        "--out", str(out_dir),
    ]
    environ = list(sr.SOURCE_FRESH_PHYSICAL_ENV)
    if profile["shared_control"] == "1":
        environ.append(sr.SHARED_CONTROL_GRAPH_ENV + "=1")
    if profile["admission"] != "release-strict":
        environ.append("AGAMEMNON_ROUTING_ADMISSION=" + profile["admission"])
    environ.extend(profile["options"])
    for item in environ:
        command.extend(("--env", item))
    clean = {
        key: value for key, value in os.environ.items()
        if not key.startswith("AGAMEMNON_") and not key.startswith("AGRV2K_")
    }
    result = subprocess.run(
        command, cwd=ROOT, env=clean, capture_output=True, text=True, timeout=1800,
    )
    if result.returncode != 0:
        raise SystemExit("emit failed for %s:\n%s" % (
            sr.graph_profile_key(profile["shared_control"], profile["admission"],
                                 profile["options"]),
            (result.stdout + result.stderr)[-4000:]))
    raw = (Path(out_dir) / "dev_pips.csv").read_bytes()
    return raw.count(b"\n") - 1, hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify the registered identities without rewriting")
    parser.add_argument("--only", action="append", default=[], metavar="KEY",
                        help="restrict to profiles whose key contains KEY")
    args = parser.parse_args(argv)
    registry = sr.load_graph_profiles()
    drift = []
    with tempfile.TemporaryDirectory(prefix="agamemnon-graph-profiles-") as scratch:
        for index, profile in enumerate(registry["profiles"]):
            key = sr.graph_profile_key(
                profile["shared_control"], profile["admission"], profile["options"])
            if args.only and not any(needle in key for needle in args.only):
                continue
            count, digest = emit(profile, Path(scratch) / ("profile-%d" % index))
            registered = (profile["graph_pip_count"], profile["graph_pips_sha256"])
            status = "ok" if registered == (count, digest) else "DRIFT"
            print("%-5s %s  rows=%d sha=%s" % (status, key, count, digest[:16]))
            if registered != (count, digest):
                drift.append(key)
                profile["graph_pip_count"] = count
                profile["graph_pips_sha256"] = digest
    if args.check:
        if drift:
            print("%d profile(s) drifted; rerun without --check to regenerate" % len(drift))
            return 1
        print("all registered physical graph profiles match their source-fresh graphs")
        return 0
    sr.GRAPH_PROFILES_PATH.write_text(
        json.dumps(registry, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print("wrote %s (%d regenerated)" % (sr.GRAPH_PROFILES_PATH, len(drift)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
