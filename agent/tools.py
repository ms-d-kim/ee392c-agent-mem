"""
Three tools for the LangGraph coding agent: read_file, write_file, run_tests.

Deliberately simple — no caching, no retries, no fancy error handling.
The agent must be interpretable, not optimal for solve rate.

Each tool emits Tracer events for its inputs and outputs so the logical
layer captures tool-output reuse across turns.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent.tracer import Tracer, compute_logical_id


def make_tools(tracer: Tracer, workdir: Path):
    """Return the three tools bound to this tracer + working directory.

    Implementation notes:
    - workdir is the per-task scratch directory (e.g. SWE-bench task repo)
    - On read: emit (op="create", repr_type="text") for the file content
    - On write: emit (op="mutate" if existed else "create")
    - On run_tests: emit (op="create", repr_type="text") for stdout/stderr
    - Tool calls happen during phase="tool_exec"
    """
    raise NotImplementedError(
        "Implement read_file/write_file/run_tests as LangGraph tools "
        "that wrap subprocess/Path operations and emit Tracer events."
    )
