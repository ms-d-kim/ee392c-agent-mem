# Hourly Repo Review — Reproduction and Boundary Audit

Date: 2026-05-31
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the official final-v3 H100 traces,
generated CSVs/figures, and the current dirty worktree for artifact
reproducibility and differentiated-memory-system alignment.

## What I reviewed

- The six official H100 traces in `traces/final_v3/`.
- The generated final-v3 CSVs in `analysis_out/final_v3/`.
- The generated final-v3 figures in `figures/final_v3/`.
- The boundary language in `README.md`, `figures/README.md`,
  `analysis_out/README.md`, and `traces/README.md`.
- The cached-token gate in `validation/validate_final_v3.py` plus its
  regression checks in `validation/assert_validate_final_v3.py`.

## Evidence-backed DMS insights

- Coding replay: prefix caching keeps total prompt tokens nearly flat
  (1,571 cache-off vs 1,590 cache-on) while reducing new prefill tokens from
  1,571 to 246 and cache-adjusted new KV from 90,087,424 B to 14,106,624 B.
  The differentiated-memory implication is a low-latency resident tier for
  stable reused prefixes rather than treating repeated context as fresh working
  set each step.
- Search replay: both conditions scan the same 88,372 B corpus, but broad
  retrieval returns 2,318 B vs 691 B and inserts 672 B vs 350 B into prompt
  history. Broad `search_result` byte-seconds are 170,625,330 vs 52,516,956
  targeted, and broad prompt tokens total 4,048 vs 2,957. The important tier
  point is that retrieval noise becomes prompt/KV pressure only when it is
  admitted into active context.
- Compaction replay: both conditions start from the same 18,602 B raw context,
  but compaction reduces raw-context byte-steps from 763,066,786 to
  370,321,154 and projected KV from 1,032,249,344 B to 443,211,776 B. This is
  the strongest repo-backed argument for transforming bulky retained context
  before it expands the active prompt/KV working set.

## What changed

- Added this review note only. No schema, tracer, validator, analysis logic, or
  figure semantics were changed in this pass.

## Validation

- `make verify`
- `python3 -m validation.assert_validate_final_v3`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

All four passed in the current checkout.

## Remaining risks

- The repo is already dirty with intentional local edits. This pass treated
  those changes as in-progress user work and did not rewrite them.
- The cached-token gate is still a vLLM counter reconciliation check, not
  independent proof that every semantic span attribution is correct.
- The six final-v3 traces are paired contrasts, not replicated conditions, so
  any paper prose drifting toward significance or benchmark language still
  needs to be tightened.
- The tier-mapping figure remains prescriptive. The repo still does not measure
  physical HBM residency, DRAM/CXL placement, cross-tier migration, or
  hardware-counter bandwidth.

## Evidence gaps to keep explicit

- Dry-run final-v3 traces remain plumbing validation only and should not enter
  paper figures or cross-condition claims.
- Auxiliary system telemetry and the single Nsight Systems replay remain
  supporting material, not additional workload evidence beyond the six official
  H100 traces.
