"""
analysis/plots.py — generate paper-ready figures.

Style notes:
- Matches the design of the interactive widgets used in the project lab notebook:
  clean type, no top/right spines, subtle grid, semi-transparent fills.
- All figures saved at 200 DPI PNG; SVG also produced for editability.

Usage:
    python -m analysis.plots traces/batch_v2/

Run from repo root. Requires matplotlib.
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

# ---------- design tokens (match the widget aesthetic) ----------
mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 10.5,
    "axes.titlesize": 12,
    "axes.titleweight": "regular",
    "axes.titlepad": 14,
    "axes.labelsize": 10.5,
    "axes.labelcolor": "#444",
    "axes.edgecolor": "#bbb",
    "axes.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#000",
    "grid.alpha": 0.06,
    "grid.linewidth": 0.5,
    "xtick.color": "#777",
    "ytick.color": "#777",
    "xtick.labelsize": 9.5,
    "ytick.labelsize": 9.5,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "xtick.major.pad": 4,
    "ytick.major.pad": 4,
    "legend.fontsize": 9.5,
    "legend.frameon": False,
    "figure.dpi": 150,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
})

CATS = ["system_prompt", "user_problem", "assistant_output",
        "tool_result", "file_content", "kv_cache"]
COLORS = {
    "system_prompt": "#534AB7",
    "user_problem":  "#993556",
    "assistant_output": "#BA7517",
    "tool_result":   "#993C1D",
    "file_content":  "#0F6E56",
    "kv_cache":      "#5F5E5A",
}
LABEL = {
    "system_prompt": "system prompt",
    "user_problem":  "user problem",
    "assistant_output": "assistant output",
    "tool_result":   "tool result",
    "file_content":  "file content",
    "kv_cache":      "KV cache",
}

LIFE_BUCKETS = [
    ("short", 0.0, 1.0, "#A7D8C8"),
    ("medium", 1.0, 3.0, "#6FB39A"),
    ("long", 3.0, float("inf"), "#2C7A62"),
]

MEMORY_CLASSES = [
    ("short_term", ["kv_cache"], "#C66A32"),
    ("medium_term", ["system_prompt", "user_problem", "assistant_output", "tool_result"], "#2C7A62"),
    ("long_term", ["file_content"], "#3D5A98"),
]


def categorize(oid):
    if oid.startswith("msg_step0_system"): return "system_prompt"
    if oid.startswith("msg_step0_user_problem"): return "user_problem"
    if "_assistant_" in oid: return "assistant_output"
    if "tool_result" in oid: return "tool_result"
    if oid.startswith("file_"): return "file_content"
    if oid.startswith("kv_prompt"): return "kv_cache"
    return "other"


def load(path):
    events = [json.loads(l) for l in Path(path).open()]
    by_oid = defaultdict(list)
    for e in events:
        by_oid[e["object_id"]].append(e)
    task_end = max(e["ts"] for e in events)
    objects = []
    for oid, evs in by_oid.items():
        evs.sort(key=lambda e: e["ts"])
        creates = [e for e in evs if e["op"] == "create"]
        if not creates:
            continue
        c0 = creates[0]
        reads = [e for e in evs if e["op"] == "read"]
        mutates = [e for e in evs if e["op"] == "mutate"]
        last_access = max((e["ts"] for e in reads + mutates), default=task_end)
        objects.append({
            "oid": oid, "category": categorize(oid),
            "size": c0["size_bytes"], "create_ts": c0["ts"],
            "last_access_ts": last_access,
            "lifetime": max(0.0, last_access - c0["ts"]),
            "reads": len(reads), "repr_type": c0["repr_type"],
        })
    return {"events": events, "objects": objects, "task_end": task_end}


def _bytes_formatter(v, _):
    if v >= 1e8: return "100 MB"
    if v >= 1e7: return "10 MB"
    if v >= 1e6: return "1 MB"
    if v >= 1e5: return "100 KB"
    if v >= 1e4: return "10 KB"
    if v >= 1e3: return "1 KB"
    if v >= 100: return "100 B"
    if v >= 10:  return "10 B"
    return ""


def fig1_scatter(traces_dir, out_base):
    """Lifetime × size scatter, all objects across all traces."""
    paths = sorted(glob.glob(f"{traces_dir}/*.jsonl"))
    buckets = defaultdict(lambda: defaultdict(int))
    for p in paths:
        tr = load(p)
        for o in tr["objects"]:
            buckets[o["category"]][(round(o["lifetime"], 1), o["size"])] += 1

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    for cat in CATS:
        if cat not in buckets:
            continue
        xs, ys, sizes = [], [], []
        for (x, y), n in buckets[cat].items():
            xs.append(x); ys.append(y)
            sizes.append(50 + 35 * (n ** 0.55))
        ax.scatter(xs, ys, s=sizes, c=COLORS[cat], alpha=0.45,
                   edgecolors=COLORS[cat], linewidths=0.7,
                   label=LABEL[cat])

    ax.set_yscale("log")
    ax.set_xlim(-0.5, 13)
    ax.set_ylim(10, 1.5e8)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(_bytes_formatter))
    ax.set_xlabel("Lifetime (s)")
    ax.set_ylabel("Size (log scale)")
    ax.set_title("Analyzing KV cache dynamics and memory tier implications",
                 loc="left", color="#666", pad=22)
    leg = ax.legend(loc="upper left", bbox_to_anchor=(0, 1.04),
                    ncol=6, handletextpad=0.4, columnspacing=1.2,
                    borderaxespad=0)
    for h in leg.legend_handles:
        h.set_alpha(0.8)
        h.set_sizes([80])
    fig.savefig(out_base.with_suffix(".png"), facecolor="white")
    fig.savefig(out_base.with_suffix(".svg"), facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_base.with_suffix('.png')}")


def fig2_timeline(traces_dir, out_base):
    """Live memory over time, hello_bug_cache_on_t0_0."""
    target = Path(traces_dir) / "hello_bug_cache_on_t0_0.jsonl"
    if not target.exists():
        target = Path(traces_dir) / "hello_bug_cache_on_t0.0.jsonl"
    tr = load(target)
    T = tr["task_end"]
    dt = 0.02
    n = int(T / dt) + 2
    times = [i * dt for i in range(n)]
    kv = [0.0] * n
    logical = [0.0] * n
    for i, t in enumerate(times):
        for o in tr["objects"]:
            if o["create_ts"] <= t <= o["last_access_ts"]:
                if o["category"] == "kv_cache":
                    kv[i] += o["size"]
                else:
                    logical[i] += o["size"]

    fig, ax1 = plt.subplots(figsize=(8.5, 4.6))
    kv_mb = [v / 1e6 for v in kv]
    ax1.fill_between(times, 0, kv_mb, color=COLORS["kv_cache"],
                     alpha=0.18, step="post", linewidth=0)
    ax1.plot(times, kv_mb, color=COLORS["kv_cache"], linewidth=1.4,
             drawstyle="steps-post", label="KV cache (left axis)")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("KV cache live (MB)", color=COLORS["kv_cache"])
    ax1.tick_params(axis="y", colors=COLORS["kv_cache"])
    ax1.set_ylim(0, max(kv_mb) * 1.15)

    ax2 = ax1.twinx()
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(True)
    ax2.spines["right"].set_color("#bbb")
    ax2.spines["right"].set_linewidth(0.6)
    ax2.plot(times, logical, color=COLORS["system_prompt"], linewidth=1.4,
             linestyle="--", drawstyle="steps-post",
             label="logical content (right axis)")
    ax2.set_ylabel("Logical content live (B)", color=COLORS["system_prompt"])
    ax2.tick_params(axis="y", colors=COLORS["system_prompt"])
    ax2.set_ylim(0, 2400)
    ax2.grid(False)

    ax1.set_title("Memory pressure over one task (hello_bug, cache_on, t=0.0)",
                  loc="left", color="#666", pad=22)

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left",
               bbox_to_anchor=(0, 1.04), ncol=2,
               handletextpad=0.5, columnspacing=1.5, borderaxespad=0)

    fig.savefig(out_base.with_suffix(".png"), facecolor="white")
    fig.savefig(out_base.with_suffix(".svg"), facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_base.with_suffix('.png')}")


def _fmt_pct(p):
    if p < 0.01:
        return "<0.01%"
    if p < 1:
        return f"{p:.2f}%"
    if p < 10:
        return f"{p:.1f}%"
    return f"{p:.0f}%"


def fig3_dichotomy(traces_dir, out_base):
    """Bytes-seconds vs read events by category."""
    paths = sorted(glob.glob(f"{traces_dir}/hello_bug*.jsonl"))
    bs = defaultdict(float)
    rd = defaultdict(int)
    for p in paths:
        tr = load(p)
        for o in tr["objects"]:
            bs[o["category"]] += o["size"] * o["lifetime"]
            rd[o["category"]] += o["reads"]

    cats_ordered = CATS
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.6),
                                  gridspec_kw={"wspace": 0.4})
    y = list(range(len(cats_ordered)))
    colors = [COLORS[c] for c in cats_ordered]
    labels = [LABEL[c] for c in cats_ordered]

    a1.barh(y, [bs[c] for c in cats_ordered], color=colors,
            edgecolor=colors, alpha=0.85, height=0.55)
    a1.set_yticks(y, labels=labels)
    a1.set_xscale("log")
    a1.set_xlim(1e2, 1e11)
    a1.set_xlabel("Byte-seconds (log scale)")
    a1.set_title("Capacity-time", loc="left", color="#444")
    a1.invert_yaxis()
    a1.grid(axis="y", alpha=0)

    total_bs = sum(bs.values())
    for i, c in enumerate(cats_ordered):
        pct = 100 * bs[c] / total_bs if total_bs else 0
        a1.text(bs[c] * 1.6, i, _fmt_pct(pct), va="center",
                fontsize=9, color="#555")

    max_rd = max(rd.values()) if rd else 1
    a2.barh(y, [rd[c] for c in cats_ordered], color=colors,
            edgecolor=colors, alpha=0.85, height=0.55)
    a2.set_yticks(y, labels=labels)
    a2.set_xlim(0, max_rd * 1.25)
    a2.set_xlabel("Read events (count)")
    a2.set_title("Bandwidth demand", loc="left", color="#444")
    a2.invert_yaxis()
    a2.grid(axis="y", alpha=0)

    total_rd = sum(rd.values())
    for i, c in enumerate(cats_ordered):
        pct = 100 * rd[c] / total_rd if total_rd else 0
        a2.text(rd[c] + max_rd * 0.02, i, _fmt_pct(pct),
                va="center", fontsize=9, color="#555")

    fig.suptitle("Same data, two axes: capacity vs bandwidth",
                 x=0.06, y=1.02, ha="left", fontsize=12.5, color="#666")
    fig.savefig(out_base.with_suffix(".png"), facecolor="white")
    fig.savefig(out_base.with_suffix(".svg"), facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_base.with_suffix('.png')}")


def fig4_tier_diagram(out_base):
    """Paper-style tier mapping diagram."""
    fig, ax = plt.subplots(figsize=(9, 5.6))
    # No aspect=equal — let the data coords fill the axes naturally
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 10.5)
    ax.axis("off")

    BOX_LEFT, BOX_RIGHT = 2.0, 10.0
    tiers = [
        {
            "y_bot": 7.4, "y_top": 9.0,
            "fill": "#FAECE7", "edge": "#7C2D14",
            "title": "Tier 1 — Always-resident (SRAM / pinned HBM)",
            "body": "System prompt + user problem",
            "spec": "Size ~600 B  ·  Lifetime = full task  ·  Read every step",
        },
        {
            "y_bot": 5.0, "y_top": 6.6,
            "fill": "#FBF1DC", "edge": "#7C5510",
            "title": "Tier 2 — Bandwidth tier (HBM)",
            "body": "Active KV (current + next step), recent messages",
            "spec": "10–25 MB per step  ·  Lifetime 1–2 steps  ·  61% of reads",
        },
        {
            "y_bot": 2.6, "y_top": 4.2,
            "fill": "#E6F1FB", "edge": "#0C447C",
            "title": "Tier 3 — Capacity tier (DDR / CXL / NVMe)",
            "body": "KV blocks past their next-read window",
            "spec": "Migratable once cache-hit consumed  ·  ~100% byte-seconds  ·  3% of reads",
        },
    ]

    for t in tiers:
        h = t["y_top"] - t["y_bot"]
        rect = patches.FancyBboxPatch(
            (BOX_LEFT, t["y_bot"]), BOX_RIGHT - BOX_LEFT, h,
            boxstyle="round,pad=0,rounding_size=0.04",
            linewidth=0.9, edgecolor=t["edge"], facecolor=t["fill"],
        )
        ax.add_patch(rect)
        ax.text(BOX_LEFT + 0.25, t["y_bot"] + h * 0.75, t["title"],
                fontsize=11, fontweight="semibold", color=t["edge"], va="center")
        ax.text(BOX_LEFT + 0.25, t["y_bot"] + h * 0.45, t["body"],
                fontsize=10, color="#222", va="center")
        ax.text(BOX_LEFT + 0.25, t["y_bot"] + h * 0.15, t["spec"],
                fontsize=9, color="#555", va="center", style="italic")

    # Down-arrows between tiers (centered between the boxes)
    for y_above, y_below in [(7.4, 6.6), (5.0, 4.2)]:
        ax.annotate(
            "", xy=((BOX_LEFT + BOX_RIGHT) / 2, y_below + 0.05),
            xytext=((BOX_LEFT + BOX_RIGHT) / 2, y_above - 0.05),
            arrowprops=dict(arrowstyle="-|>", color="#999",
                            lw=0.9, mutation_scale=14))

    # Left side: arrow points UP toward the fastest tier
    # (bandwidth and $/bit are both highest at Tier 1)
    ax.annotate(
        "", xy=(1.2, 9.0), xytext=(1.2, 2.6),
        arrowprops=dict(arrowstyle="-|>", color="#666",
                        lw=1.0, mutation_scale=14))
    ax.text(0.9, 5.8, "Bandwidth · $/bit",
            rotation=90, fontsize=10, color="#666",
            ha="center", va="center", style="italic")

    # Right side: arrow points DOWN toward the largest tier
    # (capacity is greatest at Tier 3)
    ax.annotate(
        "", xy=(10.8, 2.6), xytext=(10.8, 9.0),
        arrowprops=dict(arrowstyle="-|>", color="#666",
                        lw=1.0, mutation_scale=14))
    ax.text(11.1, 5.8, "Capacity",
            rotation=90, fontsize=10, color="#666",
            ha="center", va="center", style="italic")

    # Title + subtitle
    ax.text(6.0, 10.1, "Proposed tier mapping for coding-agent inference",
            fontsize=13, color="#222", ha="center", va="center",
            fontweight="medium")
    ax.text(6.0, 9.65, "anchored to 20-trace dataset (Qwen2.5-Coder-7B, vLLM 0.6.6, L4 24 GB)",
            fontsize=10, color="#888", ha="center", va="center", style="italic")

    # Caveat
    ax.text(BOX_LEFT, 1.7,
            "Caveat: traces are 4–6 steps; Tier 3 capacity benefit scales with step count.",
            fontsize=9, color="#888", va="center", style="italic")
    ax.text(BOX_LEFT, 1.2,
            "On 20+ step agents (SWE-bench-style), Tier 3 byte-seconds dominate further.",
            fontsize=9, color="#888", va="center", style="italic")

    fig.savefig(out_base.with_suffix(".png"), facecolor="white", dpi=200)
    fig.savefig(out_base.with_suffix(".svg"), facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_base.with_suffix('.png')}")


def fig5_reuse_lifetime(traces_dir, out_base):
    """Per-object reuse count vs lifetime across all traces."""
    paths = sorted(glob.glob(f"{traces_dir}/*.jsonl"))
    buckets = defaultdict(lambda: defaultdict(int))
    for p in paths:
        tr = load(p)
        for o in tr["objects"]:
            cat = o["category"]
            if cat not in CATS:
                continue
            key = (round(o["lifetime"], 1), int(o["reads"]), int(o["size"]))
            buckets[cat][key] += 1

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    for cat in CATS:
        if cat not in buckets:
            continue
        xs, ys, sizes = [], [], []
        for (x, y, size_bytes), n in buckets[cat].items():
            xs.append(x)
            ys.append(y)
            # Bubble area encodes object size and count.
            sizes.append(35 + 14 * (n ** 0.55) + 20 * ((max(size_bytes, 1) / 1024) ** 0.35))
        ax.scatter(
            xs,
            ys,
            s=sizes,
            c=COLORS[cat],
            alpha=0.45,
            edgecolors=COLORS[cat],
            linewidths=0.7,
            label=LABEL[cat],
        )

    ax.set_xlim(-0.5, 13)
    ax.set_ylim(-0.3, 13)
    ax.set_xlabel("Lifetime (s)")
    ax.set_ylabel("Reuse count (read events)")
    ax.set_title("Reuse patterns vs data lifetimes across traces",
                 loc="left", color="#666", pad=22)
    leg = ax.legend(
        loc="upper left",
        bbox_to_anchor=(0, 1.04),
        ncol=6,
        handletextpad=0.4,
        columnspacing=1.2,
        borderaxespad=0,
    )
    for h in leg.legend_handles:
        h.set_alpha(0.8)
        h.set_sizes([70])
    fig.savefig(out_base.with_suffix(".png"), facecolor="white")
    fig.savefig(out_base.with_suffix(".svg"), facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_base.with_suffix('.png')}")


def fig6_reuse_hist_lifetime_stack(traces_dir, out_base):
    """Reuse histogram stacked by lifetime bucket."""
    paths = sorted(glob.glob(f"{traces_dir}/*.jsonl"))
    objects = []
    for p in paths:
        tr = load(p)
        objects.extend([o for o in tr["objects"] if o["category"] in CATS])
    if not objects:
        return

    max_reads = max(int(o["reads"]) for o in objects)
    xs = list(range(max_reads + 1))
    counts_by_bucket = {name: [0 for _ in xs] for name, _, _, _ in LIFE_BUCKETS}

    for o in objects:
        reads = int(o["reads"])
        lifetime = float(o["lifetime"])
        for name, lo, hi, _ in LIFE_BUCKETS:
            if lo <= lifetime < hi:
                counts_by_bucket[name][reads] += 1
                break

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    bottom = [0 for _ in xs]
    for name, _, _, color in LIFE_BUCKETS:
        vals = counts_by_bucket[name]
        ax.bar(
            xs,
            vals,
            bottom=bottom,
            width=0.85,
            color=color,
            edgecolor=color,
            alpha=0.9,
            label=f"{name} lifetime",
        )
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xticks(xs)
    ax.set_xlabel("Read count per object")
    ax.set_ylabel("Number of objects")
    ax.set_title("Reuse distribution with time-based lifetime composition",
                 loc="left", color="#666", pad=22)
    ax.legend(loc="upper right")
    fig.savefig(out_base.with_suffix(".png"), facecolor="white")
    fig.savefig(out_base.with_suffix(".svg"), facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_base.with_suffix('.png')}")


def fig7_reuse_hist_memory_class_stack(traces_dir, out_base):
    """Reuse histogram stacked by conceptual memory class."""
    paths = sorted(glob.glob(f"{traces_dir}/*.jsonl"))
    objects = []
    for p in paths:
        tr = load(p)
        objects.extend([o for o in tr["objects"] if o["category"] in CATS])
    if not objects:
        return

    cat_to_class = {}
    for class_name, cats, _ in MEMORY_CLASSES:
        for c in cats:
            cat_to_class[c] = class_name

    max_reads = max(int(o["reads"]) for o in objects)
    xs = list(range(max_reads + 1))
    counts_by_class = {name: [0 for _ in xs] for name, _, _ in MEMORY_CLASSES}

    for o in objects:
        reads = int(o["reads"])
        class_name = cat_to_class.get(o["category"])
        if class_name is None:
            continue
        counts_by_class[class_name][reads] += 1

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    bottom = [0 for _ in xs]
    for class_name, _, color in MEMORY_CLASSES:
        vals = counts_by_class[class_name]
        label = class_name.replace("_", " ")
        ax.bar(
            xs,
            vals,
            bottom=bottom,
            width=0.85,
            color=color,
            edgecolor=color,
            alpha=0.9,
            label=label,
        )
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xticks(xs)
    ax.set_xlabel("Read count per object")
    ax.set_ylabel("Number of objects")
    ax.set_title("Reuse distribution with conceptual memory-class composition",
                 loc="left", color="#666", pad=22)
    ax.legend(loc="upper right")
    fig.savefig(out_base.with_suffix(".png"), facecolor="white")
    fig.savefig(out_base.with_suffix(".svg"), facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_base.with_suffix('.png')}")


def main():
    traces_dir = sys.argv[1] if len(sys.argv) > 1 else "traces/batch_v2"
    out_dir = Path("figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Reading traces from {traces_dir}")
    fig1_scatter(traces_dir, out_dir / "fig1_lifetime_size_scatter")
    fig2_timeline(traces_dir, out_dir / "fig2_memory_pressure_timeline")
    fig3_dichotomy(traces_dir, out_dir / "fig3_capacity_vs_bandwidth")
    fig4_tier_diagram(out_dir / "fig4_dms_tier_proposal")
    fig5_reuse_lifetime(traces_dir, out_dir / "fig5_reuse_vs_lifetime")
    fig6_reuse_hist_lifetime_stack(traces_dir, out_dir / "fig6_reuse_hist_lifetime_stack")
    fig7_reuse_hist_memory_class_stack(traces_dir, out_dir / "fig7_reuse_hist_memory_class_stack")


if __name__ == "__main__":
    main()
