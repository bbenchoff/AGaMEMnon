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
import itertools
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


WHY_OPTION = {
    "AGAMEMNON_BRAM_PORTB_EXIT":
        "live BRAM Port B (withholds the Port-B exit-corridor RMUX rows)",
    "AGAMEMNON_BRAM_SITE_READ_PATHS":
        "board-witnessed BRAM site-read paths (adds the recorded site-read hops; the CLI "
        "auto-enables this for any MCU-read ALTA_BRAM9K, so without this profile a strict build "
        "of such a design cannot be produced at all)",
    "AGAMEMNON_NO_OMUX_PRESENT0":
        "OMUX(3z) presentation disabled (removes the default OMUX[3z+2]->OMUX[3z+0] OMUXPRES pips "
        "at the silicon-witnessed slices of omux3z_presentation_evidence.csv)",
    "AGRV2K_SHARED_CONTROL_ASYNC_CLEAR":
        "async-clear reset admitted (adds the CtrlMUX->TileAsyncMUX01 pips + ASYNCCLR1 sink bels; "
        "the CLI auto-enables this for any ordinary --uarch build, so without this profile a "
        "strict build of an async-reset design cannot be produced at all)",
}


def why_for(shared_control, admission, options):
    """The human reason a derived profile exists; the registry test requires one."""
    enables = "native enables" if shared_control == "1" else "data-logic enables"
    reasons = []
    for item in options:
        name = item.split("=", 1)[0]
        reasons.append(WHY_OPTION.get(name, name))
    return "%s, %s, %s" % (admission, enables, " + ".join(reasons))


def complete(registry):
    """Add any (shared control x admission x option subset) combination the registry lacks.

    The registry used to be hand-maintained, which meant a combination nobody had
    happened to build was simply absent -- and an absent profile is not a permissive
    default, it is a hard refusal ("physical graph identity drift").  That is how
    release-strict lost every read-ported BRAM design: SITE_READ_PATHS is auto-enabled
    for any read-ported ALTA_BRAM9K, only its tiered profiles were registered, so the
    strict build of a BRAM design could not be produced at all and the design had to
    fall back to --tiered.  Deriving the set instead of listing it means a new
    admission or option cannot silently leave that hole behind.

    Registering a profile does not admit a single extra pip: it records the identity of
    the graph the emitter already produces for that option set, and under release-strict
    the emitter admits only witnessed rows.  The identities themselves still come from a
    source-fresh emit below.
    """
    have = {sr.graph_profile_key(p["shared_control"], p["admission"], p["options"])
            for p in registry["profiles"]}
    added = []
    for shared in ("0", "1"):
        for admission in ("release-strict", "tiered"):
            for size in range(1, len(sr.GRAPH_PROFILE_OPTIONS) + 1):
                for combo in itertools.combinations(sorted(sr.GRAPH_PROFILE_OPTIONS), size):
                    options = ["%s=1" % name for name in combo]
                    key = sr.graph_profile_key(shared, admission, options)
                    if key in have:
                        continue
                    registry["profiles"].append({
                        "shared_control": shared, "admission": admission,
                        "options": options, "graph_pip_count": 0, "graph_pips_sha256": "",
                        "why": why_for(shared, admission, options),
                    })
                    have.add(key)
                    added.append(key)
    return added


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify the registered identities without rewriting")
    parser.add_argument("--only", action="append", default=[], metavar="KEY",
                        help="restrict to profiles whose key contains KEY")
    args = parser.parse_args(argv)
    registry = sr.load_graph_profiles()
    for key in complete(registry):
        print("added  %s  (was unregistered, so refused)" % key)
    drift = []
    with tempfile.TemporaryDirectory(prefix="agamemnon-graph-profiles-") as scratch:
        for index, profile in enumerate(registry["profiles"]):
            key = sr.graph_profile_key(
                profile["shared_control"], profile["admission"], profile["options"])
            if args.only and not any(needle in key for needle in args.only):
                continue
            count, digest = emit(profile, Path(scratch) / ("profile-%d" % index))
            registered = (profile["graph_pip_count"], profile["graph_pips_sha256"])
            status = ("NEW" if not profile["graph_pips_sha256"]
                      else "ok" if registered == (count, digest) else "DRIFT")
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
