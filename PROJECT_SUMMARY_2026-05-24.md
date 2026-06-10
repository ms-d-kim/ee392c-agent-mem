# Project Summary — archived planning context

> **Current master-plan update (May 29, 2026):** final-v3 is now the active
> project plan. The official quantitative dataset is the six paired workflow
> traces in `traces/final_v3/`, collected on RunPod NVIDIA H100 80GB HBM3 with
> Qwen2.5-Coder-7B-Instruct + vLLM 0.10.2. All six traces pass
> `validation.validate_final_v3`, and cached-token availability/count
> reconciliation passed on every engine cross-check event. Auxiliary system
> telemetry exists under `traces/final_v3_system/`. The optional Nsight Systems
> artifact is one representative H100 compaction trace/profile, not a seventh
> core workload:
> `traces/final_v3_nsight/compaction_agent_compaction_on.jsonl` and
> `analysis_out/final_v3/nsight_compaction_on.nsys-rep`.
>
> **Hardware update:** replace prior RTX 4090 planning language with H100 for
> final-v3 results. Historical v2 traces/figures remain background only.

> **Superseded by final-v3 implementation work on May 28, 2026.** The current
> build target is 3 scripted agent-workflow replay families × 2 contrast traces
> = 6 traces, not 10 workloads × 3 runs. Block-table/HBM residency, cross-tier
> migration, bootstrap CIs, and autonomous agent-loop claims are not part of the
> final artifact unless a later note explicitly reintroduces them.

**Status:** The sections below are an archived May 24 planning snapshot kept for
audit history. Use the May 29 master-plan update above plus `DECISIONS.md` for
current scope, hardware, validation, and report-facing claims.

---

## 1. Current scope (post-pivot)

**[NEW]** The project is no longer focused on coding-agent characterization. The new framing:

> Workload-conditioned memory lifetime characterization on a fixed LLM deployment. We characterize how memory lifetime, reuse, footprint, and cross-representation duplication vary across 10 production-relevant LLM workload archetypes, all served on the same Qwen2.5-Coder-7B-Instruct + vLLM V1 + LangGraph stack. The contribution is cross-workload variability of memory patterns, not within-workload depth.

**Key reframe:** Memory patterns are driven by *prompt shape and turn structure*, not by model task quality on each workload. So running Qwen-Coder on e-commerce or RAG is methodologically valid for memory characterization, even though task quality will be poor. This caveat must be stated explicitly in the report and framing slide.

**Title needs to change.** "Coding-Agent Inference" no longer fits. Working candidate: *Workload-Conditioned Memory Lifetime Characterization in LLM Inference*. Not finalized.

---

## 2. Workloads (10)

**[SUPERSEDED]** This May-24 sketch replaced previous 30–50 SWE-bench tasks
with one model, but the May-28 final-v3 target is now 3 workload families × 2
contrast traces.

| # | Workload | Shape signature |
|---|---|---|
| 1 | Conversational chatbot | Multi-turn short, monotonic growth, no tools |
| 2 | Customer support agent | Multi-turn with tools, medium context |
| 3 | E-commerce product Q&A | Long shared catalog prefix, short query/answer, prefix-reuse heavy |
| 4 | Enterprise RAG search | Retrieved docs + query, structured answer, shared sys prompt |
| 5 | Long-document summarization | Very long prefill (50k+), medium output |
| 6 | Translation / localization batch | Symmetric in/out, no growth, no reuse, parallel |
| 7 | Video-metadata reasoning agent | Text-proxy: ASR transcript + scene metadata, multi-turn with tools |
| 8 | Structured data extraction | Long input + JSON schema, short structured output, few-shot prefix reuse |
| 9 | Long-form content generation | Short prompt + style guide, very long output |
| 10 | Multi-document research synthesis | Many long inputs, single long output, growing context, occasional tools |

Selection criterion: span the design axes (prefill length, generation length, turn count, tool use, prefix reuse, context growth). Not cherry-picked.

