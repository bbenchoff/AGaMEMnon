#!/usr/bin/env python3
"""Durable work queue for silicon qualification campaigns.

The scheduler deliberately keeps three separate records:

* a candidate is the immutable physical path and test recipe;
* a job is its current scheduling state; and
* an attempt is one leased execution, including an immutable candidate snapshot.

Input to ``seed`` is JSONL (or a JSON array).  Each candidate must contain
``target_pip``, ``exact_path``, ``oracle``, ``board``, and ``port``.  Artifact
hashes may be supplied as ``routed_sha256``, ``bitstream_sha256``, and/or an
``artifact_hashes`` object.  Candidate keys are content-addressed when omitted.

This module has no non-standard dependencies and can be invoked directly::

    python -m agamemnon.engine.qualification_scheduler seed jobs.sqlite jobs.jsonl
    python -m agamemnon.engine.qualification_scheduler claim jobs.sqlite --worker bench-1
    python -m agamemnon.engine.qualification_scheduler finish jobs.sqlite \
        --job-id 1 --token TOKEN --result pass --observed toggle
    python -m agamemnon.engine.qualification_scheduler stats jobs.sqlite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


STATES = ("pending", "running", "pass", "fail", "inconclusive", "retry")
FINISH_STATES = ("pass", "fail", "inconclusive", "retry")
SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id                    INTEGER PRIMARY KEY,
    candidate_key         TEXT NOT NULL UNIQUE,
    target_pip            TEXT NOT NULL,
    exact_path_json       TEXT NOT NULL,
    routed_sha256         TEXT,
    bitstream_sha256      TEXT,
    artifact_hashes_json  TEXT NOT NULL,
    oracle_json           TEXT NOT NULL,
    board                 TEXT NOT NULL,
    port                  TEXT NOT NULL,
    metadata_json         TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id                    INTEGER PRIMARY KEY,
    candidate_id          INTEGER NOT NULL UNIQUE REFERENCES candidates(id),
    state                 TEXT NOT NULL CHECK (state IN
                             ('pending','running','pass','fail','inconclusive','retry')),
    priority              INTEGER NOT NULL DEFAULT 0,
    max_attempts          INTEGER,
    attempt_count         INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    active_attempt_id     INTEGER,
    available_at          TEXT NOT NULL,
    lease_owner           TEXT,
    lease_token           TEXT,
    lease_expires_at      TEXT,
    last_result           TEXT,
    last_message          TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    started_at            TEXT,
    finished_at           TEXT,
    CHECK (max_attempts IS NULL OR max_attempts > 0)
);

CREATE TABLE IF NOT EXISTS attempts (
    id                    INTEGER PRIMARY KEY,
    job_id                INTEGER NOT NULL REFERENCES jobs(id),
    attempt_no            INTEGER NOT NULL CHECK (attempt_no > 0),
    state                 TEXT NOT NULL CHECK (state IN
                             ('running','pass','fail','inconclusive','retry')),
    lease_owner           TEXT NOT NULL,
    lease_token           TEXT NOT NULL UNIQUE,
    target_pip            TEXT NOT NULL,
    exact_path_json       TEXT NOT NULL,
    routed_sha256         TEXT,
    bitstream_sha256      TEXT,
    artifact_hashes_json  TEXT NOT NULL,
    oracle_json           TEXT NOT NULL,
    board                 TEXT NOT NULL,
    port                  TEXT NOT NULL,
    claimed_at            TEXT NOT NULL,
    lease_expires_at      TEXT NOT NULL,
    finished_at           TEXT,
    observed_json         TEXT,
    message               TEXT NOT NULL DEFAULT '',
    UNIQUE (job_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS jobs_ready
    ON jobs(state, available_at, priority, id);
CREATE INDEX IF NOT EXISTS jobs_lease_expiry
    ON jobs(state, lease_expires_at);
CREATE INDEX IF NOT EXISTS attempts_job
    ON attempts(job_id, attempt_no);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_lease_token
    ON jobs(lease_token) WHERE lease_token IS NOT NULL;
"""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _decode(value):
    return json.loads(value) if value is not None else None


