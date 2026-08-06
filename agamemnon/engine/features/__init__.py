"""Feature registry for the strangler migration of the AGRV2K engine core."""

from __future__ import annotations

from .protocol import FeatureProtocol
from .bram import FEATURE as BRAM
from .route_through import FEATURE as ROUTE_THROUGH


FEATURES = (ROUTE_THROUGH, BRAM)


def validate_features(features=FEATURES):
    feature_ids = set()
    chipdb_owners = {}
    for feature in features:
        if not isinstance(feature, FeatureProtocol):
            raise TypeError("feature does not implement FeatureProtocol: %r" % (feature,))
        descriptor = feature.descriptor
        if descriptor.feature_id in feature_ids:
            raise ValueError("duplicate feature id %s" % descriptor.feature_id)
        feature_ids.add(descriptor.feature_id)
        for filename in descriptor.chipdb_files:
            previous = chipdb_owners.setdefault(filename, descriptor.feature_id)
            if previous != descriptor.feature_id:
                raise ValueError(
                    "chipdb file %s is owned by both %s and %s" %
                    (filename, previous, descriptor.feature_id)
                )
    return dict(chipdb_owners)


CHIPDB_OWNERS = validate_features()
