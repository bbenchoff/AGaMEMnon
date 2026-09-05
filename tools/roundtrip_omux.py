"""Independent routed OMUX intent reconstruction for round-trip validation.

No encoder output-owner helper or selector arbitration table is consulted.
Physical bit addresses still come from the decoder's shared feature map.
"""
import re


def expected_omux_selections(module, environment=None):
    environment = environment or {}
    alternate = environment.get('AGAMEMNON_VENDOR_OUT_SLICE')
    alternate_site = None
    if alternate:
        if not re.fullmatch(r'\d+,\d+,\d+', alternate):
            raise ValueError('malformed alternate output site')
        alternate_site = tuple(map(int, alternate.split(',')))
    direct_sites = set()
    if environment.get('AGAMEMNON_DIRECT_D'):
        declared = environment.get('AGAMEMNON_DIRECT_D_SITES')
        if declared:
            for token in declared.split(';'):
                match = re.fullmatch(r'X(\d+)Y(\d+)_SLICE(\d+)', token.strip())
                if not match:
                    raise ValueError('malformed direct-D site')
                direct_sites.add(tuple(map(int, match.groups())))
        else:
            direct_sites = {(14, 11, z) for z in (4, 5, 6, 7)}
    placed = {}
    for name, cell in module.get('cells', {}).items():
        if cell.get('type') != 'GENERIC_SLICE':
            continue
        match = re.fullmatch(r'X(\d+)Y(\d+)_SLICE(\d+)', cell.get('attributes', {}).get('NEXTPNR_BEL', ''))
        if not match:
            continue
        site = tuple(map(int, match.groups()))
        if site in placed:
            raise ValueError('duplicate OMUX slice owner at %s' % (site,))
        placed[site] = (name, cell)
    expected, unowned = {}, set()
    for name, net in module.get('netnames', {}).items():
        route = net.get('attributes', {}).get('ROUTING', '')
        wires = set(re.findall(r'X(\d+)Y(\d+)_OMUX(\d+)(?!\d)', route))
        for coords in wires:
            x, y, index = map(int, coords)
            site = (x, y, index // 3)
            if site not in placed:
                unowned.add((x, y, index))
                continue  # Not a GENERIC_SLICE: another typed resource owns it.
            owner_name, owner = placed[site]
            bits = net.get('bits', [])
            connections = owner.get('connections', {})
            candidates = [port for port in ('F', 'Q') if len(bits) == 1
                          and type(bits[0]) is int and connections.get(port) == bits]
            if len(candidates) != 1:
                raise ValueError('no unique F/Q owner for net %s at %s' % (name, owner_name))
            registered = candidates[0] == 'Q'
            used = owner.get('parameters', {}).get('FF_USED', '0')
            used = int(used, 2) if isinstance(used, str) else int(used)
            if registered and used != 1:
                raise ValueError('inactive Q owner %s' % owner_name)
            feature = (x, y, 'CFG_OMUX%d[%d]' % (index // 3, index % 3))
            value = int(registered)
            if site in direct_sites:
                # The declared direct-D presentation owns the whole field.
                # Retained checkpoints can retain a logical OMUX+2 name while
                # this mode presents outputs through selectors 0/1 instead.
                for slot, expected_bit in enumerate((1, int(used == 1), 0)):
                    key = (x, y, 'CFG_OMUX%d[%d]' % (index // 3, slot))
                    if key in expected and expected[key] != expected_bit:
                        raise ValueError('conflicting direct-D output selection')
                    expected[key] = expected_bit
                continue
            selected = owner.get('attributes', {}).get('AGRV2K_OMUX_SEL')
            if selected is not None:
                selection = int(selected, 2) if isinstance(selected, str) else int(selected)
                packed = owner.get('attributes', {}).get('AGRV2K_BRAM_PINPACKED', '0')
                packed = int(packed, 2) if isinstance(packed, str) else int(packed)
                # The BRAM hint identifies the routed output pin, not whether
                # its register is active. Retain the independently reconstructed
                # F/Q value: a combinational F owner requires zero even when
                # pin packing assigned an explicit selector index.
                if packed != 1 or not 0 <= selection < 3 or selection != index % 3:
                    raise ValueError('unsupported explicit BRAM-output selection at %s' % owner_name)
            elif site == alternate_site or environment.get('AGAMEMNON_VENDOR_OUT_ALL'):
                if index % 3 != (1 if registered else 0):
                    raise ValueError('alternate F/Q presentation uses wrong output at %s' % owner_name)
                value = 1
            if feature in expected and expected[feature] != value:
                raise ValueError('conflicting F/Q selection for %s' % (feature,))
            expected[feature] = value
    return expected, len(unowned)


def compare_omux_selections(module, raw, feature_bits, environment=None):
    expected, unowned = expected_omux_selections(module, environment)
    mismatches = []
    for feature, value in expected.items():
        physical = feature_bits.get(feature)
        if physical is None:
            mismatches.append({'kind': 'omux_selection', 'feature': feature,
                               'expected': value, 'error': 'missing decoder feature'})
            continue
        byte, mask = physical
        if not 0 <= byte < len(raw):
            mismatches.append({'kind': 'omux_selection', 'feature': feature,
                               'expected': value, 'error': 'decoder bit outside image'})
            continue
        actual = int(bool(raw[byte] & mask))
        if actual != value:
            mismatches.append({'kind': 'omux_selection', 'feature': feature,
                               'expected': value, 'actual': actual,
                               'byte': byte, 'mask': mask})
    return len(expected), mismatches, unowned
