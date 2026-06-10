# Locked Technical Decisions

These decisions are locked for the first pass. Revisit only if a downstream
finding forces it. Document any change here with date and reason.

---

## 1. KV instrumentation: ANALYTICAL ONLY (first pass)

**Decision:** Use the analytical estimate, not BlockManager hooks:
```
kv_bytes ≈ 2 × n_layers × n_kv_heads × head_dim × n_tokens × dtype_bytes
```
For Qwen2.5-Coder-7B-Instruct with grouped-query attention:
28 layers × 4 KV heads × 128 head_dim × bfloat16 (2 bytes)
→ kv_bytes ≈ 2 × 28 × 4 × 128 × n_tokens × 2 = 57,344 bytes/token
(~56 KiB/token).

**Why:** vLLM V1 KVCacheManager hook surface is not stable enough for a 5-day
timeline. Block-level events would be nice-to-have but the analytical estimate
captures the same first-order behavior (KV bytes scale linearly with context
length). Final-v3 tiles the engine-reported cached-token count
(`request_output.num_cached_tokens`) over the tracer's contiguous span offsets,
so the recorded `cached_token_delta` is structurally zero whenever the counter
does not exceed the prompt length. The gate therefore verifies counter
availability plus tiling sanity (cached tokens never exceed the
tokenizer-derived prompt length, attribution within one KV block, and — since
2026-06-10 — that the emitted cached-prefix read events sum to the recorded
attribution). It is not an independent count reconciliation, physical KV
residency, or semantic-span ground truth.
*(2026-06-10: wording corrected — the previous text implied two independently
derived counts being reconciled.)*

**Revisit:** if cached-token extraction becomes unavailable, the engine ever
reports more cached tokens than the tokenizer-derived prompt length, or a
later implementation adds stable engine-level KV occupancy metrics.

---

## 2. Lifetime definition: LOGICAL-PRESENCE, TASK-BOUNDED

**Primary definition:**
```
lifetime(obj) = min(t_last_access, t_task_end) - t_first_observation
```
"How long did the system care about this object."

**Sensitivity alternatives** (one supplementary plot in the report):
- **Strict KV-residence lifetime** — block allocation to block free/eviction
- **Prompt-step KV lifetime** — duration a projected KV span remains relevant
  until the next prefill boundary
- **Context-window lifetime** — duration the object remained in the prompt context

**Axes:** report both wall-clock seconds and step-count-normalized lifetime.
Step-count is the more useful cross-task comparison axis.

**Final-v3 convention:** text/token objects use logical presence. Per-step
`kv_estimated` prompt spans are bounded at the next prefill boundary because
they are analytical snapshots of prompt construction, not measured resident
blocks. This avoids presenting task-end-bounded KV byte-seconds as physical
no-eviction occupancy.

---

## 3. Compute: RUNPOD NVIDIA H100 80GB HBM3

**Pod template:** `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
(or closest current equivalent — verify on RunPod template catalog)
**GPU:** NVIDIA H100 80GB HBM3 on-demand
**Persistent volume:** 50GB attached at `/workspace`

**Decision update (2026-05-29):** The official final-v3 dataset and auxiliary
Nsight Systems profile are collected on RunPod H100, not RTX 4090. Do not mix
H100 final-v3 timing/system-telemetry observations with older RTX 4090 planning
language.

**Why H100:** Available RunPod capacity and 80GB HBM headroom reduce bring-up
risk for the final sweep. The project claims remain about semantic lifetime,
reuse, token spans, analytical KV pressure, and prescriptive tier mapping; they
do not depend on H100-specific kernel performance.

**Why not local AMD RX 9060 XT:** ROCm support exists (ROCm 7.0.2+, Oct 2025
for RDNA 4) but adds framework-debugging risk on top of methodology risk.
Local PC is reserved for dev work against hosted APIs and trace analysis only.

---

## 4. Nsight Systems: IN SCOPE (droppable cut #5 only)

**Decision:** Install nsys on the RunPod pod, profile one representative
final-v3 trace/condition, generate one auxiliary timeline figure for the pitch
and report. This is not a seventh final-v3 workload and is not part of the
six-trace quantitative comparison.

**Representative profile:** use an existing compaction replay, preferably
`compaction_agent` / `compaction_on`. Compaction has the strongest systems
story because prompt length changes materially; the Nsight figure can show
whether that corresponds to shorter GPU-active prefill/generate regions.

**Why in scope:** ~half-day cost for one strong figure validating that NVTX
phase boundaries correspond to real kernel activity. Falls naturally into the
same week as the system-telemetry layer.

**Out of scope:** Nsight Compute (per-kernel hardware counters). Multi-day
effort, requires `CAP_SYS_ADMIN` that RunPod containers may not grant, and
answers a different question (kernel-level perf, not memory lifetime).

**Drop trigger:** if nsys install on the chosen pod template fails or requires
permissions we don't have. Per-pre-committed cut #5, this is the first stretch
item to drop.

---

## 5. Pre-committed cuts (in order if behind schedule)

Apply earliest cuts first.

1. ~~BlockManager hooks → analytical KV~~ (already locked above)
2. Drop 1.5B variance check, primary 7B model only
3. Drop multi-task analysis, 1 task in depth
4. Drop cross-representation duplication, text-level only
5. Drop Nsight Systems if RunPod permissions block it

The lightning pitch always presents *something* end-to-end. A complete pitch
on one task beats a half-instrumented pitch on five.

---

## 6. Workload scope: final-v3 scripted workflow replays

**Final-v3 traces:** 3 workload families × 2 contrast traces = 6 traces.
Keep this as the official quantitative dataset. Auxiliary system profiles such
as the one Nsight Systems timeline may profile one of these existing traces,
but must not be counted as an additional final-v3 workload.

**Workload families:**
- `coding_agent`: read/edit/test workflow replay, cache on vs off
- `search_agent`: iterative grep/retrieval replay, targeted vs broad retrieval
- `compaction_agent`: context-growth compaction replay, compaction on vs off

These are deterministic multi-step agent-workflow replays, not autonomous
tool-selection loops. The LLM output is still generated and included in prompt
history, but tool choices are scripted to make memory-shape comparisons
repeatable. Search and compaction use small checked-in seed fixtures expanded
deterministically at runtime so the prompt shape is large enough to exercise the
intended memory behavior without committing bulky generated text.

**Legacy v2 tools:** `read_file`, `write_file`, `run_tests`
**Step cap:** 15 per task
**Statistical scope:** characterization only. There is no within-condition
replication, so do not use bootstrap CIs or significance language.

**Why simple:** memory patterns must be interpretable and repeatable, not
optimized for solve rate. The headline is cross-workload variability of
semantic memory behavior, with mechanisms attached to each observed difference.

---

## 7. JSONL schema: SEE `agent/tracer.py` DOCSTRING

The schema is the contract between the agent code and analysis code. Locked
in `agent/tracer.py`. Any schema change requires bumping a `schema_version`
field and updating `analysis/load_traces.py`.
