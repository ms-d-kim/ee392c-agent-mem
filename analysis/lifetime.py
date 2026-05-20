"""
analysis/lifetime.py — per-trace lifetime + access-frequency summary.

Usage:
    python -m analysis.lifetime traces/some.jsonl
    python -m analysis.lifetime traces/batch_v2/*.jsonl > summary.csv
"""

from __future__ import annotations

import collections
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PHYSICAL_REPRS = frozenset({"text", "tokens", "kv_estimated", "kv_actual"})


@dataclass
class ObjectStats:
    logical_id: str
    object_id: str
    repr_type: str
    size_bytes: int
    create_ts: float
    last_access_ts: float
    access_count: int = 0
    mutate_count: int = 0

    @property
    def lifetime_s(self):
        return max(0.0, self.last_access_ts - self.create_ts)


def per_object_stats(events):
    by_oid = collections.defaultdict(list)
    for e in events:
        by_oid[e["object_id"]].append(e)
    task_end = max((e["ts"] for e in events), default=0.0)
    out = []
    for oid, evs in by_oid.items():
        evs_sorted = sorted(evs, key=lambda e: e["ts"])
        creates = [e for e in evs_sorted if e["op"] == "create"]
        if not creates:
            continue
        c0 = creates[0]
        reads = [e for e in evs_sorted if e["op"] == "read"]
        mutates = [e for e in evs_sorted if e["op"] == "mutate"]
        frees = [e for e in evs_sorted if e["op"] == "free"]
        last_access_ts = max((e["ts"] for e in reads + mutates + frees), default=task_end)
        out.append(ObjectStats(
            logical_id=c0["logical_id"], object_id=oid,
            repr_type=c0["repr_type"], size_bytes=c0["size_bytes"],
            create_ts=c0["ts"], last_access_ts=last_access_ts,
            access_count=len(reads), mutate_count=len(mutates),
        ))
    return out


def trace_summary(trace_path):
    events = [json.loads(l) for l in trace_path.open()]
    stats = per_object_stats(events)
    physical_events = [e for e in events if e["repr_type"] in PHYSICAL_REPRS]
    total_physical = sum(e["size_bytes"] for e in physical_events
                         if e["op"] in ("create", "mutate"))
    rep_size = {}
    for e in physical_events:
        if e["op"] not in ("create", "mutate"):
            continue
        lid = e["logical_id"]
        if e["repr_type"] == "text":
            rep_size[lid] = e["size_bytes"]
        elif lid not in rep_size:
            rep_size[lid] = e["size_bytes"]
    unique_logical = sum(rep_size.values())
    lifetimes = [s.lifetime_s for s in stats if s.repr_type in PHYSICAL_REPRS]
    access_counts = [s.access_count for s in stats if s.repr_type in PHYSICAL_REPRS]
    return {
        "trace": trace_path.name,
        "n_events": len(events),
        "n_physical_events": len(physical_events),
        "n_logical_ids": len({s.logical_id for s in stats}),
        "n_objects": len(stats),
        "total_physical_bytes": total_physical,
        "unique_logical_bytes": unique_logical,
        "duplication_factor": (
            round(total_physical / unique_logical, 2) if unique_logical > 0 else None
        ),
        "median_lifetime_s": (
            round(sorted(lifetimes)[len(lifetimes) // 2], 3) if lifetimes else None
        ),
        "max_lifetime_s": round(max(lifetimes), 3) if lifetimes else None,
        "median_access_count": (
            sorted(access_counts)[len(access_counts) // 2] if access_counts else None
        ),
        "max_access_count": max(access_counts) if access_counts else None,
        "total_read_events": sum(1 for e in events if e["op"] == "read"),
        "total_mutate_events": sum(1 for e in events if e["op"] == "mutate"),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m analysis.lifetime <trace.jsonl> ...", file=sys.stderr)
        sys.exit(1)
    paths = [Path(p) for p in sys.argv[1:]]
    summaries = [trace_summary(p) for p in paths]
    if not summaries:
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=list(summaries[0].keys()))
    writer.writeheader()
    for s in summaries:
        writer.writerow(s)


if __name__ == "__main__":
    main()
