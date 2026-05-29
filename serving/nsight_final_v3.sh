#!/bin/bash
# Profile one representative final-v3 trace with Nsight Systems.
#
# Run on the RunPod environment after dependencies and vLLM packages are
# installed. This is a droppable timeline artifact; semantic traces do not
# depend on it.

set -euo pipefail

OUT_DIR="${1:-traces/final_v3_nsight}"
PROFILE_OUT="${2:-analysis_out/final_v3/nsight_compaction_on}"

mkdir -p "$OUT_DIR"
mkdir -p "$(dirname "$PROFILE_OUT")"

if ! command -v nsys >/dev/null 2>&1; then
    BUNDLED_NSYS="/opt/nvidia/nsight-compute/2024.1.1/host/target-linux-x64/nsys"
    if [[ -x "$BUNDLED_NSYS" ]]; then
        NSYS="$BUNDLED_NSYS"
    else
        echo "nsys not found; skipping Nsight Systems profile" >&2
        exit 2
    fi
else
    NSYS="nsys"
fi

if ! command -v ninja >/dev/null 2>&1; then
    echo "ninja not found; install ninja-build before profiling vLLM/FlashInfer" >&2
    exit 2
fi

"$NSYS" profile \
    --trace=cuda,nvtx,osrt \
    --trace-fork-before-exec=true \
    --sample=none \
    --wait=all \
    --stop-on-exit=true \
    --output "$PROFILE_OUT" \
    --force-overwrite=true \
    python3 -m agent.run_final_v3 \
        --workload compaction_agent \
        --condition compaction_on \
        --out "$OUT_DIR/compaction_agent_compaction_on.jsonl"

echo "Nsight profile written to ${PROFILE_OUT}.nsys-rep"
