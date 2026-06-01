"""Regression checks for validation.validate_final_v3.

This script exercises negative cases that the six real final-v3 traces do not
cover directly, especially the cached-token gate coverage requirement.

Run:
    python -m validation.assert_validate_final_v3
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from validation.validate_final_v3 import validate_trace

SCHEMA_VERSION = 3
KV_BYTES_PER_TOKEN = 57344


def _base_metadata() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts": 0.0,
        "step": 0,
        "phase": "task_setup",
        "object_id": "trace_meta",
        "logical_id": "trace_meta",
        "repr_type": "text",
        "size_bytes": 0,
        "op": "create",
        "semantic_type": "trace_metadata",
        "workload": "test_workload",
        "condition": "test_condition",
        "dry_run": False,
    }


def _kv_span(step: int, prompt_tokens: int, *, ts: float = 0.01) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "step": step,
        "phase": "prefill",
        "object_id": f"kv_prompt_step{step}",
        "logical_id": f"kv_prompt_step{step}",
        "repr_type": "kv_estimated",
        "size_bytes": prompt_tokens * KV_BYTES_PER_TOKEN,
        "op": "create",
        "semantic_type": "assistant_history",
        "source": "test_prompt",
        "token_offset_start": 0,
        "token_offset_end": prompt_tokens,
        "token_count": prompt_tokens,
        "confidence": "high",
        "kv_bytes_per_token": KV_BYTES_PER_TOKEN,
    }


def _cross_check(
    step: int,
    prompt_tokens: int,
    cached_tokens: int,
    *,
    ts: float = 0.02,
    status: str = "passed",
    passed: bool = True,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "step": step,
        "phase": "prefill",
        "object_id": f"engine_cc_step{step}",
        "logical_id": f"engine_cc_step{step}",
        "repr_type": "text",
        "size_bytes": 0,
        "op": "create",
        "semantic_type": "engine_cross_check",
        "prompt_token_count": prompt_tokens,
        "prefix_caching": True,
        "cached_tokens": cached_tokens,
        "cached_tokens_available": True,
        "cached_tokens_source": "request_output.num_cached_tokens",
        "cached_span_tokens": cached_tokens,
        "cached_token_delta": 0,
        "cross_check_status": status,
        "cross_check_pass": passed,
        "kv_block_size_tokens": 16,
        "kv_bytes_per_token": KV_BYTES_PER_TOKEN,
    }


def _write_events(tmpdir: Path, name: str, events: list[dict]) -> Path:
    path = tmpdir / name
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")
    return path


def _expect(name: str, errors: list[str], needle: str) -> bool:
    matched = any(needle in error for error in errors)
    status = "PASS" if matched else "FAIL"
    print(f"{status} {name}: expected error containing {needle!r}")
    if not matched:
        print("  actual errors:", errors)
    return matched


def _expect_clean(name: str, errors: list[str]) -> bool:
    clean = not errors
    status = "PASS" if clean else "FAIL"
    print(f"{status} {name}: errors={errors}")
    return clean


def main() -> int:
    passed = True
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        good = _write_events(
            tmpdir,
            "good.jsonl",
            [_base_metadata(), _kv_span(step=1, prompt_tokens=32), _cross_check(step=1, prompt_tokens=32, cached_tokens=16)],
        )
        passed &= _expect_clean("good_trace_passes", validate_trace(good)[0])

        missing_cross_check = _write_events(
            tmpdir,
            "missing_cross_check.jsonl",
            [_base_metadata(), _kv_span(step=1, prompt_tokens=32)],
        )
        passed &= _expect(
            "missing_cross_check_fails",
            validate_trace(missing_cross_check)[0],
            "no engine_cross_check events",
        )

        missing_step = _write_events(
            tmpdir,
            "missing_step.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=16, ts=0.01),
                _cross_check(step=1, prompt_tokens=16, cached_tokens=0, ts=0.02),
                _kv_span(step=2, prompt_tokens=24, ts=0.03),
            ],
        )
        passed &= _expect(
            "missing_step_cross_check_fails",
            validate_trace(missing_step)[0],
            "prompt steps [2] missing engine_cross_check events",
        )

        cached_too_large = _write_events(
            tmpdir,
            "cached_too_large.jsonl",
            [_base_metadata(), _kv_span(step=1, prompt_tokens=8), _cross_check(step=1, prompt_tokens=8, cached_tokens=9)],
        )
        passed &= _expect(
            "cached_tokens_gt_prompt_fails",
            validate_trace(cached_too_large)[0],
            "cached_tokens=9 exceeds prompt_token_count=8",
        )

        unavailable = _write_events(
            tmpdir,
            "unavailable.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=8),
                _cross_check(step=1, prompt_tokens=8, cached_tokens=0, status="unavailable", passed=False),
            ],
        )
        passed &= _expect(
            "unavailable_status_fails",
            validate_trace(unavailable)[0],
            "cached-token API unavailable",
        )

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
