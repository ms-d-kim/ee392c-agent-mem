# Setup runbook — RunPod bring-up

Estimated time: 2–3 hours for first run. Subsequent: ~15 min to start a session.

This is the exact recipe to follow when actually bringing the stack up. Do not
deviate without updating this file. Discoveries → append to `TROUBLESHOOTING.md`.

---

## 1. Launch RunPod pod

- Template: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
  (verify the latest equivalent in RunPod's template catalog)
- GPU: NVIDIA H100 80GB HBM3 on-demand
- Persistent volume: 50GB attached at `/workspace`
- SSH key registered with RunPod, SSH enabled

Note the pod IP and SSH port from the RunPod dashboard.

---

## 2. SSH in, clone repo

```bash
ssh root@<pod-ip> -p <port>
cd /workspace
git clone <repo-url> ee392c-agent-mem
cd ee392c-agent-mem
```

---

## 3. Install Python dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
```

**Expected:** ~5–10 min. vLLM pulls a lot of CUDA libs.
**Common failure:** `pynvml` import errors → ensure `nvidia-ml-py` is installed
(not the deprecated `pynvml` package).

---

## 4. Pre-download model to persistent volume

```bash
huggingface-cli login   # if model gated; Qwen2.5-Coder is open
huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct \
    --local-dir /workspace/hf-cache/Qwen2.5-Coder-7B-Instruct
```

**Expected:** ~14 GB, 5–10 min on RunPod.

Putting it on the persistent volume means re-launching the pod doesn't re-download.

---

## 5. Launch vLLM (foreground, in tmux)

```bash
tmux new -s vllm
bash serving/launch_vllm.sh
```

**Expected:** server ready in ~60 s, listening on `:8000`. Look for
`Uvicorn running on http://0.0.0.0:8000`.

Detach the tmux session: `Ctrl-b d`. Reattach later: `tmux attach -t vllm`.

---

## 6. Smoke test the chat endpoint

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Print hello in Python."}]
  }' | jq .
```

**Expected:** JSON response with a code completion in `choices[0].message.content`.

---

## 7. Smoke test the metrics endpoint

```bash
curl -s http://localhost:8000/metrics | grep -E "vllm:(gpu_cache|prefix_cache|num_)"
```

**Expected:** Prometheus-format metrics including `vllm:gpu_cache_usage_perc`,
`vllm:prefix_cache_queries`, `vllm:prefix_cache_hits`, `vllm:num_requests_*`.

These are what the engine-layer telemetry scrapes.

---

## 8. (Stretch, ~30 min) Install Nsight Systems

```bash
# Method 1: apt (preferred, package name varies by image)
apt-get update
apt-get install -y nsight-systems-cli || true
apt-get install -y ninja-build
nsys --version

# Method 2: if apt package lookup fails, check bundled NVIDIA tooling first
find /opt/nvidia /usr/local /usr -path '*nsys' -type f 2>/dev/null | head

# Method 3: if neither path works, download the .deb directly from
# https://developer.nvidia.com/nsight-systems and dpkg -i
```

On the H100 RunPod used for the final-v3 sweep, `nsight-systems-cli` was not
available by that apt name, but this bundled binary worked:
`/opt/nvidia/nsight-compute/2024.1.1/host/target-linux-x64/nsys`.

**Drop trigger:** if install fails or requires permissions you don't have on
the RunPod container, drop nsys (per pre-committed cut #5 in DECISIONS.md).
The methodology does not depend on it.

**Smoke test:**
```bash
nsys profile -o /tmp/smoke --force-overwrite=true python -c "import time; time.sleep(2); print('ok')"
nsys stats /tmp/smoke.nsys-rep | head -20
```
**Expected:** stats output with no errors. If it works here, it'll work on the
real agent.

---

## 9. Validate environment

```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0))"
python -c "import pynvml; pynvml.nvmlInit(); print('NVML OK')"
python -c "import psutil; print('RSS MB:', psutil.Process().memory_info().rss / 1e6)"
nvidia-smi
```

All four should run cleanly.

---

## 10. Commit pod-specific notes

If you discovered any quirks (apt package names, vLLM flag tweaks, permission
issues), append them to `TROUBLESHOOTING.md` in the repo root and commit.

---

## Next session — final-v3 run order

Once the bring-up runbook above succeeds end-to-end, use the final-v3 path:

1. Run `python3 -m validation.synthetic --output /tmp/synthetic_v3.jsonl`.
2. Run `python3 -m validation.assert_synthetic /tmp/synthetic_v3.jsonl`.
3. Run `python3 -m validation.assert_validate_final_v3`.
4. Run one real final-v3 trace with `agent.run_final_v3` and verify
   `validation.validate_final_v3` does not report cached-token API unavailable.
5. Run all six final-v3 traces under `traces/final_v3/`.
6. Run `analysis.final_v3` to produce final CSVs and figures.

**Current H100 status (2026-05-29):** steps 1-6 have passed for the six
final-v3 traces on RunPod H100. Keep these traces as the official final-v3
dataset unless `DECISIONS.md` is explicitly revised again.

The synthetic gate remains mandatory. If it fails, every plot from real traces
is suspect.

## Optional Nsight Systems profile

Nsight is one auxiliary profile of an existing final-v3 trace, not a seventh
core workload. Prefer the compaction replay because its prompt length changes
materially across conditions.

```bash
mkdir -p analysis_out/final_v3 traces/final_v3_nsight
nsys profile \
  --trace=cuda,nvtx,osrt \
  --trace-fork-before-exec=true \
  --sample=none \
  --wait=all \
  --stop-on-exit=true \
  --output analysis_out/final_v3/nsight_compaction_on \
  --force-overwrite=true \
  python3 -m agent.run_final_v3 \
    --workload compaction_agent \
    --condition compaction_on \
    --out traces/final_v3_nsight/compaction_agent_compaction_on.jsonl
```

Expected primary output:

```text
analysis_out/final_v3/nsight_compaction_on.nsys-rep
```
