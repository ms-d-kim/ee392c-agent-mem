# Traces

Checked-in trace artifacts for the historical v2 batch, the official final-v3
H100 workflow-replay sweep, auxiliary system telemetry, and one representative
Nsight Systems replay trace.

## Directory roles

- `batch_v2/` — historical 20-trace background dataset. Useful for appendix
  figures and the logical access-versus-capacity split, but not the primary
  evidence for the final report.
- `final_v3/` — official six-trace H100 dataset for the final artifact:
  `coding_agent`, `search_agent`, and `compaction_agent`, each with one matched
  default trace and one contrast trace.
- `final_v3_system/` — auxiliary system telemetry captured alongside the six
  final-v3 traces.
- `final_v3_nsight/` — one Nsight-profiled compaction replay. This is not a
  seventh workload.

Only `final_v3/` feeds the paper-facing `analysis.final_v3` CSVs and figures.
`final_v3_system/` and `final_v3_nsight/` are supporting artifacts for sanity
checks and timeline context, not extra rows in the six-trace comparison.

## Evidence boundary

- `final_v3/` traces are deterministic scripted workflow replays, not autonomous
  tool-selection runs.
- Cached-token fields support availability/count reconciliation against vLLM
  counters; they do not independently prove semantic-span attribution.
- `kv_estimated` events are analytical prompt-span projections, not measured
  physical HBM occupancy or cross-tier movement.
