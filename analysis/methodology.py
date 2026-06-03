"""Render the methodology flowchart used as Figure 1 in the report/slides.

Academic-conference style modeled on a DataSimulator-style stage diagram:
labeled stage rows on the left margin, small named boxes for each step with all
detail living in callout text beside them (in --detailed mode), yellow decision
diamonds for validation gates, and reference panels on the right for schema +
defaults.

Two output modes:
  --style clean     stages + boxes + arrows only (default; figures/methodology.png)
  --style detailed  + callouts + 4 right-side reference panels
                     (writes figures/methodology_detailed.png by default)

Run:
    python3 -m analysis.methodology                 # clean
    python3 -m analysis.methodology --style detailed
"""

from __future__ import annotations

import argparse
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
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon
except ImportError:  # pragma: no cover - optional local dependency
    matplotlib = None
    plt = None
    FancyArrowPatch = None
    FancyBboxPatch = None
    Polygon = None

SVG_HASH_SALT = "ee392c-final-v3"
SVG_METADATA = {"Date": None}

FILLS = {
    "input":       "#D6E4F0", "input_edge":   "#3A6E96",
    "process":     "#DDEBD6", "process_edge": "#476B3F",
    "gate":        "#F8E08A", "gate_edge":    "#A07B12",
    "output":      "#E3DCEC", "output_edge":  "#5B4882",
    "ref":         "#F7F7F7", "ref_edge":     "#6B6B6B",
    "stage_band":  "#F0F0F0",
    "arrow":       "#222222",
    "callout":     "#222222",
}


def rounded(ax, x, y, w, h, *, fill, edge, lw=1.1, rounding=0.012):
    box = FancyBboxPatch((x, y), w, h,
                         boxstyle=f"round,pad=0.001,rounding_size={rounding}",
                         linewidth=lw, facecolor=fill, edgecolor=edge)
    ax.add_patch(box)


def diamond(ax, cx, cy, w, h, *, fill, edge, lw=1.1):
    pts = [(cx, cy + h / 2), (cx + w / 2, cy),
           (cx, cy - h / 2), (cx - w / 2, cy)]
    ax.add_patch(Polygon(pts, closed=True, linewidth=lw,
                         facecolor=fill, edgecolor=edge))


def label(ax, x, y, text, *, fontsize=9.5, weight="normal", ha="left",
          va="center", color="#111", family=None, style="normal"):
    kw = dict(fontsize=fontsize, fontweight=weight, ha=ha, va=va,
              color=color, style=style)
    if family:
        kw["family"] = family
    ax.text(x, y, text, **kw)


def stage_band(ax, y_top, y_bot, x_left=0.005, x_right=0.995):
    ax.axhspan(y_bot, y_top, xmin=x_left, xmax=x_right,
               facecolor=FILLS["stage_band"], alpha=0.45, zorder=0)


def arrow(ax, x1, y1, x2, y2, *, color=None, ls="-", curve=0.0, lw=1.4,
          mut=12):
    arr = FancyArrowPatch((x1, y1), (x2, y2),
                          arrowstyle="-|>", mutation_scale=mut,
                          connectionstyle=f"arc3,rad={curve}",
                          color=color or FILLS["arrow"],
                          linewidth=lw, linestyle=ls)
    ax.add_patch(arr)


def connector(ax, x1, y1, x2, y2, *, color="#7A7A7A", lw=0.8):
    ax.plot([x1, x2], [y1, y2], color=color, linewidth=lw, zorder=1)


# ---------------------------------------------------------------------------
# Clean (flowchart-only) renderer
# ---------------------------------------------------------------------------

