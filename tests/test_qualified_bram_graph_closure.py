"""Every reserved source tree must be representable before native placement."""
import csv
import os
from pathlib import Path
import subprocess
import sys

from agamemnon.engine import qualified_bram_tmux9 as bram


def test_source_profile_graph_covers_every_reserved_tree(tmp_path):
    root = Path(__file__).resolve().parents[1]
    graph = tmp_path / 'source-profile'
    command = [sys.executable, str(root / 'agamemnon/engine/emit_uarch_db.py'),
               '--arch', str(root / 'agamemnon/engine/arch.py'),
               '--data', str(root / 'agamemnon/chipdb'), '--out', str(graph)]
    for setting in ('AGAMEMNON_CONDUCTION_GATE=1', 'AGAMEMNON_HW_CARRY=1',
                    'AGAMEMNON_LEDPADS=1', 'AGAMEMNON_STRICT_GATE=1',
                    'AGAMEMNON_XBAR_CONDUCT=1', 'AGAMEMNON_CLEAN_SEL_GATE=1',
                    'AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE=source'):
        command.extend(('--env', setting))
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('AGAMEMNON_', 'AGRV2K_'))}
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                            text=True, timeout=1800)
    assert result.returncode == 0, result.stdout + result.stderr
    with (graph / 'dev_pips.csv').open(newline='', encoding='utf-8') as stream:
        pips = {row['name'] for row in csv.DictReader(stream)}
    missing = {}
    for profile in sorted(bram.PROFILES):
        routes = bram.required_routes(profile)
        for net, route in routes.items():
            fields = route.split(';')
            absent = sorted({fields[i] for i in range(1, len(fields), 3)
                             if fields[i] and fields[i] not in pips})
            if absent:
                missing[(profile, net)] = absent
    assert not missing, missing
