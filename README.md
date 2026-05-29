# EE 392C — Memory Lifetime Characterization of LLM Agent-Workflow Replays

**Authors:** Minseok Kim, Kristen Guernsey
**Course:** EE 392C — Differentiated Memory Systems, Stanford Spring 2026 (Professor Tambe)

<p align="center">
  <img src="figures/final_v3/prompt_cache_reuse.png" alt="Final-v3 prompt tokens split into cached reuse and new prefill" width="92%">
  <br>
  <em>Final-v3 H100 traces expose where workflow structure pays new prefill work<br>
  versus reusing cached-prefix KV.</em>
</p>

## What this project is

We characterize memory access patterns in instrumented LLM workflow traces,
with the goal of informing how application-level data classes should map onto a
tiered (differentiated) memory system. The final artifact uses deterministic
multi-step **agent-workflow replays**: coding, search/retrieval, and
context-growth compaction. The headline is cross-workload variability: the same
semantic class can have different lifetime, reuse, token, KV, and duplication
behavior depending on workflow shape.

This is exploratory characterization, not a generalizable benchmark. Findings
are tightly coupled to Qwen2.5-Coder-7B-Instruct + vLLM and a small replay set.
The framing "scripted agent-workflow replays with agent-like prompt/tool
structure" is honest; "autonomous production agents broadly" is overclaiming.

## Stack

- **Final artifact:** `agent/run_final_v3.py`, six deterministic
  agent-workflow replay traces
- **Historical v2 batch:** Minimal ReAct-style harness (`agent/run_vllm.py`)
  with three tools (`read_file`, `write_file`, `run_tests`) and a fenced-JSON
  tool-call protocol
- **Engine:** vLLM 0.10.2 + Qwen2.5-Coder-7B-Instruct
- **Compute:** RunPod NVIDIA H100 80GB HBM3
- **Historical v2 tasks:** 2 hand-crafted fixtures (`hello_bug`, `recursion_bug`) ×
  5 sampling temperatures × 2 cache modes (prefix caching on/off) = 20 traces

## Telemetry — logical layer

JSONL events from the workflow/replay code:

```
{schema_version, ts, step, phase, object_id, logical_id, repr_type, size_bytes, op}
```

Schema v3 is additive over v2 (runtime validation in `agent/tracer.py`). Each
event records one create / read / mutate / free on a logical object across
representations such as text, tokens, and analytically projected KV. v3 can also
carry `semantic_type`, `source`, token-span offsets, token count, and confidence.

What we are **not** tracking: Nsight Compute kernel counters, DRAM bandwidth
aggregates, SRAM/L1/L2 behavior, actual HBM residency, or cross-tier migration.
The tier mapping is *prescriptive* from logical semantic/token/KV observations,
not measured physical placement.

## Headline metrics

1. **Lifetime** — task-bounded logical presence (create → last access)
2. **Reuse count** — accesses after creation
3. **Memory footprint over time** — bytes per category, time series
4. **Byte-seconds** — size × lifetime (capacity-time pressure)
5. **Per-category logical access-vs-capacity split** — logical read events vs byte-seconds
   per category (this is the novel angle vs GainSight: GainSight measures
   activation lifetime within a single forward pass; we measure logical-object
   lifetime across workflow steps)

## Final-v3 H100 findings

The final report should lead with the schema-v3 H100 traces in
`traces/final_v3/`. These six traces are paired workflow contrasts, not
replicates, so the right framing is mechanism-based characterization rather
than statistical generalization.

### 1. Prefix caching turns repeated coding context into cached-prefix reuse

![Prompt-cache reuse](figures/final_v3/prompt_cache_reuse.png)

In the coding replay, cache-on and cache-off have nearly the same total prompt
tokens (1,590 vs 1,571). With prefix caching enabled, vLLM reports 1,344 cached
tokens and only 246 new prefill tokens. Cache-adjusted new KV falls from
90,087,424 B to 14,106,624 B, an 84.3% reduction.

### 2. Targeted retrieval reduces prompt pollution after the same scan

![Search prompt pollution](figures/final_v3/search_prompt_pollution.png)

