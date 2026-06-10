# Troubleshooting — pod and environment quirks

Discoveries from bring-up sessions, per the protocol in `SETUP.md` ("append
discoveries here"). Newest entries at the bottom.

## CUDA / driver pinning (RunPod H100, driver 570.x)

The pod driver (570.x) supports CUDA 12.8 but rejects CUDA-13 builds. Keep the
stack pinned to the CUDA-12 line (already encoded in `requirements.txt`):

- `vllm==0.10.2` (pulls `torch 2.8.0+cu128`); newer vllm (>=0.20) requires CUDA 13
- `transformers>=4.55.2,<5` — vllm 0.10.2 references tokenizer APIs removed in 5.x
- Symptom of a mismatch: torch wheels fail at import with a driver/runtime
  version error rather than at install time.

## NVML bindings

`pynvml` import errors at telemetry start → install `nvidia-ml-py`, not the
deprecated `pynvml` package (see `requirements.txt`). `serving/telemetry.py`
degrades gracefully (emits `nvml_available 0.0`) instead of crashing.

## Nsight Systems on the RunPod image

`apt-get install nsight-systems-cli` does not resolve on the
`runpod/pytorch:2.4.0-py3.11-cuda12.4.1` image. A working `nsys` ships bundled
with Nsight Compute instead:

```
/opt/nvidia/nsight-compute/2024.1.1/host/target-linux-x64/nsys
```

Per pre-committed cut #5 in `DECISIONS.md`, drop nsys entirely if neither path
works — the methodology does not depend on it.

## Kernel-level capture truncation in the auxiliary Nsight profile

In the compaction profile, CUPTI kernel-level capture is buffer-truncated
around step 1, while NVTX phase ranges and memcpy counters survive across all
five steps. `analysis/nsight.py` and the figure caption already state this;
treat per-step kernel comparisons from that profile as out of bounds.
