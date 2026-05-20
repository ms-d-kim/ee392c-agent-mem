"""
Logical-layer tracer for the EE 392C agent-memory characterization project.

JSONL event schema:
{
    "ts": float, "step": int, "phase": str, "object_id": str,
    "logical_id": str, "repr_type": str, "size_bytes": int, "op": str,
}

Schema version: 2
  v1 -> v2 changes (2026-05-19):
    - Tracer opens output in 'w' (truncate) mode by default; pass
      append=True for v1 behavior. v1's silent append caused trace pollution.
    - emit() now validates phase, repr_type, op, step, and size_bytes
      against declared enums/types at runtime. Out-of-schema values are
      rejected with TracerSchemaError.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import unicodedata
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = 2

PHASES = frozenset({"prefill", "decode", "tool_exec", "agent_loop", "task_setup"})
REPR_TYPES = frozenset({"text", "tokens", "kv_estimated", "kv_actual"})
OPS = frozenset({"create", "read", "mutate", "free"})

Phase = Literal["prefill", "decode", "tool_exec", "agent_loop", "task_setup"]
ReprType = Literal["text", "tokens", "kv_estimated", "kv_actual"]
Op = Literal["create", "read", "mutate", "free"]


class TracerSchemaError(ValueError):
    """Raised when an emit() call violates the trace schema."""


def normalize_for_logical_id(content: str) -> str:
    normalized = unicodedata.normalize("NFC", content)
    return " ".join(normalized.lower().split())


def compute_logical_id(content: str) -> str:
    h = hashlib.sha1(normalize_for_logical_id(content).encode("utf-8"))
    return h.hexdigest()


class Tracer:
    def __init__(self, output_path, append=False):
        self.output_path = Path(output_path)
        self._mode = "a" if append else "w"
        self._fh = None
        self._t0 = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._fh is not None:
                raise RuntimeError("Tracer.start() called while already started")
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.output_path.open(self._mode, encoding="utf-8")
            self._t0 = time.monotonic()

    def stop(self):
        with self._lock:
            if self._fh is None:
                return
            try:
                self._fh.flush()
            finally:
                self._fh.close()
                self._fh = None

    def emit(self, step, phase, object_id, logical_id, repr_type, size_bytes, op):
        if phase not in PHASES:
            raise TracerSchemaError(f"invalid phase {phase!r}; must be one of {sorted(PHASES)}")
        if repr_type not in REPR_TYPES:
            raise TracerSchemaError(f"invalid repr_type {repr_type!r}; must be one of {sorted(REPR_TYPES)}")
        if op not in OPS:
            raise TracerSchemaError(f"invalid op {op!r}; must be one of {sorted(OPS)}")
        if not isinstance(step, int) or step < 0:
            raise TracerSchemaError(f"invalid step {step!r}; must be a nonnegative int")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise TracerSchemaError(f"invalid size_bytes {size_bytes!r}; must be a nonnegative int")
        if not object_id or not isinstance(object_id, str):
            raise TracerSchemaError("object_id must be a non-empty string")
        if not logical_id or not isinstance(logical_id, str):
            raise TracerSchemaError("logical_id must be a non-empty string")

        with self._lock:
            if self._t0 is None or self._fh is None:
                raise RuntimeError("Tracer.emit() called before start() or after stop()")
            event = {
                "ts": time.monotonic() - self._t0,
                "step": step,
                "phase": phase,
                "object_id": object_id,
                "logical_id": logical_id,
                "repr_type": repr_type,
                "size_bytes": size_bytes,
                "op": op,
            }
            self._fh.write(json.dumps(event) + "\n")
            self._fh.flush()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
