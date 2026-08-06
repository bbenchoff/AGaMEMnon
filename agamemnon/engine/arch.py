"""nextpnr injected-global entry shim for the AGRV2K architecture."""

from agamemnon.engine.archgen import build


if "ctx" in globals() and "Loc" in globals():
    build(ctx, Loc)
