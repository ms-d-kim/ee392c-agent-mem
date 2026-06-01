# AGENTS.md — Briefing for AI coding agents

You are working on **EE 392C — Memory Lifetime Characterization of LLM
Agent-Workflow Replays**, a Stanford grad course project (Tambe, Spring 2026).
The final-v3 artifact measures memory access patterns in deterministic
multi-step workflow replays running on vLLM, and uses those measurements to
argue for a prescriptive tier-mapping recommendation onto a differentiated
memory system.

**Authors:** Minseok Kim and Kristen Guernsey.

**Hard deadlines:**
- Lightning pitch (3 slides): May 13, 2026
- Final presentation: June 1–3, 2026
- Final report: June 8, 2026

---

## Read these files first, in order

1. `README.md` — what the project is, stack, status
2. `DECISIONS.md` — locked technical decisions with rationale (authoritative)
3. `SETUP.md` — bring-up runbook
4. `agent/tracer.py` (docstring) — the JSONL schema contract
5. `validation/synthetic.py` (docstring) — the tracer correctness contract

If anything in your task contradicts these files, **stop and ask**, do not
reinterpret. `DECISIONS.md` is authoritative; `README.md` is summary.

---

## Current status

- Tracer v3, synthetic validation, final-v3 runner, final-v3 analysis, and
  optional system telemetry are implemented locally.
- `validation.assert_validate_final_v3` exists as a local regression check for
  final-v3 validator failure modes that the six checked-in traces do not
  exercise directly.
- Historical v2 traces live under `traces/batch_v2/`; the official final-v3
  H100 traces live under `traces/final_v3/`.
- The final-v3 H100 six-trace sweep has passed
  `validation.validate_final_v3`; auxiliary Nsight output is a representative
  compaction profile, not a seventh core workload.
- The cached-token gate is an availability/count-reconciliation check against
  vLLM request-output counters, not independent semantic-attribution proof.
- The final-v3 workloads are scripted agent-workflow replays, not autonomous
  tool-selection loops.

---

## Implementation order (do not reorder without asking)

1. Preserve the `agent/tracer.py` schema contract.
2. Preserve `validation/synthetic.py` and `validation/assert_synthetic.py` as
   the tracer correctness gate.
3. Use `agent/run_final_v3.py` for final-v3 traces.
4. Use `validation/validate_final_v3.py` before trusting final-v3 traces.
5. Use `analysis/final_v3.py` for final-v3 CSVs/figures.
6. Run one real vLLM trace on RunPod and verify cached-token extraction is not
   `unavailable` before collecting all six final traces.

Steps 2 and 6 are the hard gates. The synthetic test must pass before any
real-trace plot, and the RunPod cached-token cross-check must return
`cross_check_status="passed"` rather than `unavailable` before collecting the
full six-trace sweep.

---

## Hard constraints

**The JSONL schema in `agent/tracer.py` is a contract.** Do not deviate without
bumping `SCHEMA_VERSION` and updating `analysis/load_traces.py`.

**Out of scope — do not add (even if it seems helpful):**
- Nsight Compute / kernel hardware counters
- DRAM bandwidth or HBM channel-level traces
- NVMe access tracing
- LMCache or any cross-tier offload
- BlockManager hooks (analytical KV only — see DECISIONS.md §1)
- Autonomous production-agent control-flow claims; final-v3 replays are
  deterministic even when they include search or compaction structure

**In scope and committed:**
- Final-v3 scope: 3 scripted workflow families × 2 contrast traces = 6 traces
- Historical v2 scope: 3 tools only (`read_file`, `write_file`, `run_tests`)
- 15-step hard cap per task
- RunPod NVIDIA H100 80GB HBM3
- vLLM 0.10.2 + Qwen2.5-Coder-7B-Instruct; prefix caching on for default traces
  with explicit cache-off ablation for the coding replay
- Nsight Systems (nsys) timeline — single figure, droppable cut

---

## Style conventions

- Type hints on public functions
- Module + public-function docstrings
- `time.monotonic()` for time references, not `time.time()`
- Append-only JSONL writes, flush after each event (resilience to crashes)
- One JSON object per line
- Use `pathlib.Path`, not raw strings, for filesystem paths

Don't add a linter config or formatting rules. Match what's already in the file.

---

## When you finish a task

1. Run the synthetic test if you touched the tracer or analysis code.
2. Run `python3 -m validation.assert_validate_final_v3` if you touched
   `validation/validate_final_v3.py` or cached-token gate logic.
3. State what you did, in one paragraph, in the commit message.
4. Do not include tool/vendor authorship tags in commit messages.
5. Do not push without the human's say-so.

---

## When you're stuck

- The synthetic test is the canonical correctness oracle.
- DECISIONS.md is authoritative — if something seems contradictory, ask.
- Out-of-scope items stay out of scope. Don't reintroduce them.
- If a vLLM/LangGraph API has changed since these stubs were written, prefer
  the current stable API, note the change in the commit message, and don't
  rewrite the schema or decisions to accommodate it.
