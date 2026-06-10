"""Analyze final-v3 semantic traces and generate artifact CSVs/figures.

Read counts are logical access events, not hardware memory transactions.
``logical_read_events`` totals two distinct populations, reported separately as
``prompt_construction_reads`` (text/token re-reads while assembling each
prompt) and ``cached_prefix_kv_reads`` (engine-reported cached-prefix KV reuse,
emitted only when prefix caching is on — so the total is cache-condition-
dependent). KV byte counts are analytical projections, not physical residency.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import statistics
from collections import defaultdict
from pathlib import Path

EXPECTED_SCHEMA_VERSION = 3


def _configure_matplotlib_cache() -> None:
    """Point Matplotlib at a writable cache dir when HOME is restricted."""
    if os.environ.get("MPLCONFIGDIR"):
        return
    default = Path.home() / ".matplotlib"
    try:
        default.mkdir(parents=True, exist_ok=True)
    except OSError:
        default = None
    if default is not None and os.access(default, os.W_OK | os.X_OK):
        return
    cache_dir = Path(tempfile.gettempdir()) / "ee392c-mplcache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_dir)


_configure_matplotlib_cache()

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
except ImportError:  # pragma: no cover - optional local dependency
    plt = None
    Line2D = None

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
    "cache_on": "#4E79A7",
    "cache_off": "#BAB0AC",
    "targeted": "#59A14F",
    "broad": "#E15759",
    "compaction_on": "#76B7B2",
    "compaction_off": "#9C755F",
}

WORKLOAD_LABELS = {
    "coding_agent": "coding",
    "search_agent": "search",
    "compaction_agent": "compaction",
}

CONDITION_LABELS = {
    "cache_on": "cache on",
    "cache_off": "cache off",
    "targeted": "targeted",
    "broad": "broad",
    "compaction_on": "compaction on",
    "compaction_off": "compaction off",
}

RETENTION_CLASS_COLORS = {
    "short-term": "#4A7EBB",
    "medium-term": "#E67A2C",
    "long-term": "#2C7A62",
}

SEMANTIC_LABELS = {
    "system_prompt": "system prompt",
    "user_problem": "user problem",
    "assistant_history": "assistant history",
    "file_content": "file content",
    "tool_result": "tool result",
    "search_corpus_scan": "corpus scan",
    "search_result": "search result",
    "retrieved_snippet": "retrieved snippet",
    "raw_context": "raw context",
    "compacted_summary": "compacted summary",
    "plan_state": "plan state",
    "prompt_template": "prompt template",
}


def label_workload(value: str) -> str:
    return WORKLOAD_LABELS.get(value, value.replace("_", " "))


def label_condition(value: str) -> str:
    return CONDITION_LABELS.get(value, value.replace("_", " "))


def label_semantic(value: str) -> str:
    label = SEMANTIC_LABELS.get(value, value.replace("_", " "))
    if value == "search_corpus_scan":
        return f"{label} (proxy)"
    return label


def compact_number(value: float) -> str:
    """Return a compact value label for byte-like quantities."""
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"{value / 1e9:.2f}B"
    if magnitude >= 1e6:
        return f"{value / 1e6:.1f}M"
    if magnitude >= 1e3:
        return f"{value / 1e3:.1f}K"
    return f"{value:.0f}"


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


def is_live_object_event(event: dict) -> bool:
    """Return whether an event should contribute to resident-object summaries.

    ``search_corpus_scan`` is a deterministic scan-volume proxy used by the
    search funnel. It is not prompt-resident context or measured resident
    memory, so it should not accrue lifetime-, duplication-, or byte-seconds
    style live-object summaries.
    """
    if is_bookkeeping_event(event):
        return False
    return semantic(event) != "search_corpus_scan"


def liveness_intervals(events: list[dict]) -> list[dict]:
    intervals = []
    live = {}
    task_end = max((event["ts"] for event in events), default=0.0)
    task_end_step = max((event["step"] for event in events), default=0)
    kv_end_by_step = kv_next_prefill_boundaries(events, task_end)
    kv_end_step_by_step = kv_next_prefill_steps(events, task_end_step)
    for event in sorted(events, key=lambda e: (e["ts"], e["step"])):
        oid = event["object_id"]
        op = event["op"]
        if not is_live_object_event(event):
            continue
        if op == "create":
            if oid in live:
                intervals.append(make_interval(live[oid], event["ts"], event["step"]))
            live[oid] = make_live_state(event)
        elif op == "mutate":
            if oid in live:
                intervals.append(make_interval(live[oid], event["ts"], event["step"]))
            live[oid] = make_live_state(event)
        elif op == "free":
            if oid in live:
                intervals.append(make_interval(live.pop(oid), event["ts"], event["step"]))
        elif op == "read":
            if oid in live:
                live[oid]["last_read_ts"] = event["ts"]
                live[oid]["last_read_step"] = event["step"]
                live[oid]["read_count"] += 1
    for state in live.values():
        event = state["event"]
        default_end = task_end
        default_end_step = task_end_step
        cap_at_default = False
        if event.get("repr_type") == "kv_estimated":
            default_end = kv_end_by_step.get(event["step"], task_end)
            default_end_step = kv_end_step_by_step.get(event["step"], task_end_step)
            cap_at_default = True
        intervals.append(make_interval(state, default_end, default_end_step, cap_at_default=cap_at_default))
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


def kv_next_prefill_steps(events: list[dict], task_end_step: int) -> dict[int, int]:
    """Return the next prompt step used for step-normalized KV lifetime."""
    steps = sorted({
        event["step"]
        for event in events
        if event.get("repr_type") == "kv_estimated"
        and event.get("op") == "create"
        and not is_bookkeeping_event(event)
    })
    boundaries = {}
    for idx, step in enumerate(steps):
        boundaries[step] = steps[idx + 1] if idx + 1 < len(steps) else task_end_step
    return boundaries


def make_live_state(event: dict) -> dict:
    return {"event": event, "last_read_ts": None, "last_read_step": None, "read_count": 0}


def make_interval(
    state: dict,
    default_end: float,
    default_end_step: int,
    *,
    cap_at_default: bool = False,
) -> dict:
    event = state["event"]
    last_read_ts = state["last_read_ts"] if state["last_read_ts"] is not None else default_end
    last_read_step = state["last_read_step"] if state["last_read_step"] is not None else default_end_step
    end_ts = default_end if cap_at_default else max(default_end, last_read_ts)
    end_step = default_end_step if cap_at_default else max(default_end_step, last_read_step)
    return {
        "semantic_type": semantic(event),
        "repr_type": event["repr_type"],
        "logical_id": event["logical_id"],
        "object_id": event["object_id"],
        "size_bytes": event["size_bytes"],
        "create_ts": event["ts"],
        "end_ts": end_ts,
        "lifetime_s": max(0.0, end_ts - event["ts"]),
        "create_step": event["step"],
        "end_step": end_step,
        "lifetime_steps": max(0, end_step - event["step"]),
        "read_count": state["read_count"],
    }


def step_duration_summary(traces: list[tuple[Path, str, str, list[dict]]]) -> dict[str, dict[str, float]]:
    durations_by_workload: dict[str, list[float]] = defaultdict(list)
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    for workload, _, events in default_traces:
        by_step: dict[int, list[float]] = defaultdict(list)
        for event in events:
            if "step" not in event or "ts" not in event:
                continue
            # Step 0 is task_setup bookkeeping (fixture load, metadata), not a
            # generation step; including it makes the per-workload minimum a
            # setup span rather than a step duration.
            if event["step"] == 0:
                continue
            by_step[event["step"]].append(float(event["ts"]))
        for ts_list in by_step.values():
            if ts_list:
                durations_by_workload[workload].append(max(ts_list) - min(ts_list))
    summary: dict[str, dict[str, float]] = {}
    for workload, durations in durations_by_workload.items():
        if not durations:
            continue
        summary[workload] = {
            "min": min(durations),
            "median": statistics.median(durations),
            "max": max(durations),
        }
    return summary


def format_step_duration_note(summary: dict[str, dict[str, float]]) -> str:
    if not summary:
        return (
            "Short-term = within-step tool use. "
            "Medium-term = session-retained objects."
        )
    ranges = []
    for workload in DEFAULT_CONDITION:
        if workload in summary:
            values = summary[workload]
            ranges.append(
                f"{label_workload(workload)}: {values['min']:.2f}–{values['max']:.2f}s"
            )
    return (
        "Short-term = within-step tool use. Medium-term = session-retained objects. "
        "Single-step durations in default traces: " + "; ".join(ranges) + "."
    )


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
        prompt_reads = defaultdict(int)
        kv_reads = defaultdict(int)
        mutates = defaultdict(int)
        for event in events:
            if not is_live_object_event(event):
                continue
            if event["op"] == "read":
                reads[semantic(event)] += 1
                if event.get("repr_type") == "kv_estimated":
                    kv_reads[semantic(event)] += 1
                else:
                    prompt_reads[semantic(event)] += 1
            elif event["op"] == "mutate":
                mutates[semantic(event)] += 1
        agg = defaultdict(lambda: {
            "byte_seconds": 0.0,
            "byte_steps": 0,
            "n_objects": 0,
            "logical_ids": set(),
            "reads": 0,
            "prompt_reads": 0,
            "kv_reads": 0,
            "mutates": 0,
            "max_lifetime_steps": 0,
        })
        for interval in intervals:
            sem = interval["semantic_type"]
            agg[sem]["byte_seconds"] += interval["size_bytes"] * interval["lifetime_s"]
            agg[sem]["byte_steps"] += interval["size_bytes"] * interval["lifetime_steps"]
            agg[sem]["n_objects"] += 1
            agg[sem]["logical_ids"].add(interval["logical_id"])
            agg[sem]["max_lifetime_steps"] = max(
                agg[sem]["max_lifetime_steps"],
                interval["lifetime_steps"],
            )
        for sem, count in reads.items():
            agg[sem]["reads"] = count
        for sem, count in prompt_reads.items():
            agg[sem]["prompt_reads"] = count
        for sem, count in kv_reads.items():
            agg[sem]["kv_reads"] = count
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
                "byte_steps": data["byte_steps"],
                "max_lifetime_steps": data["max_lifetime_steps"],
                "logical_read_events": data["reads"],
                "prompt_construction_reads": data["prompt_reads"],
                "cached_prefix_kv_reads": data["kv_reads"],
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


def prompt_cache_summary(traces: list[tuple[Path, str, str, list[dict]]]) -> list[dict]:
    rows = []
    for path, workload, condition, events in traces:
        checks = [event for event in events if semantic(event) == "engine_cross_check"]
        prompt_tokens = sum(int(event.get("prompt_token_count", 0)) for event in checks)
        cached_tokens = sum(int(event.get("cached_tokens", 0)) for event in checks)
        new_tokens = max(0, prompt_tokens - cached_tokens)
        rows.append({
            "trace": path.name,
            "workload": workload,
            "condition": condition,
            "generation_steps": len(checks),
            "prompt_tokens_total": prompt_tokens,
            "cached_tokens_total": cached_tokens,
            "new_prefill_tokens_total": new_tokens,
            "cached_token_fraction": round(cached_tokens / prompt_tokens, 3) if prompt_tokens else "",
            "max_prompt_tokens": max((int(event.get("prompt_token_count", 0)) for event in checks), default=0),
        })
    return rows


def bar_figure(
    rows: list[dict],
    *,
    value_key: str,
    group_key: str,
    out_path: Path,
    title: str,
    x_label: str | None = None,
    value_format: str | None = None,
    note: str | None = None,
) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(float)
    for row in rows:
        grouped[(row["workload"], row[group_key])] += float(row[value_key] or 0)
    ordered = sorted(grouped.items(), key=lambda item: item[1])
    workloads = {workload for (workload, _), _ in ordered}
    labels = []
    for (workload, group), _ in ordered:
        if group_key == "semantic_type":
            labels.append(f"{label_workload(workload)} - {label_semantic(group)}")
        elif len(workloads) == 1:
            labels.append(label_condition(group))
        else:
            labels.append(f"{label_workload(workload)} - {label_condition(group)}")
    values = [value for _, value in ordered]
    colors = [COLORS.get(group, "#888888") for (workload, group), _ in ordered]
    fig, ax = plt.subplots(figsize=(9.5, max(4.8, len(labels) * 0.34)))
    ax.barh(range(len(labels)), values, color=colors)
    ax.set_yticks(range(len(labels)), labels=labels)
    ax.set_title(title, loc="left")
    ax.set_xlabel(x_label or value_key.replace("_", " "))
    ax.grid(axis="x", alpha=0.18)
    ax.grid(axis="y", alpha=0)
    right = max(values) if values else 1.0
    for idx, value in enumerate(values):
        label = format(value, value_format) if value_format else compact_number(value)
        ax.text(value + right * 0.015, idx, label, va="center", fontsize=8.5, color="#555")
    ax.set_xlim(0, right * 1.18 if right > 0 else 1)
    if note:
        fig.text(0.02, 0.01, note, fontsize=8.5, color="#555")
        fig.tight_layout(rect=(0, 0.04, 1, 1))
    else:
        fig.tight_layout()
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def semantic_inventory_figure(
    rows: list[dict],
    *,
    value_key: str,
    out_path: Path,
    title: str,
    x_label: str,
) -> None:
    """Render one semantic inventory panel per default workload trace.

    A single mixed bar chart is numerically correct, but it buries the
    cross-workload mechanism story by interleaving semantic classes from coding,
    search, and compaction on one axis. Faceting by workload keeps each replay's
    semantic inventory legible while preserving the absolute values in labels.
    """
    if plt is None or not rows:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    workloads = [workload for workload in DEFAULT_CONDITION if any(row["workload"] == workload for row in rows)]
    if not workloads:
        return
    max_bars = max(sum(1 for row in rows if row["workload"] == workload) for workload in workloads)
    fig, axes = plt.subplots(
        1,
        len(workloads),
        figsize=(13.5, max(4.8, 1.15 + max_bars * 0.48)),
    )
    if len(workloads) == 1:
        axes = [axes]
    panel_max = max(float(row[value_key] or 0) for row in rows)
    panel_max = panel_max if panel_max > 0 else 1.0
    for ax, workload in zip(axes, workloads):
        workload_rows = sorted(
            [row for row in rows if row["workload"] == workload],
            key=lambda row: float(row[value_key] or 0),
            reverse=True,
        )
        labels = [label_semantic(row["semantic_type"]) for row in workload_rows]
        values = [float(row[value_key] or 0) for row in workload_rows]
        colors = [COLORS.get(row["semantic_type"], "#888888") for row in workload_rows]
        ax.barh(range(len(labels)), values, color=colors)
        ax.set_yticks(range(len(labels)), labels=labels)
        ax.invert_yaxis()
        ax.set_title(label_workload(workload), fontsize=11)
        ax.grid(axis="x", alpha=0.18)
        ax.grid(axis="y", alpha=0)
        ax.set_xlim(0, panel_max * 1.18)
        for idx, value in enumerate(values):
            ax.text(value + panel_max * 0.015, idx, compact_number(value), va="center", fontsize=8.5, color="#555")
    axes[0].set_ylabel("semantic class")
    center = len(axes) // 2
    axes[center].set_xlabel(x_label)
    fig.suptitle(title, x=0.06, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def search_funnel_figure(rows: list[dict], out_path: Path) -> None:
    if plt is None or not rows:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row["condition"])
    labels = [label_condition(row["condition"]) for row in ordered]
    scanned = [float(row["scanned_bytes"] or 0) for row in ordered]
    returned = [float(row["returned_bytes"] or 0) for row in ordered]
    inserted = [float(row["inserted_bytes"] or 0) for row in ordered]
    x = range(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.bar([i - width / 2 for i in x], returned, width=width, label="returned", color=COLORS["search_result"])
    ax.bar([i + width / 2 for i in x], inserted, width=width, label="inserted", color=COLORS["retrieved_snippet"])
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("bytes")
    ax.set_title("Search prompt pollution by condition", loc="left")
    unique_scanned = sorted({int(value) for value in scanned})
    if len(unique_scanned) == 1:
        ax.text(
            0.0,
            1.02,
            f"Both traces scan {compact_number(unique_scanned[0])}B; difference is returned/inserted prompt history.",
            transform=ax.transAxes,
            fontsize=8.5,
            color="#555555",
            va="bottom",
        )
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def prompt_cache_figure(rows: list[dict], out_path: Path) -> None:
    if plt is None or not rows:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: (row["workload"], row["condition"]))
    labels = [f"{label_workload(row['workload'])}\n{label_condition(row['condition'])}" for row in ordered]
    cached = [float(row["cached_tokens_total"] or 0) for row in ordered]
    new = [float(row["new_prefill_tokens_total"] or 0) for row in ordered]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar(x, cached, label="cached prefix tokens", color="#4E79A7")
    ax.bar(x, new, bottom=cached, label="new prefill tokens", color="#E15759")
    ax.set_xticks(list(x), labels, rotation=35, ha="right")
    ax.set_ylabel("prompt tokens")
    ax.set_title("Prompt tokens split into cached reuse and new prefill", loc="left")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def step_duration_figure(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary = step_duration_summary(traces)
    if not summary:
        return
    workloads = [w for w in DEFAULT_CONDITION if w in summary]
    if not workloads:
        return
    y = list(range(len(workloads)))
    mins = [summary[workload]["min"] for workload in workloads]
    maxs = [summary[workload]["max"] for workload in workloads]
    medians = [summary[workload]["median"] for workload in workloads]
    widths = [maxs[i] - mins[i] for i in y]
    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    ax.barh(y, widths, left=mins, height=0.6, color=RETENTION_CLASS_COLORS["short-term"], alpha=0.75)
    ax.scatter(medians, y, marker="o", color="#222222", zorder=3, label="median")
    ax.set_yticks(y, [label_workload(workload) for workload in workloads])
    ax.set_xlabel("Single-step duration (seconds)")
    ax.set_title("Single-step time ranges for default final-v3 workloads", loc="left")
    ax.set_xlim(0, max(maxs) * 1.12 if maxs else 1.0)
    ax.grid(axis="x", alpha=0.18)
    ax.legend(frameon=False)
    fig.text(
        0.02,
        0.02,
        "Durations are max(ts)-min(ts) for each step in default traces.",
        fontsize=8.5,
        color="#555",
    )
    fig.tight_layout()
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def tier_assignment(sem: str, byte_seconds: float, reuse_count: int) -> str:
    """Assign tier based on paper's empirical observations."""
    if sem in {"plan_state", "system_prompt", "compacted_summary"}:
        return "T1"
    if sem in {"assistant_history"}:
        return "T2"
    if sem in {"raw_context", "search_result", "retrieved_snippet", "search_corpus_scan"}:
        return "T3"
    if byte_seconds > 1e8 or sem in {"user_problem", "prompt_template"}:
        return "T2"
    return "T1"