The targeted and broad search traces scan the same expanded corpus size
(88,372 B). The memory difference comes from what enters prompt history: broad
search returns 2,318 B and inserts 672 B of selected snippets, while targeted
search returns 691 B and inserts 350 B. Broad `search_result` logical KV is
3.22x targeted search.

### 3. Compaction cuts retained raw-context pressure, with a reuse tradeoff

![Compaction raw-context KV](figures/final_v3/compaction_raw_context_kv.png)

Both compaction traces ingest the same 18,602 B of raw log context. Compaction
adds a 513 B summary, demotes earlier raw context, and cuts raw-context logical
KV from 1.032 GB to 443 MB. The tradeoff is visible in cached-prefix reuse:
compaction-on has fewer total prompt tokens than compaction-off (12,364 vs
22,234), but more new prefill tokens (5,740 vs 4,826) because inserting a
summary disrupts the long leading prefix.

## Historical v2 background

The original v2 batch remains useful background, but the final report should use
fresh v3 traces for cross-workload claims. v2 duplication factors are historical
only: v2 assigned KV logical IDs at full-prompt granularity, so cross-representation
duplication is not meaningfully measurable from that batch.

### 1. Two object populations, six orders of magnitude apart in size

![Lifetime vs size scatter](figures/fig1_lifetime_size_scatter.png)

KV-cache blocks (10–50 MB, gray, top cluster) and logical content (10 B–1 KB,
colored, bottom cluster) live in disjoint regions of the size–lifetime plane.
They will never be well-served by a single memory tier.

### 2. KV cache dominates byte-seconds but not bandwidth

![Memory pressure timeline](figures/fig2_memory_pressure_timeline.png)

Across one task (`hello_bug`, cache_on, t=0.0), live KV grows step-wise to
42 MB while live logical content stays under 2 KB. The historical v2 aggregate
CSV reports that KV holds **99.994% of byte-seconds but only 3.3% of logical
read events**; logical content inverts that ratio. This is not a hardware
bandwidth measurement.

### 3. Proposed three-tier mapping

![DMS tier proposal](figures/fig4_dms_tier_proposal.svg)

Anchored to the historical 20-trace v2 dataset. Caveat: tier labels are
prescriptive from logical traces, not measured SRAM/HBM residency.

### 4. Reuse and lifetime are coupled, but by category

![Reuse vs lifetime](figures/fig5_reuse_vs_lifetime.png)

The reuse-lifetime scatter shows that "hot" objects are not always large, and
large objects are not always hot. In memory-system terms: small/high-reuse
state (system prompt, current user/problem text, frequently revisited tool and
assistant snippets) wants high-bandwidth volatile tiers (SRAM/HBM), while
large/lower-reuse KV regions want capacity-oriented tiers (HBM/DDR, and
eventually CXL-attached capacity). This is a placement prescription, not a
measured SRAM/HBM residency result.

### 5. Reuse distribution with time-based lifetime buckets

![Reuse histogram with lifetime composition](figures/fig6_reuse_hist_lifetime_stack.png)

Lifetime buckets used in this figure are: **short** = [0, 1) seconds,
**medium** = [1, 3) seconds, **long** = [3, inf) seconds.

Stacking reuse counts by lifetime bucket makes the retention requirement
explicit: most reused objects are short/medium lived, so low-latency volatile
memory carries the critical path. Longer-lived low-reuse data is a better fit
for larger, cheaper tiers (DDR or emerging NVM such as MRAM/RRAM if endurance
and write-latency constraints are acceptable), where non-volatility and
capacity matter more than peak bandwidth.

### 6. Reuse distribution with conceptual memory classes

![Reuse histogram with memory-class composition](figures/fig7_reuse_hist_memory_class_stack.png)

This view uses the systems-oriented taxonomy directly: short-term = `kv_cache`,
medium-term = `system_prompt` + `user_problem` + `assistant_output` +
`tool_result`, long-term = `file_content`. It is a role-based mapping rather
than a pure time-threshold mapping, and therefore better aligned with
differentiated-tier design choices (bandwidth-critical volatile tiers vs
capacity/retention-oriented tiers).

