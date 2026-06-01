# Hourly Repo Review — Core Dataset Boundary Note

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the required contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the current final-v3 traces,
generated CSVs/figures, validator gates, and artifact-boundary documentation.

## What I reviewed

- The six official H100 final-v3 traces in `traces/final_v3/`.
- The auxiliary telemetry and Nsight artifacts in `traces/final_v3_system/`
  and `traces/final_v3_nsight/`.
- Generated outputs in `analysis_out/final_v3/` and figures in
  `figures/final_v3/`.
- Existing uncommitted repo changes, to avoid overwriting prior work.

## Evidence-backed assessment

The repo remains internally consistent with the locked final-v3 framing:

- The six H100 traces are still the only core comparison dataset for the final
  artifact.
- Cached-token checks remain availability/count reconciliation against vLLM
  counters, not independent semantic-span proof.
- The differentiated-memory story remains strongest where the CSVs isolate one
  mechanism at a time: resident prefix reuse in coding, prompt pollution in
  search, and capacity-versus-prefix-reuse tradeoff in compaction.

No checked-in figure or CSV in this pass appeared to outrun the validated
boundary into physical placement, migration, bandwidth measurement, or
autonomous-agent claims.

## Improvement applied in this pass

- `traces/README.md` now states explicitly that only `traces/final_v3/` feeds
  the paper-facing `analysis.final_v3` CSVs and figures. The auxiliary
  `final_v3_system/` and `final_v3_nsight/` directories remain supporting
  artifacts only. This reduces the risk of future report work accidentally
  treating them as extra rows in the six-trace comparison.

## Validation status

- `make verify` passed.
- `make verify-v3-validator` passed.
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl` passed.
- `python3 -m analysis.final_v3 traces/final_v3` completed and rewrote the
  current final-v3 CSVs/figures in this checkout.

## Remaining risks and evidence gaps

- No physical tier placement, migration, residency, or bandwidth evidence is
  measured by design.
- The six final-v3 traces are paired contrasts, not replications, so the final
  report should stay mechanism-focused rather than statistical.
- Auxiliary telemetry and Nsight artifacts are useful supporting context, but
  the report should keep them clearly subordinate to the six validated H100
  replay traces.
