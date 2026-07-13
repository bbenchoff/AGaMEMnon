import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from agamemnon.engine.qualification_scheduler import (
    QualificationScheduler,
    main,
)


ROUTED_HASH = "12" * 32
BITSTREAM_HASH = "ab" * 32


def _candidate(**changes):
    value = {
        "target_pip": "X2Y3_OMUX01.X2Y3_RMUX04",
        "exact_path": [
            "X2Y3_LUT_OUT.X2Y3_OMUX01",
            "X2Y3_OMUX01.X2Y3_RMUX04",
            "X2Y3_RMUX04.X3Y3_IMUX02",
        ],
        "routed_sha256": ROUTED_HASH,
        "bitstream_sha256": BITSTREAM_HASH,
        "artifact_hashes": {"probe_source": "34" * 32},
        "oracle": {"kind": "digital_toggle", "pin": 6, "minimum_edges": 2},
        "board": "ag32-l48-001",
        "port": "COM6",
        "metadata": {"campaign": "full-chip-xbar"},
    }
    value.update(changes)
    return value


def _time(second=0):
    return datetime(2026, 7, 12, 20, 0, second, tzinfo=timezone.utc)


def test_seed_is_idempotent_and_rejects_key_collision(tmp_path):
    scheduler = QualificationScheduler(tmp_path / "jobs.sqlite")
    first = scheduler.seed(_candidate(), now=_time())
    second = scheduler.seed(_candidate(), now=_time(1))

    assert first == {"job_id": 1, "candidate_created": True, "job_created": True}
    assert second == {"job_id": 1, "candidate_created": False, "job_created": False}
    assert scheduler.stats(now=_time(2))["candidates"] == 1
    assert scheduler.stats(now=_time(2))["jobs"]["pending"] == 1

    explicit = _candidate(candidate_key="operator-key")
    scheduler.seed(explicit, now=_time(2))
    changed = _candidate(candidate_key="operator-key", board="different-board")
    with pytest.raises(ValueError, match="collision"):
        scheduler.seed(changed, now=_time(3))


def test_claim_snapshots_complete_evidence_and_finish_pass(tmp_path):
    database = tmp_path / "jobs.sqlite"
    scheduler = QualificationScheduler(database)
    scheduler.seed(_candidate(), now=_time())

    claim = scheduler.claim("pico-com6", lease_seconds=30, now=_time(1))
    assert claim["state"] == "running"
    assert claim["attempt_no"] == 1
    assert claim["target_pip"] == _candidate()["target_pip"]
    assert claim["exact_path"] == _candidate()["exact_path"]
    assert claim["routed_sha256"] == ROUTED_HASH
    assert claim["bitstream_sha256"] == BITSTREAM_HASH
    assert claim["artifact_hashes"] == {"probe_source": "34" * 32}
    assert claim["oracle"]["kind"] == "digital_toggle"
    assert claim["board"] == "ag32-l48-001"
    assert claim["port"] == "COM6"

    finished = scheduler.finish(
        claim["job_id"], claim["lease_token"], "pass",
        observed={"edges": 11}, message="logic analyzer passed", now=_time(2))
    assert finished["state"] == "pass"
    assert finished["lease_token"] is None

    connection = sqlite3.connect(database)
    row = connection.execute(
        """SELECT state,target_pip,exact_path_json,routed_sha256,
                  bitstream_sha256,oracle_json,board,port,claimed_at,finished_at,
                  observed_json,message FROM attempts""").fetchone()
    connection.close()
    assert row[0] == "pass"
    assert row[1] == _candidate()["target_pip"]
    assert json.loads(row[2]) == _candidate()["exact_path"]
    assert row[3:5] == (ROUTED_HASH, BITSTREAM_HASH)
    assert json.loads(row[5])["minimum_edges"] == 2
    assert row[6:8] == ("ag32-l48-001", "COM6")
    assert row[8] and row[9]
    assert json.loads(row[10]) == {"edges": 11}
    assert row[11] == "logic analyzer passed"


