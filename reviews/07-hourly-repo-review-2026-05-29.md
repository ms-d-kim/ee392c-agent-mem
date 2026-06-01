# Hourly Repo Review — Differentiated-Memory Evidence Check

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the required contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the checked-in final-v3 traces,
generated CSVs/figures, validator gates, and the current differentiated-memory
framing.

## What I reviewed

- Final-v3 H100 traces in `traces/final_v3/` and the auxiliary Nsight-profiled
  compaction trace in `traces/final_v3_nsight/`.
- Generated final-v3 CSVs in `analysis_out/final_v3/`.
- Paper-facing plots in `figures/final_v3/` and the historical appendix-facing
  figures in `figures/`.
- Current wording in `README.md`, `analysis_out/README.md`,
  `figures/README.md`, and `traces/README.md` for claim drift.

## Evidence-backed differentiated-memory readout

The checked-in traces support a coherent prescriptive mapping onto a
differentiated memory system, with the evidence boundary still stated honestly:
logical semantic objects, token spans, and analytical KV pressure are measured;
physical HBM residency, bandwidth, migration, and offload are not.

The main mechanism-level insights remain aligned with the CSVs:

- Coding replay: `prompt_cache_summary.csv` shows 1,344 cached prompt tokens
  and only 246 new prefill tokens with cache on, versus 1,571 new prefill
  tokens with cache off. `kv_pressure.csv` shows cache-adjusted new KV falling
  from 90,087,424 B to 14,106,624 B. This is strong evidence that stable
  repeated prompt prefixes belong in the lowest-latency resident tier when
  reuse is high.
- Search replay: `search_funnel.csv` shows identical scanned bytes
  (88,372 B) across targeted and broad search, but materially different prompt
  insertion pressure: returned bytes are 691 B vs 2,318 B and inserted snippet
  bytes are 350 B vs 672 B. `kv_pressure.csv` shows `search_result` logical KV
  at 23,396,352 B targeted versus 75,292,672 B broad, about 3.22x. This
  supports the claim that the memory problem is prompt pollution, not corpus
  scan volume itself.
- Compaction replay: `compaction_funnel.csv` shows the same 18,602 B raw input
  in both conditions, with compaction adding a 513 B summary. `kv_pressure.csv`
  shows `raw_context` logical KV dropping from 1,032,249,344 B to
  443,211,776 B, while cache-adjusted new KV for raw context stays
  269,287,424 B in both conditions. The honest differentiated-memory takeaway
  is capacity relief plus a reuse disruption tradeoff, not a free win.

## Figure alignment

The current headline figures match the validated evidence and the project goal:

- `figures/final_v3/prompt_cache_reuse` is the clearest direct link between
  workflow structure and resident-tier reuse.
- `figures/final_v3/search_prompt_pollution` correctly emphasizes inserted
  prompt content rather than scanned corpus size.
- `figures/final_v3/compaction_raw_context_kv` is the strongest quantitative
  support for the capacity-tier part of the tier-mapping argument.
- `figures/fig4_dms_tier_proposal` remains appropriately framed as a
  prescriptive diagram derived from the traces, not measured placement or
  migration evidence.

I did not find a checked-in figure or README claim in this pass that crossed
the locked boundary into physical-tier or autonomous-agent overclaiming.

## Validation rerun

- `python3 -m validation.assert_synthetic traces/synthetic.jsonl`
- `python3 -m validation.assert_validate_final_v3`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

All four passed in this repo state.

## Repo-quality assessment

Toward a PhD-standard final artifact, the repo is now in a strong state on
internal consistency: schema contract, synthetic gate, final-v3 validator,
trace-backed figures, and paper-facing evidence boundaries are mutually
aligned.

The remaining quality risk is not internal inconsistency. It is the inherent
scope limit of the artifact:

- No physical tier-placement or migration measurement exists by design.
- Cached-token reconciliation is an availability/count check, not independent
  semantic attribution proof.
- The six H100 traces are paired contrasts, not replicated conditions, so the
  report still needs mechanism language rather than statistical generalization.
