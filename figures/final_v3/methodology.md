# Methodology flowchart — image-model prompt

A redesign brief for `figures/final_v3/methodology.png`. The current matplotlib
render at `figures/final_v3/methodology.png` is a working draft of the layout
described below; a better-typeset version is desired.

---

## Visual style (overall)

- **Academic conference Figure-1 style.** Think NeurIPS / ICML / arXiv method
  figure, not slideware.
- **Clean white background, no gradients, no shadows, no 3-D.**
- Thin **black 1-1.5 px borders** on every box.
- **Muted pastel fills** (blue for input/output, green for process, yellow for
  decision diamonds, light purple for final outputs, very-light-grey for
  right-side reference panels). Saturation low; high contrast for text only.
- Typography: **sans-serif for labels** (Inter / Helvetica / Arial); **monospace
  for code identifiers, schema fields, and CSV filenames** (JetBrains Mono /
  Fira Code / Menlo).
- Faint alternating **horizontal stage bands** behind the main flow (very-pale
  grey, almost invisible) so the 7 stages visually separate without lines.
- Stage labels on the **far left margin** in a column: `STAGE 1`, `STAGE 2`, ...
  with a short subtitle underneath each.
- A **single column of small named boxes** down the centre-left, with all
  detail living in **callout text to their right**. Thin grey connector lines
  (no arrowheads) join each box to its callout.
- **Vertical arrows with arrowheads** flow downward between stages.
- The **far right column** contains 3-4 stacked **reference panels** (light-grey
  filled rectangles) that hold dense reference info — schema, defaults,
  findings, scope. These do not have arrows in or out of them; they are
  reference material.

The reference style we want to match is a stage-numbered pipeline figure with:
- numbered stage rows on the left,
- small boxes labelled by title only,
- all detail text *outside* the boxes (callouts beside them with thin connector
  lines or curly braces),
- yellow diamonds for decision/validation steps with `PASS` / `FAIL` branches,
- right-side sidecar panels for `DEFAULTS` and similar dense tables.

Avoid: text crammed inside boxes, overlapping text, bold colour fills, every
detail living in one giant block.

---

## Canvas

- Aspect ratio **landscape ~1.4 : 1** (e.g. 1550 × 1100 px or 15.5 × 11 in at
  100 dpi).
- Title strip at the top, then 7 stages stacked vertically, then no footer.
- Right ~25% of the canvas is dedicated to reference panels.

---

## Title (top strip, centred)

**Bold title (≈ 15 pt):**
`EE 392C · Logical-layer instrumentation of LLM agent-workflow replays`

**Italic subtitle below (≈ 10 pt, grey):**
`Pipeline from scripted replay through validation, analysis, to prescriptive tier mapping`

---

## Stages (vertical, top → bottom)

For each stage: the **left margin** carries `STAGE N` (bold) and a 1-2 word
subtitle in lighter grey; the **centre column** has the boxes; the
**right of the centre column** has callout text connected by a thin grey line.

### STAGE 1 — Workload Fixtures

Centre: **three small blue-tinted rounded rectangles** side by side, each
showing the workload name in bold and `2 traces` beneath:

- `coding`        · 2 traces
- `search`        · 2 traces
- `compaction`    · 2 traces

Callout (monospace, three lines):
```
tasks/hello_bug         · PROBLEM.md, src/math_utils.py, tests/   (5-step debug loop)
tasks/search_agent      · PROBLEM.md, corpus/*.txt                (4-step grep · max_matches 4 vs 14)
tasks/compaction_agent  · PROBLEM.md, logs/log{1,2,3}.txt          (5-step ingest · summarize+free at s3)
```

### STAGE 2 — Scripted Replay

Centre: **one larger green-tinted rounded rectangle** titled
**`agent/run_final_v3.py`** (bold, monospace), subtitle
`SemanticWorkflowReplay`, and below in italic grey: `× 6 traces, deterministic`.

Callout — labelled header `Methods (per generate step):` then 7 monospace lines:
```
add_message()              create text+tokens objects
read_active_history()      re-read every still-active object
generate()                 vllm.LLM in-process call
emit_kv_spans()            projected KV per message
emit_cached_prefix_reads() vllm RequestOutput.num_cached_tokens
emit_engine_cross_check()  per-step reconciliation
demote_records()           compaction → op=free
```

### STAGE 3 — Instrument (3 streams)

Centre: **three small green-tinted boxes** side by side:

- `tracer.py`     · `schema v3`     · `primary`
- `telemetry.py`  · `NVML 1Hz`      · `auxiliary`
- `Nsight`        · `aux. cut`      · `auxiliary`

