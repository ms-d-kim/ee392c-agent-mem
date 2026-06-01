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
  object.
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
