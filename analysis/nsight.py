"""Analyze the auxiliary Nsight Systems profile for the compaction_on replay.

DECISIONS.md §4 frames Nsight as a single droppable timeline cut — one
representative profile of an existing final-v3 trace, not a seventh workload.
This script reads the SQLite export of ``analysis_out/final_v3/nsight_compaction_on.sqlite``
and produces a three-panel figure plus a CSV summary:

  1. Phase timeline of the five generate steps showing per-step wall time, with
     ``prompt_build`` (CPU-side prompt assembly) and ``vllm_generate`` (vLLM
     forward call) ranges from the NVTX markers emitted by
     ``serving/telemetry.nvtx_phase`` in ``agent/run_final_v3.py``.
  2. GPU kernel time broken down by class (GEMM/matmul, elementwise/activation,
     normalization/reduction, other). GEMM dominates as expected for an
     attention-and-MLP workload.
  3. Host->device memcpy volume captured during the same window (proxy for
     bulk model-weight + KV traffic that is *not* logical-layer instrumented).

Honest caveat baked into the figure: the captured GPU-kernel window is
truncated by the CUPTI buffer at ~step 1; the NVTX phase ranges and memcpy
counters survive across all five steps and remain valid. The point of the
figure is to validate that our NVTX phase markers correspond to real GPU
activity and to anchor the cross-vendor kernel class composition, not to draw
per-step kernel comparisons.

Run:
    python3 -m analysis.nsight
"""

from __future__ import annotations

import csv
import os
import sqlite3
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
except ImportError:  # pragma: no cover - optional local dependency
    matplotlib = None
    plt = None

SVG_HASH_SALT = "ee392c-final-v3"
SVG_METADATA = {"Date": None}

PHASE_COLORS = {"prompt_build": "#9C755F", "vllm_generate": "#4E79A7"}
CLASS_COLORS = {
    "GEMM / matmul": "#4E79A7",
    "elementwise / SwiGLU": "#59A14F",
    "norm / RMSNorm": "#EDC948",
    "other": "#BAB0AC",
}


def phase_ranges(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT text, start, end FROM NVTX_EVENTS WHERE text IS NOT NULL ORDER BY start"
    ).fetchall()
    out = []
    step_per_phase: dict[str, int] = {}
    for phase, start, end in rows:
        step_per_phase[phase] = step_per_phase.get(phase, 0) + 1
        out.append({"phase": phase, "step": step_per_phase[phase],
                    "start_ns": start, "end_ns": end,
                    "duration_ms": (end - start) / 1e6})
    return out


def kernel_breakdown(conn: sqlite3.Connection) -> dict[str, tuple[int, float]]:
    rows = conn.execute(
        """SELECT s.value, COUNT(*), SUM(k.end - k.start)
           FROM CUPTI_ACTIVITY_KIND_KERNEL k
           JOIN StringIds s ON k.shortName = s.id
           GROUP BY s.value"""
    ).fetchall()
    classes: dict[str, list[int]] = {k: [0, 0] for k in CLASS_COLORS}
    for name, count, total_ns in rows:
        if "nvjet" in name or "gemm" in name.lower() or "cutlass" in name.lower():
            klass = "GEMM / matmul"
        elif "silu" in name.lower() or name.startswith("triton_poi") or "elementwise" in name.lower():
            klass = "elementwise / SwiGLU"
        elif name.startswith("triton_red") or "rsqrt" in name.lower() or "norm" in name.lower():
            klass = "norm / RMSNorm"
        else:
            klass = "other"
        classes[klass][0] += count
        classes[klass][1] += total_ns
    return {k: (n, ns / 1e6) for k, (n, ns) in classes.items()}