Callout — header `Event streams emitted in parallel:` then 5 monospace lines:
```
tracer    → JSONL · append-only, flushed per event
            {ts, step, phase, object_id, logical_id, repr_type,
             size_bytes, op, semantic_type, source,
             token_offset_*, token_count, confidence}
telemetry → JSONL · NVML gpu_mem · psutil rss · torch.cuda
Nsight    → .nsys-rep + .sqlite · CUPTI kernel + memcpy + NVTX
```

### STAGE 4 — Validation Gates

Centre: **two yellow diamonds** side by side, labelled inside:

- diamond 1: `synthetic` / `gate` (bold + sub)
- diamond 2: `final-v3` / `validator`

A small third item to the right of the two diamonds (still in the centre
column): **`assert_validate_final_v3`** as a small yellow rounded rectangle
labelled "failure-mode regression" beneath.

Each diamond has:
- a green **`PASS`** label on its top-right edge with an arrow continuing
  downward into Stage 5;
- a red **`FAIL → fix tracer`** (under diamond 1) / **`FAIL → reject trace`**
  (under diamond 2) label below in small italic.

Callout — header `Hard gates before any real-trace plotting:` then 7 monospace
lines:
```
synthetic                   tracer correctness oracle
                            → 3 logical_ids · v1 reads=3 · v2 reads=0
validate_final_v3           schema · span contiguity
                            size_bytes = tokens × 57,344
                            engine_cross_check per step
                            cached ≤ prompt · status ≠ unavailable
assert_validate_final_v3    failure-mode regression
```

### STAGE 5 — Analysis Modules

Centre: **three small green-tinted boxes** side by side:

- `final_v3.py`   · `primary`     · italic grey: `analysis/`
- `carryover.py`  · `cross-step`  · italic grey: `analysis/ (new)`
- `nsight.py`     · `auxiliary`   · italic grey: `analysis/ (new)`

Callout — header `What each module computes:` then 7 monospace lines:
```
final_v3      lifetime + byte-seconds + reads / semantic class
              kv_pressure (logical / cached / new)
              duplication, search & compaction funnels
              + retention + reuse-interval (Kristen, 2026-06-02)
carryover     KV(step k, origin step o) age-strata decomposition
              → cross-step lifetime (vs GainSight within-pass)
nsight        NVTX timeline · kernel class · memcpy volume
```

### STAGE 6 — Artifacts

Centre: **one purple-tinted rounded rectangle** titled
**`CSVs + figures`** (bold), subtitle (monospace):
`analysis_out/ + figures/`, italic grey: `checked in, deterministic regen`.

Callout — header `Per-trace artifacts (checked into the repo):` then 9
monospace lines (two-column aligned):
```
semantic_summary.csv          byte-seconds & reads / class
kv_pressure.csv               logical / cached / new KV
duplication_factor.csv        text·tokens·KV amplification
prompt_cache_summary.csv      per-trace cache fraction
search_funnel.csv             scan / returned / inserted
compaction_funnel.csv         raw → summary ratio
cached_token_cross_check.csv  per-step engine gate
carryover.csv                 per-step KV age decomposition
nsight_summary.csv            phases + kernel classes
```

### STAGE 7 — Tier Mapping

Centre: **one purple-tinted rounded rectangle** (slightly thicker border)
titled **`Prescriptive tier proposal`** (bold), subtitle (monospace):
`fig4_dms_tier_proposal`, italic grey: `from observation, not placement`.

Callout — header `Mapping derived from observed (size × lifetime, reuse) per class:`
then 3 monospace tier lines:
```
Tier 1   low-latency, resident  · system_prompt, plan_state, summary
Tier 2   bandwidth              · active KV, recent context
Tier 3   cheap capacity         · raw_context, broad search_result
```

Italic grey final line beneath:
`Logical-layer observations · physical placement not measured.`

---

## Right-side reference panels (top → bottom, light-grey filled rectangles)

These are reference material; **no arrows in or out**. Each has a bold ALL-CAPS
header, an italic-grey one-line attribution, then a two-column aligned table.

### Panel 1 — TRACER SCHEMA v3
*`agent/tracer.py · append-only JSONL`*

| field             | type / domain                                |
|-------------------|----------------------------------------------|
| `schema_version`  | `int = 3`                                    |
| `ts`              | `float (time.monotonic)`                     |
| `step`            | `int ≥ 0`                                    |
| `phase`           | `prefill \| decode \| tool_exec \| agent_loop \| task_setup` |
| `object_id`       | `str  (stable per buffer)`                   |
| `logical_id`      | `sha1(normalised content)`                   |
| `repr_type`       | `text \| tokens \| kv_estimated`             |
| `size_bytes`      | `int ≥ 0`                                    |
| `op`              | `create \| read \| mutate \| free`           |
| `semantic_type`   | `str  (system_prompt, ...)`                  |
| `source`          | `str  (read_file, ...)`                      |
| `token_offset_*`  | `int span endpoints`                         |
| `token_count`     | `int = end - start`                          |
| `confidence`      | `high \| medium \| low`                      |