def _timestamp(value=None):
    if value is None:
        value = datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _future(timestamp, seconds):
    current = datetime.fromisoformat(timestamp)
    return _timestamp(current + timedelta(seconds=seconds))


def _nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % field)
    return value.strip()


def _sha256(value, field):
    if value is None or value == "":
        return None
    value = _nonempty(value, field).lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("%s must be a 64-character SHA-256 digest" % field)
    return value


def _candidate(record):
    if not isinstance(record, dict):
        raise ValueError("candidate must be a JSON object")
    target = _nonempty(record.get("target_pip"), "target_pip")
    path = record.get("exact_path")
    if not isinstance(path, (list, tuple)) or not path:
        raise ValueError("exact_path must be a non-empty array")
    path = [_nonempty(pip, "exact_path entry") for pip in path]
    if len(set(path)) != len(path):
        raise ValueError("exact_path must not contain duplicate PIPs")
    if target not in path:
        raise ValueError("target_pip must occur in exact_path")

    hashes = record.get("artifact_hashes", record.get("hashes", {}))
    if hashes is None:
        hashes = {}
    if not isinstance(hashes, dict):
        raise ValueError("artifact_hashes must be an object")
    hashes = {_nonempty(str(name), "artifact hash name"):
              _sha256(digest, "artifact_hashes.%s" % name)
              for name, digest in hashes.items()}
    if any(digest is None for digest in hashes.values()):
        raise ValueError("artifact hashes may not be empty")

    oracle = record.get("oracle")
    if oracle is None or oracle == "" or oracle == {}:
        raise ValueError("oracle must describe the expected observation")
    board = _nonempty(record.get("board"), "board")
    port = _nonempty(record.get("port"), "port")
    metadata = record.get("metadata", {})
    # Encoding here also rejects unserialisable values before opening a transaction.
    oracle_json = _json(oracle)
    metadata_json = _json(metadata)
    hashes_json = _json(hashes)
    routed = _sha256(record.get("routed_sha256"), "routed_sha256")
    bitstream = _sha256(record.get("bitstream_sha256"), "bitstream_sha256")

    identity = {
        "schema": 1,
        "target_pip": target,
        "exact_path": path,
        "routed_sha256": routed,
        "bitstream_sha256": bitstream,
        "artifact_hashes": hashes,
        "oracle": oracle,
        "board": board,
        "port": port,
        "metadata": metadata,
    }
    generated = hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()
    key = record.get("candidate_key", generated)
    key = _nonempty(key, "candidate_key")

    priority = record.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError("priority must be an integer")
    maximum = record.get("max_attempts")
    if maximum in (None, 0):
        maximum = None
    elif isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError("max_attempts must be a positive integer or zero")
    return {
        "candidate_key": key,
        "target_pip": target,
        "exact_path_json": _json(path),
        "routed_sha256": routed,
        "bitstream_sha256": bitstream,
        "artifact_hashes_json": hashes_json,
        "oracle_json": oracle_json,
        "board": board,
        "port": port,
        "metadata_json": metadata_json,
        "priority": priority,
        "max_attempts": maximum,
    }


