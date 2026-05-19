import os, re, json, subprocess
from pathlib import Path
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from agent.tracer import Tracer, compute_logical_id

MAX_STEPS = 15
MODEL_PATH = "/workspace/models/qwen-coder-7b"
TASK_DIR = Path("tasks/hello_bug")
TRACE_OUT = Path("traces/hello_bug_run2.jsonl")

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
    lid = compute_logical_id(content)
    tracer.emit(step=step, phase=phase, object_id=f"{label}_s{step}",
                logical_id=lid, repr_type="text",
                size_bytes=len(content.encode()), op=op)
    n_tok = max(1, len(content) // 4)
    tracer.emit(step=step, phase=phase, object_id=f"{label}_tok_s{step}",
                logical_id=lid, repr_type="tokens",
                size_bytes=n_tok * 4, op=op)
    return lid

def main():
    # Reset task fixture so the bug is freshly re-introduced for this run
    (TASK_DIR / "src" / "math_utils.py").write_text(BUGGY_SRC)

    print("Loading model...")
    tok = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH, torch_dtype=torch.bfloat16, device_map="auto"
    ).eval()
    print(f"Model on {next(model.parameters()).device}")

    problem = (TASK_DIR / "PROBLEM.md").read_text()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem},
    ]
    TRACE_OUT.parent.mkdir(parents=True, exist_ok=True)

    with Tracer(output_path=str(TRACE_OUT)) as tracer:
        emit_text(tracer, 0, "setup", "problem", problem)

        for step in range(1, MAX_STEPS + 1):
            prompt_text = tok.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            prompt_lid = emit_text(tracer, step, "prefill", "prompt", prompt_text)

            inputs = tok(prompt_text, return_tensors="pt").to(model.device)
            n_tokens = inputs.input_ids.shape[1]
            tracer.emit(step=step, phase="prefill", object_id=f"kv_s{step}",
                        logical_id=prompt_lid, repr_type="kv_estimated",
                        size_bytes=n_tokens * KV_BYTES_PER_TOKEN, op="create")

            with torch.no_grad():
                out = model.generate(
                    **inputs, max_new_tokens=512,
                    do_sample=False, pad_token_id=tok.eos_token_id,
                )
            output = tok.decode(out[0][inputs.input_ids.shape[1]:],
                                skip_special_tokens=True)
            emit_text(tracer, step, "decode", "model_output", output)
            print(f"\n--- step {step} ---\n{output[:300]}\n")

            call = parse_tool_call(output)
            if not call or call.get("tool") == "done":
                print("agent: done")
                break

            tool, args = call.get("tool"), call.get("args", {})
            try:
                if tool == "read_file":   result = read_file(**args)
                elif tool == "write_file": result = write_file(**args)
                elif tool == "run_tests":  result = run_tests()
                else: result = f"unknown tool: {tool}"
            except Exception as e:
                result = f"tool error: {e}"

            emit_text(tracer, step, "tool_exec", f"{tool}_result", result)
            messages.append({"role": "assistant", "content": output})
            messages.append({"role": "user", "content": f"Tool result:\n{result[:1500]}"})
        else:
            print(f"hit max steps ({MAX_STEPS})")

    print(f"trace: {TRACE_OUT}")

if __name__ == "__main__":
    main()
