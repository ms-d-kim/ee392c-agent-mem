# agent/tracer.py Review

Scope: reviewed `AGENTS.md`, the required project docs, `agent/tracer.py`, and the synthetic tracer contract. No code changes were made to `agent/tracer.py`.

## Findings

### [BLOCKER] `agent/tracer.py:59`

`compute_logical_id()` returns only the first 12 hex characters of the SHA1 digest, but the schema contract says `logical_id` is the "sha1 of normalized content." A 12-character prefix is not the exact schema value and also reduces the ID to 48 bits, which makes accidental collisions more plausible as traces grow.

Suggested fix:

```python
def compute_logical_id(content: str) -> str:
    """SHA1 of normalized content."""
    h = hashlib.sha1(normalize_for_logical_id(content).encode("utf-8"))
    return h.hexdigest()
```

### [HIGH] `agent/tracer.py:85`

`start()` is not idempotent and is not guarded by the tracer lock. Calling it twice silently overwrites `self._fh`, leaks the first file handle until garbage collection, and resets `self._t0`, so timestamps appended to the same JSONL file are no longer seconds since the original trace start.

Suggested fix:

```python
def start(self) -> None:
    """Open the output file and record t0."""
    with self._lock:
        if self._fh is not None:
            raise RuntimeError("Tracer.start() called while already started")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.output_path.open("a", encoding="utf-8")
        self._t0 = time.monotonic()
```

### [HIGH] `agent/tracer.py:119`

Lifecycle state is read partly outside the lock in `emit()`, while `start()` is currently unsynchronized. Concurrent `emit()` calls after a clean `start()` are serialized correctly, but concurrent lifecycle operations can observe inconsistent `_t0`/`_fh` state. This also makes future changes to `stop()` riskier because timestamp state and file-handle state are not protected as one invariant.

Suggested fix:

```python
with self._lock:
    if self._t0 is None or self._fh is None:
        raise RuntimeError("Tracer.emit() called before start() or after stop()")
    event = {
        "ts": time.monotonic() - self._t0,
        # remaining fields...
    }
    self._fh.write(json.dumps(event, allow_nan=False) + "\n")
    self._fh.flush()
```

### [HIGH] `agent/tracer.py:102`

The `Literal` annotations for `phase`, `repr_type`, and `op` are advisory only at runtime. A caller can emit invalid phases, invalid representation types, negative sizes, non-integer steps, or non-finite numeric values, and the tracer will still write them. That can produce schema-invalid JSONL even though the function signature looks constrained.

Suggested fix:

```python
from typing import get_args

_ALLOWED_PHASES = set(get_args(Phase))
_ALLOWED_REPR_TYPES = set(get_args(ReprType))
_ALLOWED_OPS = set(get_args(Op))

if phase not in _ALLOWED_PHASES:
    raise ValueError(f"invalid phase: {phase!r}")
if repr_type not in _ALLOWED_REPR_TYPES:
    raise ValueError(f"invalid repr_type: {repr_type!r}")
if op not in _ALLOWED_OPS:
    raise ValueError(f"invalid op: {op!r}")
if not isinstance(step, int) or step < 0:
    raise ValueError(f"invalid step: {step!r}")
if not isinstance(size_bytes, int) or size_bytes < 0:
    raise ValueError(f"invalid size_bytes: {size_bytes!r}")
```

### [HIGH] `agent/tracer.py:50`

`normalize_for_logical_id()` lowercases and collapses whitespace, but it does not normalize Unicode. Visually identical NFC and NFD strings can hash to different `logical_id` values, which breaks duplicate detection for content that differs only by canonical Unicode representation.

Suggested fix:

```python
import unicodedata

def normalize_for_logical_id(content: str) -> str:
    """Normalize content for cross-representation duplicate detection."""
    normalized = unicodedata.normalize("NFC", content)
    return " ".join(normalized.lower().split())
```

### [HIGH] `agent/tracer.py:65`

`Tracer` has `start()` and `stop()`, but no context-manager support. If caller code raises after `start()` and before `stop()`, the handle remains open until process cleanup. The per-event flushes protect already written events, but exception-safe closing should be built into the tracer API because the agent loop and tools are expected to fail during development.

Suggested fix:

```python
def __enter__(self) -> "Tracer":
    self.start()
    return self

def __exit__(self, exc_type, exc, tb) -> bool:
    self.stop()
    return False
```

### [NIT] `agent/tracer.py:50`

For very long content, `normalize_for_logical_id()` creates several full-size intermediate objects: the lowercased string, the `split()` list, the joined string, and then the UTF-8 bytes in `compute_logical_id()`. This is correct for ordinary prompt/file strings, but content above 1 MB can add avoidable memory pressure and tracing overhead.

Suggested fix:

```python
def update_hash_with_normalized_content(h: "hashlib._Hash", content: str) -> None:
    pending_space = False
    wrote_any = False
    for ch in unicodedata.normalize("NFC", content).lower():
        if ch.isspace():
            pending_space = wrote_any
            continue
        if pending_space:
            h.update(b" ")
            pending_space = False
        h.update(ch.encode("utf-8"))
        wrote_any = True
```

## Checks With No Finding

- `agent/tracer.py:134` writes exactly one JSON object followed by a trailing newline.
- `agent/tracer.py:135` flushes after every event, and `agent/tracer.py:97` flushes during `stop()`.
- Concurrent `emit()` calls after a single completed `start()` are serialized by `self._lock`, so JSONL lines should not interleave.
- Embedded newlines in `object_id` are escaped by `json.dumps()`, so they do not create extra JSONL records.
- Event objects contain the eight schema fields from the docstring and do not add extra fields.
- Empty strings and all-whitespace strings are handled deterministically, although both normalize to the same empty string by the current whitespace-collapsing contract.
- Content that is already lowercase and whitespace-collapsed is normalized idempotently.
- Leading and trailing whitespace is intentionally removed by `split()`/`join()` as part of whitespace collapse.

## Commit Message

`Review agent/tracer.py against the JSONL schema contract, thread-safety expectations, crash-resilience requirements, logical-id normalization edge cases, lifecycle/file-handle safety, and runtime type-validation gaps.`
