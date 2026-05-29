# Final-v3 Project Pass

Date: 2026-05-29

Follow-up note: the consolidated audit and cleanup in
`reviews/03-consolidated-final-v3-audit.md` refine the cached-token gate as an
availability/count-reconciliation check and replace the weak final-v3 figures
flagged below.

## Executive Verdict

The project is now internally coherent enough for the final presentation/report,
provided the claims stay inside the locked final-v3 boundary: six deterministic
H100 vLLM workflow-replay traces plus one auxiliary Nsight Systems compaction
profile. The strongest story is not "we measured physical HBM residency." The
defensible story is:

> Semantic workflow structure changes prompt-token composition, which changes
> analytical KV pressure and reuse. Prefix caching, targeted retrieval, and
> compaction each shift where new KV pressure is paid and which semantic objects
> remain live or reused.

That aligns with `DECISIONS.md`: analytical KV only, deterministic scripted
replays, no autonomous-agent or cross-tier-residency claims.

## Validation Evidence

Commands run during this pass:

```bash
python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl traces/final_v3_nsight/compaction_agent_compaction_on.jsonl
python3 -m validation.synthetic --output /private/tmp/ee392c_synthetic_audit.jsonl
python3 validation/assert_synthetic.py /private/tmp/ee392c_synthetic_audit.jsonl
python3 -m analysis.final_v3 traces/final_v3 /private/tmp/final_v3_analysis_audit /private/tmp/final_v3_figures_audit
```

Results:

- All six core traces pass `validation.validate_final_v3`.
- The auxiliary Nsight trace also passes `validation.validate_final_v3`.
- The synthetic tracer oracle passes, including v3 semantic/span checks.
- Re-running `analysis.final_v3` into `/private/tmp` reproduces all six checked
  CSV files byte-for-byte.
- Final-v3 traces are real RunPod H100 runs: every trace has `dry_run=false`.
- All 28 engine cross-check rows have `cross_check_status=passed`; none are
  `unavailable`.

Nsight artifact check:

- `analysis_out/final_v3/nsight_compaction_on.nsys-rep` exists.
- SQLite export contains 10 NVTX events: 5 `prompt_build`, 5 `vllm_generate`.
- SQLite export contains 28,627 CUDA kernel events, 126,752 CUDA runtime events,
  and 5,533,786 OS runtime events.

## Architecture Map

The current final-v3 path is clean:

1. `agent/run_final_v3.py` defines exactly six traces:
   `coding_agent` cache on/off, `search_agent` targeted/broad, and
   `compaction_agent` compaction on/off.
2. `SemanticWorkflowReplay` creates text/token objects, builds prompt spans,
   emits analytical KV spans, attributes cached-prefix reads, and writes a vLLM
   cached-token cross-check for each generation step.
3. `validation/validate_final_v3.py` checks schema version, base fields,
   contiguous prompt spans, cached-token count reconciliation, KV byte sizing,
   and mutate logical-ID changes.
4. `analysis/final_v3.py` turns traces into semantic byte-seconds, KV pressure,
   duplication/amplification, retrieval funnel, compaction funnel, cached-token
   cross-check CSVs, and figures.
5. `serving/telemetry.py` adds auxiliary NVML/RSS samples and NVTX ranges.
6. `serving/nsight_final_v3.sh` profiles the existing compaction-on trace, not a
   new workload.

Historical `agent/tools.py` and `agent/graph.py` are still stubs. That is not a
final-v3 blocker because the final-v3 artifact uses deterministic replay, but it
means the report must not imply the LangGraph autonomous agent path is live.

## Data Readout

### Trace-level prompt pressure

| Trace | Steps | Prompt tokens total | Max prompt tokens | Cached fraction |
|---|---:|---:|---:|---:|
| `coding_agent_cache_off` | 5 | 1,571 | 533 | 0.000 |
| `coding_agent_cache_on` | 5 | 1,590 | 548 | 0.845 |
| `search_agent_targeted` | 4 | 2,957 | 1,347 | 0.871 |
| `search_agent_broad` | 4 | 4,048 | 1,784 | 0.798 |
| `compaction_agent_compaction_on` | 5 | 12,364 | 3,878 | 0.536 |
| `compaction_agent_compaction_off` | 5 | 22,234 | 6,335 | 0.783 |

