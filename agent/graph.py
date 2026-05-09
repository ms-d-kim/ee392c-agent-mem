"""
LangGraph coding agent: prompt -> model inference -> optional tool exec ->
state update -> repeat. Hard step cap of 15.

This is the orchestration layer. The actual model is served by vLLM at
http://localhost:8000 (OpenAI-compatible endpoint).

The agent emits Tracer events for:
- Prompt construction (phase="task_setup" or "agent_loop")
- Model response (phase="decode")
- Tool invocations (phase="tool_exec", via tools.py)
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from agent.tracer import Tracer

MAX_STEPS = 15
VLLM_BASE_URL = "http://localhost:8000/v1"
MODEL_NAME = "Qwen/Qwen2.5-Coder-7B-Instruct"


class AgentState(TypedDict):
    """LangGraph state passed between nodes."""
    task_id: str
    messages: list  # OpenAI-format chat messages
    workdir: Path
    step: int
    done: bool


def build_agent_graph(tracer: Tracer):
    """Construct the LangGraph state machine.

    Nodes:
    - propose_action: call vLLM with current messages, parse tool call or final
    - execute_tool: invoke read_file / write_file / run_tests
    - update_state: append assistant + tool messages, increment step
    - check_terminate: stop on final answer or step >= MAX_STEPS

    Implementation notes:
    - Use langgraph.graph.StateGraph
    - Use openai.OpenAI(base_url=VLLM_BASE_URL, api_key="EMPTY") as client
    - Capture per-request usage.cached_tokens for engine-layer telemetry
    - Wrap each node body in tracer events
    """
    raise NotImplementedError
