#!/bin/bash
# Launch vLLM V1 serving Qwen2.5-Coder-7B-Instruct with prefix caching ON.
# Run on RunPod pod with /workspace persistent volume.
#
# Usage:
#     bash serving/launch_vllm.sh
# Or in tmux:
#     tmux new -s vllm
#     bash serving/launch_vllm.sh
#     # Ctrl-b d to detach

set -euo pipefail

MODEL="Qwen/Qwen2.5-Coder-7B-Instruct"
MODEL_DIR="/workspace/hf-cache/${MODEL##*/}"
PORT=8000

# Use local cache if present (set during SETUP.md step 4), else download
if [ -d "$MODEL_DIR" ]; then
    MODEL_ARG="$MODEL_DIR"
    echo "Using cached model at $MODEL_DIR"
else
    MODEL_ARG="$MODEL"
    echo "Model not cached locally; vLLM will download from HF"
fi

vllm serve "$MODEL_ARG" \
    --served-model-name "$MODEL" \
    --port "$PORT" \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.85 \
    --max-model-len 16384 \
    --dtype bfloat16 \
    --disable-log-requests \
    --download-dir /workspace/hf-cache
