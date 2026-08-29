from __future__ import annotations

import csv
import io
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def test_python_emitter_quotes_vendor_output_slice_metadata() -> None:
    stream = io.StringIO(newline="")
    csv.writer(stream).writerow(
        ["agamemnon_env", "AGAMEMNON_VENDOR_OUT_SLICE=14,9,4"]
    )
    emitted = stream.getvalue()
    assert emitted == 'agamemnon_env,"AGAMEMNON_VENDOR_OUT_SLICE=14,9,4"\r\n'
    assert next(csv.reader(io.StringIO(emitted))) == [
        "agamemnon_env",
        "AGAMEMNON_VENDOR_OUT_SLICE=14,9,4",
    ]


def test_uarch_csv_reader_honours_quotes_and_fails_closed() -> None:
    source = UARCH.read_text(encoding="utf-8")
    reader = source[source.index("struct Csv") : source.index("static int to_int")]
    assert "bool in_quotes = false;" in reader
    assert "bool closed_quote = false;" in reader
    assert "cur.push_back('\"');" in reader
    assert 'if (ch != \',\')' in reader
    assert "malformed quoted CSV field" in reader
    assert "unterminated quoted CSV field" in reader
