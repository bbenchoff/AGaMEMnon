"""Shared graph-profile rules for direct-D slice presentation."""

import re


def direct_d_sites(options):
    if not options.enabled("AGAMEMNON_DIRECT_D"):
        return set()
    raw = options.raw("AGAMEMNON_DIRECT_D_SITES")
    if not raw:
        return {(14, 11, z) for z in range(4, 8)}
    sites = set()
    for token in str(raw).split(";"):
        match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", token.strip())
        if not match:
            raise ValueError("invalid AGAMEMNON_DIRECT_D_SITES token %r" % token)
        sites.add(tuple(int(match.group(i)) for i in (1, 2, 3)))
    return sites


def direct_d_arch_sites(options):
    sites = direct_d_sites(options)
    if options.raw("AGAMEMNON_DIRECT_D_COMB_F2"):
        sites.discard(options.coordinates("AGAMEMNON_DIRECT_D_COMB_F2"))
    return sites
