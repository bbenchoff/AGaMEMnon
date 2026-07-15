import csv

import pytest

from qualification.restrict_devdb_sink import restrict, restrict_egress


FIELDS = ["src", "dst", "delay", "flags"]


def _write(path):
    rows = [
        {"src": "A", "dst": "X", "delay": "1", "flags": "0"},
        {"src": "B", "dst": "X", "delay": "2", "flags": "0"},
        {"src": "A", "dst": "Y", "delay": "3", "flags": "1"},
        {"src": "C", "dst": "Z", "delay": "4", "flags": "0"},
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_restrict_fanin_preserves_schema_and_unrelated_rows(tmp_path):
    source, output = tmp_path / "in.csv", tmp_path / "out.csv"
    _write(source)

    assert restrict(source, output, "X", {"B"}) == (2, 1, 1)
    assert _read(output) == [
        {"src": "B", "dst": "X", "delay": "2", "flags": "0"},
        {"src": "A", "dst": "Y", "delay": "3", "flags": "1"},
        {"src": "C", "dst": "Z", "delay": "4", "flags": "0"},
    ]


def test_restrict_fanout_and_reject_missing_destination(tmp_path):
    source, output = tmp_path / "in.csv", tmp_path / "out.csv"
    _write(source)

    assert restrict_egress(source, output, "A", {"Y"}) == (2, 1, 1)
    assert {(row["src"], row["dst"]) for row in _read(output)} == {
        ("B", "X"), ("A", "Y"), ("C", "Z")
    }
    with pytest.raises(ValueError, match="requested destinations"):
        restrict_egress(source, output, "A", {"missing"})
