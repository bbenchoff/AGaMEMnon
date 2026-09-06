"""Plan the two tile asynchronous controllers without admitting emission.

Controllers are primitives, not routing edges. Every registered slice needs a
selected controller, including slices whose asynchronous input stays low.
Physical ingress routing and silicon admission remain separate requirements.
"""
from dataclasses import dataclass
import re

from .shared_control import validate_module_shared_controls


@dataclass(frozen=True)
class AsyncControl:
    # Logical primitive modes: zero, one, Din, inverted Din.
    mode: int
    source_bit: object = None

    def __post_init__(self):
        if type(self.mode) is not int or self.mode not in range(4):
            raise ValueError("async control mode must be an integer from 0 to 3")
        if self.mode >= 2:
            if type(self.source_bit) is not int or self.source_bit < 0:
                raise ValueError("dynamic async control requires a bound source net")
        elif self.source_bit is not None:
            raise ValueError("constant async control must not claim a source net")

    def field_bits(self, controller):
        """Return the controller's asserted indices in CFG_TILEASYNCMUX.

        Reject unconnected dynamic inputs rather than reproducing vendor
        constant folding of an unspecified Din value.
        """
        if type(controller) is not int or controller not in (0, 1):
            raise ValueError("async controller index must be 0 or 1")
        local = ((3,), (), (2,), (2, 3))[self.mode]
        return tuple(4 * controller + bit for bit in local)


GROUND = AsyncControl(0)


@dataclass(frozen=True)
class TileAsyncPlan:
    controls: tuple
    # (slice index, controller index), sorted by slice index.
    selections: tuple

    @property
    def field_value(self):
        return sum(1 << bit for index, control in enumerate(self.controls)
                   for bit in control.field_bits(index))

    @property
    def slice_selector_value(self):
        return sum(controller << index for index, controller in self.selections)


def plan_tile_async_controls(assignments):
    """Allocate control identities for registered slices in one logic tile.

    Source and inversion are part of identity. An inactive register consumes
    the grounded controller; it cannot be placed on a driven control merely
    because it has no reset port. Combinational slices must not be supplied.
    """
    for index, control in assignments.items():
        if type(index) is not int or index not in range(16):
            raise ValueError("async slice index must be from 0 to 15")
        if not isinstance(control, AsyncControl):
            raise ValueError("async assignment requires a typed control")
    # Keep ordinary grounded-only tiles on controller zero. For mixed tiles,
    # allocate driven controls first and ground last, without using cell names.
    controls = tuple(sorted(set(assignments.values()),
                            key=lambda c: (c.mode < 2, c.mode,
                                           -1 if c.source_bit is None else c.source_bit)))
    if len(controls) > 2:
        raise ValueError("async tile needs %d controls, including inactive registers; capacity is 2"
                         % len(controls))
    indices = {control: index for index, control in enumerate(controls)}
    return TileAsyncPlan(controls, tuple((z, indices[control])
                                        for z, control in sorted(assignments.items())))


def plan_module_async_controls(module):
    """Plan placed register controls using the existing frontend protocol.

    This computes resource requirements only. It neither adds graph edges nor
    bypasses the active-clear refusal in the native engine and bitstream writer.
    """
    requirements = validate_module_shared_controls(module)
    tiles = {}
    for name, requirement in requirements.items():
        cell = module['cells'][name]
        try:
            ff_used = int(str(cell['parameters']['FF_USED']), 2)
        except (KeyError, TypeError, ValueError):
            raise ValueError("async planning requires a valid FF_USED on %r" % name)
        if ff_used not in (0, 1):
            raise ValueError("async planning requires FF_USED zero or one")
        if not ff_used:
            continue
        bel = cell.get('attributes', {}).get('NEXTPNR_BEL', '')
        match = re.fullmatch(r'X(\d+)Y(\d+)_SLICE(\d+)', bel)
        if not match:
            raise ValueError("async planning requires a placed slice for %r" % name)
        x, y, z = map(int, match.groups())
        assignments = tiles.setdefault((x, y), {})
        if z in assignments:
            raise ValueError("multiple registers occupy the same async slice")
        assignments[z] = AsyncControl(2, requirement.control_bit) if requirement.active else GROUND
    return {tile: plan_tile_async_controls(assignments)
            for tile, assignments in sorted(tiles.items())}
