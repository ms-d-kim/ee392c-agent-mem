"""
Lifetime computation per the locked DECISIONS.md §2.

Primary: logical-presence, task-bounded.
    lifetime = min(t_last_access, t_task_end) - t_first_observation

Sensitivity alternatives (supplementary plot):
- Strict KV-residence: from KV block "create" to "free" (kv_estimated/kv_actual only)
- Context-window: from create to last "read" excluding tool_exec phase
"""

from __future__ import annotations

import pandas as pd


def compute_logical_presence_lifetime(df: pd.DataFrame) -> pd.DataFrame:
    """Primary lifetime definition.

    Group by logical_id; lifetime = min(last_access, task_end) - first_obs.

    Returns:
        DataFrame with columns: logical_id, t_first, t_last, lifetime_s,
                                reuse_count, peak_size_bytes
    """
    raise NotImplementedError


def compute_kv_residence_lifetime(df: pd.DataFrame) -> pd.DataFrame:
    """Sensitivity definition: KV block create -> free."""
    raise NotImplementedError


def compute_context_window_lifetime(df: pd.DataFrame) -> pd.DataFrame:
    """Sensitivity definition: while object remained in prompt context."""
    raise NotImplementedError


def lifetime_cdf_data(df: pd.DataFrame, definition: str = "logical_presence"):
    """Return (lifetime_s_array, cumulative_prob_array) for plotting."""
    raise NotImplementedError
