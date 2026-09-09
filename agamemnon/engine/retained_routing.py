"""Exact historical routing reproduction, never portable selector evidence."""
import hashlib
import json
from pathlib import Path

from . import retained_replay, routing_selectors


# This retained SERV checkpoint uses a subsequently withdrawn translation.
# Its working image is reproducible, but does not qualify this edge generally.
SERV_ROUTED_SHA256 = "4ffe1076ce65a9a2e0bbbdcbeb67900c6c6249367b3c4f7da41210fdec4563d2"
SERV_MODULE_SHA256 = "d77104e0c8a8e6a996ed62b24abbba182094944a67e97deb3805523ac6a2b7e4"
SERV_IMAGE_SHA256 = "abe1c97a44fb235c56d377f3060a74d2a22f99db76cabcdccd1749ffdb4ae5a0"
SERV_PRE_OWNER_SHA256 = "8f9c76bedcd7e9c684726bd9f1ac3889a435e62f399498aed4a9c68ba620dd7f"
SERV_PIPS = frozenset({"X18Y3_RMUX27.X18Y6_RMUX20"})
SERV_ENVIRONMENT = {
    "AGAMEMNON_DIRECT_D": "1", "AGAMEMNON_HSE": "8",
    "AGAMEMNON_LEFT_PAD_OUT": "1", "AGAMEMNON_SYSCLK": "25",
}


def withdrawn_pips(pips, clean_edges):
    return frozenset(pip for pip in pips
                     if routing_selectors.nonportable_translation(
                         clean_edges, *pip.split(".", 1)))


def authenticate(pips, clean_edges, routed_path, module, options):
    """Return allowed historical pips and mandatory final-image identity.

    Any change to the input checkpoint or module rejects the exception. The
    caller must enforce the returned image hash after all emission phases.
    """
    withdrawn = withdrawn_pips(pips, clean_edges)
    if not withdrawn:
        return frozenset(), None
    reason = "withdrawn selector translation requires an exact retained checkpoint"
    if withdrawn != SERV_PIPS:
        raise ValueError(reason + ": " + ", ".join(sorted(withdrawn)))
    source = Path(routed_path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    module_bytes = json.dumps(module, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if (hashlib.sha256(source).hexdigest() != SERV_ROUTED_SHA256 or
            hashlib.sha256(module_bytes).hexdigest() != SERV_MODULE_SHA256):
        raise ValueError(reason)
    for key, expected in SERV_ENVIRONMENT.items():
        if str(options.raw(key)) != expected:
            raise ValueError("retained routing environment mismatch at " + key)
    expected = SERV_PRE_OWNER_SHA256 if retained_replay.enabled(options) else SERV_IMAGE_SHA256
    return withdrawn, expected
