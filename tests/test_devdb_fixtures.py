"""Fixture custody and refusal checks; real graphs are exercised by consumers."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from devdb_fixtures import DatabaseFixtures


@pytest.fixture
def databases():
    value = DatabaseFixtures()
    yield value
    value.close()


def test_explicit_database_override_is_never_generated_or_replaced(databases, monkeypatch, tmp_path):
    external = tmp_path / "caller-owned-missing-database"
    monkeypatch.setenv("AGAMEMNON_UARCH_DEVDB", str(external))
    assert databases.path("strict", override="AGAMEMNON_UARCH_DEVDB") == external
    databases.prepare()
    assert not external.exists()
    assert not databases.requested


def test_owned_profiles_are_isolated_reused_and_environment_clean(databases, monkeypatch):
    other = DatabaseFixtures()
    monkeypatch.setenv("AGAMEMNON_ROUTING_ADMISSION", "unqualified-parent-setting")
    monkeypatch.setenv("AGRV2K_COMB_PRESENT_FIX", "1")
    calls = []

    def generate(command, **kwargs):
        assert not any(k.startswith(("AGAMEMNON_", "AGRV2K_")) for k in kwargs["env"])
        output = Path(command[command.index("--out") + 1])
        output.mkdir()
        for name in ("dev_pips.csv", "dev_belpins.csv", "dev_meta.csv"):
            (output / name).write_text("fixture orchestration only\n")
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("devdb_fixtures.subprocess.run", generate)
    try:
        paths = {p: databases.path(p) for p in ("strict", "strict_pcf", "tiered")}
        assert len(set(paths.values())) == 3
        assert databases.path("strict") == paths["strict"]
        assert other.path("strict") != paths["strict"]
        databases.prepare()
        databases.prepare()
        assert len(calls) == 3
        physical = next(c for c in calls if c[c.index("--out") + 1] == str(paths["strict_pcf"]))
        assert "AGAMEMNON_PHYSICAL_IO=1" in physical
        assert "AGAMEMNON_LEFT_PAD_OUT=1" in physical
        tiered = next(c for c in calls if c[c.index("--out") + 1] == str(paths["tiered"]))
        assert "AGAMEMNON_ROUTING_ADMISSION=tiered" in tiered
    finally:
        other.close()


@pytest.mark.parametrize("returncode", [0, 1])
def test_failed_or_incomplete_generator_never_admits_a_fixture(databases, monkeypatch, returncode):
    databases.path("strict")
    monkeypatch.setattr("devdb_fixtures.subprocess.run", lambda *a, **k:
                        SimpleNamespace(returncode=returncode, stdout="partial output", stderr="failed"))
    with pytest.raises(RuntimeError, match="generation failed|missing"):
        databases.prepare()
    assert not databases.ready
