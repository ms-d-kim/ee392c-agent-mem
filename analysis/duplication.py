"""
Duplication factor — the genuinely novel angle vs. GainSight.

Same logical content (same logical_id) can exist simultaneously as:
- text (raw string in conversation history)
- tokens (token IDs in the input prompt)
- kv_estimated / kv_actual (KV cache entries in the engine)

Duplication factor at time t:
    sum(size_bytes of all live representations at t)
    -----------------------------------------------------
    sum(size_bytes of one representative per unique logical_id at t)

Or equivalently: the multiplier on physical bytes vs. unique logical bytes.
"""

from __future__ import annotations

import pandas as pd


def compute_duplication_over_time(df: pd.DataFrame, sample_hz: float = 10.0) -> pd.DataFrame:
    """Time series of duplication factor at sample_hz.

    Returns DataFrame with columns: ts, total_bytes, unique_bytes, dup_factor.

    Algorithm sketch:
    1. Build a per-(logical_id, repr_type, object_id) liveness interval from
       create/mutate/free events.
    2. At each sample timestamp ts, sum sizes of all live (object_id) entries.
    3. Group by logical_id, take size of one representative, sum.
    4. dup_factor = total / unique.
    """
    raise NotImplementedError


def duplication_by_task_dimension(
    traces: list[pd.DataFrame],
    dimension: str,
) -> pd.DataFrame:
    """Per-task duplication peak vs. a task dimension.

    dimension: "step_count" | "tool_call_density" | "prefix_cache_mode"
    """
    raise NotImplementedError
