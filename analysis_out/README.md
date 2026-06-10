# Analysis Outputs

Generated CSV artifacts for the historical v2 batch and the official final-v3
H100 sweep.

Regenerate final-v3 outputs with:

```bash
python3 -m analysis.final_v3 traces/final_v3
```

## Final-v3 CSVs

These files are derived from the six checked-in H100 workflow-replay traces in
`traces/final_v3/`.

- `semantic_summary.csv` — semantic-class counts, byte-seconds, step-normalized
  byte-steps, and logical read-event totals per trace. For cross-workload
  comparison, prefer `byte_steps`: it preserves the logical capacity-time
  signal while avoiding wall-clock drift from generation speed or system load.
  This excludes `search_corpus_scan`, which is a scan-pressure proxy for the
  search replay rather than a prompt-resident or measured resident-memory
  object. `logical_read_events` totals two populations, reported separately as
  `prompt_construction_reads` (text/token re-reads during prompt assembly) and
  `cached_prefix_kv_reads` (engine-reported cached-prefix KV reuse; present
  only when prefix caching is on, so the total is cache-condition-dependent).
- `kv_pressure.csv` — analytical KV totals split into logical projected KV,
  cached-prefix reuse KV, and cache-adjusted new KV.
- `duplication_factor.csv` — text/token duplication and KV amplification
  diagnostics. Useful for reasoning about representational overhead, but not a
  headline figure by itself.
- `search_funnel.csv` — scanned, returned, and inserted bytes for the search
  contrast.
- `compaction_funnel.csv` — raw-context bytes, summary bytes, and summary reuse
  for the compaction contrast.
- `cached_token_cross_check.csv` — per-step cached-token availability and
  count-reconciliation rows from vLLM request-output counters.
- `prompt_cache_summary.csv` — per-trace totals for prompt tokens, cached
  tokens, new prefill tokens, and cached-token fraction.
- `carryover.csv` — per-step KV working set split into new-prefill versus
  carried-from-an-earlier-step bytes, with the carried fraction
  (`analysis/carryover.py`).
- `nsight_summary.csv` — NVTX phase spans, kernel-class times, and total CUDA
  memcpy from the auxiliary Nsight profile (`analysis/nsight.py`). The memcpy
  volume is dominated by the one-time model-weight upload before step 1.

## Historical v2 CSVs

- `summary_v2.csv` — per-trace lifetime/reuse summary over `traces/batch_v2/`
  (`analysis/lifetime.py`).
- `per_category_breakdown.csv` — per-category byte-seconds and read shares.
  **Provenance:** computed from the `hello_bug` subset (10 of the 20 v2
  traces), per the usage line in `analysis/per_category.py`. The headline
  99.994% / 3.34% split is for that subset; over all 20 traces the read share
  is 3.46%. The qualitative capacity/access dichotomy holds for both.

## Evidence boundary

- `cached_token_cross_check.csv` is an availability/count-reconciliation check,
  not independent semantic-attribution proof.
- `kv_pressure.csv` reports analytical KV projections from token spans, not
  measured physical HBM residency or cross-tier migration.
- `semantic_summary.csv` mixes text/token logical-presence lifetime with
  next-prefill-bounded `kv_estimated` lifetime, matching `DECISIONS.md`.
- `semantic_summary.csv` includes both wall-clock `byte_seconds` and
  step-normalized `byte_steps`; use `byte_steps` for cross-workload mechanism
  comparisons and keep `byte_seconds` as supporting timing context only.
- `search_corpus_scan` is intentionally kept in `search_funnel.csv` and omitted
  from live-object summaries because it represents scan volume, not resident
  prompt/KV state.
- Dry-run outputs are valid for plumbing validation only. Do not use dry-run
  byte-seconds or dry-run figures for the paper.
