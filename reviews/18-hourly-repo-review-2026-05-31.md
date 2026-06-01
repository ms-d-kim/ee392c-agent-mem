# Hourly Repo Review — Figure Set Prioritization

Date: 2026-05-31
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the official final-v3 H100 traces,
derived CSVs, rendered figures, and current dirty worktree for
differentiated-memory-system story clarity.

## What I reviewed

- The six official H100 traces in `traces/final_v3/`.
- The generated final-v3 CSVs in `analysis_out/final_v3/`.
- The rendered final-v3 figures in `figures/final_v3/` plus the tier proposal
  diagram in `figures/fig4_dms_tier_proposal.svg`.
- The paper-facing boundary language in `README.md`, `figures/README.md`,
  `analysis_out/README.md`, and `traces/README.md`.
- The validator hard gate in `validation/validate_final_v3.py` plus its
  regression checks in `validation/assert_validate_final_v3.py`.

## Evidence-backed DMS insights

- Coding replay: prefix caching keeps total prompt tokens nearly flat
  (1,571 cache-off vs 1,590 cache-on) while reducing new prefill tokens to 246
  and cache-adjusted new KV to 14,106,624 B. The DMS implication remains that
  stable reused scaffolding belongs in the lowest-latency resident tier.
- Search replay: both traces scan the same 88,372 B corpus, but broad retrieval
  returns 2,318 B vs 691 B and inserts 672 B vs 350 B into prompt history.
  The DMS point is admission control: retrieval noise becomes bandwidth-heavy
  prompt/KV pressure only after it is admitted into active context.
- Compaction replay: both traces start from the same 18,602 B raw context, but
  compaction reduces raw-context projected KV from 1,032,249,344 B to
  443,211,776 B. This remains the clearest repo-backed argument for
  transforming bulky retained context before it expands the active working set.

## What changed

- Updated `figures/README.md` with a recommended paper figure order so the repo
  explicitly distinguishes the core DMS evidence figures from supporting
  diagnostics and from the prescriptive tier-proposal diagram.

## Validation

- `make verify`
- `python3 -m validation.assert_validate_final_v3`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl`

All three passed in the current checkout. No tracer, validator, or analysis
logic changed in this pass, so figure regeneration was unnecessary.

## Remaining risks

- The repo remains dirty with other in-progress local edits that this pass did
  not overwrite.
- The cached-token gate is still a vLLM counter availability/count
  reconciliation check, not independent proof of semantic-span attribution.
- The six final-v3 traces remain paired contrasts, not replicated conditions,
  so paper prose still needs to avoid significance or benchmark language.
- The tier-mapping diagram remains prescriptive. The repo still does not
  measure physical HBM residency, DRAM/CXL placement, cross-tier migration, or
  hardware-counter bandwidth.

## Evidence gaps to keep explicit

- Dry-run final-v3 traces remain plumbing validation only and should not enter
  paper figures or cross-condition claims.
- Auxiliary system telemetry and the single Nsight Systems replay remain
  supporting artifacts, not additional workload evidence beyond the six
  official H100 traces.
