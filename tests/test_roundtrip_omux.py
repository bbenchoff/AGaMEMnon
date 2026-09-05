import copy
import unittest

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from roundtrip_omux import compare_omux_selections, expected_omux_selections


def module(port='F', index=2):
    return {'cells': {'driver': {'type': 'GENERIC_SLICE',
        'attributes': {'NEXTPNR_BEL': 'X4Y5_SLICE0'},
        'parameters': {'FF_USED': '1' if port == 'Q' else '0'},
        'connections': {port: [10]}}},
        'netnames': {'signal': {'bits': [10], 'attributes': {
            'ROUTING': 'X4Y5_OMUX%d;;1' % index}}}}


class OmuxRoundtripTests(unittest.TestCase):
    def test_both_polarities_and_all_three_outputs(self):
        for port in ('F', 'Q'):
            for index in range(3):
                with self.subTest(port=port, index=index):
                    design = module(port, index)
                    bits = {(4, 5, 'CFG_OMUX0[%d]' % index): (0, 1 << index)}
                    correct = (1 << index) if port == 'Q' else 0
                    self.assertEqual(compare_omux_selections(design, bytes([correct]), bits), (1, [], 0))
                    self.assertEqual(len(compare_omux_selections(design, bytes([correct ^ (1 << index)]), bits)[1]), 1)

    def test_alias_and_mixed_f_q(self):
        design = module()
        design['cells']['driver']['connections']['Q'] = [11]
        design['cells']['driver']['parameters']['FF_USED'] = '1'
        design['netnames']['signal']['attributes']['ROUTING'] = 'X4Y5_OMUX2;;1;X4Y5_OMUX0;X4Y5_OMUX2.X4Y5_OMUX0;1'
        design['netnames']['registered'] = {'bits': [11], 'attributes': {'ROUTING': 'X4Y5_OMUX1;;1'}}
        bits = {(4, 5, 'CFG_OMUX0[%d]' % i): (0, 1 << i) for i in range(3)}
        self.assertEqual(compare_omux_selections(design, b'\x02', bits), (3, [], 0))
        for mask in (1, 2, 4):
            self.assertEqual(len(compare_omux_selections(design, bytes([2 ^ mask]), bits)[1]), 1)

    def test_bad_ownership_refuses(self):
        cases = []
        missing = module(); missing['cells']['driver']['connections'] = {}; cases.append(missing)
        ambiguous = module(); ambiguous['cells']['driver']['connections']['Q'] = [10]; cases.append(ambiguous)
        inactive = module('Q'); inactive['cells']['driver']['parameters']['FF_USED'] = '0'; cases.append(inactive)
        duplicate = module(); duplicate['cells']['other'] = copy.deepcopy(duplicate['cells']['driver']); cases.append(duplicate)
        for design in cases:
            with self.assertRaises(ValueError):
                expected_omux_selections(design)

    def test_missing_decode_bit_is_not_a_clear_bit(self):
        count, errors, _ = compare_omux_selections(module(), b'\x00', {})
        self.assertEqual(count, 1)
        self.assertEqual(errors[0]['error'], 'missing decoder feature')

    def test_non_slice_resource_is_counted_unrecoverable(self):
        design = module(); design['cells'] = {}
        self.assertEqual(compare_omux_selections(design, b'\x00', {}), (0, [], 1))

    def test_out_of_image_decode_bit_is_not_a_clear_bit(self):
        for offset in (-1, 1):
            bits = {(4, 5, 'CFG_OMUX0[2]'): (offset, 4)}
            count, errors, unowned = compare_omux_selections(module(), b'\x00', bits)
            self.assertEqual((count, unowned), (1, 0))
            self.assertEqual(errors[0]['error'], 'decoder bit outside image')

    def test_omux_is_checked_separately_from_group_presence(self):
        from tools.roundtrip_check import expected_mux_groups

        design = module()
        design['netnames']['signal']['attributes']['ROUTING'] = (
            'X4Y5_OMUX2;;1;X4Y5_OMUX0;X4Y5_OMUX2.X4Y5_OMUX0;1'
        )
        groups, skipped = expected_mux_groups(design)
        self.assertEqual(groups, {})
        self.assertEqual(dict(skipped), {})
        expected, unowned = expected_omux_selections(design)
        self.assertEqual(len(expected), 2)
        self.assertEqual(unowned, 0)

    def test_explicit_bram_selection_is_checked_and_requires_mode_marker(self):
        design = module()
        design['cells']['driver']['attributes'].update(AGRV2K_OMUX_SEL='10', AGRV2K_BRAM_PINPACKED='1')
        design['cells']['driver']['parameters']['INIT'] = '0'
        bits = {(4, 5, 'CFG_OMUX0[2]'): (0, 4)}
        self.assertEqual(compare_omux_selections(design, b'\x04', bits), (1, [], 0))
        self.assertEqual(len(compare_omux_selections(design, b'\x00', bits)[1]), 1)
        design['cells']['driver']['parameters']['INIT'] = '1010'
        self.assertEqual(compare_omux_selections(design, b'\x04', bits), (1, [], 0))
        design['cells']['driver']['attributes'].pop('AGRV2K_BRAM_PINPACKED')
        with self.assertRaises(ValueError):
            compare_omux_selections(design, b'\x04', bits)

    def test_alternate_presentation_is_scoped_and_bit_checked(self):
        design = module('F', 0)
        env = {'AGAMEMNON_VENDOR_OUT_SLICE': '4,5,0'}
        bits = {(4, 5, 'CFG_OMUX0[0]'): (0, 1)}
        self.assertEqual(compare_omux_selections(design, b'\x01', bits, env), (1, [], 0))
        self.assertEqual(len(compare_omux_selections(design, b'\x00', bits, env)[1]), 1)
        self.assertEqual(len(compare_omux_selections(design, b'\x01', bits, {})[1]), 1)
        with self.assertRaises(ValueError):
            expected_omux_selections(module('F', 2), env)

    def test_declared_direct_d_checks_entire_field(self):
        design = module('Q', 2)
        env = {'AGAMEMNON_DIRECT_D': '1', 'AGAMEMNON_DIRECT_D_SITES': 'X4Y5_SLICE0'}
        bits = {(4, 5, 'CFG_OMUX0[%d]' % i): (0, 1 << i) for i in range(3)}
        self.assertEqual(compare_omux_selections(design, b'\x03', bits, env), (3, [], 0))
        for mask in (1, 2, 4):
            self.assertEqual(len(compare_omux_selections(design, bytes([3 ^ mask]), bits, env)[1]), 1)
        self.assertEqual(len(compare_omux_selections(design, b'\x03', bits, {})[1]), 1)


if __name__ == '__main__':
    unittest.main()
