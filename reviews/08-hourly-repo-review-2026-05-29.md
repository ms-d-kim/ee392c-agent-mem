# Hourly Repo Review — Scan-Pressure Boundary Pass

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the checked-in final-v3 traces,
generated CSVs/figures, current repo diffs, and paper-facing evidence
boundaries.

## What I reviewed

- Final-v3 H100 traces in `traces/final_v3/` plus the auxiliary Nsight-profiled
  compaction trace in `traces/final_v3_nsight/`.
- Generated outputs in `analysis_out/final_v3/` and figures in
  `figures/final_v3/`.
- Existing uncommitted repo changes, to avoid overwriting prior user or
  automation edits.
- Current differentiated-memory framing for resident reuse, prompt pollution,
  compaction tradeoffs, and analytical-KV limits.

## Evidence-backed readout

The repo remains internally consistent with the locked final-v3 scope:
deterministic workflow replays, analytical KV sizing, cached-token
availability/count reconciliation, and prescriptive tier mapping rather than
measured physical placement.

The strongest differentiated-memory insights still come from the three paired
workflow contrasts:

- Coding replay: cache-on keeps total prompt tokens nearly matched to cache-off
  while cutting cache-adjusted new KV from 90,087,424 B to 14,106,624 B, which
  supports a low-latency resident tier for stable repeated prefixes.
- Search replay: both traces scan 88,372 B, but broad retrieval returns 2,318 B
  versus 691 B and inserts 672 B versus 350 B, with `search_result` logical KV
  rising to 75,292,672 B from 23,396,352 B. The cost driver is what enters
  prompt history, not the scan itself.
- Compaction replay: raw-context logical KV falls from 1,032,249,344 B to
  443,211,776 B, but cached-token fraction falls from 0.783 to 0.536 and new
  prefill tokens rise from 4,826 to 5,740. This remains a capacity-versus-prefix
  reuse tradeoff, not a free win.

## Improvement applied in this pass

- `analysis_out/README.md` now states that `search_corpus_scan` in
  `semantic_summary.csv` is a deterministic scan-pressure proxy for the search
  replay, not a claim that the entire scanned corpus stayed resident like prompt
  history or KV state.
- `figures/README.md` now carries the same caveat on
  `final_v3/semantic_byte_seconds`, so the dense inventory-style plot is less
  likely to be overread in the report.

## Validation rerun

- `make verify`
- `make verify-v3-validator`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

All four passed in this repo state.

## Remaining risks and evidence gaps

- No physical tier placement, bandwidth, migration, or offload evidence is
  measured by design.
- Cached-token reconciliation is still an availability/count check against
  vLLM counters, not independent semantic-span attribution proof.
- `semantic_summary.csv` still mixes logical-presence lifetime for text/token
  objects with next-prefill-bounded lifetime for `kv_estimated` spans, which is
  intentional per `DECISIONS.md` but should stay explicit in the report.
