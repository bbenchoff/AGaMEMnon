"""Inventory placed slices and inter-tile nets; does not infer move legality."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

BEL = re.compile(r"^(X\d+Y\d+)_SLICE(\d+)$")


def active(value):
    if isinstance(value, str) and set(value) <= {'0', '1'}:
        return bool(int(value or '0', 2))
    return bool(value)


def analyze(document):
    tiles = defaultdict(list)
    nets = defaultdict(set)
    cells = []
    for module_name, module in document['modules'].items():
        for name, cell in module.get('cells', {}).items():
            if cell['type'] != 'GENERIC_SLICE':
                continue
            attrs = cell.get('attributes', {})
            bel = attrs.get('NEXTPNR_BEL', attrs.get('BEL', ''))
            match = BEL.fullmatch(bel)
            if not match:
                raise ValueError(f'unplaced slice {module_name}/{name}: {bel!r}')
            tile, slot = match.group(1), int(match.group(2))
            params = cell.get('parameters', {})
            record = dict(module=module_name, name=name, tile=tile, slot=slot,
                          register=active(params.get('FF_USED', 0)),
                          native_enable=(active(params.get('FF_USED', 0)) and
                                         'AGRV2K_CLOCK_ENABLE_NET' in attrs),
                          attributes=attrs, parameters=params)
            tiles[tile].append(record)
            cells.append(record)
            for port, bits in cell.get('connections', {}).items():
                if port == 'CLK':
                    continue
                for bit in bits:
                    if isinstance(bit, int):
                        nets[(module_name, bit)].add((tile, name, port))
    rows = []
    for tile, occupants in sorted(tiles.items()):
        slots = [c['slot'] for c in occupants]
        if len(set(slots)) != len(slots):
            raise ValueError('duplicate occupied slot in ' + tile)
        crossings = [key for key, users in nets.items()
                     if tile in {u[0] for u in users} and len({u[0] for u in users}) > 1]
        rows.append(dict(tile=tile, slices=len(occupants),
                         registers=sum(c['register'] for c in occupants),
                         slots=sorted(slots), empty_slots=sorted(set(range(16))-set(slots)),
                         incident_intertile_data_nets=len(crossings),
                         cells=[c['name'] for c in occupants]))
    return dict(slices=len(cells), occupied_tiles=len(rows),
                cells_per_tile=len(cells)/len(rows) if rows else 0,
                occupancy_histogram=dict(sorted(Counter(r['slices'] for r in rows).items())),
                tiles=rows, cells=cells,
                scope='Inventory only. Empty slots are not asserted legal or simultaneously routable. '
                      'Placed BEL attributes are not themselves proof of original hard constraints.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('routed', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    data = a.routed.read_bytes()
    result = analyze(json.loads(data))
    result['input_sha256'] = hashlib.sha256(data).hexdigest()
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('slices', 'occupied_tiles', 'cells_per_tile', 'occupancy_histogram')}))


if __name__ == '__main__':
    main()
