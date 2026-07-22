"""Declarative AGRV2K global/configuration-chain preamble emitter.

The first 164 raw bytes precede the tile frame grid. They are configuration
chain records, not a file header and not per-die calibration data. The release
profile below was recovered by corpus invariance and is emitted directly so a
build never inherits these bytes from its baseline image.
"""
from __future__ import annotations

import hashlib


PREAMBLE_LENGTH = 164

# Fabric-idle release profile: fixed descriptors, the qualified clk-0
# distribution-chain defaults, and a disabled (all-zero) PLL source chain.
IDLE_PROFILE = bytes.fromhex(
    "a20000200003412008020080200802008020080200802008020080200802008042a210842104010040100000080420802010820080200800001004010000100401084208042108421082010842080200802010820020080200802008020080200802008020080200802010842080420800000000a20000210000ee200000000000000000000000000000000000000000000000000000000000000000a20000000c2d7f20"
)

# Qualified HSE -> PLL source configuration for SYSCLK/HSE = 100/8 MHz.
CLOCK_DISTRIBUTION_100_8 = bytes((0x84, 0x20, 0x42))
PLL_SOURCE_100_8 = bytes.fromhex(
    "294000002000000000000001feff7fbfdfeff7fbfd0100524900000106a4"
)

REGIONS = (
    (0, 33, "leading_descriptor_and_idle", "reconstructed-fixed"),
    (33, 64, "global_setup", "reconstructed-fixed"),
    (64, 113, "clock_distribution", "qualified-profile"),
    (113, 124, "pll_descriptor", "reconstructed-fixed"),
    (124, 154, "pll_source", "qualified-parametric"),
    (154, 164, "trailer", "reconstructed-fixed"),
)


if len(IDLE_PROFILE) != PREAMBLE_LENGTH:
    raise RuntimeError("internal preamble profile has the wrong length")
if len(PLL_SOURCE_100_8) != 30:
    raise RuntimeError("internal PLL source profile has the wrong length")


def build(*, clocked=False, sysclk=100, hse=8):
    """Build a complete supported preamble without consulting a baseline."""
    raw = bytearray(IDLE_PROFILE)
    if clocked:
        from . import pll_emit

        pll_emit.require_supported_ratio(sysclk, hse)
        raw[83:86] = CLOCK_DISTRIBUTION_100_8
        raw[124:154] = PLL_SOURCE_100_8
        if (sysclk, hse) != (100, 8):
            pll_emit.apply_ratio(raw, sysclk, hse)
    return bytes(raw)


def apply(raw, *, clocked=False, sysclk=100, hse=8):
    """Replace the full preamble in a mutable raw image, atomically."""
    if len(raw) < PREAMBLE_LENGTH:
        raise ValueError("raw image is shorter than the 164-byte preamble")
    generated = build(clocked=clocked, sysclk=sysclk, hse=hse)
    raw[:PREAMBLE_LENGTH] = generated
    return generated


def describe(raw):
    """Return a stable audit report for an image's leading config chains."""
    if len(raw) < PREAMBLE_LENGTH:
        raise ValueError("raw image is shorter than the 164-byte preamble")
    actual = bytes(raw[:PREAMBLE_LENGTH])
    profiles = {"idle": IDLE_PROFILE}
    from . import pll_emit

    for sysclk, hse in pll_emit.SUPPORTED_RATIOS:
        profiles["pll-%d-%d" % (sysclk, hse)] = build(
            clocked=True, sysclk=sysclk, hse=hse
        )
    profile = next((name for name, value in profiles.items() if value == actual), "custom")
    regions = []
    for start, end, name, evidence in REGIONS:
        reference = IDLE_PROFILE[start:end]
        regions.append({
            "start": start,
            "end": end,
            "name": name,
            "evidence": evidence,
            "bytes_changed_from_idle": sum(
                left != right for left, right in zip(actual[start:end], reference)
            ),
        })
    return {
        "length": PREAMBLE_LENGTH,
        "sha256": hashlib.sha256(actual).hexdigest(),
        "profile": profile,
        "generated_profile": profile != "custom",
        "regions": regions,
    }
