"""Render the 'What we built' presentation slide (16:9).

Maps the course slide template onto this repo:
  - What did you build? + artifact type      → title + type pill
  - What parts are complete?                  → status checklist
  - System / profiling / experimental flow    → horizontal pipeline strip
  - Memory tiers, placement, lifetime, policy → tier ladder + assumptions
  - What is new                               → highlighted callout

Run:
    python3 -m analysis.slide_what_we_built
"""

from __future__ import annotations

import os
import sys
import tempfile
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
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
except ImportError:  # pragma: no cover
    matplotlib = None
    plt = None
    FancyArrowPatch = None
    FancyBboxPatch = None

SVG_HASH_SALT = "ee392c-final-v3"
SVG_METADATA = {"Date": None}

BLUE,  BLUE_E  = "#D6E4F0", "#3A6E96"
GREEN, GREEN_E = "#DDEBD6", "#476B3F"
YEL,   YEL_E   = "#F8E08A", "#A07B12"
PURP,  PURP_E  = "#E3DCEC", "#5B4882"
TAN,   TAN_E   = "#EFE3D2", "#9C6B3F"
INK = "#1A1A1A"
MUT = "#5A5A5A"
NEW_FILL, NEW_E = "#FFF3D6", "#C58A12"


def box(ax, x, y, w, h, *, fill, edge, lw=1.3, r=0.018):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                 boxstyle=f"round,pad=0.002,rounding_size={r}",
                 facecolor=fill, edgecolor=edge, linewidth=lw))


def t(ax, x, y, s, *, fs=11, w="normal", ha="left", va="center", c=INK,
      fam=None, st="normal"):
    kw = dict(fontsize=fs, fontweight=w, ha=ha, va=va, color=c, style=st)
    if fam:
        kw["family"] = fam
    ax.text(x, y, s, **kw)


def arrow(ax, x1, y1, x2, y2, *, c=INK, lw=1.6, mut=13):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                 mutation_scale=mut, color=c, linewidth=lw))


