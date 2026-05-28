# Project Summary — for Codex cross-check

> **Superseded by final-v3 implementation work on May 28, 2026.** The current
> build target is 3 scripted agent-workflow replay families × 2 contrast traces
> = 6 traces, not 10 workloads × 3 runs. Block-table/HBM residency, cross-tier
> migration, bootstrap CIs, and autonomous agent-loop claims are not part of the
> final artifact unless a later note explicitly reintroduces them.

**Status:** Updated through conversation of May 24, 2026. Two scope pivots have happened in this conversation that Codex may not have context on — flagged with **[NEW]** where they're new today. Anything labeled **[VERIFY]** is something Claude is uncertain about and wants Codex to push back on.

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

1. **Engine cross-check:** Sum tracer-derived prefix-reusable tokens per request == vLLM's `usage.cached_tokens`. **[NEW]** Promoted from optional to required gate.
2. **Block accounting:** Block table's live block count × block_size × per-token KV bytes ≈ tracer's analytical KV sum per request.

If both pass, the labeling is calibrated against engine ground truth.

---

## 6. Tier mapping: prescriptive, not measured

**[NEW]** Two-path commitment:

- **Path A (primary):** No offload. Measure HBM block-level residence with per-class breakdown. Argue prescriptively from lifetime/reuse/footprint what *should* live in HBM vs DRAM vs NVMe.
- **Path B (stretch):** Enable vLLM native CPU swap on 1–2 workloads. Measure HBM↔DRAM migration. Drop if it costs >1 day. KVBM and LMCache are out — too risky for the remaining timeline. **[VERIFY]** Codex should pressure-test whether Path B is worth attempting at all given the 10-day window.

The methods-boundary statement for the report/slide:

> Measured: KV cache residency at block granularity in HBM, logical-class attribution via app-layer instrumentation cross-validated against engine prefix-cache counters, coarse DRAM via RSS. Not measured: SRAM, activation lifetimes, HBM bandwidth, cross-tier residence absent offload. Tier mapping is prescriptive, derived from measured lifetime/reuse, not measured cross-tier residence.

---

## 7. Implementation state (as of May 24)

From memory, last confirmed status:

- ✅ Cycle 1 (Tracer implementation) — merged to main
- ✅ Cycle 2 (synthetic validation with oracle assertions) — merged to main
- ✅ Append-mode bug fix — landed
- ❌ Cycle 3 (system telemetry, `serving/telemetry.py`) — not committed
- ❌ Agent loop (`agent/tools.py`, `agent/graph.py`) — not committed
- ❓ vLLM bring-up on RunPod — status unknown
- ❌ Token-offset tracking — not yet added (new requirement)
- ❌ Block table snapshot logic — not yet added (new requirement)

**[VERIFY]** Codex should confirm current main against this list. The pivot today doesn't change Cycle 3 or agent-loop requirements — those still need to land before the workload sweep.

---

## 8. Schedule

| Window | Deliverable |
|---|---|
| May 25–26 | Lock 10 workloads with Kristen. Source public datasets. Token-offset + block-table snapshot land. Engine cross-check gate passes on workload #1. |
| May 27–29 | 3 traces per workload = 30 runs. Cross-workload plots. |
| May 30–31 | Analysis, tier mapping argument, presentation deck. |
| Jun 1–3 | Final presentation. |
| Jun 4–8 | Report (5–6 pages, 10pt, 2-col). Artifact submission (repo + trace dataset). |

Hard deadline reminders: presentation Jun 1–3 (~15 min talk); report due Jun 8; artifact due Jun 8.

---

## 9. Open risks

1. **Coder model on non-code workloads.** Validity caveat must be stated up front. Memory characterization is shape-driven, not quality-driven.
2. **Per-workload sample size note is superseded.** The current final-v3 scope
   has one default trace and one ablation per workload family, so use mechanism-
   based characterization only; no bootstrap CIs or significance language.
3. **Setup cost on 10 prompt scaffolds.** New dominant cost. If dataset sourcing slips, cut to 6–7 workloads rather than reduce runs per workload.
4. **vLLM block table API.** V1 internals have churned — block table access path must be verified before promising the snapshot approach. **[VERIFY]**
5. **Tambe Q3 (SRAM/DRAM/HBM physical access) only partially addressed.** SRAM is gone; HBM is measured at block level; DRAM is coarse. Cross-tier residence only via Path B if attempted.
6. **RunPod bring-up status unconfirmed.** Cycle 3 system telemetry not committed yet. Both must clear before the May 27 sweep starts.

---

## 10. Where Codex should push back specifically

- Is the "memory patterns are shape-driven not quality-driven" claim airtight, or does running a coder model on e-commerce introduce subtle KV-pattern artifacts (e.g., tokenizer behavior, special-token frequency) that distort the characterization?
- Is dropping the SWE-bench archetype entirely the right call, given the lightning pitch presented coding-agent results? Is there continuity risk with reviewers?
- Block table snapshot approach vs. BlockManager hooks — is the snapshot path's effort underestimated or the hook path's risk overestimated?
- 30 runs (10 × 3) sufficient for the cross-workload variability claim? Should it be 10 × 5 = 50?
- Path B realism: any chance vLLM CPU swap is actually 1-day work and worth committing to?
- Anything in this summary that contradicts what's actually in the repo / on main right now.
