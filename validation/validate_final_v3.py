"""Validate final-v3 semantic traces.

Checks:
  - v2 base fields still exist
  - v3 token spans are ordered and length-matched per prompt step
  - every prompt-construction step carries an engine_cross_check event
  - cached-token attribution is exact or within one KV block
  - KV byte counts match token_count * kv_bytes_per_token
  - mutate creates a new logical version for the same object_id
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BASE_FIELDS = {
    "schema_version",
    "ts",
    "step",
    "phase",
    "object_id",
    "logical_id",
    "repr_type",
    "size_bytes",
    "op",
}

EXPECTED_SCHEMA_VERSION = 3
QWEN25_CODER_7B_BF16_KV_BYTES = 57344


def load_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def validate_base_fields(path: Path, events: list[dict]) -> list[str]:
    errors = []
    for line_no, event in enumerate(events, 1):
        missing = sorted(BASE_FIELDS - set(event))
        if missing:
            errors.append(f"{path}:{line_no}: missing base fields {missing}")
    return errors


def validate_schema_version(path: Path, events: list[dict]) -> list[str]:
    errors = []
    for line_no, event in enumerate(events, 1):
        if event.get("schema_version") != EXPECTED_SCHEMA_VERSION:
            errors.append(
                f"{path}:{line_no}: schema_version={event.get('schema_version')!r}, "
                f"expected {EXPECTED_SCHEMA_VERSION}"
            )
    return errors


def validate_spans(path: Path, events: list[dict]) -> list[str]:
    errors = []
    by_step = defaultdict(list)
    prompt_counts = {}
    for event in events:
        if event.get("semantic_type") == "engine_cross_check":
            prompt_counts[event["step"]] = event.get("prompt_token_count")
        if event.get("repr_type") == "kv_estimated" and event.get("op") == "create":
            if "token_offset_start" in event:
                by_step[event["step"]].append(event)

    for step, spans in by_step.items():
        spans.sort(key=lambda e: e["token_offset_start"])
        expected_start = 0
        for span in spans:
            start = span["token_offset_start"]
            end = span["token_offset_end"]
            count = span["token_count"]
            if start != expected_start:
                errors.append(f"{path}:step {step}: span gap/overlap at {start}, expected {expected_start}")
            if end < start:
                errors.append(f"{path}:step {step}: negative span {start}->{end}")
            if count != end - start:
                errors.append(f"{path}:step {step}: token_count {count} != {end - start}")
            expected_start = end
        prompt_count = prompt_counts.get(step)
        if prompt_count is not None and expected_start != prompt_count:
            errors.append(f"{path}:step {step}: spans end at {expected_start}, prompt has {prompt_count}")
    return errors


def validate_cached_tokens(path: Path, events: list[dict]) -> list[str]:
    errors = []
    for event in events:
        if event.get("semantic_type") != "engine_cross_check":
            continue
        status = event.get("cross_check_status")
        if status == "unavailable":
            errors.append(
                f"{path}:step {event['step']}: cached-token API unavailable "
                f"(source={event.get('cached_tokens_source')!r})"
            )
            continue
        cached = int(event.get("cached_tokens", 0))
        attributed = int(event.get("cached_span_tokens", 0))
        prompt_count = int(event.get("prompt_token_count", 0))
        block = int(event.get("kv_block_size_tokens", 16))
        if cached > prompt_count:
            errors.append(
                f"{path}:step {event['step']}: cached_tokens={cached} exceeds "
                f"prompt_token_count={prompt_count}"
            )
        if not event.get("cross_check_pass", False) or abs(cached - attributed) > block:
            errors.append(
                f"{path}:step {event['step']}: cached_tokens={cached}, "
                f"cached_span_tokens={attributed}, block={block}, status={status!r}"
            )
    return errors


def validate_cross_check_coverage(path: Path, events: list[dict]) -> list[str]:
    """Require an engine_cross_check event on every prompt-construction step.

    AGENTS.md makes ``cross_check_status="passed"`` a hard gate, but
    ``validate_cached_tokens`` only inspects cross-check events that already
    exist, so a truncated trace with zero cross-check events would pass
    vacuously. We anchor coverage to the per-step KV prompt spans, which are
    emitted independently during prompt construction, and require the two step
    sets to coincide. This catches both a wholly missing gate and a gate that
    silently drops individual generation steps.
    """
    errors = []
    cc_steps = {
        event["step"]
        for event in events
        if event.get("semantic_type") == "engine_cross_check"
    }
    span_steps = {
        event["step"]
        for event in events
        if event.get("repr_type") == "kv_estimated"
        and event.get("op") == "create"
        and "token_offset_start" in event
    }
    if not cc_steps:
        errors.append(f"{path}: no engine_cross_check events; cached-token gate not exercised")
        return errors
    missing = sorted(span_steps - cc_steps)
    if missing:
        errors.append(f"{path}: prompt steps {missing} missing engine_cross_check events")
    extra = sorted(cc_steps - span_steps)
    if extra:
        errors.append(f"{path}: engine_cross_check steps {extra} have no prompt KV spans")
    return errors


def validate_metadata_warnings(path: Path, events: list[dict]) -> list[str]:
    warnings = []
    metadata = next((event for event in events if event.get("semantic_type") == "trace_metadata"), {})
    if metadata.get("dry_run"):
        warnings.append(
            f"{path}: dry_run=true; byte-seconds are tracer-overhead-bound and "
            "must not be used for paper figures or cross-condition claims"
        )
    for event in events:
        if event.get("semantic_type") != "engine_cross_check":
            continue
        if event.get("cross_check_status") == "cache_disabled_unverified":
            warnings.append(
                f"{path}:step {event['step']}: cache disabled but cached-token API "
                "was unavailable, so zero-cache behavior is unverified"
            )
    return warnings


def validate_kv_sizes(path: Path, events: list[dict]) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    kv_values = {
        event.get("kv_bytes_per_token")
        for event in events
        if event.get("kv_bytes_per_token") is not None
    }
    if not kv_values:
        errors.append(f"{path}: no kv_bytes_per_token metadata found")
        return errors, warnings
    if len(kv_values) != 1:
        errors.append(f"{path}: multiple kv_bytes_per_token values {sorted(kv_values)}")
        return errors, warnings
    kv_bytes = int(next(iter(kv_values)))
    if kv_bytes != QWEN25_CODER_7B_BF16_KV_BYTES:
        warnings.append(
            f"{path}: kv_bytes_per_token={kv_bytes}; "
            f"Qwen2.5-Coder-7B bf16 fingerprint is {QWEN25_CODER_7B_BF16_KV_BYTES}"
        )
    for event in events:
        if event.get("repr_type") != "kv_estimated":
            continue
        token_count = event.get("token_count")
        if token_count is None:
            continue
        expected = int(token_count) * kv_bytes
        if event["size_bytes"] != expected:
            errors.append(
                f"{path}:step {event['step']}:{event['object_id']}: "
                f"size_bytes={event['size_bytes']} expected={expected}"
            )
    return errors, warnings


def validate_mutations(path: Path, events: list[dict]) -> list[str]:
    errors = []
    live_logical = {}
    for event in sorted(events, key=lambda e: (e["ts"], e["step"])):
        oid = event["object_id"]
        op = event["op"]
        lid = event["logical_id"]
        if op == "create":
            live_logical[oid] = lid
        elif op == "mutate":
            previous = live_logical.get(oid)
            if previous is not None and previous == lid:
                errors.append(f"{path}: {oid} mutate reused logical_id {lid}")
            live_logical[oid] = lid
        elif op == "free":
            live_logical.pop(oid, None)
    return errors


def validate_trace(path: Path) -> tuple[list[str], list[str]]:
    events = load_events(path)
    errors = []
    warnings = []
    errors.extend(validate_base_fields(path, events))
    errors.extend(validate_schema_version(path, events))
    errors.extend(validate_spans(path, events))
    errors.extend(validate_cached_tokens(path, events))
    errors.extend(validate_cross_check_coverage(path, events))
    warnings.extend(validate_metadata_warnings(path, events))
    kv_errors, kv_warnings = validate_kv_sizes(path, events)
    errors.extend(kv_errors)
    warnings.extend(kv_warnings)
    errors.extend(validate_mutations(path, events))
    return errors, warnings


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python -m validation.validate_final_v3 <trace.jsonl> ...")
        return 1
    all_errors = []
    all_warnings = []
    for raw in argv[1:]:
        path = Path(raw)
        errors, warnings = validate_trace(path)
        all_warnings.extend(warnings)
        if errors:
            all_errors.extend(errors)
            print(f"FAIL {path}: {len(errors)} errors")
        else:
            print(f"PASS {path}")
    for warning in all_warnings:
        print(f"WARN {warning}")
    for error in all_errors:
        print(error)
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
