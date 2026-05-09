# AGENTS.md — Briefing for AI coding agents

You are working on **EE 392C — Memory Lifetime Characterization of Coding-Agent
Inference**, a Stanford grad course project (Tambe, Spring 2026). The project
measures memory access patterns in an instrumented LangGraph coding agent
running on vLLM, and uses those measurements to argue for a tier-mapping
recommendation onto a differentiated memory system.

**Authors:** Minseok Kim (lead, first pass) and Kristen Guernsey.
This repo is currently in solo first-pass mode; Kristen joins after handoff.

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

- Scaffold + stubs committed.
- No implementation yet.
- vLLM not yet brought up.
- No real traces collected.

---

## Implementation order (do not reorder without asking)

1. `agent/tracer.py` — implement the `Tracer` class against the docstring schema.
2. `serving/telemetry.py` — implement `SystemTelemetry` (NVML + psutil + 1 Hz thread).
3. `agent/tools.py` + `agent/graph.py` — minimal LangGraph 3-tool agent.
4. `validation/synthetic.py` — implement the synthetic test scenario.
5. **Run the synthetic test and verify expected values BEFORE any real trace.**
6. `analysis/load_traces.py` + `lifetime.py` + `duplication.py` — analysis.
7. First real SWE-bench task trace.

Step 5 is the hard gate. Real-trace plots are untrusted until the synthetic
test passes against the values in `validation/synthetic.py::EXPECTED`.

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
- Production-agent context-management (retrieval, summarization, reflection)

**In scope and committed:**
- 3 tools only: `read_file`, `write_file`, `run_tests`
- 15-step hard cap per task
- vLLM V1 + Qwen2.5-Coder-7B-Instruct, prefix caching ON
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
2. State what you did, in one paragraph, in the commit message.
3. Tag the commit message with `[CC]` if you are Claude Code, `[CX]` if Codex,
   so the human can see at a glance who wrote what during ping-pong cycles.
4. Do not push without the human's say-so.

---

## When you're stuck

- The synthetic test is the canonical correctness oracle.
- DECISIONS.md is authoritative — if something seems contradictory, ask.
- Out-of-scope items stay out of scope. Don't reintroduce them.
- If a vLLM/LangGraph API has changed since these stubs were written, prefer
  the current stable API, note the change in the commit message, and don't
  rewrite the schema or decisions to accommodate it.