class QualificationScheduler:
    """SQLite-backed qualification scheduler safe for multiple worker processes."""

    def __init__(self, database, timeout=30.0):
        self.database = os.fspath(database)
        self.timeout = float(timeout)
        if self.database != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.database))
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=self.timeout,
                                     isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = %d" % int(self.timeout * 1000))
        return connection

    def _initialize(self):
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA user_version = 1")
        finally:
            connection.close()

    @contextmanager
    def _transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def seed(self, record, now=None):
        """Idempotently create one candidate and its job."""
        result = self.seed_many([record], now=now)
        return {
            "job_id": result["job_ids"][0],
            "candidate_created": bool(result["candidates_created"]),
            "job_created": bool(result["jobs_created"]),
        }

    def seed_many(self, records, now=None):
        """Atomically and idempotently seed a collection of candidates."""
        normalized = [_candidate(record) for record in records]
        stamp = _timestamp(now)
        candidate_created = 0
        job_created = 0
        job_ids = []
        with self._transaction() as connection:
            for item in normalized:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO candidates
                       (candidate_key,target_pip,exact_path_json,routed_sha256,
                        bitstream_sha256,artifact_hashes_json,oracle_json,board,
                        port,metadata_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (item["candidate_key"], item["target_pip"],
                     item["exact_path_json"], item["routed_sha256"],
                     item["bitstream_sha256"], item["artifact_hashes_json"],
                     item["oracle_json"], item["board"], item["port"],
                     item["metadata_json"], stamp, stamp))
                candidate_created += cursor.rowcount
                candidate = connection.execute(
                    "SELECT * FROM candidates WHERE candidate_key = ?",
                    (item["candidate_key"],)).fetchone()
                expected = (
                    item["target_pip"], item["exact_path_json"],
                    item["routed_sha256"], item["bitstream_sha256"],
                    item["artifact_hashes_json"], item["oracle_json"],
                    item["board"], item["port"], item["metadata_json"])
                actual = tuple(candidate[name] for name in (
                    "target_pip", "exact_path_json", "routed_sha256",
                    "bitstream_sha256", "artifact_hashes_json", "oracle_json",
                    "board", "port", "metadata_json"))
                if actual != expected:
                    raise ValueError("candidate_key collision with different payload: %s" %
                                     item["candidate_key"])
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO jobs
                       (candidate_id,state,priority,max_attempts,available_at,
                        created_at,updated_at)
                       VALUES (?,'pending',?,?,?,?,?)""",
                    (candidate["id"], item["priority"], item["max_attempts"],
                     stamp, stamp, stamp))
                job_created += cursor.rowcount
                row = connection.execute(
                    "SELECT id FROM jobs WHERE candidate_id = ?",
                    (candidate["id"],)).fetchone()
                job_ids.append(row["id"])
        return {
            "input": len(normalized),
            "candidates_created": candidate_created,
            "jobs_created": job_created,
            "existing": len(normalized) - job_created,
            "job_ids": job_ids,
        }

    @staticmethod
    def _recover(connection, stamp):
        stale = connection.execute(
            """SELECT id,active_attempt_id,attempt_count,max_attempts
               FROM jobs
               WHERE state = 'running' AND lease_expires_at <= ?""",
            (stamp,)).fetchall()
        for job in stale:
            exhausted = (job["max_attempts"] is not None and
                         job["attempt_count"] >= job["max_attempts"])
            job_state = "inconclusive" if exhausted else "retry"
            if job["active_attempt_id"] is not None:
                connection.execute(
                    """UPDATE attempts SET state='retry',finished_at=?,
                           message='lease expired before completion'
                       WHERE id=? AND state='running'""",
                    (stamp, job["active_attempt_id"]))
            connection.execute(
                """UPDATE jobs SET state=?,active_attempt_id=NULL,
                       lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                       available_at=?,last_result='retry',
                       last_message='lease expired before completion',updated_at=?,
                       finished_at=?
                   WHERE id=? AND state='running'""",
                (job_state, stamp, stamp,
                 stamp if exhausted else None, job["id"]))
        return len(stale)

    def recover_stale(self, now=None):
        """Move expired running jobs to retry, preserving expired attempts."""
        stamp = _timestamp(now)
        with self._transaction() as connection:
            return self._recover(connection, stamp)

    def claim(self, worker, lease_seconds=300, now=None):
        """Atomically lease the highest priority ready job, or return ``None``."""
        worker = _nonempty(worker, "worker")
        if isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        stamp = _timestamp(now)
        expires = _future(stamp, lease_seconds)
        # argparse treats a URL-safe token that happens to begin with ``-`` as
        # another option when workers pass it back to the CLI.  A fixed
        # alphanumeric prefix keeps the opaque token shell/CLI safe without
        # reducing the random portion's entropy.
        token = "lease_" + secrets.token_urlsafe(24)
        with self._transaction() as connection:
            self._recover(connection, stamp)
            job = connection.execute(
                """SELECT jobs.*, candidates.*,
                          jobs.id AS job_id, candidates.id AS candidate_id
                   FROM jobs JOIN candidates ON candidates.id=jobs.candidate_id
                   WHERE jobs.state IN ('pending','retry')
                     AND jobs.available_at <= ?
                     AND (jobs.max_attempts IS NULL OR
                          jobs.attempt_count < jobs.max_attempts)
                   ORDER BY jobs.priority DESC,jobs.id ASC LIMIT 1""",
                (stamp,)).fetchone()
            if job is None:
                return None
            attempt_no = job["attempt_count"] + 1
            cursor = connection.execute(
                """INSERT INTO attempts
                   (job_id,attempt_no,state,lease_owner,lease_token,target_pip,
                    exact_path_json,routed_sha256,bitstream_sha256,
                    artifact_hashes_json,oracle_json,board,port,claimed_at,
                    lease_expires_at)
                   VALUES (?,?,'running',?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job["job_id"], attempt_no, worker, token, job["target_pip"],
                 job["exact_path_json"], job["routed_sha256"],
                 job["bitstream_sha256"], job["artifact_hashes_json"],
                 job["oracle_json"], job["board"], job["port"], stamp, expires))
            attempt_id = cursor.lastrowid
            connection.execute(
                """UPDATE jobs SET state='running',attempt_count=?,
                       active_attempt_id=?,lease_owner=?,lease_token=?,
                       lease_expires_at=?,updated_at=?,
                       started_at=COALESCE(started_at,?),finished_at=NULL
                   WHERE id=?""",
                (attempt_no, attempt_id, worker, token, expires, stamp, stamp,
                 job["job_id"]))
            return self._claimed_payload(connection, job["job_id"])

    @staticmethod
    def _claimed_payload(connection, job_id):
        row = connection.execute(
            """SELECT jobs.id AS job_id,jobs.candidate_id,jobs.state,
                      jobs.priority,jobs.max_attempts,jobs.attempt_count,
                      jobs.active_attempt_id AS attempt_id,jobs.lease_owner,
                      jobs.lease_token,jobs.lease_expires_at,jobs.created_at,
                      jobs.updated_at,candidates.candidate_key,
                      candidates.target_pip,candidates.exact_path_json,
                      candidates.routed_sha256,candidates.bitstream_sha256,
                      candidates.artifact_hashes_json,candidates.oracle_json,
                      candidates.board,candidates.port,candidates.metadata_json
               FROM jobs JOIN candidates ON candidates.id=jobs.candidate_id
               WHERE jobs.id=?""", (job_id,)).fetchone()
        payload = dict(row)
        payload["attempt_no"] = payload["attempt_count"]
        for source, destination in (
                ("exact_path_json", "exact_path"),
                ("artifact_hashes_json", "artifact_hashes"),
                ("oracle_json", "oracle"),
                ("metadata_json", "metadata")):
            payload[destination] = _decode(payload.pop(source))
        return payload

    def finish(self, job_id, lease_token, result, observed=None, message="",
               retry_delay=0, now=None):
        """Finish the active attempt, rejecting stale or foreign lease tokens."""
        if result not in FINISH_STATES:
            raise ValueError("result must be one of: %s" % ", ".join(FINISH_STATES))
        if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
            raise ValueError("job_id must be a positive integer")
        lease_token = _nonempty(lease_token, "lease_token")
        if isinstance(retry_delay, bool) or retry_delay < 0:
            raise ValueError("retry_delay must not be negative")
        stamp = _timestamp(now)
        available = _future(stamp, retry_delay)
        observed_json = _json(observed)
        message = "" if message is None else str(message)
        with self._transaction() as connection:
            self._recover(connection, stamp)
            job = connection.execute("SELECT * FROM jobs WHERE id=?",
                                     (job_id,)).fetchone()
            if job is None:
                raise ValueError("unknown job: %d" % job_id)
            if job["state"] != "running" or job["active_attempt_id"] is None:
                raise ValueError("job %d has no active lease" % job_id)
            if not secrets.compare_digest(job["lease_token"], lease_token):
                raise ValueError("lease token does not own job %d" % job_id)

            exhausted = (result == "retry" and job["max_attempts"] is not None and
                         job["attempt_count"] >= job["max_attempts"])
            job_state = "inconclusive" if exhausted else result
            final_message = message
            if exhausted:
                suffix = "maximum attempts reached"
                final_message = "%s; %s" % (message, suffix) if message else suffix
            connection.execute(
                """UPDATE attempts SET state=?,finished_at=?,observed_json=?,
                       message=? WHERE id=? AND state='running'""",
                (result, stamp, observed_json, final_message,
                 job["active_attempt_id"]))
            connection.execute(
                """UPDATE jobs SET state=?,active_attempt_id=NULL,
                       lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                       available_at=?,last_result=?,last_message=?,updated_at=?,
                       finished_at=? WHERE id=?""",
                (job_state, available, result, final_message, stamp,
                 None if job_state == "retry" else stamp, job_id))
            payload = self._claimed_payload(connection, job_id)
            payload["completed_attempt_id"] = job["active_attempt_id"]
            payload["requested_result"] = result
            return payload

    def stats(self, now=None):
        """Return state totals without changing expired leases."""
        stamp = _timestamp(now)
        connection = self._connect()
        try:
            jobs = {state: 0 for state in STATES}
            for row in connection.execute(
                    "SELECT state,COUNT(*) AS count FROM jobs GROUP BY state"):
                jobs[row["state"]] = row["count"]
            attempts = {state: 0 for state in ("running",) + FINISH_STATES}
            for row in connection.execute(
                    "SELECT state,COUNT(*) AS count FROM attempts GROUP BY state"):
                attempts[row["state"]] = row["count"]
            ready = connection.execute(
                """SELECT COUNT(*) FROM jobs
                   WHERE state IN ('pending','retry') AND available_at <= ?
                     AND (max_attempts IS NULL OR attempt_count < max_attempts)""",
                (stamp,)).fetchone()[0]
            stale = connection.execute(
                """SELECT COUNT(*) FROM jobs
                   WHERE state='running' AND lease_expires_at <= ?""",
                (stamp,)).fetchone()[0]
            return {
                "timestamp": stamp,
                "candidates": connection.execute(
                    "SELECT COUNT(*) FROM candidates").fetchone()[0],
                "total_jobs": sum(jobs.values()),
                "jobs": jobs,
                "ready": ready,
                "stale_running": stale,
                "total_attempts": sum(attempts.values()),
                "attempts": attempts,
            }
        finally:
            connection.close()


