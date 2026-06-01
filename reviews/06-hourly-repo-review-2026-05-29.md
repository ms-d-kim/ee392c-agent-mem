# Hourly Repo Review — Gate Hardening Follow-Through

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and `validation/synthetic.py`,
then reviewed the current final-v3 traces, generated CSVs/figures, validation
code, and artifact-boundary documentation.

## What I reviewed

- The six checked-in H100 final-v3 traces in `traces/final_v3/` plus the
  auxiliary Nsight-profiled compaction trace in `traces/final_v3_nsight/`.
- Generated final-v3 outputs in `analysis_out/final_v3/` and paper-facing
  figures in `figures/final_v3/`.
- Current README / setup / trace / figure / analysis-output framing around
  logical read events, analytical KV, cached-token reconciliation, and
  differentiated-memory implications.
- The strengthened cached-token validator path in
  `validation/validate_final_v3.py` and
  `validation/assert_validate_final_v3.py`.

## Evidence-backed assessment

The current repo state stays inside the locked methodological boundary:
deterministic workflow replays, analytical KV sizing, cached-token
availability/count reconciliation, and prescriptive tier mapping rather than
measured physical placement or migration.

The differentiated-memory story remains coherent and trace-backed:

- Coding replay: prefix caching cuts new prefill KV sharply when the leading
  context is stable.
- Search replay: prompt pressure comes from what enters history, not what is
  scanned.
- Compaction replay: retained raw-context pressure falls materially, but prefix
  reuse is disrupted, so the honest claim is a capacity-versus-recompute
  tradeoff.

## Improvement applied in this pass

- `AGENTS.md` now records the validator regression gate explicitly. Future
  edits that touch `validation/validate_final_v3.py` or cached-token gate logic
  are instructed to run `python3 -m validation.assert_validate_final_v3`, which
  matches the current repo’s strengthened validation path and reduces the risk
  of a silent gate regression.

## Validation rerun

- `make verify`
- `make verify-v3-validator`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

## Remaining risks and evidence gaps

- The project still does not measure physical HBM residency, bandwidth, tier
  migration, or offload behavior.
- The six final-v3 traces are paired contrasts, not replicated conditions, so
  they support mechanism-based characterization only.
- Final-v3 figures and CSVs are strong for the report’s intended claim, but the
  report still needs to keep dry-run plumbing validation, cached-token
  reconciliation, and real H100 evidence clearly separated.
