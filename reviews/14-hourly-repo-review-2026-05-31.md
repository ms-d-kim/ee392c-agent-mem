# Hourly Repo Review — Step-Normalized Semantic Inventory

Date: 2026-05-31
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the official final-v3 H100 traces,
generated CSVs/figures, and the current dirty worktree for a scoped artifact
improvement.

## What I reviewed

- The six official H100 traces in `traces/final_v3/` plus the auxiliary
  Nsight-profiled compaction replay in `traces/final_v3_nsight/`.
- `analysis_out/final_v3/*.csv` with emphasis on `semantic_summary.csv`,
  `kv_pressure.csv`, `prompt_cache_summary.csv`, and
  `cached_token_cross_check.csv`.
- The paper-facing descriptions in `README.md`, `analysis_out/README.md`,
  `figures/README.md`, and the current `analysis/final_v3.py` plotting path.

## Evidence-backed assessment

The checked-in six-trace H100 dataset remains internally consistent:

- all six final-v3 traces are real (`dry_run=false`),
- every cached-token cross-check row currently reports
  `cross_check_status="passed"`,
- the broad-vs-targeted search and compaction-on-vs-off contrasts still support
  the intended differentiated-memory story without implying physical placement
  or migration measurement.

The main remaining artifact-level inconsistency in this pass was presentation:
the repo already tells the report writer to prefer `byte_steps` over
wall-clock `byte_seconds` for cross-workload mechanism comparisons, but the
generated semantic inventory figure existed only in `byte_seconds` form.

## Improvement applied

- Added `figures/final_v3/semantic_byte_steps.{png,svg}` generation to
  `analysis/final_v3.py` so the preferred step-normalized semantic inventory is
  available as a first-class artifact, not just a CSV column.
- Updated `figures/README.md` to make `semantic_byte_steps` the preferred
  cross-workload inventory view and demote `semantic_byte_seconds` to
  supporting timing context.
- Added one README sentence pointing paper writing toward the new
  step-normalized figure.

## Validation status

- `python3 -m validation.synthetic --output /tmp/synthetic_hourly_review_20260531.jsonl`
- `python3 -m validation.assert_synthetic /tmp/synthetic_hourly_review_20260531.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`

These should remain the minimum checks for this pass because analysis code
changed but the schema and validator logic did not.

## Remaining risks and evidence gaps

- The artifact still does not measure physical placement, residency, bandwidth,
  or migration across differentiated memory tiers.
- Cached-token cross-checks remain availability/count reconciliation against
  vLLM counters, not independent semantic-span attribution proof.
- The six final-v3 traces remain paired contrasts rather than replicated
  conditions, so report framing should stay mechanism-based rather than
  statistical.
