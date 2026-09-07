"""Exact-image migration must preserve its old identities and new witnesses."""
import hashlib
import json
from pathlib import Path

from agamemnon.engine.registry import CONSTANTS

ROOT = Path(__file__).resolve().parents[1]
PATH = 'qualification/serv_f_output_requalification_20260905.json'


def test_three_serv_images_bind_fresh_f_output_witnesses():
    migration = json.loads((ROOT / PATH).read_text())
    manifest = json.loads((ROOT / 'qualification/pack_regression.json').read_text())
    artifacts = {row['routed']: row for row in manifest['artifacts']}
    assert migration['schema'] == 1
    assert migration['changed_artifacts'] == len(migration['records']) == 3
    assert migration['unchanged_artifacts'] == len(artifacts) - 3 == 55
    assert {row['routed'] for row in migration['records']} == {
        'qualification/serv_blinky_L48_routed.json',
        'qualification/serv_rv32i_smoke_L48_routed.json',
        'qualification/serv_rv32i_heartbeat_L48_routed.json',
    }
    for row in migration['records']:
        artifact = artifacts[row['routed']]
        for key in ('routed_sha256', 'bitstream_sha256', 'environment'):
            assert row[key] == artifact[key]
        data = (ROOT / row['routed']).read_bytes().replace(b'\r\n', b'\n')
        assert hashlib.sha256(data).hexdigest() == row['routed_sha256']
        assert row['previous_bitstream_sha256'] != row['bitstream_sha256']
        assert row['hardware'] and row['runs'] == 3
        assert row['control_status'] == 'PASS' and row['board_reset']
        assert row['flash_written'] is False
        assert row['evidence'] == (
            'https://github.com/bbenchoff/AG32-Docs/tree/'
            '51c1dffe732a24a639ffae15e34f113df88a40d8/tools/vendor_parity/'
            'gpt6_serv_f_output_silicon_20260905')
        assert row['report_sha256_lf'] == '116975ba48d583bba1c6e4b88d891f5506fb0b565df5bf77274ead286d1cad55'


def test_sdk_blinky_binds_new_raw_and_compressed_image():
    migration = json.loads((ROOT / PATH).read_text())
    row = next(r for r in migration['records'] if r['trial_id'] == 'serv-f-output-blinky-20260905')
    profiles = json.loads((ROOT / 'agamemnon/sdk/qualified_fabric_profiles.json').read_text())
    profile = next(p for p in profiles['profiles'].values()
                   if p['claim_constant'] == 'l48_serv_blinky_image_sha256')
    assert profile['image_sha256'] == row['bitstream_sha256']
    assert CONSTANTS[profile['claim_constant']].value == row['bitstream_sha256']
    assert profile['compressed_sha256'] == row['compressed_sha256']
    assert profile['compressed_bytes'] == row['compressed_bytes']
    assert profile['routed_sha256'] == row['routed_sha256']
    assert profile['silicon_evidence'] == PATH + '#' + row['trial_id']
