"""Bind allocated asynchronous controllers to routed configuration segments.

This validates controller ingress/leaves and ownership, not the conductivity
of the upstream ordinary routing tree or silicon behavior. Emission admission
remains separate. No cell or signal names determine acceptance.
"""
from collections import defaultdict
from dataclasses import dataclass
import re

from .async_control_plan import AsyncControl, GROUND, TileAsyncPlan, async_control_bit_plan
from .ctrlmux_encoding import ctrlmux_input_bit_plan, ctrlmux_source_bits
from .shared_control import validate_module_shared_controls


def _reject(message):
    raise ValueError('async route: ' + message)


def _integer(value, label):
    if not isinstance(value, str) or not value or set(value) - {'0', '1'}:
        _reject('missing or malformed ' + label)
    return int(value, 2)


def _site(cell, kind):
    match = re.fullmatch(r'X(\d+)Y(\d+)_' + kind + r'(\d+)',
                         cell.get('attributes', {}).get('NEXTPNR_BEL', ''))
    if not match:
        _reject('missing or malformed placed ' + kind)
    return tuple(map(int, match.groups()))


def _wire(x, y, resource, index):
    return 'X%dY%d_%s%02d' % (x, y, resource, index)


def _routes(module):
    routes, owners = {}, {}
    for name, net in module.get('netnames', {}).items():
        text = net.get('attributes', {}).get('ROUTING')
        if text is None:
            continue
        if not isinstance(text, str):
            _reject('non-string ROUTING on ' + name)
        if not text:
            continue
        bits = net.get('bits', [])
        if len(bits) != 1 or type(bits[0]) is not int or bits[0] < 0:
            _reject('routed alias requires one integer signal bit')
        fields = text.split(';')
        if len(fields) % 3:
            _reject('ROUTING requires wire/PIP/strength triples')
        incoming, roots = {}, set()
        for wire, pip, strength in zip(fields[::3], fields[1::3], fields[2::3]):
            if (not wire or wire.strip() != wire or pip.strip() != pip
                    or strength not in {'0', '1', '2', '3', '4', '5', '6'}):
                _reject('invalid route token')
            if wire in incoming or wire in roots:
                _reject('multiple route records for one wire')
            if pip:
                pair = pip.split('.')
                if len(pair) != 2 or not pair[0] or pair[1] != wire:
                    _reject('PIP destination disagrees with route wire')
                incoming[wire] = pair[0]
            else:
                roots.add(wire)
        if len(roots) != 1:
            _reject('routed net requires exactly one root')
        reached = set(roots)
        pending = dict(incoming)
        while pending:
            ready = [dst for dst, src in pending.items() if src in reached]
            if not ready:
                _reject('disconnected or cyclic route')
            for dst in ready:
                reached.add(dst)
                del pending[dst]
        route = (frozenset(roots), frozenset(incoming.items()))
        if bits[0] in routes and routes[bits[0]] != route:
            _reject('signal aliases disagree about ROUTING')
        routes[bits[0]] = route
        for wire in reached:
            previous = owners.setdefault(wire, bits[0])
            if previous != bits[0]:
                _reject('different signals own routed wire ' + wire)
    return routes, owners


@dataclass(frozen=True)
class RoutedAsyncPlan:
    tiles: dict
    ctrlmux_inputs: dict
    writes: dict


