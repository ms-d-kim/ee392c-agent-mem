"""
Logical-layer tracer for the EE 392C agent-memory characterization project.

JSONL event schema:
{
    "schema_version": int, "ts": float, "step": int, "phase": str,
    "object_id": str, "logical_id": str, "repr_type": str,
    "size_bytes": int, "op": str,
}

Schema version: 3
  v1 -> v2 changes (2026-05-19):
    - Tracer opens output in 'w' (truncate) mode by default; pass
      append=True for v1 behavior. v1's silent append caused trace pollution.
    - emit() now validates phase, repr_type, op, step, and size_bytes
      against declared enums/types at runtime. Out-of-schema values are
      rejected with TracerSchemaError.
  v2 -> v3 changes (2026-05-28):
    - Adds optional semantic attribution fields:
      semantic_type, source, token_offset_start, token_offset_end,
      token_count, confidence.
    - Existing v2 fields remain required and unchanged.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 3

PHASES = frozenset({"prefill", "decode", "tool_exec", "agent_loop", "task_setup"})
REPR_TYPES = frozenset({"text", "tokens", "kv_estimated", "kv_actual"})
OPS = frozenset({"create", "read", "mutate", "free"})
CONFIDENCES = frozenset({"high", "medium", "low"})

Phase = Literal["prefill", "decode", "tool_exec", "agent_loop", "task_setup"]
ReprType = Literal["text", "tokens", "kv_estimated", "kv_actual"]
Op = Literal["create", "read", "mutate", "free"]
Confidence = Literal["high", "medium", "low"]


class TracerSchemaError(ValueError):
    """Raised when an emit() call violates the trace schema."""


def normalize_for_logical_id(content: str) -> str:
    """Normalize content identity.

    Whitespace is intentionally collapsed, so whitespace-only edits do not
    create a new logical version.
    """
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
            if self._mode == "a" and self.output_path.exists() and self.output_path.stat().st_size:
                raise RuntimeError(
                    "append=True is only allowed for empty trace files; "
                    "otherwise relative timestamps become non-monotonic"
                )
            self._fh = self.output_path.open(self._mode, encoding="utf-8")
            self._t0 = time.monotonic()

    @property
    def time_origin_monotonic(self) -> float:
        if self._t0 is None:
            raise RuntimeError("Tracer has not been started")
        return self._t0

    def stop(self):
        with self._lock:
            if self._fh is None:
                return
            try:
                self._fh.flush()
            finally:
                self._fh.close()
                self._fh = None

    def emit(
        self,
        step,
        phase,
        object_id,
        logical_id,
        repr_type,
        size_bytes,
        op,
        *,
        semantic_type: str | None = None,
        source: str | None = None,
        token_offset_start: int | None = None,
        token_offset_end: int | None = None,
        token_count: int | None = None,
        confidence: Confidence | None = None,
        extra: dict[str, Any] | None = None,
    ):
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
        if semantic_type is not None and (not isinstance(semantic_type, str) or not semantic_type):
            raise TracerSchemaError("semantic_type must be a non-empty string when provided")
        if source is not None and (not isinstance(source, str) or not source):
            raise TracerSchemaError("source must be a non-empty string when provided")
        if confidence is not None and confidence not in CONFIDENCES:
            raise TracerSchemaError(f"invalid confidence {confidence!r}; must be one of {sorted(CONFIDENCES)}")
        span_values = [token_offset_start, token_offset_end, token_count]
        if any(v is not None for v in span_values):
            if not all(isinstance(v, int) for v in span_values):
                raise TracerSchemaError(
                    "token_offset_start, token_offset_end, and token_count must all be ints when any is provided"
                )
            if token_offset_start < 0 or token_offset_end < 0 or token_offset_end < token_offset_start:
                raise TracerSchemaError("invalid token offset range")
            if token_count != token_offset_end - token_offset_start:
                raise TracerSchemaError("token_count must equal token_offset_end - token_offset_start")
        if extra is not None and not isinstance(extra, dict):
            raise TracerSchemaError("extra must be a dict when provided")
        reserved_extra_keys = {
            "schema_version",
            "ts",
            "step",
            "phase",
            "object_id",
            "logical_id",
            "repr_type",
            "size_bytes",
            "op",
            "semantic_type",
            "source",
            "token_offset_start",
            "token_offset_end",
            "token_count",
            "confidence",
        }
        if extra:
            shadowed = sorted(reserved_extra_keys & set(extra))
            if shadowed:
                raise TracerSchemaError(f"extra cannot override schema fields {shadowed}")

        with self._lock:
            if self._t0 is None or self._fh is None:
                raise RuntimeError("Tracer.emit() called before start() or after stop()")
            event = {
                "schema_version": SCHEMA_VERSION,
                "ts": time.monotonic() - self._t0,
                "step": step,
                "phase": phase,
                "object_id": object_id,
                "logical_id": logical_id,
                "repr_type": repr_type,
                "size_bytes": size_bytes,
                "op": op,
            }
            if semantic_type is not None:
                event["semantic_type"] = semantic_type
            if source is not None:
                event["source"] = source
            if token_offset_start is not None:
                event["token_offset_start"] = token_offset_start
                event["token_offset_end"] = token_offset_end
                event["token_count"] = token_count
            if confidence is not None:
                event["confidence"] = confidence
            if extra:
                event.update(extra)
            self._fh.write(json.dumps(event) + "\n")
            self._fh.flush()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