def render_clean(out_path: Path) -> None:
    if plt is None:
        print("matplotlib not installed; skipped figure")
        return
    fig, ax = plt.subplots(figsize=(8.5, 13.0))
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.0)
    ax.axis("off")

    # Title
    label(ax, 0.55, 0.975,
          "EE 392C · Logical-layer instrumentation",
          fontsize=15, weight="bold", ha="center")
    label(ax, 0.55, 0.953,
          "of LLM agent-workflow replays",
          fontsize=15, weight="bold", ha="center")
    label(ax, 0.55, 0.929,
          "Pipeline from scripted replay through validation, "
          "analysis, to prescriptive tier mapping",
          fontsize=9.0, ha="center", color="#555", style="italic")

    # Layout
    STAGE_X = 0.025
    BOX_X = 0.235
    BOX_W = 0.700

    # Slightly more vertical breathing room.
    stage_centers = {
        1: 0.862,
        2: 0.755,
        3: 0.638,
        4: 0.500,
        5: 0.357,
        6: 0.225,
        7: 0.097,
    }

    band_edges = [0.900, 0.808, 0.690, 0.568, 0.430, 0.290, 0.160, 0.030]
    for i in range(len(band_edges) - 1):
        if i % 2 == 0:
            stage_band(ax, band_edges[i], band_edges[i + 1])

    # Colors (override Stage 6 to blue, per reference).
    BLUE_FILL, BLUE_EDGE = FILLS["input"], FILLS["input_edge"]
    GREEN_PASS, RED_FAIL = "#2A6B2A", "#9C2A2A"

    def stage_label(cy, num, *lines):
        label(ax, STAGE_X, cy + 0.022, f"STAGE {num} —",
              fontsize=11.0, weight="bold", color="#1A1A1A")
        for i, line in enumerate(lines):
            label(ax, STAGE_X, cy + 0.005 - i * 0.017, line,
                  fontsize=9.5, color="#3A3A3A")

    # ---------- STAGE 1: Workload Fixtures ----------
    cy1 = stage_centers[1]
    stage_label(cy1, 1, "Workload", "Fixtures")

    sub_w = (BOX_W - 0.040) / 3
    s1_box_xs = []  # remember box centres for funnel arrows
    for i, title in enumerate(["coding", "search", "compaction"]):
        x = BOX_X + i * (sub_w + 0.020)
        s1_box_xs.append(x + sub_w / 2)
        rounded(ax, x, cy1 - 0.032, sub_w, 0.064,
                fill=BLUE_FILL, edge=BLUE_EDGE, lw=1.3)
        label(ax, x + sub_w / 2, cy1 + 0.010, title,
              fontsize=10.5, weight="bold", ha="center", color=BLUE_EDGE)
        label(ax, x + sub_w / 2, cy1 - 0.014, "2 traces",
              fontsize=8.6, ha="center", color="#555")

    # ---------- STAGE 2: Scripted Replay ----------
    cy2 = stage_centers[2]
    stage_label(cy2, 2, "Scripted", "Replay")

    rounded(ax, BOX_X, cy2 - 0.040, BOX_W, 0.080,
            fill=FILLS["process"], edge=FILLS["process_edge"], lw=1.5)
    label(ax, BOX_X + BOX_W / 2, cy2 + 0.020,
          "agent/run_final_v3.py",
          fontsize=12.5, weight="bold", ha="center",
          color=FILLS["process_edge"], family="monospace")
    label(ax, BOX_X + BOX_W / 2, cy2 - 0.001,
          "SemanticWorkflowReplay",
          fontsize=9.8, ha="center", color="#333")
    label(ax, BOX_X + BOX_W / 2, cy2 - 0.023,
          "× 6 traces, deterministic",
          fontsize=9.0, ha="center", color="#666", style="italic")

    # Funnel: 3 arrows from Stage 1 boxes -> Stage 2 box top
    s2_top = cy2 + 0.040
    for x_from in s1_box_xs:
        arrow(ax, x_from, cy1 - 0.032,
              BOX_X + BOX_W / 2, s2_top + 0.001,
              lw=1.6, mut=13)

    # ---------- STAGE 3: Instrument (3 streams) ----------
    cy3 = stage_centers[3]
    stage_label(cy3, 3, "Instrument", "(3 streams)")

    inst_w = (BOX_W - 0.040) / 3
    s3_xs = []
    for i, (title, sub, role) in enumerate([
        ("tracer.py",    "schema v3", "primary"),
        ("telemetry.py", "NVML 1Hz",  "auxiliary"),
        ("Nsight",       "aux. cut",  "auxiliary"),
    ]):
        x = BOX_X + i * (inst_w + 0.020)
        s3_xs.append(x + inst_w / 2)
        rounded(ax, x, cy3 - 0.040, inst_w, 0.080,
                fill=FILLS["process"], edge=FILLS["process_edge"], lw=1.3)
        label(ax, x + inst_w / 2, cy3 + 0.020, title,
              fontsize=10.0, weight="bold", ha="center",
              color=FILLS["process_edge"], family="monospace")
        label(ax, x + inst_w / 2, cy3 + 0.000, sub,
              fontsize=8.8, ha="center", color="#333")
        label(ax, x + inst_w / 2, cy3 - 0.022, role,
              fontsize=8.0, ha="center", color="#777", style="italic")

    # Stage 2 -> 3: fan-out — 3 arrows from Stage 2 box bottom to each Stage 3 box
    s2_bot = cy2 - 0.040
    for x_to in s3_xs:
        arrow(ax, BOX_X + BOX_W / 2, s2_bot - 0.001,
              x_to, cy3 + 0.040 + 0.001, lw=1.6, mut=13)

    # ---------- STAGE 4: Validation Gates ----------
    cy4 = stage_centers[4]
    stage_label(cy4, 4, "Validation", "Gates")

    dia_w, dia_h = 0.240, 0.090
    dx1 = BOX_X + 0.165
    dx2 = BOX_X + 0.525
    diamond(ax, dx1, cy4, dia_w, dia_h,
            fill=FILLS["gate"], edge=FILLS["gate_edge"], lw=1.5)
    label(ax, dx1, cy4 + 0.011,
          "synthetic", fontsize=11.0, weight="bold", ha="center",
          color=FILLS["gate_edge"])
    label(ax, dx1, cy4 - 0.012,
          "gate", fontsize=9.2, ha="center", color="#444")

    diamond(ax, dx2, cy4, dia_w, dia_h,
            fill=FILLS["gate"], edge=FILLS["gate_edge"], lw=1.5)
    label(ax, dx2, cy4 + 0.011,
          "final-v3", fontsize=11.0, weight="bold", ha="center",
          color=FILLS["gate_edge"])
    label(ax, dx2, cy4 - 0.012,
          "validator", fontsize=9.2, ha="center", color="#444")

    # Stage 3 -> 4: clean, non-crossing mapping.
    #   tracer    -> synthetic gate (the synthetic oracle checks the tracer)
    #   telemetry -> validator (left vertex)
    #   nsight    -> validator (right vertex)
    s3_bot = cy3 - 0.040
    targets = [
        (s3_xs[0], dx1, cy4 + dia_h / 2 + 0.001),            # tracer -> synthetic
        (s3_xs[1], dx2 - dia_w * 0.16, cy4 + dia_h * 0.32),  # telemetry -> validator
        (s3_xs[2], dx2 + dia_w * 0.16, cy4 + dia_h * 0.32),  # nsight -> validator
    ]
    for x_from, x_to, y_to in targets:
        arrow(ax, x_from, s3_bot - 0.001, x_to, y_to,
              lw=1.4, mut=12, color="#444")

    # PASS arrow between diamonds (horizontal)
    arrow(ax, dx1 + dia_w / 2, cy4, dx2 - dia_w / 2, cy4,
          lw=2.0, mut=14, color=GREEN_PASS)
    label(ax, (dx1 + dx2) / 2, cy4 + 0.013, "PASS",
          fontsize=9.6, weight="bold", ha="center", color=GREEN_PASS)

    # FAIL: red arrows pointing OUTWARD (down-left from dx1, down-right from
    # dx2) so they exit the centre region and don't collide with the green
    # PASS arrows that fan down to Stage 5.
    fail_y_start = cy4 - dia_h / 2 + 0.005
    # dx1 (synthetic) FAIL → down-left
    fx1_end_x = dx1 - 0.085
    fx1_end_y = cy4 - dia_h / 2 - 0.028
    arrow(ax, dx1 - dia_w * 0.18, fail_y_start, fx1_end_x, fx1_end_y,
          lw=1.8, mut=13, color=RED_FAIL)
    label(ax, fx1_end_x, fx1_end_y - 0.013,
          "FAIL → fix tracer",
          fontsize=8.6, ha="center", weight="bold", color=RED_FAIL)
    # dx2 (validator) FAIL → down-right
    fx2_end_x = dx2 + 0.085
    fx2_end_y = cy4 - dia_h / 2 - 0.028
    arrow(ax, dx2 + dia_w * 0.18, fail_y_start, fx2_end_x, fx2_end_y,
          lw=1.8, mut=13, color=RED_FAIL)
    label(ax, fx2_end_x, fx2_end_y - 0.013,
          "FAIL → reject trace",
          fontsize=8.6, ha="center", weight="bold", color=RED_FAIL)

    # ---------- STAGE 5: Analysis Modules ----------
    cy5 = stage_centers[5]
    stage_label(cy5, 5, "Analysis", "Modules")

    an_w = (BOX_W - 0.040) / 3
    s5_xs = []
    for i, (title, sub, role) in enumerate([
        ("final_v3.py",  "primary",    "metric pipeline"),
        ("carryover.py", "cross-step", "decomposer"),
        ("nsight.py",    "auxiliary",  "visualisations"),
    ]):
        x = BOX_X + i * (an_w + 0.020)
        s5_xs.append(x + an_w / 2)
        rounded(ax, x, cy5 - 0.040, an_w, 0.080,
                fill=FILLS["process"], edge=FILLS["process_edge"], lw=1.3)
        label(ax, x + an_w / 2, cy5 + 0.020, title,
              fontsize=10.0, weight="bold", ha="center",
              color=FILLS["process_edge"], family="monospace")
        label(ax, x + an_w / 2, cy5 + 0.000, sub,
              fontsize=8.8, ha="center", color="#333")
        label(ax, x + an_w / 2, cy5 - 0.022, role,
              fontsize=8.0, ha="center", color="#777", style="italic")

    # PASS path from validator down — 3 green arrows fanning to Stage 5 boxes
    s4_bot = cy4 - dia_h / 2
    for x_to in s5_xs:
        arrow(ax, dx2, s4_bot - 0.001, x_to, cy5 + 0.040 + 0.001,
              lw=1.8, mut=13, color=GREEN_PASS)

    # ---------- STAGE 6: Artifacts (blue, per reference) ----------
    cy6 = stage_centers[6]
    stage_label(cy6, 6, "Artifacts")

    rounded(ax, BOX_X, cy6 - 0.040, BOX_W, 0.080,
            fill=BLUE_FILL, edge=BLUE_EDGE, lw=1.5)
    label(ax, BOX_X + BOX_W / 2, cy6 + 0.020,
          "CSVs + figures",
          fontsize=12.5, weight="bold", ha="center", color=BLUE_EDGE)
    label(ax, BOX_X + BOX_W / 2, cy6 - 0.001,
          "analysis_out/ + figures/", fontsize=9.4, ha="center",
          color="#333", family="monospace")
    label(ax, BOX_X + BOX_W / 2, cy6 - 0.023,
          "checked in, deterministic regen",
          fontsize=8.6, ha="center", color="#666", style="italic")

    # Stage 5 -> 6: 3 funnel arrows into the artifacts box
    s5_bot = cy5 - 0.040
    for x_from in s5_xs:
        arrow(ax, x_from, s5_bot - 0.001,
              BOX_X + BOX_W / 2, cy6 + 0.040 + 0.001,
              lw=1.6, mut=13)

    # ---------- STAGE 7: Tier Mapping ----------
    cy7 = stage_centers[7]
    stage_label(cy7, 7, "Tier", "Mapping")

    rounded(ax, BOX_X, cy7 - 0.040, BOX_W, 0.080,
            fill=FILLS["output"], edge=FILLS["output_edge"], lw=1.7)
    label(ax, BOX_X + BOX_W / 2, cy7 + 0.020,
          "Prescriptive tier proposal",
          fontsize=12.5, weight="bold", ha="center",
          color=FILLS["output_edge"])
    label(ax, BOX_X + BOX_W / 2, cy7 - 0.001,
          "fig4_dms_tier_proposal", fontsize=9.4, ha="center",
          color="#333", family="monospace")
    label(ax, BOX_X + BOX_W / 2, cy7 - 0.023,
          "from observation, not placement",
          fontsize=8.6, ha="center", color="#666", style="italic")

    # Stage 6 -> 7: single vertical arrow
    arrow(ax, BOX_X + BOX_W / 2, cy6 - 0.040,
          BOX_X + BOX_W / 2, cy7 + 0.040 + 0.001,
          lw=1.8, mut=14)

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    if matplotlib is not None:
        previous = matplotlib.rcParams.get("svg.hashsalt")
        matplotlib.rcParams["svg.hashsalt"] = SVG_HASH_SALT
        try:
            fig.savefig(out_path.with_suffix(".svg"),
                        metadata=SVG_METADATA, bbox_inches="tight")
        finally:
            matplotlib.rcParams["svg.hashsalt"] = previous
    plt.close(fig)