Model weights are part of the long-term memory conceptually, but are not
represented as per-object JSONL events in the current tracer and therefore do
not appear in this figure.

## Repo layout

```
agent/         Agent code + JSONL tracer + matrix runner
serving/       vLLM launch helpers
validation/    Synthetic-agent test (tracer correctness contract)
analysis/      Trace parsing + per-category breakdown
analysis_out/  Generated summary CSVs
traces/        Historical v2 traces plus final-v3 H100 trace artifacts
figures/       Paper-ready figures + standalone SVGs
tasks/         Task fixtures (hello_bug, recursion_bug)
```

## Status (May 29, 2026)

- Tracer v3 additive schema + final-v3 replay runner: in local implementation
- Final-v3 H100 sweep: six real vLLM traces collected under `traces/final_v3/`
  and passing `validation.validate_final_v3`
- Final-v3 system telemetry: collected under `traces/final_v3_system/`
- Final-v3 analysis CSVs/figures: generated under `analysis_out/final_v3/`
  and `figures/final_v3/`
- Auxiliary Nsight Systems profile: one H100 compaction trace under
  `traces/final_v3_nsight/` with report
  `analysis_out/final_v3/nsight_compaction_on.nsys-rep`
- Historical 20-trace v2 batch + summary CSV + per-category CSV: in repo
- Historical paper-ready v2 figures (`figures/fig1`–`fig7`): in repo
- Optional system telemetry is auxiliary; final claims should not depend on it
- Final presentation + report: W5–W6

## Final v3 artifact path

The final report artifact should use the schema-v3 H100 traces in
`traces/final_v3/`, not the historical `traces/batch_v2/` batch. The v3 path
profiles three structurally distinct scripted agent-workflow replays with two
contrast traces each:

- `coding_agent`: prefix-cache on (matched default) vs off
- `search_agent`: targeted retrieval (matched default) vs broad/noisy retrieval
- `compaction_agent`: compaction on (matched default) vs off

The second trace in each pair is an ablation, not a replicate. Do not report CIs
or significance tests from these six traces. The search and compaction replays
expand small seed fixtures deterministically at runtime so prompt shape is large
enough to stress retrieval/compaction without storing bulky synthetic files.

```
python3 -m agent.run_final_v3 --all --out-dir traces/final_v3 \
  --system-telemetry-dir traces/final_v3_system
python3 -m validation.validate_final_v3 traces/final_v3/*.jsonl
python3 -m analysis.final_v3 traces/final_v3
```

For local validation without vLLM:

```
python3 -m agent.run_final_v3 --all --dry-run --out-dir /tmp/final_v3_dryrun
python3 -m validation.validate_final_v3 /tmp/final_v3_dryrun/*.jsonl
```

Dry-run traces validate schema and attribution plumbing only. Their
byte-seconds are dominated by local tracing overhead and must not be used for
paper figures or cross-condition claims.

Schema v3 is additive: all v2 lifecycle fields remain, and events can also
carry `semantic_type`, `source`, token-span offsets, token count, and confidence.
KV pressure is a GQA-aware analytical projection derived from model config. KV
span byte-seconds are bounded at the next prefill boundary. Cache-adjusted KV
uses vLLM cached-token counters when available and assumes cached prefixes are
contiguous leading spans. This is a cached-token availability and
count-reconciliation check, not independent semantic-attribution ground truth.
Actual physical HBM residency is not claimed.

## Key dates

| Milestone          | Date           |
| ------------------ | -------------- |
| Lightning pitch    | May 13, 2026 (done) |
| Final presentation | June 1–3, 2026 |
| Final report       | June 8, 2026   |

## Anchor papers

- **GainSight** (arXiv 2504.14866) — methodology anchor for data-lifetime
  profiling, applied at activation/within-pass granularity
- **ReCA** — dual-memory framework for agentic systems (motivates the
  long-term/short-term split we map to Tiers 2/3)
- **DualPath** — multi-turn agent memory bottleneck

See `DECISIONS.md` for locked-in technical decisions and `SETUP.md` for the
bring-up runbook.
