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


def _cached_read(step: int, cached_tokens: int, *, ts: float = 0.015) -> dict:
    """The per-span cached-prefix read event the runner emits alongside a
    cross-check whose cached_tokens is nonzero."""
    return {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "step": step,
        "phase": "prefill",
        "object_id": f"kv_prompt_step{step}",
        "logical_id": f"kv_prompt_step{step}",
        "repr_type": "kv_estimated",
        "size_bytes": cached_tokens * KV_BYTES_PER_TOKEN,
        "op": "read",
        "semantic_type": "assistant_history",
        "source": "vllm_cached_prefix",
        "token_offset_start": 0,
        "token_offset_end": cached_tokens,
        "token_count": cached_tokens,
        "confidence": "medium",
        "kv_bytes_per_token": KV_BYTES_PER_TOKEN,
    }


def _write_events(tmpdir: Path, name: str, events: list[dict]) -> Path:
    path = tmpdir / name
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")
    return path


def _write_raw(tmpdir: Path, name: str, lines: list[str]) -> Path:
    path = tmpdir / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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


def _expect_warning(name: str, warnings: list[str], needle: str) -> bool:
    matched = any(needle in warning for warning in warnings)
    status = "PASS" if matched else "FAIL"
    print(f"{status} {name}: expected warning containing {needle!r}")
    if not matched:
        print("  actual warnings:", warnings)
    return matched


