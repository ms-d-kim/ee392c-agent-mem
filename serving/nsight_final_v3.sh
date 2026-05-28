#!/bin/bash
# Profile one representative final-v3 trace with Nsight Systems.
#
# Run on the RunPod environment after dependencies and vLLM packages are
# installed. This is a droppable timeline artifact; semantic traces do not
# depend on it.

set -euo pipefail

OUT_DIR="${1:-traces/final_v3_nsight}"
PROFILE_OUT="${2:-analysis_out/final_v3/nsight_coding_cache_on}"

mkdir -p "$OUT_DIR"
mkdir -p "$(dirname "$PROFILE_OUT")"

if ! command -v nsys >/dev/null 2>&1; then
    echo "nsys not found; skipping Nsight Systems profile" >&2
    exit 2
fi

nsys profile \
    --trace=cuda,nvtx,osrt \
    --sample=cpu \
    --output "$PROFILE_OUT" \
    --force-overwrite=true \
    python3 -m agent.run_final_v3 \
        --workload coding_agent \
        --condition cache_on \
        --out "$OUT_DIR/coding_agent_cache_on.jsonl"

echo "Nsight profile written to ${PROFILE_OUT}.nsys-rep"
