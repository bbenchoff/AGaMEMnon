"""Source-owned lane-1 modes for explicitly typed routed checkpoints.

Historical checkpoints retain their previous encoding. This module does not
admit sites or routing edges; a native producer must mark the new output model.
"""
import re

MODEL_ATTRIBUTE = "AGRV2K_SOURCE_TYPED_XBAR"
BEL = re.compile(r"X(\d+)Y(\d+)_SLICE(\d+)$")
PIP = re.compile(r"X(\d+)Y(\d+)_OMUX(\d+)\.X(\d+)Y(\d+)_(OMUX|IMUX|RMUX)(\d+)$")


def source_modes(module):
    """Map lane-1 owners to 0=LUT/F or 1=register/Q, refusing conflicts."""
    sites = {}
    drivers = {}
    for name, cell in module.get("cells", {}).items():
        if cell.get("type") != "GENERIC_SLICE":
            continue
        attrs = cell.get("attributes", {})
        if str(attrs.get(MODEL_ATTRIBUTE, "0")) != "1":
            continue
        match = BEL.fullmatch(attrs.get("NEXTPNR_BEL", ""))
        if match is None:
            raise ValueError("typed crossbar cell has no physical BEL: " + name)
        site = tuple(map(int, match.groups()))
        if site in sites:
            raise ValueError("multiple typed cells occupy crossbar site %s" % (site,))
        sites[site] = name
        for port, mode in (("F", 0), ("Q", 1)):
            bits = cell.get("connections", {}).get(port, [])
            if not bits:
                continue
            if len(bits) != 1 or not isinstance(bits[0], int):
                raise ValueError("typed crossbar output must have one signal bit")
            if bits[0] in drivers:
                raise ValueError("ambiguous typed crossbar output driver")
            drivers[bits[0]] = (site, mode)
    if not sites:
        return {}
    modes = {}
    for net in module.get("netnames", {}).values():
        for token in net.get("attributes", {}).get("ROUTING", "").split(";"):
            match = PIP.fullmatch(token)
            if match is None:
                continue
            x, y, index, dx, dy, family, target = match.groups()
            x, y, index, dx, dy, target = map(int, (x, y, index, dx, dy, target))
            bridge = (family == "OMUX" and (x, y) == (dx, dy)
                      and index % 3 == 2 and target == index - 1)
            if index % 3 != 1 and not bridge:
                continue
            owner = (x, y, index // 3)
            if owner not in sites:
                continue
            bits = net.get("bits", [])
            driver = drivers.get(bits[0]) if len(bits) == 1 else None
            if driver is None or driver[0] != owner:
                raise ValueError("lane-1 route has no matching typed source driver: " + token)
            mode = driver[1]
            if owner in modes and modes[owner] != mode:
                raise ValueError("F and Q compete for one lane-1 output at %s" % (owner,))
            modes[owner] = mode
    return modes
