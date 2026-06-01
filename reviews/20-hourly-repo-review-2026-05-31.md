# Hourly Repo Review — Validation Pass and Runbook Hygiene

Date: 2026-05-31
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the official final-v3 H100 traces,
derived CSVs, rendered figures, validation path, and current dirty worktree
for one narrow documentation improvement aligned with the final artifact.

## What I reviewed

- The six official H100 traces in `traces/final_v3/`.
- The derived final-v3 CSVs in `analysis_out/final_v3/`, especially
  `prompt_cache_summary.csv`, `cached_token_cross_check.csv`,
  `kv_pressure.csv`, `semantic_summary.csv`, `search_funnel.csv`, and
  `compaction_funnel.csv`.
- The rendered final-v3 figures in `figures/final_v3/` and the prescriptive
  tier-mapping diagram in `figures/fig4_dms_tier_proposal.*`.
- The tracer correctness gate in `validation.synthetic` /
  `validation.assert_synthetic`, the final-v3 validator, the validator
  regression harness, and the operator-facing runbooks.

## Evidence-backed DMS insights

- Coding replay: cache-on keeps total prompt tokens close to cache-off
  (1,590 vs 1,571) while shifting 1,344 tokens into cached-prefix reuse and
  reducing cache-adjusted new KV from 90,087,424 B to 14,106,624 B. The
  differentiated-memory implication remains that stable repeated prompt
  scaffolding benefits most from the lowest-latency resident tier.
- Search replay: both traces still scan the same 88,372 B corpus, but broad
  retrieval returns 2,318 B vs 691 B and inserts 672 B vs 350 B into prompt
  history. The trace-backed admission-control point remains that scan volume is
  not itself resident working-set pressure until retrieved content is promoted
  into prompt/KV state.
- Compaction replay: both traces still start from the same 18,602 B raw
  context, while compaction reduces raw-context logical KV from 1,032,249,344 B
  to 443,211,776 B and raw-context byte-steps from 763,066,786 to 370,321,154.
  This remains the clearest repo-backed mechanism for moving bulky retained
  context out of the active bandwidth-sensitive working set.

## What changed

- Updated operator-facing docs to use `python3` consistently in the final-v3
  runbook and figure-regeneration commands.
- Refreshed the README status snapshot to reflect the current locally passing
  validator regression gate alongside the checked-in H100 sweep.

## Validation

- `make verify`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl`
- `python3 -m validation.assert_validate_final_v3`
- `python3 -m analysis.final_v3 traces/final_v3`

All four passed in the current checkout.

## Remaining risks

- The worktree remains dirty with other in-progress local edits that this pass
  did not overwrite.
- Cached-token cross-check rows remain a vLLM counter
  availability/count-reconciliation gate, not independent proof of semantic KV
  span attribution.
- The tier-mapping diagram remains prescriptive rather than measured physical
  placement, migration, or hardware-counter evidence.
- The six final-v3 traces remain paired contrasts, not replicated conditions,
  so report prose still needs to avoid statistical or benchmark framing.

## Evidence gaps to keep explicit

- Dry-run final-v3 outputs remain plumbing validation only and should not enter
  paper figures or cross-condition claims.
- Auxiliary system telemetry and the single Nsight Systems replay remain
  supporting artifacts, not additional workload evidence beyond the six
  official H100 traces.
