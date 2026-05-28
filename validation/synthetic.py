"""
Synthetic agent test — the tracer correctness contract.

The tracer MUST recover these expected values when run on this script.
If it doesn't, the tracer is wrong. Fix it before any real trace.

Scenario:
    1. Create a file `data.txt` with content "hello world" (v1)
    2. read_file(data.txt) x 3
    3. write_file(data.txt, "hello world goodbye") -> v2
    4. run_tests() once
    5. Task ends

Expected tracer outputs:
    - 3 unique logical_ids (v1 and v2 of data.txt content + test output)
    - lifetime(v1) ≈ time from first read to mutation (steps 0->3)
    - lifetime(v2) ≈ time from mutation to task_end (steps 3->5)
    - reuse_count(v1) = 3 (three reads)
    - reuse_count(v2) = 0 (mutated then task ended; no subsequent reads)
    - duplication_factor at peak: depends on whether the same content is
      represented as text + tokens + KV simultaneously. With all three:
      ~3.0 ± rounding.

Run:
    python -m validation.synthetic --output traces/synthetic.jsonl

Then assert:
    python -m validation.assert_synthetic traces/synthetic.jsonl

The assertion script checks the recovered values against the expected table
above, including v3 semantic/span fields on KV events.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from agent.tracer import Tracer, compute_logical_id

KV_BYTES_PER_TOKEN = 800
TOKEN_ID_BYTES = 4


def _sizes(content: str) -> tuple[int, int, int, int]:
    """Return (text_bytes, n_tokens, tokens_bytes, kv_bytes) for content.

    n_tokens uses a 4-bytes/token rule of thumb (BPE on UTF-8 English text);
    kv uses an arbitrary nonzero synthetic constant for tracer correctness.
    It is not intended to match a real model's KV-cache footprint.
    """
    text_bytes = len(content.encode("utf-8"))
    n_tokens = max(1, math.ceil(text_bytes / 4))
    return text_bytes, n_tokens, n_tokens * TOKEN_ID_BYTES, n_tokens * KV_BYTES_PER_TOKEN


def run_synthetic(output_path: Path) -> None:
    """Hand-built event stream that mimics the scenario above.

    Implementation notes:
    - Don't actually run a model; emit Tracer events directly to simulate
      the agent loop. This isolates tracer correctness from agent/model
      correctness.
    - Use time.sleep(0.01) between phases to make lifetimes nonzero.
    """
    v1_content = "hello world"
    v2_content = "hello world goodbye"
    test_output_content = "test_output: 1 passed"

    v1_id = compute_logical_id(v1_content)
    v2_id = compute_logical_id(v2_content)
    test_id = compute_logical_id(test_output_content)

    v1_text_b, v1_tokens, v1_tokens_b, v1_kv_b = _sizes(v1_content)
    v2_text_b, v2_tokens, v2_tokens_b, v2_kv_b = _sizes(v2_content)
    t_text_b, t_tokens, t_tokens_b, t_kv_b = _sizes(test_output_content)

    # Stable per-representation object_ids for data.txt: the same physical
    # buffers are read across steps 1-3 and then mutated in step 4.
    OID_DATA_TEXT = "text_msg_data"
    OID_DATA_TOKENS = "tokens_data"
    OID_DATA_KV = "kv_data"

    OID_TEST_TEXT = "text_msg_test_output"
    OID_TEST_TOKENS = "tokens_test_output"
    OID_TEST_KV = "kv_test_output"

    with Tracer(output_path) as t:
        # Step 0 — task_setup: create data.txt v1 in all three live reps.
        t.emit(step=0, phase="task_setup", object_id=OID_DATA_TEXT,
               logical_id=v1_id, repr_type="text",
               size_bytes=v1_text_b, op="create",
               semantic_type="file_content", source="synthetic_setup",
               confidence="high")
        time.sleep(0.01)
        t.emit(step=0, phase="task_setup", object_id=OID_DATA_TOKENS,
               logical_id=v1_id, repr_type="tokens",
               size_bytes=v1_tokens_b, op="create",
               semantic_type="file_content", source="synthetic_setup",
               confidence="high")
        time.sleep(0.01)
        t.emit(step=0, phase="task_setup", object_id=OID_DATA_KV,
               logical_id=v1_id, repr_type="kv_estimated",
               size_bytes=v1_kv_b, op="create",
               semantic_type="file_content", source="synthetic_setup",
               token_offset_start=0, token_offset_end=v1_tokens,
               token_count=v1_tokens, confidence="medium",
               extra={"kv_bytes_per_token": KV_BYTES_PER_TOKEN})
        time.sleep(0.01)

        # Steps 1-3 — tool_exec: read_file(data.txt) three times.
        # Each read touches all three live reps of v1.
        for step in (1, 2, 3):
            t.emit(step=step, phase="tool_exec", object_id=OID_DATA_TEXT,
                   logical_id=v1_id, repr_type="text",
                   size_bytes=v1_text_b, op="read",
                   semantic_type="file_content", source="synthetic_read",
                   confidence="high")
            time.sleep(0.01)
            t.emit(step=step, phase="tool_exec", object_id=OID_DATA_TOKENS,
                   logical_id=v1_id, repr_type="tokens",
                   size_bytes=v1_tokens_b, op="read",
                   semantic_type="file_content", source="synthetic_read",
                   confidence="high")
            time.sleep(0.01)
            t.emit(step=step, phase="tool_exec", object_id=OID_DATA_KV,
                   logical_id=v1_id, repr_type="kv_estimated",
                   size_bytes=v1_kv_b, op="read",
                   semantic_type="file_content", source="synthetic_read",
                   token_offset_start=0, token_offset_end=v1_tokens,
                   token_count=v1_tokens, confidence="medium",
                   extra={"kv_bytes_per_token": KV_BYTES_PER_TOKEN})
            time.sleep(0.01)

        # Step 4 — tool_exec: write_file mutates data.txt v1 -> v2.
        # Same object_ids, new logical_id and new sizes per rep.
        t.emit(step=4, phase="tool_exec", object_id=OID_DATA_TEXT,
               logical_id=v2_id, repr_type="text",
               size_bytes=v2_text_b, op="mutate",
               semantic_type="file_content", source="synthetic_write",
               confidence="high")
        time.sleep(0.01)
        t.emit(step=4, phase="tool_exec", object_id=OID_DATA_TOKENS,
               logical_id=v2_id, repr_type="tokens",
               size_bytes=v2_tokens_b, op="mutate",
               semantic_type="file_content", source="synthetic_write",
               confidence="high")
        time.sleep(0.01)
        t.emit(step=4, phase="tool_exec", object_id=OID_DATA_KV,
               logical_id=v2_id, repr_type="kv_estimated",
               size_bytes=v2_kv_b, op="mutate",
               semantic_type="file_content", source="synthetic_write",
               token_offset_start=0, token_offset_end=v2_tokens,
               token_count=v2_tokens, confidence="medium",
               extra={"kv_bytes_per_token": KV_BYTES_PER_TOKEN})
        time.sleep(0.01)

        # Step 5 — tool_exec: run_tests produces a separate test_output object.
        t.emit(step=5, phase="tool_exec", object_id=OID_TEST_TEXT,
               logical_id=test_id, repr_type="text",
               size_bytes=t_text_b, op="create",
               semantic_type="tool_result", source="synthetic_run_tests",
               confidence="high")
        time.sleep(0.01)
        t.emit(step=5, phase="tool_exec", object_id=OID_TEST_TOKENS,
               logical_id=test_id, repr_type="tokens",
               size_bytes=t_tokens_b, op="create",
               semantic_type="tool_result", source="synthetic_run_tests",
               confidence="high")
        time.sleep(0.01)
        t.emit(step=5, phase="tool_exec", object_id=OID_TEST_KV,
               logical_id=test_id, repr_type="kv_estimated",
               size_bytes=t_kv_b, op="create",
               semantic_type="tool_result", source="synthetic_run_tests",
               token_offset_start=0, token_offset_end=t_tokens,
               token_count=t_tokens, confidence="medium",
               extra={"kv_bytes_per_token": KV_BYTES_PER_TOKEN})


EXPECTED = {
    "n_unique_logical_ids": 3,  # v1 and v2 of data.txt + test_output from run_tests
    "v1_reuse_count": 3,
    "v2_reuse_count": 0,
    "duplication_factor_peak_min": 2.5,  # at least text+tokens+kv ≈ 3
    "duplication_factor_peak_max": 3.5,
}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("traces/synthetic.jsonl"))
    args = ap.parse_args()
    run_synthetic(args.output)
    print(f"Synthetic trace written to {args.output}")
    print("Now run: python -m validation.assert_synthetic", args.output)
