"""A missing or skipped native suite must not satisfy the release gate."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('native_gate',
    Path(__file__).resolve().parents[1] / 'tools/run_native_tests.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize('counts,returncode,passed', [
    ('tests="2" failures="0" errors="0" skipped="0"', 0, True),
    ('tests="2" failures="0" errors="0" skipped="1"', 0, False),
    ('tests="0" failures="0" errors="0" skipped="0"', 0, False),
    ('tests="2" failures="1" errors="0" skipped="0"', 1, False),
    (None, 0, False),
])
def test_gate_requires_nonempty_unskipped_suite(tmp_path, monkeypatch, counts, returncode, passed):
    source = tmp_path / 'agamemnon/engine/uarch/agrv2k/agrv2k.cc'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'native source')
    binary = tmp_path / 'nextpnr'
    binary.write_bytes(b'fake native executable for orchestration test')
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_native_example.py').write_text('')
    (tests / 'test_uarch_shared_control_legality.py').write_text('')
    database = tmp_path / 'db'
    database.mkdir()
    (database / 'dev_pips.csv').write_text('fixture')
    closed = []
    fixtures = SimpleNamespace(path=lambda profile: database, prepare=lambda: None,
                               close=lambda: closed.append(True))
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'DatabaseFixtures', lambda: fixtures)
    output = tmp_path / 'output'
    monkeypatch.setattr(gate.sys, 'argv', ['native_gate', '--binary', str(binary),
        '--overlay', str(source), '--output', str(output)])

    def execute(command, **kwargs):
        assert str(tests / 'test_uarch_shared_control_legality.py') in command
        assert kwargs['env']['AGAMEMNON_UARCH_DEVDB'] == str(database)
        if counts is not None:
            (output / 'suite.xml').write_text('<testsuites><testsuite ' + counts + '/></testsuites>')
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(gate.subprocess, 'run', execute)
    assert gate.main() == (0 if passed else 1)
    assert json.loads((output / 'RESULT.json').read_text())['status'] == ('PASS' if passed else 'FAIL')
    assert closed == [True]
