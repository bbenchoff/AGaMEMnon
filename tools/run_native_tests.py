"""Run the compiled native regression families with explicit tool/data custody."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from devdb_fixtures import DatabaseFixtures


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    overlay = args.overlay.resolve(strict=True)
    source = ROOT / 'agamemnon/engine/uarch/agrv2k/agrv2k.cc'
    if source.read_bytes() != overlay.read_bytes():
        raise ValueError('Compiled overlay differs from checkout source')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    targets = sorted(ROOT.glob('tests/test_native*.py'))
    if not targets:
        raise ValueError('No native regression families found')
    # These packing/admission checks predate the test_native naming convention.
    # Keep them in the compiled, no-skip CI gate rather than the Python-only run.
    targets.append(ROOT / 'tests/test_uarch_shared_control_legality.py')
    fixtures = DatabaseFixtures()
    try:
        database = fixtures.path('strict')
        fixtures.prepare()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('AGAMEMNON_', 'AGRV2K_'))}
        env.update(AGAMEMNON_UARCH_NEXTPNR=str(binary),
                   AGAMEMNON_UARCH_SOURCE=str(overlay),
                   AGAMEMNON_UARCH_DEVDB=str(database),
                   AGAMEMNON_DATA=str(ROOT / 'agamemnon/chipdb'))
        junit = output / 'suite.xml'
        command = [sys.executable, '-m', 'pytest', '-q',
                   '--junitxml=' + str(junit), *map(str, targets)]
        report = dict(status='RUNNING', binary_sha256=sha(binary),
                      source_sha256=sha(source), command=command,
                      test_sha256={str(path.relative_to(ROOT)): sha(path) for path in targets},
                      database_sha256={path.name: sha(path) for path in sorted(database.iterdir())
                                       if path.is_file()})
        result = output / 'RESULT.json'
        result.write_text(json.dumps(report, indent=2) + '\n')
        with (output / 'suite.log').open('w') as log:
            run = subprocess.run(command, cwd=ROOT, env=env, stdout=log,
                                 stderr=subprocess.STDOUT)
        counts = dict(tests=0, failures=0, errors=0, skipped=0)
        if junit.is_file():
            for suite in ET.parse(junit).getroot().iter('testsuite'):
                for key in counts:
                    counts[key] += int(suite.get(key, '0'))
            report['junit_sha256'] = sha(junit)
        passed = (run.returncode == 0 and counts['tests'] > 0
                  and not any(counts[key] for key in ('failures', 'errors', 'skipped'))
                  and sha(binary) == report['binary_sha256']
                  and sha(source) == report['source_sha256'])
        report.update(status='PASS' if passed else 'FAIL', counts=counts,
                      returncode=run.returncode, log_sha256=sha(output / 'suite.log'))
        result.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        return 0 if passed else 1
    finally:
        fixtures.close()


if __name__ == '__main__':
    raise SystemExit(main())
