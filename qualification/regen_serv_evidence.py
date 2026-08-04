#!/usr/bin/env python3
"""Refresh the SERV compliance evidence record from the on-disk artifacts.

Why this exists
---------------
``serv_compliance_evidence.jsonl`` records sha256 hashes of the SERV sources,
the routed nextpnr JSONs, and the packed bitstreams, plus the strict-bitgen pip
metrics and the exact environment needed to replay the qualified pack. Text
hashes use canonical LF bytes so checkout newline policy cannot change them.
A re-routed artifact can otherwise silently diverge from its recorded hash (and
``test_serv_rv32i_signature_sources_match_recorded_evidence`` then fails).
Worse, a routed JSON can be shipped that no longer packs strict-clean at all.

This tool regenerates the *derivable* fields of the record from the actual
files, and — crucially — **re-packs each routed JSON through strict AGaMEMnon
bitgen and refuses to bless an artifact that does not pack clean**
(``unmapped != 0``, or any predicted/legacy selector).  It never invents
silicon results: ``rtl.*``, ``hardware.*``, ``estimate_mhz``, ``verdict``,
``meaning`` and the prose fields are left exactly as they are — refresh them by
hand from your requalification run.

Typical requalification flow
----------------------------
    # 1. select and record the qualified pack_environment, then rebuild
    #    the routed artifacts with those same settings (your toolchain + board)
    agamemnon build qualification/serv_rv32i_smoke.v     ... -> serv_rv32i_smoke_L48_routed.json
    agamemnon build qualification/serv_rv32i_heartbeat.v ... -> serv_rv32i_heartbeat_L48_routed.json
    # 2. update the silicon/prose fields in the record by hand from your run
    # 3. sync every hash + bitstream + pip metric, gated on a strict clean pack:
    python qualification/regen_serv_evidence.py --write

If a later qualified selector table changes only the reproducible packing
classification of the retained artifacts, preserve the original record and
append a replay record instead::

    python qualification/regen_serv_evidence.py \
        --trial-suffix signature-and-jal-heartbeat --write \
        --append-trial-id 2026-08-03-serv-selector-replay-20260803

Dry-run (default) prints what would change and exits non-zero if anything is
stale or any routed artifact fails the strict-clean pack gate — so it doubles as
a CI check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EVIDENCE = os.path.join(HERE, "serv_compliance_evidence.jsonl")
# Track the newest append-only replay record. Keep this suffix specific: the
# historical local-int replay intentionally remains in the same ledger.
DEFAULT_TRIAL_SUFFIX = "haddr5-selector-replay-20260803"
TEXT_HASH_MODE = "sha256-lf-v1"

# A qualification record is data, not permission to inject arbitrary process
# settings into CI. These are the only bitgen inputs this replay currently needs
# and understands. In particular, AGAMEMNON_ALLOW_UNMAPPED is intentionally not
# accepted: qualification must always use strict routing.
QUALIFIED_PACK_ENV_KEYS = {
    "AGAMEMNON_HSE",
    "AGAMEMNON_LEFT_PAD_OUT",
    "AGAMEMNON_SYSCLK",
}

# Direct-D presentation was unconditional when the retained SERV images were
# qualified.  It is now activated on demand for new builds, but historical
# replay must preserve the graph/emission policy that produced those images.
# This is a compatibility constant, not an ambient or record-controlled knob.
LEGACY_REPLAY_ENV = {"AGAMEMNON_DIRECT_D": "1"}

# record field -> repo-relative source file (mirrors the assertions in
# tests/test_large_flow_helpers.py::test_serv_rv32i_signature_sources_match_recorded_evidence)
FILE_HASH_FIELDS = {
    "source_sha256": "qualification/serv_rv32i_smoke.v",
    "assembly_sha256": "qualification/serv_rv32i_smoke.S",
    "signature_testbench_sha256": "qualification/tb_serv_rv32i_smoke.v",
    "heartbeat_wrapper_sha256": "qualification/serv_rv32i_heartbeat.v",
    "heartbeat_testbench_sha256": "qualification/tb_serv_rv32i_heartbeat.v",
    "pcf_sha256": "qualification/serv_rv32i_smoke_L48.pcf",
}
# build sub-record -> its routed nextpnr JSON
ROUTED = {
    "signature_build": "qualification/serv_rv32i_smoke_L48_routed.json",
    "heartbeat_build": "qualification/serv_rv32i_heartbeat_L48_routed.json",
}

# "data pips: 4293 total, 4292 mapped (0 groups exact, 4024 block-clean,
#  82 relative-clean, 0 legacy-abs, 0 predicted), 1 unmapped -> 8445 bits"
_PIP_RE = re.compile(
    r"data pips:\s*(?P<total>\d+)\s*total.*?"
    r"(?P<block>\d+)\s*block-clean,\s*"
    r"(?P<rel>\d+)\s*relative-clean,\s*"
    r"(?P<legacy>\d+)\s*legacy-abs,\s*"
    r"(?P<predicted>\d+)\s*predicted\).*?"
    r"(?P<unmapped>\d+)\s*unmapped",
    re.DOTALL,
)


def sha256_binary_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text_file(path):
    """Hash text using repository-canonical LF bytes on every host."""
    with open(path, "rb") as f:
        data = f.read()
    canonical = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def qualified_pack_environment(record):
    if record.get("artifact_hash_mode") != TEXT_HASH_MODE:
        raise RuntimeError(
            "unsupported or missing artifact_hash_mode %r (expected %r)"
            % (record.get("artifact_hash_mode"), TEXT_HASH_MODE)
        )
    configured = record.get("pack_environment")
    if not isinstance(configured, dict) or not configured:
        raise RuntimeError("missing qualified pack_environment")
    missing = sorted(QUALIFIED_PACK_ENV_KEYS - set(configured))
    unknown = sorted(set(configured) - QUALIFIED_PACK_ENV_KEYS)
    if missing:
        raise RuntimeError("missing qualified pack setting(s): %s" % ", ".join(missing))
    if unknown:
        raise RuntimeError("unsupported qualified pack setting(s): %s" % ", ".join(unknown))
    invalid = sorted(k for k, v in configured.items() if not isinstance(v, str) or not v)
    if invalid:
        raise RuntimeError("qualified pack setting(s) must be non-empty strings: %s"
                           % ", ".join(invalid))
    return dict(configured)


def strict_pack(routed_abs, out_bin, pack_environment):
    """Pack a routed JSON through strict bitgen (no archival ALLOW_UNMAPPED).

    Returns (bitstream_sha256, metrics dict). Raises RuntimeError if the pack
    fails or is not strict-clean — this is the gate that stops a non-conducting
    or unmapped artifact from being recorded as qualified.
    """
    # Do not let a developer shell silently alter a qualification replay. Drop
    # every ambient AGaMEMnon switch, then apply only the reviewed record.
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGAMEMNON_")}
    env.update(pack_environment)
    env.update(LEGACY_REPLAY_ENV)
    proc = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", routed_abs, out_bin],
        cwd=REPO, env=env, capture_output=True, text=True,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    m = _PIP_RE.search(log)
    if not m:
        raise RuntimeError("could not parse pip metrics from pack output:\n" + log[-2000:])
    metrics = {
        "data_pips": int(m["total"]),
        "physical_clean": int(m["block"]),
        "relative_unanimous": int(m["rel"]),
        "predicted": int(m["predicted"]),
        "legacy": int(m["legacy"]),
        "unmapped": int(m["unmapped"]),
    }
    dirty = {k: metrics[k] for k in ("unmapped", "predicted", "legacy") if metrics[k]}
    if proc.returncode != 0 or dirty:
        raise RuntimeError(
            "strict pack of %s is NOT clean (%s); refusing to record it as "
            "qualified. Re-route until it packs with 0 unmapped/predicted/legacy.\n%s"
            % (os.path.relpath(routed_abs, REPO), dirty or "pack failed", log[-1500:])
        )
    return sha256_binary_file(out_bin), metrics


def refresh(record, tmpdir):
    """Return (updated_record, list_of_changes). Pure w.r.t. the record dict copy."""
    rec = json.loads(json.dumps(record))   # deep copy
    changes = []

    def set_field(container, key, new, label):
        old = container.get(key)
        if old != new:
            changes.append((label, old, new))
            container[key] = new

    pack_environment = qualified_pack_environment(rec)

    for field, rel in FILE_HASH_FIELDS.items():
        set_field(rec, field, sha256_text_file(os.path.join(REPO, rel)), field)

    for build_key, rel in ROUTED.items():
        routed_abs = os.path.join(REPO, rel)
        sub = rec.setdefault(build_key, {})
        set_field(sub, "routed_sha256", sha256_text_file(routed_abs),
                  build_key + ".routed_sha256")
        out_bin = os.path.join(tmpdir, build_key + ".bin")
        bit_sha, metrics = strict_pack(routed_abs, out_bin, pack_environment)
        set_field(sub, "bitstream_sha256", bit_sha, build_key + ".bitstream_sha256")
        for k, v in metrics.items():
            set_field(sub, k, v, build_key + "." + k)
    return rec, changes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence", default=EVIDENCE, help="path to the evidence jsonl")
    ap.add_argument("--trial-suffix", default=DEFAULT_TRIAL_SUFFIX,
                    help="match the record whose trial_id ends with this")
    ap.add_argument("--write", action="store_true",
                    help="rewrite the record in place (default: dry-run / CI check)")
    ap.add_argument(
        "--append-trial-id",
        help=("with --write, append a superseding artifact-replay record under "
              "this new trial_id instead of rewriting qualified history"),
    )
    a = ap.parse_args(argv)

    if a.append_trial_id and not a.write:
        ap.error("--append-trial-id requires --write")

    lines = [json.loads(l) for l in open(a.evidence)]
    idx = [i for i, r in enumerate(lines) if str(r.get("trial_id", "")).endswith(a.trial_suffix)]
    if len(idx) != 1:
        print("error: expected exactly one record ending in %r, found %d"
              % (a.trial_suffix, len(idx)))
        return 2
    i = idx[0]

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        try:
            updated, changes = refresh(lines[i], tmp)
        except RuntimeError as exc:
            print("REFUSED: %s" % exc)
            return 1

    if not changes:
        print("up to date: every derivable field already matches the artifacts.")
        return 0

    print("%d field(s) %s:" % (len(changes), "updated" if a.write else "stale (dry-run)"))
    for label, old, new in changes:
        print("  %-34s %s -> %s" % (label, str(old)[:12] if old else "(none)", str(new)[:12]))

    if not a.write:
        print("\nrun with --write to apply. NOTE: refresh rtl.*/hardware.*/estimate_mhz/"
              "verdict by hand from your requalification run first.")
        return 1

    if a.append_trial_id:
        if any(r.get("trial_id") == a.append_trial_id for r in lines):
            print("error: trial_id %r already exists" % a.append_trial_id)
            return 2
        updated["supersedes"] = lines[i]["trial_id"]
        updated["trial_id"] = a.append_trial_id
        updated["replay_scope"] = (
            "Derivable artifact replay after independently qualified selector "
            "tables changed packing classification; silicon fields are inherited "
            "unchanged from the superseded record and no new hardware claim is made."
        )
        with open(a.evidence, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(updated) + "\n")
        print("\nappended superseding replay to %s" % a.evidence)
    else:
        lines[i] = updated
        with open(a.evidence, "w", encoding="utf-8", newline="\n") as f:
            for r in lines:
                f.write(json.dumps(r) + "\n")
        print("\nwrote %s" % a.evidence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
