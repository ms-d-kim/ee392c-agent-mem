"""
Logical-layer tracer for the EE 392C agent-memory characterization project.

JSONL event schema (the contract between agent code and analysis code):

{
    "ts": float,           # monotonic seconds since trace start
    "step": int,           # agent step counter (0-indexed)
    "phase": str,          # "prefill" | "decode" | "tool_exec" |
                           # "agent_loop" | "task_setup"
    "object_id": str,      # unique id for this physical instance
                           # (e.g. "kv_block_0042", "text_msg_007",
                           #  "tool_output_003")
    "logical_id": str,     # sha1 of normalized content (lowercased,
                           # whitespace-collapsed). Same content across
                           # representations -> same logical_id.
                           # This is how cross-representation duplication
                           # is tracked.
    "repr_type": str,      # "text" | "tokens" | "kv_estimated" | "kv_actual"
    "size_bytes": int,     # physical bytes in this representation
    "op": str,             # "create" | "read" | "mutate" | "free"
}

Schema version: 1
Bump this version (and update analysis/load_traces.py) on any schema change.

Derived metrics:
- lifetime(logical_id) = min(t_last_access, t_task_end) - t_first_observation
- reuse_count(logical_id) = count of "read" ops for that logical_id
- duplication_factor(t) = sum(size_bytes) / sum(unique logical_id sizes)
- byte_seconds(logical_id) = size_bytes * lifetime
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = 1

Phase = Literal["prefill", "decode", "tool_exec", "agent_loop", "task_setup"]
ReprType = Literal["text", "tokens", "kv_estimated", "kv_actual"]
Op = Literal["create", "read", "mutate", "free"]


def normalize_for_logical_id(content: str) -> str:
    """Normalize content for cross-representation duplicate detection.

    Lowercase + collapse whitespace. Same content across {text, tokens, kv}
    must hash to the same logical_id.
    """
    return " ".join(content.lower().split())


def compute_logical_id(content: str) -> str:
    """SHA1 of normalized content. First 12 chars used as id for readability."""
    h = hashlib.sha1(normalize_for_logical_id(content).encode("utf-8"))
    return h.hexdigest()[:12]


class Tracer:
    """Append-only JSONL event emitter.

    Usage:
        t = Tracer(Path("traces/run_001.jsonl"))
        t.start()
        t.emit(step=0, phase="task_setup", object_id="prompt_000",
               logical_id=compute_logical_id(prompt_text),
               repr_type="text", size_bytes=len(prompt_text.encode()),
               op="create")
        # ... agent loop ...
        t.stop()
    """

    def __init__(self, output_path: Path):
        self.output_path = Path(output_path)
        self._fh = None
        self._t0: float | None = None

    def start(self) -> None:
        """Open the output file and record t0."""
        raise NotImplementedError("Implement: open file, set self._t0 = time.monotonic()")

    def stop(self) -> None:
        """Flush and close. Idempotent."""
        raise NotImplementedError

    def emit(
        self,
        step: int,
        phase: Phase,
        object_id: str,
        logical_id: str,
        repr_type: ReprType,
        size_bytes: int,
        op: Op,
    ) -> None:
        """Append one event to the JSONL file.

        Implementation notes:
        - ts = time.monotonic() - self._t0
        - Write one JSON object per line, flush after each (so traces survive
          crashes mid-run)
        """
        raise NotImplementedError