# ---------------------------------------------------------------------------
# Detailed renderer (kept for reference; callouts + right-side panels)
# ---------------------------------------------------------------------------

def render_detailed(out_path: Path) -> None:
    if plt is None:
        print("matplotlib not installed; skipped figure")
        return
    fig, ax = plt.subplots(figsize=(15.5, 11.0))
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.0)
    ax.axis("off")

    label(ax, 0.50, 0.972,
          "EE 392C · Logical-layer instrumentation of LLM agent-workflow replays",
          fontsize=15, weight="bold", ha="center")
    label(ax, 0.50, 0.947,
          "Pipeline from scripted replay through validation, analysis, "
          "to prescriptive tier mapping",
          fontsize=10, ha="center", color="#555", style="italic")

    STAGE_X = 0.015
    BOX_X = 0.115
    BOX_W = 0.190
    CALLOUT_X = 0.330
    REF_X = 0.735
    REF_W = 0.250

    stage_centers = {1: 0.880, 2: 0.770, 3: 0.650, 4: 0.500,
                     5: 0.355, 6: 0.215, 7: 0.090}

    band_edges = [0.918, 0.815, 0.700, 0.580, 0.430, 0.290, 0.160, 0.020]
    for i in range(len(band_edges) - 1):
        if i % 2 == 0:
            stage_band(ax, band_edges[i], band_edges[i + 1])

    # STAGE 1
    cy = stage_centers[1]
    label(ax, STAGE_X, cy + 0.022, "STAGE 1", fontsize=9.5, weight="bold",
          color="#444")
    label(ax, STAGE_X, cy + 0.005, "Workload", fontsize=8.5, color="#555")
    label(ax, STAGE_X, cy - 0.011, "Fixtures", fontsize=8.5, color="#555")
    sub_w = (BOX_W - 0.014) / 3
    for i, title in enumerate(["coding", "search", "compaction"]):
        x = BOX_X + i * (sub_w + 0.007)
        rounded(ax, x, cy - 0.026, sub_w, 0.052,
                fill=FILLS["input"], edge=FILLS["input_edge"])
        label(ax, x + sub_w / 2, cy + 0.008, title, fontsize=9.0,
              weight="bold", ha="center", color=FILLS["input_edge"])
        label(ax, x + sub_w / 2, cy - 0.015, "2 traces", fontsize=7.5,
              ha="center", color="#555")
    callout_lines = [
        "tasks/hello_bug         · PROBLEM.md, src/math_utils.py, tests/   (5-step debug loop)",
        "tasks/search_agent      · PROBLEM.md, corpus/*.txt              (4-step grep · max_matches 4 vs 14)",
        "tasks/compaction_agent  · PROBLEM.md, logs/log{1,2,3}.txt        (5-step ingest · summarize+free at s3)",
    ]
    for i, line in enumerate(callout_lines):
        label(ax, CALLOUT_X, cy + 0.020 - i * 0.018, line, fontsize=8.4,
              family="monospace", color=FILLS["callout"])
    connector(ax, BOX_X + BOX_W, cy, CALLOUT_X - 0.005, cy)

    # The detailed render kept the same layout from the previous version;
    # to keep this file readable, only the clean renderer is the active
    # report figure. Use git history to retrieve the full detailed version
    # if needed.
    label(ax, CALLOUT_X, 0.04,
          "(detailed callouts + right-side reference panels — see git history)",
          fontsize=8, color="#888", style="italic")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path.with_suffix(".png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", type=Path, default=None)
    ap.add_argument("--style", choices=["clean", "detailed"], default="clean")
    args = ap.parse_args(argv[1:])

    if args.out is None:
        args.out = Path("figures/final_v3/methodology")
        if args.style == "detailed":
            args.out = Path("figures/final_v3/methodology_detailed")

    if args.style == "clean":
        render_clean(args.out)
    else:
        render_detailed(args.out)
    print(f"Wrote {args.out}.png/.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
