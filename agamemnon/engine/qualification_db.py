#!/usr/bin/env python3
"""Record and fold silicon routing evidence without overclaiming dead edges.

The hardware campaigns produce useful evidence only when it is tied to the
specific source-to-observed-sink path that the probe exercised.  A passing
probe proves every PIP on that path.  A failing probe proves a PIP dead only
when exactly one PIP on the path was not already known live.

Evidence is append-only JSONL so interrupted campaigns are resumable and every
promotion can be traced back to routed and bitstream artifact hashes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_artifact_label(value):
    """Describe an evidence artifact without persisting a builder's host root."""
    original = Path(value)
    if not original.is_absolute():
        return original.as_posix()
    resolved = original.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.name


def split_pip(pip):
    """Return (source wire, destination wire), or raise for a pseudo PIP.

    Most wires are positioned (``XnYn_name``), while global clock roots such
    as ``GCLK0`` are intentionally positionless.
    """
    try:
        src, dst = pip.split(".", 1)
    except ValueError as exc:
        raise ValueError("PIP has no source/destination separator: %s" % pip) from exc
    if not src or not dst or "." in src or "." in dst:
        raise ValueError("PIP does not name two wires: %s" % pip)
    return src, dst


def routed_nets(path):
    """Extract {module/net: {pip names}} from nextpnr generic JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for module_name, module in data.get("modules", {}).items():
        for net_name, net in module.get("netnames", {}).items():
            route = net.get("attributes", {}).get("ROUTING")
            if not route:
                continue
            fields = route.split(";")
            pips = {fields[pos] for pos in range(1, len(fields), 3)
                    if fields[pos] and "." in fields[pos]}
            if pips:
                result["%s/%s" % (module_name, net_name)] = pips
    return result


def select_net(nets, name):
    if name in nets:
        return nets[name]
    matches = [pips for key, pips in nets.items()
               if key.rsplit("/", 1)[-1] == name]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError("routed net not found: %s" % name)
    raise ValueError("routed net name is ambiguous; use module/net: %s" % name)


def unique_path(pips, source=None, sink=None):
    """Find one unambiguous directed path through a routed net.

    Source or sink may be omitted only when the graph has a single root or
    leaf respectively.  Branches outside the selected path are deliberately
    ignored: observing one sink says nothing about the other branches.
    """
    adjacency = defaultdict(list)
    indegree = defaultdict(int)
    outdegree = defaultdict(int)
    nodes = set()
    for pip in sorted(pips):
        src, dst = split_pip(pip)
        adjacency[src].append((dst, pip))
        indegree[dst] += 1
        outdegree[src] += 1
        nodes.update((src, dst))

    roots = sorted(node for node in nodes if indegree[node] == 0)
    leaves = sorted(node for node in nodes if outdegree[node] == 0)
    if source is None:
        if len(roots) != 1:
            raise ValueError("route has %d roots; specify --source-wire" % len(roots))
        source = roots[0]
    if sink is None:
        if len(leaves) != 1:
            raise ValueError("route has %d leaves; specify --observed-wire" % len(leaves))
        sink = leaves[0]
    if source not in nodes or sink not in nodes:
        raise ValueError("source or observed wire is not present in the routed net")

    paths = []

    def walk(node, visited, path):
        if len(paths) > 1:
            return
        if node == sink:
            paths.append(list(path))
            return
        for nxt, pip in adjacency.get(node, ()):
            if nxt in visited:
                continue
            visited.add(nxt)
            path.append(pip)
            walk(nxt, visited, path)
            path.pop()
            visited.remove(nxt)

    walk(source, {source}, [])
    if not paths:
        raise ValueError("no route from source wire to observed wire")
    if len(paths) != 1:
        raise ValueError("multiple routes connect source wire to observed wire")
    return paths[0], source, sink


def load_events(path):
    if not os.path.exists(path):
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("bad evidence JSON at %s:%d" % (path, lineno)) from exc
            events.append(event)
    return events


def fold_events(events):
    evidence = defaultdict(lambda: {"live": [], "dead": []})
    for event in events:
        trial = event.get("trial_id", "unknown")
        if event.get("verdict") == "pass" and event.get("path_isolated"):
            for pip in event.get("path_pips", ()):
                evidence[pip]["live"].append(trial)
        if event.get("verdict") == "fail" and event.get("dead_candidate"):
            evidence[event["dead_candidate"]]["dead"].append(trial)
    state = {}
    for pip, ev in evidence.items():
        live, dead = bool(ev["live"]), bool(ev["dead"])
        status = "conflict" if live and dead else ("live" if live else "dead")
        state[pip] = {"status": status, "live_evidence": ev["live"],
                      "dead_evidence": ev["dead"]}
    return state


def silicon_csv_pips(paths):
    result = set()
    for path in paths:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                src = "X%sY%s_%s" % (row["src_x"], row["src_y"], row["src_res"])
                dst = "X%sY%s_%s" % (row["dst_x"], row["dst_y"], row["dst_res"])
                result.add("%s.%s" % (src, dst))
    return result


def append_event(path, event):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write(encoded)
        f.flush()
        os.fsync(f.fileno())


def record(args):
    nets = routed_nets(args.routed)
    pips = select_net(nets, args.net)
    path, source, sink = unique_path(pips, args.source_wire, args.observed_wire)

    old_events = load_events(args.database)
    if any(event.get("trial_id") == args.trial_id for event in old_events):
        raise ValueError("trial id already exists: %s" % args.trial_id)
    previous = fold_events(old_events)
    seeded_live = silicon_csv_pips(args.seed_live)
    known_live = seeded_live | {pip for pip, row in previous.items()
                                if row["status"] == "live"}
    unknown = sorted(set(path) - known_live)
    dead_candidate = None
    resolution = "live_path" if args.verdict == "pass" else "inconclusive"
    suspect_pip = unknown[0] if args.verdict == "fail" and len(unknown) == 1 else None
    failure_observation = 0
    if suspect_pip:
        failure_observation = 1 + sum(
            1 for event in old_events
            if event.get("verdict") == "fail" and event.get("suspect_pip") == suspect_pip
        )
        resolution = "dead_suspect"
        if failure_observation >= args.min_dead_observations:
            dead_candidate = suspect_pip
            resolution = "dead_edge"

    event = {
        "schema": 1,
        "trial_id": args.trial_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "campaign": args.campaign,
        "probe": args.probe,
        "verdict": args.verdict,
        "resolution": resolution,
        "path_isolated": True,
        "net": args.net,
        "source_wire": source,
        "observed_wire": sink,
        "path_pips": path,
        "unknown_before": unknown,
        "suspect_pip": suspect_pip,
        "failure_observation": failure_observation,
        "min_dead_observations": args.min_dead_observations,
        "dead_candidate": dead_candidate,
        "routed_json": portable_artifact_label(args.routed),
        "routed_sha256": sha256_file(args.routed),
        "bitstream": portable_artifact_label(args.bitstream) if args.bitstream else None,
        "bitstream_sha256": sha256_file(args.bitstream) if args.bitstream else None,
        "expected": args.expected,
        "observed": args.observed,
        "notes": args.notes,
    }
    append_event(args.database, event)
    print("%s: %s (%d PIPs, %d previously unknown)" %
          (args.trial_id, resolution, len(path), len(unknown)))
    if dead_candidate:
        print("dead candidate: %s" % dead_candidate)


def write_state(database, output):
    state = fold_events(load_events(database))
    with open(output, "w", encoding="utf-8", newline="") as f:
        fields = ["pip", "status", "live_evidence", "dead_evidence"]
        out = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        out.writeheader()
        for pip in sorted(state):
            row = state[pip]
            out.writerow({"pip": pip, "status": row["status"],
                          "live_evidence": ";".join(row["live_evidence"]),
                          "dead_evidence": ";".join(row["dead_evidence"])})
    counts = defaultdict(int)
    for row in state.values():
        counts[row["status"]] += 1
    print("wrote %d PIPs: %s" %
          (len(state), ", ".join("%s=%d" % item for item in sorted(counts.items()))))


def report(database, dev_pips=None):
    state = fold_events(load_events(database))
    counts = defaultdict(int)
    for row in state.values():
        counts[row["status"]] += 1
    print("evidence: live=%d dead=%d conflict=%d" %
          (counts["live"], counts["dead"], counts["conflict"]))
    if not dev_pips:
        return
    by_type = defaultdict(lambda: defaultdict(int))
    with open(dev_pips, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            status = state.get(row["name"], {}).get("status", "untested")
            by_type[row.get("type", "")][status] += 1
            by_type[row.get("type", "")]["total"] += 1
    print("type,total,live,dead,conflict,untested")
    for typ in sorted(by_type):
        row = by_type[typ]
        print("%s,%d,%d,%d,%d,%d" %
              (typ, row["total"], row["live"], row["dead"], row["conflict"],
               row["untested"]))


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="append one isolated hardware trial")
    rec.add_argument("database")
    rec.add_argument("--routed", required=True)
    rec.add_argument("--net", required=True)
    rec.add_argument("--source-wire")
    rec.add_argument("--observed-wire")
    rec.add_argument("--verdict", choices=("pass", "fail"), required=True)
    rec.add_argument("--trial-id", required=True)
    rec.add_argument("--campaign", default="manual")
    rec.add_argument("--probe", default="digital_path")
    rec.add_argument("--bitstream")
    rec.add_argument("--seed-live", action="append", default=[])
    rec.add_argument("--min-dead-observations", type=int, default=2,
                     help="independent one-unknown failures required before marking a PIP dead")
    rec.add_argument("--expected", default="")
    rec.add_argument("--observed", default="")
    rec.add_argument("--notes", default="")
    rec.set_defaults(func=record)

    export = sub.add_parser("export", help="fold JSONL evidence into a PIP-state CSV")
    export.add_argument("database")
    export.add_argument("output")
    export.set_defaults(func=lambda a: write_state(a.database, a.output))

    rep = sub.add_parser("report", help="summarize evidence and optional device coverage")
    rep.add_argument("database")
    rep.add_argument("--dev-pips")
    rep.set_defaults(func=lambda a: report(a.database, a.dev_pips))
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        args.func(args)
    except (OSError, ValueError) as exc:
        print("qualification error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