def _records(path):
    stream = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        first = stream.read(1)
        while first and first.isspace():
            first = stream.read(1)
        if not first:
            return []
        remainder = stream.read()
        text = first + remainder
        if first == "[":
            value = json.loads(text)
            if not isinstance(value, list):
                raise ValueError("seed JSON must be an array")
            return value
        records = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError("bad seed JSON on line %d" % line_number) from exc
        return records
    finally:
        if stream is not sys.stdin:
            stream.close()


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="idempotently seed candidate jobs")
    seed.add_argument("database")
    seed.add_argument("input", nargs="?", default="-", help="JSONL/JSON file or -")

    claim = commands.add_parser("claim", help="atomically lease one ready job")
    claim.add_argument("database")
    claim.add_argument("--worker", "--owner", dest="worker", required=True)
    claim.add_argument("--lease-seconds", type=float, default=300)

    finish = commands.add_parser("finish", help="finish the owned active attempt")
    finish.add_argument("database")
    finish.add_argument("--job-id", type=int, required=True)
    finish.add_argument("--token", required=True)
    finish.add_argument("--result", choices=FINISH_STATES, required=True)
    finish.add_argument("--observed", default=None)
    finish.add_argument("--message", default="")
    finish.add_argument("--retry-delay", type=float, default=0)

    stats = commands.add_parser("stats", help="print queue and attempt totals")
    stats.add_argument("database")
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        scheduler = QualificationScheduler(args.database)
        if args.command == "seed":
            output = scheduler.seed_many(_records(args.input))
        elif args.command == "claim":
            output = scheduler.claim(args.worker, args.lease_seconds)
        elif args.command == "finish":
            output = scheduler.finish(args.job_id, args.token, args.result,
                                      args.observed, args.message, args.retry_delay)
        else:
            output = scheduler.stats()
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        print("qualification scheduler error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
