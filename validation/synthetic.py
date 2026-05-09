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
    - 2 unique logical_ids (v1 and v2 of data.txt content)
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

The assertion script (TODO) checks the recovered values against the
expected table above. CI-style green/red on tracer correctness.
"""

from __future__ import annotations

from pathlib import Path

# from agent.tracer import Tracer, compute_logical_id


def run_synthetic(output_path: Path) -> None:
    """Hand-built event stream that mimics the scenario above.

    Implementation notes:
    - Don't actually run a model; emit Tracer events directly to simulate
      the agent loop. This isolates tracer correctness from agent/model
      correctness.
    - Use time.sleep(0.01) between phases to make lifetimes nonzero.
    """
    raise NotImplementedError(
        "Emit a hand-crafted event sequence matching the scenario in the "
        "module docstring."
    )


EXPECTED = {
    "n_unique_logical_ids": 2,  # v1 and v2 of data.txt content
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
