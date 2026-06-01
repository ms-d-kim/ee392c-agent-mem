# Hourly Repo Review — Resident Figure Label Cleanup

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the current final-v3 traces,
generated CSVs/figures, prior hourly-review notes, and the dirty worktree.

## What I reviewed

- The six official H100 traces in `traces/final_v3/` plus the auxiliary
  Nsight-profiled compaction replay in `traces/final_v3_nsight/`.
- Final-v3 generated outputs under `analysis_out/final_v3/` and the paper-facing
  figures under `figures/final_v3/`.
- Current analysis and docs changes already in the worktree, to avoid
  overwriting earlier user or automation work.

## Evidence-backed assessment

The repo remains aligned with the locked final-v3 boundary:

- The six H100 workflow replays remain the core dataset.
- Cached-token checks remain availability/count reconciliation against vLLM
  counters, not independent semantic-span proof.
- The differentiated-memory argument remains strongest in the paired mechanisms:
  coding prefix reuse, search prompt pollution after equal scan volume, and
  compaction’s capacity-versus-prefix-reuse tradeoff.

I did not find a new data-integrity or validator gap in this pass. The main
remaining issue was artifact wording drift after the prior `search_corpus_scan`
cleanup.

## Improvement applied

- `analysis/final_v3.py` now titles the `semantic_byte_seconds` figure as
  **resident** semantic byte-seconds, matching the current code path that
  excludes the `search_corpus_scan` proxy from live-object summaries.
- `figures/README.md` now uses the same resident-only wording for that figure.
- Regenerated `figures/final_v3/semantic_byte_seconds.{png,svg}` through
  `python3 -m analysis.final_v3 traces/final_v3`.

This is a wording/figure-alignment fix only. No schema, trace, or metric logic
changed beyond the title string.

## Validation rerun

- `python3 -m validation.synthetic --output /tmp/synthetic_hourly_review.jsonl`
- `python3 -m validation.assert_synthetic /tmp/synthetic_hourly_review.jsonl`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

All four completed successfully in this repo state.

## Remaining risks and evidence gaps

- The artifact still does not measure physical placement, migration, residency,
  or bandwidth across differentiated memory tiers.
- Cached-token cross-checks remain a vLLM availability/count-reconciliation
  gate, not independent semantic-attribution proof.
- The six final-v3 traces remain paired contrasts rather than replicated
  conditions, so the final report should stay mechanism-focused rather than
  statistical.