### Panel 2 — DEFAULTS
*`per agent/run_final_v3.py · DECISIONS.md`*

| key                 | value                                       |
|---------------------|---------------------------------------------|
| Model               | `Qwen2.5-Coder-7B-Instruct`                 |
| Engine              | `vLLM 0.10.2 (in-process)`                  |
| Device              | `NVIDIA H100 80GB HBM3`                     |
| Dtype               | `bfloat16`                                  |
| `max_model_len`     | `8192`                                      |
| `max_steps`         | `15 (per task cap)`                         |
| temperature         | `0.0  (deterministic)`                      |
| seed                | `42`                                        |
| `kv_bytes / token`  | `57,344  (GQA-derived: 2·28·4·128·2)`       |
| `kv_block_size`     | `16 tokens`                                 |
| scan expansion      | `search ×30 · compaction ×14`               |
| prefix caching      | `ON by default · OFF only in coding cache_off` |

### Panel 3 — MECHANISM FINDINGS
*`3 paired contrasts · 6 H100 traces`*

| # | finding |
|---|---|
| 1. Coding      | cache_on cuts new KV 84.3 % · cache_off → 0 reuse events |
| 2. Search      | scan identical at 44 KB/step · broad → result KV × 3.22 · broad → +437 prompt tok by s4 |
| 3. Compaction  | raw KV 1.03 GB → 443 MB (2.33×) but new prefill ↑ · long prefix broken at s3 |
| 4. Cross-step  | ≥ 90 % of s5 KV is carried · compaction is the only reset (46 % at s3 vs 99 % elsewhere) |

### Panel 4 — SCOPE

In two short blocks separated by a blank line:

**In scope (green check):**
- logical-layer lifetime + reuse
- analytical KV (model-config derived)
- scripted replay (not autonomous)

**Out of scope (red ✗):**
- HBM residency · SRAM/L1/L2
- DRAM bandwidth · BlockManager
- statistical CIs (n = 1 / condition)

---

## Arrows and connectors

- **Vertical arrows** (1.4 px, dark grey, with arrowheads): one from each
  stage's centre box down to the next stage's centre box. Six total
  (between stages 1-2, 2-3, 3-4, 4-5, 5-6, 6-7).
- **Horizontal connector lines** (0.8 px, light grey, no arrowheads): from the
  right edge of each centre box to the start of its callout text. One per
  stage.
- **PASS arrows** from each Stage-4 diamond: short green-tinted arrow segments
  continuing downward.

---

## Colour palette (suggested hex)

| element                          | fill      | edge      |
|----------------------------------|-----------|-----------|
| input boxes (Stage 1)            | `#D6E4F0` | `#3A6E96` |
| process boxes (Stages 2, 3, 5)   | `#DDEBD6` | `#476B3F` |
| decision diamonds (Stage 4)      | `#F8E08A` | `#A07B12` |
| output boxes (Stages 6, 7)       | `#E3DCEC` | `#5B4882` |
| reference panels (right column)  | `#F7F7F7` | `#6B6B6B` |
| stage bands (background)         | `#F0F0F0` | —         |
| arrows                           | `#222222` | —         |
| body text                        | `#111111` | —         |
| muted/italic text                | `#555555` / `#666666` | — |
| PASS labels                      | `#2A6B2A` | —         |
| FAIL labels                      | `#9C2A2A` | —         |

---

## What to preserve from the current draft

- Stage numbering and order.
- All text labels exactly as written above.
- The callout-beside-box pattern.
- The four right-side reference panels (do not merge into the main flow).
- Yellow diamonds for the validation gates (not boxes).
- Monospace for code identifiers / schema fields / CSV filenames; sans-serif
  for prose labels.

## What can change freely

- Box dimensions and exact placement (pixel-perfect layout welcome).
- Connector line style (curves, right-angle elbows, straight lines all OK).
- Typography choice (any clean sans + clean monospace pair).
- Stage-band visibility (could be removed if the alternating shading hurts
  legibility).
- Decorative element styling (rounded corner radius, border weight, etc.).

---

## Reference draft

The current matplotlib draft at `figures/final_v3/methodology.png` has the
correct overall structure but suffers from cramped callout text and a slightly
heavy SCHEMA panel. The redesign should preserve the structure while improving
typesetting, spacing, and overall polish.
