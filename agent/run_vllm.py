"""
agent/run_vllm.py

vLLM-backed version of agent/run.py. Same Tracer schema, same prompt, same
tool dispatch — only the inference backend swaps from transformers
.model.generate to vLLM's LLM.generate.

Adds three things beyond run.py:
  1. CLI flag --prefix-caching / --no-prefix-caching → enable_prefix_caching
  2. cuda_mem snapshots before/after each prefill (§11.1 validation hook;
     compensates for the cut BlockManager hooks by giving us a ground-truth
     CUDA memory delta we can compare the analytical KV formula against)
  3. cache_hit events emitted from vLLM's per-request num_cached_tokens
     (defensive: falls back silently if the field isn't present on this
     vLLM version)

Usage (from repo root, on the pod):
  python -m agent.run_vllm --prefix-caching    --out traces/hello_bug_vllm_cache_on.jsonl
  python -m agent.run_vllm --no-prefix-caching --out traces/hello_bug_vllm_cache_off.jsonl
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import torch
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

from agent.tracer import Tracer, compute_logical_id

MAX_STEPS = 15
MODEL_PATH = "/workspace/models/qwen-coder-7b"
TASK_DIR = Path("tasks/hello_bug")

# Qwen2.5-Coder-7B-Instruct (GQA): n_layers=28, n_kv_heads=4, head_dim=128, bf16
# kv_bytes_per_token = 2(K,V) * n_layers * n_kv_heads * head_dim * dtype_bytes
KV_BYTES_PER_TOKEN = 2 * 28 * 4 * 128 * 2  # = 57344 bytes ~= 56 KB/tok

BUGGY_SRC = """def add(a, b):
    return a - b  # bug

def multiply(a, b):
    return a * b
"""

SYSTEM_PROMPT = """You are a coding agent with three tools:
- read_file(path): returns file contents
- write_file(path, content): replaces file contents
- run_tests(): runs pytest, returns stdout+stderr

Respond with EXACTLY one fenced JSON block per turn, like:
~~~json
{"tool": "read_file", "args": {"path": "src/math_utils.py"}}
~~~

When done, respond with:
~~~json
{"tool": "done"}
~~~

