"""LogicTile control-input selector encoding for local and right-side RMUXes.

This is a geometry rule, not a route-admission decision. Callers must establish
that both endpoints belong to supported LogicTiles and bind the source to the
actual routed net. Other source banks remain unsupported here.
"""


def ctrlmux_source_bits(ctrlmux, source_index, source_dx=0, source_dy=0):
    """Return two asserted CFG_CTRLMUX indices for a checked input geometry.

    Source displacement is relative to the destination tile. The four muxes
    each own twelve bits. Their even/odd input lanes differ; sharing one mux
    among clock/reset consumers requires the same source, not merely the same
    selector pair on another mux.
    """
    values = (ctrlmux, source_index, source_dx, source_dy)
    if any(type(value) is not int for value in values):
        raise ValueError("control mux geometry requires integer indices and offsets")
    if ctrlmux not in range(4) or source_index not in range(96):
        raise ValueError("control mux or RMUX index outside LogicTile geometry")
    if source_dy != 0:
        raise ValueError("unsupported vertical control mux ingress")
    parity = ctrlmux % 2
    if source_dx == 0:
        if source_index % 6 != 4 + parity:
            raise ValueError("RMUX does not reach this local control mux lane")
        low, high = (source_index // 6) % 8, 10 + source_index // 48
    elif source_dx == 1:
        if source_index % 12 != 6 * parity:
            raise ValueError("RMUX does not reach this right-side control mux lane")
        low, high = source_index // 12, 9
    else:
        raise ValueError("unsupported horizontal control mux ingress")
    return 12 * ctrlmux + low, 12 * ctrlmux + high


def ctrlmux_input_bit_plan(tile, inputs, chipdb_root=None):
    """Plan set/clear bits for selected control muxes in supported LogicTiles.

    ``inputs`` maps CtrlMUX index to (source_x, source_y, RMUX_index).
    Only those muxes' twelve-bit fields are claimed. Shared clock/reset
    consumers must agree on one routed source before calling this function.
    No image mutation or ordinary-emission admission occurs here.
    """
    import json
    from pathlib import Path
    from agamemnon.engine import default_frame

    root = Path(chipdb_root) if chipdb_root is not None else default_frame.CHIPDB_ROOT
    anchors = json.loads((root / 'logictile_asyncmux3.json').read_text())
    if (not isinstance(tile, tuple) or len(tile) != 2
            or any(type(value) is not int for value in tile)):
        raise ValueError("control mux destination requires integer tile coordinates")
    x, y = tile
    if '%d,%d' % tile not in anchors:
        raise ValueError("control mux destination is not a supported LogicTile")
    selected = {}
    for mux, source in inputs.items():
        if (not isinstance(source, tuple) or len(source) != 3
                or any(type(value) is not int for value in source)):
            raise ValueError("control mux source requires integer tile and RMUX coordinates")
        sx, sy, index = source
        if '%d,%d' % (sx, sy) not in anchors:
            raise ValueError("control mux source is not a supported LogicTile")
        selected[mux] = set(ctrlmux_source_bits(mux, index, sx - x, sy - y))
    cells, _ = default_frame.load_logictile_template(root)
    locations = {}
    for (word, bank), name in cells.items():
        if not name.startswith('CFG_CTRLMUX['):
            continue
        index = int(name[len('CFG_CTRLMUX['):-1])
        if index in locations:
            raise ValueError("duplicate control mux configuration field")
        offset, bit = default_frame._cell_to_offset_bit(x, y, word, bank)
        if not default_frame.BODY_START <= offset < default_frame.CRC_OFFSET:
            raise ValueError("control mux configuration outside payload body")
        locations[index] = offset, 1 << bit
    if set(locations) != set(range(48)) or len(set(locations.values())) != 48:
        raise ValueError("incomplete or overlapping control mux configuration geometry")
    return {locations[index]: index in bits
            for mux, bits in selected.items() for index in range(12 * mux, 12 * (mux + 1))}
