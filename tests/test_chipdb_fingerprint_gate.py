"""GAP-1 closure: discoverable, individually-runnable copy of the chipdb
change tripwire.

The real enforcement point is the autouse, session-scoped fixture
``_chipdb_change_gate`` in tests/conftest.py: it fires for every pytest
session that touches the tests/ directory tree, regardless of which test
file(s) are named on the command line, which is what makes it "cannot be
bypassed by picking a narrow test target." See that file's module-level
banner for the full contract (what it does and does not cover) --
this file exists only so the check also shows up as its own named,
googleable test result, and so the pin file's own structure (non-empty
reason, valid date, valid hash) is checked directly. Both this file and the
conftest.py fixture consume the SAME session-cached
``chipdb_change_gate_message`` fixture, so opting to run only this file still
gets the real, unabridged check -- and running it alongside everything else
never repeats the (potentially expensive) escalation.
"""

from datetime import date

_SHA256_LEN = 64


def test_chipdb_matches_its_recorded_fingerprint_pin(chipdb_change_gate_message):
    assert chipdb_change_gate_message is None, chipdb_change_gate_message


def test_chipdb_fingerprint_pin_is_well_formed(chipdb_fingerprint_pin):
    pin = chipdb_fingerprint_pin
    assert pin["schema"] == "agamemnon.chipdb-fingerprint-pin.v1"
    assert isinstance(pin["fingerprint_sha256"], str) and len(pin["fingerprint_sha256"]) == _SHA256_LEN
    int(pin["fingerprint_sha256"], 16)  # raises ValueError if not hex
    assert isinstance(pin["file_count"], int) and pin["file_count"] > 0
    # Fails closed on the exact 2026-08-18 incident's shape: a change that adds
    # or removes rows inside an existing file trips the content hash; a
    # change that adds or removes a WHOLE FILE also has to trip the count.
    assert isinstance(pin["reason"], str) and pin["reason"].strip(), (
        "every fingerprint pin must record why it was set -- an empty reason "
        "is exactly the un-reviewed, unnoticed chipdb edit this gate exists "
        "to prevent"
    )
    date.fromisoformat(pin["pinned_date"])  # raises ValueError if malformed
