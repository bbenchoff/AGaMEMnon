"""Fail-closed gates for the four exact registered-source TMUX09 BRAM images.

This is deliberately a retained-checkpoint surface.  None of these tests turns
the measured codewords into general architecture routing or claims that an
ordinary source-to-route build can reproduce the composition.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agamemnon import cli
from agamemnon.engine.features.bram import _tmux9_profile_signature


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
PACKAGED = ROOT / "agamemnon" / "sdk" / "qualified_bram_tmux9"
PROFILES = tuple(
    name for name, row in cli.QUALIFIED_ROUTE_PROFILES.items()
    if row.get("pack_only")
)


def _clean_env():
    return {
        name: value for name, value in os.environ.items()
        if not name.startswith("AGAMEMNON_")
    }


def _checkpoint(profile):
    return PACKAGED / cli.QUALIFIED_ROUTE_PROFILES[profile]["checkpoint"]


@pytest.mark.parametrize("profile", PROFILES)
def test_all_four_exact_profiles_reproduce_raw_and_compressed_hashes(profile, tmp_path):
    expected = cli.QUALIFIED_ROUTE_PROFILES[profile]
    output = tmp_path / (profile + ".bin")
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", str(_checkpoint(profile)),
         str(output), "--qualified-checkpoint", profile],
        cwd=ROOT, env=_clean_env(), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert hashlib.sha256(output.read_bytes()).hexdigest() == expected["bitstream_sha256"]
    assert hashlib.sha256(Path(str(output) + ".comp").read_bytes()).hexdigest() == \
        expected["compressed_sha256"]
    assert "0 unmapped" in result.stdout
    assert "exact raw/compressed hashes verified" in result.stdout


def test_output_hash_mismatch_deletes_both_artifacts(monkeypatch, tmp_path):
    profile = PROFILES[0]
    output = tmp_path / "wrong.bin"
    for name in tuple(os.environ):
        if name.startswith("AGAMEMNON_"):
            monkeypatch.delenv(name, raising=False)

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"wrong raw")
        Path(command[-1] + ".comp").write_bytes(b"wrong compressed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli, "_run_child", fake_run)
    with pytest.raises(SystemExit) as error:
        cli.cmd_pack(SimpleNamespace(
            input=str(_checkpoint(profile)), output=str(output), baseline=None,
            research_unsafe=False, qualified_checkpoint=profile,
        ))
    assert error.value.code == 1
    assert not output.exists()
    assert not Path(str(output) + ".comp").exists()


def test_ambient_option_wrong_path_and_alias_are_rejected(monkeypatch, tmp_path):
    profile = PROFILES[0]
    args = SimpleNamespace(qualified_checkpoint=profile, input=str(_checkpoint(profile)))
    monkeypatch.setenv("AGAMEMNON_ALLOW_UNMAPPED", "1")
    with pytest.raises(ValueError, match="ambient option"):
        cli._qualified_pack_profile(args)
    monkeypatch.delenv("AGAMEMNON_ALLOW_UNMAPPED")

    alias = tmp_path / "alias.json"
    shutil.copyfile(_checkpoint(profile), alias)
    args.input = str(alias)
    with pytest.raises(ValueError, match="requires packaged checkpoint"):
        cli._qualified_pack_profile(args)

    other = PROFILES[1]
    args.qualified_checkpoint = other
    args.input = str(_checkpoint(profile))
    with pytest.raises(ValueError, match="requires packaged checkpoint"):
        cli._qualified_pack_profile(args)


def test_packaged_source_or_checkpoint_hash_drift_is_rejected(monkeypatch, tmp_path):
    profile = PROFILES[0]
    record = cli.QUALIFIED_ROUTE_PROFILES[profile]
    source = tmp_path / record["source"]
    checkpoint = tmp_path / record["checkpoint"]
    shutil.copyfile(PACKAGED / record["source"], source)
    shutil.copyfile(PACKAGED / record["checkpoint"], checkpoint)
    source.write_bytes(source.read_bytes() + b"\n// mutation\n")
    monkeypatch.setattr(cli, "_qualified_profile_root", lambda _profile: str(tmp_path))
    with pytest.raises(ValueError, match="source hash drifted"):
        cli._qualified_pack_profile(SimpleNamespace(
            qualified_checkpoint=profile, input=str(checkpoint),
        ))
    shutil.copyfile(PACKAGED / record["source"], source)
    checkpoint.write_bytes(checkpoint.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checkpoint hash drifted"):
        cli._qualified_pack_profile(SimpleNamespace(
            qualified_checkpoint=profile, input=str(checkpoint),
        ))


def test_semantic_mutation_and_cross_profile_signature_fail_closed():
    profile = PROFILES[0]
    module = json.loads(_checkpoint(profile).read_text(encoding="utf-8"))["modules"]["top"]
    assert _tmux9_profile_signature(module, profile)
    assert not _tmux9_profile_signature(module, PROFILES[1])
    module["cells"]["source_stage"]["parameters"]["INIT"] = "0"
    assert not _tmux9_profile_signature(module, profile)


def test_ordinary_pack_cannot_use_scoped_codewords(tmp_path):
    profile = "bram-tmux9-i0-d1-we1"
    output = tmp_path / "ordinary.bin"
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack",
         str(_checkpoint(profile)), str(output)],
        cwd=ROOT, env=_clean_env(), capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "1 unmapped" in result.stdout + result.stderr
    assert "loaded 1 exact BRAM route codeword" in result.stdout
    assert not output.exists()
    assert not Path(str(output) + ".comp").exists()


def test_build_rejects_pack_only_profile_before_synthesis():
    profile = PROFILES[0]
    with pytest.raises(ValueError, match="pack-only"):
        cli._qualified_route_profile(
            SimpleNamespace(qualified_checkpoint=profile), [], cli.ENGINE,
            cli.CHIPDB, {}, 10,
        )


@pytest.mark.parametrize(
    "profile", ("mcu-ahb-bank16-read-word0", "mcu-ahb-bank16-public-scratch4")
)
def test_older_build_replay_profiles_still_resolve_from_checkout(
        profile, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("AGAMEMNON_"):
            monkeypatch.delenv(name, raising=False)
    record = cli.QUALIFIED_ROUTE_PROFILES[profile]
    source = Path(cli.QUALIFICATION) / record["source"]
    args = SimpleNamespace(
        qualified_checkpoint=profile, leds=False, mcu=False, true_topo=False,
        no_intra_rmux=False, pin=None, pin_hook=None, baseline=None, pcf=None,
        hard_carry=False,
    )
    resolved = cli._qualified_route_profile(
        args, [str(source)], cli.ENGINE, cli.CHIPDB,
        {"AGAMEMNON_HSE": "8"}, 10,
    )
    assert resolved["checkpoint_path"] == str(
        Path(cli.QUALIFICATION) / record["checkpoint"]
    )


def test_high_profile_replaces_whole_kmux03_field_including_sel35(tmp_path):
    profile = "bram-tmux9-i0-d1-we1"
    output = tmp_path / "high.bin"
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", str(_checkpoint(profile)),
         str(output), "--qualified-checkpoint", profile],
        cwd=ROOT, env=_clean_env(), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    raw = output.read_bytes()[8:]
    with (CHIPDB / "bram_cell.csv").open(newline="", encoding="utf-8") as stream:
        cells = {
            int(row["sel"]): (int(row["byte"]), int(row["mask"]))
            for row in csv.DictReader(stream)
            if row["mux"] == "CFG_KMUX" and
            (int(row["x"]), int(row["y"])) == (13, 4)
        }
    assert all(raw[cells[sel][0]] & cells[sel][1] for sel in (30, 33))
    assert all(not (raw[cells[sel][0]] & cells[sel][1])
               for sel in (29, 34, 35, 40, 43))


def test_tmux13_serv_footprint_remains_unchanged_and_unpromoted():
    with (CHIPDB / "bram_serv_write_paths.csv").open(
            newline="", encoding="utf-8") as stream:
        wea = [row for row in csv.DictReader(stream) if row["port"] == "WeA"]
    assert [(row["src_wire"], row["dst_wire"]) for row in wea[-2:]] == [
        ("X16Y4_RMUX20", "X13Y4_TMUX13"),
        ("X13Y4_TMUX13", "X13Y4_KMUX03"),
    ]
    with (CHIPDB / "bram_route_codewords.csv").open(
            newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert not any(row["dst_family"] == "TMUX" and
                   int(row["dst_index"]) == 13 for row in rows)
    scoped = [row for row in rows if row.get("qualified_profiles")]
    assert {int(row["dst_index"]) for row in scoped} == {3, 9}


def test_checked_in_paired_semantic_diff_audit_is_exhaustive():
    report = json.loads((
        ROOT / "qualification" / "registered_bram_tmux9_pack_audit.json"
    ).read_text(encoding="utf-8"))
    assert report["ordinary_build_claim"] is False
    assert report["ordinary_routing_claim"] is False
    assert set(report["profiles"]) == set(PROFILES)
    assert all(pair["unattributed_bits"] == 0
               for pair in report["paired_semantic_diffs"])
    assert all(pair["changed_bits"] ==
               pair["named_feature_bits"] + pair["relocated_lut_bits"]
               for pair in report["paired_semantic_diffs"])
    for profile, row in report["profiles"].items():
        assert row["bitstream_sha256"] == \
            cli.QUALIFIED_ROUTE_PROFILES[profile]["bitstream_sha256"]
        if profile.endswith("we1"):
            assert row["kmux03_field"] == {
                "29": False, "30": True, "33": True, "34": False,
                "35": False, "40": False, "43": False,
            }