Compaction has the clearest prompt-length systems story: compaction-on cuts
total prompt tokens by 44.4% and max prompt tokens by 38.8% versus
compaction-off.

### KV pressure totals

| Pair | Condition | Logical KV bytes | Cache-adjusted new KV bytes |
|---|---|---:|---:|
| Coding | cache off | 90,087,424 | 90,087,424 |
| Coding | cache on | 91,176,960 | 14,106,624 |
| Search | targeted | 169,566,208 | 21,848,064 |
| Search | broad | 232,128,512 | 46,792,704 |
| Compaction | compaction on | 709,001,216 | 329,154,560 |
| Compaction | compaction off | 1,274,986,496 | 276,742,144 |

Key interpretation:

- Prefix caching is strongly validated in the coding pair: cache-on reduces
  cache-adjusted new KV by 84.3% versus cache-off.
- Broad search creates 36.9% more total logical KV than targeted search and
  2.14x more cache-adjusted new KV.
- Compaction-on reduces total logical KV by 44.4% versus compaction-off, but
  cache-adjusted new KV is higher overall because compaction breaks the long
  prefix and forces more non-prefix recomputation after the summary insertion.
  The compaction benefit is therefore reduced carried context and lower repeated
  raw-context pressure, not universally lower new-KV cost.

### Search mechanism

The search contrast is not about scan volume. Both traces scan the same expanded
corpus: 88,372 bytes. The effect is what gets returned and inserted into prompt
history:

- Broad returns 2,318 bytes; targeted returns 691 bytes: broad is 3.35x larger.
- Broad inserts 672 selected-snippet bytes; targeted inserts 350 bytes: broad is
  1.92x larger.
- Broad `search_result` logical KV is 75,292,672 bytes; targeted is 23,396,352
  bytes: broad is 3.22x larger.
- Broad `retrieved_snippet` logical KV is 22,249,472 bytes; targeted is
  11,583,488 bytes: broad is 1.92x larger.

So the correct claim is: targeted retrieval reduces prompt pollution after the
same corpus scan, not that it scans less data.

### Compaction mechanism

Both compaction traces ingest the same 18,602 raw-context bytes. Compaction-on
adds a 513-byte summary, a 36.3x compression ratio relative to raw context, and
that summary is read 8 times.

Measured effect:

- Raw-context byte-seconds fall from 2.810B to 1.196B: 57.4% lower.
- Raw-context logical KV falls from 1.032B to 443.2M bytes: 57.1% lower.
- Raw-context read events fall from 30 to 12.
- Raw-context cache-adjusted new KV is identical at 269.3M bytes in both
  conditions, because each newly ingested raw chunk still must be prefetched once.

The defensible phrasing is: compaction reduces retained/repeated raw-context
pressure, while preserving a small summary that remains reusable.

## Hypothesis Alignment

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Workflow shape changes semantic lifetime/reuse/KV pressure. | Supported. | Compaction and search pairs show large semantic-type-specific shifts in prompt tokens, KV bytes, and byte-seconds. |
| Prefix caching materially changes new KV pressure. | Strongly supported. | Coding cache-on has 84.5% cached prompt-token fraction and 84.3% lower cache-adjusted new KV than cache-off. |
| Targeted retrieval reduces memory pressure. | Supported with precise wording. | Returned/inserted prompt content and search-result KV drop sharply; scanned bytes do not. |
| Compaction reduces long-context pressure. | Supported with nuance. | Retained raw-context pressure and total prompt tokens drop; cache-adjusted new KV does not monotonically drop. |
| Semantic attribution can support tier-mapping recommendations. | Supported as prescriptive characterization only. | v3 spans map semantic objects to token/KV pressure, but physical HBM residency and migration are not measured. |

## Report-facing Insights

Use these as the main final-v3 findings:

1. Prefix caching changes the memory cost of repeated coding context from mostly
   new KV to mostly cached-prefix reuse.
2. Retrieval quality matters as a memory-system property: broad search pollutes
   prompt history with larger returned/result spans even when corpus scan volume
   is unchanged.
