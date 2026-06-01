# Hourly Repo Review — Final-v3 Evidence Check

Date: 2026-05-31
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the official final-v3 H100 traces,
generated CSVs/figures, and the current dirty worktree for paper-facing
consistency.

## What I reviewed

- The six official H100 traces in `traces/final_v3/`.
- The generated final-v3 artifacts in `analysis_out/final_v3/` and
  `figures/final_v3/`.
- The paper-facing boundary language in `README.md`, `figures/README.md`,
  `analysis_out/README.md`, and `traces/README.md`.
- The current validator hard gate in `validation/validate_final_v3.py` and its
  regression checks in `validation/assert_validate_final_v3.py`.

## Evidence-backed DMS insights

- Coding replay: prefix caching cuts cache-adjusted new KV from 90,087,424 B to
  14,106,624 B, an 84.3% reduction, while total prompt tokens stay nearly flat
  (1,571 vs 1,590). For differentiated memory systems, this supports keeping
  reused prompt scaffolding and prefix-resident state in the lowest-latency
  resident tier.
- Search replay: the targeted and broad traces scan the same corpus volume
  (88,372 B), but broad retrieval returns 2,318 B versus 691 B and inserts
  672 B versus 350 B into prompt history. Broad `search_result` projected KV is
  3.22x targeted. The tier implication is not "search is large" in general; it
  is that prompt-admitted retrieval noise creates avoidable high-bandwidth KV
  pressure.
- Compaction replay: both traces ingest the same 18,602 B of raw context, but
  compaction cuts raw-context projected KV from 1,032,249,344 B to
  443,211,776 B and raw-context byte-steps from 763,066,786 to 370,321,154.
  This is the clearest differentiated-memory result in the repo: bulky,
  lower-reuse retained context is the best candidate for demotion or
  transformation before it expands the active prompt/KV working set.

## What changed

- Added this review note only. No tracer, validator, trace, schema, or figure
  semantics were changed in this pass.

## Validation

- `python3 -m validation.synthetic --output /tmp/synthetic_hourly_review_20260531.jsonl`
- `python3 -m validation.assert_synthetic /tmp/synthetic_hourly_review_20260531.jsonl`
- `python3 -m validation.assert_validate_final_v3`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

All of these passed in the current checkout.

## Remaining risks

- The current repo state is dirty before and after this pass. Existing edits to
  docs, analysis, validator logic, and figures appear intentional, so this pass
  did not overwrite them.
- The cached-token cross-check remains a count-reconciliation gate against vLLM
  counters, not independent proof that every semantic span attribution is
  correct.
- The final-v3 six-trace dataset is still paired-contrast characterization, not
  replicated measurement. Any final report prose that sounds statistical should
  be tightened back to mechanism-based interpretation.
- The tier-mapping figure remains prescriptive. Nothing in the repo measures
  physical HBM residency, DRAM placement, CXL movement, or migration policy.

## Evidence gaps to keep explicit

- Dry-run final-v3 traces are still plumbing validation only and should not
  enter paper figures or cross-condition claims.
- Auxiliary system telemetry and the single Nsight Systems replay are support
  material, not extra workload evidence alongside the six official traces.