def plan_routed_async_controls(module, chipdb_root=None):
    """Return configuration writes only after validating the whole composition.

    All registers in an allocated tile must select a compatible controller.
    Dynamic DIN ingress must be a modeled RMUX -> CtrlMUX -> TileAsyncMUX
    segment on the DIN signal. DOUT routes must contain exactly the local
    ARST leaves selected by their consumers. Ground slots have no routed net.
    Full upstream PIP/driver legality is the caller's separate responsibility.
    """
    cells = module.get('cells', {})
    requirements = validate_module_shared_controls(module)
    routes, owners = _routes(module)
    drivers, users = defaultdict(list), defaultdict(list)
    for name, cell in cells.items():
        for port, bits in cell.get('connections', {}).items():
            direction = cell.get('port_directions', {}).get(port)
            for bit in bits:
                if type(bit) is int:
                    if direction not in ('input', 'output'):
                        _reject('connected port has unsupported direction')
                    (drivers if direction == 'output' else users)[bit].append((name, port))
    controllers, outputs, inputs = {}, {}, {}
    for name, cell in cells.items():
        if cell.get('type') != 'AGRV2K_ASYNCCTRL':
            continue
        x, y, slot = _site(cell, 'ASYNCCTRL')
        if slot not in (0, 1) or (x, y, slot) in controllers:
            _reject('invalid or occupied controller site')
        mode = _integer(cell.get('parameters', {}).get('MODE'), 'controller MODE')
        ports = cell.get('connections', {})
        if set(ports) != {'DIN', 'DOUT'} or cell.get('port_directions') != {'DIN': 'input', 'DOUT': 'output'}:
            _reject('controller requires exactly DIN input and DOUT output')
        dout = ports['DOUT']
        if len(dout) != 1 or type(dout[0]) is not int or dout[0] < 0:
            _reject('controller requires a distinct DOUT signal')
        dout = dout[0]
        if drivers[dout] != [(name, 'DOUT')]:
            _reject('controller DOUT has another driver')
        if mode == 0:
            if ports['DIN'] or users[dout] or dout in routes:
                _reject('ground controller must have no DIN or routed DOUT consumers')
            control, mux = GROUND, None
        elif mode == 2:
            din = ports['DIN']
            if len(din) != 1 or type(din[0]) is not int or din[0] < 0 or din[0] == dout:
                _reject('controller requires separate bound DIN and DOUT')
            din = din[0]
            if len(drivers[din]) != 1 or din not in routes:
                _reject('controller DIN requires a single driver and routed ingress')
            incoming = dict(routes[din][1])
            terminal = _wire(x, y, 'TileAsyncMUX', slot)
            selected = incoming.get(terminal, '')
            match = re.fullmatch(r'X(\d+)Y(\d+)_CtrlMUX(\d+)', selected)
            if not match:
                _reject('controller DIN has no routed CtrlMUX selection')
            sx, sy, mux = map(int, match.groups())
            if (sx, sy) != (x, y) or mux not in (2 * slot, 2 * slot + 1):
                _reject('CtrlMUX selection belongs to another controller')
            source = re.fullmatch(r'X(\d+)Y(\d+)_RMUX(\d+)', incoming.get(selected, ''))
            if not source:
                _reject('CtrlMUX requires an explicit routed RMUX source')
            sx, sy, index = map(int, source.groups())
            ctrlmux_source_bits(mux, index, sx - x, sy - y)
            inputs.setdefault((x, y), {})[mux] = (sx, sy, index)
            control = AsyncControl(2, din)
        else:
            _reject('unsupported routed controller mode')
        controllers[x, y, slot] = (control, mux, name, dout)
        outputs[name] = set()
    selections = defaultdict(list)
    for name, requirement in requirements.items():
        cell = cells[name]
        ff = _integer(cell.get('parameters', {}).get('FF_USED'), 'FF_USED')
        if ff not in (0, 1):
            _reject('FF_USED must be zero or one')
        if not ff:
            continue
        x, y, z = _site(cell, 'SLICE')
        if z not in range(16):
            _reject('invalid register slice')
        allocated = any((x, y, slot) in controllers for slot in (0, 1))
        if not allocated and not requirement.active:
            continue
        slot = _integer(cell.get('attributes', {}).get('AGRV2K_ASYNC_CONTROLLER_INDEX'), 'controller index')
        controller = controllers.get((x, y, slot))
        if controller is None:
            _reject('register selects an absent controller')
        control, mux, controller_name, dout = controller
        if requirement.active:
            if control.mode != 2 or cell.get('connections', {}).get('ARST') != [dout] or cell.get('port_directions', {}).get('ARST') != 'input':
                _reject('active register does not use its selected controller DOUT')
            outputs[controller_name].add((name, 'ARST'))
        elif control != GROUND:
            _reject('inactive register requires a ground controller')
        selections[x, y].append((z, slot))
    expected_protected = set()
    tiles, writes = {}, {}
    for tile in sorted({key[:2] for key in controllers}):
        controls, muxes = [None, None], [None, None]
        for slot in (0, 1):
            value = controllers.get((*tile, slot))
            if value is None:
                continue
            control, mux, name, dout = value
            controls[slot], muxes[slot] = control, mux
            if control.mode == 2:
                expected_users = outputs[name]
                if not expected_users or set(users[dout]) != expected_users:
                    _reject('controller DOUT has absent or foreign consumers')
                root = _wire(*tile, 'alta_asyncctrl', slot)
                edges = frozenset((_wire(*tile, 'AsyncMUX', _site(cells[user], 'SLICE')[2]), root)
                                  for user, port in expected_users)
                if routes.get(dout) != (frozenset({root}), edges):
                    _reject('controller DOUT route does not exactly match local ARST leaves')
                expected_protected.update({root, _wire(*tile, 'TileAsyncMUX', slot)})
                expected_protected.update(dst for dst, src in edges)
        plan = TileAsyncPlan(tuple(controls), tuple(sorted(selections[tile])), tuple(muxes))
        bits = async_control_bit_plan(tile, plan, chipdb_root)
        bits.update(ctrlmux_input_bit_plan(tile, inputs.get(tile, {}), chipdb_root))
        if writes.keys() & bits.keys():
            _reject('tile configuration fields overlap')
        writes.update(bits)
        tiles[tile] = plan
    for wire in owners:
        if re.fullmatch(r'X\d+Y\d+_(?:TileAsyncMUX|alta_asyncctrl|AsyncMUX)\d+', wire) and wire not in expected_protected:
            _reject('orphan asynchronous route resource ' + wire)
    return RoutedAsyncPlan(tiles, inputs, writes)