def memcpy_summary(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT COUNT(*), SUM(bytes), SUM(end - start) FROM CUPTI_ACTIVITY_KIND_MEMCPY"
    ).fetchone()
    return {
        "n_memcpys": rows[0] or 0,
        "total_bytes": rows[1] or 0,
        "total_ms": (rows[2] or 0) / 1e6,
    }


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


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def figure(phases: list[dict], classes: dict, memcpy: dict, out_path: Path) -> None:
    if plt is None:
        print("matplotlib not installed; skipped figure")
        return
    fig = plt.figure(figsize=(13.5, 6.0))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.5, 1.0], height_ratios=[1.0, 1.0],
                          hspace=0.45, wspace=0.28)
    ax_tl = fig.add_subplot(gs[0, :])
    ax_kc = fig.add_subplot(gs[1, 0])
    ax_mc = fig.add_subplot(gs[1, 1])

    # --- Panel A: NVTX phase timeline ---
    t0 = min(p["start_ns"] for p in phases)
    for p in phases:
        ax_tl.barh(p["phase"], (p["end_ns"] - p["start_ns"]) / 1e9,
                   left=(p["start_ns"] - t0) / 1e9,
                   color=PHASE_COLORS.get(p["phase"], "#999"), edgecolor="white",
                   height=0.55)
        ax_tl.text((p["start_ns"] - t0) / 1e9 + (p["end_ns"] - p["start_ns"]) / 2e9,
                   p["phase"], f"s{p['step']}\n{p['duration_ms']:.0f} ms",
                   ha="center", va="center", fontsize=8.5, color="white")
    ax_tl.set_xlabel("wall-clock time within profile (s)")
    ax_tl.set_title("NVTX phase markers: 5 generate steps captured end-to-end",
                    loc="left", fontsize=11)
    ax_tl.invert_yaxis()
    ax_tl.spines[["top", "right"]].set_visible(False)
    ax_tl.grid(axis="x", alpha=0.25)

    # --- Panel B: GPU kernel time by class ---
    items = [(k, v[1]) for k, v in classes.items() if v[1] > 0]
    items.sort(key=lambda kv: -kv[1])
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    total = sum(values)
    bars = ax_kc.bar(labels, values, color=[CLASS_COLORS[k] for k in labels],
                     edgecolor="white", width=0.65)
    for bar, value in zip(bars, values):
        pct = 100 * value / total if total else 0
        ax_kc.text(bar.get_x() + bar.get_width() / 2,
                   bar.get_height(), f"{value:.0f} ms\n({pct:.0f}%)",
                   ha="center", va="bottom", fontsize=8.5)
    ax_kc.set_ylabel("GPU kernel time (ms)")
    ax_kc.set_title(f"Kernel class composition · {total:.0f} ms total",
                    loc="left", fontsize=10.5)
    ax_kc.spines[["top", "right"]].set_visible(False)
    ax_kc.tick_params(axis="x", labelsize=8.5, rotation=12)
    ax_kc.margins(y=0.20)

    # --- Panel C: CUDA memcpy volume + caveat ---
    ax_mc.axis("off")
    lines = [
        "All CUDA memcpy (full profile)",
        "",
        f"   {memcpy['n_memcpys']:>5,} ops",
        f"   {memcpy['total_bytes']/1e9:>5.2f} GB   ({memcpy['total_ms']:.0f} ms)",
        "",
        "Volume is dominated by the one-",
        "time model-weight upload before",
        "step 1; ms sums overlapping async",
        "copies, so it can exceed the",
        "profile span.",
        "",
        "Caveat — kernel-level capture is",
        "buffer-truncated at step 1; NVTX",
        "phase ranges and memcpy counters",
        "survive across all 5 steps. The",
        "figure validates instrumentation",
        "alignment, not per-step kernel",
        "comparisons (see DECISIONS §4).",
    ]
    ax_mc.text(0.02, 0.98, "\n".join(lines), transform=ax_mc.transAxes,
               family="monospace", fontsize=9.5, va="top", ha="left",
               bbox=dict(boxstyle="round,pad=0.6", facecolor="#F7F4EE",
                         edgecolor="#9C755F", linewidth=0.8))

    fig.suptitle(
        "Auxiliary Nsight Systems profile · compaction_agent · compaction_on",
        x=0.06, y=0.99, ha="left", fontsize=12.5,
    )
    save_figure(fig, out_path)
    plt.close(fig)


def main(argv: list[str]) -> int:
    db = Path(argv[1]) if len(argv) > 1 else Path("analysis_out/final_v3/nsight_compaction_on.sqlite")
    out_csv = Path(argv[2]) if len(argv) > 2 else Path("analysis_out/final_v3/nsight_summary.csv")
    out_fig = Path(argv[3]) if len(argv) > 3 else Path("figures/final_v3/nsight_phase_kernels")
    if not db.exists():
        print(f"Nsight SQLite not found: {db}", file=sys.stderr)
        print("Build it once with: nsys export --type sqlite --output <path>.sqlite "
              "analysis_out/final_v3/nsight_compaction_on.nsys-rep")
        return 1

    conn = sqlite3.connect(str(db))
    try:
        phases = phase_ranges(conn)
        classes = kernel_breakdown(conn)
        memcpy = memcpy_summary(conn)
    finally:
        conn.close()

    rows = [
        {"row_kind": "phase", "label": f"{p['phase']}_s{p['step']}",
         "value_ms": round(p["duration_ms"], 2), "note": ""}
        for p in phases
    ]
    for klass, (n, ms) in classes.items():
        rows.append({"row_kind": "kernel_class", "label": klass,
                     "value_ms": round(ms, 2), "note": f"{n} kernels"})
    rows.append({"row_kind": "memcpy", "label": "h2d_d2h_total",
                 "value_ms": round(memcpy["total_ms"], 2),
                 "note": f"{memcpy['n_memcpys']} ops, {memcpy['total_bytes']/1e9:.2f} GB"})
    write_csv(out_csv, rows, ["row_kind", "label", "value_ms", "note"])
    print(f"Wrote {out_csv}")
    figure(phases, classes, memcpy, out_fig)
    print(f"Wrote {out_fig}.png/.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