**Prompt scaffolds source from public datasets where possible** (HotpotQA, XSum, FLORES, MMLU, etc.). Specific dataset mapping per workload not yet finalized — **[VERIFY]** with Codex.

---

## 3. Dropped from prior scope

- **Second model (Qwen-Coder-1.5B variance check)** — dropped
- **Explicit comparison to GainSight / DualPath / ReCA** — dropped from analysis. Kept as related work in the report.
- **30–50 SWE-bench tasks** — replaced in the May-24 sketch by 10 workloads ×
  ~3 runs, then superseded on May 28 by 3 workload families × 2 contrast traces
- **SWE-bench coding-agent archetype itself** — dropped (per user direction; Codex may want to flag if it should be retained as one of the 10 for continuity with the lightning pitch story)

---

## 4. Methodology — three measurement layers

### Layer A: Application / agent (Tracer)

JSONL events from Python instrumentation in the agent loop.

**[NEW]** Schema extended with token offsets:

```
{ts, step, phase, object_id, logical_id, repr_type, size_bytes,
 token_offset_start, token_offset_end, op}
```

- `logical_id` = SHA1 of normalized content (identifies cross-representation duplication)
- `repr_type` ∈ {text, tokens, kv_estimated}
- `op` ∈ {create, read, mutate, free}
- Token offsets recorded after tokenization, before vLLM submission

### Layer B: Engine (vLLM)

- `/metrics` Prometheus scrape (~100ms)
- Per-request `usage.cached_tokens`
- **[NEW]** Block table snapshots at every turn boundary — replaces BlockManager hooks as the preferred approach. Read-only, low-effort, gives `request_id → [block_ids]` and `block_id → token_range`. BlockManager hooks remain as fallback but the V1 API has churned during 2025 — risk.

### Layer C: System

- NVML / nvidia-smi at 1 Hz (GPU VRAM)
- psutil RSS at 1 Hz (host memory)
- `torch.cuda.memory_allocated/reserved()` snapshots at phase boundaries
- NVTX ranges for prefill / decode / tool-exec
- Nsight Systems: optional, one timeline figure if RunPod permits

### Not measured (handled via structural formulas)

- Model weights (static, known from config)
- Activations (`≈ batch × seq × hidden × n_layers × dtype`)
- SRAM behavior (would require Nsight Compute — explicitly out of scope)

---

## 5. Attribution: how we label what's what

The chain: `tracer event (logical class)` → `token_offset_start/end` → `block table snapshot` → `block_id` → physical block in HBM.

**Validation gates** (both must pass before scale-up):

1. **Engine cross-check:** Sum tracer-derived prefix-reusable tokens per request == vLLM's `usage.cached_tokens`. **[NEW]** Promoted from optional to required gate. **[SUPERSEDED — see the final-v3 update below; the implemented check is not two independent counts.]**
2. **Block accounting:** Block table's live block count × block_size × per-token KV bytes ≈ tracer's analytical KV sum per request.

Final-v3 update: the implemented gate tiles the engine-reported cached-token
counter over the tracer's contiguous span offsets, so the recorded delta is
structurally zero whenever the counter does not exceed the prompt length. It
verifies counter availability and tiling sanity (plus, since 2026-06-10, that
the emitted cached-prefix read events match the recorded attribution); it is
not independent engine ground truth for semantic-span attribution or physical
KV residency.

---

## 6. Tier mapping: prescriptive, not measured

**[NEW]** Two-path commitment:

- **Path A (primary):** No offload. Measure HBM block-level residence with per-class breakdown. Argue prescriptively from lifetime/reuse/footprint what *should* live in HBM vs DRAM vs NVMe.
- **Path B (stretch):** Enable vLLM native CPU swap on 1–2 workloads. Measure HBM↔DRAM migration. Drop if it costs >1 day. KVBM and LMCache are out — too risky for the remaining timeline. **[VERIFY]** Codex should pressure-test whether Path B is worth attempting at all given the 10-day window.

