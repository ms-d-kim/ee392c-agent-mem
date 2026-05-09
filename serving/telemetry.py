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

import threading
import time
from contextlib import contextmanager
from pathlib import Path

# import nvtx
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

    def start(self) -> None:
        """Init NVML, open file, spawn background thread."""
        raise NotImplementedError(
            "Implement: pynvml.nvmlInit(); open file; self._t0=time.monotonic(); "
            "spawn thread running self._loop()"
        )

    def stop(self) -> None:
        """Signal stop, join thread, flush, close. Idempotent."""
        raise NotImplementedError

    def snapshot_cuda(self, label: str) -> None:
        """Record torch.cuda.memory_allocated/reserved at a phase boundary.

        Call this at start/end of prefill, decode, tool_exec.
        """
        raise NotImplementedError

    def _loop(self) -> None:
        """Poll NVML + psutil at self.interval_s until stop_event."""
        raise NotImplementedError


@contextmanager
def nvtx_phase(name: str):
    """NVTX range context manager; visible in Nsight Systems timelines.

    Usage:
        with nvtx_phase("prefill"):
            ...
    """
    # with nvtx.annotate(name):
    #     yield
    raise NotImplementedError("Wrap nvtx.annotate(name) as a context manager")
