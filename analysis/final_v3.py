"""Analyze final-v3 semantic traces and generate artifact CSVs/figures.

Read counts are logical prompt-construction accesses, not hardware memory
transactions. KV byte counts are analytical projections, not physical residency.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
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
            if not is_live_object_event(event):
                continue
            if event["op"] == "read":
                reads[semantic(event)] += 1
            elif event["op"] == "mutate":
                mutates[semantic(event)] += 1
        agg = defaultdict(lambda: {
            "byte_seconds": 0.0,
            "byte_steps": 0,
            "n_objects": 0,
            "logical_ids": set(),
            "reads": 0,
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
        ax.text(value + right * 0.015, idx, compact_number(value), va="center", fontsize=8.5, color="#555")
    ax.set_xlim(0, right * 1.18 if right > 0 else 1)
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
        fig.legend(handles=legend_items, loc="center left", bbox_to_anchor=(0.98, 0.5), frameon=False)
    fig.tight_layout(rect=(0, 0, 0.9, 0.93))
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
        "logical_read_events", "mutate_events",
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
    )
    scatter_lifetime_reuse(traces, fig_dir / "lifetime_reuse")
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
    print(f"Wrote CSVs to {out_dir}")
    if plt is None:
        print("Skipped figures because matplotlib is not installed")
    else:
        print(f"Wrote figures to {fig_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