def test_claim_is_atomic_across_workers(tmp_path):
    scheduler = QualificationScheduler(tmp_path / "jobs.sqlite")
    scheduler.seed(_candidate(), now=_time())

    def claim(index):
        return scheduler.claim("worker-%d" % index, lease_seconds=60, now=_time(1))

    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(claim, range(8)))
    owned = [claim for claim in claims if claim is not None]
    assert len(owned) == 1
    assert owned[0]["attempt_count"] == 1
    assert scheduler.stats(now=_time(2))["total_attempts"] == 1


def test_expired_lease_becomes_audited_retry_then_reclaims(tmp_path):
    database = tmp_path / "jobs.sqlite"
    scheduler = QualificationScheduler(database)
    scheduler.seed(_candidate(), now=_time())
    first = scheduler.claim("worker-a", lease_seconds=10, now=_time(1))

    assert scheduler.stats(now=_time(12))["stale_running"] == 1
    second = scheduler.claim("worker-b", lease_seconds=10, now=_time(12))
    assert second["job_id"] == first["job_id"]
    assert second["attempt_no"] == 2
    assert second["lease_token"] != first["lease_token"]

    connection = sqlite3.connect(database)
    attempts = connection.execute(
        "SELECT attempt_no,state,finished_at,message FROM attempts ORDER BY attempt_no"
    ).fetchall()
    connection.close()
    assert attempts[0][0:2] == (1, "retry")
    assert attempts[0][2]
    assert "lease expired" in attempts[0][3]
    assert attempts[1][0:2] == (2, "running")

    with pytest.raises(ValueError, match="does not own"):
        scheduler.finish(first["job_id"], first["lease_token"], "pass",
                         now=_time(13))


def test_retry_limit_resolves_job_inconclusive(tmp_path):
    scheduler = QualificationScheduler(tmp_path / "jobs.sqlite")
    scheduler.seed(_candidate(max_attempts=2), now=_time())

    first = scheduler.claim("worker", now=_time(1))
    retried = scheduler.finish(first["job_id"], first["lease_token"], "retry",
                               retry_delay=5, now=_time(2))
    assert retried["state"] == "retry"
    assert scheduler.claim("too-early", now=_time(3)) is None

    second = scheduler.claim("worker", now=_time(7))
    exhausted = scheduler.finish(second["job_id"], second["lease_token"],
                                 "retry", now=_time(8))
    assert exhausted["state"] == "inconclusive"
    assert exhausted["attempt_count"] == 2
    assert scheduler.claim("worker", now=_time(9)) is None
    stats = scheduler.stats(now=_time(9))
    assert stats["jobs"]["inconclusive"] == 1
    assert stats["attempts"]["retry"] == 2


def test_cli_seed_claim_finish_and_stats(tmp_path, capsys):
    database = tmp_path / "jobs.sqlite"
    source = tmp_path / "candidates.jsonl"
    source.write_text(json.dumps(_candidate()) + "\n", encoding="utf-8")

    assert main(["seed", str(database), str(source)]) == 0
    seeded = json.loads(capsys.readouterr().out)
    assert seeded["jobs_created"] == 1

    assert main(["claim", str(database), "--worker", "pico", "--lease-seconds", "60"]) == 0
    claim = json.loads(capsys.readouterr().out)
    assert claim["state"] == "running"

    assert main(["finish", str(database), "--job-id", str(claim["job_id"]),
                 "--token", claim["lease_token"], "--result", "pass",
                 "--observed", "toggle"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "pass"

    assert main(["stats", str(database)]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["jobs"]["pass"] == 1
    assert stats["attempts"]["pass"] == 1


def test_validation_requires_exact_target_and_real_hashes(tmp_path):
    scheduler = QualificationScheduler(tmp_path / "jobs.sqlite")
    with pytest.raises(ValueError, match="target_pip must occur"):
        scheduler.seed(_candidate(exact_path=["X1Y1_A.X1Y1_B"]))
    with pytest.raises(ValueError, match="64-character"):
        scheduler.seed(_candidate(routed_sha256="not-a-hash"))
