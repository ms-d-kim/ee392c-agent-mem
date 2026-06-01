# Hourly Repo Review — Validation Boundary Hygiene

Date: 2026-05-31
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the official final-v3 H100 traces,
derived CSVs, rendered figures, validation path, and current dirty worktree for
one scoped improvement aligned with the differentiated-memory framing.

## What I reviewed

- The six official H100 traces in `traces/final_v3/`.
- The derived final-v3 CSVs in `analysis_out/final_v3/`, especially
  `prompt_cache_summary.csv`, `cached_token_cross_check.csv`,
  `kv_pressure.csv`, `semantic_summary.csv`, `search_funnel.csv`, and
  `compaction_funnel.csv`.
- The rendered final-v3 figures in `figures/final_v3/` and the tier-mapping
  diagram in `figures/fig4_dms_tier_proposal.*`.
- The tracer correctness and final-v3 validation path in `validation/`,
  `analysis/final_v3.py`, and the operator-facing `Makefile`.

## Evidence-backed DMS insights

- Coding replay: cache-on still keeps total prompt tokens near flat
  (1,590 vs 1,571) while shifting 1,344 prompt tokens into cached-prefix reuse
  and cutting cache-adjusted new KV from 90,087,424 B to 14,106,624 B. The
  mapping implication remains that stable repeated prefixes benefit most from a
  lowest-latency resident tier.
- Search replay: both traces still scan the same 88,372 B corpus, but broad
  retrieval returns 2,318 B vs 691 B and inserts 672 B vs 350 B into prompt
  history. The DMS implication remains admission control: bulky scan volume is
  only a tier-pressure problem once retrieved content is admitted into the
  prompt/KV working set.
- Compaction replay: both traces still start from the same 18,602 B raw
  context, while compaction reduces raw-context projected KV from
  1,032,249,344 B to 443,211,776 B and raw-context byte-steps from 763,066,786
  to 370,321,154. This remains the clearest repo-backed mechanism for moving
  bulky retained context out of the active working set before it drives
  bandwidth-sensitive pressure.

## What changed

- Updated `Makefile` help and `verify-v3` messaging to state explicitly that
  dry-run analysis is CSV-first and that figure rendering is intentionally
  skipped by default unless `--allow-dry-run-figures` is passed directly to
  `analysis.final_v3`.

## Validation

- `make verify`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl`
- `python3 -m validation.assert_validate_final_v3`
- `python3 -m analysis.final_v3 traces/final_v3`

All four passed in the current checkout.

## Remaining risks

- The repo remains dirty with other in-progress local edits that this pass did
  not overwrite.
- Cached-token cross-check rows remain a vLLM counter
  availability/count-reconciliation gate, not independent proof of semantic KV
  span attribution.
- The tier-mapping diagram remains prescriptive rather than measured physical
  placement, migration, or hardware-counter evidence.
- The six final-v3 traces remain paired contrasts, not replicated conditions,
  so paper prose still needs to avoid statistical or benchmark framing.

## Evidence gaps to keep explicit

- Dry-run final-v3 outputs remain plumbing validation only and should not enter
  paper figures or cross-condition claims.
- Auxiliary system telemetry and the single Nsight Systems replay remain
  supporting artifacts, not additional workload evidence beyond the six
  official H100 traces.
