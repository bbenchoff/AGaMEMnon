"""A failed one-stage optimization must not bypass downstream native legality."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from test_native_bram_output_reservation import fixture


def test_unavailable_bridge_does_not_bypass_native_legality(tmp_path):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    if not binary or not Path(binary).is_file() or not (devdb/'dev_pips.csv').is_file():
        pytest.skip('configure isolated native binary and database')
    source, routed = tmp_path/'input.json', tmp_path/'routed.json'
    source.write_text(json.dumps(fixture(8, 4, site=3)))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_')) and k != 'LD_PRELOAD'}
    env.update(AGAMEMNON_DATA=os.environ['AGAMEMNON_DATA'], AGRV2K_BRAM_PINPACK='1', AGRV2K_IO_PINPACK='1')
    result = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}',
        '--json', str(source), '--write', str(routed), '--top', 'top', '--router', 'router2'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = result.stdout+result.stderr
    (tmp_path/'native.log').write_text(transcript)
    assert 'retaining original net for routing' in transcript
    assert result.returncode != 0
    assert not routed.exists()
    assert "Bel 'X13Y3_BRAM' of type 'ALTA_BRAM9K' is not valid for cell 'ram'" in transcript
