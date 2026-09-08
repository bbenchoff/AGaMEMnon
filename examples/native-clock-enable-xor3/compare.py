"""Compare actual routed slice use; timing and silicon qualification are separate."""
import argparse
from collections import Counter
import json
from pathlib import Path


def number(value):
    return int(value, 2) if isinstance(value, str) else int(value)


def inspect(path):
    document = json.loads(Path(path).read_text())
    cells = document['modules']['top']['cells'].values()
    slices = [cell for cell in cells if cell['type'] == 'GENERIC_SLICE']
    registers = [cell for cell in slices if number(cell['parameters'].get('FF_USED', 0))]
    native = [cell for cell in registers if cell.get('attributes', {}).get('AGRV2K_CLOCK_ENABLE_NET')]
    tiles = {cell['attributes']['NEXTPNR_BEL'].split('_SLICE')[0] for cell in slices}
    return dict(slices=len(slices), registers=len(registers), native_registers=len(native),
                occupied_tiles=len(tiles),
                native_input_modes=dict(Counter(cell['attributes'].get('AGRV2K_REGISTER_INPUT_MODE',
                                                                         'UNSPECIFIED') for cell in native)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_logic')
    parser.add_argument('native')
    args = parser.parse_args()
    data, native = inspect(args.data_logic), inspect(args.native)
    saved = data['slices'] - native['slices']
    print(json.dumps(dict(data_logic=data, native=native, slices_saved=saved,
                          slice_reduction_percent=100 * saved / data['slices'] if data['slices'] else None),
                     indent=2))
