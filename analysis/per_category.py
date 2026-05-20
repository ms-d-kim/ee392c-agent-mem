"""
analysis/per_category.py — bandwidth vs capacity dichotomy.

Categorizes objects (system_prompt, user_problem, assistant_output, tool_result,
file_content, kv_cache) and computes byte-seconds and read-event share per
category, across an arbitrary set of traces.

Usage:
    python -m analysis.per_category traces/batch_v2/hello_bug_*.jsonl

Output: stdout table; also writes analysis_out/per_category_breakdown.csv
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


def categorize(oid: str) -> str:
    if oid.startswith("msg_step0_system"):
        return "system_prompt"
    if oid.startswith("msg_step0_user_problem"):
        return "user_problem"
    if "_assistant_" in oid:
        return "assistant_output"
    if "tool_result" in oid:
        return "tool_result"
    if oid.startswith("file_"):
        return "file_content"
    if oid.startswith("kv_prompt"):
        return "kv_cache"
    return "other"


def per_category(trace_paths):
    agg = defaultdict(lambda: {
        "byte_seconds": 0.0, "n_reads": 0, "n_mutates": 0,
        "n_objects": 0, "total_create_bytes": 0,
    })
    for path in trace_paths:
        events = [json.loads(l) for l in path.open()]
        by_oid = defaultdict(list)
        for e in events:
            by_oid[e["object_id"]].append(e)
        task_end = max(e["ts"] for e in events)
        for oid, evs in by_oid.items():
            evs.sort(key=lambda e: e["ts"])
            creates = [e for e in evs if e["op"] == "create"]
            if not creates:
                continue
            c0 = creates[0]
            reads = [e for e in evs if e["op"] == "read"]
            mutates = [e for e in evs if e["op"] == "mutate"]
            last_access = max((e["ts"] for e in reads + mutates), default=task_end)
            lifetime = max(0.0, last_access - c0["ts"])
            cat = categorize(oid)
            agg[cat]["byte_seconds"] += c0["size_bytes"] * lifetime
            agg[cat]["n_reads"] += len(reads)
            agg[cat]["n_mutates"] += len(mutates)
            agg[cat]["n_objects"] += 1
            agg[cat]["total_create_bytes"] += c0["size_bytes"]
    return dict(agg)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m analysis.per_category <trace.jsonl> ...", file=sys.stderr)
        sys.exit(1)
    paths = [Path(p) for p in sys.argv[1:]]
    agg = per_category(paths)
    total_bs = sum(d["byte_seconds"] for d in agg.values())
    total_reads = sum(d["n_reads"] for d in agg.values())
    header = ["category", "n_objects", "total_create_bytes", "byte_seconds",
              "pct_byte_seconds", "n_reads", "pct_reads", "n_mutates"]
    rows = []
    for cat in sorted(agg.keys(), key=lambda c: -agg[c]["byte_seconds"]):
        d = agg[cat]
        rows.append({
            "category": cat,
            "n_objects": d["n_objects"],
            "total_create_bytes": d["total_create_bytes"],
            "byte_seconds": round(d["byte_seconds"], 1),
            "pct_byte_seconds": round(100 * d["byte_seconds"] / total_bs, 3) if total_bs else 0,
            "n_reads": d["n_reads"],
            "pct_reads": round(100 * d["n_reads"] / total_reads, 2) if total_reads else 0,
            "n_mutates": d["n_mutates"],
        })
    print(f"\nTraces analyzed: {len(paths)}")
    print(f"Total byte-seconds: {total_bs:,.0f}")
    print(f"Total read events:  {total_reads}\n")
    print(f"{'category':22s}  {'n_obj':>5s}  {'byte_sec':>13s}  {'bs %':>7s}  {'reads':>6s}  {'rd %':>6s}")
    for r in rows:
        print(f"  {r['category']:20s}  {r['n_objects']:>5d}  {r['byte_seconds']:>13,.0f}  "
              f"{r['pct_byte_seconds']:>6.2f}%  {r['n_reads']:>6d}  {r['pct_reads']:>5.2f}%")
    out_path = Path("analysis_out/per_category_breakdown.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
