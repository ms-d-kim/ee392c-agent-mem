"""Cross-step memory carry-over analysis for final-v3 traces.

This is the contribution that separates this project from GainSight. GainSight
profiles activation lifetime *within a single forward pass*; here we profile how
long a *logical object* (a message, a tool result, a retrieved snippet) survives
*across* agent steps. At every generate step the runner re-reads and re-projects
every still-active object (``read_active_history`` + ``emit_kv_spans`` in
``agent/run_final_v3.py``), so the per-step KV working set decomposes exactly
into "created this step" vs "carried from an earlier step".

For each generate step k we attribute the projected KV to the step at which each
object's content was first prefilled (its ``logical_id`` first KV-projection).
The stacked bars therefore read bottom-up as the age structure of the working
set: the topmost (origin == k) slice is genuinely new prefill work; everything
below it is carry-over that a tiered memory system could resolve from a
cached/cheaper tier.

The decomposition is computed purely from logical KV re-projections and never
reads the engine's cached-token counters, so it is independent of the prefix-
cache condition by construction: the coding cache-on and cache-off panels
differ only through sampled generation text, not through caching itself.

Run:
    python3 -m analysis.carryover traces/final_v3
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


def _configure_matplotlib_cache() -> None:
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
except ImportError:  # pragma: no cover - optional local dependency
    matplotlib = None
    plt = None

SVG_HASH_SALT = "ee392c-final-v3"
SVG_METADATA = {"Date": None}

# Panel layout: defaults on top row, contrast ablation on the bottom row.
PANELS = [
    [("coding_agent", "cache_on"), ("search_agent", "targeted"), ("compaction_agent", "compaction_on")],
    [("coding_agent", "cache_off"), ("search_agent", "broad"), ("compaction_agent", "compaction_off")],
]

TITLES = {
    ("coding_agent", "cache_on"): "coding · cache on (default)",
    ("coding_agent", "cache_off"): "coding · cache off",
    ("search_agent", "targeted"): "search · targeted (default)",
    ("search_agent", "broad"): "search · broad",
    ("compaction_agent", "compaction_on"): "compaction · on (default)",
    ("compaction_agent", "compaction_off"): "compaction · off",
}

# Sequential ramp indexed by origin step. The earliest observed origin is
# step 1 (the first generate step prefills the initial system+problem prompt);
# step 0 is task_setup bookkeeping and never projects KV.
ORIGIN_COLORS = ["#08306B", "#2171B5", "#4292C6", "#6BAED6", "#9ECAE1", "#C6DBEF"]

EXPECTED_SCHEMA_VERSION = 3


def load(path: Path) -> list[dict]:
    events = [json.loads(line) for line in path.open() if line.strip()]
    bad_versions = sorted({
        event.get("schema_version")
        for event in events
        if event.get("schema_version") != EXPECTED_SCHEMA_VERSION
    }, key=repr)
    if bad_versions:
        raise ValueError(
            f"{path}: expected schema_version={EXPECTED_SCHEMA_VERSION}, found {bad_versions}"
        )
    return events


def trace_id(events: list[dict], path: Path) -> tuple[str, str]:
    for event in events:
        if event.get("semantic_type") == "trace_metadata":
            return event["workload"], event["condition"]
    return "unknown", path.stem


def origin_steps(events: list[dict]) -> dict[str, int]:
    """First step at which each logical_id is projected as KV (becomes prefill work).

    Origin is the first generate step whose prompt contains this content, i.e. the
    step where its KV must first be computed. A later step that re-projects the
    same ``logical_id`` is therefore carry-over (a reusable cached prefix), while
    origin == step is genuinely new prefill. An edit yields a new ``logical_id``
    and so re-enters as new work at the step it is first prefilled.
    """
    origin: dict[str, int] = {}
    for event in events:
        if event.get("repr_type") != "kv_estimated" or event.get("op") != "create":
            continue
        if event.get("semantic_type") in ("trace_metadata", "engine_cross_check"):
            continue
        lid = event["logical_id"]
        origin[lid] = min(origin.get(lid, event["step"]), event["step"])
    return origin


def carryover_matrix(events: list[dict]) -> tuple[list[int], dict[int, dict[int, int]]]:
    """Return (sorted generate steps, {step: {origin_step: kv_bytes}})."""
    origin = origin_steps(events)
    per_step: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        if event.get("repr_type") != "kv_estimated" or event.get("op") != "create":
            continue
        if event.get("semantic_type") in ("trace_metadata", "engine_cross_check"):
            continue
        step = event["step"]
        origin_step = origin.get(event["logical_id"], step)
        per_step[step][origin_step] += event["size_bytes"]
    return sorted(per_step), per_step


def summarize(name: str, steps: list[int], matrix: dict[int, dict[int, int]]) -> list[dict]:
    rows = []
    for step in steps:
        total = sum(matrix[step].values())
        carried = sum(v for o, v in matrix[step].items() if o < step)
        new = total - carried
        rows.append({
            "trace": name,
            "step": step,
            "working_set_kv_bytes": total,
            "new_prefill_kv_bytes": new,
            "carried_kv_bytes": carried,
            "carried_fraction": round(carried / total, 4) if total else 0.0,
        })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["trace", "step", "working_set_kv_bytes", "new_prefill_kv_bytes",
              "carried_kv_bytes", "carried_fraction"]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def save_figure(fig, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path.with_suffix(".png"), dpi=180)
    if matplotlib is None:
        return
    previous = matplotlib.rcParams.get("svg.hashsalt")
    matplotlib.rcParams["svg.hashsalt"] = SVG_HASH_SALT
    try:
        fig.savefig(out_path.with_suffix(".svg"), metadata=SVG_METADATA)
    finally:
        matplotlib.rcParams["svg.hashsalt"] = previous


def figure(by_trace: dict[tuple[str, str], tuple[list[int], dict]], out_path: Path) -> None:
    if plt is None:
        print("matplotlib not installed; skipped figure")
        return
    observed_origins: set[int] = set()
    for steps, matrix in by_trace.values():
        for step in steps:
            observed_origins.update(matrix[step])
    if not observed_origins:
        print("no KV origins observed; skipped figure")
        return
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.2), sharex=False)
    for r, row in enumerate(PANELS):
        for c, key in enumerate(row):
            ax = axes[r][c]
            steps, matrix = by_trace[key]
            bottoms = [0.0] * len(steps)
            for origin in sorted(observed_origins):
                heights = [matrix[s].get(origin, 0) / 1e6 for s in steps]
                if not any(heights):
                    continue
                ax.bar(
                    [str(s) for s in steps], heights, bottom=bottoms,
                    color=ORIGIN_COLORS[origin % len(ORIGIN_COLORS)],
                    edgecolor="white", linewidth=0.5, width=0.74,
                )
                bottoms = [b + h for b, h in zip(bottoms, heights)]
            # Annotate the carried fraction at the last step.
            last = steps[-1]
            total = sum(matrix[last].values())
            carried = sum(v for o, v in matrix[last].items() if o < last)
            frac = carried / total if total else 0.0
            ax.text(len(steps) - 1, bottoms[-1], f"{frac*100:.0f}% carried",
                    ha="center", va="bottom", fontsize=8.5, color="#08306B")
            ax.set_title(TITLES[key], fontsize=10.5, loc="left")
            ax.set_ylabel("working-set KV (MB)" if c == 0 else "")
            ax.set_xlabel("generate step")
            ax.spines[["top", "right"]].set_visible(False)
            ax.margins(y=0.16)
    initial_origin = min(observed_origins)
    legend_origins = sorted(observed_origins)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=ORIGIN_COLORS[o % len(ORIGIN_COLORS)])
        for o in legend_origins
    ]
    labels = [
        f"origin step {o}" + (" (initial prompt)" if o == initial_origin else "")
        for o in legend_origins
    ]
    fig.legend(handles, labels, loc="lower center", ncol=len(legend_origins),
               frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(
        "Cross-step memory carry-over: per-step KV working set colored by the step that created it",
        x=0.5, y=0.99, fontsize=12.5,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    save_figure(fig, out_path)
    plt.close(fig)


def main(argv: list[str]) -> int:
    traces_dir = Path(argv[1]) if len(argv) > 1 else Path("traces/final_v3")
    out_csv = Path(argv[2]) if len(argv) > 2 else Path("analysis_out/final_v3/carryover.csv")
    out_fig = Path(argv[3]) if len(argv) > 3 else Path("figures/final_v3/carryover_kv_origin")
    by_trace: dict[tuple[str, str], tuple[list[int], dict]] = {}
    rows: list[dict] = []
    for path in sorted(traces_dir.glob("*.jsonl")):
        events = load(path)
        key = trace_id(events, path)
        steps, matrix = carryover_matrix(events)
        by_trace[key] = (steps, matrix)
        rows.extend(summarize(f"{key[0]}_{key[1]}", steps, matrix))
    write_csv(out_csv, rows)
    print(f"Wrote {out_csv}")
    if all(k in by_trace for row in PANELS for k in row):
        figure(by_trace, out_fig)
        print(f"Wrote {out_fig}.png/.svg")
    else:
        print("Not all six final-v3 traces present; wrote CSV only.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
