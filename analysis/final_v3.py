"""Analyze final-v3 semantic traces and generate artifact CSVs/figures.

Read counts are logical prompt-construction accesses, not hardware memory
transactions. KV byte counts are analytical projections, not physical residency.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

EXPECTED_SCHEMA_VERSION = 3

try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover - optional local dependency
    plt = None

DEFAULT_CONDITION = {
    "coding_agent": "cache_on",
    "search_agent": "targeted",
    "compaction_agent": "compaction_on",
}

COLORS = {
    "system_prompt": "#534AB7",
    "user_problem": "#993556",
    "assistant_history": "#BA7517",
    "file_content": "#0F6E56",
    "tool_result": "#993C1D",
    "search_corpus_scan": "#7A7A7A",
    "search_result": "#4E79A7",
    "retrieved_snippet": "#59A14F",
    "raw_context": "#E15759",
    "compacted_summary": "#76B7B2",
    "plan_state": "#EDC948",
    "prompt_template": "#C7C7C7",
}


def load_trace(path: Path) -> list[dict]:
    events = [json.loads(line) for line in path.open() if line.strip()]
    bad_versions = sorted({
        event.get("schema_version")
        for event in events
        if event.get("schema_version") != EXPECTED_SCHEMA_VERSION
    }, key=lambda value: repr(value))
    if bad_versions:
        raise ValueError(f"{path}: expected schema_version={EXPECTED_SCHEMA_VERSION}, found {bad_versions}")
    return events


def trace_label(path: Path, events: list[dict]) -> tuple[str, str]:
    for event in events:
        if event.get("semantic_type") == "trace_metadata":
            return event["workload"], event["condition"]
    stem = path.stem
    for workload in DEFAULT_CONDITION:
        prefix = f"{workload}_"
        if stem.startswith(prefix):
            return workload, stem[len(prefix):]
    return "unknown", stem


def semantic(event: dict) -> str:
    return event.get("semantic_type") or "unknown"


def trace_metadata(events: list[dict]) -> dict:
    for event in events:
        if event.get("semantic_type") == "trace_metadata":
            return event
    return {}


def is_bookkeeping_event(event: dict) -> bool:
    return event.get("semantic_type") in {"trace_metadata", "engine_cross_check"}


def liveness_intervals(events: list[dict]) -> list[dict]:
    intervals = []
    live = {}
    task_end = max((event["ts"] for event in events), default=0.0)
    kv_end_by_step = kv_next_prefill_boundaries(events, task_end)
    for event in sorted(events, key=lambda e: (e["ts"], e["step"])):
        oid = event["object_id"]
        op = event["op"]
        if is_bookkeeping_event(event):
            continue
        if op == "create":
            if oid in live:
                intervals.append(make_interval(live[oid], event["ts"]))
            live[oid] = event
        elif op == "mutate":
            if oid in live:
                intervals.append(make_interval(live[oid], event["ts"]))
            live[oid] = event
        elif op == "free":
            if oid in live:
                intervals.append(make_interval(live.pop(oid), event["ts"]))
        elif op == "read":
            if oid in live:
                live[oid]["_last_read_ts"] = event["ts"]
                live[oid]["_read_count"] = live[oid].get("_read_count", 0) + 1
    for event in live.values():
        default_end = task_end
        cap_at_default = False
        if event.get("repr_type") == "kv_estimated":
            default_end = kv_end_by_step.get(event["step"], task_end)
            cap_at_default = True
        intervals.append(make_interval(event, default_end, cap_at_default=cap_at_default))
    return intervals


def kv_next_prefill_boundaries(events: list[dict], task_end: float) -> dict[int, float]:
    """Bound per-step logical KV spans at the next prompt prefill boundary."""
    first_kv_create_by_step = {}
    for event in events:
        if event.get("repr_type") != "kv_estimated" or event.get("op") != "create":
            continue
        if is_bookkeeping_event(event):
            continue
        step = event["step"]
        first_kv_create_by_step[step] = min(first_kv_create_by_step.get(step, event["ts"]), event["ts"])
    ordered = sorted(first_kv_create_by_step.items())
    boundaries = {}
    for idx, (step, _) in enumerate(ordered):
        boundaries[step] = ordered[idx + 1][1] if idx + 1 < len(ordered) else task_end
    return boundaries


def make_interval(event: dict, default_end: float, *, cap_at_default: bool = False) -> dict:
    end_ts = default_end if cap_at_default else max(default_end, event.get("_last_read_ts", default_end))
    return {
        "semantic_type": semantic(event),
        "repr_type": event["repr_type"],
        "logical_id": event["logical_id"],
        "object_id": event["object_id"],
        "size_bytes": event["size_bytes"],
        "create_ts": event["ts"],
        "end_ts": end_ts,
        "lifetime_s": max(0.0, end_ts - event["ts"]),
        "read_count": event.get("_read_count", 0),
    }


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def semantic_summary(traces: list[tuple[Path, str, str, list[dict]]]) -> list[dict]:
    rows = []
    for path, workload, condition, events in traces:
        intervals = liveness_intervals(events)
        reads = defaultdict(int)
        mutates = defaultdict(int)
        for event in events:
            if is_bookkeeping_event(event):
                continue
            if event["op"] == "read":
                reads[semantic(event)] += 1
            elif event["op"] == "mutate":
                mutates[semantic(event)] += 1
        agg = defaultdict(lambda: {
            "byte_seconds": 0.0,
            "n_objects": 0,
            "logical_ids": set(),
            "reads": 0,
            "mutates": 0,
        })
        for interval in intervals:
            sem = interval["semantic_type"]
            agg[sem]["byte_seconds"] += interval["size_bytes"] * interval["lifetime_s"]
            agg[sem]["n_objects"] += 1
            agg[sem]["logical_ids"].add(interval["logical_id"])
        for sem, count in reads.items():
            agg[sem]["reads"] = count
        for sem, count in mutates.items():
            agg[sem]["mutates"] = count
        for sem, data in sorted(agg.items()):
            rows.append({
                "trace": path.name,
                "workload": workload,
                "condition": condition,
                "semantic_type": sem,
                "n_objects": data["n_objects"],
                "n_logical_objects": len(data["logical_ids"]),
                "byte_seconds": round(data["byte_seconds"], 3),
                "logical_read_events": data["reads"],
                "mutate_events": data["mutates"],
            })
    return rows


def kv_pressure(traces: list[tuple[Path, str, str, list[dict]]]) -> list[dict]:
    rows = []
    for path, workload, condition, events in traces:
        agg = defaultdict(lambda: {"logical": 0, "cached": 0})
        for event in events:
            if event.get("repr_type") != "kv_estimated":
                continue
            sem = semantic(event)
            if event["op"] == "create":
                agg[sem]["logical"] += event["size_bytes"]
            elif event["op"] == "read" and event.get("kv_pressure_kind") == "cache_adjusted_reuse":
                agg[sem]["cached"] += event["size_bytes"]
        for sem, data in sorted(agg.items()):
            rows.append({
                "trace": path.name,
                "workload": workload,
                "condition": condition,
                "semantic_type": sem,
                "logical_projected_kv_bytes": data["logical"],
                "cached_reuse_kv_bytes": data["cached"],
                "cache_adjusted_new_kv_bytes": max(0, data["logical"] - data["cached"]),
            })
    return rows


def duplication_summary(traces: list[tuple[Path, str, str, list[dict]]]) -> list[dict]:
    rows = []
    for path, workload, condition, events in traces:
        intervals = liveness_intervals(events)
        by_sem_lid = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        cumulative_by_sem = defaultdict(lambda: {"total": 0, "kv": 0})
        for interval in intervals:
            sem = interval["semantic_type"]
            lid = interval["logical_id"]
            by_sem_lid[sem][lid][interval["repr_type"]].append(interval["size_bytes"])
            cumulative_by_sem[sem]["total"] += interval["size_bytes"]
            if interval["repr_type"] == "kv_estimated":
                cumulative_by_sem[sem]["kv"] += interval["size_bytes"]
        for sem, by_lid in sorted(by_sem_lid.items()):
            unique_baseline = 0
            text_tokens_bytes = 0
            kv_one_snapshot_bytes = 0
            spatial_bytes = 0
            for reps in by_lid.values():
                text_b = max(reps.get("text", [0]))
                tokens_b = max(reps.get("tokens", [0]))
                kv_b = max(reps.get("kv_estimated", [0]))
                baseline = text_b or tokens_b or kv_b
                unique_baseline += baseline
                text_tokens_bytes += text_b + tokens_b
                kv_one_snapshot_bytes += kv_b
                spatial_bytes += text_b + tokens_b + kv_b
            rows.append({
                "trace": path.name,
                "workload": workload,
                "condition": condition,
                "semantic_type": sem,
                "n_logical_objects": len(by_lid),
                "unique_baseline_bytes": unique_baseline,
                "text_tokens_snapshot_bytes": text_tokens_bytes,
                "kv_one_snapshot_bytes": kv_one_snapshot_bytes,
                "spatial_snapshot_bytes": spatial_bytes,
                "text_tokens_duplication_factor": (
                    round(text_tokens_bytes / unique_baseline, 3) if unique_baseline else ""
                ),
                "kv_text_amplification": (
                    round(kv_one_snapshot_bytes / unique_baseline, 3) if unique_baseline else ""
                ),
                "cumulative_create_bytes": cumulative_by_sem[sem]["total"],
                "cumulative_kv_create_bytes": cumulative_by_sem[sem]["kv"],
            })
    return rows


def search_funnel(traces: list[tuple[Path, str, str, list[dict]]]) -> list[dict]:
    rows = []
    for path, workload, condition, events in traces:
        if workload != "search_agent":
            continue
        scanned = sum(event.get("scanned_bytes", 0) for event in events if semantic(event) == "search_corpus_scan")
        returned = sum(
            event["size_bytes"]
            for event in events
            if semantic(event) == "search_result"
            and event["op"] == "create"
            and event.get("repr_type") == "text"
        )
        inserted = sum(
            event["size_bytes"]
            for event in events
            if semantic(event) == "retrieved_snippet"
            and event["op"] == "create"
            and event.get("repr_type") == "text"
        )
        reused = sum(1 for event in events if semantic(event) == "retrieved_snippet" and event["op"] == "read")
        rows.append({
            "trace": path.name,
            "workload": workload,
            "condition": condition,
            "scanned_bytes": scanned,
            "returned_bytes": returned,
            "inserted_bytes": inserted,
            "retrieved_snippet_read_events": reused,
        })
    return rows


def compaction_funnel(traces: list[tuple[Path, str, str, list[dict]]]) -> list[dict]:
    rows = []
    for path, workload, condition, events in traces:
        if workload != "compaction_agent":
            continue
        raw = sum(
            event["size_bytes"]
            for event in events
            if semantic(event) == "raw_context"
            and event["op"] == "create"
            and event.get("repr_type") == "text"
        )
        summary = sum(
            event["size_bytes"]
            for event in events
            if semantic(event) == "compacted_summary"
            and event["op"] == "create"
            and event.get("repr_type") == "text"
        )
        summary_reads = sum(1 for event in events if semantic(event) == "compacted_summary" and event["op"] == "read")
        rows.append({
            "trace": path.name,
            "workload": workload,
            "condition": condition,
            "raw_context_bytes": raw,
            "summary_bytes": summary,
            "compression_ratio": round(raw / summary, 3) if summary else "",
            "summary_read_events": summary_reads,
        })
    return rows


def cached_cross_checks(traces: list[tuple[Path, str, str, list[dict]]]) -> list[dict]:
    rows = []
    for path, workload, condition, events in traces:
        for event in events:
            if semantic(event) != "engine_cross_check":
                continue
            rows.append({
                "trace": path.name,
                "workload": workload,
                "condition": condition,
                "step": event["step"],
                "prompt_token_count": event.get("prompt_token_count", 0),
                "prefix_caching": event.get("prefix_caching", ""),
                "cached_tokens": event.get("cached_tokens", 0),
                "cached_tokens_available": event.get("cached_tokens_available", ""),
                "cached_tokens_source": event.get("cached_tokens_source", ""),
                "cached_span_tokens": event.get("cached_span_tokens", 0),
                "cached_token_delta": event.get("cached_token_delta", 0),
                "cross_check_status": event.get("cross_check_status", ""),
                "cross_check_pass": event.get("cross_check_pass", False),
                "cross_check_note": event.get("cross_check_note", ""),
            })
    return rows


def bar_figure(rows: list[dict], *, value_key: str, group_key: str, out_path: Path, title: str) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(float)
    for row in rows:
        grouped[(row["workload"], row[group_key])] += float(row[value_key] or 0)
    labels = [f"{workload}\n{group}" for workload, group in grouped]
    values = list(grouped.values())
    colors = [COLORS.get(group, "#888888") for _, group in grouped]
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.55), 4.8))
    ax.bar(range(len(labels)), values, color=colors)
    ax.set_xticks(range(len(labels)), labels=labels, rotation=45, ha="right")
    ax.set_title(title, loc="left")
    ax.set_ylabel(value_key.replace("_", " "))
    fig.tight_layout()
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def scatter_lifetime_reuse(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    for _, workload, condition, events in traces:
        if DEFAULT_CONDITION.get(workload) != condition:
            continue
        for interval in liveness_intervals(events):
            sem = interval["semantic_type"]
            ax.scatter(
                interval["lifetime_s"],
                interval["read_count"],
                s=25 + min(120, interval["size_bytes"] / 1024),
                c=COLORS.get(sem, "#888888"),
                alpha=0.45,
            )
    ax.set_xlabel("Lifetime (s)")
    ax.set_ylabel("Read events")
    ax.set_title("Lifetime vs reuse by semantic class (default traces)", loc="left")
    fig.tight_layout()
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def main(argv: list[str]) -> int:
    args = [arg for arg in argv[1:] if arg != "--allow-dry-run-figures"]
    allow_dry_run_figures = "--allow-dry-run-figures" in argv[1:]
    traces_dir = Path(args[0]) if len(args) > 0 else Path("traces/final_v3")
    out_dir = Path(args[1]) if len(args) > 1 else Path("analysis_out/final_v3")
    fig_dir = Path(args[2]) if len(args) > 2 else Path("figures/final_v3")
    paths = sorted(traces_dir.glob("*.jsonl"))
    if not paths:
        print(f"No traces found in {traces_dir}", file=sys.stderr)
        return 1
    traces = []
    for path in paths:
        events = load_trace(path)
        workload, condition = trace_label(path, events)
        traces.append((path, workload, condition, events))
    has_dry_run = any(trace_metadata(events).get("dry_run") for _, _, _, events in traces)

    semantic_rows = semantic_summary(traces)
    kv_rows = kv_pressure(traces)
    dup_rows = duplication_summary(traces)
    search_rows = search_funnel(traces)
    compaction_rows = compaction_funnel(traces)
    check_rows = cached_cross_checks(traces)

    write_csv(out_dir / "semantic_summary.csv", semantic_rows, [
        "trace", "workload", "condition", "semantic_type", "n_objects",
        "n_logical_objects", "byte_seconds", "logical_read_events", "mutate_events",
    ])
    write_csv(out_dir / "kv_pressure.csv", kv_rows, [
        "trace", "workload", "condition", "semantic_type",
        "logical_projected_kv_bytes", "cached_reuse_kv_bytes",
        "cache_adjusted_new_kv_bytes",
    ])
    write_csv(out_dir / "duplication_factor.csv", dup_rows, [
        "trace", "workload", "condition", "semantic_type",
        "n_logical_objects", "unique_baseline_bytes",
        "text_tokens_snapshot_bytes", "kv_one_snapshot_bytes",
        "spatial_snapshot_bytes", "text_tokens_duplication_factor",
        "kv_text_amplification", "cumulative_create_bytes",
        "cumulative_kv_create_bytes",
    ])
    write_csv(out_dir / "search_funnel.csv", search_rows, [
        "trace", "workload", "condition", "scanned_bytes", "returned_bytes",
        "inserted_bytes", "retrieved_snippet_read_events",
    ])
    write_csv(out_dir / "compaction_funnel.csv", compaction_rows, [
        "trace", "workload", "condition", "raw_context_bytes", "summary_bytes",
        "compression_ratio", "summary_read_events",
    ])
    write_csv(out_dir / "cached_token_cross_check.csv", check_rows, [
        "trace", "workload", "condition", "step", "prompt_token_count",
        "prefix_caching", "cached_tokens", "cached_tokens_available",
        "cached_tokens_source", "cached_span_tokens", "cached_token_delta",
        "cross_check_status", "cross_check_pass", "cross_check_note",
    ])

    default_semantic = [
        row for row in semantic_rows
        if DEFAULT_CONDITION.get(row["workload"]) == row["condition"]
    ]
    default_kv = [
        row for row in kv_rows
        if DEFAULT_CONDITION.get(row["workload"]) == row["condition"]
    ]
    default_dup = [
        row for row in dup_rows
        if DEFAULT_CONDITION.get(row["workload"]) == row["condition"]
    ]
    if has_dry_run and not allow_dry_run_figures:
        print(
            "Skipped figures because traces include dry_run=true; dry-run "
            "byte-seconds are tracer-overhead-bound and not valid paper figures. "
            "Pass --allow-dry-run-figures only for local visual debugging."
        )
        print(f"Wrote CSVs to {out_dir}")
        return 0
    bar_figure(
        default_semantic,
        value_key="byte_seconds",
        group_key="semantic_type",
        out_path=fig_dir / "semantic_byte_seconds",
        title="Semantic byte-seconds across default workload traces",
    )
    bar_figure(
        default_kv,
        value_key="logical_projected_kv_bytes",
        group_key="semantic_type",
        out_path=fig_dir / "logical_kv_pressure",
        title="Logical projected KV pressure by workload",
    )
    bar_figure(
        default_dup,
        value_key="kv_text_amplification",
        group_key="semantic_type",
        out_path=fig_dir / "duplication_factor",
        title="KV/text amplification by workload",
    )
    scatter_lifetime_reuse(traces, fig_dir / "lifetime_reuse")
    if search_rows:
        bar_figure(search_rows, value_key="scanned_bytes", group_key="condition",
                   out_path=fig_dir / "search_scanned_bytes",
                   title="Search scanned bytes by condition")
    if compaction_rows:
        bar_figure(compaction_rows, value_key="raw_context_bytes", group_key="condition",
                   out_path=fig_dir / "compaction_raw_context",
                   title="Compaction raw context bytes by condition")
    print(f"Wrote CSVs to {out_dir}")
    if plt is None:
        print("Skipped figures because matplotlib is not installed")
    else:
        print(f"Wrote figures to {fig_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
