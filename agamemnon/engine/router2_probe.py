"""Capability probe for the configured nextpnr's ``router2`` (AG32-Docs TASK_QUEUE.md queue G,
G5 layer 1 -- "make AGaMEMnon immune however it is installed").

``AGAMEMNON_UARCH_NEXTPNR`` can point at any binary a user or CI job has lying around, including a
stock nextpnr build with none of AGaMEMnon's local fixes. A ``--version`` string cannot distinguish
a patched build from an unpatched one at the same upstream commit: the router2 constant-net
reservation defect (see ``AG32-Docs/NEXTPNR_ROUTER2_BUG.md``) was fixed as a *local, uncommitted*
patch to a pinned checkout, so ``git describe`` is identical before and after the fix. Detecting the
fix needs a behavioural probe: actually exercise the router and see whether it exhibits the defect.

STATUS OF THE BUNDLED PROBE (read before trusting a "buggy" verdict) --------------------------

This module ships the full run-once-and-cache mechanism -- identity keying, the persistent cache,
and the fail/warn/pass decision policy -- fully working and unit-tested against injected fake probe
runners. It does **not** ship a working synthetic trigger for the actual defect, and says so rather
than pretending otherwise. Reasoning, established by reading (not guessing) how this repo's nextpnr
is built and what the defect actually requires:

  1. The real production binary (``agamemnon/engine/uarch/agrv2k/build.sh``) is built with
     ``-DBUILD_PYTHON=OFF``. The obvious approach -- a tiny ``--pre-pack`` Python arch -- is not an
     option against the actual binary users point ``AGAMEMNON_UARCH_NEXTPNR`` at.
  2. The only synthetic device graph compiled into that same binary without Python is the
     ``--uarch example`` viaduct fixture nextpnr ships in-tree (``generic/viaduct/example/``,
     unconditionally listed in ``generic/CMakeLists.txt`` alongside ``agrv2k``). It is usable
     without Python or yosys (a hand-written JSON netlist is enough) and is a legitimate vehicle for
     a *general* "can this router complete an ordinary multi-hop route at all" sanity check.
  3. It is **not** a vehicle for reproducing the *specific* known defect. Per
     ``AG32-Docs/NEXTPNR_ROUTER2_BUG.md``, that defect requires a device graph where a
     wide-fanout packer-constant net's reservation walk can permanently claim a wire that is also
     the *sole* single-branch corridor for a real net -- i.e. a genuine chokepoint. The example
     fixture's mesh is a dense, richly cross-connected reference topology (that is the point of it)
     and does not have one; engineering an artificial one would require editing
     ``third_party/nextpnr/**`` (out of scope here and off-limits per this task's constraints) or a
     new custom viaduct uarch (same constraint). The document that pinned the root cause explicitly
     lists a validated synthetic minimal reproducer as **not yet built** ("Not yet established", item
     3) -- future work (queue G's G3/G4), not something this task can respond to without a real
     nextpnr binary to iterate against, which this task was explicitly told not to run.

Consequently the bundled default probe (``run_example_fixture_probe``) can only ever return
``"ok"`` (routed a genuine multi-hop case) or ``"inconclusive"`` (crashed, produced unexpected
output, or timed out) -- **never** ``"buggy"``. It
is shipped anyway because it is real, if partial, protection: it catches a configured "nextpnr" that
cannot do basic viaduct routing at all (wrong binary, wrong flags, ABI mismatch, disabled uarch
registration), which is a much more common misconfiguration than the specific reservation defect,
and it validates the caching/identity machinery end-to-end today rather than leaving it dormant.

The moment queue G's synthetic minimal reproducer exists, wire it in via ``probe_fn=`` (see
``check_router2``) to upgrade this from "sanity check" to "defect detector"; the cache/identity/
decision-policy plumbing below does not need to change.

FAIL VS WARN -------------------------------------------------------------------------------------

Given a probe run, the decision is:

  * verdict "buggy" (confirmed defect signature) -> **fail the build** (loud, specific, naming the
    defect and pointing at the doc), overridable via ``AGAMEMNON_ROUTER2_PROBE_MODE=warn`` or
    ``=off``. Rationale: this exact category of mistake -- "a warning nobody reads" -- is how the
    BRAM-lowering signal got lost the same night this defect was found (see the goal docs). A
    confirmed hit means every subsequent unroutable-arc report from this binary is now suspect, and
    letting the build proceed to fail obscurely later, instead of failing clearly now, reproduces
    the exact multi-hour misattribution this whole effort exists to prevent. An explicit,
    documented override exists because a purely behavioural heuristic can misfire and a hard,
    silent, unconditional block would be worse than the defect it guards against.
  * verdict "inconclusive" (probe itself could not run cleanly) -> **warn, do not fail**. Blocking
    every build whenever the probe has a hiccup (sandboxing, a stricter/older nextpnr rejecting a
    flag, disk pressure on the cache) would be a worse regression than the defect it is meant to
    catch. The warning is unmistakable and specific (never a generic "something went wrong").
  * verdict "ok" -> proceed silently (a one-line ``[build]`` confirmation only, matching this
    codebase's existing preflight logging style; no warning fatigue for the common case).
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from typing import Callable, List, NamedTuple, Optional

PROBE_VERSION = 1  # bump to invalidate every cached verdict if the probe logic changes meaning
DOC_POINTER = "AG32-Docs/NEXTPNR_ROUTER2_BUG.md"

# Wide open on purpose: this only ever gates a routing *sanity* result today (see module docstring),
# never a confirmed defect, so a conservative default of "enforce" costs nothing yet and is the
# correct default to have already wired up for the day a real fixture lands.
_VALID_MODES = ("enforce", "warn", "off")


class ProbeResult(NamedTuple):
    verdict: str          # "ok" | "buggy" | "inconclusive" | "skipped"
    detail: str
    cached: bool


class ProbeRunOutcome(NamedTuple):
    """What a probe runner callable reports for one actual invocation (not cached)."""
    verdict: str           # "ok" | "buggy" | "inconclusive"
    detail: str


def _default_cache_path() -> str:
    override = os.environ.get("AGAMEMNON_ROUTER2_PROBE_CACHE")
    if override:
        return override
    base = os.environ.get("XDG_CACHE_HOME") or os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "agamemnon", "router2_probe_cache.json")


def _resolve_binary_path(argv: List[str], env: Optional[dict]) -> Optional[str]:
    if not argv:
        return None
    candidate = argv[0]
    path_env = (env or {}).get("PATH")
    resolved = shutil.which(candidate, path=path_env) if path_env is not None else shutil.which(candidate)
    return resolved or (candidate if os.path.isfile(candidate) else None)


def binary_identity(argv: List[str], env: Optional[dict] = None) -> str:
    """A cache key identifying "this exact nextpnr binary", cheaply.

    Preferred identity is (resolved absolute path, mtime, size) -- cheap to compute (a single
    ``os.stat``, no file content read) and good enough: a binary replaced in place with identical
    size and mtime is an extremely rare deployment accident, not a case worth reading potentially
    large binaries on every single build invocation to guard against.

    A WSL-style invocation (``wsl.exe ... <path>``) or a bare command not resolvable to a local
    file (e.g. only meaningful inside a container/remote shell this process cannot stat) falls back
    to keying on the literal argv -- the cache still works (avoids re-probing identical invocations)
    but will not notice a same-path binary silently replaced. ``AGAMEMNON_ROUTER2_PROBE_FORCE=1`` or
    bumping ``PROBE_VERSION`` are the escape hatches for that gap.
    """
    resolved = _resolve_binary_path(argv, env)
    if resolved and os.path.isfile(resolved):
        try:
            st = os.stat(resolved)
            return "stat:%s:%d:%d" % (os.path.normcase(os.path.abspath(resolved)), st.st_mtime_ns, st.st_size)
        except OSError:
            pass
    return "argv:" + hashlib.sha256("\x1f".join(argv).encode("utf-8", "surrogateescape")).hexdigest()


def binary_identity_by_hash(path: str) -> str:
    """An alternative, content-addressed identity for callers that want it (e.g. a CI job that
    always wants to detect a same-path binary swap). Not used by default: see ``binary_identity``.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _load_cache(cache_path: str) -> dict:
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _store_cache(cache_path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        tmp = cache_path + ".tmp-%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, cache_path)
    except OSError:
        pass  # a cache write failure must never fail a build


def probe_router2(
    argv: List[str],
    env: Optional[dict],
    probe_fn: Callable[[List[str], Optional[dict]], ProbeRunOutcome],
    *,
    cache_path: Optional[str] = None,
    force: bool = False,
) -> ProbeResult:
    """Run (or reuse a cached result of) ``probe_fn`` against the configured nextpnr ``argv``.

    ``probe_fn`` is required and does the actual work of invoking nextpnr; it is always injected
    (never hard-coded here) so this function's caching/identity/decision-policy logic is fully unit
    testable without a real nextpnr binary, and so a future real defect-detecting fixture is a
    drop-in replacement with no change to this function. See ``run_example_fixture_probe`` for the
    bundled sanity-only implementation, and the module docstring for why it is not a defect detector
    yet.
    """
    cache_path = cache_path or _default_cache_path()
    key = binary_identity(argv, env)
    # Always load the *whole* cache (it holds entries for other binaries too) even when
    # bypassing the lookup for this key -- overwriting it with a single-entry dict on every
    # forced re-probe would silently discard every other binary's cached verdict.
    cache = _load_cache(cache_path)
    entry = cache.get(key)
    if entry and not force and entry.get("probe_version") == PROBE_VERSION:
        return ProbeResult(entry.get("verdict", "inconclusive"), entry.get("detail", ""), True)

    try:
        outcome = probe_fn(argv, env)
        verdict, detail = outcome.verdict, outcome.detail
    except Exception as exc:  # the probe itself must never crash the build it is protecting
        verdict, detail = "inconclusive", "probe runner raised %s: %s" % (type(exc).__name__, exc)

    if verdict not in ("ok", "buggy", "inconclusive"):
        verdict, detail = "inconclusive", "probe runner returned an unrecognized verdict %r" % (verdict,)

    cache[key] = {"verdict": verdict, "detail": detail, "probe_version": PROBE_VERSION,
                  "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _store_cache(cache_path, cache)
    return ProbeResult(verdict, detail, False)


def check_router2(
    argv: List[str],
    env: Optional[dict],
    *,
    probe_fn: Optional[Callable[[List[str], Optional[dict]], ProbeRunOutcome]] = None,
    mode: Optional[str] = None,
    cache_path: Optional[str] = None,
) -> ProbeResult:
    """The single call site ``agamemnon/cli.py`` uses.

    ``mode`` (or ``env["AGAMEMNON_ROUTER2_PROBE_MODE"]``, default ``"enforce"``) controls what a
    "buggy" verdict does; see the module docstring's "FAIL VS WARN" section. ``mode="off"`` skips
    the probe entirely (verdict ``"skipped"``).

    ``probe_fn`` defaults to ``get_default_probe_fn()`` (today: ``run_example_fixture_probe``, a
    real sanity check that can never itself return "buggy" -- see the module docstring). The
    ``active_probe_fn is None`` guard below is defense in depth / a seam for tests and for a future
    where the default is deliberately unregistered again: callers must not assume a probe always
    runs. When it does not, this returns ``verdict="skipped"`` rather than fabricating a result, and
    callers should treat "skipped" as silent (not a warning): it reflects a known, documented scope
    limit, not a runtime problem.
    """
    resolved_mode = (mode or (env or {}).get("AGAMEMNON_ROUTER2_PROBE_MODE") or "enforce").lower()
    if resolved_mode not in _VALID_MODES:
        resolved_mode = "enforce"
    if resolved_mode == "off":
        return ProbeResult("skipped", "AGAMEMNON_ROUTER2_PROBE_MODE=off", False)
    active_probe_fn = probe_fn or get_default_probe_fn()
    if active_probe_fn is None:
        return ProbeResult("skipped", "no validated router2 defect fixture is wired up yet "
                                       "(see %s item 3)" % DOC_POINTER, False)
    force = str((env or {}).get("AGAMEMNON_ROUTER2_PROBE_FORCE", "")).strip() in ("1", "true", "yes")
    return probe_router2(argv, env, active_probe_fn, cache_path=cache_path, force=force)


def get_default_probe_fn():
    """The fixture ``check_router2`` uses when the caller does not supply one.

    Returns the bundled sanity-only example-fixture probe. It is real and runs against the exact
    configured binary, but -- see the module docstring -- it structurally cannot produce a "buggy"
    verdict; it can only confirm basic viaduct routing capability or flag "inconclusive". Swap in a
    real defect-detecting fixture here once one exists (queue G, G4).
    """
    return run_example_fixture_probe


# ---- the bundled sanity-only probe (see module docstring: not a defect detector) ------------------

_EXAMPLE_SRC_BEL = "X2/Y2/SLICE0_LUT"
_EXAMPLE_DST_BEL = "X29/Y29/SLICE0_LUT"


def _example_fixture_json() -> str:
    """A hand-written (no yosys, no Python-in-nextpnr) netlist for nextpnr's own bundled
    ``--uarch example`` viaduct fixture: two LUT4 cells, forced by NEXTPNR_BEL onto far corners of
    its 32x32 grid, joined by exactly one net. Routing this exercises a genuine multi-hop path
    through the example mesh's local-wire interconnect (dozens of tile hops apart), not a same-tile
    or adjacent-tile trivial case.

    LUT4 port names/types and the "X<x>/Y<y>/SLICE<z>_LUT" bel-name format are taken directly from
    ``third_party/nextpnr/generic/viaduct/example/example.cc`` (``constids.inc``, ``add_slice_bels``,
    ``ViaductHelpers::xy_id`` + ``generic/arch.h``'s ``/`` name delimiter) -- not guessed. Neither
    cell binds a DFF, so ``isBelLocationValid``'s ``slice_valid`` (only checked when both a LUT and a
    FF are bound at the same site) is unconditionally true, and ``pack()``'s IOB-trim/constant-
    replace/LUT-FF-pairing passes are all no-ops for a two-LUT, no-port, no-constant netlist.
    """
    def lut(bel, out_bit, in_bit):
        return {
            "hide_name": 0,
            "type": "LUT4",
            "parameters": {"INIT": "1111111111111111"},
            "attributes": {"NEXTPNR_BEL": bel, "BEL_STRENGTH": "1"},
            "port_directions": {"I[0]": "input", "I[1]": "input", "I[2]": "input",
                                 "I[3]": "input", "F": "output"},
            "connections": {
                "I[0]": [in_bit] if in_bit is not None else [],
                "I[1]": [], "I[2]": [], "I[3]": [],
                "F": [out_bit] if out_bit is not None else [],
            },
        }

    module = {
        "attributes": {"top": 1},
        "ports": {},
        "cells": {
            "u_src": lut(_EXAMPLE_SRC_BEL, out_bit=2, in_bit=None),
            "u_dst": lut(_EXAMPLE_DST_BEL, out_bit=None, in_bit=2),
        },
        "netnames": {
            "probe_net": {"hide_name": 0, "bits": [2], "attributes": {}},
        },
    }
    return json.dumps({"modules": {"top": module}})


def run_example_fixture_probe(argv: List[str], env: Optional[dict]) -> ProbeRunOutcome:
    """Route the fixture above through the configured binary with ``--router router2``.

    Never raises: any failure to even start the process is reported as ``"inconclusive"``.

    Uses plain ``subprocess.run`` rather than ``agamemnon.cli._run_child`` (this module is engine
    code; importing from ``cli`` would invert the package's layering) -- its Windows-only
    kill-on-parent-close Job Object is a defence against a build the user cancels leaving a
    long-lived tool running, which does not apply here: this call is short and already bounded by
    its own explicit ``timeout=``.
    """
    import tempfile

    from agamemnon.engine.router2_diagnostics import parse_last_route_arc_failure

    try:
        with tempfile.TemporaryDirectory(prefix="agamemnon_router2_probe_") as tmp:
            json_path = os.path.join(tmp, "probe.json")
            out_path = os.path.join(tmp, "probe_routed.json")
            with open(json_path, "w", encoding="utf-8") as fh:
                fh.write(_example_fixture_json())
            cmd = list(argv) + ["--uarch", "example", "--json", json_path,
                                 "--write", out_path, "--router", "router2"]
            try:
                result = subprocess.run(
                    cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=60,
                )
            except subprocess.TimeoutExpired:
                return ProbeRunOutcome("inconclusive", "router2 probe fixture timed out after 60s")
            except OSError as exc:
                return ProbeRunOutcome("inconclusive", "could not start nextpnr (%s: %s)"
                                        % (type(exc).__name__, exc))
            log = result.stdout or ""
            if result.returncode == 0 and "Routing complete" in log:
                return ProbeRunOutcome("ok", "routed the 27-tile example-fixture sanity case cleanly")
            # NOTE: this bundled fixture cannot legitimately produce a "buggy" verdict (see the
            # module docstring) -- its mesh has no chokepoint for the known reservation defect to
            # bite on. Any non-clean result here (including a "Failed to route arc" message) is
            # reported as inconclusive: it may be a genuine router problem, but this fixture cannot
            # attribute it to the specific known defect, so it must not claim to.
            failure = parse_last_route_arc_failure(log)
            tail = log.strip()[-500:]
            if failure is not None:
                return ProbeRunOutcome(
                    "inconclusive",
                    "example-fixture sanity case reported %r unroutable (exit %d) -- this fixture "
                    "cannot confirm whether that is the known reservation defect; see %s"
                    % (failure.raw, result.returncode, DOC_POINTER))
            return ProbeRunOutcome("inconclusive",
                                    "example-fixture sanity case did not route cleanly "
                                    "(exit %d): %s" % (result.returncode, tail))
    except Exception as exc:  # defensive: a probe must never raise into the caller
        return ProbeRunOutcome("inconclusive", "probe fixture raised %s: %s" % (type(exc).__name__, exc))