def main() -> int:
    passed = True
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        good = _write_events(
            tmpdir,
            "good.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=32),
                _cached_read(step=1, cached_tokens=16),
                _cross_check(step=1, prompt_tokens=32, cached_tokens=16),
            ],
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

        dropped_read = _write_events(
            tmpdir,
            "dropped_read.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=32),
                _cross_check(step=1, prompt_tokens=32, cached_tokens=16),
            ],
        )
        passed &= _expect(
            "dropped_cached_read_fails",
            validate_trace(dropped_read)[0],
            "cached-prefix read events sum to 0",
        )

        gap_second_span = dict(
            _kv_span(step=1, prompt_tokens=32, ts=0.012),
            object_id="kv_prompt_step1_span1",
            logical_id="kv_prompt_step1_span1",
            token_offset_start=20,
            token_offset_end=32,
            token_count=12,
            size_bytes=12 * KV_BYTES_PER_TOKEN,
        )
        span_gap = _write_events(
            tmpdir,
            "span_gap.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=16),
                gap_second_span,
                _cross_check(step=1, prompt_tokens=32, cached_tokens=0),
            ],
        )
        passed &= _expect(
            "span_gap_fails",
            validate_trace(span_gap)[0],
            "span gap/overlap at 20",
        )

        bad_count = dict(_kv_span(step=1, prompt_tokens=16), token_count=15)
        bad_count["size_bytes"] = 15 * KV_BYTES_PER_TOKEN
        token_count_mismatch = _write_events(
            tmpdir,
            "token_count_mismatch.jsonl",
            [_base_metadata(), bad_count, _cross_check(step=1, prompt_tokens=16, cached_tokens=0)],
        )
        passed &= _expect(
            "token_count_mismatch_fails",
            validate_trace(token_count_mismatch)[0],
            "token_count 15 != 16",
        )

        bad_size = dict(_kv_span(step=1, prompt_tokens=16), size_bytes=15 * KV_BYTES_PER_TOKEN)
        kv_size_mismatch = _write_events(
            tmpdir,
            "kv_size_mismatch.jsonl",
            [_base_metadata(), bad_size, _cross_check(step=1, prompt_tokens=16, cached_tokens=0)],
        )
        passed &= _expect(
            "kv_size_mismatch_fails",
            validate_trace(kv_size_mismatch)[0],
            f"size_bytes={15 * KV_BYTES_PER_TOKEN} expected={16 * KV_BYTES_PER_TOKEN}",
        )

        spans_short = _write_events(
            tmpdir,
            "spans_short.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=16),
                _cross_check(step=1, prompt_tokens=24, cached_tokens=0),
            ],
        )
        passed &= _expect(
            "spans_short_of_prompt_fails",
            validate_trace(spans_short)[0],
            "spans end at 16, prompt has 24",
        )

        no_prompt_count = _cross_check(step=1, prompt_tokens=0, cached_tokens=0)
        del no_prompt_count["prompt_token_count"]
        missing_prompt_count = _write_events(
            tmpdir,
            "missing_prompt_count.jsonl",
            [_base_metadata(), _kv_span(step=1, prompt_tokens=16), no_prompt_count],
        )
        passed &= _expect(
            "missing_prompt_token_count_fails",
            validate_trace(missing_prompt_count)[0],
            "missing or non-integer counters ['prompt_token_count']",
        )

        ts_regression = _write_events(
            tmpdir,
            "ts_regression.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=16, ts=0.05),
                _cross_check(step=1, prompt_tokens=16, cached_tokens=0, ts=0.02),
            ],
        )
        passed &= _expect(
            "ts_regression_fails",
            validate_trace(ts_regression)[0],
            "decreases from",
        )

        stray_free = {
            "schema_version": SCHEMA_VERSION,
            "ts": 0.03,
            "step": 1,
            "phase": "agent_loop",
            "object_id": "never_created",
            "logical_id": "never_created_v1",
            "repr_type": "text",
            "size_bytes": 8,
            "op": "free",
        }
        free_before_create = _write_events(
            tmpdir,
            "free_before_create.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=16),
                _cross_check(step=1, prompt_tokens=16, cached_tokens=0),
                stray_free,
            ],
        )
        passed &= _expect(
            "free_before_create_fails",
            validate_trace(free_before_create)[0],
            "freed before create",
        )

        duplicate_create = dict(_kv_span(step=1, prompt_tokens=16), ts=0.013)
        create_while_live = _write_events(
            tmpdir,
            "create_while_live.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=16),
                duplicate_create,
                _cross_check(step=1, prompt_tokens=16, cached_tokens=0),
            ],
        )
        passed &= _expect(
            "create_while_live_fails",
            validate_trace(create_while_live)[0],
            "created while already live",
        )

        mutate_same_lid = {
            "schema_version": SCHEMA_VERSION,
            "ts": 0.03,
            "step": 1,
            "phase": "tool_exec",
            "object_id": "file_demo_text",
            "logical_id": "file_demo_v1",
            "repr_type": "text",
            "size_bytes": 8,
            "op": "mutate",
        }
        mutate_reuse = _write_events(
            tmpdir,
            "mutate_reuse.jsonl",
            [
                _base_metadata(),
                _kv_span(step=1, prompt_tokens=16),
                _cross_check(step=1, prompt_tokens=16, cached_tokens=0),
                dict(mutate_same_lid, ts=0.025, op="create"),
                mutate_same_lid,
            ],
        )
        passed &= _expect(
            "mutate_reuse_lid_fails",
            validate_trace(mutate_reuse)[0],
            "mutate reused logical_id",
        )

        wrong_version = _write_events(
            tmpdir,
            "wrong_version.jsonl",
            [
                _base_metadata(),
                dict(_kv_span(step=1, prompt_tokens=16), schema_version=2),
                _cross_check(step=1, prompt_tokens=16, cached_tokens=0),
            ],
        )
        passed &= _expect(
            "wrong_schema_version_fails",
            validate_trace(wrong_version)[0],
            "schema_version=2, expected 3",
        )

        invalid_json = _write_raw(
            tmpdir,
            "invalid_json.jsonl",
            [
                json.dumps(_base_metadata()),
                json.dumps(_kv_span(step=1, prompt_tokens=16)),
                '{"schema_version": 3, "ts": 0.02, truncated',
                json.dumps(_cross_check(step=1, prompt_tokens=16, cached_tokens=0)),
            ],
        )
        passed &= _expect(
            "invalid_json_line_fails_cleanly",
            validate_trace(invalid_json)[0],
            "invalid JSON",
        )

        cache_disabled = _cross_check(
            step=1, prompt_tokens=16, cached_tokens=0,
            status="cache_disabled_unverified", passed=False,
        )
        cache_disabled["prefix_caching"] = False
        cache_disabled["cached_tokens_available"] = False
        cache_disabled_trace = _write_events(
            tmpdir,
            "cache_disabled.jsonl",
            [_base_metadata(), _kv_span(step=1, prompt_tokens=16), cache_disabled],
        )
        disabled_errors, disabled_warnings = validate_trace(cache_disabled_trace)
        passed &= _expect_clean("cache_disabled_unverified_is_not_an_error", disabled_errors)
        passed &= _expect_warning(
            "cache_disabled_unverified_warns",
            disabled_warnings,
            "zero-cache behavior is unverified",
        )

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
