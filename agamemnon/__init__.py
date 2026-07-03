"""Project AGaMEMnon — an open bitstream/P&R toolchain for the AGM AG32 / AGRV2K eFPGA.

Every layer here is reverse-engineered from AGM's tools and validated byte-for-byte against
af.exe (and on real silicon). No proprietary vendor binary in any runtime path.
"""
import os, sys

# The self-contained engine (agamemnon/engine/: lzw_codec, physmap, sel_byteexact, bitgen_seq,
# arch, ...) imports its modules by bare name; put the engine dir on sys.path so that works
# however the package is imported. This is the single source of truth — the old root-level
# duplicate modules were removed once the engine was vendored + proven byte-exact.
_ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

__version__ = "0.1.0"
