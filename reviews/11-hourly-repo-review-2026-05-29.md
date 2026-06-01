# Hourly Repo Review — Search Scan Proxy Cleanup

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the required contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the final-v3 H100 traces, generated
CSV/figure artifacts, and current evidence boundaries for differentiated memory
system claims.

## What I reviewed

- The six official H100 traces in `traces/final_v3/` plus the auxiliary Nsight
  replay trace in `traces/final_v3_nsight/`.
- Final-v3 analysis outputs under `analysis_out/final_v3/` and figures under
  `figures/final_v3/`.
- Current README / artifact README language to check whether the figures match
  the validated evidence boundary.
- Existing dirty-worktree changes, to avoid overwriting unrelated work.

## Finding fixed in this pass

`search_corpus_scan` was intended as a deterministic scan-volume proxy for the
search replay, but `analysis.final_v3` still let it flow into live-object
summaries through `liveness_intervals()`. That made byte-seconds, duplication,
and reuse-style summaries treat a scan counter as if it were resident
prompt/KV-backed state.

## Improvement applied

- `analysis/final_v3.py` now excludes `search_corpus_scan` from resident
  live-object summaries while preserving it in `search_funnel.csv`, where it
  belongs as the equal-scan control.
- Regenerated `analysis_out/final_v3/semantic_summary.csv` and
  `analysis_out/final_v3/duplication_factor.csv`; the `search_corpus_scan` rows
  are gone from those resident-object summaries.
- Updated `README.md`, `analysis_out/README.md`, and `figures/README.md` so the
  repo states explicitly that scan volume is carried by the funnel artifact,
  not by byte-seconds or duplication summaries.

## Validation rerun

- `python3 -m validation.synthetic --output /tmp/synthetic_review.jsonl`
- `python3 -m validation.assert_synthetic /tmp/synthetic_review.jsonl`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

All four passed in this repo state.

## Remaining risks and evidence gaps

- The repo still does not measure physical placement, migration, or bandwidth
  across differentiated memory tiers; the tier diagram remains prescriptive.
- Cached-token cross-checks remain vLLM availability/count reconciliation, not
  independent semantic-span proof.
- `agent/graph.py` and `agent/tools.py` remain historical LangGraph stubs with
  extra dependencies that are not part of the final-v3 scripted replay path.
