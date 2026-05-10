"""Assert the synthetic trace contract without using analysis helpers.

Run:
    python -m validation.assert_synthetic traces/synthetic.jsonl
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys

EXPECTED = {
    "n_unique_logical_ids": 3,
    "v1_reuse_count": 3,
    "v2_reuse_count": 0,
    "duplication_factor_peak_min": 2.5,
    "duplication_factor_peak_max": 3.5,
}

V1_CONTENT = "hello world"
V2_CONTENT = "hello world goodbye"
TEST_OUTPUT_CONTENT = "test_output: 1 passed"
SAMPLE_PERIOD_SECONDS = 0.1

REQUIRED_FIELDS = {
    "ts",
    "step",
    "phase",
    "object_id",
    "logical_id",
    "repr_type",
    "size_bytes",
    "op",
}


def _logical_id(content: str) -> str:
    normalized = " ".join(content.lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _load_events(path: str) -> tuple[list[dict], list[str]]:
    events = []
    errors = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"line {line_no}: invalid JSON: {exc}")
                    continue
                missing = sorted(REQUIRED_FIELDS - set(event))
                if missing:
                    errors.append(f"line {line_no}: missing fields {missing}")
                events.append(event)
    except OSError as exc:
        errors.append(str(exc))
    return events, errors


def _steps_for(events: list[dict], logical_id: str, op: str) -> list[int]:
    return sorted(
        {
            event["step"]
            for event in events
            if event.get("logical_id") == logical_id and event.get("op") == op
        }
    )


def _build_intervals(events: list[dict]) -> tuple[list[dict], list[str]]:
    intervals = []
    errors = []
    live_by_object = {}
    task_end = max((event["ts"] for event in events), default=0.0)

    for event in events:
        object_id = event["object_id"]
        op = event["op"]
        ts = event["ts"]

        if op == "create":
            if object_id in live_by_object:
                errors.append(f"{object_id}: create while already live at ts={ts!r}")
            live_by_object[object_id] = event
        elif op == "mutate":
            previous = live_by_object.get(object_id)
            if previous is None:
                errors.append(f"{object_id}: mutate before create at ts={ts!r}")
            else:
                intervals.append(_interval(previous, ts))
            live_by_object[object_id] = event
        elif op == "free":
            previous = live_by_object.pop(object_id, None)
            if previous is None:
                errors.append(f"{object_id}: free before create at ts={ts!r}")
            else:
                intervals.append(_interval(previous, ts))
        elif op == "read":
            continue
        else:
            errors.append(f"{object_id}: unknown op {op!r} at ts={ts!r}")

    for event in live_by_object.values():
        intervals.append(_interval(event, task_end))

    for interval in intervals:
        if interval["end_ts"] < interval["start_ts"]:
            errors.append(
                f"{interval['object_id']}: negative lifetime "
                f"{interval['start_ts']!r}->{interval['end_ts']!r}"
            )

    return intervals, errors


def _interval(event: dict, end_ts: float) -> dict:
    return {
        "object_id": event["object_id"],
        "logical_id": event["logical_id"],
        "repr_type": event["repr_type"],
        "size_bytes": event["size_bytes"],
        "start_ts": event["ts"],
        "end_ts": end_ts,
    }


def _sample_times(events: list[dict], intervals: list[dict]) -> list[float]:
    if not events:
        return [0.0]

    start = min(event["ts"] for event in events)
    end = max(event["ts"] for event in events)
    samples = {start, end}

    ts = start
    while ts <= end:
        samples.add(round(ts, 10))
        ts += SAMPLE_PERIOD_SECONDS

    # The 100 ms grid is the primary sampling rule. Boundary samples make this
    # adversarial for short synthetic phases and avoid hiding mutate/free bugs.
    for interval in intervals:
        samples.add(interval["start_ts"])
        samples.add(interval["end_ts"])

    return sorted(samples)


def _duplication_factor_peak(events: list[dict]) -> tuple[float, list[str]]:
    intervals, errors = _build_intervals(events)
    peak = 0.0

    for ts in _sample_times(events, intervals):
        live = [
            interval
            for interval in intervals
            if interval["start_ts"] <= ts <= interval["end_ts"]
        ]
        total_bytes = sum(interval["size_bytes"] for interval in live)
        sizes_by_logical_id = collections.defaultdict(list)
        for interval in live:
            sizes_by_logical_id[interval["logical_id"]].append(interval["size_bytes"])

        # Synthetic EXPECTED treats text+tokens+KV as roughly three copies even
        # though their byte sizes differ. Use the mean live representative size
        # as one logical copy, then compare physical bytes to logical bytes.
        unique_bytes = sum(
            sum(sizes) / len(sizes) for sizes in sizes_by_logical_id.values()
        )
        if unique_bytes > 0:
            peak = max(peak, total_bytes / unique_bytes)

    return peak, errors


def _timestamps_are_monotonic(events: list[dict]) -> bool:
    return all(
        events[index]["ts"] <= events[index + 1]["ts"]
        for index in range(len(events) - 1)
    )


def _logical_ids_stable_before_mutate(events: list[dict], expected_v1_id: str) -> bool:
    data_events_before_mutate = [
        event
        for event in events
        if event.get("object_id") in {"text_msg_data", "tokens_data", "kv_data"}
        and event.get("step", 0) < 4
    ]
    return bool(data_events_before_mutate) and all(
        event.get("logical_id") == expected_v1_id for event in data_events_before_mutate
    )


def _print_result(name: str, passed: bool, actual, expected) -> bool:
    status = "PASS" if passed else "FAIL"
    print(f"{status} {name}: actual={actual!r} expected={expected!r}")
    return passed


def main(argv: list[str]) -> int:
    """Load a synthetic trace and assert the expected metrics."""
    if len(argv) > 2:
        print("Usage: python -m validation.assert_synthetic [trace.jsonl]")
        return 1

    path = argv[1] if len(argv) == 2 else "traces/synthetic.jsonl"
    events, load_errors = _load_events(path)
    if load_errors:
        for error in load_errors:
            print(f"FAIL load_trace: {error}")
        return 1

    v1_id = _logical_id(V1_CONTENT)
    v2_id = _logical_id(V2_CONTENT)
    test_output_id = _logical_id(TEST_OUTPUT_CONTENT)
    expected_ids = {v1_id, v2_id, test_output_id}
    actual_ids = {event["logical_id"] for event in events}

    v1_read_steps = _steps_for(events, v1_id, "read")
    v2_read_steps = _steps_for(events, v2_id, "read")
    v2_mutate_steps = _steps_for(events, v2_id, "mutate")
    test_create_steps = _steps_for(events, test_output_id, "create")
    duplicate_peak, duplication_errors = _duplication_factor_peak(events)

    checks = [
        _print_result(
            "n_unique_logical_ids",
            len(actual_ids) == EXPECTED["n_unique_logical_ids"],
            len(actual_ids),
            EXPECTED["n_unique_logical_ids"],
        ),
        _print_result(
            "expected_logical_ids_present",
            expected_ids <= actual_ids,
            sorted(actual_ids),
            sorted(expected_ids),
        ),
        _print_result(
            "v1_reuse_count",
            len(v1_read_steps) == EXPECTED["v1_reuse_count"],
            len(v1_read_steps),
            EXPECTED["v1_reuse_count"],
        ),
        _print_result(
            "v1_read_steps",
            v1_read_steps == [1, 2, 3],
            v1_read_steps,
            [1, 2, 3],
        ),
        _print_result(
            "v2_reuse_count",
            len(v2_read_steps) == EXPECTED["v2_reuse_count"],
            len(v2_read_steps),
            EXPECTED["v2_reuse_count"],
        ),
        _print_result(
            "v2_mutate_steps",
            v2_mutate_steps == [4],
            v2_mutate_steps,
            [4],
        ),
        _print_result(
            "test_output_create_steps",
            test_create_steps == [5],
            test_create_steps,
            [5],
        ),
        _print_result(
            "duplication_factor_peak",
            EXPECTED["duplication_factor_peak_min"]
            <= duplicate_peak
            <= EXPECTED["duplication_factor_peak_max"],
            round(duplicate_peak, 6),
            (
                EXPECTED["duplication_factor_peak_min"],
                EXPECTED["duplication_factor_peak_max"],
            ),
        ),
        _print_result(
            "timestamps_monotonic",
            _timestamps_are_monotonic(events),
            [event["ts"] for event in events[:3]],
            "nondecreasing ts",
        ),
        _print_result(
            "timestamps_start_near_zero",
            bool(events) and 0.0 <= events[0]["ts"] < 1.0,
            events[0]["ts"] if events else None,
            "0 <= first ts < 1.0",
        ),
        _print_result(
            "data_v1_logical_id_stable",
            _logical_ids_stable_before_mutate(events, v1_id),
            "stable" if _logical_ids_stable_before_mutate(events, v1_id) else "unstable",
            v1_id,
        ),
        _print_result(
            "liveness_intervals",
            not duplication_errors,
            duplication_errors,
            [],
        ),
    ]

    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