def render(out_path: Path) -> None:
    if plt is None:
        print("matplotlib not installed; skipped slide")
        return
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # ---------------- Title band ----------------
    t(ax, 0.025, 0.955, "What we built", fs=25, w="bold")
    t(ax, 0.025, 0.915,
      "A logical-memory lifetime profiler for LLM agent-workflow replays",
      fs=13.5, c=MUT)

    # Type pill (answers 'which artifact type')
    box(ax, 0.660, 0.905, 0.315, 0.072, fill="#F2F2F2", edge="#999", lw=1.1)
    t(ax, 0.8175, 0.953, "Experimental framework + analysis pipeline",
      fs=10.5, w="bold", ha="center", c="#333")
    t(ax, 0.8175, 0.927, "instrumentation on real vLLM · Qwen2.5-Coder-7B · H100",
      fs=8.6, ha="center", c=MUT, st="italic")
    t(ax, 0.8175, 0.912, "not a simulator · compiler pass · hardware model",
      fs=8.0, ha="center", c="#999", st="italic")

    # ---------------- Horizontal pipeline strip ----------------
    py, ph = 0.792, 0.080
    stages = [
        ("Workloads", "3 families × 2", BLUE, BLUE_E),
        ("Replay runner", "run_final_v3.py", GREEN, GREEN_E),
        ("Logical tracer", "events / logical_id", GREEN, GREEN_E),
        ("Validate", "synthetic + final-v3", YEL, YEL_E),
        ("Analyze", "lifetime·reuse·KV", GREEN, GREEN_E),
        ("Tier map", "prescriptive", PURP, PURP_E),
    ]
    n = len(stages)
    gap = 0.020
    bw = (0.95 - (n - 1) * gap) / n
    x0 = 0.025
    for i, (title, sub, fill, edge) in enumerate(stages):
        x = x0 + i * (bw + gap)
        box(ax, x, py - ph / 2, bw, ph, fill=fill, edge=edge, lw=1.3)
        t(ax, x + bw / 2, py + 0.018, title, fs=10.8, w="bold", ha="center",
          c=edge)
        t(ax, x + bw / 2, py - 0.010, sub, fs=8.0, ha="center", c="#444",
          fam="monospace")
        if i < n - 1:
            arrow(ax, x + bw + 0.001, py, x + bw + gap - 0.001, py,
                  lw=1.5, mut=11)
    t(ax, 0.025, 0.726,
      "Profiling pipeline — deterministic scripted replays → logical events "
      "→ gated traces → metrics → tier map",
      fs=8.8, c=MUT, st="italic")

    # ---------------- Divider ----------------
    ax.plot([0.025, 0.975], [0.700, 0.700], color="#DDD", lw=1.0)

    # ============ LEFT column: status + what's new ============
    LX = 0.025
    t(ax, LX, 0.668, "Status — what's complete", fs=13, w="bold", c=BLUE_E)
    items = [
        ("✓", "Tracer v3 schema — the logged contract:"),
        ("",  "    create/read/mutate/free × text·tokens·KV per logical_id"),
        ("✓", "6 H100 traces collected · pass synthetic + final-v3 gates"),
        ("✓", "Metrics: lifetime, reuse, byte-seconds, KV pressure,"),
        ("",  "    duplication, and cross-step carry-over"),
        ("✓", "Auxiliary Nsight profile analyzed (NVTX phases · 86% GEMM)"),
        ("✓", "All figures + CSVs regenerate deterministically"),
        ("▢", "Remaining: final report write-up (due Jun 8)"),
    ]
    yy = 0.632
    for mark, line in items:
        if mark:
            c = "#2A6B2A" if mark == "✓" else ("#B0860E" if mark == "▢" else INK)
            t(ax, LX, yy, mark, fs=11, w="bold", c=c)
        t(ax, LX + 0.022, yy, line, fs=9.6, c=INK)
        yy -= 0.0345

    # What's new callout
    box(ax, LX, 0.055, 0.455, 0.235, fill=NEW_FILL, edge=NEW_E, lw=1.6)
    t(ax, LX + 0.018, 0.263, "What's new in our design", fs=12.5, w="bold",
      c="#8A5A00")
    new_bullets = [
        ("Cross-step lifetime",
         "track a logical object across agent steps — not",
         "within one forward pass (the GainSight altitude)"),
        ("Carry-over dominates",
         "87–99% of final-step KV is carried from earlier steps;",
         "compaction is the only reset (→ 46% at step 3)"),
        ("Semantic-class → tiers",
         "per-class lifetime / reuse drives the tier map",
         None),
    ]
    yy = 0.228
    for lead, l1, l2 in new_bullets:
        t(ax, LX + 0.018, yy, "▸ " + lead, fs=9.9, w="bold", c="#7A4F00")
        t(ax, LX + 0.042, yy - 0.018, l1, fs=9.0, c="#2A2A2A")
        if l2:
            t(ax, LX + 0.042, yy - 0.034, l2, fs=9.0, c="#2A2A2A")
            yy -= 0.064
        else:
            yy -= 0.046

    # ============ RIGHT column: memory model ============
    RX = 0.520
    RW = 0.455
    t(ax, RX, 0.668, "Memory model — tiers · lifetime · policies",
      fs=13, w="bold", c=PURP_E)

    tiers = [
        ("Tier 1 — resident, low-latency", BLUE, BLUE_E,
         "system_prompt · plan_state · compacted_summary",
         "small · high-reuse · long-lived → keep hot"),
        ("Tier 2 — bandwidth", GREEN, GREEN_E,
         "active KV · recent context",
         "hot, re-read every step → BW-sensitive"),
        ("Tier 3 — capacity, cheap", TAN, TAN_E,
         "raw_context · broad search_result",
         "bulky · low-reuse → demote to cold tier"),
    ]
    ty = 0.628
    th = 0.082
    for title, fill, edge, classes, why in tiers:
        box(ax, RX, ty - th, RW, th, fill=fill, edge=edge, lw=1.4)
        # accent bar on the left
        box(ax, RX, ty - th, 0.012, th, fill=edge, edge=edge, lw=0.5, r=0.004)
        t(ax, RX + 0.026, ty - 0.016, title, fs=10.3, w="bold", c=edge)
        t(ax, RX + 0.026, ty - 0.038, classes, fs=8.8, c=INK, fam="monospace")
        t(ax, RX + 0.026, ty - 0.058, why, fs=8.4, c=MUT, st="italic")
        ty -= th + 0.018

    # Lifetime + policy assumptions
    ay = 0.300
    t(ax, RX, ay, "Lifetime / retention assumptions", fs=10.2, w="bold",
      c="#333")
    assume = [
        "logical-presence, task-bounded lifetime; reuse = re-read count",
        "KV = analytical GQA projection (57,344 B/token),",
        "    bounded at the next prefill boundary",
        "placement is prescriptive from observation, not measured residency",
    ]
    yy = ay - 0.026
    for line in assume:
        t(ax, RX + 0.010, yy, line, fs=8.8, c=INK, fam="monospace")
        yy -= 0.027

    yy -= 0.012
    t(ax, RX, yy, "Control policies studied", fs=10.2, w="bold", c="#333")
    yy -= 0.026
    for line in [
        "prefix caching (on / off)",
        "retrieval selectivity (targeted / broad)",
        "compaction (summarize + demote → op=free)",
    ]:
        t(ax, RX + 0.010, yy, "• " + line, fs=8.8, c=INK)
        yy -= 0.025

    # ---------------- Save ----------------
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path.with_suffix(".png"), dpi=200, bbox_inches="tight")
    if matplotlib is not None:
        prev = matplotlib.rcParams.get("svg.hashsalt")
        matplotlib.rcParams["svg.hashsalt"] = SVG_HASH_SALT
        try:
            fig.savefig(out_path.with_suffix(".svg"), metadata=SVG_METADATA,
                        bbox_inches="tight")
        finally:
            matplotlib.rcParams["svg.hashsalt"] = prev
    plt.close(fig)


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("figures/final_v3/slide_what_we_built")
    render(out)
    print(f"Wrote {out}.png/.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
