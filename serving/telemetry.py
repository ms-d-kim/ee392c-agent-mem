"""
System-layer telemetry: GPU VRAM, host RSS, CUDA memory snapshots, NVTX phase markers.

Sampling:
- 1 Hz background thread for GPU VRAM (NVML) and host RSS (psutil)
- Explicit calls at phase boundaries for torch.cuda.memory_allocated/reserved
- NVTX context manager for visual phase markers (visible in Nsight Systems)

Output: traces/system_<task_id>.jsonl, one record per sample.
Schema:
    {ts: float, source: str, metric: str, value: float, unit: str}

Examples:
    {"ts": 1.23, "source": "nvml", "metric": "gpu_mem_used", "value": 8.4e9, "unit": "bytes"}
    {"ts": 1.23, "source": "psutil", "metric": "rss", "value": 1.2e9, "unit": "bytes"}
    {"ts": 5.67, "source": "torch", "metric": "cuda_allocated", "value": 7.1e9, "unit": "bytes"}
    {"ts": 5.67, "source": "torch", "metric": "cuda_reserved", "value": 8.0e9, "unit": "bytes"}
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import nvtx
except ImportError:  # pragma: no cover - optional profiling dependency
    nvtx = None
# import psutil
# import pynvml
# import torch


class SystemTelemetry:
    """1 Hz background poller for GPU VRAM and host RSS, plus phase snapshots."""

    def __init__(self, output_path: Path, interval_s: float = 1.0):
        self.output_path = Path(output_path)
        self.interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._fh = None
        self._t0: float | None = None
        self._lock = threading.Lock()
        self._process = None
        self._nvml = None
        self._gpu_handles = []

    def start(self) -> None:
        """Open the telemetry JSONL and start optional psutil/NVML polling."""
        if self._fh is not None:
            raise RuntimeError("SystemTelemetry.start() called while already started")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.output_path.open("w", encoding="utf-8")
        self._t0 = time.monotonic()
        self._stop_event.clear()

        try:
            import psutil

            self._process = psutil.Process()
            self._emit("system", "psutil_available", 1.0, "bool")
        except Exception as exc:  # pragma: no cover - environment dependent
            self._process = None
            self._emit("system", "psutil_available", 0.0, "bool", {"error": repr(exc)})

        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._gpu_handles = [
                pynvml.nvmlDeviceGetHandleByIndex(index)
                for index in range(pynvml.nvmlDeviceGetCount())
            ]
            self._emit("system", "nvml_available", 1.0, "bool", {"gpu_count": len(self._gpu_handles)})
        except Exception as exc:  # pragma: no cover - environment dependent
            self._nvml = None
            self._gpu_handles = []
            self._emit("system", "nvml_available", 0.0, "bool", {"error": repr(exc)})

        self._thread = threading.Thread(target=self._loop, name="ee392c-system-telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal stop, join thread, flush, close. Idempotent."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_s * 2))
            self._thread = None
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:  # pragma: no cover - environment dependent
                pass
            self._nvml = None
            self._gpu_handles = []
        with self._lock:
            if self._fh is None:
                return
            try:
                self._fh.flush()
            finally:
                self._fh.close()
                self._fh = None
                self._t0 = None

    def snapshot_cuda(self, label: str) -> None:
        """Record torch.cuda.memory_allocated/reserved at a phase boundary.

        Call this at start/end of prefill, decode, tool_exec.
        """
        try:
            import torch

            if not torch.cuda.is_available():
                self._emit("torch", "cuda_available", 0.0, "bool", {"label": label})
                return
            device_count = torch.cuda.device_count()
            for index in range(device_count):
                self._emit(
                    "torch",
                    "cuda_allocated",
                    float(torch.cuda.memory_allocated(index)),
                    "bytes",
                    {"label": label, "gpu_index": index},
                )
                self._emit(
                    "torch",
                    "cuda_reserved",
                    float(torch.cuda.memory_reserved(index)),
                    "bytes",
                    {"label": label, "gpu_index": index},
                )
        except Exception as exc:  # pragma: no cover - environment dependent
            self._emit("torch", "cuda_snapshot_error", 1.0, "count", {"label": label, "error": repr(exc)})

    def record_time_anchor(self, label: str, monotonic_time: float) -> None:
        """Record an offset between this telemetry clock and another clock."""
        if self._t0 is None:
            return
        self._emit(
            "system",
            "monotonic_anchor_delta",
            float(monotonic_time - self._t0),
            "seconds",
            {"label": label},
        )

    def _loop(self) -> None:
        """Poll NVML + psutil at self.interval_s until stop_event."""
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self.interval_s)

    def _poll_once(self) -> None:
        if self._process is not None:
            try:
                mem = self._process.memory_info()
                self._emit("psutil", "rss", float(mem.rss), "bytes")
                self._emit("psutil", "vms", float(mem.vms), "bytes")
            except Exception as exc:  # pragma: no cover - environment dependent
                self._emit("psutil", "rss_error", 1.0, "count", {"error": repr(exc)})

        if self._nvml is not None:
            for index, handle in enumerate(self._gpu_handles):
                try:
                    mem = self._nvml.nvmlDeviceGetMemoryInfo(handle)
                    self._emit("nvml", "gpu_mem_used", float(mem.used), "bytes", {"gpu_index": index})
                    self._emit("nvml", "gpu_mem_total", float(mem.total), "bytes", {"gpu_index": index})
                except Exception as exc:  # pragma: no cover - environment dependent
                    self._emit("nvml", "gpu_mem_error", 1.0, "count", {"gpu_index": index, "error": repr(exc)})

    def _emit(self, source: str, metric: str, value: float, unit: str, extra: dict[str, Any] | None = None) -> None:
        if self._fh is None or self._t0 is None:
            return
        record = {
            "ts": time.monotonic() - self._t0,
            "source": source,
            "metric": metric,
            "value": value,
            "unit": unit,
        }
        if extra:
            record.update(extra)
        with self._lock:
            if self._fh is None:
                return
            self._fh.write(json.dumps(record) + "\n")
            self._fh.flush()


@contextmanager
def nvtx_phase(name: str):
    """NVTX range context manager; visible in Nsight Systems timelines.

    Usage:
        with nvtx_phase("prefill"):
            ...
    """
    if nvtx is None:
        yield
        return
    with nvtx.annotate(name):
        yield
