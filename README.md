# EE 392C — Memory Lifetime Characterization of Coding-Agent Inference

**Authors:** Minseok Kim, Kristen Guernsey
**Course:** EE 392C — Differentiated Memory Systems, Stanford Spring 2026 (Professor Tambe)

## What this project is

We characterize memory access patterns in a small, instrumented coding-agent
inference workload, with the goal of informing how application-level data
classes should map onto a tiered (differentiated) memory system. The work
measures lifetime, reuse, footprint, and **cross-representation duplication**
of agent state, and proposes a prescriptive tier mapping based on observed
patterns.

This is exploratory characterization, not a generalizable benchmark. Findings
are tightly coupled to our specific configuration (Qwen-Coder + vLLM +
LangGraph) and should be read accordingly.

## Stack

- **Agent:** LangGraph coding agent with 3 tools (`read_file`, `write_file`, `run_tests`)
- **Engine:** vLLM V1 + Qwen2.5-Coder-7B-Instruct (prefix caching ON)
- **Compute:** RunPod RTX 4090 24GB
- **Tasks:** 30–50 SWE-bench-lite-style problems, hard cap 15 steps/task

## Telemetry — four layers

| Layer | What | Cost |
|---|---|---|
| **Logical** | JSONL events from agent code (`{ts, step, phase, object_id, logical_id, repr_type, size_bytes, op}`) | We build it |
| **Engine** | vLLM `/metrics` Prometheus scrape, `usage.cached_tokens`, analytical KV estimate | Free |
| **System** | `nvidia-smi` VRAM, `psutil` RSS, `torch.cuda.memory_*` snapshots, NVTX phase ranges (1 Hz) | ~50 LOC |
| **Timeline** | Nsight Systems kernel/transfer timeline (one figure for pitch/report) | ~half day |

**What we are NOT tracking:** Nsight Compute kernel counters, DRAM bandwidth aggregates,
HBM internals, cross-tier offload dynamics. The tier mapping is *prescriptive*
(argued from logical patterns + published memory-tech specs), not measured.

## Headline metrics

1. **Lifetime** — task-bounded logical-presence; primary definition in DECISIONS.md
2. **Reuse count** — accesses after creation
3. **Memory footprint over time** — bytes per class, time series
4. **Duplication factor** — same logical content as text + tokens + KV simultaneously (the genuinely novel angle vs. GainSight)
5. **Byte-seconds** — size × lifetime

## Repo layout

```
agent/        Agent code + JSONL tracer
serving/      vLLM launch + system telemetry pollers
validation/   Synthetic-agent test (tracer correctness contract)
analysis/     Trace parsing + plotting notebooks
traces/       Output JSONL/Parquet (gitignored)
```

## Status (May 8, 2026)

- Scaffold + decisions committed.
- Bring-up not yet executed. See `SETUP.md` for the runbook.

## Key dates

| Milestone | Date |
|---|---|
| Lightning pitch | May 13, 2026 |
| Final presentation | June 1–3, 2026 |
| Final report | June 8, 2026 |

## Anchor papers

- **GainSight** (arXiv 2504.14866) — methodology anchor (data lifetime profiling)
- **ReCA** — dual-memory framework for agentic systems (motivation)
- **DualPath** — multi-turn agent memory bottleneck (motivation)

See `DECISIONS.md` for locked-in technical decisions and `SETUP.md` for the bring-up runbook.
