#!/usr/bin/env python3
"""Round-trip equivalence check for AGaMEMnon routed netlists.

For every retained routed-JSON artifact in ``qualification/pack_regression.json``
this tool:

  1. Packs the routed JSON to a bitstream with the exact CLI invocation and
     per-artifact environment used by ``tests/test_qualified_pack_regression.py``
     (``python -m agamemnon.cli pack <routed.json> <out.bin>``).
  2. Decodes the produced image back into named features, using
     ``agamemnon.engine.bitstream_inspect``/``agasc`` (the shipped
     ``.agasc`` feature tables) and, separately, ``agamemnon.engine.lzw_codec``
     to independently re-decompress the flash-oriented ``.comp`` sidecar.
  3. Reconstructs, directly from the routed JSON's cell parameters and every
     net's ``ROUTING`` attribute, the subset of the feature set we can predict
     *without* re-running the packer, and diffs it against what decode
     produced.
  4. Reports, per artifact and in aggregate: how many features were
     COMPARED, how many MATCHED, how many MISMATCHED, and how many fall in a
     class this tool declines to check at all (UNRECOVERABLE) -- with the
     reason.

================================================================================
CRITICAL CAVEAT -- READ BEFORE TRUSTING A GREEN RESULT
================================================================================
A round trip that decodes with the SAME table the encoder used to encode
proves *self-consistency*, not *silicon correctness*. If chipdb table
``pips_full.csv`` has row X wrong, the encoder writes bit B for pip P, and the
decoder -- consulting the identical row X -- reports "pip P looks correctly
encoded" by reading bit B right back. A shared misunderstanding of the
silicon survives the round trip; both directions agree while both are wrong.
Only an independent oracle (silicon readback, a hand-derived truth table, a
second, differently-sourced encoding) can catch that class of bug. This tool
is explicit about where it is, and is not, using an independent oracle:

  INDEPENDENT of the encoder's chipdb tables (this really does catch
  encoder/pipeline bugs, not just table bugs):
    * CRC-32/BZIP2 image integrity (``agasc.crc32_bzip2`` is a fixed
      algorithm, not a data table; it covers all 99,932 payload bytes at
      once).
    * The LZW compressed-sidecar round trip (``lzw_codec`` is a fixed
      algorithm; this exercises the exact bytes written to flash).
    * LUT truth-table (``INIT``) bits of every placed ``GENERIC_SLICE`` /
      ``AGRV2K_DUAL_LUT_CONST`` cell (except explicit route-throughs -- see
      below). ``agamemnon.engine.physmap`` is a closed-form *geometric
      formula* (``init0_byte``/``init_bit_pos``), derived independently of
      ``agamemnon/engine/features/routing.py``'s selector tables and of
      ``agamemnon/chipdb/slice_cfg.csv`` (which does not even carry LUT bits
      -- see "NOT RECOVERABLE" below). ``agamemnon/engine/features/core_logic.py``
      calls the exact same formula, so this still shares *code*, but it
      shares a small, auditable arithmetic function rather than an opaque,
      row-by-row lookup table: a bug in the formula would misplace LUT bits
      *systematically* across many tiles, which is a much easier class of bug
      to notice than one wrong row in a 276,835-row CSV.

  SHARED with the encoder (a green result here bounds the check's value to
  self-consistency, not correctness):
    * "mux group presence": for every net's ``ROUTING`` attribute, every
      destination-side ``RMUX``/``IMUX``/``OMUX`` group and every
      ``BBMUXE``/``BBMUXW``/``BBMUXS`` instance is expected to
      assert *some* bit in its own selector group. Naming the group
      (``CFG_RMUX<n>`` etc.) at all requires the same physical-bit tables
      (``pips_full.csv``, ``pips_mcuedge.csv``) the encoder consults, via
      ``agasc.load_feature_map`` on the decode side. This check is
      deliberately coarse (presence, not identity) precisely because the
      *specific source* selected within a group cannot be independently
      re-derived without the encoder's own selector-pair tables
      (``RoutingSelectorTables``/admission data) -- see below.

  NOT RECOVERABLE / NOT ATTEMPTED (an honest negative, not a bug):
    * *Which* upstream wire a mux group selects. Decoding a raw image only
      ever tells you "these two bits in this ten/twelve-wide block are set";
      turning that back into "pip P was chosen" requires the identical
      arbitration table the encoder used to decide the codeword in the first
      place. There is no independent oracle for this in the codebase, so no
      round trip -- however elaborate -- can certify it. Silicon readback is
      the only real check (see AG32-Docs, the vendor RE workbench).
    * LUT truth-table bits of cells with ``AGRV2K_ROUTE_THROUGH`` set: their
      bits are owned by a separate, chipdb-table-driven feature
      (``features/route_through.py``) with its own qualified footprint, not
      by the ``core_logic``/``physmap`` formula this tool re-derives.
    * BRAM cell configuration (``ALTA_BRAM9K``, via ``bram_cell.csv``) and IO
      pad configuration (``GENERIC_IOB``, via ``pips_io.csv``): both are
      shared, table-driven, and this tool only *counts* their presence; it
      does not attempt to predict their bits. Same limitation class as the
      general routing crossbar, just not implemented here.
    * Any raw byte outside all five ``agasc`` feature tables at all (the
      preamble, the still-unmapped tail, etc.) -- reported as
      ``unknown_set_bits`` by ``bitstream_inspect``. This is unmapped, full
      stop; nobody's table names it.
    * Destination mux families this tool does not model at all:
      ``ClkMUX``/``TileClkMUX``/``TileClkEnMUX``/``KMUX``/``TMUX``/
      ``CARRYIN``/``CARRYOUT``/``IOMUX``/``SeamMUX`` (owned by the
      clocks/carry/physical_io features, each with its own encoding), and the
      known no-config pass-through wire families
      ``InputMUX``/``BufMUX``/``SinkMUXPseudo`` (``routing.py``'s own
      ``NOCFG`` tuple -- these destinations never own a selector bit at all,
      by construction, so their absence from the decoded feature set is not
      a mismatch). ``SeamMUX`` looks, at first glance, exactly like
      ``BBMUXE``/``BBMUXW``/``BBMUXS`` (``pips_mcuedge.csv`` carries the same
      per-instance ``SeamMUX0``.. rows) but is a trap: it is a clock-tree
      mux, and ``features/clocks.py`` encodes it as a single
      ``CFG_SEAMMUX`` cell at a fixed, silicon-qualified constant selector
      (``registry.CONSTANTS["clock_seam_selector"]`` == 5), completely
      decoupled from the specific instance index named in any net's
      ``ROUTING`` attribute. Found empirically while building this tool
      (every shipped SERV design's clock net names an instance like
      ``X13Y4_SeamMUX01``, which never appears verbatim in the decoded
      feature set): treating that instance number as the feature name is
      simply the wrong table.
    * Pad-feed nets: any net whose ``ROUTING`` tree reaches an ``IOMUX`` node
      is a pad-feed/pad-output path, and the RMUX hop that feeds it resolves
      through ``features/physical_io.py``'s own vendor-harvested
      ``padfeed_exact``/``padfeed_unowned`` codeword table, which can
      legitimately land its selector bits on a *different* tile than the
      naive destination node name implies. Found empirically while building
      this tool: a pad-feed hop into ``X19Y13_RMUX04`` (on
      ``carry_seam_comb_routed.json``) encodes at ``X18Y13``'s
      ``CFG_RMUX0[26,27]``, not at ``X19Y13`` at all. This tool excludes
      whole pad-feed nets from the mux-group presence check rather than
      report that indirection as a false mismatch (see
      ``expected_mux_groups``); it does not attempt to verify pad-feed
      codewords by any other means.

In short: this tool proves the packer is internally consistent end to end
(pack -> compress -> decompress -> decode reproduces what was asked for) and
independently proves LUT logic + image integrity. It does NOT prove the
general fabric interconnect is encoded to the *correct* physical wire --
that would require an oracle this codebase does not have outside silicon.

Usage:
    python tools/roundtrip_check.py                  # every corpus artifact
    python tools/roundtrip_check.py --limit 5         # first 5 (smoke test)
    python tools/roundtrip_check.py --artifact qualification/foo_routed.json
    python tools/roundtrip_check.py --json report.json  # also dump full JSON
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agamemnon.engine import agasc, bitstream_inspect, lzw_codec, physmap  # noqa: E402

CHIPDB = ROOT / "agamemnon" / "chipdb"
MANIFEST_PATH = ROOT / "qualification" / "pack_regression.json"

# Mirrors agamemnon/engine/features/routing.py::NPG -- the number of
# selectable-source SUB-GROUPS per crossbar family. This is architectural
# metadata (how the physical fan-in is partitioned), not an admission
# decision, so reproducing the constant here does not smuggle in the
# encoder's arbitration logic.
NPG = {"RMUX": 6, "IMUX": 4, "OMUX": 3}

# Destination-side mux families whose *group* (not individual source) this
# tool can name using the same physical-bit tables agasc decodes with.
GROUPED_MUX_FAMILIES = ("RMUX", "IMUX", "OMUX")
INSTANCE_MUX_FAMILIES = ("BBMUXE", "BBMUXW", "BBMUXS")

# routing.py's own NOCFG tuple: destinations that are fixed wires with no
# selector bit at all. Their absence from the decoded feature set is
# expected, not a mismatch.
NOCFG_DEST_FAMILIES = ("InputMUX", "BufMUX", "SinkMUXPseudo")

# Destination families owned by a different feature module (clocks, carry,
# physical IO) with its own, separately chipdb-driven encoding. Out of scope
# for this tool; counted, not silently dropped.
#
# SeamMUX belongs here, NOT in INSTANCE_MUX_FAMILIES, despite
# agamemnon/chipdb/pips_mcuedge.csv carrying per-instance "SeamMUX0".."
# SeamMUX11" rows that superficially look just like BBMUXE/BBMUXW. Found
# empirically while building this tool: a clock net's ROUTING attribute
# names a specific instance (e.g. "X13Y4_SeamMUX01"), but
# agamemnon/engine/features/routing.py itself never resolves clock-tree
# pips that way -- routing.py explicitly PRUNES SeamMUX/ClkMUX/CtrlMUX/etc.
# out of the general "data mesh" pip graph (see its own comment: "the clock
# TREE is modeled SEPARATELY ... bitgen emits CFG_SEAMMUX/CFG_TILECLKMUX
# independently"). The real emitter, features/clocks.py, looks up a single
# ``(x, y, "CFG_SEAMMUX", seam_selection)`` cell where ``seam_selection`` is
# the fixed, silicon-qualified constant ``registry.CONSTANTS["clock_seam_
# selector"]`` (value 5) -- entirely decoupled from the ROUTING pip's own
# instance index. Treating the pip's literal instance number as the feature
# name (as this tool naively does for BBMUXE/BBMUXW/BBMUXS) is simply the
# wrong table for SeamMUX, so it is excluded rather than checked.
OTHER_FEATURE_DEST_FAMILIES = (
    "ClkMUX", "TileClkMUX", "TileClkEnMUX", "KMUX", "TMUX",
    "CARRYIN", "CARRYOUT", "IOMUX", "SeamMUX",
)

NODE_RE = re.compile(r"^X(\d+)Y(\d+)_([A-Za-z]+)(\d+)$")
BEL_RE = re.compile(r"^X(\d+)Y(\d+)_(?:DUAL_)?SLICE(\d+)$")
SLICE_CELL_TYPES = ("GENERIC_SLICE", "AGRV2K_DUAL_LUT_CONST")


def _parse_node(text):
    match = NODE_RE.match(text.strip())
    if not match:
        return None
    x, y, family, index = match.groups()
    return int(x), int(y), family, int(index)


def route_items(route):
    """Parse a nextpnr ``ROUTING`` attribute into (destination, pip, strength).

    Same grammar as ``agamemnon.engine.status_overlay.route_items``: a flat
    ``;``-joined list of 3-tuples, the pip's ``SRC.DST`` suffix always equal
    to the destination. Reimplemented locally (rather than imported) to keep
    this tool a self-contained, read-only consumer of the routed JSON text --
    but it is a pure string-format parser, not a chipdb lookup, so
    duplicating it does not create a second copy of anything that bears on
    correctness. Whitespace-only routes (nextpnr emits these for nets fully
    absorbed inside one slice, e.g. an internal carry wire) parse to ``[]``.
    """
    route = (route or "").strip()
    if not route:
        return []
    fields = route.split(";")
    if len(fields) % 3:
        raise ValueError("malformed ROUTING attribute: %r" % route[:120])
    items = []
    for pos in range(0, len(fields), 3):
        destination, pip, strength = fields[pos:pos + 3]
        if not destination.strip():
            continue
        items.append((destination, pip, strength))
    return items


def expected_mux_groups(module):
    """Destination-side mux selector groups implied by every net's ROUTING.

    SHARED-TABLE CHECK (see module docstring): naming a group at all uses the
    same physical-bit tables the encoder consults. Returns
    ``(checked, skipped)``: ``checked`` maps ``(x, y, prefix) -> family`` for
    every group this tool expects to see *some* asserted bit for; ``skipped``
    counts destination families this tool does not attempt to verify, keyed
    by reason.
    """
    checked = {}
    skipped = collections.Counter()
    for net in module.get("netnames", {}).values():
        route = net.get("attributes", {}).get("ROUTING")
        try:
            items = route_items(route)
        except ValueError:
            skipped["malformed_routing_attribute"] += 1
            continue
        # Pad-feed exclusion (found while building this tool -- see module
        # docstring "NOT RECOVERABLE"): any net whose ROUTING tree reaches an
        # IOMUX node is a pad-feed/pad-output path. Its upstream RMUX hop is
        # resolved through agamemnon/engine/features/physical_io.py's own
        # vendor-harvested ``padfeed_exact``/``padfeed_unowned`` codeword
        # table, not the general (dx, dy)-local crossbar table this function
        # models -- the codeword can legitimately land on a *different* tile
        # than the naive destination node names (observed: a pad-feed hop
        # into X19Y13_RMUX04 encoded at X18Y13's CFG_RMUX0, not X19Y13's).
        # Forming a same-tile expectation for those destinations produces a
        # false mismatch, not a real encoder bug, so skip the whole net.
        parsed_destinations = [
            (destination, pip, _parse_node(destination)) for destination, pip, _s in items
        ]
        if any(parsed is not None and parsed[2] == "IOMUX"
               for _d, _p, parsed in parsed_destinations):
            skipped["padfeed_net_excluded"] += sum(
                1 for _d, pip, parsed in parsed_destinations
                if pip and parsed is not None
                and parsed[2] in GROUPED_MUX_FAMILIES + INSTANCE_MUX_FAMILIES
            )
            continue
        for destination, pip, _strength in items:
            if not pip:
                continue  # net driver / root: nothing selects into it
            parsed = _parse_node(destination)
            if parsed is None:
                skipped["unparsed_destination_node"] += 1
                continue
            x, y, family, index = parsed
            if family in GROUPED_MUX_FAMILIES:
                group = index // NPG[family]
                prefix = "CFG_%s%d" % (family, group)
            elif family in INSTANCE_MUX_FAMILIES:
                prefix = "%s%d" % (family, index)
            elif family in NOCFG_DEST_FAMILIES:
                skipped["nocfg_wire:%s" % family] += 1
                continue
            elif family in OTHER_FEATURE_DEST_FAMILIES:
                skipped["other_feature_owned:%s" % family] += 1
                continue
            else:
                skipped["unclassified_family:%s" % family] += 1
                continue
            checked[(x, y, prefix)] = family
    return checked, skipped


def slice_lut_expectations(module):
    """Per-bit expected LUT-init raw bits, independent of any chipdb table.

    Reproduces exactly the two facts documented in
    ``agamemnon/engine/physmap.py`` (a closed-form geometric formula) and
    ``agamemnon/engine/features/core_logic.py``'s ``prepare()``/
    ``emit_bitstream()``: the stored raw bit is the COMPLEMENT of the
    routed-JSON ``INIT`` bit, at ``physmap.init_bit_pos(x, y, z, index)``.
    Explicit route-throughs are excluded: their 16 bits per slice are owned
    by a different, chipdb-table-driven feature and are reported as
    ``route_through_slices`` instead of an expectation.
    """
    expectations = []  # (x, y, z, byte, mask, expected_bit)
    route_through_slices = 0
    other_cell_types = collections.Counter()
    for cell in module.get("cells", {}).values():
        cell_type = cell.get("type")
        if cell_type not in SLICE_CELL_TYPES:
            if cell_type:
                other_cell_types[cell_type] += 1
            continue
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL", "")
        match = BEL_RE.match(bel)
        if not match:
            continue
        x, y, z = (int(match.group(i)) for i in (1, 2, 3))
        route_through_attr = cell.get("attributes", {}).get(
            "AGRV2K_ROUTE_THROUGH", "0"
        )
        try:
            is_route_through = bool(int(str(route_through_attr), 2))
        except ValueError:
            is_route_through = False
        if is_route_through:
            route_through_slices += 1
            continue
        if cell_type == "AGRV2K_DUAL_LUT_CONST":
            value = int(cell.get("parameters", {}).get("VALUE", "0"), 2)
            init = 0xFFFF if value else 0
        else:
            init = int(cell["parameters"]["INIT"], 2)
        for index in range(16):
            byte, mask = physmap.init_bit_pos(x, y, z, index)
            expected_bit = 0 if (init >> index) & 1 else 1  # complemented storage
            expectations.append((x, y, z, byte, mask, expected_bit))
    return expectations, route_through_slices, other_cell_types


def _clean_env(extra):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("AGAMEMNON_")}
    env.update(extra or {})
    return env


def pack_artifact(routed_path, environment, out_path):
    env = _clean_env(environment)
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", str(routed_path), str(out_path)],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )
    return result


def check_artifact(artifact, workdir):
    """Run the full round trip for one ``pack_regression.json`` entry."""
    routed_rel = artifact["routed"]
    routed_path = ROOT / routed_rel
    out_path = workdir / (Path(routed_rel).stem + ".bin")
    comp_path = Path(str(out_path) + ".comp")

    report = {"routed": routed_rel}
    result = pack_artifact(routed_path, artifact.get("environment", {}), out_path)
    report["pack_returncode"] = result.returncode
    if result.returncode != 0:
        report["pack_ok"] = False
        report["pack_error"] = (result.stdout + result.stderr)[-4000:]
        return report
    report["pack_ok"] = True

    data = out_path.read_bytes()
    report["bitstream_sha256"] = hashlib.sha256(data).hexdigest()
    report["bitstream_sha256_expected"] = artifact.get("bitstream_sha256")
    report["bitstream_sha256_match"] = (
        report["bitstream_sha256"] == artifact.get("bitstream_sha256")
    )

    header, raw = data[:8], data[8:]
    module = json.loads(routed_path.read_text(encoding="utf-8"))["modules"]["top"]

    compared = matched = mismatched = unrecoverable = 0
    mismatches = []

    # -- 1. CRC-32/BZIP2 image integrity: INDEPENDENT (fixed algorithm). --
    described = bitstream_inspect.describe(header, raw, str(CHIPDB))
    compared += 1
    if described["crc"]["valid"]:
        matched += 1
    else:
        mismatched += 1
        mismatches.append({"kind": "crc", "detail": described["crc"]})

    # -- 2. LZW compressed-sidecar round trip: INDEPENDENT (fixed codec). --
    if comp_path.exists():
        comp_data = comp_path.read_bytes()
        compared += 1
        redecoded = bytes(lzw_codec.decode(comp_data[8:]))
        if redecoded == raw:
            matched += 1
        else:
            mismatched += 1
            mismatches.append({
                "kind": "lzw_roundtrip",
                "expected_len": len(raw), "actual_len": len(redecoded),
            })
    else:
        unrecoverable += 1
        mismatches.append({"kind": "lzw_roundtrip", "note": "no .comp sidecar produced"})

    # -- 3. LUT-init bits: INDEPENDENT (closed-form geometric formula). --
    expectations, route_through_slices, other_cell_types = slice_lut_expectations(module)
    for x, y, z, byte, mask, expected_bit in expectations:
        compared += 1
        actual_bit = 1 if (byte < len(raw) and raw[byte] & mask) else 0
        if actual_bit == expected_bit:
            matched += 1
        else:
            mismatched += 1
            mismatches.append({
                "kind": "lut_init", "x": x, "y": y, "z": z,
                "byte": byte, "mask": mask,
                "expected": expected_bit, "actual": actual_bit,
            })
    unrecoverable += route_through_slices * 16

    # -- 4. Routing mux-group presence: SHARED TABLE (see caveat). --
    decoded_prefixes = collections.defaultdict(set)
    for tile in described["tiles"]:
        for feature in tile["features"]:
            decoded_prefixes[(tile["x"], tile["y"])].add(feature.split("[", 1)[0])
    expected_groups, skipped_families = expected_mux_groups(module)
    for (x, y, prefix), family in expected_groups.items():
        compared += 1
        if prefix in decoded_prefixes.get((x, y), ()):
            matched += 1
        else:
            mismatched += 1
            mismatches.append({
                "kind": "mux_group_presence", "x": x, "y": y,
                "prefix": prefix, "family": family,
            })
    unrecoverable += sum(skipped_families.values())

    bram_cells = other_cell_types.get("ALTA_BRAM9K", 0)
    iob_cells = other_cell_types.get("GENERIC_IOB", 0)

    report.update({
        "compared": compared,
        "matched": matched,
        "mismatched": mismatched,
        "unrecoverable": unrecoverable,
        "mismatches": mismatches,
        "crc_valid": described["crc"]["valid"],
        "unknown_set_bits": described["summary"]["unknown_set_bits"],
        "named_features_total": described["summary"]["named_features"],
        "lut_slices_checked": len(expectations) // 16 if expectations else 0,
        "route_through_slices_skipped": route_through_slices,
        "mux_groups_checked": len(expected_groups),
        "mux_group_families_not_attempted": dict(skipped_families),
        "bram_cells_not_independently_verified": bram_cells,
        "io_pad_cells_not_independently_verified": iob_cells,
    })
    return report


def load_manifest():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return manifest["artifacts"]


def run_corpus(artifacts, workdir):
    reports = []
    for artifact in artifacts:
        reports.append(check_artifact(artifact, workdir))
    return reports


def summarize(reports):
    totals = collections.Counter()
    failed_pack = []
    with_mismatches = []
    for report in reports:
        if not report.get("pack_ok"):
            failed_pack.append(report["routed"])
            continue
        totals["compared"] += report["compared"]
        totals["matched"] += report["matched"]
        totals["mismatched"] += report["mismatched"]
        totals["unrecoverable"] += report["unrecoverable"]
        if report["mismatched"]:
            with_mismatches.append(report["routed"])
    return totals, failed_pack, with_mismatches


def format_table(reports):
    header = "%-62s %8s %8s %8s %8s %6s" % (
        "artifact", "compared", "matched", "mismatch", "unrec.", "pack"
    )
    lines = [header, "-" * len(header)]
    for report in reports:
        name = Path(report["routed"]).name
        if not report.get("pack_ok"):
            lines.append("%-62s %8s %8s %8s %8s %6s" % (name, "-", "-", "-", "-", "FAIL"))
            continue
        lines.append("%-62s %8d %8d %8d %8d %6s" % (
            name, report["compared"], report["matched"],
            report["mismatched"], report["unrecoverable"], "ok",
        ))
    totals, failed_pack, with_mismatches = summarize(reports)
    lines.append("-" * len(header))
    lines.append("%-62s %8d %8d %8d %8d" % (
        "TOTAL", totals["compared"], totals["matched"],
        totals["mismatched"], totals["unrecoverable"],
    ))
    lines.append("")
    lines.append("artifacts: %d, pack failures: %d, artifacts with mismatches: %d" % (
        len(reports), len(failed_pack), len(with_mismatches)
    ))
    if failed_pack:
        lines.append("  pack FAILED: " + ", ".join(failed_pack))
    if with_mismatches:
        lines.append("  MISMATCHES in: " + ", ".join(with_mismatches))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifact", help="run a single qualification/*_routed.json path")
    parser.add_argument("--limit", type=int, help="only run the first N corpus artifacts")
    parser.add_argument("--json", help="also write the full machine-readable report here")
    args = parser.parse_args(argv)

    artifacts = load_manifest()
    if args.artifact:
        wanted = Path(args.artifact).as_posix()
        artifacts = [a for a in artifacts if a["routed"] == wanted or
                     Path(a["routed"]).name == Path(args.artifact).name]
        if not artifacts:
            print("error: %r is not in %s" % (args.artifact, MANIFEST_PATH))
            return 2
    elif args.limit:
        artifacts = artifacts[: args.limit]

    with tempfile.TemporaryDirectory(prefix="agamemnon_roundtrip_") as tmp:
        reports = run_corpus(artifacts, Path(tmp))

    print(format_table(reports))

    if args.json:
        Path(args.json).write_text(
            json.dumps({"artifacts": reports}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("\nwrote %s" % args.json)

    totals, failed_pack, with_mismatches = summarize(reports)
    return 0 if not failed_pack and not with_mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
