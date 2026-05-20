"""
agent/run_vllm.py — vLLM-backed agent runner with full memory-lifecycle
                    event emission (create/read/mutate).

Usage:
    python -m agent.run_vllm --task-dir tasks/hello_bug --prefix-caching \
        --temperature 0.0 --out traces/hello_bug_cache_on_t0.0.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

from agent.tracer import Tracer, compute_logical_id

MAX_STEPS = 15
MODEL_PATH = "/workspace/models/qwen-coder-7b"
KV_BYTES_PER_TOKEN = 2 * 28 * 4 * 128 * 2

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
    """Find first JSON object inside a fenced code block, robust to trailing content."""
    m = re.search(r"(?:```|~~~)(?:json)?\s*(\{[\s\S]*)", text)
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(m.group(1))
        return obj
    except json.JSONDecodeError:
        return None


def _msg_oid_base(step, role, kind):
    return f"msg_step{step}_{role}_{kind}"


def _file_oid(path, repr_type):
    safe = path.replace("/", "_").replace(".", "_")
    return f"file_{safe}_{repr_type}"


def _kv_oid(step):
    return f"kv_prompt_step{step}"


@dataclass
class MessageRecord:
    origin_step: int
    role: str
    kind: str
    content: str
    logical_id: str

    def text_bytes(self):
        return len(self.content.encode("utf-8"))

    def token_bytes(self):
        return max(1, len(self.content) // 4) * 4


def emit_text_and_tokens(tracer, *, step, phase, object_id_base, content, op, logical_id=None):
    lid = logical_id or compute_logical_id(content)
    text_b = len(content.encode("utf-8"))
    tok_b = max(1, len(content) // 4) * 4
    tracer.emit(step=step, phase=phase, object_id=f"{object_id_base}_text",
                logical_id=lid, repr_type="text", size_bytes=text_b, op=op)
    tracer.emit(step=step, phase=phase, object_id=f"{object_id_base}_tokens",
                logical_id=lid, repr_type="tokens", size_bytes=tok_b, op=op)
    return lid


def emit_message_create(tracer, *, step, phase, role, kind, content):
    base = _msg_oid_base(step, role, kind)
    lid = emit_text_and_tokens(tracer, step=step, phase=phase,
                               object_id_base=base, content=content, op="create")
    return MessageRecord(step, role, kind, content, lid)


def emit_message_reads(tracer, *, step, log):
    for rec in log:
        base = _msg_oid_base(rec.origin_step, rec.role, rec.kind)
        tracer.emit(step=step, phase="prefill", object_id=f"{base}_text",
                    logical_id=rec.logical_id, repr_type="text",
                    size_bytes=rec.text_bytes(), op="read")
        tracer.emit(step=step, phase="prefill", object_id=f"{base}_tokens",
                    logical_id=rec.logical_id, repr_type="tokens",
                    size_bytes=rec.token_bytes(), op="read")


def emit_file_event(tracer, *, step, phase, path, content, op):
    lid = compute_logical_id(content)
    text_b = len(content.encode("utf-8"))
    tok_b = max(1, len(content) // 4) * 4
    tracer.emit(step=step, phase=phase, object_id=_file_oid(path, "text"),
                logical_id=lid, repr_type="text", size_bytes=text_b, op=op)
    tracer.emit(step=step, phase=phase, object_id=_file_oid(path, "tokens"),
                logical_id=lid, repr_type="tokens", size_bytes=tok_b, op=op)
    return lid


def emit_kv_create(tracer, *, step, logical_id, n_tokens):
    tracer.emit(step=step, phase="prefill", object_id=_kv_oid(step),
                logical_id=logical_id, repr_type="kv_estimated",
                size_bytes=n_tokens * KV_BYTES_PER_TOKEN, op="create")


def emit_kv_cache_hit(tracer, *, step, cached_tokens, prev_step, prev_logical_id):
    """vLLM served cached_tokens from cache => READ of prior step's prompt KV."""
    tracer.emit(step=step, phase="prefill", object_id=_kv_oid(prev_step),
                logical_id=prev_logical_id, repr_type="kv_estimated",
                size_bytes=cached_tokens * KV_BYTES_PER_TOKEN, op="read")


def reset_task_fixture(task_dir):
    fixture_py = task_dir / "fixture.py"
    if fixture_py.exists():
        ns = {"__file__": str(fixture_py)}
        exec(compile(fixture_py.read_text(), str(fixture_py), "exec"), ns)
        ns["reset"](task_dir)
        return
    src = task_dir / "src" / "math_utils.py"
    if src.exists():
        src.write_text(
            "def add(a, b):\n    return a - b  # bug\n\n"
            "def multiply(a, b):\n    return a * b\n"
        )