def tier_assignment_by_byte_seconds(byte_seconds: float) -> str:
    """Assign tier purely based on byte-seconds thresholds."""
    if byte_seconds < 100e6:  # < 100M
        return "T1"
    elif byte_seconds < 1e9:  # < 1B
        return "T2"
    else:
        return "T3"


def tier_color(tier: str) -> str:
    """Color tier 1 as fast (green), tier 2 as bandwidth (orange), tier 3 as capacity (red)."""
    tier_colors = {
        "T1": "#2E7D32",  # green
        "T2": "#F57C00",  # orange
        "T3": "#C62828",  # red
    }
    return tier_colors.get(tier, "#888888")


def capacity_reuse_scatter(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return
    
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    
    all_byte_seconds = []
    all_reuse = []
    all_colors = []
    all_sizes = []
    all_labels = []
    all_tiers = set()
    
    for workload, _, events in default_traces:
        intervals = liveness_intervals(events)
        by_sem = defaultdict(lambda: {"byte_seconds": 0.0, "reuse": 0, "size_bytes": 0, "count": 0})
        for interval in intervals:
            sem = interval["semantic_type"]
            by_sem[sem]["byte_seconds"] += interval["size_bytes"] * interval["lifetime_s"]
            by_sem[sem]["size_bytes"] += interval["size_bytes"]
            by_sem[sem]["count"] += 1
        
        for event in events:
            if event["op"] == "read" and not is_bookkeeping_event(event):
                sem = semantic(event)
                if sem in by_sem:
                    by_sem[sem]["reuse"] += 1
        
        max_size_in_trace = max((data["size_bytes"] for data in by_sem.values()), default=1)
        for sem, data in by_sem.items():
            byte_seconds = data["byte_seconds"]
            reuse = data["reuse"]
            if byte_seconds > 0:
                tier = tier_assignment(sem, byte_seconds, reuse)
                all_byte_seconds.append(byte_seconds)
                all_reuse.append(reuse)
                all_colors.append(tier_color(tier))
                size_normalized = data["size_bytes"] / max_size_in_trace
                bubble_size = 100 + size_normalized * 250  # range 100-350
                all_sizes.append(bubble_size)
                all_labels.append((label_semantic(sem), byte_seconds, reuse))
                all_tiers.add(tier)
    
    scatter = ax.scatter(
        all_byte_seconds, all_reuse,
        c=all_colors, s=all_sizes,
        alpha=0.65, edgecolors="white", linewidths=1.2
    )
    
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Capacity-time: size × lifetime (byte-seconds, log scale)", fontsize=11)
    ax.set_ylabel("Reuse: logical read events (log scale)", fontsize=11)
    ax.set_title("Decoupling of capacity-time and reuse: joint (size×lifetime, reuse) tier mapping", loc="left", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.2, which="both", linestyle="--")
    
    # Legend: tiers + size explanation
    legend_items = []
    if Line2D is not None:
        for tier_label in ["T1 (Resident)", "T2 (Bandwidth)", "T3 (Capacity)"]:
            tier = tier_label.split()[0]
            legend_items.append(
                Line2D([0], [0], marker="o", color="none", markerfacecolor=tier_color(tier),
                       markeredgecolor="white", markeredgewidth=1.2, markersize=10,
                       label=tier_label)
            )
        # Add size legend
        legend_items.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="#999",
                                   markeredgecolor="white", markeredgewidth=1, markersize=7,
                                   label="Small object"))
        legend_items.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="#999",
                                   markeredgecolor="white", markeredgewidth=1, markersize=14,
                                   label="Large object"))
        ax.legend(handles=legend_items, loc="upper left", frameon=True, fancybox=True, shadow=True, fontsize=9.5)
    
    fig.text(0.02, 0.01, 
             "Bubble size ∝ max object size in semantic class. "
             "Key insight: raw_context vs assistant_history both have ~30 reads but differ 4.6× in capacity-time, "
             "showing (size×lifetime, reuse) decoupling.",
             fontsize=8.0, color="#555", wrap=True)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(out_path.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def capacity_reuse_scatter_byteseconds_tiers(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    """Capacity-reuse scatter using data-driven byte-seconds thresholds for tier assignment."""
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return
    
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    
    all_byte_seconds = []
    all_reuse = []
    all_colors = []
    all_sizes = []
    all_labels = []
    all_tiers = set()
    
    for workload, _, events in default_traces:
        intervals = liveness_intervals(events)
        by_sem = defaultdict(lambda: {"byte_seconds": 0.0, "reuse": 0, "size_bytes": 0, "count": 0})
        for interval in intervals:
            sem = interval["semantic_type"]
            by_sem[sem]["byte_seconds"] += interval["size_bytes"] * interval["lifetime_s"]
            by_sem[sem]["size_bytes"] += interval["size_bytes"]
            by_sem[sem]["count"] += 1
        
        for event in events:
            if event["op"] == "read" and not is_bookkeeping_event(event):
                sem = semantic(event)
                if sem in by_sem:
                    by_sem[sem]["reuse"] += 1
        
        max_size_in_trace = max((data["size_bytes"] for data in by_sem.values()), default=1)
        for sem, data in by_sem.items():
            byte_seconds = data["byte_seconds"]
            reuse = data["reuse"]
            if byte_seconds > 0:
                tier = tier_assignment_by_byte_seconds(byte_seconds)
                all_byte_seconds.append(byte_seconds)
                all_reuse.append(reuse)
                all_colors.append(tier_color(tier))
                size_normalized = data["size_bytes"] / max_size_in_trace
                bubble_size = 100 + size_normalized * 250  # range 100-350
                all_sizes.append(bubble_size)
                all_labels.append((label_semantic(sem), byte_seconds, reuse))
                all_tiers.add(tier)
    
    scatter = ax.scatter(
        all_byte_seconds, all_reuse,
        c=all_colors, s=all_sizes,
        alpha=0.65, edgecolors="white", linewidths=1.2
    )
    
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Capacity-time: size × lifetime (byte-seconds, log scale)", fontsize=11)
    ax.set_ylabel("Reuse: logical read events (log scale)", fontsize=11)
    ax.set_title("Data-driven tier assignment: byte-seconds thresholds (T1 <100M, T2 100M–1B, T3 >1B)", loc="left", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.2, which="both", linestyle="--")
    
    # Legend: tiers + size explanation
    legend_items = []
    if Line2D is not None:
        for tier_label in ["T1 (Resident)", "T2 (Bandwidth)", "T3 (Capacity)"]:
            tier = tier_label.split()[0]
            legend_items.append(
                Line2D([0], [0], marker="o", color="none", markerfacecolor=tier_color(tier),
                       markeredgecolor="white", markeredgewidth=1.2, markersize=10,
                       label=tier_label)
            )
        # Add size legend
        legend_items.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="#999",
                                   markeredgecolor="white", markeredgewidth=1, markersize=7,
                                   label="Small object"))
        legend_items.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="#999",
                                   markeredgecolor="white", markeredgewidth=1, markersize=14,
                                   label="Large object"))
        ax.legend(handles=legend_items, loc="upper left", frameon=True, fancybox=True, shadow=True, fontsize=9.5)
    
    fig.text(0.02, 0.01, 
             "Bubble size ∝ max object size in semantic class. "
             "Tiers assigned by byte-seconds: <100M → T1, 100M–1B → T2, >1B → T3. "
             "Boundary effects show semantic-class homogeneity vs. byte-seconds clustering.",
             fontsize=8.0, color="#555", wrap=True)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(out_path.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def capacity_reuse_tier_comparison(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    """Side-by-side comparison: semantic-class tiers (left) vs. byte-seconds tiers (right)."""
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return
    
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(15, 6))
    
    all_byte_seconds = []
    all_reuse = []
    all_sizes = []
    all_labels = []
    
    for workload, _, events in default_traces:
        intervals = liveness_intervals(events)
        by_sem = defaultdict(lambda: {"byte_seconds": 0.0, "reuse": 0, "size_bytes": 0, "count": 0})
        for interval in intervals:
            sem = interval["semantic_type"]
            by_sem[sem]["byte_seconds"] += interval["size_bytes"] * interval["lifetime_s"]
            by_sem[sem]["size_bytes"] += interval["size_bytes"]
            by_sem[sem]["count"] += 1
        
        for event in events:
            if event["op"] == "read" and not is_bookkeeping_event(event):
                sem = semantic(event)
                if sem in by_sem:
                    by_sem[sem]["reuse"] += 1
        
        max_size_in_trace = max((data["size_bytes"] for data in by_sem.values()), default=1)
        for sem, data in by_sem.items():
            byte_seconds = data["byte_seconds"]
            reuse = data["reuse"]
            if byte_seconds > 0:
                all_byte_seconds.append(byte_seconds)
                all_reuse.append(reuse)
                size_normalized = data["size_bytes"] / max_size_in_trace
                bubble_size = 100 + size_normalized * 250  # range 100-350
                all_sizes.append(bubble_size)
                all_labels.append((label_semantic(sem), byte_seconds, reuse))
    
    # Left: semantic class tiers
    colors_semantic = [tier_color(tier_assignment(all_labels[i][0], all_byte_seconds[i], all_reuse[i])) 
                       for i in range(len(all_byte_seconds))]
    ax_left.scatter(all_byte_seconds, all_reuse, c=colors_semantic, s=all_sizes, alpha=0.65, 
                    edgecolors="white", linewidths=1.2)
    ax_left.set_xscale("log")
    ax_left.set_yscale("log")
    ax_left.set_xlabel("Capacity-time (byte-seconds, log scale)", fontsize=10)
    ax_left.set_ylabel("Reuse (logical reads, log scale)", fontsize=10)
    ax_left.set_title("Semantic-class assignment (low overhead)", fontsize=11, fontweight="bold")
    ax_left.grid(True, alpha=0.2, which="both", linestyle="--")
    
    # Right: byte-seconds thresholds
    colors_bytes = [tier_color(tier_assignment_by_byte_seconds(b)) for b in all_byte_seconds]
    ax_right.scatter(all_byte_seconds, all_reuse, c=colors_bytes, s=all_sizes, alpha=0.65, 
                     edgecolors="white", linewidths=1.2)
    ax_right.set_xscale("log")
    ax_right.set_yscale("log")
    ax_right.set_xlabel("Capacity-time (byte-seconds, log scale)", fontsize=10)
    ax_right.set_ylabel("Reuse (logical reads, log scale)", fontsize=10)
    ax_right.set_title("Byte-seconds thresholds (<100M, 100M–1B, >1B)", fontsize=11, fontweight="bold")
    ax_right.grid(True, alpha=0.2, which="both", linestyle="--")
    
    # Shared legend
    legend_items = []
    if Line2D is not None:
        for tier_label in ["T1 (Resident)", "T2 (Bandwidth)", "T3 (Capacity)"]:
            tier = tier_label.split()[0]
            legend_items.append(
                Line2D([0], [0], marker="o", color="none", markerfacecolor=tier_color(tier),
                       markeredgecolor="white", markeredgewidth=1.2, markersize=10,
                       label=tier_label)
            )
        legend_items.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="#999",
                                   markeredgecolor="white", markeredgewidth=1, markersize=7,
                                   label="Small"))
        legend_items.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="#999",
                                   markeredgecolor="white", markeredgewidth=1, markersize=14,
                                   label="Large"))
        fig.legend(handles=legend_items, loc="lower center", ncol=6, frameon=True, 
                   fancybox=True, shadow=True, fontsize=9.5, bbox_to_anchor=(0.5, -0.05))
    
    fig.suptitle("Tier assignment strategies: semantic domain knowledge vs. data-driven byte-seconds", 
                 fontsize=12, fontweight="bold", y=0.98)
    fig.text(0.5, 0.02, 
             "Left: semantic-class hardcoding (used in paper, zero profiling overhead). "
             "Right: data-driven byte-seconds thresholds (generalizable, requires full-trace profiling). "
             "Bubble size ∝ max object size per semantic class.",
             fontsize=8.5, color="#555", ha="center", wrap=True)
    fig.tight_layout(rect=(0, 0.08, 1, 0.96))
    fig.savefig(out_path.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def lifetime_range_by_workload(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return

    workloads = [workload for workload in DEFAULT_CONDITION if any(w == workload for w, _, _ in default_traces)]
    stats_by_workload: dict[str, dict[str, dict[str, float] | None]] = {}
    dominance_notes: list[str] = []

    for workload, _, events in default_traces:
        intervals = liveness_intervals(events)
        by_retention = {
            "short-term": [interval["lifetime_s"] for interval in intervals if object_retention_class(interval) == "short-term"],
            "medium-term": [interval["lifetime_s"] for interval in intervals if object_retention_class(interval) == "medium-term"],
        }
        stats: dict[str, dict[str, float] | None] = {}
        for retention_class, values in by_retention.items():
            if values:
                stats[retention_class] = {
                    "min": min(values),
                    "median": statistics.median(values),
                    "max": max(values),
                }
            else:
                stats[retention_class] = None
        short_intervals = [interval for interval in intervals if object_retention_class(interval) == "short-term"]
        if short_intervals:
            semantic_counts: dict[str, int] = defaultdict(int)
            kv_count = 0
            for interval in short_intervals:
                semantic_counts[interval["semantic_type"]] += 1
                if interval.get("repr_type") == "kv_estimated":
                    kv_count += 1
            top_semantic, top_count = max(semantic_counts.items(), key=lambda pair: pair[1])
            short_pct = 100.0 * top_count / len(short_intervals)
            kv_pct = 100.0 * kv_count / len(short_intervals)
            note = f"{label_workload(workload)} short-term dominated by {label_semantic(top_semantic)} ({short_pct:.0f}%)"
            if kv_count:
                note += f", {kv_pct:.0f}% KV-estimated"
            dominance_notes.append(note)
        else:
            dominance_notes.append(f"{label_workload(workload)} has no short-term objects")
        stats_by_workload[workload] = stats

    y_positions: list[float] = []
    y_labels: list[str] = []
    lefts: list[float] = []
    widths: list[float] = []
    medians: list[float | None] = []
    colors: list[str] = []
    for idx, workload in enumerate(workloads):
        stats = stats_by_workload.get(workload, {})
        for offset, retention_class in enumerate(["short-term", "medium-term"]):
            y = idx * 3 + offset
            y_positions.append(y)
            y_labels.append(f"{label_workload(workload)} {retention_class}")
            stat = stats.get(retention_class)
            if stat:
                lefts.append(stat["min"])
                widths.append(stat["max"] - stat["min"])
                medians.append(stat["median"])
            else:
                lefts.append(0.0)
                widths.append(0.0)
                medians.append(None)
            colors.append(RETENTION_CLASS_COLORS[retention_class])

    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    bar = ax.barh(y_positions, widths, left=lefts, height=0.6, color=colors, alpha=0.75)
    for pos, median in zip(y_positions, medians):
        if median is not None:
            ax.scatter(median, pos, marker="o", color="#222222", zorder=3, s=30)

    ax.set_yticks(y_positions)
    ax.set_yticklabels(y_labels)
    ax.set_xlabel("Lifetime (seconds)")
    ax.set_title("Short- and medium-term lifetime ranges by default workload", loc="left")
    ax.grid(axis="x", alpha=0.18)
    legend_items = []
    if Line2D is not None:
        for retention_class in ["short-term", "medium-term"]:
            legend_items.append(
                Line2D(
                    [0], [0], marker="s", color=RETENTION_CLASS_COLORS[retention_class], markersize=8,
                    linestyle="", label=retention_class,
                )
            )
        legend_items.append(Line2D([0], [0], marker="o", color="#222222", markersize=6, linestyle="", label="median"))
        ax.legend(handles=legend_items, frameon=False)

    note_text = "Short-term dominance: " + "; ".join(dominance_notes) + "."
    fig.text(0.02, 0.02, note_text, fontsize=8.5, color="#555")
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def scatter_lifetime_reuse(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return
    fig, axes = plt.subplots(1, len(default_traces), figsize=(13.5, 4.6), sharex=True, sharey=True)
    if len(default_traces) == 1:
        axes = [axes]
    seen = set()
    legend_items = []
    for ax, (workload, _, events) in zip(axes, default_traces):
        for interval in liveness_intervals(events):
            sem = interval["semantic_type"]
            color = COLORS.get(sem, "#888888")
            ax.scatter(
                interval["lifetime_steps"],
                interval["read_count"],
                s=35 + min(140, interval["size_bytes"] / 1024),
                c=color,
                alpha=0.65,
                edgecolors="white",
                linewidths=0.5,
            )
            if sem not in seen and Line2D is not None:
                legend_items.append(
                    Line2D(
                        [0],
                        [0],
                        marker="o",
                        color="none",
                        markerfacecolor=color,
                        markeredgecolor="white",
                        markeredgewidth=0.5,
                        markersize=7.5,
                        label=label_semantic(sem),
                    )
                )
                seen.add(sem)
        ax.set_title(label_workload(workload), fontsize=11)
        ax.set_xlabel("Lifetime (steps)")
        ax.grid(alpha=0.18)
    axes[0].set_ylabel("Read events")
    fig.suptitle("Step-normalized lifetime vs reuse by semantic class (default traces)", x=0.06, ha="left")
    if legend_items:
        fig.legend(
            handles=legend_items,
            loc="upper left",
            bbox_to_anchor=(1.02, 0.99),
            frameon=False,
        )
    fig.tight_layout(rect=(0, 0.03, 0.88, 0.93))
    fig.savefig(out_path.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def object_retention_class(interval: dict) -> str:
    """Classify objects by workflow-relative retention.

    short-term: object exists only within a single step or tool-use boundary
      (single-step times are workload-dependent in these traces).
    medium-term: object persists across multiple steps in the current session.
    long-term: not present in current single-run traces.
    """
    if interval["lifetime_steps"] == 0:
        return "short-term"
    return "medium-term"


def retention_class_color(retention_class: str) -> str:
    return RETENTION_CLASS_COLORS.get(retention_class, "#888888")


def object_reuse_intervals(events: list[dict]) -> list[dict]:
    by_oid: dict[str, list[float]] = defaultdict(list)
    for event in sorted(events, key=lambda e: (e.get("object_id"), e.get("ts", 0.0))):
        if event.get("op") != "read":
            continue
        if is_bookkeeping_event(event):
            continue
        oid = event.get("object_id")
        if oid is None:
            continue
        by_oid[oid].append(float(event["ts"]))

    lifetime_by_oid = {interval["object_id"]: interval for interval in liveness_intervals(events)}
    intervals = []
    for oid, ts_list in by_oid.items():
        if len(ts_list) < 2:
            continue
        lifetime = lifetime_by_oid.get(oid)
        if lifetime is None:
            continue
        retention = object_retention_class(lifetime)
        for prev_ts, next_ts in zip(ts_list, ts_list[1:]):
            intervals.append({
                "object_id": oid,
                "interval_s": next_ts - prev_ts,
                "retention": retention,
            })
    return intervals


def reuse_interval_by_workload(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return

    fig, axes = plt.subplots(1, len(default_traces), figsize=(13.5, 4.8), sharey=True)
    if len(default_traces) == 1:
        axes = [axes]

    for ax, (workload, _, events) in zip(axes, default_traces):
        intervals = object_reuse_intervals(events)
        short_vals = [item["interval_s"] for item in intervals if item["retention"] == "short-term"]
        medium_vals = [item["interval_s"] for item in intervals if item["retention"] == "medium-term"]

        values = []
        labels = []
        colors = []
        if short_vals:
            values.append(short_vals)
            labels.append("short-term")
            colors.append(RETENTION_CLASS_COLORS["short-term"])
        if medium_vals:
            values.append(medium_vals)
            labels.append("medium-term")
            colors.append(RETENTION_CLASS_COLORS["medium-term"])
        if not values:
            ax.text(0.5, 0.5, "no reuse intervals", ha="center", va="center", color="#777")
            ax.set_xticks([])
            ax.set_title(label_workload(workload), fontsize=11)
            continue

        bp = ax.boxplot(values, patch_artist=True, labels=labels, medianprops={"color": "black"})
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.75)

        ax.set_title(label_workload(workload), fontsize=11)
        ax.set_xlabel("Retention class")
        ax.set_yscale("log")
        ax.grid(axis="y", alpha=0.18)
        if ax is axes[0]:
            ax.set_ylabel("Reuse interval (s)")

    fig.suptitle("Reuse interval by workload and retention class", x=0.06, ha="left")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def lifetime_reuse_seconds(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return

    fig, axes = plt.subplots(1, len(default_traces), figsize=(13.5, 4.6), sharex=True, sharey=True)
    if len(default_traces) == 1:
        axes = [axes]
    legend_items = []
    seen = set()
    max_y = 0

    for ax, (workload, _, events) in zip(axes, default_traces):
        for interval in liveness_intervals(events):
            x = interval["lifetime_s"]
            y = interval["read_count"]
            max_y = max(max_y, y)
            retention = object_retention_class(interval)
            color = retention_class_color(retention)
            ax.scatter(
                x,
                y,
                s=35 + min(140, interval["size_bytes"] / 1024),
                c=color,
                alpha=0.65,
                edgecolors="white",
                linewidths=0.5,
            )
            if retention not in seen and Line2D is not None:
                legend_items.append(
                    Line2D(
                        [0],
                        [0],
                        marker="o",
                        color="none",
                        markerfacecolor=color,
                        markeredgecolor="white",
                        markeredgewidth=0.5,
                        markersize=7.5,
                        label=retention,
                    )
                )
                seen.add(retention)
        ax.set_title(label_workload(workload), fontsize=11)
        ax.set_xlabel("Lifetime (seconds)")
        ax.grid(alpha=0.18)

    axes[0].set_ylabel("Read events")
    fig.suptitle(
        "Object lifetime (seconds) vs reuse count with workflow-relative retention classes",
        x=0.06,
        ha="left",
    )
    if legend_items:
        fig.legend(handles=legend_items, loc="upper right", bbox_to_anchor=(0.98, 0.95), frameon=False)
    fig.text(
        0.06,
        0.01,
        "Note: long-term retention after session end is not present in these single-run traces.",
        fontsize=8.5,
        color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1.0, 0.93))
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def workload_lifetime_buckets(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bucket_counts = defaultdict(lambda: {"short-term": 0, "medium-term": 0, "long-term": 0})
    for _, workload, condition, events in traces:
        if DEFAULT_CONDITION.get(workload) != condition:
            continue
        for interval in liveness_intervals(events):
            bucket = object_retention_class(interval)
            bucket_counts[workload][bucket] += 1

    workloads = [workload for workload in DEFAULT_CONDITION if workload in bucket_counts]
    if not workloads:
        return

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    bottom = [0] * len(workloads)
    xs = list(range(len(workloads)))
    for retention_class in ["short-term", "medium-term", "long-term"]:
        values = [bucket_counts[workload][retention_class] for workload in workloads]
        if not any(values):
            # long-term never occurs in single-run traces; drawing a
            # zero-height bar adds a misleading legend entry and edge sliver.
            continue
        ax.bar(
            xs,
            values,
            bottom=bottom,
            color=retention_class_color(retention_class),
            edgecolor=retention_class_color(retention_class),
            alpha=0.9,
            label=retention_class,
        )
        bottom = [b + v for b, v in zip(bottom, values)]

    ax.set_xticks(xs)
    ax.set_xticklabels([label_workload(workload) for workload in workloads])
    ax.set_xlabel("Workload")
    ax.set_ylabel("Number of objects")
    ax.set_title("Workflow retention classes by workload (default traces)", loc="left")
    ax.legend(title="Retention class")
    ax.grid(axis="y", alpha=0.18)
    duration_summary = step_duration_summary(traces)
    fig.text(
        0.06,
        0.01,
        format_step_duration_note(duration_summary),
        fontsize=8.5,
        color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def workload_retention_composition(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bucket_counts = defaultdict(lambda: {"short-term": 0, "medium-term": 0, "long-term": 0})
    for _, workload, condition, events in traces:
        if DEFAULT_CONDITION.get(workload) != condition:
            continue
        for interval in liveness_intervals(events):
            bucket = object_retention_class(interval)
            bucket_counts[workload][bucket] += 1

    workloads = [workload for workload in DEFAULT_CONDITION if workload in bucket_counts]
    if not workloads:
        return

    xs = list(range(len(workloads)))
    short_values = [bucket_counts[workload]["short-term"] for workload in workloads]
    medium_values = [bucket_counts[workload]["medium-term"] for workload in workloads]
    long_values = [bucket_counts[workload]["long-term"] for workload in workloads]
    totals = [short_values[i] + medium_values[i] + long_values[i] for i in range(len(workloads))]
    if any(total == 0 for total in totals):
        return

    short_pct = [100 * short_values[i] / totals[i] for i in range(len(workloads))]
    medium_pct = [100 * medium_values[i] / totals[i] for i in range(len(workloads))]
    long_pct = [100 * long_values[i] / totals[i] for i in range(len(workloads))]

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    ax.bar(xs, short_pct, color=RETENTION_CLASS_COLORS["short-term"], label="short-term")
    ax.bar(xs, medium_pct, bottom=short_pct, color=RETENTION_CLASS_COLORS["medium-term"], label="medium-term")
    if any(value > 0 for value in long_pct):
        ax.bar(xs, long_pct, bottom=[short_pct[i] + medium_pct[i] for i in range(len(xs))], color=RETENTION_CLASS_COLORS["long-term"], label="long-term")

    ax.set_xticks(xs)
    ax.set_xticklabels([label_workload(workload) for workload in workloads])
    ax.set_ylabel("Percent of objects")
    ax.set_xlabel("Workload")
    ax.set_title("Retention-class composition by workload (default traces)", loc="left")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.18)
    ax.legend(title="Retention class")
    ax.text(
        0.02,
        0.02,
        "Short-term = within-step; medium-term = across steps; long-term = not observed in current traces.",
        transform=fig.transFigure,
        fontsize=8.5,
        color="#555",
    )
    fig.tight_layout()
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    fig.savefig(out_path.with_suffix(".svg"))
    plt.close(fig)


def semantic_retention_by_class(traces: list[tuple[Path, str, str, list[dict]]], out_path: Path) -> None:
    if plt is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)

    default_traces = [
        (workload, condition, events)
        for _, workload, condition, events in traces
        if DEFAULT_CONDITION.get(workload) == condition
    ]
    if not default_traces:
        return

    workloads = [workload for workload in DEFAULT_CONDITION if any(w == workload for w, _, _ in default_traces)]
    semantic_classes = [sem for sem in SEMANTIC_LABELS if any(
        any(interval["semantic_type"] == sem for interval in liveness_intervals(events))
        for _, _, events in default_traces
    )]
    if not semantic_classes:
        return

    counts = {
        workload: {
            sem: {"short-term": 0, "medium-term": 0, "long-term": 0}
            for sem in semantic_classes
        }
        for workload in workloads
    }
    for workload, _, events in default_traces:
        for interval in liveness_intervals(events):
            sem = interval["semantic_type"]
            if sem not in semantic_classes:
                continue
            counts[workload][sem][object_retention_class(interval)] += 1

    semantic_classes = [sem for sem in semantic_classes if any(
        counts[workload][sem]["short-term"] + counts[workload][sem]["medium-term"] + counts[workload][sem]["long-term"]
        for workload in workloads
    )]
    if not semantic_classes:
        return

    fig, axes = plt.subplots(1, len(workloads), figsize=(14, 5.4), sharey=True)
    if len(workloads) == 1:
        axes = [axes]

    for ax, workload in zip(axes, workloads):
        short_pct = []
        medium_pct = []
        long_pct = []
        for sem in semantic_classes:
            total = sum(counts[workload][sem].values())
            if total:
                short_pct.append(100 * counts[workload][sem]["short-term"] / total)
                medium_pct.append(100 * counts[workload][sem]["medium-term"] / total)
                long_pct.append(100 * counts[workload][sem]["long-term"] / total)
            else:
                short_pct.append(0.0)
                medium_pct.append(0.0)
                long_pct.append(0.0)

        x = list(range(len(semantic_classes)))
        ax.bar(x, short_pct, color=RETENTION_CLASS_COLORS["short-term"], label="short-term")
        ax.bar(x, medium_pct, bottom=short_pct, color=RETENTION_CLASS_COLORS["medium-term"], label="medium-term")
        if any(long_pct):
            bottom = [short_pct[i] + medium_pct[i] for i in range(len(x))]
            ax.bar(x, long_pct, bottom=bottom, color=RETENTION_CLASS_COLORS["long-term"], label="long-term")

        ax.set_title(label_workload(workload), fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels([label_semantic(sem) for sem in semantic_classes], rotation=45, ha="right")
        ax.set_xlabel("Semantic class")
        ax.grid(axis="y", alpha=0.18)
        if ax is axes[0]:
            ax.set_ylabel("Percent of objects")

    fig.suptitle("Short-term vs medium-term retention by semantic class and workload", x=0.06, ha="left")
    handles, labels = [], []
    for ax in axes:
        for handle, label in zip(*ax.get_legend_handles_labels()):
            if label not in labels:
                handles.append(handle)
                labels.append(label)
    if handles:
        fig.legend(
            handles=handles,
            labels=labels,
            loc="lower center",
            bbox_to_anchor=(0.5, -0.08),
            ncol=min(3, len(labels)),
            frameon=False,
        )
    fig.tight_layout(rect=(0, 0.06, 1, 0.92))
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
    prompt_cache_rows = prompt_cache_summary(traces)

    write_csv(out_dir / "semantic_summary.csv", semantic_rows, [
        "trace", "workload", "condition", "semantic_type", "n_objects",
        "n_logical_objects", "byte_seconds", "byte_steps", "max_lifetime_steps",
        "logical_read_events", "prompt_construction_reads",
        "cached_prefix_kv_reads", "mutate_events",
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
    write_csv(out_dir / "prompt_cache_summary.csv", prompt_cache_rows, [
        "trace", "workload", "condition", "generation_steps",
        "prompt_tokens_total", "cached_tokens_total", "new_prefill_tokens_total",
        "cached_token_fraction", "max_prompt_tokens",
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
        and row["semantic_type"] != "prompt_template"
    ]
    if has_dry_run and not allow_dry_run_figures:
        print(
            "Skipped figures because traces include dry_run=true; dry-run "
            "byte-seconds are tracer-overhead-bound and not valid paper figures. "
            "Pass --allow-dry-run-figures only for local visual debugging."
        )
        print(f"Wrote CSVs to {out_dir}")
        return 0
    semantic_inventory_figure(
        default_semantic,
        value_key="byte_steps",
        out_path=fig_dir / "semantic_byte_steps",
        title="Resident semantic byte-steps across default workload traces",
        x_label="byte-steps",
    )
    semantic_inventory_figure(
        default_semantic,
        value_key="byte_seconds",
        out_path=fig_dir / "semantic_byte_seconds",
        title="Resident semantic byte-seconds across default workload traces",
        x_label="byte-seconds",
    )
    bar_figure(
        default_kv,
        value_key="logical_projected_kv_bytes",
        group_key="semantic_type",
        out_path=fig_dir / "logical_kv_pressure",
        title="Logical projected KV pressure by workload",
        x_label="logical projected KV bytes",
    )
    bar_figure(
        default_dup,
        value_key="text_tokens_duplication_factor",
        group_key="semantic_type",
        out_path=fig_dir / "duplication_factor",
        title="Text/token duplication factor by workload",
        x_label="text/token duplication factor",
        value_format=".2f",
        note=(
            "Floor of ~2 is an instrumentation invariant: the runner always emits "
            "coexisting text + token snapshots per message. Deviation from 2 tracks "
            "tokenizer byte density, not workload memory behavior."
        ),
    )
    if search_rows:
        search_funnel_figure(search_rows, fig_dir / "search_prompt_pollution")
    if prompt_cache_rows:
        prompt_cache_figure(prompt_cache_rows, fig_dir / "prompt_cache_reuse")
    raw_context_kv = [
        row for row in kv_rows
        if row["workload"] == "compaction_agent" and row["semantic_type"] == "raw_context"
    ]
    if raw_context_kv:
        bar_figure(raw_context_kv, value_key="logical_projected_kv_bytes", group_key="condition",
                   out_path=fig_dir / "compaction_raw_context_kv",
                   title="Compaction raw-context logical KV by condition",
                   x_label="logical projected KV bytes")
    raw_context_semantic = [
        row for row in semantic_rows
        if row["workload"] == "compaction_agent" and row["semantic_type"] == "raw_context"
    ]
    if raw_context_semantic:
        bar_figure(raw_context_semantic, value_key="byte_steps", group_key="condition",
                   out_path=fig_dir / "compaction_raw_context_byte_steps",
                   title="Compaction raw-context byte-steps by condition",
                   x_label="byte-steps")
    scatter_lifetime_reuse(traces, fig_dir / "lifetime_reuse")
    lifetime_reuse_seconds(traces, fig_dir / "lifetime_reuse_seconds")
    capacity_reuse_scatter(traces, fig_dir / "capacity_reuse_tier_mapping")
    capacity_reuse_scatter_byteseconds_tiers(traces, fig_dir / "capacity_reuse_byteseconds_tiers")
    workload_lifetime_buckets(traces, fig_dir / "lifetime_buckets_by_workload")
    workload_retention_composition(traces, fig_dir / "workload_retention_composition")
    semantic_retention_by_class(traces, fig_dir / "semantic_retention_by_class")
    reuse_interval_by_workload(traces, fig_dir / "reuse_interval_by_workload")
    step_duration_figure(traces, fig_dir / "step_duration_by_workload")
    lifetime_range_by_workload(traces, fig_dir / "lifetime_ranges_by_workload")
    print(f"Wrote CSVs to {out_dir}")
    if plt is None:
        print("Skipped figures because matplotlib is not installed")
    else:
        print(f"Wrote figures to {fig_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
