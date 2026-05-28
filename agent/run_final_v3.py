"""
Final-v3 semantic memory runner for scripted agent-workflow replay.

This runner collects the six final traces:
    coding_agent: cache_on / cache_off
    search_agent: targeted / broad
    compaction_agent: compaction_on / compaction_off

The workloads are deterministic multi-step replays that preserve agent-like
prompt/tool/context structure. They are not autonomous tool-selection loops.
The runner keeps the v2 lifecycle schema intact and adds v3 semantic/span
fields. Use --dry-run for local validation without vLLM; omit it on RunPod.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.tracer import Tracer, compute_logical_id
from serving.telemetry import SystemTelemetry, nvtx_phase

MAX_STEPS = 15
MAX_MODEL_LEN = 8192
MODEL_PATH = "/workspace/hf-cache/Qwen2.5-Coder-7B-Instruct"
DEFAULT_MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"
KV_DTYPE_BYTES = 2
KV_BLOCK_SIZE_TOKENS = 16
TOKEN_ID_BYTES = 4
SEARCH_CORPUS_EXPANSION_FACTOR = 30
COMPACTION_LOG_EXPANSION_FACTOR = 14

FINAL_TRACES = [
    ("coding_agent", "cache_on"),
    ("coding_agent", "cache_off"),
    ("search_agent", "targeted"),
    ("search_agent", "broad"),
    ("compaction_agent", "compaction_on"),
    ("compaction_agent", "compaction_off"),
]


class SimpleTokenizer:
    """Content-aware tokenizer stand-in for local dry-run validation.

    The IDs are deterministic hashes of byte chunks, so prefix-cache checks
    depend on prompt content instead of only prompt length.
    """

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        text = ""
        for msg in messages:
            text += f"<|{msg['role']}|>\n{msg['content']}\n"
        if add_generation_prompt:
            text += "<|assistant|>\n"
        if tokenize:
            return self(text)["input_ids"]
        return text

    def __call__(self, text):
        data = text.encode("utf-8")
        if not data:
            return {"input_ids": [0]}
        ids = []
        for offset in range(0, len(data), 4):
            chunk = data[offset: offset + 4]
            digest = hashlib.sha1(chunk).digest()
            ids.append(int.from_bytes(digest[:4], "big"))
        return {"input_ids": ids}


@dataclass
class MessageRecord:
    role: str
    content: str
    semantic_type: str
    source: str
    origin_step: int
    logical_id: str
    object_base: str
    active: bool = True


@dataclass
class PromptSpan:
    index: int
    semantic_type: str
    source: str
    logical_id: str
    token_offset_start: int
    token_offset_end: int

    @property
    def token_count(self) -> int:
        return self.token_offset_end - self.token_offset_start


@dataclass(frozen=True)
class CachedTokenLookup:
    value: int | None
    source: str


def token_count(tok, text: str) -> int:
    return len(tok(text)["input_ids"])


def derive_kv_bytes_per_token(config: Any, dtype_bytes: int = KV_DTYPE_BYTES) -> int:
    """Derive GQA-aware KV bytes/token from a Hugging Face config."""
    n_layers = int(getattr(config, "num_hidden_layers"))
    n_heads = int(getattr(config, "num_attention_heads"))
    n_kv_heads = int(getattr(config, "num_key_value_heads", n_heads))
    hidden_size = int(getattr(config, "hidden_size"))
    head_dim = int(getattr(config, "head_dim", hidden_size // n_heads))
    return 2 * n_layers * n_kv_heads * head_dim * dtype_bytes


def qwen25_coder_7b_kv_bytes_per_token() -> int:
    """Fallback value for Qwen2.5-Coder-7B-Instruct bf16."""
    return 2 * 28 * 4 * 128 * KV_DTYPE_BYTES


def _int_attr(obj: Any, attr: str) -> int | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        value = obj.get(attr)
    elif hasattr(obj, attr):
        value = getattr(obj, attr)
    else:
        return None
    if value is None:
        return None
    return int(value)


def get_cached_tokens(out: Any) -> CachedTokenLookup:
    """Best-effort vLLM cached-token extraction without silently defaulting."""
    candidates = [
        ("request_output.num_cached_tokens", out, "num_cached_tokens"),
        ("request_output.metrics.num_cached_tokens", getattr(out, "metrics", None), "num_cached_tokens"),
        ("request_output.usage.cached_tokens", getattr(out, "usage", None), "cached_tokens"),
    ]
    outputs = getattr(out, "outputs", None) or []
    if outputs:
        first = outputs[0]
        candidates.extend([
            ("output.num_cached_tokens", first, "num_cached_tokens"),
            ("output.metrics.num_cached_tokens", getattr(first, "metrics", None), "num_cached_tokens"),
            ("output.usage.cached_tokens", getattr(first, "usage", None), "cached_tokens"),
        ])

    for source, obj, attr in candidates:
        try:
            value = _int_attr(obj, attr)
        except Exception:
            continue
        if value is not None:
            return CachedTokenLookup(value=value, source=source)
    return CachedTokenLookup(value=None, source="unavailable")


def leading_prefix_match(a: list[int], b: list[int]) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")


class SemanticWorkflowReplay:
    """Shared semantic tracing loop for the three scripted workload replays."""

    def __init__(
        self,
        *,
        tracer: Tracer,
        tok,
        llm,
        sampling,
        dry_run: bool,
        prefix_caching: bool,
        workload: str,
        condition: str,
        kv_bytes_per_token: int,
    ):
        self.tracer = tracer
        self.tok = tok
        self.llm = llm
        self.sampling = sampling
        self.dry_run = dry_run
        self.prefix_caching = prefix_caching
        self.workload = workload
        self.condition = condition
        self.kv_bytes_per_token = kv_bytes_per_token
        self.records: list[MessageRecord] = []
        self.prev_prompt_ids: list[int] | None = None

    def emit_trace_metadata(self) -> None:
        payload = {
            "workload_kind": "scripted_agent_workflow_replay",
            "workload": self.workload,
            "condition": self.condition,
            "dry_run": self.dry_run,
            "kv_bytes_per_token": self.kv_bytes_per_token,
            "kv_dtype_bytes": KV_DTYPE_BYTES,
            "kv_block_size_tokens": KV_BLOCK_SIZE_TOKENS,
            "max_model_len": MAX_MODEL_LEN,
            "prefix_caching": self.prefix_caching,
            "model": MODEL_PATH,
            "default_model_id": DEFAULT_MODEL_ID,
            "search_corpus_expansion_factor": SEARCH_CORPUS_EXPANSION_FACTOR,
            "compaction_log_expansion_factor": COMPACTION_LOG_EXPANSION_FACTOR,
        }
        self.tracer.emit(
            step=0,
            phase="task_setup",
            object_id="trace_metadata",
            logical_id=compute_logical_id(json.dumps(payload, sort_keys=True)),
            repr_type="text",
            size_bytes=0,
            op="create",
            semantic_type="trace_metadata",
            source="runner",
            confidence="high",
            extra=payload,
        )

    def add_message(
        self,
        *,
        role: str,
        content: str,
        semantic_type: str,
        source: str,
        step: int,
    ) -> MessageRecord:
        logical_id = compute_logical_id(content)
        base = f"msg_step{step}_{role}_{safe_name(semantic_type)}_{len(self.records)}"
        text_bytes = len(content.encode("utf-8"))
        tok_bytes = token_count(self.tok, content) * TOKEN_ID_BYTES
        self.tracer.emit(
            step=step,
            phase="agent_loop" if step else "task_setup",
            object_id=f"{base}_text",
            logical_id=logical_id,
            repr_type="text",
            size_bytes=text_bytes,
            op="create",
            semantic_type=semantic_type,
            source=source,
            confidence="high",
        )
        self.tracer.emit(
            step=step,
            phase="agent_loop" if step else "task_setup",
            object_id=f"{base}_tokens",
            logical_id=logical_id,
            repr_type="tokens",
            size_bytes=tok_bytes,
            op="create",
            semantic_type=semantic_type,
            source=source,
            confidence="high",
        )
        rec = MessageRecord(role, content, semantic_type, source, step, logical_id, base)
        self.records.append(rec)
        return rec

    def read_active_history(self, step: int) -> None:
        for rec in self.records:
            if not rec.active:
                continue
            self.tracer.emit(
                step=step,
                phase="prefill",
                object_id=f"{rec.object_base}_text",
                logical_id=rec.logical_id,
                repr_type="text",
                size_bytes=len(rec.content.encode("utf-8")),
                op="read",
                semantic_type=rec.semantic_type,
                source=rec.source,
                confidence="high",
            )
            self.tracer.emit(
                step=step,
                phase="prefill",
                object_id=f"{rec.object_base}_tokens",
                logical_id=rec.logical_id,
                repr_type="tokens",
                size_bytes=token_count(self.tok, rec.content) * TOKEN_ID_BYTES,
                op="read",
                semantic_type=rec.semantic_type,
                source=rec.source,
                confidence="high",
            )

    def demote_records(self, *, semantic_type: str, step: int) -> None:
        for rec in self.records:
            if not rec.active or rec.semantic_type != semantic_type:
                continue
            rec.active = False
            self.tracer.emit(
                step=step,
                phase="agent_loop",
                object_id=f"{rec.object_base}_text",
                logical_id=rec.logical_id,
                repr_type="text",
                size_bytes=len(rec.content.encode("utf-8")),
                op="free",
                semantic_type=rec.semantic_type,
                source="compaction_demote",
                confidence="high",
            )
            self.tracer.emit(
                step=step,
                phase="agent_loop",
                object_id=f"{rec.object_base}_tokens",
                logical_id=rec.logical_id,
                repr_type="tokens",
                size_bytes=token_count(self.tok, rec.content) * TOKEN_ID_BYTES,
                op="free",
                semantic_type=rec.semantic_type,
                source="compaction_demote",
                confidence="high",
            )

    def active_messages(self) -> list[dict[str, str]]:
        return [{"role": rec.role, "content": rec.content} for rec in self.records if rec.active]

    def active_records(self) -> list[MessageRecord]:
        return [rec for rec in self.records if rec.active]

    def build_prompt_spans(self) -> tuple[str, list[int], list[PromptSpan]]:
        messages = self.active_messages()
        records = self.active_records()
        prompt_text = self.tok.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        prompt_ids = self.tok(prompt_text)["input_ids"]
        spans: list[PromptSpan] = []
        start = 0
        for idx, rec in enumerate(records):
            prefix_text = self.tok.apply_chat_template(
                messages[: idx + 1],
                tokenize=False,
                add_generation_prompt=False,
            )
            # BPE tokenization is not perfectly compositional across segment
            # boundaries. Clamp prefix-derived ends so spans remain contiguous
            # and length-matched to the actual serialized prompt.
            end = min(max(token_count(self.tok, prefix_text), start), len(prompt_ids))
            if end > start:
                spans.append(PromptSpan(
                    index=len(spans),
                    semantic_type=rec.semantic_type,
                    source=rec.source,
                    logical_id=rec.logical_id,
                    token_offset_start=start,
                    token_offset_end=end,
                ))
            start = end
        if len(prompt_ids) > start:
            spans.append(PromptSpan(
                index=len(spans),
                semantic_type="prompt_template",
                source="chat_template",
                logical_id=compute_logical_id("assistant_generation_prompt"),
                token_offset_start=start,
                token_offset_end=len(prompt_ids),
            ))
        return prompt_text, prompt_ids, spans

    def emit_kv_spans(self, *, step: int, spans: list[PromptSpan]) -> None:
        for span in spans:
            self.tracer.emit(
                step=step,
                phase="prefill",
                object_id=f"kv_prompt_step{step}_span{span.index}",
                logical_id=span.logical_id,
                repr_type="kv_estimated",
                size_bytes=span.token_count * self.kv_bytes_per_token,
                op="create",
                semantic_type=span.semantic_type,
                source=span.source,
                token_offset_start=span.token_offset_start,
                token_offset_end=span.token_offset_end,
                token_count=span.token_count,
                confidence="medium",
                extra={
                    "workload": self.workload,
                    "condition": self.condition,
                    "kv_bytes_per_token": self.kv_bytes_per_token,
                    "kv_pressure_kind": "logical_projected",
                },
            )

    def emit_cached_prefix_reads(self, *, step: int, spans: list[PromptSpan], cached_tokens: int) -> int:
        cached_span_tokens = 0
        for span in spans:
            overlap = max(
                0,
                min(span.token_offset_end, cached_tokens) - span.token_offset_start,
            )
            if overlap <= 0:
                continue
            cached_span_tokens += overlap
            self.tracer.emit(
                step=step,
                phase="prefill",
                object_id=f"kv_prompt_step{step}_span{span.index}",
                logical_id=span.logical_id,
                repr_type="kv_estimated",
                size_bytes=overlap * self.kv_bytes_per_token,
                op="read",
                semantic_type=span.semantic_type,
                source="vllm_cached_prefix",
                token_offset_start=span.token_offset_start,
                token_offset_end=span.token_offset_start + overlap,
                token_count=overlap,
                confidence="medium",
                extra={
                    "workload": self.workload,
                    "condition": self.condition,
                    "kv_bytes_per_token": self.kv_bytes_per_token,
                    "kv_pressure_kind": "cache_adjusted_reuse",
                    "cached_tokens_total": cached_tokens,
                },
            )
        return cached_span_tokens

    def emit_engine_cross_check(
        self,
        *,
        step: int,
        prompt_token_count: int,
        cached_tokens: int,
        cached_span_tokens: int,
        cached_tokens_available: bool,
        cached_tokens_source: str,
    ) -> None:
        delta = cached_tokens - cached_span_tokens
        cross_check_pass = cached_tokens_available and abs(delta) <= KV_BLOCK_SIZE_TOKENS
        if cross_check_pass:
            status = "passed"
        elif cached_tokens_available:
            status = "failed"
        else:
            status = "unavailable"
        if not self.prefix_caching and not cached_tokens_available:
            status = "cache_disabled_unverified"
        payload = {
            "workload": self.workload,
            "condition": self.condition,
            "dry_run": self.dry_run,
            "prefix_caching": self.prefix_caching,
            "prompt_token_count": prompt_token_count,
            "cached_tokens": cached_tokens,
            "cached_tokens_available": cached_tokens_available,
            "cached_tokens_source": cached_tokens_source,
            "cached_span_tokens": cached_span_tokens,
            "cached_token_delta": delta,
            "kv_block_size_tokens": KV_BLOCK_SIZE_TOKENS,
            "kv_bytes_per_token": self.kv_bytes_per_token,
            "cross_check_pass": cross_check_pass,
            "cross_check_status": status,
            "cross_check_note": (
                "dry_run uses a content-aware synthetic tokenizer; real-vLLM "
                "cached-token attribution must be validated on RunPod"
                if self.dry_run else ""
            ),
        }
        self.tracer.emit(
            step=step,
            phase="prefill",
            object_id=f"engine_cross_check_step{step}",
            logical_id=compute_logical_id(json.dumps(payload, sort_keys=True)),
            repr_type="tokens",
            size_bytes=0,
            op="create",
            semantic_type="engine_cross_check",
            source="vllm_metrics",
            confidence="medium",
            extra=payload,
        )

    def generate(self, *, step: int, label: str) -> str:
        with nvtx_phase("prompt_build"):
            self.read_active_history(step)
            prompt_text, prompt_ids, spans = self.build_prompt_spans()
            self.emit_kv_spans(step=step, spans=spans)
        with nvtx_phase("vllm_generate"):
            if not self.prefix_caching:
                if self.dry_run:
                    output = f"Dry-run assistant step {step}: {label}."
                    cached_lookup = CachedTokenLookup(value=0, source="dry_run_prefix_caching_disabled")
                else:
                    outputs = self.llm.generate([prompt_text], self.sampling, use_tqdm=False)
                    out = outputs[0]
                    output = out.outputs[0].text
                    cached_lookup = get_cached_tokens(out)
                cached_tokens_available = cached_lookup.value is not None
                cached_tokens_source = cached_lookup.source
                cached_tokens = cached_lookup.value if cached_lookup.value is not None else 0
            elif self.dry_run:
                output = f"Dry-run assistant step {step}: {label}."
                cached_tokens = (
                    leading_prefix_match(self.prev_prompt_ids, prompt_ids)
                    if self.prefix_caching and self.prev_prompt_ids is not None
                    else 0
                )
                cached_tokens_available = True
                cached_tokens_source = "dry_run_content_prefix_match"
            else:
                outputs = self.llm.generate([prompt_text], self.sampling, use_tqdm=False)
                out = outputs[0]
                output = out.outputs[0].text
                cached_lookup = get_cached_tokens(out)
                cached_tokens_available = cached_lookup.value is not None
                cached_tokens_source = cached_lookup.source
                cached_tokens = cached_lookup.value if cached_lookup.value is not None else 0
        cached_span_tokens = self.emit_cached_prefix_reads(
            step=step,
            spans=spans,
            cached_tokens=cached_tokens,
        )
        self.emit_engine_cross_check(
            step=step,
            prompt_token_count=len(prompt_ids),
            cached_tokens=cached_tokens,
            cached_span_tokens=cached_span_tokens,
            cached_tokens_available=cached_tokens_available,
            cached_tokens_source=cached_tokens_source,
        )
        self.prev_prompt_ids = prompt_ids
        self.add_message(
            role="assistant",
            content=output,
            semantic_type="assistant_history",
            source="model_decode",
            step=step,
        )
        return output

    def emit_file_content(self, *, step: int, path: str, content: str, op: str) -> None:
        logical_id = compute_logical_id(content)
        base = f"file_{safe_name(path)}"
        self.tracer.emit(
            step=step,
            phase="tool_exec",
            object_id=f"{base}_text",
            logical_id=logical_id,
            repr_type="text",
            size_bytes=len(content.encode("utf-8")),
            op=op,
            semantic_type="file_content",
            source="read_file" if op == "create" else "write_file",
            confidence="high",
        )
        self.tracer.emit(
            step=step,
            phase="tool_exec",
            object_id=f"{base}_tokens",
            logical_id=logical_id,
            repr_type="tokens",
            size_bytes=token_count(self.tok, content) * TOKEN_ID_BYTES,
            op=op,
            semantic_type="file_content",
            source="read_file" if op == "create" else "write_file",
            confidence="high",
        )

    def emit_tool_result(self, *, step: int, content: str, source: str, semantic_type: str = "tool_result") -> None:
        self.add_message(
            role="user",
            content=f"Tool result ({source}):\n{content}",
            semantic_type=semantic_type,
            source=source,
            step=step,
        )


def reset_coding_fixture(task_dir: Path) -> None:
    fixture_py = task_dir / "fixture.py"
    if fixture_py.exists():
        ns = {"__file__": str(fixture_py)}
        exec(compile(fixture_py.read_text(), str(fixture_py), "exec"), ns)
        ns["reset"](task_dir)
        return
    src = task_dir / "src" / "math_utils.py"
    src.write_text(
        "def add(a, b):\n    return a - b  # bug\n\n"
        "def multiply(a, b):\n    return a * b\n"
    )


def replay_coding_workflow(run: SemanticWorkflowReplay, task_dir: Path) -> None:
    reset_coding_fixture(task_dir)
    problem = (task_dir / "PROBLEM.md").read_text()
    run.add_message(
        role="system",
        content=(
            "You are a coding agent. Use read_file, write_file, and run_tests. "
            "Preserve existing functions and stop when tests pass."
        ),
        semantic_type="system_prompt",
        source="runner",
        step=0,
    )
    run.add_message(role="user", content=problem, semantic_type="user_problem", source="task", step=0)

    run.generate(step=1, label="inspect source")
    source_path = "src/math_utils.py"
    source = (task_dir / source_path).read_text()
    run.emit_file_content(step=1, path=source_path, content=source, op="create")
    run.emit_tool_result(step=1, content=source, source="read_file", semantic_type="file_content")

    run.generate(step=2, label="run failing tests")
    with nvtx_phase("tool_exec"):
        test = subprocess.run(
            ["python3", "-m", "pytest", "tests/", "-x"],
            cwd=task_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    run.emit_tool_result(step=2, content=(test.stdout + test.stderr)[:2500], source="run_tests")

    run.generate(step=3, label="patch source")
    fixed = "def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n"
    (task_dir / source_path).write_text(fixed)
    run.emit_file_content(step=3, path=source_path, content=fixed, op="mutate")
    run.emit_tool_result(step=3, content=f"wrote {source_path} ({len(fixed)} bytes)", source="write_file")

    run.generate(step=4, label="confirm tests")
    with nvtx_phase("tool_exec"):
        test = subprocess.run(
            ["python3", "-m", "pytest", "tests/", "-x"],
            cwd=task_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    run.emit_tool_result(step=4, content=(test.stdout + test.stderr)[:2500], source="run_tests")
    run.generate(step=5, label="final answer")


def expand_text_for_replay(text: str, *, copies: int, label: str) -> str:
    """Deterministically expand a seed fixture without storing large files."""
    if copies <= 1:
        return text
    parts = []
    for index in range(1, copies + 1):
        parts.append(f"[{label} synthetic segment {index:02d}]\n{text.strip()}")
    return "\n\n".join(parts) + "\n"


def grep_search(corpus_dir: Path, query: str, *, max_matches: int) -> tuple[int, str, str]:
    terms = [t.lower() for t in re.findall(r"[a-zA-Z0-9_]+", query)]
    scanned_bytes = 0
    matches = []
    for path in sorted(corpus_dir.glob("*.txt")):
        text = expand_text_for_replay(
            path.read_text(),
            copies=SEARCH_CORPUS_EXPANSION_FACTOR,
            label=path.stem,
        )
        scanned_bytes += len(text.encode("utf-8"))
        for line_no, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if any(term in low for term in terms):
                matches.append(f"{path.name}:{line_no}: {line}")
    returned = "\n".join(matches[:max_matches])
    inserted = "\n".join(matches[: max(1, min(4, max_matches // 2))])
    return scanned_bytes, returned, inserted


def emit_search_events(
    run: SemanticWorkflowReplay,
    *,
    step: int,
    query: str,
    scanned_bytes: int,
    returned: str,
    inserted: str,
) -> None:
    scan_payload = f"query={query}; scanned_bytes={scanned_bytes}"
    run.tracer.emit(
        step=step,
        phase="tool_exec",
        object_id=f"search_scan_step{step}",
        logical_id=compute_logical_id(scan_payload),
        repr_type="text",
        size_bytes=scanned_bytes,
        op="create",
        semantic_type="search_corpus_scan",
        source="grep_search",
        confidence="high",
        extra={"query": query, "scanned_bytes": scanned_bytes},
    )
    run.add_message(
        role="user",
        content=f"Search results for `{query}`:\n{returned}",
        semantic_type="search_result",
        source="grep_search",
        step=step,
    )
    run.add_message(
        role="user",
        content=f"Selected snippets for reasoning:\n{inserted}",
        semantic_type="retrieved_snippet",
        source="grep_search_selection",
        step=step,
    )


def replay_search_workflow(run: SemanticWorkflowReplay, task_dir: Path, condition: str) -> None:
    corpus_dir = task_dir / "corpus"
    run.add_message(
        role="system",
        content=(
            "You are a search-heavy agent. Iteratively grep a local corpus, "
            "select only useful snippets, and answer from selected context."
        ),
        semantic_type="system_prompt",
        source="runner",
        step=0,
    )
    run.add_message(
        role="user",
        content=(task_dir / "PROBLEM.md").read_text(),
        semantic_type="user_problem",
        source="task",
        step=0,
    )

    if condition == "targeted":
        queries = [("auth timeout retry", 4), ("token refresh failure", 4)]
    else:
        queries = [("error timeout user cache auth retry database", 14), ("failure request token session", 14)]

    for idx, (query, max_matches) in enumerate(queries, 1):
        run.generate(step=idx, label=f"search query {idx}")
        with nvtx_phase("tool_exec"):
            scanned, returned, inserted = grep_search(corpus_dir, query, max_matches=max_matches)
        emit_search_events(
            run,
            step=idx,
            query=query,
            scanned_bytes=scanned,
            returned=returned,
            inserted=inserted,
        )

    run.generate(step=3, label="synthesize selected snippets")
    run.add_message(
        role="user",
        content="Use the selected snippets again and produce the final root-cause summary.",
        semantic_type="plan_state",
        source="workflow_instruction",
        step=3,
    )
    run.generate(step=4, label="final search answer")


def summarize_chunks(chunks: list[str]) -> str:
    joined = "\n".join(chunks)
    lines = [line.strip() for line in joined.splitlines() if line.strip()]
    important = [line for line in lines if any(k in line.lower() for k in ("error", "fail", "timeout", "retry", "memory"))]
    if not important:
        important = lines[:6]
    return "Summary of retained evidence:\n" + "\n".join(f"- {line[:180]}" for line in important[:8])


def replay_compaction_workflow(run: SemanticWorkflowReplay, task_dir: Path, condition: str) -> None:
    chunks = [
        expand_text_for_replay(
            (task_dir / "logs" / f"log{i}.txt").read_text(),
            copies=COMPACTION_LOG_EXPANSION_FACTOR,
            label=f"log{i}",
        )
        for i in (1, 2, 3)
    ]
    run.add_message(
        role="system",
        content=(
        "You are a long-context operations agent. Track evidence across logs, "
            "compact old context when needed, and reuse retained summaries."
        ),
        semantic_type="system_prompt",
        source="runner",
        step=0,
    )
    run.add_message(
        role="user",
        content=(task_dir / "PROBLEM.md").read_text(),
        semantic_type="user_problem",
        source="task",
        step=0,
    )

    for idx, chunk in enumerate(chunks[:2], 1):
        run.add_message(
            role="user",
            content=f"Raw log chunk {idx}:\n{chunk}",
            semantic_type="raw_context",
            source="log_ingest",
            step=idx,
        )
        run.generate(step=idx, label=f"reason over raw log {idx}")

    if condition == "compaction_on":
        summary = summarize_chunks(chunks[:2])
        run.add_message(
            role="user",
            content=summary,
            semantic_type="compacted_summary",
            source="compaction",
            step=3,
        )
        run.demote_records(semantic_type="raw_context", step=3)
        run.generate(step=3, label="reason over compacted summary")
    else:
        run.generate(step=3, label="reason without compaction")

    run.add_message(
        role="user",
        content=f"New raw log chunk 3:\n{chunks[2]}",
        semantic_type="raw_context",
        source="log_ingest",
        step=4,
    )
    run.generate(step=4, label="integrate final log")
    run.add_message(
        role="user",
        content="Re-read the retained evidence and state the incident cause plus mitigation.",
        semantic_type="plan_state",
        source="workflow_instruction",
        step=5,
    )
    run.generate(step=5, label="final incident answer")


def build_runtime(prefix_caching: bool, dry_run: bool):
    if dry_run:
        return SimpleTokenizer(), None, None, qwen25_coder_7b_kv_bytes_per_token()
    from transformers import AutoConfig, AutoTokenizer
    from vllm import LLM, SamplingParams

    model_source = MODEL_PATH if Path(MODEL_PATH).exists() else DEFAULT_MODEL_ID
    config = AutoConfig.from_pretrained(model_source)
    kv_bytes = derive_kv_bytes_per_token(config)
    tok = AutoTokenizer.from_pretrained(model_source)
    llm = LLM(
        model=model_source,
        dtype="bfloat16",
        max_model_len=MAX_MODEL_LEN,
        gpu_memory_utilization=0.85,
        enable_prefix_caching=prefix_caching,
    )
    sampling = SamplingParams(temperature=0.0, max_tokens=384, seed=42)
    return tok, llm, sampling, kv_bytes


def run_one(
    *,
    workload: str,
    condition: str,
    out_path: Path,
    dry_run: bool,
    system_telemetry_dir: Path | None = None,
    system_telemetry_interval_s: float = 1.0,
) -> None:
    prefix_caching = condition != "cache_off"
    tok, llm, sampling, kv_bytes = build_runtime(prefix_caching=prefix_caching, dry_run=dry_run)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry = None
    if system_telemetry_dir is not None:
        system_telemetry_dir.mkdir(parents=True, exist_ok=True)
        telemetry = SystemTelemetry(
            system_telemetry_dir / f"system_{workload}_{condition}.jsonl",
            interval_s=system_telemetry_interval_s,
        )
        telemetry.start()
    try:
        if telemetry is not None:
            telemetry.snapshot_cuda("trace_start")
        with Tracer(out_path) as tracer:
            if telemetry is not None:
                telemetry.record_time_anchor("tracer_t0", tracer.time_origin_monotonic)
            run = SemanticWorkflowReplay(
                tracer=tracer,
                tok=tok,
                llm=llm,
                sampling=sampling,
                dry_run=dry_run,
                prefix_caching=prefix_caching,
                workload=workload,
                condition=condition,
                kv_bytes_per_token=kv_bytes,
            )
            run.emit_trace_metadata()
            if workload == "coding_agent":
                with tempfile.TemporaryDirectory(prefix=f"ee392c_{workload}_{condition}_") as tmp:
                    task_copy = Path(tmp) / "hello_bug"
                    shutil.copytree(Path("tasks/hello_bug"), task_copy)
                    replay_coding_workflow(run, task_copy)
            elif workload == "search_agent":
                replay_search_workflow(run, Path("tasks/search_agent"), condition)
            elif workload == "compaction_agent":
                replay_compaction_workflow(run, Path("tasks/compaction_agent"), condition)
            else:
                raise ValueError(f"unknown workload {workload!r}")
        if telemetry is not None:
            telemetry.snapshot_cuda("trace_end")
    finally:
        if telemetry is not None:
            telemetry.stop()
    if not dry_run:
        del llm
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
    print(f"trace written: {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", choices=sorted({w for w, _ in FINAL_TRACES}))
    ap.add_argument("--condition")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("traces/final_v3"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--system-telemetry-dir", type=Path)
    ap.add_argument("--system-telemetry-interval-s", type=float, default=1.0)
    args = ap.parse_args()

    if args.all:
        for workload, condition in FINAL_TRACES:
            out = args.out_dir / f"{workload}_{condition}.jsonl"
            run_one(
                workload=workload,
                condition=condition,
                out_path=out,
                dry_run=args.dry_run,
                system_telemetry_dir=args.system_telemetry_dir,
                system_telemetry_interval_s=args.system_telemetry_interval_s,
            )
        return

    if not args.workload or not args.condition or not args.out:
        ap.error("--workload, --condition, and --out are required unless --all is used")
    run_one(
        workload=args.workload,
        condition=args.condition,
        out_path=args.out,
        dry_run=args.dry_run,
        system_telemetry_dir=args.system_telemetry_dir,
        system_telemetry_interval_s=args.system_telemetry_interval_s,
    )


if __name__ == "__main__":
    main()