The methods-boundary statement for the report/slide:

> Measured in final-v3: logical semantic-object lifetime/reuse, prompt token
> spans, analytical KV pressure, and vLLM cached-token count reconciliation.
> Not measured: physical HBM residency by semantic class, SRAM, activation
> lifetimes, HBM bandwidth, or cross-tier residence/offload. Tier mapping is
> prescriptive, derived from semantic lifetime/reuse and analytical KV pressure.

---

## 7. Implementation state

**Current as of May 29, 2026:**

- Tracer v3 with semantic/span metadata is implemented.
- Synthetic tracer correctness gate passes.
- Final-v3 runner emits six deterministic workflow replay traces:
  `coding_agent` cache on/off, `search_agent` targeted/broad, and
  `compaction_agent` compaction on/off.
- The official six-trace final-v3 sweep has been collected on RunPod H100 under
  `traces/final_v3/`.
- `validation.validate_final_v3 traces/final_v3/*.jsonl` passes for all six
  traces.
- Cached-token extraction is no longer `unavailable`: all observed final-v3
  engine cross-check events pass the count-reconciliation gate.
- System telemetry for all six traces exists under `traces/final_v3_system/`.
- Final-v3 analysis outputs exist under `analysis_out/final_v3/` and
  `figures/final_v3/`.
- One auxiliary Nsight Systems compaction profile exists for timeline evidence;
  it is not part of the six-trace quantitative comparison.

---

## 8. Schedule

| Window | Deliverable |
|---|---|
| May 25–28 | Lock final-v3 scope and implement tracer/runner/validation/analysis path. |
| May 29 | H100 six-trace final-v3 sweep, validation, analysis, and auxiliary Nsight profile. |
| May 30–31 | Tighten final-v3 figures, tier-mapping argument, and presentation deck. |
| Jun 1–3 | Final presentation. |
| Jun 4–8 | Report (5–6 pages, 10pt, 2-col). Artifact submission (repo + trace dataset). |

Hard deadline reminders: presentation Jun 1–3 (~15 min talk); report due Jun 8; artifact due Jun 8.

---

## 9. Open risks

1. **Coder model on non-code workloads.** Validity caveat must be stated up front. Memory characterization is shape-driven, not quality-driven.
2. **Per-workload sample size note is superseded.** The current final-v3 scope
   has one default trace and one ablation per workload family, so use mechanism-
   based characterization only; no bootstrap CIs or significance language.
3. **Hardware language drift.** Final-v3 results are H100, not RTX 4090. Slides
   and report text must not retain stale RTX 4090 wording for the final dataset.
4. **Physical-residency overclaim risk.** Final-v3 uses semantic/token-span
   attribution and analytical KV pressure, count-reconciled against vLLM cached
   token counters. Do not claim block-table/HBM residency, independent semantic
   ground truth from vLLM, or cross-tier migration.
5. **Nsight scope risk.** Nsight is auxiliary timeline evidence only. It can
   support phase/kernel-activity intuition, but it is not a seventh workload and
   should not drive the quantitative final-v3 comparison.

---

## 10. Where Codex should push back specifically

- Is the "memory patterns are shape-driven not quality-driven" claim airtight, or does running a coder model on e-commerce introduce subtle KV-pattern artifacts (e.g., tokenizer behavior, special-token frequency) that distort the characterization?
- Is dropping the SWE-bench archetype entirely the right call, given the lightning pitch presented coding-agent results? Is there continuity risk with reviewers?
- Block table snapshot approach vs. BlockManager hooks — is the snapshot path's effort underestimated or the hook path's risk overestimated?
- 30 runs (10 × 3) sufficient for the cross-workload variability claim? Should it be 10 × 5 = 50?
- Path B realism: any chance vLLM CPU swap is actually 1-day work and worth committing to?
- Anything in this summary that contradicts what's actually in the repo / on main right now.
