"""Validate final-v3 semantic traces.

Checks:
  - JSONL lines parse and v2 base fields still exist
  - timestamps are nondecreasing and start near zero
  - v3 token spans are ordered and length-matched per prompt step
  - every prompt-construction step carries an engine_cross_check event
  - cached-token attribution is exact or within one KV block, and the
    cross-check's cached_span_tokens matches the cached-prefix read events
    actually emitted in the trace
  - KV byte counts match token_count * kv_bytes_per_token
  - object lifecycle is legal (create-once-live; mutate/free require a live
    object) and mutate creates a new logical version for the same object_id

``cross_check_status="cache_disabled_unverified"`` is warning-only by policy:
a cache-off trace from an engine without the cached-token API cannot verify
zero-cache behavior, which is a measurement limitation rather than a corrupt
trace.
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


def load_events(path: Path) -> tuple[list[dict], list[str]]:
    """Parse JSONL tolerantly: collect per-line errors instead of crashing.

    A partially written trace (e.g. after a crashed run) must surface as a
    clean ``FAIL <path>: N errors`` line, not an uncaught JSONDecodeError.
    """
    events = []
    errors = []
    for line_no, line in enumerate(path.open(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_no}: invalid JSON: {exc}")
    return events, errors


def validate_timestamps(path: Path, events: list[dict]) -> list[str]:
    """Timestamps are tracer-relative monotonic offsets; enforce both properties.

    Shuffled or negative timestamps would silently corrupt every lifetime and
    byte-seconds figure downstream, so they are gate-fatal.
    """
    errors = []
    previous = None
    for line_no, event in enumerate(events, 1):
        ts = event.get("ts")
        if not isinstance(ts, (int, float)):
            errors.append(f"{path}:{line_no}: non-numeric ts {ts!r}")
            continue
        if previous is not None and ts < previous:
            errors.append(f"{path}:{line_no}: ts {ts} decreases from {previous}")
        previous = ts
    first = next((e.get("ts") for e in events if isinstance(e.get("ts"), (int, float))), None)
    if first is not None and not (0.0 <= first < 1.0):
        errors.append(
            f"{path}: first ts {first} outside [0, 1); tracer timestamps are "
            "relative to Tracer.start()"
        )
    return errors


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
        if status == "cache_disabled_unverified":
            # Warning-only by policy (see module docstring); reported by
            # validate_metadata_warnings. The generic counter checks below
            # would always fail this status because cross_check_pass is False.
            continue
        missing_counters = [
            name
            for name in ("cached_tokens", "cached_span_tokens", "prompt_token_count")
            if not isinstance(event.get(name), int)
        ]
        if missing_counters:
            errors.append(
                f"{path}:step {event['step']}: engine_cross_check missing or "
                f"non-integer counters {missing_counters}"
            )
            continue
        cached = int(event["cached_tokens"])
        attributed = int(event["cached_span_tokens"])
        prompt_count = int(event["prompt_token_count"])
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


def validate_cached_read_attribution(path: Path, events: list[dict]) -> list[str]:
    """Reconcile cross-check counters against the emitted cached-prefix reads.

    ``validate_cached_tokens`` compares two fields of the same
    engine_cross_check event, so a trace whose per-span cached-prefix read
    events (op="read", source="vllm_cached_prefix") were dropped or corrupted
    would still pass. Here we recompute the attributed token count per step
    from those read events and require it to match the cross-check's
    cached_span_tokens exactly.
    """
    errors = []
    read_tokens_by_step = defaultdict(int)
    for event in events:
        if (
            event.get("repr_type") == "kv_estimated"
            and event.get("op") == "read"
            and event.get("source") == "vllm_cached_prefix"
        ):
            read_tokens_by_step[event["step"]] += int(event.get("token_count") or 0)
    for event in events:
        if event.get("semantic_type") != "engine_cross_check":
            continue
        if event.get("cross_check_status") in ("unavailable", "cache_disabled_unverified"):
            continue
        attributed = event.get("cached_span_tokens")
        if not isinstance(attributed, int):
            continue  # reported by validate_cached_tokens
        observed = read_tokens_by_step.get(event["step"], 0)
        if observed != attributed:
            errors.append(
                f"{path}:step {event['step']}: cached-prefix read events sum to "
                f"{observed} tokens but cross-check recorded cached_span_tokens={attributed}"
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


def validate_lifecycle(path: Path, events: list[dict]) -> list[str]:
    """Per-object lifecycle legality plus the mutate-new-logical-version rule.

    create while already live, mutate before create, and free before create
    are all illegal sequences that the synthetic oracle rejects for its own
    trace; enforce the same invariants on real traces.
    """
    errors = []
    live_logical = {}
    for event in sorted(events, key=lambda e: (e["ts"], e["step"])):
        oid = event["object_id"]
        op = event["op"]
        lid = event["logical_id"]
        if op == "create":
            if oid in live_logical:
                errors.append(f"{path}: {oid} created while already live")
            live_logical[oid] = lid
        elif op == "mutate":
            if oid not in live_logical:
                errors.append(f"{path}: {oid} mutated before create")
            elif live_logical[oid] == lid:
                errors.append(f"{path}: {oid} mutate reused logical_id {lid}")
            live_logical[oid] = lid
        elif op == "free":
            if live_logical.pop(oid, None) is None:
                errors.append(f"{path}: {oid} freed before create")
    return errors


def validate_trace(path: Path) -> tuple[list[str], list[str]]:
    events, errors = load_events(path)
    warnings = []
    errors.extend(validate_base_fields(path, events))
    errors.extend(validate_schema_version(path, events))
    errors.extend(validate_timestamps(path, events))
    errors.extend(validate_spans(path, events))
    errors.extend(validate_cached_tokens(path, events))
    errors.extend(validate_cached_read_attribution(path, events))
    errors.extend(validate_cross_check_coverage(path, events))
    warnings.extend(validate_metadata_warnings(path, events))
    kv_errors, kv_warnings = validate_kv_sizes(path, events)
    errors.extend(kv_errors)
    warnings.extend(kv_warnings)
    errors.extend(validate_lifecycle(path, events))
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
