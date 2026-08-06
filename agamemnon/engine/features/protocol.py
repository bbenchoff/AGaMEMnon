"""Shared contracts for independently owned architecture and bitstream features."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, MutableSequence, Optional, Protocol, Tuple, runtime_checkable


class EmissionPhase(str, Enum):
    CLEAR_BASELINE = "clear_baseline"
    LOGIC = "logic"
    ROUTING = "routing"
    CLOCKS = "clocks"
    IO = "io"
    MCU_EDGES = "mcu_edges"
    BRAM = "bram"
    PREAMBLE = "preamble"
    INTEGRITY = "integrity"


@dataclass(frozen=True)
class WritableRegion:
    """A declarative source for a feature's sparse or contiguous image region."""

    kind: str
    source: str
    byte_field: Optional[str] = None
    mask_field: Optional[str] = None


@dataclass(frozen=True)
class FeatureDescriptor:
    feature_id: str
    options: Tuple[str, ...]
    chipdb_files: Tuple[str, ...]
    writable_regions: Tuple[WritableRegion, ...]
    phase: EmissionPhase
    evidence: Tuple[str, ...]
    maturity: str
    architecture: str
    bitstream: str

    def __post_init__(self) -> None:
        if not self.feature_id:
            raise ValueError("feature_id must be non-empty")
        if self.maturity not in {"release", "experimental", "archival", "diagnostic"}:
            raise ValueError("unsupported feature maturity %r" % self.maturity)
        if len(set(self.chipdb_files)) != len(self.chipdb_files):
            raise ValueError("feature %s owns a chipdb file more than once" % self.feature_id)


@dataclass
class ArchitectureContext:
    ctx: Any
    loc: Any
    device: Any
    chipdb_root: Path
    options: Any


@dataclass
class BitstreamContext:
    image: MutableSequence[int]
    module: Mapping[str, Any]
    chipdb_root: Path
    options: Any
    ownership: Any = None
    state: Any = None


@runtime_checkable
class FeatureProtocol(Protocol):
    descriptor: FeatureDescriptor

    def add_architecture(self, context: ArchitectureContext) -> None:
        """Add this feature's wires, pips, and BELs to an architecture."""

    def clear_bitstream(self, context: BitstreamContext) -> int:
        """Clear this feature's complete owned surface before overlays."""

    def emit_bitstream(self, context: BitstreamContext) -> int:
        """Apply this feature's contribution and return its physical write count."""
