"""
agent/run_batch.py — single-process matrix runner.

Loads vLLM once per cache mode and runs N agent traces in sequence.
Saves ~60s per trace vs. invoking `python -m agent.run_vllm` separately.

Matrix: TASKS x TEMPS x CACHE_MODES. Edit below to reshape.

Usage:
    python -m agent.run_batch
"""

from __future__ import annotations

import gc
import time
from pathlib import Path

import torch
from transformers import AutoTokenizer
from vllm import LLM

from agent.run_vllm import MODEL_PATH, run_agent

TASKS = ["hello_bug", "recursion_bug"]
TEMPS = [0.0, 0.3, 0.5, 0.7, 1.0]
CACHE_MODES = [True, False]
OUT_DIR = Path("traces/batch_v2")


def run_matrix():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(MODEL_PATH)

    for prefix_caching in CACHE_MODES:
        cache_label = "cache_on" if prefix_caching else "cache_off"
        t0 = time.time()
        print(f"\n========== Loading vLLM (prefix_caching={prefix_caching}) ==========")
        llm = LLM(
            model=MODEL_PATH, dtype="bfloat16", max_model_len=4096,
            gpu_memory_utilization=0.85, enable_prefix_caching=prefix_caching,
        )
        print(f"loaded in {time.time() - t0:.1f}s")

        for task in TASKS:
            task_dir = Path("tasks") / task
            if not task_dir.exists():
                print(f"SKIP {task}: {task_dir} does not exist")
                continue
            for temp in TEMPS:
                out = OUT_DIR / f"{task}_{cache_label}_t{temp:.1f}.jsonl"
                print(f"\n----- {out.name} -----")
                try:
                    run_agent(task_dir=task_dir, out_path=out,
                              prefix_caching=prefix_caching, temperature=temp,
                              llm=llm, tok=tok)
                except Exception as e:
                    print(f"FAILED: {e}")
                    out.with_suffix(".FAILED").write_text(str(e))

        del llm
        gc.collect()
        torch.cuda.empty_cache()

    files = sorted(OUT_DIR.glob("*.jsonl"))
    print(f"\n========== Done: {len(files)} traces ==========")
    for f in files:
        n_events = sum(1 for _ in f.open())
        print(f"  {f.name}: {n_events} events, {f.stat().st_size} B")


if __name__ == "__main__":
    run_matrix()