One tool per turn. Preserve all existing functions when editing. Be concise."""

TOOL_RE = re.compile(r"(?:```|~~~)(?:json)?\s*(\{.*?\})\s*(?:```|~~~)", re.DOTALL)


def parse_tool_call(text):
    m = TOOL_RE.search(text)
    return json.loads(m.group(1)) if m else None


def read_file(path):
    return (TASK_DIR / path).read_text()


def write_file(path, content):
    (TASK_DIR / path).write_text(content)
    return f"wrote {path} ({len(content)} bytes)"


def run_tests():
    r = subprocess.run(["python3", "-m", "pytest", "tests/", "-x"],
                       cwd=TASK_DIR, capture_output=True, text=True)
    return (r.stdout + r.stderr)[:2000]


def emit_text(tracer, step, phase, label, content, op="create"):
    """Identical to run.py: emit text + tokens with shared logical_id."""
    lid = compute_logical_id(content)
    tracer.emit(step=step, phase=phase, object_id=f"{label}_s{step}",
                logical_id=lid, repr_type="text",
                size_bytes=len(content.encode()), op=op)
    n_tok = max(1, len(content) // 4)
    tracer.emit(step=step, phase=phase, object_id=f"{label}_tok_s{step}",
                logical_id=lid, repr_type="tokens",
                size_bytes=n_tok * 4, op=op)
    return lid


def emit_cuda_mem(tracer, step, phase, when):
    """torch.cuda.memory_allocated() snapshot.

    Each snapshot gets a unique logical_id (it's a measurement, not deduplicable
    content). repr_type='cuda_mem' so the analysis pipeline can filter these
    out of duplication-factor calculations or use them for §11.1 validation."""
    torch.cuda.synchronize()
    mem = torch.cuda.memory_allocated()
    lid = compute_logical_id(f"cuda_mem_{step}_{phase}_{when}")
    tracer.emit(step=step, phase=phase, object_id=f"cuda_mem_{when}_s{step}",
                logical_id=lid, repr_type="cuda_mem",
                size_bytes=mem, op="snapshot")


def emit_cache_hit(tracer, step, cached_tokens, prompt_lid):
    """vLLM cache hit (number of prompt tokens served from prefix cache).

    Shares logical_id with the prompt — these tokens reference the same logical
    content as the prompt, but are accessed (not created), so op='read' and
    repr_type='cache_hit'. Skipped when cached_tokens is None/0."""
    if not cached_tokens:
        return
    tracer.emit(step=step, phase="prefill", object_id=f"cache_hit_s{step}",
                logical_id=prompt_lid, repr_type="cache_hit",
                size_bytes=cached_tokens * KV_BYTES_PER_TOKEN, op="read")


def get_cached_tokens(out):
    """Defensive lookup across vLLM versions. Returns int or None."""
    try:
        if hasattr(out, "num_cached_tokens"):
            return out.num_cached_tokens
        m = getattr(out, "metrics", None)
        if m is not None:
            return getattr(m, "num_cached_tokens", None)
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix-caching", dest="prefix_caching",
                    action="store_true", default=True,
                    help="Enable vLLM prefix caching (default: enabled)")
    ap.add_argument("--no-prefix-caching", dest="prefix_caching",
                    action="store_false",
                    help="Disable vLLM prefix caching")
    ap.add_argument("--out", required=True, type=Path,
                    help="Trace output path, e.g. traces/hello_bug_vllm_cache_on.jsonl")
    args = ap.parse_args()

    # Reset task fixture so the bug is freshly re-introduced for this run
    (TASK_DIR / "src" / "math_utils.py").write_text(BUGGY_SRC)

    print(f"vLLM run: prefix_caching={args.prefix_caching}, out={args.out}")
    print("Loading model...")

    tok = AutoTokenizer.from_pretrained(MODEL_PATH)
    llm = LLM(
        model=MODEL_PATH,
        dtype="bfloat16",
        max_model_len=4096,
        gpu_memory_utilization=0.85,
        enable_prefix_caching=args.prefix_caching,
    )
    sampling = SamplingParams(temperature=0.0, max_tokens=512)
    print("Model loaded.")

    problem = (TASK_DIR / "PROBLEM.md").read_text()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem},
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with Tracer(output_path=str(args.out)) as tracer:
        emit_text(tracer, 0, "setup", "problem", problem)

        for step in range(1, MAX_STEPS + 1):
            prompt_text = tok.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            prompt_lid = emit_text(tracer, step, "prefill", "prompt", prompt_text)

            # CUDA mem snapshot BEFORE prefill (§11.1 validation hook)
            emit_cuda_mem(tracer, step, "prefill", "pre")

            # Inference via vLLM
            outputs = llm.generate([prompt_text], sampling, use_tqdm=False)
            out = outputs[0]
            n_tokens = len(out.prompt_token_ids)
            output = out.outputs[0].text

            # Analytical KV estimate (same formula as run.py — for direct comparability)
            tracer.emit(step=step, phase="prefill", object_id=f"kv_s{step}",
                        logical_id=prompt_lid, repr_type="kv_estimated",
                        size_bytes=n_tokens * KV_BYTES_PER_TOKEN, op="create")

            # CUDA mem snapshot AFTER prefill
            emit_cuda_mem(tracer, step, "prefill", "post")

            # Prefix-cache hit event (silent if vLLM doesn't expose this)
            cached_tokens = get_cached_tokens(out)
            emit_cache_hit(tracer, step, cached_tokens, prompt_lid)

            emit_text(tracer, step, "decode", "model_output", output)
            print(f"\n--- step {step} ---\n{output[:300]}\n")
            if cached_tokens is not None:
                print(f"  (cached_tokens={cached_tokens} / {n_tokens})")

            call = parse_tool_call(output)
            if not call or call.get("tool") == "done":
                print("agent: done")
                break

            tool, tool_args = call.get("tool"), call.get("args", {})
            try:
                if tool == "read_file":    result = read_file(**tool_args)
                elif tool == "write_file": result = write_file(**tool_args)
                elif tool == "run_tests":  result = run_tests()
                else: result = f"unknown tool: {tool}"
            except Exception as e:
                result = f"tool error: {e}"

            emit_text(tracer, step, "tool_exec", f"{tool}_result", result)
            messages.append({"role": "assistant", "content": output})
            messages.append({"role": "user", "content": f"Tool result:\n{result[:1500]}"})
        else:
            print(f"hit max steps ({MAX_STEPS})")

    print(f"trace: {args.out}")


if __name__ == "__main__":
    main()
