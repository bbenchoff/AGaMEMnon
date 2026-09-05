"""Generate the installed-runtime dual-hash legacy clock registry.

Outputs JSON to stdout. Run from a source checkout; runtime validation never
needs to open the qualification corpus. The module hashes bind the caller's
in-memory document as well as its claimed routed-file hash.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agamemnon.engine.features.clock_validate import _module_sha256


def generate():
    source = (ROOT / 'qualification/pack_regression.json').read_bytes()
    manifest = json.loads(source)
    rows = []
    for artifact in manifest['artifacts']:
        data = (ROOT / artifact['routed']).read_bytes()
        canonical = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        assert hashlib.sha256(canonical).hexdigest() == artifact['routed_sha256']
        rows.append(dict(artifact, canonical_module_sha256=
                         _module_sha256(json.loads(data)['modules']['top'])))
    return {'schema': 1, 'hash_mode': manifest['hash_mode'],
            'source_registry_sha256': hashlib.sha256(source).hexdigest(),
            'artifacts': rows}


if __name__ == '__main__':
    print(json.dumps(generate(), indent=2) + '\n', end='')