def get_cached_tokens(out):
    try:
        if hasattr(out, "num_cached_tokens"):
            return out.num_cached_tokens
        m = getattr(out, "metrics", None)
        if m is not None:
            return getattr(m, "num_cached_tokens", None)
    except Exception:
        pass
    return None


def run_agent(*, task_dir, out_path, prefix_caching, temperature, llm=None, tok=None):
    reset_task_fixture(task_dir)
    if llm is None:
        tok = AutoTokenizer.from_pretrained(MODEL_PATH)
        llm = LLM(model=MODEL_PATH, dtype="bfloat16", max_model_len=4096,
                  gpu_memory_utilization=0.85, enable_prefix_caching=prefix_caching)
    sampling = SamplingParams(temperature=temperature, max_tokens=512, seed=42)

    problem = (task_dir / "PROBLEM.md").read_text()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem},
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Tracer(out_path) as tracer:
        log = []
        log.append(emit_message_create(tracer, step=0, phase="task_setup",
                                       role="system", kind="main", content=SYSTEM_PROMPT))
        log.append(emit_message_create(tracer, step=0, phase="task_setup",
                                       role="user", kind="problem", content=problem))
        files_seen = {}
        prev_kv = None

        for step in range(1, MAX_STEPS + 1):
            emit_message_reads(tracer, step=step, log=log)
            prompt_text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            prompt_token_ids = tok(prompt_text)["input_ids"]
            n_tokens = len(prompt_token_ids)
            prompt_lid = compute_logical_id(prompt_text)
            emit_kv_create(tracer, step=step, logical_id=prompt_lid, n_tokens=n_tokens)

            outputs = llm.generate([prompt_text], sampling, use_tqdm=False)
            out = outputs[0]
            output = out.outputs[0].text

            cached_tokens = get_cached_tokens(out)
            if cached_tokens and prev_kv is not None:
                prev_step, prev_lid = prev_kv
                emit_kv_cache_hit(tracer, step=step, cached_tokens=cached_tokens,
                                  prev_step=prev_step, prev_logical_id=prev_lid)
            prev_kv = (step, prompt_lid)

            log.append(emit_message_create(tracer, step=step, phase="decode",
                                           role="assistant", kind="main", content=output))
            messages.append({"role": "assistant", "content": output})

            print(f"\n--- step {step} ---\n{output[:300]}\n")
            if cached_tokens is not None:
                print(f"  (cached_tokens={cached_tokens} / {n_tokens})")

            call = parse_tool_call(output)
            if not call or call.get("tool") == "done":
                print("agent: done")
                break

            tool, tool_args = call.get("tool"), call.get("args", {})
            try:
                if tool == "read_file":
                    path = tool_args.get("path", "")
                    content = (task_dir / path).read_text()
                    op = "read" if path in files_seen else "create"
                    files_seen[path] = emit_file_event(tracer, step=step,
                        phase="tool_exec", path=path, content=content, op=op)
                    result = content
                elif tool == "write_file":
                    path = tool_args.get("path", "")
                    content = tool_args.get("content", "")
                    full = task_dir / path
                    full.parent.mkdir(parents=True, exist_ok=True)
                    full.write_text(content)
                    op = "mutate" if path in files_seen else "create"
                    files_seen[path] = emit_file_event(tracer, step=step,
                        phase="tool_exec", path=path, content=content, op=op)
                    result = f"wrote {path} ({len(content)} bytes)"
                elif tool == "run_tests":
                    r = subprocess.run(["python3", "-m", "pytest", "tests/", "-x"],
                                       cwd=task_dir, capture_output=True, text=True, timeout=30)
                    result = (r.stdout + r.stderr)[:2000]
                else:
                    result = f"unknown tool: {tool}"
            except Exception as e:
                result = f"tool error: {e}"

            log.append(emit_message_create(tracer, step=step, phase="tool_exec",
                                           role="user", kind="tool_result", content=result))
            messages.append({"role": "user", "content": f"Tool result:\n{result[:1500]}"})
        else:
            print(f"hit max steps ({MAX_STEPS})")

    print(f"trace: {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--prefix-caching", dest="prefix_caching", action="store_true", default=True)
    ap.add_argument("--no-prefix-caching", dest="prefix_caching", action="store_false")
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args()
    print(f"vLLM run: task={args.task_dir}, prefix_caching={args.prefix_caching}, "
          f"temperature={args.temperature}, out={args.out}")
    print("Loading model...")
    run_agent(task_dir=args.task_dir, out_path=args.out,
              prefix_caching=args.prefix_caching, temperature=args.temperature)


if __name__ == "__main__":
    main()
