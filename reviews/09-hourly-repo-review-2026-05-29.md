# Hourly Repo Review — Search Figure Control Annotation

Date: 2026-05-29
Reviewer: Codex automation

## Scope

This pass re-read the required project contracts in `AGENTS.md`, `README.md`,
`DECISIONS.md`, `SETUP.md`, `agent/tracer.py`, and
`validation/synthetic.py`, then reviewed the checked-in final-v3 traces,
generated CSVs/figures, and current paper-facing evidence boundaries.

## What I reviewed

- Final-v3 H100 traces in `traces/final_v3/` and the auxiliary Nsight trace in
  `traces/final_v3_nsight/`.
- Generated outputs in `analysis_out/final_v3/` and figures in
  `figures/final_v3/`.
- Existing uncommitted repo changes, to avoid overwriting prior work.
- Whether the figures make the differentiated-memory mechanism visible without
  overstating measured evidence.

## Evidence-backed readout

The final-v3 artifact still supports the intended differentiated-memory story:

- Coding replay: prefix caching preserves nearly matched prompt size while
  sharply reducing cache-adjusted new KV, which supports a low-latency
  resident tier for reused stable prefixes.
- Search replay: both conditions scan the same 88,372 B, but the broad replay
  returns and inserts materially more content into prompt history. The memory
  difference is prompt pollution, not scan volume.
- Compaction replay: compaction reduces retained raw-context KV substantially,
  but weakens prefix reuse and raises new prefill work. This is a tradeoff
  between capacity pressure and resident-prefix reuse, not a free improvement.

## Improvement applied in this pass

- `analysis/final_v3.py` now annotates the search prompt-pollution figure with
  the equal-scan control when both traces share the same scanned-byte total.
  This makes the causal comparison explicit on the artifact itself instead of
  requiring the viewer to cross-reference the CSV or README.

## Validation rerun

- `make verify`
- `python3 -m validation.assert_validate_final_v3`
- `python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/*.jsonl`
- `python3 -m analysis.final_v3 traces/final_v3`

All four passed in this repo state.

## Remaining risks and evidence gaps

- The traces still do not measure physical placement, migration, or bandwidth
  across differentiated memory tiers.
- Cached-token cross-checks remain an availability/count-reconciliation gate
  against vLLM counters, not independent semantic-span attribution proof.
- The final report still needs to keep dry-run validation, cached-token
  cross-checks, and real H100 evidence clearly separated.
