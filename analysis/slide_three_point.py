"""Render the condensed 3-point 'What we built / Design / Novel contribution' slide.

Run:
    python3 -m analysis.slide_three_point
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
GOLD_E = "#C58A12"
TAN_E = "#9C6B3F"
INK, MUT = "#1A1A1A", "#5A5A5A"


def box(ax, x, y, w, h, *, fill, edge, lw=1.2, r=0.016):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                 boxstyle=f"round,pad=0.002,rounding_size={r}",
                 facecolor=fill, edgecolor=edge, linewidth=lw))


def t(ax, x, y, s, *, fs=11, w="normal", ha="left", va="center", c=INK,
      fam=None, st="normal"):
    kw = dict(fontsize=fs, fontweight=w, ha=ha, va=va, color=c, style=st)
    if fam:
        kw["family"] = fam
    ax.text(x, y, s, **kw)


def arrow(ax, x1, y1, x2, y2, *, c=INK, lw=1.4, mut=10):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                 mutation_scale=mut, color=c, linewidth=lw))


def band(ax, y0, y1, tab_label, tab_lines, tab_fill):
    """Draw a band background + a colored left tab with a 1-2 line label."""
    box(ax, 0.025, y0, 0.950, y1 - y0, fill="#FBFBFB", edge="#D8D8D8", lw=1.1)
    box(ax, 0.025, y0, 0.150, y1 - y0, fill=tab_fill, edge=tab_fill, lw=1.0)
    cy = (y0 + y1) / 2
    if len(tab_lines) == 1:
        t(ax, 0.100, cy, tab_lines[0], fs=13.5, w="bold", ha="center",
          c="white")
    else:
        t(ax, 0.100, cy + 0.022, tab_lines[0], fs=12.5, w="bold", ha="center",
          c="white")
        t(ax, 0.100, cy - 0.020, tab_lines[1], fs=12.5, w="bold", ha="center",
          c="white")


def render(out_path: Path) -> None:
    if plt is None:
        print("matplotlib not installed; skipped slide")
        return
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Header
    t(ax, 0.025, 0.965,
      "EE 392C · Memory-lifetime characterization of LLM agent-workflow replays",
      fs=11.5, w="bold", c="#333")

    CX = 0.190          # content left edge (right of tab)

    # ===================== Band 1: WHAT WE BUILT =====================
    band(ax, 0.665, 0.930, "what", ["WHAT WE", "BUILT"], BLUE_E)
    t(ax, CX, 0.888,
      "A logical-memory lifetime profiler for LLM agent-workflow replays.",
      fs=14.5, w="bold")
    t(ax, CX, 0.838,
      "Experimental framework + analysis pipeline — instruments deterministic "
      "scripted replays on",
      fs=10.8, c="#2A2A2A")
    t(ax, CX, 0.808,
      "real vLLM · Qwen2.5-Coder-7B · H100, logging create/read/mutate/free × "
      "text·tokens·KV per object.",
      fs=10.8, c="#2A2A2A")
    t(ax, CX, 0.772,
      "6 gated traces (3 workload families × 2 contrasts).  "
      "Not a simulator, compiler pass, or hardware model.",
      fs=10.0, c=MUT, st="italic")

    # ===================== Band 2: DESIGN =====================
    band(ax, 0.350, 0.625, "design", ["DESIGN"], GREEN_E)

    # Pipeline strip
    stages = [
        ("Workloads", BLUE, BLUE_E),
        ("Replay", GREEN, GREEN_E),
        ("Tracer", GREEN, GREEN_E),
        ("Validate", YEL, YEL_E),
        ("Analyze", GREEN, GREEN_E),
        ("Tier map", PURP, PURP_E),
    ]
    n = len(stages)
    px0, px1 = CX, 0.965
    gap = 0.012
    bw = ((px1 - px0) - (n - 1) * gap) / n
    pyc, bh = 0.588, 0.046
    for i, (name, fill, edge) in enumerate(stages):
        x = px0 + i * (bw + gap)
        box(ax, x, pyc - bh / 2, bw, bh, fill=fill, edge=edge, lw=1.2)
        t(ax, x + bw / 2, pyc, name, fs=9.6, w="bold", ha="center", c=edge)
        if i < n - 1:
            arrow(ax, x + bw + 0.0005, pyc, x + bw + gap - 0.0005, pyc,
                  lw=1.3, mut=8)

    # Left sub-column: tiers
    t(ax, CX, 0.530, "Memory tiers (prescriptive placement)", fs=10.2,
      w="bold", c="#333")
    tiers = [
        (BLUE_E, "T1 resident", "system_prompt · plan_state · summary"),
        (GREEN_E, "T2 bandwidth", "active KV · recent context"),
        (TAN_E, "T3 capacity", "raw_context · broad search_result"),
    ]
    yy = 0.500
    for col, tier, classes in tiers:
        t(ax, CX, yy, "●", fs=9, c=col)
        t(ax, CX + 0.016, yy, tier, fs=9.4, w="bold", c=col)
        t(ax, CX + 0.140, yy, classes, fs=9.0, c="#2A2A2A", fam="monospace")
        yy -= 0.030

    # Right sub-column: lifetime + policies
    RX = 0.610
    t(ax, RX, 0.530, "Lifetime model & control policies", fs=10.2, w="bold",
      c="#333")
    right_lines = [
        "lifetime = logical-presence, task-bounded",
        "KV = analytical GQA projection (57,344 B/token)",
        "policies: prefix caching · retrieval selectivity · compaction",
    ]
    yy = 0.500
    for line in right_lines:
        t(ax, RX, yy, "– " + line, fs=9.2, c="#2A2A2A")
        yy -= 0.030

    # ===================== Band 3: NOVEL CONTRIBUTION =====================
    band(ax, 0.045, 0.320, "novel", ["NOVEL", "CONTRIBUTION"], GOLD_E)
    t(ax, CX, 0.278,
      "Cross-step logical-object lifetime — how long data lives ACROSS agent "
      "steps,",
      fs=13.0, w="bold", c="#7A4F00")
    t(ax, CX, 0.248,
      "where GainSight measures activation lifetime WITHIN a single forward pass.",
      fs=13.0, w="bold", c="#7A4F00")
    t(ax, CX, 0.198,
      "87–99% of final-step KV is carried from earlier steps; compaction is the "
      "only mechanism that resets it (→ 46% at step 3).",
      fs=10.6, c="#2A2A2A")
    t(ax, CX, 0.168,
      "Result: a per-semantic-class, cross-step memory characterization that "
      "grounds the prescriptive tier mapping —",
      fs=10.6, c="#2A2A2A")
    t(ax, CX, 0.138,
      "the actionable signal a hardware-counter / within-pass profiler cannot "
      "produce.",
      fs=10.6, c="#2A2A2A")
    t(ax, CX, 0.090,
      "evidence: figures/final_v3/carryover_kv_origin.png  ·  "
      "analysis_out/final_v3/carryover.csv",
      fs=8.6, c=MUT, fam="monospace", st="italic")

    # Save
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
    out = Path(argv[1]) if len(argv) > 1 else Path("figures/final_v3/slide_three_point")
    render(out)
    print(f"Wrote {out}.png/.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