3. Compaction is a semantic lifetime transform: it frees raw log context and
   replaces it with a small reusable summary, cutting total prompt-token and
   raw-context KV pressure.
4. The same semantic role is not enough for placement. `raw_context`,
   `search_result`, `retrieved_snippet`, `assistant_history`, and stable prompt
   scaffolding have different reuse and capacity profiles across workflows.
5. KV/text amplification is enormous for prompt-resident objects. In the v3
   duplication CSV, many semantic classes have KV/text amplification in the
   7,000x to 20,000x range. Treat this as analytical KV amplification, not
   measured physical duplication.

## Risks And Required Cleanup

### 1. Current final-v3 figures understate the actual pairwise effects

`analysis/final_v3.py` plots `search_scanned_bytes`, but scanned bytes are equal
for targeted and broad search. It also plots `compaction_raw_context`, but raw
input bytes are equal for compaction-on and compaction-off. Those figures are
technically correct but report-weak because they visualize constants.

Better final figures:

- Search: returned bytes, inserted bytes, `search_result` logical KV, or
  `retrieved_snippet` logical KV by targeted/broad.
- Compaction: total prompt tokens, max prompt tokens, raw-context logical KV,
  raw-context byte-seconds, or summary compression/read reuse.
- Coding: cache-adjusted new KV for cache-on/off.

### 2. Step-normalized lifetime is promised but not emitted

`DECISIONS.md` says to report both wall-clock seconds and step-count-normalized
lifetime. `analysis/final_v3.py` currently reports wall-clock byte-seconds and
read counts, but no step-normalized lifetime/byte-step output. This matters
because wall-clock byte-seconds can move with model generation time and system
noise, not just workflow memory shape.

Before the report, either add a step-normalized CSV/figure or explicitly revise
the decision. The cleaner path is to add byte-steps or lifetime-steps per
semantic type.

### 3. DECISIONS.md has one stale cross-check phrase

The current implementation cross-checks tracer-attributed cached prefix tokens
against vLLM request output fields such as `request_output.num_cached_tokens`.
`DECISIONS.md` still says the analytical estimate is cross-checked against
`/metrics` `gpu_cache_usage_perc`. That should be updated before the report so
the locked decision matches the actual validator.

### 4. System telemetry is a health artifact, not a result

Peak NVML GPU memory is essentially flat at about 74.35 GB across traces, which
mostly reflects vLLM reservation behavior on H100. Do not use system telemetry
to claim per-workload physical memory differences. Use it to say the runs were
real GPU runs and to provide coarse runtime/resource context.

### 5. README still leads with historical v2 figures

The README labels v2 findings as historical, but the "Headline findings" section
still visually leads with the old v2 figures. For the final deck/report, lead
with final-v3 H100 figures and demote v2 to background/method-history.

## Claim Boundaries

Safe:

- "Six deterministic workflow-replay traces were collected on RunPod H100 with
  vLLM 0.10.2 and Qwen2.5-Coder-7B-Instruct."
- "All final-v3 cached-token count-reconciliation checks passed."
- "We attribute semantic objects to prompt token spans and analytical KV
  pressure."
- "Compaction reduces retained raw-context pressure; targeted retrieval reduces
  prompt-inserted search content; prefix caching reduces new KV pressure."
- "Tier mapping is prescriptive from measured semantic lifetime/reuse and
  analytical KV pressure."

Unsafe:

- "We measured physical HBM residency by semantic class."
- "We measured bandwidth, SRAM/L1/L2 behavior, or cross-tier migration."
- "The results generalize statistically across agent workloads."
- "The system is an autonomous production-agent benchmark."
- "The Nsight run is a seventh workload or a quantitative condition."

## Bottom Line

The project now has a defensible final-v3 core. The best report should be
mechanistic and narrow: three paired workflow contrasts, validated cached-token
attribution, semantic token/KV pressure, and a prescriptive memory-tier argument.
The remaining work is mostly presentation hygiene: replace two weak final-v3
figures, add or explicitly waive step-normalized lifetime, fix the stale
`/metrics` wording in `DECISIONS.md`, and keep v2 material clearly historical.
