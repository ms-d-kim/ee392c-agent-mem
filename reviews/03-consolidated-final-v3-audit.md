# Consolidated Final-v3 Audit

Date: 2026-05-29

This reconciles the Codex project pass in
`reviews/02-final-v3-project-pass.md` with Claude's independent audit.

Follow-up implementation status: the report-facing cleanup items below have
been applied in the repo. `analysis.final_v3` now emits step-normalized
`byte_steps`, `prompt_cache_summary.csv`, and non-constant final-v3 figures;
`DECISIONS.md` and `README.md` now describe cached-token validation as
availability/count reconciliation rather than semantic ground truth.

## Shared Verdict

Both audits agree on the core result: final-v3 is a defensible, internally
consistent project if the report stays inside its actual measurement boundary.

The safe headline is:

> Six deterministic H100 vLLM workflow replays show that workflow structure
> changes semantic prompt spans, analytical KV pressure, and reuse. Prefix
> caching, targeted retrieval, and compaction each move pressure between new KV,
> cached-prefix reuse, and retained semantic context.

The unsafe headline is:

> We measured physical HBM residency, memory bandwidth, cross-tier migration, or
> autonomous production-agent behavior.

## Validated Facts

- The official quantitative dataset is six traces in `traces/final_v3/`.
- All six are real H100 traces with `dry_run=false`.
- The auxiliary Nsight trace in `traces/final_v3_nsight/` is an existing
  `compaction_agent / compaction_on` profile, not a seventh workload.
- `validation.validate_final_v3` passes for all six core traces and the Nsight
  trace.
- The synthetic oracle passes.
- Re-running `analysis.final_v3` reproduces the checked CSVs byte-for-byte.
- `analysis_out/final_v3/cached_token_cross_check.csv` has 28 rows:
  coding has 5+5 generation steps, compaction has 5+5, search has 4+4.

## Corrections To Claude's Audit

Claude's main reasoning is sound, but two numbers need correction:

1. The cross-check CSV has 28 rows, not 30.
2. Local trace and system telemetry durations do not show compaction-on taking
   about 13.5 s versus compaction-off about 6.4 s. The local artifacts show:

| Trace | Trace duration (s) | System telemetry duration (s) |
|---|---:|---:|
| `compaction_agent_compaction_on` | 13.455 | 13.460 |
| `compaction_agent_compaction_off` | 13.625 | 13.631 |

So the "compaction trades capacity for recompute" finding is supported by
new-prefill-token accounting, not by observed wall-clock in this one sweep.

## Most Important Addition From Claude

Claude correctly sharpened the cached-token gate interpretation.

The current gate proves that:

- vLLM exposes a cached-token counter for every generation step.
- `cached_tokens <= prompt_token_count`.
- The tracer's leading-prefix accounting reconciles with the vLLM count.
- The value is not `unavailable`.

It does not independently prove semantic-span attribution. Because prompt spans
tile `[0, prompt_token_count]`, summing overlap with `[0, cached_tokens)` will
equal `cached_tokens` whenever `cached_tokens <= prompt_token_count`. That makes
the zero-delta rows a count-reconciliation/availability check, not independent
semantic attribution validation.

Report wording should say:

> We reconcile vLLM's cached-prefix token count with tracer-derived leading
> prompt spans and use that to ensure cached-token extraction is available and
> internally consistent.

Avoid:

> The engine independently validates semantic KV attribution.

## Strongest Final-v3 Results

### Prefix caching

Coding cache-on versus cache-off is the cleanest engine ablation:

| Trace | Prompt tokens | Cached tokens | New prefill tokens | Cache-adjusted new KV |
|---|---:|---:|---:|---:|
| cache off | 1,571 | 0 | 1,571 | 90,087,424 B |
| cache on | 1,590 | 1,344 | 246 | 14,106,624 B |

Claim: prefix caching reduces cache-adjusted new KV by 84.3% in the coding
replay.

### Targeted versus broad search

Both search traces scan the same 88,372-byte expanded corpus. The contrast is
returned/inserted context, not scan volume:

- Broad returned bytes: 2,318; targeted: 691.
- Broad inserted snippet bytes: 672; targeted: 350.
- Broad `search_result` logical KV: 75,292,672 B; targeted: 23,396,352 B.
- Broad `retrieved_snippet` logical KV: 22,249,472 B; targeted: 11,583,488 B.

Claim: targeted retrieval reduces prompt pollution after the same scan volume.

### Compaction

Both compaction traces ingest the same 18,602 raw-context bytes. Compaction-on
adds a 513-byte summary and demotes earlier raw context.

Capacity-side result:

- Total prompt tokens: 12,364 on versus 22,234 off.
- Max prompt tokens: 3,878 on versus 6,335 off.
- Raw-context logical KV: 443.2 MB on versus 1,032.2 MB off.
- Raw-context byte-seconds: 1.196B on versus 2.810B off.

Reuse/recompute-side result:

| Trace | Prompt tokens | Cached tokens | New prefill tokens |
|---|---:|---:|---:|
| compaction on | 12,364 | 6,624 | 5,740 |
| compaction off | 22,234 | 17,408 | 4,826 |

Claim: compaction lowers retained raw-context capacity pressure but can increase
new prefill work because it disrupts prefix-cache continuity. This is a stronger
systems insight than a simple "compaction always makes inference cheaper" claim.

## Issues Addressed Or Still To Track

1. Fixed: `DECISIONS.md` now says final-v3 uses vLLM request-output cached-token
   fields for availability/count reconciliation.
2. Fixed: `analysis.final_v3` now emits step-normalized `byte_steps` and
   `max_lifetime_steps` in `semantic_summary.csv`.
3. Fixed: weak final-v3 figures have been replaced in the analysis path:
   - `search_prompt_pollution` replaces constant `search_scanned_bytes`.
   - `compaction_raw_context_kv` and `compaction_raw_context_byte_steps`
     replace constant raw-input byte figures.
4. Fixed: the README leads with final-v3 H100 findings and treats
   `kv_text_amplification` as an analytical caution rather than the hero plot.
5. Still track: regenerate or relabel any historical v2 figure that still implies bandwidth
   rather than logical read events.
6. Fixed in README: v2 findings are now explicitly background after final-v3
   H100 findings.

## Recommended Report Structure

1. Methods: scripted final-v3 workflow replays, schema v3 tracing, semantic
   prompt spans, analytical KV projection, vLLM cached-token reconciliation.
2. Validation: synthetic oracle, final-v3 validator, `dry_run=false`, cached
   token availability/reconciliation, Nsight as auxiliary timeline only.
3. Results:
   - prefix caching reduces new KV in coding,
   - targeted retrieval reduces prompt-inserted search content,
   - compaction trades retained context capacity for prefix-cache disruption.
4. Discussion: differentiated memory implication:
   - stable repeated prefixes benefit from cache/high-bandwidth reuse,
   - bulky retained context creates capacity pressure,
   - compaction is a semantic memory-management operation with both capacity and
     recompute consequences.
5. Limitations: no physical HBM residency, bandwidth, SRAM, cross-tier migration,
   autonomous-agent benchmark, or statistical generalization.

## Bottom Line

Claude's audit and the Codex audit mostly converge. Claude's best contribution
is the sharper interpretation of the cached-token cross-check and the
new-prefill-token compaction tradeoff. Codex's prior audit already captured the
figure weakness, report-boundary cautions, and concrete pairwise KV/readout
numbers. The combined final message should be: the project is solid, but the
paper should become more precise, not more ambitious.
