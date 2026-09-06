"""Reject ambiguous or malformed authority across the two BRAM route tables."""
import csv
from pathlib import Path

import pytest

from agamemnon.engine.bram_routing import CORRIDOR_TABLE, FIELDS, TABLE, load_routes

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon/chipdb"


def write_rows(root, name, rows):
    with (root / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def shared_row():
    with (CHIPDB / TABLE).open(newline="") as stream:
        return next(row for row in csv.DictReader(stream)
                    if "_RMUX" in row["src_wire"] and "_RMUX" in row["dst_wire"])


@pytest.mark.parametrize("duplicate", [False, True])
def test_cross_table_ambiguity_rejected(tmp_path, duplicate):
    row = shared_row()
    alias = dict(row)
    if not duplicate:
        alias["src_wire"] = "X14Y7_RMUX99"
        assert alias["src_wire"] != row["src_wire"]
    write_rows(tmp_path, TABLE, [row])
    write_rows(tmp_path, CORRIDOR_TABLE, [alias])
    with pytest.raises(ValueError, match="across tables"):
        load_routes(tmp_path)


def test_missing_corridor_authority_is_not_silently_ignored(tmp_path):
    write_rows(tmp_path, TABLE, [shared_row()])
    with pytest.raises(FileNotFoundError):
        load_routes(tmp_path)


def test_corridor_table_cannot_admit_clock_or_unrelated_source_family(tmp_path):
    write_rows(tmp_path, TABLE, [])
    row = dict(shared_row(), src_wire="X14Y7_OMUX00")
    write_rows(tmp_path, CORRIDOR_TABLE, [row])
    with pytest.raises(ValueError, match="unsupported BRAM logic-side corridor family"):
        load_routes(tmp_path)
