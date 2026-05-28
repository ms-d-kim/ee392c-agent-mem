"""
Load JSONL trace files into a pandas DataFrame for analysis.

Schema version compatibility: this module checks SCHEMA_VERSION matches.
On a schema bump, update both agent/tracer.py and this loader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agent.tracer import SCHEMA_VERSION


def load_trace(path: Path, *, expected_schema_version: int | None = SCHEMA_VERSION) -> pd.DataFrame:
    """Load a single JSONL trace into a DataFrame.

    Columns: ts, step, phase, object_id, logical_id, repr_type, size_bytes, op
    """
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    df = pd.DataFrame(records)
    if expected_schema_version is not None:
        if "schema_version" not in df.columns:
            raise ValueError(f"{path}: missing schema_version; pass expected_schema_version=None for legacy traces")
        bad = sorted(df.loc[df["schema_version"] != expected_schema_version, "schema_version"].dropna().unique())
        if bad:
            raise ValueError(f"{path}: expected schema_version={expected_schema_version}, found {bad}")
    return df


def load_system_trace(path: Path) -> pd.DataFrame:
    """Load a system-telemetry JSONL into a DataFrame.

    Columns: ts, source, metric, value, unit
    """
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return pd.DataFrame(records)
