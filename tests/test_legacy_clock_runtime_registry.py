"""Installed legacy admission must be reproducible and dual-hash bound."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon.engine.features import clock_validate

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_clock_registry_is_exact_source_derivative():
    spec = importlib.util.spec_from_file_location(
        'clock_registry_export', ROOT / 'qualification/export_legacy_clock_registry.py')
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    path = ROOT / 'agamemnon/chipdb/clock_legacy_pack_registry.json'
    data = path.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
    assert hashlib.sha256(data).hexdigest() == clock_validate._LEGACY_RUNTIME_REGISTRY_SHA256
    assert json.loads(data) == exporter.generate()
    assert len(json.loads(data)['artifacts']) == 58


def test_runtime_admission_is_dual_hash_bound_and_fails_on_registry_drift(tmp_path, monkeypatch):
    registry = ROOT / 'agamemnon/chipdb/clock_legacy_pack_registry.json'
    raw = registry.read_bytes()
    row = next(r for r in json.loads(raw)['artifacts']
               if r['routed'] == 'qualification/counter8_carry_routed.json')
    module = json.loads((ROOT / row['routed']).read_text())['modules']['top']
    copied = tmp_path / registry.name
    copied.write_bytes(raw)
    # Isolate the non-quarantined registry path from the separately tested
    # extra-clock-leaf quarantine. There is no qualification directory here.
    monkeypatch.setattr(clock_validate, '_load_quarantine', lambda *args: [])
    monkeypatch.setattr(clock_validate, '__file__', str(tmp_path / 'installed/features/clock_validate.py'))
    def validate():
        return clock_validate._legacy_metadata_absence(
            module, row['routed_sha256'], SimpleNamespace(profile='unused'),
            1, tmp_path, None)
    assert validate() == row['bitstream_sha256']
    module.setdefault('attributes', {})['unrelated_mutation'] = '1'
    with pytest.raises(clock_validate.ClockValidationError, match='module mismatch'):
        validate()
    module['attributes'].pop('unrelated_mutation')
    copied.write_bytes(raw + b' ')
    with pytest.raises(clock_validate.ClockValidationError, match='registry digest drifted'):
        validate()
