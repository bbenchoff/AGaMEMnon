import json
import shutil
from pathlib import Path

from tools.validate_evidence import MANIFEST, QUALIFICATION, validate


def copy_ledgers(tmp_path):
    target = tmp_path / "qualification"
    target.mkdir()
    shutil.copy2(MANIFEST, target / MANIFEST.name)
    for source in QUALIFICATION.glob("*.jsonl"):
        shutil.copy2(source, target / source.name)
    return target


def test_checked_evidence_ledgers_pass_release_gate():
    assert validate() == []


def test_valid_schema1_append_preserves_checked_prefix(tmp_path):
    root = copy_ledgers(tmp_path)
    ledger = root / "analog_adc0_db1_route_evidence.jsonl"
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "schema": 1,
            "trial_id": "append-test",
            "artifact_sha256": "00" * 32,
        }, separators=(",", ":")) + "\n")
    assert validate(root, root / MANIFEST.name) == []


def test_crlf_checkout_preserves_checked_prefixes(tmp_path):
    root = copy_ledgers(tmp_path)
    for ledger in root.glob("*.jsonl"):
        canonical = ledger.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        ledger.write_bytes(canonical.replace(b"\n", b"\r\n"))
    assert validate(root, root / MANIFEST.name) == []


def test_prefix_rewrite_and_unmanifested_ledger_fail(tmp_path):
    root = copy_ledgers(tmp_path)
    ledger = root / "analog_adc0_db1_route_evidence.jsonl"
    data = ledger.read_bytes()
    ledger.write_bytes(b"X" + data[1:])
    (root / "unreviewed.jsonl").write_text('{"schema":1}\n', encoding="utf-8")
    errors = validate(root, root / MANIFEST.name)
    assert any("checked prefix changed" in error for error in errors)
    assert any("not declared" in error for error in errors)


def test_new_malformed_hash_is_rejected(tmp_path):
    root = copy_ledgers(tmp_path)
    ledger = root / "analog_adc0_db1_route_evidence.jsonl"
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write('{"schema":1,"trial_id":"bad","image_sha256":"1234"}\n')
    assert any("image_sha256 is not a SHA-256" in error
               for error in validate(root, root / MANIFEST.name))
