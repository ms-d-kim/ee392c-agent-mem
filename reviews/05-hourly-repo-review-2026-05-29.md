# Hourly Repo Review — Artifact Boundary Pass

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and `validation/synthetic.py`,
then reviewed the current repo state, checked final-v3 trace artifacts, and
revalidated the synthetic and final-v3 gates.

## What I reviewed

- Repo state and current uncommitted changes, to avoid overwriting existing
  user or prior-automation work.
- Final-v3 trace artifacts under `traces/final_v3/` and the auxiliary Nsight
  trace under `traces/final_v3_nsight/`.
- Generated outputs under `analysis_out/final_v3/` and figures under
  `figures/final_v3/`.
- The README / figure / setup framing around cached-token validation,
  workflow-replay scope, and differentiated-memory implications.

## Assessment

The current checkout is internally consistent with the locked final-v3 framing.
The six H100 traces remain the official dataset; the Nsight trace remains an
auxiliary profile of an existing compaction replay; and the repo consistently
describes tier mapping as prescriptive from logical semantic/token/KV evidence
rather than measured physical placement.

The strongest differentiated-memory evidence remains:

- coding cache-on versus cache-off cleanly isolates resident-prefix reuse,
- targeted versus broad search isolates prompt pollution after the same scan,
- compaction shows a capacity-versus-prefix-reuse tradeoff rather than a simple
  "always cheaper" story.

## Improvement applied in this pass

I tightened artifact-level documentation so the generated outputs are harder to
misread:

- `analysis_out/README.md` now explains each final-v3 CSV and states the
  evidence boundary explicitly, including the cached-token reconciliation limit
  and analytical-KV limit.

This is a scoped documentation improvement only. No schema or analysis logic
changed in this pass.

## Validation rerun

- `make verify`
- `make verify-v3-validator`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

## Remaining risks and evidence gaps

- No physical tier-placement, residency, migration, or bandwidth evidence is
  measured.
- No within-condition replication exists, so the six final-v3 traces support
  mechanism-based characterization rather than statistical generalization.
- Historical v2 analysis remains background/appendix material and should not be
  allowed to outrun the final-v3 H100 evidence in the report.
