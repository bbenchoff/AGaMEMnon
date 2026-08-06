"""Compatibility exports for the migrated route-through feature.

New engine code imports :mod:`agamemnon.engine.features.route_through`.
"""

from .features.route_through import (  # noqa: F401
    FEATURE,
    RouteThroughFeature,
    RouteThroughPolicyError,
    complete_footprint_for_cell,
    load_footprints,
)


__all__ = [
    "FEATURE",
    "RouteThroughFeature",
    "RouteThroughPolicyError",
    "complete_footprint_for_cell",
    "load_footprints",
]
